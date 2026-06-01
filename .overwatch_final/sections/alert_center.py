# sections/alert_center.py - single alert inbox and email-first alert operations
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, DEFAULT_ALERT_EMAIL
from utils import (
    ALERT_OPEN_STATUSES,
    ALERT_STATUS_CHOICES,
    acknowledge_alert_escalation,
    alert_escalation_candidates,
    alert_history_to_actions,
    build_alert_digest_body,
    build_alert_digest_subject,
    build_alert_digest_summary,
    build_alert_task_sql,
    build_dashboard_issue_rows,
    download_csv,
    format_snowflake_error,
    get_active_company,
    get_active_environment,
    get_session,
    load_action_queue,
    load_alert_delivery_log,
    load_alert_history,
    load_alert_rule_audit,
    load_alert_rule_catalog,
    log_alert_digest_delivery,
    mark_alerts_routed,
    run_query,
    safe_identifier,
    sql_literal,
    update_alert_rule,
    update_alert_status,
    upsert_actions,
)
from utils.alerts import ANNOTATION_TABLE
from utils.workflows import render_operator_briefing, render_priority_dataframe


ALERT_CENTER_PANES = [
    "Control Health",
    "Issue Inbox",
    "Triage Digest",
    "Alert History",
    "Email Delivery",
    "Action Queue Routing",
    "Rules & SLAs",
    "Suppression Windows",
    "Setup SQL",
]

ALERT_CENTER_SOURCES_BY_PANE = {
    "Control Health": {"alerts", "action_queue", "delivery_log", "rules", "rule_audit"},
    "Issue Inbox": {"alerts", "action_queue"},
    "Triage Digest": {"alerts"},
    "Alert History": {"alerts"},
    "Email Delivery": {"alerts", "delivery_log"},
    "Action Queue Routing": {"alerts", "action_queue"},
    "Rules & SLAs": {"alerts", "rules", "rule_audit"},
    "Suppression Windows": set(),
    "Setup SQL": set(),
}


def _alert_center_sources_for_view(view: str) -> set[str]:
    return set(ALERT_CENTER_SOURCES_BY_PANE.get(view, {"alerts"}))


def _status_key(value) -> str:
    return str(value or "New").strip().upper().replace(" ", "_")


def _open_alert_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty or "STATUS" not in df.columns:
        return pd.Series(dtype=bool)
    return df["STATUS"].apply(_status_key).isin(ALERT_OPEN_STATUSES)


def _alert_actor() -> str:
    return str(st.session_state.get("_overwatch_actor") or "OVERWATCH").strip() or "OVERWATCH"


def _load_center_data(
    session,
    company: str,
    environment: str,
    days: int,
    limit: int,
    sources: set[str] | None = None,
) -> dict:
    sources = set(sources or ALERT_CENTER_SOURCES_BY_PANE["Control Health"])
    data: dict[str, object] = {
        "alerts": pd.DataFrame(),
        "action_queue": pd.DataFrame(),
        "issues": pd.DataFrame(),
        "delivery_log": pd.DataFrame(),
        "rules": pd.DataFrame(),
        "rule_audit": pd.DataFrame(),
        "alerts_error": "",
        "queue_error": "",
        "delivery_error": "",
        "rule_error": "",
        "rule_audit_error": "",
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
        "_loaded_sources": sorted(sources),
    }
    if "alerts" in sources:
        try:
            data["alerts"] = load_alert_history(
                session,
                company=company,
                environment=environment,
                days=days,
                limit=limit,
                section="Alert Center",
            )
        except Exception as exc:
            data["alerts_error"] = format_snowflake_error(exc)
    if "action_queue" in sources:
        try:
            data["action_queue"] = load_action_queue(session, limit=max(200, limit))
        except Exception as exc:
            data["queue_error"] = format_snowflake_error(exc)
    if "delivery_log" in sources:
        try:
            data["delivery_log"] = load_alert_delivery_log(days=max(days, 14), limit=100, section="Alert Center")
        except Exception as exc:
            data["delivery_error"] = format_snowflake_error(exc)
    if "rules" in sources:
        try:
            data["rules"] = load_alert_rule_catalog(section="Alert Center")
        except Exception as exc:
            data["rule_error"] = format_snowflake_error(exc)
    if "rule_audit" in sources:
        try:
            data["rule_audit"] = load_alert_rule_audit(section="Alert Center", limit=50)
        except Exception as exc:
            data["rule_audit_error"] = format_snowflake_error(exc)
    data["issues"] = build_dashboard_issue_rows(
        alerts=data["alerts"] if isinstance(data["alerts"], pd.DataFrame) else pd.DataFrame(),
        queue=data["action_queue"] if isinstance(data["action_queue"], pd.DataFrame) else pd.DataFrame(),
    )
    return data


def _annotation_table_name() -> str:
    return (
        f"{safe_identifier(ALERT_DB)}."
        f"{safe_identifier(ALERT_SCHEMA)}."
        f"{safe_identifier(ANNOTATION_TABLE)}"
    )


def _render_annotations(session) -> None:
    table_name = _annotation_table_name()
    st.subheader("Suppression Windows")
    st.caption("Use suppression windows for planned maintenance, deployments, backfills, and load tests so the hourly alert task does not create duplicate noise.")

    with st.form("alert_center_annotation_create"):
        c1, c2, c3 = st.columns(3)
        with c1:
            entity_type = st.selectbox("Entity type", ["WAREHOUSE", "TASK", "USER", "GLOBAL"], key="alert_annotation_entity_type")
            entity = st.text_input(
                "Entity",
                value="*" if entity_type == "GLOBAL" else "",
                key="alert_annotation_entity",
                placeholder="Warehouse, task, user, or *",
            )
        with c2:
            window_start = st.text_input("Window start", key="alert_annotation_start", placeholder="2026-05-31 22:00:00")
            window_end = st.text_input("Window end", key="alert_annotation_end", placeholder="2026-06-01 02:00:00")
        with c3:
            annotation_type = st.selectbox(
                "Reason",
                ["DEPLOYMENT", "LOAD_TEST", "PLANNED_MAINTENANCE", "BACKFILL", "OTHER"],
                key="alert_annotation_type",
            )
            suppress = st.checkbox("Suppress alerts", value=True, key="alert_annotation_suppress")
        description = st.text_area("Description", key="alert_annotation_description", placeholder="Release, migration, planned warehouse test, etc.")
        submitted = st.form_submit_button("Create Suppression Window")
        if submitted:
            if not entity.strip() or not window_start.strip() or not window_end.strip():
                st.warning("Entity, window start, and window end are required.")
            else:
                try:
                    session.sql(f"""
                        INSERT INTO {table_name}
                            (CREATED_BY, ENTITY, ENTITY_TYPE, WINDOW_START, WINDOW_END,
                             ANNOTATION_TYPE, DESCRIPTION, SUPPRESS_ALERTS, ACTIVE)
                        VALUES (
                            CURRENT_USER(),
                            {sql_literal(entity.strip(), 500)},
                            {sql_literal(entity_type)},
                            {sql_literal(window_start.strip())}::TIMESTAMP_NTZ,
                            {sql_literal(window_end.strip())}::TIMESTAMP_NTZ,
                            {sql_literal(annotation_type)},
                            {sql_literal(description, 2000)},
                            {str(bool(suppress)).upper()},
                            TRUE
                        )
                    """).collect()
                    st.success("Suppression window created.")
                    st.session_state.pop("alert_center_annotations", None)
                except Exception as exc:
                    st.error(f"Could not create suppression window: {format_snowflake_error(exc)}")

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Load Suppression Windows", key="alert_center_load_annotations"):
            try:
                st.session_state["alert_center_annotations"] = run_query(f"""
                    SELECT
                        ANNOTATION_ID,
                        ENTITY,
                        ENTITY_TYPE,
                        WINDOW_START,
                        WINDOW_END,
                        ANNOTATION_TYPE,
                        DESCRIPTION,
                        SUPPRESS_ALERTS,
                        ACTIVE,
                        CREATED_BY,
                        CREATED_AT
                    FROM {table_name}
                    WHERE WINDOW_END >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                    ORDER BY ACTIVE DESC, WINDOW_START DESC
                    LIMIT 300
                """, ttl_key="alert_center_annotations", tier="recent", section="Alert Center")
            except Exception as exc:
                st.info(f"Suppression windows are unavailable until the setup SQL is deployed. {format_snowflake_error(exc)}")
                st.session_state["alert_center_annotations"] = pd.DataFrame()
    with c2:
        st.caption("Active global windows suppress every alert; entity windows suppress only the named warehouse, task, user, or alert entity.")

    df_ann = st.session_state.get("alert_center_annotations")
    if isinstance(df_ann, pd.DataFrame) and not df_ann.empty:
        render_priority_dataframe(
            df_ann,
            title="Suppression windows",
            priority_columns=[
                "ACTIVE", "ENTITY_TYPE", "ENTITY", "WINDOW_START", "WINDOW_END",
                "ANNOTATION_TYPE", "SUPPRESS_ALERTS", "DESCRIPTION",
            ],
            sort_by=["ACTIVE", "WINDOW_START"],
            ascending=[False, False],
            raw_label="All suppression windows",
            height=280,
        )
        download_csv(df_ann, "overwatch_alert_suppression_windows.csv")

        active_ids = df_ann.loc[df_ann.get("ACTIVE", pd.Series(dtype=bool)).astype(bool), "ANNOTATION_ID"].dropna().astype(int).tolist()
        if active_ids:
            selected_id = st.selectbox("Deactivate window", active_ids, key="alert_center_deactivate_id")
            if st.button("Deactivate Suppression Window", key="alert_center_deactivate_annotation"):
                try:
                    session.sql(f"""
                        UPDATE {table_name}
                        SET ACTIVE = FALSE
                        WHERE ANNOTATION_ID = {int(selected_id)}
                    """).collect()
                    st.success(f"Suppression window {int(selected_id)} deactivated.")
                    st.session_state.pop("alert_center_annotations", None)
                except Exception as exc:
                    st.error(f"Deactivate failed: {format_snowflake_error(exc)}")


def _filtered_issues(issues: pd.DataFrame) -> pd.DataFrame:
    if issues is None or issues.empty:
        return pd.DataFrame()
    source_options = ["ALL"] + sorted(issues["ISSUE_SOURCE"].dropna().astype(str).unique().tolist())
    severity_options = ["ALL", "Critical", "High", "Medium", "Low"]
    status_options = ["ALL"] + sorted(issues["STATUS"].dropna().astype(str).unique().tolist())
    f1, f2, f3 = st.columns(3)
    with f1:
        source = st.selectbox("Issue source", source_options, key="alert_center_source_filter")
    with f2:
        severity = st.selectbox("Severity", severity_options, key="alert_center_severity_filter")
    with f3:
        status = st.selectbox("Status", status_options, key="alert_center_status_filter")

    visible = issues
    if source != "ALL":
        visible = visible[visible["ISSUE_SOURCE"] == source]
    if severity != "ALL":
        visible = visible[visible["SEVERITY"] == severity]
    if status != "ALL":
        visible = visible[visible["STATUS"] == status]
    return visible


def _alert_center_operability_rows(
    data: dict,
    *,
    company: str,
    environment: str,
    days: int,
    limit: int,
    loaded_scope: tuple | None = None,
) -> pd.DataFrame:
    """Build a fast Alert Center control-health table from already-loaded data."""

    alerts = data.get("alerts") if isinstance(data.get("alerts"), pd.DataFrame) else pd.DataFrame()
    queue = data.get("action_queue") if isinstance(data.get("action_queue"), pd.DataFrame) else pd.DataFrame()
    delivery_log = data.get("delivery_log") if isinstance(data.get("delivery_log"), pd.DataFrame) else pd.DataFrame()
    rules = data.get("rules") if isinstance(data.get("rules"), pd.DataFrame) else pd.DataFrame()
    issues = data.get("issues") if isinstance(data.get("issues"), pd.DataFrame) else pd.DataFrame()

    rows: list[dict] = []

    def add(control: str, state: str, severity: str, evidence: str, next_action: str, owner: str = "DBA") -> None:
        rows.append({
            "CONTROL": control,
            "STATE": state,
            "SEVERITY": severity,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
            "OWNER": owner,
            "SCOPE": f"{company} / {environment} / {int(days)}d / {int(limit)} rows",
        })

    expected_scope = (company, environment, int(days), int(limit))
    if loaded_scope and loaded_scope != expected_scope:
        add(
            "Loaded scope freshness",
            "Scope Stale",
            "High",
            f"Loaded {loaded_scope}; current filter is {expected_scope}.",
            "Reload Alert Center before triage, routing, or delivery logging.",
        )
    else:
        add(
            "Loaded scope freshness",
            "Ready",
            "Low",
            f"Loaded scope matches current filters: {expected_scope}.",
            "Continue triage from the loaded evidence.",
        )

    alert_error = str(data.get("alerts_error") or "")
    if alert_error:
        add(
            "Alert history source",
            "Needs Setup",
            "High",
            alert_error,
            "Deploy alert table, triage view, and hourly task from Setup SQL.",
        )
    elif alerts.empty:
        add(
            "Alert history source",
            "No Rows",
            "Low",
            "Alert source loaded successfully but returned zero rows.",
            "If issues are expected, validate the hourly alert task and source grants.",
        )
    else:
        open_mask = _open_alert_mask(alerts)
        overdue = int((alerts.get("SLA_STATE", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).eq("Overdue") & open_mask).sum())
        add(
            "Alert history source",
            "Ready",
            "Low" if overdue == 0 else "High",
            f"{len(alerts):,} alert row(s), {int(open_mask.sum()):,} open, {overdue:,} overdue.",
            "Work overdue rows first, then route confirmed alerts to the action queue.",
        )

    queue_error = str(data.get("queue_error") or "")
    if queue_error:
        add(
            "Action queue source",
            "Degraded",
            "Medium",
            queue_error,
            "Deploy or grant action queue access before relying on alert-to-action routing.",
        )
    elif queue.empty:
        add(
            "Action queue source",
            "No Rows",
            "Low",
            "Action queue source loaded successfully with no rows.",
            "Route confirmed open alerts when work needs owner, ticket, and proof tracking.",
        )
    else:
        open_queue = 0
        if "STATUS" in queue.columns:
            open_queue_mask = ~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])
            open_queue = int(open_queue_mask.sum())
        add(
            "Action queue source",
            "Ready",
            "Low",
            f"{len(queue):,} queue row(s) loaded; open count is {open_queue:,}.",
            "Use queue rows to verify owner, due date, ticket, and closure evidence.",
        )

    delivery_error = str(data.get("delivery_error") or "")
    if delivery_error:
        add(
            "Delivery audit source",
            "Needs Setup",
            "Medium",
            delivery_error,
            "Deploy OVERWATCH_ALERT_DELIVERY_LOG before logging digest/email evidence.",
        )
    elif delivery_log.empty:
        add(
            "Delivery audit source",
            "No Rows",
            "Low",
            "Delivery audit table loaded but has no recent rows.",
            "Log the next digest delivery so escalations have audit evidence.",
        )
    else:
        add(
            "Delivery audit source",
            "Ready",
            "Low",
            f"{len(delivery_log):,} delivery audit row(s) loaded.",
            "Use delivery audit rows to prove who was notified and when.",
        )

    if rules.empty:
        add(
            "Rule catalog source",
            "Needs Setup",
            "Medium",
            str(data.get("rule_error") or "No alert rules were loaded."),
            "Deploy OVERWATCH_ALERT_RULES so DBA-owned severity, SLA, route, and runbook edits are persisted.",
        )
    else:
        source = rules.get("RULE_SOURCE", pd.Series(index=rules.index, dtype=str)).fillna("").astype(str)
        configured = int(source.eq("Database").sum())
        fallback = int(len(rules) - configured)
        state = "Ready" if configured else "Fallback"
        add(
            "Rule catalog source",
            state,
            "Low" if configured else "Medium",
            f"{configured:,} database rule(s), {fallback:,} built-in fallback rule(s).",
            "Persist rules in Snowflake before production ownership/SLA changes.",
        )

    email_targets = pd.Series(dtype=str)
    if not alerts.empty and "EMAIL_TARGET" in alerts.columns:
        email_targets = alerts["EMAIL_TARGET"].fillna("").astype(str).str.strip()
    missing_email = int(email_targets.eq("").sum()) if len(email_targets) else 0
    ready_email = int(alerts.get("DELIVERY_STATUS", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).str.upper().str.contains("EMAIL_READY").sum()) if not alerts.empty else 0
    add(
        "Email route",
        "Ready" if missing_email == 0 else "Review",
        "Low" if missing_email == 0 else "Medium",
        f"Default recipient {DEFAULT_ALERT_EMAIL}; {ready_email:,} email-ready alert(s); {missing_email:,} missing target(s).",
        "Keep email-first delivery until the approved Snowflake notification integration is available.",
    )

    generic_owners = {"", "DBA", "OVERWATCH"}
    if alerts.empty or "OWNER" not in alerts.columns:
        generic_count = 0
    else:
        open_mask = _open_alert_mask(alerts)
        generic_count = int(alerts.loc[open_mask, "OWNER"].fillna("").astype(str).str.upper().isin(generic_owners).sum())
    add(
        "Owner route",
        "Ready" if generic_count == 0 else "Review",
        "Low" if generic_count == 0 else "Medium",
        f"{generic_count:,} open alert(s) still have generic or missing owner.",
        "Use owner directory routing before escalating high-severity alerts.",
    )

    add(
        "Unified issue inbox",
        "Ready" if not issues.empty else "No Rows",
        "Low",
        f"{len(issues):,} consolidated issue row(s) from alert history and action queue.",
        "Use the unified inbox as the front door for active DBA issues.",
    )

    order = {"High": 0, "Medium": 1, "Low": 2}
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["_SORT"] = result["SEVERITY"].map(order).fillna(9)
    return result.sort_values(["_SORT", "CONTROL"]).drop(columns=["_SORT"]).reset_index(drop=True)


def _alert_center_readiness_score(rows: pd.DataFrame) -> int:
    if rows is None or rows.empty:
        return 0
    penalty = 0
    for _, row in rows.iterrows():
        state = str(row.get("STATE") or "").upper()
        severity = str(row.get("SEVERITY") or "").upper()
        if state in {"READY", "NO ROWS"}:
            continue
        if severity == "HIGH":
            penalty += 18
        elif severity == "MEDIUM":
            penalty += 10
        else:
            penalty += 4
    return max(0, min(100, 100 - penalty))


def render() -> None:
    session = get_session()
    company = get_active_company()
    environment = get_active_environment()

    render_operator_briefing(
        [
            ("Source of truth", "Alert history and queued actions live here, not scattered across specialist pages."),
            ("Delivery", f"Email-first until Teams exists. Default recipient: {DEFAULT_ALERT_EMAIL}."),
            ("Scope", "Company and environment filters apply when alert rows carry database context."),
            ("DBA action", "Route confirmed alerts to the persistent action queue with owner and proof."),
        ],
        columns=4,
    )

    active_view = st.radio(
        "Alert Center view",
        ALERT_CENTER_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="alert_center_active_view",
    )
    required_sources = _alert_center_sources_for_view(active_view)

    if active_view == "Setup SQL":
        st.subheader("Alert Framework Setup SQL")
        st.caption("Deploy this through controlled Snowflake change management. It creates/updates alerts, owner routing, delivery audit, optional email replay, and the hourly email-ready alert task.")
        st.code(build_alert_task_sql(email_target=DEFAULT_ALERT_EMAIL), language="sql")
        return
    if active_view == "Suppression Windows":
        _render_annotations(session)
        return

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        days = st.selectbox("Alert window", [1, 3, 7, 14, 30], index=2, format_func=lambda value: f"{value} days")
    with c2:
        limit = st.selectbox("Rows", [50, 100, 200, 500], index=2)
    with c3:
        load_label = "Load Full Control Health" if active_view == "Control Health" else f"Load {active_view}"
        if st.button(load_label, key="alert_center_load", type="primary"):
            st.session_state["alert_center_data"] = _load_center_data(
                session,
                company,
                environment,
                int(days),
                int(limit),
                sources=required_sources,
            )
            st.session_state["alert_center_scope"] = (company, environment, int(days), int(limit))

    data = st.session_state.get("alert_center_data")
    if not isinstance(data, dict):
        st.info(f"Load {active_view} to fetch only the source tables needed for this view.")
        return

    loaded_scope = st.session_state.get("alert_center_scope")
    if loaded_scope != (company, environment, int(days), int(limit)):
        st.warning("Company, environment, or window changed after this load. Reload before triaging alerts.")
    loaded_sources = set(data.get("_loaded_sources") or [])
    missing_sources = sorted(required_sources - loaded_sources)
    if missing_sources:
        st.info(f"Load {active_view} to fetch required source(s): {', '.join(missing_sources)}.")
        return

    alerts = data.get("alerts") if isinstance(data.get("alerts"), pd.DataFrame) else pd.DataFrame()
    queue = data.get("action_queue") if isinstance(data.get("action_queue"), pd.DataFrame) else pd.DataFrame()
    issues = data.get("issues") if isinstance(data.get("issues"), pd.DataFrame) else pd.DataFrame()
    delivery_log = data.get("delivery_log") if isinstance(data.get("delivery_log"), pd.DataFrame) else pd.DataFrame()
    rules = data.get("rules") if isinstance(data.get("rules"), pd.DataFrame) else pd.DataFrame()
    rule_audit = data.get("rule_audit") if isinstance(data.get("rule_audit"), pd.DataFrame) else pd.DataFrame()
    if data.get("alerts_error"):
        st.info(f"Alert history unavailable. Deploy the alert table/task setup SQL first. {data['alerts_error']}")
    if data.get("queue_error"):
        st.caption(f"Action queue unavailable for this role/context: {data['queue_error']}")
    if data.get("delivery_error"):
        st.caption(f"Delivery audit unavailable until setup SQL is deployed: {data['delivery_error']}")
    if data.get("rule_error"):
        st.caption(f"Alert rule catalog unavailable until setup SQL is deployed: {data['rule_error']}")
    if data.get("rule_audit_error"):
        st.caption(f"Alert rule audit unavailable until setup SQL is deployed: {data['rule_audit_error']}")
    st.caption(f"Loaded {data.get('loaded_at', '')}. Email target defaults to {DEFAULT_ALERT_EMAIL}.")

    open_alerts = _open_alert_mask(alerts)
    high_alerts = pd.Series(dtype=bool)
    if not alerts.empty:
        high_alerts = alerts["SEVERITY"].isin(["Critical", "High"]) & open_alerts
    email_ready = pd.Series(dtype=bool)
    if not alerts.empty:
        email_ready = alerts["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("EMAIL_READY")
    email_logged = pd.Series(dtype=bool)
    if not alerts.empty:
        email_logged = alerts["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("EMAIL_LOGGED")
    overdue_alerts = pd.Series(dtype=bool)
    if not alerts.empty and "SLA_STATE" in alerts.columns:
        overdue_alerts = alerts["SLA_STATE"].fillna("").astype(str).eq("Overdue") & open_alerts
    open_queue = pd.Series(dtype=bool)
    if not queue.empty and "STATUS" in queue.columns:
        open_queue = ~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])

    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Open Issues", f"{len(issues):,}")
    m2.metric("Open Alerts", f"{int(open_alerts.sum()) if len(open_alerts) else 0:,}")
    m3.metric("Critical / High", f"{int(high_alerts.sum()) if len(high_alerts) else 0:,}")
    m4.metric("Overdue", f"{int(overdue_alerts.sum()) if len(overdue_alerts) else 0:,}", delta_color="inverse")
    m5.metric("Email Ready", f"{int(email_ready.sum()) if len(email_ready) else 0:,}")
    m6.metric("Delivery Logged", f"{int(email_logged.sum()) if len(email_logged) else 0:,}")
    m7.metric("Open Queue", f"{int(open_queue.sum()) if len(open_queue) else 0:,}")

    readiness_rows = pd.DataFrame()
    readiness_score = 0
    if active_view == "Control Health":
        readiness_rows = _alert_center_operability_rows(
            data,
            company=company,
            environment=environment,
            days=int(days),
            limit=int(limit),
            loaded_scope=loaded_scope,
        )
        readiness_score = _alert_center_readiness_score(readiness_rows)

    if active_view == "Control Health":
        st.subheader("Alert Control Health")
        st.caption("Uses only the data loaded by the explicit Alert Center refresh. No hidden tab scans are required to review source readiness.")
        h1, h2, h3, h4 = st.columns(4)
        blocked = int(readiness_rows["STATE"].isin(["Needs Setup", "Degraded", "Scope Stale"]).sum()) if not readiness_rows.empty else 0
        review = int(readiness_rows["STATE"].eq("Review").sum()) if not readiness_rows.empty else 0
        ready = int(readiness_rows["STATE"].isin(["Ready", "No Rows"]).sum()) if not readiness_rows.empty else 0
        h1.metric("Readiness", f"{readiness_score}/100")
        h2.metric("Ready Controls", f"{ready:,}")
        h3.metric("Needs Review", f"{review:,}", delta_color="inverse")
        h4.metric("Blocked / Setup", f"{blocked:,}", delta_color="inverse")
        render_priority_dataframe(
            readiness_rows,
            title="Alert source and delivery readiness",
            priority_columns=[
                "SEVERITY", "CONTROL", "STATE", "EVIDENCE", "NEXT_ACTION", "OWNER", "SCOPE",
            ],
            sort_by=["SEVERITY", "CONTROL"],
            ascending=[True, True],
            raw_label="All alert control-health rows",
            height=360,
        )

    elif active_view == "Issue Inbox":
        st.subheader("All Active DBA Issues")
        visible = _filtered_issues(issues)
        if visible.empty:
            st.success("No active alert or action queue issues found for this scope.")
        else:
            render_priority_dataframe(
                visible,
                title="Unified DBA issue inbox",
                priority_columns=[
                    "ISSUE_SOURCE", "SEVERITY", "STATUS", "DOMAIN", "SIGNAL",
                    "ENTITY", "DETAIL", "NEXT_ACTION", "OWNER", "EMAIL_TARGET",
                    "DELIVERY_STATUS", "ROUTE",
                ],
                sort_by=["SEVERITY", "ISSUE_SOURCE", "SIGNAL"],
                ascending=[True, True, True],
                raw_label="All active issues",
                height=420,
            )
            download_csv(visible, "overwatch_alert_center_issues.csv")

    elif active_view == "Triage Digest":
        st.subheader("DBA Triage Digest")
        if alerts.empty:
            st.info("Load alert history before building the operator digest.")
        else:
            digest_summary = build_alert_digest_summary(alerts)
            d1, d2, d3, d4, d5 = st.columns(5)
            d1.metric("Open", f"{digest_summary['open']:,}")
            d2.metric("Critical / High", f"{digest_summary['critical_high']:,}")
            d3.metric("Overdue", f"{digest_summary['overdue']:,}", delta_color="inverse")
            d4.metric("Due Soon", f"{digest_summary['due_soon']:,}")
            d5.metric("Needs Owner", f"{digest_summary['needs_owner']:,}")

            digest_subject = build_alert_digest_subject(alerts, company=company, environment=environment)
            digest_body = build_alert_digest_body(
                alerts,
                company=company,
                environment=environment,
                recipient=DEFAULT_ALERT_EMAIL,
                limit=10,
            )
            st.text_input("Digest email subject", value=digest_subject, key="alert_center_digest_subject")
            st.text_area("Digest email body", value=digest_body, height=340, key="alert_center_digest_body")
            with st.expander("Log digest delivery", expanded=False):
                st.caption("Use this after the email digest is sent or handed off. This records delivery evidence and marks included alerts as escalated.")
                with st.form("alert_center_log_digest_delivery"):
                    delivery_target = st.text_input(
                        "Delivery target",
                        value=DEFAULT_ALERT_EMAIL,
                        key="alert_center_digest_target",
                    )
                    delivery_notes = st.text_area(
                        "Delivery notes",
                        key="alert_center_digest_notes",
                        placeholder="Example: Sent via Outlook to DBA on-call and platform owner; INC12345 opened.",
                    )
                    submitted_delivery = st.form_submit_button("Log Digest Delivery")
                if submitted_delivery:
                    digest_alerts = alerts[_open_alert_mask(alerts)]
                    if digest_alerts.empty:
                        st.warning("No open alert rows are available to log.")
                    elif len(delivery_notes.strip()) < 10:
                        st.warning("Delivery notes are required for audit evidence.")
                    else:
                        try:
                            logged = log_alert_digest_delivery(
                                session,
                                digest_alerts,
                                company=company,
                                environment=environment,
                                delivery_target=delivery_target,
                                email_subject=digest_subject,
                                email_body=digest_body,
                                actor=_alert_actor(),
                                notes=delivery_notes,
                            )
                            st.success(f"Logged digest delivery for {logged:,} alert(s). Reload the Alert Center to refresh delivery state.")
                            st.session_state.pop("alert_center_data", None)
                        except Exception as exc:
                            st.error(f"Could not log digest delivery: {format_snowflake_error(exc)}")

            candidates = alert_escalation_candidates(alerts, limit=15)
            if candidates.empty:
                st.success("No escalation candidates for this scope.")
            else:
                render_priority_dataframe(
                    candidates,
                    title="Escalate first",
                    priority_columns=[
                        "ALERT_TS", "SLA_STATE", "ALERT_AGE_HOURS", "SEVERITY",
                        "CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER",
                        "ESCALATION_TARGET", "MESSAGE", "SUGGESTED_ACTION",
                    ],
                    sort_by=["TRIAGE_PRIORITY", "ALERT_TS"],
                    ascending=[True, False],
                    raw_label="All escalation candidates",
                    height=300,
                )

            if not alerts.empty and {"CATEGORY", "SLA_STATE", "SEVERITY"}.issubset(alerts.columns):
                category_mix = (
                    alerts[_open_alert_mask(alerts)]
                    .groupby(["CATEGORY", "SLA_STATE", "SEVERITY"], dropna=False)
                    .size()
                    .reset_index(name="ALERTS")
                    .sort_values(["SLA_STATE", "SEVERITY", "ALERTS"], ascending=[True, True, False])
                )
                if not category_mix.empty:
                    render_priority_dataframe(
                        category_mix,
                        title="Open alert mix",
                        priority_columns=["CATEGORY", "SLA_STATE", "SEVERITY", "ALERTS"],
                        sort_by=["SLA_STATE", "SEVERITY", "ALERTS"],
                        ascending=[True, True, False],
                        raw_label="All open alert mix rows",
                        height=220,
                    )

    elif active_view == "Alert History":
        st.subheader("Alert History")
        if alerts.empty:
            st.info("No alert history rows found for this scope.")
        else:
            render_priority_dataframe(
                alerts,
                title="Alert history",
                priority_columns=[
                    "ALERT_TS", "ALERT_AGE_HOURS", "SLA_TARGET_HOURS", "SLA_STATE",
                    "SEVERITY", "STATUS", "CATEGORY", "ALERT_TYPE",
                    "ENTITY_NAME", "ENVIRONMENT", "MESSAGE", "SUGGESTED_ACTION",
                    "OWNER", "ESCALATION_TARGET", "ESCALATED_AT", "ESCALATION_ACK_AT",
                    "DELIVERY_STATUS", "LAST_DELIVERY_AT",
                ],
                sort_by=["TRIAGE_PRIORITY", "ALERT_TS"],
                ascending=[True, False],
                raw_label="All alert history rows",
                height=420,
            )
            download_csv(alerts, "overwatch_alert_history.csv")

            alert_ids = alerts["ALERT_ID"].dropna().astype(str).tolist() if "ALERT_ID" in alerts.columns else []
            if alert_ids:
                with st.expander("Update alert lifecycle", expanded=False):
                    with st.form("alert_center_status_update"):
                        c_status_1, c_status_2 = st.columns([1, 1])
                        with c_status_1:
                            selected_alert = st.selectbox("Alert ID", alert_ids, key="alert_center_status_alert_id")
                        with c_status_2:
                            next_status = st.selectbox("New status", list(ALERT_STATUS_CHOICES), key="alert_center_next_status")
                        reason = st.text_area(
                            "Reason / evidence",
                            key="alert_center_status_reason",
                            placeholder="Ticket, owner confirmation, remediation proof, or reason for ignore.",
                        )
                        submitted = st.form_submit_button("Update Alert Status")
                    if submitted:
                        if not reason.strip():
                            st.warning("A reason or evidence note is required before changing alert status.")
                        else:
                            try:
                                update_alert_status(
                                    session,
                                    selected_alert,
                                    next_status,
                                    reason=reason,
                                    actor=_alert_actor(),
                                )
                                st.success(f"Alert {selected_alert} moved to {next_status}. Reload the Alert Center to refresh the queue.")
                                st.session_state.pop("alert_center_data", None)
                            except Exception as exc:
                                st.error(f"Could not update alert status: {format_snowflake_error(exc)}")
                with st.expander("Acknowledge escalation", expanded=False):
                    with st.form("alert_center_escalation_ack"):
                        ack_alert = st.selectbox("Escalated alert ID", alert_ids, key="alert_center_ack_alert_id")
                        ack_note = st.text_area(
                            "Acknowledgment note",
                            key="alert_center_ack_note",
                            placeholder="Owner accepted, ticket opened, escalation recipient confirmed, or next checkpoint.",
                        )
                        submitted_ack = st.form_submit_button("Acknowledge Escalation")
                    if submitted_ack:
                        if len(ack_note.strip()) < 10:
                            st.warning("Acknowledgment note is required for escalation audit.")
                        else:
                            try:
                                acknowledge_alert_escalation(
                                    session,
                                    ack_alert,
                                    actor=_alert_actor(),
                                    note=ack_note,
                                )
                                st.success(f"Escalation acknowledged for alert {ack_alert}. Reload the Alert Center to refresh.")
                                st.session_state.pop("alert_center_data", None)
                            except Exception as exc:
                                st.error(f"Could not acknowledge escalation: {format_snowflake_error(exc)}")

    elif active_view == "Email Delivery":
        st.subheader("Email Delivery Queue")
        st.caption("Rows are email-ready by default; the setup SQL also includes a dry-run governed SYSTEM$SEND_EMAIL procedure for an approved Snowflake email integration.")
        if alerts.empty:
            st.info("No email-ready alert rows found.")
        else:
            email_view = alerts.copy()
            email_view["EMAIL_TARGET"] = email_view["EMAIL_TARGET"].replace("", DEFAULT_ALERT_EMAIL).fillna(DEFAULT_ALERT_EMAIL)
            render_priority_dataframe(
                email_view,
                title="Email-ready alert messages",
                priority_columns=[
                    "ALERT_TS", "SEVERITY", "DELIVERY_STATUS", "EMAIL_TARGET",
                    "EMAIL_SUBJECT", "ENTITY_NAME", "MESSAGE",
                ],
                sort_by=["ALERT_TS"],
                ascending=False,
                raw_label="All email delivery rows",
                height=320,
            )
            for _, row in email_view.head(5).iterrows():
                with st.expander(str(row.get("EMAIL_SUBJECT") or "OVERWATCH alert email"), expanded=False):
                    st.text(str(row.get("EMAIL_BODY") or row.get("MESSAGE") or "No email body captured."))
        st.subheader("Delivery Audit")
        if delivery_log.empty:
            st.info("No delivery audit rows loaded for this window.")
        else:
            render_priority_dataframe(
                delivery_log,
                title="Email delivery audit",
                priority_columns=[
                    "DELIVERY_TS", "DELIVERY_STATUS", "DELIVERY_TARGET", "ALERT_COUNT",
                    "EMAIL_SUBJECT", "DELIVERY_BY", "DELIVERY_NOTES",
                ],
                sort_by=["DELIVERY_TS"],
                ascending=False,
                raw_label="All delivery audit rows",
                height=260,
            )

    elif active_view == "Action Queue Routing":
        st.subheader("Route Alerts To Action Queue")
        if alerts.empty:
            st.info("Load alert history before routing alerts to the action queue.")
        else:
            routable = alerts[_open_alert_mask(alerts)] if not alerts.empty else alerts
            st.caption(f"{len(routable):,} open alert row(s) are eligible for action queue routing.")
            actions_preview = pd.DataFrame(alert_history_to_actions(routable, company=company))
            if not actions_preview.empty:
                recovery_count = int((actions_preview.get("Category", pd.Series(dtype=str)) == "Task & Procedure Reliability").sum())
                if recovery_count:
                    st.caption(f"{recovery_count:,} task/procedure recovery action(s) include owner approval and recovery SLA evidence fields.")
                render_priority_dataframe(
                    actions_preview,
                    title="Action queue routing preview",
                    priority_columns=[
                        "Severity", "Category", "Entity Type", "Entity", "Owner",
                        "Oncall Primary", "Approval Group", "Owner Source",
                        "Owner Approval Status", "Recovery SLA State", "Recovery SLA Target Hours",
                        "Verification Status", "Action",
                    ],
                    sort_by=["Severity", "Category", "Entity"],
                    ascending=[True, True, True],
                    raw_label="All routed action fields",
                    height=300,
                )
            if st.button("Send Open Alerts To Action Queue", key="alert_center_to_action_queue"):
                try:
                    saved = upsert_actions(session, actions_preview.to_dict("records"))
                    alert_ids = routable.get("ALERT_ID", pd.Series(dtype=str)).dropna().astype(str).tolist()
                    mark_alerts_routed(session, alert_ids, action_count=saved, actor=_alert_actor())
                    st.success(f"Saved {saved} alert action(s) to the action queue.")
                    st.session_state.pop("alert_center_data", None)
                except Exception as exc:
                    st.error(f"Could not save alerts to action queue: {format_snowflake_error(exc)}")
        if not queue.empty:
            render_priority_dataframe(
                queue,
                title="Current action queue",
                priority_columns=[
                    "SEVERITY", "STATUS", "CATEGORY", "ENTITY_NAME", "OWNER",
                    "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
                    "FINDING", "RECOMMENDED_ACTION", "TICKET_ID", "DUE_STATE",
                    "EVIDENCE_GAP",
                ],
                sort_by=["SEVERITY", "STATUS", "UPDATED_AT"],
                ascending=[True, True, False],
                raw_label="All action queue rows",
                height=320,
            )

    elif active_view == "Rules & SLAs":
        st.subheader("Alert Rules And SLAs")
        render_priority_dataframe(
            rules,
            title="Active alert rules",
            priority_columns=[
                "RULE_ID", "CATEGORY", "ALERT_TYPE", "DEFAULT_SEVERITY",
                "SLA_HOURS", "OWNER", "ROUTE", "IS_ACTIVE", "RULE_SOURCE", "RUNBOOK",
            ],
            sort_by=["SLA_HOURS", "CATEGORY", "ALERT_TYPE"],
            ascending=[True, True, True],
            max_rows=50,
            raw_label="All alert rules",
            height=320,
        )
        if not rule_audit.empty:
            render_priority_dataframe(
                rule_audit,
                title="Recent rule changes",
                priority_columns=[
                    "AUDIT_TS", "RULE_ID", "ACTION", "PRIOR_DEFAULT_SEVERITY", "NEW_DEFAULT_SEVERITY",
                    "PRIOR_SLA_HOURS", "NEW_SLA_HOURS", "PRIOR_OWNER", "NEW_OWNER",
                    "CHANGED_BY", "CHANGE_REASON",
                ],
                sort_by=["AUDIT_TS"],
                ascending=False,
                raw_label="All rule audit rows",
                height=260,
            )
        if not rules.empty:
            configured_count = int((rules["RULE_SOURCE"].astype(str) == "Database").sum()) if "RULE_SOURCE" in rules.columns else 0
            st.caption(
                f"{configured_count:,} rule(s) loaded from Snowflake configuration; "
                f"{len(rules) - configured_count:,} built-in fallback rule(s) shown for deployment readiness."
            )
            editable_rules = rules[rules.get("RULE_SOURCE", pd.Series(index=rules.index, dtype=str)).astype(str).eq("Database")]
            if editable_rules.empty:
                st.info("Deploy `OVERWATCH_ALERT_RULES` from Setup SQL before editing alert rule ownership, SLA, and routing.")
            else:
                with st.expander("Edit alert rule routing and SLA", expanded=False):
                    selected_rule = st.selectbox(
                        "Rule",
                        editable_rules["RULE_ID"].dropna().astype(str).tolist(),
                        key="alert_center_rule_id",
                    )
                    selected_row = editable_rules[editable_rules["RULE_ID"].astype(str) == str(selected_rule)].iloc[0]
                    with st.form("alert_center_rule_update"):
                        r1, r2, r3 = st.columns([1, 1, 2])
                        with r1:
                            severity = st.selectbox(
                                "Default severity",
                                ["Critical", "High", "Medium", "Low"],
                                index=["Critical", "High", "Medium", "Low"].index(str(selected_row.get("DEFAULT_SEVERITY", "Medium"))),
                                key="alert_center_rule_severity",
                            )
                        with r2:
                            sla_hours = st.number_input(
                                "SLA hours",
                                min_value=1,
                                max_value=168,
                                value=int(selected_row.get("SLA_HOURS", 24) or 24),
                                step=1,
                                key="alert_center_rule_sla",
                            )
                        with r3:
                            owner = st.text_input("Owner", value=str(selected_row.get("OWNER", "DBA")), key="alert_center_rule_owner")
                        route = st.text_input("Route", value=str(selected_row.get("ROUTE", "Alert Center")), key="alert_center_rule_route")
                        runbook = st.text_area(
                            "Runbook",
                            value=str(selected_row.get("RUNBOOK", "")),
                            key="alert_center_rule_runbook",
                        )
                        is_active = st.checkbox(
                            "Active",
                            value=bool(selected_row.get("IS_ACTIVE", True)),
                            key="alert_center_rule_active",
                        )
                        submitted_rule = st.form_submit_button("Update Alert Rule")
                    if submitted_rule:
                        try:
                            update_alert_rule(
                                session,
                                rule_id=selected_rule,
                                default_severity=severity,
                                sla_hours=int(sla_hours),
                                owner=owner,
                                route=route,
                                runbook=runbook,
                                is_active=bool(is_active),
                                actor=_alert_actor(),
                            )
                            st.success(f"Updated alert rule {selected_rule}. Reload the Alert Center to refresh rule metadata.")
                            st.session_state.pop("alert_center_data", None)
                        except Exception as exc:
                            st.error(f"Could not update alert rule: {format_snowflake_error(exc)}")
        if not alerts.empty and "SLA_STATE" in alerts.columns:
            sla_summary = (
                alerts.groupby(["SLA_STATE", "SEVERITY"], dropna=False)
                .size()
                .reset_index(name="ALERTS")
                .sort_values(["SLA_STATE", "SEVERITY"])
            )
            render_priority_dataframe(
                sla_summary,
                title="Loaded alert SLA mix",
                priority_columns=["SLA_STATE", "SEVERITY", "ALERTS"],
                sort_by=["SLA_STATE", "SEVERITY"],
                ascending=[True, True],
                max_rows=20,
                raw_label="All SLA mix rows",
                height=220,
            )
