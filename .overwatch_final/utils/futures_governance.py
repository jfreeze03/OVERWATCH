# utils/futures_governance.py - forward Snowflake platform governance helpers
from __future__ import annotations

from collections.abc import Iterable, Mapping

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, DEFAULT_ALERT_EMAIL, FORWARD_PLATFORM_CONTROLS, THRESHOLDS
from .company_filter import (
    company_value_allowed,
    environment_value_allowed,
    get_global_filter_clause,
)
from .compatibility import filter_existing_columns, get_available_columns
from .helpers import safe_float, safe_int
from .metadata import show_to_df
from .owner_directory import load_owner_directory, resolve_owner_context
from .query import run_query, safe_identifier, sql_literal


PLATFORM_FUTURES_AREAS = (
    "Agent & MCP Governance",
    "AI Spend & Token Guardrails",
    "Openflow Operations",
    "Horizon Governance Readiness",
    "Semantic Trust & Verified Query Testing",
    "BCDR Drill Ledger",
    "AI Change Governance",
)

PLATFORM_FUTURES_CONTROL_TABLE = "OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER"
PLATFORM_FUTURES_EVIDENCE_TABLE = "OVERWATCH_PLATFORM_FUTURES_EVIDENCE"
PLATFORM_FUTURES_LATEST_VIEW = "OVERWATCH_PLATFORM_FUTURES_EVIDENCE_LATEST_V"
PLATFORM_FUTURES_COVERAGE_VIEW = "OVERWATCH_PLATFORM_FUTURES_CONTROL_COVERAGE_V"

ADMIN_ROLE_TOKENS = ("ACCOUNTADMIN", "SECURITYADMIN", "ORGADMIN")
EXTERNAL_INTERFACE_TOKENS = ("EXTERNAL", "MICROSOFT_TEAMS", "TEAMS", "API")

HORIZON_SEMANTIC_PROBES = (
    {
        "CONTROL_AREA": "Horizon Governance Readiness",
        "SURFACE": "Sensitive Data Classification",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.DATA_CLASSIFICATION_LATEST",
        "MANDATORY": True,
        "DBA_ACTION": "Use classification evidence to prove sensitive data discovery before expanding cross-engine access.",
    },
    {
        "CONTROL_AREA": "Horizon Governance Readiness",
        "SURFACE": "Policy Coverage",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES",
        "MANDATORY": True,
        "DBA_ACTION": "Use policy-reference evidence to prove masking, row access, and policy attachment coverage.",
    },
    {
        "CONTROL_AREA": "Horizon Governance Readiness",
        "SURFACE": "Access History",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY",
        "MANDATORY": True,
        "DBA_ACTION": "Use access history to answer who touched what before approving broader data product or AI access.",
    },
    {
        "CONTROL_AREA": "Horizon Governance Readiness",
        "SURFACE": "Object Dependency Lineage",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES",
        "MANDATORY": True,
        "DBA_ACTION": "Use dependencies to prove blast radius before changing shared views, semantic models, or data products.",
    },
    {
        "CONTROL_AREA": "Semantic Trust & Verified Query Testing",
        "SURFACE": "Semantic Views",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_VIEWS",
        "MANDATORY": False,
        "DBA_ACTION": "Inventory semantic views and require owner, certification, and regression query evidence.",
    },
    {
        "CONTROL_AREA": "Semantic Trust & Verified Query Testing",
        "SURFACE": "Semantic Tables",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_TABLES",
        "MANDATORY": False,
        "DBA_ACTION": "Inventory semantic tables and validate freshness and ownership before agent trust.",
    },
    {
        "CONTROL_AREA": "Semantic Trust & Verified Query Testing",
        "SURFACE": "Semantic Metrics",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_METRICS",
        "MANDATORY": False,
        "DBA_ACTION": "Treat metric definitions as governed assets with owner, test, and change evidence.",
    },
    {
        "CONTROL_AREA": "AI Change Governance",
        "SURFACE": "Cortex Code CLI Usage",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY",
        "MANDATORY": False,
        "DBA_ACTION": "Route AI-assisted code activity into Change & Drift when DDL, grants, or deployment SQL is involved.",
    },
    {
        "CONTROL_AREA": "AI Change Governance",
        "SURFACE": "Cortex Code Snowsight Usage",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY",
        "MANDATORY": False,
        "DBA_ACTION": "Require ticket, reviewer, rollback, and verification for AI-assisted admin changes.",
    },
    {
        "CONTROL_AREA": "AI Change Governance",
        "SURFACE": "Cortex AISQL Usage",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AISQL_USAGE_HISTORY",
        "MANDATORY": False,
        "DBA_ACTION": "Watch AI SQL adoption for cost, correctness, owner, and semantic-model trust gaps.",
    },
    {
        "CONTROL_AREA": "Horizon Governance Readiness",
        "SURFACE": "Trust Center Findings",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.TRUST_CENTER_FINDINGS",
        "MANDATORY": False,
        "DBA_ACTION": "Use Trust Center findings as account-level evidence for audit and executive risk review.",
    },
    {
        "CONTROL_AREA": "Horizon Governance Readiness",
        "SURFACE": "Data Quality Monitoring",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.DATA_QUALITY_MONITORING_USAGE_HISTORY",
        "MANDATORY": False,
        "DBA_ACTION": "Use data-quality monitoring evidence to prove important data products are measured, not just documented.",
    },
    {
        "CONTROL_AREA": "BCDR Drill Ledger",
        "SURFACE": "Backup Operation History",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.BACKUP_OPERATION_HISTORY",
        "MANDATORY": False,
        "DBA_ACTION": "Use backup operation evidence with failover/replication rows to build a real BCDR drill ledger.",
    },
)


def _upper_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    view = frame.copy()
    view.columns = [str(col).upper() for col in view.columns]
    return view


def platform_futures_table_fqn(
    db: str,
    schema: str,
    table: str,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"
    return f"{db}.{schema}.{table}"


def _control_seed_values_sql() -> str:
    rows = []
    for item in FORWARD_PLATFORM_CONTROLS:
        row = {str(key).upper(): value for key, value in item.items()}
        rows.append("(" + ", ".join([
            sql_literal(row.get("CONTROL_ID"), 200),
            sql_literal(row.get("CONTROL_AREA"), 200),
            sql_literal(row.get("OWNER"), 200),
            sql_literal(row.get("OWNER_KEY"), 200),
            sql_literal(row.get("APPROVAL_GROUP"), 200),
            sql_literal(row.get("PRIMARY_EVIDENCE"), 1000),
            sql_literal(row.get("SOURCE_OBJECTS"), 1000),
            sql_literal(row.get("RISK_IF_MISSING"), 2000),
            sql_literal(row.get("DBA_DECISION"), 2000),
            sql_literal(row.get("AUTOMATION_BOUNDARY"), 2000),
            str(safe_int(row.get("MATCH_PRIORITY"))),
        ]) + ")")
    return ",\n    ".join(rows)


def build_platform_futures_evidence_ddl(db: str = ALERT_DB, schema: str = ALERT_SCHEMA) -> str:
    """Return DDL for durable AI/platform-futures controls and evidence."""
    db_safe = safe_identifier(db)
    schema_safe = safe_identifier(schema)
    control_table = safe_identifier(PLATFORM_FUTURES_CONTROL_TABLE)
    evidence_table = safe_identifier(PLATFORM_FUTURES_EVIDENCE_TABLE)
    latest_view = safe_identifier(PLATFORM_FUTURES_LATEST_VIEW)
    coverage_view = safe_identifier(PLATFORM_FUTURES_COVERAGE_VIEW)
    control_fqn = f"{db_safe}.{schema_safe}.{control_table}"
    evidence_fqn = f"{db_safe}.{schema_safe}.{evidence_table}"
    latest_fqn = f"{db_safe}.{schema_safe}.{latest_view}"
    coverage_fqn = f"{db_safe}.{schema_safe}.{coverage_view}"
    return f"""-- OVERWATCH platform futures control register and evidence ledger
-- Use this for Cortex Agents, MCP servers, AI usage, Openflow, Horizon,
-- semantic trust, BCDR drills, and AI-assisted change governance.
CREATE TABLE IF NOT EXISTS {control_fqn} (
    CONTROL_ID          VARCHAR(200) PRIMARY KEY,
    CONTROL_AREA        VARCHAR(200),
    OWNER               VARCHAR(200),
    OWNER_KEY           VARCHAR(200),
    APPROVAL_GROUP      VARCHAR(200),
    PRIMARY_EVIDENCE    VARCHAR(1000),
    SOURCE_OBJECTS      VARCHAR(1000),
    RISK_IF_MISSING     VARCHAR(2000),
    DBA_DECISION        VARCHAR(2000),
    AUTOMATION_BOUNDARY VARCHAR(2000),
    MATCH_PRIORITY      NUMBER DEFAULT 0,
    IS_ACTIVE           BOOLEAN DEFAULT TRUE,
    UPDATED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_BY          VARCHAR(200) DEFAULT CURRENT_USER()
);

MERGE INTO {control_fqn} tgt
USING (
    SELECT * FROM VALUES
    {_control_seed_values_sql()}
) src(CONTROL_ID, CONTROL_AREA, OWNER, OWNER_KEY, APPROVAL_GROUP, PRIMARY_EVIDENCE,
      SOURCE_OBJECTS, RISK_IF_MISSING, DBA_DECISION, AUTOMATION_BOUNDARY, MATCH_PRIORITY)
ON UPPER(tgt.CONTROL_ID) = UPPER(src.CONTROL_ID)
WHEN MATCHED THEN UPDATE SET
    CONTROL_AREA = src.CONTROL_AREA,
    OWNER = src.OWNER,
    OWNER_KEY = src.OWNER_KEY,
    APPROVAL_GROUP = src.APPROVAL_GROUP,
    PRIMARY_EVIDENCE = src.PRIMARY_EVIDENCE,
    SOURCE_OBJECTS = src.SOURCE_OBJECTS,
    RISK_IF_MISSING = src.RISK_IF_MISSING,
    DBA_DECISION = src.DBA_DECISION,
    AUTOMATION_BOUNDARY = src.AUTOMATION_BOUNDARY,
    MATCH_PRIORITY = src.MATCH_PRIORITY,
    IS_ACTIVE = TRUE,
    UPDATED_AT = CURRENT_TIMESTAMP(),
    UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
    (CONTROL_ID, CONTROL_AREA, OWNER, OWNER_KEY, APPROVAL_GROUP, PRIMARY_EVIDENCE,
     SOURCE_OBJECTS, RISK_IF_MISSING, DBA_DECISION, AUTOMATION_BOUNDARY, MATCH_PRIORITY)
VALUES
    (src.CONTROL_ID, src.CONTROL_AREA, src.OWNER, src.OWNER_KEY, src.APPROVAL_GROUP,
     src.PRIMARY_EVIDENCE, src.SOURCE_OBJECTS, src.RISK_IF_MISSING, src.DBA_DECISION,
     src.AUTOMATION_BOUNDARY, src.MATCH_PRIORITY);

CREATE TABLE IF NOT EXISTS {evidence_fqn} (
    EVIDENCE_ID          NUMBER AUTOINCREMENT PRIMARY KEY,
    CAPTURED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONTROL_ID           VARCHAR(200),
    CONTROL_AREA         VARCHAR(200),
    EVIDENCE_SURFACE     VARCHAR(200),
    SOURCE_TYPE          VARCHAR(200),
    ENTITY_TYPE          VARCHAR(200),
    ENTITY_NAME          VARCHAR(500),
    COMPANY              VARCHAR(100),
    ENVIRONMENT          VARCHAR(100),
    SEVERITY             VARCHAR(40),
    FINDING              VARCHAR(4000),
    DBA_ACTION           VARCHAR(4000),
    OWNER                VARCHAR(200),
    OWNER_EMAIL          VARCHAR(500),
    APPROVAL_GROUP       VARCHAR(200),
    APPROVAL_STATUS      VARCHAR(100),
    TICKET_ID            VARCHAR(200),
    SOURCE_OBJECTS       VARCHAR(1000),
    SOURCE_FRESHNESS     VARCHAR(200),
    EVIDENCE_CONFIDENCE  VARCHAR(200),
    VERIFICATION_QUERY   VARCHAR(8000),
    VERIFICATION_RESULT  VARCHAR(8000),
    AUTOMATION_BOUNDARY  VARCHAR(2000),
    ACTION_ID            VARCHAR(64),
    SOURCE_QUERY_ID      VARCHAR(200),
    RAW_EVIDENCE         VARIANT,
    CAPTURED_BY          VARCHAR(200) DEFAULT CURRENT_USER(),
    NOTES                VARCHAR(4000)
);

CREATE OR REPLACE VIEW {latest_fqn} AS
SELECT *
FROM {evidence_fqn}
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY COALESCE(CONTROL_ID, CONTROL_AREA), COALESCE(ENTITY_NAME, EVIDENCE_SURFACE), COALESCE(EVIDENCE_SURFACE, SOURCE_TYPE)
    ORDER BY CAPTURED_AT DESC, EVIDENCE_ID DESC
) = 1;

CREATE OR REPLACE VIEW {coverage_fqn} AS
SELECT
    r.CONTROL_ID,
    r.CONTROL_AREA,
    r.OWNER,
    r.OWNER_KEY,
    r.APPROVAL_GROUP,
    r.PRIMARY_EVIDENCE,
    r.SOURCE_OBJECTS,
    r.RISK_IF_MISSING,
    r.DBA_DECISION,
    r.AUTOMATION_BOUNDARY,
    r.MATCH_PRIORITY,
    e.CAPTURED_AT AS LAST_EVIDENCE_AT,
    e.EVIDENCE_SURFACE,
    e.SOURCE_TYPE,
    e.ENTITY_NAME,
    e.SEVERITY,
    e.FINDING,
    e.APPROVAL_STATUS,
    e.TICKET_ID,
    e.VERIFICATION_RESULT,
    CASE
      WHEN e.EVIDENCE_ID IS NULL THEN 'Evidence Not Captured'
      WHEN UPPER(COALESCE(e.SEVERITY, '')) IN ('CRITICAL', 'HIGH')
       AND UPPER(COALESCE(e.APPROVAL_STATUS, '')) NOT IN ('APPROVED', 'NOT REQUIRED', 'VERIFIED')
        THEN 'Action Open'
      WHEN UPPER(COALESCE(e.VERIFICATION_RESULT, '')) = '' THEN 'Proof Needed'
      ELSE 'Evidence Captured'
    END AS COVERAGE_STATE
FROM {control_fqn} r
LEFT JOIN {latest_fqn} e
  ON UPPER(COALESCE(e.CONTROL_ID, e.CONTROL_AREA)) IN (UPPER(r.CONTROL_ID), UPPER(r.CONTROL_AREA))
WHERE COALESCE(r.IS_ACTIVE, TRUE);"""


def _has_text(value: object) -> bool:
    return str(value or "").strip() != ""


def _first_text(row: Mapping | pd.Series, *keys: str, default: str = "") -> str:
    for key in keys:
        try:
            if key in row and _has_text(row.get(key)):
                return str(row.get(key)).strip()
            upper = str(key).upper()
            if upper in row and _has_text(row.get(upper)):
                return str(row.get(upper)).strip()
        except Exception:
            continue
    return default


def _scope_runtime_frame(frame: pd.DataFrame, company: str, environment: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    scoped = _upper_frame(frame)
    db_col = next((col for col in ("DATABASE_NAME", "AGENT_DATABASE_NAME") if col in scoped.columns), "")
    if db_col:
        has_db = scoped[db_col].fillna("").astype(str).str.strip() != ""
        allowed = scoped[db_col].apply(lambda value: company_value_allowed(value, "database", company))
        env_allowed = scoped[db_col].apply(lambda value: environment_value_allowed(value, environment, company))
        scoped = scoped[(~has_db) | (allowed & env_allowed)].copy()
    user_filter = str(st.session_state.get("global_user", "") or "").strip()
    if user_filter and user_filter.upper() not in {"ALL", "ANY"} and "USER_NAME" in scoped.columns:
        scoped = scoped[scoped["USER_NAME"].fillna("").astype(str).str.upper() == user_filter.upper()].copy()
    role_filter = str(st.session_state.get("global_role", "") or "").strip()
    if role_filter and role_filter.upper() not in {"ALL", "ANY"} and "ROLE_NAME" in scoped.columns:
        scoped = scoped[scoped["ROLE_NAME"].fillna("").astype(str).str.upper() == role_filter.upper()].copy()
    db_filter = str(st.session_state.get("global_database", "") or "").strip()
    if db_filter and db_filter.upper() not in {"ALL", "ANY"} and db_col:
        scoped = scoped[scoped[db_col].fillna("").astype(str).str.upper() == db_filter.upper()].copy()
    return scoped


def _severity_rank(value: object) -> int:
    order = {"Critical": 0, "High": 1, "Medium": 2, "Watch": 3, "Low": 4, "Info": 5}
    return order.get(str(value or "Info"), 9)


def _owner_context(row: Mapping | pd.Series, entity: str, entity_type: str, category: str) -> dict:
    directory = load_owner_directory("Architecture Readiness")
    owner_seed = {
        "AI_AGENT": "DBA / AI Governance",
        "AI_USAGE": "DBA / FinOps",
        "MCP_SERVER": "DBA / AI Governance",
        "OPENFLOW": "DBA / Integration Platform",
        "SEMANTIC_TRUST": "DBA / Analytics Governance",
    }.get(entity_type, "DBA / Platform Architecture")
    return resolve_owner_context(
        row,
        directory=directory,
        entity=entity,
        entity_type=entity_type,
        owner=owner_seed,
        category=category,
        alert_type="Architecture Readiness",
    )


def build_forward_platform_control_register() -> pd.DataFrame:
    """Return the manual forward-platform control register."""
    frame = pd.DataFrame([{str(k).upper(): v for k, v in item.items()} for item in FORWARD_PLATFORM_CONTROLS])
    if frame.empty:
        return frame
    ordered = [
        "CONTROL_AREA",
        "CONTROL_ID",
        "OWNER",
        "OWNER_KEY",
        "APPROVAL_GROUP",
        "PRIMARY_EVIDENCE",
        "SOURCE_OBJECTS",
        "RISK_IF_MISSING",
        "DBA_DECISION",
        "AUTOMATION_BOUNDARY",
        "MATCH_PRIORITY",
    ]
    for col in ordered:
        if col not in frame.columns:
            frame[col] = ""
    return frame[ordered].sort_values(["MATCH_PRIORITY", "CONTROL_AREA"], ascending=[False, True])


def classify_agent_mcp_inventory(
    frame: pd.DataFrame,
    *,
    source_type: str,
    company: str = "ALL",
    environment: str = "ALL",
) -> pd.DataFrame:
    """Annotate SHOW AGENTS / SHOW MCP SERVERS output with DBA governance actions."""
    raw = _scope_runtime_frame(frame, company, environment)
    if raw.empty:
        return raw
    rows = []
    source = str(source_type or "").upper()
    entity_type = "MCP_SERVER" if "MCP" in source else "AI_AGENT"
    source_label = "MCP Server" if entity_type == "MCP_SERVER" else "Cortex Agent"
    for _, row in raw.iterrows():
        name = _first_text(row, "NAME", default="UNKNOWN")
        database = _first_text(row, "DATABASE_NAME")
        schema = _first_text(row, "SCHEMA_NAME")
        owner_role = _first_text(row, "OWNER", "OWNER_ROLE")
        comment = _first_text(row, "COMMENT")
        entity = ".".join([part for part in (database, schema, name) if part]) or name
        owner_upper = owner_role.upper()
        admin_owned = any(token in owner_upper for token in ADMIN_ROLE_TOKENS)
        missing_comment = not comment
        if entity_type == "MCP_SERVER":
            if admin_owned:
                severity = "Critical"
                finding = "MCP server is owned by a privileged admin role."
            elif missing_comment:
                severity = "High"
                finding = "MCP server lacks a purpose/comment for tool-scope review."
            else:
                severity = "Medium"
                finding = "MCP server requires owner, tool-scope, and blast-radius review."
            action = "Document approved tools, allowed roles, data scope, owner, and rollback path before production use."
            proof_sql = "SHOW MCP SERVERS IN ACCOUNT;"
        else:
            if admin_owned:
                severity = "High"
                finding = "Cortex Agent is owned by a privileged admin role."
            elif missing_comment:
                severity = "Medium"
                finding = "Cortex Agent lacks a purpose/comment for governance review."
            else:
                severity = "Low"
                finding = "Cortex Agent is visible; verify owner, semantic source, and usage."
            action = "Confirm owner, semantic source, tool inventory, role scope, and support route before trusted use."
            proof_sql = "SHOW AGENTS IN ACCOUNT;"
        context = _owner_context(row, entity, entity_type, "Agent & MCP Governance")
        rows.append({
            **row.to_dict(),
            "SOURCE_TYPE": source_label,
            "ENTITY_TYPE": entity_type,
            "ENTITY_NAME": entity,
            "DATABASE_NAME": database,
            "SCHEMA_NAME": schema,
            "OWNER_ROLE": owner_role,
            "SEVERITY": severity,
            "FINDING": finding,
            "DBA_ACTION": action,
            "APPROVAL_REQUIRED": "Yes" if severity in {"Critical", "High", "Medium"} else "No",
            "APPROVAL_GROUP": context.get("APPROVAL_GROUP", ""),
            "OWNER": context.get("OWNER", ""),
            "OWNER_EMAIL": context.get("OWNER_EMAIL", ""),
            "ONCALL_PRIMARY": context.get("ONCALL_PRIMARY", ""),
            "ONCALL_SECONDARY": context.get("ONCALL_SECONDARY", ""),
            "ESCALATION_TARGET": context.get("ESCALATION_TARGET", ""),
            "OWNER_SOURCE": context.get("OWNER_SOURCE", ""),
            "OWNER_EVIDENCE": context.get("OWNER_EVIDENCE", ""),
            "PROOF_SQL": proof_sql,
            "VERIFICATION_QUERY": proof_sql,
            "QUEUE_READINESS": "Ready to Queue" if context.get("OWNER_EMAIL") else "Owner Route Gap",
        })
    annotated = pd.DataFrame(rows)
    annotated["_SEVERITY_RANK"] = annotated["SEVERITY"].apply(_severity_rank)
    return annotated.sort_values(["_SEVERITY_RANK", "ENTITY_NAME"]).drop(columns=["_SEVERITY_RANK"])


def load_agent_mcp_inventory(session, company: str = "ALL", environment: str = "ALL") -> pd.DataFrame:
    """Load visible Cortex Agents and MCP servers without scanning history views."""
    frames = []
    agents = classify_agent_mcp_inventory(
        show_to_df(session, "SHOW AGENTS IN ACCOUNT"),
        source_type="Cortex Agent",
        company=company,
        environment=environment,
    )
    if agents is not None and not agents.empty:
        frames.append(agents)
    mcp = classify_agent_mcp_inventory(
        show_to_df(session, "SHOW MCP SERVERS IN ACCOUNT"),
        source_type="MCP Server",
        company=company,
        environment=environment,
    )
    if mcp is not None and not mcp.empty:
        frames.append(mcp)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _ai_usage_query(
    session,
    object_name: str,
    source_label: str,
    days: int,
    row_limit: int,
) -> str:
    requested = [
        "START_TIME",
        "END_TIME",
        "USER_NAME",
        "AGENT_DATABASE_NAME",
        "AGENT_SCHEMA_NAME",
        "AGENT_NAME",
        "TOKEN_CREDITS",
        "TOKENS",
        "METADATA",
        "SNOWFLAKE_INTELLIGENCE_NAME",
    ]
    cols = set(filter_existing_columns(session, object_name, requested))
    if "START_TIME" not in cols or "USER_NAME" not in cols:
        return ""
    entity_expr = "agent_name" if "AGENT_NAME" in cols else "NULL::VARCHAR"
    if "SNOWFLAKE_INTELLIGENCE_NAME" in cols:
        entity_expr = "COALESCE(snowflake_intelligence_name, agent_name)"
    database_expr = "agent_database_name" if "AGENT_DATABASE_NAME" in cols else "NULL::VARCHAR"
    schema_expr = "agent_schema_name" if "AGENT_SCHEMA_NAME" in cols else "NULL::VARCHAR"
    token_credit_expr = "SUM(COALESCE(token_credits, 0))" if "TOKEN_CREDITS" in cols else "0::FLOAT"
    token_expr = "SUM(COALESCE(tokens, 0))" if "TOKENS" in cols else "0::FLOAT"
    role_expr = "COALESCE(TO_VARCHAR(metadata:role_name), '')" if "METADATA" in cols else "''"
    interface_expr = (
        "COALESCE(TO_VARCHAR(metadata:interaction_interface), '')"
        if "METADATA" in cols
        else "''"
    )
    ai_func_expr = (
        "SUM(COALESCE(TRY_TO_DOUBLE(metadata:ai_functions_credits::STRING), 0))"
        if "METADATA" in cols
        else "0::FLOAT"
    )
    filters = get_global_filter_clause(
        date_col="start_time",
        wh_col="",
        user_col="user_name",
        role_col="",
        db_col="agent_database_name" if "AGENT_DATABASE_NAME" in cols else "",
    )
    return f"""
        SELECT
            '{source_label}' AS source_type,
            {database_expr} AS database_name,
            {schema_expr} AS schema_name,
            {entity_expr} AS entity_name,
            user_name,
            {role_expr} AS role_name,
            {interface_expr} AS interface_name,
            COUNT(*) AS requests,
            ROUND({token_credit_expr}, 3) AS token_credits,
            ROUND({token_expr}, 0) AS tokens,
            ROUND({ai_func_expr}, 3) AS ai_function_credits,
            MAX(start_time) AS last_seen
        FROM {object_name}
        WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {filters}
        GROUP BY 1,2,3,4,5,6,7
        ORDER BY token_credits DESC, requests DESC
        LIMIT {int(row_limit)}
    """


def classify_ai_usage_guardrails(
    frame: pd.DataFrame,
    *,
    company: str = "ALL",
    environment: str = "ALL",
) -> pd.DataFrame:
    """Classify AI usage rows into DBA guardrail actions."""
    raw = _scope_runtime_frame(frame, company, environment)
    if raw.empty:
        return raw
    credit_watch = safe_float(THRESHOLDS.get("ai_token_credit_watch", 25.0), 25.0)
    request_watch = safe_int(THRESHOLDS.get("ai_request_watch", 1000), 1000)
    rows = []
    for _, row in raw.iterrows():
        entity = _first_text(row, "ENTITY_NAME", default="Unknown AI surface")
        role = _first_text(row, "ROLE_NAME")
        interface = _first_text(row, "INTERFACE_NAME")
        source = _first_text(row, "SOURCE_TYPE", default="AI usage")
        token_credits = safe_float(row.get("TOKEN_CREDITS"))
        requests = safe_int(row.get("REQUESTS"))
        ai_function_credits = safe_float(row.get("AI_FUNCTION_CREDITS"))
        role_upper = role.upper()
        interface_upper = interface.upper()
        admin_role = any(token in role_upper for token in ADMIN_ROLE_TOKENS)
        external_interface = any(token in interface_upper for token in EXTERNAL_INTERFACE_TOKENS)
        if admin_role and token_credits > 0:
            severity = "Critical"
            finding = "AI usage is running under a privileged admin role."
        elif token_credits >= credit_watch:
            severity = "High"
            finding = f"AI token-credit usage exceeds the DBA watch threshold ({credit_watch:g})."
        elif external_interface:
            severity = "High"
            finding = "AI usage is coming through an external or collaboration interface."
        elif requests >= request_watch:
            severity = "Medium"
            finding = f"AI request volume exceeds the DBA watch threshold ({request_watch:,})."
        elif ai_function_credits > 0:
            severity = "Medium"
            finding = "AI function credits are attached to this usage path."
        else:
            severity = "Low"
            finding = "AI usage is visible; keep owner and budget review attached."
        action = (
            "Assign owner, budget lane, approved role, source data scope, and proof query before expanding usage."
            if severity in {"Critical", "High", "Medium"}
            else "Keep usage in periodic review and verify owner/budget tags before production promotion."
        )
        context = _owner_context(row, entity, "AI_USAGE", "AI Spend & Token Guardrails")
        proof_sql = (
            "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY "
            "WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP()) ORDER BY token_credits DESC LIMIT 100; "
            "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY "
            "WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP()) ORDER BY token_credits DESC LIMIT 100;"
        )
        rows.append({
            **row.to_dict(),
            "ENTITY_TYPE": "AI_USAGE",
            "ENTITY_NAME": entity,
            "SOURCE_TYPE": source,
            "SEVERITY": severity,
            "FINDING": finding,
            "DBA_ACTION": action,
            "APPROVAL_REQUIRED": "Yes" if severity in {"Critical", "High", "Medium"} else "No",
            "APPROVAL_GROUP": context.get("APPROVAL_GROUP", ""),
            "OWNER": context.get("OWNER", ""),
            "OWNER_EMAIL": context.get("OWNER_EMAIL", ""),
            "ONCALL_PRIMARY": context.get("ONCALL_PRIMARY", ""),
            "ONCALL_SECONDARY": context.get("ONCALL_SECONDARY", ""),
            "ESCALATION_TARGET": context.get("ESCALATION_TARGET", ""),
            "OWNER_SOURCE": context.get("OWNER_SOURCE", ""),
            "OWNER_EVIDENCE": context.get("OWNER_EVIDENCE", ""),
            "PROOF_SQL": proof_sql,
            "VERIFICATION_QUERY": proof_sql,
            "QUEUE_READINESS": "Ready to Queue" if context.get("OWNER_EMAIL") else "Owner Route Gap",
        })
    annotated = pd.DataFrame(rows)
    annotated["_SEVERITY_RANK"] = annotated["SEVERITY"].apply(_severity_rank)
    return annotated.sort_values(
        ["_SEVERITY_RANK", "TOKEN_CREDITS", "REQUESTS"],
        ascending=[True, False, False],
    ).drop(columns=["_SEVERITY_RANK"])


def load_ai_usage_guardrails(
    session,
    days: int = 7,
    row_limit: int = 100,
    company: str = "ALL",
    environment: str = "ALL",
) -> pd.DataFrame:
    """Load Cortex Agent and Snowflake Intelligence usage guardrail rows."""
    frames = []
    query_specs = (
        ("SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY", "Cortex Agent Usage"),
        ("SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY", "Snowflake Intelligence Usage"),
    )
    for object_name, label in query_specs:
        sql = _ai_usage_query(session, object_name, label, days, row_limit)
        if not sql:
            continue
        df = run_query(
            sql,
            ttl_key=f"arch_ai_usage_{label.replace(' ', '_').lower()}_{days}_{row_limit}",
            tier="historical",
            section="Architecture Readiness",
        )
        if df is not None and not df.empty:
            frames.append(df)
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return classify_ai_usage_guardrails(raw, company=company, environment=environment)


def classify_openflow_operations(
    frame: pd.DataFrame,
    *,
    company: str = "ALL",
    environment: str = "ALL",
) -> pd.DataFrame:
    raw = _scope_runtime_frame(frame, company, environment)
    if raw.empty:
        return raw
    credit_watch = safe_float(THRESHOLDS.get("openflow_credit_watch", 25.0), 25.0)
    rows = []
    for _, row in raw.iterrows():
        runtime = _first_text(row, "RUNTIME_NAME", default="Unknown Openflow runtime")
        data_plane = _first_text(row, "DATA_PLANE_NAME")
        entity = f"{data_plane} / {runtime}" if data_plane else runtime
        credits = safe_float(row.get("TOTAL_CREDITS"))
        runtime_type = _first_text(row, "RUNTIME_TYPE")
        data_plane_type = _first_text(row, "DATA_PLANE_TYPE")
        if credits >= credit_watch:
            severity = "High"
            finding = f"Openflow runtime credits exceed the DBA watch threshold ({credit_watch:g})."
        elif "BYOC" in data_plane_type.upper():
            severity = "Medium"
            finding = "BYOC Openflow deployment needs explicit secret, network, and recovery evidence."
        elif not runtime_type:
            severity = "Medium"
            finding = "Openflow runtime type is not visible to this role."
        else:
            severity = "Low"
            finding = "Openflow usage is visible; keep runtime owner and recovery plan attached."
        action = "Assign runtime owner, data source/destination, authentication strategy, secret owner, recovery step, and cost threshold."
        context = _owner_context(row, entity, "OPENFLOW", "Openflow Operations")
        proof_sql = (
            "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.OPENFLOW_USAGE_HISTORY "
            "WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP()) "
            "ORDER BY runtime_credits_used DESC LIMIT 100;"
        )
        rows.append({
            **row.to_dict(),
            "SOURCE_TYPE": "Openflow Usage",
            "ENTITY_TYPE": "OPENFLOW",
            "ENTITY_NAME": entity,
            "SEVERITY": severity,
            "FINDING": finding,
            "DBA_ACTION": action,
            "APPROVAL_REQUIRED": "Yes" if severity in {"High", "Medium"} else "No",
            "APPROVAL_GROUP": context.get("APPROVAL_GROUP", ""),
            "OWNER": context.get("OWNER", ""),
            "OWNER_EMAIL": context.get("OWNER_EMAIL", ""),
            "ONCALL_PRIMARY": context.get("ONCALL_PRIMARY", ""),
            "ONCALL_SECONDARY": context.get("ONCALL_SECONDARY", ""),
            "ESCALATION_TARGET": context.get("ESCALATION_TARGET", ""),
            "OWNER_SOURCE": context.get("OWNER_SOURCE", ""),
            "OWNER_EVIDENCE": context.get("OWNER_EVIDENCE", ""),
            "PROOF_SQL": proof_sql,
            "VERIFICATION_QUERY": proof_sql,
            "QUEUE_READINESS": "Ready to Queue" if context.get("OWNER_EMAIL") else "Owner Route Gap",
        })
    annotated = pd.DataFrame(rows)
    annotated["_SEVERITY_RANK"] = annotated["SEVERITY"].apply(_severity_rank)
    return annotated.sort_values(
        ["_SEVERITY_RANK", "TOTAL_CREDITS", "HOURS_REPORTED"],
        ascending=[True, False, False],
    ).drop(columns=["_SEVERITY_RANK"])


def load_openflow_operations(
    session,
    days: int = 7,
    row_limit: int = 100,
    company: str = "ALL",
    environment: str = "ALL",
) -> pd.DataFrame:
    """Load Openflow runtime usage if the account exposes the usage view."""
    object_name = "SNOWFLAKE.ACCOUNT_USAGE.OPENFLOW_USAGE_HISTORY"
    cols = set(filter_existing_columns(
        session,
        object_name,
        [
            "START_TIME",
            "END_TIME",
            "DATA_PLANE_NAME",
            "DATA_PLANE_TYPE",
            "DATA_PLANE_CREDITS_USED",
            "RUNTIME_NAME",
            "RUNTIME_TYPE",
            "RUNTIME_CREDITS_USED",
        ],
    ))
    if "START_TIME" not in cols:
        return pd.DataFrame()
    data_plane_credit_expr = "SUM(COALESCE(data_plane_credits_used, 0))" if "DATA_PLANE_CREDITS_USED" in cols else "0::FLOAT"
    runtime_credit_expr = "SUM(COALESCE(runtime_credits_used, 0))" if "RUNTIME_CREDITS_USED" in cols else "0::FLOAT"
    data_plane_name_expr = "data_plane_name" if "DATA_PLANE_NAME" in cols else "NULL::VARCHAR"
    data_plane_type_expr = "data_plane_type" if "DATA_PLANE_TYPE" in cols else "NULL::VARCHAR"
    runtime_name_expr = "runtime_name" if "RUNTIME_NAME" in cols else "NULL::VARCHAR"
    runtime_type_expr = "runtime_type" if "RUNTIME_TYPE" in cols else "NULL::VARCHAR"
    df = run_query(f"""
        SELECT
            {data_plane_name_expr} AS data_plane_name,
            {data_plane_type_expr} AS data_plane_type,
            {runtime_name_expr} AS runtime_name,
            {runtime_type_expr} AS runtime_type,
            COUNT(*) AS hours_reported,
            ROUND({data_plane_credit_expr}, 3) AS data_plane_credits,
            ROUND({runtime_credit_expr}, 3) AS runtime_credits,
            ROUND(({data_plane_credit_expr}) + ({runtime_credit_expr}), 3) AS total_credits,
            MAX(start_time) AS last_seen
        FROM {object_name}
        WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        GROUP BY 1,2,3,4
        ORDER BY total_credits DESC
        LIMIT {int(row_limit)}
    """, ttl_key=f"arch_openflow_{days}_{row_limit}", tier="historical", section="Architecture Readiness")
    return classify_openflow_operations(df, company=company, environment=environment)


def build_horizon_semantic_readiness_from_availability(records: Iterable[Mapping]) -> pd.DataFrame:
    rows = []
    for record in records:
        available = bool(record.get("AVAILABLE"))
        mandatory = bool(record.get("MANDATORY"))
        control_area = str(record.get("CONTROL_AREA") or "Horizon Governance Readiness")
        surface = str(record.get("SURFACE") or record.get("OBJECT_NAME") or "Governance surface")
        object_name = str(record.get("OBJECT_NAME") or "")
        column_count = safe_int(record.get("COLUMN_COUNT"))
        if available:
            severity = "Low"
            state = "Ready"
            finding = f"{surface} metadata is visible to the active role."
        elif mandatory:
            severity = "High"
            state = "Not Visible"
            finding = f"{surface} evidence is not visible; governance proof may be incomplete."
        else:
            severity = "Medium"
            state = "Not Visible"
            finding = f"{surface} is not visible; track as an adoption/readiness gap if the capability is used."
        if "Semantic Trust" in control_area:
            owner = "DBA / Analytics Governance"
            approval_group = "Analytics Owner / DBA Lead"
        elif "AI Change" in control_area:
            owner = "DBA Change Owner"
            approval_group = "Change Advisory / DBA Lead"
        elif "BCDR" in control_area:
            owner = "DBA / Platform Architecture"
            approval_group = "DBA Lead / Infrastructure Owner"
        elif "Horizon" in control_area:
            owner = "DBA / Data Governance"
            approval_group = "Data Governance Lead / DBA Lead"
        else:
            owner = "DBA / Platform Architecture"
            approval_group = "DBA Lead"
        rows.append({
            "CONTROL_AREA": control_area,
            "SOURCE_TYPE": "Horizon / Semantic Probe",
            "ENTITY_TYPE": "GOVERNANCE_VIEW",
            "ENTITY_NAME": surface,
            "OBJECT_NAME": object_name,
            "STATE": state,
            "SEVERITY": severity,
            "MANDATORY": "Yes" if mandatory else "No",
            "COLUMN_COUNT": column_count,
            "FINDING": finding,
            "DBA_ACTION": str(record.get("DBA_ACTION") or "Document owner, proof, and adoption decision."),
            "APPROVAL_REQUIRED": "Yes" if severity in {"High", "Medium"} else "No",
            "OWNER": owner,
            "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
            "APPROVAL_GROUP": approval_group,
            "QUEUE_READINESS": "Ready to Queue" if severity in {"High", "Medium"} else "Observe",
            "PROOF_SQL": f"SELECT * FROM {object_name} LIMIT 0;" if object_name else "",
            "VERIFICATION_QUERY": f"SELECT * FROM {object_name} LIMIT 0;" if object_name else "",
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["_SEVERITY_RANK"] = frame["SEVERITY"].apply(_severity_rank)
    return frame.sort_values(["_SEVERITY_RANK", "CONTROL_AREA", "ENTITY_NAME"]).drop(columns=["_SEVERITY_RANK"])


def load_horizon_semantic_readiness(session) -> pd.DataFrame:
    """Probe governance/semantic/account-usage surfaces with LIMIT 0 metadata calls."""
    records = []
    for probe in HORIZON_SEMANTIC_PROBES:
        object_name = probe["OBJECT_NAME"]
        try:
            columns = get_available_columns(session, object_name)
            available = True
        except Exception:
            columns = set()
            available = False
        records.append({
            **probe,
            "AVAILABLE": available,
            "COLUMN_COUNT": len(columns),
        })
    return build_horizon_semantic_readiness_from_availability(records)


def build_platform_futures_board(
    frames: Iterable[pd.DataFrame | None],
    *,
    include_low: bool = False,
) -> pd.DataFrame:
    """Consolidate loaded forward-platform evidence into one prioritized board."""
    rows = []
    for frame in frames:
        if frame is None or getattr(frame, "empty", True):
            continue
        view = _upper_frame(frame)
        for _, row in view.iterrows():
            severity = _first_text(row, "SEVERITY", default="Info")
            if not include_low and severity not in {"Critical", "High", "Medium"}:
                continue
            rows.append({
                "CONTROL_AREA": _first_text(row, "CONTROL_AREA", "SOURCE_TYPE", default="Platform Futures"),
                "SEVERITY": severity,
                "SOURCE_TYPE": _first_text(row, "SOURCE_TYPE", default="Platform Futures"),
                "ENTITY_TYPE": _first_text(row, "ENTITY_TYPE", default="Platform"),
                "ENTITY_NAME": _first_text(row, "ENTITY_NAME", "OBJECT_NAME", default="Platform future control"),
                "FINDING": _first_text(row, "FINDING", default="Open forward-platform control item."),
                "DBA_ACTION": _first_text(row, "DBA_ACTION", default="Assign owner, evidence, approval, and verification."),
                "OWNER": _first_text(row, "OWNER", default="DBA / Platform Architecture"),
                "OWNER_EMAIL": _first_text(row, "OWNER_EMAIL"),
                "APPROVAL_GROUP": _first_text(row, "APPROVAL_GROUP", default="DBA Lead"),
                "APPROVAL_REQUIRED": _first_text(row, "APPROVAL_REQUIRED", default="Yes"),
                "QUEUE_READINESS": _first_text(row, "QUEUE_READINESS", default="Ready to Queue"),
                "PROOF_SQL": _first_text(row, "PROOF_SQL", "VERIFICATION_QUERY"),
                "VERIFICATION_QUERY": _first_text(row, "VERIFICATION_QUERY", "PROOF_SQL"),
            })
    board = pd.DataFrame(rows)
    if board.empty:
        return board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_severity_rank)
    return board.sort_values(["_SEVERITY_RANK", "CONTROL_AREA", "ENTITY_NAME"]).drop(columns=["_SEVERITY_RANK"])
