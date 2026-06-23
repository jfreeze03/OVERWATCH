"""Account Health access-hygiene renderer."""
from __future__ import annotations

import streamlit as st

from sections.account_health_access_hygiene import _annotate_account_health_access_hygiene
from sections.account_health_action_queue import _queue_account_health_access_hygiene
from sections.account_health_common import _account_health_action_session
from sections.account_health_models import _account_health_meta_matches, _account_health_scope_meta
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import render_shell_snapshot


pd = lazy_pandas()

day_window_selectbox = _lazy_util("day_window_selectbox")
format_snowflake_error = _lazy_util("format_snowflake_error")
load_shared_access_hygiene_snapshot = _lazy_util("load_shared_access_hygiene_snapshot")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_account_health_access_hygiene(company: str, environment: str) -> None:
    with st.expander("Account Access Hygiene", expanded=False):
        st.caption(
            "Account-level user/auth posture is intentionally not database-filtered. "
            "Rows are labeled No Database Context so PROD/DEV selections do not imply false precision."
        )
        days = day_window_selectbox(
            "Access hygiene lookback",
            key="account_health_access_hygiene_days",
            default=30,
        )
        if st.button("Load Access Hygiene", key="account_health_access_hygiene_load"):
            action_session = _account_health_action_session("load Account Access Hygiene")
            if action_session is None:
                return
            try:
                hygiene_result = load_shared_access_hygiene_snapshot(
                    action_session,
                    days,
                    company,
                    environment=environment,
                    force=True,
                    section="Account Health",
                )
                raw = hygiene_result.data
                st.session_state["account_health_access_hygiene_source"] = hygiene_result.source
                st.session_state["account_health_access_hygiene"] = _annotate_account_health_access_hygiene(raw)
                st.session_state["account_health_access_hygiene_meta"] = _account_health_scope_meta(
                    company,
                    environment,
                    window=f"{int(days)}d",
                    ignore_environment=True,
                    filter_keys=("global_user",),
                )
            except Exception as exc:
                st.session_state["account_health_access_hygiene"] = pd.DataFrame()
                st.warning(f"Account access hygiene unavailable: {format_snowflake_error(exc)}")

        hygiene = st.session_state.get("account_health_access_hygiene")
        if (
            hygiene is not None
            and not _account_health_meta_matches(
                st.session_state.get("account_health_access_hygiene_meta"),
                _account_health_scope_meta(
                    company,
                    environment,
                    window=f"{int(days)}d",
                    ignore_environment=True,
                    filter_keys=("global_user",),
                ),
            )
        ):
            st.info("Loaded access hygiene is stale for the active scope. Reload before queuing access work.")
            with st.expander("Access Hygiene Status", expanded=False):
                render_shell_snapshot((
                    ("Scope", "Stale"),
                    ("Refresh", "Required"),
                    ("Queue reviews", "After refresh"),
                    ("Execution", "Runbook only"),
                ))
        elif hygiene is not None and not hygiene.empty:
            high = int((hygiene.get("SEVERITY", pd.Series(dtype=str)).astype(str).str.upper() == "HIGH").sum())
            failed = int((pd.to_numeric(hygiene.get("FAILED_LOGINS", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
            admins = int((pd.to_numeric(hygiene.get("ADMIN_ROLE_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
            render_shell_snapshot((
                ("Users Review", f"{len(hygiene):,}"),
                ("High Risk", f"{high:,}"),
                ("Failed Logins", f"{failed:,}"),
                ("Admin Reviews", f"{admins:,}"),
            ))
            render_priority_dataframe(
                hygiene,
                title="Account-level user/auth hygiene candidates",
                priority_columns=[
                    "SEVERITY", "USER_NAME", "POSTURE_FINDINGS", "FAILED_LOGINS",
                    "FAILED_IPS", "ADMIN_ROLE_COUNT", "ADMIN_ROLES", "MFA_SIGNAL",
                    "DAYS_SINCE_SEEN", "DATABASE_CONTEXT", "ENVIRONMENT_SCOPE",
                    "SCOPE_CONFIDENCE", "OWNER", "APPROVAL_GROUP", "QUEUE_READINESS",
                    "QUEUE_BLOCKERS", "NEXT_ACTION", "PROOF_REQUIRED",
                ],
                sort_by=["ACCESS_RISK_RANK", "FAILED_LOGINS", "ADMIN_ROLE_COUNT", "DAYS_SINCE_SEEN"],
                ascending=[True, False, False, False],
                raw_label="All account access hygiene rows",
                height=320,
            )
            actionable = hygiene[
                hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper().isin(
                    {"CRITICAL", "HIGH", "MEDIUM"}
                )
            ]
            b1, b2 = st.columns([1, 3])
            with b1:
                if st.button(
                    "Queue Access Hygiene Reviews",
                    key="account_health_queue_access_hygiene",
                    width="stretch",
                    disabled=actionable.empty,
                ):
                    action_session = _account_health_action_session("queue Account Access Hygiene reviews")
                    if action_session is not None:
                        _queue_account_health_access_hygiene(
                            action_session,
                            hygiene,
                            company=company,
                            days=days,
                        )
            with b2:
                route_ready = int((hygiene.get("QUEUE_READINESS", pd.Series(dtype=str)) == "Ready to Queue").sum())
                st.caption(
                    f"{len(actionable):,} medium-or-higher user/auth review(s) can be saved with read-only telemetry "
                    f"and No Database Context scope. {route_ready:,} loaded row(s) are route-ready."
                )
            with st.expander("Access Hygiene Status", expanded=False):
                render_shell_snapshot((
                    ("Telemetry", "Read-only"),
                    ("Status", "Required"),
                    ("Queue action", "Available"),
                    ("Execution", "Runbook only"),
                ))
        elif hygiene is not None:
            st.success("No account-level access hygiene candidates found for the selected lookback.")


__all__ = [
    '_render_account_health_access_hygiene',
]
