# sections/task_management_sla_cost_view.py - SLA & Cost Drift renderer
import pandas as pd
import streamlit as st

from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from utils.workflows import render_priority_dataframe
from utils import (
    build_task_history_sql,
    day_window_selectbox,
    download_csv,
    format_snowflake_error,
    get_active_company,
    admin_button_disabled,
    load_live_task_runs,
    load_shared_task_history_detail,
    run_query,
    run_query_or_raise,
    safe_int,
    safe_float,
    sql_literal,
    render_ranked_bar_chart,
)
from sections.task_management_action_queue import *
from sections.task_management_common import *
from sections.task_management_contracts import *
from sections.task_management_models import *
from sections.task_management_sql import *

def _render_sla_cost_drift_console(session) -> None:
    company = get_active_company()
    st.subheader("Task SLA & Cost Drift")
    st.caption(
        "Use this after product releases or stored procedure changes. It compares each task's latest run "
        "to its own historical baseline and highlights duration or estimated-credit regressions."
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        days = day_window_selectbox("Lookback", key="task_sla_days", default=14)
    with c2:
        duration_pct = st.slider("Duration drift threshold (%)", 10, 300, 50, key="task_sla_duration_pct")
    with c3:
        cost_pct = st.slider("Cost drift threshold (%)", 10, 300, 50, key="task_sla_cost_pct")
    with c4:
        min_duration_sec = st.number_input("Minimum latest runtime (sec)", min_value=0, value=300, step=60, key="task_sla_min_runtime")
    min_credits = st.number_input(
        "Minimum estimated credits before cost drift matters",
        min_value=0.0,
        value=0.01,
        step=0.01,
        format="%.4f",
        key="task_sla_min_credits",
    )
    threshold_context = {
        "Lookback Days": int(days),
        "Duration Drift Threshold %": float(duration_pct),
        "Cost Drift Threshold %": float(cost_pct),
        "Minimum Runtime Sec": float(min_duration_sec),
        "Minimum Estimated Credits": float(min_credits),
    }
    st.caption(
        "Thresholds: "
        f"runtime >= {safe_float(min_duration_sec):,.0f}s and +{safe_float(duration_pct):,.0f}% over baseline; "
        f"estimated credits >= {safe_float(min_credits):,.4f} and +{safe_float(cost_pct):,.0f}% over baseline."
    )

    if st.button("Load SLA & Cost Drift", key="task_sla_load"):
        summary, exceptions, latest, inventory, details_loaded = _load_task_ops_scope(
            session, days, "task_sla", force_inventory_refresh=True
        )
        st.session_state["task_sla_summary"] = summary
        st.session_state["task_sla_latest"] = latest
        st.session_state["task_sla_inventory"] = inventory
        st.session_state["task_sla_details_loaded"] = details_loaded
        st.session_state["task_sla_threshold_context"] = threshold_context

    latest = st.session_state.get("task_sla_latest", pd.DataFrame())
    if latest is None or latest.empty:
        st.info("Load SLA & Cost Drift to compare latest task runs to historical baselines.")
        return

    view = latest.copy()
    for col in ["DURATION_SEC", "AVG_DURATION_SEC", "EST_TOTAL_CREDITS", "AVG_EST_CREDITS"]:
        if col not in view.columns:
            view[col] = 0.0
        view[col] = pd.to_numeric(view[col], errors="coerce").fillna(0.0)
    view["DURATION_CHANGE_PCT"] = view.apply(
        lambda row: ((row["DURATION_SEC"] - row["AVG_DURATION_SEC"]) / row["AVG_DURATION_SEC"] * 100)
        if row["AVG_DURATION_SEC"] > 0 else 0.0,
        axis=1,
    )
    view["COST_CHANGE_PCT"] = view.apply(
        lambda row: ((row["EST_TOTAL_CREDITS"] - row["AVG_EST_CREDITS"]) / row["AVG_EST_CREDITS"] * 100)
        if row["AVG_EST_CREDITS"] > 0 else 0.0,
        axis=1,
    )
    view["SLA_BREACH"] = (
        (view["AVG_DURATION_SEC"] > 0)
        & (view["DURATION_SEC"] >= float(min_duration_sec))
        & (view["DURATION_CHANGE_PCT"] >= float(duration_pct))
    )
    view["COST_DRIFT"] = (
        (view["AVG_EST_CREDITS"] > 0)
        & (view["EST_TOTAL_CREDITS"] >= float(min_credits))
        & (view["COST_CHANGE_PCT"] >= float(cost_pct))
    )
    view["BREACH_REASON"] = view.apply(
        lambda row: "SLA and cost drift" if row["SLA_BREACH"] and row["COST_DRIFT"]
        else "SLA breach" if row["SLA_BREACH"]
        else "Cost drift" if row["COST_DRIFT"]
        else "Within threshold",
        axis=1,
    )
    for label, value in threshold_context.items():
        view[label.upper().replace(" ", "_").replace("%", "PCT")] = value
    breaches = (
        view[view["SLA_BREACH"] | view["COST_DRIFT"]]
        .sort_values(["SLA_BREACH", "COST_DRIFT", "DURATION_CHANGE_PCT", "COST_CHANGE_PCT"], ascending=[False, False, False, False])
    )

    summary = st.session_state.get("task_sla_summary", {})
    render_shell_snapshot((
        ("Tasks Compared", f"{len(view):,}"),
        ("SLA Breaches", f"{int(view['SLA_BREACH'].sum()):,}"),
        ("Cost Drift", f"{int(view['COST_DRIFT'].sum()):,}"),
        ("Failures", f"{safe_int(summary.get('FAILED_RUNS')):,}"),
        ("Query Detail", "Loaded" if st.session_state.get("task_sla_details_loaded") else "Estimated"),
    ))
    task_sla_sources = st.session_state.get("task_sla_sources", {})
    if task_sla_sources:
        st.caption(
            " | ".join([
                str(task_sla_sources.get("inventory", "")),
                str(task_sla_sources.get("history", "")),
                str(task_sla_sources.get("query_detail", "")),
            ])
        )
    if st.session_state.get("task_sla_details_loaded"):
        st.caption("Cost drift uses linked QUERY_HISTORY query detail and estimated task query credits.")
    else:
        st.caption("Cost drift needs linked QUERY_HISTORY detail; duration/SLA review is still available.")

    display_cols = [
        col for col in [
            "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "STATE", "QUERY_ID",
            "DURATION_SEC", "AVG_DURATION_SEC", "DURATION_CHANGE_PCT",
            "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "COST_CHANGE_PCT",
            "BREACH_REASON", "WAREHOUSE_NAME", "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT",
            "BLAST_RADIUS", "IMPACT_OBJECTS", "TASK_FQN",
        ] if col in view.columns
    ]
    if breaches.empty:
        st.success("No task runs breached the selected SLA or cost drift thresholds.")
    else:
        st.warning("Task regressions found. Review these before the next production handoff.")
        render_priority_dataframe(
            breaches[display_cols],
            title="Task SLA and cost regressions",
            priority_columns=[
                "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "BREACH_REASON",
                "DURATION_SEC", "AVG_DURATION_SEC", "DURATION_CHANGE_PCT",
                "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "COST_CHANGE_PCT",
                "WAREHOUSE_NAME", "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT",
                "BLAST_RADIUS", "IMPACT_OBJECTS",
            ],
            sort_by=["DOWNSTREAM_TASK_COUNT", "DURATION_CHANGE_PCT", "COST_CHANGE_PCT", "DURATION_SEC"],
            ascending=[False, False, False, False],
            raw_label="All task SLA/cost breach rows",
        )
        top_duration = breaches.sort_values("DURATION_CHANGE_PCT", ascending=False).head(15)
        top_cost = breaches.sort_values("COST_CHANGE_PCT", ascending=False).head(15)
        left, right = st.columns(2)
        with left:
            if "TASK_NAME" in top_duration.columns:
                render_ranked_bar_chart(
                    top_duration,
                    "TASK_NAME",
                    "DURATION_CHANGE_PCT",
                    title="Top Duration Regressions",
                    top_n=15,
                )
        with right:
            if "TASK_NAME" in top_cost.columns:
                render_ranked_bar_chart(
                    top_cost,
                    "TASK_NAME",
                    "COST_CHANGE_PCT",
                    title="Top Cost Regressions",
                    top_n=15,
                    color="#f59e0b",
                )
        queue_rows = []
        for _, row in breaches.head(100).iterrows():
            signal = "Long Running / SLA Risk" if row.get("SLA_BREACH") else "Cost Drift / Release Regression"
            if row.get("SLA_BREACH") and row.get("COST_DRIFT"):
                signal = "SLA and Cost Drift"
            queue_stub = pd.Series({
                "SIGNAL": signal,
                "DOWNSTREAM_TASK_COUNT": row.get("DOWNSTREAM_TASK_COUNT", 0),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
            })
            queue_rows.append({
                "SEVERITY": "High" if row.get("SLA_BREACH") and safe_float(row.get("DURATION_CHANGE_PCT")) >= duration_pct * 2 else "Medium",
                "SIGNAL": signal,
                "INCIDENT_PRIORITY": _task_exception_incident_priority(queue_stub),
                "RECOVERY_READINESS": _task_exception_recovery_readiness(queue_stub),
                "TASK_NAME": row.get("TASK_NAME", ""),
                "ROOT_TASK_NAME": row.get("ROOT_TASK_NAME", ""),
                "PROCEDURE_NAME": row.get("PROCEDURE_NAME", ""),
                "QUERY_ID": row.get("QUERY_ID", ""),
                "STATE": row.get("STATE", ""),
                "DETAIL": (
                    f"Latest runtime {safe_float(row.get('DURATION_SEC')):,.0f}s vs avg {safe_float(row.get('AVG_DURATION_SEC')):,.0f}s "
                    f"({safe_float(row.get('DURATION_CHANGE_PCT')):,.1f}%). "
                    f"Latest credits {safe_float(row.get('EST_TOTAL_CREDITS')):,.4f} vs avg {safe_float(row.get('AVG_EST_CREDITS')):,.4f} "
                    f"({safe_float(row.get('COST_CHANGE_PCT')):,.1f}%). "
                    f"Thresholds: runtime +{safe_float(duration_pct):,.0f}% over baseline and >= {safe_float(min_duration_sec):,.0f}s; "
                    f"cost +{safe_float(cost_pct):,.0f}% over baseline and >= {safe_float(min_credits):,.4f} credits."
                ),
                "IMPACT_OBJECTS": row.get("IMPACT_OBJECTS", ""),
                "TASK_FQN": row.get("TASK_FQN", ""),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
                "DOWNSTREAM_TASK_COUNT": row.get("DOWNSTREAM_TASK_COUNT", 0),
                "BLAST_RADIUS": row.get("BLAST_RADIUS", ""),
                "RETRY_SCOPE": row.get("RETRY_SCOPE", ""),
            })
        queue_df = pd.DataFrame(queue_rows)
        if st.button("Save SLA/Cost Drift Findings to Action Queue", key="task_sla_queue"):
            try:
                saved = _queue_task_ops_findings(session, queue_df)
                st.success(f"Saved {saved} SLA/cost drift findings to the action queue.")
            except Exception as e:
                st.error(f"Could not save SLA/cost drift findings: {format_snowflake_error(e)}")
                st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")

    with st.expander("All Latest Task Runs"):
        render_priority_dataframe(
            view[display_cols],
            title="Latest task run detail",
            priority_columns=display_cols,
            sort_by=["DURATION_SEC", "EST_TOTAL_CREDITS"],
            ascending=[False, False],
            raw_label="Full latest task run detail",
            max_rows=100,
        )
    download_csv(view[display_cols], f"task_sla_cost_drift_{company.lower()}.csv")


def render_task_sla_cost_drift(session) -> None:
    _render_sla_cost_drift_console(session)


__all__ = ["_render_sla_cost_drift_console", "render_task_sla_cost_drift"]
