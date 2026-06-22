"""Central OVERWATCH configuration.

This module is intentionally dependency-light. App startup imports it before
Snowflake or Streamlit sections are loaded, so navigation, company scoping, and
cost defaults should stay here instead of being repeated in section modules.
"""

from dataclasses import dataclass


CONFIG_VERSION = "2026-06-05-trexis-scope-v1"


DEFAULTS = {
    # Keep aligned with OVERWATCH_SETTINGS.CREDIT_PRICE_USD in the setup bundle.
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
TREXIS_WAREHOUSE_PATTERNS = tuple(dict.fromkeys((*TREXIS_WAREHOUSES, "WH_TRXS%")))

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

WAREHOUSE_ADVISOR_CONFIG = {
    # Savings rates are directional until a complete post-change telemetry window
    # confirms lower credits without worse queue, spill, p95, or failures.
    "auto_suspend_savings_rates": (
        (1000, 0.25),
        (600, 0.15),
        (300, 0.08),
        (0, 0.50),
    ),
    "default_auto_suspend_sec": 300,
    "pressure_queue_sec": 5.0,
    "pressure_p95_sec": 120.0,
    "pressure_spill_gb": THRESHOLDS["spill_warning_gb"],
    "downsize_min_monthly_usd": 100.0,
    "downsize_max_queue_sec": 1.0,
    "downsize_max_spill_gb": 1.0,
    "downsize_max_p95_sec": 30.0,
    "downsize_recoverable_rate": 0.40,
    "verification_window_days": 7,
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

# Warehouse inventory confirmed from Snowflake UI:
# Trexis currently uses the four known WH_TRXS_* warehouses; the pattern keeps
# future WH_TRXS warehouses out of ALFA until the static dropdown is refreshed.
COMPANY_CONFIG = {
    "ALFA": {
        "wh_patterns": [],
        "wh_exclude_patterns": list(TREXIS_WAREHOUSE_PATTERNS),
        "db_patterns": ["ADMIN", "ALFA%"],
        "db_exclude_patterns": list(TREXIS_DATABASES),
        "exclude_db_pattern": "",
        "user_patterns": [],
        "user_exclude_patterns": ["TRXS_%"],
        "role_patterns": [],
        "role_exclude_patterns": ["%TRXS%"],
        "label": "ALFA",
        "color": "#34d399",
    },
    "Trexis": {
        "wh_patterns": list(TREXIS_WAREHOUSE_PATTERNS),
        "wh_exclude_patterns": [],
        "db_patterns": list(TREXIS_DATABASES),
        "db_exclude_patterns": [],
        "exclude_db_pattern": "",
        "user_patterns": ["TRXS_%"],
        "user_exclude_patterns": [],
        "role_patterns": ["%TRXS%"],
        "role_exclude_patterns": [],
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
        "role_patterns": [],
        "role_exclude_patterns": [],
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


# Production navigation exposes only the monitoring surfaces that should be
# first-class in front of DBAs and leadership. Legacy redirect aliases below
# keep deep links working without keeping weak standalone pages alive.
SECTION_DEFINITIONS = (
    SectionDefinition("MONITORING CORE", "briefcase", "Executive Landing", "sections.executive_landing"),
    SectionDefinition("MONITORING CORE", "target", "DBA Control Room", "sections.dba_control_room"),
    SectionDefinition("MONITORING CORE", "bell", "Alert Center", "sections.alert_center"),
    SectionDefinition("FINANCIAL CONTROL", "cost", "Cost & Contract", "sections.cost_contract"),
    SectionDefinition("OPERATIONS", "work", "Workload Operations", "sections.workload_operations"),
    SectionDefinition("SECURITY", "security", "Security Monitoring", "sections.security_posture"),
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
    "Query Workbench": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Live Monitor": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Detailed Diagnosis": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Query Analysis": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Query Search & History": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Task Management": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Pipeline Health": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Stored Proc Tracker": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Object Change Monitor": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Schema Compare": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Data Compare": _CANONICAL_SECTION_BY_TITLE["Workload Operations"],
    "Cost Center": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Credit Contract": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Recommendations": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Recommendations & Anomalies": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Cortex Monitor": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "AI & Cortex Monitor": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "SPCS Tracker": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Usage Overview": _CANONICAL_SECTION_BY_TITLE["DBA Control Room"],
    "Service Health": _CANONICAL_SECTION_BY_TITLE["DBA Control Room"],
    "Alerts": _CANONICAL_SECTION_BY_TITLE["Alert Center"],
    "Alert History": _CANONICAL_SECTION_BY_TITLE["Alert Center"],
    "Alert Configuration": _CANONICAL_SECTION_BY_TITLE["Alert Center"],
    "Adoption Analytics": _CANONICAL_SECTION_BY_TITLE["Executive Landing"],
    "Storage Monitor": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Security Posture": _CANONICAL_SECTION_BY_TITLE["Security Monitoring"],
    "Security & Access": _CANONICAL_SECTION_BY_TITLE["Security Monitoring"],
    "Data Sharing": _CANONICAL_SECTION_BY_TITLE["Security Monitoring"],
    "Command Center": _CANONICAL_SECTION_BY_TITLE["DBA Control Room"],
    "Warehouse Health": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Optimization": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
}
RETIRED_SECTION_REDIRECTS = {
    "Account Health": _CANONICAL_SECTION_BY_TITLE["DBA Control Room"],
    "Warehouse Health": _CANONICAL_SECTION_BY_TITLE["Cost & Contract"],
    "Security Posture": _CANONICAL_SECTION_BY_TITLE["Security Monitoring"],
}
SECTION_ROUTE_STATE = {
    "Account Health": {
        "dba_control_room_active_view": "Fast Watch",
        "_dba_control_room_full_workspace_requested": True,
        "_dba_control_room_brief_mode": False,
    },
    "Warehouse Health": {
        "cost_contract_workflow": "Waste Detection",
        "_cost_contract_full_workspace_requested": True,
        "_cost_contract_brief_mode": False,
    },
    "Optimization": {
        "cost_contract_workflow": "Cost Recommendations",
        "_cost_contract_full_workspace_requested": True,
        "_cost_contract_brief_mode": False,
    },
    "Cost Center": {
        "cost_contract_workflow": "Cost by Warehouse",
    },
    "Credit Contract": {
        "cost_contract_workflow": "Budget vs Actual",
    },
    "Recommendations & Anomalies": {
        "cost_contract_workflow": "Cost Recommendations",
    },
    "Recommendations": {
        "cost_contract_workflow": "Cost Recommendations",
    },
    "Cortex Monitor": {
        "cost_contract_workflow": "Cost Overview",
        "cost_contract_advanced_tool": "Cortex Spend",
        "_cost_contract_show_advanced_tools": True,
    },
    "AI & Cortex Monitor": {
        "cost_contract_workflow": "Cost Overview",
        "cost_contract_advanced_tool": "Cortex Spend",
        "_cost_contract_show_advanced_tools": True,
    },
    "Storage Monitor": {
        "cost_contract_workflow": "Cost Overview",
        "cost_contract_advanced_tool": "Storage & Retention",
        "_cost_contract_show_advanced_tools": True,
    },
    "SPCS Tracker": {
        "cost_contract_workflow": "Cost Overview",
        "cost_contract_advanced_tool": "SPCS Spend",
        "_cost_contract_show_advanced_tools": True,
    },
    "Alerts": {
        "alert_center_active_view": "Active Alerts",
    },
    "Alert History": {
        "alert_center_active_view": "Alert History",
    },
    "Alert Configuration": {
        "alert_center_active_view": "Alert Settings / Admin",
        "alert_center_admin_view": "Delivery & Automation",
    },
    "Security Posture": {
        "security_posture_view": "Failed Logins",
    },
    "Query Workbench": {
        "workload_operations_workflow": "Query Investigation",
    },
    "Query Analysis": {
        "workload_operations_workflow": "Query Investigation",
    },
    "Query Search & History": {
        "workload_operations_workflow": "Query Investigation",
        "query_analysis_active_view": "History Search",
    },
    "Detailed Diagnosis": {
        "workload_operations_workflow": "Query Investigation",
        "query_analysis_active_view": "Detailed Diagnosis",
    },
    "Live Monitor": {
        "workload_operations_workflow": "Performance & Contention",
    },
    "Task Management": {
        "workload_operations_workflow": "Pipeline & Task Health",
        "workload_operations_pipeline_focus": "Failed Tasks",
    },
    "Pipeline Health": {
        "workload_operations_workflow": "Pipeline & Task Health",
        "workload_operations_pipeline_focus": "Load Issues & SLA",
    },
    "Stored Proc Tracker": {
        "workload_operations_workflow": "Pipeline & Task Health",
        "workload_operations_pipeline_focus": "Failed Procedures",
    },
    "Object Change Monitor": {
        "workload_operations_workflow": "Change Analysis",
    },
    "Schema Compare": {
        "workload_operations_workflow": "Advanced DBA Tools",
        "dba_tools_focus": "Object Monitoring",
        "dba_tools_focus_tool": "Schema Compare",
        "dba_tools_group_selector": "Object Monitoring",
    },
    "Data Compare": {
        "workload_operations_workflow": "Advanced DBA Tools",
        "dba_tools_focus": "Object Monitoring",
        "dba_tools_focus_tool": "Data Compare",
        "dba_tools_group_selector": "Object Monitoring",
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


ADMIN_ACCESS_ROLES = (
    "SNOW_ACCOUNTADMINS",
    "SNOW_SYSADMINS",
)


ETL_AUDIT_DB = "DBA_MAINT_DB"
ETL_AUDIT_SCHEMA = "OVERWATCH"
ETL_AUDIT_TABLE = "ETL_RUN_AUDIT"

ALERT_DB = "DBA_MAINT_DB"
ALERT_SCHEMA = "OVERWATCH"
ALERT_TABLE = "OVERWATCH_ALERTS"
# Approved release-candidate recipient. Override with OVERWATCH_SETTINGS in
# Snowflake or Settings when governance changes the delivery route.
DEFAULT_ALERT_EMAILS: tuple[str, ...] = ("jdees@alfains.com",)
DEFAULT_ALERT_EMAIL = ",".join(DEFAULT_ALERT_EMAILS)
ALERT_DELIVERY_METHOD = "EMAIL"

ACTION_QUEUE_TABLE = "OVERWATCH_ACTION_QUEUE"
