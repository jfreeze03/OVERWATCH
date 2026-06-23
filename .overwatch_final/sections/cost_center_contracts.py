"""Cost Center workflow contracts and stable labels."""
from __future__ import annotations


COST_CENTER_VIEWS = (
    "Cost Explorer",
    "Explain This Bill",
    "User Leaderboard",
    "Burn Rate",
    "Reconciliation",
    "Forecast",
    "Attribution",
    "Chargeback",
)

COST_CENTER_VIEW_DETAILS = {
    "Cost Explorer": "Pivot one loaded attribution set by company, department, warehouse, database, role, and user.",
    "Explain This Bill": "Narrative answer for why spend changed.",
    "User Leaderboard": "Cost by User / Role: top users, roles, and warehouses by allocated credits.",
    "Burn Rate": "Burn Rate & Forecast: daily metered credit trend by warehouse.",
    "Reconciliation": "Metered credits vs query allocation.",
    "Forecast": "Run-rate projection detail from recent usage.",
    "Attribution": "Role, schema, client, and lineage cost views.",
    "Chargeback": "Chargeback / Company Split: ALFA/Trexis company allocation output.",
}

COST_CENTER_VIEW_LABELS = {
    "User Leaderboard": "Cost by User / Role",
    "Burn Rate": "Burn Rate & Forecast",
    "Forecast": "Run-Rate Projection",
    "Chargeback": "Chargeback / Company Split",
}

NO_DATABASE_CONTEXT_VALUES = {
    "",
    "NONE",
    "NULL",
    "NAN",
    "NO_DATABASE_CONTEXT",
    "NO DATABASE CONTEXT",
}

COST_EXPLORER_LENSES = (
    "Company",
    "Department / Cost Center",
    "Warehouse",
    "Database",
    "Role",
    "User",
    "Environment",
    "Company x Warehouse",
    "Database x Role",
    "Department x Warehouse",
)

COST_EXPLORER_LENS_COLUMNS = {
    "Company": ["COMPANY"],
    "Department / Cost Center": ["DEPARTMENT"],
    "Warehouse": ["WAREHOUSE_NAME"],
    "Database": ["DATABASE_NAME"],
    "Role": ["ROLE_NAME"],
    "User": ["USER_NAME"],
    "Environment": ["ENVIRONMENT_ROLLUP"],
    "Company x Warehouse": ["COMPANY", "WAREHOUSE_NAME"],
    "Database x Role": ["DATABASE_NAME", "ROLE_NAME"],
    "Department x Warehouse": ["DEPARTMENT", "WAREHOUSE_NAME"],
}


__all__ = [
    "COST_CENTER_VIEWS",
    "COST_CENTER_VIEW_DETAILS",
    "COST_CENTER_VIEW_LABELS",
    "NO_DATABASE_CONTEXT_VALUES",
    "COST_EXPLORER_LENSES",
    "COST_EXPLORER_LENS_COLUMNS",
]
