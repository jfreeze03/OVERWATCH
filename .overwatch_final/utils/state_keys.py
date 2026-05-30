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
    "_prev_nav_section",
    "credit_price",
    "_credit_price",
    "storage_cost",
    "rt_interval",
    "theme_picker_radio",
    "exceptions_only_mode",
}

PRESERVE_STATE_PREFIXES = (
    "nav_",
    "_prev_nav_",
    "global_",
    "theme_",
    "company_",
    "exceptions_only",
)
