# sections/security_posture_access_changes_view.py - Security-sensitive change detail renderer
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util


pd = lazy_pandas()

load_change_event_detail = _lazy_util("load_change_event_detail")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_security_change_detail(company: str, environment: str) -> None:
    """Expose security-sensitive change events only after an operator asks for them."""
    st.markdown("**Security-Sensitive Changes**")
    st.caption("Loads role, grant, network policy, integration, and security-sensitive change evidence from the change mart.")
    if st.button("Load Security-Sensitive Changes", key="security_load_change_intelligence", width="stretch"):
        st.session_state["security_change_intelligence_detail"] = load_change_event_detail(
            company,
            environment,
            change_types=(
                "ROLE_CHANGE",
                "GRANT_CHANGE",
                "NETWORK_POLICY_CHANGE",
                "INTEGRATION_CHANGE",
                "SECURITY_SENSITIVE_CHANGE",
            ),
            days=180,
        )
        st.session_state["security_change_intelligence_scope"] = (company, environment)

    detail = st.session_state.get("security_change_intelligence_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("security_change_intelligence_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No security-sensitive change rows are available for this scope yet.")
            return
        render_priority_dataframe(
            detail,
            title="Security-sensitive change events",
            priority_columns=[
                "CHANGE_TS", "CHANGE_TYPE", "OBJECT_TYPE", "OBJECT_NAME",
                "CHANGED_BY", "RISK_LEVEL", "BUSINESS_IMPACT", "OWNER_ROUTE",
                "OWNER_GAP", "RELATED_ALERT_COUNT", "CONFIDENCE", "LAST_REFRESHED_TS",
            ],
            sort_by=["CHANGE_TS"],
            ascending=False,
            raw_label="All security-sensitive change rows",
            height=300,
            max_rows=12,
        )


__all__ = ["_render_security_change_detail"]
