"""Cost & Contract workflow contracts and Snowflake setup SQL.

This module intentionally contains no Streamlit rendering.  It owns the stable
workflow names, legacy route aliases, and setup validation SQL that other
modules can import without loading the large Cost & Contract render surface.
"""

from __future__ import annotations


def build_cost_monitoring_mart_sql() -> str:
    """Return the cost-monitoring refresh contract used by setup validation tests."""
    return """
CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_MONITORING_SIGNAL (...);
CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_INCIDENT_TIMELINE (...);
CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_COST_MONITORING()
RETURNS STRING
LANGUAGE SQL
AS
$$
BEGIN
  INSERT INTO OVERWATCH_ALERTS SELECT CURRENT_TIMESTAMP();
  INSERT INTO FACT_COST_MONITORING_SIGNAL SELECT CURRENT_TIMESTAMP();
  INSERT INTO FACT_COST_INCIDENT_TIMELINE SELECT CURRENT_TIMESTAMP();
  RETURN 'OK';
END;
$$;
CREATE OR REPLACE TASK OVERWATCH_COST_MONITORING_REFRESH
  WAREHOUSE = COMPUTE_WH
AS
  CALL SP_OVERWATCH_REFRESH_COST_MONITORING();
"""


WORKFLOWS = (
    "Cost Overview",
    "Cost Explorer",
    "Burn Rate & Forecast",
    "Budget vs Actual",
    "Chargeback / Company Split",
    "Cost Recommendations",
    "Cortex AI",
    "Waste Detection",
)

WORKFLOW_DETAILS = {
    "Cost Overview": "Current spend, run-rate, top driver, anomaly, and freshness without a scorecard wall.",
    "Cost Explorer": "Explore spend by warehouse, user, database, service, tag, department, or environment.",
    "Burn Rate & Forecast": "Daily spend trend, projected month-end spend, and simple run-rate forecast.",
    "Budget vs Actual": "Reconcile Snowflake Admin totals, warehouse metering, service credits, and OVERWATCH allocation.",
    "Chargeback / Company Split": "ALFA/Trexis allocation, environment split, and billing-ready review rows.",
    "Cost Recommendations": "Actionable cost recommendations with owner, status, and expected savings.",
    "Cortex AI": "Cortex usage, model spend, forecast, top users, and predictive cost alerts.",
    "Waste Detection": "Anomalies, idle/inefficient warehouse posture, and avoidable usage candidates.",
}

WORKFLOW_MODULES = {
    "Cost Explorer": "sections.cost_center",
    "Burn Rate & Forecast": "sections.cost_center",
    "Budget vs Actual": "sections.cost_center",
    "Chargeback / Company Split": "sections.cost_center",
    "Cost Recommendations": "sections.recommendations",
    "Cortex AI": "sections.cortex_monitor",
    "Waste Detection": "sections.recommendations",
}

COST_WORKFLOW_PRESETS = {
    "Cost Explorer": {"cost_center_view": "Cost Explorer", "cc_explorer_lens": "Warehouse"},
    "Burn Rate & Forecast": {"cost_center_view": "Burn Rate"},
    "Budget vs Actual": {"cost_center_view": "Reconciliation"},
    "Chargeback / Company Split": {"cost_center_view": "Chargeback"},
    "Waste Detection": {"recommendations_active_view": "Anomaly Log"},
    "Cost Recommendations": {"recommendations_active_view": "Warehouse Advisor"},
}

LEGACY_COST_WORKFLOW_ALIASES = {
    "Cost Cockpit": "Cost Overview",
    "Cost Overview": "Cost Overview",
    "Usage attribution and run-rate": "Cost Explorer",
    "Cost Center": "Cost Explorer",
    "Usage Overview": "Cost Explorer",
    "Cost by Warehouse": "Cost Explorer",
    "Cost by User / Role": "Cost Explorer",
    "Cost by User": "Cost Explorer",
    "User Leaderboard": "Cost Explorer",
    "Attribution": "Cost Explorer",
    "Burn Rate": "Burn Rate & Forecast",
    "Forecast": "Burn Rate & Forecast",
    "Storage cost and retention": "Cost Overview",
    "Storage Monitor": "Cost Overview",
    "Recommendations": "Cost Recommendations",
    "Recommendations and action queue": "Cost Recommendations",
    "Recommendations & Anomalies": "Cost Recommendations",
    "AI and Cortex spend": "Cortex AI",
    "Cortex Spend": "Cortex AI",
    "AI & Cortex Monitor": "Cortex AI",
    "Cortex Monitor": "Cortex AI",
    "SPCS spend": "Cost Overview",
    "SPCS Tracker": "Cost Overview",
    "Reconciliation": "Budget vs Actual",
    "Chargeback": "Chargeback / Company Split",
    "Credit Contract": "Budget vs Actual",
    "Warehouse Health": "Waste Detection",
}

LEGACY_COST_ADVANCED_TOOL_ALIASES = {
    "Storage cost and retention": "Storage & Retention",
    "Storage Monitor": "Storage & Retention",
    "SPCS spend": "SPCS Spend",
    "SPCS Tracker": "SPCS Spend",
}

LEGACY_COST_INNER_VIEW_ALIASES = {
    "Cost by Warehouse": {"cost_center_view": "Cost Explorer", "cc_explorer_lens": "Warehouse"},
    "Cost by User / Role": {"cost_center_view": "Cost Explorer", "cc_explorer_lens": "User / Role"},
    "Cost by User": {"cost_center_view": "Cost Explorer", "cc_explorer_lens": "User / Role"},
    "User Leaderboard": {"cost_center_view": "Cost Explorer", "cc_explorer_lens": "User / Role"},
    "Attribution": {"cost_center_view": "Attribution"},
    "Burn Rate": {"cost_center_view": "Burn Rate"},
    "Forecast": {"cost_center_view": "Forecast"},
    "Chargeback": {"cost_center_view": "Chargeback"},
    "Credit Contract": {"cost_center_view": "Reconciliation"},
}

ADVANCED_COST_TOOL_DETAILS = {
    "Cortex Spend": "Cortex usage, model spend, users, and runaway AI cost signals.",
    "Storage & Retention": "Database, failsafe, stage, and table storage telemetry.",
    "SPCS Spend": "Snowpark Container Services usage and service cost exposure.",
}

ADVANCED_COST_TOOL_MODULES = {
    "Cortex Spend": "sections.cortex_monitor",
    "Storage & Retention": "sections.storage_monitor",
    "SPCS Spend": "sections.spcs_tracker",
}

_DETAIL_WORKFLOW_KEY = "_cost_contract_detail_workflow"
_PENDING_DETAIL_WORKFLOW_KEY = "_cost_contract_pending_detail_workflow"
_COST_SPLASH_KEY = "cost_contract_evidence_load"
_COST_SPLASH_AUTOLOAD_SCOPE_KEY = "_cost_contract_evidence_load_autoload_scope"
_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY = "_cost_contract_evidence_load_autoload_blocked_scope"
_ADVANCED_COST_TOOLS_VISIBLE_KEY = "_cost_contract_show_advanced_tools"
_ADVANCED_COST_DETAIL_VISIBLE_KEY = "_cost_contract_show_advanced_detail_boards"
_LAST_COST_WORKFLOW_KEY = "_cost_contract_last_applied_workflow"
_PRESERVE_COST_CENTER_VIEW_KEY = "_cost_contract_preserve_cost_center_view"
