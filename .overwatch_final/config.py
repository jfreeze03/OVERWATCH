"""Central OVERWATCH configuration.

This module is intentionally dependency-light. App startup imports it before
Snowflake or Streamlit sections are loaded, so navigation, company scoping, and
cost defaults should stay here instead of being repeated in section modules.
"""

from dataclasses import dataclass


DEFAULTS = {
    "credit_price": 3.00,
    "ai_credit_price": 2.20,
    "storage_cost_per_tb": 23.00,
    "rt_interval_sec": 30,
}

THRESHOLDS = {
    "idle_warehouse_minutes": 10,
    "spill_warning_gb": 1.0,
    "query_duration_alert_sec": 300,
    "partition_scan_warning_pct": 80,
    "storage_cost_per_tb": 23,
    "ai_credit_rate": 2.20,
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

# Warehouse inventory confirmed from Snowflake UI:
# ALFA uses non-TRXS warehouses; Trexis uses WH_TRXS_* only.
COMPANY_CONFIG = {
    "ALFA": {
        "wh_patterns": [
            "WH_ALFA_%",
            "BI_COMPUTE_WH",
            "COMPUTE_WH",
            "CROWDSTRIKE_WH",
            "DOC_AI_WH",
            "POSIT_WORKBENCH",
            "SNOWFLAKE_LEARNING_WH",
            "SYSTEM$STREAMLIT%",
        ],
        "wh_exclude_patterns": ["WH_TRXS_%"],
        "db_patterns": ["ADMIN", "ALFA%"],
        "exclude_db_pattern": "TRXS_%",
        "user_patterns": [],
        "user_exclude_patterns": ["TRXS_%"],
        "label": "ALFA",
        "color": "#34d399",
    },
    "Trexis": {
        "wh_patterns": ["WH_TRXS_%"],
        "wh_exclude_patterns": [],
        "db_patterns": ["TRXS_%"],
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


SECTION_DEFINITIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition("COMMAND CENTER", "🎯", "DBA Control Room", "sections.dba_control_room"),
    SectionDefinition("COMMAND CENTER", "🏠", "Account Health", "sections.account_health"),
    SectionDefinition("DBA WORKFLOWS", "🧰", "Query Workbench", "sections.query_workbench"),
    SectionDefinition("DBA WORKFLOWS", "🏭", "Warehouse Health", "sections.warehouse_health"),
    SectionDefinition("DBA WORKFLOWS", "💸", "Cost & Contract", "sections.cost_contract"),
    SectionDefinition("DBA WORKFLOWS", "🔒", "Security Posture", "sections.security_posture"),
    SectionDefinition("DBA WORKFLOWS", "🔀", "Change & Drift", "sections.change_drift"),
    SectionDefinition("PLATFORM SIGNALS", "📊", "Usage Overview", "sections.usage_overview"),
    SectionDefinition("PLATFORM SIGNALS", "📈", "Adoption Analytics", "sections.adoption_analytics"),
    SectionDefinition("PLATFORM SIGNALS", "🩺", "Service Health", "sections.service_health"),
    SectionDefinition("PLATFORM SIGNALS", "🗄️", "Storage Monitor", "sections.storage_monitor"),
    SectionDefinition("PLATFORM SIGNALS", "🚚", "Pipeline Health", "sections.pipeline_health"),
    SectionDefinition("PLATFORM SIGNALS", "🕸️", "Platform Topology", "sections.platform_topology"),
    SectionDefinition("PLATFORM SIGNALS", "⚙️", "Task Management", "sections.task_management"),
)

# Mission Control navigation: the original individual modules remain importable
# through aliases/workflow hubs, but the app shell exposes only DBA workflows.
SECTION_DEFINITIONS = (
    SectionDefinition("COMMAND CENTER", "target", "DBA Control Room", "sections.dba_control_room"),
    SectionDefinition("COMMAND CENTER", "home", "Account Health", "sections.account_health"),
    SectionDefinition("OPERATIONS", "work", "Workload Operations", "sections.workload_operations"),
    SectionDefinition("OPERATIONS", "warehouse", "Warehouse Health", "sections.warehouse_health"),
    SectionDefinition("FINANCIAL CONTROL", "cost", "Cost & Contract", "sections.cost_contract"),
    SectionDefinition("GOVERNANCE", "security", "Security Posture", "sections.security_posture"),
    SectionDefinition("GOVERNANCE", "change", "Change & Drift", "sections.change_drift"),
)

NAV_GROUPS: dict[str, list[str]] = {}
for _section in SECTION_DEFINITIONS:
    NAV_GROUPS.setdefault(_section.group, []).append(_section.label)

ALL_SECTIONS = [_section.label for _section in SECTION_DEFINITIONS]
SECTION_MODULES = {_section.label: _section.module for _section in SECTION_DEFINITIONS}
SECTION_BY_TITLE = {_section.title: _section.label for _section in SECTION_DEFINITIONS}
SECTION_BY_TITLE.update({
    "Query Workbench": SECTION_BY_TITLE["Workload Operations"],
    "Live Monitor": SECTION_BY_TITLE["Workload Operations"],
    "Detailed Diagnosis": SECTION_BY_TITLE["Workload Operations"],
    "Query Analysis": SECTION_BY_TITLE["Workload Operations"],
    "Query Search & History": SECTION_BY_TITLE["Workload Operations"],
    "Task Management": SECTION_BY_TITLE["Workload Operations"],
    "Pipeline Health": SECTION_BY_TITLE["Workload Operations"],
    "Stored Proc Tracker": SECTION_BY_TITLE["Workload Operations"],
    "Cost Center": SECTION_BY_TITLE["Cost & Contract"],
    "Credit Contract": SECTION_BY_TITLE["Cost & Contract"],
    "Recommendations & Anomalies": SECTION_BY_TITLE["Cost & Contract"],
    "Snowflake Value": SECTION_BY_TITLE["Cost & Contract"],
    "AI & Cortex Monitor": SECTION_BY_TITLE["Cost & Contract"],
    "SPCS Tracker": SECTION_BY_TITLE["Cost & Contract"],
    "Usage Overview": SECTION_BY_TITLE["DBA Control Room"],
    "Adoption Analytics": SECTION_BY_TITLE["Security Posture"],
    "Service Health": SECTION_BY_TITLE["DBA Control Room"],
    "Storage Monitor": SECTION_BY_TITLE["Cost & Contract"],
    "Platform Topology": SECTION_BY_TITLE["Change & Drift"],
    "Security & Access": SECTION_BY_TITLE["Security Posture"],
    "Data Sharing": SECTION_BY_TITLE["Security Posture"],
    "Who Changed What?": SECTION_BY_TITLE["Change & Drift"],
    "DBA Tools": SECTION_BY_TITLE["Change & Drift"],
})
SECTION_ICONS = {_section.title: _section.icon for _section in SECTION_DEFINITIONS}

SECTION_ALIASES = {
    "DBA Control Room": SECTION_BY_TITLE["DBA Control Room"],
    "Command Center": SECTION_BY_TITLE["DBA Control Room"],
    "Usage Overview": SECTION_BY_TITLE["Usage Overview"],
    "Adoption Analytics": SECTION_BY_TITLE["Adoption Analytics"],
    "Service Health": SECTION_BY_TITLE["Service Health"],
    "Live Monitor": SECTION_BY_TITLE["Query Workbench"],
    "🔴 Live Monitor": SECTION_BY_TITLE["Query Workbench"],
    "Detailed Diagnosis": SECTION_BY_TITLE["Query Workbench"],
    "🧪 Detailed Diagnosis": SECTION_BY_TITLE["Query Workbench"],
    "Query Analysis": SECTION_BY_TITLE["Query Workbench"],
    "🔍 Query Analysis": SECTION_BY_TITLE["Query Workbench"],
    "Query Search & History": SECTION_BY_TITLE["Query Workbench"],
    "🕰️ Query Search & History": SECTION_BY_TITLE["Query Workbench"],
    "Cost Center": SECTION_BY_TITLE["Cost & Contract"],
    "💸 Cost Center": SECTION_BY_TITLE["Cost & Contract"],
    "Credit Contract": SECTION_BY_TITLE["Cost & Contract"],
    "📉 Credit Contract": SECTION_BY_TITLE["Cost & Contract"],
    "Recommendations & Anomalies": SECTION_BY_TITLE["Cost & Contract"],
    "💡 Recommendations & Anomalies": SECTION_BY_TITLE["Cost & Contract"],
    "Snowflake Value": SECTION_BY_TITLE["Cost & Contract"],
    "🏆 Snowflake Value": SECTION_BY_TITLE["Cost & Contract"],
    "AI & Cortex Monitor": SECTION_BY_TITLE["Cost & Contract"],
    "🤖 AI & Cortex Monitor": SECTION_BY_TITLE["Cost & Contract"],
    "SPCS Tracker": SECTION_BY_TITLE["Cost & Contract"],
    "🐳 SPCS Tracker": SECTION_BY_TITLE["Cost & Contract"],
    "Security & Access": SECTION_BY_TITLE["Security Posture"],
    "🔒 Security & Access": SECTION_BY_TITLE["Security Posture"],
    "Data Sharing": SECTION_BY_TITLE["Security Posture"],
    "🌐 Data Sharing": SECTION_BY_TITLE["Security Posture"],
    "Who Changed What?": SECTION_BY_TITLE["Change & Drift"],
    "🔀 Who Changed What?": SECTION_BY_TITLE["Change & Drift"],
    "Stored Proc Tracker": SECTION_BY_TITLE["Change & Drift"],
    "📦 Stored Proc Tracker": SECTION_BY_TITLE["Change & Drift"],
    "DBA Tools": SECTION_BY_TITLE["Change & Drift"],
    "🛠️ DBA Tools": SECTION_BY_TITLE["Change & Drift"],
    "Optimization": SECTION_BY_TITLE["Warehouse Health"],
    "💡 Optimization": SECTION_BY_TITLE["Warehouse Health"],
}

SECTION_ALIASES.update({
    "Query Workbench": SECTION_BY_TITLE["Workload Operations"],
    "Live Monitor": SECTION_BY_TITLE["Workload Operations"],
    "Detailed Diagnosis": SECTION_BY_TITLE["Workload Operations"],
    "Query Analysis": SECTION_BY_TITLE["Workload Operations"],
    "Query Search & History": SECTION_BY_TITLE["Workload Operations"],
    "Task Management": SECTION_BY_TITLE["Workload Operations"],
    "Pipeline Health": SECTION_BY_TITLE["Workload Operations"],
    "Stored Proc Tracker": SECTION_BY_TITLE["Workload Operations"],
    "Usage Overview": SECTION_BY_TITLE["DBA Control Room"],
    "Service Health": SECTION_BY_TITLE["DBA Control Room"],
    "Adoption Analytics": SECTION_BY_TITLE["Security Posture"],
    "Storage Monitor": SECTION_BY_TITLE["Cost & Contract"],
    "Platform Topology": SECTION_BY_TITLE["Change & Drift"],
})


def _sections_by_title(*titles: str) -> list[str]:
    return [SECTION_BY_TITLE[title] for title in titles]


ROLE_SECTIONS = {
    "ANALYST": _sections_by_title(
        "DBA Control Room",
        "Account Health",
        "Usage Overview",
        "Adoption Analytics",
        "Service Health",
        "Query Workbench",
        "Warehouse Health",
        "Cost & Contract",
        "Storage Monitor",
        "Pipeline Health",
        "Platform Topology",
    ),
    "MANAGER": _sections_by_title(
        "DBA Control Room",
        "Account Health",
        "Usage Overview",
        "Adoption Analytics",
        "Service Health",
        "Query Workbench",
        "Warehouse Health",
        "Cost & Contract",
        "Security Posture",
        "Change & Drift",
        "Storage Monitor",
        "Platform Topology",
    ),
    "REPORT": _sections_by_title(
        "DBA Control Room",
        "Account Health",
        "Usage Overview",
        "Adoption Analytics",
        "Service Health",
        "Query Workbench",
        "Warehouse Health",
        "Cost & Contract",
        "Storage Monitor",
        "Pipeline Health",
        "Platform Topology",
    ),
    "DBA": list(ALL_SECTIONS),
    "SYSADMIN": list(ALL_SECTIONS),
    "ACCOUNTADMIN": list(ALL_SECTIONS),
}

# Mission Control keeps all roles on the same simplified shell. Role-based
# limits still apply by reducing access to governance workflows where needed.
ROLE_SECTIONS = {
    "ANALYST": _sections_by_title(
        "DBA Control Room",
        "Account Health",
        "Workload Operations",
        "Warehouse Health",
        "Cost & Contract",
    ),
    "MANAGER": list(ALL_SECTIONS),
    "REPORT": _sections_by_title(
        "DBA Control Room",
        "Account Health",
        "Workload Operations",
        "Warehouse Health",
        "Cost & Contract",
    ),
    "DBA": list(ALL_SECTIONS),
    "SYSADMIN": list(ALL_SECTIONS),
    "ACCOUNTADMIN": list(ALL_SECTIONS),
}

ETL_AUDIT_DB = "DBA_MAINT_DB"
ETL_AUDIT_SCHEMA = "OVERWATCH"
ETL_AUDIT_TABLE = "ETL_RUN_AUDIT"

ALERT_DB = "DBA_MAINT_DB"
ALERT_SCHEMA = "OVERWATCH"
ALERT_TABLE = "OVERWATCH_ALERTS"

ACTION_QUEUE_TABLE = "OVERWATCH_ACTION_QUEUE"
