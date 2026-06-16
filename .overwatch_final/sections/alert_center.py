# sections/alert_center.py - single alert inbox and email-first alert operations
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, DAY_WINDOW_OPTIONS, DEFAULT_ALERT_EMAIL, DEFAULT_DAY_WINDOW
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    with_loaded_at,
)


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
    "Active Alerts",
    "Detection Catalog",
    "Issue Inbox",
    "Triage Digest",
    "Alert History",
    "Email Delivery",
    "Action Queue Routing",
    "Delivery & Remediation",
    "Suppression Windows",
]

ALERT_CENTER_PANE_LABELS = {
    "Active Alerts": "Active",
    "Detection Catalog": "Catalog",
    "Issue Inbox": "Inbox",
    "Triage Digest": "Digest",
    "Alert History": "History",
    "Email Delivery": "Email",
    "Action Queue Routing": "Routing",
    "Delivery & Remediation": "Remediation",
    "Suppression Windows": "Suppressions",
}

ALERT_CENTER_BRIEF_FIRST_VERSION = 2
ALERT_CENTER_DEFAULT_VIEW = "Active Alerts"

ALERT_CENTER_BRIEF_WORKFLOWS = (
    {
        "VIEW": "Active Alerts",
        "BUTTON_LABEL": "Open Active Alerts",
        "DBA_MOVE": "Start with severity-ranked operational risk and alert routes.",
        "WHEN": "First look, shift start, incident review",
    },
    {
        "VIEW": "Detection Catalog",
        "BUTTON_LABEL": "Open Detection Catalog",
        "DBA_MOVE": "Review Snowflake-native checks before enabling or tuning alert rules.",
        "WHEN": "Coverage review, audit, threshold tuning",
    },
    {
        "VIEW": "Issue Inbox",
        "BUTTON_LABEL": "Open Issue Inbox",
        "DBA_MOVE": "Start with the combined alert and action-queue inbox.",
        "WHEN": "Morning triage, new alerts, route assignment",
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
        "DBA_MOVE": "Confirm which alerts are email-ready or already logged.",
        "WHEN": "Notification audit, executive status, daily digest",
    },
    {
        "VIEW": "Action Queue Routing",
        "BUTTON_LABEL": "Open Queue Routing",
        "DBA_MOVE": "Move alert telemetry into routed work.",
        "WHEN": "Queue closure, ticket routing, DBA follow-up",
    },
    {
        "VIEW": "Delivery & Remediation",
        "BUTTON_LABEL": "Open Remediation",
        "DBA_MOVE": "Review delivery status, suppression windows, and remediation log evidence.",
        "WHEN": "Notification review, remediation status, suppression cleanup",
    },
)

ALERT_CENTER_SOURCES_BY_PANE = {
    "Active Alerts": {"alerts", "action_queue", "delivery_log", "rules"},
    "Detection Catalog": set(),
    "Issue Inbox": {"alerts", "action_queue"},
    "Triage Digest": {"alerts"},
    "Alert History": {"alerts"},
    "Email Delivery": {"alerts", "delivery_log"},
    "Action Queue Routing": {"alerts", "action_queue"},
    "Delivery & Remediation": {"alerts", "delivery_log", "rules"},
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
        "WHY": "Route, ticket, due date, and status tracking",
        "COST_GUARDRAIL": "Limited queue read",
    },
    "delivery_log": {
        "SOURCE": "Email delivery audit",
        "OBJECT": "Alert delivery log",
        "WHY": "Notification telemetry and escalation audit",
        "COST_GUARDRAIL": "Recent-window audit read",
    },
    "rules": {
        "SOURCE": "Rule catalog",
        "OBJECT": "Alert rules",
        "WHY": "Severity, SLA, route, and runbook control",
        "COST_GUARDRAIL": "Small configuration read",
    },
}


def _alert_email_target() -> str:
    from utils.alerts import current_alert_recipient

    return current_alert_recipient(DEFAULT_ALERT_EMAIL)


def _alert_center_sources_for_view(view: str) -> set[str]:
    return set(ALERT_CENTER_SOURCES_BY_PANE.get(_normalize_alert_center_view(view), {"alerts"}))


def _normalize_alert_center_view(view: object) -> str:
    normalized = str(view or "")
    if normalized in {"Alert Brief", "Command Center", "Control Health"}:
        return ALERT_CENTER_DEFAULT_VIEW
    return normalized if normalized in ALERT_CENTER_PANES else ALERT_CENTER_DEFAULT_VIEW


def _alert_center_source_summary(sources: set[str]) -> str:
    names = [
        str(ALERT_CENTER_SOURCE_PLAN[source]["SOURCE"]).replace("sources", "inputs").replace("Sources", "Inputs")
        for source in sorted(sources)
        if source in ALERT_CENTER_SOURCE_PLAN
    ]
    return ", ".join(names) if names else "No Snowflake inputs"


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
            "Status changes are handled by the DBA team outside this dashboard."
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
        load_alert_rule_catalog,
    )

    sources = set(sources or ALERT_CENTER_SOURCES_BY_PANE[ALERT_CENTER_DEFAULT_VIEW])
    data: dict[str, object] = {
        "alerts": pd.DataFrame(),
        "action_queue": pd.DataFrame(),
        "issues": pd.DataFrame(),
        "delivery_log": pd.DataFrame(),
        "rules": pd.DataFrame(),
        "alerts_error": "",
        "queue_error": "",
        "delivery_error": "",
        "rule_error": "",
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
    st.caption("Use suppression windows for planned maintenance, backfills, and noisy operating windows so the hourly alert task does not create duplicate noise.")

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
                st.info(f"Suppression windows are not available in this environment yet. {_format_snowflake_error(exc)}")
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
            "Loaded scope status",
            "Scope Stale",
            "High",
            f"Loaded {loaded_scope}; current filter is {expected_scope}.",
            "Reload Alert Center before triage, routing, or delivery logging.",
        )
    else:
        add(
            "Loaded scope status",
            "Ready",
            "Low",
            f"Loaded scope matches current filters: {expected_scope}.",
            "Continue triage from the loaded telemetry.",
        )

    alert_error = str(data.get("alerts_error") or "")
    if alert_error:
        add(
            "Alert history input",
            "Needs Data",
            "High",
            alert_error,
            "Enable alert history objects before relying on this monitor.",
        )
    elif alerts.empty:
        add(
            "Alert history input",
            "No Rows",
            "Low",
            "Alert input loaded successfully but returned zero rows.",
            "If issues are expected, validate the hourly alert task and access grants.",
        )
    else:
        open_mask = _open_alert_mask(alerts)
        overdue = int((alerts.get("SLA_STATE", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).eq("Overdue") & open_mask).sum())
        add(
            "Alert history input",
            "Ready",
            "Low" if overdue == 0 else "High",
            f"{len(alerts):,} alert row(s), {int(open_mask.sum()):,} open, {overdue:,} overdue.",
            "Work overdue rows first, then route confirmed alerts to the action queue.",
        )

    queue_error = str(data.get("queue_error") or "")
    if queue_error:
        add(
            "Action queue input",
            "Degraded",
            "Medium",
            queue_error,
            "Action queue telemetry is unavailable; keep alert routing informational until queue data loads.",
        )
    elif queue.empty:
        add(
            "Action queue input",
            "No Rows",
            "Low",
            "Action queue input loaded successfully with no rows.",
            "Route confirmed open alerts when work needs route, notes, and status tracking.",
        )
    else:
        open_queue = 0
        if "STATUS" in queue.columns:
            open_queue_mask = ~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])
            open_queue = int(open_queue_mask.sum())
        add(
            "Action queue input",
            "Ready",
            "Low",
            f"{len(queue):,} queue row(s) loaded; open count is {open_queue:,}.",
            "Use queue rows to confirm route, due date, ticket/reference, and closure status.",
        )

    delivery_error = str(data.get("delivery_error") or "")
    if delivery_error:
        add(
            "Delivery audit input",
            "Needs Data",
            "Medium",
            delivery_error,
            "Delivery status telemetry is unavailable; keep digest/email status informational until the input loads.",
        )
    elif delivery_log.empty:
        add(
            "Delivery audit input",
            "No Rows",
            "Low",
            "Delivery audit table loaded but has no recent rows.",
            "Log the next digest delivery so escalations have audit status.",
        )
    else:
        add(
            "Delivery audit input",
            "Ready",
            "Low",
            f"{len(delivery_log):,} delivery audit row(s) loaded.",
            "Use delivery audit rows to confirm who was notified and when.",
        )

    if rules.empty:
        add(
            "Rule catalog input",
            "Needs Data",
            "Medium",
            str(data.get("rule_error") or "No alert rules were loaded."),
            "Use built-in rules until Snowflake rule telemetry is available.",
        )
    else:
        source = rules.get("RULE_SOURCE", pd.Series(index=rules.index, dtype=str)).fillna("").astype(str)
        configured = int(source.eq("Database").sum())
        fallback = int(len(rules) - configured)
        state = "Ready" if configured else "Fallback"
        add(
            "Rule catalog input",
            state,
            "Low" if configured else "Medium",
            f"{configured:,} database rule(s), {fallback:,} built-in fallback rule(s).",
            "Use loaded rule telemetry before treating SLA or routing changes as authoritative.",
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
        "Keep email-first delivery until the Snowflake notification integration is configured.",
    )

    generic_owners = {"", "DBA", "OVERWATCH"}
    if alerts.empty or "OWNER" not in alerts.columns:
        generic_count = 0
    else:
        open_mask = _open_alert_mask(alerts)
        generic_count = int(alerts.loc[open_mask, "OWNER"].fillna("").astype(str).str.upper().isin(generic_owners).sum())
    add(
        "Alert routing",
        "Ready" if generic_count == 0 else "Review",
        "Low" if generic_count == 0 else "Medium",
        f"{generic_count:,} open alert(s) still have generic or missing routes.",
        "Route high-severity alerts before escalating outside the app.",
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


def _alert_center_health_score(rows: pd.DataFrame) -> int:
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
        blockers = rows[state_text.isin({"NEEDS DATA", "DEGRADED", "SCOPE STALE"})]
        if not blockers.empty:
            row = blockers.iloc[0]
            control = str(row.get("CONTROL") or "Alert control")
            evidence = str(row.get("EVIDENCE") or "Control telemetry needs review.")
            next_action = str(row.get("NEXT_ACTION") or "").strip()
            return {
                "state": str(row.get("STATE") or "Blocked"),
                "headline": "Restore alert control telemetry.",
                "detail": f"{control}: {next_action or evidence}".strip(": "),
                "primary_label": "Open Active Alerts",
                "target": ALERT_CENTER_DEFAULT_VIEW,
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
            "detail": f"{open_queue:,} open queue row(s) need route, ticket, due date, or closure status.",
            "primary_label": "Open Queue",
            "target": "Action Queue Routing",
        }
    if email_ready > email_logged:
        return {
            "state": "Telemetry",
            "headline": "Log alert delivery status.",
            "detail": f"{email_ready:,} email-ready alert(s); {email_logged:,} delivery row(s) logged in this scope.",
            "primary_label": "Open Delivery",
            "target": "Email Delivery",
        }
    if open_issues > 0:
        return {
            "state": "Triage",
            "headline": "Review the consolidated issue inbox.",
            "detail": f"{open_issues:,} issue row(s) are loaded from alert history and action queue telemetry.",
            "primary_label": "Open Inbox",
            "target": "Issue Inbox",
        }
    return {
        "state": "Clear",
        "headline": "No immediate Alert Center move.",
        "detail": "Keep the selected window loaded for delivery status, routing, and rule telemetry when new alerts arrive.",
        "primary_label": "Open Inbox",
        "target": "Issue Inbox",
    }


def _alert_center_pending_brief(active_view: str, required_sources: set[str]) -> dict:
    active_view = _normalize_alert_center_view(active_view)
    return {
        "state": "Ready",
        "headline": f"Load {active_view} before routing alert work.",
        "detail": f"Inputs on load: {_alert_center_source_summary(required_sources)}.",
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
    normalized = _normalize_alert_center_view(view)
    if normalized in ALERT_CENTER_PANES:
        st.session_state["alert_center_requested_view"] = normalized
        st.rerun()


def _apply_queued_alert_center_view() -> None:
    requested = st.session_state.pop("alert_center_requested_view", None)
    if requested:
        st.session_state["alert_center_active_view"] = _normalize_alert_center_view(requested)


def _apply_alert_center_brief_first_default() -> None:
    if st.session_state.get("_alert_center_brief_first_version") == ALERT_CENTER_BRIEF_FIRST_VERSION:
        st.session_state["alert_center_active_view"] = _normalize_alert_center_view(
            st.session_state.get("alert_center_active_view")
        )
        return
    if st.session_state.get("alert_center_active_view") in (None, "Alert Brief", "Command Center"):
        st.session_state["alert_center_active_view"] = ALERT_CENTER_DEFAULT_VIEW
    else:
        st.session_state["alert_center_active_view"] = _normalize_alert_center_view(
            st.session_state.get("alert_center_active_view")
        )
    st.session_state["_alert_center_brief_first_version"] = ALERT_CENTER_BRIEF_FIRST_VERSION


def _render_alert_center_brief_launchpad() -> None:
    st.markdown("**Alert Investigation Workflows**")
    rows = _alert_center_brief_workflow_rows()
    for offset in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, rows[offset:offset + 3]):
            with col:
                st.markdown(f"**{row['VIEW']}**")
                help_text = f"{row['DBA_MOVE']} When: {row['WHEN']}"
                if st.button(
                    row["BUTTON_LABEL"],
                    key=f"alert_center_brief_{row['VIEW']}",
                    help=help_text,
                    width="stretch",
                ):
                    _queue_alert_center_view(row["VIEW"])


def _render_alert_center_action_brief(brief: dict) -> None:
    render_shell_status_strip(
        state=brief.get("state") or "Review",
        headline=brief.get("headline") or "Review Alert Center telemetry.",
        detail=brief.get("detail") or "",
    )


def _alert_center_scope_key(
    active_view: str,
    company: str,
    environment: str,
    days: int,
    limit: int,
    required_sources: set[str],
) -> tuple:
    return (
        str(active_view),
        str(company),
        str(environment),
        int(days),
        int(limit),
        tuple(sorted(required_sources)),
    )


def _alert_center_loaded_meta(data: dict | None, active_view: str) -> dict:
    if not isinstance(data, dict):
        return {}
    meta = data.get("_freshness_meta")
    if isinstance(meta, dict):
        return meta
    loaded_at = str(data.get("loaded_at") or "").strip()
    if not loaded_at:
        return {}
    return {
        "loaded_at": loaded_at,
        "source": f"{active_view} loaded sources",
    }


def _load_alert_center_view_data(
    active_view: str,
    company: str,
    environment: str,
    days: int,
    limit: int,
    required_sources: set[str],
) -> bool:
    session = _alert_center_action_session(f"load {active_view}")
    if session is None:
        return False
    st.session_state["alert_center_data"] = _load_center_data(
        session,
        company,
        environment,
        int(days),
        int(limit),
        sources=required_sources,
    )
    if isinstance(st.session_state.get("alert_center_data"), dict):
        st.session_state["alert_center_data"]["_freshness_meta"] = with_loaded_at(
            {
                "view": active_view,
                "company": company,
                "environment": environment,
                "days": int(days),
                "limit": int(limit),
                "sources": sorted(required_sources),
            },
            source=f"{active_view} loaded sources",
        )
    st.session_state["alert_center_scope"] = (company, environment, int(days), int(limit))
    st.session_state["alert_center_loaded_scope_key"] = _alert_center_scope_key(
        active_view,
        company,
        environment,
        int(days),
        int(limit),
        required_sources,
    )
    return True


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
    if not loaded:
        render_shell_kpi_row((
            ("Scope", "Company"),
            ("Window", "Selected"),
            ("Telemetry", "Load view"),
            ("Route", "Issue Inbox"),
        ))
        return
    render_shell_kpi_row((
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


def _alert_command_lanes(
    *,
    active_view: str,
    required_sources: set[str],
    alerts: object | None = None,
    queue: object | None = None,
    issues: object | None = None,
    delivery_log: object | None = None,
    loaded: bool = False,
) -> list[dict[str, str]]:
    """Return alert monitoring lanes without loading new data."""
    if not loaded:
        source_text = ", ".join(sorted(required_sources)) if required_sources else "no source load required"
        return [
            {
                "label": "Critical / high",
                "value": "On demand",
                "state": "Severity",
                "detail": f"{active_view} will read: {source_text}.",
            },
            {
                "label": "Overdue SLA",
                "value": "On demand",
                "state": "Aging",
                "detail": "Open alerts need route, acknowledgement, suppression, or resolution.",
            },
            {
                "label": "Security risk",
                "value": "On demand",
                "state": "Security",
                "detail": "Failed logins, risky grants, exfiltration, and policy drift route here.",
            },
            {
                "label": "Cost",
                "value": "On demand",
                "state": "Spend",
                "detail": "Runaway spend, warehouse spikes, Cortex spend, and spend risk.",
            },
            {
                "label": "Performance",
                "value": "On demand",
                "state": "Queries",
                "detail": "Long, queued, failed, spilling, and blocked query signals.",
            },
            {
                "label": "Pipeline reliability",
                "value": "On demand",
                "state": "Tasks",
                "detail": "Failed, skipped, late, or suspended task/procedure paths.",
            },
            {
                "label": "Data quality",
                "value": "Configured",
                "state": "Rules",
                "detail": "Metadata-driven freshness, row count, null, duplicate, and schema checks.",
            },
            {
                "label": "Notification route",
                "value": "On demand",
                "state": "Delivery",
                "detail": "Email/webhook/native-alert delivery remains audit-backed.",
            },
        ]

    pd = _pd()
    alerts = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    queue = queue if isinstance(queue, pd.DataFrame) else pd.DataFrame()
    issues = issues if isinstance(issues, pd.DataFrame) else pd.DataFrame()
    delivery_log = delivery_log if isinstance(delivery_log, pd.DataFrame) else pd.DataFrame()
    open_alerts = _open_alert_mask(alerts) if not alerts.empty else pd.Series(dtype=bool)
    severity = alerts.get("SEVERITY", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str) if not alerts.empty else pd.Series(dtype=str)
    category = alerts.get("CATEGORY", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).str.upper() if not alerts.empty else pd.Series(dtype=str)
    critical_high = int((severity.isin(["Critical", "High"]) & open_alerts).sum()) if not alerts.empty else 0
    overdue = 0
    if not alerts.empty and "SLA_STATE" in alerts.columns:
        overdue = int((alerts["SLA_STATE"].fillna("").astype(str).eq("Overdue") & open_alerts).sum())
    open_queue = 0
    if not queue.empty and "STATUS" in queue.columns:
        open_queue = int((~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])).sum())
    delivery_failures = 0
    if not delivery_log.empty and "DELIVERY_STATUS" in delivery_log.columns:
        delivery_failures = int(delivery_log["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("FAILED|ERROR|BOUNCED", regex=True).sum())

    def cat_count(*needles: str) -> int:
        if category.empty:
            return 0
        mask = pd.Series(False, index=category.index)
        for needle in needles:
            mask = mask | category.str.contains(needle, regex=False)
        return int((mask & open_alerts).sum())

    return [
        {
            "label": "Critical / high",
            "value": f"{critical_high:,}",
            "state": "Severity" if critical_high else "Clear",
            "detail": f"{int(open_alerts.sum()) if not open_alerts.empty else 0:,} open alert(s) in loaded scope.",
        },
        {
            "label": "Overdue SLA",
            "value": f"{overdue:,}",
            "state": "Aging" if overdue else "Clear",
            "detail": "Overdue high-severity rows should be acknowledged or escalated first.",
        },
        {
            "label": "Security risk",
            "value": f"{cat_count('SECURITY'):,}",
            "state": "Security",
            "detail": "Login, privilege, sharing, and access anomalies.",
        },
        {
            "label": "Cost",
            "value": f"{cat_count('COST', 'COST'):,}",
            "state": "Spend",
            "detail": "Warehouse, Cortex, service-cost, and spend risk signals.",
        },
        {
            "label": "Performance",
            "value": f"{cat_count('PERFORMANCE', 'QUERY', 'WAREHOUSE'):,}",
            "state": "Queries",
            "detail": "Long, queued, failed, spilling, and blocked queries.",
        },
        {
            "label": "Pipeline reliability",
            "value": f"{cat_count('TASK', 'PIPELINE', 'PROCEDURE'):,}",
            "state": "Tasks",
            "detail": "Task/procedure failures, late runs, and recovery alerts.",
        },
        {
            "label": "Action queue",
            "value": f"{open_queue:,}",
            "state": "Routes",
            "detail": f"{len(issues):,} unified issue row(s) loaded.",
        },
        {
            "label": "Delivery failures",
            "value": f"{delivery_failures:,}",
            "state": "Delivery" if delivery_failures else "Ready",
            "detail": f"{len(delivery_log):,} notification audit row(s).",
        },
    ]


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
            "Review route, SLA state, and delivery status for critical/high alerts.",
            route="Triage Digest",
        )
        if "SLA_STATE" in alerts.columns:
            sla_state = alerts["SLA_STATE"].fillna("").astype(str)
            add(
                "Overdue alert SLAs",
                "High",
                int((sla_state.eq("Overdue") & open_alerts).sum()),
                "Overdue",
                "Send overdue alert rows through the digest and confirm route response.",
                route="Triage Digest",
            )
        owner = alerts.get("OWNER", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).str.upper()
        add(
            "Generic alert routes",
            "Medium",
            int((owner.isin(["", "DBA", "OVERWATCH"]) & open_alerts).sum()),
            "Route alert",
            "Replace generic alert routes before escalation.",
            owner="Platform DBA",
            route=ALERT_CENTER_DEFAULT_VIEW,
        )
        delivery_status = alerts.get("DELIVERY_STATUS", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).str.upper()
        ready_count = int(delivery_status.str.contains("EMAIL_READY").sum())
        logged_count = int(delivery_status.str.contains("EMAIL_LOGGED").sum())
        add(
            "Delivery status gap",
            "Medium",
            max(0, ready_count - logged_count),
            "Log delivery",
            "Log digest/email delivery status for ready alerts.",
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
                "Confirm route, due date, ticket, and closure status on open queue rows.",
                owner="DBA Lead",
                route="Action Queue Routing",
            )

    if readiness_rows is not None and not readiness_rows.empty and "STATE" in readiness_rows.columns:
        blockers = readiness_rows["STATE"].fillna("").astype(str).str.upper().isin({"NEEDS DATA", "DEGRADED", "SCOPE STALE"})
        add(
            "Alert control blockers",
            "High",
            int(blockers.sum()),
            "Reload inputs",
            "Reload alert inputs, route status, or delivery logs before acting on stale telemetry.",
            owner="Platform DBA",
            route=ALERT_CENTER_DEFAULT_VIEW,
        )

    if issues is not None and not issues.empty:
        severity = issues.get("SEVERITY", pd.Series(index=issues.index, dtype=str)).fillna("").astype(str)
        add(
            "High-priority issue rows",
            "High",
            int(severity.isin(["Critical", "High"]).sum()),
            "Review first",
            "Open issue detail only when the exception strip needs row-level detail.",
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
            "Review failed notification attempts and route to the email integration contact.",
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
        "DBA / COST OWNER",
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
                "OWNER_ROUTE_STATE": "Needs named route" if owner_key in generic_owners else "Named route",
                "DELIVERY_ROUTE_STATE": "Missing email target" if not email_target else "Email target ready",
                "ACTION_ROUTE_STATE": "Route to action queue" if route == "Alert Center" else f"Route: {route}",
                "NEXT_ACTION": row.get("SUGGESTED_ACTION", "Review alert telemetry and assign route."),
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
                "OWNER_ROUTE_STATE": "Needs named route" if owner_key in generic_owners else "Named route",
                "DELIVERY_ROUTE_STATE": "Missing route email" if not email_target else "Route email ready",
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

    owner_ready = board["OWNER_ROUTE_STATE"].astype(str).eq("Named route")
    email_ready = ~board["DELIVERY_ROUTE_STATE"].astype(str).str.startswith("Missing")
    oncall_ready = board["ONCALL_PRIMARY"].fillna("").astype(str).str.strip().ne("")
    route_gap = (
        board["OWNER_ROUTE_STATE"].astype(str).ne("Named route")
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
            lifecycle_state = "Closed - confirm status"
        elif sla_state == "Overdue" and severity in {"Critical", "High"}:
            lifecycle_state = "Escalate now"
        elif not owner_ready:
            lifecycle_state = "Assign route"
        elif not queued:
            lifecycle_state = "Route to action queue"
        elif not delivery_logged and email_ready:
            lifecycle_state = "Log delivery status"
        else:
            lifecycle_state = "Work and confirm"

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
            "CLOSURE_STATUS_REQUIRED": (
                "ticket/reference, remediation note, and post-fix telemetry status"
                if status_key not in {"FIXED", "RESOLVED", "CLOSED"}
                else "retain closure status and delivery/action audit"
            ),
            "NEXT_ACTION": row.get("SUGGESTED_ACTION", "Review alert telemetry and update lifecycle."),
            "ALERT_TS": row.get("ALERT_TS", ""),
        })

    board = pd.DataFrame(rows)
    if board.empty:
        return board
    state_rank = {
        "Escalate now": 0,
        "Assign route": 1,
        "Route to action queue": 2,
        "Log delivery status": 3,
        "Work and confirm": 4,
        "Closed - confirm status": 5,
    }
    severity_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    board["_STATE_RANK"] = board["LIFECYCLE_STATE"].map(state_rank).fillna(9)
    board["_SEV_RANK"] = board["SEVERITY"].map(severity_rank).fillna(9)
    return board.sort_values(["_STATE_RANK", "_SEV_RANK", "ALERT_TS"], ascending=[True, True, False]).drop(
        columns=["_STATE_RANK", "_SEV_RANK"], errors="ignore"
    ).reset_index(drop=True)


def _alert_integration_health_board(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
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
        "CONTROL": "Email delivery status",
        "STATE": "Ready" if delivery_rows > 0 else "Review",
        "EVIDENCE": f"{email_ready:,} email-ready alert(s); {delivery_rows:,} delivery audit row(s).",
        "NEXT_ACTION": "Log each digest delivery until a Snowflake notification integration is enabled.",
        "OWNER": "DBA On-Call",
    })
    rows.append({
        "CONTROL": "Snowflake notification integration",
        "STATE": "Review",
        "EVIDENCE": "Email-first delivery uses configured recipients until a Snowflake notification integration exists.",
        "NEXT_ACTION": "Create email/notification integration and replace placeholders with production distribution lists.",
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
        "CONTROL": "Action queue lifecycle",
        "STATE": "Review" if tickets == 0 else "Partial",
        "EVIDENCE": f"{open_queue:,} open queue row(s); {tickets:,} reference id(s) attached.",
        "NEXT_ACTION": "Use the in-app action queue for acknowledgement, routing, comments, suppression, and closure status.",
        "OWNER": "DBA On-Call",
    })
    rows.append({
        "CONTROL": "Open alert lifecycle",
        "STATE": "Ready" if open_alert_count == 0 else "Review",
        "EVIDENCE": f"{open_alert_count:,} open alert(s) in the loaded scope.",
        "NEXT_ACTION": "Every open alert needs route, notes, delivery status, action queue state, and closure status.",
        "OWNER": "DBA On-Call",
    })

    board = pd.DataFrame(rows)
    if board.empty:
        return board
    board["_STATE_RANK"] = board["STATE"].map({
        "Priority Gap": 0,
        "Review": 1,
        "Review": 2,
        "Partial": 3,
        "Ready": 4,
    }).fillna(9)
    return board.sort_values(["_STATE_RANK", "CONTROL"]).drop(columns=["_STATE_RANK"], errors="ignore")


def _render_active_alerts(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    rules: pd.DataFrame,
) -> None:
    from utils.alerts import (
        build_alert_command_center_summary,
        build_alert_incident_action_board,
        build_alert_owner_workload_board,
    )

    pd = _pd()
    st.subheader("Active Alert Queue")
    summary = build_alert_command_center_summary(alerts)
    metrics = summary.get("metrics", pd.DataFrame())
    if isinstance(metrics, pd.DataFrame) and not metrics.empty:
        metric_lookup = {str(row["METRIC"]): row for _, row in metrics.iterrows()}
        render_shell_snapshot((
            ("Open Critical", f"{int(metric_lookup.get('Open critical', {}).get('VALUE', 0)):,}"),
            ("Warnings", f"{int(metric_lookup.get('Warning alerts', {}).get('VALUE', 0)):,}"),
            ("Info", f"{int(metric_lookup.get('Info alerts', {}).get('VALUE', 0)):,}"),
            ("Resolved", f"{int(metric_lookup.get('Resolved alerts', {}).get('VALUE', 0)):,}"),
        ))
        _render_priority_dataframe(
            metrics,
            title="Operating metrics",
            priority_columns=["METRIC", "VALUE", "STATE", "DETAIL"],
            raw_label="All alert operating metrics",
            height=220,
        )

    incident_board = build_alert_incident_action_board(alerts, queue, limit=25)
    if isinstance(incident_board, pd.DataFrame) and not incident_board.empty:
        _render_priority_dataframe(
            incident_board,
            title="Incidents to work first",
            priority_columns=[
                "PRIORITY", "SEVERITY", "SLA_STATE", "AGE_HOURS", "CATEGORY",
                "SIGNAL", "ENTITY", "OWNER", "BUSINESS_IMPACT",
                "FIRST_RESPONSE", "RECOMMENDED_ACTION", "TICKET_ID",
                "REMEDIATION_MODE",
            ],
            sort_by=["PRIORITY"],
            ascending=True,
            raw_label="All active incident rows",
            height=420,
        )
        _download_csv(incident_board, "overwatch_alert_incident_action_board.csv")

    category_board = summary.get("category_board", pd.DataFrame())
    if isinstance(category_board, pd.DataFrame) and not category_board.empty:
        _render_priority_dataframe(
            category_board,
            title="Business-impact categories",
            priority_columns=[
                "CATEGORY", "OPEN", "CRITICAL_HIGH", "RESOLVED",
                "SEVERITY_SCORE", "BUSINESS_IMPACT",
                "RECOMMENDED_ACTION",
            ],
            sort_by=["SEVERITY_SCORE", "OPEN"],
            ascending=[False, False],
            raw_label="All alert categories",
            height=300,
        )
    else:
        st.success("No open category risk rows found in the loaded alert scope.")

    recurring = summary.get("recurring", pd.DataFrame())
    if isinstance(recurring, pd.DataFrame) and not recurring.empty:
        _render_priority_dataframe(
            recurring,
            title="Top recurring issues",
            priority_columns=["CATEGORY", "SIGNAL", "ENTITY", "ALERTS", "SEVERITY", "OWNER", "RECOMMENDED_ACTION"],
            sort_by=["ALERTS", "SEVERITY"],
            ascending=[False, True],
            raw_label="All recurring alert groups",
            height=260,
        )

    owner_board = build_alert_owner_workload_board(alerts, queue)
    if isinstance(owner_board, pd.DataFrame) and not owner_board.empty:
        _render_priority_dataframe(
            owner_board,
            title="Route workload and telemetry gaps",
            priority_columns=[
                "OWNER", "OPEN_ALERTS", "CRITICAL_HIGH", "SLA_BREACHED",
                "TICKETS_ATTACHED", "TOP_CATEGORY", "NEXT_ACTION", "APPROVAL_GROUP",
            ],
            sort_by=["SLA_BREACHED", "CRITICAL_HIGH", "OPEN_ALERTS"],
            ascending=[False, False, False],
            raw_label="All route workload rows",
            height=260,
        )

    queue_open = 0
    if not queue.empty and "STATUS" in queue.columns:
        queue_open = int((~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])).sum())
    digest_rows = [
        {
            "CONTROL": "Action queue handoff",
            "STATE": "Ready" if queue_open else "No Open Queue",
            "EVIDENCE": f"{queue_open:,} open action queue row(s).",
            "NEXT_ACTION": "Route confirmed alerts into action rows with ticket/reference and telemetry state.",
            "OWNER": "DBA On-Call",
        },
        {
            "CONTROL": "Rule coverage",
            "STATE": "Ready" if not rules.empty else "Fallback",
            "EVIDENCE": f"{len(rules):,} alert rule row(s) available.",
            "NEXT_ACTION": "Use loaded rule telemetry before treating severity, SLA, route, or runbook changes as authoritative.",
            "OWNER": "Platform DBA",
        },
        {
            "CONTROL": "Notification telemetry",
            "STATE": "Ready" if not delivery_log.empty else "Review",
            "EVIDENCE": f"{len(delivery_log):,} delivery log row(s) loaded.",
            "NEXT_ACTION": "Log alert digests until Snowflake notification integration is live.",
            "OWNER": "DBA On-Call",
        },
    ]
    _render_priority_dataframe(
        pd.DataFrame(digest_rows),
        title="Operating controls",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
        raw_label="All alert monitoring controls",
        height=220,
    )


def _render_alert_detection_catalog() -> None:
    from utils.alerts import build_alert_signal_query_catalog

    st.subheader("Detection Catalog")
    catalog = build_alert_signal_query_catalog(hours=24)
    category_options = ["All"] + sorted(catalog["CATEGORY"].dropna().astype(str).unique().tolist())
    selected_category = st.selectbox("Catalog category", category_options, key="alert_detection_catalog_category")
    visible = catalog if selected_category == "All" else catalog[catalog["CATEGORY"].astype(str) == selected_category]
    visible_display = visible.drop(columns=["SQL"], errors="ignore").rename(columns={"OWNER": "ROUTE"})
    _render_priority_dataframe(
        visible_display,
        title="Snowflake-native alert signals",
        priority_columns=[
            "CATEGORY", "SIGNAL", "SEVERITY", "TELEMETRY", "FRESHNESS",
            "ROUTE", "WHY_THIS_MATTERS", "RECOMMENDED_ACTION",
        ],
        raw_label="All detection catalog rows",
        height=360,
    )
    if not visible.empty:
        signal_options = visible["SIGNAL"].dropna().astype(str).tolist()
        selected_signal = st.selectbox("Signal detail", signal_options, key="alert_detection_catalog_signal")
        selected = visible[visible["SIGNAL"].astype(str) == selected_signal].iloc[0]
        st.caption(str(selected.get("RECOMMENDED_ACTION") or "Review this alert signal with the owning DBA team."))
    defer_source_note("Detection Catalog lists alert signals and required Snowflake telemetry.")


def _render_alert_notification_remediation(
    alerts: pd.DataFrame,
    delivery_log: pd.DataFrame,
    rules: pd.DataFrame,
) -> None:
    from utils.alerts import build_alert_remediation_contract

    pd = _pd()
    st.subheader("Delivery & Remediation")
    controls = [
        {
            "CONTROL": "Alert inbox",
            "STATE": "Ready",
            "EVIDENCE": f"{len(alerts):,} alert row(s) loaded.",
            "NEXT_ACTION": "Use alert status, acknowledgement, suppression, and action-queue routing from Alert Center.",
            "ROUTE": "Alert Center",
        },
        {
            "CONTROL": "Delivery status",
            "STATE": "Ready" if not delivery_log.empty else "Review",
            "EVIDENCE": f"{len(delivery_log):,} delivery audit row(s) loaded.",
            "NEXT_ACTION": "Log delivery status for open critical/high alerts.",
            "ROUTE": "Email Delivery",
        },
        {
            "CONTROL": "Rule catalog",
            "STATE": "Ready" if not rules.empty else "Fallback",
            "EVIDENCE": f"{len(rules):,} rules loaded.",
            "NEXT_ACTION": "Use rules as monitoring context; do not change thresholds from the alert view.",
            "ROUTE": "Detection Catalog",
        },
    ]
    _render_priority_dataframe(
        pd.DataFrame(controls),
        title="Delivery and remediation status",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "ROUTE"],
        raw_label="All delivery and remediation rows",
        height=240,
    )
    if alerts.empty:
        st.info("Load alert history to review remediation status for real alert rows.")
        return

    alert_options = alerts.get("ALERT_ID", pd.Series(range(1, len(alerts) + 1), index=alerts.index)).dropna().astype(str).tolist()
    selected_id = st.selectbox("Remediation status alert", alert_options[:100], key="alert_remediation_contract_id")
    if "ALERT_ID" in alerts.columns:
        selected_rows = alerts[alerts["ALERT_ID"].astype(str) == str(selected_id)]
    else:
        selected_rows = alerts.iloc[[max(0, alert_options.index(selected_id))]]
    contract = build_alert_remediation_contract(selected_rows.iloc[0].to_dict() if not selected_rows.empty else {})
    _render_priority_dataframe(
        pd.DataFrame([contract]),
        title="Safe remediation status",
        priority_columns=[
            "REMEDIATION_MODE", "EXECUTION_BOUNDARY", "ROLLBACK_GUIDANCE",
            "VERIFY_NEXT",
        ],
        raw_label="All remediation status fields",
        height=260,
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

    if active_view == "Suppression Windows":
        _render_annotations()
        return

    if active_view == "Detection Catalog":
        _render_alert_detection_catalog()
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
    data = st.session_state.get("alert_center_data")
    expected_scope = (company, environment, int(days), int(limit))
    loaded_sources = set(data.get("_loaded_sources") or []) if isinstance(data, dict) else set()
    current_data = (
        isinstance(data, dict)
        and st.session_state.get("alert_center_scope") == expected_scope
        and required_sources.issubset(loaded_sources)
    )
    alert_autoload_requested = consume_section_autoload_request("Alert Center")
    if (
        alert_autoload_requested
        and active_view not in {"Suppression Windows", "Detection Catalog"}
        and not current_data
    ):
        st.caption(
            "Alert Center opened without live Snowflake reads. "
            f"Load {active_view} when fresh alert telemetry is needed."
        )
        defer_source_note(f"Inputs on load: {_alert_center_source_summary(required_sources)}")
    render_data_freshness(
        _alert_center_loaded_meta(data, active_view) if current_data else {},
        source=f"{active_view} inputs",
        target_minutes=60,
        delayed_note="Alert Center reads bounded alert/action sources on demand; ACCOUNT_USAGE-backed inputs can lag.",
    )
    with c3:
        if st.button(f"Load {active_view}", key="alert_center_load", type="primary"):
            if _load_alert_center_view_data(active_view, company, environment, int(days), int(limit), required_sources):
                st.rerun()

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
        defer_source_note(f"Inputs on load: {_alert_center_source_summary(required_sources)}")
        return

    loaded_scope = st.session_state.get("alert_center_scope")
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
        st.info(f"Load {active_view} to fetch missing input(s).")
        defer_source_note(f"Missing Alert Center input(s): {_alert_center_source_summary(set(missing_sources))}")
        return

    pd = _pd()
    alerts = data.get("alerts") if isinstance(data.get("alerts"), pd.DataFrame) else pd.DataFrame()
    queue = data.get("action_queue") if isinstance(data.get("action_queue"), pd.DataFrame) else pd.DataFrame()
    issues = data.get("issues") if isinstance(data.get("issues"), pd.DataFrame) else pd.DataFrame()
    delivery_log = data.get("delivery_log") if isinstance(data.get("delivery_log"), pd.DataFrame) else pd.DataFrame()
    rules = data.get("rules") if isinstance(data.get("rules"), pd.DataFrame) else pd.DataFrame()
    if data.get("alerts_error"):
        st.info("Alert history unavailable.")
        defer_source_note(
            "Enable alert history objects before relying on this monitoring source.",
            data["alerts_error"],
        )
    if data.get("queue_error"):
        defer_source_note("Action queue unavailable for this role/context.", data["queue_error"])
    if data.get("delivery_error"):
        defer_source_note("Delivery audit is not available in this environment yet.", data["delivery_error"])
    if data.get("rule_error"):
        defer_source_note("Alert rule catalog is not available in this environment yet.", data["rule_error"])
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

    if active_view == ALERT_CENTER_DEFAULT_VIEW:
        _render_active_alerts(alerts, queue, delivery_log, rules)

    elif active_view == "Delivery & Remediation":
        _render_alert_notification_remediation(alerts, delivery_log, rules)

    elif active_view == "Issue Inbox":
        st.subheader("All Active DBA Issues")
        visible = _filtered_issues(issues)
        if visible.empty:
            st.success("No active alert or action queue issues found for this scope.")
        else:
            st.caption(
                f"{len(visible):,} issue row(s) match the filters. "
                "Use the exception strip first; render row-level detail only when needed."
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
            st.info("Load alert history before preparing the operator digest.")
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
                ("Needs Route", f"{digest_summary['needs_owner']:,}"),
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
                st.caption("Use this after the email digest is sent or handed off. This records delivery status and marks included alerts as escalated.")
                with st.form("alert_center_log_digest_delivery"):
                    delivery_target = st.text_input(
                        "Delivery target",
                        value=_alert_email_target(),
                        key="alert_center_digest_target",
                    )
                    delivery_notes = st.text_area(
                        "Delivery notes",
                        key="alert_center_digest_notes",
                        placeholder="Example: Sent via Outlook to DBA on-call and platform route; INC12345 opened.",
                    )
                    submitted_delivery = st.form_submit_button("Log Digest Delivery")
                if submitted_delivery:
                    digest_alerts = alerts[_open_alert_mask(alerts)]
                    if digest_alerts.empty:
                        st.warning("No open alert rows are available to log.")
                    elif len(delivery_notes.strip()) < 10:
                        st.warning("Delivery notes are required for audit status.")
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
                    ("Needs Route", f"{int(lifecycle['LIFECYCLE_STATE'].eq('Assign route').sum()):,}"),
                    ("Not Queued", f"{int(lifecycle['ACTION_QUEUE_STATE'].eq('Not queued').sum()):,}"),
                ))
                _render_priority_dataframe(
                    lifecycle,
                    title="Alert lifecycle summary",
                    priority_columns=[
                        "LIFECYCLE_STATE", "SLA_STATE", "SEVERITY", "STATUS",
                        "CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER",
                        "ESCALATION_TARGET", "DELIVERY_STATUS", "ACTION_QUEUE_STATE",
                        "NEXT_ACTION",
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
                    build_alert_acknowledgement_insert_sql,
                    build_alert_remediation_log_insert_sql,
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
                            "Reason / status",
                            key="alert_center_status_reason",
                            placeholder="Ticket, route confirmation, remediation status, or reason for ignore.",
                        )
                        submitted = st.form_submit_button("Update Alert Status")
                    if submitted:
                        if not reason.strip():
                            st.warning("A reason or status note is required before changing alert status.")
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
                            placeholder="Route accepted, ticket opened, escalation recipient confirmed, or next checkpoint.",
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
                with st.expander("Lifecycle audit preview", expanded=False):
                    audit_alert = st.selectbox("Audit event ID", alert_ids, key="alert_center_audit_event_id")
                    audit_status = st.selectbox(
                        "Lifecycle status",
                        list(ALERT_STATUS_CHOICES),
                        key="alert_center_audit_status",
                    )
                    audit_owner = st.text_input(
                        "Route",
                        key="alert_center_audit_owner",
                        placeholder="DBA / Cost owner / Security route",
                    )
                    audit_note = st.text_area(
                        "Audit note",
                        key="alert_center_audit_note",
                        placeholder="Ticket, investigation result, route assignment, or remediation status.",
                    )
                    if len(str(audit_note or "").strip()) >= 5:
                        audit_sql_parts = [
                            build_alert_acknowledgement_insert_sql(
                                event_id=audit_alert,
                                alert_key=str(audit_alert),
                                note=audit_note,
                                actor=_alert_actor(),
                                owner=audit_owner,
                                status_after_ack=audit_status,
                                next_checkpoint_hours=8,
                            ),
                            build_alert_remediation_log_insert_sql(
                                event_id=audit_alert,
                                alert_key=str(audit_alert),
                                remediation_mode="RECOMMEND",
                                action_type=f"Lifecycle status: {audit_status}",
                                before_state="Alert reviewed from Alert Center.",
                                after_state=str(audit_note),
                                execution_status="RECORDED",
                                rollback_guidance="Reopen the alert or add a follow-up acknowledgement if the condition returns.",
                                actor=_alert_actor(),
                            ),
                        ]
                        st.caption("Lifecycle audit will record the selected status, note, checkpoint, and remediation log.")
                        if st.button(
                            "Record Lifecycle Audit",
                            key="alert_center_record_lifecycle_audit",
                            help="Records the acknowledgement and remediation log. No remediation action is executed.",
                            width="stretch",
                        ):
                            try:
                                session = _alert_center_action_session("record alert lifecycle audit")
                                if session is None:
                                    return
                                for statement in audit_sql_parts:
                                    session.sql(statement).collect()
                                st.success(f"Lifecycle audit recorded for alert {audit_alert}. Reload the Alert Center to refresh.")
                                st.session_state.pop("alert_center_data", None)
                            except Exception as exc:
                                st.error(f"Could not record lifecycle audit: {_format_snowflake_error(exc)}")
                    else:
                        st.caption("Enter an audit note to record acknowledgement and remediation-log status.")

    elif active_view == "Email Delivery":
        st.subheader("Email Delivery Queue")
        defer_source_note(
            "Rows are email-ready by default once the Snowflake email integration is enabled."
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
                    defer_source_note(f"{recovery_count:,} task/procedure recovery action(s) include recovery SLA and telemetry status fields.")
                _render_priority_dataframe(
                    actions_preview,
                    title="Action queue routing preview",
                    priority_columns=[
                        "Severity", "Category", "Entity Type", "Entity", "Owner",
                        "Oncall Primary", "Review Group",
                        "Recovery SLA State", "Recovery SLA Target Hours",
                        "Action",
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
                    "ONCALL_PRIMARY", "FINDING", "RECOMMENDED_ACTION",
                    "TICKET_ID", "DUE_STATE",
                ],
                sort_by=["SEVERITY", "STATUS", "UPDATED_AT"],
                ascending=[True, True, False],
                raw_label="All action queue rows",
                height=320,
            )
