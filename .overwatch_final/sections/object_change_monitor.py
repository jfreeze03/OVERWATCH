# sections/object_change_monitor.py - Who changed what?
import streamlit as st
from utils import (
    build_action_queue_ddl,
    download_csv,
    get_global_filter_clause,
    get_session,
    make_action_id,
    run_query,
    sql_literal,
    upsert_actions,
)


def _active_company() -> str:
    return st.session_state.get("active_company", "ALFA")


def _queue_changes(session, df, source: str, category: str, entity_type: str, severity: str) -> None:
    if df is None or df.empty:
        st.info("Nothing to queue from this result set.")
        return
    actions = []
    company = _active_company()
    for _, row in df.head(200).iterrows():
        entity = (
            row.get("DATABASE_NAME")
            or row.get("SCHEMA_NAME")
            or row.get("USER_NAME")
            or row.get("QUERY_ID")
            or "Snowflake account"
        )
        change_type = str(row.get("CHANGE_TYPE") or row.get("DRIFT_INDICATOR") or category)
        qid = str(row.get("QUERY_ID") or "")
        finding = f"{change_type} by {row.get('USER_NAME', 'unknown')} at {row.get('START_TIME', '')}"
        actions.append({
            "Action ID": make_action_id(category, str(entity), f"{finding}|{qid}"),
            "Source": source,
            "Severity": severity,
            "Category": category,
            "Entity Type": entity_type,
            "Entity": str(entity),
            "Owner": "DBA",
            "Finding": finding,
            "Action": "Review change for approval, ownership, policy impact, and drift risk.",
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "-- Review the captured query text before reverting or approving this change.",
            "Proof Query": f"QUERY_HISTORY query_id = '{qid}'",
            "Company": company,
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {e}")
        st.download_button(
            "Download Action Queue DDL",
            build_action_queue_ddl(),
            file_name="overwatch_action_queue_setup.sql",
            mime="text/plain",
            key=f"ocm_queue_ddl_{source}",
        )


def render():
    session = get_session()
    company = _active_company()
    st.header("Who Changed What?")
    st.caption("DDL, grants, roles, policy changes, owner changes, and Terraform drift indicators.")

    days = st.slider("Lookback (days)", 1, 90, 14, key="ocm_days")
    row_limit = st.slider("Max rows per scan", 100, 1000, 500, step=100, key="ocm_row_limit")
    text_filter = st.text_input("Filter query/object text", key="ocm_filter")
    filter_clause = f"AND query_text ILIKE {sql_literal('%' + text_filter + '%')}" if text_filter else ""
    company_filter = get_global_filter_clause(
        date_col=None,
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )

    tab_ddl, tab_access, tab_policy, tab_drift = st.tabs([
        "Objects", "Grants & Roles", "Policies & Tags", "Terraform Drift"
    ])

    with tab_ddl:
        if st.button("Load Object Changes", key="ocm_obj_load"):
            try:
                st.session_state["ocm_df_object_changes"] = run_query(f"""
                SELECT query_id, user_name, role_name, warehouse_name, database_name, schema_name,
                       start_time,
                       CASE
                         WHEN query_text ILIKE 'CREATE%TABLE%' THEN 'CREATE TABLE'
                         WHEN query_text ILIKE 'ALTER%TABLE%' THEN 'ALTER TABLE'
                         WHEN query_text ILIKE 'DROP%TABLE%' THEN 'DROP TABLE'
                         WHEN query_text ILIKE 'CREATE%VIEW%' THEN 'CREATE VIEW'
                         WHEN query_text ILIKE 'ALTER%VIEW%' THEN 'ALTER VIEW'
                         WHEN query_text ILIKE 'DROP%VIEW%' THEN 'DROP VIEW'
                         WHEN query_text ILIKE 'CREATE%PROCEDURE%' THEN 'CREATE PROCEDURE'
                         WHEN query_text ILIKE 'ALTER%PROCEDURE%' THEN 'ALTER PROCEDURE'
                         WHEN query_text ILIKE 'DROP%PROCEDURE%' THEN 'DROP PROCEDURE'
                         WHEN query_text ILIKE 'CREATE%TASK%' THEN 'CREATE TASK'
                         WHEN query_text ILIKE 'ALTER%TASK%' THEN 'ALTER TASK'
                         WHEN query_text ILIKE 'DROP%TASK%' THEN 'DROP TASK'
                         ELSE query_type
                       END AS change_type,
                       SUBSTR(query_text, 1, 1500) AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND (
                    query_text ILIKE 'CREATE%TABLE%' OR query_text ILIKE 'ALTER%TABLE%' OR query_text ILIKE 'DROP%TABLE%'
                    OR query_text ILIKE 'CREATE%VIEW%' OR query_text ILIKE 'ALTER%VIEW%' OR query_text ILIKE 'DROP%VIEW%'
                    OR query_text ILIKE 'CREATE%PROCEDURE%' OR query_text ILIKE 'ALTER%PROCEDURE%' OR query_text ILIKE 'DROP%PROCEDURE%'
                    OR query_text ILIKE 'CREATE%TASK%' OR query_text ILIKE 'ALTER%TASK%' OR query_text ILIKE 'DROP%TASK%'
                  )
                  {company_filter}
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT {row_limit}
                """, ttl_key=f"ocm_objects_{company}_{days}_{text_filter}_{row_limit}", tier="standard")
            except Exception as e:
                st.warning(f"Object change scan unavailable in this role/context: {e}")
        if st.session_state.get("ocm_df_object_changes") is not None:
            df = st.session_state["ocm_df_object_changes"]
            if not df.empty:
                st.dataframe(df.groupby(["CHANGE_TYPE", "USER_NAME"]).size().reset_index(name="COUNT"), use_container_width=True)
            st.dataframe(df, use_container_width=True)
            download_csv(df, "object_changes.csv")
            if st.button("Save object changes to Action Queue", key="ocm_obj_queue"):
                _queue_changes(session, df, "Object Change Monitor", "Governance", "Object", "Medium")

    with tab_access:
        if st.button("Load Grant / Role Changes", key="ocm_grant_load"):
            try:
                st.session_state["ocm_df_access_changes"] = run_query(f"""
                SELECT query_id, user_name, role_name, start_time,
                       CASE
                         WHEN query_text ILIKE '%OWNERSHIP%' THEN 'OWNER CHANGE'
                         WHEN query_text ILIKE 'GRANT%' THEN 'GRANT'
                         WHEN query_text ILIKE 'REVOKE%' THEN 'REVOKE'
                         WHEN query_text ILIKE 'CREATE%ROLE%' THEN 'CREATE ROLE'
                         WHEN query_text ILIKE 'ALTER%ROLE%' THEN 'ALTER ROLE'
                         WHEN query_text ILIKE 'DROP%ROLE%' THEN 'DROP ROLE'
                         ELSE query_type
                       END AS change_type,
                       SUBSTR(query_text, 1, 1500) AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND (query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
                       OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%')
                  {company_filter}
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT {row_limit}
                """, ttl_key=f"ocm_access_{company}_{days}_{text_filter}_{row_limit}", tier="standard")
            except Exception as e:
                st.warning(f"Access change scan unavailable in this role/context: {e}")
        if st.session_state.get("ocm_df_access_changes") is not None:
            df = st.session_state["ocm_df_access_changes"]
            st.dataframe(df, use_container_width=True)
            if st.button("Save access changes to Action Queue", key="ocm_access_queue"):
                _queue_changes(session, df, "Access Change Monitor", "Security", "Grant/Role", "High")

    with tab_policy:
        if st.button("Load Masking / Tag Policy Changes", key="ocm_policy_load"):
            try:
                st.session_state["ocm_df_policy_changes"] = run_query(f"""
                SELECT query_id, user_name, role_name, start_time,
                       CASE
                         WHEN query_text ILIKE '%MASKING POLICY%' THEN 'MASKING POLICY'
                         WHEN query_text ILIKE '%TAG%' THEN 'TAG POLICY'
                         WHEN query_text ILIKE '%ROW ACCESS POLICY%' THEN 'ROW ACCESS POLICY'
                         ELSE query_type
                       END AS change_type,
                       SUBSTR(query_text, 1, 1500) AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND (query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%TAG%'
                       OR query_text ILIKE '%ROW ACCESS POLICY%')
                  {company_filter}
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT {row_limit}
                """, ttl_key=f"ocm_policy_{company}_{days}_{text_filter}_{row_limit}", tier="standard")
            except Exception as e:
                st.warning(f"Policy change scan unavailable in this role/context: {e}")
        if st.session_state.get("ocm_df_policy_changes") is not None:
            df = st.session_state["ocm_df_policy_changes"]
            st.dataframe(df, use_container_width=True)
            if st.button("Save policy changes to Action Queue", key="ocm_policy_queue"):
                _queue_changes(session, df, "Policy Change Monitor", "Security", "Policy/Tag", "High")

    with tab_drift:
        if st.button("Load Drift Indicators", key="ocm_drift_load"):
            try:
                st.session_state["ocm_df_drift"] = run_query(f"""
                SELECT query_id, user_name, role_name, query_tag,
                       start_time, SUBSTR(query_text, 1, 1500) AS query_text,
                       CASE
                         WHEN query_tag ILIKE '%terraform%' THEN 'IaC managed'
                         ELSE 'Manual / non-IaC'
                       END AS drift_indicator
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND (query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%' OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%')
                  AND NOT (query_tag ILIKE '%terraform%')
                  {company_filter}
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT {row_limit}
                """, ttl_key=f"ocm_drift_{company}_{days}_{text_filter}_{row_limit}", tier="standard")
            except Exception as e:
                st.warning(f"Drift scan unavailable in this role/context: {e}")
        if st.session_state.get("ocm_df_drift") is not None:
            df = st.session_state["ocm_df_drift"]
            st.dataframe(df, use_container_width=True)
            download_csv(df, "terraform_drift_indicators.csv")
            if st.button("Save drift indicators to Action Queue", key="ocm_drift_queue"):
                _queue_changes(session, df, "Terraform Drift Monitor", "Governance", "Drift", "High")
