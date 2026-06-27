# sections/dba_tools_warehouse_settings_view.py - Warehouse Settings render branch.

from html import escape as html_escape

import pandas as pd
import streamlit as st

from sections.dba_tools_common import (
    _as_bool,
    _as_int,
    _require_typed_confirmation,
    _typed_confirmation,
)
from sections.dba_tools_warehouse_settings import _build_warehouse_setting_plan
from sections.shell_helpers import render_shell_snapshot
from utils import (
    admin_button_disabled,
    format_snowflake_error,
    get_active_company,
    get_active_environment,
    load_warehouse_inventory,
    log_admin_action,
    safe_sql,
)
from utils.dba_tool_catalog import (
    SCALE_OPTS as _SCALE_OPTS,
    SIZE_OPTS as _SIZE_OPTS,
    WH_PARAM_HELP as _WH_PARAM_HELP,
)
from utils.workflows import render_priority_dataframe


def render_warehouse_settings_tool(session, company: str) -> None:
    st.subheader("Warehouse Settings Manager")
    st.caption(
        "View and interactively change all warehouse parameters - "
        "size, timeouts, auto-suspend, multi-cluster, QAS, and scaling policy. "
        "Changes are applied only after a reviewed plan, rollback SQL, typed confirmation, and audit logging."
    )

    active_company = get_active_company()
    needs_wh_load = (
        st.session_state.get("_dba_wh_cfg_company") != active_company
        or "dba_df_wh_cfg" not in st.session_state
    )
    last_failed_company = st.session_state.get("_dba_wh_cfg_failed_company")

    col_r1, col_r2 = st.columns([1, 1])
    with col_r1:
        refresh_wh = st.button("Refresh Warehouses", key="wh_cfg_load")
        if refresh_wh or (needs_wh_load and last_failed_company != active_company):
            try:
                df_raw = load_warehouse_inventory(session, active_company, force_refresh=bool(refresh_wh))
                df_raw.columns = [c.lower() for c in df_raw.columns]
                st.session_state["dba_df_wh_cfg"] = df_raw
                st.session_state["_dba_wh_cfg_company"] = active_company
                st.session_state.pop("_dba_wh_cfg_failed_company", None)
            except Exception as e:
                st.warning(f"Warehouse list unavailable in this role/context: {format_snowflake_error(e)}")
                st.session_state["dba_df_wh_cfg"] = pd.DataFrame()
                st.session_state["_dba_wh_cfg_company"] = active_company
                st.session_state["_dba_wh_cfg_failed_company"] = active_company
    with col_r2:
        wh_filter_txt = st.text_input("Filter warehouse", key="wh_cfg_filter",
                                       placeholder="e.g. ALFA or leave blank for all")

    df_wh = st.session_state.get("dba_df_wh_cfg")
    if df_wh is not None and not df_wh.empty:
        # Apply filter
        if wh_filter_txt:
            mask   = df_wh["name"].astype(str).str.upper().str.contains(safe_sql(wh_filter_txt).upper(), na=False)
            df_wh  = df_wh[mask]

        # Summary table
        st.subheader(f"Warehouses ({len(df_wh)})")
        display_cols = [c for c in ["name","size","state","auto_suspend","auto_resume",
                                     "min_cluster_count","max_cluster_count","scaling_policy",
                                     "enable_query_acceleration","statement_timeout_in_seconds",
                                     "statement_queued_timeout_in_seconds"] if c in df_wh.columns]
        render_priority_dataframe(
            df_wh[display_cols],
            title="Warehouse settings by risk",
            priority_columns=display_cols,
            sort_by=["auto_suspend", "state", "name"],
            ascending=[False, True, True],
            raw_label="All warehouse setting rows",
            height=220,
        )

        # Flag issues
        issues = []
        for _, row in df_wh.iterrows():
            wn  = row.get("name","")
            sus = row.get("auto_suspend", 0)
            try:
                if int(sus) > 600:
                    issues.append(f"Medium - **{wn}**: AUTO_SUSPEND={sus}s (>10 min) - wasting credits when idle")
                if int(sus) == 0:
                    issues.append(f"High - **{wn}**: AUTO_SUSPEND=0 - warehouse never suspends")
            except Exception:
                pass
        if issues:
            with st.expander(f"{len(issues)} configuration issue(s) detected"):
                for i in issues:
                    st.markdown(i)

        st.divider()
        st.subheader("Edit Warehouse Settings")
        st.caption("Select a warehouse, adjust parameters, review the proposed change, then apply.")

        wh_names = df_wh["name"].tolist() if "name" in df_wh.columns else []
        sel_wh   = st.selectbox("Select warehouse to edit", wh_names, key="wh_edit_sel")

        if sel_wh:
            wh_row = df_wh[df_wh["name"] == sel_wh].iloc[0]

            def _get(col, default=""):
                v = wh_row.get(col, default)
                return "" if v is None or str(v).lower() in ("nan","none","") else str(v)

            st.html(
                "<div style='line-height:1.45;margin:.15rem 0;'>"
                f"<strong>Editing:</strong> <code>{html_escape(str(sel_wh))}</code> | "
                f"Current state: <code>{html_escape(_get('state', 'unknown'))}</code>"
                "</div>"
            )

            with st.form(f"wh_edit_form_{sel_wh}"):
                c1, c2, c3 = st.columns(3)

                with c1:
                    st.markdown("**Compute**")
                    curr_size = _get("size","X-Small")
                    new_size  = st.selectbox(
                        "Size", _SIZE_OPTS,
                        index=_SIZE_OPTS.index(curr_size) if curr_size in _SIZE_OPTS else 0,
                        key=f"wh_size_{sel_wh}",
                        help=_WH_PARAM_HELP["WAREHOUSE_SIZE"],
                    )
                    new_auto_resume = st.checkbox(
                        "Auto Resume",
                        value=_as_bool(_get("auto_resume","true"), True),
                        key=f"wh_ar_{sel_wh}",
                        help=_WH_PARAM_HELP["AUTO_RESUME"],
                    )
                    curr_sus = _as_int(_get("auto_suspend","600"), 600)
                    new_auto_suspend = st.number_input(
                        "AUTO_SUSPEND (seconds, 0=never)",
                        min_value=0, max_value=86400, value=curr_sus, step=60,
                        key=f"wh_sus_{sel_wh}",
                        help=_WH_PARAM_HELP["AUTO_SUSPEND"],
                    )

                with c2:
                    st.markdown("**Timeouts**")
                    curr_stmt_to = _as_int(_get("statement_timeout_in_seconds","0"), 0)
                    new_stmt_timeout = st.number_input(
                        "STATEMENT_TIMEOUT (sec, 0=no limit)",
                        min_value=0, max_value=604800, value=curr_stmt_to, step=300,
                        key=f"wh_stmto_{sel_wh}",
                        help=_WH_PARAM_HELP["STATEMENT_TIMEOUT_IN_SECONDS"],
                    )
                    curr_q_to = _as_int(_get("statement_queued_timeout_in_seconds","0"), 0)
                    new_queue_timeout = st.number_input(
                        "QUEUE_TIMEOUT (sec, 0=no limit)",
                        min_value=0, max_value=86400, value=curr_q_to, step=60,
                        key=f"wh_qto_{sel_wh}",
                        help=_WH_PARAM_HELP["STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"],
                    )
                    curr_concur = _as_int(_get("max_concurrency_level","8"), 8)
                    new_concurrency = st.number_input(
                        "MAX_CONCURRENCY_LEVEL",
                        min_value=1, max_value=10, value=min(max(curr_concur,1),10),
                        key=f"wh_concur_{sel_wh}",
                        help=_WH_PARAM_HELP["MAX_CONCURRENCY_LEVEL"],
                    )

                with c3:
                    st.markdown("**Scaling & QAS**")
                    curr_scale = _get("scaling_policy","STANDARD").upper()
                    new_scaling = st.selectbox(
                        "SCALING_POLICY",
                        _SCALE_OPTS,
                        index=_SCALE_OPTS.index(curr_scale) if curr_scale in _SCALE_OPTS else 0,
                        key=f"wh_sp_{sel_wh}",
                        help=_WH_PARAM_HELP["SCALING_POLICY"],
                    )
                    curr_min = _as_int(_get("min_cluster_count","1"), 1)
                    curr_max = _as_int(_get("max_cluster_count","1"), 1)
                    new_min_clusters = st.number_input(
                        "MIN_CLUSTER_COUNT",
                        min_value=1, max_value=10, value=max(curr_min,1),
                        key=f"wh_minc_{sel_wh}",
                        help=_WH_PARAM_HELP["MIN_CLUSTER_COUNT"],
                    )
                    new_max_clusters = st.number_input(
                        "MAX_CLUSTER_COUNT",
                        min_value=1, max_value=10, value=max(curr_max,1),
                        key=f"wh_maxc_{sel_wh}",
                        help=_WH_PARAM_HELP["MAX_CLUSTER_COUNT"],
                    )
                    curr_qas = _as_bool(_get("enable_query_acceleration","false"), False)
                    new_qas  = st.checkbox(
                        "Enable QAS",
                        value=curr_qas,
                        key=f"wh_qas_{sel_wh}",
                        help=_WH_PARAM_HELP["ENABLE_QUERY_ACCELERATION"],
                    )
                    curr_qas_sf = _as_int(_get("query_acceleration_max_scale_factor","8"), 8)
                    new_qas_sf = st.number_input(
                        "QAS Max Scale Factor (0=unlimited)",
                        min_value=0, max_value=100, value=curr_qas_sf,
                        key=f"wh_qassf_{sel_wh}",
                        help=_WH_PARAM_HELP["QUERY_ACCELERATION_MAX_SCALE_FACTOR"],
                        disabled=not new_qas,
                    )

                preview_plan = st.form_submit_button("Preview Change Plan", type="primary")

            plan_key = f"wh_change_plan_{sel_wh}"
            if preview_plan:
                requested = {
                    "WAREHOUSE_SIZE": new_size,
                    "AUTO_SUSPEND": int(new_auto_suspend),
                    "AUTO_RESUME": bool(new_auto_resume),
                    "STATEMENT_TIMEOUT_IN_SECONDS": int(new_stmt_timeout),
                    "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": int(new_queue_timeout),
                    "MAX_CONCURRENCY_LEVEL": int(new_concurrency),
                    "SCALING_POLICY": new_scaling,
                    "MIN_CLUSTER_COUNT": int(new_min_clusters),
                    "MAX_CLUSTER_COUNT": int(new_max_clusters),
                    "ENABLE_QUERY_ACCELERATION": bool(new_qas),
                    "QUERY_ACCELERATION_MAX_SCALE_FACTOR": int(new_qas_sf),
                }
                st.session_state[plan_key] = _build_warehouse_setting_plan(sel_wh, wh_row, requested)

            plan = st.session_state.get(plan_key)
            if plan:
                st.subheader("Reviewed Warehouse Change Plan")
                changes_df = plan.get("changes_df", pd.DataFrame())
                skipped_df = plan.get("skipped_df", pd.DataFrame())
                if changes_df.empty:
                    st.success("No warehouse settings changed from the loaded before-state.")
                else:
                    render_priority_dataframe(
                        changes_df,
                        title="Before/after settings requiring review",
                        priority_columns=[
                            "REVIEW_GATE", "REVIEW_DECISION", "PARAMETER",
                            "CURRENT", "REQUESTED", "RISK",
                            "PROOF_REQUIRED", "VERIFY_AFTER_CHANGE",
                        ],
                        sort_by=["PARAMETER"],
                        ascending=True,
                        raw_label="All proposed warehouse changes",
                        height=240,
                    )
                    st.caption(
                        "Only changed parameters are included in the reviewed change plan. "
                        "Run pre-flight checks and keep rollback instructions with the change ticket."
                    )
                    render_shell_snapshot((
                        ("Pre-flight", "Required"),
                        ("Apply plan", "Review gated"),
                        ("Rollback", "Required"),
                        ("Execution", "reviewed workflow"),
                    ))

                if not skipped_df.empty:
                    st.warning("Some settings were not included because their current values were unavailable.")
                    render_priority_dataframe(
                        skipped_df,
                        title="Skipped settings",
                        priority_columns=["PARAMETER", "REASON"],
                        sort_by=["PARAMETER"],
                        ascending=True,
                        raw_label="All skipped settings",
                        height=160,
                    )

                if not changes_df.empty:
                    col_apply, col_audit = st.columns([1, 3])
                    with col_apply:
                        wh_confirmed = _typed_confirmation(
                            f"Type {plan['confirmation_text']} to apply this warehouse change",
                            plan["confirmation_text"],
                            f"wh_confirm_reviewed_{sel_wh}",
                        )
                        if st.button(
                            "Apply Warehouse Change",
                            type="primary",
                            key=f"wh_apply_reviewed_{sel_wh}",
                            disabled=admin_button_disabled(),
                        ):
                            if _require_typed_confirmation(wh_confirmed, plan["confirmation_text"]):
                                try:
                                    log_admin_action(
                                        session,
                                        action_type="ALTER WAREHOUSE",
                                        target_object=sel_wh,
                                        sql_text=plan["alter_sql"],
                                        result_status="STARTED",
                                        result_message="Warehouse change submitted from OVERWATCH.",
                                        confirmation_text=plan["confirmation_text"],
                                        control_context=plan["control_context"],
                                        company=active_company,
                                        environment=get_active_environment(),
                                    )
                                    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                    session.sql(plan["alter_sql"]).collect()
                                    audited = log_admin_action(
                                        session,
                                        action_type="ALTER WAREHOUSE",
                                        target_object=sel_wh,
                                        sql_text=plan["alter_sql"],
                                        result_status="SUCCESS",
                                        result_message="Warehouse change completed.",
                                        confirmation_text=plan["confirmation_text"],
                                        control_context=plan["control_context"],
                                        company=active_company,
                                        environment=get_active_environment(),
                                    )
                                    st.success(f"Warehouse `{sel_wh}` updated successfully.")
                                    if not audited:
                                        st.warning("The change completed, but the admin audit table was unavailable or not writable.")
                                    st.session_state.pop("dba_df_wh_cfg", None)
                                    st.session_state.pop(plan_key, None)
                                    st.rerun()
                                except Exception as e:
                                    err = format_snowflake_error(e)
                                    log_admin_action(
                                        session,
                                        action_type="ALTER WAREHOUSE",
                                        target_object=sel_wh,
                                        sql_text=plan["alter_sql"],
                                        result_status="FAILED",
                                        result_message=err,
                                        confirmation_text=plan["confirmation_text"],
                                        control_context=plan["control_context"],
                                        company=active_company,
                                        environment=get_active_environment(),
                                    )
                                    err_str = str(e).lower()
                                    if "insufficient privilege" in err_str or "not authorized" in err_str:
                                        st.error(
                                            f"Permission denied on `{sel_wh}`. "
                                            f"ALTER WAREHOUSE requires MODIFY privilege."
                                        )
                                    elif "enterprise" in err_str or "not supported" in err_str:
                                        st.error(
                                            "Feature not available in your Snowflake edition. "
                                            "Multi-cluster and QAS require Enterprise or higher."
                                        )
                                    else:
                                        st.error(f"ALTER failed: {err}")
                    with col_audit:
                        st.caption(
                            "Audit path: OVERWATCH_ADMIN_ACTION_AUDIT captures company, environment, "
                            "Snowflake role/user, SQL hash, confirmation text, control context, and result."
                        )
