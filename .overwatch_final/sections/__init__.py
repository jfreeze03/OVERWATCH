# sections/__init__.py — Lazy section loader + dispatch
# ─────────────────────────────────────────────────────────────────────────────
# FIX 1: Lazy loading via importlib (Kiro Immediate Win #1) — sections are
#         imported on first access rather than all at startup, cutting cold
#         start time significantly on SPCS.
# FIX 2: "🔀 Who Changed What?" emoji now matches config.py NAV_GROUPS key.
# ─────────────────────────────────────────────────────────────────────────────
import importlib
import streamlit as st

# Maps nav label → dotted module path.
# Modules are NOT imported here — importlib loads them on first dispatch call.
_MODULE_MAP: dict[str, str] = {
    "🏠 Account Health":              "sections.account_health",
    "🔴 Live Monitor":                "sections.live_monitor",
    "🔍 Query Analysis":              "sections.query_analysis",
    "🕰️ Query Search & History":     "sections.query_search",
    "🏭 Warehouse Health":            "sections.warehouse_health",
    "💸 Cost Center":                 "sections.cost_center",
    "💡 Optimization":                "sections.optimization",
    "🗄️ Storage Monitor":            "sections.storage_monitor",
    "🐳 SPCS Tracker":                "sections.spcs_tracker",
    "🔒 Security & Access":           "sections.security_access",
    "🔀 Who Changed What?":           "sections.object_change_monitor",  # FIX: emoji added
    "📦 Stored Proc Tracker":         "sections.stored_proc_tracker",
    "🌐 Data Sharing":                "sections.data_sharing",
    "⚙️ Task Management":             "sections.task_management",
    "💡 Recommendations & Anomalies": "sections.recommendations",
    "🛠️ DBA Tools":                   "sections.dba_tools",
    "🔄 Migration Confidence":        "sections.migration_confidence",
    "🤖 AI & Cortex Monitor":         "sections.cortex_monitor",
}

# Module cache — populated on first access, avoids repeated importlib calls
_loaded: dict[str, object] = {}


def dispatch(active_section: str) -> None:
    """Lazy-load and render the section for the active nav selection.

    On first call for a section: importlib.import_module() loads it.
    On subsequent calls: the cached module object is reused — no re-import.
    If the section key is not in _MODULE_MAP, a clear warning is shown.
    """
    module_path = _MODULE_MAP.get(active_section)

    if not module_path:
        st.warning(
            f"⚠️ Section `{active_section}` not found in registry. "
            "Check that the nav label in config.py NAV_GROUPS matches _MODULE_MAP exactly."
        )
        return

    if module_path not in _loaded:
        try:
            _loaded[module_path] = importlib.import_module(module_path)
        except ImportError as e:
            st.error(f"Failed to load section `{active_section}`: {e}")
            return

    _loaded[module_path].render()
