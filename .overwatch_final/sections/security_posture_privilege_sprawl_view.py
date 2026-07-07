# sections/security_posture_privilege_sprawl_view.py - Privilege Sprawl renderer
from __future__ import annotations

import streamlit as st

from utils.performance import EVIDENCE_CLICK_QUERY_BUDGET, query_budget_context
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.security_posture_access_review import _security_exception_environment, _security_owner_context
from sections.security_posture_action_queue import _queue_privileged_grant_actions
from sections.security_posture_admin_view import _render_advanced_security_evidence
from sections.security_posture_models import _security_meta_matches, _security_scope_meta
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot


pd = lazy_pandas()

build_shared_security_privileged_grant_review_sql = _lazy_util("build_shared_security_privileged_grant_review_sql")
day_window_selectbox = _lazy_util("day_window_selectbox")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_session = _lazy_util("get_session")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
run_query = _lazy_util("run_query")

def _security_privileged_grant_review_sql(days: int, company: str, environment: str = "ALL") -> str:
    return build_shared_security_privileged_grant_review_sql(days, company, environment)

def _annotate_security_privileged_grant_readiness(grants: pd.DataFrame) -> pd.DataFrame:
    """Add route and review status fields to privileged grant rows."""
    if grants is None or grants.empty:
        return pd.DataFrame() if grants is None else grants
    view = grants.copy()
    view.columns = [str(col).upper() for col in view.columns]
    rows = []
    for _, row in view.iterrows():
        context = _security_owner_context({
            "FINDING_TYPE": row.get("FINDING_TYPE", "Privileged Grant"),
            "ENTITY": row.get("ENTITY", ""),
            "DATABASE_NAME": row.get("DATABASE_NAME", ""),
        })
        route_ready = bool(context.get("route_email") or context.get("review_primary") or context.get("escalation"))
        database_context = bool(row.get("DATABASE_CONTEXT"))
        role_name = str(row.get("ROLE_NAME") or "").strip().upper()
        object_name = str(row.get("OBJECT_NAME") or "").strip()
        severity = str(row.get("SEVERITY") or "").strip().upper()
        if role_name in {"ACCOUNTADMIN", "ORGADMIN", "SECURITYADMIN"}:
            review_state = "Tier 0 role grant"
        elif role_name:
            review_state = "Privileged role grant"
        elif object_name:
            review_state = "Privileged object grant"
        else:
            review_state = "Grant review"
        if not route_ready:
            readiness = "Assignment Blocked"
            rank = 0
            next_action = "Assign this privileged-access finding before changing access."
        elif severity in {"CRITICAL", "HIGH"}:
            readiness = "Telemetry Pending"
            rank = 1
            next_action = "Load ticket/reference, impact note, and rollback status before revoke or narrowing action."
        else:
            readiness = "Review Ready"
            rank = 2
            next_action = "Validate business justification and monitor telemetry before closure."
        rows.append({
            "OWNER": context.get("owner", ""),
            "EMAIL_TARGET": context.get("route_email", ""),
            "REVIEWED_BY": context.get("review_primary", ""),
            "REVIEW_STATUS": "",
            "WORKFLOW_ROUTE": context.get("escalation", ""),
            "ALLOCATION_SOURCE": context.get("source", ""),
            "ALLOCATION_BASIS": context.get("route_evidence", ""),
            "WORKFLOW_ROUTE_READY": "Yes" if route_ready else "No",
            "GRANT_REVIEW_STATE": review_state,
            "GRANT_REVIEW_READINESS": readiness,
            "GRANT_REVIEW_RANK": rank,
            "DATABASE_CONTEXT": database_context,
            "SCOPE_CONFIDENCE": "Database Context" if database_context else "Account/User Context",
            "NEXT_GRANT_ACTION": next_action,
        })
    annotated = pd.concat([view.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    return annotated.sort_values(
        ["GRANT_REVIEW_RANK", "SEVERITY", "CREATED_ON"],
        ascending=[True, True, False],
    )

def _privilege_sprawl_summary(grants: pd.DataFrame | None) -> dict:
    """Summarize privileged access sprawl without requiring another Snowflake query."""
    if grants is None or not isinstance(grants, pd.DataFrame) or grants.empty:
        return {
            "total": 0,
            "tier0": 0,
            "admin_role_grants": 0,
            "object_privileges": 0,
            "ownership_or_grant_option": 0,
            "verification_required": 0,
            "route_blocked": 0,
            "account_scope": 0,
            "stale_admin_grants": 0,
        }
    frame = grants.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    def _column(name: str, default=None) -> pd.Series:
        value = frame.get(name)
        if isinstance(value, pd.DataFrame):
            return value.iloc[:, -1]
        if isinstance(value, pd.Series):
            return value
        return pd.Series([default] * len(frame))

    role = _column("ROLE_NAME", "").fillna("").astype(str).str.upper()
    privilege = _column("PRIVILEGE", "").fillna("").astype(str).str.upper()
    grant_option = _column("GRANT_OPTION", False).fillna(False)
    if not isinstance(grant_option, pd.Series):
        grant_option = pd.Series(dtype=bool)
    grant_option_flag = grant_option.astype(str).str.lower().isin(["true", "1", "yes"])
    readiness = _column("GRANT_REVIEW_READINESS", "").fillna("").astype(str)
    database_context = _column("DATABASE_CONTEXT", False).fillna(False)
    age_days = pd.to_numeric(_column("GRANT_AGE_DAYS", 0), errors="coerce").fillna(0)
    tier0_roles = {"ACCOUNTADMIN", "ORGADMIN", "SECURITYADMIN"}
    admin_role_mask = role.ne("")
    object_privilege_mask = privilege.ne("")
    tier0_mask = role.isin(tier0_roles)
    ownership_or_grant_option = privilege.isin(["OWNERSHIP", "MANAGE GRANTS"]) | grant_option_flag
    return {
        "total": int(len(frame)),
        "tier0": int(tier0_mask.sum()),
        "admin_role_grants": int(admin_role_mask.sum()),
        "object_privileges": int(object_privilege_mask.sum()),
        "ownership_or_grant_option": int(ownership_or_grant_option.sum()),
        "verification_required": int(readiness.eq("Telemetry Pending").sum()),
        "route_blocked": int(readiness.eq("Assignment Blocked").sum()),
        "account_scope": int((~database_context.astype(bool)).sum()),
        "stale_admin_grants": int((admin_role_mask & (age_days >= 90)).sum()),
    }

def load_privileged_grant_readiness(company: str, environment: str, grant_days: int) -> tuple[pd.DataFrame, str, dict]:
    """Load and annotate privileged-grant evidence for the current security scope."""
    grant_sql = _security_privileged_grant_review_sql(grant_days, company, environment)
    grant_rows = run_query(
        grant_sql,
        ttl_key=f"security_privileged_grants_{company}_{environment}_{grant_days}",
        tier="standard",
        section="Security Posture",
        max_rows=500,
        query_boundary="evidence_targeted",
    )
    return (
        _annotate_security_privileged_grant_readiness(grant_rows),
        grant_sql,
        _security_scope_meta(company, environment, grant_days),
    )

def _render_privileged_grant_readiness(
    company: str,
    environment: str,
    days: int,
    *,
    as_expander: bool = True,
    expanded: bool = False,
    title: str = "Privileged Grant Status",
    load_label: str = "Load Privileged Grant Status",
    load_key: str = "security_priv_grant_load",
) -> None:
    def _body() -> None:
        st.caption(
            "Reviews account-level admin role grants and database-scoped object privileges before DBA grant/revoke work. "
            "Account-role grants stay visible under PROD/DEV filters because they have no database context."
        )
        grant_days = day_window_selectbox(
            "Privileged grant lookback",
            key="security_priv_grant_days",
            default=max(7, int(days or 30)),
        )
        if st.button(load_label, key=load_key, type="primary" if not as_expander else "secondary"):
            try:
                with query_budget_context(
                    "evidence_click",
                    section="Security Monitoring",
                    workflow="Privilege Sprawl",
                    budget=EVIDENCE_CLICK_QUERY_BUDGET,
                ):
                    grants, grant_sql, grant_meta = load_privileged_grant_readiness(company, environment, grant_days)
                    st.session_state["security_privileged_grants"] = grants
                    st.session_state["security_privileged_grants_sql"] = grant_sql
                    st.session_state["security_privileged_grants_meta"] = grant_meta
            except Exception as exc:
                st.session_state["security_privileged_grants"] = pd.DataFrame()
                st.warning(f"Privileged grant status unavailable: {format_snowflake_error(exc)}")

        grants = st.session_state.get("security_privileged_grants")
        if grants is None:
            st.info("Load this before granting, revoking, or narrowing high-risk roles and object privileges.")
            with st.expander("Privileged Grant Status", expanded=False):
                render_shell_snapshot((
                    ("Scope", "Details available when needed"),
                    ("Escalation route", "Required"),
                    ("Review", "Required"),
                    ("Execution", "Runbook only"),
                ))
            return
        if not _security_meta_matches(
            st.session_state.get("security_privileged_grants_meta"),
            _security_scope_meta(company, environment, grant_days),
        ):
            st.info("Loaded privileged grant status is stale for the active scope. Reload before granting, revoking, or narrowing access.")
            with st.expander("Privileged Grant Status", expanded=False):
                render_shell_snapshot((
                    ("Scope", "Stale"),
                    ("Refresh", "Required"),
                    ("Approval", "Required"),
                    ("Execution", "Runbook only"),
                ))
            return
        if grants.empty:
            st.success("No privileged grant rows found for the selected scope and lookback.")
            return

        summary = _privilege_sprawl_summary(grants)
        blocked = grants[grants["GRANT_REVIEW_READINESS"] == "Assignment Blocked"]
        approval = grants[grants["GRANT_REVIEW_READINESS"] == "Telemetry Pending"]
        account_scope = grants[~grants["DATABASE_CONTEXT"]]
        render_shell_snapshot((
            ("Privileged Grants", f"{len(grants):,}"),
            ("Telemetry", f"{len(approval):,}"),
            ("Assignment Blocked", f"{len(blocked):,}"),
            ("Account Scope", f"{len(account_scope):,}"),
        ))
        if not as_expander:
            render_shell_snapshot((
                ("Tier 0", f"{summary['tier0']:,}"),
                ("Admin Roles", f"{summary['admin_role_grants']:,}"),
                ("Grant Option", f"{summary['ownership_or_grant_option']:,}"),
                ("Stale Admin", f"{summary['stale_admin_grants']:,}"),
            ))

        render_priority_dataframe(
            grants,
            title="Privileged grant review before access changes",
            priority_columns=[
                "SEVERITY", "GRANT_REVIEW_READINESS", "GRANT_REVIEW_STATE",
                "FINDING_TYPE", "ENTITY", "ROLE_NAME", "PRIVILEGE", "GRANT_OPTION",
                "OBJECT_NAME", "DATABASE_NAME", "GRANT_AGE_DAYS",
                "ENVIRONMENT", "SCOPE_CONFIDENCE", "OWNER", "WORKFLOW_ROUTE_READY",
                "REVIEWED_BY", "REVIEW_STATUS", "GRANTED_BY", "CREATED_ON",
                "PROOF_REQUIRED", "NEXT_GRANT_ACTION",
            ],
            sort_by=["GRANT_REVIEW_RANK", "SEVERITY", "CREATED_ON"],
            ascending=[True, True, False],
            raw_label="All privileged grant status rows",
            height=320,
        )
        if st.button("Save Privileged Grants to Action Queue", key="security_priv_grants_queue"):
            _queue_privileged_grant_actions(get_session(), grants, company=company, environment=environment)
        with st.expander("Privileged Grant Status", expanded=False):
            render_shell_snapshot((
                ("Grant review", "Ready"),
                ("Telemetry", "Required"),
                ("Queue action", "Available"),
                ("Execution", "Runbook only"),
            ))

    if as_expander:
        with st.expander(title, expanded=expanded):
            _body()
    else:
        render_escaped_bold_text(title)
        _body()

def _render_privilege_sprawl_workflow(company: str, environment: str, days: int) -> None:
    _render_privileged_grant_readiness(
        company,
        environment,
        days,
        as_expander=False,
        title="Privilege Sprawl",
        load_label="Load Privilege Sprawl",
        load_key="security_privilege_sprawl_load",
    )

def render_security_privilege_sprawl(company: str, environment: str, days: int) -> None:
    _render_privilege_sprawl_workflow(company, environment, days)
    _render_advanced_security_evidence(company, environment)

__all__ = [
    '_security_privileged_grant_review_sql',
    '_annotate_security_privileged_grant_readiness',
    '_privilege_sprawl_summary',
    'load_privileged_grant_readiness',
    '_render_privileged_grant_readiness',
    '_render_privilege_sprawl_workflow',
    'render_security_privilege_sprawl',
]
