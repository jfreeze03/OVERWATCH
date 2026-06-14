"""Central OVERWATCH configuration.

This module is intentionally dependency-light. App startup imports it before
Snowflake or Streamlit sections are loaded, so navigation, company scoping, and
cost defaults should stay here instead of being repeated in section modules.
"""

from dataclasses import dataclass


CONFIG_VERSION = "2026-06-05-trexis-scope-v1"


DEFAULTS = {
    # Keep aligned with OVERWATCH_SETTINGS.CREDIT_PRICE_USD in the mart setup SQL.
    "credit_price": 3.68,
    "ai_credit_price": 2.20,
    "storage_cost_per_tb": 23.00,
    "rt_interval_sec": 30,
}

CREDIT_SOURCE_LABELS = {
    "warehouse_metering": "Official warehouse metering",
    "query_attribution": "Official query attribution",
    "metering_history": "Official account metering",
    "live_estimate": "Live estimate fallback",
}

DAY_WINDOW_OPTIONS = (1, 7, 14, 30, 60, 90)
DEFAULT_DAY_WINDOW = 7

TREXIS_WAREHOUSES = (
    "WH_TRXS_LOAD",
    "WH_TRXS_QUERY",
    "WH_TRXS_TRANSFORM",
    "WH_TRXS_UNLOAD",
)

ALFA_WAREHOUSES = (
    "BLCOMPUTE_WH",
    "COMPUTE_WH",
    "CROWDSTRIKE_WH",
    "DOC_ALWH",
    "POSIT_WORKBENCH",
    "SNOWFLAKE_LEARNING_WH",
    "SYSTEM$STREAMLIT_NOTEBOOK_WH",
    "WH_ALFA_ANALYTICS",
    "WH_ALFA_LOAD",
    "WH_ALFA_QA",
    "WH_ALFA_QUERY",
    "WH_ALFA_TRANSFORM",
    "WH_ALFA_UNLOAD",
)

ACCOUNT_WAREHOUSES = tuple(dict.fromkeys((*ALFA_WAREHOUSES, *TREXIS_WAREHOUSES)))

TREXIS_DATABASES = (
    "TRXS_ABC_METADATA_DEV",
    "TRXS_ABC_METADATA_PRD",
    "TRXS_ABC_METADATA_SIT",
    "TRXS_EDW_DEV",
    "TRXS_EDW_PRD",
    "TRXS_EDW_SIT",
    "TRXS_GW_DATA_DEV",
    "TRXS_GW_DATA_PRD",
    "TRXS_GW_DATA_SIT",
)
TREXIS_PROD_DATABASES = tuple(db for db in TREXIS_DATABASES if db.endswith("_PRD"))
TREXIS_DEV_DATABASES = tuple(db for db in TREXIS_DATABASES if db.endswith(("_DEV", "_SIT")))

ALFA_PROD_DATABASES = ("ALFA_EDW_PROD", "ALFA_EDW_MGM")
ALFA_DEV_DATABASES = (
    "ALFA_EDW_DEV",
    "ALFA_EDW_SAN",
    "ALFA_EDW_PHX",
    "ALFA_EDW_SEA",
    "ALFA_EDW_SIT",
)

THRESHOLDS = {
    "idle_warehouse_minutes": 10,
    "spill_warning_gb": 1.0,
    "query_duration_alert_sec": 300,
    "partition_scan_warning_pct": 80,
    "storage_cost_per_tb": DEFAULTS["storage_cost_per_tb"],
    "ai_credit_rate": DEFAULTS["ai_credit_price"],
    "error_rate_high": 10,
    "credit_spike_pct": 30,
    "queue_pressure": 5,
    "dormant_user_days": 90,
    "long_session_hours": 8,
    "task_failure_threshold": 3,
    "idle_credit_waste_min": 1.0,
    "remote_spill_alert_gb": 5.0,
    "replication_lag_warn_min": 120,
    "dynamic_table_lag_warn_min": 60,
    "ai_token_credit_watch": 25.0,
    "ai_request_watch": 1000,
    "openflow_credit_watch": 25.0,
    "adaptive_compute_credit_watch": 25.0,
    "adaptive_compute_query_watch": 500,
    "adaptive_compute_spill_watch_gb": 5.0,
}

CREDIT_RATES = {
    "X-Small": 1,
    "Small": 2,
    "Medium": 4,
    "Large": 8,
    "X-Large": 16,
    "2X-Large": 32,
    "3X-Large": 64,
    "4X-Large": 128,
    "5X-Large": 256,
    "6X-Large": 512,
}

COMPUTE_CREDIT_CASE = """
    CASE warehouse_size
        WHEN 'X-Small'  THEN 1   WHEN 'Small'    THEN 2
        WHEN 'Medium'   THEN 4   WHEN 'Large'    THEN 8
        WHEN 'X-Large'  THEN 16  WHEN '2X-Large' THEN 32
        WHEN '3X-Large' THEN 64  WHEN '4X-Large' THEN 128
        WHEN '5X-Large' THEN 256 WHEN '6X-Large' THEN 512
        ELSE 1
    END
"""

DEFAULT_COMPANY = "ALFA"

DEFAULT_ENVIRONMENT = "ALL"

ENVIRONMENT_CONFIG = {
    "ALL": {
        "label": "All environments",
        "db_patterns": [],
        "company_db_patterns": {},
    },
    "PROD": {
        "label": "PROD",
        "db_patterns": list(ALFA_PROD_DATABASES),
        "company_db_patterns": {
            "ALFA": list(ALFA_PROD_DATABASES),
            "Trexis": list(TREXIS_PROD_DATABASES),
        },
    },
    "DEV_ALL": {
        "label": "All DEV/Sandbox",
        "trexis_label": "All DEV/SIT",
        "db_patterns": list(ALFA_DEV_DATABASES),
        "company_db_patterns": {
            "ALFA": list(ALFA_DEV_DATABASES),
            "Trexis": list(TREXIS_DEV_DATABASES),
        },
    },
    "ALFA_EDW_DEV": {"label": "ALFA_EDW_DEV", "db_patterns": ["ALFA_EDW_DEV"]},
    "ALFA_EDW_SAN": {"label": "ALFA_EDW_SAN", "db_patterns": ["ALFA_EDW_SAN"]},
    "ALFA_EDW_PHX": {"label": "ALFA_EDW_PHX", "db_patterns": ["ALFA_EDW_PHX"]},
    "ALFA_EDW_SEA": {"label": "ALFA_EDW_SEA", "db_patterns": ["ALFA_EDW_SEA"]},
    "ALFA_EDW_SIT": {"label": "ALFA_EDW_SIT", "db_patterns": ["ALFA_EDW_SIT"]},
}

ENVIRONMENT_OPTIONS_BY_COMPANY = {
    "ALFA": tuple(ENVIRONMENT_CONFIG.keys()),
    "Trexis": ("ALL", "PROD", "DEV_ALL"),
    "ALL": tuple(ENVIRONMENT_CONFIG.keys()),
}


def static_warehouse_options(company: str | None = None) -> tuple[str, ...]:
    """Return confirmed warehouse choices without opening a Snowflake session."""
    company_key = str(company or DEFAULT_COMPANY)
    if company_key == "Trexis":
        return TREXIS_WAREHOUSES
    if company_key == "ALL":
        return ACCOUNT_WAREHOUSES
    return ALFA_WAREHOUSES


def static_database_options(
    company: str | None = None,
    environment: str | None = None,
) -> tuple[str, ...]:
    """Return confirmed database choices for the topbar triage scope without live metadata."""
    company_key = str(company or DEFAULT_COMPANY)
    env_key = str(environment or DEFAULT_ENVIRONMENT)

    if company_key == "Trexis":
        if env_key == "PROD":
            return TREXIS_PROD_DATABASES
        if env_key == "DEV_ALL":
            return TREXIS_DEV_DATABASES
        return TREXIS_DATABASES

    if company_key == "ALFA":
        if env_key == "PROD":
            return ALFA_PROD_DATABASES
        if env_key == "DEV_ALL":
            return ALFA_DEV_DATABASES
        if env_key in ALFA_PROD_DATABASES or env_key in ALFA_DEV_DATABASES:
            return (env_key,)
        return tuple(dict.fromkeys((*ALFA_PROD_DATABASES, *ALFA_DEV_DATABASES, "ADMIN")))

    if env_key == "PROD":
        return tuple(dict.fromkeys((*ALFA_PROD_DATABASES, *TREXIS_PROD_DATABASES)))
    if env_key == "DEV_ALL":
        return tuple(dict.fromkeys((*ALFA_DEV_DATABASES, *TREXIS_DEV_DATABASES)))
    if env_key in ALFA_PROD_DATABASES or env_key in ALFA_DEV_DATABASES:
        return (env_key,)
    return tuple(dict.fromkeys((*ALFA_PROD_DATABASES, *ALFA_DEV_DATABASES, *TREXIS_DATABASES, "ADMIN")))

# Manual architecture objectives used by Governance & Security architecture checks. These are not
# discovered from Snowflake; update them when ALFA/Trexis database families,
# execution warehouses, RPO/RTO expectations, or workload isolation policy
# changes.
ARCHITECTURE_OBJECTIVES = (
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "ALFA_EDW_PROD",
        "EXPECTED_ENVIRONMENT": "PROD",
        "WORKLOAD_CLASS": "Production EDW",
        "SERVICE_TIER": "Tier 0",
        "OWNER": "ALFA EDW Data Owner",
        "APPROVAL_GROUP": "DBA Lead / ALFA EDW Data Owner",
        "RPO_MINUTES": 120,
        "RTO_MINUTES": 240,
        "ISOLATION_POLICY": "Production EDW should use approved PROD routes; investigate broad shared-warehouse routing.",
        "CACHE_POLICY": "BI and reporting traffic should stay on warm, intentional warehouses when repeat-query evidence exists.",
        "CLUSTERING_POLICY": "Run table-specific clustering-depth proof before adding or changing clustering keys.",
        "DR_POLICY": "Failover or replication evidence, RPO/RTO owner approval, and drill notes are required.",
        "MATCH_PRIORITY": 220,
    },
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "ALFA_EDW_DEV",
        "EXPECTED_ENVIRONMENT": "DEV_ALL",
        "WORKLOAD_CLASS": "Development EDW",
        "SERVICE_TIER": "Tier 2",
        "OWNER": "ALFA Development Data Owner",
        "APPROVAL_GROUP": "DBA Lead / Development Platform Owner",
        "RPO_MINUTES": 1440,
        "RTO_MINUTES": 2880,
        "ISOLATION_POLICY": "DEV workloads can share approved DEV/Sandbox routes but should not spill into PROD warehouses.",
        "CACHE_POLICY": "Do not tune cache for one-off development queries unless repeated workload evidence exists.",
        "CLUSTERING_POLICY": "Avoid clustering DEV tables unless they mirror production access patterns and have DBA approval.",
        "DR_POLICY": "Restore or clone strategy is acceptable unless a named owner documents a stricter requirement.",
        "MATCH_PRIORITY": 180,
    },
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "ALFA_EDW_SAN",
        "EXPECTED_ENVIRONMENT": "DEV_ALL",
        "WORKLOAD_CLASS": "Sandbox EDW",
        "SERVICE_TIER": "Tier 2",
        "OWNER": "ALFA Development Data Owner",
        "APPROVAL_GROUP": "DBA Lead / Development Platform Owner",
        "RPO_MINUTES": 1440,
        "RTO_MINUTES": 2880,
        "ISOLATION_POLICY": "Sandbox workloads can share DEV/Sandbox compute but should be isolated from PROD routes.",
        "CACHE_POLICY": "Cache tuning is usually not justified unless repeated sandbox workload evidence is loaded.",
        "CLUSTERING_POLICY": "Do not add clustering keys without production-like predicate proof and cost review.",
        "DR_POLICY": "Document restore expectations; formal failover is not assumed for sandbox by default.",
        "MATCH_PRIORITY": 170,
    },
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "ALFA_EDW_PHX",
        "EXPECTED_ENVIRONMENT": "DEV_ALL",
        "WORKLOAD_CLASS": "Regional DEV EDW",
        "SERVICE_TIER": "Tier 2",
        "OWNER": "ALFA Development Data Owner",
        "APPROVAL_GROUP": "DBA Lead / Development Platform Owner",
        "RPO_MINUTES": 1440,
        "RTO_MINUTES": 2880,
        "ISOLATION_POLICY": "Regional DEV workloads can share DEV/Sandbox compute but must not be treated as PROD.",
        "CACHE_POLICY": "Tune only when repeated regional DEV query evidence is loaded.",
        "CLUSTERING_POLICY": "Validate table predicates and depth before any clustering key change.",
        "DR_POLICY": "Document restore or clone path before treating this as protected production data.",
        "MATCH_PRIORITY": 170,
    },
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "ALFA_EDW_SEA",
        "EXPECTED_ENVIRONMENT": "DEV_ALL",
        "WORKLOAD_CLASS": "Regional DEV EDW",
        "SERVICE_TIER": "Tier 2",
        "OWNER": "ALFA Development Data Owner",
        "APPROVAL_GROUP": "DBA Lead / Development Platform Owner",
        "RPO_MINUTES": 1440,
        "RTO_MINUTES": 2880,
        "ISOLATION_POLICY": "Regional DEV workloads can share DEV/Sandbox compute but must not be treated as PROD.",
        "CACHE_POLICY": "Tune only when repeated regional DEV query evidence is loaded.",
        "CLUSTERING_POLICY": "Validate table predicates and depth before any clustering key change.",
        "DR_POLICY": "Document restore or clone path before treating this as protected production data.",
        "MATCH_PRIORITY": 170,
    },
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "ALFA_EDW_SIT",
        "EXPECTED_ENVIRONMENT": "DEV_ALL",
        "WORKLOAD_CLASS": "SIT EDW",
        "SERVICE_TIER": "Tier 1",
        "OWNER": "ALFA SIT Data Owner",
        "APPROVAL_GROUP": "DBA Lead / SIT Owner",
        "RPO_MINUTES": 720,
        "RTO_MINUTES": 1440,
        "ISOLATION_POLICY": "SIT can share approved non-production compute but production-release validation should have a named route.",
        "CACHE_POLICY": "Review cache only for repeat release-cycle workloads that affect release validation.",
        "CLUSTERING_POLICY": "Keep clustering aligned with production-like validation predicates and approved cost posture.",
        "DR_POLICY": "Document refresh and recovery path for release-critical SIT data.",
        "MATCH_PRIORITY": 185,
    },
    *(
        {
            "COMPANY": "Trexis",
            "ENTITY_TYPE": "DATABASE",
            "ENTITY_PATTERN": database,
            "EXPECTED_ENVIRONMENT": "PROD",
            "WORKLOAD_CLASS": "Trexis production data",
            "SERVICE_TIER": "Tier 1",
            "OWNER": "Trexis Data Owner",
            "APPROVAL_GROUP": "Trexis Owner / DBA Lead",
            "RPO_MINUTES": 240,
            "RTO_MINUTES": 480,
            "ISOLATION_POLICY": "Route Trexis production data through approved Trexis PROD warehouses and owner-approved access paths.",
            "CACHE_POLICY": "Tune cache only from repeated Trexis production workload evidence.",
            "CLUSTERING_POLICY": "Use production query predicates and owner approval before clustering changes.",
            "DR_POLICY": "Confirm Trexis production data has documented recovery ownership and drill evidence.",
            "MATCH_PRIORITY": 205,
        }
        for database in TREXIS_PROD_DATABASES
    ),
    *(
        {
            "COMPANY": "Trexis",
            "ENTITY_TYPE": "DATABASE",
            "ENTITY_PATTERN": database,
            "EXPECTED_ENVIRONMENT": "DEV_ALL",
            "WORKLOAD_CLASS": "Trexis DEV/SIT data",
            "SERVICE_TIER": "Tier 2",
            "OWNER": "Trexis Development Data Owner",
            "APPROVAL_GROUP": "Trexis Owner / DBA Lead",
            "RPO_MINUTES": 1440,
            "RTO_MINUTES": 2880,
            "ISOLATION_POLICY": "Keep Trexis DEV and SIT data on approved non-production routes unless an owner-approved exception exists.",
            "CACHE_POLICY": "Do not tune cache for one-off DEV/SIT queries unless repeated workload evidence exists.",
            "CLUSTERING_POLICY": "Avoid clustering DEV/SIT tables without production-like predicate proof and cost review.",
            "DR_POLICY": "Document refresh or restore path before treating DEV/SIT data as protected production data.",
            "MATCH_PRIORITY": 175,
        }
        for database in TREXIS_DEV_DATABASES
    ),
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "WAREHOUSE",
        "ENTITY_PATTERN": "OVERWATCH_WH",
        "EXPECTED_ENVIRONMENT": "No Database Context",
        "WORKLOAD_CLASS": "OVERWATCH app execution compute",
        "SERVICE_TIER": "Tier 1",
        "OWNER": "OVERWATCH Platform Owner",
        "APPROVAL_GROUP": "DBA Lead / OVERWATCH Platform Owner",
        "RPO_MINUTES": 240,
        "RTO_MINUTES": 480,
        "ISOLATION_POLICY": "Dedicated Streamlit app execution warehouse; keep dashboard runtime separate from ALFA/Trexis workload warehouses.",
        "CACHE_POLICY": "Do not optimize business workload cache from app-execution evidence alone.",
        "CLUSTERING_POLICY": "Not applicable to warehouse settings.",
        "DR_POLICY": "App persistence objects, tasks, and email alerting need documented recovery ownership.",
        "MATCH_PRIORITY": 215,
    },
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "WAREHOUSE",
        "ENTITY_PATTERN": "COMPUTE_WH",
        "EXPECTED_ENVIRONMENT": "No Database Context",
        "WORKLOAD_CLASS": "OVERWATCH summary refresh and utility compute",
        "SERVICE_TIER": "Tier 1",
        "OWNER": "OVERWATCH Platform Owner",
        "APPROVAL_GROUP": "DBA Lead / OVERWATCH Platform Owner",
        "RPO_MINUTES": 240,
        "RTO_MINUTES": 480,
        "ISOLATION_POLICY": "Legacy mart task and utility warehouse; monitor cost separately from ALFA/Trexis workload warehouses.",
        "CACHE_POLICY": "Do not optimize business workload cache from app-execution evidence alone.",
        "CLUSTERING_POLICY": "Not applicable to warehouse settings.",
        "DR_POLICY": "App persistence objects, tasks, and email alerting need documented recovery ownership.",
        "MATCH_PRIORITY": 210,
    },
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "WAREHOUSE",
        "ENTITY_PATTERN": "BI_COMPUTE_WH",
        "EXPECTED_ENVIRONMENT": "ALL",
        "WORKLOAD_CLASS": "BI and reporting compute",
        "SERVICE_TIER": "Tier 1",
        "OWNER": "BI Platform Owner",
        "APPROVAL_GROUP": "BI Product Owner / DBA Lead",
        "RPO_MINUTES": 240,
        "RTO_MINUTES": 480,
        "ISOLATION_POLICY": "Repeated BI/reporting workloads should use stable BI routes and avoid mixed ad hoc traffic.",
        "CACHE_POLICY": "Prefer warm-cache behavior for repeat dashboards before increasing warehouse size.",
        "CLUSTERING_POLICY": "Use top BI predicates as clustering proof input, not warehouse-level evidence alone.",
        "DR_POLICY": "Confirm BI critical reports have documented fallback expectations.",
        "MATCH_PRIORITY": 200,
    },
    {
        "COMPANY": "ALFA",
        "ENTITY_TYPE": "WAREHOUSE",
        "ENTITY_PATTERN": "WH_ALFA_%",
        "EXPECTED_ENVIRONMENT": "ALL",
        "WORKLOAD_CLASS": "ALFA application workload compute",
        "SERVICE_TIER": "Tier 1",
        "OWNER": "ALFA Workload Owner",
        "APPROVAL_GROUP": "Application Owner / DBA Lead",
        "RPO_MINUTES": 240,
        "RTO_MINUTES": 480,
        "ISOLATION_POLICY": "Keep production, BI, ETL, and DEV/Sandbox routes intentional and owner approved.",
        "CACHE_POLICY": "Tune suspend/cache behavior only after repeated query-family evidence is loaded.",
        "CLUSTERING_POLICY": "Route top table candidates to query owners before clustering changes.",
        "DR_POLICY": "Link critical workload compute to protected database/object recovery expectations.",
        "MATCH_PRIORITY": 150,
    },
    *(
        {
            "COMPANY": "Trexis",
            "ENTITY_TYPE": "WAREHOUSE",
            "ENTITY_PATTERN": warehouse,
            "EXPECTED_ENVIRONMENT": "ALL",
            "WORKLOAD_CLASS": "Trexis workload compute",
            "SERVICE_TIER": "Tier 1",
            "OWNER": "Trexis Workload Owner",
            "APPROVAL_GROUP": "Trexis Owner / DBA Lead",
            "RPO_MINUTES": 240,
            "RTO_MINUTES": 480,
            "ISOLATION_POLICY": "Keep Trexis compute isolated from ALFA routes unless an owner-approved exception exists.",
            "CACHE_POLICY": "Tune cache only from Trexis repeated workload evidence.",
            "CLUSTERING_POLICY": "Use Trexis query predicates and owner approval before clustering changes.",
            "DR_POLICY": "Confirm Trexis critical data has documented recovery ownership.",
            "MATCH_PRIORITY": 180,
        }
        for warehouse in TREXIS_WAREHOUSES
    ),
    {
        "COMPANY": "ALL",
        "ENTITY_TYPE": "DATABASE",
        "ENTITY_PATTERN": "*",
        "EXPECTED_ENVIRONMENT": "ALL",
        "WORKLOAD_CLASS": "Unregistered database workload",
        "SERVICE_TIER": "Tier 2",
        "OWNER": "DBA / Platform Architecture",
        "APPROVAL_GROUP": "DBA Lead",
        "RPO_MINUTES": 1440,
        "RTO_MINUTES": 2880,
        "ISOLATION_POLICY": "Add a named architecture objective before approving routing, clustering, or DR posture.",
        "CACHE_POLICY": "Do not tune cache without named workload objective and repeated-query evidence.",
        "CLUSTERING_POLICY": "Do not cluster without table-specific proof and owner route.",
        "DR_POLICY": "Document RPO/RTO and protected scope before marking DR ready.",
        "MATCH_PRIORITY": 1,
    },
    {
        "COMPANY": "ALL",
        "ENTITY_TYPE": "WAREHOUSE",
        "ENTITY_PATTERN": "*",
        "EXPECTED_ENVIRONMENT": "ALL",
        "WORKLOAD_CLASS": "Unregistered warehouse workload",
        "SERVICE_TIER": "Tier 2",
        "OWNER": "DBA / Platform Architecture",
        "APPROVAL_GROUP": "DBA Lead",
        "RPO_MINUTES": 1440,
        "RTO_MINUTES": 2880,
        "ISOLATION_POLICY": "Add a named warehouse objective before changing routing or settings.",
        "CACHE_POLICY": "Do not tune cache without named workload objective and repeated-query evidence.",
        "CLUSTERING_POLICY": "Not applicable to warehouse settings.",
        "DR_POLICY": "Link warehouse-critical workloads to protected database/object recovery expectations.",
        "MATCH_PRIORITY": 1,
    },
    {
        "COMPANY": "ALL",
        "ENTITY_TYPE": "DR_GROUP",
        "ENTITY_PATTERN": "*",
        "EXPECTED_ENVIRONMENT": "ALL",
        "WORKLOAD_CLASS": "Snowflake DR object",
        "SERVICE_TIER": "Tier 0",
        "OWNER": "DBA / Platform Architecture",
        "APPROVAL_GROUP": "DBA Lead / Infrastructure Owner",
        "RPO_MINUTES": 120,
        "RTO_MINUTES": 240,
        "ISOLATION_POLICY": "Not applicable to DR group metadata.",
        "CACHE_POLICY": "Not applicable to DR group metadata.",
        "CLUSTERING_POLICY": "Not applicable to DR group metadata.",
        "DR_POLICY": "Every visible DR group needs protected object scope, schedule, RPO/RTO, target account, and drill evidence.",
        "MATCH_PRIORITY": 80,
    },
)

# Manual forward-platform controls for Snowflake capabilities that are emerging
# quickly: CoWork, Cortex Sense, Cortex Agents, MCP servers, Snowflake Intelligence,
# Openflow, Horizon, semantic models, and AI-assisted change workflows. These rows intentionally
# define DBA ownership and guardrails before broad adoption creates hidden risk.
FORWARD_PLATFORM_CONTROLS = (
    {
        "CONTROL_ID": "ADAPTIVE_COMPUTE_READINESS",
        "CONTROL_AREA": "Adaptive Compute Readiness",
        "OWNER": "DBA / Platform Architecture",
        "OWNER_KEY": "ADAPTIVE_COMPUTE_DEFAULT",
        "APPROVAL_GROUP": "DBA Lead / FinOps Lead",
        "PRIMARY_EVIDENCE": "SHOW WAREHOUSES; SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY; WAREHOUSE_METERING_HISTORY",
        "SOURCE_OBJECTS": "Standard warehouse transition candidates",
        "RISK_IF_MISSING": "Warehouse conversion decisions can be made without workload pressure, cost baseline, owner approval, or rollback evidence.",
        "DBA_DECISION": "Require owner-approved pilot, preview-limitation screen, before/after p95/queue/spill/cost proof, and rollback path before conversion.",
        "AUTOMATION_BOUNDARY": "Advisor only. Do not create, convert, or drop adaptive warehouses from dashboard automation.",
        "MATCH_PRIORITY": 245,
    },
    {
        "CONTROL_ID": "AI_AGENT_MCP_GOVERNANCE",
        "CONTROL_AREA": "Agent & MCP Governance",
        "OWNER": "DBA / AI Governance",
        "OWNER_KEY": "AI_AGENT_DEFAULT",
        "APPROVAL_GROUP": "DBA Lead / Security Approver",
        "PRIMARY_EVIDENCE": "SHOW AGENTS IN ACCOUNT; SHOW MCP SERVERS IN ACCOUNT",
        "SOURCE_OBJECTS": "Cortex Agents, MCP Servers",
        "RISK_IF_MISSING": "Agents or MCP tool endpoints can be created without owner, tool-scope review, or blast-radius evidence.",
        "DBA_DECISION": "Require owner, approved tool purpose, role scope, semantic source, and rollback plan before production use.",
        "AUTOMATION_BOUNDARY": "Inventory and queue only. Do not alter or drop agents/MCP servers from dashboard automation.",
        "MATCH_PRIORITY": 240,
    },
    {
        "CONTROL_ID": "CORTEX_SENSE_CONTEXT_GOVERNANCE",
        "CONTROL_AREA": "Cortex Sense Context Governance",
        "OWNER": "DBA / AI Governance",
        "OWNER_KEY": "CORTEX_SENSE_DEFAULT",
        "APPROVAL_GROUP": "DBA Lead / Data Governance Lead",
        "PRIMARY_EVIDENCE": "Cortex Sense context inventory when available; SEMANTIC_VIEWS; SEMANTIC_TABLES; SEMANTIC_METRICS; MCP server inventory; policy/access history",
        "SOURCE_OBJECTS": "Cortex Sense shared context, business definitions, semantic sources, MCP connectors, agent skills",
        "RISK_IF_MISSING": "Agents can appear trustworthy while using stale definitions, unowned semantic sources, or unapproved connector/tool context.",
        "DBA_DECISION": "Require context owner, semantic source certification, connector/tool approval, data classification proof, citation policy, and regression validation set before production adoption.",
        "AUTOMATION_BOUNDARY": "Readiness and queue only. Do not publish or mutate Cortex Sense context, skills, semantic models, or MCP connectors from dashboard automation.",
        "MATCH_PRIORITY": 238,
    },
    {
        "CONTROL_ID": "COWORK_ARTIFACT_GOVERNANCE",
        "CONTROL_AREA": "CoWork Artifact Governance",
        "OWNER": "DBA / Analytics Governance",
        "OWNER_KEY": "COWORK_ARTIFACT_DEFAULT",
        "APPROVAL_GROUP": "Analytics Owner / DBA Lead",
        "PRIMARY_EVIDENCE": "CoWork Artifact inventory when available; Snowflake Intelligence usage; semantic view ownership; dashboard/share/access policy evidence",
        "SOURCE_OBJECTS": "CoWork Artifacts, publishable dashboards, shared AI outputs, governed live-data views",
        "RISK_IF_MISSING": "Knowledge workers can create shared dashboards or artifacts that look official while bypassing certified metrics, data owner approval, or access-review evidence.",
        "DBA_DECISION": "Require owner, certified data source, semantic validation set, sensitivity classification, sharing scope, freshness SLA, and retirement plan before publishing artifacts broadly.",
        "AUTOMATION_BOUNDARY": "Inventory, readiness, and queue only. Do not publish, share, delete, or alter CoWork Artifacts from dashboard automation.",
        "MATCH_PRIORITY": 236,
    },
    {
        "CONTROL_ID": "AI_SPEND_TOKEN_GUARDRAILS",
        "CONTROL_AREA": "AI Spend & Token Guardrails",
        "OWNER": "DBA / FinOps",
        "OWNER_KEY": "AI_COST_DEFAULT",
        "APPROVAL_GROUP": "FinOps Lead / DBA Lead",
        "PRIMARY_EVIDENCE": "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY; SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY",
        "SOURCE_OBJECTS": "Cortex Agent usage, Snowflake Intelligence usage",
        "RISK_IF_MISSING": "AI usage can create token-credit spend with weak user, role, interface, or owner accountability.",
        "DBA_DECISION": "Route high-credit, external-interface, or privileged-role usage to owners with Snowflake budget, quota, and custom-action review.",
        "AUTOMATION_BOUNDARY": "Generate budget and quota deployment SQL, alert, and queue only. Do not auto-revoke AI access or change budget limits without approval.",
        "MATCH_PRIORITY": 230,
    },
    {
        "CONTROL_ID": "AI_SECURITY_GUARDRAILS",
        "CONTROL_AREA": "AI Security Guardrails",
        "OWNER": "DBA / AI Governance",
        "OWNER_KEY": "AI_SECURITY_DEFAULT",
        "APPROVAL_GROUP": "DBA Lead / Security Approver",
        "PRIMARY_EVIDENCE": "AI_SETTINGS; CORTEX_ENABLED_CROSS_REGION; SHOW GRANTS TO ROLE PUBLIC; SNOWFLAKE.DATA_SECURITY reports",
        "SOURCE_OBJECTS": "Cortex AI Guardrails, AI function privileges, sensitive-data entitlement/access reports",
        "RISK_IF_MISSING": "AI workloads can run without prompt-injection guardrails, granular function privileges, or proof of who can access sensitive data.",
        "DBA_DECISION": "Require account-level AI guardrails, narrow per-function grants, no PUBLIC blanket AI access, and sensitive-data report visibility before production AI expansion.",
        "AUTOMATION_BOUNDARY": "Readiness and queue only. Do not change account parameters or revoke/grant AI privileges from dashboard automation.",
        "MATCH_PRIORITY": 225,
    },
    {
        "CONTROL_ID": "OPENFLOW_OPERABILITY",
        "CONTROL_AREA": "Openflow Operations",
        "OWNER": "DBA / Integration Platform",
        "OWNER_KEY": "OPENFLOW_DEFAULT",
        "APPROVAL_GROUP": "Data Engineering Lead / DBA Lead",
        "PRIMARY_EVIDENCE": "SNOWFLAKE.ACCOUNT_USAGE.OPENFLOW_USAGE_HISTORY",
        "SOURCE_OBJECTS": "Openflow data planes and runtimes",
        "RISK_IF_MISSING": "Managed ingestion runtimes can consume credits or move sensitive data without DBA operating evidence.",
        "DBA_DECISION": "Track runtime credits, data-plane type, owner, secret/auth posture, and recovery playbook before expanding.",
        "AUTOMATION_BOUNDARY": "Observe and queue. Do not stop runtimes or deployments from the dashboard.",
        "MATCH_PRIORITY": 220,
    },
    {
        "CONTROL_ID": "HORIZON_GOVERNANCE_READINESS",
        "CONTROL_AREA": "Horizon Governance Readiness",
        "OWNER": "DBA / Data Governance",
        "OWNER_KEY": "HORIZON_GOVERNANCE_DEFAULT",
        "APPROVAL_GROUP": "Data Governance Lead / Security Approver",
        "PRIMARY_EVIDENCE": "DATA_CLASSIFICATION_LATEST, POLICY_REFERENCES, ACCESS_HISTORY, OBJECT_DEPENDENCIES",
        "SOURCE_OBJECTS": "Classification, policies, lineage, access history",
        "RISK_IF_MISSING": "The account may not be ready to prove classification, policy coverage, lineage, and access behavior across engines.",
        "DBA_DECISION": "Make governance observability visible before adopting broader Horizon, Marketplace, or cross-engine access patterns.",
        "AUTOMATION_BOUNDARY": "Readiness only. Do not change policies or tags automatically.",
        "MATCH_PRIORITY": 210,
    },
    {
        "CONTROL_ID": "SEMANTIC_TRUST_VALIDATION",
        "CONTROL_AREA": "Semantic Trust & Verified Query Validation",
        "OWNER": "DBA / Analytics Governance",
        "OWNER_KEY": "SEMANTIC_TRUST_DEFAULT",
        "APPROVAL_GROUP": "Analytics Owner / DBA Lead",
        "PRIMARY_EVIDENCE": "SEMANTIC_VIEWS, SEMANTIC_TABLES, SEMANTIC_METRICS",
        "SOURCE_OBJECTS": "Semantic model metadata",
        "RISK_IF_MISSING": "Agent or analyst answers can look authoritative while using unowned or uncertified semantic definitions.",
        "DBA_DECISION": "Require owner, certified model, validation query set, freshness proof, and regression checks before trusted use.",
        "AUTOMATION_BOUNDARY": "Validate and queue only. Do not rewrite semantic models automatically.",
        "MATCH_PRIORITY": 200,
    },
    {
        "CONTROL_ID": "BCDR_DRILL_LEDGER",
        "CONTROL_AREA": "BCDR Drill Ledger",
        "OWNER": "DBA / Platform Architecture",
        "OWNER_KEY": "BCDR_DRILL_DEFAULT",
        "APPROVAL_GROUP": "DBA Lead / Infrastructure Owner",
        "PRIMARY_EVIDENCE": "SHOW FAILOVER GROUPS; SHOW REPLICATION GROUPS; REPLICATION_GROUP_USAGE_HISTORY; BACKUP_OPERATION_HISTORY",
        "SOURCE_OBJECTS": "Failover groups, replication groups, backup operation history",
        "RISK_IF_MISSING": "DR can be configured but unproven, with no RPO/RTO drill record or recovery owner.",
        "DBA_DECISION": "Keep a drill ledger with protected scope, target account, last success, failure notes, and next drill date.",
        "AUTOMATION_BOUNDARY": "Never execute failover from dashboard automation.",
        "MATCH_PRIORITY": 190,
    },
    {
        "CONTROL_ID": "AI_CHANGE_GOVERNANCE",
        "CONTROL_AREA": "AI Change Governance",
        "OWNER": "DBA Change Owner",
        "OWNER_KEY": "AI_CHANGE_GOVERNANCE_DEFAULT",
        "APPROVAL_GROUP": "Change Advisory / DBA Lead",
        "PRIMARY_EVIDENCE": "CORTEX_CODE_CLI_USAGE_HISTORY; CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY; CORTEX_AISQL_USAGE_HISTORY",
        "SOURCE_OBJECTS": "Cortex Code, Cortex AISQL, AI-assisted SQL",
        "RISK_IF_MISSING": "AI-assisted code or SQL can bypass owner approval, rollback proof, and verification evidence.",
        "DBA_DECISION": "Treat AI-generated DDL/SQL like any other change: ticket, source, reviewer, rollout, rollback, and verification.",
        "AUTOMATION_BOUNDARY": "Observe usage and route to Governance & Security change control. Do not execute generated changes automatically.",
        "MATCH_PRIORITY": 180,
    },
)

# Warehouse inventory confirmed from Snowflake UI:
# Trexis uses only the four WH_TRXS_* warehouses below; every other warehouse belongs to ALFA.
COMPANY_CONFIG = {
    "ALFA": {
        "wh_patterns": [],
        "wh_exclude_patterns": list(TREXIS_WAREHOUSES),
        "db_patterns": ["ADMIN", "ALFA%"],
        "db_exclude_patterns": list(TREXIS_DATABASES),
        "exclude_db_pattern": "",
        "user_patterns": [],
        "user_exclude_patterns": ["TRXS_%"],
        "label": "ALFA",
        "color": "#34d399",
    },
    "Trexis": {
        "wh_patterns": list(TREXIS_WAREHOUSES),
        "wh_exclude_patterns": [],
        "db_patterns": list(TREXIS_DATABASES),
        "db_exclude_patterns": [],
        "exclude_db_pattern": "",
        "user_patterns": ["TRXS_%"],
        "user_exclude_patterns": [],
        "label": "Trexis",
        "color": "#c084fc",
    },
    "ALL": {
        "wh_patterns": [],
        "wh_exclude_patterns": [],
        "db_patterns": [],
        "db_exclude_patterns": [],
        "exclude_db_pattern": "",
        "user_patterns": [],
        "user_exclude_patterns": [],
        "label": "ALL",
        "color": "#38bdf8",
    },
}


@dataclass(frozen=True)
class SectionDefinition:
    group: str
    icon: str
    title: str
    module: str

    @property
    def label(self) -> str:
        return self.title


# Production navigation exposes only the command-center surfaces that should be
# first-class in front of DBAs and leadership. Legacy redirect aliases below
# keep deep links working without keeping weak standalone pages alive.
SECTION_DEFINITIONS = (
    SectionDefinition("COMMAND CENTER", "briefcase", "Executive Landing", "sections.executive_landing_shell"),
    SectionDefinition("COMMAND CENTER", "target", "DBA Control Room", "sections.dba_control_room_shell"),
    SectionDefinition("COMMAND CENTER", "bell", "Alert Center", "sections.alert_center_shell"),
    SectionDefinition("FINANCIAL CONTROL", "cost", "Cost & Contract", "sections.cost_contract_shell"),
    SectionDefinition("OPERATIONS", "work", "Workload Operations", "sections.workload_operations_shell"),
    SectionDefinition("GOVERNANCE", "security", "Governance & Security", "sections.governance_security"),
)

PRIMARY_NAV_HIDDEN_SECTIONS = frozenset()

NAV_GROUPS: dict[str, list[str]] = {}
for _section in SECTION_DEFINITIONS:
    if _section.label in PRIMARY_NAV_HIDDEN_SECTIONS:
        continue
    NAV_GROUPS.setdefault(_section.group, []).append(_section.label)

ALL_SECTIONS = [_section.label for _section in SECTION_DEFINITIONS]
PRIMARY_SECTIONS = [section for section in ALL_SECTIONS if section not in PRIMARY_NAV_HIDDEN_SECTIONS]
SECTION_MODULES = {_section.label: _section.module for _section in SECTION_DEFINITIONS}
_CANONICAL_SECTION_BY_TITLE = {_section.title: _section.label for _section in SECTION_DEFINITIONS}
SECTION_REDIRECTS = {
    "Executive Briefing": _CANONICAL_SECTION_BY_TITLE["Executive Landing"],
    "Executive Evidence": _CANONICAL_SECTION_BY_TITLE["Executive Landing"],
    "Query Workbench": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Live Monitor": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Detailed Diagnosis": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Query Analysis": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Query Search & History": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Task Management": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Pipeline Health": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Stored Proc Tracker": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Cost Center": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Credit Contract": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Recommendations & Anomalies": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Snowflake Value": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "AI & Cortex Monitor": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "SPCS Tracker": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Usage Overview": _CANONICAL_SECTION_BY_TITLE["DBA Control Room"],
    "Service Health": _CANONICAL_SECTION_BY_TITLE["DBA Control Room"],
    "Alerts": _CANONICAL_SECTION_BY_TITLE["Alert Center"],
    "Alert History": _CANONICAL_SECTION_BY_TITLE["Alert Center"],
    "Alert Configuration": _CANONICAL_SECTION_BY_TITLE["Alert Center"],
    "Adoption Analytics": _CANONICAL_SECTION_BY_TITLE["Executive Landing"],
    "Storage Monitor": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Platform Topology": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Security Posture": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Security & Access": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Data Sharing": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Change & Drift": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Who Changed What?": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "DBA Tools": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Command Center": _CANONICAL_SECTION_BY_TITLE["DBA Control Room"],
    "Warehouse Health": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Optimization": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Architecture Readiness": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Architecture": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Platform Architecture": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Workload Isolation": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Clustering Strategy": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Cache Optimization": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "DR Readiness": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Disaster Recovery": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
}
RETIRED_SECTION_REDIRECTS = {
    "Account Health": _CANONICAL_SECTION_BY_TITLE["DBA Control Room"],
    "Warehouse Health": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Architecture Readiness": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Security Posture": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
    "Change & Drift": _CANONICAL_SECTION_BY_TITLE["Governance & Security"],
}
SECTION_ROUTE_STATE = {
    "Account Health": {
        "dba_control_room_active_view": "Morning Brief",
        "_dba_control_room_full_workspace_requested": True,
        "_dba_control_room_brief_mode": False,
    },
    "Warehouse Health": {
        "cost_contract_workflow": "Recommendations and action queue",
        "_cost_contract_full_workspace_requested": True,
        "_cost_contract_brief_mode": False,
    },
    "Optimization": {
        "cost_contract_workflow": "Recommendations and action queue",
        "_cost_contract_full_workspace_requested": True,
        "_cost_contract_brief_mode": False,
    },
    "Security Posture": {
        "governance_security_view": "Security Posture",
        "_governance_security_full_workspace_requested": True,
    },
    "Change & Drift": {
        "governance_security_view": "Change & Drift",
        "_governance_security_full_workspace_requested": True,
    },
    "Who Changed What?": {
        "governance_security_view": "Change & Drift",
        "change_drift_requested_workflow": "Object and access changes",
        "_governance_security_full_workspace_requested": True,
    },
    "DBA Tools": {
        "governance_security_view": "Change & Drift",
        "change_drift_requested_workflow": "Controlled DBA actions",
        "_governance_security_full_workspace_requested": True,
    },
    "Architecture Readiness": {
        "governance_security_view": "Change & Drift",
        "change_drift_requested_workflow": "Schema and object drift",
        "_governance_security_full_workspace_requested": True,
    },
}
SECTION_BY_TITLE = dict(_CANONICAL_SECTION_BY_TITLE)
SECTION_ICONS = {_section.title: _section.icon for _section in SECTION_DEFINITIONS}

SECTION_ALIASES = {
    **_CANONICAL_SECTION_BY_TITLE,
    **SECTION_REDIRECTS,
    **RETIRED_SECTION_REDIRECTS,
}


def normalize_section_name(section: str) -> str:
    """Return the current canonical section name for a route or alias."""
    return SECTION_ALIASES.get(str(section or "").strip(), str(section or "").strip())


def compatibility_state_for_section(section: str) -> dict[str, object]:
    """Return session-state adjustments for retired routes that now open a canonical workflow."""
    return dict(SECTION_ROUTE_STATE.get(str(section or "").strip(), {}))


def _sections_by_title(*titles: str) -> list[str]:
    return [SECTION_BY_TITLE[title] for title in titles]


# Role profiles keep users on the same production shell while reducing access
# to workflows where the selected experience view should not expose controls.
ROLE_SECTIONS = {
    "EXECUTIVE": _sections_by_title(
        "Executive Landing",
        "DBA Control Room",
        "Alert Center",
        "Cost & Contract",
    ),
    "ANALYST": _sections_by_title(
        "Executive Landing",
        "DBA Control Room",
        "Alert Center",
        "Workload Operations",
        "Cost & Contract",
        "Governance & Security",
    ),
    "MANAGER": list(PRIMARY_SECTIONS),
    "REPORT": _sections_by_title(
        "Executive Landing",
        "DBA Control Room",
        "Alert Center",
        "Workload Operations",
        "Cost & Contract",
        "Governance & Security",
    ),
    "DBA": list(PRIMARY_SECTIONS),
    "SYSADMIN": list(PRIMARY_SECTIONS),
    "ACCOUNTADMIN": list(PRIMARY_SECTIONS),
}

ROLE_PROFILE_OVERRIDES = {
    # ALFA production access roles.
    "SNOW_PRI_GFR_PRD_ALFA_PDMWMGMT": "EXECUTIVE",
    "SNOW_PRI_GFR_PRD_ALFA_DSA": "MANAGER",
    "SNOW_PRI_GFR_PRD_ALFA_DTI": "ANALYST",
    # ALFA non-production access roles.
    "SNOW_PRI_GFR_NONPRD_ALFA_PDMWMGMT": "EXECUTIVE",
    "SNOW_PRI_GFR_NONPRD_ALFA_DSA": "MANAGER",
    "SNOW_PRI_GFR_NONPRD_ALFA_DTI": "ANALYST",
    # DBA/admin deployment roles.
    "SNOW_ACCOUNTADMINS": "DBA",
    "SNOW_SYSADMINS": "DBA",
    "ACCOUNTADMIN": "DBA",
}


def resolve_role_profile(role: str) -> str:
    """Return the OVERWATCH navigation profile for a Snowflake role name."""
    normalized = str(role or "").strip().upper()
    if not normalized:
        return "REPORT"
    if normalized in ROLE_PROFILE_OVERRIDES:
        return ROLE_PROFILE_OVERRIDES[normalized]
    if normalized.endswith("_DSA") or "_DSA_" in normalized:
        return "MANAGER"
    if normalized.endswith("_DTI") or "_DTI_" in normalized:
        return "ANALYST"
    if normalized.endswith("_PDMWMGMT") or "_PDMWMGMT_" in normalized:
        return "EXECUTIVE"
    if "ACCOUNTADMIN" in normalized or "SYSADMIN" in normalized or "DBA" in normalized:
        return "DBA"
    for profile in ROLE_SECTIONS:
        if profile in normalized:
            return profile
    return "REPORT"


EXPERIENCE_VIEW_SECTIONS = {
    "DBA": list(PRIMARY_SECTIONS),
    "Executive": _sections_by_title(
        "Executive Landing",
        "DBA Control Room",
        "Alert Center",
        "Cost & Contract",
    ),
    "FinOps": _sections_by_title(
        "Executive Landing",
        "Cost & Contract",
        "Alert Center",
        "Governance & Security",
    ),
    "Security": _sections_by_title(
        "Executive Landing",
        "Alert Center",
        "Governance & Security",
    ),
    "Platform": _sections_by_title(
        "Executive Landing",
        "DBA Control Room",
        "Workload Operations",
        "Cost & Contract",
        "Governance & Security",
    ),
}

ROLE_EXPERIENCE_VIEWS = {
    "EXECUTIVE": ("Executive",),
    "ANALYST": ("Platform",),
    "MANAGER": ("Executive", "FinOps", "Security", "Platform"),
    "REPORT": ("Executive",),
    "DBA": tuple(EXPERIENCE_VIEW_SECTIONS.keys()),
    "SYSADMIN": tuple(EXPERIENCE_VIEW_SECTIONS.keys()),
    "ACCOUNTADMIN": tuple(EXPERIENCE_VIEW_SECTIONS.keys()),
}


def resolve_allowed_experience_views(role: str) -> tuple[str, ...]:
    """Return the Experience View choices allowed for a Snowflake role."""
    profile = resolve_role_profile(role)
    allowed = ROLE_EXPERIENCE_VIEWS.get(profile, ROLE_EXPERIENCE_VIEWS["DBA"])
    return tuple(view for view in allowed if view in EXPERIENCE_VIEW_SECTIONS) or ("DBA",)


def default_experience_view_for_role(role: str) -> str:
    """Return the first useful Experience View for the current Snowflake role."""
    profile = resolve_role_profile(role)
    preferred = {
        "EXECUTIVE": "Executive",
        "MANAGER": "Executive",
        "REPORT": "Executive",
        "ANALYST": "Platform",
        "DBA": "DBA",
        "SYSADMIN": "DBA",
        "ACCOUNTADMIN": "DBA",
    }.get(profile, "DBA")
    allowed = resolve_allowed_experience_views(role)
    return preferred if preferred in allowed else allowed[0]


ETL_AUDIT_DB = "DBA_MAINT_DB"
ETL_AUDIT_SCHEMA = "OVERWATCH"
ETL_AUDIT_TABLE = "ETL_RUN_AUDIT"

ALERT_DB = "DBA_MAINT_DB"
ALERT_SCHEMA = "OVERWATCH"
ALERT_TABLE = "OVERWATCH_ALERTS"
# Public-repo default only. Replace in the app Settings panel or deployment config
# before enabling scheduled alert delivery.
DEFAULT_ALERT_EMAILS = ("dba-alerts@yourcompany.com",)
DEFAULT_ALERT_EMAIL = ",".join(DEFAULT_ALERT_EMAILS)
ALERT_DELIVERY_METHOD = "EMAIL"

ACTION_QUEUE_TABLE = "OVERWATCH_ACTION_QUEUE"
