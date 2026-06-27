# sections/query_search.py - Query search and history browser
import os

import streamlit as st

from utils import (
    day_window_selectbox,
    download_csv,
    format_snowflake_error,
    get_active_company,
    get_global_filter_clause,
    render_query_drilldown,
    run_query,
    sql_literal,
)
from utils.mart_names import mart_object_name
from performance import ACCOUNT_USAGE_TARGETED_SCAN_ALLOWED, query_budget_context


def _looks_like_query_id(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 16 or any(ch.isspace() for ch in text):
        return False
    return "-" in text or text[:2].isdigit()


def _query_search_clause(search_value: str, mode: str) -> tuple[str, str, int | None]:
    """Return SQL predicate, display mode, and an optional day cap for safe query search."""
    normalized_mode = str(mode or "Auto").strip()
    if normalized_mode == "Exact query ID" or (normalized_mode == "Auto" and _looks_like_query_id(search_value)):
        return f"AND query_id = {sql_literal(search_value)}", "Exact query ID", None
    if normalized_mode == "Query signature":
        if len(search_value) < 6:
            raise ValueError("Enter at least 6 characters for query signature search.")
        return (
            f"AND (query_hash = {sql_literal(search_value)} OR query_signature = {sql_literal(search_value)})",
            "Query signature",
            None,
        )
    if normalized_mode == "Prefix starts with":
        if len(search_value) < 3:
            raise ValueError("Enter at least 3 characters for prefix search.")
        return f"AND query_text ILIKE {sql_literal(search_value + '%')}", "Prefix starts with", None
    if len(search_value) < 6:
        raise ValueError("Enter at least 6 characters for contains search, or switch to exact query ID.")
    return f"AND query_text ILIKE '%' || {sql_literal(search_value)} || '%'", "Text contains", 7


def _global_date_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if start and end:
        return f"Triage Filters date range: {start} to {end}"
    if start:
        return f"Triage Filters date range: from {start}"
    if end:
        return f"Triage Filters date range: through {end}"
    return ""


def _search_date_predicate(days_back: int, day_cap: int | None) -> tuple[str, str, int]:
    """Return extra date predicate, display label, and effective local-day value."""
    global_label = _global_date_label()
    if global_label:
        if day_cap:
            return (
                f"AND start_time >= DATEADD('day', -{int(day_cap)}, CURRENT_TIMESTAMP())",
                f"{global_label}; contains safety cap: {int(day_cap)}d",
                int(day_cap),
            )
        return "", global_label, int(days_back)
    effective_days = min(int(days_back), int(day_cap)) if day_cap else int(days_back)
    return (
        f"AND start_time >= DATEADD('day', -{effective_days}, CURRENT_TIMESTAMP())",
        f"{effective_days}d",
        effective_days,
    )


def _recent_query_detail_sql(
    *,
    search_cl: str,
    date_predicate: str,
    scoped_filters: str,
    user_cl: str,
    status_cl: str,
    target_wh_cl: str,
    row_limit: int,
) -> str:
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    return f"""
        SELECT
            query_id,
            user_name,
            warehouse_name,
            warehouse_size AS warehouse_size,
            execution_status,
            start_time,
            total_elapsed_time/1000 AS elapsed_sec,
            bytes_scanned/POWER(1024,3) AS gb_scanned,
            rows_produced AS rows_produced,
            query_hash,
            credits_used_cloud_services AS cloud_credits
        FROM {table}
        WHERE 1=1
          {date_predicate}
          {search_cl}
          {scoped_filters}
          {user_cl} {status_cl} {target_wh_cl}
        ORDER BY start_time DESC
        LIMIT {int(row_limit)}
    """


def _query_text_preview_sql(query_id: str) -> str:
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    return f"""
        SELECT query_id, SUBSTR(query_text, 1, 1200) AS query_text_preview
        FROM {table}
        WHERE query_id = {sql_literal(query_id)}
        ORDER BY start_time DESC
        LIMIT 1
    """


def search_recent_query_summary(sql: str, *, ttl_key: str, row_limit: int):
    return run_query(
        sql,
        ttl_key=ttl_key,
        tier="recent",
        section="Query Search & History",
        max_rows=min(int(row_limit), 500),
        query_boundary="query_search",
    )


def load_query_text_preview(query_id: str):
    return run_query(
        _query_text_preview_sql(query_id),
        ttl_key=f"query_text_preview_{query_id}",
        tier="recent",
        section="Query Search & History",
        max_rows=1,
        query_boundary="query_preview",
    )


def render():
    company = get_active_company()
    workload_target = st.session_state.get("workload_operations_evidence_target")
    workload_target = workload_target if isinstance(workload_target, dict) else {}
    target_entity_type = str(workload_target.get("entity_type") or "").lower()
    target_value = str(
        workload_target.get("entity_id")
        or workload_target.get("entity_name")
        or workload_target.get("evidence_id")
        or ""
    ).strip()
    target_warehouse = target_value if target_entity_type == "warehouse" else ""
    target_query = target_value if target_entity_type in {"query", "query_id", "query_signature"} else ""
    if target_query and not str(st.session_state.get("qs_text") or "").strip():
        target_kind = "query_id" if _looks_like_query_id(target_query) else target_entity_type
        st.session_state["qs_text"] = target_query
        st.session_state["qs_mode"] = (
            "Exact query ID"
            if target_kind == "query_id"
            else "Query signature"
            if target_kind == "query_signature"
            else "Prefix starts with"
        )
        st.session_state["qs_autorun"] = target_kind in {"query_id", "query_signature"}

    st.subheader("Query Search & History")
    st.caption("Search recent mart-backed query detail first. Account Usage fallback runs only after explicit request.")
    if target_warehouse:
        st.caption(f"Focused on finding target: warehouse {target_warehouse}")
        st.session_state.setdefault("qs_warehouse", target_warehouse)

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        search_text = st.text_input("Search query text or query ID", key="qs_text")
    with c2:
        days_back = day_window_selectbox("Days back", key="qs_days", default=7)
    with c3:
        user_filter = st.text_input("User (optional)", key="qs_user")
    with c4:
        row_limit = st.slider("Max results", 50, 500, 200, step=50, key="qs_row_limit")

    status_filter = st.selectbox(
        "Status filter",
        ["ALL", "SUCCESS", "FAILED_WITH_ERROR", "QUEUED", "BLOCKED"],
        key="qs_status",
    )
    search_mode = st.selectbox(
        "Search mode",
        ["Auto", "Exact query ID", "Query signature", "Prefix starts with", "Text contains"],
        key="qs_mode",
    )
    st.caption(
        "Exact query ID is the cheapest path. Prefix search avoids a leading wildcard. "
        "Contains search is capped at 7 days to avoid broad query-text scans. "
        "Snowflake Search Optimization does not accelerate ACCOUNT_USAGE query-text history."
    )
    global_date_label = _global_date_label()
    if global_date_label:
        st.caption(f"Using {global_date_label}; the Days back slider applies only when Triage Filter dates are cleared.")

    autorun = bool(st.session_state.pop("qs_autorun", False))
    explicit_search = st.button("Search recent mart detail", key="qs_run")
    account_usage_fallback = False
    with st.expander("Advanced Account Usage fallback", expanded=False):
        st.warning(
            "Account Usage fallback can scan Snowflake history and may be slower or costlier. "
            "Use recent mart detail first unless an admin specifically needs older proof."
        )
        fallback_confirmed = os.environ.get("OVERWATCH_TEST_MODE") == "1" or st.checkbox(
            "I understand this may scan Account Usage.",
            key="qs_account_usage_fallback_confirmed",
        )
        account_usage_fallback = st.button(
            "Search Account Usage fallback",
            key="qs_account_usage_fallback",
            disabled=not fallback_confirmed,
        )
    if (explicit_search or autorun or account_usage_fallback) and (search_text or target_warehouse):
        if autorun and target_warehouse and not ACCOUNT_USAGE_TARGETED_SCAN_ALLOWED:
            st.info("Warehouse target is prefilled. Click Search to run a bounded warehouse query history lookup.")
            return
        search_value = search_text.strip()
        if search_value:
            try:
                search_cl, resolved_mode, day_cap = _query_search_clause(search_value, search_mode)
            except ValueError as exc:
                st.warning(str(exc))
                return
        else:
            search_cl, resolved_mode, day_cap = "", "Warehouse target", None
        date_predicate, date_label, effective_days = _search_date_predicate(days_back, day_cap)
        if day_cap and (days_back > day_cap or global_date_label):
            st.warning(
                f"Contains search is capped at {day_cap} days. "
                "Use exact query ID or prefix search for wider lookbacks."
            )
        if resolved_mode == "Text contains":
            st.info(
                "Text contains mode scans query text. Prefer exact query ID or prefix search "
                "when the query ID or leading SQL token is known."
            )
        if resolved_mode == "Exact query ID":
            row_limit = 1
        elif resolved_mode == "Query signature":
            row_limit = min(int(row_limit), 200)

        user_cl = f"AND user_name ILIKE '%' || {sql_literal(user_filter)} || '%'" if user_filter else ""
        status_cl = f"AND execution_status = {sql_literal(status_filter)}" if status_filter != "ALL" else ""
        target_wh_cl = f"AND UPPER(warehouse_name) = UPPER({sql_literal(target_warehouse)})" if target_warehouse else ""
        scoped_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )

        try:
            if account_usage_fallback:
                sql = f"""
                    SELECT query_id, user_name, warehouse_name, warehouse_size AS warehouse_size, execution_status,
                           start_time, total_elapsed_time/1000 AS elapsed_sec,
                           bytes_scanned/POWER(1024,3) AS gb_scanned,
                           rows_produced AS rows_produced,
                           credits_used_cloud_services AS cloud_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE 1=1
                      {date_predicate}
                      {search_cl}
                      {scoped_filters}
                      {user_cl} {status_cl} {target_wh_cl}
                    ORDER BY start_time DESC
                    LIMIT {row_limit}
                """
                ttl_prefix = "query_search_account_usage"
            else:
                sql = _recent_query_detail_sql(
                    search_cl=search_cl,
                    date_predicate=date_predicate,
                    scoped_filters=scoped_filters,
                    user_cl=user_cl,
                    status_cl=status_cl,
                    target_wh_cl=target_wh_cl,
                    row_limit=row_limit,
                )
                ttl_prefix = "query_search_recent_detail"
            ttl_key = f"{ttl_prefix}_{company}_{resolved_mode}_{search_value}_{target_warehouse}_{user_filter}_{status_filter}_{effective_days}_{row_limit}"
            if account_usage_fallback:
                with query_budget_context("account_usage_fallback", section="Workload Operations", workflow="Query Investigation", budget=1):
                    df_qs = run_query(
                        sql,
                        ttl_key=ttl_key,
                        tier="historical",
                        section="Query Search & History",
                        max_rows=min(int(row_limit), 200),
                        query_boundary="account_usage",
                    )
            else:
                context_name = (
                    "query_search_exact"
                    if resolved_mode == "Exact query ID"
                    else "query_search_signature"
                    if resolved_mode == "Query signature"
                    else "query_search_text"
                )
                with query_budget_context(context_name, section="Workload Operations", workflow="Query Investigation", budget=1):
                    df_qs = search_recent_query_summary(sql, ttl_key=ttl_key, row_limit=row_limit)
            st.session_state["qs_df_qs"] = df_qs
            st.session_state["qs_search_mode"] = resolved_mode
            st.session_state["qs_effective_days"] = effective_days
            st.session_state["qs_date_label"] = date_label
            st.session_state["qs_last_search_filters"] = {
                "scoped_filters": scoped_filters,
                "user_cl": user_cl,
                "status_cl": status_cl,
                "target_wh_cl": target_wh_cl,
                "effective_days": effective_days,
            }
        except Exception as e:
            st.warning(f"Query search unavailable: {format_snowflake_error(e)}")

    df_q = st.session_state.get("qs_df_qs")
    if df_q is not None:
        if not df_q.empty:
            st.success(
                f"Found {len(df_q):,} matching queries "
                f"({st.session_state.get('qs_search_mode', 'Search')}, {st.session_state.get('qs_date_label', str(st.session_state.get('qs_effective_days', days_back)) + 'd')})."
            )
            render_query_drilldown(df_q, key="qs_result")
            query_ids = [
                str(value).strip()
                for value in df_q.get("QUERY_ID", df_q.get("query_id", [])).tolist()
                if str(value).strip()
            ] if hasattr(df_q, "get") else []
            selected_preview_id = query_ids[0] if query_ids else ""
            if selected_preview_id and st.button("Load SQL preview", key="qs_load_sql_preview"):
                with query_budget_context("query_preview", section="Workload Operations", workflow="Query Investigation", budget=1):
                    preview_df = load_query_text_preview(selected_preview_id)
                st.session_state["qs_sql_preview_df"] = preview_df
                st.session_state["qs_sql_preview_query_id"] = selected_preview_id
            if st.session_state.get("qs_sql_preview_query_id"):
                st.caption("SQL preview loaded. Open admin detail to inspect full text.")
            selected_row = df_q.iloc[0].to_dict() if hasattr(df_q, "iloc") and len(df_q) else {}
            selected_hash = str(
                selected_row.get("QUERY_HASH")
                or selected_row.get("query_hash")
                or ""
            ).strip()
            if selected_hash and selected_preview_id and st.button("Show related executions", key="qs_show_related_executions"):
                last_filters = st.session_state.get("qs_last_search_filters")
                last_filters = last_filters if isinstance(last_filters, dict) else {}
                related_days = max(1, min(int(last_filters.get("effective_days") or 7), 7))
                related_sql = _recent_query_detail_sql(
                    search_cl=(
                        f"AND query_hash = {sql_literal(selected_hash)} "
                        f"AND query_id <> {sql_literal(selected_preview_id)}"
                    ),
                    date_predicate=f"AND start_time >= DATEADD('day', -{related_days}, CURRENT_TIMESTAMP())",
                    scoped_filters=str(last_filters.get("scoped_filters") or ""),
                    user_cl=str(last_filters.get("user_cl") or ""),
                    status_cl=str(last_filters.get("status_cl") or ""),
                    target_wh_cl=str(last_filters.get("target_wh_cl") or ""),
                    row_limit=50,
                )
                with query_budget_context("query_search_signature", section="Workload Operations", workflow="Query Investigation", budget=1):
                    st.session_state["qs_related_df"] = search_recent_query_summary(
                        related_sql,
                        ttl_key=f"query_search_related_{company}_{selected_hash}_{selected_preview_id}_50",
                        row_limit=50,
                    )
            related_df = st.session_state.get("qs_related_df")
            if related_df is not None and hasattr(related_df, "empty") and not related_df.empty:
                st.caption(f"Related executions loaded: {len(related_df):,}.")
            export_df = df_q.drop(
                columns=[column for column in getattr(df_q, "columns", []) if str(column).lower() == "query_text"],
                errors="ignore",
            )
            download_csv(export_df, "query_search_results.csv")
        else:
            st.info("No queries matched the search criteria.")
