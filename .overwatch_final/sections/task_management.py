# sections/task_management.py — Task history, ETL audit framework, execute task
import streamlit as st
import pandas as pd
from utils import (
    build_action_queue_ddl,
    download_csv,
    get_session,
    make_action_id,
    normalize_df,
    run_query,
    safe_identifier,
    upsert_actions,
)
from config import ETL_AUDIT_DB, ETL_AUDIT_SCHEMA, ETL_AUDIT_TABLE


def _queue_task_findings(session, df: pd.DataFrame, source: str) -> None:
    if df is None or df.empty:
        st.info("No task findings to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in df.head(200).iterrows():
        name = str(row.get("NAME") or row.get("PIPELINE_NAME") or "Unknown task")
        err = str(row.get("ERROR_MESSAGE") or "")[:1000]
        state = str(row.get("STATE") or row.get("STATUS") or "FAILED")
        finding = f"{name} finished with {state}"
        if err:
            finding += f": {err[:250]}"
        actions.append({
            "Action ID": make_action_id("Task Reliability", name, finding),
            "Source": source,
            "Severity": "High",
            "Category": "Reliability",
            "Entity Type": "Task/Pipeline",
            "Entity": name,
            "Owner": "Data Engineering",
            "Finding": finding,
            "Action": "Review error message, fix upstream dependency or SQL failure, then retry the task/pipeline.",
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": f"-- Review task or pipeline: {name}\n-- EXECUTE TASK <database>.<schema>.{safe_identifier(name)};",
            "Proof Query": "TASK_HISTORY or ETL audit failure row.",
            "Company": company,
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} task reliability findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {e}")
        st.download_button(
            "Download Action Queue DDL",
            build_action_queue_ddl(),
            file_name="overwatch_action_queue_setup.sql",
            mime="text/plain",
            key=f"tm_queue_ddl_{source}",
        )


def _qualified_name(*parts: str) -> str:
    return ".".join(f'"{str(part).replace(chr(34), chr(34) + chr(34))}"' for part in parts)


def _show_tasks(session) -> pd.DataFrame:
    try:
        df = normalize_df(session.sql("SHOW TASKS IN ACCOUNT").to_pandas())
    except Exception:
        return pd.DataFrame()
    for col in ["NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "SCHEDULE", "WAREHOUSE", "DEFINITION"]:
        if col not in df.columns:
            df[col] = ""
    return df


ETL_AUDIT_FQN = (
    f"{safe_identifier(ETL_AUDIT_DB)}."
    f"{safe_identifier(ETL_AUDIT_SCHEMA)}."
    f"{safe_identifier(ETL_AUDIT_TABLE)}"
)


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
                df_tl = _show_tasks(session)
                st.session_state["tg_list"] = df_tl
            except Exception:
                st.session_state["tg_list"] = pd.DataFrame()

            # Task history
            try:
                df_th = run_query(f"""
                    SELECT name, state, scheduled_time, completed_time,
                           query_start_time, error_code, error_message,
                           DATEDIFF('second', query_start_time, completed_time) AS duration_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
                    WHERE scheduled_time >= DATEADD('day', -{th_days}, CURRENT_TIMESTAMP())
                    ORDER BY scheduled_time DESC
                    LIMIT 1000
                """, ttl_key=f"task_management_history_{th_days}", tier="standard")
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
                if st.button("Save failed tasks to Action Queue", key="tm_failed_queue"):
                    _queue_task_findings(session, failed_tasks, "Task Management - Task History")

            st.subheader("Full History")
            st.dataframe(th, use_container_width=True, height=400)
            download_csv(th, "task_history.csv")

    # ── ETL AUDIT ─────────────────────────────────────────────────────────────
    with tab_etl:
        st.header("📋 ETL Audit Framework")
        st.caption(f"Custom ETL run tracking table: `{ETL_AUDIT_FQN}`")

        # DDL setup
        etl_ddl = f"""-- Run once to create the ETL audit table
CREATE TABLE IF NOT EXISTS {ETL_AUDIT_FQN} (
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
                df_etl = run_query(f"""
                    SELECT * FROM {ETL_AUDIT_FQN}
                    ORDER BY RUN_START DESC LIMIT 500
                """, ttl_key="task_management_etl_audit", tier="standard")
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
            if not err.empty and st.button("Save failed ETL runs to Action Queue", key="tm_etl_queue"):
                _queue_task_findings(session, err, "Task Management - ETL Audit")

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
                    full = _qualified_name(db, sch, selected)
                    st.info(f"Task: `{full}` | State: {row.get('STATE','N/A')} | Schedule: {row.get('SCHEDULE','N/A')}")
                    st.warning("⚠️ This runs the task immediately regardless of schedule.")

                    exec_confirmed = st.text_input(
                        "Type EXECUTE to enable task run",
                        key=f"exec_task_confirm_{selected}",
                    ) == "EXECUTE"

                    if st.button(
                        f"▶️ Execute {selected}",
                        type="primary",
                        key="exec_task_btn",
                        disabled=not exec_confirmed,
                    ):
                        try:
                            session.sql(f"EXECUTE TASK {full}").collect()
                            st.success(f"✅ Task `{full}` triggered.")
                        except Exception as e:
                            st.error(f"Execution failed: {e}")
