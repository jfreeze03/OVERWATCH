# sections/alert_center.py - single alert inbox and email-first alert operations
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, DAY_WINDOW_OPTIONS, DEFAULT_ALERT_EMAIL, DEFAULT_DAY_WINDOW
from sections.shell_helpers import render_shell_snapshot


ANNOTATION_TABLE = "OVERWATCH_ANNOTATIONS"
_DEFERRED_NOTES_PREFIX = "_overwatch_deferred_section_notes"


def _deferred_notes_key(section: str) -> str:
    safe_section = str(section or "section").strip() or "section"
    return f"{_DEFERRED_NOTES_PREFIX}:{safe_section}"


def defer_source_note(*parts: object, section: str | None = None) -> None:
    """Collect Alert Center source notes without importing the full playbook module on first paint."""
    clean_parts = [
        " ".join(str(part or "").split())
        for part in parts
        if str(part or "").strip()
    ]
    if not clean_parts:
        return
    active_section = section or st.session_state.get("_overwatch_active_section", "")
    key = _deferred_notes_key(active_section)
    clean_note = " | ".join(clean_parts)
    notes = list(st.session_state.get(key, []))
    if clean_note not in notes:
        notes.append(clean_note)
    st.session_state[key] = notes

ALERT_CENTER_PANES = [
    "Alert Brief",
    "Issue Inbox",
    "Triage Digest",
    "Alert History",
    "Email Delivery",
    "Action Queue Routing",
    "Control Health",
    "Automation Readiness",
    "Rules & SLAs",
    "Suppression Windows",
]

ALERT_CENTER_PANE_LABELS = {
    "Alert Brief": "Brief",
    "Issue Inbox": "Inbox",
    "Triage Digest": "Digest",
    "Alert History": "History",
    "Email Delivery": "Email",
    "Action Queue Routing": "Routing",
    "Control Health": "Controls",
    "Automation Readiness": "Automation",
    "Rules & SLAs": "Rules",
    "Suppression Windows": "Suppressions",
}

ALERT_CENTER_HEALTH_DETAIL_OPTIONS = (
    "Controls",
    "Owner Routes",
    "Owner Directory",
    "Delivery & ITSM",
)

ALERT_CENTER_BRIEF_FIRST_VERSION = 2

ALERT_CENTER_BRIEF_WORKFLOWS = (
    {
        "VIEW": "Issue Inbox",
        "BUTTON_LABEL": "Open Issue Inbox",
        "DBA_MOVE": "Start with the combined alert and action-queue inbox.",
        "WHEN": "Morning triage, new alerts, owner assignment",
    },
    {
        "VIEW": "Triage Digest",
        "BUTTON_LABEL": "Open Triage Digest",
        "DBA_MOVE": "Escalate critical, high, and overdue rows first.",
        "WHEN": "Shift handoff, incident review, email digest prep",
    },
    {
        "VIEW": "Email Delivery",
        "BUTTON_LABEL": "Open Delivery",
        "DBA_MOVE": "Prove which alerts are email-ready or already logged.",
        "WHEN": "Notification audit, executive proof, daily digest",
    },
    {
        "VIEW": "Action Queue Routing",
        "BUTTON_LABEL": "Open Queue Routing",
        "DBA_MOVE": "Move alert evidence into accountable owner work.",
        "WHEN": "Queue closure, ticket routing, DBA follow-up",
    },
    {
        "VIEW": "Control Health",
        "BUTTON_LABEL": "Open Control Health",
        "DBA_MOVE": "Check source readiness, owner routing, and control gaps.",
        "WHEN": "Setup validation, route gaps, delivery issues",
    },
    {
        "VIEW": "Automation Readiness",
        "BUTTON_LABEL": "Open Automation",
        "DBA_MOVE": "Review no-touch alert, Control-M, Jira, Terraform, and Flyway health.",
        "WHEN": "Automation checks, external feed freshness",
    },
)

ALERT_CENTER_SOURCES_BY_PANE = {
    "Alert Brief": set(),
    "Control Health": {"alerts", "action_queue", "delivery_log", "rules", "rule_audit", "owner_directory"},
    "Automation Readiness": {"alerts", "action_queue", "delivery_log", "rules", "owner_directory", "automation_health"},
    "Issue Inbox": {"alerts", "action_queue"},
    "Triage Digest": {"alerts"},
    "Alert History": {"alerts"},
    "Email Delivery": {"alerts", "delivery_log"},
    "Action Queue Routing": {"alerts", "action_queue"},
    "Rules & SLAs": {"alerts", "rules", "rule_audit"},
    "Suppression Windows": set(),
}

ALERT_CENTER_SOURCE_PLAN = {
    "alerts": {
        "SOURCE": "Alert history",
        "OBJECT": "Alert triage view",
        "WHY": "Open issues, SLA state, email-ready rows",
        "COST_GUARDRAIL": "Bounded by selected window and row limit",
    },
    "action_queue": {
        "SOURCE": "Action queue",
        "OBJECT": "Persistent DBA action queue",
        "WHY": "Owner, ticket, due date, and proof tracking",
        "COST_GUARDRAIL": "Limited queue read",
    },
    "delivery_log": {
        "SOURCE": "Email delivery audit",
        "OBJECT": "Alert delivery log",
        "WHY": "Notification evidence and escalation audit",
        "COST_GUARDRAIL": "Recent-window audit read",
    },
    "rules": {
        "SOURCE": "Rule catalog",
        "OBJECT": "Alert rules",
        "WHY": "Severity, SLA, owner, route, and runbook control",
        "COST_GUARDRAIL": "Small configuration read",
    },
    "rule_audit": {
        "SOURCE": "Rule audit",
        "OBJECT": "Alert rule audit",
        "WHY": "Evidence for alert-rule changes",
        "COST_GUARDRAIL": "Recent configuration audit read",
    },
    "owner_directory": {
        "SOURCE": "Owner directory",
        "OBJECT": "Owner/on-call routing directory",
        "WHY": "Named owner, email, approval, and escalation readiness",
        "COST_GUARDRAIL": "Small configuration read with built-in fallback",
    },
    "automation_health": {
        "SOURCE": "No-touch automation health",
        "OBJECT": "OVERWATCH_AUTOMATION_HEALTH_V",
        "WHY": "Scheduled run state and Control-M/Jira/Terraform/Flyway feed freshness",
        "COST_GUARDRAIL": "Single-row health view",
    },
}


def _alert_email_target() -> str:
    from utils.alerts import current_alert_recipient

    return current_alert_recipient(DEFAULT_ALERT_EMAIL)


def _alert_center_sources_for_view(view: str) -> set[str]:
    return set(ALERT_CENTER_SOURCES_BY_PANE.get(view, {"alerts"}))


def _alert_center_source_summary(sources: set[str]) -> str:
    names = [
        str(ALERT_CENTER_SOURCE_PLAN[source]["SOURCE"])
        for source in sorted(sources)
        if source in ALERT_CENTER_SOURCE_PLAN
    ]
    return ", ".join(names) if names else "No Snowflake sources"


def _status_key(value) -> str:
    return str(value or "New").strip().upper().replace(" ", "_")


def _alert_open_statuses() -> set[str]:
    from utils import ALERT_OPEN_STATUSES

    return ALERT_OPEN_STATUSES


def _format_snowflake_error(exc: Exception) -> str:
    from utils import format_snowflake_error

    return format_snowflake_error(exc)


def _alert_center_action_session(action: str):
    from utils import get_session_for_action

    return get_session_for_action(
        action,
        surface="Alert Center",
        offline_note=(
            "Alert Center source summaries remain available without a connection. "
            "Alert DDL is managed in snowflake/OVERWATCH_MART_SETUP.sql."
        ),
    )


def _download_csv(df: pd.DataFrame, file_name: str) -> None:
    from utils import download_csv

    download_csv(df, file_name)


def _pd():
    import pandas as pd

    return pd


def get_active_company() -> str:
    from utils import get_active_company as _get_active_company

    return _get_active_company()


def get_active_environment() -> str:
    from utils import get_active_environment as _get_active_environment

    return _get_active_environment()


def _render_priority_dataframe(*args, **kwargs) -> None:
    from utils.workflows import render_priority_dataframe

    render_priority_dataframe(*args, **kwargs)


def _render_workflow_selector(*args, **kwargs) -> str:
    from utils.workflows import render_workflow_selector

    return render_workflow_selector(*args, **kwargs)


def _open_alert_mask(df: pd.DataFrame) -> pd.Series:
    pd = _pd()
    if df is None or df.empty or "STATUS" not in df.columns:
        return pd.Series(dtype=bool)
    return df["STATUS"].apply(_status_key).isin(_alert_open_statuses())


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
    pd = _pd()
    from utils.alerts import (
        build_dashboard_issue_rows,
        load_alert_delivery_log,
        load_alert_history,
        load_alert_rule_audit,
        load_alert_rule_catalog,
    )

    sources = set(sources or ALERT_CENTER_SOURCES_BY_PANE["Control Health"])
    data: dict[str, object] = {
        "alerts": pd.DataFrame(),
        "action_queue": pd.DataFrame(),
        "issues": pd.DataFrame(),
        "delivery_log": pd.DataFrame(),
        "rules": pd.DataFrame(),
        "rule_audit": pd.DataFrame(),
        "owner_directory": pd.DataFrame(),
        "automation_health": pd.DataFrame(),
        "alerts_error": "",
        "queue_error": "",
        "delivery_error": "",
        "rule_error": "",
        "rule_audit_error": "",
        "owner_directory_error": "",
        "automation_health_error": "",
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
            data["alerts_error"] = _format_snowflake_error(exc)
    if "action_queue" in sources:
        try:
            from utils.action_queue import load_action_queue

            data["action_queue"] = load_action_queue(session, limit=max(200, limit))
        except Exception as exc:
            data["queue_error"] = _format_snowflake_error(exc)
    if "delivery_log" in sources:
        try:
            data["delivery_log"] = load_alert_delivery_log(days=max(days, 14), limit=100, section="Alert Center")
        except Exception as exc:
            data["delivery_error"] = _format_snowflake_error(exc)
    if "rules" in sources:
        try:
            data["rules"] = load_alert_rule_catalog(section="Alert Center")
        except Exception as exc:
            data["rule_error"] = _format_snowflake_error(exc)
    if "rule_audit" in sources:
        try:
            data["rule_audit"] = load_alert_rule_audit(section="Alert Center", limit=50)
        except Exception as exc:
            data["rule_audit_error"] = _format_snowflake_error(exc)
    if "owner_directory" in sources:
        try:
            from utils import load_owner_directory

            data["owner_directory"] = load_owner_directory(section="Alert Center")
        except Exception as exc:
            data["owner_directory_error"] = _format_snowflake_error(exc)
    if "automation_health" in sources:
        try:
            from utils import run_query_or_raise

            data["automation_health"] = run_query_or_raise(
                """
                SELECT
                  RUN_TS,
                  COMPANY,
                  ENVIRONMENT,
                  PRIMARY_EVIDENCE_STATE,
                  ACTION_QUEUE_SEEDED,
                  OWNER_ROUTES_UPDATED,
                  VERIFIED_SAVINGS_STATE,
                  ALERT_DIGEST_STATE,
                  EXTERNAL_FEED_ROWS,
                  OPEN_ACTIONS,
                  VERIFIED_ACTIONS,
                  CONTROL_M_ROWS,
                  TERRAFORM_ROWS,
                  FLYWAY_ROWS,
                  GIT_ROWS,
                  JIRA_ROWS,
                  LAST_DIGEST_TS,
                  TERRAFORM_DRIFT_MODE,
                  NEXT_ACTION
                FROM OVERWATCH_AUTOMATION_HEALTH_V
                LIMIT 1
                """,
                section="Alert Center",
                ttl_key=f"alert_center_automation_health_{company}_{environment}",
                tier="standard",
                max_rows=5,
            )
        except Exception as exc:
            data["automation_health_error"] = _format_snowflake_error(exc)
    data["issues"] = build_dashboard_issue_rows(
        alerts=data["alerts"] if isinstance(data["alerts"], pd.DataFrame) else pd.DataFrame(),
        queue=data["action_queue"] if isinstance(data["action_queue"], pd.DataFrame) else pd.DataFrame(),
    )
    return data


def _annotation_table_name() -> str:
    from utils import safe_identifier

    return (
        f"{safe_identifier(ALERT_DB)}."
        f"{safe_identifier(ALERT_SCHEMA)}."
        f"{safe_identifier(ANNOTATION_TABLE)}"
    )


def _render_annotations() -> None:
    pd = _pd()
    table_name = _annotation_table_name()
    st.subheader("Suppression Windows")
    st.caption("Use suppression windows for planned maintenance, deployments, backfills, and high-volume validation windows so the hourly alert task does not create duplicate noise.")

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
                ["DEPLOYMENT", "HIGH_VOLUME_VALIDATION", "PLANNED_MAINTENANCE", "BACKFILL", "OTHER"],
                key="alert_annotation_type",
            )
            suppress = st.checkbox("Suppress alerts", value=True, key="alert_annotation_suppress")
        description = st.text_area("Description", key="alert_annotation_description", placeholder="Release, migration, planned warehouse validation, etc.")
        submitted = st.form_submit_button("Create Suppression Window")
        if submitted:
            if not entity.strip() or not window_start.strip() or not window_end.strip():
                st.warning("Entity, window start, and window end are required.")
            else:
                try:
                    from utils import sql_literal

                    session = _alert_center_action_session("create a suppression window")
                    if session is None:
                        return
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
                    st.error(f"Could not create suppression window: {_format_snowflake_error(exc)}")

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Load Suppression Windows", key="alert_center_load_annotations"):
            try:
                from utils import run_query

                session = _alert_center_action_session("load suppression windows")
                if session is None:
                    st.session_state["alert_center_annotations"] = pd.DataFrame()
                    return
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
                st.info(f"Suppression windows are unavailable until `snowflake/OVERWATCH_MART_SETUP.sql` is deployed. {_format_snowflake_error(exc)}")
                st.session_state["alert_center_annotations"] = pd.DataFrame()
    with c2:
        st.caption("Active global windows suppress every alert; entity windows suppress only the named warehouse, task, user, or alert entity.")

    df_ann = st.session_state.get("alert_center_annotations")
    if isinstance(df_ann, pd.DataFrame) and not df_ann.empty:
        _render_priority_dataframe(
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
        _download_csv(df_ann, "overwatch_alert_suppression_windows.csv")

        active_ids = df_ann.loc[df_ann.get("ACTIVE", pd.Series(dtype=bool)).astype(bool), "ANNOTATION_ID"].dropna().astype(int).tolist()
        if active_ids:
            selected_id = st.selectbox("Deactivate window", active_ids, key="alert_center_deactivate_id")
            if st.button("Deactivate Suppression Window", key="alert_center_deactivate_annotation"):
                try:
                    session = _alert_center_action_session("deactivate a suppression window")
                    if session is None:
                        return
                    session.sql(f"""
                        UPDATE {table_name}
                        SET ACTIVE = FALSE
                        WHERE ANNOTATION_ID = {int(selected_id)}
                    """).collect()
                    st.success(f"Suppression window {int(selected_id)} deactivated.")
                    st.session_state.pop("alert_center_annotations", None)
                except Exception as exc:
                    st.error(f"Deactivate failed: {_format_snowflake_error(exc)}")


def _filtered_issues(issues: pd.DataFrame) -> pd.DataFrame:
    pd = _pd()
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

    pd = _pd()
    alerts = data.get("alerts") if isinstance(data.get("alerts"), pd.DataFrame) else pd.DataFrame()
    queue = data.get("action_queue") if isinstance(data.get("action_queue"), pd.DataFrame) else pd.DataFrame()
    delivery_log = data.get("delivery_log") if isinstance(data.get("delivery_log"), pd.DataFrame) else pd.DataFrame()
    rules = data.get("rules") if isinstance(data.get("rules"), pd.DataFrame) else pd.DataFrame()
    owner_directory = data.get("owner_directory") if isinstance(data.get("owner_directory"), pd.DataFrame) else pd.DataFrame()
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
            "Deploy alert objects from snowflake/OVERWATCH_MART_SETUP.sql.",
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

    owner_directory_error = str(data.get("owner_directory_error") or "")
    if owner_directory_error:
        add(
            "Owner directory source",
            "Degraded",
            "Medium",
            owner_directory_error,
            "Deploy or grant the owner directory before trusting named route coverage.",
        )
    else:
        try:
            from utils import owner_directory_readiness_board

            owner_summary, _owner_board = owner_directory_readiness_board(owner_directory)
            placeholder_routes = int(owner_summary.get("placeholder_routes", 0))
            tier_gaps = int(owner_summary.get("tier0_tier1_gaps", 0))
            add(
                "Owner directory source",
                "Ready" if placeholder_routes == 0 else "Review",
                "Low" if tier_gaps == 0 else "High",
                (
                    f"{int(owner_summary.get('total_routes', 0)):,} route(s); "
                    f"{placeholder_routes:,} placeholder route(s); {tier_gaps:,} Tier 0/1 gap(s)."
                ),
                "Replace built-in placeholder rows with named ALFA owner, email, on-call, approval, and escalation routes.",
            )
        except Exception as exc:
            add(
                "Owner directory source",
                "Review",
                "Medium",
                f"Could not evaluate owner directory: {_format_snowflake_error(exc)}",
                "Review owner directory data shape and deployment.",
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
        f"Default recipient {_alert_email_target()}; {ready_email:,} email-ready alert(s); {missing_email:,} missing target(s).",
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


def _alert_center_action_brief(
    *,
    open_issues: int,
    open_alerts: int,
    critical_high: int,
    overdue: int,
    email_ready: int,
    email_logged: int,
    open_queue: int,
    readiness_rows: pd.DataFrame | None = None,
) -> dict:
    rows = readiness_rows
    if rows is not None and not getattr(rows, "empty", True) and "STATE" in getattr(rows, "columns", []):
        state_text = rows["STATE"].fillna("").astype(str).str.upper()
        blockers = rows[state_text.isin({"NEEDS SETUP", "DEGRADED", "SCOPE STALE"})]
        if not blockers.empty:
            row = blockers.iloc[0]
            control = str(row.get("CONTROL") or "Alert control")
            evidence = str(row.get("EVIDENCE") or "Control evidence needs review.")
            next_action = str(row.get("NEXT_ACTION") or "").strip()
            return {
                "state": str(row.get("STATE") or "Blocked"),
                "headline": "Restore alert control evidence.",
                "detail": f"{control}: {next_action or evidence}".strip(": "),
                "primary_label": "Open Health",
                "target": "Control Health",
            }

    if overdue > 0:
        return {
            "state": "Escalate",
            "headline": "Escalate overdue alert rows first.",
            "detail": f"{overdue:,} overdue alert(s); {critical_high:,} critical/high open alert(s).",
            "primary_label": "Open Digest",
            "target": "Triage Digest",
        }
    if critical_high > 0:
        return {
            "state": "Priority",
            "headline": "Review critical and high alert rows.",
            "detail": f"{critical_high:,} critical/high open alert(s) across {open_alerts:,} open alert(s).",
            "primary_label": "Open Digest",
            "target": "Triage Digest",
        }
    if open_queue > 0:
        return {
            "state": "Queue",
            "headline": "Work open action queue rows.",
            "detail": f"{open_queue:,} open queue row(s) need owner, ticket, due-date, or closure proof.",
            "primary_label": "Open Queue",
            "target": "Action Queue Routing",
        }
    if email_ready > email_logged:
        return {
            "state": "Evidence",
            "headline": "Log alert delivery evidence.",
            "detail": f"{email_ready:,} email-ready alert(s); {email_logged:,} delivery row(s) logged in this scope.",
            "primary_label": "Open Delivery",
            "target": "Email Delivery",
        }
    if open_issues > 0:
        return {
            "state": "Triage",
            "headline": "Review the consolidated issue inbox.",
            "detail": f"{open_issues:,} issue row(s) are loaded from alert history and action queue evidence.",
            "primary_label": "Open Inbox",
            "target": "Issue Inbox",
        }
    return {
        "state": "Clear",
        "headline": "No immediate Alert Center move.",
        "detail": "Keep the selected window loaded for delivery proof, routing, and rule evidence when new alerts arrive.",
        "primary_label": "Open Inbox",
        "target": "Issue Inbox",
    }


def _alert_center_pending_brief(active_view: str, required_sources: set[str]) -> dict:
    if active_view == "Alert Brief":
        return {
            "state": "Brief Ready",
            "headline": "Choose the alert workflow before loading evidence.",
            "detail": "Start with the issue inbox, triage digest, delivery proof, queue routing, or control health based on the operator question.",
        }
    return {
        "state": "Ready",
        "headline": f"Load {active_view} before routing alert work.",
        "detail": f"Sources on load: {_alert_center_source_summary(required_sources)}.",
    }


def _alert_center_brief_workflow_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in ALERT_CENTER_BRIEF_WORKFLOWS:
        view = str(item["VIEW"])
        sources = _alert_center_source_summary(_alert_center_sources_for_view(view))
        rows.append({
            "VIEW": view,
            "BUTTON_LABEL": str(item["BUTTON_LABEL"]),
            "DBA_MOVE": str(item["DBA_MOVE"]),
            "WHEN": str(item["WHEN"]),
            "SOURCES": sources,
        })
    return rows


def _queue_alert_center_view(view: str) -> None:
    if view in ALERT_CENTER_PANES:
        st.session_state["alert_center_requested_view"] = view
        st.rerun()


def _apply_queued_alert_center_view() -> None:
    requested = st.session_state.pop("alert_center_requested_view", None)
    if requested in ALERT_CENTER_PANES:
        st.session_state["alert_center_active_view"] = requested


def _apply_alert_center_brief_first_default() -> None:
    if st.session_state.get("_alert_center_brief_first_version") == ALERT_CENTER_BRIEF_FIRST_VERSION:
        return
    if (
        "alert_center_data" not in st.session_state
        and st.session_state.get("alert_center_active_view") not in (None, "Alert Brief")
    ):
        st.session_state["alert_center_active_view"] = "Alert Brief"
    st.session_state["_alert_center_brief_first_version"] = ALERT_CENTER_BRIEF_FIRST_VERSION


def _render_alert_center_brief_launchpad() -> None:
    st.markdown("**Morning Alert Workflows**")
    rows = _alert_center_brief_workflow_rows()
    show_all = bool(st.session_state.get("alert_center_show_all_workflows"))
    visible_rows = rows if show_all else rows[:3]
    for offset in range(0, len(visible_rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, visible_rows[offset:offset + 3]):
            with col:
                st.markdown(f"**{row['VIEW']}**")
                st.caption(row["DBA_MOVE"])
                st.caption(row["WHEN"])
                if st.button(row["BUTTON_LABEL"], key=f"alert_center_brief_{row['VIEW']}", width="stretch"):
                    _queue_alert_center_view(row["VIEW"])
    if len(rows) > len(visible_rows):
        if st.button("More Alert Workflows", key="alert_center_show_all_workflows_button"):
            st.session_state["alert_center_show_all_workflows"] = True
            st.rerun()
    elif show_all and len(rows) > 3:
        if st.button("Hide Alert Workflows", key="alert_center_hide_all_workflows_button"):
            st.session_state["alert_center_show_all_workflows"] = False
            st.rerun()


def _render_alert_center_action_brief(brief: dict) -> None:
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.1, 3.2, 1.4])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(str(brief.get("state") or "Review"))
        with detail_col:
            st.markdown(f"**{brief.get('headline') or 'Review Alert Center evidence.'}**")
            st.caption(str(brief.get("detail") or ""))
        with action_col:
            primary_label = str(brief.get("primary_label") or "").strip()
            target = str(brief.get("target") or "Issue Inbox")
            if primary_label and st.button(primary_label, key="alert_center_action_brief_primary", width="stretch"):
                _queue_alert_center_view(target)
            if primary_label and target != "Issue Inbox":
                if st.button("Issue Inbox", key="alert_center_action_brief_inbox", width="stretch"):
                    _queue_alert_center_view("Issue Inbox")


def _render_alert_center_metric_rows(
    *,
    open_issues: int,
    open_alerts: int,
    critical_high: int,
    overdue: int,
    email_ready: int,
    email_logged: int,
    open_queue: int,
    loaded: bool = True,
) -> None:
    st.markdown("**Operating Snapshot**")
    if not loaded:
        render_shell_snapshot((
            ("Scope", "Company"),
            ("Window", "Selected"),
            ("Evidence", "Load view"),
            ("Route", "Issue Inbox"),
        ))
        return
    render_shell_snapshot((
        ("Issues", f"{open_issues:,}"),
        ("Alerts", f"{open_alerts:,}"),
        ("Critical", f"{critical_high:,}"),
        ("Overdue", f"{overdue:,}"),
    ))
    if loaded:
        with st.expander("Delivery and queue counts", expanded=False):
            render_shell_snapshot((
                ("Email Ready", f"{email_ready:,}"),
                ("Delivered", f"{email_logged:,}"),
                ("Open Queue", f"{open_queue:,}"),
            ))


def _alert_center_exception_rows(
    *,
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    issues: pd.DataFrame,
    delivery_log: pd.DataFrame,
    readiness_rows: pd.DataFrame | None = None,
) -> pd.DataFrame:
    pd = _pd()
    rows: list[dict] = []

    def add(
        signal: str,
        severity: str,
        count: int,
        state: str,
        next_action: str,
        owner: str = "DBA On-Call",
        route: str = "Issue Inbox",
    ) -> None:
        if count <= 0:
            return
        rows.append({
            "SIGNAL": signal,
            "SEVERITY": severity,
            "COUNT": int(count),
            "STATE": state,
            "NEXT_ACTION": next_action,
            "OWNER": owner,
            "ROUTE": route,
        })

    if alerts is not None and not alerts.empty:
        open_alerts = _open_alert_mask(alerts)
        severity = alerts.get("SEVERITY", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str)
        add(
            "Critical/high alerts",
            "High",
            int((severity.isin(["Critical", "High"]) & open_alerts).sum()),
            "Escalate",
            "Review owner, SLA state, and delivery proof for critical/high alerts.",
            route="Triage Digest",
        )
        if "SLA_STATE" in alerts.columns:
            sla_state = alerts["SLA_STATE"].fillna("").astype(str)
            add(
                "Overdue alert SLAs",
                "High",
                int((sla_state.eq("Overdue") & open_alerts).sum()),
                "Overdue",
                "Send overdue alert rows through the digest and confirm owner response.",
                route="Triage Digest",
            )
        owner = alerts.get("OWNER", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).str.upper()
        add(
            "Generic alert owners",
            "Medium",
            int((owner.isin(["", "DBA", "OVERWATCH"]) & open_alerts).sum()),
            "Route owner",
            "Replace generic owners with named owner-directory routes before escalation.",
            owner="Platform DBA",
            route="Control Health",
        )
        delivery_status = alerts.get("DELIVERY_STATUS", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).str.upper()
        ready_count = int(delivery_status.str.contains("EMAIL_READY").sum())
        logged_count = int(delivery_status.str.contains("EMAIL_LOGGED").sum())
        add(
            "Delivery proof gap",
            "Medium",
            max(0, ready_count - logged_count),
            "Log delivery",
            "Log digest/email delivery evidence for ready alerts.",
            route="Email Delivery",
        )

    if queue is not None and not queue.empty:
        if "STATUS" in queue.columns:
            open_queue = ~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])
            add(
                "Open action queue",
                "Medium",
                int(open_queue.sum()),
                "Work queue",
                "Confirm owner, due date, ticket, and closure proof on open queue rows.",
                owner="DBA Lead",
                route="Action Queue Routing",
            )

    if readiness_rows is not None and not readiness_rows.empty and "STATE" in readiness_rows.columns:
        blockers = readiness_rows["STATE"].fillna("").astype(str).str.upper().isin({"NEEDS SETUP", "DEGRADED", "SCOPE STALE"})
        add(
            "Alert control blockers",
            "High",
            int(blockers.sum()),
            "Fix control",
            "Restore alert source, owner, route, or delivery controls before relying on automation.",
            owner="Platform DBA",
            route="Control Health",
        )

    if issues is not None and not issues.empty:
        severity = issues.get("SEVERITY", pd.Series(index=issues.index, dtype=str)).fillna("").astype(str)
        add(
            "High-priority issue rows",
            "High",
            int(severity.isin(["Critical", "High"]).sum()),
            "Review first",
            "Open issue detail only when the exception strip needs row-level proof.",
            route="Issue Inbox",
        )

    if delivery_log is not None and not delivery_log.empty:
        status = delivery_log.get("DELIVERY_STATUS", pd.Series(index=delivery_log.index, dtype=str)).fillna("").astype(str).str.upper()
        failed = status.str.contains("FAILED|ERROR|BOUNCED", regex=True)
        add(
            "Delivery failures",
            "High",
            int(failed.sum()),
            "Retry delivery",
            "Review failed notification attempts and route to the email integration owner.",
            owner="DBA On-Call",
            route="Email Delivery",
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    severity_rank = {"High": 0, "Medium": 1, "Low": 2}
    result["_SORT"] = result["SEVERITY"].map(severity_rank).fillna(9)
    result = result.sort_values(["_SORT", "COUNT", "SIGNAL"], ascending=[True, False, True])
    return result.drop(columns=["_SORT"]).reset_index(drop=True)


def _render_alert_center_exception_strip(exceptions: pd.DataFrame) -> None:
    st.markdown("**Exception Strip**")
    if exceptions is None or exceptions.empty:
        st.success("No alert exceptions found for the loaded scope.")
        return
    _render_priority_dataframe(
        exceptions,
        title="Alert exceptions to work first",
        priority_columns=["SEVERITY", "SIGNAL", "COUNT", "STATE", "NEXT_ACTION", "OWNER", "ROUTE"],
        sort_by=["SEVERITY", "COUNT", "SIGNAL"],
        ascending=[True, False, True],
        max_rows=5,
        raw_label="All alert exceptions",
        height=220,
    )


def _alert_owner_route_board(alerts: pd.DataFrame, queue: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    pd = _pd()
    generic_owners = {
        "",
        "DBA",
        "OVERWATCH",
        "DBA / FINOPS",
        "DBA / PLATFORM",
        "DBA / SECURITY",
        "DBA / PIPELINE OWNER",
        "DBA / PROCEDURE OWNER",
        "DATA ENGINEERING",
        "UNKNOWN",
        "UNASSIGNED",
    }
    rows: list[dict] = []

    if alerts is not None and not alerts.empty:
        open_alerts = alerts[_open_alert_mask(alerts)].copy()
        for _, row in open_alerts.iterrows():
            owner = str(row.get("OWNER") or "").strip()
            owner_key = owner.upper()
            email_target = str(row.get("EMAIL_TARGET") or _alert_email_target() or "").strip()
            route = str(row.get("ALERT_ROUTE") or row.get("ROUTE") or "Alert Center").strip()
            rows.append({
                "ISSUE_SOURCE": "Alert",
                "SEVERITY": row.get("SEVERITY", ""),
                "STATUS": row.get("STATUS", "New"),
                "CATEGORY": row.get("CATEGORY", ""),
                "ENTITY": row.get("ENTITY_NAME", ""),
                "OWNER": owner or "DBA",
                "EMAIL_TARGET": email_target,
                "ONCALL_PRIMARY": row.get("ONCALL_PRIMARY", ""),
                "ESCALATION_TARGET": row.get("ESCALATION_TARGET", ""),
                "OWNER_SOURCE": row.get("OWNER_SOURCE", ""),
                "OWNER_ROUTE_STATE": "Needs named owner" if owner_key in generic_owners else "Named owner",
                "DELIVERY_ROUTE_STATE": "Missing email target" if not email_target else "Email target ready",
                "ACTION_ROUTE_STATE": "Route to action queue" if route == "Alert Center" else f"Route: {route}",
                "NEXT_ACTION": row.get("SUGGESTED_ACTION", "Review alert evidence and assign owner."),
            })

    if queue is not None and not queue.empty:
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_queue = queue[~status.isin(["Fixed", "Ignored"])].copy()
        for _, row in open_queue.iterrows():
            owner = str(row.get("OWNER") or row.get("OWNER_NAME") or "").strip()
            owner_key = owner.upper()
            email_target = str(row.get("OWNER_EMAIL") or row.get("EMAIL_TARGET") or "").strip()
            rows.append({
                "ISSUE_SOURCE": "Action Queue",
                "SEVERITY": row.get("SEVERITY", ""),
                "STATUS": row.get("STATUS", "New"),
                "CATEGORY": row.get("CATEGORY", ""),
                "ENTITY": row.get("ENTITY_NAME", row.get("ENTITY", "")),
                "OWNER": owner or "DBA",
                "EMAIL_TARGET": email_target,
                "ONCALL_PRIMARY": row.get("ONCALL_PRIMARY", ""),
                "ESCALATION_TARGET": row.get("ESCALATION_TARGET", ""),
                "OWNER_SOURCE": row.get("OWNER_SOURCE", ""),
                "OWNER_ROUTE_STATE": "Needs named owner" if owner_key in generic_owners else "Named owner",
                "DELIVERY_ROUTE_STATE": "Missing owner email" if not email_target else "Owner email ready",
                "ACTION_ROUTE_STATE": "Queued",
                "NEXT_ACTION": row.get("RECOMMENDED_ACTION", row.get("NEXT_ACTION", "Work queued DBA action.")),
            })

    board = pd.DataFrame(rows)
    if board.empty:
        return {
            "open_items": 0,
            "named_owner_pct": 100.0,
            "email_route_pct": 100.0,
            "oncall_pct": 100.0,
            "route_gaps": 0,
        }, board

    owner_ready = board["OWNER_ROUTE_STATE"].astype(str).eq("Named owner")
    email_ready = ~board["DELIVERY_ROUTE_STATE"].astype(str).str.startswith("Missing")
    oncall_ready = board["ONCALL_PRIMARY"].fillna("").astype(str).str.strip().ne("")
    route_gap = (
        board["OWNER_ROUTE_STATE"].astype(str).ne("Named owner")
        | ~email_ready
        | ~oncall_ready
    )
    board["ROUTE_READY"] = route_gap.map({True: "Review", False: "Ready"})
    board["_ROUTE_RANK"] = route_gap.map({True: 0, False: 1})
    board = board.sort_values(["_ROUTE_RANK", "SEVERITY", "ISSUE_SOURCE", "ENTITY"]).drop(
        columns=["_ROUTE_RANK"], errors="ignore"
    )
    total = max(len(board), 1)
    return {
        "open_items": int(len(board)),
        "named_owner_pct": round(float(owner_ready.sum()) / total * 100, 1),
        "email_route_pct": round(float(email_ready.sum()) / total * 100, 1),
        "oncall_pct": round(float(oncall_ready.sum()) / total * 100, 1),
        "route_gaps": int(route_gap.sum()),
    }, board.reset_index(drop=True)


def _alert_lifecycle_board(alerts: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    pd = _pd()
    if alerts is None or alerts.empty:
        return pd.DataFrame()

    queue_entities = set()
    queue_alert_ids = set()
    if queue is not None and not queue.empty:
        for col in ["ALERT_ID", "SOURCE_ID", "SOURCE_ALERT_ID"]:
            if col in queue.columns:
                queue_alert_ids |= set(queue[col].dropna().astype(str))
        for col in ["ENTITY_NAME", "ENTITY"]:
            if col in queue.columns:
                queue_entities |= set(queue[col].dropna().astype(str))

    rows: list[dict] = []
    for _, row in alerts.iterrows():
        alert_id = str(row.get("ALERT_ID") or "").strip()
        entity = str(row.get("ENTITY_NAME") or "").strip()
        status_key = _status_key(row.get("STATUS"))
        owner = str(row.get("OWNER") or "DBA").strip()
        owner_ready = owner.upper() not in {"", "DBA", "OVERWATCH"}
        sla_state = str(row.get("SLA_STATE") or "Unknown").strip()
        severity = str(row.get("SEVERITY") or "").strip()
        delivery_status = str(row.get("DELIVERY_STATUS") or "").upper()
        delivery_logged = "LOGGED" in delivery_status
        email_ready = "EMAIL_READY" in delivery_status or bool(str(row.get("EMAIL_TARGET") or "").strip())
        queued = bool((alert_id and alert_id in queue_alert_ids) or (entity and entity in queue_entities))

        if status_key in {"FIXED", "RESOLVED", "CLOSED"}:
            lifecycle_state = "Closed - verify evidence"
        elif sla_state == "Overdue" and severity in {"Critical", "High"}:
            lifecycle_state = "Escalate now"
        elif not owner_ready:
            lifecycle_state = "Assign owner"
        elif not queued:
            lifecycle_state = "Route to action queue"
        elif not delivery_logged and email_ready:
            lifecycle_state = "Log delivery evidence"
        else:
            lifecycle_state = "Work and verify"

        rows.append({
            "ALERT_ID": alert_id,
            "LIFECYCLE_STATE": lifecycle_state,
            "SLA_STATE": sla_state,
            "SEVERITY": severity,
            "STATUS": row.get("STATUS", "New"),
            "CATEGORY": row.get("CATEGORY", ""),
            "ALERT_TYPE": row.get("ALERT_TYPE", ""),
            "ENTITY_NAME": entity,
            "OWNER": owner,
            "ESCALATION_TARGET": row.get("ESCALATION_TARGET", ""),
            "DELIVERY_STATUS": row.get("DELIVERY_STATUS", ""),
            "ACTION_QUEUE_STATE": "Queued" if queued else "Not queued",
            "CLOSURE_PROOF_REQUIRED": (
                "ticket, owner approval, remediation note, and post-fix verification evidence"
                if status_key not in {"FIXED", "RESOLVED", "CLOSED"}
                else "retain closure evidence and delivery/action audit"
            ),
            "NEXT_ACTION": row.get("SUGGESTED_ACTION", "Review alert evidence and update lifecycle."),
            "ALERT_TS": row.get("ALERT_TS", ""),
        })

    board = pd.DataFrame(rows)
    if board.empty:
        return board
    state_rank = {
        "Escalate now": 0,
        "Assign owner": 1,
        "Route to action queue": 2,
        "Log delivery evidence": 3,
        "Work and verify": 4,
        "Closed - verify evidence": 5,
    }
    severity_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    board["_STATE_RANK"] = board["LIFECYCLE_STATE"].map(state_rank).fillna(9)
    board["_SEV_RANK"] = board["SEVERITY"].map(severity_rank).fillna(9)
    return board.sort_values(["_STATE_RANK", "_SEV_RANK", "ALERT_TS"], ascending=[True, True, False]).drop(
        columns=["_STATE_RANK", "_SEV_RANK"], errors="ignore"
    ).reset_index(drop=True)


def _alert_integration_readiness_board(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    owner_summary: dict,
) -> pd.DataFrame:
    pd = _pd()
    alerts = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    queue = queue if isinstance(queue, pd.DataFrame) else pd.DataFrame()
    delivery_log = delivery_log if isinstance(delivery_log, pd.DataFrame) else pd.DataFrame()
    rows: list[dict] = []
    open_alert_count = int(_open_alert_mask(alerts).sum()) if not alerts.empty else 0
    email_ready = 0
    if not alerts.empty and "DELIVERY_STATUS" in alerts.columns:
        email_ready = int(alerts["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("EMAIL_READY").sum())
    delivery_rows = len(delivery_log)

    rows.append({
        "CONTROL": "Email delivery evidence",
        "STATE": "Ready" if delivery_rows > 0 else "Manual",
        "EVIDENCE": f"{email_ready:,} email-ready alert(s); {delivery_rows:,} delivery audit row(s).",
        "NEXT_ACTION": "Log each digest delivery until an approved Snowflake notification integration is enabled.",
        "OWNER": "DBA / Alert Owner",
    })
    rows.append({
        "CONTROL": "Snowflake notification integration",
        "STATE": "Manual",
        "EVIDENCE": "Teams webhook is not available; email-first delivery uses a placeholder recipient until approved integration exists.",
        "NEXT_ACTION": "Create approved email/notification integration and replace placeholder routing with production distribution lists.",
        "OWNER": "DBA / Platform",
    })

    ticket_col = "TICKET_ID" if "TICKET_ID" in queue.columns else ""
    tickets = 0
    open_queue = 0
    if not queue.empty:
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_queue = int((~status.isin(["Fixed", "Ignored"])).sum())
        if ticket_col:
            tickets = int(queue[ticket_col].fillna("").astype(str).str.strip().ne("").sum())
    rows.append({
        "CONTROL": "ITSM lifecycle sync",
        "STATE": "Manual" if tickets == 0 else "Partial",
        "EVIDENCE": f"{open_queue:,} open queue row(s); {tickets:,} ticket id(s) attached.",
        "NEXT_ACTION": "Sync alert/action status to ITSM so acknowledgment, owner approval, and closure evidence are not manually reconciled.",
        "OWNER": "DBA / ITSM Owner",
    })

    placeholder_routes = int(owner_summary.get("placeholder_routes", 0) or 0)
    tier_gaps = int(owner_summary.get("tier0_tier1_gaps", 0) or 0)
    rows.append({
        "CONTROL": "Named owner routes",
        "STATE": "Ready" if placeholder_routes == 0 else "Priority Gap" if tier_gaps else "Review",
        "EVIDENCE": (
            f"{int(owner_summary.get('production_ready', 0) or 0):,}/"
            f"{int(owner_summary.get('total_routes', 0) or 0):,} route(s) production-ready; "
            f"{tier_gaps:,} Tier 0/1 gap(s)."
        ),
        "NEXT_ACTION": "Replace built-in owner-directory defaults with named ALFA owner, email, on-call, approval, and escalation rows.",
        "OWNER": "DBA Lead",
    })
    rows.append({
        "CONTROL": "Open alert lifecycle",
        "STATE": "Ready" if open_alert_count == 0 else "Review",
        "EVIDENCE": f"{open_alert_count:,} open alert(s) in the loaded scope.",
        "NEXT_ACTION": "Every open alert needs owner, ticket/notes, delivery evidence, action queue state, and closure proof.",
        "OWNER": "DBA / Alert Owner",
    })

    board = pd.DataFrame(rows)
    if board.empty:
        return board
    board["_STATE_RANK"] = board["STATE"].map({
        "Priority Gap": 0,
        "Manual": 1,
        "Review": 2,
        "Partial": 3,
        "Ready": 4,
    }).fillna(9)
    return board.sort_values(["_STATE_RANK", "CONTROL"]).drop(columns=["_STATE_RANK"], errors="ignore")


def _render_no_touch_automation_health(automation_health: pd.DataFrame) -> None:
    pd = _pd()
    st.markdown("**No-Touch Automation Health**")
    if automation_health is None or automation_health.empty:
        st.info("No automation health row loaded yet. Deploy the automation task and run the Alert Center refresh.")
        return

    row = automation_health.iloc[0]

    def text_value(column: str, default: str = "") -> str:
        value = row.get(column, default)
        if pd.isna(value):
            return default
        return str(value or default).strip()

    def int_value(column: str) -> int:
        try:
            value = row.get(column, 0)
            if pd.isna(value):
                return 0
            return int(float(value))
        except Exception:
            return 0

    primary_state = text_value("PRIMARY_EVIDENCE_STATE", "Not Run")
    digest_state = text_value("ALERT_DIGEST_STATE", "Not Run")
    savings_state = text_value("VERIFIED_SAVINGS_STATE", "Verifier scheduled")
    run_scope = " / ".join(
        part for part in [text_value("COMPANY", "ALL"), text_value("ENVIRONMENT", "ALL")] if part
    ) or "ALL / ALL"
    run_ts = text_value("RUN_TS", "Not Run")[:19]
    feed_total = int_value("EXTERNAL_FEED_ROWS")
    open_actions = int_value("OPEN_ACTIONS")
    verified_actions = int_value("VERIFIED_ACTIONS")

    render_shell_snapshot((
        ("Last Run", run_ts),
        ("External Rows", f"{feed_total:,}"),
        ("Open Actions", f"{open_actions:,}"),
        ("Verified", f"{verified_actions:,}"),
    ))

    rows = [
        {
            "STATE": "Ready" if primary_state.upper() in {"READY", "PRIMARY_EVIDENCE_READY"} else "Review",
            "CONTROL": "Primary evidence refresh",
            "EVIDENCE": f"{primary_state} for {run_scope}.",
            "NEXT_ACTION": text_value("NEXT_ACTION", "Review the latest automation run."),
            "OWNER": "DBA On-Call",
        },
        {
            "STATE": "Ready" if int_value("ACTION_QUEUE_SEEDED") > 0 else "Review",
            "CONTROL": "Action queue seeding",
            "EVIDENCE": f"{int_value('ACTION_QUEUE_SEEDED'):,} row(s) seeded in the latest run.",
            "NEXT_ACTION": "Review open action queue rows and close only after owner/proof evidence is present.",
            "OWNER": "DBA Lead",
        },
        {
            "STATE": "Ready" if int_value("OWNER_ROUTES_UPDATED") > 0 else "Review",
            "CONTROL": "Owner route update",
            "EVIDENCE": f"{int_value('OWNER_ROUTES_UPDATED'):,} owner route row(s) updated.",
            "NEXT_ACTION": "Keep owner directory mapped to named teams, email routes, and approval groups.",
            "OWNER": "Platform DBA",
        },
        {
            "STATE": "Ready" if "VERIFIED" in savings_state.upper() or "SCHEDULED" in savings_state.upper() else "Review",
            "CONTROL": "Savings verification",
            "EVIDENCE": savings_state,
            "NEXT_ACTION": "Let the verifier close savings outcomes from metering proof instead of manual notes.",
            "OWNER": "Cost Owner",
        },
        {
            "STATE": "Ready" if "READY" in digest_state.upper() or "PREPARED" in digest_state.upper() or "SENT" in digest_state.upper() else "Review",
            "CONTROL": "Alert digest",
            "EVIDENCE": f"{digest_state}; last delivery {text_value('LAST_DIGEST_TS', 'not logged')[:19]}.",
            "NEXT_ACTION": "Enable Snowflake email delivery only after the approved notification integration is available.",
            "OWNER": "DBA On-Call",
        },
    ]

    for feed, column, owner in [
        ("Control-M", "CONTROL_M_ROWS", "Job Scheduler Owner"),
        ("Jira", "JIRA_ROWS", "ITSM Owner"),
        ("Terraform", "TERRAFORM_ROWS", "DevOps Owner"),
        ("Flyway", "FLYWAY_ROWS", "DevOps Owner"),
        ("Git", "GIT_ROWS", "DevOps Owner"),
    ]:
        count = int_value(column)
        rows.append({
            "STATE": "Ready" if count > 0 else "Needs Setup",
            "CONTROL": f"{feed} evidence feed",
            "EVIDENCE": f"{count:,} row(s) ingested.",
            "NEXT_ACTION": (
                f"Feed {feed} evidence into OVERWATCH_EXTERNAL_CONTROL_FEED."
                if count == 0 else f"Keep {feed} evidence synchronized for drift and closure checks."
            ),
            "OWNER": owner,
        })

    board = pd.DataFrame(rows)
    board["_STATE_RANK"] = board["STATE"].map({"Needs Setup": 0, "Review": 1, "Ready": 2}).fillna(9)
    board = board.sort_values(["_STATE_RANK", "CONTROL"]).drop(columns=["_STATE_RANK"], errors="ignore")
    _render_priority_dataframe(
        board,
        title="No-touch automation run controls",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
        raw_label="All no-touch automation controls",
        height=320,
    )


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    _apply_alert_center_brief_first_default()
    _apply_queued_alert_center_view()

    active_view = _render_workflow_selector(
        "Alert Center view",
        "alert_center_active_view",
        ALERT_CENTER_PANES,
        labels=ALERT_CENTER_PANE_LABELS,
        columns=4,
    )
    required_sources = _alert_center_sources_for_view(active_view)

    if active_view == "Alert Brief":
        _render_alert_center_action_brief(_alert_center_pending_brief(active_view, required_sources))
        _render_alert_center_metric_rows(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
            loaded=False,
        )
        _render_alert_center_brief_launchpad()
        st.caption("Each workflow loads only the sources listed on its load button; no Alert Center data is fetched by the brief itself.")
        return

    if active_view == "Suppression Windows":
        _render_annotations()
        return

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        days = st.selectbox(
            "Alert window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(DEFAULT_DAY_WINDOW),
            format_func=lambda value: f"{value} days",
        )
    with c2:
        limit = st.selectbox("Rows", [50, 100, 200, 500], index=2)
    with c3:
        load_label = "Load Full Control Health" if active_view == "Control Health" else f"Load {active_view}"
        if st.button(load_label, key="alert_center_load", type="primary"):
            session = _alert_center_action_session(f"load {active_view}")
            if session is not None:
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
        _render_alert_center_action_brief(_alert_center_pending_brief(active_view, required_sources))
        _render_alert_center_metric_rows(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
            loaded=False,
        )
        st.info(f"Load {active_view} when ready.")
        defer_source_note(f"Sources on load: {_alert_center_source_summary(required_sources)}")
        return

    loaded_scope = st.session_state.get("alert_center_scope")
    expected_scope = (company, environment, int(days), int(limit))
    if loaded_scope != expected_scope:
        _render_alert_center_action_brief(_alert_center_pending_brief(active_view, required_sources))
        _render_alert_center_metric_rows(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
            loaded=False,
        )
        st.warning("Company, environment, or window changed after this load. Reload before triaging alerts.")
        defer_source_note(f"Loaded scope: {loaded_scope or 'none'} | Current scope: {expected_scope}")
        return
    loaded_sources = set(data.get("_loaded_sources") or [])
    missing_sources = sorted(required_sources - loaded_sources)
    if missing_sources:
        _render_alert_center_action_brief(_alert_center_pending_brief(active_view, required_sources))
        _render_alert_center_metric_rows(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
            loaded=False,
        )
        st.info(f"Load {active_view} to fetch missing source(s).")
        defer_source_note(f"Missing Alert Center source(s): {_alert_center_source_summary(set(missing_sources))}")
        return

    pd = _pd()
    alerts = data.get("alerts") if isinstance(data.get("alerts"), pd.DataFrame) else pd.DataFrame()
    queue = data.get("action_queue") if isinstance(data.get("action_queue"), pd.DataFrame) else pd.DataFrame()
    issues = data.get("issues") if isinstance(data.get("issues"), pd.DataFrame) else pd.DataFrame()
    delivery_log = data.get("delivery_log") if isinstance(data.get("delivery_log"), pd.DataFrame) else pd.DataFrame()
    rules = data.get("rules") if isinstance(data.get("rules"), pd.DataFrame) else pd.DataFrame()
    rule_audit = data.get("rule_audit") if isinstance(data.get("rule_audit"), pd.DataFrame) else pd.DataFrame()
    owner_directory = data.get("owner_directory") if isinstance(data.get("owner_directory"), pd.DataFrame) else pd.DataFrame()
    automation_health = data.get("automation_health") if isinstance(data.get("automation_health"), pd.DataFrame) else pd.DataFrame()
    if data.get("alerts_error"):
        st.info("Alert history unavailable.")
        defer_source_note(
            "Deploy alert objects from snowflake/OVERWATCH_MART_SETUP.sql first.",
            data["alerts_error"],
        )
    if data.get("queue_error"):
        defer_source_note("Action queue unavailable for this role/context.", data["queue_error"])
    if data.get("delivery_error"):
        defer_source_note("Delivery audit unavailable until snowflake/OVERWATCH_MART_SETUP.sql is deployed.", data["delivery_error"])
    if data.get("rule_error"):
        defer_source_note("Alert rule catalog unavailable until snowflake/OVERWATCH_MART_SETUP.sql is deployed.", data["rule_error"])
    if data.get("rule_audit_error"):
        defer_source_note("Alert rule audit unavailable until snowflake/OVERWATCH_MART_SETUP.sql is deployed.", data["rule_audit_error"])
    if data.get("owner_directory_error"):
        defer_source_note("Owner directory unavailable until snowflake/OVERWATCH_MART_SETUP.sql is deployed.", data["owner_directory_error"])
    if data.get("automation_health_error"):
        defer_source_note("No-touch automation health unavailable until snowflake/OVERWATCH_MART_SETUP.sql is deployed.", data["automation_health_error"])
    defer_source_note(f"Loaded {data.get('loaded_at', '')}. Email target defaults to {_alert_email_target()}.")

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

    open_issue_count = len(issues)
    open_alert_count = int(open_alerts.sum()) if len(open_alerts) else 0
    critical_high_count = int(high_alerts.sum()) if len(high_alerts) else 0
    overdue_count = int(overdue_alerts.sum()) if len(overdue_alerts) else 0
    email_ready_count = int(email_ready.sum()) if len(email_ready) else 0
    email_logged_count = int(email_logged.sum()) if len(email_logged) else 0
    open_queue_count = int(open_queue.sum()) if len(open_queue) else 0

    readiness_rows = pd.DataFrame()
    if active_view == "Control Health":
        readiness_rows = _alert_center_operability_rows(
            data,
            company=company,
            environment=environment,
            days=int(days),
            limit=int(limit),
            loaded_scope=loaded_scope,
        )
    exception_rows = _alert_center_exception_rows(
        alerts=alerts,
        queue=queue,
        issues=issues,
        delivery_log=delivery_log,
        readiness_rows=readiness_rows,
    )

    _render_alert_center_action_brief(
        _alert_center_action_brief(
            open_issues=open_issue_count,
            open_alerts=open_alert_count,
            critical_high=critical_high_count,
            overdue=overdue_count,
            email_ready=email_ready_count,
            email_logged=email_logged_count,
            open_queue=open_queue_count,
            readiness_rows=readiness_rows,
        )
    )
    _render_alert_center_metric_rows(
        open_issues=open_issue_count,
        open_alerts=open_alert_count,
        critical_high=critical_high_count,
        overdue=overdue_count,
        email_ready=email_ready_count,
        email_logged=email_logged_count,
        open_queue=open_queue_count,
    )
    _render_alert_center_exception_strip(exception_rows)

    if active_view == "Control Health":
        st.subheader("Alert Control Health")
        defer_source_note("Uses only the data loaded by the explicit Alert Center refresh; no hidden tab scans are required.")
        blocked = int(readiness_rows["STATE"].isin(["Needs Setup", "Degraded", "Scope Stale"]).sum()) if not readiness_rows.empty else 0
        review = int(readiness_rows["STATE"].eq("Review").sum()) if not readiness_rows.empty else 0
        ready = int(readiness_rows["STATE"].isin(["Ready", "No Rows"]).sum()) if not readiness_rows.empty else 0
        render_shell_snapshot((
            ("Ready Controls", f"{ready:,}"),
            ("Needs Review", f"{review:,}"),
            ("Blocked / Setup", f"{blocked:,}"),
            ("Controls", f"{len(readiness_rows):,}"),
        ))
        health_detail = st.selectbox(
            "Alert health detail",
            ALERT_CENTER_HEALTH_DETAIL_OPTIONS,
            key="alert_center_health_detail",
        )

        if health_detail == "Controls":
            _render_priority_dataframe(
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
        elif health_detail == "Owner Routes":
            owner_summary, owner_board = _alert_owner_route_board(alerts, queue)
            render_shell_snapshot((
                ("Open routed items", f"{owner_summary['open_items']:,}"),
                ("Named owners", f"{owner_summary['named_owner_pct']:.0f}%"),
                ("Email routes", f"{owner_summary['email_route_pct']:.0f}%"),
                ("Route gaps", f"{owner_summary['route_gaps']:,}"),
            ))
            if owner_board.empty:
                st.success("No owner route gaps found for the loaded scope.")
            else:
                _render_priority_dataframe(
                    owner_board,
                    title="Owner/on-call route gaps",
                    priority_columns=[
                        "ROUTE_READY", "ISSUE_SOURCE", "SEVERITY", "STATUS", "CATEGORY",
                        "ENTITY", "OWNER", "OWNER_ROUTE_STATE", "EMAIL_TARGET",
                        "DELIVERY_ROUTE_STATE", "ONCALL_PRIMARY", "ESCALATION_TARGET",
                        "OWNER_SOURCE", "NEXT_ACTION",
                    ],
                    sort_by=["ROUTE_READY", "SEVERITY", "ENTITY"],
                    ascending=[True, True, True],
                    raw_label="All owner route rows",
                    height=280,
                )
        elif health_detail == "Owner Directory":
            from utils import owner_directory_readiness_board

            directory_summary, directory_board = owner_directory_readiness_board(owner_directory)
            st.markdown("**Owner Directory Production Readiness**")
            render_shell_snapshot((
                ("Route readiness", f"{directory_summary['readiness_pct']:.0f}%"),
                (
                    "Production routes",
                    f"{directory_summary['production_ready']:,}/{directory_summary['total_routes']:,}",
                ),
                ("Placeholder routes", f"{directory_summary['placeholder_routes']:,}"),
                ("Tier 0/1 gaps", f"{directory_summary['tier0_tier1_gaps']:,}"),
            ))
            if directory_board.empty:
                st.success("No owner-directory route rows found for the loaded scope.")
            else:
                _render_priority_dataframe(
                    directory_board,
                    title="Owner directory route readiness",
                    priority_columns=[
                        "ROUTE_STATE", "SERVICE_TIER", "OWNER_KEY", "ENTITY_TYPE",
                        "ENTITY_PATTERN", "OWNER_NAME", "OWNER_EMAIL", "ONCALL_PRIMARY",
                        "APPROVAL_GROUP", "ESCALATION_TARGET", "BLOCKERS", "NEXT_ACTION",
                    ],
                    raw_label="All owner directory rows",
                    height=300,
                )
        elif health_detail == "Delivery & ITSM":
            from utils import owner_directory_readiness_board

            directory_summary, _ = owner_directory_readiness_board(owner_directory)
            integration_board = _alert_integration_readiness_board(
                alerts,
                queue,
                delivery_log,
                directory_summary,
            )
            st.markdown("**Notification & ITSM Readiness**")
            if integration_board.empty:
                st.success("No delivery or ITSM integration blockers found for the loaded scope.")
            else:
                _render_priority_dataframe(
                    integration_board,
                    title="Alert integration readiness",
                    priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
                    raw_label="All alert integration controls",
                    height=220,
                )

    elif active_view == "Automation Readiness":
        st.subheader("Alert Automation Readiness")
        from utils import owner_directory_readiness_board
        from utils.alerts import build_alert_digest_summary

        _render_no_touch_automation_health(automation_health)

        digest_summary = build_alert_digest_summary(alerts)
        owner_summary, owner_board = _alert_owner_route_board(alerts, queue)
        directory_summary, _ = owner_directory_readiness_board(owner_directory)
        integration_board = _alert_integration_readiness_board(
            alerts,
            queue,
            delivery_log,
            directory_summary,
        )
        automation_rows = [
            {
                "CONTROL": "Digest generation",
                "STATE": "Ready" if digest_summary["open"] else "No Open Alerts",
                "EVIDENCE": f"{digest_summary['open']:,} open alert(s), {digest_summary['critical_high']:,} critical/high.",
                "NEXT_ACTION": "Generate the digest and log delivery when open alerts exist.",
                "OWNER": "DBA On-Call",
            },
            {
                "CONTROL": "Delivery proof",
                "STATE": "Ready" if not delivery_log.empty else "Manual",
                "EVIDENCE": f"{len(delivery_log):,} delivery audit row(s) loaded.",
                "NEXT_ACTION": "Log each digest delivery until a governed Snowflake notification integration is enabled.",
                "OWNER": "DBA On-Call",
            },
            {
                "CONTROL": "Owner route automation",
                "STATE": "Ready" if owner_summary.get("route_gaps", 0) == 0 and owner_summary.get("open_items", 0) else "Review",
                "EVIDENCE": f"{owner_summary.get('route_gaps', 0):,} route gap(s); {owner_summary.get('named_owner_pct', 0):.0f}% named owners.",
                "NEXT_ACTION": "Close placeholder owner/email routes before enabling unattended escalation.",
                "OWNER": "Platform DBA",
            },
            {
                "CONTROL": "Action queue handoff",
                "STATE": "Ready" if int(open_queue.sum()) else "No Open Queue",
                "EVIDENCE": f"{int(open_queue.sum()) if len(open_queue) else 0:,} open queue row(s).",
                "NEXT_ACTION": "Route alerts into owned queue rows with SLA, approval, and verification fields.",
                "OWNER": "DBA Lead",
            },
        ]
        automation_board = pd.concat(
            [pd.DataFrame(automation_rows), integration_board],
            ignore_index=True,
            sort=False,
        )
        blocked = int(automation_board["STATE"].astype(str).isin(["Blocked", "Needs Setup"]).sum()) if not automation_board.empty else 0
        review = int(automation_board["STATE"].astype(str).isin(["Manual", "Review"]).sum()) if not automation_board.empty else 0
        ready = int(automation_board["STATE"].astype(str).isin(["Ready", "No Open Alerts", "No Open Queue"]).sum()) if not automation_board.empty else 0
        render_shell_snapshot((
            ("Ready Controls", f"{ready:,}"),
            ("Manual / Review", f"{review:,}"),
            ("Blocked", f"{blocked:,}"),
            ("Controls", f"{len(automation_board):,}"),
        ))
        _render_priority_dataframe(
            automation_board,
            title="Alert automation controls",
            priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
            sort_by=["STATE", "CONTROL"],
            ascending=[True, True],
            raw_label="All alert automation controls",
            height=320,
        )
        if not owner_board.empty:
            _render_priority_dataframe(
                owner_board,
                title="Automation route blockers",
                priority_columns=[
                    "ROUTE_READY", "ISSUE_SOURCE", "SEVERITY", "ENTITY",
                    "OWNER", "EMAIL_TARGET", "ONCALL_PRIMARY", "ESCALATION_TARGET",
                    "NEXT_ACTION",
                ],
                sort_by=["ROUTE_READY", "SEVERITY", "ENTITY"],
                ascending=[True, True, True],
                raw_label="All route blocker rows",
                height=260,
            )
        defer_source_note(
            "Automation Readiness is deliberately email-first until Snowflake notification integration and ITSM/Jira sync are approved."
        )

    elif active_view == "Issue Inbox":
        st.subheader("All Active DBA Issues")
        visible = _filtered_issues(issues)
        if visible.empty:
            st.success("No active alert or action queue issues found for this scope.")
        else:
            st.caption(
                f"{len(visible):,} issue row(s) match the filters. "
                "Use the exception strip first; render row-level proof only when needed."
            )
            detail_visible = bool(st.session_state.get("alert_center_issue_detail_visible"))
            detail_label = "Hide Issue Detail" if detail_visible else "Show Issue Detail"
            if st.button(detail_label, key="alert_center_toggle_issue_detail", width="stretch"):
                detail_visible = not detail_visible
                st.session_state["alert_center_issue_detail_visible"] = detail_visible
            if st.session_state.get("alert_center_issue_detail_visible"):
                _render_priority_dataframe(
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
                _download_csv(visible, "overwatch_alert_center_issues.csv")

    elif active_view == "Triage Digest":
        st.subheader("DBA Triage Digest")
        if alerts.empty:
            st.info("Load alert history before building the operator digest.")
        else:
            from utils.alerts import (
                alert_escalation_candidates,
                build_alert_digest_body,
                build_alert_digest_subject,
                build_alert_digest_summary,
                log_alert_digest_delivery,
            )

            digest_summary = build_alert_digest_summary(alerts)
            render_shell_snapshot((
                ("Open", f"{digest_summary['open']:,}"),
                ("Critical / High", f"{digest_summary['critical_high']:,}"),
                ("Overdue", f"{digest_summary['overdue']:,}"),
                ("Due Soon", f"{digest_summary['due_soon']:,}"),
                ("Needs Owner", f"{digest_summary['needs_owner']:,}"),
            ))

            digest_subject = build_alert_digest_subject(alerts, company=company, environment=environment)
            digest_body = build_alert_digest_body(
                alerts,
                company=company,
                environment=environment,
                recipient=_alert_email_target(),
                limit=10,
            )
            st.text_input("Digest email subject", value=digest_subject, key="alert_center_digest_subject")
            st.text_area("Digest email body", value=digest_body, height=340, key="alert_center_digest_body")
            with st.expander("Log digest delivery", expanded=False):
                st.caption("Use this after the email digest is sent or handed off. This records delivery evidence and marks included alerts as escalated.")
                with st.form("alert_center_log_digest_delivery"):
                    delivery_target = st.text_input(
                        "Delivery target",
                        value=_alert_email_target(),
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
                            session = _alert_center_action_session("log alert digest delivery")
                            if session is None:
                                return
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
                            st.error(f"Could not log digest delivery: {_format_snowflake_error(exc)}")

            candidates = alert_escalation_candidates(alerts, limit=15)
            if candidates.empty:
                st.success("No escalation candidates for this scope.")
            else:
                _render_priority_dataframe(
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
                    _render_priority_dataframe(
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
            lifecycle = _alert_lifecycle_board(alerts, queue)
            if not lifecycle.empty:
                render_shell_snapshot((
                    ("Lifecycle Rows", f"{len(lifecycle):,}"),
                    ("Escalate Now", f"{int(lifecycle['LIFECYCLE_STATE'].eq('Escalate now').sum()):,}"),
                    ("Needs Owner", f"{int(lifecycle['LIFECYCLE_STATE'].eq('Assign owner').sum()):,}"),
                    ("Not Queued", f"{int(lifecycle['ACTION_QUEUE_STATE'].eq('Not queued').sum()):,}"),
                ))
                _render_priority_dataframe(
                    lifecycle,
                    title="Alert lifecycle command board",
                    priority_columns=[
                        "LIFECYCLE_STATE", "SLA_STATE", "SEVERITY", "STATUS",
                        "CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER",
                        "ESCALATION_TARGET", "DELIVERY_STATUS", "ACTION_QUEUE_STATE",
                        "CLOSURE_PROOF_REQUIRED", "NEXT_ACTION",
                    ],
                    sort_by=["LIFECYCLE_STATE", "SEVERITY", "ALERT_TS"],
                    ascending=[True, True, False],
                    raw_label="All alert lifecycle rows",
                    height=300,
                )
            _render_priority_dataframe(
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
            _download_csv(alerts, "overwatch_alert_history.csv")

            alert_ids = alerts["ALERT_ID"].dropna().astype(str).tolist() if "ALERT_ID" in alerts.columns else []
            if alert_ids:
                from utils.alerts import (
                    ALERT_STATUS_CHOICES,
                    acknowledge_alert_escalation,
                    update_alert_status,
                )

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
                                session = _alert_center_action_session("update alert status")
                                if session is None:
                                    return
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
                                st.error(f"Could not update alert status: {_format_snowflake_error(exc)}")
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
                                session = _alert_center_action_session("acknowledge alert escalation")
                                if session is None:
                                    return
                                acknowledge_alert_escalation(
                                    session,
                                    ack_alert,
                                    actor=_alert_actor(),
                                    note=ack_note,
                                )
                                st.success(f"Escalation acknowledged for alert {ack_alert}. Reload the Alert Center to refresh.")
                                st.session_state.pop("alert_center_data", None)
                            except Exception as exc:
                                st.error(f"Could not acknowledge escalation: {_format_snowflake_error(exc)}")

    elif active_view == "Email Delivery":
        st.subheader("Email Delivery Queue")
        defer_source_note(
            "Rows are email-ready by default; snowflake/OVERWATCH_MART_SETUP.sql includes a dry-run governed SYSTEM$SEND_EMAIL procedure for an approved Snowflake email integration."
        )
        if alerts.empty:
            st.info("No email-ready alert rows found.")
        else:
            email_view = alerts.copy()
            email_view["EMAIL_TARGET"] = email_view["EMAIL_TARGET"].replace("", _alert_email_target()).fillna(_alert_email_target())
            _render_priority_dataframe(
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
            _render_priority_dataframe(
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
            from utils.alerts import alert_history_to_actions, mark_alerts_routed
            from utils.action_queue import upsert_actions

            routable = alerts[_open_alert_mask(alerts)] if not alerts.empty else alerts
            defer_source_note(f"{len(routable):,} open alert row(s) are eligible for action queue routing.")
            actions_preview = pd.DataFrame(alert_history_to_actions(routable, company=company))
            if not actions_preview.empty:
                recovery_count = int((actions_preview.get("Category", pd.Series(dtype=str)) == "Task & Procedure Reliability").sum())
                if recovery_count:
                    defer_source_note(f"{recovery_count:,} task/procedure recovery action(s) include owner approval and recovery SLA evidence fields.")
                _render_priority_dataframe(
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
                    session = _alert_center_action_session("route alerts to the action queue")
                    if session is None:
                        return
                    saved = upsert_actions(session, actions_preview.to_dict("records"))
                    alert_ids = routable.get("ALERT_ID", pd.Series(dtype=str)).dropna().astype(str).tolist()
                    mark_alerts_routed(session, alert_ids, action_count=saved, actor=_alert_actor())
                    st.success(f"Saved {saved} alert action(s) to the action queue.")
                    st.session_state.pop("alert_center_data", None)
                except Exception as exc:
                    st.error(f"Could not save alerts to action queue: {_format_snowflake_error(exc)}")
        if not queue.empty:
            _render_priority_dataframe(
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
        _render_priority_dataframe(
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
            _render_priority_dataframe(
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
            defer_source_note(
                f"{configured_count:,} rule(s) loaded from Snowflake configuration; "
                f"{len(rules) - configured_count:,} built-in fallback rule(s) shown for deployment readiness."
            )
            editable_rules = rules[rules.get("RULE_SOURCE", pd.Series(index=rules.index, dtype=str)).astype(str).eq("Database")]
            if editable_rules.empty:
                st.info("Deploy `OVERWATCH_ALERT_RULES` from `snowflake/OVERWATCH_MART_SETUP.sql` before editing alert rule ownership, SLA, and routing.")
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
                            from utils.alerts import update_alert_rule

                            session = _alert_center_action_session("update an alert rule")
                            if session is None:
                                return
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
                            st.error(f"Could not update alert rule: {_format_snowflake_error(exc)}")
        if not alerts.empty and "SLA_STATE" in alerts.columns:
            sla_summary = (
                alerts.groupby(["SLA_STATE", "SEVERITY"], dropna=False)
                .size()
                .reset_index(name="ALERTS")
                .sort_values(["SLA_STATE", "SEVERITY"])
            )
            _render_priority_dataframe(
                sla_summary,
                title="Loaded alert SLA mix",
                priority_columns=["SLA_STATE", "SEVERITY", "ALERTS"],
                sort_by=["SLA_STATE", "SEVERITY"],
                ascending=[True, True],
                max_rows=20,
                raw_label="All SLA mix rows",
                height=220,
            )
