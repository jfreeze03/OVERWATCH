# utils/owner_directory.py - shared owner/on-call routing for DBA control workflows
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA, DEFAULT_ALERT_EMAIL
from .query import run_query, safe_identifier, sql_literal


OWNER_DIRECTORY_TABLE = "OVERWATCH_OWNER_DIRECTORY"
OWNER_DIRECTORY_VIEW = "OVERWATCH_OWNER_DIRECTORY_ACTIVE_V"

OWNER_CONTEXT_COLUMNS = [
    "OWNER",
    "OWNER_EMAIL",
    "ONCALL_PRIMARY",
    "ONCALL_SECONDARY",
    "APPROVAL_GROUP",
    "ESCALATION_TARGET",
    "OWNER_SOURCE",
    "OWNER_EVIDENCE",
]

PLACEHOLDER_ROUTE_VALUES = {
    "",
    "DBA",
    "DBA LEAD",
    "DBA ON-CALL",
    "DBA BACKUP",
    "FINOPS LEAD",
    "FINOPS BACKUP",
    "PIPELINE OWNER",
    "PIPELINE OWNER BACKUP",
    "PROCEDURE OWNER",
    "PROCEDURE OWNER BACKUP",
    "PLATFORM DBA BACKUP",
    "SECURITY BACKUP",
    "DATA ENGINEERING BACKUP",
    "INFRASTRUCTURE BACKUP",
    "CHANGE ADVISORY BACKUP",
    "ANALYTICS OWNER",
    "ANALYTICS OWNER BACKUP",
    "OVERWATCH PLATFORM OWNER",
}

GENERIC_OWNERS = {
    "",
    "DBA",
    "DBA / FINOPS",
    "DBA / PLATFORM",
    "DBA / SECURITY",
    "DBA / WORKLOAD OWNER",
    "DBA / PIPELINE OWNER",
    "DBA / PROCEDURE OWNER",
    "DBA / DATA ENGINEERING",
    "DATA ENGINEERING",
    "UNKNOWN",
    "UNASSIGNED",
    "N/A",
    "NONE",
    "NULL",
}

DEFAULT_OWNER_DIRECTORY = [
    {
        "OWNER_KEY": "COST_CONTROL_DEFAULT",
        "ENTITY_TYPE": "COST_CONTROL",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / FinOps",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "FinOps Backup",
        "APPROVAL_GROUP": "FinOps Lead / Cost Owner",
        "ESCALATION_TARGET": "FinOps Lead",
        "DEFAULT_ROUTE": "Cost & Contract",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 80,
        "NOTES": "Default route for bill movement, chargeback, savings verification, and cost-control actions.",
    },
    {
        "OWNER_KEY": "COST_VERIFIER_TASK",
        "ENTITY_TYPE": "TASK",
        "ENTITY_PATTERN": "*OVERWATCH_COST_SAVINGS_VERIFY*",
        "OWNER_NAME": "DBA / FinOps",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "FinOps Backup",
        "APPROVAL_GROUP": "FinOps Lead",
        "ESCALATION_TARGET": "FinOps Lead",
        "DEFAULT_ROUTE": "Cost & Contract",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 200,
        "NOTES": "Owner route for the scheduled savings-verification task.",
    },
    {
        "OWNER_KEY": "TASK_DEFAULT",
        "ENTITY_TYPE": "TASK",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Pipeline Owner",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Pipeline Owner Backup",
        "APPROVAL_GROUP": "Pipeline Owner",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Workload Operations",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 70,
        "NOTES": "Default route for failed or late task graph recovery.",
    },
    {
        "OWNER_KEY": "PROCEDURE_DEFAULT",
        "ENTITY_TYPE": "PROCEDURE",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Procedure Owner",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Procedure Owner Backup",
        "APPROVAL_GROUP": "Procedure Owner",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Workload Operations",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 70,
        "NOTES": "Default route for stored procedure runtime, orchestration, and cost regressions.",
    },
    {
        "OWNER_KEY": "WAREHOUSE_DEFAULT",
        "ENTITY_TYPE": "WAREHOUSE",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Platform",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Platform DBA Backup",
        "APPROVAL_GROUP": "Platform DBA Lead",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Warehouse Health",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 60,
        "NOTES": "Default route for warehouse pressure, capacity, and setting-change controls.",
    },
    {
        "OWNER_KEY": "COMPUTE_WH_EXECUTION",
        "ENTITY_TYPE": "WAREHOUSE",
        "ENTITY_PATTERN": "COMPUTE_WH",
        "OWNER_NAME": "OVERWATCH Platform Owner",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Platform DBA Backup",
        "APPROVAL_GROUP": "DBA Lead / OVERWATCH Platform Owner",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 205,
        "NOTES": "Current OVERWATCH app and task execution warehouse; monitor separately from business workload warehouses.",
    },
    {
        "OWNER_KEY": "ADAPTIVE_COMPUTE_DEFAULT",
        "ENTITY_TYPE": "ADAPTIVE_COMPUTE",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Platform Architecture",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "FinOps Backup",
        "APPROVAL_GROUP": "DBA Lead / FinOps Lead",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 158,
        "NOTES": "Default route for Adaptive Compute candidate review, pilot approval, cost baseline, and rollback proof.",
    },
    {
        "OWNER_KEY": "ALFA_EDW_PROD_DATABASE",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "ALFA_EDW_PROD",
        "OWNER_NAME": "ALFA EDW Data Owner",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Data Platform Backup",
        "APPROVAL_GROUP": "DBA Lead / ALFA EDW Data Owner",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 220,
        "NOTES": "Owner route for PROD EDW isolation, clustering, cache, and DR architecture decisions.",
    },
    {
        "OWNER_KEY": "ALFA_EDW_DEV_DATABASES",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "ALFA_EDW_%",
        "OWNER_NAME": "ALFA Development Data Owner",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Development Platform Backup",
        "APPROVAL_GROUP": "DBA Lead / Development Platform Owner",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 2",
        "MATCH_PRIORITY": 120,
        "NOTES": "Fallback route for ALFA DEV/Sandbox EDW database architecture decisions.",
    },
    {
        "OWNER_KEY": "ARCHITECTURE_DEFAULT",
        "ENTITY_TYPE": "ARCHITECTURE",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Platform Architecture",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Platform DBA Backup",
        "APPROVAL_GROUP": "DBA Lead",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 65,
        "NOTES": "Fallback route for architecture objective, workload isolation, clustering, cache, and DR findings.",
    },
    {
        "OWNER_KEY": "AI_AGENT_DEFAULT",
        "ENTITY_TYPE": "AI_AGENT",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / AI Governance",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Security Backup",
        "APPROVAL_GROUP": "DBA Lead / Security Approver",
        "ESCALATION_TARGET": "Security Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 160,
        "NOTES": "Default route for Cortex Agent inventory, Snowflake Intelligence usage, MCP tool exposure, and AI governance actions.",
    },
    {
        "OWNER_KEY": "MCP_SERVER_DEFAULT",
        "ENTITY_TYPE": "MCP_SERVER",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / AI Governance",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Security Backup",
        "APPROVAL_GROUP": "DBA Lead / Security Approver",
        "ESCALATION_TARGET": "Security Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 170,
        "NOTES": "Default route for MCP server owner, tool-scope, role-scope, and blast-radius review.",
    },
    {
        "OWNER_KEY": "CORTEX_SENSE_DEFAULT",
        "ENTITY_TYPE": "CORTEX_SENSE",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / AI Governance",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Data Governance Backup",
        "APPROVAL_GROUP": "DBA Lead / Data Governance Lead",
        "ESCALATION_TARGET": "Data Governance Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 168,
        "NOTES": "Default route for Cortex Sense shared context, business definitions, semantic source, connector, citation, and regression-test governance.",
    },
    {
        "OWNER_KEY": "COWORK_ARTIFACT_DEFAULT",
        "ENTITY_TYPE": "COWORK_ARTIFACT",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Analytics Governance",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Analytics Owner Backup",
        "APPROVAL_GROUP": "Analytics Owner / DBA Lead",
        "ESCALATION_TARGET": "Analytics Owner",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 166,
        "NOTES": "Default route for CoWork Artifact publisher, certified source, sharing scope, freshness, sensitivity, and retirement governance.",
    },
    {
        "OWNER_KEY": "AI_COST_DEFAULT",
        "ENTITY_TYPE": "AI_USAGE",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / FinOps",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "FinOps Backup",
        "APPROVAL_GROUP": "FinOps Lead / DBA Lead",
        "ESCALATION_TARGET": "FinOps Lead",
        "DEFAULT_ROUTE": "Cost & Contract",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 155,
        "NOTES": "Default route for AI token-credit spend, Snowflake Intelligence usage, and Cortex Agent cost guardrails.",
    },
    {
        "OWNER_KEY": "AI_SECURITY_DEFAULT",
        "ENTITY_TYPE": "AI_SECURITY",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / AI Governance",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Security Backup",
        "APPROVAL_GROUP": "DBA Lead / Security Approver",
        "ESCALATION_TARGET": "Security Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 156,
        "NOTES": "Default route for Cortex AI Guardrails, PUBLIC AI access, per-function privileges, and sensitive-data report readiness.",
    },
    {
        "OWNER_KEY": "OPENFLOW_DEFAULT",
        "ENTITY_TYPE": "OPENFLOW",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Integration Platform",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Data Engineering Backup",
        "APPROVAL_GROUP": "Data Engineering Lead / DBA Lead",
        "ESCALATION_TARGET": "Data Engineering Lead",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 150,
        "NOTES": "Default route for Openflow runtime, data-plane, auth, cost, and recovery evidence.",
    },
    {
        "OWNER_KEY": "HORIZON_GOVERNANCE_DEFAULT",
        "ENTITY_TYPE": "GOVERNANCE_VIEW",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Data Governance",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Security Backup",
        "APPROVAL_GROUP": "Data Governance Lead / Security Approver",
        "ESCALATION_TARGET": "Data Governance Lead",
        "DEFAULT_ROUTE": "Security Posture",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 145,
        "NOTES": "Default route for Horizon catalog, classification, policy, lineage, access-history, and governance-readiness gaps.",
    },
    {
        "OWNER_KEY": "SEMANTIC_TRUST_DEFAULT",
        "ENTITY_TYPE": "SEMANTIC_TRUST",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Analytics Governance",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Analytics Owner Backup",
        "APPROVAL_GROUP": "Analytics Owner / DBA Lead",
        "ESCALATION_TARGET": "Analytics Owner",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 140,
        "NOTES": "Default route for semantic model ownership, certification, verified query tests, and AI answer trust.",
    },
    {
        "OWNER_KEY": "BCDR_DRILL_DEFAULT",
        "ENTITY_TYPE": "BCDR_DRILL",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Platform Architecture",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Infrastructure Backup",
        "APPROVAL_GROUP": "DBA Lead / Infrastructure Owner",
        "ESCALATION_TARGET": "Infrastructure Owner",
        "DEFAULT_ROUTE": "Architecture Readiness",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 135,
        "NOTES": "Default route for DR drill ledger, recovery proof, RPO/RTO validation, and failover/replication evidence.",
    },
    {
        "OWNER_KEY": "AI_CHANGE_GOVERNANCE_DEFAULT",
        "ENTITY_TYPE": "AI_CHANGE_GOVERNANCE",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA Change Owner",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Change Advisory Backup",
        "APPROVAL_GROUP": "Change Advisory / DBA Lead",
        "ESCALATION_TARGET": "DBA Lead / Change Advisory",
        "DEFAULT_ROUTE": "Change & Drift",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 130,
        "NOTES": "Default route for Cortex Code, AISQL, and AI-assisted admin change governance.",
    },
    {
        "OWNER_KEY": "CHANGE_CONTROL_DEFAULT",
        "ENTITY_TYPE": "CHANGE_CONTROL",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA Change Owner",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Change Advisory Backup",
        "APPROVAL_GROUP": "Change Advisory / Data Owner",
        "ESCALATION_TARGET": "DBA Lead / Security Owner",
        "DEFAULT_ROUTE": "Change & Drift",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 65,
        "NOTES": "Default route for DDL, access drift, policy/tag, IaC, and change-control actions.",
    },
    {
        "OWNER_KEY": "SECURITY_DEFAULT",
        "ENTITY_TYPE": "SECURITY",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA / Security",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Security Backup",
        "APPROVAL_GROUP": "Security Approver",
        "ESCALATION_TARGET": "Security Lead",
        "DEFAULT_ROUTE": "Security Posture",
        "SERVICE_TIER": "Tier 0",
        "MATCH_PRIORITY": 60,
        "NOTES": "Default route for grant, revoke, role, and rights controls.",
    },
    {
        "OWNER_KEY": "ACCOUNT_HEALTH_DEFAULT",
        "ENTITY_TYPE": "ACCOUNT_HEALTH",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA Lead",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "Platform DBA Backup",
        "APPROVAL_GROUP": "DBA Lead",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Account Health",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 50,
        "NOTES": "Default route for daily DBA checklist, account health closure, and control-room readiness gaps.",
    },
    {
        "OWNER_KEY": "ALERT_DEFAULT",
        "ENTITY_TYPE": "ALERT",
        "ENTITY_PATTERN": "*",
        "OWNER_NAME": "DBA",
        "OWNER_EMAIL": DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": "DBA On-Call",
        "ONCALL_SECONDARY": "DBA Backup",
        "APPROVAL_GROUP": "DBA Lead",
        "ESCALATION_TARGET": "DBA Lead",
        "DEFAULT_ROUTE": "Alert Center",
        "SERVICE_TIER": "Tier 1",
        "MATCH_PRIORITY": 10,
        "NOTES": "Fallback route for alerts without a more specific owner.",
    },
]


def owner_directory_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = OWNER_DIRECTORY_TABLE,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"
    return f"{db}.{schema}.{table}"


def owner_directory_view_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    view: str = OWNER_DIRECTORY_VIEW,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(view)}"
    return f"{db}.{schema}.{view}"


def default_owner_directory() -> pd.DataFrame:
    """Return the built-in owner/on-call defaults as a dataframe."""
    return pd.DataFrame(DEFAULT_OWNER_DIRECTORY)


def _seed_values_sql() -> str:
    rows = []
    for row in DEFAULT_OWNER_DIRECTORY:
        rows.append(
            "("
            + ", ".join([
                sql_literal(row.get("OWNER_KEY"), 200),
                sql_literal(row.get("ENTITY_TYPE"), 100),
                sql_literal(row.get("ENTITY_PATTERN"), 500),
                sql_literal(row.get("OWNER_NAME"), 200),
                sql_literal(row.get("OWNER_EMAIL"), 500),
                sql_literal(row.get("ONCALL_PRIMARY"), 200),
                sql_literal(row.get("ONCALL_SECONDARY"), 200),
                sql_literal(row.get("APPROVAL_GROUP"), 200),
                sql_literal(row.get("ESCALATION_TARGET"), 200),
                sql_literal(row.get("DEFAULT_ROUTE"), 200),
                sql_literal(row.get("SERVICE_TIER"), 50),
                str(int(row.get("MATCH_PRIORITY", 0))),
                sql_literal(row.get("NOTES"), 2000),
            ])
            + ")"
        )
    return ",\n        ".join(rows)


def build_owner_directory_ddl(db: str = ALERT_DB, schema: str = ALERT_SCHEMA) -> str:
    db_safe = safe_identifier(db)
    schema_safe = safe_identifier(schema)
    table = safe_identifier(OWNER_DIRECTORY_TABLE)
    view = safe_identifier(OWNER_DIRECTORY_VIEW)
    return f"""-- OVERWATCH owner/on-call routing directory
-- Replace seed rows with named ALFA service owners as teams are onboarded.
CREATE TABLE IF NOT EXISTS {db_safe}.{schema_safe}.{table} (
    OWNER_KEY         VARCHAR(200) PRIMARY KEY,
    ENTITY_TYPE       VARCHAR(100),
    ENTITY_PATTERN    VARCHAR(500),
    OWNER_NAME        VARCHAR(200),
    OWNER_EMAIL       VARCHAR(500),
    ONCALL_PRIMARY    VARCHAR(200),
    ONCALL_SECONDARY  VARCHAR(200),
    APPROVAL_GROUP    VARCHAR(200),
    ESCALATION_TARGET VARCHAR(200),
    DEFAULT_ROUTE     VARCHAR(200),
    SERVICE_TIER      VARCHAR(50),
    MATCH_PRIORITY    NUMBER DEFAULT 0,
    IS_ACTIVE         BOOLEAN DEFAULT TRUE,
    UPDATED_AT        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_BY        VARCHAR(200) DEFAULT CURRENT_USER(),
    NOTES             VARCHAR(2000)
);

MERGE INTO {db_safe}.{schema_safe}.{table} tgt
USING (
    SELECT * FROM VALUES
        {_seed_values_sql()}
) src(OWNER_KEY, ENTITY_TYPE, ENTITY_PATTERN, OWNER_NAME, OWNER_EMAIL, ONCALL_PRIMARY,
      ONCALL_SECONDARY, APPROVAL_GROUP, ESCALATION_TARGET, DEFAULT_ROUTE, SERVICE_TIER,
      MATCH_PRIORITY, NOTES)
ON UPPER(tgt.OWNER_KEY) = UPPER(src.OWNER_KEY)
WHEN MATCHED THEN UPDATE SET
    ENTITY_TYPE = src.ENTITY_TYPE,
    ENTITY_PATTERN = src.ENTITY_PATTERN,
    OWNER_NAME = src.OWNER_NAME,
    OWNER_EMAIL = src.OWNER_EMAIL,
    ONCALL_PRIMARY = src.ONCALL_PRIMARY,
    ONCALL_SECONDARY = src.ONCALL_SECONDARY,
    APPROVAL_GROUP = src.APPROVAL_GROUP,
    ESCALATION_TARGET = src.ESCALATION_TARGET,
    DEFAULT_ROUTE = src.DEFAULT_ROUTE,
    SERVICE_TIER = src.SERVICE_TIER,
    MATCH_PRIORITY = src.MATCH_PRIORITY,
    IS_ACTIVE = TRUE,
    NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT
    (OWNER_KEY, ENTITY_TYPE, ENTITY_PATTERN, OWNER_NAME, OWNER_EMAIL, ONCALL_PRIMARY,
     ONCALL_SECONDARY, APPROVAL_GROUP, ESCALATION_TARGET, DEFAULT_ROUTE, SERVICE_TIER,
     MATCH_PRIORITY, NOTES)
VALUES
    (src.OWNER_KEY, src.ENTITY_TYPE, src.ENTITY_PATTERN, src.OWNER_NAME, src.OWNER_EMAIL,
     src.ONCALL_PRIMARY, src.ONCALL_SECONDARY, src.APPROVAL_GROUP, src.ESCALATION_TARGET,
     src.DEFAULT_ROUTE, src.SERVICE_TIER, src.MATCH_PRIORITY, src.NOTES);

CREATE OR REPLACE VIEW {db_safe}.{schema_safe}.{view} AS
SELECT
    OWNER_KEY,
    UPPER(COALESCE(ENTITY_TYPE, 'GLOBAL')) AS ENTITY_TYPE,
    COALESCE(ENTITY_PATTERN, '*') AS ENTITY_PATTERN,
    OWNER_NAME,
    OWNER_EMAIL,
    ONCALL_PRIMARY,
    ONCALL_SECONDARY,
    APPROVAL_GROUP,
    ESCALATION_TARGET,
    DEFAULT_ROUTE,
    SERVICE_TIER,
    COALESCE(MATCH_PRIORITY, 0) AS MATCH_PRIORITY,
    NOTES,
    UPDATED_AT,
    UPDATED_BY
FROM {db_safe}.{schema_safe}.{table}
WHERE COALESCE(IS_ACTIVE, TRUE);"""


def load_owner_directory(section: str = "Owner Directory") -> pd.DataFrame:
    """Load the configured owner directory, falling back to seed defaults."""
    try:
        df = run_query(
            f"""
            SELECT OWNER_KEY, ENTITY_TYPE, ENTITY_PATTERN, OWNER_NAME, OWNER_EMAIL,
                   ONCALL_PRIMARY, ONCALL_SECONDARY, APPROVAL_GROUP, ESCALATION_TARGET,
                   DEFAULT_ROUTE, SERVICE_TIER, MATCH_PRIORITY, NOTES
            FROM {owner_directory_view_fqn(quoted=True)}
            ORDER BY MATCH_PRIORITY DESC, OWNER_KEY
            """,
            ttl_key="owner_directory_active",
            tier="historical",
            section=section,
        )
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return default_owner_directory()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _is_generic_owner(value: Any) -> bool:
    return _upper(value).replace("\\", "/") in GENERIC_OWNERS


def _is_placeholder_route_value(value: Any) -> bool:
    text = _upper(value).replace("\\", "/")
    if not text or text in PLACEHOLDER_ROUTE_VALUES or text in GENERIC_OWNERS:
        return True
    if text.startswith("DBA /") or text.endswith(" OWNER") or text.endswith(" BACKUP"):
        return True
    return False


def owner_directory_readiness_board(
    directory: pd.DataFrame | None = None,
    *,
    default_email: str = DEFAULT_ALERT_EMAIL,
) -> tuple[dict[str, int | float], pd.DataFrame]:
    """Summarize whether owner routes are production-ready or placeholders."""
    directory = directory if directory is not None and not directory.empty else default_owner_directory()
    if directory is None or directory.empty:
        empty = pd.DataFrame(columns=[
            "OWNER_KEY", "ROUTE_STATE", "BLOCKERS", "NEXT_ACTION",
        ])
        return {
            "total_routes": 0,
            "production_ready": 0,
            "placeholder_routes": 0,
            "tier0_tier1_gaps": 0,
            "readiness_pct": 0.0,
        }, empty

    view = directory.copy().fillna("")
    rows: list[dict[str, Any]] = []
    default_email_upper = _upper(default_email)
    for _, row in view.iterrows():
        owner_name = _text(row.get("OWNER_NAME"))
        owner_email = _text(row.get("OWNER_EMAIL"))
        oncall = _text(row.get("ONCALL_PRIMARY"))
        approval = _text(row.get("APPROVAL_GROUP"))
        escalation = _text(row.get("ESCALATION_TARGET"))
        tier = _text(row.get("SERVICE_TIER")) or "Tier ?"
        blockers: list[str] = []
        if _is_placeholder_route_value(owner_name):
            blockers.append("named owner")
        if not owner_email or _upper(owner_email) == default_email_upper:
            blockers.append("non-placeholder email")
        if _is_placeholder_route_value(oncall):
            blockers.append("named on-call")
        if _is_placeholder_route_value(approval):
            blockers.append("approval owner")
        if _is_placeholder_route_value(escalation):
            blockers.append("escalation owner")

        if not blockers:
            route_state = "Production Ready"
            next_action = "Keep route current through owner-directory change control."
        elif tier.upper() in {"TIER 0", "TIER 1"}:
            route_state = "Priority Gap"
            next_action = "Replace placeholder owner, email, on-call, approval, and escalation values before relying on this route."
        else:
            route_state = "Route Gap"
            next_action = "Complete owner-directory fields before production escalation."

        rows.append({
            "OWNER_KEY": row.get("OWNER_KEY", ""),
            "ENTITY_TYPE": row.get("ENTITY_TYPE", ""),
            "ENTITY_PATTERN": row.get("ENTITY_PATTERN", ""),
            "OWNER_NAME": owner_name,
            "OWNER_EMAIL": owner_email,
            "ONCALL_PRIMARY": oncall,
            "APPROVAL_GROUP": approval,
            "ESCALATION_TARGET": escalation,
            "DEFAULT_ROUTE": row.get("DEFAULT_ROUTE", ""),
            "SERVICE_TIER": tier,
            "MATCH_PRIORITY": row.get("MATCH_PRIORITY", ""),
            "ROUTE_STATE": route_state,
            "BLOCKERS": ", ".join(blockers) if blockers else "none",
            "NEXT_ACTION": next_action,
        })

    board = pd.DataFrame(rows)
    if board.empty:
        return {
            "total_routes": 0,
            "production_ready": 0,
            "placeholder_routes": 0,
            "tier0_tier1_gaps": 0,
            "readiness_pct": 0.0,
        }, board
    production_ready = int(board["ROUTE_STATE"].eq("Production Ready").sum())
    placeholder_routes = int(len(board) - production_ready)
    tier0_tier1 = board["SERVICE_TIER"].astype(str).str.upper().isin(["TIER 0", "TIER 1"])
    tier0_tier1_gaps = int((tier0_tier1 & board["ROUTE_STATE"].ne("Production Ready")).sum())
    board["_STATE_RANK"] = board["ROUTE_STATE"].map({
        "Priority Gap": 0,
        "Route Gap": 1,
        "Production Ready": 2,
    }).fillna(9)
    board["_TIER_RANK"] = board["SERVICE_TIER"].astype(str).str.extract(r"(\d+)", expand=False).fillna("9").astype(int)
    board = board.sort_values(
        ["_STATE_RANK", "_TIER_RANK", "MATCH_PRIORITY", "OWNER_KEY"],
        ascending=[True, True, False, True],
    ).drop(columns=["_STATE_RANK", "_TIER_RANK"], errors="ignore").reset_index(drop=True)
    return {
        "total_routes": int(len(board)),
        "production_ready": production_ready,
        "placeholder_routes": placeholder_routes,
        "tier0_tier1_gaps": tier0_tier1_gaps,
        "readiness_pct": round(production_ready / max(len(board), 1) * 100, 1),
    }, board


def _wildcard_match(pattern: Any, value: Any) -> tuple[bool, int]:
    pat = _upper(pattern) or "*"
    val = _upper(value)
    if not val:
        return False, 0
    if pat in {"*", "%"}:
        return True, 1
    if pat == val:
        return True, 100
    regex = "^" + re.escape(pat).replace("\\*", ".*").replace("%", ".*") + "$"
    if re.match(regex, val):
        return True, 40
    if pat.replace("*", "").replace("%", "") and pat.replace("*", "").replace("%", "") in val:
        return True, 20
    return False, 0


def _entity_type_candidates(entity_type: Any, category: Any = "", alert_type: Any = "") -> set[str]:
    raw_values = {_upper(entity_type), _upper(category), _upper(alert_type)}
    candidates = {value for value in raw_values if value}
    joined = " ".join(candidates)
    if "COST" in joined or "FINOPS" in joined or "CHARGEBACK" in joined:
        candidates.add("COST_CONTROL")
    if "TASK" in joined:
        candidates.add("TASK")
    if "PROCEDURE" in joined or "PROC" in joined or "CALL" in joined:
        candidates.add("PROCEDURE")
    if "WAREHOUSE" in joined:
        candidates.add("WAREHOUSE")
    if "GRANT" in joined or "ROLE" in joined or "SECURITY" in joined:
        candidates.add("SECURITY")
    if "CHANGE" in joined or "DRIFT" in joined or "DDL" in joined or "IAC" in joined:
        candidates.add("CHANGE_CONTROL")
    if "ACCOUNT HEALTH" in joined or "CHECKLIST" in joined or "CONTROL ROOM" in joined:
        candidates.add("ACCOUNT_HEALTH")
    candidates.add("ALERT")
    candidates.add("GLOBAL")
    return candidates


def _canonical_entity_type(entity_type: Any) -> str:
    value = _upper(entity_type)
    if "COST" in value or "FINOPS" in value or "CHARGEBACK" in value:
        return "COST_CONTROL"
    if "PROCEDURE" in value or "PROC" in value or "CALL" in value:
        return "PROCEDURE"
    if "TASK" in value:
        return "TASK"
    if "WAREHOUSE" in value:
        return "WAREHOUSE"
    if "CHANGE" in value or "DRIFT" in value or "DDL" in value or "IAC" in value:
        return "CHANGE_CONTROL"
    if "GRANT" in value or "ROLE" in value or "SECURITY" in value:
        return "SECURITY"
    if "ACCOUNT HEALTH" in value or "CHECKLIST" in value or "CONTROL ROOM" in value:
        return "ACCOUNT_HEALTH"
    if "ALERT" in value:
        return "ALERT"
    return value


def resolve_owner_context(
    row: pd.Series | dict | None = None,
    *,
    directory: pd.DataFrame | None = None,
    entity: Any = "",
    entity_type: Any = "",
    owner: Any = "",
    category: Any = "",
    alert_type: Any = "",
) -> dict[str, str]:
    """Resolve owner/on-call metadata for a workflow row.

    Existing non-generic owners are preserved, while on-call, approval, and
    source metadata are still filled from the best matching directory row.
    """
    source_row = row if row is not None else {}
    get = source_row.get if hasattr(source_row, "get") else lambda key, default=None: default
    entity = entity or get("ENTITY_NAME") or get("ENTITY") or get("TASK_FQN") or get("TASK_NAME") or get("PROCEDURE_NAME")
    entity_type = entity_type or get("ENTITY_TYPE") or get("OBJECT_TYPE") or get("CATEGORY")
    owner = owner or get("OWNER") or get("OWNER_NAME")
    category = category or get("CATEGORY") or get("SIGNAL")
    alert_type = alert_type or get("ALERT_TYPE") or get("SIGNAL")
    directory = directory if directory is not None and not directory.empty else default_owner_directory()

    values_to_match = [
        entity,
        get("DATABASE_NAME"),
        get("WAREHOUSE_NAME"),
        get("TASK_NAME"),
        get("PROCEDURE_NAME"),
        category,
        alert_type,
        get("SOURCE"),
    ]
    canonical_type = _canonical_entity_type(entity_type)
    type_candidates = _entity_type_candidates(entity_type, category, alert_type)
    if canonical_type:
        type_candidates.add(canonical_type)

    best_row: dict[str, Any] | None = None
    best_score = -1
    for _, candidate in directory.fillna("").iterrows():
        cand_type = _upper(candidate.get("ENTITY_TYPE")) or "GLOBAL"
        if cand_type not in type_candidates and cand_type not in {"GLOBAL", "ALERT"}:
            continue
        pattern = candidate.get("ENTITY_PATTERN") or "*"
        match_scores = [_wildcard_match(pattern, value)[1] for value in values_to_match]
        pattern_score = max(match_scores or [0])
        if pattern_score <= 0:
            continue
        priority = int(float(candidate.get("MATCH_PRIORITY") or 0))
        type_score = 85 if cand_type == canonical_type else 55 if cand_type in type_candidates else 5
        score = priority + type_score + pattern_score
        if score > best_score:
            best_score = score
            best_row = candidate.to_dict()

    if best_row is None:
        best_row = DEFAULT_OWNER_DIRECTORY[-1].copy()

    current_owner = _text(owner)
    directory_owner = _text(best_row.get("OWNER_NAME"))
    resolved_owner = directory_owner if _is_generic_owner(current_owner) else current_owner or directory_owner
    owner_key = _text(best_row.get("OWNER_KEY")) or "OWNER_DIRECTORY"
    pattern = _text(best_row.get("ENTITY_PATTERN")) or "*"
    resolved = {
        "OWNER": resolved_owner or "DBA",
        "OWNER_EMAIL": _text(best_row.get("OWNER_EMAIL")) or DEFAULT_ALERT_EMAIL,
        "ONCALL_PRIMARY": _text(best_row.get("ONCALL_PRIMARY")),
        "ONCALL_SECONDARY": _text(best_row.get("ONCALL_SECONDARY")),
        "APPROVAL_GROUP": _text(best_row.get("APPROVAL_GROUP")) or _text(best_row.get("ESCALATION_TARGET")),
        "ESCALATION_TARGET": _text(best_row.get("ESCALATION_TARGET")) or _text(best_row.get("APPROVAL_GROUP")),
        "OWNER_SOURCE": f"OWNER_DIRECTORY:{owner_key}",
        "OWNER_EVIDENCE": f"Matched {best_row.get('ENTITY_TYPE', 'GLOBAL')} pattern {pattern}",
    }
    return resolved


def enrich_owner_dataframe(
    df: pd.DataFrame,
    *,
    directory: pd.DataFrame | None = None,
    entity_column: str = "ENTITY_NAME",
    entity_type_column: str = "ENTITY_TYPE",
) -> pd.DataFrame:
    """Add owner context columns to a dataframe using the shared directory."""
    if df is None or df.empty:
        return df
    view = df.copy()
    directory = directory if directory is not None and not directory.empty else default_owner_directory()
    contexts = view.apply(
        lambda row: resolve_owner_context(
            row,
            directory=directory,
            entity=row.get(entity_column, ""),
            entity_type=row.get(entity_type_column, ""),
            owner=row.get("OWNER", ""),
        ),
        axis=1,
    )
    for column in OWNER_CONTEXT_COLUMNS:
        view[column] = contexts.apply(lambda context: context.get(column, ""))
    return view
