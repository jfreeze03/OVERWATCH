# utils/display.py — Charts, dataframe wrappers, CSV export, drill-downs
# FIXES vs previous version:
#   1. clear_all_cache() clears cached data while preserving operator context
#      and resetting the session TTL marker.
#   2. safe_sql() applied to qid in render_query_drilldown operator stats call
#      (was a bare string embed — low risk but now consistent).
#   3. st.dataframe() in fallback path now includes use_container_width=True.
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
from .cost import format_credits
from .compatibility import filter_existing_columns
from .query import format_snowflake_error, run_query, run_query_or_raise, sql_literal
from .company_filter import get_db_filter_clause, get_user_filter_clause, get_wh_filter_clause
from .helpers import safe_float
from .state_keys import PRESERVE_STATE_EXACT, PRESERVE_STATE_PREFIXES

CHART_COLORS = [
    '#38bdf8','#818cf8','#c084fc','#f472b6',
    '#fb923c','#4ade80','#fbbf24','#22d3ee',
]


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


# ── CSV Export ─────────────────────────────────────────────────────────────────

def download_csv(df: pd.DataFrame, filename: str, label: str = "📥 Export CSV"):
    if df is not None and not df.empty:
        st.download_button(
            label, df.to_csv(index=False),
            file_name=filename, mime="text/csv",
            key=f"dl_{filename}_{id(df)}",
        )


# ── Load timestamps ────────────────────────────────────────────────────────────

def mark_loaded(key: str):
    st.session_state[f"_ts_{key}"] = datetime.now().strftime('%H:%M:%S')


def show_loaded_time(key: str):
    ts = st.session_state.get(f"_ts_{key}")
    if ts:
        st.caption(f"📅 Last loaded: {ts}")


# ── Cache + session clearing ───────────────────────────────────────────────────

_METADATA_CACHE_PREFIXES = (
    "_overwatch_available_columns",
    "_overwatch_unavailable_column_views",
    "_overwatch_column_probe",
    "_overwatch_qh_detail_exprs",
)


def clear_all_cache(
    *,
    clear_streamlit_cache: bool = True,
    clear_metadata: bool = True,
):
    """
    Clear all OVERWATCH cached data from session state.
    Preserves settings, navigation, company scope, and operator modes while
    resetting the session TTL clock.

    Routine filter/metric changes should pass clear_streamlit_cache=False so
    scoped st.cache_data entries can be reused when their query context still
    matches. The top-level Refresh button keeps the default hard purge.
    """
    transient_prefixes = (
        "_data_", "_ts_", "df_", "_refresh_salt_", "_sec_",
        "_overwatch_query_", "alert_center_", "cortex_", "cost_contract_", "cc_", "ah_", "cm_", "ds_", "dba_",
        "lm_", "mc_", "ocm_", "opt_", "qa_", "qs_", "rec_", "sec_", "spcs_",
        "stor_", "spt_", "sp_ops_", "sp_sla_", "tm_", "task_ops_", "task_sla_",
        "pipe_", "qw_", "sf_value_",
        "wh_", "uo_", "aa_", "dd_", "svc_",
        "contract_", "topology_", "recommendations", "anomalies",
        "health_data", "morning_data", "tg_list", "tg_hist", "cm_base_",
        "change_drift_summary", "change_drift_exceptions", "change_drift_meta",
        "change_drift_proof_sql", "security_posture_summary",
        "security_posture_exceptions", "security_posture_meta",
        "security_posture_proof_sql",
    )
    if clear_metadata:
        transient_prefixes = transient_prefixes + _METADATA_CACHE_PREFIXES
    keys_to_remove = [
        k for k in list(st.session_state.keys())
        if k not in PRESERVE_STATE_EXACT
        and not any(k.startswith(p) for p in PRESERVE_STATE_PREFIXES)
        and any(k.startswith(p) for p in transient_prefixes)
    ]
    for k in keys_to_remove:
        del st.session_state[k]

    # Reset the TTL timestamp; get_session() will stamp an existing session
    # without paying for an immediate SELECT 1 check.
    st.session_state.pop("_sf_session_created_at", None)

    if clear_streamlit_cache:
        try:
            st.cache_data.clear()
        except Exception:
            pass


# ── Query drill-down ───────────────────────────────────────────────────────────

def render_query_drilldown(
    df: pd.DataFrame,
    key: str,
    title: str = "🔎 Query Drill Down",
):
    """Interactive single-row drill-down with operator statistics."""
    if df is None or df.empty or "QUERY_ID" not in df.columns:
        return

    st.subheader(title)
    grid_df = df.head(1000)
    if len(df) > len(grid_df):
        st.caption(f"Showing the first {len(grid_df):,} rows for fast selection. Narrow filters to inspect deeper rows.")
    try:
        event = st.dataframe(
            grid_df,
            use_container_width=True,
            height=380,
            selection_mode="single-row",
            on_select="rerun",
            key=f"{key}_grid",
        )
        selected_rows = event.selection.rows
    except Exception:
        st.dataframe(grid_df, use_container_width=True, height=380)
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
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("User",       str(row.get("USER_NAME","N/A")))
        wh_name = str(row.get("WAREHOUSE_NAME","N/A"))
        wh_size = str(row.get("WAREHOUSE_SIZE","") or "")
        m2.metric("Warehouse", f"{wh_name} ({wh_size})" if wh_size else wh_name)
        m3.metric("Elapsed Sec",f"{safe_float(row.get('ELAPSED_SEC',0)):,.1f}")
        est_cr = safe_float(row.get("TOTAL_EST_CREDITS", row.get("EST_COMPUTE_CREDITS",0)))
        m4.metric("Est. Credits", format_credits(est_cr))

        st.markdown("**SQL Text**")
        st.code(str(row.get("QUERY_TEXT","")), language="sql")

        from .session import get_session
        _session = get_session()

        if st.button("Load operator stats", key=f"{key}_opstats"):
            try:
                ops_df = run_query_or_raise(
                    f"SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS({sql_literal(qid)}))"
                )
                st.dataframe(ops_df, use_container_width=True, height=350)
            except Exception as e:
                st.info(f"Operator stats unavailable: {format_snowflake_error(e)}")


# ── Warehouse drill-down ───────────────────────────────────────────────────────

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
        SELECT query_id, user_name, warehouse_name, {qh_expr["warehouse_size"]}, execution_status, start_time,
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
                           title=f"🔎 Warehouse Drill Down — {warehouse_name}")


# ── Entity drill-down ──────────────────────────────────────────────────────────

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
                           title=f"Drill Down — {entity_column}: {entity_value}")


# ── Altair drillable bar chart ─────────────────────────────────────────────────

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

    chart_df = df[[dimension, measure]].dropna().copy()
    chart_df[measure] = pd.to_numeric(chart_df[measure], errors="coerce").fillna(0)
    chart_df = chart_df.sort_values(measure, ascending=False).head(top_n)
    if chart_df.empty:
        return None

    if title:
        st.subheader(title)

    selection_name    = f"{key}_select"
    selection_factory = getattr(alt, "selection_point", alt.selection_single)
    selection         = selection_factory(fields=[dimension], name=selection_name, empty=False)
    chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(f"{dimension}:N", sort="-y", title=None),
            y=alt.Y(f"{measure}:Q", title=measure.replace("_"," ").title()),
            color=alt.condition(selection, alt.value("#38bdf8"), alt.value("#475569")),
            tooltip=[alt.Tooltip(f"{dimension}:N"), alt.Tooltip(f"{measure}:Q", format=",.2f")],
        )
    )
    chart = (
        chart.add_params(selection)
        if hasattr(chart, "add_params")
        else chart.add_selection(selection)
    )
    chart = chart.properties(height=320)

    selected = None
    try:
        event    = st.altair_chart(chart, use_container_width=True,
                                   on_select="rerun", key=f"{key}_chart")
        selected = _selected_altair_value(event, selection_name, dimension)
    except Exception:
        st.altair_chart(chart, use_container_width=True)

    options       = chart_df[dimension].astype(str).tolist()
    default_index = (
        options.index(str(selected)) if selected and str(selected) in options else 0
    )
    selected = st.selectbox("Drill into", options, index=default_index,
                            key=f"{key}_drill_select")

    drill_col = drilldown_column or dimension.lower()
    if drill_col.lower() == "warehouse_name":
        render_warehouse_drilldown(selected, key=key, lookback_hours=lookback_hours)
    else:
        render_entity_query_drilldown(selected, key=key,
                                      entity_column=drill_col, lookback_hours=lookback_hours)
    return selected
