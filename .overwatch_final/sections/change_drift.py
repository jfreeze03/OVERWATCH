# sections/change_drift.py - Consolidated change, drift, and lineage workflow
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections import dba_tools, object_change_monitor, stored_proc_tracker
from utils import (
    build_action_queue_ddl,
    filter_existing_columns,
    format_snowflake_error,
    get_active_company,
    get_global_filter_clause,
    get_session,
    mart_object_name,
    make_action_id,
    run_query,
    safe_float,
    safe_int,
    upsert_actions,
)
from utils.workflows import render_signal_confidence, render_workflow_guide, render_workflow_selector

WORKFLOWS = (
    "Object and access changes",
    "Stored procedure lineage",
    "Schema and object drift",
    "Data movement and replication",
    "Controlled DBA actions",
)

WORKFLOW_DETAILS = {
    "Object and access changes": "Who changed what, access movement, destructive DDL, and policy changes.",
    "Stored procedure lineage": "Procedure ownership, child SQL, downstream objects, and runtime/cost drift.",
    "Schema and object drift": "Schema compare, object inventory, unused objects, and Terraform drift signals.",
    "Data movement and replication": "Replication, dynamic tables, Snowpipe, data loading, and freshness risk.",
    "Controlled DBA actions": "Guarded admin actions, generated SQL, and operational controls.",
}


def _change_drift_score(
    *,
    object_changes: int,
    access_changes: int,
    policy_changes: int,
    owner_changes: int,
    destructive_changes: int,
    manual_drift: int,
) -> int:
    object_penalty = min(15, safe_float(object_changes) * 0.3)
    access_penalty = min(20, safe_float(access_changes) * 0.8)
    policy_penalty = min(25, safe_float(policy_changes) * 4)
    owner_penalty = min(20, safe_float(owner_changes) * 3)
    destructive_penalty = min(25, safe_float(destructive_changes) * 5)
    drift_penalty = min(20, safe_float(manual_drift) * 1.5)
    return max(0, min(100, int(round(
        100
        - object_penalty
        - access_penalty
        - policy_penalty
        - owner_penalty
        - destructive_penalty
        - drift_penalty
    ))))


def _change_drift_rating(score: int) -> str:
    if score >= 95:
        return "Controlled"
    if score >= 85:
        return "Watch"
    if score >= 70:
        return "Elevated"
    return "High Drift Risk"


def _change_action_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "drop" in value or "destructive" in value:
        return (
            "Object",
            "Confirm change approval, downstream dependencies, backup/recovery posture, and whether the object should be restored.",
            "-- Proof: QUERY_HISTORY destructive DDL query_id and query text.",
        )
    if "policy" in value or "tag" in value or "masking" in value:
        return (
            "Policy/Tag",
            "Validate policy owner, classification impact, and whether masking/tag changes match governance approval.",
            "-- Proof: QUERY_HISTORY masking/tag/row-access policy DDL.",
        )
    if "grant" in value or "role" in value or "owner" in value:
        return (
            "Grant/Role",
            "Confirm requester, approver, role hierarchy, and ownership transfer before accepting the access change.",
            "-- Proof: QUERY_HISTORY grant/revoke/ownership DDL.",
        )
    if "drift" in value:
        return (
            "Drift",
            "Compare the query with Terraform/IaC state; either codify the change or revert it through approved deployment.",
            "-- Proof: QUERY_HISTORY non-IaC DDL/DCL query text and query tag.",
        )
    return (
        "Object",
        "Review change for approval, ownership, dependency impact, and drift risk.",
        "-- Proof: QUERY_HISTORY change statement.",
    )


def _change_workflow_for(row: pd.Series) -> str:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    query_text = str(row.get("QUERY_TEXT") or "").lower()
    if "drift" in finding_type:
        return "Schema and object drift"
    if "procedure" in query_text:
        return "Stored procedure lineage"
    if "dynamic table" in query_text or "replication" in query_text or "pipe" in query_text:
        return "Data movement and replication"
    if "grant" in finding_type or "role" in finding_type or "owner" in finding_type or "policy" in finding_type or "tag" in finding_type:
        return "Object and access changes"
    return "Object and access changes"


def _change_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = exceptions.copy()
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["ENTITY_TYPE"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _change_action_for(value)[0])
    view["NEXT_ACTION"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _change_action_for(value)[1])
    view["NEXT_WORKFLOW"] = view.apply(_change_workflow_for, axis=1)
    sort_cols = ["_RANK"]
    ascending = [True]
    if "LAST_SEEN" in view.columns:
        sort_cols.append("LAST_SEEN")
        ascending.append(False)
    return view.sort_values(sort_cols, ascending=ascending).drop(columns=["_RANK"], errors="ignore")


def _render_change_watch_floor(score: int, exceptions: pd.DataFrame, row) -> None:
    priority = _change_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())
    actors = safe_int(row.get("ACTORS", 0))
    affected_dbs = safe_int(row.get("AFFECTED_DATABASES", 0))

    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 2.2])
    c1.metric("Change Readiness", f"{score}/100", _change_drift_rating(score))
    c2.metric("High-Risk Changes", f"{high_risk:,}", delta_color="inverse")
    c3.metric("Manual Drift", f"{safe_int(row.get('MANUAL_DRIFT', 0)):,}", delta_color="inverse")
    with c4:
        if priority.empty:
            st.success("No urgent change/drift exceptions crossed the brief thresholds.")
        else:
            first = priority.iloc[0]
            st.warning(
                f"First move: {first.get('FINDING_TYPE', 'Change')} by "
                f"{first.get('USER_NAME', 'unknown')} -> {first.get('NEXT_ACTION', 'Validate the change.')}"
            )

    st.markdown("**Change Watch Floor**")
    st.caption(f"Actors: {actors:,} | Affected databases: {affected_dbs:,}")
    if priority.empty:
        st.caption("No immediate change cards. Use Object and access changes for investigation or Schema and object drift for periodic control review.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Object and access changes")
        with cols[idx]:
            st.markdown(f"**{item.get('SEVERITY', 'Medium')}: {item.get('FINDING_TYPE', '')}**")
            st.caption(f"{item.get('ENTITY_TYPE', 'Object')}: {item.get('ENTITY', 'unknown')}")
            st.caption(f"Actor: {item.get('USER_NAME', 'unknown')} | Query: {item.get('QUERY_ID', '')}")
            st.write(str(item.get("NEXT_ACTION", "")))
            if st.button(f"Open {workflow}", key=f"change_watch_floor_{idx}_{workflow}", use_container_width=True):
                entity = str(item.get("ENTITY") or "").strip()
                actor = str(item.get("USER_NAME") or "").strip()
                query_id = str(item.get("QUERY_ID") or "").strip()
                if actor and actor.lower() != "unknown":
                    st.session_state["global_user"] = actor
                if entity and entity.lower() != "unknown" and not entity.startswith("01"):
                    st.session_state["global_database"] = entity.split(".")[0]
                if query_id:
                    st.session_state["qs_text"] = query_id
                    st.session_state["qs_status"] = "ALL"
                    st.session_state["qs_autorun"] = True
                for stale_key in (
                    "ocm_df_object_changes",
                    "ocm_df_access_changes",
                    "ocm_df_policy_changes",
                    "ocm_df_drift",
                ):
                    st.session_state.pop(stale_key, None)
                st.session_state["change_drift_workflow"] = workflow
                st.rerun()


def _build_change_drift_markdown(
    *,
    company: str,
    days: int,
    score: int,
    summary_row,
    exceptions: pd.DataFrame,
) -> str:
    exception_lines = []
    if exceptions is not None and not exceptions.empty:
        for _, row in exceptions.head(10).iterrows():
            exception_lines.append(
                f"- {row.get('SEVERITY', 'Medium')}: {row.get('FINDING_TYPE', 'Change')} "
                f"by {row.get('USER_NAME', 'unknown')} on {row.get('ENTITY', 'unknown')}."
            )
    else:
        exception_lines.append("- No change/drift exceptions crossed the configured thresholds.")
    lines = [
        f"# OVERWATCH Change & Drift Brief - {company}",
        "",
        f"Lookback window: {days} day(s).",
        f"Control score: {score} ({_change_drift_rating(score)}).",
        "",
        "## Key Metrics",
        f"- Object changes: {safe_int(summary_row.get('OBJECT_CHANGES', 0)):,}",
        f"- Access changes: {safe_int(summary_row.get('ACCESS_CHANGES', 0)):,}",
        f"- Owner changes: {safe_int(summary_row.get('OWNER_CHANGES', 0)):,}",
        f"- Policy/tag changes: {safe_int(summary_row.get('POLICY_CHANGES', 0)):,}",
        f"- Destructive changes: {safe_int(summary_row.get('DESTRUCTIVE_CHANGES', 0)):,}",
        f"- Manual/non-IaC drift indicators: {safe_int(summary_row.get('MANUAL_DRIFT', 0)):,}",
        "",
        "## Exceptions",
        *exception_lines,
        "",
        "## DBA Follow-Up",
        "- Review destructive and policy changes first.",
        "- Validate grants, revokes, and ownership transfers against approved access requests.",
        "- Compare manual/non-IaC changes with Terraform or deployment records.",
        "- Save material exceptions to the OVERWATCH Action Queue for owner/status tracking.",
        "",
        "## Confidence",
        "Source: QUERY_HISTORY. DDL/DCL detection is text-pattern based, so it is strong for investigation but should be validated against source control and change tickets.",
    ]
    return "\n".join(lines)


def _build_change_drift_sql(session, days: int, company: str) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["QUERY_TAG"],
    ))
    query_tag_expr = "query_tag" if "QUERY_TAG" in qh_cols else "NULL::VARCHAR"
    manual_drift_predicate = (
        "AND COALESCE(query_tag, '') NOT ILIKE '%terraform%'"
        if "QUERY_TAG" in qh_cols else ""
    )
    scope = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    base_where = f"""
        start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        {scope}
    """
    summary_sql = f"""
    WITH changes AS (
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            database_name,
            schema_name,
            start_time,
            {query_tag_expr} AS query_tag,
            query_text,
            CASE
                WHEN query_text ILIKE 'DROP%' THEN 'DESTRUCTIVE'
                WHEN query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%' THEN 'POLICY'
                WHEN query_text ILIKE '%OWNERSHIP%' THEN 'OWNER'
                WHEN query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%' THEN 'ACCESS'
                WHEN query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' THEN 'OBJECT'
                ELSE 'OTHER'
            END AS change_family
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {base_where}
          AND (
            query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%'
            OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
            OR query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%'
          )
    )
    SELECT
        '{company}' AS company,
        COUNT_IF(change_family IN ('OBJECT', 'DESTRUCTIVE')) AS object_changes,
        COUNT_IF(change_family IN ('ACCESS', 'OWNER')) AS access_changes,
        COUNT_IF(change_family = 'OWNER') AS owner_changes,
        COUNT_IF(change_family = 'POLICY') AS policy_changes,
        COUNT_IF(change_family = 'DESTRUCTIVE') AS destructive_changes,
        COUNT_IF(change_family <> 'OTHER' {manual_drift_predicate}) AS manual_drift,
        COUNT(DISTINCT user_name) AS actors,
        COUNT(DISTINCT database_name) AS affected_databases
    FROM changes
    """
    exceptions_sql = f"""
    WITH changes AS (
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            database_name,
            schema_name,
            start_time,
            {query_tag_expr} AS query_tag,
            SUBSTR(query_text, 1, 1500) AS query_text,
            CASE
                WHEN query_text ILIKE 'DROP%' THEN 'Destructive DDL'
                WHEN query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%' THEN 'Policy or Tag Change'
                WHEN query_text ILIKE '%OWNERSHIP%' THEN 'Owner Change'
                WHEN query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%' THEN 'Grant or Role Change'
                WHEN query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' THEN 'Object Change'
                ELSE 'Other Change'
            END AS finding_type
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {base_where}
          AND (
            query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%'
            OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
            OR query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%'
          )
          {manual_drift_predicate}
    )
    SELECT
        finding_type,
        CASE
            WHEN finding_type IN ('Destructive DDL', 'Policy or Tag Change', 'Owner Change') THEN 'High'
            WHEN finding_type = 'Grant or Role Change' THEN 'Medium'
            ELSE 'Low'
        END AS severity,
        COALESCE(database_name || '.' || schema_name, database_name, query_id) AS entity,
        user_name,
        role_name,
        query_id,
        start_time AS last_seen,
        1 AS event_count,
        'QUERY_HISTORY query_id = ' || query_id AS proof_query,
        query_text
    FROM changes
    WHERE finding_type <> 'Other Change'
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        start_time DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def _build_mart_change_drift_sql(days: int, company: str) -> tuple[str, str]:
    """Build change/drift brief SQL from the OVERWATCH object-change fact."""
    table = mart_object_name("FACT_OBJECT_CHANGE")
    scope = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    base_where = f"""
        start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        AND company = '{company}'
        {scope}
    """
    summary_sql = f"""
    SELECT
        '{company}' AS company,
        COUNT_IF(change_category IN ('CREATE', 'ALTER', 'DROP')) AS object_changes,
        COUNT_IF(change_category IN ('GRANT', 'OWNER')) AS access_changes,
        COUNT_IF(change_category = 'OWNER') AS owner_changes,
        COUNT_IF(change_category = 'POLICY') AS policy_changes,
        COUNT_IF(change_category = 'DROP') AS destructive_changes,
        COUNT_IF(COALESCE(query_tag, '') NOT ILIKE '%terraform%') AS manual_drift,
        COUNT(DISTINCT user_name) AS actors,
        COUNT(DISTINCT database_name) AS affected_databases
    FROM {table}
    WHERE {base_where}
    """
    exceptions_sql = f"""
    SELECT
        CASE
            WHEN change_category = 'DROP' THEN 'Destructive DDL'
            WHEN change_category = 'POLICY' THEN 'Policy or Tag Change'
            WHEN change_category = 'OWNER' THEN 'Owner Change'
            WHEN change_category = 'GRANT' THEN 'Grant or Role Change'
            WHEN change_category IN ('CREATE', 'ALTER') THEN 'Object Change'
            ELSE 'Other Change'
        END AS finding_type,
        CASE
            WHEN change_category IN ('DROP', 'POLICY', 'OWNER') THEN 'High'
            WHEN change_category = 'GRANT' THEN 'Medium'
            ELSE 'Low'
        END AS severity,
        COALESCE(database_name || '.' || schema_name, database_name, query_id) AS entity,
        user_name,
        role_name,
        query_id,
        start_time AS last_seen,
        1 AS event_count,
        'FACT_OBJECT_CHANGE query_id = ' || query_id AS proof_query,
        query_tag,
        SUBSTR(query_text, 1, 1500) AS query_text
    FROM {table}
    WHERE {base_where}
      AND change_category <> 'OTHER'
      AND COALESCE(query_tag, '') NOT ILIKE '%terraform%'
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        start_time DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def _queue_change_exceptions(session, exceptions: pd.DataFrame) -> None:
    if exceptions is None or exceptions.empty:
        st.info("No change/drift exceptions to queue.")
        return
    company = get_active_company()
    actions = []
    for _, row in exceptions.head(100).iterrows():
        finding_type = str(row.get("FINDING_TYPE") or "Change")
        entity = str(row.get("ENTITY") or row.get("QUERY_ID") or "Snowflake account")
        user_name = str(row.get("USER_NAME") or "unknown")
        severity = str(row.get("SEVERITY") or "Medium")
        entity_type, action, generated_sql = _change_action_for(finding_type)
        finding = f"{finding_type} by {user_name} on {entity}"
        actions.append({
            "Action ID": make_action_id("Change Drift", entity, f"{finding}|{row.get('QUERY_ID', '')}"),
            "Source": "Change & Drift - Brief",
            "Severity": severity,
            "Category": "Governance",
            "Entity Type": entity_type,
            "Entity": entity,
            "Owner": "DBA",
            "Finding": finding,
            "Action": action,
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": generated_sql,
            "Proof Query": str(row.get("PROOF_QUERY") or f"QUERY_HISTORY query_id = '{row.get('QUERY_ID', '')}'"),
            "Company": company,
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} change/drift exceptions to the action queue.")
    except Exception as e:
        st.error(f"Could not save change/drift exceptions: {format_snowflake_error(e)}")
        st.download_button(
            "Download Action Queue DDL",
            build_action_queue_ddl(),
            file_name="overwatch_action_queue_setup.sql",
            mime="text/plain",
            key="change_drift_action_queue_ddl",
        )


def render() -> None:
    session = get_session()
    company = get_active_company()
    if st.session_state.get("exceptions_only_mode") and "change_drift_workflow" not in st.session_state:
        st.session_state["change_drift_workflow"] = "Object and access changes"
    st.header("Change & Drift")
    st.caption(
        "One workflow for who-changed-what investigations, stored procedure lineage, "
        "schema/object drift, dynamic tables, replication, and controlled DBA maintenance."
    )
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="estimated",
        scope_note="DDL/change detection is query-history based; SHOW commands fill live metadata gaps.",
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize recent DDL, grant, owner, policy, replication, and task-control issues.")
    render_workflow_guide(
        "Confirm who changed what, trace stored procedure blast radius, then use DBA toolkit checks "
        "for drift, replication, dynamic tables, and controlled actions.",
        [
            ("DDL, grant, owner, or policy changed", "Use Object and access changes."),
            ("A stored procedure drove unexpected cost or changes", "Use Stored procedure lineage."),
            ("Schemas, objects, or unused assets may have drifted", "Use Schema and object drift."),
            ("Loads, pipes, dynamic tables, or replication are suspect", "Use Data movement and replication."),
            ("A query, task, warehouse, or setup action is required", "Use Controlled DBA actions."),
        ],
    )

    days = st.slider("Change brief lookback (days)", 1, 90, 14, key="change_drift_brief_days")
    if st.button("Load Change & Drift Brief", key="change_drift_brief_load", type="primary"):
        try:
            summary_sql, exceptions_sql = _build_mart_change_drift_sql(days, company)
            st.session_state["change_drift_summary"] = run_query(
                summary_sql,
                ttl_key=f"change_drift_summary_mart_{company}_{days}",
                tier="standard",
            )
            st.session_state["change_drift_exceptions"] = run_query(
                exceptions_sql,
                ttl_key=f"change_drift_exceptions_mart_{company}_{days}",
                tier="standard",
            )
            st.session_state["change_drift_proof_sql"] = {
                "summary": summary_sql,
                "exceptions": exceptions_sql,
            }
            st.session_state["change_drift_meta"] = {
                "company": company,
                "days": days,
                "source": "OVERWATCH mart: FACT_OBJECT_CHANGE",
            }
        except Exception as exc:
            try:
                summary_sql, exceptions_sql = _build_change_drift_sql(session, days, company)
                st.session_state["change_drift_summary"] = run_query(
                    summary_sql,
                    ttl_key=f"change_drift_summary_live_{company}_{days}",
                    tier="standard",
                )
                st.session_state["change_drift_exceptions"] = run_query(
                    exceptions_sql,
                    ttl_key=f"change_drift_exceptions_live_{company}_{days}",
                    tier="standard",
                )
                st.session_state["change_drift_proof_sql"] = {
                    "summary": summary_sql,
                    "exceptions": exceptions_sql,
                }
                st.session_state["change_drift_meta"] = {
                    "company": company,
                    "days": days,
                    "source": "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                }
                st.info(f"Change mart unavailable; used live QUERY_HISTORY fallback. {format_snowflake_error(exc)}")
            except Exception as live_exc:
                st.session_state["change_drift_summary"] = pd.DataFrame()
                st.session_state["change_drift_exceptions"] = pd.DataFrame()
                st.error(f"Unable to load change brief: {format_snowflake_error(live_exc)}")

    summary = st.session_state.get("change_drift_summary")
    exceptions = st.session_state.get("change_drift_exceptions")
    meta = st.session_state.get("change_drift_meta", {})
    if (
        summary is not None
        and not summary.empty
        and meta.get("company") == company
        and meta.get("days") == days
    ):
        row = summary.iloc[0]
        score = _change_drift_score(
            object_changes=safe_int(row.get("OBJECT_CHANGES", 0)),
            access_changes=safe_int(row.get("ACCESS_CHANGES", 0)),
            policy_changes=safe_int(row.get("POLICY_CHANGES", 0)),
            owner_changes=safe_int(row.get("OWNER_CHANGES", 0)),
            destructive_changes=safe_int(row.get("DESTRUCTIVE_CHANGES", 0)),
            manual_drift=safe_int(row.get("MANUAL_DRIFT", 0)),
        )
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Change Control Score", score, _change_drift_rating(score))
        c2.metric("Object Changes", f"{safe_int(row.get('OBJECT_CHANGES', 0)):,}")
        c3.metric("Access Changes", f"{safe_int(row.get('ACCESS_CHANGES', 0)):,}")
        c4.metric("Policy/Owner", f"{safe_int(row.get('POLICY_CHANGES', 0)) + safe_int(row.get('OWNER_CHANGES', 0)):,}", delta_color="inverse")
        c5.metric("Manual Drift", f"{safe_int(row.get('MANUAL_DRIFT', 0)):,}", delta_color="inverse")
        if score < 85:
            st.warning("Change control needs DBA review; high-risk changes or drift indicators are present.")
        elif score < 95:
            st.info("Change control is usable, but there are changes worth validating.")
        else:
            st.success("Change control looks clean for the selected window.")
        st.caption(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

        _render_change_watch_floor(score, exceptions, row)
        st.divider()

        if exceptions is not None and not exceptions.empty:
            st.subheader("Change & Drift Exceptions")
            st.dataframe(exceptions, use_container_width=True, hide_index=True)
            if st.button("Save Change Exceptions to Action Queue", key="change_drift_queue"):
                _queue_change_exceptions(session, exceptions)
        elif exceptions is not None:
            st.success("No change/drift exceptions crossed the default thresholds.")
        brief_md = _build_change_drift_markdown(
            company=company,
            days=days,
            score=score,
            summary_row=row,
            exceptions=exceptions,
        )
        dl1, dl2 = st.columns([1, 3])
        with dl1:
            st.download_button(
                "Download Change Brief",
                brief_md,
                file_name=f"overwatch_change_drift_brief_{company.lower()}.md",
                mime="text/markdown",
                key="change_drift_download",
            )
        with dl2:
            with st.expander("Proof SQL", expanded=False):
                proof_sql = st.session_state.get("change_drift_proof_sql", {})
                st.caption("Use these source queries to defend change counts and exception rows.")
                st.code(proof_sql.get("summary", "-- Load the change brief first."), language="sql")
                st.code(proof_sql.get("exceptions", "-- Load the change brief first."), language="sql")
        if st.session_state.get("exceptions_only_mode"):
            st.stop()

    workflow = render_workflow_selector(
        "Change workflow",
        "change_drift_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
    )

    if workflow == "Object and access changes":
        object_change_monitor.render()
    elif workflow == "Stored procedure lineage":
        stored_proc_tracker.render()
    elif workflow == "Schema and object drift":
        st.session_state["dba_tools_focus"] = "Governance"
        st.info("Focused toolkit: schema compare, recent objects, unused objects, object inventory, and drift checks.")
        dba_tools.render()
    elif workflow == "Data movement and replication":
        st.session_state["dba_tools_focus"] = "Data Movement"
        st.info("Focused toolkit: data loading, Snowpipe, dynamic tables, and replication checks.")
        dba_tools.render()
    else:
        st.session_state["dba_tools_focus"] = "Controlled Actions"
        st.info("Focused toolkit: query cancellation, warehouse settings, task graph control, setup, and audit evidence.")
        dba_tools.render()
