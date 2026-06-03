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
from .metadata import load_warehouse_inventory, show_to_df
from .owner_directory import load_owner_directory, resolve_owner_context
from .query import run_query, safe_identifier, sql_literal


PLATFORM_FUTURES_AREAS = (
    "Adaptive Compute Readiness",
    "Agent & MCP Governance",
    "Cortex Sense Context Governance",
    "CoWork Artifact Governance",
    "AI Spend & Token Guardrails",
    "AI Security Guardrails",
    "Openflow Operations",
    "Horizon Governance Readiness",
    "Semantic Trust & Verified Query Validation",
    "BCDR Drill Ledger",
    "AI Change Governance",
)

AGENTIC_AI_CONTROL_AREAS = (
    "Agent & MCP Governance",
    "Cortex Sense Context Governance",
    "CoWork Artifact Governance",
    "AI Spend & Token Guardrails",
    "AI Security Guardrails",
    "Semantic Trust & Verified Query Validation",
    "AI Change Governance",
)

AGENTIC_AI_SURFACE_CLASSES = {
    "Agent & MCP Governance": "Agent / Tooling",
    "Cortex Sense Context Governance": "Context Trust",
    "CoWork Artifact Governance": "Shared Artifact",
    "AI Spend & Token Guardrails": "Cost Control",
    "AI Security Guardrails": "Security",
    "Semantic Trust & Verified Query Validation": "Semantic Trust",
    "AI Change Governance": "Change Control",
}

PLATFORM_FUTURES_CONTROL_TABLE = "OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER"
PLATFORM_FUTURES_EVIDENCE_TABLE = "OVERWATCH_PLATFORM_FUTURES_EVIDENCE"
PLATFORM_FUTURES_LATEST_VIEW = "OVERWATCH_PLATFORM_FUTURES_EVIDENCE_LATEST_V"
PLATFORM_FUTURES_COVERAGE_VIEW = "OVERWATCH_PLATFORM_FUTURES_CONTROL_COVERAGE_V"

ADMIN_ROLE_TOKENS = ("ACCOUNTADMIN", "SECURITYADMIN", "ORGADMIN")
EXTERNAL_INTERFACE_TOKENS = ("EXTERNAL", "MICROSOFT_TEAMS", "TEAMS", "API")

PLATFORM_FUTURES_EXPERT_CRITERIA = {
    "Adaptive Compute Readiness": {
        "surfaces": ("Adaptive compute advisor",),
        "why": "Adaptive Compute can simplify warehouse tuning, but DBAs need owner-approved pilots, preview-limitation screening, and before/after cost-performance proof.",
    },
    "Agent & MCP Governance": {
        "surfaces": ("AI agent and MCP inventory",),
        "why": "Agentic tools need owner, role scope, tool scope, semantic source, blast-radius proof, and rollback evidence before production use.",
    },
    "Cortex Sense Context Governance": {
        "surfaces": ("Horizon and semantic trust", "AI agent and MCP inventory"),
        "why": "Cortex Sense can make agents more useful by sharing business context, but experts will expect owner, semantic certification, connector approval, citation policy, and regression-validation proof before broad trust.",
    },
    "CoWork Artifact Governance": {
        "surfaces": ("AI usage guardrails", "Horizon and semantic trust"),
        "why": "CoWork Artifacts turn AI outputs into reusable shared dashboards and knowledge, so DBA teams must prove certified data sources, sharing scope, access policy, freshness, and retirement controls.",
    },
    "AI Spend & Token Guardrails": {
        "surfaces": ("AI usage guardrails",),
        "why": "AI usage can create token-credit spend that is hard to defend without user, role, interface, owner, and budget evidence.",
    },
    "AI Security Guardrails": {
        "surfaces": ("AI security guardrails",),
        "why": "Production AI needs proof of prompt-injection guardrails, scoped Cortex privileges, and sensitive-data access report visibility before broad rollout.",
    },
    "Openflow Operations": {
        "surfaces": ("Openflow operations",),
        "why": "Managed data movement needs runtime owner, data-plane, secret/auth, failure, recovery, and cost evidence before expansion.",
    },
    "Horizon Governance Readiness": {
        "surfaces": ("Horizon and semantic trust",),
        "why": "Governance claims need visible classification, policy, access-history, lineage, Trust Center, and data-quality evidence.",
    },
    "Semantic Trust & Verified Query Validation": {
        "surfaces": ("Horizon and semantic trust",),
        "why": "Semantic models make answers look authoritative, so owners, certification, freshness, and verified query tests are mandatory.",
    },
    "BCDR Drill Ledger": {
        "surfaces": ("DR readiness", "Horizon and semantic trust"),
        "why": "DR cannot be trusted from configuration alone; experts expect RPO/RTO drill proof, failure notes, and recovery owner evidence.",
    },
    "AI Change Governance": {
        "surfaces": ("AI usage guardrails", "Horizon and semantic trust"),
        "why": "AI-assisted SQL and code must still pass ticket, review, rollback, and verification controls before DBA adoption.",
    },
}

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
        "CONTROL_AREA": "Semantic Trust & Verified Query Validation",
        "SURFACE": "Semantic Views",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_VIEWS",
        "MANDATORY": False,
        "DBA_ACTION": "Inventory semantic views and require owner, certification, and regression query evidence.",
    },
    {
        "CONTROL_AREA": "Semantic Trust & Verified Query Validation",
        "SURFACE": "Semantic Tables",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_TABLES",
        "MANDATORY": False,
        "DBA_ACTION": "Inventory semantic tables and validate freshness and ownership before agent trust.",
    },
    {
        "CONTROL_AREA": "Semantic Trust & Verified Query Validation",
        "SURFACE": "Semantic Metrics",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.SEMANTIC_METRICS",
        "MANDATORY": False,
        "DBA_ACTION": "Treat metric definitions as governed assets with owner, validation, and change evidence.",
    },
    {
        "CONTROL_AREA": "Cortex Sense Context Governance",
        "SURFACE": "Cortex Sense Context Inventory",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SENSE_CONTEXTS",
        "MANDATORY": False,
        "DBA_ACTION": "If Cortex Sense is enabled, require owner, certified business definitions, approved MCP connectors, citation policy, and regression validation before production agent use.",
    },
    {
        "CONTROL_AREA": "CoWork Artifact Governance",
        "SURFACE": "CoWork Artifact Inventory",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.COWORK_ARTIFACTS",
        "MANDATORY": False,
        "DBA_ACTION": "If CoWork Artifacts are enabled, require publisher, certified source, sharing scope, freshness SLA, sensitivity review, and retirement owner.",
    },
    {
        "CONTROL_AREA": "CoWork Artifact Governance",
        "SURFACE": "Snowflake Intelligence Usage",
        "OBJECT_NAME": "SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY",
        "MANDATORY": False,
        "DBA_ACTION": "Use Snowflake Intelligence usage as early evidence for who is creating or consuming CoWork outputs before artifact metadata is generally visible.",
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

AI_SECURITY_REPORT_PROBES = (
    {
        "SURFACE": "Sensitive Data Entitlement report",
        "OBJECT_NAME": "SNOWFLAKE.DATA_SECURITY.ENTITLEMENT_REPORT",
        "MANDATORY": True,
        "DBA_ACTION": "Enable and grant report visibility so DBA/security can prove who can access sensitive tables before AI expansion.",
    },
    {
        "SURFACE": "Sensitive Data Access report",
        "OBJECT_NAME": "SNOWFLAKE.DATA_SECURITY.ACCESS_REPORT",
        "MANDATORY": True,
        "DBA_ACTION": "Enable and grant report visibility so DBA/security can prove which users actually accessed sensitive tables.",
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


def _scope_warehouse_runtime_frame(frame: pd.DataFrame, company: str, environment: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    scoped = _upper_frame(frame)
    if "WAREHOUSE_NAME" in scoped.columns:
        has_wh = scoped["WAREHOUSE_NAME"].fillna("").astype(str).str.strip() != ""
        allowed = scoped["WAREHOUSE_NAME"].apply(lambda value: company_value_allowed(value, "warehouse", company))
        scoped = scoped[(~has_wh) | allowed].copy()
    if "DATABASE_NAME" in scoped.columns:
        has_db = scoped["DATABASE_NAME"].fillna("").astype(str).str.strip() != ""
        allowed = scoped["DATABASE_NAME"].apply(lambda value: company_value_allowed(value, "database", company))
        env_allowed = scoped["DATABASE_NAME"].apply(lambda value: environment_value_allowed(value, environment, company))
        scoped = scoped[(~has_db) | (allowed & env_allowed)].copy()
    wh_filter = str(st.session_state.get("global_warehouse", "") or "").strip()
    if wh_filter and wh_filter.upper() not in {"ALL", "ANY"} and "WAREHOUSE_NAME" in scoped.columns:
        scoped = scoped[scoped["WAREHOUSE_NAME"].fillna("").astype(str).str.upper() == wh_filter.upper()].copy()
    return scoped


def _severity_rank(value: object) -> int:
    order = {"Critical": 0, "High": 1, "Medium": 2, "Watch": 3, "Low": 4, "Info": 5}
    return order.get(str(value or "Info"), 9)


def _owner_context(row: Mapping | pd.Series, entity: str, entity_type: str, category: str) -> dict:
    directory = load_owner_directory("Architecture Readiness")
    owner_seed = {
        "ADAPTIVE_COMPUTE": "DBA / Platform Architecture",
        "AI_AGENT": "DBA / AI Governance",
        "AI_SECURITY": "DBA / AI Governance",
        "AI_USAGE": "DBA / FinOps",
        "MCP_SERVER": "DBA / AI Governance",
        "OPENFLOW": "DBA / Integration Platform",
        "SEMANTIC_TRUST": "DBA / Analytics Governance",
        "CORTEX_SENSE": "DBA / AI Governance",
        "COWORK_ARTIFACT": "DBA / Analytics Governance",
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
            "CONTROL_AREA": "Agent & MCP Governance",
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


def _truthy_setting(value: object) -> bool:
    text = str(value or "").strip().upper()
    return text in {"TRUE", "YES", "Y", "ON", "1"}


def _adaptive_compute_proof_sql(warehouse_name: str, days: int) -> str:
    wh_sql = sql_literal(warehouse_name, 300)
    days = max(1, min(int(days or 14), 90))
    return f"""SHOW WAREHOUSES LIKE {wh_sql};
SELECT warehouse_name, COUNT(*) AS query_count,
       ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_elapsed_time) / 1000, 2) AS p95_elapsed_sec,
       ROUND(SUM(COALESCE(queued_overload_time, 0) + COALESCE(queued_provisioning_time, 0) + COALESCE(queued_repair_time, 0)) / 1000, 2) AS queued_sec,
       ROUND(SUM(COALESCE(bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
  AND warehouse_name = {wh_sql}
GROUP BY warehouse_name;
SELECT warehouse_name, ROUND(SUM(credits_used), 3) AS credits_used
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
  AND warehouse_name = {wh_sql}
GROUP BY warehouse_name;"""


def classify_adaptive_compute_readiness(
    frame: pd.DataFrame,
    *,
    company: str = "ALL",
    environment: str = "ALL",
    days: int = 14,
) -> pd.DataFrame:
    """Rank standard warehouses for an owner-approved Adaptive Compute pilot."""
    raw = _scope_warehouse_runtime_frame(frame, company, environment)
    if raw.empty:
        return raw
    credit_watch = safe_float(THRESHOLDS.get("adaptive_compute_credit_watch", 25.0), 25.0)
    query_watch = safe_int(THRESHOLDS.get("adaptive_compute_query_watch", 500), 500)
    spill_watch = safe_float(THRESHOLDS.get("adaptive_compute_spill_watch_gb", 5.0), 5.0)
    queue_watch = safe_float(THRESHOLDS.get("queue_pressure", 5.0), 5.0)
    rows = []
    for _, row in raw.iterrows():
        warehouse = _first_text(row, "WAREHOUSE_NAME", "NAME", default="UNKNOWN_WAREHOUSE")
        warehouse_upper = warehouse.upper()
        size = _first_text(row, "WAREHOUSE_SIZE", "SIZE")
        size_upper = size.upper().replace(" ", "").replace("-", "")
        warehouse_type = _first_text(row, "WAREHOUSE_TYPE", "TYPE", "RESOURCE_CONSTRAINT")
        warehouse_type_upper = warehouse_type.upper()
        query_count = safe_int(row.get("QUERY_COUNT"))
        users = safe_int(row.get("USERS"))
        roles = safe_int(row.get("ROLES"))
        databases = safe_int(row.get("DATABASES"))
        credits = safe_float(row.get("CREDITS_30D") if "CREDITS_30D" in raw.columns else row.get("CREDITS_USED"))
        queued_sec = safe_float(row.get("QUEUED_SEC"))
        remote_spill_gb = safe_float(row.get("REMOTE_SPILL_GB"))
        p95_elapsed = safe_float(row.get("P95_ELAPSED_SEC"))
        repeated_queries = safe_int(row.get("REPEATED_QUERIES"))
        max_cluster = max(1, safe_int(row.get("MAX_CLUSTER_COUNT"), 1))
        auto_suspend = safe_int(row.get("AUTO_SUSPEND"))
        qas_enabled = _truthy_setting(row.get("ENABLE_QUERY_ACCELERATION") or row.get("QUERY_ACCELERATION"))
        pressure = queued_sec >= queue_watch or remote_spill_gb >= spill_watch or p95_elapsed >= 300
        material_spend = credits >= credit_watch
        steady_workload = query_count >= query_watch or repeated_queries >= max(50, int(query_watch / 5))
        manual_tuning_signal = max_cluster > 1 or qas_enabled
        preview_limited = (
            "SNOWPARK" in warehouse_type_upper
            or "INTERACTIVE" in warehouse_type_upper
            or size_upper in {"5XLARGE", "6XLARGE", "X5LARGE", "X6LARGE"}
        )
        app_execution = warehouse_upper in {"OVERWATCH_WH", "COMPUTE_WH"} or warehouse_upper.startswith("SYSTEM$STREAMLIT")
        low_signal = query_count < max(25, int(query_watch / 10)) and credits < max(1.0, credit_watch / 10)
        score = 45
        score += 18 if material_spend else 0
        score += 18 if pressure else 0
        score += 12 if steady_workload else 0
        score += 10 if manual_tuning_signal else 0
        score += 5 if users >= 3 or roles >= 3 else 0
        score -= 38 if preview_limited else 0
        score -= 32 if app_execution else 0
        score -= 18 if low_signal else 0
        readiness_score = max(0, min(100, int(round(score))))
        if preview_limited:
            decision = "Hold - Preview Limitation"
            severity = "High" if material_spend or pressure else "Medium"
            finding = "Warehouse has preview-limitation signals for Adaptive Compute conversion."
            action = "Keep this warehouse on its current engine until Snowflake support/region/type limitations are cleared and owner approval is recorded."
            queue_readiness = "Review Only"
        elif app_execution:
            decision = "Hold - App Execution"
            severity = "Medium"
            finding = "Warehouse is the OVERWATCH app/utility execution route; do not mix app runtime with business workload conversion tests."
            action = "Keep OVERWATCH_WH/COMPUTE_WH execution routes out of business workload conversion tests unless the OVERWATCH owner approves a separate benchmark and rollback window."
            queue_readiness = "Review Only"
        elif pressure and material_spend and steady_workload:
            decision = "Pilot Candidate"
            severity = "High"
            finding = "Warehouse has spend, workload volume, and pressure signals that justify an Adaptive Compute pilot review."
            action = "Open an owner-approved pilot: capture baseline p95, queue, spill, credits, user impact, and rollback plan before conversion."
            queue_readiness = "Ready to Queue"
        elif material_spend and (pressure or manual_tuning_signal or steady_workload):
            decision = "Pilot Candidate"
            severity = "Medium"
            finding = "Warehouse has enough spend and tuning signal to evaluate as a controlled Adaptive Compute pilot."
            action = "Validate workload class, owner, region/support status, and before/after cost-performance proof before any conversion."
            queue_readiness = "Ready to Queue"
        elif low_signal:
            decision = "No Move Yet"
            severity = "Low"
            finding = "Warehouse activity is too small to justify an Adaptive Compute pilot."
            action = "Leave unchanged; revisit when query volume, credit spend, queue, or spill evidence becomes material."
            queue_readiness = "Observe"
        else:
            decision = "Observe"
            severity = "Low"
            finding = "Warehouse does not show enough pressure to justify a conversion decision yet."
            action = "Keep collecting workload, cost, and owner evidence before proposing Adaptive Compute."
            queue_readiness = "Observe"
        context = _owner_context(row, warehouse, "ADAPTIVE_COMPUTE", "Adaptive Compute Readiness")
        proof_sql = _adaptive_compute_proof_sql(warehouse, days)
        rows.append({
            **row.to_dict(),
            "CONTROL_AREA": "Adaptive Compute Readiness",
            "SOURCE_TYPE": "Warehouse transition advisor",
            "ENTITY_TYPE": "ADAPTIVE_COMPUTE",
            "ENTITY_NAME": warehouse,
            "WAREHOUSE_NAME": warehouse,
            "QUERY_COUNT": query_count,
            "USERS": users,
            "ROLES": roles,
            "DATABASES": databases,
            "CREDITS_30D": credits,
            "QUEUED_SEC": queued_sec,
            "REMOTE_SPILL_GB": remote_spill_gb,
            "P95_ELAPSED_SEC": p95_elapsed,
            "REPEATED_QUERIES": repeated_queries,
            "SEVERITY": severity,
            "ADAPTIVE_DECISION": decision,
            "READINESS_SCORE": readiness_score,
            "PILOT_RANK": 100 - readiness_score if "Pilot Candidate" in decision else 200 - readiness_score,
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
            "QUEUE_READINESS": queue_readiness if context.get("OWNER_EMAIL") else "Owner Route Gap",
            "AUTOMATION_BOUNDARY": "Advisor only. Do not create, convert, or drop adaptive warehouses from dashboard automation.",
            "PROOF_SQL": proof_sql,
            "VERIFICATION_QUERY": proof_sql,
            "CONVERSION_BOUNDARY": "No automatic conversion; require off-peak pilot, owner approval, rollback proof, and before/after cost-performance verification.",
            "SOURCE_CONFIDENCE": "ACCOUNT_USAGE delayed plus live SHOW WAREHOUSES metadata",
        })
    annotated = pd.DataFrame(rows)
    annotated["_SEVERITY_RANK"] = annotated["SEVERITY"].apply(_severity_rank)
    return annotated.sort_values(
        ["_SEVERITY_RANK", "READINESS_SCORE", "CREDITS_30D", "QUERY_COUNT"],
        ascending=[True, False, False, False],
    ).drop(columns=["_SEVERITY_RANK"])


def load_adaptive_compute_readiness(
    session,
    days: int = 14,
    row_limit: int = 100,
    company: str = "ALL",
    environment: str = "ALL",
) -> pd.DataFrame:
    """Load bounded warehouse workload evidence for Adaptive Compute pilot review."""
    object_name = "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
    requested = [
        "START_TIME",
        "WAREHOUSE_NAME",
        "USER_NAME",
        "ROLE_NAME",
        "DATABASE_NAME",
        "TOTAL_ELAPSED_TIME",
        "QUERY_HASH",
        "EXECUTION_STATUS",
        "ERROR_CODE",
        "QUEUED_OVERLOAD_TIME",
        "QUEUED_PROVISIONING_TIME",
        "QUEUED_REPAIR_TIME",
        "BYTES_SPILLED_TO_REMOTE_STORAGE",
        "BYTES_SCANNED",
        "PERCENTAGE_SCANNED_FROM_CACHE",
    ]
    cols = set(filter_existing_columns(session, object_name, requested))
    if "START_TIME" not in cols or "WAREHOUSE_NAME" not in cols or "TOTAL_ELAPSED_TIME" not in cols:
        return pd.DataFrame()
    user_expr = "COUNT(DISTINCT q.user_name)" if "USER_NAME" in cols else "0"
    role_expr = "COUNT(DISTINCT q.role_name)" if "ROLE_NAME" in cols else "0"
    db_expr = "COUNT(DISTINCT q.database_name)" if "DATABASE_NAME" in cols else "0"
    if "ERROR_CODE" in cols:
        failure_expr = "q.error_code IS NOT NULL"
    elif "EXECUTION_STATUS" in cols:
        failure_expr = "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'"
    else:
        failure_expr = "FALSE"
    queue_terms = [
        f"COALESCE(q.{col.lower()}, 0)"
        for col in ("QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME", "QUEUED_REPAIR_TIME")
        if col in cols
    ]
    queue_expr = "SUM(" + " + ".join(queue_terms) + ") / 1000" if queue_terms else "0::FLOAT"
    spill_expr = (
        "SUM(COALESCE(q.bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in cols else "0::FLOAT"
    )
    scanned_expr = "SUM(COALESCE(q.bytes_scanned, 0)) / POWER(1024, 3)" if "BYTES_SCANNED" in cols else "0::FLOAT"
    cache_expr = (
        "SUM(COALESCE(q.bytes_scanned, 0) * COALESCE(q.percentage_scanned_from_cache, 0)) / NULLIF(SUM(COALESCE(q.bytes_scanned, 0)), 0)"
        if {"BYTES_SCANNED", "PERCENTAGE_SCANNED_FROM_CACHE"}.issubset(cols) else "NULL::FLOAT"
    )
    repeated_expr = "COUNT(*) - COUNT(DISTINCT q.query_hash)" if "QUERY_HASH" in cols else "0"
    filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name" if "USER_NAME" in cols else "",
        role_col="q.role_name" if "ROLE_NAME" in cols else "",
        db_col="q.database_name" if "DATABASE_NAME" in cols else "",
    )
    metrics = run_query(f"""
        WITH qh AS (
            SELECT
                q.warehouse_name,
                COUNT(*) AS query_count,
                {user_expr} AS users,
                {role_expr} AS roles,
                {db_expr} AS databases,
                SUM(IFF({failure_expr}, 1, 0)) AS failed_queries,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time) / 1000, 2) AS p95_elapsed_sec,
                ROUND({queue_expr}, 2) AS queued_sec,
                ROUND({spill_expr}, 2) AS remote_spill_gb,
                ROUND({scanned_expr}, 2) AS gb_scanned,
                ROUND({cache_expr}, 3) AS cache_ratio,
                {repeated_expr} AS repeated_queries,
                MAX(q.start_time) AS last_seen
            FROM {object_name} q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {filters}
            GROUP BY q.warehouse_name
        ),
        metering AS (
            SELECT
                warehouse_name,
                ROUND(SUM(credits_used), 3) AS credits_30d
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
            GROUP BY warehouse_name
        )
        SELECT
            qh.*,
            COALESCE(m.credits_30d, 0) AS credits_30d
        FROM qh
        LEFT JOIN metering m
          ON UPPER(m.warehouse_name) = UPPER(qh.warehouse_name)
        ORDER BY credits_30d DESC, query_count DESC
        LIMIT {int(row_limit)}
    """, ttl_key=f"arch_adaptive_compute_{days}_{row_limit}", tier="historical", section="Architecture Readiness")
    if metrics is None or metrics.empty:
        return pd.DataFrame()
    inventory = load_warehouse_inventory(session, company)
    if inventory is not None and not inventory.empty:
        inv = _upper_frame(inventory)
        if "NAME" in inv.columns:
            inv = inv.rename(columns={"NAME": "WAREHOUSE_NAME"})
        for col in [
            "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "STATE", "TYPE", "WAREHOUSE_TYPE",
            "RESOURCE_CONSTRAINT", "AUTO_SUSPEND", "AUTO_RESUME", "MIN_CLUSTER_COUNT",
            "MAX_CLUSTER_COUNT", "SCALING_POLICY", "ENABLE_QUERY_ACCELERATION", "COMMENT",
        ]:
            if col not in inv.columns:
                inv[col] = ""
        metrics = _upper_frame(metrics).merge(
            inv[[
                "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "STATE", "TYPE", "WAREHOUSE_TYPE",
                "RESOURCE_CONSTRAINT", "AUTO_SUSPEND", "AUTO_RESUME", "MIN_CLUSTER_COUNT",
                "MAX_CLUSTER_COUNT", "SCALING_POLICY", "ENABLE_QUERY_ACCELERATION", "COMMENT",
            ]],
            on="WAREHOUSE_NAME",
            how="left",
        )
    return classify_adaptive_compute_readiness(
        metrics,
        company=company,
        environment=environment,
        days=days,
    )


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
            "CONTROL_AREA": "AI Spend & Token Guardrails",
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


def _parameter_value(frame: pd.DataFrame | None, parameter_name: str) -> tuple[str, bool]:
    view = _upper_frame(frame)
    if view.empty:
        return "", False
    target = str(parameter_name or "").upper()
    for _, row in view.iterrows():
        key = _first_text(row, "KEY", "NAME", "PARAMETER_NAME")
        if key.upper() == target:
            return _first_text(row, "VALUE", "PARAMETER_VALUE", "DEFAULT", default=""), True
    if len(view) == 1:
        return _first_text(view.iloc[0], "VALUE", "PARAMETER_VALUE", "DEFAULT", default=""), True
    return "", False


def _ai_settings_guardrails_enabled(value: object) -> bool:
    text = str(value or "").upper()
    return "ADVANCED_PROMPT_INJECTION" in text and "ENABLED" in text and "TRUE" in text


def _ai_security_proof_sql(surface: str) -> str:
    surface_upper = str(surface or "").upper()
    if "AI_SETTINGS" in surface_upper:
        return "SHOW PARAMETERS LIKE 'AI_SETTINGS' IN ACCOUNT;"
    if "CORTEX_ENABLED_CROSS_REGION" in surface_upper or "CROSS" in surface_upper:
        return "SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;"
    if "PUBLIC" in surface_upper:
        return "SHOW GRANTS TO ROLE PUBLIC;"
    if "CORTEX_USER" in surface_upper:
        return "SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.CORTEX_USER;"
    if "AI_FUNCTIONS_USER" in surface_upper:
        return "SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.AI_FUNCTIONS_USER;"
    if "ENTITLEMENT" in surface_upper:
        return "SELECT * FROM SNOWFLAKE.DATA_SECURITY.ENTITLEMENT_REPORT LIMIT 0;"
    if "ACCESS" in surface_upper:
        return "SELECT * FROM SNOWFLAKE.DATA_SECURITY.ACCESS_REPORT LIMIT 0;"
    return (
        "SHOW PARAMETERS LIKE 'AI_SETTINGS' IN ACCOUNT; "
        "SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT; "
        "SHOW GRANTS TO ROLE PUBLIC;"
    )


def _ai_security_row(
    *,
    entity_name: str,
    source_type: str,
    severity: str,
    finding: str,
    action: str,
    entity_type: str = "AI_SECURITY",
    proof_sql: str = "",
    extra: Mapping | None = None,
) -> dict:
    context = _owner_context(extra or {}, entity_name, "AI_SECURITY", "AI Security Guardrails")
    proof = proof_sql or _ai_security_proof_sql(entity_name)
    return {
        **dict(extra or {}),
        "CONTROL_AREA": "AI Security Guardrails",
        "SOURCE_TYPE": source_type,
        "ENTITY_TYPE": entity_type,
        "ENTITY_NAME": entity_name,
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
        "QUEUE_READINESS": "Ready to Queue" if severity in {"Critical", "High", "Medium"} and context.get("OWNER_EMAIL") else "Observe",
        "AUTOMATION_BOUNDARY": "Readiness and queue only. Do not change account parameters or revoke/grant AI privileges from dashboard automation.",
        "PROOF_SQL": proof,
        "VERIFICATION_QUERY": proof,
    }


def _grant_blob(row: Mapping | pd.Series) -> str:
    try:
        values = row.to_dict().values() if isinstance(row, pd.Series) else row.values()
    except Exception:
        values = []
    return " ".join(str(value or "").upper() for value in values)


def _ai_public_grant_rows(frame: pd.DataFrame | None) -> list[dict]:
    view = _upper_frame(frame)
    if view.empty:
        return []
    rows = []
    ai_terms = ("USE AI FUNCTION", "USE AI FUNCTIONS", "CORTEX_USER", "AI_FUNCTIONS_USER", "CORTEX_EMBED_USER", "COPILOT_USER")
    for _, row in view.iterrows():
        blob = _grant_blob(row)
        if not any(term in blob for term in ai_terms):
            continue
        privilege = _first_text(row, "PRIVILEGE", default="AI/Cortex grant")
        granted_on = _first_text(row, "GRANTED_ON", default="ACCOUNT")
        grant_name = _first_text(row, "NAME", "GRANTED_NAME", default="")
        if "USE AI FUNCTIONS" in blob or "CORTEX_USER" in blob or "AI_FUNCTIONS_USER" in blob:
            severity = "Critical"
            finding = "PUBLIC has blanket AI/Cortex access visible in grants."
            action = "Replace PUBLIC AI access with approved DBA/security-owned roles and per-function grants after change approval."
        else:
            severity = "High"
            finding = "PUBLIC has AI-related access that needs explicit owner approval."
            action = "Validate the business need, scope the function access, and remove PUBLIC exposure through change control if not justified."
        rows.append(_ai_security_row(
            entity_name=f"PUBLIC {privilege} {grant_name}".strip(),
            source_type="PUBLIC AI grant",
            severity=severity,
            finding=finding,
            action=action,
            proof_sql="SHOW GRANTS TO ROLE PUBLIC;",
            extra={
                "GRANTED_ON": granted_on,
                "PRIVILEGE": privilege,
                "GRANT_NAME": grant_name,
                "GRANTEE_NAME": "PUBLIC",
            },
        ))
    return rows


def _database_role_public_grant_rows(frame: pd.DataFrame | None, role_name: str) -> list[dict]:
    view = _upper_frame(frame)
    if view.empty:
        return []
    rows = []
    for _, row in view.iterrows():
        blob = _grant_blob(row)
        if "PUBLIC" not in blob:
            continue
        rows.append(_ai_security_row(
            entity_name=f"SNOWFLAKE.{role_name} -> PUBLIC",
            source_type="Cortex database role grant",
            severity="Critical",
            finding=f"SNOWFLAKE.{role_name} database role is granted to PUBLIC.",
            action="Move Cortex access to named approved roles with owner, budget, model/function scope, and rollback proof before broad AI rollout.",
            proof_sql=f"SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.{role_name};",
            extra={
                "DATABASE_ROLE": f"SNOWFLAKE.{role_name}",
                "GRANTEE_NAME": "PUBLIC",
            },
        ))
    return rows


def classify_ai_security_guardrails(
    *,
    parameters: pd.DataFrame | None = None,
    public_grants: pd.DataFrame | None = None,
    cortex_user_grants: pd.DataFrame | None = None,
    ai_functions_user_grants: pd.DataFrame | None = None,
    report_records: Iterable[Mapping] | None = None,
    visibility_records: Iterable[Mapping] | None = None,
) -> pd.DataFrame:
    """Classify AI security posture without changing account parameters or grants."""
    rows = []
    ai_settings, ai_settings_visible = _parameter_value(parameters, "AI_SETTINGS")
    if _ai_settings_guardrails_enabled(ai_settings):
        rows.append(_ai_security_row(
            entity_name="Account AI_SETTINGS",
            source_type="Account parameter",
            severity="Low",
            finding="Cortex AI Guardrails advanced prompt-injection setting is visible as enabled.",
            action="Keep guardrail configuration under change control and review guardrail logs for false positives or attack patterns.",
            proof_sql="SHOW PARAMETERS LIKE 'AI_SETTINGS' IN ACCOUNT;",
            extra={"PARAMETER_NAME": "AI_SETTINGS", "PARAMETER_VALUE": ai_settings},
        ))
    else:
        severity = "High" if ai_settings_visible else "Medium"
        finding = (
            "AI_SETTINGS is visible but advanced prompt-injection guardrails are not enabled."
            if ai_settings_visible
            else "AI_SETTINGS is not visible to the active role, so guardrail proof is missing."
        )
        rows.append(_ai_security_row(
            entity_name="Account AI_SETTINGS",
            source_type="Account parameter",
            severity=severity,
            finding=finding,
            action="Review with ACCOUNTADMIN/security; enable or explicitly document the guardrail exception before production AI expansion.",
            proof_sql="SHOW PARAMETERS LIKE 'AI_SETTINGS' IN ACCOUNT;",
            extra={"PARAMETER_NAME": "AI_SETTINGS", "PARAMETER_VALUE": ai_settings},
        ))

    cross_region, cross_visible = _parameter_value(parameters, "CORTEX_ENABLED_CROSS_REGION")
    cross_upper = str(cross_region or "").upper()
    approved_cross = any(token in cross_upper for token in ("ANY_REGION", "AWS_US", "AWS_GLOBAL"))
    if approved_cross:
        rows.append(_ai_security_row(
            entity_name="CORTEX_ENABLED_CROSS_REGION",
            source_type="Account parameter",
            severity="Low",
            finding="Cross-region inference setting is visible in a guardrail-compatible value.",
            action="Keep the selected routing boundary tied to data-residency approval and AI model availability requirements.",
            proof_sql="SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;",
            extra={"PARAMETER_NAME": "CORTEX_ENABLED_CROSS_REGION", "PARAMETER_VALUE": cross_region},
        ))
    else:
        rows.append(_ai_security_row(
            entity_name="CORTEX_ENABLED_CROSS_REGION",
            source_type="Account parameter",
            severity="Medium",
            finding=(
                "Cross-region inference is disabled or not in an AI Guardrails-compatible value."
                if cross_visible
                else "Cross-region inference setting is not visible to the active role."
            ),
            action="Decide whether strict data residency or guardrail/model availability wins for each AI workload; record the approved boundary.",
            proof_sql="SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;",
            extra={"PARAMETER_NAME": "CORTEX_ENABLED_CROSS_REGION", "PARAMETER_VALUE": cross_region},
        ))

    public_rows = _ai_public_grant_rows(public_grants)
    rows.extend(public_rows)
    if not public_rows:
        rows.append(_ai_security_row(
            entity_name="PUBLIC AI grants",
            source_type="PUBLIC AI grant",
            severity="Low",
            finding="No PUBLIC AI/Cortex grants were visible in SHOW GRANTS TO ROLE PUBLIC.",
            action="Keep PUBLIC clean and use named approved roles for AI features.",
            proof_sql="SHOW GRANTS TO ROLE PUBLIC;",
        ))

    role_rows = []
    role_rows.extend(_database_role_public_grant_rows(cortex_user_grants, "CORTEX_USER"))
    role_rows.extend(_database_role_public_grant_rows(ai_functions_user_grants, "AI_FUNCTIONS_USER"))
    rows.extend(role_rows)
    if not role_rows:
        rows.append(_ai_security_row(
            entity_name="Cortex database role grants",
            source_type="Cortex database role grant",
            severity="Low",
            finding="No PUBLIC grant of SNOWFLAKE.CORTEX_USER or SNOWFLAKE.AI_FUNCTIONS_USER was visible.",
            action="Keep Cortex access on named DBA/security-approved roles with budget and function scope.",
            proof_sql="SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.CORTEX_USER; SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.AI_FUNCTIONS_USER;",
        ))

    for record in report_records or []:
        available = bool(record.get("AVAILABLE"))
        mandatory = bool(record.get("MANDATORY"))
        surface = str(record.get("SURFACE") or record.get("OBJECT_NAME") or "Sensitive data report")
        object_name = str(record.get("OBJECT_NAME") or "")
        severity = "Low" if available else ("High" if mandatory else "Medium")
        state = "Ready" if available else "Not Visible"
        rows.append(_ai_security_row(
            entity_name=surface,
            source_type="Sensitive data report",
            entity_type="DATA_SECURITY_REPORT",
            severity=severity,
            finding=(
                f"{surface} is visible to the active role."
                if available
                else f"{surface} is not visible; AI/security review cannot prove sensitive-data exposure from this app role."
            ),
            action=str(record.get("DBA_ACTION") or "Enable report visibility through Snowflake Data Security application roles."),
            proof_sql=f"SELECT * FROM {object_name} LIMIT 0;" if object_name else "",
            extra={
                "STATE": state,
                "OBJECT_NAME": object_name,
                "COLUMN_COUNT": safe_int(record.get("COLUMN_COUNT")),
                "MANDATORY": "Yes" if mandatory else "No",
            },
        ))

    for record in visibility_records or []:
        source = str(record.get("SOURCE_TYPE") or record.get("SQL") or "AI security evidence")
        rows.append(_ai_security_row(
            entity_name=source,
            source_type="Evidence visibility gap",
            severity="Medium",
            finding=f"{source} could not be loaded by the active role.",
            action="Reload with an approved DBA/security role or document alternate evidence before production AI adoption.",
            proof_sql=str(record.get("SQL") or _ai_security_proof_sql(source)),
            extra={"ERROR_TEXT": str(record.get("ERROR") or "")[:500]},
        ))

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["_SEVERITY_RANK"] = frame["SEVERITY"].apply(_severity_rank)
    return frame.sort_values(["_SEVERITY_RANK", "SOURCE_TYPE", "ENTITY_NAME"]).drop(columns=["_SEVERITY_RANK"])


def _safe_show(session, sql: str, source_type: str, errors: list[dict]) -> pd.DataFrame:
    try:
        return show_to_df(session, sql)
    except Exception as exc:
        errors.append({
            "SOURCE_TYPE": source_type,
            "SQL": sql,
            "ERROR": str(exc),
        })
        return pd.DataFrame()


def load_ai_security_guardrails(session) -> pd.DataFrame:
    """Load bounded AI security evidence from SHOW metadata and LIMIT 0 report probes."""
    errors: list[dict] = []
    parameter_frames = [
        _safe_show(session, "SHOW PARAMETERS LIKE 'AI_SETTINGS' IN ACCOUNT", "AI_SETTINGS", errors),
        _safe_show(session, "SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT", "CORTEX_ENABLED_CROSS_REGION", errors),
    ]
    non_empty_parameters = [frame for frame in parameter_frames if frame is not None and not frame.empty]
    parameters = pd.concat(non_empty_parameters, ignore_index=True) if non_empty_parameters else pd.DataFrame()
    public_grants = _safe_show(session, "SHOW GRANTS TO ROLE PUBLIC", "SHOW GRANTS TO ROLE PUBLIC", errors)
    cortex_user_grants = _safe_show(
        session,
        "SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.CORTEX_USER",
        "SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.CORTEX_USER",
        errors,
    )
    ai_functions_user_grants = _safe_show(
        session,
        "SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.AI_FUNCTIONS_USER",
        "SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.AI_FUNCTIONS_USER",
        errors,
    )
    reports = []
    for probe in AI_SECURITY_REPORT_PROBES:
        object_name = probe["OBJECT_NAME"]
        try:
            columns = get_available_columns(session, object_name)
            available = True
        except Exception:
            columns = set()
            available = False
        reports.append({
            **probe,
            "AVAILABLE": available,
            "COLUMN_COUNT": len(columns),
        })
    return classify_ai_security_guardrails(
        parameters=parameters,
        public_grants=public_grants,
        cortex_user_grants=cortex_user_grants,
        ai_functions_user_grants=ai_functions_user_grants,
        report_records=reports,
        visibility_records=errors,
    )


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
            "CONTROL_AREA": "Openflow Operations",
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
        if "Cortex Sense" in control_area:
            owner = "DBA / AI Governance"
            approval_group = "DBA Lead / Data Governance Lead"
        elif "CoWork Artifact" in control_area:
            owner = "DBA / Analytics Governance"
            approval_group = "Analytics Owner / DBA Lead"
        elif "Semantic Trust" in control_area:
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


def _area_rows(frame: pd.DataFrame | None, area: str) -> pd.DataFrame:
    if frame is None or getattr(frame, "empty", True):
        return pd.DataFrame()
    view = _upper_frame(frame)
    if "CONTROL_AREA" in view.columns:
        return view[view["CONTROL_AREA"].fillna("").astype(str).str.upper() == area.upper()].copy()
    return pd.DataFrame()


def _count_truthy_gap(frame: pd.DataFrame, *columns: str) -> int:
    if frame.empty:
        return 0
    gap_count = 0
    for _, row in frame.iterrows():
        row_has_gap = False
        for column in columns:
            if column not in frame.columns:
                continue
            value = str(row.get(column) or "").strip().upper()
            if not value or "GAP" in value or value in {"MISSING", "UNKNOWN", "NOT VISIBLE", "NOT LOADED", "STALE"}:
                row_has_gap = True
        if row_has_gap:
            gap_count += 1
    return gap_count


def _source_health_for_area(source_health: pd.DataFrame | None, area: str) -> tuple[int, str]:
    if source_health is None or getattr(source_health, "empty", True):
        return 1, "Source health not loaded"
    view = _upper_frame(source_health)
    if not {"SURFACE", "STATE"}.issubset(view.columns):
        return 1, "Source health unavailable"
    surfaces = tuple(
        surface.upper()
        for surface in PLATFORM_FUTURES_EXPERT_CRITERIA.get(area, {}).get("surfaces", ())
    )
    if not surfaces:
        return 0, "No mapped source surface"
    scoped = view[view["SURFACE"].fillna("").astype(str).str.upper().isin(surfaces)]
    if scoped.empty:
        return 1, "Mapped source surface missing"
    gap_states = {"NOT LOADED", "STALE"}
    source_gaps = int(scoped["STATE"].fillna("").astype(str).str.upper().isin(gap_states).sum())
    summary = "; ".join(
        f"{row.get('SURFACE')}: {row.get('STATE')}"
        for _, row in scoped.iterrows()
    )
    return source_gaps, summary


def _adoption_next_move(
    area: str,
    *,
    state: str,
    critical_high: int,
    source_gaps: int,
    owner_gaps: int,
    approval_gaps: int,
    evidence_rows: int,
) -> str:
    if state == "Blocked":
        return (
            f"Do not expand {area}; close critical/high findings, owner route gaps, "
            "approval gaps, and source-health blockers first."
        )
    if source_gaps or evidence_rows == 0:
        return f"Load or persist {area} evidence before approving pilot or production adoption."
    if owner_gaps or approval_gaps:
        return f"Pilot {area} only after owner route, approval group, proof query, and rollback path are attached."
    if critical_high:
        return f"Contain {area} to approved users until the critical/high findings are closed and verified."
    if state == "Controlled Pilot":
        return f"Keep {area} in controlled pilot with named owner, budget, rollback, and verification cadence."
    return f"Proceed with controlled {area} adoption; keep evidence ledger and approval state current."


def build_platform_futures_adoption_gate(
    control_register: pd.DataFrame | None,
    evidence_frames: Iterable[pd.DataFrame | None] | None = None,
    *,
    source_health: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Score forward-platform capabilities as strict DBA adoption gates."""
    controls = _upper_frame(control_register)
    frames = list(evidence_frames or [])
    board = build_platform_futures_board(frames, include_low=True)
    rows = []
    for area in PLATFORM_FUTURES_AREAS:
        control_rows = _area_rows(controls, area)
        evidence = _area_rows(board, area)
        severity = (
            evidence["SEVERITY"].fillna("").astype(str).str.upper()
            if "SEVERITY" in evidence.columns
            else pd.Series(dtype=str)
        )
        critical_high = int(severity.isin(["CRITICAL", "HIGH"]).sum())
        medium = int((severity == "MEDIUM").sum())
        owner_gaps = _count_truthy_gap(evidence, "OWNER_EMAIL", "QUEUE_READINESS")
        approval_gaps = _count_truthy_gap(evidence, "APPROVAL_GROUP")
        source_gaps, source_summary = _source_health_for_area(source_health, area)
        control_count = len(control_rows)
        evidence_rows = len(evidence)
        score = 100
        score -= min(36, critical_high * 12)
        score -= min(16, medium * 4)
        score -= min(20, owner_gaps * 10)
        score -= min(16, approval_gaps * 8)
        score -= min(30, source_gaps * 10)
        if evidence_rows == 0:
            score -= 15 if source_gaps else 5
        if control_count == 0:
            score -= 25
        score = max(0, min(100, int(round(score))))
        if critical_high > 0 or score < 75:
            adoption_state = "Blocked"
        elif source_gaps > 0 or owner_gaps > 0 or approval_gaps > 0 or score < 95:
            adoption_state = "Evidence Gaps"
        elif score < 99 or evidence_rows == 0:
            adoption_state = "Controlled Pilot"
        else:
            adoption_state = "Adoption Ready"
        criteria = PLATFORM_FUTURES_EXPERT_CRITERIA.get(area, {})
        first_control = control_rows.iloc[0] if not control_rows.empty else {}
        rows.append({
            "CONTROL_AREA": area,
            "ADOPTION_STATE": adoption_state,
            "READINESS_SCORE": score,
            "CONTROL_COUNT": control_count,
            "EVIDENCE_ROWS": evidence_rows,
            "CRITICAL_HIGH_FINDINGS": critical_high,
            "MEDIUM_FINDINGS": medium,
            "OWNER_ROUTE_GAPS": owner_gaps,
            "APPROVAL_GAPS": approval_gaps,
            "SOURCE_GAPS": source_gaps,
            "SOURCE_HEALTH": source_summary,
            "NEXT_DBA_MOVE": _adoption_next_move(
                area,
                state=adoption_state,
                critical_high=critical_high,
                source_gaps=source_gaps,
                owner_gaps=owner_gaps,
                approval_gaps=approval_gaps,
                evidence_rows=evidence_rows,
            ),
            "WHY_EXPERTS_CARE": criteria.get("why", "Experts expect owner, evidence, approval, rollback, and verification before adoption."),
            "PRIMARY_EVIDENCE": _first_text(first_control, "PRIMARY_EVIDENCE"),
            "AUTOMATION_BOUNDARY": _first_text(first_control, "AUTOMATION_BOUNDARY"),
        })
    gate = pd.DataFrame(rows)
    if gate.empty:
        return gate
    state_rank = {"Blocked": 0, "Evidence Gaps": 1, "Controlled Pilot": 2, "Adoption Ready": 3}
    gate["_STATE_RANK"] = gate["ADOPTION_STATE"].map(state_rank).fillna(9)
    return gate.sort_values(
        ["_STATE_RANK", "READINESS_SCORE", "CRITICAL_HIGH_FINDINGS", "SOURCE_GAPS"],
        ascending=[True, True, False, False],
    ).drop(columns=["_STATE_RANK"])


def _agentic_go_live_state(row: Mapping | pd.Series) -> str:
    score = safe_int(_first_text(row, "READINESS_SCORE", default="0"))
    critical_high = safe_int(_first_text(row, "CRITICAL_HIGH_FINDINGS", default="0"))
    medium = safe_int(_first_text(row, "MEDIUM_FINDINGS", default="0"))
    source_gaps = safe_int(_first_text(row, "SOURCE_GAPS", default="0"))
    owner_gaps = safe_int(_first_text(row, "OWNER_ROUTE_GAPS", default="0"))
    approval_gaps = safe_int(_first_text(row, "APPROVAL_GAPS", default="0"))
    evidence_rows = safe_int(_first_text(row, "EVIDENCE_ROWS", default="0"))
    if critical_high > 0 or score < 75:
        return "Blocked"
    if source_gaps > 0 or owner_gaps > 0 or approval_gaps > 0 or evidence_rows == 0 or medium > 0 or score < 95:
        return "Evidence Gaps"
    if score < 99:
        return "Controlled Pilot"
    return "Production Ready"


def _agentic_blockers(row: Mapping | pd.Series) -> str:
    blockers: list[str] = []
    score = safe_int(_first_text(row, "READINESS_SCORE", default="0"))
    critical_high = safe_int(_first_text(row, "CRITICAL_HIGH_FINDINGS", default="0"))
    medium = safe_int(_first_text(row, "MEDIUM_FINDINGS", default="0"))
    source_gaps = safe_int(_first_text(row, "SOURCE_GAPS", default="0"))
    owner_gaps = safe_int(_first_text(row, "OWNER_ROUTE_GAPS", default="0"))
    approval_gaps = safe_int(_first_text(row, "APPROVAL_GAPS", default="0"))
    evidence_rows = safe_int(_first_text(row, "EVIDENCE_ROWS", default="0"))
    if critical_high:
        blockers.append(f"{critical_high} critical/high finding(s)")
    if medium:
        blockers.append(f"{medium} medium evidence gap(s)")
    if source_gaps:
        blockers.append(f"{source_gaps} unloaded or stale source surface(s)")
    if evidence_rows == 0:
        blockers.append("no loaded evidence rows")
    if owner_gaps:
        blockers.append(f"{owner_gaps} owner route gap(s)")
    if approval_gaps:
        blockers.append(f"{approval_gaps} approval gap(s)")
    if score < 95:
        blockers.append(f"readiness {score} below 95 target")
    return "; ".join(blockers) or "No blocking gaps in loaded evidence"


def _agentic_dba_decision(row: Mapping | pd.Series) -> str:
    state = _first_text(row, "GO_LIVE_STATE", default="Evidence Gaps")
    area = _first_text(row, "CONTROL_AREA", default="agentic AI surface")
    if state == "Blocked":
        return f"No-go for {area}; contain usage until blockers are closed with owner-approved proof."
    if state == "Evidence Gaps":
        return f"Do not expand {area}; load evidence and attach owner, approval, proof, and rollback route first."
    if state == "Controlled Pilot":
        return f"Keep {area} in a named pilot with explicit users, budget/quota guardrails, and weekly verification."
    return f"{area} can proceed under production governance with evidence refresh, owner review, and rollback checks."


def build_agentic_ai_surface_scorecard(
    control_register: pd.DataFrame | None,
    evidence_frames: Iterable[pd.DataFrame | None] | None = None,
    *,
    source_health: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Return strict go-live readiness for agentic AI surfaces."""
    gate = build_platform_futures_adoption_gate(
        control_register,
        evidence_frames,
        source_health=source_health,
    )
    summary = {
        "STRICT_SCORE": 0,
        "AVERAGE_SCORE": 0,
        "SURFACES": 0,
        "PRODUCTION_READY": 0,
        "CONTROLLED_PILOT": 0,
        "EVIDENCE_GAPS": 0,
        "BLOCKED": 0,
        "CRITICAL_HIGH": 0,
        "SOURCE_GAPS": 0,
        "OWNER_ROUTE_GAPS": 0,
        "APPROVAL_GAPS": 0,
        "TOP_RISK": "No agentic AI readiness evidence loaded",
        "NEXT_DBA_MOVE": "Load the Agentic AI Cockpit evidence surfaces before approving production AI expansion.",
    }
    if gate is None or gate.empty:
        return summary, pd.DataFrame()

    view = _upper_frame(gate)
    scorecard = view[view["CONTROL_AREA"].isin(AGENTIC_AI_CONTROL_AREAS)].copy()
    if scorecard.empty:
        return summary, scorecard

    scorecard["SURFACE_CLASS"] = scorecard["CONTROL_AREA"].map(AGENTIC_AI_SURFACE_CLASSES).fillna("Agentic AI")
    scorecard["GO_LIVE_STATE"] = scorecard.apply(_agentic_go_live_state, axis=1)
    scorecard["BLOCKERS"] = scorecard.apply(_agentic_blockers, axis=1)
    scorecard["DBA_DECISION"] = scorecard.apply(_agentic_dba_decision, axis=1)
    scorecard["PROOF_REQUIRED"] = scorecard.get("PRIMARY_EVIDENCE", pd.Series(["Attach source evidence."] * len(scorecard), index=scorecard.index))
    scorecard["DO_NOT_DO"] = scorecard.get("AUTOMATION_BOUNDARY", pd.Series(["Do not automate production changes without approval."] * len(scorecard), index=scorecard.index))

    state_rank = {"Blocked": 0, "Evidence Gaps": 1, "Controlled Pilot": 2, "Production Ready": 3}
    scorecard["_STATE_RANK"] = scorecard["GO_LIVE_STATE"].map(state_rank).fillna(9)
    scorecard = scorecard.sort_values(
        ["_STATE_RANK", "READINESS_SCORE", "CRITICAL_HIGH_FINDINGS", "SOURCE_GAPS"],
        ascending=[True, True, False, False],
    ).drop(columns=["_STATE_RANK"])

    ready = int((scorecard["GO_LIVE_STATE"] == "Production Ready").sum())
    pilots = int((scorecard["GO_LIVE_STATE"] == "Controlled Pilot").sum())
    gaps = int((scorecard["GO_LIVE_STATE"] == "Evidence Gaps").sum())
    blocked = int((scorecard["GO_LIVE_STATE"] == "Blocked").sum())
    summary.update({
        "STRICT_SCORE": int(scorecard["READINESS_SCORE"].min()),
        "AVERAGE_SCORE": int(round(safe_float(scorecard["READINESS_SCORE"].mean()))),
        "SURFACES": int(len(scorecard)),
        "PRODUCTION_READY": ready,
        "CONTROLLED_PILOT": pilots,
        "EVIDENCE_GAPS": gaps,
        "BLOCKED": blocked,
        "CRITICAL_HIGH": int(scorecard["CRITICAL_HIGH_FINDINGS"].sum()),
        "SOURCE_GAPS": int(scorecard["SOURCE_GAPS"].sum()),
        "OWNER_ROUTE_GAPS": int(scorecard["OWNER_ROUTE_GAPS"].sum()),
        "APPROVAL_GAPS": int(scorecard["APPROVAL_GAPS"].sum()),
        "TOP_RISK": str(scorecard.iloc[0].get("CONTROL_AREA") or "Agentic AI readiness"),
        "NEXT_DBA_MOVE": str(scorecard.iloc[0].get("NEXT_DBA_MOVE") or scorecard.iloc[0].get("DBA_DECISION") or summary["NEXT_DBA_MOVE"]),
    })
    return summary, scorecard
