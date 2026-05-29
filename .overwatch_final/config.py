# ─────────────────────────────────────────────────────────────────────────────
# config.py — OVERWATCH V3 · ALFA Insurance
# Central configuration: thresholds, company filter, defaults, credit rates
# NEW: ROLE_SECTIONS — controls which nav items are visible per Snowflake role
# ─────────────────────────────────────────────────────────────────────────────

# ── Credit / cost defaults ────────────────────────────────────────────────────
DEFAULTS = {
    "credit_price": 3.00,
    "ai_credit_price": 2.20,
    "storage_cost_per_tb": 23.00,
    "rt_interval_sec": 30,
}

# ── Alert / anomaly thresholds ────────────────────────────────────────────────
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

# ── Warehouse credit rates (credits/hour) ─────────────────────────────────────
CREDIT_RATES = {
    "X-Small": 1,    "Small": 2,    "Medium": 4,    "Large": 8,
    "X-Large": 16,   "2X-Large": 32, "3X-Large": 64, "4X-Large": 128,
    "5X-Large": 256, "6X-Large": 512,
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

# ── Default company ───────────────────────────────────────────────────────────
DEFAULT_COMPANY = "ALFA"

# ── Multi-tenant company filter ───────────────────────────────────────────────
# Warehouse inventory (confirmed from Snowflake UI 2025-05-20):
#   ALFA:   WH_ALFA_*, BI_COMPUTE_WH, COMPUTE_WH, CROWDSTRIKE_WH,
#           DOC_AI_WH, POSIT_WORKBENCH, SNOWFLAKE_LEARNING_WH, SYSTEM$STREAMLIT*
#   Trexis: WH_TRXS_* only
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
        "db_patterns":         ["ADMIN", "ALFA%"],
        "exclude_db_pattern":  "TRXS_%",
        "user_patterns":       [],
        "user_exclude_patterns": ["TRXS_%"],
        "label": "ALFA",
        "color": "#34d399",
    },
    "Trexis": {
        "wh_patterns":         ["WH_TRXS_%"],
        "wh_exclude_patterns": [],
        "db_patterns":         ["TRXS_%"],
        "exclude_db_pattern":  "",
        "user_patterns":       ["TRXS_%"],
        "user_exclude_patterns": [],
        "label": "Trexis",
        "color": "#c084fc",
    },
    "ALL": {
        "wh_patterns":         [],
        "wh_exclude_patterns": [],
        "db_patterns":         [],
        "exclude_db_pattern":  "",
        "user_patterns":       [],
        "user_exclude_patterns": [],
        "label": "ALL",
        "color": "#38bdf8",
    },
}

# ── Navigation sections (ordered) ─────────────────────────────────────────────
NAV_GROUPS = {
    "MONITORING": [
        "🏠 Account Health",
        "📊 Usage Overview",
        "📈 Adoption Analytics",
        "🩺 Service Health",
        "🔴 Live Monitor",
        "🧪 Detailed Diagnosis",
        "🔍 Query Analysis",
        "🕰️ Query Search & History",
        "🏭 Warehouse Health",
    ],
    "INFRASTRUCTURE": [
        "🗄️ Storage Monitor",
        "🚚 Pipeline Health",
        "🕸️ Platform Topology",
        "🐳 SPCS Tracker",
        "⚙️ Task Management",
    ],
    "COST & PERFORMANCE": [
        "💸 Cost Center",
        "💡 Recommendations & Anomalies",
        "🏆 Snowflake Value",
        "🤖 AI & Cortex Monitor",
    ],
    "SECURITY & OPS": [
        "🔒 Security & Access",
        "🔀 Who Changed What?",
        "📦 Stored Proc Tracker",
        "🌐 Data Sharing",
        "🛠️ DBA Tools",
    ],
}

# Flat list for st.radio (app.py uses this)
ALL_SECTIONS = [s for group in NAV_GROUPS.values() for s in group]

SECTION_MODULE_PATHS = [
    "sections.account_health",
    "sections.usage_overview",
    "sections.adoption_analytics",
    "sections.service_health",
    "sections.live_monitor",
    "sections.detailed_diagnosis",
    "sections.query_analysis",
    "sections.query_search",
    "sections.warehouse_health",
    "sections.storage_monitor",
    "sections.pipeline_health",
    "sections.platform_topology",
    "sections.spcs_tracker",
    "sections.task_management",
    "sections.cost_center",
    "sections.recommendations",
    "sections.snowflake_value",
    "sections.cortex_monitor",
    "sections.security_access",
    "sections.object_change_monitor",
    "sections.stored_proc_tracker",
    "sections.data_sharing",
    "sections.dba_tools",
]

if len(SECTION_MODULE_PATHS) != len(ALL_SECTIONS):
    raise RuntimeError("SECTION_MODULE_PATHS must stay aligned with NAV_GROUPS.")

SECTION_MODULES = dict(zip(ALL_SECTIONS, SECTION_MODULE_PATHS))
SECTION_BY_TITLE = {section.split(" ", 1)[1]: section for section in ALL_SECTIONS}
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

# ── Role-based section visibility ─────────────────────────────────────────────
# Keys are substrings matched case-insensitively against CURRENT_ROLE().
# First match wins. Falls back to DBA (all sections) if no role matches.
#
# How to map your Snowflake roles:
#   - ANALYST users: analysts, report, bi, self-service roles
#   - MANAGER users: leadership, executive, director roles
#   - DBA (default): sysadmin, accountadmin, dba roles → full access
#
# Add new roles here without touching app.py or any section file.
ROLE_SECTIONS = {
    # Business analysts — cost visibility + query search, no admin/DBA tools
    "ANALYST": [
        "🏠 Account Health",
        "📊 Usage Overview",
        "📈 Adoption Analytics",
        "🩺 Service Health",
        "🧪 Detailed Diagnosis",
        "🔍 Query Analysis",
        "🕰️ Query Search & History",
        "💸 Cost Center",
        "🗄️ Storage Monitor",
        "🚚 Pipeline Health",
        "🕸️ Platform Topology",
        "🤖 AI & Cortex Monitor",
    ],
    # Managers / leadership — executive summary, cost, recommendations, Snowflake value
    "MANAGER": [
        "🏠 Account Health",
        "📊 Usage Overview",
        "📈 Adoption Analytics",
        "🩺 Service Health",
        "🧪 Detailed Diagnosis",
        "💸 Cost Center",
        "💡 Recommendations & Anomalies",
        "🏆 Snowflake Value",
        "🗄️ Storage Monitor",
        "🤖 AI & Cortex Monitor",
        "🕸️ Platform Topology",
    ],
    # Report / BI roles — same as analyst
    "REPORT": [
        "🏠 Account Health",
        "📊 Usage Overview",
        "📈 Adoption Analytics",
        "🩺 Service Health",
        "🧪 Detailed Diagnosis",
        "🔍 Query Analysis",
        "🕰️ Query Search & History",
        "💸 Cost Center",
        "🗄️ Storage Monitor",
        "🚚 Pipeline Health",
        "🕸️ Platform Topology",
    ],
    # DBA / admin / sysadmin — full access (default fallback also gives full access)
    "DBA":         list(ALL_SECTIONS),
    "SYSADMIN":    list(ALL_SECTIONS),
    "ACCOUNTADMIN":list(ALL_SECTIONS),
}

# ── ETL Audit table target ────────────────────────────────────────────────────
ETL_AUDIT_DB     = "DBA_MAINT_DB"
ETL_AUDIT_SCHEMA = "OVERWATCH"
ETL_AUDIT_TABLE  = "ETL_RUN_AUDIT"

# ── Alert task target ─────────────────────────────────────────────────────────
ALERT_DB     = "DBA_MAINT_DB"
ALERT_SCHEMA = "OVERWATCH"
ALERT_TABLE  = "OVERWATCH_ALERTS"

# Persistent action queue for recommendations, alerts, and operator follow-up.
ACTION_QUEUE_TABLE = "OVERWATCH_ACTION_QUEUE"
