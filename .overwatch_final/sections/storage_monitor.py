# sections/storage_monitor.py - Storage overview, data freshness, iceberg, egress
import streamlit as st
from config import DEFAULTS
from sections.shell_helpers import render_shell_snapshot
from utils import (
    day_window_selectbox,
    defer_source_note,
    get_active_company,
    get_db_filter_clause,
    load_shared_storage_db_detail,
    load_shared_storage_trend,
    metric_confidence_label,
    freshness_note,
    download_csv,
    format_snowflake_error,
    render_chart_with_data_toggle,
    run_query,
    safe_float,
)
from utils.workflows import render_priority_dataframe


LIVE_STORAGE_FALLBACK_MAX_DAYS = 90


def _load_storage_trend(stor_days: int, company: str, *, allow_live_fallback: bool = False) -> bool:
    result = load_shared_storage_trend(
        stor_days,
        company,
        allow_live_fallback=allow_live_fallback,
        max_live_days=LIVE_STORAGE_FALLBACK_MAX_DAYS,
        section="Storage Monitor",
    )
    if result.data.empty:
        return False
    st.session_state["stor_df_stor"] = result.data
    st.session_state["stor_source"] = result.source
    st.session_state["stor_meta"] = {"company": company, "days": int(result.effective_days or stor_days)}
    return True


def render():
    storage_cost_per_tb = st.session_state.get("storage_cost_per_tb", DEFAULTS["storage_cost_per_tb"])
    company = get_active_company()

    st.subheader("Storage Monitor")
    st.caption("Database & stage storage with cost estimates ($23/TB/month default).")

    stor_days = day_window_selectbox("Lookback", key="stor_days", default=90)
    stor_meta = {"company": company, "days": int(stor_days)}

    if (
        st.session_state.get("stor_meta") != stor_meta
        and st.session_state.get("stor_autoload_failed_meta") != stor_meta
    ):
        try:
            if not _load_storage_trend(stor_days, company, allow_live_fallback=False):
                st.session_state["stor_autoload_failed_meta"] = stor_meta
        except Exception:
            st.session_state["stor_autoload_failed_meta"] = stor_meta

    if st.button("Load Storage Data", key="stor_load"):
        try:
            if not _load_storage_trend(stor_days, company, allow_live_fallback=True):
                raise RuntimeError("Storage summary returned no rows.")
            if company != "ALL":
                st.info("Stage storage is account-level in Snowflake, so this company view shows database and failsafe storage only.")
            fallback_days = min(int(stor_days), LIVE_STORAGE_FALLBACK_MAX_DAYS)
            if int(stor_days) > fallback_days and st.session_state.get("stor_source", "").startswith("Live fallback"):
                st.info(
                    f"Live storage fallback is capped at {fallback_days} days. "
                    "Use the fast storage summary for longer trends."
                )
        except Exception as e:
            st.warning(f"Storage data unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("stor_df_stor") is not None and not st.session_state["stor_df_stor"].empty:
        df_st = st.session_state["stor_df_stor"]
        latest = df_st.iloc[-1] if not df_st.empty else None

        if latest is not None:
            total_tb = safe_float(latest.get("TOTAL_STORAGE_TB", 0))
            render_shell_snapshot((
                ("Database GB", f"{safe_float(latest.get('STORAGE_GB', 0)):,.1f}"),
                ("Failsafe GB", f"{safe_float(latest.get('FAILSAFE_GB', 0)):,.1f}"),
                ("Stage GB", f"{safe_float(latest.get('STAGE_GB', 0)):,.1f}"),
                ("Est Monthly Cost", f"${total_tb * storage_cost_per_tb:,.2f}"),
            ))
            confidence = "account-wide" if company != "ALL" else "exact"
            defer_source_note(
                metric_confidence_label(confidence),
                st.session_state.get("stor_source", "SNOWFLAKE.ACCOUNT_USAGE"),
                freshness_note("ACCOUNT_USAGE"),
            )

        if "TOTAL_STORAGE_TB" not in df_st.columns:
            df_st["TOTAL_STORAGE_TB"] = [
                (
                    safe_float(row.get("STORAGE_GB", 0))
                    + safe_float(row.get("FAILSAFE_GB", 0))
                    + safe_float(row.get("STAGE_GB", 0))
                ) / 1024
                for _, row in df_st.iterrows()
            ]
        df_st["EST_MONTHLY_COST"] = df_st["TOTAL_STORAGE_TB"].apply(
            lambda value: safe_float(value) * storage_cost_per_tb
        )
        render_chart_with_data_toggle(
            "Storage Trend",
            "storage_trend",
            lambda: st.area_chart(df_st.set_index("USAGE_DATE")[["STORAGE_GB","FAILSAFE_GB","STAGE_GB"]]),
            df_st,
            priority_columns=[
                "USAGE_DATE", "STORAGE_GB", "FAILSAFE_GB", "STAGE_GB",
                "TOTAL_STORAGE_TB", "EST_MONTHLY_COST",
            ],
            sort_by=["USAGE_DATE"],
            ascending=True,
            max_rows=90,
            raw_label="All storage trend rows",
        )

        # Per-database breakdown
        st.divider()
        st.subheader("Per-Database Storage")
        if st.button("Load DB Detail", key="stor_db_detail"):
            try:
                result = load_shared_storage_db_detail(company, section="Storage Monitor")
                if result.data.empty:
                    raise RuntimeError(result.message or "Storage detail returned no rows.")
                df_db = result.data
                st.session_state["stor_df_db_detail"] = df_db
                defer_source_note(result.source)
                render_priority_dataframe(
                    df_db,
                    title="Largest databases by storage",
                    priority_columns=[
                        "DATABASE_NAME", "USAGE_DATE", "DATABASE_GB",
                        "STORAGE_GB", "FAILSAFE_GB", "TOTAL_STORAGE_TB",
                    ],
                    sort_by=["DATABASE_GB", "STORAGE_GB", "TOTAL_STORAGE_TB", "FAILSAFE_GB"],
                    ascending=[False, False, False, False],
                    raw_label="All database storage rows",
                )
                download_csv(df_db, "db_storage_detail.csv")
            except Exception as e:
                st.warning(f"Large table data unavailable in this role/context: {format_snowflake_error(e)}")

        download_csv(df_st, "storage_trend.csv")

    # Table-level storage
    st.divider()
    st.subheader("Table Storage Metrics (Top 50 by size)")
    if st.button("Load Table Metrics", key="tbl_stor_load"):
        try:
            df_tbl = run_query(f"""
                SELECT table_catalog, table_schema, table_name,
                       active_bytes/POWER(1024,3)          AS active_gb,
                       time_travel_bytes/POWER(1024,3)     AS time_travel_gb,
                       failsafe_bytes/POWER(1024,3)        AS failsafe_gb,
                       retained_for_clone_bytes/POWER(1024,3) AS clone_gb
                FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
                WHERE (deleted IS NULL OR deleted = FALSE)
                  {get_db_filter_clause("table_catalog")}
                ORDER BY active_gb DESC
                LIMIT 50
            """, ttl_key=f"storage_table_metrics_{get_active_company()}", tier="standard")
            st.session_state["stor_df_table_metrics"] = df_tbl
            render_priority_dataframe(
                df_tbl,
                title="Largest table storage consumers",
                priority_columns=[
                    "TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME", "ACTIVE_GB",
                    "TIME_TRAVEL_GB", "FAILSAFE_GB", "CLONE_GB",
                ],
                sort_by=["ACTIVE_GB", "TIME_TRAVEL_GB", "FAILSAFE_GB"],
                ascending=[False, False, False],
                raw_label="All table storage rows",
            )
            download_csv(df_tbl, "table_storage.csv")
        except Exception as e:
            st.warning(f"Time Travel/Failsafe data unavailable in this role/context: {format_snowflake_error(e)}")
