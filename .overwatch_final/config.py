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
        return f"{self.icon} {self.title}"


SECTION_DEFINITIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition("MONITORING", "🏠", "Account Health", "sections.account_health"),
    SectionDefinition("MONITORING", "📊", "Usage Overview", "sections.usage_overview"),
    SectionDefinition("MONITORING", "📈", "Adoption Analytics", "sections.adoption_analytics"),
    SectionDefinition("MONITORING", "🩺", "Service Health", "sections.service_health"),
    SectionDefinition("MONITORING", "🔴", "Live Monitor", "sections.live_monitor"),
    SectionDefinition("MONITORING", "🧪", "Detailed Diagnosis", "sections.detailed_diagnosis"),
    SectionDefinition("MONITORING", "🔍", "Query Analysis", "sections.query_analysis"),
    SectionDefinition("MONITORING", "🕰️", "Query Search & History", "sections.query_search"),
    SectionDefinition("MONITORING", "🏭", "Warehouse Health", "sections.warehouse_health"),
    SectionDefinition("INFRASTRUCTURE", "🗄️", "Storage Monitor", "sections.storage_monitor"),
    SectionDefinition("INFRASTRUCTURE", "🚚", "Pipeline Health", "sections.pipeline_health"),
    SectionDefinition("INFRASTRUCTURE", "🕸️", "Platform Topology", "sections.platform_topology"),
    SectionDefinition("INFRASTRUCTURE", "🐳", "SPCS Tracker", "sections.spcs_tracker"),
    SectionDefinition("INFRASTRUCTURE", "⚙️", "Task Management", "sections.task_management"),
    SectionDefinition("COST & PERFORMANCE", "💸", "Cost Center", "sections.cost_center"),
    SectionDefinition("COST & PERFORMANCE", "💡", "Recommendations & Anomalies", "sections.recommendations"),
    SectionDefinition("COST & PERFORMANCE", "🏆", "Snowflake Value", "sections.snowflake_value"),
    SectionDefinition("COST & PERFORMANCE", "🤖", "AI & Cortex Monitor", "sections.cortex_monitor"),
    SectionDefinition("SECURITY & OPS", "🔒", "Security & Access", "sections.security_access"),
    SectionDefinition("SECURITY & OPS", "🔀", "Who Changed What?", "sections.object_change_monitor"),
    SectionDefinition("SECURITY & OPS", "📦", "Stored Proc Tracker", "sections.stored_proc_tracker"),
    SectionDefinition("SECURITY & OPS", "🌐", "Data Sharing", "sections.data_sharing"),
    SectionDefinition("SECURITY & OPS", "🛠️", "DBA Tools", "sections.dba_tools"),
)

NAV_GROUPS: dict[str, list[str]] = {}
for _section in SECTION_DEFINITIONS:
    NAV_GROUPS.setdefault(_section.group, []).append(_section.label)

ALL_SECTIONS = [_section.label for _section in SECTION_DEFINITIONS]
SECTION_MODULES = {_section.label: _section.module for _section in SECTION_DEFINITIONS}
SECTION_BY_TITLE = {_section.title: _section.label for _section in SECTION_DEFINITIONS}
SECTION_ICONS = {_section.title: _section.icon for _section in SECTION_DEFINITIONS}

SECTION_ALIASES = {
    "Usage Overview": SECTION_BY_TITLE["Usage Overview"],
    "Adoption Analytics": SECTION_BY_TITLE["Adoption Analytics"],
    "Service Health": SECTION_BY_TITLE["Service Health"],
    "Detailed Diagnosis": SECTION_BY_TITLE["Detailed Diagnosis"],
    "Pipeline Health": SECTION_BY_TITLE["Pipeline Health"],
    "Platform Topology": SECTION_BY_TITLE["Platform Topology"],
    "Credit Contract": SECTION_BY_TITLE["Cost Center"],
    "📉 Credit Contract": SECTION_BY_TITLE["Cost Center"],
    "Snowflake Value": SECTION_BY_TITLE["Snowflake Value"],
    "Optimization": SECTION_BY_TITLE["Warehouse Health"],
    "💡 Optimization": SECTION_BY_TITLE["Warehouse Health"],
}


def _sections_by_title(*titles: str) -> list[str]:
    return [SECTION_BY_TITLE[title] for title in titles]


ROLE_SECTIONS = {
    "ANALYST": _sections_by_title(
        "Account Health",
        "Usage Overview",
        "Adoption Analytics",
        "Service Health",
        "Detailed Diagnosis",
        "Query Analysis",
        "Query Search & History",
        "Cost Center",
        "Storage Monitor",
        "Pipeline Health",
        "Platform Topology",
        "AI & Cortex Monitor",
    ),
    "MANAGER": _sections_by_title(
        "Account Health",
        "Usage Overview",
        "Adoption Analytics",
        "Service Health",
        "Detailed Diagnosis",
        "Cost Center",
        "Recommendations & Anomalies",
        "Snowflake Value",
        "Storage Monitor",
        "AI & Cortex Monitor",
        "Platform Topology",
    ),
    "REPORT": _sections_by_title(
        "Account Health",
        "Usage Overview",
        "Adoption Analytics",
        "Service Health",
        "Detailed Diagnosis",
        "Query Analysis",
        "Query Search & History",
        "Cost Center",
        "Storage Monitor",
        "Pipeline Health",
        "Platform Topology",
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
