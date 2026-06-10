# utils/display.py - chart and drill-down rendering helpers
import streamlit as st
import pandas as pd
from config import DAY_WINDOW_OPTIONS, DEFAULT_DAY_WINDOW
from sections.shell_helpers import render_shell_snapshot
from .cache import clear_all_cache
from .cost import format_credits
from .compatibility import filter_existing_columns
from .downloads import download_csv, mark_loaded, show_loaded_time
from .query import format_snowflake_error, run_query, run_query_or_raise, sql_literal
from .company_filter import get_db_filter_clause, get_user_filter_clause, get_wh_filter_clause
from .helpers import safe_float
from .workflows import add_cost_companion_columns, prioritize_context_columns
from .workflows import apply_operator_status_labels
from .workflows import render_mode_selector, render_priority_dataframe


DISPLAY_VERSION = "2026-06-05-chart-drillback-cost-v1"


def day_window_selectbox(
    label: str,
    *,
    key: str,
    default: int = DEFAULT_DAY_WINDOW,
    options: tuple[int, ...] = DAY_WINDOW_OPTIONS,
    help: str | None = None,
) -> int:
    """Render a standard DBA lookback selector using approved day windows."""
    valid_options = tuple(int(value) for value in options)
    if not valid_options:
        valid_options = tuple(int(value) for value in DAY_WINDOW_OPTIONS)
    requested_default = int(default)
    fallback = (
        requested_default
        if requested_default in valid_options
        else min(valid_options, key=lambda value: (abs(value - requested_default), value))
    )
    current = st.session_state.get(key, fallback)
    try:
        current = int(current)
    except (TypeError, ValueError):
        current = fallback
    if current not in valid_options:
        current = fallback
        st.session_state[key] = current
    return int(
        st.selectbox(
            label,
            valid_options,
            index=valid_options.index(current),
            key=key,
            format_func=lambda value: f"{int(value)} days",
            help=help,
        )
    )


def _altair():
    """Import Altair only when a chart path actually needs it."""
    import altair as alt

    return alt


def rank_chart_frame(
    df: pd.DataFrame,
    dimension: str,
    measure: str,
    *,
    top_n: int = 20,
    ascending: bool = False,
) -> pd.DataFrame:
    """Return a metric-ranked chart frame with one row per displayed dimension."""
    if df is None or df.empty or dimension not in df.columns or measure not in df.columns:
        return pd.DataFrame(columns=[dimension, measure])
    chart_df = df[[dimension, measure]].dropna(subset=[dimension]).copy()
    chart_df[dimension] = chart_df[dimension].astype(str)
    chart_df[measure] = pd.to_numeric(chart_df[measure], errors="coerce").fillna(0)
    chart_df = chart_df.groupby(dimension, as_index=False, dropna=False, sort=False)[measure].sum()
    chart_df = chart_df.sort_values(measure, ascending=ascending, kind="mergesort")
    return chart_df.head(max(1, int(top_n or 20)))


def _ranked_chart_height(row_count: int) -> int:
    return max(180, min(520, 28 * int(row_count or 1) + 56))


def render_ranked_bar_chart(
    df: pd.DataFrame,
    dimension: str,
    measure: str,
    *,
    title: str = "",
    top_n: int = 20,
    color: str = "#38bdf8",
) -> pd.DataFrame:
    """Render a horizontal top-to-bottom ranked bar chart and return plotted rows."""
    chart_df = add_cost_companion_columns(rank_chart_frame(df, dimension, measure, top_n=top_n))
    if chart_df.empty:
        return chart_df
    if title:
        st.subheader(title)

    alt = _altair()
    tooltips = [alt.Tooltip(f"{dimension}:N"), alt.Tooltip(f"{measure}:Q", format=",.2f")]
    cost_column = f"{str(measure).upper()}_COST_USD"
    if cost_column in chart_df.columns:
        tooltips.append(alt.Tooltip(f"{cost_column}:Q", title="Cost USD", format="$,.2f"))
    chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3, color=color)
        .encode(
            x=alt.X(f"{measure}:Q", title=measure.replace("_", " ").title()),
            y=alt.Y(
                f"{dimension}:N",
                sort=alt.SortField(field=measure, order="descending"),
                title=None,
                axis=alt.Axis(labelLimit=260),
            ),
            tooltip=tooltips,
        )
        .properties(height=_ranked_chart_height(len(chart_df)))
    )
    st.altair_chart(chart, width="stretch")
    return chart_df


def render_chart_with_data_toggle(
    title: str,
    key: str,
    chart_renderer,
    data_rows: pd.DataFrame,
    *,
    priority_columns: list[str] | tuple[str, ...] | None = None,
    sort_by: list[str] | tuple[str, ...] | None = None,
    ascending: list[bool] | tuple[bool, ...] | bool = False,
    max_rows: int = 25,
    raw_label: str | None = None,
) -> str:
    """Render a chart or its backing table with a clear return path."""
    if title:
        st.markdown(f"**{title}**")
    mode_key = f"{key}_chart_data_mode"
    requested_key = f"{key}_chart_data_requested"
    requested_mode = st.session_state.pop(requested_key, None)
    if requested_mode in {"Chart", "Data"}:
        st.session_state[mode_key] = requested_mode
    mode = render_mode_selector(
        "Chart view",
        mode_key,
        ("Chart", "Data"),
        default="Chart",
    )
    if mode == "Data":
        back_col, note_col = st.columns([1, 4])
        with back_col:
            if st.button("Back to chart", key=f"{key}_back_to_chart", width="stretch"):
                st.session_state[requested_key] = "Chart"
                st.rerun()
        with note_col:
            st.caption(f"Showing table rows behind {title or 'this chart'}.")
        if data_rows is None or getattr(data_rows, "empty", True):
            st.info("No chart data rows are loaded for this scope.")
        else:
            render_priority_dataframe(
                data_rows,
                title=f"{title or 'Chart'} data",
                priority_columns=priority_columns,
                sort_by=sort_by,
                ascending=ascending,
                max_rows=max_rows,
                raw_label=raw_label or f"{title or 'Chart'} full data",
                height=260,
            )
        return "Data"
    chart_renderer()
    return "Chart"


def _query_history_detail_exprs(prefix: str = "") -> dict:
    """Return safe query-history projection snippets for optional columns."""
    from .session import get_session

    cache_key = f"_overwatch_qh_detail_exprs_{prefix or 'base'}"
    cached = st.session_state.get(cache_key)
    if cached:
        return cached

    cols = set(filter_existing_columns(
        get_session(),
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SCANNED",
            "ROWS_PRODUCED",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "CREDITS_USED_CLOUD_SERVICES",
            "QUERY_TAG",
        ],
    ))
    p = f"{prefix}." if prefix else ""
    result = {
        "warehouse_size": (
            f"{p}warehouse_size AS warehouse_size"
            if "WAREHOUSE_SIZE" in cols else "NULL::VARCHAR AS warehouse_size"
        ),
        "queued_sec": (
            f"{p}queued_overload_time/1000 AS queued_sec"
            if "QUEUED_OVERLOAD_TIME" in cols else "0::FLOAT AS queued_sec"
        ),
        "gb_scanned": (
            f"{p}bytes_scanned/POWER(1024,3) AS gb_scanned"
            if "BYTES_SCANNED" in cols else "0::FLOAT AS gb_scanned"
        ),
        "rows_produced": (
            f"{p}rows_produced AS rows_produced"
            if "ROWS_PRODUCED" in cols else "0::NUMBER AS rows_produced"
        ),
        "remote_spill_gb": (
            f"{p}bytes_spilled_to_remote_storage/POWER(1024,3) AS remote_spill_gb"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in cols else "0::FLOAT AS remote_spill_gb"
        ),
        "cloud_credits": (
            f"{p}credits_used_cloud_services AS cloud_credits"
            if "CREDITS_USED_CLOUD_SERVICES" in cols else "0::FLOAT AS cloud_credits"
        ),
        "query_tag": (
            f"COALESCE({p}query_tag, 'UNTAGGED') AS query_tag"
            if "QUERY_TAG" in cols else "'UNTAGGED' AS query_tag"
        ),
        "has_query_tag": "QUERY_TAG" in cols,
    }
    st.session_state[cache_key] = result
    return result


# -- Query drill-down -----------------------------------------------------------

def render_query_drilldown(
    df: pd.DataFrame,
    key: str,
    title: str = "Query Drill Down",
):
    """Interactive single-row drill-down with operator statistics."""
    if df is None or df.empty or "QUERY_ID" not in df.columns:
        return

    st.subheader(title)
    grid_df = add_cost_companion_columns(
        prioritize_context_columns(df.head(1000), leading_columns=("QUERY_ID",))
    )
    grid_df = apply_operator_status_labels(grid_df)
    if len(df) > len(grid_df):
        st.caption(f"Showing the first {len(grid_df):,} rows for fast selection. Narrow filters to inspect deeper rows.")
    try:
        event = st.dataframe(
            grid_df,
            width="stretch",
            height=380,
            selection_mode="single-row",
            on_select="rerun",
            key=f"{key}_grid",
        )
        selected_rows = event.selection.rows
    except Exception:
        st.dataframe(grid_df, width="stretch", height=380)
        selected_qid = st.selectbox(
            "Select query_id",
            grid_df["QUERY_ID"].astype(str).tolist(),
            key=f"{key}_fallback_select",
        )
        query_ids = grid_df["QUERY_ID"].astype(str).tolist()
        selected_rows = [query_ids.index(selected_qid)] if selected_qid in query_ids else []

    if not selected_rows:
        st.caption("Select a row to open the drill-down panel.")
        return

    row = grid_df.iloc[selected_rows[0]]
    qid = str(row.get("QUERY_ID", ""))

    with st.expander(f"Details for `{qid}`", expanded=True):
        wh_name = str(row.get("WAREHOUSE_NAME","N/A"))
        wh_size = str(row.get("WAREHOUSE_SIZE","") or "")
        est_cr = safe_float(row.get("TOTAL_EST_CREDITS", row.get("EST_COMPUTE_CREDITS",0)))
        render_shell_snapshot((
            ("User", str(row.get("USER_NAME","N/A"))),
            ("Warehouse", f"{wh_name} ({wh_size})" if wh_size else wh_name),
            ("Elapsed Sec", f"{safe_float(row.get('ELAPSED_SEC',0)):,.1f}"),
            ("Est. Credits", format_credits(est_cr)),
        ))

        st.markdown("**SQL Text**")
        st.code(str(row.get("QUERY_TEXT","")), language="sql")

        from .session import get_session
        _session = get_session()

        if st.button("Load operator stats", key=f"{key}_opstats"):
            try:
                ops_df = run_query_or_raise(
                    f"SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS({sql_literal(qid)}))"
                )
                st.dataframe(
                    apply_operator_status_labels(add_cost_companion_columns(ops_df)),
                    width="stretch",
                    height=350,
                )
            except Exception as e:
                st.info(f"Operator stats unavailable: {format_snowflake_error(e)}")


# -- Warehouse drill-down -------------------------------------------------------

def render_warehouse_drilldown(
    warehouse_name: str,
    key: str,
    lookback_hours: int = 24,
):
    if not warehouse_name:
        return
    wh_safe = sql_literal(warehouse_name)
    company_filter = " ".join(filter(None, [
        get_wh_filter_clause("warehouse_name"),
        get_db_filter_clause("database_name"),
        get_user_filter_clause("user_name"),
    ]))
    qh_expr = _query_history_detail_exprs()
    df_wh = run_query(f"""
        SELECT query_id, user_name, warehouse_name, {qh_expr["warehouse_size"]}, database_name, schema_name,
               execution_status, start_time,
               total_elapsed_time/1000          AS elapsed_sec,
               compilation_time/1000            AS compile_sec,
               execution_time/1000              AS exec_sec,
               {qh_expr["queued_sec"]},
               {qh_expr["gb_scanned"]},
               {qh_expr["rows_produced"]},
               {qh_expr["cloud_credits"]},
               SUBSTR(query_text,1,2000)        AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE warehouse_name = {wh_safe}
          AND start_time >= DATEADD('hours', -{lookback_hours}, CURRENT_TIMESTAMP())
          {company_filter}
        ORDER BY total_elapsed_time DESC LIMIT 200
    """, ttl_key=f"wh_detail_{key}_{warehouse_name}", tier="recent")
    if df_wh.empty:
        st.info("No recent query detail found for this warehouse.")
        return
    render_query_drilldown(df_wh, key=f"{key}_wh_query",
                           title=f"Warehouse Drill Down - {warehouse_name}")


# -- Entity drill-down ----------------------------------------------------------

def render_entity_query_drilldown(
    entity_value: str,
    key: str,
    entity_column: str = "warehouse_name",
    lookback_hours: int = 24,
):
    if not entity_value:
        return
    col = entity_column.lower()
    allowed = {
        "warehouse_name","user_name","role_name","database_name",
        "schema_name","query_id","query_tag",
        "database_schema","application_client","lineage_dimension",
    }
    if col not in allowed:
        st.info(f"Drill-down not configured for `{entity_column}`.")
        return
    value = sql_literal(str(entity_value))
    qh_expr = _query_history_detail_exprs()
    has_query_tag = bool(qh_expr.get("has_query_tag"))
    if col == "query_id":
        where_clause = f"query_id = {value}"
    elif col == "database_schema":
        where_clause = (
            "COALESCE(database_name,'UNKNOWN')||'.'||COALESCE(schema_name,'UNKNOWN') "
            f"= {value}"
        )
    elif col == "application_client":
        if not has_query_tag:
            st.info("Application/client drill-down needs QUERY_TAG access, which is not exposed in this Snowflake context.")
            return
        where_clause = f"COALESCE(query_tag, 'UNTAGGED') = {value}"
    elif col == "query_tag":
        if not has_query_tag:
            st.info("Query-tag drill-down needs QUERY_TAG access, which is not exposed in this Snowflake context.")
            return
        where_clause = f"COALESCE(query_tag, 'UNTAGGED') = {value}"
    elif col == "lineage_dimension":
        where_clause = (
            "COALESCE(REGEXP_SUBSTR(query_text,'CALL\\\\s+([^\\\\(]+)',1,1,'i',1), "
            f"query_type, 'ADHOC') = {value}"
        )
    else:
        where_clause = f"{col} = {value}"
    company_filter = " ".join(filter(None, [
        get_wh_filter_clause("warehouse_name"),
        get_db_filter_clause("database_name"),
        get_user_filter_clause("user_name"),
    ]))
    df_detail   = run_query(f"""
        SELECT query_id, user_name, role_name, warehouse_name, {qh_expr["warehouse_size"]}, database_name, schema_name,
               {qh_expr["query_tag"]},
               query_type, execution_status, start_time,
               total_elapsed_time/1000          AS elapsed_sec,
               compilation_time/1000            AS compile_sec,
               execution_time/1000              AS exec_sec,
               {qh_expr["queued_sec"]},
               {qh_expr["gb_scanned"]},
               {qh_expr["remote_spill_gb"]},
               {qh_expr["rows_produced"]},
               {qh_expr["cloud_credits"]},
               SUBSTR(query_text,1,4000)        AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {where_clause}
          AND start_time >= DATEADD('hours', -{lookback_hours}, CURRENT_TIMESTAMP())
          {company_filter}
        ORDER BY total_elapsed_time DESC LIMIT 300
    """, ttl_key=f"entity_{key}_{col}_{value}_{lookback_hours}", tier="recent")
    if df_detail.empty:
        st.info("No query detail found for the selected item.")
        return
    render_query_drilldown(df_detail, key=f"{key}_{col}_query",
                           title=f"Drill Down - {entity_column}: {entity_value}")


# -- Altair drillable bar chart -------------------------------------------------

def _selected_altair_value(event, selection_name: str, dimension: str):
    try:
        raw = getattr(event, "selection", None) or {}
        if hasattr(raw, "to_dict"):
            raw = raw.to_dict()
        candidates = []
        if isinstance(raw, dict):
            candidates.extend([raw.get(selection_name), raw.get(f"{selection_name}_selection")])
            candidates.extend(raw.values())
        for candidate in candidates:
            if isinstance(candidate, list) and candidate:
                first = candidate[0]
                if isinstance(first, dict):
                    return first.get(dimension)
            if isinstance(candidate, dict):
                if dimension in candidate:
                    return candidate.get(dimension)
                values = candidate.get("values")
                if isinstance(values, list) and values and isinstance(values[0], dict):
                    return values[0].get(dimension)
    except Exception:
        return None
    return None


def render_drillable_bar_chart(
    df: pd.DataFrame,
    dimension: str,
    measure: str,
    key: str,
    title: str = "",
    drilldown_column: str = None,
    lookback_hours: int = 24,
    top_n: int = 20,
):
    if df is None or df.empty or dimension not in df.columns or measure not in df.columns:
        return None

    chart_df = add_cost_companion_columns(rank_chart_frame(df, dimension, measure, top_n=top_n))
    if chart_df.empty:
        return None

    if title:
        st.subheader(title)

    alt = _altair()
    tooltips = [alt.Tooltip(f"{dimension}:N"), alt.Tooltip(f"{measure}:Q", format=",.2f")]
    cost_column = f"{str(measure).upper()}_COST_USD"
    if cost_column in chart_df.columns:
        tooltips.append(alt.Tooltip(f"{cost_column}:Q", title="Cost USD", format="$,.2f"))
    selection_name    = f"{key}_select"
    selection_factory = getattr(alt, "selection_point", alt.selection_single)
    selection         = selection_factory(fields=[dimension], name=selection_name, empty=False)
    chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
        .encode(
            x=alt.X(f"{measure}:Q", title=measure.replace("_"," ").title()),
            y=alt.Y(
                f"{dimension}:N",
                sort=alt.SortField(field=measure, order="descending"),
                title=None,
                axis=alt.Axis(labelLimit=260),
            ),
            color=alt.condition(selection, alt.value("#38bdf8"), alt.value("#475569")),
            tooltip=tooltips,
        )
    )
    chart = (
        chart.add_params(selection)
        if hasattr(chart, "add_params")
        else chart.add_selection(selection)
    )
    chart = chart.properties(height=_ranked_chart_height(len(chart_df)))

    selected = None
    try:
        event    = st.altair_chart(chart, width="stretch",
                                   on_select="rerun", key=f"{key}_chart")
        selected = _selected_altair_value(event, selection_name, dimension)
    except Exception:
        st.altair_chart(chart, width="stretch")

    options       = chart_df[dimension].astype(str).tolist()
    default_index = (
        options.index(str(selected)) if selected and str(selected) in options else 0
    )
    select_col, load_col = st.columns([4, 1])
    with select_col:
        selected = st.selectbox(
            "Drill into",
            options,
            index=default_index,
            key=f"{key}_drill_select",
        )
    requested_key = f"{key}_drill_requested"
    with load_col:
        st.write("")
        if st.button("Load", key=f"{key}_drill_load", width="stretch"):
            st.session_state[requested_key] = selected

    requested = st.session_state.get(requested_key)
    if requested not in options:
        st.session_state.pop(requested_key, None)
        requested = None
    if requested != selected:
        return selected

    back_col, selected_col = st.columns([1, 4])
    with back_col:
        if st.button("Back to chart", key=f"{key}_drill_back", width="stretch"):
            st.session_state.pop(requested_key, None)
            st.rerun()
    with selected_col:
        st.caption(f"Showing loaded detail for `{requested}`.")

    drill_col = drilldown_column or dimension.lower()
    if drill_col.lower() == "warehouse_name":
        render_warehouse_drilldown(requested, key=key, lookback_hours=lookback_hours)
    else:
        render_entity_query_drilldown(requested, key=key,
                                      entity_column=drill_col, lookback_hours=lookback_hours)
    return selected
