"""DBA Control Room - operational landing page for OVERWATCH.

This page is intentionally workflow-first. It summarizes exceptions that a DBA
must triage, routes each signal to the right specialist tool, and creates
report-ready notes for leadership without making executives use the app.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from config import SECTION_BY_TITLE
from utils import (
    build_metered_credit_cte,
    build_task_failure_summary_sql,
    build_task_history_sql,
    credits_to_dollars,
    download_csv,
    format_credits,
    format_snowflake_error,
    freshness_note,
    filter_existing_columns,
    get_db_filter_clause,
    get_global_filter_clause,
    get_query_budget_summary,
    get_session,
    get_user_filter_clause,
    get_wh_filter_clause,
    build_mart_control_room_summary_sql,
    build_mart_control_room_credits_sql,
    build_mart_control_room_cost_drivers_sql,
    build_mart_control_room_warehouse_pressure_sql,
    build_mart_control_room_failed_queries_sql,
    build_mart_control_room_object_changes_sql,
    build_mart_control_room_failed_logins_sql,
    build_mart_control_room_task_failures_sql,
    build_mart_query_detail_recent_sql,
    build_mart_task_history_sql,
    build_mart_procedure_sla_sql,
    load_latest_control_room_mart,
    load_task_inventory,
    load_action_queue,
    metric_confidence_label,
    run_query,
    safe_float,
    safe_int,
    sql_literal,
)
from sections.task_management import (
    _build_task_ops_frames,
    _extract_object_candidates,
    _normalize_query_details,
    _procedure_from_definition,
    _query_detail_sql,
)
from sections.cortex_monitor import (
    _build_cortex_control_sql,
    _cortex_cost_rating,
    _cortex_cost_score,
)
from sections.stored_proc_tracker import (
    _build_procedure_sla_frames,
    _build_procedure_sla_sql,
    _procedure_run_estimated_credits,
    _query_history_has_root_query_id,
)
from utils.workflows import render_operator_briefing, render_priority_dataframe


def _jump(title: str, *, warehouse: str = "", user: str = "", workflow: str = "") -> None:
    """Navigate to a registered section and carry useful filter context."""
    target = SECTION_BY_TITLE.get(title)
    if not target:
        return
    st.session_state["nav_section"] = target
    if workflow:
        if title in {"Query Workbench", "Workload Operations"}:
            if workflow == "Diagnosis":
                st.session_state["workload_operations_workflow"] = "Query diagnosis"
            elif workflow == "History Search":
                st.session_state["workload_operations_workflow"] = "History search"
            else:
                st.session_state["workload_operations_workflow"] = workflow
        elif title == "Cost & Contract":
            st.session_state["cost_contract_workflow"] = workflow
        elif title == "Security Posture":
            st.session_state["security_posture_workflow"] = workflow
        elif title == "Change & Drift":
            st.session_state["change_drift_workflow"] = workflow
    if warehouse:
        st.session_state["global_warehouse"] = warehouse
        st.session_state["wh_filter"] = warehouse
    if user:
        st.session_state["global_user"] = user
    st.rerun()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


def _snapshot_metric(df: pd.DataFrame, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    return safe_float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _control_room_snapshot_to_data(snapshot: pd.DataFrame) -> dict:
    """Convert the lightweight mart snapshot into the data shape used by the page.

    The mart snapshot is intentionally small: it supports the watch floor and
    morning triage metrics, while deep evidence tables still load on demand.
    """
    if snapshot is None or snapshot.empty:
        return {}
    latest = snapshot.copy()
    latest.columns = [str(col).upper() for col in latest.columns]
    worst_score = safe_float(pd.to_numeric(latest.get("HEALTH_SCORE", pd.Series([100])), errors="coerce").min())
    failed_queries = _snapshot_metric(latest, "FAILED_QUERIES_24H")
    failed_tasks = _snapshot_metric(latest, "FAILED_TASKS_24H")
    queued_ms = _snapshot_metric(latest, "QUEUED_MS_24H")
    credits = _snapshot_metric(latest, "CREDITS_24H")
    cortex_cost = _snapshot_metric(latest, "CORTEX_COST_7D_USD")
    security_events = _snapshot_metric(latest, "SECURITY_EVENTS_24H")
    object_changes = _snapshot_metric(latest, "OBJECT_CHANGES_24H")

    top_risks = [
        str(value)
        for value in latest.get("TOP_RISK", pd.Series(dtype=str)).dropna().astype(str).tolist()
        if str(value).strip() and str(value).strip().lower() != "no immediate exception"
    ]
    summary = pd.DataFrame([{
        "TOTAL_QUERIES": 0,
        "FAILED_QUERIES": failed_queries,
        "QUEUED_QUERIES": 1 if queued_ms > 0 else 0,
        "REMOTE_SPILL_QUERIES": 0,
        "AVG_ELAPSED_SEC": 0,
        "P95_ELAPSED_SEC": 0,
        "ACTIVE_WAREHOUSES": 0,
        "ACTIVE_USERS": 0,
        "MART_HEALTH_SCORE": worst_score,
        "MART_TOP_RISK": ", ".join(dict.fromkeys(top_risks)) or "No immediate exception",
    }])
    credits_df = pd.DataFrame([{"PERIOD_CREDITS": credits, "PRIOR_CREDITS": 0}])
    task_failures = pd.DataFrame(
        [{"TASK_NAME": "Mart summary", "FAILURES": failed_tasks}]
    ) if failed_tasks > 0 else _empty_df()
    failed_logins = pd.DataFrame(
        [{"SIGNAL": "Failed login/security events", "EVENTS": security_events}]
    ) if security_events > 0 else _empty_df()
    object_df = pd.DataFrame(
        [{"SIGNAL": "Object or grant changes", "CHANGES": object_changes}]
    ) if object_changes > 0 else _empty_df()
    cortex_summary = pd.DataFrame([{
        "PROJECTED_30D_COST": cortex_cost / 7 * 30 if cortex_cost > 0 else 0,
        "TOTAL_COST": cortex_cost,
    }])
    return {
        "summary": summary,
        "credits": credits_df,
        "task_failures": task_failures,
        "failed_logins": failed_logins,
        "object_changes": object_df,
        "cortex_summary": cortex_summary,
        "_mart_snapshot": latest,
        "_source_mode": pd.DataFrame([{"MODE": "OVERWATCH mart snapshot"}]),
    }


def _scalar_frame_value(data: dict, key: str, column: str, default=0):
    df = data.get(key, _empty_df())
    if df is None or df.empty or column not in df.columns:
        return default
    return df.iloc[0].get(column, default)


def _release_window_predicate(column: str, start: date, end: date) -> str:
    """Build an inclusive date-window predicate with an exclusive next-day bound."""
    start_ts = sql_literal(f"{start.isoformat()} 00:00:00")
    end_ts = sql_literal(f"{end.isoformat()} 00:00:00")
    return (
        f"{column} >= TO_TIMESTAMP_NTZ({start_ts}) "
        f"AND {column} < DATEADD('day', 1, TO_TIMESTAMP_NTZ({end_ts}))"
    )


def _clean_release_text(values: pd.Series, limit: int = 5) -> str:
    if values is None or values.empty:
        return ""
    seen: list[str] = []
    for raw in values.dropna().astype(str):
        for piece in raw.split(","):
            item = piece.strip()
            if item and item not in seen:
                seen.append(item)
            if len(seen) >= limit:
                return ", ".join(seen)
    return ", ".join(seen)


def _aggregate_release_window(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """Normalize task/procedure run rows into comparable release-window metrics."""
    if df is None or df.empty:
        return pd.DataFrame()
    prepared = df.copy()
    prepared.columns = [str(col).upper() for col in prepared.columns]
    key_col = key_col.upper()
    if key_col not in prepared.columns:
        return pd.DataFrame()

    duration_col = "TOTAL_ELAPSED_SEC" if "TOTAL_ELAPSED_SEC" in prepared.columns else "DURATION_SEC"
    if duration_col not in prepared.columns:
        prepared[duration_col] = 0
    prepared[duration_col] = pd.to_numeric(prepared[duration_col], errors="coerce").fillna(0)
    if "EST_TOTAL_CREDITS" not in prepared.columns:
        prepared["EST_TOTAL_CREDITS"] = 0
    prepared["EST_TOTAL_CREDITS"] = pd.to_numeric(prepared["EST_TOTAL_CREDITS"], errors="coerce").fillna(0)
    if "STATE" not in prepared.columns:
        prepared["STATE"] = ""
    if "ERROR_CODE" not in prepared.columns:
        prepared["ERROR_CODE"] = ""
    if "PROCEDURE_NAME" not in prepared.columns:
        prepared["PROCEDURE_NAME"] = ""
    if "IMPACT_OBJECTS" not in prepared.columns:
        prepared["IMPACT_OBJECTS"] = ""

    prepared[key_col] = prepared[key_col].fillna("").astype(str).str.strip()
    prepared = prepared[prepared[key_col] != ""]
    if prepared.empty:
        return pd.DataFrame()

    failure_mask = (
        prepared["STATE"].fillna("").astype(str).str.upper().isin(["FAILED", "FAILED_WITH_ERROR"])
        | (prepared["ERROR_CODE"].fillna("").astype(str).str.strip() != "")
    )
    prepared["FAILED_RUN"] = failure_mask.astype(int)

    grouped = prepared.groupby(key_col, dropna=False).agg(
        RUNS=(key_col, "count"),
        FAILURES=("FAILED_RUN", "sum"),
        AVG_DURATION_SEC=(duration_col, "mean"),
        P95_DURATION_SEC=(duration_col, lambda s: float(s.quantile(0.95)) if len(s) else 0.0),
        MAX_DURATION_SEC=(duration_col, "max"),
        EST_CREDITS=("EST_TOTAL_CREDITS", "sum"),
    ).reset_index()
    grouped["PROCEDURE_NAME"] = prepared.groupby(key_col)["PROCEDURE_NAME"].apply(_clean_release_text).values
    grouped["IMPACT_OBJECTS"] = prepared.groupby(key_col)["IMPACT_OBJECTS"].apply(_clean_release_text).values
    grouped = grouped.rename(columns={key_col: "ENTITY"})
    return grouped


def _pct_change(before: float, after: float) -> float:
    before = safe_float(before)
    after = safe_float(after)
    if before == 0:
        return 100.0 if after > 0 else 0.0
    return round((after - before) / before * 100, 1)


def _release_signal(
    row: pd.Series,
    runtime_pct_threshold: float = 25,
    runtime_delta_sec_threshold: float = 30,
    credit_pct_threshold: float = 25,
    credit_delta_threshold: float = 0,
) -> tuple[str, str]:
    failure_delta = safe_int(row.get("FAILURES_DELTA"))
    runtime_pct = safe_float(row.get("AVG_DURATION_CHANGE_PCT"))
    credit_pct = safe_float(row.get("EST_CREDITS_CHANGE_PCT"))
    runtime_delta = safe_float(row.get("AVG_DURATION_DELTA_SEC"))
    credit_delta = safe_float(row.get("EST_CREDITS_DELTA"))

    signals = []
    if failure_delta > 0:
        signals.append(f"{failure_delta} more failures")
    if runtime_pct >= safe_float(runtime_pct_threshold) and runtime_delta >= safe_float(runtime_delta_sec_threshold):
        signals.append(f"runtime +{runtime_pct:.1f}%")
    if credit_pct >= safe_float(credit_pct_threshold) and credit_delta > safe_float(credit_delta_threshold):
        signals.append(f"credits +{credit_pct:.1f}%")
    if not signals:
        return "Stable", "No material release-window regression detected."

    severity = (
        "High"
        if failure_delta > 0
        or runtime_pct >= safe_float(runtime_pct_threshold) * 2
        or credit_pct >= safe_float(credit_pct_threshold) * 2
        else "Medium"
    )
    return severity, "; ".join(signals)


def _compare_release_windows(
    before: pd.DataFrame,
    after: pd.DataFrame,
    key_col: str,
    runtime_pct_threshold: float = 25,
    runtime_delta_sec_threshold: float = 30,
    credit_pct_threshold: float = 25,
    credit_delta_threshold: float = 0,
) -> pd.DataFrame:
    before_agg = _aggregate_release_window(before, key_col)
    after_agg = _aggregate_release_window(after, key_col)
    if before_agg.empty and after_agg.empty:
        return pd.DataFrame()

    merged = before_agg.merge(after_agg, on="ENTITY", how="outer", suffixes=("_BEFORE", "_AFTER")).fillna(0)
    for col in ["PROCEDURE_NAME", "IMPACT_OBJECTS"]:
        before_col = f"{col}_BEFORE"
        after_col = f"{col}_AFTER"
        if before_col not in merged.columns:
            merged[before_col] = ""
        if after_col not in merged.columns:
            merged[after_col] = ""
        merged[col] = [
            _clean_release_text(pd.Series([left, right]))
            for left, right in zip(merged[before_col], merged[after_col])
        ]

    for col in ["RUNS", "FAILURES", "AVG_DURATION_SEC", "P95_DURATION_SEC", "MAX_DURATION_SEC", "EST_CREDITS"]:
        before_col = f"{col}_BEFORE"
        after_col = f"{col}_AFTER"
        if before_col not in merged.columns:
            merged[before_col] = 0
        if after_col not in merged.columns:
            merged[after_col] = 0
        merged[f"{col}_DELTA"] = pd.to_numeric(merged[after_col], errors="coerce").fillna(0) - pd.to_numeric(
            merged[before_col], errors="coerce"
        ).fillna(0)

    merged["AVG_DURATION_CHANGE_PCT"] = [
        _pct_change(before, after)
        for before, after in zip(merged["AVG_DURATION_SEC_BEFORE"], merged["AVG_DURATION_SEC_AFTER"])
    ]
    merged["EST_CREDITS_CHANGE_PCT"] = [
        _pct_change(before, after)
        for before, after in zip(merged["EST_CREDITS_BEFORE"], merged["EST_CREDITS_AFTER"])
    ]
    signal_data = merged.apply(
        _release_signal,
        axis=1,
        runtime_pct_threshold=runtime_pct_threshold,
        runtime_delta_sec_threshold=runtime_delta_sec_threshold,
        credit_pct_threshold=credit_pct_threshold,
        credit_delta_threshold=credit_delta_threshold,
    )
    merged["SEVERITY"] = [item[0] for item in signal_data]
    merged["SIGNAL"] = [item[1] for item in signal_data]
    merged["RUNTIME_THRESHOLD_PCT"] = safe_float(runtime_pct_threshold)
    merged["RUNTIME_DELTA_THRESHOLD_SEC"] = safe_float(runtime_delta_sec_threshold)
    merged["CREDIT_THRESHOLD_PCT"] = safe_float(credit_pct_threshold)
    merged["CREDIT_DELTA_THRESHOLD"] = safe_float(credit_delta_threshold)
    return merged.sort_values(
        by=["SEVERITY", "FAILURES_DELTA", "AVG_DURATION_CHANGE_PCT", "EST_CREDITS_CHANGE_PCT"],
        ascending=[True, False, False, False],
    )


def _prepare_task_release_runs(inventory: pd.DataFrame, history: pd.DataFrame, query_details: pd.DataFrame) -> pd.DataFrame:
    runs = history.copy() if history is not None else pd.DataFrame()
    if runs.empty:
        return runs
    runs.columns = [str(col).upper() for col in runs.columns]
    details = _normalize_query_details(query_details)
    if not details.empty and "QUERY_ID" in runs.columns and "QUERY_ID" in details.columns:
        keep = [
            col for col in [
                "QUERY_ID", "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "DATABASE_NAME", "SCHEMA_NAME",
                "QUERY_ELAPSED_SEC", "CLOUD_CREDITS", "EST_TOTAL_CREDITS", "QUERY_TEXT"
            ] if col in details.columns
        ]
        runs = runs.merge(details[keep], on="QUERY_ID", how="left", suffixes=("", "_QUERY"))
    if "EST_TOTAL_CREDITS" not in runs.columns:
        runs["EST_TOTAL_CREDITS"] = 0.0
    if "QUERY_TEXT" in runs.columns:
        runs["IMPACT_OBJECTS"] = runs["QUERY_TEXT"].apply(_extract_object_candidates)
    else:
        runs["IMPACT_OBJECTS"] = ""

    inv = inventory.copy() if inventory is not None else pd.DataFrame()
    if not inv.empty:
        inv.columns = [str(col).upper() for col in inv.columns]
        name_col = "NAME" if "NAME" in inv.columns else "TASK_NAME" if "TASK_NAME" in inv.columns else ""
        if name_col:
            inv["PROCEDURE_NAME"] = inv.get("DEFINITION", pd.Series([""] * len(inv), index=inv.index)).apply(_procedure_from_definition)
            inv["TASK_IMPACT_OBJECTS"] = inv.get("DEFINITION", pd.Series([""] * len(inv), index=inv.index)).apply(_extract_object_candidates)
            runs = runs.merge(
                inv[[name_col, "PROCEDURE_NAME", "TASK_IMPACT_OBJECTS"]].rename(columns={name_col: "TASK_NAME"}),
                on="TASK_NAME",
                how="left",
            )
            runs["IMPACT_OBJECTS"] = [
                _clean_release_text(pd.Series([query_objects, task_objects]))
                for query_objects, task_objects in zip(runs.get("IMPACT_OBJECTS", ""), runs.get("TASK_IMPACT_OBJECTS", ""))
            ]
    return runs


def _build_procedure_release_sql(session, company: str, start: date, end: date, has_root_query_id: bool) -> str:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    root_expr = "COALESCE(q.root_query_id, q.query_id)" if has_root_query_id else "q.query_id"
    call_wh_size_expr = "warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    child_wh_size_expr = "q.warehouse_size AS warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    child_cloud_expr = (
        "q.credits_used_cloud_services AS credits_used_cloud_services"
        if "CREDITS_USED_CLOUD_SERVICES" in qh_cols else "0::FLOAT AS credits_used_cloud_services"
    )
    call_filters = get_global_filter_clause(
        date_col="",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    child_filters = get_global_filter_clause(
        date_col="",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    call_window = _release_window_predicate("start_time", start, end)
    child_window = _release_window_predicate("q.start_time", start, end)
    return f"""
        WITH calls AS (
            SELECT query_id AS root_query_id,
                   REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) AS procedure_name,
                   user_name,
                   role_name,
                   warehouse_name,
                   {call_wh_size_expr},
                   start_time,
                   SUBSTR(query_text, 1, 1000) AS call_text
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE query_type = 'CALL'
              AND {call_window}
              {call_filters}
        ),
        children AS (
            SELECT {root_expr} AS root_query_id,
                   q.query_id,
                   q.total_elapsed_time,
                   {child_cloud_expr},
                   {child_wh_size_expr}
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE {child_window}
              {child_filters}
        )
        SELECT c.procedure_name,
               c.root_query_id,
               c.user_name,
               c.role_name,
               c.warehouse_name,
               COALESCE(MAX(ch.warehouse_size), MAX(c.warehouse_size)) AS warehouse_size,
               c.start_time,
               c.call_text,
               COUNT(DISTINCT ch.query_id) AS downstream_query_count,
               SUM(COALESCE(ch.total_elapsed_time, 0)) / 1000 AS total_elapsed_sec,
               SUM(COALESCE(ch.credits_used_cloud_services, 0)) AS cloud_credits
        FROM calls c
        LEFT JOIN children ch ON c.root_query_id = ch.root_query_id
        GROUP BY c.procedure_name, c.root_query_id, c.user_name, c.role_name,
                 c.warehouse_name, c.start_time, c.call_text
        ORDER BY c.start_time DESC
        LIMIT 2000
    """


def _prepare_procedure_release_runs(runs: pd.DataFrame) -> pd.DataFrame:
    prepared = runs.copy() if runs is not None else pd.DataFrame()
    if prepared.empty:
        return prepared
    prepared.columns = [str(col).upper() for col in prepared.columns]
    prepared["TOTAL_ELAPSED_SEC"] = pd.to_numeric(prepared.get("TOTAL_ELAPSED_SEC", 0), errors="coerce").fillna(0)
    prepared["CLOUD_CREDITS"] = pd.to_numeric(prepared.get("CLOUD_CREDITS", 0), errors="coerce").fillna(0)
    prepared["EST_TOTAL_CREDITS"] = prepared.apply(_procedure_run_estimated_credits, axis=1)
    prepared["IMPACT_OBJECTS"] = prepared.get("CALL_TEXT", pd.Series([""] * len(prepared), index=prepared.index)).apply(
        _extract_object_candidates
    )
    return prepared


def _load_release_compare(
    session,
    company: str,
    before_start: date,
    before_end: date,
    after_start: date,
    after_end: date,
    runtime_pct_threshold: float,
    runtime_delta_sec_threshold: float,
    credit_pct_threshold: float,
    credit_delta_threshold: float,
) -> dict:
    task_inventory = load_task_inventory(session, company)

    def load_task_window(label: str, start: date, end: date) -> pd.DataFrame:
        history = run_query(
            build_task_history_sql(
                session,
                _release_window_predicate("scheduled_time", start, end),
                limit=2000,
                company=company,
            ),
            ttl_key=f"dba_release_{company}_{label}_{start}_{end}_task_history",
            tier="historical",
            section="DBA Control Room",
        )
        query_details = _empty_df()
        if not history.empty and "QUERY_ID" in history.columns:
            qids = history["QUERY_ID"].dropna().astype(str).tolist()
            query_sql = _query_detail_sql(session, qids)
            if query_sql:
                query_details = run_query(
                    query_sql,
                    ttl_key=f"dba_release_{company}_{label}_{start}_{end}_task_query_detail_{len(qids)}",
                    tier="historical",
                    section="DBA Control Room",
                )
        return _prepare_task_release_runs(task_inventory, history, query_details)

    has_root_query_id = _query_history_has_root_query_id(session)

    def load_proc_window(label: str, start: date, end: date) -> pd.DataFrame:
        runs = run_query(
            _build_procedure_release_sql(session, company, start, end, has_root_query_id),
            ttl_key=f"dba_release_{company}_{label}_{start}_{end}_procedure_runs_{has_root_query_id}",
            tier="historical",
            section="DBA Control Room",
        )
        return _prepare_procedure_release_runs(runs)

    task_before = load_task_window("before", before_start, before_end)
    task_after = load_task_window("after", after_start, after_end)
    proc_before = load_proc_window("before", before_start, before_end)
    proc_after = load_proc_window("after", after_start, after_end)

    return {
        "task_compare": _compare_release_windows(
            task_before,
            task_after,
            "TASK_NAME",
            runtime_pct_threshold=runtime_pct_threshold,
            runtime_delta_sec_threshold=runtime_delta_sec_threshold,
            credit_pct_threshold=credit_pct_threshold,
            credit_delta_threshold=credit_delta_threshold,
        ),
        "procedure_compare": _compare_release_windows(
            proc_before,
            proc_after,
            "PROCEDURE_NAME",
            runtime_pct_threshold=runtime_pct_threshold,
            runtime_delta_sec_threshold=runtime_delta_sec_threshold,
            credit_pct_threshold=credit_pct_threshold,
            credit_delta_threshold=credit_delta_threshold,
        ),
        "task_before": task_before,
        "task_after": task_after,
        "procedure_before": proc_before,
        "procedure_after": proc_after,
        "before_label": f"{before_start.isoformat()} to {before_end.isoformat()}",
        "after_label": f"{after_start.isoformat()} to {after_end.isoformat()}",
        "thresholds": {
            "runtime_pct_threshold": safe_float(runtime_pct_threshold),
            "runtime_delta_sec_threshold": safe_float(runtime_delta_sec_threshold),
            "credit_pct_threshold": safe_float(credit_pct_threshold),
            "credit_delta_threshold": safe_float(credit_delta_threshold),
        },
    }


def _build_release_compare_report(company: str, release_data: dict, credit_price: float) -> str:
    task_compare = release_data.get("task_compare", _empty_df())
    proc_compare = release_data.get("procedure_compare", _empty_df())
    before_label = release_data.get("before_label", "before")
    after_label = release_data.get("after_label", "after")
    thresholds = release_data.get("thresholds", {})

    task_regressions = task_compare[task_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])] if not task_compare.empty else pd.DataFrame()
    proc_regressions = proc_compare[proc_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])] if not proc_compare.empty else pd.DataFrame()
    total_credit_delta = (
        safe_float(task_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not task_compare.empty else 0)
        + safe_float(proc_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not proc_compare.empty else 0)
    )
    lines = [
        f"# OVERWATCH Release Compare - {company}",
        "",
        f"- Before window: {before_label}",
        f"- After window: {after_label}",
        (
            "- Thresholds: "
            f"runtime +{safe_float(thresholds.get('runtime_pct_threshold', 25)):,.0f}% "
            f"and +{safe_float(thresholds.get('runtime_delta_sec_threshold', 30)):,.0f}s; "
            f"credits +{safe_float(thresholds.get('credit_pct_threshold', 25)):,.0f}% "
            f"and +{safe_float(thresholds.get('credit_delta_threshold', 0)):,.4f} credits"
        ),
        f"- Task regressions: {len(task_regressions):,}",
        f"- Procedure regressions: {len(proc_regressions):,}",
        f"- Estimated credit delta: {format_credits(total_credit_delta)} (${credits_to_dollars(total_credit_delta, credit_price):,.2f})",
        "",
        "## Highest-Risk Task Changes",
    ]
    if task_regressions.empty:
        lines.append("- No material task runtime/cost/failure regressions detected.")
    else:
        for _, row in task_regressions.head(10).iterrows():
            lines.append(
                f"- {row.get('ENTITY', '')}: {row.get('SIGNAL', '')}; "
                f"after avg {safe_float(row.get('AVG_DURATION_SEC_AFTER')):,.1f}s; "
                f"procedure {row.get('PROCEDURE_NAME', '')}; impact {row.get('IMPACT_OBJECTS', '')}"
            )
    lines.extend(["", "## Highest-Risk Procedure Changes"])
    if proc_regressions.empty:
        lines.append("- No material stored procedure runtime/cost/failure regressions detected.")
    else:
        for _, row in proc_regressions.head(10).iterrows():
            lines.append(
                f"- {row.get('ENTITY', '')}: {row.get('SIGNAL', '')}; "
                f"after avg {safe_float(row.get('AVG_DURATION_SEC_AFTER')):,.1f}s; "
                f"credit delta {format_credits(row.get('EST_CREDITS_DELTA', 0))}"
            )
    return "\n".join(lines)


def _finalize_control_room_data(
    data: dict[str, pd.DataFrame],
    source_rows: list[dict],
    credit_price: float,
    cortex_budget_usd: float,
) -> dict[str, pd.DataFrame]:
    data["_loaded_at"] = pd.DataFrame({"LOADED_AT": [datetime.now().isoformat()]})
    data["_credit_price"] = pd.DataFrame({"CREDIT_PRICE": [credit_price]})
    data["_cortex_budget_usd"] = pd.DataFrame({"BUDGET_USD": [safe_float(cortex_budget_usd)]})
    data["_source_modes"] = pd.DataFrame(source_rows)
    return data


def _load_control_room(
    session,
    company: str,
    credit_price: float,
    lookback_hours: int,
    cortex_budget_usd: float,
    *,
    include_deep_evidence: bool = False,
    allow_live_fallback: bool = False,
) -> dict:
    wh_q = get_wh_filter_clause("q.warehouse_name", company)
    wh_m = get_wh_filter_clause("warehouse_name", company)
    db_q = get_db_filter_clause("q.database_name", company)
    user_q = get_user_filter_clause("q.user_name", company)
    global_q = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )

    data: dict[str, pd.DataFrame] = {}
    queries = {
        "summary": f"""
            SELECT
                COUNT(*) AS total_queries,
                SUM(CASE WHEN error_code IS NOT NULL
                           OR UPPER(execution_status) = 'FAILED_WITH_ERROR'
                         THEN 1 ELSE 0 END) AS failed_queries,
                SUM(CASE WHEN COALESCE(queued_overload_time, 0)
                            + COALESCE(queued_provisioning_time, 0)
                            + COALESCE(queued_repair_time, 0) > 0
                         THEN 1 ELSE 0 END) AS queued_queries,
                SUM(CASE WHEN COALESCE(bytes_spilled_to_remote_storage, 0) > 0
                         THEN 1 ELSE 0 END) AS remote_spill_queries,
                ROUND(AVG(total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                ROUND(APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95), 2) AS p95_elapsed_sec,
                COUNT(DISTINCT warehouse_name) AS active_warehouses,
                COUNT(DISTINCT user_name) AS active_users
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {global_q}
        """,
        "credits": f"""
            SELECT
                SUM(CASE WHEN start_time >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())
                         THEN credits_used ELSE 0 END) AS period_credits,
                SUM(CASE WHEN start_time >= DATEADD('hour', -{int(lookback_hours * 2)}, CURRENT_TIMESTAMP())
                          AND start_time < DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())
                         THEN credits_used ELSE 0 END) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('hour', -{int(lookback_hours * 2)}, CURRENT_TIMESTAMP())
              {wh_m}
        """,
        "cost_drivers": f"""
            WITH {build_metered_credit_cte(hours_back=lookback_hours, include_recent=True)}
            SELECT
                q.user_name,
                q.warehouse_name,
                COUNT(*) AS query_count,
                ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                ROUND(SUM(COALESCE(q.bytes_scanned, 0)) / POWER(1024, 3), 2) AS gb_scanned,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            WHERE q.start_time >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {global_q}
            GROUP BY q.user_name, q.warehouse_name
            HAVING SUM(COALESCE(pqc.metered_credits, 0)) > 0
            ORDER BY allocated_credits DESC
            LIMIT 10
        """,
        "warehouse_pressure": f"""
            SELECT
                q.warehouse_name,
                MAX(q.warehouse_size) AS warehouse_size,
                COUNT(*) AS total_queries,
                SUM(CASE WHEN COALESCE(q.queued_overload_time, 0)
                            + COALESCE(q.queued_provisioning_time, 0)
                            + COALESCE(q.queued_repair_time, 0) > 0
                         THEN 1 ELSE 0 END) AS queued_queries,
                SUM(CASE WHEN COALESCE(q.bytes_spilled_to_remote_storage, 0) > 0
                         THEN 1 ELSE 0 END) AS remote_spill_queries,
                ROUND(SUM(COALESCE(q.bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb,
                ROUND(APPROX_PERCENTILE(q.total_elapsed_time / 1000, 0.95), 2) AS p95_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {wh_q} {db_q} {user_q}
            GROUP BY q.warehouse_name
            HAVING queued_queries > 0 OR remote_spill_queries > 0 OR p95_elapsed_sec >= 60
            ORDER BY queued_queries DESC, remote_spill_gb DESC, p95_elapsed_sec DESC
            LIMIT 10
        """,
        "failed_queries": f"""
            SELECT
                q.query_id,
                q.user_name,
                q.role_name,
                q.warehouse_name,
                q.database_name,
                q.query_type,
                q.error_code,
                LEFT(q.error_message, 240) AS error_message,
                q.start_time
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())
              AND (q.error_code IS NOT NULL OR UPPER(q.execution_status) = 'FAILED_WITH_ERROR')
              {wh_q} {db_q} {user_q}
            ORDER BY q.start_time DESC
            LIMIT 25
        """,
        "object_changes": f"""
            SELECT
                q.start_time,
                q.user_name,
                q.role_name,
                q.query_type,
                q.database_name,
                q.schema_name,
                q.warehouse_name,
                LEFT(q.query_text, 220) AS query_preview
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())
              AND (
                    q.query_type ILIKE 'CREATE%'
                 OR q.query_type ILIKE 'ALTER%'
                 OR q.query_type ILIKE 'DROP%'
                 OR q.query_type ILIKE 'GRANT%'
                 OR q.query_type ILIKE 'REVOKE%'
              )
              {wh_q} {db_q} {user_q}
            ORDER BY q.start_time DESC
            LIMIT 25
        """,
        "failed_logins": f"""
            SELECT
                event_timestamp,
                user_name,
                client_ip,
                reported_client_type,
                error_code,
                error_message
            FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
            WHERE event_timestamp >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())
              AND is_success = 'NO'
              {get_user_filter_clause("user_name", company)}
            ORDER BY event_timestamp DESC
            LIMIT 25
        """,
    }

    mart_queries = {
        "summary": build_mart_control_room_summary_sql(lookback_hours, company),
        "credits": build_mart_control_room_credits_sql(lookback_hours, company),
        "cost_drivers": build_mart_control_room_cost_drivers_sql(lookback_hours, company),
        "warehouse_pressure": build_mart_control_room_warehouse_pressure_sql(lookback_hours, company),
        "failed_queries": build_mart_control_room_failed_queries_sql(lookback_hours, company),
        "object_changes": build_mart_control_room_object_changes_sql(lookback_hours, company),
        "failed_logins": build_mart_control_room_failed_logins_sql(lookback_hours, company),
    }
    source_rows: list[dict] = []
    for key, sql in queries.items():
        try:
            try:
                data[key] = run_query(
                    mart_queries[key],
                    ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_{key}",
                    tier="historical",
                    section="DBA Control Room",
                )
                source_rows.append({"Source": key, "Mode": "OVERWATCH mart"})
            except Exception as mart_exc:
                if not allow_live_fallback:
                    data[key] = _empty_df()
                    data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                    source_rows.append({
                        "Source": key,
                        "Mode": "Mart unavailable",
                        "Message": "Live fallback skipped to keep DBA Control Room responsive.",
                    })
                    continue
                data[key] = run_query(
                    sql,
                    ttl_key=f"dba_control_room_live_{company}_{lookback_hours}_{key}",
                    tier="recent" if lookback_hours <= 24 else "historical",
                    section="DBA Control Room",
                )
                source_rows.append({
                    "Source": key,
                    "Mode": "Live fallback",
                    "Message": format_snowflake_error(mart_exc),
                })
        except Exception as exc:
            data[key] = _empty_df()
            data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        try:
            data["task_failures"] = run_query(
                build_mart_control_room_task_failures_sql(lookback_hours, company),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_failures",
                tier="historical",
                section="DBA Control Room",
            )
            source_rows.append({"Source": "task_failures", "Mode": "OVERWATCH mart"})
        except Exception as mart_exc:
            if not allow_live_fallback:
                data["task_failures"] = _empty_df()
                data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                source_rows.append({
                    "Source": "task_failures",
                    "Mode": "Mart unavailable",
                    "Message": "Live fallback skipped to keep DBA Control Room responsive.",
                })
            else:
                data["task_failures"] = run_query(
                    build_task_failure_summary_sql(
                        session,
                        f"scheduled_time >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())",
                        limit=10,
                        company=company,
                    ),
                    ttl_key=f"dba_control_room_live_{company}_{lookback_hours}_task_failures",
                    tier="recent",
                    section="DBA Control Room",
                )
                source_rows.append({
                    "Source": "task_failures",
                    "Mode": "Live fallback",
                    "Message": format_snowflake_error(mart_exc),
                })
    except Exception as exc:
        data["task_failures"] = _empty_df()
        data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    if not include_deep_evidence:
        data["task_sla_cost"] = _empty_df()
        data["task_latest_runs"] = _empty_df()
        data["procedure_sla_cost"] = _empty_df()
        data["procedure_latest_runs"] = _empty_df()
        data["cortex_summary"] = _empty_df()
        data["cortex_exceptions"] = _empty_df()
        source_rows.extend([
            {
                "Source": "task_sla_history",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Workload Operations for task run evidence.",
            },
            {
                "Source": "procedure_sla",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Workload Operations for procedure SLA/cost evidence.",
            },
            {
                "Source": "cortex_cost",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Cost & Contract for Cortex cost evidence.",
            },
        ])
        try:
            data["action_queue"] = load_action_queue(session, limit=25)
        except Exception as exc:
            data["action_queue"] = _empty_df()
            data["action_queue_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
        return _finalize_control_room_data(data, source_rows, credit_price, cortex_budget_usd)

    try:
        task_inventory = load_task_inventory(session, company)
        task_history_source = "OVERWATCH mart"
        try:
            task_history = run_query(
                build_mart_task_history_sql(max(1, int((lookback_hours + 23) / 24)), company=company, limit=1000),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_sla_history",
                tier="historical",
                section="DBA Control Room",
            )
        except Exception as mart_exc:
            task_history_source = "Live fallback"
            task_history = run_query(
                build_task_history_sql(
                    session,
                    f"scheduled_time >= DATEADD('hour', -{int(lookback_hours)}, CURRENT_TIMESTAMP())",
                    limit=1000,
                    company=company,
                ),
                ttl_key=f"dba_control_room_live_{company}_{lookback_hours}_task_sla_history",
                tier="recent",
                section="DBA Control Room",
            )
            source_rows.append({
                "Source": "task_sla_history",
                "Mode": task_history_source,
                "Message": format_snowflake_error(mart_exc),
            })
        if task_history_source == "OVERWATCH mart":
            source_rows.append({"Source": "task_sla_history", "Mode": task_history_source})
        task_query_details = _empty_df()
        if not task_history.empty and "QUERY_ID" in task_history.columns:
            qids = task_history["QUERY_ID"].dropna().astype(str).tolist()
            try:
                query_sql = build_mart_query_detail_recent_sql(qids)
                if query_sql:
                    task_query_details = run_query(
                        query_sql,
                        ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_query_detail_{len(qids)}",
                        tier="historical",
                        section="DBA Control Room",
                    )
                    source_rows.append({"Source": "task_query_detail", "Mode": "OVERWATCH mart"})
            except Exception as mart_exc:
                query_sql = _query_detail_sql(session, qids)
                if query_sql:
                    task_query_details = run_query(
                        query_sql,
                        ttl_key=f"dba_control_room_live_{company}_{lookback_hours}_task_query_detail_{len(qids)}",
                        tier="standard",
                        section="DBA Control Room",
                    )
                source_rows.append({
                    "Source": "task_query_detail",
                    "Mode": "Live fallback",
                    "Message": format_snowflake_error(mart_exc),
                })
        _, task_ops_exceptions, task_latest = _build_task_ops_frames(task_inventory, task_history, task_query_details)
        data["task_sla_cost"] = task_ops_exceptions[
            task_ops_exceptions.get("SIGNAL", pd.Series(dtype=str)).isin([
                "Long Running / SLA Risk",
                "Cost Drift / Release Regression",
            ])
        ].copy() if not task_ops_exceptions.empty else _empty_df()
        data["task_latest_runs"] = task_latest
    except Exception as exc:
        data["task_sla_cost"] = _empty_df()
        data["task_latest_runs"] = _empty_df()
        data["task_sla_cost_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        try:
            proc_runs = run_query(
                build_mart_procedure_sla_sql(max(1, int((lookback_hours + 23) / 24)), company=company),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_procedure_sla",
                tier="historical",
                section="DBA Control Room",
            )
            source_rows.append({"Source": "procedure_sla", "Mode": "OVERWATCH mart"})
        except Exception as mart_exc:
            has_root_query_id = _query_history_has_root_query_id(session)
            proc_runs = run_query(
                _build_procedure_sla_sql(session, max(1, int(lookback_hours / 24)), has_root_query_id),
                ttl_key=f"dba_control_room_live_{company}_{lookback_hours}_procedure_sla_{has_root_query_id}",
                tier="standard",
                section="DBA Control Room",
            )
            source_rows.append({
                "Source": "procedure_sla",
                "Mode": "Live fallback",
                "Message": format_snowflake_error(mart_exc),
            })
        _, proc_exceptions, proc_latest = _build_procedure_sla_frames(proc_runs)
        data["procedure_sla_cost"] = proc_exceptions
        data["procedure_latest_runs"] = proc_latest
    except Exception as exc:
        data["procedure_sla_cost"] = _empty_df()
        data["procedure_latest_runs"] = _empty_df()
        data["procedure_sla_cost_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        data["action_queue"] = load_action_queue(session, limit=100)
    except Exception as exc:
        data["action_queue"] = _empty_df()
        data["action_queue_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        cortex_summary_sql, cortex_exceptions_sql = _build_cortex_control_sql(30, cortex_budget_usd)
        data["cortex_summary"] = run_query(
            cortex_summary_sql,
            ttl_key=f"dba_control_room_{company}_cortex_summary_{cortex_budget_usd}",
            tier="historical",
            section="DBA Control Room",
        )
        data["cortex_exceptions"] = run_query(
            cortex_exceptions_sql,
            ttl_key=f"dba_control_room_{company}_cortex_exceptions_{cortex_budget_usd}",
            tier="historical",
            section="DBA Control Room",
        )
    except Exception as exc:
        data["cortex_summary"] = _empty_df()
        data["cortex_exceptions"] = _empty_df()
        cortex_error = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
        data["cortex_summary_error"] = cortex_error
        data["cortex_exceptions_error"] = cortex_error

    data["_loaded_at"] = pd.DataFrame({"LOADED_AT": [datetime.now().isoformat()]})
    data["_credit_price"] = pd.DataFrame({"CREDIT_PRICE": [credit_price]})
    data["_cortex_budget_usd"] = pd.DataFrame({"BUDGET_USD": [safe_float(cortex_budget_usd)]})
    data["_source_modes"] = pd.DataFrame(source_rows)
    return data


def _severity_rows(data: dict, credit_price: float) -> pd.DataFrame:
    summary = data.get("summary", _empty_df())
    credits = data.get("credits", _empty_df())
    wh = data.get("warehouse_pressure", _empty_df())
    failed = data.get("failed_queries", _empty_df())
    tasks = data.get("task_failures", _empty_df())
    task_sla_cost = data.get("task_sla_cost", _empty_df())
    procedure_sla_cost = data.get("procedure_sla_cost", _empty_df())
    cortex_summary = data.get("cortex_summary", _empty_df())
    cortex_exceptions = data.get("cortex_exceptions", _empty_df())
    logins = data.get("failed_logins", _empty_df())
    changes = data.get("object_changes", _empty_df())
    queue = data.get("action_queue", _empty_df())

    row = summary.iloc[0] if not summary.empty else {}
    cr = credits.iloc[0] if not credits.empty else {}
    period_credits = safe_float(cr.get("PERIOD_CREDITS", 0))
    prior_credits = safe_float(cr.get("PRIOR_CREDITS", 0))
    credit_delta = ((period_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0

    rows = []
    failed_queries = safe_int(row.get("FAILED_QUERIES", 0))
    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    spill_queries = safe_int(row.get("REMOTE_SPILL_QUERIES", 0))
    p95 = safe_float(row.get("P95_ELAPSED_SEC", 0))

    if failed_queries:
        rows.append({
            "Severity": "High" if failed_queries >= 10 else "Medium",
            "Signal": "Query failures",
            "Evidence": f"{failed_queries:,} failed queries in lookback",
            "Action": "Review failed SQL and recurring error patterns.",
            "Route": "Workload Operations",
            "Workflow": "Query diagnosis",
        })
    if queued_queries or not wh.empty:
        rows.append({
            "Severity": "High" if queued_queries >= 20 else "Medium",
            "Signal": "Queue or warehouse pressure",
            "Evidence": f"{queued_queries:,} queued queries; {len(wh):,} pressured warehouses",
            "Action": "Check warehouse sizing, clustering, and concurrency pressure.",
            "Route": "Warehouse Health",
            "Workflow": "",
        })
    if spill_queries:
        rows.append({
            "Severity": "High" if spill_queries >= 10 else "Medium",
            "Signal": "Remote spill",
            "Evidence": f"{spill_queries:,} queries spilled to remote storage",
            "Action": "Inspect spilling queries before resizing.",
            "Route": "Warehouse Health",
            "Workflow": "",
        })
    if p95 >= 120:
        rows.append({
            "Severity": "Medium",
            "Signal": "High p95 duration",
            "Evidence": f"p95 elapsed {p95:,.0f}s",
            "Action": "Investigate slow-query plan and operator stats.",
            "Route": "Workload Operations",
            "Workflow": "Query diagnosis",
        })
    if credit_delta >= 25:
        rows.append({
            "Severity": "High" if credit_delta >= 60 else "Medium",
            "Signal": "Credit spike",
            "Evidence": f"{credit_delta:+.1f}% vs prior window; est. ${credits_to_dollars(period_credits, credit_price):,.0f}",
            "Action": "Identify top users, warehouses, tasks, and query patterns.",
            "Route": "Cost & Contract",
            "Workflow": "Explain bill / attribution / contract",
        })
    if not tasks.empty:
        rows.append({
            "Severity": "High",
            "Signal": "Task failures",
            "Evidence": f"{len(tasks):,} failed task groups",
            "Action": "Review task history, retry logic, and downstream load impact.",
            "Route": "Workload Operations",
            "Workflow": "Task graphs",
        })
    if not task_sla_cost.empty:
        signals = task_sla_cost.get("SIGNAL", pd.Series(dtype=str)).astype(str)
        sla_count = int((signals == "Long Running / SLA Risk").sum())
        cost_count = int((signals == "Cost Drift / Release Regression").sum())
        rows.append({
            "Severity": "High" if cost_count or sla_count >= 3 else "Medium",
            "Signal": "Task SLA or cost regression",
            "Evidence": f"{sla_count:,} runtime breach(es); {cost_count:,} cost regression candidate(s)",
            "Action": "Compare current task graph runs to recent baseline and inspect release-related procedure/query changes.",
            "Route": "Workload Operations",
            "Workflow": "Task graphs",
        })
    if not procedure_sla_cost.empty:
        signals = procedure_sla_cost.get("SIGNAL", pd.Series(dtype=str)).astype(str)
        runtime_count = int((signals == "Procedure Runtime SLA Breach").sum())
        cost_count = int((signals == "Procedure Cost Regression").sum())
        rows.append({
            "Severity": "High" if cost_count or runtime_count >= 3 else "Medium",
            "Signal": "Stored procedure release regression",
            "Evidence": f"{runtime_count:,} runtime breach(es); {cost_count:,} cost regression candidate(s)",
            "Action": "Review procedures whose latest CALL duration or estimated credits jumped after the release.",
            "Route": "Workload Operations",
            "Workflow": "Stored procedures",
        })
    if not cortex_summary.empty:
        cortex_budget = safe_float(_scalar_frame_value(data, "_cortex_budget_usd", "BUDGET_USD", 0))
        cortex_row = cortex_summary.iloc[0]
        projected_cost = safe_float(cortex_row.get("PROJECTED_30D_COST", 0))
        score = _cortex_cost_score(
            projected_cost=projected_cost,
            budget_usd=cortex_budget,
            spike_users=safe_int(cortex_row.get("HEAVY_USERS", 0)),
            active_users=safe_int(cortex_row.get("ACTIVE_USERS", 0)),
        )
        if projected_cost > cortex_budget or score < 78 or not cortex_exceptions.empty:
            rows.append({
                "Severity": "High" if projected_cost > cortex_budget or score < 65 else "Medium",
                "Signal": "Cortex / AI cost risk",
                "Evidence": (
                    f"Projected 30-day Cortex cost ${projected_cost:,.0f} vs ${cortex_budget:,.0f} budget; "
                    f"{len(cortex_exceptions):,} user/source exception(s); score {score} ({_cortex_cost_rating(score)})"
                ),
                "Action": "Review Cortex users, source split, cost-per-request spikes, and daily credit guardrails.",
                "Route": "Cost & Contract",
                "Workflow": "AI and Cortex spend",
            })
    if not logins.empty:
        rows.append({
            "Severity": "Medium",
            "Signal": "Failed logins",
            "Evidence": f"{len(logins):,} recent failed login records",
            "Action": "Review source IPs, user posture, MFA, and client versions.",
            "Route": "Security Posture",
            "Workflow": "Access posture",
        })
    if not changes.empty:
        rows.append({
            "Severity": "Medium",
            "Signal": "Object or grant changes",
            "Evidence": f"{len(changes):,} recent DDL/access changes",
            "Action": "Validate expected change windows and ownership.",
            "Route": "Change & Drift",
            "Workflow": "Object and access changes",
        })
    if not queue.empty:
        open_queue = queue[~queue.get("STATUS", "").isin(["Fixed", "Ignored"])] if "STATUS" in queue.columns else queue
        if not open_queue.empty:
            rows.append({
                "Severity": "Medium",
                "Signal": "Open action queue",
                "Evidence": f"{len(open_queue):,} open recommendations",
                "Action": "Assign owners and move items toward fixed/ignored.",
                "Route": "Cost & Contract",
                "Workflow": "Recommendations and action queue",
            })

    return pd.DataFrame(rows)


def _priority_exceptions(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return _empty_df()
    severity_rank = {"High": 0, "Medium": 1, "Low": 2}
    view = exceptions.copy()
    view["_RANK"] = view.get("Severity", pd.Series(dtype=str)).map(severity_rank).fillna(3)
    return view.sort_values(["_RANK", "Signal"]).drop(columns=["_RANK"], errors="ignore")


def _control_room_score(
    exceptions: pd.DataFrame,
    row: pd.Series | dict,
    credit_delta: float,
    regression_count: int,
    cortex_exception_count: int,
) -> int:
    if exceptions is None or exceptions.empty:
        high_count = medium_count = 0
    else:
        severities = exceptions.get("Severity", pd.Series(dtype=str)).astype(str)
        high_count = int((severities == "High").sum())
        medium_count = int((severities == "Medium").sum())
    failed_queries = safe_int(row.get("FAILED_QUERIES", 0))
    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    remote_spill = safe_int(row.get("REMOTE_SPILL_QUERIES", 0))
    penalty = (
        high_count * 12
        + medium_count * 6
        + min(failed_queries / 10, 10)
        + min(queued_queries / 10, 8)
        + min(remote_spill / 20, 8)
        + min(max(credit_delta, 0) / 5, 10)
        + min(safe_int(regression_count) * 3, 12)
        + min(safe_int(cortex_exception_count) * 2, 10)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _control_room_rating(score: int) -> str:
    if score >= 92:
        return "Clear"
    if score >= 82:
        return "Watch"
    if score >= 70:
        return "Degraded"
    return "War Room"


def _render_watch_floor(
    data: dict,
    exceptions: pd.DataFrame,
    row: pd.Series | dict,
    period_credits: float,
    credit_delta: float,
    credit_price: float,
    regression_count: int,
    cortex_exception_count: int,
) -> None:
    score = _control_room_score(exceptions, row, credit_delta, regression_count, cortex_exception_count)
    rating = _control_room_rating(score)
    priority = _priority_exceptions(exceptions).head(3)
    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 2.2])
    c1.metric("Readiness", f"{score}/100", rating)
    c2.metric("Critical Moves", f"{len(priority):,}", delta_color="inverse")
    c3.metric("Cost Window", f"${credits_to_dollars(period_credits, credit_price):,.0f}", f"{credit_delta:+.1f}%", delta_color="inverse")
    with c4:
        if priority.empty:
            st.success("Watch floor is clear. Use Release Compare or Source Health if you are validating a recent deployment.")
        else:
            first = priority.iloc[0]
            st.warning(
                f"First move: {first.get('Signal', 'Exception')} -> {first.get('Action', 'Review the routed workflow.')}"
            )

    st.markdown("**DBA Watch Floor**")
    if priority.empty:
        st.caption("No immediate exception cards. Keep this page as the morning triage and evidence export point.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        route = str(item.get("Route", "") or "")
        workflow = str(item.get("Workflow", "") or "")
        with cols[idx]:
            st.markdown(f"**{item.get('Severity', 'Signal')}: {item.get('Signal', '')}**")
            st.caption(str(item.get("Evidence", "")))
            st.write(str(item.get("Action", "")))
            if route and st.button(f"Open {route}", key=f"dba_watch_floor_{idx}_{route}", use_container_width=True):
                _jump(route, workflow=workflow)


def _render_route_buttons(exceptions: pd.DataFrame) -> None:
    if exceptions.empty or "Route" not in exceptions.columns:
        return
    route_rows = (
        exceptions[["Route", "Workflow"]]
        .dropna(subset=["Route"])
        .drop_duplicates()
        .head(5)
        .to_dict("records")
    )
    cols = st.columns(min(max(len(route_rows), 1), 5))
    for idx, item in enumerate(route_rows):
        route = str(item.get("Route", ""))
        workflow = str(item.get("Workflow", "") or "")
        with cols[idx % len(cols)]:
            if st.button(route, key=f"dba_control_route_{route}", use_container_width=True):
                _jump(route, workflow=workflow)


def _build_report(data: dict, exceptions: pd.DataFrame, company: str, credit_price: float, lookback_hours: int) -> str:
    summary = data.get("summary", _empty_df())
    credits = data.get("credits", _empty_df())
    task_sla_cost = data.get("task_sla_cost", _empty_df())
    procedure_sla_cost = data.get("procedure_sla_cost", _empty_df())
    cortex_summary = data.get("cortex_summary", _empty_df())
    cortex_exceptions = data.get("cortex_exceptions", _empty_df())
    row = summary.iloc[0] if not summary.empty else {}
    cr = credits.iloc[0] if not credits.empty else {}
    period_credits = safe_float(cr.get("PERIOD_CREDITS", 0))
    prior_credits = safe_float(cr.get("PRIOR_CREDITS", 0))
    credit_delta = ((period_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0
    cortex_budget = safe_float(_scalar_frame_value(data, "_cortex_budget_usd", "BUDGET_USD", 0))
    cortex_projected = safe_float(cortex_summary.iloc[0].get("PROJECTED_30D_COST", 0)) if not cortex_summary.empty else 0

    lines = [
        "# OVERWATCH DBA Control Room Brief",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Company view: {company}",
        f"Lookback: {lookback_hours} hours",
        "",
        "## Operating Summary",
        f"- Queries reviewed: {safe_int(row.get('TOTAL_QUERIES', 0)):,}",
        f"- Failed queries: {safe_int(row.get('FAILED_QUERIES', 0)):,}",
        f"- Queued queries: {safe_int(row.get('QUEUED_QUERIES', 0)):,}",
        f"- Remote spill queries: {safe_int(row.get('REMOTE_SPILL_QUERIES', 0)):,}",
        f"- p95 elapsed seconds: {safe_float(row.get('P95_ELAPSED_SEC', 0)):,.2f}",
        f"- Task SLA/cost regression candidates: {0 if task_sla_cost.empty else len(task_sla_cost):,}",
        f"- Stored procedure release-regression candidates: {0 if procedure_sla_cost.empty else len(procedure_sla_cost):,}",
        f"- Cortex projected 30-day cost: ${cortex_projected:,.2f} vs ${cortex_budget:,.2f} budget",
        f"- Cortex user/source exceptions: {0 if cortex_exceptions.empty else len(cortex_exceptions):,}",
        f"- Credits: {format_credits(period_credits)} (${credits_to_dollars(period_credits, credit_price):,.2f})",
        f"- Credit change vs prior window: {credit_delta:+.1f}%",
        "",
        "## Exceptions",
    ]
    if exceptions.empty:
        lines.append("- No major exceptions detected by the control room rules.")
    else:
        for _, item in exceptions.iterrows():
            lines.append(
                f"- {item['Severity']}: {item['Signal']} - {item['Evidence']} "
                f"Action: {item['Action']} Route: {item['Route']}."
            )
    if not task_sla_cost.empty:
        lines.extend(["", "## Task SLA / Cost Regression Candidates"])
        for _, item in task_sla_cost.head(10).iterrows():
            lines.append(
                f"- {item.get('SEVERITY', 'Medium')}: {item.get('TASK_NAME', '')} "
                f"{item.get('SIGNAL', '')} - {item.get('DETAIL', '')} "
                f"Procedure: {item.get('PROCEDURE_NAME', '')}. Impact hints: {item.get('IMPACT_OBJECTS', '')}."
            )
    if not procedure_sla_cost.empty:
        lines.extend(["", "## Stored Procedure Release Regression Candidates"])
        for _, item in procedure_sla_cost.head(10).iterrows():
            lines.append(
                f"- {item.get('SEVERITY', 'Medium')}: {item.get('PROCEDURE_NAME', '')} "
                f"{item.get('SIGNAL', '')} - latest {safe_float(item.get('LATEST_ELAPSED_SEC')):,.0f}s "
                f"vs avg {safe_float(item.get('AVG_ELAPSED_SEC')):,.0f}s; "
                f"estimated credits {safe_float(item.get('EST_TOTAL_CREDITS')):,.4f}."
            )
    if not cortex_exceptions.empty:
        lines.extend(["", "## Cortex Cost Control Candidates"])
        for _, item in cortex_exceptions.head(10).iterrows():
            lines.append(
                f"- {item.get('SEVERITY', 'Medium')}: {item.get('USER_NAME', '')} "
                f"{item.get('SOURCE', '')} {item.get('SIGNAL', '')}; "
                f"projected ${safe_float(item.get('PROJECTED_30D_COST')):,.2f}; "
                f"credits/request {safe_float(item.get('CREDITS_PER_REQUEST')):,.6f}."
            )
    lines.extend([
        "",
        "## Metric Notes",
        "- Credit by query is allocated from warehouse-hour metering and should be treated as estimated.",
        "- ACCOUNT_USAGE metrics can lag up to roughly 45 minutes.",
        "- Security and grant signals are scoped by the selected company naming rules where Snowflake metadata allows it.",
    ])
    return "\n".join(lines)


def render() -> None:
    session = get_session()
    company = st.session_state.get("active_company", "ALFA")
    credit_price = safe_float(st.session_state.get("credit_price", 3.0)) or 3.0

    st.header("DBA Control Room")
    st.caption(
        "One place to triage Snowflake cost, reliability, security, task, warehouse, and change exceptions. "
        "Use this page first, then drill into specialist tools only when the signal deserves it."
    )
    render_operator_briefing(
        [
            ("First move", "Use the fast snapshot for cheap triage."),
            ("Evidence", "Load details only when a signal needs proof."),
            ("Control", "Route to the specialist workflow before taking action."),
            ("Output", "Export a DBA brief for leaders without giving them the app."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.info(
            "Exceptions-only mode is on. This page is prioritizing actionable issues and report-ready evidence "
            "over broad exploratory charts."
        )

    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    with c1:
        lookback_hours = st.selectbox("Lookback", [12, 24, 48, 168], index=1, format_func=lambda h: f"{h} hours")
    with c2:
        cortex_budget_usd = st.number_input(
            "Cortex monthly budget ($)",
            min_value=1.0,
            value=float(st.session_state.get("cortex_control_budget_usd", 5000.0)),
            step=250.0,
            key="dba_control_room_cortex_budget_usd",
        )
    with c3:
        st.metric("Company Scope", company)
    with c4:
        st.info(
            f"{freshness_note('ACCOUNT_USAGE')} "
            f"Cost confidence: {metric_confidence_label('allocated')}. "
            "Use this as triage, then validate high-impact actions in the drilldown page."
        )

    snapshot_result = load_latest_control_room_mart(company, max_age_hours=6)
    if snapshot_result.available and not snapshot_result.data.empty:
        snapshot = snapshot_result.data.copy()
        st.caption(f"Fast snapshot available from {snapshot_result.source}. Use it for cheap triage; load detail only for investigation.")
        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Snapshot Health", f"{safe_float(snapshot['HEALTH_SCORE'].min()):.0f}/100")
        s2.metric("Failed Queries 24h", f"{safe_int(snapshot['FAILED_QUERIES_24H'].sum()):,}", delta_color="inverse")
        s3.metric("Failed Tasks 24h", f"{safe_int(snapshot['FAILED_TASKS_24H'].sum()):,}", delta_color="inverse")
        s4.metric("Credits 24h", format_credits(snapshot["CREDITS_24H"].sum()))
        s5.metric("Cortex 7d", f"${safe_float(snapshot['CORTEX_COST_7D_USD'].sum()):,.0f}", delta_color="inverse")
        if st.button("Use Fast Snapshot", key="dba_control_room_use_snapshot"):
            st.session_state["dba_control_room_data"] = _control_room_snapshot_to_data(snapshot)
            st.session_state["dba_control_room_company"] = company
            st.session_state["dba_control_room_lookback"] = 24
            st.session_state["dba_control_room_source_mode"] = "OVERWATCH mart snapshot"
            st.rerun()
    elif not snapshot_result.available:
        st.caption("Fast mart snapshot unavailable. Install/run OVERWATCH_MART_SETUP.sql to enable cheap control-room triage.")

    include_deep_evidence = st.checkbox(
        "Include deep task/procedure/Cortex evidence",
        value=False,
        key="dba_control_room_include_deep_evidence",
        help=(
            "Default off keeps this page fast. Turn on only when you need task run baselines, "
            "stored procedure SLA/cost evidence, and Cortex exception detail in this page."
        ),
    )
    allow_live_fallback = st.checkbox(
        "Allow live ACCOUNT_USAGE fallback queries",
        value=False,
        key="dba_control_room_allow_live_fallback",
        help=(
            "Default off prevents surprise long compiles. Turn on only when the OVERWATCH mart is missing "
            "or stale and you accept slower direct ACCOUNT_USAGE scans."
        ),
    )
    load_label = "Load DBA Control Room Deep Evidence" if include_deep_evidence else "Load DBA Control Room Triage"
    if st.button(load_label, key="dba_control_room_load", type="primary"):
        with st.spinner("Loading exception signals..."):
            st.session_state["dba_control_room_data"] = _load_control_room(
                session,
                company,
                credit_price,
                int(lookback_hours),
                safe_float(cortex_budget_usd),
                include_deep_evidence=bool(include_deep_evidence),
                allow_live_fallback=bool(allow_live_fallback),
            )
            st.session_state["dba_control_room_company"] = company
            st.session_state["dba_control_room_lookback"] = int(lookback_hours)
            st.session_state["dba_control_room_source_mode"] = (
                "Deep evidence live + fallback queries"
                if include_deep_evidence
                else "Fast triage mart queries"
            )
            st.session_state["dba_control_room_live_fallback"] = bool(allow_live_fallback)

    data = st.session_state.get("dba_control_room_data", {})
    if not data:
        st.warning("Use the fast mart snapshot or load detail to see today's DBA exceptions and report-ready evidence.")
        st.markdown("**Designed workflow**")
        st.write("Fast snapshot -> investigate exception -> assign action -> export leadership evidence.")
        return

    loaded_company = st.session_state.get("dba_control_room_company", company)
    loaded_lookback = st.session_state.get("dba_control_room_lookback", lookback_hours)
    if loaded_company != company:
        st.warning("Company selection changed after this control-room load. Reload before taking action.")
    source_mode = st.session_state.get("dba_control_room_source_mode", "Detailed live + fallback queries")
    if source_mode == "OVERWATCH mart snapshot":
        st.info("Showing fast mart snapshot. Deep evidence tabs may be sparse until you load detail.")
    elif source_mode == "Fast triage mart queries":
        st.info("Showing fast triage. Deep task, procedure, and Cortex evidence is deferred to keep this page responsive.")
        if not st.session_state.get("dba_control_room_live_fallback"):
            st.caption("Live ACCOUNT_USAGE fallbacks were skipped. Missing mart panels show as unavailable instead of running slow scans.")

    exceptions = _severity_rows(data, credit_price)
    summary = data.get("summary", _empty_df())
    credits = data.get("credits", _empty_df())
    row = summary.iloc[0] if not summary.empty else {}
    cr = credits.iloc[0] if not credits.empty else {}
    period_credits = safe_float(cr.get("PERIOD_CREDITS", 0))
    prior_credits = safe_float(cr.get("PRIOR_CREDITS", 0))
    credit_delta = ((period_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0

    task_sla_cost = data.get("task_sla_cost", _empty_df())
    procedure_sla_cost = data.get("procedure_sla_cost", _empty_df())
    regression_count = (0 if task_sla_cost.empty else len(task_sla_cost)) + (0 if procedure_sla_cost.empty else len(procedure_sla_cost))
    cortex_summary = data.get("cortex_summary", _empty_df())
    cortex_exceptions = data.get("cortex_exceptions", _empty_df())
    cortex_projected = safe_float(cortex_summary.iloc[0].get("PROJECTED_30D_COST", 0)) if not cortex_summary.empty else 0

    m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
    m1.metric("Open Exceptions", len(exceptions))
    m2.metric("Failed Queries", f"{safe_int(row.get('FAILED_QUERIES', 0)):,}", delta_color="inverse")
    m3.metric("Queued Queries", f"{safe_int(row.get('QUEUED_QUERIES', 0)):,}", delta_color="inverse")
    m4.metric("p95 Runtime", f"{safe_float(row.get('P95_ELAPSED_SEC', 0)):,.0f}s")
    m5.metric("Credits", format_credits(period_credits), f"{credit_delta:+.1f}%", delta_color="inverse")
    m6.metric("Est. Cost", f"${credits_to_dollars(period_credits, credit_price):,.0f}")
    m7.metric("SLA/Cost Drift", f"{regression_count:,}", delta_color="inverse")
    m8.metric("Cortex Risk", f"{0 if cortex_exceptions.empty else len(cortex_exceptions):,}", f"${cortex_projected:,.0f}/30d", delta_color="inverse")

    _render_watch_floor(
        data,
        exceptions,
        row,
        period_credits,
        credit_delta,
        credit_price,
        regression_count,
        0 if cortex_exceptions.empty else len(cortex_exceptions),
    )
    st.divider()

    tab_triage, tab_routes, tab_release, tab_evidence, tab_sources = st.tabs([
        "Triage", "Drill Routes", "Release Compare", "Executive Evidence", "Source Health"
    ])

    with tab_triage:
        if exceptions.empty:
            st.success("No major exceptions detected by the DBA Control Room rules.")
        else:
            st.subheader("Priority Exceptions")
            render_priority_dataframe(
                exceptions,
                title="Control-room exceptions to work first",
                priority_columns=[
                    "SEVERITY", "DOMAIN", "SIGNAL", "ENTITY", "DETAIL",
                    "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["SEVERITY", "DOMAIN", "ENTITY"],
                ascending=[True, True, True],
                raw_label="All control-room exceptions",
                height=260,
            )
            _render_route_buttons(exceptions)

        st.divider()
        left, right = st.columns(2)
        with left:
            st.subheader("Top Cost Drivers")
            cost_df = data.get("cost_drivers", _empty_df())
            if not cost_df.empty:
                cost_df = cost_df.copy()
                cost_df["EST_COST"] = cost_df["ALLOCATED_CREDITS"].apply(
                    lambda v: credits_to_dollars(v, credit_price)
                )
                render_priority_dataframe(
                    cost_df,
                    title="Largest cost drivers",
                    priority_columns=[
                        "WAREHOUSE_NAME", "USER_NAME", "ROLE_NAME",
                        "DATABASE_NAME", "ALLOCATED_CREDITS", "EST_COST",
                        "QUERY_COUNT", "AVG_ELAPSED_SEC",
                    ],
                    sort_by=["ALLOCATED_CREDITS", "EST_COST"],
                    ascending=[False, False],
                    raw_label="All cost-driver rows",
                    height=280,
                )
                download_csv(cost_df, "dba_control_room_cost_drivers.csv")
            else:
                st.info("No cost-driver rows found in the loaded lookback.")
        with right:
            st.subheader("Warehouse Pressure")
            wh_df = data.get("warehouse_pressure", _empty_df())
            if not wh_df.empty:
                render_priority_dataframe(
                    wh_df,
                    title="Warehouses under pressure",
                    priority_columns=[
                        "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "QUEUED_QUERIES",
                        "FAILED_QUERIES", "P95_ELAPSED_SEC", "REMOTE_SPILL_GB",
                        "QUERY_COUNT", "ALLOCATED_CREDITS",
                    ],
                    sort_by=["QUEUED_QUERIES", "FAILED_QUERIES", "P95_ELAPSED_SEC"],
                    ascending=[False, False, False],
                    raw_label="All warehouse-pressure rows",
                    height=280,
                )
                sel_wh = st.selectbox(
                    "Open warehouse",
                    [""] + wh_df["WAREHOUSE_NAME"].dropna().astype(str).tolist(),
                    key="dba_control_room_wh_select",
                )
                if sel_wh and st.button("Open Warehouse Health", key="dba_control_room_open_wh"):
                    _jump("Warehouse Health", warehouse=sel_wh)
            else:
                st.success("No warehouse pressure detected by the control-room thresholds.")

    with tab_routes:
        r1, r2, r3 = st.columns(3)
        with r1:
            st.subheader("Reliability")
            st.write("Failed queries, task failures, queued workload, and slow p95 runtime.")
            reliability_routes = [
                ("Query Diagnosis", "Query diagnosis"),
                ("Task Graphs", "Task graphs"),
                ("Pipeline Health", "Pipeline health"),
            ]
            for label, workflow in reliability_routes:
                if st.button(label, key=f"dba_control_reliability_{label}", use_container_width=True):
                    _jump("Workload Operations", workflow=workflow)
        with r2:
            st.subheader("Cost and Capacity")
            st.write("Bill explanations, contract pacing, warehouse pressure, rightsizing, recommendations, and value evidence.")
            for label, title, workflow in [
                ("Cost & Contract", "Cost & Contract", "Explain bill / attribution / contract"),
                ("AI / Cortex Spend", "Cost & Contract", "AI and Cortex spend"),
                ("Warehouse Health", "Warehouse Health", ""),
            ]:
                if st.button(label, key=f"dba_control_cost_{label}", use_container_width=True):
                    _jump(title, workflow=workflow)
        with r3:
            st.subheader("Security and Governance")
            st.write("Login posture, grants, data sharing, object changes, procedure lineage, drift checks, and admin controls.")
            for title, workflow in [("Security Posture", "Access posture"), ("Change & Drift", "Object and access changes")]:
                if st.button(title, key=f"dba_control_security_{title}", use_container_width=True):
                    _jump(title, workflow=workflow)

        st.divider()
        st.subheader("Exception Detail Samples")
        detail_tabs = st.tabs([
            "Failed Queries",
            "Task Failures",
            "Task SLA/Cost",
            "Procedure SLA/Cost",
            "Cortex Cost",
            "Failed Logins",
            "Object Changes",
            "Action Queue",
        ])
        for tab, key in zip(
            detail_tabs,
            [
                "failed_queries",
                "task_failures",
                "task_sla_cost",
                "procedure_sla_cost",
                "cortex_exceptions",
                "failed_logins",
                "object_changes",
                "action_queue",
            ],
        ):
            with tab:
                df = data.get(key, _empty_df())
                if not df.empty:
                    render_priority_dataframe(
                        df,
                        title=f"{key.replace('_', ' ').title()} evidence",
                        priority_columns=[
                            "SEVERITY", "SIGNAL", "ENTITY", "TASK_NAME", "PROCEDURE_NAME",
                            "QUERY_ID", "WAREHOUSE_NAME", "USER_NAME", "ERROR_MESSAGE",
                            "ALLOCATED_CREDITS", "EST_TOTAL_CREDITS", "DURATION_SEC",
                            "START_TIME", "SCHEDULED_TIME", "EVENT_TIMESTAMP",
                        ],
                        sort_by=[
                            "ALLOCATED_CREDITS", "EST_TOTAL_CREDITS", "DURATION_SEC",
                            "START_TIME", "SCHEDULED_TIME", "EVENT_TIMESTAMP",
                        ],
                        ascending=[False, False, False, False, False, False],
                        raw_label=f"All {key.replace('_', ' ')} evidence rows",
                        height=320,
                    )
                else:
                    err = data.get(f"{key}_error", _empty_df())
                    if not err.empty:
                        st.warning(str(err["ERROR"].iloc[0]))
                    else:
                        st.info("No rows found.")

    with tab_release:
        st.subheader("Release Compare")
        st.caption(
            "Compare before/after release windows for task graph duration, stored procedure runtime, "
            "estimated credits, failures, and impacted objects. Use this when a product release changes "
            "stored procedure or task-graph behavior."
        )
        today = date.today()
        default_after_end = today
        default_after_start = today - timedelta(days=7)
        default_before_end = default_after_start - timedelta(days=1)
        default_before_start = default_before_end - timedelta(days=7)

        w1, w2 = st.columns(2)
        with w1:
            before_range = st.date_input(
                "Before release window",
                value=(default_before_start, default_before_end),
                key="dba_release_before_window",
            )
        with w2:
            after_range = st.date_input(
                "After release window",
                value=(default_after_start, default_after_end),
                key="dba_release_after_window",
            )
        t1, t2, t3, t4 = st.columns(4)
        with t1:
            runtime_pct_threshold = st.number_input(
                "Runtime drift threshold (%)",
                min_value=1.0,
                value=25.0,
                step=5.0,
                key="dba_release_runtime_pct_threshold",
            )
        with t2:
            runtime_delta_sec_threshold = st.number_input(
                "Runtime delta threshold (sec)",
                min_value=0.0,
                value=30.0,
                step=30.0,
                key="dba_release_runtime_delta_sec_threshold",
            )
        with t3:
            credit_pct_threshold = st.number_input(
                "Credit drift threshold (%)",
                min_value=1.0,
                value=25.0,
                step=5.0,
                key="dba_release_credit_pct_threshold",
            )
        with t4:
            credit_delta_threshold = st.number_input(
                "Credit delta threshold",
                min_value=0.0,
                value=0.0,
                step=0.01,
                format="%.4f",
                key="dba_release_credit_delta_threshold",
            )
        st.caption(
            "Release compare flags failures, runtime drift above both runtime thresholds, "
            "or estimated-credit drift above both credit thresholds."
        )

        valid_ranges = (
            isinstance(before_range, (tuple, list)) and len(before_range) == 2
            and isinstance(after_range, (tuple, list)) and len(after_range) == 2
            and before_range[0] <= before_range[1]
            and after_range[0] <= after_range[1]
        )
        if not valid_ranges:
            st.warning("Choose valid before and after date ranges.")
        elif st.button("Compare Release Windows", key="dba_release_compare_load", type="primary"):
            with st.spinner("Comparing task graphs and stored procedure runs..."):
                try:
                    st.session_state["dba_release_compare_data"] = _load_release_compare(
                        session,
                        company,
                        before_range[0],
                        before_range[1],
                        after_range[0],
                        after_range[1],
                        runtime_pct_threshold,
                        runtime_delta_sec_threshold,
                        credit_pct_threshold,
                        credit_delta_threshold,
                    )
                    st.session_state["dba_release_compare_company"] = company
                    st.session_state["dba_release_compare_credit_price"] = credit_price
                except Exception as exc:
                    st.session_state["dba_release_compare_data"] = {
                        "error": format_snowflake_error(exc),
                        "before_label": f"{before_range[0]} to {before_range[1]}",
                        "after_label": f"{after_range[0]} to {after_range[1]}",
                    }

        release_data = st.session_state.get("dba_release_compare_data", {})
        if release_data.get("error"):
            st.error(release_data["error"])
        elif release_data:
            task_compare = release_data.get("task_compare", _empty_df())
            proc_compare = release_data.get("procedure_compare", _empty_df())
            task_regressions = task_compare[
                task_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])
            ] if not task_compare.empty else pd.DataFrame()
            proc_regressions = proc_compare[
                proc_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])
            ] if not proc_compare.empty else pd.DataFrame()
            total_credit_delta = (
                safe_float(task_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not task_compare.empty else 0)
                + safe_float(proc_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not proc_compare.empty else 0)
            )
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Task Regressions", f"{len(task_regressions):,}", delta_color="inverse")
            k2.metric("Procedure Regressions", f"{len(proc_regressions):,}", delta_color="inverse")
            k3.metric("Est. Credit Delta", format_credits(total_credit_delta), delta_color="inverse")
            k4.metric("Est. Cost Delta", f"${credits_to_dollars(total_credit_delta, credit_price):,.2f}", delta_color="inverse")

            show_all = st.checkbox("Show stable rows too", value=False, key="dba_release_show_all")
            task_display = task_compare if show_all else task_regressions
            proc_display = proc_compare if show_all else proc_regressions

            st.markdown("**Task Graph / Task Changes**")
            if not task_display.empty:
                task_cols = [
                    col for col in [
                        "SEVERITY", "ENTITY", "SIGNAL", "RUNS_BEFORE", "RUNS_AFTER", "FAILURES_DELTA",
                        "AVG_DURATION_SEC_BEFORE", "AVG_DURATION_SEC_AFTER", "AVG_DURATION_CHANGE_PCT",
                        "EST_CREDITS_BEFORE", "EST_CREDITS_AFTER", "EST_CREDITS_CHANGE_PCT",
                        "PROCEDURE_NAME", "IMPACT_OBJECTS",
                    ] if col in task_display.columns
                ]
                render_priority_dataframe(
                    task_display[task_cols],
                    title="Task graph release regressions",
                    priority_columns=task_cols,
                    sort_by=[
                        "AVG_DURATION_CHANGE_PCT", "EST_CREDITS_CHANGE_PCT",
                        "FAILURES_DELTA", "EST_CREDITS_DELTA",
                    ],
                    ascending=[False, False, False, False],
                    raw_label="All task graph release comparison rows",
                    height=320,
                )
                download_csv(task_display, "overwatch_release_task_compare.csv")
            else:
                st.success("No material task graph regressions found for the selected windows.")

            st.markdown("**Stored Procedure Changes**")
            if not proc_display.empty:
                proc_cols = [
                    col for col in [
                        "SEVERITY", "ENTITY", "SIGNAL", "RUNS_BEFORE", "RUNS_AFTER", "FAILURES_DELTA",
                        "AVG_DURATION_SEC_BEFORE", "AVG_DURATION_SEC_AFTER", "AVG_DURATION_CHANGE_PCT",
                        "EST_CREDITS_BEFORE", "EST_CREDITS_AFTER", "EST_CREDITS_CHANGE_PCT",
                        "IMPACT_OBJECTS",
                    ] if col in proc_display.columns
                ]
                render_priority_dataframe(
                    proc_display[proc_cols],
                    title="Stored procedure release regressions",
                    priority_columns=proc_cols,
                    sort_by=[
                        "AVG_DURATION_CHANGE_PCT", "EST_CREDITS_CHANGE_PCT",
                        "FAILURES_DELTA", "EST_CREDITS_DELTA",
                    ],
                    ascending=[False, False, False, False],
                    raw_label="All stored procedure release comparison rows",
                    height=320,
                )
                download_csv(proc_display, "overwatch_release_procedure_compare.csv")
            else:
                st.success("No material stored procedure regressions found for the selected windows.")

            report = _build_release_compare_report(
                company,
                release_data,
                safe_float(st.session_state.get("dba_release_compare_credit_price", credit_price)) or credit_price,
            )
            with st.expander("Release comparison brief", expanded=False):
                st.text_area("Brief", report, height=320, key="dba_release_compare_report_text")
                st.download_button(
                    "Download Release Brief",
                    report,
                    file_name=f"overwatch_release_compare_{company}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown",
                    key="dba_release_compare_report_download",
                )
        else:
            st.info("Choose release windows and run the comparison when you need post-release evidence.")

    with tab_evidence:
        st.subheader("Report-Ready Brief")
        report = _build_report(data, exceptions, company, credit_price, int(loaded_lookback))
        st.text_area("Brief text", report, height=420)
        st.download_button(
            "Download DBA Brief",
            report,
            file_name=f"overwatch_dba_brief_{company}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
            mime="text/markdown",
            key="dba_control_room_brief_download",
        )

    with tab_sources:
        st.subheader("Control Room Source Status")
        rows = []
        source_modes = data.get("_source_modes", _empty_df())
        mode_map = {}
        if source_modes is not None and not source_modes.empty and "Source" in source_modes.columns:
            for _, source_row in source_modes.iterrows():
                mode_map[str(source_row.get("Source"))] = {
                    "Mode": str(source_row.get("Mode", "")),
                    "Mode Message": str(source_row.get("Message", "")),
                }
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if key.endswith("_error"):
                continue
            err = data.get(f"{key}_error", _empty_df())
            mode_info = mode_map.get(str(key), {})
            message = "" if err.empty else str(err["ERROR"].iloc[0])
            if not message and mode_info.get("Mode Message", "").lower() not in ("", "nan", "none"):
                message = mode_info["Mode Message"]
            rows.append({
                "Source": key,
                "Mode": mode_info.get("Mode", "Live or local"),
                "Rows": 0 if value is None or value.empty else len(value),
                "Status": "Warning" if not err.empty else "OK",
                "Message": message,
            })
        source_status = pd.DataFrame(rows)
        render_priority_dataframe(
            source_status,
            title="Source status by warning first",
            priority_columns=["Source", "Mode", "Rows", "Status", "Message"],
            sort_by=["Status", "Rows"],
            ascending=[False, False],
            raw_label="All source status rows",
            height=360,
        )
        snapshot_df = data.get("_mart_snapshot", _empty_df())
        if snapshot_df is not None and not snapshot_df.empty:
            st.subheader("Fast Snapshot Rows")
            render_priority_dataframe(
                snapshot_df,
                title="Latest fast snapshot",
                priority_columns=[
                    "SNAPSHOT_TS", "COMPANY", "HEALTH_SCORE", "FAILED_QUERIES_24H",
                    "FAILED_TASKS_24H", "CREDITS_24H", "CORTEX_COST_7D",
                ],
                sort_by=["SNAPSHOT_TS"],
                ascending=False,
                raw_label="All fast snapshot rows",
                height=180,
            )
        budget_summary = get_query_budget_summary()
        st.subheader("Current Session Query Budget")
        if budget_summary is None or budget_summary.empty:
            st.info("No query telemetry has been recorded in this Streamlit session yet.")
        else:
            st.caption(
                "Use this to spot OVERWATCH pages that are repeatedly scanning too much, returning too many rows, "
                "or taking too long. High-risk rows should be candidates for caching, aggregation, or progressive load."
            )
            render_priority_dataframe(
                budget_summary,
                title="Query budget risks",
                priority_columns=[
                    "section", "budget_risk", "calls", "unique_queries",
                    "expensive_calls", "elapsed_sec", "max_rows", "max_result_mb",
                ],
                sort_by=["budget_risk", "expensive_calls", "elapsed_sec"],
                ascending=[False, False, False],
                raw_label="All query budget rows",
            )
            download_csv(budget_summary, "overwatch_query_budget_summary.csv")
