# sections/query_search.py - Query search and history browser
import streamlit as st

from utils import (
    download_csv,
    filter_existing_columns,
    format_snowflake_error,
    get_active_company,
    get_global_filter_clause,
    get_session,
    render_query_drilldown,
    run_query,
    sql_literal,
)


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
        return f"Global Filters date range: {start} to {end}"
    if start:
        return f"Global Filters date range: from {start}"
    if end:
        return f"Global Filters date range: through {end}"
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


def render():
    session = get_session()
    company = get_active_company()
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "BYTES_SCANNED",
            "ROWS_PRODUCED",
            "CREDITS_USED_CLOUD_SERVICES",
        ],
    ))
    warehouse_size_expr = (
        "warehouse_size AS warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    )
    gb_scanned_expr = (
        "bytes_scanned/POWER(1024,3) AS gb_scanned"
        if "BYTES_SCANNED" in qh_cols else "0::FLOAT AS gb_scanned"
    )
    rows_produced_expr = (
        "rows_produced AS rows_produced"
        if "ROWS_PRODUCED" in qh_cols else "0::NUMBER AS rows_produced"
    )
    cloud_credits_expr = (
        "credits_used_cloud_services AS cloud_credits"
        if "CREDITS_USED_CLOUD_SERVICES" in qh_cols else "0::FLOAT AS cloud_credits"
    )

    st.header("Query Search & History")
    st.caption("Search company-scoped ACCOUNT_USAGE.QUERY_HISTORY by exact query ID or query-text keyword.")

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        search_text = st.text_input("Search query text or query ID", key="qs_text")
    with c2:
        days_back = st.slider("Days back", 1, 30, 7, key="qs_days")
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
        ["Auto", "Exact query ID", "Prefix starts with", "Text contains"],
        key="qs_mode",
    )
    st.caption(
        "Exact query ID is the cheapest path. Prefix search avoids a leading wildcard. "
        "Contains search is capped at 7 days to avoid broad query-text scans. "
        "Snowflake Search Optimization does not accelerate ACCOUNT_USAGE query-text history."
    )
    global_date_label = _global_date_label()
    if global_date_label:
        st.caption(f"Using {global_date_label}; the Days back slider applies only when Global Filters dates are cleared.")

    autorun = bool(st.session_state.pop("qs_autorun", False))
    if (st.button("Search", key="qs_run") or autorun) and search_text:
        search_value = search_text.strip()
        try:
            search_cl, resolved_mode, day_cap = _query_search_clause(search_value, search_mode)
        except ValueError as exc:
            st.warning(str(exc))
            return
        date_predicate, date_label, effective_days = _search_date_predicate(days_back, day_cap)
        if day_cap and (days_back > day_cap or global_date_label):
            st.warning(
                f"Contains search is capped at {day_cap} days. "
                "Use exact query ID or prefix search for wider lookbacks."
            )
        if resolved_mode == "Text contains":
            st.info(
                "Text contains mode scans query text in ACCOUNT_USAGE. Prefer exact query ID or prefix search "
                "when the query ID or leading SQL token is known."
            )

        user_cl = f"AND user_name ILIKE '%' || {sql_literal(user_filter)} || '%'" if user_filter else ""
        status_cl = f"AND execution_status = {sql_literal(status_filter)}" if status_filter != "ALL" else ""
        scoped_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )

        try:
            df_qs = run_query(f"""
                SELECT query_id, user_name, warehouse_name, {warehouse_size_expr}, execution_status,
                       start_time, total_elapsed_time/1000 AS elapsed_sec,
                       {gb_scanned_expr},
                       {rows_produced_expr},
                       {cloud_credits_expr},
                       SUBSTR(query_text,1,500) AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE 1=1
                  {date_predicate}
                  {search_cl}
                  {scoped_filters}
                  {user_cl} {status_cl}
                ORDER BY start_time DESC
                LIMIT {row_limit}
            """, ttl_key=f"query_search_{company}_{resolved_mode}_{search_value}_{user_filter}_{status_filter}_{effective_days}_{row_limit}", tier="historical", section="Query Search & History")
            st.session_state["qs_df_qs"] = df_qs
            st.session_state["qs_search_mode"] = resolved_mode
            st.session_state["qs_effective_days"] = effective_days
            st.session_state["qs_date_label"] = date_label
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
            download_csv(df_q, "query_search_results.csv")
        else:
            st.info("No queries matched the search criteria.")
