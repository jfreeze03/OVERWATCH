# utils/state_keys.py - shared Streamlit session-state preservation rules
"""Shared session-state keys that survive cache invalidation.

Company switches and global refreshes both need to clear loaded data while
preserving operator context. Keeping the rules here prevents the two code paths
from drifting apart as the app grows.
"""

PRESERVE_STATE_EXACT = {
    "active_company",
    "active_theme",
    "nav_section",
    "_prev_active_company",
    "_prev_global_filter_signature",
    "_prev_metric_settings_signature",
    "_prev_nav_section",
    "credit_price",
    "_credit_price",
    "storage_cost",
    "rt_interval",
    "exceptions_only_mode",
    "triage_view_mode",
}

PRESERVE_STATE_PREFIXES = (
    "nav_",
    "_prev_nav_",
    "global_",
    "company_",
    "exceptions_only",
    "triage_",
)
