# sections/task_management.py — Task history, ETL audit framework, execute task
import streamlit as st
import pandas as pd
from utils import get_session, normalize_df, download_csv, safe_sql
from config import ETL_AUDIT_DB, ETL_AUDIT_SCHEMA, ETL_AUDIT_TABLE


def render():
    session = get_session()

    tab_history, tab_etl, tab_execute = st.tabs([
        "Task History", "ETL Audit", "Execute Task"
    ])

    # ── TASK HISTORY ──────────────────────────────────────────────────────────
    with tab_history:
        st.header("⚙️ Task Execution History")
        th_days = st.slider("Lookback (days)", 1, 30, 7, key="th_days")

        if st.button("Load Task Data", key="th_load"):
            # Task list
            try:
                df_tl = normalize_df(session.sql("""
                    SELECT name, database_name, schema_name, state,
                           schedule, warehouse, definition
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TASKS
                    ORDER BY name
                """).to_pandas())
                st.session_state["tg_list"] = df_tl
            except Exception:
                st.session_state["tg_list"] = pd.DataFrame()

            # Task history
            try:
                df_th = normalize_df(session.sql(f"""
                    SELECT name, state, scheduled_time, completed_time,
                           query_start_time, error_code, error_message,
                           DATEDIFF('second', query_start_time, completed_time) AS duration_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
                    WHERE scheduled_time >= DATEADD('days', -{th_days}, CURRENT_TIMESTAMP())
                    ORDER BY scheduled_time DESC
                    LIMIT 1000
                """).to_pandas())
                st.session_state["tg_hist"] = df_th
            except Exception:
                st.session_state["tg_hist"] = pd.DataFrame()

        tl = st.session_state.get("tg_list", pd.DataFrame())
        th = st.session_state.get("tg_hist", pd.DataFrame())

        if not tl.empty:
            c1, c2 = st.columns(2)
            c1.metric("Total Tasks", len(tl))
            active_tasks = tl[tl["STATE"] == "started"] if "STATE" in tl.columns else pd.DataFrame()
            c2.metric("Active (started)", len(active_tasks))

        if not th.empty:
            failed_tasks = th[th["STATE"] == "FAILED"] if "STATE" in th.columns else pd.DataFrame()
            succeeded    = th[th["STATE"] == "SUCCEEDED"] if "STATE" in th.columns else pd.DataFrame()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Runs",  len(th))
            c2.metric("Succeeded",   len(succeeded))
            c3.metric("Failed",      len(failed_tasks), delta_color="inverse")

            if not failed_tasks.empty:
                st.subheader("❌ Failed Tasks")
                st.dataframe(failed_tasks.head(20), use_container_width=True)

            st.subheader("Full History")
            st.dataframe(th, use_container_width=True, height=400)
            download_csv(th, "task_history.csv")

    # ── ETL AUDIT ─────────────────────────────────────────────────────────────
    with tab_etl:
        st.header("📋 ETL Audit Framework")
        st.caption(f"Custom ETL run tracking table: `{ETL_AUDIT_DB}.{ETL_AUDIT_SCHEMA}.{ETL_AUDIT_TABLE}`")

        # DDL setup
        etl_ddl = f"""-- Run once to create the ETL audit table
CREATE TABLE IF NOT EXISTS {ETL_AUDIT_DB}.{ETL_AUDIT_SCHEMA}.{ETL_AUDIT_TABLE} (
    RUN_ID          NUMBER AUTOINCREMENT PRIMARY KEY,
    RUN_START       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    RUN_END         TIMESTAMP_NTZ,
    PIPELINE_NAME   VARCHAR(500),
    STATUS          VARCHAR(50),   -- RUNNING | SUCCESS | FAILED
    ROWS_LOADED     NUMBER,
    ERROR_MESSAGE   VARCHAR(4000),
    RUN_BY          VARCHAR(200)
);"""
        with st.expander("📋 Setup DDL — run once to create audit table"):
            st.code(etl_ddl, language="sql")

        if st.button("Load ETL Audit Log", key="etl_load"):
            try:
                df_etl = normalize_df(session.sql(f"""
                    SELECT * FROM {ETL_AUDIT_DB}.{ETL_AUDIT_SCHEMA}.{ETL_AUDIT_TABLE}
                    ORDER BY RUN_START DESC LIMIT 500
                """).to_pandas())
                st.session_state["tm_df_etl"] = df_etl
            except Exception as e:
                st.info(f"Audit table not found — run the setup DDL above first. ({e})")

        if st.session_state.get("tm_df_etl") is not None and not st.session_state["tm_df_etl"].empty:
            df_e = st.session_state["tm_df_etl"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Runs", len(df_e))
            ok  = df_e[df_e["STATUS"] == "SUCCESS"] if "STATUS" in df_e.columns else pd.DataFrame()
            err = df_e[df_e["STATUS"] == "FAILED"]  if "STATUS" in df_e.columns else pd.DataFrame()
            c2.metric("Success", len(ok))
            c3.metric("Failed",  len(err), delta_color="inverse")
            st.dataframe(df_e, use_container_width=True)
            download_csv(df_e, "etl_audit.csv")

    # ── EXECUTE TASK ──────────────────────────────────────────────────────────
    with tab_execute:
        st.header("▶️ Execute Task On-Demand")
        st.caption("Select and manually trigger a task. Ensure dependencies are met before running.")

        tl = st.session_state.get("tg_list", pd.DataFrame())
        if tl.empty:
            st.warning("⬆️ Click **Load Task Data** in the Task History tab first.")
        else:
            task_names = tl["NAME"].unique().tolist() if "NAME" in tl.columns else []
            selected   = st.selectbox("Select task", task_names, key="exec_task_sel")

            if selected:
                row = tl[tl["NAME"] == selected].iloc[0] if len(tl[tl["NAME"] == selected]) else None
                if row is not None:
                    db   = row.get("DATABASE_NAME", "")
                    sch  = row.get("SCHEMA_NAME", "")
                    full = f"{db}.{sch}.{selected}"
                    st.info(f"Task: `{full}` | State: {row.get('STATE','N/A')} | Schedule: {row.get('SCHEDULE','N/A')}")
                    st.warning("⚠️ This runs the task immediately regardless of schedule.")

                    if st.button(f"▶️ Execute {selected}", type="primary", key="exec_task_btn"):
                        try:
                            session.sql(f"EXECUTE TASK {full}").collect()
                            st.success(f"✅ Task `{full}` triggered.")
                        except Exception as e:
                            st.error(f"Execution failed: {e}")
