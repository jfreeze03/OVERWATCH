# sections/object_change_monitor.py - Who changed what?
import streamlit as st
from utils import (
    download_csv,
    format_snowflake_error,
    filter_existing_columns,
    get_global_filter_clause,
    get_session,
    make_action_id,
    mart_object_name,
    render_priority_dataframe,
    run_query,
    sql_literal,
    upsert_actions,
)


def _active_company() -> str:
    return st.session_state.get("active_company", "ALFA")


def _mart_company_filter(company: str) -> str:
    if str(company or "ALL").upper() == "ALL":
        return ""
    return f"AND c.company = {sql_literal(company, 100)}"


def _load_object_change_mart(
    *,
    company: str,
    days: int,
    row_limit: int,
    text_filter: str,
    category_sql: str,
    ttl_suffix: str,
) -> tuple[object, str]:
    """Load change rows from the pre-aggregated mart when its retention covers the request."""
    if days > 35:
        raise ValueError("Object-change mart keeps the most recent 35 days; using live history for this wider lookback.")

    table = mart_object_name("FACT_OBJECT_CHANGE")
    text_clause = f"AND c.query_text ILIKE {sql_literal('%' + text_filter + '%')}" if text_filter else ""
    sql = f"""
        SELECT
            c.query_id,
            c.user_name,
            c.role_name,
            NULL::VARCHAR AS warehouse_name,
            c.database_name,
            c.schema_name,
            c.start_time,
            CASE
              WHEN c.change_category = 'GRANT' AND c.query_text ILIKE '%OWNERSHIP%' THEN 'OWNER CHANGE'
              WHEN c.change_category = 'GRANT' AND c.query_text ILIKE 'GRANT%' THEN 'GRANT'
              WHEN c.change_category = 'GRANT' AND c.query_text ILIKE 'REVOKE%' THEN 'REVOKE'
              WHEN c.query_text ILIKE 'CREATE%ROLE%' THEN 'CREATE ROLE'
              WHEN c.query_text ILIKE 'ALTER%ROLE%' THEN 'ALTER ROLE'
              WHEN c.query_text ILIKE 'DROP%ROLE%' THEN 'DROP ROLE'
              WHEN c.change_category = 'POLICY' AND c.query_text ILIKE '%MASKING POLICY%' THEN 'MASKING POLICY'
              WHEN c.change_category = 'POLICY' AND c.query_text ILIKE '%ROW ACCESS POLICY%' THEN 'ROW ACCESS POLICY'
              WHEN c.change_category = 'POLICY' AND c.query_text ILIKE '%TAG%' THEN 'TAG POLICY'
              WHEN c.query_text ILIKE 'CREATE%TABLE%' THEN 'CREATE TABLE'
              WHEN c.query_text ILIKE 'ALTER%TABLE%' THEN 'ALTER TABLE'
              WHEN c.query_text ILIKE 'DROP%TABLE%' THEN 'DROP TABLE'
              WHEN c.query_text ILIKE 'CREATE%VIEW%' THEN 'CREATE VIEW'
              WHEN c.query_text ILIKE 'ALTER%VIEW%' THEN 'ALTER VIEW'
              WHEN c.query_text ILIKE 'DROP%VIEW%' THEN 'DROP VIEW'
              WHEN c.query_text ILIKE 'CREATE%PROCEDURE%' THEN 'CREATE PROCEDURE'
              WHEN c.query_text ILIKE 'ALTER%PROCEDURE%' THEN 'ALTER PROCEDURE'
              WHEN c.query_text ILIKE 'DROP%PROCEDURE%' THEN 'DROP PROCEDURE'
              WHEN c.query_text ILIKE 'CREATE%TASK%' THEN 'CREATE TASK'
              WHEN c.query_text ILIKE 'ALTER%TASK%' THEN 'ALTER TASK'
              WHEN c.query_text ILIKE 'DROP%TASK%' THEN 'DROP TASK'
              ELSE COALESCE(c.change_category, c.query_type)
            END AS change_type,
            c.query_tag,
            SUBSTR(c.query_text, 1, 1500) AS query_text
        FROM {table} c
        WHERE c.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {_mart_company_filter(company)}
          {category_sql}
          {text_clause}
        ORDER BY c.start_time DESC
        LIMIT {int(row_limit)}
    """
    df = run_query(
        sql,
        ttl_key=f"ocm_mart_{ttl_suffix}_{company}_{days}_{text_filter}_{row_limit}",
        tier="standard",
        section="Object Change Monitor",
    )
    return df, "OVERWATCH mart: FACT_OBJECT_CHANGE"


def _change_route(change_type: object, category: str = "") -> tuple[str, str]:
    text = f"{change_type or ''} {category or ''}".upper()
    if "DROP" in text:
        return (
            "Change & Drift",
            "Confirm approval, downstream dependencies, recovery path, and whether the object needs restore.",
        )
    if "OWNERSHIP" in text or "OWNER" in text or "GRANT" in text or "REVOKE" in text or "ROLE" in text:
        return (
            "Security Posture",
            "Validate requester, approver, role hierarchy, and ownership transfer before accepting the access change.",
        )
    if "MASKING" in text or "TAG" in text or "ROW ACCESS" in text or "POLICY" in text:
        return (
            "Security Posture",
            "Validate data classification, policy owner, and governance approval before leaving the policy change active.",
        )
    if "DRIFT" in text or "IAC" in text:
        return (
            "Change & Drift",
            "Compare with Terraform/source control; codify the change or revert through approved deployment.",
        )
    if "PROCEDURE" in text or "TASK" in text:
        return (
            "Workload Operations",
            "Check task/procedure lineage and runtime impact before approving the object change.",
        )
    return (
        "Change & Drift",
        "Review approval, owner, dependency impact, and drift risk before accepting the change.",
    )


def _annotate_change_routes(df, category: str = ""):
    if df is None or getattr(df, "empty", True):
        return df
    routed = df.copy()
    route_source = routed.get("CHANGE_TYPE", routed.get("DRIFT_INDICATOR", ""))
    routed["NEXT_WORKFLOW"] = route_source.apply(lambda value: _change_route(value, category)[0])
    routed["NEXT_ACTION"] = route_source.apply(lambda value: _change_route(value, category)[1])
    return routed


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
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def render():
    session = get_session()
    company = _active_company()
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["QUERY_TAG"],
    ))
    query_tag_select = "query_tag" if "QUERY_TAG" in qh_cols else "NULL::VARCHAR AS query_tag"
    drift_case = (
        "WHEN query_tag ILIKE '%terraform%' THEN 'IaC managed'"
        if "QUERY_TAG" in qh_cols else ""
    )
    drift_exclusion = (
        "AND NOT (query_tag ILIKE '%terraform%')"
        if "QUERY_TAG" in qh_cols else ""
    )
    st.header("Who Changed What?")
    st.caption("DDL, grants, roles, policy changes, owner changes, and Terraform drift indicators.")

    days = st.slider("Lookback (days)", 1, 90, 14, key="ocm_days")
    row_limit = st.slider("Max rows per scan", 100, 1000, 250, step=50, key="ocm_row_limit")
    text_filter = st.text_input("Filter query/object text", key="ocm_filter")
    if days > 30 and not text_filter:
        st.caption("Tip: add a query/object text filter for long lookbacks so governance scans stay inexpensive.")
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
    mart_object_category = """
          AND c.change_category IN ('CREATE', 'ALTER', 'DROP')
          AND (
            c.query_text ILIKE 'CREATE%TABLE%' OR c.query_text ILIKE 'ALTER%TABLE%' OR c.query_text ILIKE 'DROP%TABLE%'
            OR c.query_text ILIKE 'CREATE%VIEW%' OR c.query_text ILIKE 'ALTER%VIEW%' OR c.query_text ILIKE 'DROP%VIEW%'
            OR c.query_text ILIKE 'CREATE%PROCEDURE%' OR c.query_text ILIKE 'ALTER%PROCEDURE%' OR c.query_text ILIKE 'DROP%PROCEDURE%'
            OR c.query_text ILIKE 'CREATE%TASK%' OR c.query_text ILIKE 'ALTER%TASK%' OR c.query_text ILIKE 'DROP%TASK%'
          )
    """
    mart_access_category = """
          AND (
            c.change_category IN ('GRANT', 'OWNER')
            OR c.query_text ILIKE 'GRANT%'
            OR c.query_text ILIKE 'REVOKE%'
            OR c.query_text ILIKE '%OWNERSHIP%'
            OR c.query_text ILIKE 'CREATE%ROLE%'
            OR c.query_text ILIKE 'ALTER%ROLE%'
            OR c.query_text ILIKE 'DROP%ROLE%'
          )
    """
    mart_policy_category = """
          AND (
            c.change_category = 'POLICY'
            OR c.query_text ILIKE '%MASKING POLICY%'
            OR c.query_text ILIKE '%TAG%'
            OR c.query_text ILIKE '%ROW ACCESS POLICY%'
          )
    """
    mart_drift_category = """
          AND c.change_category IN ('CREATE', 'ALTER', 'DROP', 'GRANT', 'OWNER', 'POLICY')
          AND (c.query_tag IS NULL OR c.query_tag NOT ILIKE '%terraform%')
    """

    with tab_ddl:
        if st.button("Load Object Changes", key="ocm_obj_load"):
            try:
                df, source = _load_object_change_mart(
                    company=company,
                    days=days,
                    row_limit=row_limit,
                    text_filter=text_filter,
                    category_sql=mart_object_category,
                    ttl_suffix="objects",
                )
                st.session_state["ocm_df_object_changes"] = df
                st.session_state["ocm_source_object_changes"] = source
            except Exception as mart_exc:
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
                """, ttl_key=f"ocm_objects_{company}_{days}_{text_filter}_{row_limit}", tier="standard", section="Object Change Monitor")
                    st.session_state["ocm_source_object_changes"] = "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                    if str(mart_exc):
                        st.caption(f"Mart path skipped: {format_snowflake_error(mart_exc)}")
                except Exception as e:
                    st.warning(f"Object change scan unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("ocm_df_object_changes") is not None:
            df = _annotate_change_routes(st.session_state["ocm_df_object_changes"], "Object")
            st.caption(st.session_state.get("ocm_source_object_changes", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
            if not df.empty:
                render_priority_dataframe(
                    df.groupby(["CHANGE_TYPE", "USER_NAME"]).size().reset_index(name="COUNT"),
                    title="Object change hot spots",
                    priority_columns=["CHANGE_TYPE", "USER_NAME", "COUNT"],
                    sort_by=["COUNT"],
                    ascending=False,
                    raw_label="All object change hot spots",
                )
            render_priority_dataframe(
                df,
                title="Object changes to review first",
                priority_columns=[
                    "CHANGE_TYPE", "USER_NAME", "DATABASE_NAME", "SCHEMA_NAME",
                    "START_TIME", "NEXT_WORKFLOW", "NEXT_ACTION", "QUERY_ID",
                ],
                sort_by=["START_TIME"],
                ascending=False,
                raw_label="All object changes",
            )
            download_csv(df, "object_changes.csv")
            if st.button("Save object changes to Action Queue", key="ocm_obj_queue"):
                _queue_changes(session, df, "Object Change Monitor", "Governance", "Object", "Medium")

    with tab_access:
        if st.button("Load Grant / Role Changes", key="ocm_grant_load"):
            try:
                df, source = _load_object_change_mart(
                    company=company,
                    days=days,
                    row_limit=row_limit,
                    text_filter=text_filter,
                    category_sql=mart_access_category,
                    ttl_suffix="access",
                )
                st.session_state["ocm_df_access_changes"] = df
                st.session_state["ocm_source_access_changes"] = source
            except Exception as mart_exc:
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
                """, ttl_key=f"ocm_access_{company}_{days}_{text_filter}_{row_limit}", tier="standard", section="Object Change Monitor")
                    st.session_state["ocm_source_access_changes"] = "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                    if str(mart_exc):
                        st.caption(f"Mart path skipped: {format_snowflake_error(mart_exc)}")
                except Exception as e:
                    st.warning(f"Access change scan unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("ocm_df_access_changes") is not None:
            df = _annotate_change_routes(st.session_state["ocm_df_access_changes"], "Access")
            st.caption(st.session_state.get("ocm_source_access_changes", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
            render_priority_dataframe(
                df,
                title="Access changes to review first",
                priority_columns=[
                    "CHANGE_TYPE", "USER_NAME", "ROLE_NAME", "START_TIME",
                    "NEXT_WORKFLOW", "NEXT_ACTION", "QUERY_ID",
                ],
                sort_by=["START_TIME"],
                ascending=False,
                raw_label="All access changes",
            )
            if st.button("Save access changes to Action Queue", key="ocm_access_queue"):
                _queue_changes(session, df, "Access Change Monitor", "Security", "Grant/Role", "High")

    with tab_policy:
        if st.button("Load Masking / Tag Policy Changes", key="ocm_policy_load"):
            try:
                df, source = _load_object_change_mart(
                    company=company,
                    days=days,
                    row_limit=row_limit,
                    text_filter=text_filter,
                    category_sql=mart_policy_category,
                    ttl_suffix="policy",
                )
                st.session_state["ocm_df_policy_changes"] = df
                st.session_state["ocm_source_policy_changes"] = source
            except Exception as mart_exc:
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
                """, ttl_key=f"ocm_policy_{company}_{days}_{text_filter}_{row_limit}", tier="standard", section="Object Change Monitor")
                    st.session_state["ocm_source_policy_changes"] = "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                    if str(mart_exc):
                        st.caption(f"Mart path skipped: {format_snowflake_error(mart_exc)}")
                except Exception as e:
                    st.warning(f"Policy change scan unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("ocm_df_policy_changes") is not None:
            df = _annotate_change_routes(st.session_state["ocm_df_policy_changes"], "Policy")
            st.caption(st.session_state.get("ocm_source_policy_changes", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
            render_priority_dataframe(
                df,
                title="Policy changes to review first",
                priority_columns=[
                    "CHANGE_TYPE", "USER_NAME", "ROLE_NAME", "START_TIME",
                    "NEXT_WORKFLOW", "NEXT_ACTION", "QUERY_ID",
                ],
                sort_by=["START_TIME"],
                ascending=False,
                raw_label="All policy changes",
            )
            if st.button("Save policy changes to Action Queue", key="ocm_policy_queue"):
                _queue_changes(session, df, "Policy Change Monitor", "Security", "Policy/Tag", "High")

    with tab_drift:
        if st.button("Load Drift Indicators", key="ocm_drift_load"):
            try:
                df, source = _load_object_change_mart(
                    company=company,
                    days=days,
                    row_limit=row_limit,
                    text_filter=text_filter,
                    category_sql=mart_drift_category,
                    ttl_suffix="drift",
                )
                st.session_state["ocm_df_drift"] = df
                st.session_state["ocm_source_drift"] = source
            except Exception as mart_exc:
                try:
                    st.session_state["ocm_df_drift"] = run_query(f"""
                SELECT query_id, user_name, role_name, {query_tag_select},
                       start_time, SUBSTR(query_text, 1, 1500) AS query_text,
                       CASE
                         {drift_case}
                         ELSE 'Manual / non-IaC'
                       END AS drift_indicator
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND (query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%' OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%')
                  {drift_exclusion}
                  {company_filter}
                  {filter_clause}
                ORDER BY start_time DESC
                LIMIT {row_limit}
                """, ttl_key=f"ocm_drift_{company}_{days}_{text_filter}_{row_limit}", tier="standard", section="Object Change Monitor")
                    st.session_state["ocm_source_drift"] = "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                    if str(mart_exc):
                        st.caption(f"Mart path skipped: {format_snowflake_error(mart_exc)}")
                except Exception as e:
                    st.warning(f"Drift scan unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("ocm_df_drift") is not None:
            df = _annotate_change_routes(st.session_state["ocm_df_drift"], "Drift")
            st.caption(st.session_state.get("ocm_source_drift", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
            render_priority_dataframe(
                df,
                title="Drift indicators to review first",
                priority_columns=[
                    "DRIFT_INDICATOR", "USER_NAME", "ROLE_NAME", "QUERY_TAG",
                    "START_TIME", "NEXT_WORKFLOW", "NEXT_ACTION", "QUERY_ID",
                ],
                sort_by=["START_TIME"],
                ascending=False,
                raw_label="All drift indicators",
            )
            download_csv(df, "terraform_drift_indicators.csv")
            if st.button("Save drift indicators to Action Queue", key="ocm_drift_queue"):
                _queue_changes(session, df, "Terraform Drift Monitor", "Governance", "Drift", "High")
