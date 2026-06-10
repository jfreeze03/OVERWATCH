# sections/change_drift.py - Consolidated change, drift, and lineage workflow
from __future__ import annotations

from datetime import datetime
from importlib import import_module
import re

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE, DEFAULT_COMPANY, DEFAULT_ENVIRONMENT
from sections.shell_helpers import render_shell_snapshot
import utils as _utils
from utils.section_guidance import defer_section_note, defer_source_note


class _LazyPandas:
    """Load pandas only after Change & Drift needs dataframe work."""

    _module = None

    def _load(self):
        if self._module is None:
            import pandas as pandas_module

            self._module = pandas_module
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


pd = _LazyPandas()


def _lazy_util(name: str):
    def _call(*args, **kwargs):
        return getattr(_utils, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


filter_existing_columns = _lazy_util("filter_existing_columns")
format_snowflake_error = _lazy_util("format_snowflake_error")
environment_label_for_database = _lazy_util("environment_label_for_database")
get_environment_case_expr = _lazy_util("get_environment_case_expr")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
get_session = _lazy_util("get_session")
mart_object_name = _lazy_util("mart_object_name")
make_action_id = _lazy_util("make_action_id")
resolve_owner_context = _lazy_util("resolve_owner_context")
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")
action_queue_environment_clause = _lazy_util("action_queue_environment_clause")
upsert_actions = _lazy_util("upsert_actions")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
render_mode_selector = _lazy_util("render_mode_selector")
render_workflow_selector = _lazy_util("render_workflow_selector")
day_window_selectbox = _lazy_util("day_window_selectbox")


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    try:
        if value is None or value != value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def _freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "account_usage" in source_key or "query_history" in source_key:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "mart" in source_key or "overwatch" in source_key:
        return "Freshness: fast summary refresh cadence"
    return "Freshness: depends on source view availability"


def _metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Source basis: Exact",
        "allocated": "Source basis: Allocated / estimated from exact source records",
        "estimated": "Source basis: Estimated",
    }
    return labels.get(str(kind or "").lower(), "Source basis: Calculation depends on available account metadata")


def render_signal_confidence(*, source: str = "ACCOUNT_USAGE", confidence: str = "allocated", scope_note: str = "") -> None:
    parts = [_freshness_note(source), _metric_confidence_label(confidence)]
    if scope_note:
        parts.append(scope_note)
    defer_source_note(*parts)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def render_workflow_module(workflow: str, workflow_modules: dict[str, str]) -> None:
    module_name = workflow_modules.get(str(workflow))
    if not module_name:
        st.warning(f"No module registered for workflow: {workflow}")
        return
    module = import_module(module_name)
    render = getattr(module, "render", None)
    if not callable(render):
        st.warning(f"Workflow module has no render() function: {module_name}")
        return
    render()

CHANGE_DRIFT_VIEWS = ("Change Brief", "Change Workflows")
CHANGE_DRIFT_BRIEF_FIRST_VERSION = 2

WORKFLOWS = (
    "Object and access changes",
    "Schema and object drift",
    "Terraform evidence",
    "Jira evidence",
    "Controlled DBA actions",
    "Data movement and replication",
    "Stored procedure lineage",
)

WORKFLOW_DETAILS = {
    "Object and access changes": "Who changed what, access movement, destructive DDL, and policy changes.",
    "Schema and object drift": "Schema compare, object inventory, unused objects, and Terraform drift signals.",
    "Terraform evidence": "Source-control, Terraform, and Flyway deploy evidence linked to Snowflake drift and Jira approval.",
    "Jira evidence": "Jira/ITSM approvals, status, owner, and change-window evidence linked to deployments and Snowflake activity.",
    "Controlled DBA actions": "Guarded admin actions, generated SQL, and operational controls.",
    "Data movement and replication": "Replication, dynamic tables, Snowpipe, data loading, and freshness risk.",
    "Stored procedure lineage": "Procedure ownership, child SQL, downstream objects, and runtime/cost drift.",
}

CHANGE_BRIEF_WORKFLOWS = (
    {
        "WORKFLOW": "Object and access changes",
        "BUTTON_LABEL": "Open Object Changes",
        "DBA_MOVE": "Start with recent DDL, grants, ownership, policy, and actor evidence.",
        "WHEN": "Unknown actor, manual DDL, access movement",
    },
    {
        "WORKFLOW": "Terraform evidence",
        "BUTTON_LABEL": "Open Terraform",
        "DBA_MOVE": "Match deploy evidence from Terraform, Flyway, or Git to Snowflake changes.",
        "WHEN": "IaC deploys, source-control proof, drift review",
    },
    {
        "WORKFLOW": "Jira evidence",
        "BUTTON_LABEL": "Open Jira",
        "DBA_MOVE": "Match approved Jira/ITSM tickets to deployment and object-change evidence.",
        "WHEN": "Approval proof, ticket status, change windows",
    },
    {
        "WORKFLOW": "Schema and object drift",
        "BUTTON_LABEL": "Open Schema Drift",
        "DBA_MOVE": "Compare databases and schemas, then review orphaned or unmanaged objects.",
        "WHEN": "Schema compare, object inventory, unused assets",
    },
    {
        "WORKFLOW": "Data movement and replication",
        "BUTTON_LABEL": "Open Data Movement",
        "DBA_MOVE": "Review Snowpipe, dynamic tables, replication, and load freshness signals.",
        "WHEN": "Pipeline freshness, replication, load issues",
    },
    {
        "WORKFLOW": "Controlled DBA actions",
        "BUTTON_LABEL": "Open DBA Actions",
        "DBA_MOVE": "Use guarded admin workflows with audit proof and verification requirements.",
        "WHEN": "Approved changes, recovery, controlled fixes",
    },
)

WORKFLOW_MODULES = {
    "Object and access changes": "sections.object_change_monitor",
    "Stored procedure lineage": "sections.stored_proc_tracker",
    "Schema and object drift": "sections.dba_tools",
    "Data movement and replication": "sections.dba_tools",
    "Controlled DBA actions": "sections.dba_tools",
}

CHANGE_CONTROL_EVIDENCE_TABLE = "OVERWATCH_CHANGE_CONTROL_EVIDENCE"
CHANGE_CONTROL_OPERABILITY_FACT_TABLE = "FACT_CHANGE_CONTROL_OPERABILITY_DAILY"
CHANGE_SOURCE_CONTROL_TABLE = "OVERWATCH_SOURCE_CONTROL_CHANGE"
CHANGE_ITSM_TICKET_TABLE = "OVERWATCH_ITSM_TICKET"
CHANGE_FEED_CSV_FILE_FORMAT = "OVERWATCH_CHANGE_EVIDENCE_CSV_FORMAT"
CHANGE_SOURCE_CONTROL_STAGE = "OVERWATCH_SOURCE_CONTROL_CHANGE_STAGE"
CHANGE_ITSM_TICKET_STAGE = "OVERWATCH_ITSM_TICKET_STAGE"
CHANGE_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)
CHANGE_TICKET_PATTERN = re.compile(
    r"\b(?:CHG|CHANGE|INC|REQ|RFC|JIRA)[-_]?\d+\b|\b[A-Z][A-Z0-9]+-\d+\b",
    re.IGNORECASE,
)


def change_control_evidence_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def change_source_control_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_SOURCE_CONTROL_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def change_itsm_ticket_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_ITSM_TICKET_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def change_feed_csv_file_format_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    file_format: str = CHANGE_FEED_CSV_FILE_FORMAT,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(file_format)}"


def change_source_control_stage_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    stage: str = CHANGE_SOURCE_CONTROL_STAGE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(stage)}"


def change_itsm_ticket_stage_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    stage: str = CHANGE_ITSM_TICKET_STAGE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(stage)}"


def _change_integration_object_inventory_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    names = ", ".join(
        sql_literal(name, 200)
        for name in (
            CHANGE_SOURCE_CONTROL_TABLE,
            CHANGE_ITSM_TICKET_TABLE,
            CHANGE_CONTROL_EVIDENCE_TABLE,
        )
    )
    return f"""
SELECT UPPER(TABLE_NAME) AS TABLE_NAME
FROM {safe_identifier(db)}.INFORMATION_SCHEMA.TABLES
WHERE UPPER(TABLE_SCHEMA) = UPPER({sql_literal(schema, 200)})
  AND UPPER(TABLE_NAME) IN ({names})
""".strip()


def _available_change_integration_tables(inventory: pd.DataFrame) -> set[str]:
    if not isinstance(inventory, pd.DataFrame) or inventory.empty or "TABLE_NAME" not in inventory.columns:
        return set()
    return {str(name or "").upper() for name in inventory["TABLE_NAME"].tolist()}


def _split_change_evidence_tables_ready(available_tables: set[str]) -> bool:
    required = {CHANGE_SOURCE_CONTROL_TABLE, CHANGE_ITSM_TICKET_TABLE}
    return required.issubset({str(name or "").upper() for name in available_tables})


def build_change_source_control_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_SOURCE_CONTROL_TABLE,
) -> str:
    fqn = change_source_control_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_TS          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY              VARCHAR(100),
    ENVIRONMENT          VARCHAR(100),
    SOURCE_SYSTEM        VARCHAR(80),
    REPOSITORY           VARCHAR(500),
    BRANCH_NAME          VARCHAR(500),
    COMMIT_SHA           VARCHAR(120),
    PR_ID                VARCHAR(120),
    PR_URL               VARCHAR(1000),
    CHANGE_TICKET_ID     VARCHAR(200),
    OBJECT_DATABASE      VARCHAR(300),
    OBJECT_SCHEMA        VARCHAR(300),
    OBJECT_NAME          VARCHAR(500),
    OBJECT_TYPE          VARCHAR(120),
    OBJECT_FQN           VARCHAR(1000),
    TERRAFORM_ADDRESS    VARCHAR(1000),
    PLANNED_ACTION       VARCHAR(80),
    APPLY_STATUS         VARCHAR(120),
    DEPLOYED_BY          VARCHAR(300),
    APPLY_TS             TIMESTAMP_NTZ,
    EVIDENCE_URL         VARCHAR(1000),
    NOTES                VARCHAR(4000)
);"""


def build_change_itsm_ticket_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_ITSM_TICKET_TABLE,
) -> str:
    fqn = change_itsm_ticket_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_TS           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY               VARCHAR(100),
    ENVIRONMENT           VARCHAR(100),
    TICKET_ID             VARCHAR(200),
    TICKET_URL            VARCHAR(1000),
    SUMMARY               VARCHAR(2000),
    STATUS                VARCHAR(120),
    ASSIGNEE              VARCHAR(300),
    REQUESTER             VARCHAR(300),
    APPROVER              VARCHAR(300),
    APPROVAL_STATUS       VARCHAR(120),
    RISK                  VARCHAR(120),
    CHANGE_WINDOW_START   TIMESTAMP_NTZ,
    CHANGE_WINDOW_END     TIMESTAMP_NTZ,
    LINKED_REPOSITORY     VARCHAR(500),
    LINKED_COMMIT_SHA     VARCHAR(120),
    LINKED_PR_URL         VARCHAR(1000),
    UPDATED_AT            TIMESTAMP_NTZ,
    NOTES                 VARCHAR(4000)
);"""


def build_change_source_control_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_SOURCE_CONTROL_TABLE,
) -> list[str]:
    fqn = change_source_control_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SOURCE_SYSTEM VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OBJECT_FQN VARCHAR(1000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS TERRAFORM_ADDRESS VARCHAR(1000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EVIDENCE_URL VARCHAR(1000)",
    ]


def build_change_itsm_ticket_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_ITSM_TICKET_TABLE,
) -> list[str]:
    fqn = change_itsm_ticket_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS APPROVAL_STATUS VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LINKED_COMMIT_SHA VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LINKED_PR_URL VARCHAR(1000)",
    ]


def build_change_evidence_feed_stage_sql(db: str = ALERT_DB, schema: str = ALERT_SCHEMA) -> str:
    file_format = change_feed_csv_file_format_fqn(db=db, schema=schema)
    source_stage = change_source_control_stage_fqn(db=db, schema=schema)
    ticket_stage = change_itsm_ticket_stage_fqn(db=db, schema=schema)
    return f"""
CREATE FILE FORMAT IF NOT EXISTS {file_format}
  TYPE = CSV
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 1
  NULL_IF = ('', 'NULL', 'null')
  EMPTY_FIELD_AS_NULL = TRUE
  TIMESTAMP_FORMAT = 'AUTO';

CREATE STAGE IF NOT EXISTS {source_stage}
  FILE_FORMAT = {file_format};

CREATE STAGE IF NOT EXISTS {ticket_stage}
  FILE_FORMAT = {file_format};
""".strip()


def build_change_source_control_feed_load_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_SOURCE_CONTROL_TABLE,
    stage: str = CHANGE_SOURCE_CONTROL_STAGE,
) -> str:
    fqn = change_source_control_fqn(db=db, schema=schema, table=table)
    stage_fqn = change_source_control_stage_fqn(db=db, schema=schema, stage=stage)
    return f"""
-- CSV column order:
-- SNAPSHOT_TS, COMPANY, ENVIRONMENT, SOURCE_SYSTEM, REPOSITORY, BRANCH_NAME,
-- COMMIT_SHA, PR_ID, PR_URL, CHANGE_TICKET_ID, OBJECT_DATABASE, OBJECT_SCHEMA,
-- OBJECT_NAME, OBJECT_TYPE, OBJECT_FQN, TERRAFORM_ADDRESS, PLANNED_ACTION,
-- APPLY_STATUS, DEPLOYED_BY, APPLY_TS, EVIDENCE_URL, NOTES
COPY INTO {fqn} (
    SNAPSHOT_TS,
    COMPANY,
    ENVIRONMENT,
    SOURCE_SYSTEM,
    REPOSITORY,
    BRANCH_NAME,
    COMMIT_SHA,
    PR_ID,
    PR_URL,
    CHANGE_TICKET_ID,
    OBJECT_DATABASE,
    OBJECT_SCHEMA,
    OBJECT_NAME,
    OBJECT_TYPE,
    OBJECT_FQN,
    TERRAFORM_ADDRESS,
    PLANNED_ACTION,
    APPLY_STATUS,
    DEPLOYED_BY,
    APPLY_TS,
    EVIDENCE_URL,
    NOTES
)
FROM (
    SELECT
        COALESCE(TRY_TO_TIMESTAMP_NTZ($1), CURRENT_TIMESTAMP()) AS SNAPSHOT_TS,
        $2::VARCHAR AS COMPANY,
        $3::VARCHAR AS ENVIRONMENT,
        COALESCE($4::VARCHAR, 'Terraform/Flyway/Git') AS SOURCE_SYSTEM,
        $5::VARCHAR AS REPOSITORY,
        $6::VARCHAR AS BRANCH_NAME,
        $7::VARCHAR AS COMMIT_SHA,
        $8::VARCHAR AS PR_ID,
        $9::VARCHAR AS PR_URL,
        $10::VARCHAR AS CHANGE_TICKET_ID,
        $11::VARCHAR AS OBJECT_DATABASE,
        $12::VARCHAR AS OBJECT_SCHEMA,
        $13::VARCHAR AS OBJECT_NAME,
        $14::VARCHAR AS OBJECT_TYPE,
        $15::VARCHAR AS OBJECT_FQN,
        $16::VARCHAR AS TERRAFORM_ADDRESS,
        $17::VARCHAR AS PLANNED_ACTION,
        $18::VARCHAR AS APPLY_STATUS,
        $19::VARCHAR AS DEPLOYED_BY,
        TRY_TO_TIMESTAMP_NTZ($20) AS APPLY_TS,
        $21::VARCHAR AS EVIDENCE_URL,
        $22::VARCHAR AS NOTES
    FROM @{stage_fqn}
)
FILE_FORMAT = (
  TYPE = CSV
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 1
  NULL_IF = ('', 'NULL', 'null')
  EMPTY_FIELD_AS_NULL = TRUE
  TIMESTAMP_FORMAT = 'AUTO'
)
ON_ERROR = 'ABORT_STATEMENT';
""".strip()


def build_change_itsm_ticket_feed_load_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_ITSM_TICKET_TABLE,
    stage: str = CHANGE_ITSM_TICKET_STAGE,
) -> str:
    fqn = change_itsm_ticket_fqn(db=db, schema=schema, table=table)
    stage_fqn = change_itsm_ticket_stage_fqn(db=db, schema=schema, stage=stage)
    return f"""
-- CSV column order:
-- SNAPSHOT_TS, COMPANY, ENVIRONMENT, TICKET_ID, TICKET_URL, SUMMARY, STATUS,
-- ASSIGNEE, REQUESTER, APPROVER, APPROVAL_STATUS, RISK, CHANGE_WINDOW_START,
-- CHANGE_WINDOW_END, LINKED_REPOSITORY, LINKED_COMMIT_SHA, LINKED_PR_URL,
-- UPDATED_AT, NOTES
COPY INTO {fqn} (
    SNAPSHOT_TS,
    COMPANY,
    ENVIRONMENT,
    TICKET_ID,
    TICKET_URL,
    SUMMARY,
    STATUS,
    ASSIGNEE,
    REQUESTER,
    APPROVER,
    APPROVAL_STATUS,
    RISK,
    CHANGE_WINDOW_START,
    CHANGE_WINDOW_END,
    LINKED_REPOSITORY,
    LINKED_COMMIT_SHA,
    LINKED_PR_URL,
    UPDATED_AT,
    NOTES
)
FROM (
    SELECT
        COALESCE(TRY_TO_TIMESTAMP_NTZ($1), CURRENT_TIMESTAMP()) AS SNAPSHOT_TS,
        $2::VARCHAR AS COMPANY,
        $3::VARCHAR AS ENVIRONMENT,
        $4::VARCHAR AS TICKET_ID,
        $5::VARCHAR AS TICKET_URL,
        $6::VARCHAR AS SUMMARY,
        $7::VARCHAR AS STATUS,
        $8::VARCHAR AS ASSIGNEE,
        $9::VARCHAR AS REQUESTER,
        $10::VARCHAR AS APPROVER,
        $11::VARCHAR AS APPROVAL_STATUS,
        $12::VARCHAR AS RISK,
        TRY_TO_TIMESTAMP_NTZ($13) AS CHANGE_WINDOW_START,
        TRY_TO_TIMESTAMP_NTZ($14) AS CHANGE_WINDOW_END,
        $15::VARCHAR AS LINKED_REPOSITORY,
        $16::VARCHAR AS LINKED_COMMIT_SHA,
        $17::VARCHAR AS LINKED_PR_URL,
        TRY_TO_TIMESTAMP_NTZ($18) AS UPDATED_AT,
        $19::VARCHAR AS NOTES
    FROM @{stage_fqn}
)
FILE_FORMAT = (
  TYPE = CSV
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 1
  NULL_IF = ('', 'NULL', 'null')
  EMPTY_FIELD_AS_NULL = TRUE
  TIMESTAMP_FORMAT = 'AUTO'
)
ON_ERROR = 'ABORT_STATEMENT';
""".strip()


def build_change_control_evidence_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> str:
    fqn = change_control_evidence_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID              VARCHAR(64),
    SNAPSHOT_TS              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY                  VARCHAR(100),
    ENVIRONMENT              VARCHAR(100),
    FINDING_TYPE             VARCHAR(120),
    SEVERITY                 VARCHAR(40),
    ENTITY                   VARCHAR(500),
    USER_NAME                VARCHAR(300),
    ROLE_NAME                VARCHAR(300),
    QUERY_ID                 VARCHAR(200),
    QUERY_TAG                VARCHAR(1000),
    LAST_SEEN                VARCHAR(100),
    CHANGE_CONTROL_STATE     VARCHAR(120),
    CONTROL_GAP              VARCHAR(1000),
    CHANGE_TICKET_ID         VARCHAR(200),
    CHANGE_TICKET_STATE      VARCHAR(120),
    IAC_RECONCILIATION_STATE VARCHAR(160),
    EXECUTION_AUDIT_STATE    VARCHAR(160),
    OWNER                    VARCHAR(200),
    ESCALATION_TARGET        VARCHAR(200),
    OWNER_SOURCE             VARCHAR(200),
    APPROVER                 VARCHAR(200),
    OWNER_APPROVAL_STATUS    VARCHAR(40),
    APPROVAL_REQUIRED        VARCHAR(20),
    TICKET_REQUIRED          VARCHAR(20),
    BLAST_RADIUS_REQUIRED    VARCHAR(20),
    APPROVAL_ROUTE_READY     VARCHAR(20),
    CHANGE_EVIDENCE_READINESS VARCHAR(80),
    EVIDENCE_BLOCKERS        VARCHAR(2000),
    REVIEW_SLA_HOURS         NUMBER,
    NEXT_CONTROL_ACTION      VARCHAR(4000),
    PROOF_REQUIRED           VARCHAR(2000),
    VERIFICATION_QUERY       VARCHAR(8000),
    BLAST_RADIUS_QUERY       VARCHAR(8000),
    SOURCE                   VARCHAR(500)
);"""


def build_change_control_evidence_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> list[str]:
    """Return additive migrations for previously deployed evidence tables."""
    fqn = change_control_evidence_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS APPROVAL_ROUTE_READY VARCHAR(20)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CHANGE_EVIDENCE_READINESS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EVIDENCE_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_SLA_HOURS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]


def change_control_operability_fact_fqn(table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)


def build_change_control_operability_fact_ddl(table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE) -> str:
    fqn = change_control_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE              DATE,
    COMPANY                    VARCHAR(100),
    ENVIRONMENT                VARCHAR(100),
    CONTROL_SOURCE             VARCHAR(80),
    CONTROL_KEY                VARCHAR(500),
    FINDING_TYPE               VARCHAR(120),
    ENTITY                     VARCHAR(500),
    OWNER                      VARCHAR(200),
    ESCALATION_TARGET          VARCHAR(200),
    SEVERITY                   VARCHAR(40),
    EVIDENCE_ROWS              NUMBER,
    HIGH_RISK_CHANGES          NUMBER,
    ROUTE_BLOCKED              NUMBER,
    CLOSURE_BLOCKED            NUMBER,
    REVIEW_READY               NUMBER,
    MISSING_TICKET_ROWS        NUMBER,
    IAC_GAP_ROWS               NUMBER,
    MISSING_QUERY_ID_ROWS      NUMBER,
    OPEN_ACTIONS               NUMBER,
    OVERDUE_OPEN               NUMBER,
    FIXED_WITHOUT_VERIFICATION NUMBER,
    VERIFIED_CLOSURES          NUMBER,
    OWNER_APPROVAL_GAP_ROWS    NUMBER,
    CONTROL_STATE              VARCHAR(120),
    CONTROL_RANK               NUMBER,
    NEXT_CONTROL_ACTION        VARCHAR(4000),
    LAST_ACTIVITY_TS           TIMESTAMP_NTZ,
    LOAD_TS                    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""


def build_change_control_operability_fact_migration_sql(
    table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = change_control_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_KEY VARCHAR(500)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS HIGH_RISK_CHANGES NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ROUTE_BLOCKED NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CLOSURE_BLOCKED NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_READY NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]


def _change_ticket_id(row: pd.Series | dict) -> str:
    haystack = " ".join([
        str(row.get("QUERY_TAG") or ""),
        str(row.get("QUERY_TEXT") or ""),
        str(row.get("PROOF_QUERY") or ""),
    ])
    match = CHANGE_TICKET_PATTERN.search(haystack)
    return match.group(0).upper() if match else ""


def _split_snowflake_qualified_name(value: object) -> list[str]:
    """Split a Snowflake qualified name while preserving dots inside quotes."""
    text = str(value or "").strip()
    if not text:
        return []
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    idx = 0
    while idx < len(text):
        char = text[idx]
        if char == '"':
            if in_quotes and idx + 1 < len(text) and text[idx + 1] == '"':
                current.append('"')
                idx += 2
                continue
            in_quotes = not in_quotes
            idx += 1
            continue
        if char == "." and not in_quotes:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
        idx += 1
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _change_database_name(row: pd.Series | dict) -> str:
    for key in ("DATABASE_NAME", "OBJECT_DATABASE", "TABLE_CATALOG"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.strip('"')
    entity = str(row.get("ENTITY") or "").strip()
    if "." in entity:
        pieces = _split_snowflake_qualified_name(entity)
        return pieces[0] if pieces else ""
    if entity.upper().startswith(("ALFA_", "TRXS_")):
        return entity.strip('"')
    return ""


def _change_database_context(row: pd.Series | dict) -> bool:
    return bool(_change_database_name(row))


def _change_environment(row: pd.Series | dict, fallback: str = "ALL") -> str:
    database_name = _change_database_name(row)
    if database_name:
        return environment_label_for_database(database_name)
    return "No Database Context" if not str(row.get("DATABASE_NAME") or "").strip() else str(fallback or "ALL")


def _change_scope_clause(
    date_col: str,
    wh_col: str,
    user_col: str,
    role_col: str,
    db_col: str,
    schema_col: str = "schema_name",
) -> str:
    """Apply company and triage filters while keeping account-level changes under environment scopes."""
    return get_global_filter_clause(
        date_col=date_col,
        wh_col=wh_col,
        user_col=user_col,
        role_col=role_col,
        db_col=db_col,
        schema_col=schema_col,
        preserve_no_database_context=True,
    )


def _bare_sql_predicate(fragment: str) -> str:
    """Return a WHERE-list predicate without a leading conjunction."""
    text = str(fragment or "").strip()
    while text.upper().startswith(("AND ", "OR ")):
        text = text.split(None, 1)[1].strip()
    return text


def _change_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _change_scope_meta(
    company: str,
    environment: str,
    days: int | None = None,
    state: dict | None = None,
) -> dict:
    """Return the filter scope that loaded Change & Drift evidence must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _change_scope_value(company),
        "environment": _change_scope_value(environment),
    }
    if days is not None:
        meta["days"] = int(days)
    for key in CHANGE_SCOPE_FILTER_KEYS:
        meta[key] = _change_scope_value(state.get(key))
    return meta


def _change_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key == "days":
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif _change_scope_value(actual) != _change_scope_value(expected_value):
            return False
    return True


def _change_looks_like_frame(value) -> bool:
    """Return True for dataframe-like values without forcing pandas import."""
    return hasattr(value, "empty") and hasattr(value, "iloc") and hasattr(value, "columns")


def _change_row_count(frame) -> int:
    return len(frame) if isinstance(frame, pd.DataFrame) else 0


def _change_source_confidence(source: str, default: str) -> str:
    source_lower = str(source or "").lower()
    if ("fast" in source_lower and "summary" in source_lower) or "mart" in source_lower or "fact_" in source_lower:
        return "Fast summary"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower:
        return "Live ACCOUNT_USAGE"
    if "action queue" in source_lower or "workflow" in source_lower or "evidence" in source_lower:
        return "Workflow evidence"
    return default


def _change_source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or triage filters."
    if state == "Unavailable":
        return "Deploy or refresh the summary/evidence tables before relying on this surface."
    if state == "Not Loaded":
        return "Load only when this workflow is part of the current change investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent change events, evidence, or action rows."
    if "fallback" in source_lower:
        return "Use for investigation; prefer summary refresh for repeated daily change control."
    return "Current for the active DBA change scope."


def _change_has_source_state(state: dict) -> bool:
    """Return True once Change & Drift has evidence or source errors to summarize."""
    for key in (
        "change_drift_summary",
        "change_drift_exceptions",
        "change_drift_error",
        "change_control_operability_fact",
        "change_control_operability_fact_error",
        "change_drift_evidence_trend",
        "change_drift_evidence_trend_error",
        "change_action_closure",
        "change_action_closure_error",
        "change_integration_terraform_status",
        "change_integration_terraform_error",
        "change_integration_jira_status",
        "change_integration_jira_error",
    ):
        value = state.get(key)
        if isinstance(value, str):
            if value.strip():
                return True
            continue
        if value is not None:
            return True
    return False


def _change_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Change & Drift evidence freshness and source strategy."""
    definitions = [
        {
            "surface": "Change brief",
            "frame_key": "change_drift_summary",
            "source_key": "change_drift_source",
            "meta_key": "change_drift_meta",
            "days_key": "change_drift_brief_days",
            "default_days": 14,
            "source": "Fast change summary or live query history",
            "confidence": "Mixed",
            "error_key": "change_drift_error",
        },
        {
            "surface": "Change exceptions",
            "frame_key": "change_drift_exceptions",
            "source_key": "change_drift_source",
            "meta_key": "change_drift_meta",
            "days_key": "change_drift_brief_days",
            "default_days": 14,
            "source": "Fast change summary or live query history",
            "confidence": "Mixed",
            "error_key": "change_drift_error",
        },
        {
            "surface": "Control summary",
            "frame_key": "change_control_operability_fact",
            "meta_key": "change_control_operability_fact_meta",
            "days_key": "change_drift_brief_days",
            "default_days": 14,
            "source": "Fast change-control summary",
            "confidence": "Fast summary",
            "error_key": "change_control_operability_fact_error",
        },
        {
            "surface": "Evidence trend",
            "frame_key": "change_drift_evidence_trend",
            "meta_key": "change_drift_evidence_trend_meta",
            "days_key": "change_drift_evidence_trend_days",
            "default_days": 30,
            "source": "Workflow evidence",
            "confidence": "Workflow evidence",
            "error_key": "change_drift_evidence_trend_error",
        },
        {
            "surface": "Closure analytics",
            "frame_key": "change_action_closure",
            "meta_key": "change_action_closure_meta",
            "days_key": "change_action_closure_days",
            "default_days": 30,
            "source": "Action queue closure evidence",
            "confidence": "Workflow evidence",
            "error_key": "change_action_closure_error",
        },
        {
            "surface": "Terraform evidence",
            "frame_key": "change_integration_terraform_status",
            "meta_key": "change_integration_terraform_meta",
            "days_key": "change_integration_terraform_days",
            "default_days": 14,
            "source": f"Workflow evidence: {CHANGE_SOURCE_CONTROL_TABLE}",
            "confidence": "Workflow evidence",
            "error_key": "change_integration_terraform_error",
        },
        {
            "surface": "Jira evidence",
            "frame_key": "change_integration_jira_status",
            "meta_key": "change_integration_jira_meta",
            "days_key": "change_integration_jira_days",
            "default_days": 14,
            "source": f"Workflow evidence: {CHANGE_ITSM_TICKET_TABLE}",
            "confidence": "Workflow evidence",
            "error_key": "change_integration_jira_error",
        },
    ]
    rows = []
    for item in definitions:
        source_key = item.get("source_key")
        source = str((state.get(source_key, item["source"]) if source_key else item["source"]) or item["source"])
        frame = state.get(item["frame_key"])
        error_key = item.get("error_key")
        error = state.get(error_key) if error_key else None
        days_key = item.get("days_key")
        days = state.get(days_key, item.get("default_days")) if days_key else item.get("default_days")
        expected_meta = _change_scope_meta(company, environment, days=days, state=state)
        loaded = isinstance(frame, pd.DataFrame)
        if error:
            status = "Unavailable"
        elif not loaded:
            status = "Not Loaded"
        elif not _change_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif frame.empty:
            status = "No Rows"
        else:
            status = "Loaded"
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": {
                "Unavailable": 0,
                "Stale": 1,
                "Loaded": 2,
                "No Rows": 3,
                "Not Loaded": 4,
            }.get(status, 9),
            "SOURCE": source,
            "CONFIDENCE": _change_source_confidence(source, item["confidence"]),
            "ROWS": _change_row_count(frame),
            "SCOPE": f"{company} / {environment} / {int(days)}d",
            "NEXT_ACTION": _change_source_next_action(status, source),
        })
    return pd.DataFrame(rows)


def _change_owner_context(row: pd.Series | dict) -> dict:
    finding = str(row.get("FINDING_TYPE") or "").lower()
    entity = str(row.get("ENTITY") or "").upper()
    environment_label = environment_label_for_database(_change_database_name(row))
    if "policy" in finding or "tag" in finding or "masking" in finding:
        base = {
            "owner": "Security / Data Governance",
            "escalation": "Security Owner / Data Governance Lead",
            "source": "Change owner map",
        }
    elif "grant" in finding or "role" in finding or "owner" in finding:
        base = {
            "owner": "Security Owner",
            "escalation": "DBA Lead / Security Owner",
            "source": "Change owner map",
        }
    elif "drop" in finding or "destructive" in finding:
        base = {
            "owner": "DBA Change Owner",
            "escalation": "Data Owner / DBA Lead",
            "source": "Change owner map",
        }
    elif "drift" in finding:
        base = {
            "owner": "Platform Owner",
            "escalation": "DBA Lead / Platform Owner",
            "source": "Change owner map",
        }
    elif environment_label == "PROD":
        base = {
            "owner": "Production Data Owner",
            "escalation": "DBA Lead",
            "source": "Environment owner hint",
        }
    elif environment_label in {
        "ALFA_EDW_DEV",
        "ALFA_EDW_SAN",
        "ALFA_EDW_PHX",
        "ALFA_EDW_SEA",
        "ALFA_EDW_SIT",
        "Other ALFA Non-Prod",
    }:
        base = {
            "owner": "Development Data Owner",
            "escalation": "DBA Lead",
            "source": "Environment owner hint",
        }
    else:
        base = {
            "owner": "DBA Change Owner",
            "escalation": "DBA Lead",
            "source": "Default change owner",
        }
    directory_context = resolve_owner_context(
        row,
        entity=entity,
        entity_type="CHANGE_CONTROL",
        owner=base["owner"],
        category=finding or "Change Control",
    )
    return {
        "owner": directory_context.get("OWNER") or base["owner"],
        "escalation": base["escalation"] or directory_context.get("ESCALATION_TARGET", ""),
        "source": f"{base['source']}; {directory_context.get('OWNER_SOURCE', '')}".strip("; "),
        "owner_email": directory_context.get("OWNER_EMAIL", ""),
        "oncall_primary": directory_context.get("ONCALL_PRIMARY", ""),
        "oncall_secondary": directory_context.get("ONCALL_SECONDARY", ""),
        "approval_group": base["escalation"] or directory_context.get("APPROVAL_GROUP", ""),
        "owner_evidence": directory_context.get("OWNER_EVIDENCE", ""),
    }


def _change_iac_state(row: pd.Series | dict) -> str:
    query_tag = str(row.get("QUERY_TAG") or "").lower()
    finding = str(row.get("FINDING_TYPE") or "").lower()
    if any(token in query_tag for token in ("terraform", "iac", "liquibase", "flyway", "dbt", "deploy", "release")):
        return "Codified / deployment-tagged"
    if "drift" in finding:
        return "Reconcile IaC"
    severity = str(row.get("SEVERITY") or "").upper()
    if severity in {"CRITICAL", "HIGH"}:
        return "Manual change - IaC proof required"
    return "Review source-control state"


def _change_execution_audit_state(row: pd.Series | dict) -> str:
    query_id = str(row.get("QUERY_ID") or "").strip()
    last_seen = str(row.get("LAST_SEEN") or "").strip()
    if query_id and last_seen:
        return "Query ID and timestamp captured"
    if query_id:
        return "Query ID captured"
    return "Missing query_id proof"


def _change_review_sla_hours(severity: object, finding_type: object) -> int:
    severity_text = str(severity or "").upper()
    finding = str(finding_type or "").lower()
    if severity_text == "CRITICAL" or "destructive" in finding or "policy" in finding or "owner" in finding:
        return 24
    if severity_text == "HIGH":
        return 24
    if severity_text == "MEDIUM" or "grant" in finding or "role" in finding:
        return 72
    return 168


def _change_control_readiness_for_row(row: pd.Series | dict) -> dict:
    owner = str(row.get("OWNER") or "").strip()
    owner_source = str(row.get("OWNER_SOURCE") or "")
    approver = str(row.get("APPROVER") or row.get("APPROVAL_GROUP") or "").strip()
    severity = str(row.get("SEVERITY") or "").upper()
    ticket_state = str(row.get("CHANGE_TICKET_STATE") or "")
    iac_state = str(row.get("IAC_RECONCILIATION_STATE") or "")
    execution_state = str(row.get("EXECUTION_AUDIT_STATE") or "")
    approval_required = str(row.get("APPROVAL_REQUIRED") or "Yes").upper() == "YES" or severity in {"CRITICAL", "HIGH", "MEDIUM"}

    blockers = []
    generic_owners = {"", "DBA", "UNKNOWN", "N/A", "DBA CHANGE OWNER", "SECURITY OWNER"}
    owner_route_ready = bool(owner) and owner.upper() not in generic_owners and "OWNER_DIRECTORY" in owner_source.upper()
    if not owner_route_ready:
        blockers.append("owner directory evidence")
    if approval_required and not approver:
        blockers.append("approver")
    if ticket_state.lower().startswith("missing"):
        blockers.append("change ticket evidence")
    if "required" in iac_state.lower() or "reconcile" in iac_state.lower():
        blockers.append("source-control/IaC evidence")
    if execution_state.lower().startswith("missing"):
        blockers.append("query_id proof")

    route_blockers = {"owner directory evidence", "approver"}
    closure_blockers = [item for item in blockers if item not in route_blockers]
    if any(item in route_blockers for item in blockers):
        readiness = "Route Blocked"
    elif closure_blockers:
        readiness = "Closure Blocked"
    else:
        readiness = "Review Ready"

    if "change ticket evidence" in blockers:
        next_action = "Attach the approved change ticket or mark the row as unauthorized drift before closure."
    elif "source-control/IaC evidence" in blockers:
        next_action = "Attach deployment/source-control evidence, codify the drift, or revert through approved deployment."
    elif "query_id proof" in blockers:
        next_action = "Capture the Snowflake query_id and timestamp before accepting the change."
    elif readiness == "Route Blocked":
        next_action = "Assign a named owner and approver before queueing or closing the change."
    else:
        next_action = "Review blast radius, retain approval proof, and close only after verification evidence is attached."

    return {
        "APPROVAL_ROUTE_READY": "Yes" if owner_route_ready and (not approval_required or bool(approver)) else "No",
        "CHANGE_EVIDENCE_READINESS": readiness,
        "EVIDENCE_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "REVIEW_SLA_HOURS": _change_review_sla_hours(severity, row.get("FINDING_TYPE")),
        "NEXT_CONTROL_ACTION": next_action,
    }


def _enrich_change_control_evidence(readiness: pd.DataFrame) -> pd.DataFrame:
    if readiness is None or readiness.empty:
        return readiness
    view = readiness.copy()
    contexts = view.apply(_change_owner_context, axis=1)
    view["OWNER"] = contexts.apply(lambda item: item["owner"])
    view["ESCALATION_TARGET"] = contexts.apply(lambda item: item["escalation"])
    view["OWNER_SOURCE"] = contexts.apply(lambda item: item["source"])
    view["OWNER_EMAIL"] = contexts.apply(lambda item: item.get("owner_email", ""))
    view["ONCALL_PRIMARY"] = contexts.apply(lambda item: item.get("oncall_primary", ""))
    view["ONCALL_SECONDARY"] = contexts.apply(lambda item: item.get("oncall_secondary", ""))
    view["APPROVAL_GROUP"] = contexts.apply(lambda item: item.get("approval_group", ""))
    view["OWNER_EVIDENCE"] = contexts.apply(lambda item: item.get("owner_evidence", ""))
    view["DATABASE_NAME"] = view.apply(_change_database_name, axis=1)
    view["DATABASE_CONTEXT"] = view.apply(_change_database_context, axis=1)
    view["ENVIRONMENT"] = view.apply(_change_environment, axis=1)
    view["SCOPE_CONFIDENCE"] = view["DATABASE_CONTEXT"].map({True: "Database Context", False: "Account/Role Context"})
    view["SCOPE_EVIDENCE"] = view.apply(
        lambda row: (
            f"Database={row.get('DATABASE_NAME')}; environment={row.get('ENVIRONMENT')}"
            if bool(row.get("DATABASE_CONTEXT"))
            else "No database context; environment filter retained account-level change"
        ),
        axis=1,
    )
    view["CHANGE_TICKET_ID"] = view.apply(_change_ticket_id, axis=1)
    view["CHANGE_TICKET_STATE"] = view["CHANGE_TICKET_ID"].apply(
        lambda value: "Ticket detected" if str(value or "").strip() else "Missing ticket evidence"
    )
    view["IAC_RECONCILIATION_STATE"] = view.apply(_change_iac_state, axis=1)
    view["EXECUTION_AUDIT_STATE"] = view.apply(_change_execution_audit_state, axis=1)

    missing_ticket = view["CHANGE_TICKET_ID"].fillna("").astype(str).str.strip().eq("")
    missing_iac = view["IAC_RECONCILIATION_STATE"].fillna("").astype(str).str.contains("required|reconcile", case=False, na=False)
    missing_query = view["EXECUTION_AUDIT_STATE"].fillna("").astype(str).str.contains("missing", case=False, na=False)
    view.loc[missing_ticket, "CONTROL_GAP"] = "Missing change ticket evidence"
    view.loc[missing_iac, "CONTROL_GAP"] = "Missing IaC reconciliation evidence"
    view.loc[missing_query, "CONTROL_GAP"] = "Missing query_id proof"
    readiness_rows = view.apply(_change_control_readiness_for_row, axis=1)
    for column in [
        "APPROVAL_ROUTE_READY",
        "CHANGE_EVIDENCE_READINESS",
        "EVIDENCE_BLOCKERS",
        "REVIEW_SLA_HOURS",
        "NEXT_CONTROL_ACTION",
    ]:
        view[column] = readiness_rows.apply(lambda item, col=column: item.get(col, ""))
    return view


def _change_control_readiness_summary(readiness: pd.DataFrame) -> pd.DataFrame:
    """Summarize change-control blockers by environment, finding, and owner route."""
    if readiness is None or readiness.empty:
        return pd.DataFrame()
    view = _enrich_change_control_evidence(readiness)
    if view.empty:
        return pd.DataFrame()
    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    view["_HIGH_RISK"] = severity.isin(["CRITICAL", "HIGH"])
    view["_MISSING_TICKET"] = view.get("CHANGE_TICKET_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.lower().str.startswith("missing")
    view["_IAC_GAP"] = view.get("IAC_RECONCILIATION_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.contains("required|reconcile", case=False, na=False)
    view["_MISSING_QUERY"] = view.get("EXECUTION_AUDIT_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.lower().str.startswith("missing")
    view["_ACCOUNT_SCOPE"] = ~view.get("DATABASE_CONTEXT", pd.Series([False] * len(view), index=view.index)).astype(bool)
    view["_ROUTE_BLOCKED"] = view.get("CHANGE_EVIDENCE_READINESS", pd.Series([""] * len(view), index=view.index)).eq("Route Blocked")
    view["_CLOSURE_BLOCKED"] = view.get("CHANGE_EVIDENCE_READINESS", pd.Series([""] * len(view), index=view.index)).eq("Closure Blocked")
    view["_READY"] = view.get("CHANGE_EVIDENCE_READINESS", pd.Series([""] * len(view), index=view.index)).eq("Review Ready")

    group_cols = ["ENVIRONMENT", "FINDING_TYPE", "OWNER", "APPROVER"]
    for column in group_cols:
        if column not in view.columns:
            view[column] = ""

    rows = []
    for keys, group in view.groupby(group_cols, dropna=False):
        env, finding, owner, approver = keys
        missing_ticket = int(group["_MISSING_TICKET"].sum())
        iac_gap = int(group["_IAC_GAP"].sum())
        missing_query = int(group["_MISSING_QUERY"].sum())
        route_blocked = int(group["_ROUTE_BLOCKED"].sum())
        closure_blocked = int(group["_CLOSURE_BLOCKED"].sum())
        ready = int(group["_READY"].sum())
        if route_blocked:
            next_action = "Complete named owner and approver routing before accepting change evidence."
            readiness_label = "Route Blocked"
            rank = 0
        elif closure_blocked:
            next_action = "Attach missing ticket, query, or source-control evidence before closure."
            readiness_label = "Closure Blocked"
            rank = 1
        elif ready:
            next_action = "Review blast radius and close only after verification evidence is retained."
            readiness_label = "Review Ready"
            rank = 8
        else:
            next_action = "Review change-control metadata."
            readiness_label = "Review Required"
            rank = 5
        rows.append({
            "ENVIRONMENT": env,
            "FINDING_TYPE": finding,
            "OWNER": owner,
            "APPROVER": approver,
            "READINESS": readiness_label,
            "READINESS_RANK": rank,
            "TOTAL_CHANGES": int(len(group)),
            "HIGH_RISK_CHANGES": int(group["_HIGH_RISK"].sum()),
            "ROUTE_BLOCKED": route_blocked,
            "CLOSURE_BLOCKED": closure_blocked,
            "REVIEW_READY": ready,
            "MISSING_TICKET_ROWS": missing_ticket,
            "IAC_GAP_ROWS": iac_gap,
            "MISSING_QUERY_ID_ROWS": missing_query,
            "ACCOUNT_SCOPE_ROWS": int(group["_ACCOUNT_SCOPE"].sum()),
            "OLDEST_LAST_SEEN": group.get("LAST_SEEN", pd.Series(dtype=str)).min() if "LAST_SEEN" in group.columns else "",
            "REVIEW_SLA_HOURS": int(pd.to_numeric(group.get("REVIEW_SLA_HOURS", pd.Series([168])), errors="coerce").fillna(168).min()),
            "NEXT_CONTROL_ACTION": next_action,
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["READINESS_RANK", "HIGH_RISK_CHANGES", "MISSING_TICKET_ROWS", "IAC_GAP_ROWS", "TOTAL_CHANGES"],
        ascending=[True, False, False, False, False],
    ).reset_index(drop=True)


def _change_frame_sum(frame: pd.DataFrame | None, column: str) -> int:
    if frame is None or frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _change_operator_next_moves(
    *,
    score: int | float,
    exceptions: pd.DataFrame | None,
    readiness_summary: pd.DataFrame | None = None,
    readiness: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a no-query decision gate for loaded change and drift evidence."""
    exception_count = 0 if exceptions is None or exceptions.empty else int(len(exceptions))
    summary = pd.DataFrame() if readiness_summary is None else readiness_summary.copy()
    detail = pd.DataFrame() if readiness is None else readiness.copy()
    close = pd.DataFrame() if closure is None else closure.copy()
    fact = pd.DataFrame() if operability_fact is None else operability_fact.copy()
    for frame in (summary, detail, close, fact):
        if not frame.empty:
            frame.columns = [str(col).upper() for col in frame.columns]

    route_blocked = max(
        _change_frame_sum(summary, "ROUTE_BLOCKED"),
        _change_frame_sum(fact, "ROUTE_BLOCKED"),
    )
    closure_blocked = max(
        _change_frame_sum(summary, "CLOSURE_BLOCKED"),
        _change_frame_sum(fact, "CLOSURE_BLOCKED"),
    )
    missing_ticket = max(
        _change_frame_sum(summary, "MISSING_TICKET_ROWS"),
        _change_frame_sum(fact, "MISSING_TICKET_ROWS"),
    )
    iac_gap = max(
        _change_frame_sum(summary, "IAC_GAP_ROWS"),
        _change_frame_sum(fact, "IAC_GAP_ROWS"),
    )
    missing_query = max(
        _change_frame_sum(summary, "MISSING_QUERY_ID_ROWS"),
        _change_frame_sum(fact, "MISSING_QUERY_ID_ROWS"),
    )
    account_scope = max(
        _change_frame_sum(summary, "ACCOUNT_SCOPE_ROWS"),
        int((~detail.get("DATABASE_CONTEXT", pd.Series(dtype=bool)).astype(bool)).sum()) if not detail.empty and "DATABASE_CONTEXT" in detail.columns else 0,
    )
    high_risk = max(
        _change_frame_sum(summary, "HIGH_RISK_CHANGES"),
        _change_frame_sum(fact, "HIGH_RISK_CHANGES"),
    )
    overdue = max(
        _change_frame_sum(close, "OVERDUE_OPEN"),
        _change_frame_sum(fact, "OVERDUE_OPEN"),
    )
    fixed_without_verification = max(
        _change_frame_sum(close, "FIXED_WITHOUT_VERIFICATION"),
        _change_frame_sum(fact, "FIXED_WITHOUT_VERIFICATION"),
    )
    recovery_risk = max(
        _change_frame_sum(close, "RECOVERY_RISK_ROWS"),
        _change_frame_sum(fact, "RECOVERY_RISK_ROWS"),
    )
    closure_proof_blocks = max(
        _change_frame_sum(close, "CLOSURE_BLOCKER_ROWS"),
        overdue + fixed_without_verification + recovery_risk,
    )
    evidence_gaps = closure_blocked + missing_ticket + iac_gap + missing_query

    rows: list[dict] = []
    if route_blocked:
        state = "Route Blocked"
        rank = 0
        next_action = "Assign named owners and approvers before accepting or queueing the change."
        count = route_blocked
    elif exception_count:
        state = "Route Ready"
        rank = 6
        next_action = "Use the readiness rows to confirm owner and approver evidence before closure."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "No change route needs owner intervention in the loaded scope."
        count = 0
    rows.append({
        "GATE": "Owner approval route",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "named owner, approver, approval group, owner evidence",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if evidence_gaps:
        state = "Evidence Blocked"
        rank = 1
        next_action = "Attach ticket, source-control/IaC, query_id, and blast-radius proof before closure."
        count = evidence_gaps
    elif exception_count:
        state = "Review Ready"
        rank = 6
        next_action = "Save the evidence snapshot, then queue only verified exceptions that still need DBA action."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "No ticket, IaC, or query proof gap crossed the current thresholds."
        count = 0
    rows.append({
        "GATE": "Change proof",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "change ticket, query_id, source-control/IaC note, blast-radius evidence",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if closure_proof_blocks:
        state = "Closure Blocked"
        rank = 2
        next_action = "Reopen or hold change actions until verification and recovery evidence is attached."
        count = closure_proof_blocks
    elif exception_count and close.empty:
        state = "Load Closure Analytics"
        rank = 4
        next_action = "Load closure analytics before claiming drift or change-control work is complete."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "Retain verified closure evidence for audit review."
        count = _change_frame_sum(close, "VERIFIED_CLOSURES") + _change_frame_sum(fact, "VERIFIED_CLOSURES")
    rows.append({
        "GATE": "Closure proof",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "verification result, recovery evidence, ticket closure, owner approval",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if account_scope:
        state = "Account-Scope Review"
        rank = 3
        next_action = "Validate account/role-only changes separately; database environment scope cannot prove ownership alone."
        count = account_scope
    else:
        state = "Database Scoped"
        rank = 8
        next_action = "Use the selected environment/database evidence for scoped change review."
        count = 0
    rows.append({
        "GATE": "Scope confidence",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "database context where present; explicit account-level approval where database context is absent",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    recovery_sensitive = 0
    if exceptions is not None and not exceptions.empty:
        finding_text = exceptions.get("FINDING_TYPE", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        recovery_sensitive = int(
            finding_text.str.contains("DESTRUCTIVE|DROP|POLICY|TAG|OWNER", regex=True, na=False).sum()
        )
    if recovery_risk or recovery_sensitive:
        state = "Recovery Proof Required"
        rank = 3
        next_action = "Attach restore, rollback, downstream dependency, and owner approval evidence before accepting this change."
        count = max(recovery_risk, recovery_sensitive)
    else:
        state = "Clear"
        rank = 8
        next_action = "No destructive, ownership, or policy/tag change currently requires extra recovery proof."
        count = 0
    rows.append({
        "GATE": "Recovery readiness",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "restore path, rollback plan, dependency impact, owner approval, post-change verification",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if high_risk or safe_float(score) < 95:
        state = "Review Required" if high_risk else "Watch"
        rank = 5
        next_action = "Work high-risk destructive, policy, owner, role, and manual drift rows before routine changes."
        count = high_risk or exception_count
    else:
        state = "Controlled"
        rank = 8
        next_action = "No high-risk change exceeded the current threshold."
        count = 0
    rows.append({
        "GATE": "Change pressure",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "severity, finding type, user, role, last seen, blast-radius review",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    return pd.DataFrame(rows).sort_values(["GATE_RANK", "COUNT"], ascending=[True, False]).reset_index(drop=True)


def _change_drift_score(
    *,
    object_changes: int,
    access_changes: int,
    policy_changes: int,
    owner_changes: int,
    destructive_changes: int,
    manual_drift: int,
) -> int:
    object_penalty = min(15, safe_float(object_changes) * 0.3)
    access_penalty = min(20, safe_float(access_changes) * 0.8)
    policy_penalty = min(25, safe_float(policy_changes) * 4)
    owner_penalty = min(20, safe_float(owner_changes) * 3)
    destructive_penalty = min(25, safe_float(destructive_changes) * 5)
    drift_penalty = min(20, safe_float(manual_drift) * 1.5)
    return max(0, min(100, int(round(
        100
        - object_penalty
        - access_penalty
        - policy_penalty
        - owner_penalty
        - destructive_penalty
        - drift_penalty
    ))))


def _change_drift_rating(score: int) -> str:
    if score >= 95:
        return "Controlled"
    if score >= 85:
        return "Watch"
    if score >= 70:
        return "Elevated"
    return "High Drift Risk"


def _change_action_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "drop" in value or "destructive" in value:
        return (
            "Object",
            "Confirm change approval, downstream dependencies, backup/recovery posture, and whether the object should be restored.",
            "-- Proof: QUERY_HISTORY destructive DDL query_id and query text.",
        )
    if "policy" in value or "tag" in value or "masking" in value:
        return (
            "Policy/Tag",
            "Validate policy owner, classification impact, and whether masking/tag changes match governance approval.",
            "-- Proof: QUERY_HISTORY masking/tag/row-access policy DDL.",
        )
    if "grant" in value or "role" in value or "owner" in value:
        return (
            "Grant/Role",
            "Confirm requester, approver, role hierarchy, and ownership transfer before accepting the access change.",
            "-- Proof: QUERY_HISTORY grant/revoke/ownership DDL.",
        )
    if "drift" in value:
        return (
            "Drift",
            "Compare the query with Terraform/IaC state; either codify the change or revert it through approved deployment.",
            "-- Proof: QUERY_HISTORY non-IaC DDL/DCL query text and query tag.",
        )
    return (
        "Object",
        "Review change for approval, ownership, dependency impact, and drift risk.",
        "-- Proof: QUERY_HISTORY change statement.",
    )


def _change_approval_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "drop" in value or "destructive" in value:
        return (
            "Requested",
            "DBA Lead / Data Owner",
            "Destructive DDL requires data-owner approval, dependency review, and recovery evidence.",
        )
    if "policy" in value or "tag" in value or "masking" in value:
        return (
            "Requested",
            "Security Owner / Data Governance",
            "Policy, tag, masking, and row-access changes require security/governance approval.",
        )
    if "grant" in value or "role" in value or "owner" in value:
        return (
            "Requested",
            "Security Owner",
            "Grant, revoke, role, and ownership changes require access-request approval evidence.",
        )
    if "drift" in value:
        return (
            "Requested",
            "DBA Lead / Platform Owner",
            "Manual drift must be tied to a change ticket, codified in IaC, or reverted through deployment.",
        )
    return (
        "Requested",
        "Data Owner",
        "Object changes require requester, approver, and change-ticket evidence before closure.",
    )


def _change_verification_sql(query_id: object) -> str:
    query_id_text = str(query_id or "").strip()
    if not query_id_text:
        return """
SELECT
    query_id,
    start_time,
    user_name,
    role_name,
    database_name,
    schema_name,
    query_type,
    query_tag,
    query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE 1 = 0
LIMIT 50""".strip()
    return f"""
SELECT
    query_id,
    start_time,
    user_name,
    role_name,
    database_name,
    schema_name,
    query_type,
    query_tag,
    query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_id = {sql_literal(query_id_text, 200)}
LIMIT 50""".strip()


def _change_blast_radius_sql(entity: object) -> str:
    """Build read-only object dependency evidence for a changed object or schema."""
    raw = str(entity or "").strip()
    pieces = _split_snowflake_qualified_name(raw)
    if not pieces or raw.lower() in {"unknown", "snowflake account"}:
        return """
SELECT
    referenced_database,
    referenced_schema,
    referenced_object_name,
    referencing_database,
    referencing_schema,
    referencing_object_name,
    dependency_type
FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
WHERE 1 = 0
LIMIT 100""".strip()

    predicates = []
    if len(pieces) >= 3:
        db_name, schema_name, object_name = pieces[0], pieces[1], pieces[2]
        predicates.append(
            "("
            f"UPPER(referenced_database) = UPPER({sql_literal(db_name, 300)}) "
            f"AND UPPER(referenced_schema) = UPPER({sql_literal(schema_name, 300)}) "
            f"AND UPPER(referenced_object_name) = UPPER({sql_literal(object_name, 500)})"
            ")"
        )
        predicates.append(
            "("
            f"UPPER(referencing_database) = UPPER({sql_literal(db_name, 300)}) "
            f"AND UPPER(referencing_schema) = UPPER({sql_literal(schema_name, 300)}) "
            f"AND UPPER(referencing_object_name) = UPPER({sql_literal(object_name, 500)})"
            ")"
        )
    elif len(pieces) == 2:
        db_name, schema_name = pieces[0], pieces[1]
        predicates.append(
            "("
            f"UPPER(referenced_database) = UPPER({sql_literal(db_name, 300)}) "
            f"AND UPPER(referenced_schema) = UPPER({sql_literal(schema_name, 300)})"
            ")"
        )
        predicates.append(
            "("
            f"UPPER(referencing_database) = UPPER({sql_literal(db_name, 300)}) "
            f"AND UPPER(referencing_schema) = UPPER({sql_literal(schema_name, 300)})"
            ")"
        )
    else:
        db_name = pieces[0]
        predicates.append(f"UPPER(referenced_database) = UPPER({sql_literal(db_name, 300)})")
        predicates.append(f"UPPER(referencing_database) = UPPER({sql_literal(db_name, 300)})")

    where_clause = " OR\n      ".join(predicates)
    return f"""
SELECT
    referenced_database,
    referenced_schema,
    referenced_object_name,
    referenced_object_domain,
    referencing_database,
    referencing_schema,
    referencing_object_name,
    referencing_object_domain,
    dependency_type
FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
WHERE {where_clause}
ORDER BY referenced_database, referenced_schema, referenced_object_name, referencing_database, referencing_schema, referencing_object_name
LIMIT 100""".strip()


def _build_change_control_readiness(exceptions: pd.DataFrame) -> pd.DataFrame:
    """Add ticket, approval, and proof requirements before queueing changes."""
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    view = _change_priority_view(exceptions).copy()
    approval_rows = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(_change_approval_for)
    view["APPROVAL_REQUIRED"] = "Yes"
    view["OWNER_APPROVAL_STATUS"] = approval_rows.apply(lambda item: item[0])
    view["APPROVER"] = approval_rows.apply(lambda item: item[1])
    view["OWNER_APPROVAL_NOTE"] = approval_rows.apply(lambda item: item[2])
    view["TICKET_REQUIRED"] = "Yes"
    view["VERIFICATION_QUERY"] = view.get("QUERY_ID", pd.Series([""] * len(view), index=view.index)).apply(_change_verification_sql)
    view["BLAST_RADIUS_QUERY"] = view.get("ENTITY", pd.Series([""] * len(view), index=view.index)).apply(_change_blast_radius_sql)
    view["BLAST_RADIUS_REQUIRED"] = "Yes"
    view["PROOF_REQUIRED"] = "query_id, approver, change ticket, dependency/blast-radius note"

    query_missing = view.get("QUERY_ID", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.strip().eq("")
    high_risk = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper().isin(["CRITICAL", "HIGH"])
    finding = view.get("FINDING_TYPE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.lower()

    view["CONTROL_GAP"] = "Needs approver, change ticket, and blast-radius note"
    view.loc[query_missing, "CONTROL_GAP"] = "Missing query_id proof"
    view["CHANGE_CONTROL_STATE"] = "Validate Approval"
    view.loc[finding.str.contains("drift", na=False), "CHANGE_CONTROL_STATE"] = "Reconcile IaC"
    view.loc[high_risk, "CHANGE_CONTROL_STATE"] = "Approval Required"
    view.loc[query_missing, "CHANGE_CONTROL_STATE"] = "Proof Missing"
    return _enrich_change_control_evidence(view)


def _change_action_payload(row: pd.Series | dict, company: str, environment: str = "") -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "Change")
    entity = str(row.get("ENTITY") or row.get("QUERY_ID") or "Snowflake account")
    user_name = str(row.get("USER_NAME") or "unknown")
    severity = str(row.get("SEVERITY") or "Medium")
    query_id = str(row.get("QUERY_ID") or "").strip()
    entity_type, action, generated_sql = _change_action_for(finding_type)
    approval_status, approver, approval_note = _change_approval_for(finding_type)
    owner_context = _change_owner_context(row)
    ticket_id = _change_ticket_id(row)
    ticket_state = "ticket detected" if ticket_id else "missing ticket evidence"
    iac_state = _change_iac_state(row)
    audit_state = _change_execution_audit_state(row)
    env_value = str(row.get("ENVIRONMENT") or _change_environment(row, environment) or environment or "ALL")
    verification_query = _change_verification_sql(query_id)
    blast_radius_query = _change_blast_radius_sql(entity)
    finding = f"{finding_type} by {user_name} on {entity}"
    generated_review = "\n".join([
        "-- Review-only change-control record. Do not execute state-changing SQL from this queue row.",
        generated_sql,
        f"-- Required proof: query_id={query_id or 'missing'}, approver, change ticket, and dependency/blast-radius note.",
        f"-- Ticket evidence: {ticket_id or 'missing'} ({ticket_state}).",
        f"-- IaC/source-control state: {iac_state}.",
        f"-- Execution audit state: {audit_state}.",
        "-- Read-only blast-radius check to run before approval:",
        blast_radius_query,
    ])
    return {
        "Action ID": make_action_id("Change Drift", entity, f"{finding}|{query_id}"),
        "Source": "Change & Drift - Brief",
        "Severity": severity,
        "Category": "Change Control",
        "Entity Type": entity_type,
        "Entity": entity,
        "Owner": owner_context["owner"],
        "Owner Email": owner_context.get("owner_email", ""),
        "Oncall Primary": owner_context.get("oncall_primary", ""),
        "Oncall Secondary": owner_context.get("oncall_secondary", ""),
        "Approval Group": owner_context.get("approval_group", approver),
        "Escalation Target": owner_context.get("escalation", ""),
        "Owner Source": owner_context.get("source", ""),
        "Owner Evidence": owner_context.get("owner_evidence", ""),
        "Finding": finding,
        "Action": action,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": generated_review,
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Approver": approver,
        "Owner Approval Status": approval_status,
        "Owner Approval Note": (
            f"{approval_note} Ticket={ticket_id or 'missing'}; "
            f"IaC={iac_state}; escalation={owner_context['escalation']}."
        ),
        "Recovery Evidence": (
            f"Run blast-radius check before closure:\n{blast_radius_query}\n\n"
            f"Ticket evidence: {ticket_id or 'missing'}\n"
            f"IaC/source-control evidence: {iac_state}\n"
            f"Execution audit: {audit_state}"
        ),
        "Recovery Audit State": audit_state,
        "Recovery SLA Target Hours": 24 if severity.upper() in {"CRITICAL", "HIGH"} else 72,
        "Company": company,
        "Environment": env_value,
        "Ticket ID": ticket_id,
    }


def _change_workflow_for(row: pd.Series) -> str:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    query_text = str(row.get("QUERY_TEXT") or "").lower()
    if "drift" in finding_type:
        return "Schema and object drift"
    if "procedure" in query_text:
        return "Stored procedure lineage"
    if "dynamic table" in query_text or "replication" in query_text or "pipe" in query_text:
        return "Data movement and replication"
    if "grant" in finding_type or "role" in finding_type or "owner" in finding_type or "policy" in finding_type or "tag" in finding_type:
        return "Object and access changes"
    return "Object and access changes"


def _change_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = exceptions.copy()
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["ENTITY_TYPE"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _change_action_for(value)[0])
    view["NEXT_ACTION"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _change_action_for(value)[1])
    view["NEXT_WORKFLOW"] = view.apply(_change_workflow_for, axis=1)
    sort_cols = ["_RANK"]
    ascending = [True]
    if "LAST_SEEN" in view.columns:
        sort_cols.append("LAST_SEEN")
        ascending.append(False)
    return view.sort_values(sort_cols, ascending=ascending).drop(columns=["_RANK"], errors="ignore")


def _change_intervention_matrix(
    exceptions: pd.DataFrame,
    readiness: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rank change/drift rows by whether the DBA can verify, reconcile, or must block closure."""
    priority = _change_priority_view(exceptions)
    if priority.empty:
        return pd.DataFrame()

    ready = readiness if isinstance(readiness, pd.DataFrame) else pd.DataFrame()
    closure_df = closure if isinstance(closure, pd.DataFrame) else pd.DataFrame()
    ready_by_key = {}
    if not ready.empty:
        for _, row in ready.iterrows():
            key = (
                str(row.get("FINDING_TYPE") or "").upper(),
                str(row.get("ENTITY") or "").upper(),
                str(row.get("QUERY_ID") or "").upper(),
            )
            ready_by_key[key] = row
    closure_by_entity = {
        str(row.get("CHANGE_ENTITY") or row.get("ENTITY") or row.get("CHECK_NAME") or "").upper(): row
        for _, row in closure_df.iterrows()
    } if not closure_df.empty else {}

    rows: list[dict] = []
    for _, item in priority.head(30).iterrows():
        finding = str(item.get("FINDING_TYPE") or "Change")
        entity = str(item.get("ENTITY") or "Snowflake account")
        query_id = str(item.get("QUERY_ID") or "").strip()
        ready_row = ready_by_key.get((finding.upper(), entity.upper(), query_id.upper()), {})
        closure_row = closure_by_entity.get(entity.upper(), {})
        severity = str(item.get("SEVERITY") or "Medium")
        control_state = str(ready_row.get("CHANGE_CONTROL_STATE") or item.get("CHANGE_CONTROL_STATE") or "Review")
        ticket_state = str(ready_row.get("CHANGE_TICKET_STATE") or "")
        iac_state = str(ready_row.get("IAC_RECONCILIATION_STATE") or "")
        closure_state = str(closure_row.get("CLOSURE_READINESS") or "No recent action")
        finding_upper = finding.upper()
        recovery_sensitive = any(token in finding_upper for token in ("DESTRUCTIVE", "DROP", "POLICY", "TAG", "OWNER"))
        missing_query = not query_id
        missing_ticket = "MISSING" in ticket_state.upper() or not str(ready_row.get("CHANGE_TICKET_ID") or "").strip()
        iac_gap = "GAP" in iac_state.upper() or "MISSING" in iac_state.upper()
        closure_bad = any(token in closure_state.upper() for token in ("OVERDUE", "WITHOUT VERIFICATION", "GAP"))

        if recovery_sensitive:
            state = "Recovery Block"
            rank = 0
            decision = "Block closure until restore path, dependency blast radius, owner approval, and rollback proof exist."
        elif missing_query or missing_ticket or iac_gap or closure_bad:
            state = "Evidence Block"
            rank = 1
            decision = "Attach query_id, ticket/source-control evidence, and verification proof before accepting the change."
        elif severity.upper() in {"CRITICAL", "HIGH"}:
            state = "Verify Now"
            rank = 2
            decision = "Review actor, role, blast radius, and approval path before queueing the action."
        else:
            state = "Watch"
            rank = 4
            decision = "Keep for trend review; no immediate high-risk intervention signal."

        rows.append({
            "DBA_PRIORITY": f"P{rank}",
            "INTERVENTION_STATE": state,
            "SEVERITY": severity,
            "FINDING_TYPE": finding,
            "ENTITY": entity,
            "USER_NAME": str(item.get("USER_NAME") or "unknown"),
            "ROLE_NAME": str(item.get("ROLE_NAME") or ""),
            "QUERY_ID": query_id,
            "CONTROL_STATE": control_state,
            "TICKET_STATE": ticket_state or "Missing",
            "IAC_STATE": iac_state or "Missing",
            "CLOSURE_READINESS": closure_state,
            "NEXT_DECISION": decision,
            "PROOF_REQUIRED": "query_id, change ticket, source-control/IaC note, blast-radius evidence, owner approval",
            "NEXT_WORKFLOW": str(item.get("NEXT_WORKFLOW") or _change_workflow_for(item)),
            "_RANK": rank,
        })

    return pd.DataFrame(rows).sort_values(
        ["_RANK", "SEVERITY", "FINDING_TYPE", "ENTITY"],
        ascending=[True, True, True, True],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _render_change_watch_floor(score: int, exceptions: pd.DataFrame, row) -> None:
    priority = _change_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())
    actors = safe_int(row.get("ACTORS", 0))
    affected_dbs = safe_int(row.get("AFFECTED_DATABASES", 0))

    render_shell_snapshot((
        ("High-Risk Changes", f"{high_risk:,}"),
        ("Manual Drift", f"{safe_int(row.get('MANUAL_DRIFT', 0)):,}"),
        ("Affected DBs", f"{affected_dbs:,}"),
    ))
    if priority.empty:
        st.success("No urgent change/drift exceptions crossed the brief thresholds.")
    else:
        first = priority.iloc[0]
        st.warning(
            f"First move: {first.get('FINDING_TYPE', 'Change')} by "
            f"{first.get('USER_NAME', 'unknown')} -> {first.get('NEXT_ACTION', 'Validate the change.')}"
        )

    st.markdown("**Change Watch Floor**")
    st.caption(f"Actors: {actors:,} | Affected databases: {affected_dbs:,}")
    if priority.empty:
        st.caption("No immediate change cards. Use Object and access changes for investigation or Schema and object drift for periodic control review.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Object and access changes")
        with cols[idx]:
            st.markdown(f"**{item.get('SEVERITY', 'Medium')}: {item.get('FINDING_TYPE', '')}**")
            st.caption(f"{item.get('ENTITY_TYPE', 'Object')}: {item.get('ENTITY', 'unknown')}")
            st.caption(f"Actor: {item.get('USER_NAME', 'unknown')} | Query: {item.get('QUERY_ID', '')}")
            st.write(str(item.get("NEXT_ACTION", "")))
            if st.button(f"Open {workflow}", key=f"change_watch_floor_{idx}_{workflow}", width="stretch"):
                entity = str(item.get("ENTITY") or "").strip()
                actor = str(item.get("USER_NAME") or "").strip()
                query_id = str(item.get("QUERY_ID") or "").strip()
                if actor and actor.lower() != "unknown":
                    st.session_state["global_user"] = actor
                if entity and entity.lower() != "unknown" and not entity.startswith("01"):
                    st.session_state["global_database"] = entity.split(".")[0]
                if query_id:
                    st.session_state["qs_text"] = query_id
                    st.session_state["qs_status"] = "ALL"
                    st.session_state["qs_autorun"] = True
                for stale_key in (
                    "ocm_df_object_changes",
                    "ocm_df_access_changes",
                    "ocm_df_policy_changes",
                    "ocm_df_drift",
                ):
                    st.session_state.pop(stale_key, None)
                _queue_change_workflow(workflow)


def _change_action_brief(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> dict:
    expected_meta = _change_scope_meta(company, environment, days)
    loaded = (
        _change_looks_like_frame(summary)
        and not summary.empty
        and _change_meta_matches(meta, expected_meta)
    )
    if not loaded:
        if _change_looks_like_frame(summary) and not summary.empty:
            return {
                "state": "Stale",
                "headline": "Reload the change brief before acting.",
                "detail": "Loaded change evidence does not match the active company, environment, filters, or lookback.",
            }
        return {
            "state": "Ready",
            "headline": "Load recent DDL, grant, owner, policy, and drift evidence.",
            "detail": "No Snowflake change evidence loads until you request the selected scope.",
        }

    row = summary.iloc[0]
    object_changes = safe_int(row.get("OBJECT_CHANGES", 0))
    access_changes = safe_int(row.get("ACCESS_CHANGES", 0))
    policy_changes = safe_int(row.get("POLICY_CHANGES", 0))
    owner_changes = safe_int(row.get("OWNER_CHANGES", 0))
    destructive_changes = safe_int(row.get("DESTRUCTIVE_CHANGES", 0))
    manual_drift = safe_int(row.get("MANUAL_DRIFT", 0))
    score = _change_drift_score(
        object_changes=object_changes,
        access_changes=access_changes,
        policy_changes=policy_changes,
        owner_changes=owner_changes,
        destructive_changes=destructive_changes,
        manual_drift=manual_drift,
    )
    high_risk = 0
    if _change_looks_like_frame(exceptions) and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())

    if destructive_changes or policy_changes or owner_changes:
        return {
            "state": "Control Review",
            "headline": "Validate recovery-sensitive changes first.",
            "detail": f"{destructive_changes:,} destructive, {policy_changes:,} policy, and {owner_changes:,} ownership change(s) need approval proof.",
        }
    if high_risk:
        return {
            "state": "Verify Now",
            "headline": "Review high-priority change exceptions.",
            "detail": f"{high_risk:,} Critical/High exception(s) across {object_changes + access_changes:,} object/access change(s).",
        }
    if manual_drift:
        return {
            "state": "Drift Watch",
            "headline": "Compare manual changes against deployment evidence.",
            "detail": f"{manual_drift:,} manual drift indicator(s) need source-control or ticket reconciliation.",
        }
    if score < 95:
        return {
            "state": _change_drift_rating(score),
            "headline": "Review change volume before closing the window.",
            "detail": f"{object_changes + access_changes:,} object/access change(s) loaded for the selected scope.",
        }
    return {
        "state": "Controlled",
        "headline": "No immediate change-control blocker in the loaded brief.",
        "detail": f"{object_changes + access_changes:,} object/access change(s), {manual_drift:,} drift indicator(s).",
    }


def _render_change_action_brief(brief: dict) -> None:
    with st.container(border=True):
        label_col, detail_col = st.columns([1.1, 4.6])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(str(brief.get("state") or "Review"))
        with detail_col:
            st.markdown(f"**{brief.get('headline') or 'Review change evidence.'}**")
            st.caption(str(brief.get("detail") or ""))


def _change_operating_snapshot(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> dict:
    loaded = (
        _change_looks_like_frame(summary)
        and not summary.empty
        and _change_meta_matches(meta, _change_scope_meta(company, environment, days))
    )
    if not loaded:
        return {
            "loaded": False,
            "scope": str(company or "All"),
            "window": f"{safe_int(days, 14):d}d",
            "evidence": "Load brief",
            "risk": "On demand",
        }

    row = summary.iloc[0]
    policy_owner = safe_int(row.get("POLICY_CHANGES", 0)) + safe_int(row.get("OWNER_CHANGES", 0))
    high_risk = 0
    if _change_looks_like_frame(exceptions) and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())
    return {
        "loaded": True,
        "object_changes": safe_int(row.get("OBJECT_CHANGES", 0)),
        "access_changes": safe_int(row.get("ACCESS_CHANGES", 0)),
        "policy_owner": policy_owner,
        "high_risk": high_risk,
    }


def _render_change_operating_snapshot(snapshot: dict) -> None:
    st.markdown("**Operating Snapshot**")
    loaded = bool(snapshot.get("loaded"))
    if not loaded:
        render_shell_snapshot((
            ("Scope", str(snapshot.get("scope") or "All")),
            ("Window", str(snapshot.get("window") or "14d")),
            ("Evidence", str(snapshot.get("evidence") or "Load brief")),
            ("Risk", str(snapshot.get("risk") or "On demand")),
        ))
        return
    render_shell_snapshot((
        ("Objects", f"{safe_int(snapshot.get('object_changes')):,}"),
        ("Access", f"{safe_int(snapshot.get('access_changes')):,}"),
        ("Policy", f"{safe_int(snapshot.get('policy_owner')):,}"),
        ("High Risk", f"{safe_int(snapshot.get('high_risk')):,}"),
    ))


def _queue_change_workflow(workflow: str) -> None:
    if workflow in WORKFLOWS:
        st.session_state["change_drift_requested_view"] = "Change Workflows"
        st.session_state["change_drift_requested_workflow"] = workflow
        st.rerun()


def _apply_queued_change_workflow() -> None:
    requested_view = st.session_state.pop("change_drift_requested_view", None)
    requested_workflow = st.session_state.pop("change_drift_requested_workflow", None)
    if requested_view in CHANGE_DRIFT_VIEWS:
        st.session_state["change_drift_view"] = requested_view
    if requested_workflow in WORKFLOWS:
        st.session_state["change_drift_workflow"] = requested_workflow


def _apply_change_brief_first_default() -> None:
    if st.session_state.get("_change_drift_brief_first_version") == CHANGE_DRIFT_BRIEF_FIRST_VERSION:
        return
    if (
        not _change_has_source_state(st.session_state)
        and st.session_state.get("change_drift_view") not in (None, "Change Brief")
    ):
        st.session_state["change_drift_view"] = "Change Brief"
    st.session_state["_change_drift_brief_first_version"] = CHANGE_DRIFT_BRIEF_FIRST_VERSION


def _change_brief_workflow_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in CHANGE_BRIEF_WORKFLOWS:
        workflow = str(item["WORKFLOW"])
        rows.append({
            "WORKFLOW": workflow,
            "BUTTON_LABEL": str(item["BUTTON_LABEL"]),
            "DBA_MOVE": str(item["DBA_MOVE"]),
            "WHEN": str(item["WHEN"]),
            "SOURCES": WORKFLOW_DETAILS.get(workflow, "Change workflow detail"),
        })
    return rows


def _render_change_brief_launchpad() -> None:
    st.markdown("**Change Investigation Workflows**")
    rows = _change_brief_workflow_rows()
    show_all = bool(st.session_state.get("change_drift_show_all_workflows"))
    visible_rows = rows if show_all else rows[:3]
    for offset in range(0, len(visible_rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, visible_rows[offset:offset + 3]):
            with col:
                st.markdown(f"**{row['WORKFLOW']}**")
                st.caption(row["DBA_MOVE"])
                st.caption(row["WHEN"])
                if st.button(row["BUTTON_LABEL"], key=f"change_brief_{row['WORKFLOW']}", width="stretch"):
                    _queue_change_workflow(row["WORKFLOW"])
    if len(rows) > len(visible_rows):
        if st.button("More Change Workflows", key="change_drift_show_all_workflows_button"):
            st.session_state["change_drift_show_all_workflows"] = True
            st.rerun()
    elif show_all and len(rows) > 3:
        if st.button("Hide Change Workflows", key="change_drift_hide_all_workflows_button"):
            st.session_state["change_drift_show_all_workflows"] = False
            st.rerun()


def _build_change_drift_markdown(
    *,
    company: str,
    days: int,
    score: int,
    summary_row,
    exceptions: pd.DataFrame,
) -> str:
    exception_lines = []
    if exceptions is not None and not exceptions.empty:
        for _, row in exceptions.head(10).iterrows():
            exception_lines.append(
                f"- {row.get('SEVERITY', 'Medium')}: {row.get('FINDING_TYPE', 'Change')} "
                f"by {row.get('USER_NAME', 'unknown')} on {row.get('ENTITY', 'unknown')}."
            )
    else:
        exception_lines.append("- No change/drift exceptions crossed the configured thresholds.")
    lines = [
        f"# OVERWATCH Change & Drift Brief - {company}",
        "",
        f"Lookback window: {days} day(s).",
        f"Control state: {_change_drift_rating(score)}.",
        "",
        "## Key Metrics",
        f"- Object changes: {safe_int(summary_row.get('OBJECT_CHANGES', 0)):,}",
        f"- Access changes: {safe_int(summary_row.get('ACCESS_CHANGES', 0)):,}",
        f"- Owner changes: {safe_int(summary_row.get('OWNER_CHANGES', 0)):,}",
        f"- Policy/tag changes: {safe_int(summary_row.get('POLICY_CHANGES', 0)):,}",
        f"- Destructive changes: {safe_int(summary_row.get('DESTRUCTIVE_CHANGES', 0)):,}",
        f"- Manual/non-IaC drift indicators: {safe_int(summary_row.get('MANUAL_DRIFT', 0)):,}",
        "",
        "## Exceptions",
        *exception_lines,
        "",
        "## DBA Follow-Up",
        "- Review destructive and policy changes first.",
        "- Validate grants, revokes, and ownership transfers against approved access requests.",
        "- Compare manual/non-IaC changes with Terraform or deployment records.",
        "- Save material exceptions to the OVERWATCH Action Queue for owner/status tracking.",
        "",
        "## Source Basis",
        "Source: QUERY_HISTORY. DDL/DCL detection is text-pattern based, so it is strong for investigation but should be validated against source control and change tickets.",
    ]
    return "\n".join(lines)


def _build_change_drift_sql(session, days: int, company: str) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["QUERY_TAG"],
    ))
    query_tag_expr = "query_tag" if "QUERY_TAG" in qh_cols else "NULL::VARCHAR"
    manual_drift_predicate = (
        "AND COALESCE(query_tag, '') NOT ILIKE '%terraform%'"
        if "QUERY_TAG" in qh_cols else ""
    )
    scope = _change_scope_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    base_where = f"""
        start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        {scope}
    """
    summary_sql = f"""
    WITH changes AS (
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            database_name,
            schema_name,
            start_time,
            {query_tag_expr} AS query_tag,
            query_text,
            CASE
                WHEN query_text ILIKE 'DROP%' THEN 'DESTRUCTIVE'
                WHEN query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%' THEN 'POLICY'
                WHEN query_text ILIKE '%OWNERSHIP%' THEN 'OWNER'
                WHEN query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%' THEN 'ACCESS'
                WHEN query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' THEN 'OBJECT'
                ELSE 'OTHER'
            END AS change_family
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {base_where}
          AND (
            query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%'
            OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
            OR query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%'
          )
    )
    SELECT
        '{company}' AS company,
        COUNT_IF(change_family IN ('OBJECT', 'DESTRUCTIVE')) AS object_changes,
        COUNT_IF(change_family IN ('ACCESS', 'OWNER')) AS access_changes,
        COUNT_IF(change_family = 'OWNER') AS owner_changes,
        COUNT_IF(change_family = 'POLICY') AS policy_changes,
        COUNT_IF(change_family = 'DESTRUCTIVE') AS destructive_changes,
        COUNT_IF(change_family <> 'OTHER' {manual_drift_predicate}) AS manual_drift,
        COUNT(DISTINCT user_name) AS actors,
        COUNT(DISTINCT database_name) AS affected_databases,
        COUNT_IF(database_name IS NULL) AS account_scope_changes
    FROM changes
    """
    exceptions_sql = f"""
    WITH changes AS (
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            database_name,
            schema_name,
            start_time,
            {query_tag_expr} AS query_tag,
            SUBSTR(query_text, 1, 1500) AS query_text,
            CASE
                WHEN query_text ILIKE 'DROP%' THEN 'Destructive DDL'
                WHEN query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%' THEN 'Policy or Tag Change'
                WHEN query_text ILIKE '%OWNERSHIP%' THEN 'Owner Change'
                WHEN query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%' THEN 'Grant or Role Change'
                WHEN query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' THEN 'Object Change'
                ELSE 'Other Change'
            END AS finding_type
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {base_where}
          AND (
            query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%'
            OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
            OR query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%'
          )
          {manual_drift_predicate}
    )
    SELECT
        finding_type,
        CASE
            WHEN finding_type IN ('Destructive DDL', 'Policy or Tag Change', 'Owner Change') THEN 'High'
            WHEN finding_type = 'Grant or Role Change' THEN 'Medium'
            ELSE 'Low'
        END AS severity,
        COALESCE(database_name || '.' || schema_name, database_name, query_id) AS entity,
        user_name,
        role_name,
        query_id,
        start_time AS last_seen,
        1 AS event_count,
        'QUERY_HISTORY query_id = ' || query_id AS proof_query,
        database_name,
        IFF(database_name IS NULL, FALSE, TRUE) AS database_context,
        {get_environment_case_expr("database_name")} AS environment,
        IFF(database_name IS NULL, 'Account/Role Context', 'Database Context') AS scope_confidence,
        IFF(database_name IS NULL, 'No database context; retained under environment scope', 'Database=' || database_name) AS scope_evidence,
        query_text
    FROM changes
    WHERE finding_type <> 'Other Change'
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        start_time DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def _build_mart_change_drift_sql(days: int, company: str) -> tuple[str, str]:
    """Build change/drift brief SQL from the OVERWATCH object-change fact."""
    table = mart_object_name("FACT_OBJECT_CHANGE")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND company = {sql_literal(company, 100)}"
    scope = _change_scope_clause(
        date_col="start_time",
        wh_col="",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    base_where = f"""
        start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        {company_filter}
        {scope}
    """
    summary_sql = f"""
    SELECT
        '{company}' AS company,
        COUNT_IF(change_category IN ('CREATE', 'ALTER', 'DROP')) AS object_changes,
        COUNT_IF(change_category IN ('GRANT', 'OWNER')) AS access_changes,
        COUNT_IF(change_category = 'OWNER') AS owner_changes,
        COUNT_IF(change_category = 'POLICY') AS policy_changes,
        COUNT_IF(change_category = 'DROP') AS destructive_changes,
        COUNT_IF(COALESCE(query_tag, '') NOT ILIKE '%terraform%') AS manual_drift,
        COUNT(DISTINCT user_name) AS actors,
        COUNT(DISTINCT database_name) AS affected_databases,
        COUNT_IF(database_name IS NULL) AS account_scope_changes
    FROM {table}
    WHERE {base_where}
    """
    exceptions_sql = f"""
    SELECT
        CASE
            WHEN change_category = 'DROP' THEN 'Destructive DDL'
            WHEN change_category = 'POLICY' THEN 'Policy or Tag Change'
            WHEN change_category = 'OWNER' THEN 'Owner Change'
            WHEN change_category = 'GRANT' THEN 'Grant or Role Change'
            WHEN change_category IN ('CREATE', 'ALTER') THEN 'Object Change'
            ELSE 'Other Change'
        END AS finding_type,
        CASE
            WHEN change_category IN ('DROP', 'POLICY', 'OWNER') THEN 'High'
            WHEN change_category = 'GRANT' THEN 'Medium'
            ELSE 'Low'
        END AS severity,
        COALESCE(database_name || '.' || schema_name, database_name, query_id) AS entity,
        user_name,
        role_name,
        query_id,
        start_time AS last_seen,
        1 AS event_count,
        'FACT_OBJECT_CHANGE query_id = ' || query_id AS proof_query,
        database_name,
        IFF(database_name IS NULL, FALSE, TRUE) AS database_context,
        {get_environment_case_expr("database_name")} AS environment,
        IFF(database_name IS NULL, 'Account/Role Context', 'Database Context') AS scope_confidence,
        IFF(database_name IS NULL, 'No database context; retained under environment scope', 'Database=' || database_name) AS scope_evidence,
        query_tag,
        SUBSTR(query_text, 1, 1500) AS query_text
    FROM {table}
    WHERE {base_where}
      AND change_category <> 'OTHER'
      AND COALESCE(query_tag, '') NOT ILIKE '%terraform%'
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        start_time DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def _queue_change_exceptions(session, exceptions: pd.DataFrame) -> None:
    if exceptions is None or exceptions.empty:
        st.info("No change/drift exceptions to queue.")
        return
    company = get_active_company()
    environment = get_active_environment()
    actions = []
    for _, row in exceptions.head(100).iterrows():
        actions.append(_change_action_payload(row, company=company, environment=environment))
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} change/drift exceptions to the action queue with approval and verification fields.")
    except Exception as e:
        st.error(f"Could not save change/drift exceptions: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _change_control_evidence_insert_sql(
    readiness: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
    snapshot_id: str = "",
) -> str:
    if readiness is None or readiness.empty:
        raise ValueError("Change-control evidence snapshot has no rows to save.")
    view = _enrich_change_control_evidence(readiness)
    fqn = change_control_evidence_fqn()
    env_value = str(environment or "").strip() or "ALL"
    snap = snapshot_id or make_action_id(
        "Change Control Evidence Snapshot",
        company,
        f"{env_value}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    selects = []
    for _, row in view.head(200).iterrows():
        row_environment = str(row.get("ENVIRONMENT") or _change_environment(row, env_value) or env_value)
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(row_environment, 100)} AS ENVIRONMENT, "
            f"{sql_literal(row.get('FINDING_TYPE', ''), 120)} AS FINDING_TYPE, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('ENTITY', ''), 500)} AS ENTITY, "
            f"{sql_literal(row.get('USER_NAME', ''), 300)} AS USER_NAME, "
            f"{sql_literal(row.get('ROLE_NAME', ''), 300)} AS ROLE_NAME, "
            f"{sql_literal(row.get('QUERY_ID', ''), 200)} AS QUERY_ID, "
            f"{sql_literal(row.get('QUERY_TAG', ''), 1000)} AS QUERY_TAG, "
            f"{sql_literal(row.get('LAST_SEEN', ''), 100)} AS LAST_SEEN, "
            f"{sql_literal(row.get('CHANGE_CONTROL_STATE', ''), 120)} AS CHANGE_CONTROL_STATE, "
            f"{sql_literal(row.get('CONTROL_GAP', ''), 1000)} AS CONTROL_GAP, "
            f"{sql_literal(row.get('CHANGE_TICKET_ID', ''), 200)} AS CHANGE_TICKET_ID, "
            f"{sql_literal(row.get('CHANGE_TICKET_STATE', ''), 120)} AS CHANGE_TICKET_STATE, "
            f"{sql_literal(row.get('IAC_RECONCILIATION_STATE', ''), 160)} AS IAC_RECONCILIATION_STATE, "
            f"{sql_literal(row.get('EXECUTION_AUDIT_STATE', ''), 160)} AS EXECUTION_AUDIT_STATE, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('APPROVER', ''), 200)} AS APPROVER, "
            f"{sql_literal(row.get('OWNER_APPROVAL_STATUS', ''), 40)} AS OWNER_APPROVAL_STATUS, "
            f"{sql_literal(row.get('APPROVAL_REQUIRED', ''), 20)} AS APPROVAL_REQUIRED, "
            f"{sql_literal(row.get('TICKET_REQUIRED', ''), 20)} AS TICKET_REQUIRED, "
            f"{sql_literal(row.get('BLAST_RADIUS_REQUIRED', ''), 20)} AS BLAST_RADIUS_REQUIRED, "
            f"{sql_literal(row.get('APPROVAL_ROUTE_READY', ''), 20)} AS APPROVAL_ROUTE_READY, "
            f"{sql_literal(row.get('CHANGE_EVIDENCE_READINESS', ''), 80)} AS CHANGE_EVIDENCE_READINESS, "
            f"{sql_literal(row.get('EVIDENCE_BLOCKERS', ''), 2000)} AS EVIDENCE_BLOCKERS, "
            f"{safe_int(row.get('REVIEW_SLA_HOURS', 168))}::NUMBER AS REVIEW_SLA_HOURS, "
            f"{sql_literal(row.get('NEXT_CONTROL_ACTION', ''), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{sql_literal(row.get('PROOF_REQUIRED', ''), 2000)} AS PROOF_REQUIRED, "
            f"{sql_literal(row.get('VERIFICATION_QUERY', ''), 8000)} AS VERIFICATION_QUERY, "
            f"{sql_literal(row.get('BLAST_RADIUS_QUERY', ''), 8000)} AS BLAST_RADIUS_QUERY, "
            f"{sql_literal(source, 500)} AS SOURCE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, FINDING_TYPE, SEVERITY,
    ENTITY, USER_NAME, ROLE_NAME, QUERY_ID, QUERY_TAG, LAST_SEEN,
    CHANGE_CONTROL_STATE, CONTROL_GAP, CHANGE_TICKET_ID, CHANGE_TICKET_STATE,
    IAC_RECONCILIATION_STATE, EXECUTION_AUDIT_STATE, OWNER, ESCALATION_TARGET,
    OWNER_SOURCE, APPROVER, OWNER_APPROVAL_STATUS, APPROVAL_REQUIRED,
    TICKET_REQUIRED, BLAST_RADIUS_REQUIRED, APPROVAL_ROUTE_READY,
    CHANGE_EVIDENCE_READINESS, EVIDENCE_BLOCKERS, REVIEW_SLA_HOURS,
    NEXT_CONTROL_ACTION, PROOF_REQUIRED, VERIFICATION_QUERY, BLAST_RADIUS_QUERY, SOURCE
)
{" UNION ALL ".join(selects)}""".strip()


def _change_control_evidence_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = change_control_evidence_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        where.append(f"ENVIRONMENT = {sql_literal(env_value, 100)}")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    FINDING_TYPE,
    SEVERITY,
    OWNER,
    ESCALATION_TARGET,
    COUNT(*) AS EVIDENCE_ROWS,
    COUNT_IF(CHANGE_TICKET_STATE ILIKE 'Missing%') AS MISSING_TICKET_ROWS,
    COUNT_IF(IAC_RECONCILIATION_STATE ILIKE '%required%' OR IAC_RECONCILIATION_STATE ILIKE '%Reconcile%') AS IAC_GAP_ROWS,
    COUNT_IF(EXECUTION_AUDIT_STATE ILIKE 'Missing%') AS MISSING_QUERY_ID_ROWS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(CHANGE_CONTROL_STATE, SNAPSHOT_TS) AS LAST_CONTROL_STATE,
    MAX_BY(CONTROL_GAP, SNAPSHOT_TS) AS LAST_CONTROL_GAP
FROM {fqn}
WHERE {where_clause}
GROUP BY FINDING_TYPE, SEVERITY, OWNER, ESCALATION_TARGET
ORDER BY
    MISSING_TICKET_ROWS DESC,
    IAC_GAP_ROWS DESC,
    MISSING_QUERY_ID_ROWS DESC,
    LAST_SNAPSHOT_TS DESC
LIMIT 100""".strip()


def _change_ticket_sql_expr(query_tag_col: str = "QUERY_TAG", query_text_col: str = "QUERY_TEXT") -> str:
    return (
        "UPPER(COALESCE(REGEXP_SUBSTR("
        f"COALESCE({query_tag_col}, '') || ' ' || COALESCE({query_text_col}, ''), "
        "'(CHG|CHANGE|INC|REQ|RFC|JIRA)[-_]?[0-9]+|[A-Z][A-Z0-9]+-[0-9]+', 1, 1, 'i'"
        "), ''))"
    )


def _change_object_where(days: int, company: str) -> list[str]:
    lookback = max(1, int(days or 14))
    object_where = [
        f"START_TIME >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())",
        "CHANGE_CATEGORY <> 'OTHER'",
    ]
    if str(company or "").upper() != "ALL":
        object_where.append(f"COMPANY = {sql_literal(company, 100)}")
    object_scope = _change_scope_clause(
        date_col="start_time",
        wh_col="",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    if object_scope:
        object_where.append(_bare_sql_predicate(object_scope))
    return object_where


def _change_legacy_evidence_where(days: int, company: str, environment: str = "ALL") -> list[str]:
    lookback = max(1, int(days or 14))
    evidence_where = [f"SNAPSHOT_TS >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        evidence_where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        evidence_where.append(_bare_sql_predicate(env_clause))
    return evidence_where


def _change_feed_scope_predicate(
    event_expr: str,
    days: int,
    company: str,
    environment: str = "ALL",
) -> str:
    lookback = max(1, int(days or 14))
    parts = [f"{event_expr} >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        parts.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        parts.append(_bare_sql_predicate(env_clause))
    return " AND ".join(parts)


def _change_split_feed_health_sql(days: int, company: str, environment: str = "ALL") -> str:
    source_table = change_source_control_fqn()
    ticket_table = change_itsm_ticket_fqn()
    source_event = "COALESCE(APPLY_TS, SNAPSHOT_TS)"
    ticket_event = "COALESCE(UPDATED_AT, SNAPSHOT_TS)"
    source_scope = _change_feed_scope_predicate(source_event, days, company, environment)
    ticket_scope = _change_feed_scope_predicate(ticket_event, days, company, environment)
    source_name = CHANGE_SOURCE_CONTROL_TABLE.replace("'", "''")
    ticket_name = CHANGE_ITSM_TICKET_TABLE.replace("'", "''")
    return f"""
WITH source_stats AS (
    SELECT
        'Terraform/Flyway/Git evidence' AS FEED,
        '{source_name}' AS TABLE_NAME,
        COUNT(*) AS "ROWS",
        COALESCE(COUNT_IF({source_scope}), 0) AS ACTIVE_SCOPE_ROWS,
        MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
        MAX({source_event}) AS LAST_EVENT_TS,
        COALESCE(COUNT_IF(CHANGE_TICKET_ID IS NOT NULL AND TRIM(CHANGE_TICKET_ID) <> ''), 0) AS TICKET_KEY_ROWS,
        COALESCE(COUNT_IF(COMMIT_SHA IS NOT NULL AND TRIM(COMMIT_SHA) <> ''), 0) AS LINK_KEY_ROWS,
        COALESCE(COUNT_IF(EVIDENCE_URL IS NOT NULL AND TRIM(EVIDENCE_URL) <> ''), 0) AS EVIDENCE_URL_ROWS
    FROM {source_table}
),
ticket_stats AS (
    SELECT
        'Jira tickets' AS FEED,
        '{ticket_name}' AS TABLE_NAME,
        COUNT(*) AS "ROWS",
        COALESCE(COUNT_IF({ticket_scope}), 0) AS ACTIVE_SCOPE_ROWS,
        MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
        MAX({ticket_event}) AS LAST_EVENT_TS,
        COALESCE(COUNT_IF(TICKET_ID IS NOT NULL AND TRIM(TICKET_ID) <> ''), 0) AS TICKET_KEY_ROWS,
        COALESCE(COUNT_IF(LINKED_COMMIT_SHA IS NOT NULL AND TRIM(LINKED_COMMIT_SHA) <> ''), 0) AS LINK_KEY_ROWS,
        COALESCE(COUNT_IF(TICKET_URL IS NOT NULL AND TRIM(TICKET_URL) <> ''), 0) AS EVIDENCE_URL_ROWS
    FROM {ticket_table}
),
feed_stats AS (
    SELECT * FROM source_stats
    UNION ALL
    SELECT * FROM ticket_stats
)
SELECT
    FEED,
    TABLE_NAME,
    "ROWS",
    ACTIVE_SCOPE_ROWS,
    LAST_SNAPSHOT_TS,
    LAST_EVENT_TS,
    TICKET_KEY_ROWS,
    LINK_KEY_ROWS,
    EVIDENCE_URL_ROWS,
    CASE
        WHEN "ROWS" = 0 THEN 'Ready - Empty'
        WHEN ACTIVE_SCOPE_ROWS = 0 THEN 'No Active Scope Rows'
        WHEN LAST_EVENT_TS < DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP()) THEN 'Stale'
        ELSE 'Flowing'
    END AS FEED_STATE,
    CASE
        WHEN "ROWS" = 0 THEN 'Start the CI/Jira export feed into this table.'
        WHEN ACTIVE_SCOPE_ROWS = 0 THEN 'Confirm company/environment mapping and selected lookback window.'
        WHEN LAST_EVENT_TS < DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP()) THEN 'Check the upstream export schedule and refresh cadence.'
        WHEN TICKET_KEY_ROWS = 0 THEN 'Add Jira/change ticket keys to the feed rows.'
        WHEN LINK_KEY_ROWS = 0 THEN 'Add commit/object link keys so OVERWATCH can join evidence to Snowflake changes.'
        ELSE 'Feed is queryable for the active scope.'
    END AS NEXT_ACTION
FROM feed_stats
ORDER BY
    CASE FEED_STATE
        WHEN 'Ready - Empty' THEN 0
        WHEN 'Stale' THEN 1
        WHEN 'No Active Scope Rows' THEN 2
        ELSE 8
    END,
    FEED
""".strip()


def _change_legacy_feed_health_sql(days: int, company: str, environment: str = "ALL") -> str:
    evidence_table = change_control_evidence_fqn()
    evidence_scope = " AND ".join(_change_legacy_evidence_where(days, company, environment))
    return f"""
SELECT
    'Legacy change-control evidence' AS FEED,
    '{CHANGE_CONTROL_EVIDENCE_TABLE}' AS TABLE_NAME,
    COUNT(*) AS "ROWS",
    COALESCE(COUNT_IF({evidence_scope}), 0) AS ACTIVE_SCOPE_ROWS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX(SNAPSHOT_TS) AS LAST_EVENT_TS,
    COALESCE(COUNT_IF(CHANGE_TICKET_ID IS NOT NULL AND TRIM(CHANGE_TICKET_ID) <> ''), 0) AS TICKET_KEY_ROWS,
    COALESCE(COUNT_IF(IAC_RECONCILIATION_STATE IS NOT NULL AND TRIM(IAC_RECONCILIATION_STATE) <> ''), 0) AS LINK_KEY_ROWS,
    0 AS EVIDENCE_URL_ROWS,
    CASE
        WHEN COUNT(*) = 0 THEN 'Ready - Empty'
        WHEN COUNT_IF({evidence_scope}) = 0 THEN 'No Active Scope Rows'
        ELSE 'Legacy Flowing'
    END AS FEED_STATE,
    CASE
        WHEN COUNT(*) = 0 THEN 'Deploy and feed the split Terraform/Jira evidence tables for full detail.'
        WHEN COUNT_IF({evidence_scope}) = 0 THEN 'Confirm company/environment mapping and selected lookback window.'
        ELSE 'Legacy evidence is queryable; split tables add repository, commit, PR, and ticket-window detail.'
    END AS NEXT_ACTION
FROM {evidence_table}
""".strip()


def _change_external_integration_ctes(days: int, company: str, environment: str = "ALL") -> str:
    fact_table = mart_object_name("FACT_OBJECT_CHANGE")
    source_table = change_source_control_fqn()
    ticket_table = change_itsm_ticket_fqn()
    lookback = max(1, int(days or 14))

    object_where = _change_object_where(lookback, company)

    source_where = [f"COALESCE(APPLY_TS, SNAPSHOT_TS) >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())"]
    ticket_where = [f"COALESCE(UPDATED_AT, SNAPSHOT_TS) >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        source_where.append(f"COMPANY = {sql_literal(company, 100)}")
        ticket_where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        source_where.append(_bare_sql_predicate(env_clause))
        ticket_where.append(_bare_sql_predicate(env_clause))

    ticket_expr = _change_ticket_sql_expr("QUERY_TAG", "QUERY_TEXT")
    source_match = """
            (oc.CHANGE_TICKET_ID <> '' AND oc.CHANGE_TICKET_ID = sc.CHANGE_TICKET_ID)
            OR (sc.COMMIT_SHA <> '' AND POSITION(sc.COMMIT_SHA IN oc.QUERY_TAG_UPPER) > 0)
            OR (sc.OBJECT_MATCH_KEY <> '' AND POSITION(sc.OBJECT_MATCH_KEY IN oc.QUERY_TEXT_UPPER) > 0)
            OR (
                sc.OBJECT_DATABASE <> ''
                AND sc.OBJECT_DATABASE = oc.DATABASE_NAME_UPPER
                AND (sc.OBJECT_SCHEMA = '' OR sc.OBJECT_SCHEMA = oc.SCHEMA_NAME_UPPER)
            )
    """.strip()
    return f"""
WITH object_changes AS (
    SELECT
        START_TIME,
        COMPANY,
        COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
        QUERY_ID,
        USER_NAME,
        ROLE_NAME,
        DATABASE_NAME,
        SCHEMA_NAME,
        UPPER(COALESCE(DATABASE_NAME, '')) AS DATABASE_NAME_UPPER,
        UPPER(COALESCE(SCHEMA_NAME, '')) AS SCHEMA_NAME_UPPER,
        CHANGE_CATEGORY,
        QUERY_TYPE,
        QUERY_TAG,
        QUERY_TEXT,
        UPPER(COALESCE(QUERY_TAG, '')) AS QUERY_TAG_UPPER,
        UPPER(COALESCE(QUERY_TEXT, '')) AS QUERY_TEXT_UPPER,
        {ticket_expr} AS CHANGE_TICKET_ID,
        COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME, DATABASE_NAME, QUERY_ID) AS ENTITY
    FROM {fact_table}
    WHERE {" AND ".join(object_where)}
),
source_control AS (
    SELECT
        COALESCE(APPLY_TS, SNAPSHOT_TS) AS EVENT_TS,
        COMPANY,
        COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
        CASE
            WHEN UPPER(COALESCE(SOURCE_SYSTEM, '')) LIKE '%FLYWAY%' THEN 'Flyway'
            WHEN UPPER(COALESCE(SOURCE_SYSTEM, '')) LIKE '%TERRAFORM%' THEN 'Terraform/Git'
            WHEN UPPER(COALESCE(SOURCE_SYSTEM, '')) LIKE '%GIT%' THEN 'Terraform/Git'
            ELSE COALESCE(SOURCE_SYSTEM, 'Terraform/Flyway/Git')
        END AS SOURCE_SYSTEM,
        REPOSITORY,
        BRANCH_NAME,
        UPPER(COALESCE(COMMIT_SHA, '')) AS COMMIT_SHA,
        PR_ID,
        PR_URL,
        UPPER(COALESCE(CHANGE_TICKET_ID, '')) AS CHANGE_TICKET_ID,
        UPPER(COALESCE(OBJECT_DATABASE, '')) AS OBJECT_DATABASE,
        UPPER(COALESCE(OBJECT_SCHEMA, '')) AS OBJECT_SCHEMA,
        UPPER(COALESCE(OBJECT_NAME, '')) AS OBJECT_NAME,
        OBJECT_TYPE,
        UPPER(COALESCE(
            OBJECT_FQN,
            OBJECT_DATABASE || '.' || OBJECT_SCHEMA || '.' || OBJECT_NAME,
            OBJECT_DATABASE || '.' || OBJECT_SCHEMA,
            OBJECT_DATABASE,
            ''
        )) AS OBJECT_MATCH_KEY,
        TERRAFORM_ADDRESS,
        COALESCE(PLANNED_ACTION, '') AS PLANNED_ACTION,
        COALESCE(APPLY_STATUS, '') AS APPLY_STATUS,
        DEPLOYED_BY,
        EVIDENCE_URL,
        NOTES
    FROM {source_table}
    WHERE {" AND ".join(source_where)}
),
tickets AS (
    SELECT
        COALESCE(UPDATED_AT, SNAPSHOT_TS) AS EVENT_TS,
        COMPANY,
        COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
        UPPER(COALESCE(TICKET_ID, '')) AS TICKET_ID,
        TICKET_URL,
        SUMMARY,
        COALESCE(STATUS, '') AS STATUS,
        ASSIGNEE,
        REQUESTER,
        APPROVER,
        COALESCE(APPROVAL_STATUS, '') AS APPROVAL_STATUS,
        RISK,
        CHANGE_WINDOW_START,
        CHANGE_WINDOW_END,
        LINKED_REPOSITORY,
        UPPER(COALESCE(LINKED_COMMIT_SHA, '')) AS LINKED_COMMIT_SHA,
        LINKED_PR_URL,
        NOTES
    FROM {ticket_table}
    WHERE {" AND ".join(ticket_where)}
),
object_flags AS (
    SELECT
        oc.*,
        (
            QUERY_TAG_UPPER ILIKE '%TERRAFORM%'
            OR QUERY_TAG_UPPER ILIKE '%FLYWAY%'
            OR QUERY_TAG_UPPER ILIKE '%IAC%'
            OR QUERY_TAG_UPPER ILIKE '%DEPLOY%'
            OR QUERY_TAG_UPPER ILIKE '%RELEASE%'
        ) AS HAS_DEPLOYMENT_TAG,
        EXISTS (
            SELECT 1
            FROM source_control sc
            WHERE {source_match}
        ) AS HAS_SOURCE_CONTROL,
        EXISTS (
            SELECT 1
            FROM tickets t
            WHERE oc.CHANGE_TICKET_ID <> '' AND t.TICKET_ID = oc.CHANGE_TICKET_ID
        ) AS HAS_ITSM_TICKET
    FROM object_changes oc
),
source_flags AS (
    SELECT
        sc.*,
        EXISTS (
            SELECT 1
            FROM tickets t
            WHERE sc.CHANGE_TICKET_ID <> '' AND t.TICKET_ID = sc.CHANGE_TICKET_ID
        ) AS HAS_ITSM_TICKET,
        EXISTS (
            SELECT 1
            FROM object_changes oc
            WHERE {source_match}
        ) AS HAS_OBSERVED_CHANGE
    FROM source_control sc
),
ticket_flags AS (
    SELECT
        t.*,
        (
            UPPER(APPROVAL_STATUS) IN ('APPROVED', 'AUTHORIZED', 'APPROVE')
            OR UPPER(STATUS) IN ('APPROVED', 'IMPLEMENTING', 'IN PROGRESS', 'DONE', 'CLOSED', 'RESOLVED')
        ) AS IS_APPROVED_OR_ACTIVE,
        EXISTS (
            SELECT 1
            FROM source_control sc
            WHERE t.TICKET_ID <> '' AND sc.CHANGE_TICKET_ID = t.TICKET_ID
        ) AS HAS_SOURCE_CONTROL,
        EXISTS (
            SELECT 1
            FROM object_changes oc
            WHERE t.TICKET_ID <> '' AND oc.CHANGE_TICKET_ID = t.TICKET_ID
        ) AS HAS_OBSERVED_CHANGE
    FROM tickets t
)
""".strip()


def _change_legacy_integration_ctes(days: int, company: str, environment: str = "ALL") -> str:
    fact_table = mart_object_name("FACT_OBJECT_CHANGE")
    evidence_table = change_control_evidence_fqn()
    object_where = _change_object_where(days, company)
    evidence_where = _change_legacy_evidence_where(days, company, environment)
    ticket_expr = _change_ticket_sql_expr("QUERY_TAG", "QUERY_TEXT")
    return f"""
WITH object_changes AS (
    SELECT
        START_TIME,
        COMPANY,
        COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
        QUERY_ID,
        USER_NAME,
        ROLE_NAME,
        DATABASE_NAME,
        SCHEMA_NAME,
        CHANGE_CATEGORY,
        QUERY_TYPE,
        QUERY_TAG,
        QUERY_TEXT,
        UPPER(COALESCE(QUERY_TAG, '')) AS QUERY_TAG_UPPER,
        UPPER(COALESCE(QUERY_TEXT, '')) AS QUERY_TEXT_UPPER,
        {ticket_expr} AS CHANGE_TICKET_ID,
        COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME, DATABASE_NAME, QUERY_ID) AS ENTITY,
        (
            UPPER(COALESCE(QUERY_TAG, '')) ILIKE '%TERRAFORM%'
            OR UPPER(COALESCE(QUERY_TAG, '')) ILIKE '%IAC%'
            OR UPPER(COALESCE(QUERY_TAG, '')) ILIKE '%DEPLOY%'
            OR UPPER(COALESCE(QUERY_TAG, '')) ILIKE '%RELEASE%'
        ) AS HAS_DEPLOYMENT_TAG
    FROM {fact_table}
    WHERE {" AND ".join(object_where)}
),
legacy_evidence AS (
    SELECT
        SNAPSHOT_TS,
        COMPANY,
        COALESCE(ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
        FINDING_TYPE,
        SEVERITY,
        ENTITY,
        USER_NAME,
        ROLE_NAME,
        QUERY_ID,
        QUERY_TAG,
        CHANGE_CONTROL_STATE,
        CONTROL_GAP,
        UPPER(COALESCE(CHANGE_TICKET_ID, '')) AS CHANGE_TICKET_ID,
        CHANGE_TICKET_STATE,
        IAC_RECONCILIATION_STATE,
        EXECUTION_AUDIT_STATE,
        OWNER,
        ESCALATION_TARGET,
        APPROVER,
        OWNER_APPROVAL_STATUS,
        CHANGE_EVIDENCE_READINESS,
        EVIDENCE_BLOCKERS,
        NEXT_CONTROL_ACTION,
        SOURCE
    FROM {evidence_table}
    WHERE {" AND ".join(evidence_where)}
),
legacy_source AS (
    SELECT *
    FROM legacy_evidence
    WHERE
        UPPER(COALESCE(SOURCE, '')) ILIKE '%TERRAFORM%'
        OR UPPER(COALESCE(SOURCE, '')) ILIKE '%GIT%'
        OR UPPER(COALESCE(SOURCE, '')) ILIKE '%SOURCE%'
        OR NULLIF(TRIM(COALESCE(IAC_RECONCILIATION_STATE, '')), '') IS NOT NULL
),
legacy_tickets AS (
    SELECT *
    FROM legacy_evidence
    WHERE
        CHANGE_TICKET_ID <> ''
        OR NULLIF(TRIM(COALESCE(CHANGE_TICKET_STATE, '')), '') IS NOT NULL
        OR UPPER(COALESCE(SOURCE, '')) ILIKE '%JIRA%'
        OR UPPER(COALESCE(SOURCE, '')) ILIKE '%ITSM%'
)
""".strip()


def _change_legacy_integration_status_sql(days: int, company: str, environment: str = "ALL") -> str:
    base = _change_legacy_integration_ctes(days, company, environment)
    return f"""
{base},
status_rows AS (
    SELECT
        'Snowflake object changes' AS SURFACE,
        CASE
            WHEN COUNT(*) = 0 THEN 'No Rows'
            WHEN COUNT_IF(CHANGE_TICKET_ID = '' AND NOT HAS_DEPLOYMENT_TAG) > 0 THEN 'Drift Gaps'
            ELSE 'Covered'
        END AS STATE,
        COUNT(*) AS "ROWS",
        COUNT_IF(HAS_DEPLOYMENT_TAG) AS SOURCE_MATCH_ROWS,
        COUNT_IF(CHANGE_TICKET_ID <> '') AS TICKET_MATCH_ROWS,
        COUNT_IF(CHANGE_TICKET_ID = '' AND NOT HAS_DEPLOYMENT_TAG) AS GAP_ROWS,
        MAX(START_TIME) AS LAST_ACTIVITY_TS,
        CASE
            WHEN COUNT_IF(CHANGE_TICKET_ID = '' AND NOT HAS_DEPLOYMENT_TAG) > 0
                THEN 'Deploy split Terraform/Jira evidence tables or attach ticket/source-control evidence in the legacy table.'
            ELSE 'Observed Snowflake changes have a deployment tag or ticket reference.'
        END AS NEXT_ACTION
    FROM object_changes
    UNION ALL
    SELECT
        'Terraform/Flyway/Git evidence' AS SURFACE,
        CASE
            WHEN COUNT(*) = 0 THEN 'No Rows'
            WHEN COUNT_IF(
                UPPER(COALESCE(IAC_RECONCILIATION_STATE, '')) IN ('', 'GAP', 'MISSING', 'UNMATCHED', 'UNKNOWN')
                OR CHANGE_TICKET_ID = ''
            ) > 0 THEN 'Evidence Gaps'
            ELSE 'Covered'
        END AS STATE,
        COUNT(*) AS "ROWS",
        COUNT_IF(UPPER(COALESCE(IAC_RECONCILIATION_STATE, '')) NOT IN ('', 'GAP', 'MISSING', 'UNMATCHED', 'UNKNOWN')) AS SOURCE_MATCH_ROWS,
        COUNT_IF(CHANGE_TICKET_ID <> '') AS TICKET_MATCH_ROWS,
        COUNT_IF(
            UPPER(COALESCE(IAC_RECONCILIATION_STATE, '')) IN ('', 'GAP', 'MISSING', 'UNMATCHED', 'UNKNOWN')
            OR CHANGE_TICKET_ID = ''
        ) AS GAP_ROWS,
        MAX(SNAPSHOT_TS) AS LAST_ACTIVITY_TS,
        'Legacy evidence is in use. Deploy the split source-control table for repository, commit, PR, and Terraform address detail.' AS NEXT_ACTION
    FROM legacy_source
    UNION ALL
    SELECT
        'Jira tickets' AS SURFACE,
        CASE
            WHEN COUNT(*) = 0 THEN 'No Rows'
            WHEN COUNT_IF(
                UPPER(COALESCE(OWNER_APPROVAL_STATUS, '')) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')
                OR UPPER(COALESCE(IAC_RECONCILIATION_STATE, '')) IN ('', 'GAP', 'MISSING', 'UNMATCHED', 'UNKNOWN')
            ) > 0 THEN 'Approval Gaps'
            ELSE 'Covered'
        END AS STATE,
        COUNT(*) AS "ROWS",
        COUNT_IF(UPPER(COALESCE(IAC_RECONCILIATION_STATE, '')) NOT IN ('', 'GAP', 'MISSING', 'UNMATCHED', 'UNKNOWN')) AS SOURCE_MATCH_ROWS,
        COUNT_IF(CHANGE_TICKET_ID <> '') AS TICKET_MATCH_ROWS,
        COUNT_IF(
            UPPER(COALESCE(OWNER_APPROVAL_STATUS, '')) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')
            OR UPPER(COALESCE(IAC_RECONCILIATION_STATE, '')) IN ('', 'GAP', 'MISSING', 'UNMATCHED', 'UNKNOWN')
        ) AS GAP_ROWS,
        MAX(SNAPSHOT_TS) AS LAST_ACTIVITY_TS,
        'Legacy evidence is in use. Deploy the split Jira/ITSM table for ticket URL, status, assignee, approval, and window detail.' AS NEXT_ACTION
    FROM legacy_tickets
)
SELECT
    SURFACE,
    STATE,
    CASE STATE
        WHEN 'Drift Gaps' THEN 0
        WHEN 'Evidence Gaps' THEN 1
        WHEN 'Approval Gaps' THEN 1
        WHEN 'Covered' THEN 8
        WHEN 'No Rows' THEN 9
        ELSE 5
    END AS STATE_RANK,
    "ROWS",
    SOURCE_MATCH_ROWS,
    TICKET_MATCH_ROWS,
    GAP_ROWS,
    LAST_ACTIVITY_TS,
    NEXT_ACTION
FROM status_rows
ORDER BY STATE_RANK, GAP_ROWS DESC, SURFACE""".strip()


def _change_integration_status_sql(days: int, company: str, environment: str = "ALL") -> str:
    base = _change_external_integration_ctes(days, company, environment)
    return f"""
{base},
status_rows AS (
    SELECT
        'Snowflake object changes' AS SURFACE,
        CASE
            WHEN COUNT(*) = 0 THEN 'No Rows'
            WHEN COUNT_IF(NOT HAS_SOURCE_CONTROL AND NOT HAS_ITSM_TICKET AND NOT HAS_DEPLOYMENT_TAG) > 0 THEN 'Drift Gaps'
            ELSE 'Covered'
        END AS STATE,
        COUNT(*) AS "ROWS",
        COUNT_IF(HAS_SOURCE_CONTROL) AS SOURCE_MATCH_ROWS,
        COUNT_IF(HAS_ITSM_TICKET) AS TICKET_MATCH_ROWS,
        COUNT_IF(NOT HAS_SOURCE_CONTROL AND NOT HAS_ITSM_TICKET AND NOT HAS_DEPLOYMENT_TAG) AS GAP_ROWS,
        MAX(START_TIME) AS LAST_ACTIVITY_TS,
        CASE
            WHEN COUNT_IF(NOT HAS_SOURCE_CONTROL AND NOT HAS_ITSM_TICKET AND NOT HAS_DEPLOYMENT_TAG) > 0
                THEN 'Attach approved ticket or source-control evidence, codify the drift, or revert through approved deployment.'
            ELSE 'Retain observed Snowflake change history with ticket/source-control evidence.'
        END AS NEXT_ACTION
    FROM object_flags
    UNION ALL
    SELECT
        'Terraform/Flyway/Git evidence' AS SURFACE,
        CASE
            WHEN COUNT(*) = 0 THEN 'No Rows'
            WHEN COUNT_IF(NOT HAS_ITSM_TICKET OR NOT HAS_OBSERVED_CHANGE) > 0 THEN 'Evidence Gaps'
            ELSE 'Covered'
        END AS STATE,
        COUNT(*) AS "ROWS",
        COUNT_IF(HAS_OBSERVED_CHANGE) AS SOURCE_MATCH_ROWS,
        COUNT_IF(HAS_ITSM_TICKET) AS TICKET_MATCH_ROWS,
        COUNT_IF(NOT HAS_ITSM_TICKET OR NOT HAS_OBSERVED_CHANGE) AS GAP_ROWS,
        MAX(EVENT_TS) AS LAST_ACTIVITY_TS,
        CASE
            WHEN COUNT_IF(NOT HAS_ITSM_TICKET) > 0 THEN 'Link Terraform/Flyway/Git deploy evidence to Jira ticket keys.'
            WHEN COUNT_IF(NOT HAS_OBSERVED_CHANGE) > 0 THEN 'Confirm applied source-control changes are visible in Snowflake object-change history.'
            ELSE 'Terraform/Flyway/Git evidence is linked to observed Snowflake or Jira evidence.'
        END AS NEXT_ACTION
    FROM source_flags
    UNION ALL
    SELECT
        'Jira tickets' AS SURFACE,
        CASE
            WHEN COUNT(*) = 0 THEN 'No Rows'
            WHEN COUNT_IF(IS_APPROVED_OR_ACTIVE AND NOT HAS_SOURCE_CONTROL AND NOT HAS_OBSERVED_CHANGE) > 0 THEN 'Approval Gaps'
            ELSE 'Covered'
        END AS STATE,
        COUNT(*) AS "ROWS",
        COUNT_IF(HAS_SOURCE_CONTROL) AS SOURCE_MATCH_ROWS,
        COUNT_IF(HAS_OBSERVED_CHANGE) AS TICKET_MATCH_ROWS,
        COUNT_IF(IS_APPROVED_OR_ACTIVE AND NOT HAS_SOURCE_CONTROL AND NOT HAS_OBSERVED_CHANGE) AS GAP_ROWS,
        MAX(EVENT_TS) AS LAST_ACTIVITY_TS,
        CASE
            WHEN COUNT_IF(IS_APPROVED_OR_ACTIVE AND NOT HAS_SOURCE_CONTROL AND NOT HAS_OBSERVED_CHANGE) > 0
                THEN 'Link approved Jira changes to Terraform/Flyway/Git evidence or observed Snowflake change rows.'
            ELSE 'Jira ticket evidence is linked to deployment or Snowflake activity.'
        END AS NEXT_ACTION
    FROM ticket_flags
)
SELECT
    SURFACE,
    STATE,
    CASE STATE
        WHEN 'Drift Gaps' THEN 0
        WHEN 'Evidence Gaps' THEN 1
        WHEN 'Approval Gaps' THEN 1
        WHEN 'Covered' THEN 8
        WHEN 'No Rows' THEN 9
        ELSE 5
    END AS STATE_RANK,
    "ROWS",
    SOURCE_MATCH_ROWS,
    TICKET_MATCH_ROWS,
    GAP_ROWS,
    LAST_ACTIVITY_TS,
    NEXT_ACTION
FROM status_rows
ORDER BY STATE_RANK, GAP_ROWS DESC, SURFACE""".strip()


def _change_unmatched_evidence_sql(days: int, company: str, environment: str = "ALL") -> str:
    base = _change_external_integration_ctes(days, company, environment)
    return f"""
{base},
unmatched_rows AS (
    SELECT
        'Snowflake' AS EVIDENCE_SOURCE,
        'Snowflake change missing external evidence' AS GAP_TYPE,
        IFF(CHANGE_CATEGORY IN ('DROP', 'POLICY', 'OWNER'), 'High', IFF(CHANGE_CATEGORY = 'GRANT', 'Medium', 'Low')) AS SEVERITY,
        ENTITY,
        USER_NAME AS ACTOR,
        CHANGE_TICKET_ID AS TICKET_ID,
        NULL::VARCHAR AS REPOSITORY,
        NULL::VARCHAR AS COMMIT_SHA,
        NULL::VARCHAR AS PR_URL,
        QUERY_ID,
        START_TIME AS EVENT_TS,
        QUERY_TAG,
        'Attach Jira approval/source-control evidence or classify as unauthorized drift.' AS NEXT_ACTION
    FROM object_flags
    WHERE NOT HAS_SOURCE_CONTROL AND NOT HAS_ITSM_TICKET AND NOT HAS_DEPLOYMENT_TAG
    UNION ALL
    SELECT
        SOURCE_SYSTEM AS EVIDENCE_SOURCE,
        CASE
            WHEN NOT HAS_ITSM_TICKET THEN SOURCE_SYSTEM || ' deploy missing Jira ticket'
            ELSE SOURCE_SYSTEM || ' deploy not observed in Snowflake change history'
        END AS GAP_TYPE,
        IFF(UPPER(PLANNED_ACTION) IN ('DELETE', 'DESTROY', 'DROP'), 'High', 'Medium') AS SEVERITY,
        COALESCE(NULLIF(OBJECT_MATCH_KEY, ''), TERRAFORM_ADDRESS, REPOSITORY, 'Source-control change') AS ENTITY,
        DEPLOYED_BY AS ACTOR,
        CHANGE_TICKET_ID AS TICKET_ID,
        REPOSITORY,
        COMMIT_SHA,
        PR_URL,
        NULL::VARCHAR AS QUERY_ID,
        EVENT_TS,
        NULL::VARCHAR AS QUERY_TAG,
        IFF(
            NOT HAS_ITSM_TICKET,
            'Add Jira ticket key to the Terraform/Flyway/Git evidence row and deployment query tag.',
            'Confirm query tag/object mapping or investigate why Snowflake did not record the applied change.'
        ) AS NEXT_ACTION
    FROM source_flags
    WHERE NOT HAS_ITSM_TICKET OR NOT HAS_OBSERVED_CHANGE
    UNION ALL
    SELECT
        'Jira' AS EVIDENCE_SOURCE,
        'Approved Jira change missing deploy evidence' AS GAP_TYPE,
        IFF(UPPER(RISK) IN ('HIGH', 'CRITICAL'), 'High', 'Medium') AS SEVERITY,
        COALESCE(SUMMARY, TICKET_ID, 'Jira change') AS ENTITY,
        COALESCE(ASSIGNEE, REQUESTER) AS ACTOR,
        TICKET_ID,
        LINKED_REPOSITORY AS REPOSITORY,
        LINKED_COMMIT_SHA AS COMMIT_SHA,
        LINKED_PR_URL AS PR_URL,
        NULL::VARCHAR AS QUERY_ID,
        EVENT_TS,
        NULL::VARCHAR AS QUERY_TAG,
        'Link the approved Jira change to Terraform/Flyway/Git evidence or observed Snowflake query history.' AS NEXT_ACTION
    FROM ticket_flags
    WHERE IS_APPROVED_OR_ACTIVE AND NOT HAS_SOURCE_CONTROL AND NOT HAS_OBSERVED_CHANGE
)
SELECT *
FROM unmatched_rows
ORDER BY
    CASE SEVERITY WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,
    EVENT_TS DESC
LIMIT 100""".strip()


def _change_legacy_unmatched_evidence_sql(days: int, company: str, environment: str = "ALL") -> str:
    base = _change_legacy_integration_ctes(days, company, environment)
    return f"""
{base},
unmatched_rows AS (
    SELECT
        'Snowflake' AS EVIDENCE_SOURCE,
        'Snowflake change missing external evidence' AS GAP_TYPE,
        IFF(CHANGE_CATEGORY IN ('DROP', 'POLICY', 'OWNER'), 'High', IFF(CHANGE_CATEGORY = 'GRANT', 'Medium', 'Low')) AS SEVERITY,
        ENTITY,
        USER_NAME AS ACTOR,
        CHANGE_TICKET_ID AS TICKET_ID,
        NULL::VARCHAR AS REPOSITORY,
        NULL::VARCHAR AS COMMIT_SHA,
        NULL::VARCHAR AS PR_URL,
        QUERY_ID,
        START_TIME AS EVENT_TS,
        QUERY_TAG,
        'Deploy split evidence tables or attach ticket/source-control evidence for this observed Snowflake change.' AS NEXT_ACTION
    FROM object_changes
    WHERE CHANGE_TICKET_ID = '' AND NOT HAS_DEPLOYMENT_TAG
    UNION ALL
    SELECT
        'Terraform/Git' AS EVIDENCE_SOURCE,
        'Terraform/Git legacy evidence missing split-table detail' AS GAP_TYPE,
        IFF(UPPER(COALESCE(SEVERITY, '')) IN ('HIGH', 'CRITICAL'), 'High', 'Medium') AS SEVERITY,
        COALESCE(ENTITY, QUERY_ID, 'Legacy source-control evidence') AS ENTITY,
        COALESCE(USER_NAME, OWNER) AS ACTOR,
        CHANGE_TICKET_ID AS TICKET_ID,
        NULL::VARCHAR AS REPOSITORY,
        NULL::VARCHAR AS COMMIT_SHA,
        NULL::VARCHAR AS PR_URL,
        QUERY_ID,
        SNAPSHOT_TS AS EVENT_TS,
        QUERY_TAG,
        COALESCE(NULLIF(NEXT_CONTROL_ACTION, ''), 'Deploy the split source-control evidence table and map repository/commit metadata.') AS NEXT_ACTION
    FROM legacy_source
    WHERE
        CHANGE_TICKET_ID = ''
        OR UPPER(COALESCE(IAC_RECONCILIATION_STATE, '')) IN ('', 'GAP', 'MISSING', 'UNMATCHED', 'UNKNOWN')
    UNION ALL
    SELECT
        'Jira' AS EVIDENCE_SOURCE,
        'Jira legacy evidence missing split-table detail' AS GAP_TYPE,
        IFF(UPPER(COALESCE(SEVERITY, '')) IN ('HIGH', 'CRITICAL'), 'High', 'Medium') AS SEVERITY,
        COALESCE(ENTITY, CHANGE_TICKET_ID, 'Legacy Jira evidence') AS ENTITY,
        COALESCE(OWNER, USER_NAME) AS ACTOR,
        CHANGE_TICKET_ID AS TICKET_ID,
        NULL::VARCHAR AS REPOSITORY,
        NULL::VARCHAR AS COMMIT_SHA,
        NULL::VARCHAR AS PR_URL,
        QUERY_ID,
        SNAPSHOT_TS AS EVENT_TS,
        QUERY_TAG,
        COALESCE(NULLIF(NEXT_CONTROL_ACTION, ''), 'Deploy the split Jira/ITSM evidence table and map ticket approval metadata.') AS NEXT_ACTION
    FROM legacy_tickets
    WHERE
        UPPER(COALESCE(OWNER_APPROVAL_STATUS, '')) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')
        OR UPPER(COALESCE(IAC_RECONCILIATION_STATE, '')) IN ('', 'GAP', 'MISSING', 'UNMATCHED', 'UNKNOWN')
)
SELECT *
FROM unmatched_rows
ORDER BY
    CASE SEVERITY WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,
    EVENT_TS DESC
LIMIT 100""".strip()


def _change_integration_timeline_sql(days: int, company: str, environment: str = "ALL") -> str:
    fact_table = mart_object_name("FACT_OBJECT_CHANGE")
    source_table = change_source_control_fqn()
    ticket_table = change_itsm_ticket_fqn()
    lookback = max(1, int(days or 14))

    object_where = _change_object_where(lookback, company)

    source_where = [f"COALESCE(APPLY_TS, SNAPSHOT_TS) >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())"]
    ticket_where = [f"COALESCE(UPDATED_AT, SNAPSHOT_TS) >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        source_where.append(f"COMPANY = {sql_literal(company, 100)}")
        ticket_where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        source_where.append(_bare_sql_predicate(env_clause))
        ticket_where.append(_bare_sql_predicate(env_clause))

    return f"""
WITH timeline AS (
    SELECT
        TO_DATE(START_TIME) AS EVENT_DATE,
        'Snowflake' AS EVENT_SOURCE,
        CHANGE_CATEGORY AS EVENT_TYPE,
        'Observed' AS EVENT_STATE,
        COUNT(*) AS EVENT_COUNT,
        COUNT_IF(CHANGE_CATEGORY IN ('DROP', 'POLICY', 'OWNER')) AS HIGH_RISK_COUNT,
        MAX(START_TIME) AS LAST_EVENT_TS
    FROM {fact_table}
    WHERE {" AND ".join(object_where)}
    GROUP BY TO_DATE(START_TIME), CHANGE_CATEGORY
    UNION ALL
    SELECT
        TO_DATE(COALESCE(APPLY_TS, SNAPSHOT_TS)) AS EVENT_DATE,
        COALESCE(SOURCE_SYSTEM, 'Terraform/Git') AS EVENT_SOURCE,
        COALESCE(PLANNED_ACTION, 'Source-control change') AS EVENT_TYPE,
        COALESCE(APPLY_STATUS, 'Recorded') AS EVENT_STATE,
        COUNT(*) AS EVENT_COUNT,
        COUNT_IF(UPPER(COALESCE(PLANNED_ACTION, '')) IN ('DELETE', 'DESTROY', 'DROP')) AS HIGH_RISK_COUNT,
        MAX(COALESCE(APPLY_TS, SNAPSHOT_TS)) AS LAST_EVENT_TS
    FROM {source_table}
    WHERE {" AND ".join(source_where)}
    GROUP BY TO_DATE(COALESCE(APPLY_TS, SNAPSHOT_TS)), COALESCE(SOURCE_SYSTEM, 'Terraform/Git'), COALESCE(PLANNED_ACTION, 'Source-control change'), COALESCE(APPLY_STATUS, 'Recorded')
    UNION ALL
    SELECT
        TO_DATE(COALESCE(UPDATED_AT, SNAPSHOT_TS)) AS EVENT_DATE,
        'Jira' AS EVENT_SOURCE,
        COALESCE(STATUS, 'Ticket update') AS EVENT_TYPE,
        COALESCE(APPROVAL_STATUS, 'Unknown approval') AS EVENT_STATE,
        COUNT(*) AS EVENT_COUNT,
        COUNT_IF(UPPER(COALESCE(RISK, '')) IN ('HIGH', 'CRITICAL')) AS HIGH_RISK_COUNT,
        MAX(COALESCE(UPDATED_AT, SNAPSHOT_TS)) AS LAST_EVENT_TS
    FROM {ticket_table}
    WHERE {" AND ".join(ticket_where)}
    GROUP BY TO_DATE(COALESCE(UPDATED_AT, SNAPSHOT_TS)), COALESCE(STATUS, 'Ticket update'), COALESCE(APPROVAL_STATUS, 'Unknown approval')
)
SELECT
    EVENT_DATE,
    EVENT_SOURCE,
    EVENT_TYPE,
    EVENT_STATE,
    EVENT_COUNT,
    HIGH_RISK_COUNT,
    LAST_EVENT_TS
FROM timeline
ORDER BY EVENT_DATE DESC, EVENT_SOURCE, EVENT_TYPE
LIMIT 500""".strip()


def _change_legacy_integration_timeline_sql(days: int, company: str, environment: str = "ALL") -> str:
    fact_table = mart_object_name("FACT_OBJECT_CHANGE")
    evidence_table = change_control_evidence_fqn()
    object_where = _change_object_where(days, company)
    evidence_where = _change_legacy_evidence_where(days, company, environment)
    return f"""
WITH legacy_evidence AS (
    SELECT *
    FROM {evidence_table}
    WHERE {" AND ".join(evidence_where)}
),
timeline AS (
    SELECT
        TO_DATE(START_TIME) AS EVENT_DATE,
        'Snowflake' AS EVENT_SOURCE,
        CHANGE_CATEGORY AS EVENT_TYPE,
        'Observed' AS EVENT_STATE,
        COUNT(*) AS EVENT_COUNT,
        COUNT_IF(CHANGE_CATEGORY IN ('DROP', 'POLICY', 'OWNER')) AS HIGH_RISK_COUNT,
        MAX(START_TIME) AS LAST_EVENT_TS
    FROM {fact_table}
    WHERE {" AND ".join(object_where)}
    GROUP BY TO_DATE(START_TIME), CHANGE_CATEGORY
    UNION ALL
    SELECT
        TO_DATE(SNAPSHOT_TS) AS EVENT_DATE,
        'Terraform/Git (legacy)' AS EVENT_SOURCE,
        COALESCE(FINDING_TYPE, 'Legacy evidence') AS EVENT_TYPE,
        COALESCE(IAC_RECONCILIATION_STATE, CHANGE_EVIDENCE_READINESS, 'Recorded') AS EVENT_STATE,
        COUNT(*) AS EVENT_COUNT,
        COUNT_IF(UPPER(COALESCE(SEVERITY, '')) IN ('HIGH', 'CRITICAL')) AS HIGH_RISK_COUNT,
        MAX(SNAPSHOT_TS) AS LAST_EVENT_TS
    FROM legacy_evidence
    WHERE
        UPPER(COALESCE(SOURCE, '')) ILIKE '%TERRAFORM%'
        OR UPPER(COALESCE(SOURCE, '')) ILIKE '%GIT%'
        OR UPPER(COALESCE(SOURCE, '')) ILIKE '%SOURCE%'
        OR NULLIF(TRIM(COALESCE(IAC_RECONCILIATION_STATE, '')), '') IS NOT NULL
    GROUP BY TO_DATE(SNAPSHOT_TS), COALESCE(FINDING_TYPE, 'Legacy evidence'), COALESCE(IAC_RECONCILIATION_STATE, CHANGE_EVIDENCE_READINESS, 'Recorded')
    UNION ALL
    SELECT
        TO_DATE(SNAPSHOT_TS) AS EVENT_DATE,
        'Jira' AS EVENT_SOURCE,
        COALESCE(CHANGE_TICKET_STATE, 'Legacy ticket evidence') AS EVENT_TYPE,
        COALESCE(OWNER_APPROVAL_STATUS, CHANGE_EVIDENCE_READINESS, 'Recorded') AS EVENT_STATE,
        COUNT(*) AS EVENT_COUNT,
        COUNT_IF(UPPER(COALESCE(SEVERITY, '')) IN ('HIGH', 'CRITICAL')) AS HIGH_RISK_COUNT,
        MAX(SNAPSHOT_TS) AS LAST_EVENT_TS
    FROM legacy_evidence
    WHERE
        CHANGE_TICKET_ID IS NOT NULL
        OR NULLIF(TRIM(COALESCE(CHANGE_TICKET_STATE, '')), '') IS NOT NULL
        OR UPPER(COALESCE(SOURCE, '')) ILIKE '%JIRA%'
        OR UPPER(COALESCE(SOURCE, '')) ILIKE '%ITSM%'
    GROUP BY TO_DATE(SNAPSHOT_TS), COALESCE(CHANGE_TICKET_STATE, 'Legacy ticket evidence'), COALESCE(OWNER_APPROVAL_STATUS, CHANGE_EVIDENCE_READINESS, 'Recorded')
)
SELECT
    EVENT_DATE,
    EVENT_SOURCE,
    EVENT_TYPE,
    EVENT_STATE,
    EVENT_COUNT,
    HIGH_RISK_COUNT,
    LAST_EVENT_TS
FROM timeline
ORDER BY EVENT_DATE DESC, EVENT_SOURCE, EVENT_TYPE
LIMIT 500""".strip()


def _change_action_queue_closure_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"
    where = [
        "SOURCE = 'Change & Drift - Brief'",
        f"COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_TIMESTAMP())",
    ]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
WITH scoped_actions AS (
    SELECT
        COALESCE(CATEGORY, 'Change Control') AS CATEGORY,
        COALESCE(ENTITY_TYPE, 'Change') AS ENTITY_TYPE,
        COALESCE(ENTITY_NAME, 'Unknown') AS ENTITY,
        COALESCE(OWNER, '') AS OWNER,
        COALESCE(APPROVER, '') AS APPROVER,
        COALESCE(STATUS, 'New') AS STATUS,
        COALESCE(SEVERITY, 'Medium') AS SEVERITY,
        COALESCE(TICKET_ID, '') AS TICKET_ID,
        DUE_DATE,
        COALESCE(VERIFICATION_STATUS, '') AS VERIFICATION_STATUS,
        COALESCE(VERIFICATION_QUERY, PROOF_QUERY, '') AS VERIFICATION_QUERY,
        COALESCE(VERIFICATION_RESULT, '') AS VERIFICATION_RESULT,
        COALESCE(OWNER_APPROVAL_STATUS, '') AS OWNER_APPROVAL_STATUS,
        COALESCE(RECOVERY_SLA_STATE, '') AS RECOVERY_SLA_STATE,
        COALESCE(RECOVERY_EVIDENCE, '') AS RECOVERY_EVIDENCE,
        COALESCE(UPDATED_AT, CREATED_AT) AS LAST_ACTIVITY_TS
    FROM {fqn}
    WHERE {where_clause}
),
rollup AS (
    SELECT
        CATEGORY,
        ENTITY_TYPE,
        ENTITY,
        MAX_BY(OWNER, LAST_ACTIVITY_TS) AS OWNER,
        MAX_BY(APPROVER, LAST_ACTIVITY_TS) AS APPROVER,
        COUNT(*) AS TOTAL_ACTIONS,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
        COUNT_IF(UPPER(STATUS) = 'FIXED') AS FIXED_ACTIONS,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND UPPER(VERIFICATION_STATUS) = 'VERIFIED'
            AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15
        ) AS VERIFIED_CLOSURES,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND (
                UPPER(VERIFICATION_STATUS) <> 'VERIFIED'
                OR LENGTH(TRIM(VERIFICATION_RESULT)) < 15
            )
        ) AS FIXED_WITHOUT_VERIFICATION,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
        COUNT_IF(UPPER(OWNER) IN ('', 'DBA', 'UNKNOWN', 'N/A', 'DBA CHANGE OWNER')) AS OWNER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(STATUS) = 'FIXED'
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) < 15
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY CATEGORY, ENTITY_TYPE, ENTITY
)
SELECT
    CATEGORY,
    ENTITY_TYPE,
    ENTITY,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Overdue closure'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Fixed without verification'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Verified closure'
        ELSE 'No recent action'
    END AS CLOSURE_READINESS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 0
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 1
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 2
        WHEN OPEN_ACTIONS > 0 THEN 3
        WHEN VERIFIED_CLOSURES > 0 THEN 8
        ELSE 9
    END AS CLOSURE_RANK,
    OWNER,
    APPROVER,
    TOTAL_ACTIONS,
    OPEN_ACTIONS,
    FIXED_ACTIONS,
    VERIFIED_CLOSURES,
    FIXED_WITHOUT_VERIFICATION,
    OVERDUE_OPEN,
    OWNER_GAP_ROWS,
    TICKET_GAP_ROWS,
    APPROVER_GAP_ROWS,
    VERIFICATION_QUERY_GAP_ROWS,
    OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_DUE_DATE,
    LAST_STATUS,
    LAST_SEVERITY,
    LAST_ACTIVITY_TS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate the change owner and ticket before accepting more drift.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Attach query, ticket, IaC, and blast-radius evidence or reopen the action.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete owner, ticket, approver, and verification metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open change action and retain source-control or rollback proof.'
        ELSE 'Retain verified closure evidence for audit review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _change_control_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read change-control blockers from the fast summary."""
    table = change_control_operability_fact_fqn()
    where = [f"SNAPSHOT_DATE >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_DATE())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
SELECT
    SNAPSHOT_DATE,
    COMPANY,
    ENVIRONMENT,
    CONTROL_SOURCE,
    CONTROL_KEY,
    FINDING_TYPE,
    ENTITY,
    OWNER,
    ESCALATION_TARGET,
    SEVERITY,
    EVIDENCE_ROWS,
    HIGH_RISK_CHANGES,
    ROUTE_BLOCKED,
    CLOSURE_BLOCKED,
    REVIEW_READY,
    MISSING_TICKET_ROWS,
    IAC_GAP_ROWS,
    MISSING_QUERY_ID_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS,
    CONTROL_STATE,
    CONTROL_RANK,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    ROUTE_BLOCKED DESC,
    CLOSURE_BLOCKED DESC,
    HIGH_RISK_CHANGES DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _save_change_control_evidence_snapshot(
    session,
    readiness: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
) -> None:
    try:
        session.sql(build_change_control_evidence_ddl()).collect()
        for migration_sql in build_change_control_evidence_migration_sql():
            session.sql(migration_sql).collect()
        session.sql(_change_control_evidence_insert_sql(
            readiness,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the Change Control Evidence snapshot for audit and trend tracking.")
    except Exception as exc:
        st.error(f"Could not save Change Control Evidence snapshot: {format_snowflake_error(exc)}")
        st.info("Deploy the change-control evidence table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _render_change_source_health(company: str, environment: str) -> None:
    source_health = _change_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Change Source Health", expanded=False):
        current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        fast_summary = int(
            source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["CONFIDENCE"].astype(str).str.contains("Fast summary", case=False, regex=False)
        ].shape[0]
        )
        render_shell_snapshot((
            ("Current Surfaces", f"{current}/{len(source_health)}"),
            ("Fast Summary", f"{fast_summary:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        defer_source_note(
            "Use this before acting on change findings. DDL/DCL detection is text-pattern based, "
            "and account/role-only events are intentionally retained when no database context exists."
        )
        render_priority_dataframe(
            source_health,
            title="Change evidence freshness and source quality",
            priority_columns=[
                "STATE", "SURFACE", "CONFIDENCE", "ROWS", "SCOPE", "SOURCE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All change source health rows",
            height=260,
        )


def _integration_mode_config(mode: str) -> dict:
    if str(mode) == "Jira":
        return {
            "slug": "jira",
            "title": "Jira Evidence",
            "caption": (
                "Load Jira/ITSM tickets ingested into Snowflake, then confirm each approved change links "
                "to Terraform/Git deploy evidence or observed Snowflake activity. OVERWATCH does not need "
                "Jira credentials at runtime."
            ),
            "lookback_label": "Jira evidence lookback (days)",
            "load_label": "Load Jira Evidence",
            "status_surfaces": {"Jira tickets", "Snowflake object changes"},
            "timeline_sources": {"Jira", "Snowflake"},
            "unmatched_gap_types": {
                "Snowflake change missing external evidence",
                "Terraform/Git deploy missing Jira ticket",
                "Approved Jira change missing deploy evidence",
            },
            "setup_sql": build_change_itsm_ticket_ddl(),
            "feed_stage_sql": build_change_evidence_feed_stage_sql(),
            "feed_load_sql": build_change_itsm_ticket_feed_load_sql(),
            "proof_placeholder": "-- Load Jira Evidence first.",
            "stale_copy": "Loaded Jira evidence is stale for the active scope. Reload before acting.",
            "unavailable_copy": (
                "Jira evidence is not available yet. Deploy the ITSM evidence table and feed it from Jira, then reload."
            ),
            "empty_copy": "No unmatched Jira/Snowflake evidence rows found for the selected window.",
            "coverage_title": "Jira and Snowflake evidence coverage",
            "raw_label": "All Jira evidence coverage rows",
        }
    return {
        "slug": "terraform",
        "title": "Terraform Evidence",
        "caption": (
            "Load Terraform/Flyway/Git deploy evidence ingested into Snowflake, then confirm each applied change "
            "links to Jira approval and observed Snowflake object-change history. OVERWATCH does not need "
            "Git, Terraform, or Flyway credentials at runtime."
        ),
        "lookback_label": "Deployment evidence lookback (days)",
        "load_label": "Load Terraform Evidence",
        "status_surfaces": {"Terraform/Flyway/Git evidence", "Terraform/Git evidence", "Flyway evidence", "Snowflake object changes"},
        "timeline_sources": {"Terraform/Git", "Git", "Terraform", "Flyway", "Snowflake"},
        "unmatched_gap_types": {
            "Snowflake change missing external evidence",
            "Terraform/Git deploy missing Jira ticket",
            "Terraform/Git deploy not observed in Snowflake change history",
            "Terraform/Flyway/Git deploy missing Jira ticket",
            "Terraform/Flyway/Git deploy not observed in Snowflake change history",
            "Flyway deploy missing Jira ticket",
            "Flyway deploy not observed in Snowflake change history",
        },
        "setup_sql": build_change_source_control_ddl(),
        "feed_stage_sql": build_change_evidence_feed_stage_sql(),
        "feed_load_sql": build_change_source_control_feed_load_sql(),
        "proof_placeholder": "-- Load Terraform Evidence first.",
        "stale_copy": "Loaded Terraform evidence is stale for the active scope. Reload before acting.",
        "unavailable_copy": (
            "Terraform/Flyway evidence is not available yet. Deploy the source-control evidence table and feed it from CI/Git/Flyway, then reload."
        ),
        "empty_copy": "No unmatched Terraform/Flyway/Snowflake evidence rows found for the selected window.",
        "coverage_title": "Terraform, Flyway, and Snowflake evidence coverage",
        "raw_label": "All deployment evidence coverage rows",
    }


def _filter_integration_frame(df: pd.DataFrame, mode: str, frame_kind: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    cfg = _integration_mode_config(mode)
    view = df.copy()
    if frame_kind == "status" and "SURFACE" in view.columns:
        return view[view["SURFACE"].astype(str).isin(cfg["status_surfaces"])].copy()
    if frame_kind == "timeline" and "EVENT_SOURCE" in view.columns:
        sources = view["EVENT_SOURCE"].fillna("").astype(str)
        if str(mode) == "Terraform":
            mask = sources.eq("Snowflake") | sources.str.contains("Terraform|Git", case=False, regex=True)
            return view[mask].copy()
        return view[sources.isin(cfg["timeline_sources"])].copy()
    if frame_kind == "unmatched" and "GAP_TYPE" in view.columns:
        return view[view["GAP_TYPE"].astype(str).isin(cfg["unmatched_gap_types"])].copy()
    return view


def _render_change_external_integrations(company: str, environment: str, default_days: int, *, mode: str) -> None:
    cfg = _integration_mode_config(mode)
    slug = cfg["slug"]
    prefix = f"change_integration_{slug}"

    st.subheader(cfg["title"])
    st.caption(cfg["caption"])
    integration_days = day_window_selectbox(
        cfg["lookback_label"],
        key=f"{prefix}_days",
        default=default_days,
    )
    if st.button(cfg["load_label"], key=f"{prefix}_load", width="stretch"):
        try:
            inventory_sql = _change_integration_object_inventory_sql()
            inventory = run_query(
                inventory_sql,
                ttl_key=f"change_integration_inventory_{company}_{environment}",
                tier="metadata",
                section="Change & Drift",
            )
            available_tables = _available_change_integration_tables(inventory)
            split_tables_ready = _split_change_evidence_tables_ready(available_tables)
            if split_tables_ready:
                status_sql = _change_integration_status_sql(integration_days, company, environment)
                unmatched_sql = _change_unmatched_evidence_sql(integration_days, company, environment)
                timeline_sql = _change_integration_timeline_sql(integration_days, company, environment)
                feed_health_sql = _change_split_feed_health_sql(integration_days, company, environment)
                st.session_state.pop(f"{prefix}_mode_note", None)
            else:
                missing = sorted(
                    table
                    for table in (CHANGE_SOURCE_CONTROL_TABLE, CHANGE_ITSM_TICKET_TABLE)
                    if table.upper() not in available_tables
                )
                status_sql = _change_legacy_integration_status_sql(integration_days, company, environment)
                unmatched_sql = _change_legacy_unmatched_evidence_sql(integration_days, company, environment)
                timeline_sql = _change_legacy_integration_timeline_sql(integration_days, company, environment)
                feed_health_sql = _change_legacy_feed_health_sql(integration_days, company, environment)
                st.session_state[f"{prefix}_mode_note"] = (
                    "Using legacy change-control evidence because the split evidence tables are not deployed yet. "
                    f"Missing: {', '.join(missing)}."
                )
            feed_health = run_query(
                feed_health_sql,
                ttl_key=f"{prefix}_feed_health_{company}_{environment}_{integration_days}",
                tier="standard",
                section="Change & Drift",
            )
            raw_status = run_query(
                status_sql,
                ttl_key=f"{prefix}_status_{company}_{environment}_{integration_days}",
                tier="standard",
                section="Change & Drift",
            )
            raw_unmatched = run_query(
                unmatched_sql,
                ttl_key=f"{prefix}_unmatched_{company}_{environment}_{integration_days}",
                tier="standard",
                section="Change & Drift",
            )
            raw_timeline = run_query(
                timeline_sql,
                ttl_key=f"{prefix}_timeline_{company}_{environment}_{integration_days}",
                tier="standard",
                section="Change & Drift",
            )
            st.session_state[f"{prefix}_feed_health"] = feed_health
            st.session_state[f"{prefix}_status"] = _filter_integration_frame(raw_status, mode, "status")
            st.session_state[f"{prefix}_unmatched"] = _filter_integration_frame(raw_unmatched, mode, "unmatched")
            st.session_state[f"{prefix}_timeline"] = _filter_integration_frame(raw_timeline, mode, "timeline")
            st.session_state[f"{prefix}_sql"] = {
                "feed_health": feed_health_sql,
                "status": status_sql,
                "unmatched": unmatched_sql,
                "timeline": timeline_sql,
            }
            st.session_state[f"{prefix}_meta"] = _change_scope_meta(
                company,
                environment,
                integration_days,
            )
            st.session_state.pop(f"{prefix}_error", None)
        except Exception as exc:
            st.session_state[f"{prefix}_feed_health"] = pd.DataFrame()
            st.session_state[f"{prefix}_status"] = pd.DataFrame()
            st.session_state[f"{prefix}_unmatched"] = pd.DataFrame()
            st.session_state[f"{prefix}_timeline"] = pd.DataFrame()
            st.session_state[f"{prefix}_error"] = format_snowflake_error(exc)
            st.warning(cfg["unavailable_copy"])

    expected_meta = _change_scope_meta(company, environment, integration_days)
    feed_health = st.session_state.get(f"{prefix}_feed_health")
    status = st.session_state.get(f"{prefix}_status")
    timeline = st.session_state.get(f"{prefix}_timeline")
    unmatched = st.session_state.get(f"{prefix}_unmatched")
    current = _change_meta_matches(st.session_state.get(f"{prefix}_meta"), expected_meta)
    mode_note = st.session_state.get(f"{prefix}_mode_note")
    if mode_note and current:
        st.info(mode_note)
    if feed_health is not None and not feed_health.empty and current:
        needs_feed = feed_health.get("FEED_STATE", pd.Series(dtype=str)).astype(str).isin(
            ["Ready - Empty", "Stale", "No Active Scope Rows"]
        ).sum()
        render_shell_snapshot((
            ("Feed Surfaces", f"{len(feed_health):,}"),
            ("Feed Rows", f"{safe_int(feed_health.get('ROWS', pd.Series(dtype=int)).sum()):,}"),
            ("Active Scope Rows", f"{safe_int(feed_health.get('ACTIVE_SCOPE_ROWS', pd.Series(dtype=int)).sum()):,}"),
            ("Needs Attention", f"{safe_int(needs_feed):,}"),
        ))
        render_priority_dataframe(
            feed_health,
            title=f"{cfg['title']} feed health",
            priority_columns=[
                "FEED_STATE", "FEED", "ROWS", "ACTIVE_SCOPE_ROWS",
                "LAST_EVENT_TS", "TICKET_KEY_ROWS", "LINK_KEY_ROWS",
                "EVIDENCE_URL_ROWS", "NEXT_ACTION",
            ],
            sort_by=["FEED_STATE", "FEED"],
            ascending=[True, True],
            raw_label=f"All {cfg['title'].lower()} feed health rows",
            height=200,
        )
    if status is not None and not status.empty and current:
        matched = status.get("SOURCE_MATCH_ROWS", pd.Series(dtype=int)).sum() + status.get("TICKET_MATCH_ROWS", pd.Series(dtype=int)).sum()
        render_shell_snapshot((
            ("Evidence Surfaces", f"{len(status):,}"),
            ("Rows", f"{safe_int(status.get('ROWS', pd.Series(dtype=int)).sum()):,}"),
            ("Matched Evidence", f"{safe_int(matched):,}"),
            ("Gaps", f"{safe_int(status.get('GAP_ROWS', pd.Series(dtype=int)).sum()):,}"),
        ))
        render_priority_dataframe(
            status,
            title=cfg["coverage_title"],
            priority_columns=[
                "STATE", "SURFACE", "ROWS", "SOURCE_MATCH_ROWS",
                "TICKET_MATCH_ROWS", "GAP_ROWS", "LAST_ACTIVITY_TS", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "GAP_ROWS", "SURFACE"],
            ascending=[True, False, True],
            raw_label=cfg["raw_label"],
            height=220,
        )
    elif status is not None and not current and not st.session_state.get(f"{prefix}_error"):
        st.info(cfg["stale_copy"])

    if unmatched is not None and not unmatched.empty and current:
        render_priority_dataframe(
            unmatched,
            title=f"Unmatched {cfg['title'].lower()} rows",
            priority_columns=[
                "SEVERITY", "GAP_TYPE", "EVIDENCE_SOURCE", "ENTITY", "ACTOR",
                "TICKET_ID", "REPOSITORY", "COMMIT_SHA", "PR_URL", "QUERY_ID",
                "EVENT_TS", "NEXT_ACTION",
            ],
            sort_by=["SEVERITY", "EVENT_TS", "GAP_TYPE"],
            ascending=[True, False, True],
            raw_label=f"All unmatched {cfg['title'].lower()} rows",
            height=300,
        )
    elif unmatched is not None and unmatched.empty and current and status is not None and not status.empty:
        st.success(cfg["empty_copy"])

    if timeline is not None and not timeline.empty and current:
        chart = (
            timeline.pivot_table(
                index="EVENT_DATE",
                columns="EVENT_SOURCE",
                values="EVENT_COUNT",
                aggfunc="sum",
            )
            .fillna(0)
            .sort_index()
        )
        st.bar_chart(chart)
        render_priority_dataframe(
            timeline,
            title=f"{cfg['title']} event timeline",
            priority_columns=[
                "EVENT_DATE", "EVENT_SOURCE", "EVENT_TYPE", "EVENT_STATE",
                "EVENT_COUNT", "HIGH_RISK_COUNT", "LAST_EVENT_TS",
            ],
            sort_by=["EVENT_DATE", "EVENT_SOURCE"],
            ascending=[False, True],
            raw_label=f"All {cfg['title'].lower()} timeline rows",
            height=260,
        )

    if st.session_state.get(f"{prefix}_error"):
        st.caption(
            f"{cfg['title']} unavailable: {st.session_state.get(f'{prefix}_error')}"
        )
    with st.expander(f"{cfg['title']} table setup SQL", expanded=False):
        st.code(cfg["setup_sql"], language="sql")
    with st.expander(f"{cfg['title']} feed load SQL", expanded=False):
        st.code(cfg["feed_stage_sql"], language="sql")
        st.code(cfg["feed_load_sql"], language="sql")
    with st.expander(f"{cfg['title']} proof SQL", expanded=False):
        proof_sql = st.session_state.get(f"{prefix}_sql", {})
        st.code(proof_sql.get("feed_health", cfg["proof_placeholder"]), language="sql")
        st.code(proof_sql.get("status", cfg["proof_placeholder"]), language="sql")
        st.code(proof_sql.get("unmatched", cfg["proof_placeholder"]), language="sql")
        st.code(proof_sql.get("timeline", cfg["proof_placeholder"]), language="sql")


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    if st.session_state.get("exceptions_only_mode") and "change_drift_workflow" not in st.session_state:
        st.session_state["change_drift_workflow"] = "Object and access changes"
    if st.session_state.get("exceptions_only_mode") and "change_drift_view" not in st.session_state:
        st.session_state["change_drift_view"] = "Change Brief"
    if st.session_state.get("change_drift_view") not in CHANGE_DRIFT_VIEWS:
        st.session_state["change_drift_view"] = CHANGE_DRIFT_VIEWS[0]
    _apply_change_brief_first_default()
    _apply_queued_change_workflow()
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="estimated",
        scope_note="DDL/change detection is query-history based; SHOW commands fill live metadata gaps.",
    )
    render_operator_briefing(
        [
            ("First move", "Identify who changed what and whether it was approved."),
            ("Evidence", "Preserve query ID, actor, object, timestamp, and dependency context."),
            ("Control", "Route drift to source control, owner review, or a guarded DBA action."),
            ("Output", "Build an audit-ready change narrative with blast-radius notes."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize recent DDL, grant, owner, policy, replication, and task-control issues.")

    days = safe_int(st.session_state.get("change_drift_brief_days", 14), 14)
    if days < 1 or days > 90:
        days = 14
    summary = st.session_state.get("change_drift_summary")
    exceptions = st.session_state.get("change_drift_exceptions")
    meta = st.session_state.get("change_drift_meta", {})
    _render_change_action_brief(
        _change_action_brief(summary, exceptions, meta, company, environment, days)
    )
    _render_change_operating_snapshot(
        _change_operating_snapshot(summary, exceptions, meta, company, environment, days)
    )

    days = day_window_selectbox(
        "Change brief lookback",
        key="change_drift_brief_days",
        default=14,
    )
    active_view = render_mode_selector(
        "Change & Drift view",
        "change_drift_view",
        CHANGE_DRIFT_VIEWS,
        default=CHANGE_DRIFT_VIEWS[0],
    )
    if active_view == "Change Brief":
        _render_change_brief_launchpad()
    if active_view == "Change Workflows":
        if _change_has_source_state(st.session_state):
            _render_change_source_health(company, environment)
        workflow = render_workflow_selector(
            "Change workflow",
            "change_drift_workflow",
            WORKFLOWS,
            WORKFLOW_DETAILS,
            columns=5,
        )

        if workflow == "Object and access changes":
            render_workflow_module(workflow, WORKFLOW_MODULES)
        elif workflow == "Stored procedure lineage":
            render_workflow_module(workflow, WORKFLOW_MODULES)
        elif workflow == "Terraform evidence":
            _render_change_external_integrations(company, environment, days, mode="Terraform")
        elif workflow == "Jira evidence":
            _render_change_external_integrations(company, environment, days, mode="Jira")
        elif workflow == "Schema and object drift":
            st.session_state["dba_tools_focus"] = "Governance"
            st.session_state["dba_tools_focus_tool"] = "Schema Compare"
            st.info("Focused toolkit: schema compare, recent objects, unused objects, object inventory, and drift checks.")
            render_workflow_module(workflow, WORKFLOW_MODULES)
        elif workflow == "Data movement and replication":
            st.session_state["dba_tools_focus"] = "Data Movement"
            st.session_state["dba_tools_focus_tool"] = "Data Loading"
            st.info("Focused toolkit: data loading, Snowpipe, dynamic tables, and replication checks.")
            render_workflow_module(workflow, WORKFLOW_MODULES)
        else:
            st.session_state["dba_tools_focus"] = "Controlled Actions"
            st.session_state["dba_tools_focus_tool"] = "Task Graph Control"
            st.info("Focused toolkit: query cancellation, warehouse settings, task graph control, setup, and audit evidence.")
            render_workflow_module(workflow, WORKFLOW_MODULES)
        return

    if st.button("Load Change & Drift Brief", key="change_drift_brief_load", type="primary"):
        try:
            summary_sql, exceptions_sql = _build_mart_change_drift_sql(days, company)
            source_label = "Fast change summary"
            st.session_state["change_drift_summary"] = run_query(
                summary_sql,
                ttl_key=f"change_drift_summary_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            st.session_state["change_drift_exceptions"] = run_query(
                exceptions_sql,
                ttl_key=f"change_drift_exceptions_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            st.session_state["change_drift_proof_sql"] = {
                "summary": summary_sql,
                "exceptions": exceptions_sql,
            }
            st.session_state["change_drift_source"] = source_label
            st.session_state["change_drift_meta"] = {
                **_change_scope_meta(company, environment, days),
                "source": source_label,
            }
            st.session_state.pop("change_drift_error", None)
        except Exception as exc:
            try:
                session = get_session()
                summary_sql, exceptions_sql = _build_change_drift_sql(session, days, company)
                source_label = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                st.session_state["change_drift_summary"] = run_query(
                    summary_sql,
                    ttl_key=f"change_drift_summary_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                st.session_state["change_drift_exceptions"] = run_query(
                    exceptions_sql,
                    ttl_key=f"change_drift_exceptions_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                st.session_state["change_drift_proof_sql"] = {
                    "summary": summary_sql,
                    "exceptions": exceptions_sql,
                }
                st.session_state["change_drift_source"] = source_label
                st.session_state["change_drift_meta"] = {
                    **_change_scope_meta(company, environment, days),
                    "source": source_label,
                }
                st.session_state.pop("change_drift_error", None)
                st.info(f"Change summary unavailable from the fast source; used live QUERY_HISTORY fallback. {format_snowflake_error(exc)}")
            except Exception as live_exc:
                st.session_state["change_drift_summary"] = pd.DataFrame()
                st.session_state["change_drift_exceptions"] = pd.DataFrame()
                st.session_state["change_drift_source"] = "Unavailable: change brief"
                st.session_state["change_drift_meta"] = _change_scope_meta(company, environment, days)
                st.session_state["change_drift_error"] = format_snowflake_error(live_exc)
                st.error(f"Unable to load change brief: {format_snowflake_error(live_exc)}")
        try:
            operability_sql = _change_control_operability_fact_sql(days, company, environment)
            st.session_state["change_control_operability_fact_sql"] = operability_sql
            st.session_state["change_control_operability_fact"] = run_query(
                operability_sql,
                ttl_key=f"change_control_operability_fact_{company}_{environment}_{days}",
                tier="standard",
                section="Change & Drift",
            )
            st.session_state["change_control_operability_fact_meta"] = _change_scope_meta(company, environment, days)
            st.session_state.pop("change_control_operability_fact_error", None)
        except Exception as fact_exc:
            st.session_state["change_control_operability_fact"] = pd.DataFrame()
            st.session_state["change_control_operability_fact_error"] = format_snowflake_error(fact_exc)

    summary = st.session_state.get("change_drift_summary")
    exceptions = st.session_state.get("change_drift_exceptions")
    meta = st.session_state.get("change_drift_meta", {})
    expected_brief_meta = _change_scope_meta(company, environment, days)
    brief_is_current = _change_meta_matches(meta, expected_brief_meta)
    if summary is not None and not summary.empty and not brief_is_current:
        st.info("Loaded Change & Drift brief is stale for the active scope. Reload the brief before acting.")
    if (
        summary is not None
        and not summary.empty
        and brief_is_current
    ):
        row = summary.iloc[0]
        score = _change_drift_score(
            object_changes=safe_int(row.get("OBJECT_CHANGES", 0)),
            access_changes=safe_int(row.get("ACCESS_CHANGES", 0)),
            policy_changes=safe_int(row.get("POLICY_CHANGES", 0)),
            owner_changes=safe_int(row.get("OWNER_CHANGES", 0)),
            destructive_changes=safe_int(row.get("DESTRUCTIVE_CHANGES", 0)),
            manual_drift=safe_int(row.get("MANUAL_DRIFT", 0)),
        )
        if score < 85:
            st.warning("Change control needs DBA review; high-risk changes or drift indicators are present.")
        elif score < 95:
            st.info("Change control is usable, but there are changes worth validating.")
        else:
            st.success("Change control looks clean for the selected window.")
        defer_source_note(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

        operability_fact = st.session_state.get("change_control_operability_fact")
        operability_fact_current = _change_meta_matches(
            st.session_state.get("change_control_operability_fact_meta"),
            expected_brief_meta,
        )
        if operability_fact is not None and not operability_fact.empty and operability_fact_current:
            st.subheader("Change Control Summary")
            render_shell_snapshot((
                ("Rows", f"{len(operability_fact):,}"),
                ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                (
                    "Route / Closure Blocks",
                    f"{int(operability_fact.get('ROUTE_BLOCKED', pd.Series(dtype=int)).sum() + operability_fact.get('CLOSURE_BLOCKED', pd.Series(dtype=int)).sum()):,}",
                ),
                ("Verified Closures", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
            ))
            render_priority_dataframe(
                operability_fact,
                title="Change-control blockers",
                priority_columns=[
                    "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "ENVIRONMENT",
                    "FINDING_TYPE", "ENTITY", "OWNER", "SEVERITY", "HIGH_RISK_CHANGES",
                    "ROUTE_BLOCKED", "CLOSURE_BLOCKED", "MISSING_TICKET_ROWS",
                    "IAC_GAP_ROWS", "MISSING_QUERY_ID_ROWS", "OPEN_ACTIONS",
                    "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES",
                    "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "HIGH_RISK_CHANGES"],
                ascending=[True, False, False, False],
                raw_label="All change-control summary rows",
                height=300,
            )
            with st.expander("Change control summary SQL", expanded=False):
                st.code(st.session_state.get("change_control_operability_fact_sql", ""), language="sql")
        elif operability_fact is not None and not operability_fact.empty and not operability_fact_current:
            st.info("Loaded change-control summary is stale for the active scope. Reload the brief before acting.")
        elif st.session_state.get("change_control_operability_fact_error"):
            defer_source_note(
                "Change-control summary is not available yet; deploy or refresh "
                "`FACT_CHANGE_CONTROL_OPERABILITY_DAILY` to enable the fast blocker surface."
            )

        _render_change_watch_floor(score, exceptions, row)
        st.divider()

        if exceptions is not None and not exceptions.empty:
            st.subheader("Change & Drift Exceptions")
            priority_exceptions = _change_priority_view(exceptions)
            render_priority_dataframe(
                priority_exceptions,
                title="Change and drift exceptions to verify first",
                priority_columns=[
                    "SEVERITY", "FINDING_TYPE", "ENTITY", "USER_NAME",
                    "ROLE_NAME", "DATABASE_NAME", "ENVIRONMENT", "SCOPE_CONFIDENCE",
                    "QUERY_ID", "LAST_SEEN", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["SEVERITY", "LAST_SEEN", "ENTITY"],
                ascending=[True, False, True],
                raw_label="All change and drift exceptions",
            )
            readiness = _build_change_control_readiness(exceptions)
            readiness_summary = _change_control_readiness_summary(readiness)
            closure_days_for_gate = safe_int(st.session_state.get("change_action_closure_days", 30)) or 30
            closure_for_gate = st.session_state.get("change_action_closure")
            if not _change_meta_matches(
                st.session_state.get("change_action_closure_meta"),
                _change_scope_meta(company, environment, closure_days_for_gate),
            ):
                closure_for_gate = pd.DataFrame()
            operator_moves = _change_operator_next_moves(
                score=score,
                exceptions=exceptions,
                readiness_summary=readiness_summary,
                readiness=readiness,
                closure=closure_for_gate,
                operability_fact=operability_fact if operability_fact_current else pd.DataFrame(),
            )
            render_priority_dataframe(
                operator_moves,
                title="Change operator next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All change operator gates",
                height=240,
                max_rows=6,
            )
            intervention_matrix = _change_intervention_matrix(
                exceptions,
                readiness=readiness,
                closure=closure_for_gate,
            )
            if not intervention_matrix.empty:
                render_priority_dataframe(
                    intervention_matrix,
                    title="Change DBA intervention matrix",
                    priority_columns=[
                        "DBA_PRIORITY", "INTERVENTION_STATE", "SEVERITY", "FINDING_TYPE", "ENTITY",
                        "USER_NAME", "ROLE_NAME", "QUERY_ID", "CONTROL_STATE",
                        "TICKET_STATE", "IAC_STATE", "CLOSURE_READINESS",
                        "NEXT_DECISION", "PROOF_REQUIRED", "NEXT_WORKFLOW",
                    ],
                    sort_by=["DBA_PRIORITY", "SEVERITY", "FINDING_TYPE"],
                    ascending=[True, True, True],
                    raw_label="All change DBA intervention rows",
                    height=300,
                    max_rows=10,
                )
            if not readiness_summary.empty:
                render_shell_snapshot((
                    ("Change Routes", f"{len(readiness_summary):,}"),
                    ("Closure Blocked", f"{int(readiness_summary['CLOSURE_BLOCKED'].sum()):,}"),
                    ("Route Blocked", f"{int(readiness_summary['ROUTE_BLOCKED'].sum()):,}"),
                    ("Account Scope", f"{int(readiness_summary['ACCOUNT_SCOPE_ROWS'].sum()):,}"),
                ))
                render_priority_dataframe(
                    readiness_summary,
                    title="Change-control blocker board",
                    priority_columns=[
                        "READINESS", "ENVIRONMENT", "FINDING_TYPE", "OWNER", "APPROVER",
                        "TOTAL_CHANGES", "HIGH_RISK_CHANGES", "ROUTE_BLOCKED",
                        "CLOSURE_BLOCKED", "REVIEW_READY", "MISSING_TICKET_ROWS",
                        "IAC_GAP_ROWS", "MISSING_QUERY_ID_ROWS", "ACCOUNT_SCOPE_ROWS",
                        "REVIEW_SLA_HOURS", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["READINESS_RANK", "HIGH_RISK_CHANGES", "MISSING_TICKET_ROWS", "IAC_GAP_ROWS"],
                    ascending=[True, False, False, False],
                    raw_label="All change-control blocker routes",
                    height=260,
                )
            render_priority_dataframe(
                readiness,
                title="Change-control readiness before queueing",
                priority_columns=[
                    "SEVERITY", "CHANGE_CONTROL_STATE", "FINDING_TYPE", "ENTITY",
                    "USER_NAME", "QUERY_ID", "APPROVER", "OWNER_APPROVAL_STATUS",
                    "OWNER", "ESCALATION_TARGET", "DATABASE_CONTEXT", "DATABASE_NAME",
                    "ENVIRONMENT", "SCOPE_CONFIDENCE", "CHANGE_TICKET_ID", "CHANGE_TICKET_STATE",
                    "IAC_RECONCILIATION_STATE", "EXECUTION_AUDIT_STATE", "APPROVAL_ROUTE_READY",
                    "CHANGE_EVIDENCE_READINESS", "EVIDENCE_BLOCKERS", "REVIEW_SLA_HOURS",
                    "CONTROL_GAP", "NEXT_CONTROL_ACTION", "PROOF_REQUIRED",
                ],
                sort_by=["SEVERITY", "CHANGE_CONTROL_STATE", "ENTITY"],
                ascending=[True, True, True],
                raw_label="All change-control readiness rows",
                height=260,
            )
            save_col, setup_col = st.columns([1, 2])
            with save_col:
                if st.button("Save Change Evidence Snapshot", key="change_drift_evidence_snapshot", width="stretch"):
                    _save_change_control_evidence_snapshot(
                        get_session(),
                        readiness,
                        company=company,
                        environment=environment,
                        source=meta.get("source", ""),
                    )
            with setup_col:
                defer_source_note(
                    "Snapshot stores ticket, IaC, owner, approver, query-id, and blast-radius requirements for audit trend review."
                )
            with st.expander("Change Control Evidence Trend", expanded=False):
                trend_days = day_window_selectbox(
                    "Change evidence trend window",
                    key="change_drift_evidence_trend_days",
                    default=30,
                )
                if st.button("Load Change Evidence Trend", key="change_drift_evidence_trend_load"):
                    try:
                        trend_sql = _change_control_evidence_history_sql(trend_days, company, environment)
                        trend = run_query(
                            trend_sql,
                            ttl_key=f"change_drift_evidence_trend_{company}_{environment}_{trend_days}",
                            tier="standard",
                            section="Change & Drift",
                        )
                        st.session_state["change_drift_evidence_trend"] = trend
                        st.session_state["change_drift_evidence_trend_sql"] = trend_sql
                        st.session_state["change_drift_evidence_trend_meta"] = _change_scope_meta(
                            company, environment, trend_days
                        )
                        st.session_state.pop("change_drift_evidence_trend_error", None)
                    except Exception as exc:
                        st.session_state["change_drift_evidence_trend"] = pd.DataFrame()
                        st.session_state["change_drift_evidence_trend_error"] = format_snowflake_error(exc)
                        st.error(f"Unable to load change-control evidence trend: {format_snowflake_error(exc)}")
                trend = st.session_state.get("change_drift_evidence_trend")
                trend_current = _change_meta_matches(
                    st.session_state.get("change_drift_evidence_trend_meta"),
                    _change_scope_meta(company, environment, trend_days),
                )
                if trend is not None and not trend.empty and trend_current:
                    render_priority_dataframe(
                        trend,
                        title="Persistent change-control evidence gaps",
                        priority_columns=[
                            "FINDING_TYPE", "SEVERITY", "OWNER", "ESCALATION_TARGET",
                            "EVIDENCE_ROWS", "MISSING_TICKET_ROWS", "IAC_GAP_ROWS",
                            "MISSING_QUERY_ID_ROWS", "LAST_CONTROL_STATE", "LAST_CONTROL_GAP",
                        ],
                        sort_by=["MISSING_TICKET_ROWS", "IAC_GAP_ROWS", "LAST_SNAPSHOT_TS"],
                        ascending=[False, False, False],
                        raw_label="All persisted change-control evidence",
                        height=260,
                    )
                elif (
                    trend is not None
                    and not trend_current
                    and not st.session_state.get("change_drift_evidence_trend_error")
                ):
                    st.info("Loaded change-control evidence trend is stale for the active scope. Reload the trend before acting.")
                with st.expander("Change-control evidence setup SQL", expanded=False):
                    st.code(build_change_control_evidence_ddl(), language="sql")
            with st.expander("Change Action Closure Analytics", expanded=False):
                defer_source_note(
                    "Uses Change & Drift action-queue rows to show open, overdue, unapproved, "
                    "or closed-without-verification change-control work."
                )
                closure_days = day_window_selectbox(
                    "Change closure window",
                    key="change_action_closure_days",
                    default=30,
                )
                if st.button("Load Change Closure Analytics", key="change_action_closure_load"):
                    try:
                        closure_sql = _change_action_queue_closure_sql(closure_days, company, environment)
                        closure = run_query(
                            closure_sql,
                            ttl_key=f"change_action_closure_{company}_{environment}_{closure_days}",
                            tier="standard",
                            section="Change & Drift",
                        )
                        st.session_state["change_action_closure"] = closure
                        st.session_state["change_action_closure_sql"] = closure_sql
                        st.session_state["change_action_closure_meta"] = _change_scope_meta(
                            company, environment, closure_days
                        )
                        st.session_state.pop("change_action_closure_error", None)
                    except Exception as exc:
                        st.session_state["change_action_closure"] = pd.DataFrame()
                        st.session_state["change_action_closure_error"] = format_snowflake_error(exc)
                        st.warning(f"Change closure analytics unavailable: {format_snowflake_error(exc)}")
                closure = st.session_state.get("change_action_closure")
                closure_current = _change_meta_matches(
                    st.session_state.get("change_action_closure_meta"),
                    _change_scope_meta(company, environment, closure_days),
                )
                if closure is not None and not closure.empty and closure_current:
                    render_priority_dataframe(
                        closure,
                        title="Change closure evidence gaps",
                        priority_columns=[
                            "CATEGORY", "ENTITY_TYPE", "ENTITY", "CLOSURE_READINESS",
                            "OWNER", "APPROVER", "TOTAL_ACTIONS", "OPEN_ACTIONS",
                            "OVERDUE_OPEN", "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                            "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                            "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                            "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                        ],
                        sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All change closure rows",
                        height=300,
                    )
                    with st.expander("Change Closure Query", expanded=False):
                        st.code(st.session_state.get("change_action_closure_sql", ""), language="sql")
                elif (
                    closure is not None
                    and not closure_current
                    and not st.session_state.get("change_action_closure_error")
                ):
                    st.info("Loaded change closure analytics are stale for the active scope. Reload closure analytics before acting.")
                elif closure is not None and closure_current:
                    st.info("No Change & Drift action-queue rows found for the selected scope.")
            if st.button("Save Change Exceptions to Action Queue", key="change_drift_queue"):
                _queue_change_exceptions(get_session(), exceptions)
        elif exceptions is not None:
            st.success("No change/drift exceptions crossed the default thresholds.")
        brief_md = _build_change_drift_markdown(
            company=company,
            days=days,
            score=score,
            summary_row=row,
            exceptions=exceptions,
        )
        dl1, dl2 = st.columns([1, 3])
        with dl1:
            st.download_button(
                "Download Change Brief",
                brief_md,
                file_name=f"overwatch_change_drift_brief_{company.lower()}.md",
                mime="text/markdown",
                key="change_drift_download",
            )
        with dl2:
            with st.expander("Proof SQL", expanded=False):
                proof_sql = st.session_state.get("change_drift_proof_sql", {})
                defer_source_note("Use these source queries to defend change counts and exception rows.")
                st.code(proof_sql.get("summary", "-- Load the change brief first."), language="sql")
                st.code(proof_sql.get("exceptions", "-- Load the change brief first."), language="sql")
        if st.session_state.get("exceptions_only_mode"):
            st.stop()
