# sections/object_change_monitor.py - Who changed what?
import streamlit as st
from utils import get_session, normalize_df, download_csv, safe_sql


def render():
    session = get_session()
    st.header("Who Changed What?")
    st.caption("DDL, grants, roles, policy changes, owner changes, and Terraform drift indicators.")

    days = st.slider("Lookback (days)", 1, 90, 14, key="ocm_days")
    text_filter = st.text_input("Filter query/object text", key="ocm_filter")
    filter_clause = f"AND query_text ILIKE '%{safe_sql(text_filter)}%'" if text_filter else ""

    tab_ddl, tab_access, tab_policy, tab_drift = st.tabs([
        "Objects", "Grants & Roles", "Policies & Tags", "Terraform Drift"
    ])

    with tab_ddl:
        if st.button("Load Object Changes", key="ocm_obj_load"):
            try:
                st.session_state["ocm_df_object_changes"] = normalize_df(session.sql(f"""
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
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT 1000
                """).to_pandas())
            except Exception as e:
                st.error(f"Object change scan failed: {e}")
        if st.session_state.get("ocm_df_object_changes") is not None:
            df = st.session_state["ocm_df_object_changes"]
            if not df.empty:
                st.dataframe(df.groupby(["CHANGE_TYPE", "USER_NAME"]).size().reset_index(name="COUNT"), use_container_width=True)
            st.dataframe(df, use_container_width=True)
            download_csv(df, "object_changes.csv")

    with tab_access:
        if st.button("Load Grant / Role Changes", key="ocm_grant_load"):
            try:
                st.session_state["ocm_df_access_changes"] = normalize_df(session.sql(f"""
                SELECT query_id, user_name, role_name, start_time,
                       CASE
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
                  AND (query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%'
                       OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%')
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT 1000
                """).to_pandas())
            except Exception as e:
                st.error(f"Access change scan failed: {e}")
        if st.session_state.get("ocm_df_access_changes") is not None:
            st.dataframe(st.session_state["ocm_df_access_changes"], use_container_width=True)

    with tab_policy:
        if st.button("Load Masking / Tag Policy Changes", key="ocm_policy_load"):
            try:
                st.session_state["ocm_df_policy_changes"] = normalize_df(session.sql(f"""
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
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT 1000
                """).to_pandas())
            except Exception as e:
                st.error(f"Policy change scan failed: {e}")
        if st.session_state.get("ocm_df_policy_changes") is not None:
            st.dataframe(st.session_state["ocm_df_policy_changes"], use_container_width=True)

    with tab_drift:
        if st.button("Load Drift Indicators", key="ocm_drift_load"):
            try:
                st.session_state["ocm_df_drift"] = normalize_df(session.sql(f"""
                SELECT query_id, user_name, role_name, client_application_id, query_tag,
                       start_time, SUBSTR(query_text, 1, 1500) AS query_text,
                       CASE
                         WHEN client_application_id ILIKE '%terraform%' OR query_tag ILIKE '%terraform%' THEN 'IaC managed'
                         ELSE 'Manual / non-IaC'
                       END AS drift_indicator
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND (query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%' OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%')
                  AND NOT (client_application_id ILIKE '%terraform%' OR query_tag ILIKE '%terraform%')
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT 1000
                """).to_pandas())
            except Exception as e:
                st.error(f"Drift scan failed: {e}")
        if st.session_state.get("ocm_df_drift") is not None:
            st.dataframe(st.session_state["ocm_df_drift"], use_container_width=True)
            download_csv(st.session_state["ocm_df_drift"], "terraform_drift_indicators.csv")
