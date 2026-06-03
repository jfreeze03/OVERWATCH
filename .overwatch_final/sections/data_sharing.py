# sections/data_sharing.py - Data transfer credits and shared databases
import pandas as pd
import streamlit as st
from utils import (
    get_active_company,
    get_db_filter_clause,
    format_credits,
    credits_to_dollars,
    download_csv,
    format_snowflake_error,
    run_query,
)
from utils.workflows import render_priority_dataframe


def _sharing_scope_meta(company: str, days: int | None = None) -> dict:
    meta = {"company": company}
    if days is not None:
        meta["days"] = int(days)
    return meta


def _load_transfer_history(company: str, days: int, *, show_errors: bool = True) -> bool:
    if company != "ALL":
        st.session_state["ds_df_dt"] = pd.DataFrame()
        st.session_state["ds_transfer_meta"] = _sharing_scope_meta(company, days)
        st.session_state["ds_transfer_error"] = ""
        return False
    try:
        df_dt = run_query(f"""
            SELECT source_cloud, source_region,
                   target_cloud, target_region,
                   DATE_TRUNC('day', start_time) AS day,
                   SUM(bytes_transferred)/POWER(1024,3) AS gb_transferred,
                   SUM(credits_used)                    AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.DATA_TRANSFER_HISTORY
            WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
            GROUP BY source_cloud, source_region, target_cloud, target_region, day
            ORDER BY credits DESC
        """, ttl_key=f"data_sharing_transfer_{company}_{days}", tier="standard")
        st.session_state["ds_df_dt"] = df_dt
        st.session_state["ds_transfer_meta"] = _sharing_scope_meta(company, days)
        st.session_state["ds_transfer_error"] = ""
        return True
    except Exception as exc:
        st.session_state["ds_df_dt"] = pd.DataFrame()
        st.session_state["ds_transfer_meta"] = _sharing_scope_meta(company, days)
        st.session_state["ds_transfer_error"] = format_snowflake_error(exc)
        if show_errors:
            st.warning(f"Data-transfer history unavailable in this role/context: {st.session_state['ds_transfer_error']}")
        return False


def _load_shared_databases(company: str, *, show_errors: bool = True) -> bool:
    try:
        df_db = run_query(f"""
            SELECT database_name, database_id, type,
                   created, last_altered,
                   comment
            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES
            WHERE type IN ('IMPORTED DATABASE', 'SHARE')
              {get_db_filter_clause("database_name")}
            ORDER BY created DESC
        """, ttl_key=f"data_sharing_databases_{company}", tier="standard")
        st.session_state["ds_df_shared_db"] = df_db
        st.session_state["ds_shared_meta"] = _sharing_scope_meta(company)
        st.session_state["ds_shared_error"] = ""
        return True
    except Exception as exc:
        st.session_state["ds_df_shared_db"] = pd.DataFrame()
        st.session_state["ds_shared_meta"] = _sharing_scope_meta(company)
        st.session_state["ds_shared_error"] = format_snowflake_error(exc)
        if show_errors:
            st.warning(f"Data-share metadata unavailable in this role/context: {st.session_state['ds_shared_error']}")
        return False


def render():
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()

    st.header("Data Sharing Monitor")
    st.caption("DATA_TRANSFER_HISTORY credit consumption and shared database visibility.")

    ds_days = st.slider("Lookback (days)", 1, 90, 30, key="ds_days")

    transfer_meta = _sharing_scope_meta(company, ds_days)
    shared_meta = _sharing_scope_meta(company)
    if (
        company == "ALL"
        and st.session_state.get("ds_transfer_meta") != transfer_meta
        and not st.session_state.get(f"ds_transfer_auto_attempted_{company}_{ds_days}")
    ):
        st.session_state[f"ds_transfer_auto_attempted_{company}_{ds_days}"] = True
        _load_transfer_history(company, ds_days, show_errors=False)
    if (
        st.session_state.get("ds_shared_meta") != shared_meta
        and not st.session_state.get(f"ds_shared_auto_attempted_{company}")
    ):
        st.session_state[f"ds_shared_auto_attempted_{company}"] = True
        _load_shared_databases(company, show_errors=False)

    c1, c2 = st.columns(2)
    with c1:
        if company != "ALL":
            st.info(
                "Data transfer history is account-level in Snowflake and does not expose "
                "a reliable ALFA/Trexis ownership column. Switch Company View to ALL for transfer costs."
            )
        elif st.button("Load Transfer History", key="ds_load"):
            _load_transfer_history(company, ds_days, show_errors=True)

    with c2:
        if st.button("Load Shared Databases", key="ds_db_load"):
            _load_shared_databases(company, show_errors=True)

    if st.session_state.get("ds_df_dt") is not None and not st.session_state["ds_df_dt"].empty:
        df_d = st.session_state["ds_df_dt"]
        total_cr = df_d["CREDITS"].sum()
        total_gb = df_d["GB_TRANSFERRED"].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total GB Transferred", f"{total_gb:,.1f}")
        c2.metric("Transfer Credits", format_credits(total_cr))
        c3.metric("Transfer Cost", f"${credits_to_dollars(total_cr, credit_price):,.2f}")
        c4.metric("Routes", f"{len(df_d[['SOURCE_REGION', 'TARGET_REGION']].drop_duplicates()):,}")
        st.subheader("Daily Transfer Trend")
        daily = df_d.groupby("DAY")[["GB_TRANSFERRED","CREDITS"]].sum().reset_index()
        st.line_chart(daily.set_index("DAY"))
        render_priority_dataframe(
            df_d,
            title="Data transfer cost drivers",
            priority_columns=[
                "SOURCE_CLOUD", "SOURCE_REGION", "TARGET_CLOUD", "TARGET_REGION",
                "DAY", "GB_TRANSFERRED", "CREDITS",
            ],
            sort_by=["CREDITS", "GB_TRANSFERRED"],
            ascending=[False, False],
            raw_label="All data transfer rows",
        )
        download_csv(df_d, "data_transfer_history.csv")
    elif st.session_state.get("ds_df_dt") is not None and company == "ALL":
        err = st.session_state.get("ds_transfer_error", "")
        st.info("No data-transfer credit usage is visible for the selected period.")
        if err:
            st.caption(err)

    if st.session_state.get("ds_df_shared_db") is not None and not st.session_state["ds_df_shared_db"].empty:
        df_shared = st.session_state["ds_df_shared_db"]
        last_altered = pd.to_datetime(df_shared.get("LAST_ALTERED"), errors="coerce")
        if last_altered is not None:
            df_shared = df_shared.copy()
            df_shared["DAYS_SINCE_ALTERED"] = (
                pd.Timestamp.now(tz=None) - last_altered.dt.tz_localize(None)
            ).dt.days
        imported = int((df_shared.get("TYPE", pd.Series(dtype=str)).fillna("").astype(str).str.upper() == "IMPORTED DATABASE").sum())
        share_type = int((df_shared.get("TYPE", pd.Series(dtype=str)).fillna("").astype(str).str.upper() == "SHARE").sum())
        stale = int((df_shared.get("DAYS_SINCE_ALTERED", pd.Series(dtype=float)).fillna(0) >= 90).sum())
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Shared Objects", f"{len(df_shared):,}")
        d2.metric("Imported DBs", f"{imported:,}")
        d3.metric("Share Rows", f"{share_type:,}")
        d4.metric("90d No Change", f"{stale:,}", delta_color="inverse")
        st.subheader("Shared / Imported Databases")
        render_priority_dataframe(
            df_shared,
            title="Shared/imported databases",
            priority_columns=["DATABASE_NAME", "TYPE", "CREATED", "LAST_ALTERED", "DAYS_SINCE_ALTERED", "COMMENT"],
            sort_by=["LAST_ALTERED", "CREATED"],
            ascending=[False, False],
            raw_label="All shared database rows",
        )
        download_csv(df_shared, "shared_databases.csv")
    elif st.session_state.get("ds_df_shared_db") is not None:
        err = st.session_state.get("ds_shared_error", "")
        st.info("No shared or imported databases are visible for the selected company scope.")
        if err:
            st.caption(err)
