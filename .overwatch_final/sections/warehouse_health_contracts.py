# sections/warehouse_health_contracts.py - Warehouse Health labels and contracts.
from __future__ import annotations


WAREHOUSE_HEALTH_VIEWS = (
    "Overview & Scaling",
    "Efficiency",
    "Spill & Memory",
    "Workload Heatmap",
    "Optimization Advisor",
)
WAREHOUSE_HEALTH_FAST_ENTRY_VERSION = "2026-06-06-support-panels-explicit-v1"
WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION = 2

WAREHOUSE_HEALTH_DETAILS = {
    "Overview & Scaling": "Warehouse volume, latency, spill, cache, and metering events.",
    "Efficiency": "Credits per query, queue per credit, spill per credit, and risk board.",
    "Spill & Memory": "Local and remote spill drilldowns by warehouse.",
    "Workload Heatmap": "Concurrency by warehouse, day, and hour.",
    "Optimization Advisor": "Actionable sizing, suspend, spill, and reliability recommendations.",
}

WAREHOUSE_HEALTH_BRIEF_WORKFLOWS = (
    {
        "VIEW": "Overview & Scaling",
        "BUTTON_LABEL": "Open Overview",
        "DBA_MOVE": "Start with warehouse pressure, metering movement, and guardrail coverage.",
        "WHEN": "Morning capacity review or before size/suspend changes.",
    },
    {
        "VIEW": "Efficiency",
        "BUTTON_LABEL": "Open Efficiency",
        "DBA_MOVE": "Rank warehouses by credits per query, queue per credit, and spill per credit.",
        "WHEN": "Cost spike, noisy warehouse, or low-value workload review.",
    },
    {
        "VIEW": "Spill & Memory",
        "BUTTON_LABEL": "Open Spill",
        "DBA_MOVE": "Review local and remote spill before upsizing or changing query shape.",
        "WHEN": "Slow queries, memory pressure, or repeated remote spill.",
    },
    {
        "VIEW": "Workload Heatmap",
        "BUTTON_LABEL": "Open Heatmap",
        "DBA_MOVE": "Find peak hours and concurrency pressure by warehouse.",
        "WHEN": "Scheduling, Snowflake task windows, or workload routing questions.",
    },
    {
        "VIEW": "Optimization Advisor",
        "BUTTON_LABEL": "Open Advisor",
        "DBA_MOVE": "Move from telemetry to recommended warehouse actions.",
        "WHEN": "After pressure telemetry is loaded or a DBA change is being planned.",
    },
)

WAREHOUSE_SETTING_REVIEW_TABLE = "OVERWATCH_WAREHOUSE_SETTING_REVIEW"
WAREHOUSE_OPERABILITY_FACT_TABLE = "FACT_WAREHOUSE_OPERABILITY_DAILY"
WAREHOUSE_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)
