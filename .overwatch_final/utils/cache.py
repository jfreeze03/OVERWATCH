# utils/cache.py - lightweight app cache invalidation helpers
import streamlit as st

from .state_keys import PRESERVE_STATE_EXACT, PRESERVE_STATE_PREFIXES


_METADATA_CACHE_PREFIXES = (
    "_overwatch_available_columns",
    "_overwatch_unavailable_column_views",
    "_overwatch_column_probe",
    "_overwatch_qh_detail_exprs",
    "_overwatch_show_statement_cache",
    "_task_management_execution_context_cache",
)


def clear_all_cache(
    *,
    clear_streamlit_cache: bool = True,
    clear_metadata: bool = True,
):
    """
    Clear all OVERWATCH cached data from session state.
    Preserves settings, navigation, company scope, and operator modes while
    resetting the session TTL clock.

    Routine filter/metric changes should pass clear_streamlit_cache=False so
    scoped st.cache_data entries can be reused when their query context still
    matches. The top-level Refresh button keeps the default hard purge.
    """
    transient_prefixes = (
        "_data_", "_ts_", "df_", "_refresh_salt_", "_sec_",
        "_overwatch_query_", "alert_center_", "cortex_", "cost_contract_", "cc_", "ah_", "cm_", "ds_", "dba_",
        "lm_", "mc_", "ocm_", "opt_", "qa_", "qs_", "rec_", "sec_", "spcs_",
        "stor_", "spt_", "sp_ops_", "sp_sla_", "tm_", "task_ops_", "task_sla_",
        "pipe_", "qw_", "sf_value_",
        "wh_", "uo_", "aa_", "dd_", "svc_",
        "arch_",
        "contract_", "topology_", "recommendations", "anomalies",
        "health_data", "morning_data", "tg_list", "tg_hist", "cm_base_",
        "change_drift_summary", "change_drift_exceptions", "change_drift_meta",
        "change_drift_proof_sql", "security_posture_summary",
        "security_posture_exceptions", "security_posture_meta",
        "security_posture_proof_sql",
    )
    if clear_metadata:
        transient_prefixes = transient_prefixes + _METADATA_CACHE_PREFIXES
    keys_to_remove = [
        k for k in list(st.session_state.keys())
        if k not in PRESERVE_STATE_EXACT
        and not any(k.startswith(p) for p in PRESERVE_STATE_PREFIXES)
        and any(k.startswith(p) for p in transient_prefixes)
    ]
    for k in keys_to_remove:
        del st.session_state[k]

    # Reset the TTL timestamp; get_session() will stamp an existing session
    # without paying for an immediate SELECT 1 check.
    st.session_state.pop("_sf_session_created_at", None)

    if clear_streamlit_cache:
        try:
            st.cache_data.clear()
        except Exception:
            pass
