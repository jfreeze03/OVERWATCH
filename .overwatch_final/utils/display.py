# utils/display.py - chart and drill-down rendering helpers
import hashlib
import re
from collections.abc import Mapping
from typing import Any

import streamlit as st
import pandas as pd
from config import DAY_WINDOW_OPTIONS, DEFAULT_DAY_WINDOW
from sections.empty_states import render_chart_empty_state
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from .cache import clear_all_cache
from .cost import format_credits
from .compatibility import filter_existing_columns
from .downloads import download_csv, mark_loaded, show_loaded_time
from .query import format_snowflake_error, run_query, run_query_or_raise, sql_literal
from .company_filter import get_combined_filter_clause
from .helpers import safe_float
from .workflows import add_cost_companion_columns, prioritize_context_columns
from .workflows import apply_operator_status_labels
from .workflows import render_mode_selector, render_priority_dataframe
from utils.performance import query_budget_context


DISPLAY_VERSION = "2026-06-05-chart-drillback-cost-v1"
OVERWATCH_TIME_SERIES_PALETTE = ("#29B5E8", "#71D3DC", "#34d399", "#f59e0b", "#ef4444", "#c084fc")
RANKED_RATIO_METRICS: dict[str, dict[str, Any]] = {
    "TOKENS_PER_DOLLAR": {
        "aggregation": "ratio",
        "numerator": "TOTAL_TOKENS",
        "denominator": "COST_USD",
        "scale": 1,
        "precision": 2,
    },
    "COST_PER_1K_TOKENS_USD": {
        "aggregation": "ratio",
        "numerator": "COST_USD",
        "denominator": "TOTAL_TOKENS",
        "scale": 1000,
        "precision": 6,
    },
    "TOKENS_PER_REQUEST": {
        "aggregation": "ratio",
        "numerator": "TOTAL_TOKENS",
        "denominator": "TOTAL_REQUESTS",
        "scale": 1,
        "precision": 2,
    },
    "COST_PER_REQUEST_USD": {
        "aggregation": "ratio",
        "numerator": "COST_USD",
        "denominator": "TOTAL_REQUESTS",
        "scale": 1,
        "precision": 6,
    },
    "AI_CREDITS_PER_1K_TOKENS": {
        "aggregation": "ratio",
        "numerator": "TOTAL_CREDITS",
        "denominator": "TOTAL_TOKENS",
        "scale": 1000,
        "precision": 6,
    },
}


def _rank_metric_spec(column: str, metric_aggregations: Mapping[str, object] | None = None) -> dict[str, Any]:
    custom = (metric_aggregations or {}).get(column)
    if isinstance(custom, str):
        return {"aggregation": custom}
    if isinstance(custom, Mapping):
        return dict(custom)
    return dict(RANKED_RATIO_METRICS.get(str(column).upper(), {"aggregation": "sum"}))


def _safe_ratio_value(
    numerator: object,
    denominator: object,
    *,
    scale: float = 1.0,
    precision: int | None = None,
    source_confirmed_zero: bool = False,
) -> object:
    numerator_value = pd.to_numeric(pd.Series([numerator]), errors="coerce").iloc[0]
    denominator_value = pd.to_numeric(pd.Series([denominator]), errors="coerce").iloc[0]
    if pd.isna(numerator_value) or pd.isna(denominator_value) or float(denominator_value) == 0:
        return 0.0 if source_confirmed_zero else pd.NA
    value = float(numerator_value) / float(denominator_value) * float(scale or 1.0)
    return round(value, int(precision)) if precision is not None else value


def _looks_like_sensitive_identifier(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if re.fullmatch(r"\d+", text):
        return True
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", text):
        return True
    return bool(len(text) >= 18 and re.fullmatch(r"[A-Za-z0-9_-]+", text))


def _disambiguate_rank_labels(frame: pd.DataFrame, dimension: str, stable_key: str | None) -> pd.DataFrame:
    if frame.empty or not stable_key or stable_key not in frame.columns or dimension not in frame.columns:
        return frame
    result = frame.copy()
    labels = result[dimension].fillna("Unknown").astype(str)
    duplicate_mask = labels.duplicated(keep=False)
    if not duplicate_mask.any():
        result[dimension] = labels
        return result
    for label, indexes in result[duplicate_mask].groupby(labels[duplicate_mask], sort=False).groups.items():
        for ordinal, index in enumerate(indexes, start=1):
            stable_value = str(result.at[index, stable_key] or "").strip()
            suffix = str(ordinal) if _looks_like_sensitive_identifier(stable_value) else stable_value
            result.at[index, dimension] = f"{label} · {suffix}"
    result.loc[~duplicate_mask, dimension] = labels[~duplicate_mask]
    return result


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
    tooltip_columns: list[str] | tuple[str, ...] | None = None,
    stable_key: str | None = None,
    metric_aggregations: Mapping[str, object] | None = None,
    source_confirmed_zero: bool = False,
) -> pd.DataFrame:
    """Return a metric-ranked chart frame with one row per displayed dimension."""
    if df is None or df.empty or dimension not in df.columns:
        return pd.DataFrame(columns=[dimension, measure])
    requested_metrics = list(dict.fromkeys([measure, *(tooltip_columns or ())]))
    metric_specs = {column: _rank_metric_spec(column, metric_aggregations) for column in requested_metrics}
    required_columns = {dimension}
    if stable_key and stable_key in df.columns:
        required_columns.add(stable_key)
    for column, spec in metric_specs.items():
        if spec.get("aggregation") == "ratio":
            required_columns.add(str(spec.get("numerator") or ""))
            required_columns.add(str(spec.get("denominator") or ""))
        else:
            required_columns.add(column)
    required_columns.discard("")
    existing_columns = [column for column in required_columns if column in df.columns]
    chart_df = df[existing_columns].dropna(subset=[dimension]).copy()
    chart_df[dimension] = chart_df[dimension].astype(str)
    stable_key_used = stable_key if stable_key and stable_key in chart_df.columns else None
    group_columns = [stable_key_used] if stable_key_used else [dimension]
    for column in existing_columns:
        if column in {dimension, stable_key_used}:
            continue
        chart_df[column] = pd.to_numeric(chart_df[column], errors="coerce")
    additive_columns: set[str] = set()
    for column, spec in metric_specs.items():
        if spec.get("aggregation") == "ratio":
            numerator = str(spec.get("numerator") or "")
            denominator = str(spec.get("denominator") or "")
            if numerator in chart_df.columns:
                additive_columns.add(numerator)
            if denominator in chart_df.columns:
                additive_columns.add(denominator)
        elif column in chart_df.columns:
            additive_columns.add(column)
    chart_df = chart_df.replace([float("inf"), float("-inf")], pd.NA)
    measure_spec = metric_specs.get(measure, {})
    if measure_spec.get("aggregation") != "ratio" and measure in chart_df.columns:
        chart_df = chart_df.dropna(subset=[measure])
    if chart_df.empty:
        return pd.DataFrame(columns=[dimension, measure])
    aggregations: dict[str, object] = {column: "sum" for column in sorted(additive_columns)}
    if stable_key_used:
        aggregations[dimension] = "first"
    chart_df = chart_df.groupby(group_columns, as_index=False, dropna=False, sort=False).agg(aggregations)
    for column, spec in metric_specs.items():
        if spec.get("aggregation") != "ratio":
            if column not in chart_df.columns:
                chart_df[column] = pd.NA
            continue
        numerator = str(spec.get("numerator") or "")
        denominator = str(spec.get("denominator") or "")
        if numerator not in chart_df.columns or denominator not in chart_df.columns:
            chart_df[column] = pd.NA
            continue
        chart_df[column] = chart_df.apply(
            lambda row: _safe_ratio_value(
                row.get(numerator),
                row.get(denominator),
                scale=safe_float(spec.get("scale"), 1.0),
                precision=int(spec["precision"]) if spec.get("precision") is not None else None,
                source_confirmed_zero=source_confirmed_zero,
            ),
            axis=1,
        )
    chart_df = _disambiguate_rank_labels(chart_df, dimension, stable_key_used)
    chart_df = chart_df.replace([float("inf"), float("-inf")], pd.NA).dropna(subset=[measure])
    chart_df = chart_df.sort_values(measure, ascending=ascending, kind="mergesort")
    return chart_df.head(max(1, int(top_n or 20)))


def _ranked_chart_height(row_count: int) -> int:
    return max(180, min(520, 28 * int(row_count or 1) + 56))


def time_series_chart_frame(
    df: pd.DataFrame,
    time_column: str,
    value_column: str,
    *,
    series_column: str | None = None,
) -> pd.DataFrame:
    """Return a normalized time-series chart frame for OVERWATCH charts."""
    columns = [time_column, value_column]
    if series_column:
        columns.append(series_column)
    if df is None or df.empty or any(column not in df.columns for column in columns):
        return pd.DataFrame(columns=columns)
    chart_df = df[columns].copy()
    chart_df[time_column] = pd.to_datetime(chart_df[time_column], errors="coerce")
    chart_df[value_column] = pd.to_numeric(chart_df[value_column], errors="coerce")
    chart_df = chart_df.replace([float("inf"), float("-inf")], pd.NA)
    chart_df = chart_df.dropna(subset=[time_column, value_column])
    if series_column:
        chart_df[series_column] = chart_df[series_column].fillna("Unknown").astype(str)
        return chart_df.sort_values([time_column, series_column], kind="mergesort").reset_index(drop=True)
    return chart_df.sort_values(time_column, kind="mergesort").reset_index(drop=True)


def build_time_series_chart(
    chart_df: pd.DataFrame,
    time_column: str,
    value_column: str,
    *,
    series_column: str | None = None,
    title: str = "",
    area: bool = False,
):
    """Build a styled Altair time-series chart from a normalized chart frame."""
    alt = _altair()
    if chart_df is None or chart_df.empty:
        return None
    mark = (
        alt.Chart(chart_df).mark_area(opacity=0.22, line=True)
        if area
        else alt.Chart(chart_df).mark_line(point=True, strokeWidth=2.5)
    )
    tooltips = [
        alt.Tooltip(f"{time_column}:T", title=time_column.replace("_", " ").title()),
        alt.Tooltip(f"{value_column}:Q", title=value_column.replace("_", " ").title(), format=",.2f"),
    ]
    encoding = {
        "x": alt.X(f"{time_column}:T", title=None),
        "y": alt.Y(f"{value_column}:Q", title=value_column.replace("_", " ").title()),
        "tooltip": tooltips,
    }
    if series_column:
        encoding["color"] = alt.Color(
            f"{series_column}:N",
            scale=alt.Scale(range=list(OVERWATCH_TIME_SERIES_PALETTE)),
            title=None,
        )
        tooltips.insert(1, alt.Tooltip(f"{series_column}:N", title=series_column.replace("_", " ").title()))
    else:
        encoding["color"] = alt.value(OVERWATCH_TIME_SERIES_PALETTE[0])
    return mark.encode(**encoding).properties(title=title or None, height=260)


def render_time_series_chart(
    df: pd.DataFrame,
    time_column: str,
    value_column: str,
    *,
    series_column: str | None = None,
    title: str = "",
    area: bool = False,
) -> pd.DataFrame:
    """Render a styled OVERWATCH time-series chart and return plotted rows."""
    chart_df = time_series_chart_frame(
        df,
        time_column,
        value_column,
        series_column=series_column,
    )
    chart = build_time_series_chart(
        chart_df,
        time_column,
        value_column,
        series_column=series_column,
        title=title,
        area=area,
    )
    if chart is not None:
        st.altair_chart(chart, width="stretch")
    else:
        render_chart_empty_state(title or "No trend data", "No valid time-series rows are loaded for this scope.")
    return chart_df


def render_area_time_series_chart(
    df: pd.DataFrame,
    time_column: str,
    value_column: str,
    *,
    series_column: str | None = None,
    title: str = "",
) -> pd.DataFrame:
    """Render a styled OVERWATCH area time-series chart and return plotted rows."""
    return render_time_series_chart(
        df,
        time_column,
        value_column,
        series_column=series_column,
        title=title,
        area=True,
    )


def render_ranked_bar_chart(
    df: pd.DataFrame,
    dimension: str,
    measure: str,
    *,
    title: str = "",
    top_n: int = 20,
    color: str = "#38bdf8",
    tooltip_columns: list[str] | tuple[str, ...] | None = None,
    stable_key: str | None = None,
    metric_aggregations: Mapping[str, object] | None = None,
    source_confirmed_zero: bool = False,
) -> pd.DataFrame:
    """Render a horizontal top-to-bottom ranked bar chart and return plotted rows."""
    chart_df = add_cost_companion_columns(
        rank_chart_frame(
            df,
            dimension,
            measure,
            top_n=top_n,
            tooltip_columns=tooltip_columns,
            stable_key=stable_key,
            metric_aggregations=metric_aggregations,
            source_confirmed_zero=source_confirmed_zero,
        )
    )
    if chart_df.empty:
        render_chart_empty_state(title or "No ranked data", "No valid ranked rows are loaded for this scope.")
        return chart_df
    if title:
        st.subheader(title)

    alt = _altair()
    tooltips = [alt.Tooltip(f"{dimension}:N"), alt.Tooltip(f"{measure}:Q", format=",.2f")]
    cost_column = f"{str(measure).upper()}_COST_USD"
    if cost_column in chart_df.columns:
        tooltips.append(alt.Tooltip(f"{cost_column}:Q", title="Cost USD", format="$,.2f"))
    for column in tooltip_columns or ():
        if column in chart_df.columns and column not in {dimension, measure, cost_column}:
            upper_column = str(column).upper()
            if upper_column.endswith("_USD") or "COST" in upper_column:
                tooltip_format = "$,.4f"
            elif "TOKEN" in upper_column or "REQUEST" in upper_column:
                tooltip_format = ",.0f"
            else:
                tooltip_format = ",.2f"
            tooltips.append(
                alt.Tooltip(
                    f"{column}:Q",
                    title=str(column).replace("_", " ").title(),
                    format=tooltip_format,
                )
            )
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
    credit_price: float | None = None,
) -> str:
    """Render a chart or its backing table with a clear return path."""
    if title:
        render_escaped_bold_text(title)
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
                credit_price=credit_price,
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

def _statement_fingerprint(statement_text: object) -> str:
    """Return a short, stable statement fingerprint without exposing SQL text."""
    normalized = re.sub(r"\s+", " ", str(statement_text or "").strip())
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:12]

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

        fingerprint = _statement_fingerprint(row.get("QUERY_TEXT", ""))
        st.markdown("**Statement Summary**")
        if fingerprint:
            st.caption(
                f"Statement fingerprint: `{fingerprint}`. "
                "Full SQL text is hidden in the daily view."
            )
        else:
            st.caption("Statement text is not available for this row.")

        if st.button("Load operator stats", key=f"{key}_opstats"):
            try:
                with query_budget_context("advanced_diagnostics", section="Workload Operations", workflow="Query Drilldown", budget=1):
                    ops_df = run_query_or_raise(
                        f"SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS({sql_literal(qid)}))"
                    )
                st.dataframe(
                    apply_operator_status_labels(add_cost_companion_columns(ops_df)),
                    width="stretch",
                    height=350,
                )
            except Exception as e:
                st.info(f"Operator stats unavailable. {format_snowflake_error(e)}")


# -- Warehouse drill-down -------------------------------------------------------

def render_warehouse_drilldown(
    warehouse_name: str,
    key: str,
    lookback_hours: int = 24,
):
    if not warehouse_name:
        return
    wh_safe = sql_literal(warehouse_name)
    company_filter = get_combined_filter_clause(
        db_col="database_name",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
    )
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
    company_filter = get_combined_filter_clause(
        db_col="database_name",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
    )
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
