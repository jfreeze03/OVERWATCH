# sections/alert_center.py - single alert inbox and email-first alert operations
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, DAY_WINDOW_OPTIONS, DEFAULT_ALERT_EMAIL, DEFAULT_DAY_WINDOW
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
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
    "Command Center",
    "Cost & Behavior",
    "Reliability",
    "Security",
    "Detection Catalog",
    "Delivery & Automation",
    "Suppression Windows",
]

ALERT_CENTER_PANE_LABELS = {
    "Command Center": "Command",
    "Cost & Behavior": "Cost/Cortex",
    "Reliability": "Reliability",
    "Security": "Security",
    "Detection Catalog": "Catalog",
    "Delivery & Automation": "Automation",
    "Suppression Windows": "Suppressions",
}

ALERT_CENTER_BRIEF_FIRST_VERSION = 3
ALERT_CENTER_DEFAULT_VIEW = "Command Center"

ALERT_CENTER_BRIEF_WORKFLOWS = (
    {
        "VIEW": "Command Center",
        "BUTTON_LABEL": "Open Command Center",
        "DBA_MOVE": "Start with severity, SLA, route, queue, and notification risk in one place.",
        "WHEN": "First look, shift start, incident review",
    },
    {
        "VIEW": "Cost & Behavior",
        "BUTTON_LABEL": "Open Cost / Cortex",
        "DBA_MOVE": "Focus on spend spikes, Cortex growth, warehouse cost behavior, and user-driven spend anomalies.",
        "WHEN": "Cost anomaly, AI spend review, contract burn concern",
    },
    {
        "VIEW": "Reliability",
        "BUTTON_LABEL": "Open Reliability",
        "DBA_MOVE": "Focus on query, task, pipeline, procedure, copy/load, and freshness risk.",
        "WHEN": "Production incident, workload health, SLA review",
    },
    {
        "VIEW": "Security",
        "BUTTON_LABEL": "Open Security",
        "DBA_MOVE": "Focus on login, privilege, role, export, sharing, and access-control risk.",
        "WHEN": "Security triage, audit review, access anomaly",
    },
    {
        "VIEW": "Detection Catalog",
        "BUTTON_LABEL": "Open Detection Catalog",
        "DBA_MOVE": "Review Snowflake-native checks before enabling or tuning alert rules.",
        "WHEN": "Coverage review, audit, threshold tuning",
    },
    {
        "VIEW": "Delivery & Automation",
        "BUTTON_LABEL": "Open Automation",
        "DBA_MOVE": "Review delivery status, queue routing, suppression windows, and remediation log evidence.",
        "WHEN": "Notification audit, queue closure, remediation status, suppression cleanup",
    },
)

ALERT_CENTER_SOURCES_BY_PANE = {
    "Command Center": {"alerts", "action_queue", "delivery_log", "rules"},
    "Cost & Behavior": {"alerts", "action_queue", "rules"},
    "Reliability": {"alerts", "action_queue", "rules"},
    "Security": {"alerts", "action_queue", "rules"},
    "Detection Catalog": set(),
    "Delivery & Automation": {
        "alerts",
        "action_queue",
        "delivery_log",
        "rules",
        "native_registry",
        "remediation_policy",
        "remediation_dry_run",
    },
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
    "native_registry": {
        "SOURCE": "Native alert registry",
        "OBJECT": "Reviewed Snowflake ALERT candidates",
        "WHY": "Shows what native detections exist, are candidates, or are enabled",
        "COST_GUARDRAIL": "Small registry table read",
    },
    "remediation_policy": {
        "SOURCE": "Remediation policy",
        "OBJECT": "Review-only automation policy catalog",
        "WHY": "Shows whether any alert class is eligible for dry-run or auto mode",
        "COST_GUARDRAIL": "Small policy table read",
    },
    "remediation_dry_run": {
        "SOURCE": "Remediation dry-runs",
        "OBJECT": "Dry-run audit log",
        "WHY": "Shows proposed actions and blockers before any automation is allowed",
        "COST_GUARDRAIL": "Recent-window audit read",
    },
}


def _alert_email_target() -> str:
    from utils.alerts import current_alert_recipient

    return current_alert_recipient(DEFAULT_ALERT_EMAIL)


def _alert_email_target_label() -> str:
    from utils.alerts import alert_recipient_label

    return alert_recipient_label(_alert_email_target())


def _alert_center_sources_for_view(view: str) -> set[str]:
    return set(ALERT_CENTER_SOURCES_BY_PANE.get(_normalize_alert_center_view(view), {"alerts"}))


def _normalize_alert_center_view(view: object) -> str:
    normalized = str(view or "")
    aliases = {
        "Active Alerts": "Command Center",
        "Issue Inbox": "Command Center",
        "Triage Digest": "Command Center",
        "Alert History": "Command Center",
        "Alert Brief": "Command Center",
        "Control Health": "Command Center",
        "Cost": "Cost & Behavior",
        "Spend": "Cost & Behavior",
        "Cost / Cortex": "Cost & Behavior",
        "Cortex": "Cost & Behavior",
        "Workload": "Reliability",
        "Pipeline": "Reliability",
        "Email Delivery": "Delivery & Automation",
        "Action Queue Routing": "Delivery & Automation",
        "Delivery & Remediation": "Delivery & Automation",
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized in {"Alert Brief", "Control Health"}:
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
        load_alert_native_object_registry,
        load_alert_remediation_dry_runs,
        load_alert_remediation_policy,
        load_alert_rule_catalog,
    )

    sources = set(sources or ALERT_CENTER_SOURCES_BY_PANE[ALERT_CENTER_DEFAULT_VIEW])
    data: dict[str, object] = {
        "alerts": pd.DataFrame(),
        "action_queue": pd.DataFrame(),
        "issues": pd.DataFrame(),
        "delivery_log": pd.DataFrame(),
        "rules": pd.DataFrame(),
        "native_registry": pd.DataFrame(),
        "remediation_policy": pd.DataFrame(),
        "remediation_dry_run": pd.DataFrame(),
        "alerts_error": "",
        "queue_error": "",
        "delivery_error": "",
        "rule_error": "",
        "native_registry_error": "",
        "remediation_policy_error": "",
        "remediation_dry_run_error": "",
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
    if "native_registry" in sources:
        try:
            data["native_registry"] = load_alert_native_object_registry(section="Alert Center")
        except Exception as exc:
            data["native_registry_error"] = _format_snowflake_error(exc)
    if "remediation_policy" in sources:
        try:
            data["remediation_policy"] = load_alert_remediation_policy(section="Alert Center")
        except Exception as exc:
            data["remediation_policy_error"] = _format_snowflake_error(exc)
    if "remediation_dry_run" in sources:
        try:
            data["remediation_dry_run"] = load_alert_remediation_dry_runs(
                days=max(days, 14),
                limit=limit,
                section="Alert Center",
            )
        except Exception as exc:
            data["remediation_dry_run_error"] = _format_snowflake_error(exc)
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
        f"Default recipient {_alert_email_target_label()}; {ready_email:,} email-ready alert(s); {missing_email:,} missing target(s).",
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
                "primary_label": "Open Command Center",
                "target": ALERT_CENTER_DEFAULT_VIEW,
            }

    if overdue > 0:
        return {
            "state": "Escalate",
            "headline": "Escalate overdue alert rows first.",
            "detail": f"{overdue:,} overdue alert(s); {critical_high:,} critical/high open alert(s).",
            "primary_label": "Open Command Center",
            "target": ALERT_CENTER_DEFAULT_VIEW,
        }
    if critical_high > 0:
        return {
            "state": "Priority",
            "headline": "Review critical and high alert rows.",
            "detail": f"{critical_high:,} critical/high open alert(s) across {open_alerts:,} open alert(s).",
            "primary_label": "Open Command Center",
            "target": ALERT_CENTER_DEFAULT_VIEW,
        }
    if open_queue > 0:
        return {
            "state": "Queue",
            "headline": "Work open action queue rows.",
            "detail": f"{open_queue:,} open queue row(s) need route, ticket, due date, or closure status.",
            "primary_label": "Open Automation",
            "target": "Delivery & Automation",
        }
    if email_ready > email_logged:
        return {
            "state": "Telemetry",
            "headline": "Log alert delivery status.",
            "detail": f"{email_ready:,} email-ready alert(s); {email_logged:,} delivery row(s) logged in this scope.",
            "primary_label": "Open Delivery",
            "target": "Delivery & Automation",
        }
    if open_issues > 0:
        return {
            "state": "Triage",
            "headline": "Review the consolidated issue inbox.",
            "detail": f"{open_issues:,} issue row(s) are loaded from alert history and action queue telemetry.",
            "primary_label": "Open Command Center",
            "target": ALERT_CENTER_DEFAULT_VIEW,
        }
    return {
        "state": "Clear",
        "headline": "No immediate Alert Center move.",
        "detail": "Keep the selected window loaded for delivery status, routing, and rule telemetry when new alerts arrive.",
        "primary_label": "Open Command Center",
        "target": ALERT_CENTER_DEFAULT_VIEW,
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
                render_escaped_bold_text(row["VIEW"])
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


def _alert_operator_workflow_rows(
    *,
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    incident_board: pd.DataFrame,
    native_registry: pd.DataFrame | None = None,
    remediation_policy: pd.DataFrame | None = None,
    remediation_dry_run: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the operator workflow spine for the loaded Alert Center scope."""
    pd = _pd()
    alerts = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    queue = queue if isinstance(queue, pd.DataFrame) else pd.DataFrame()
    delivery_log = delivery_log if isinstance(delivery_log, pd.DataFrame) else pd.DataFrame()
    incident_board = incident_board if isinstance(incident_board, pd.DataFrame) else pd.DataFrame()
    native_registry = native_registry if isinstance(native_registry, pd.DataFrame) else pd.DataFrame()
    remediation_policy = remediation_policy if isinstance(remediation_policy, pd.DataFrame) else pd.DataFrame()
    remediation_dry_run = remediation_dry_run if isinstance(remediation_dry_run, pd.DataFrame) else pd.DataFrame()

    open_incidents = int(len(incident_board))
    severe = 0
    breached = 0
    route_needed = 0
    ticket_missing = 0
    if not incident_board.empty:
        severity = incident_board.get("SEVERITY", pd.Series(index=incident_board.index, dtype=str)).fillna("").astype(str)
        sla_state = incident_board.get("SLA_STATE", pd.Series(index=incident_board.index, dtype=str)).fillna("").astype(str).str.upper()
        severe = int(severity.isin(["Critical", "High"]).sum())
        breached = int(sla_state.isin(["BREACHED", "OVERDUE"]).sum())
        queue_state = incident_board.get("QUEUE_STATE", pd.Series(index=incident_board.index, dtype=str)).fillna("").astype(str)
        route_needed = int(queue_state.str.upper().str.contains("ROUTE TO ACTION QUEUE|NOT QUEUED", regex=True).sum())
        tickets = incident_board.get("TICKET_ID", pd.Series(index=incident_board.index, dtype=str)).fillna("").astype(str).str.strip()
        ticket_missing = int((tickets.eq("") & severity.isin(["Critical", "High"])).sum())

    email_ready = 0
    email_logged = 0
    if not alerts.empty and "DELIVERY_STATUS" in alerts.columns:
        delivery_status = alerts["DELIVERY_STATUS"].fillna("").astype(str).str.upper()
        email_ready = int(delivery_status.str.contains("EMAIL_READY", regex=False).sum())
        email_logged = int(delivery_status.str.contains("EMAIL_LOGGED", regex=False).sum())
    delivery_failed = 0
    if not delivery_log.empty and "DELIVERY_STATUS" in delivery_log.columns:
        delivery_failed = int(delivery_log["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("FAILED|ERROR|BOUNCED", regex=True).sum())
    delivery_gap = max(0, email_ready - email_logged) + delivery_failed

    native_candidates = 0
    if not native_registry.empty and "STATUS" in native_registry.columns:
        native_candidates = int(native_registry["STATUS"].fillna("CANDIDATE").astype(str).str.upper().isin({"CANDIDATE", "READY", "APPROVED", "READY_TO_DEPLOY"}).sum())
    policy_count = int(len(remediation_policy))
    dry_run_count = int(len(remediation_dry_run))

    queue_open = 0
    if not queue.empty and "STATUS" in queue.columns:
        queue_status = queue["STATUS"].fillna("New").astype(str).str.title()
        queue_open = int((~queue_status.isin(["Fixed", "Ignored", "Resolved", "Closed"])).sum())

    rows = [
        {
            "STEP": "1 Detect",
            "STATE": "Review" if open_incidents else "Clear",
            "COUNT": open_incidents,
            "WHAT_TO_CHECK": "Open incident rows in the loaded alert/action scope.",
            "NEXT_ACTION": "Work the highest-priority packet first." if open_incidents else "Keep the scope loaded for new events.",
            "OPERATOR_VIEW": "Command Center",
        },
        {
            "STEP": "2 Triage",
            "STATE": "Escalate" if breached else ("Priority" if severe else "Ready"),
            "COUNT": breached or severe,
            "WHAT_TO_CHECK": "SLA, severity, business impact, and source freshness.",
            "NEXT_ACTION": "Acknowledge breached or critical/high incidents before lower-risk rows." if (breached or severe) else "Review medium/low rows after queue and delivery are clean.",
            "OPERATOR_VIEW": "Next incident packet",
        },
        {
            "STEP": "3 Route",
            "STATE": "Review" if route_needed or ticket_missing else "Ready",
            "COUNT": max(route_needed, ticket_missing),
            "WHAT_TO_CHECK": "Named owner, action queue state, ticket/reference, and approval group.",
            "NEXT_ACTION": "Route rows without action queue or ticket context before escalation." if (route_needed or ticket_missing) else "Routes and references are ready for loaded incidents.",
            "OPERATOR_VIEW": "Delivery & Automation",
        },
        {
            "STEP": "4 Notify",
            "STATE": "Review" if delivery_gap else "Ready",
            "COUNT": delivery_gap,
            "WHAT_TO_CHECK": "Email-ready rows, delivery audit rows, and failed notification attempts.",
            "NEXT_ACTION": "Log digest delivery or investigate failed delivery attempts." if delivery_gap else "Delivery telemetry is current for the loaded scope.",
            "OPERATOR_VIEW": "Delivery & Automation",
        },
        {
            "STEP": "5 Dry-run",
            "STATE": "Candidate" if native_candidates or policy_count else "Not configured",
            "COUNT": native_candidates or policy_count,
            "WHAT_TO_CHECK": "Native alert candidates, remediation policy rows, and dry-run audit evidence.",
            "NEXT_ACTION": (
                "Stage or review dry-runs only; do not execute corrective SQL from Alert Center."
                if native_candidates or policy_count
                else "Load the automation pane after native alert deployment objects exist."
            ),
            "OPERATOR_VIEW": "Delivery & Automation",
        },
        {
            "STEP": "6 Close",
            "STATE": "Review" if queue_open else "Ready",
            "COUNT": queue_open,
            "WHAT_TO_CHECK": "Closure note, ticket/reference, post-fix telemetry, rollback status, and queue status.",
            "NEXT_ACTION": "Close only after evidence and route status are recorded." if queue_open else "No open queue rows need closure in this scope.",
            "OPERATOR_VIEW": "Command Center",
        },
    ]
    if dry_run_count:
        rows[4]["WHAT_TO_CHECK"] = f"{rows[4]['WHAT_TO_CHECK']} {dry_run_count:,} dry-run row(s) loaded."
    return pd.DataFrame(rows)


def _alert_next_incident_packet(incident_board: pd.DataFrame) -> pd.DataFrame:
    """Return the next incident as a small DBA decision packet."""
    pd = _pd()
    if incident_board is None or incident_board.empty:
        return pd.DataFrame(columns=["CHECKPOINT", "STATE", "DETAIL", "NEXT_ACTION"])
    top = incident_board.iloc[0]
    signal = str(top.get("SIGNAL") or top.get("CATEGORY") or "Alert")
    entity = str(top.get("ENTITY") or "Snowflake account")
    severity = str(top.get("SEVERITY") or "Medium")
    sla_state = str(top.get("SLA_STATE") or "On Track")
    remediation_mode = str(top.get("REMEDIATION_MODE") or "RECOMMEND")
    queue_state = str(top.get("QUEUE_STATE") or "Route to action queue")
    ticket = str(top.get("TICKET_ID") or "").strip()
    owner = str(top.get("OWNER") or "DBA").strip()
    route = str(top.get("ROUTE") or "Alert Center").strip()
    evidence_gap = str(top.get("EVIDENCE_GAP") or "Telemetry, route, and closure status required.")
    proof = str(top.get("PROOF_QUERY") or "Open source telemetry and record status.")
    return pd.DataFrame([
        {
            "CHECKPOINT": "What fired",
            "STATE": f"{severity} / {sla_state}",
            "DETAIL": f"{signal} on {entity}",
            "NEXT_ACTION": str(top.get("FIRST_RESPONSE") or "Acknowledge and triage the alert."),
        },
        {
            "CHECKPOINT": "Why it matters",
            "STATE": str(top.get("CATEGORY") or "Alert"),
            "DETAIL": str(top.get("BUSINESS_IMPACT") or "Business impact needs review."),
            "NEXT_ACTION": str(top.get("IMPACT_ESTIMATE") or "Attach impact estimate before closure."),
        },
        {
            "CHECKPOINT": "Owner and route",
            "STATE": "Ready" if owner.upper() not in {"", "DBA", "OVERWATCH"} and ticket else "Review",
            "DETAIL": f"Owner: {owner or 'DBA'} | Route: {route} | Ticket: {ticket or 'missing'}",
            "NEXT_ACTION": f"Queue state: {queue_state}. {evidence_gap}",
        },
        {
            "CHECKPOINT": "Evidence",
            "STATE": str(top.get("SOURCE_FRESHNESS") or "Loaded telemetry"),
            "DETAIL": proof,
            "NEXT_ACTION": "Use this evidence before escalation, suppression, or closure.",
        },
        {
            "CHECKPOINT": "Automation boundary",
            "STATE": remediation_mode,
            "DETAIL": str(top.get("APPROVAL_GROUP") or "DBA Review"),
            "NEXT_ACTION": "Dry-run/status review only unless a separately approved guarded workflow executes the change.",
        },
    ])


def _alert_domain_next_move_rows(board: pd.DataFrame, active_view: str) -> pd.DataFrame:
    """Return the first domain-lane move without requiring users to scan the full table."""
    pd = _pd()
    if board is None or board.empty:
        return pd.DataFrame(columns=["MOVE", "STATE", "DETAIL", "NEXT_ACTION"])
    top = board.iloc[0]
    destination = str(top.get("DESTINATION_SECTION") or "Alert Center")
    workflow = str(top.get("DESTINATION_WORKFLOW") or active_view)
    boundary = str(top.get("AUTOMATION_READINESS") or "Recommend only")
    guardrail = str(top.get("CORTEX_GUARDRAIL") or "").strip()
    return pd.DataFrame([
        {
            "MOVE": "Confirm signal",
            "STATE": str(top.get("SEVERITY") or "Review"),
            "DETAIL": f"{top.get('SIGNAL', 'Alert')} on {top.get('ENTITY', 'Snowflake account')}",
            "NEXT_ACTION": str(top.get("FIRST_RESPONSE") or "Acknowledge and review loaded telemetry."),
        },
        {
            "MOVE": "Open owner workflow",
            "STATE": destination,
            "DETAIL": f"{destination} > {workflow}",
            "NEXT_ACTION": str(top.get("DRILLDOWN_HINT") or top.get("OPEN_PATH") or "Open the owning monitoring section."),
        },
        {
            "MOVE": "Capture evidence",
            "STATE": str(top.get("SOURCE_FRESHNESS") or "Loaded telemetry"),
            "DETAIL": str(top.get("PROOF_QUERY") or "Open source telemetry and record status."),
            "NEXT_ACTION": "Attach proof before suppression, escalation, or closure.",
        },
        {
            "MOVE": "Respect boundary",
            "STATE": boundary,
            "DETAIL": guardrail or str(top.get("REMEDIATION_MODE") or "No automatic action from this alert row."),
            "NEXT_ACTION": "Use dry-run/status review only until the owning workflow approves execution.",
        },
    ])


def _alert_threshold_tuning_rows(alerts: pd.DataFrame | None = None, rules: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return alert threshold review rows grounded in the DBA-owned threshold catalog."""
    from utils.alerts import build_alert_threshold_seed_rows

    pd = _pd()
    alerts = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    rules = rules if isinstance(rules, pd.DataFrame) else pd.DataFrame()
    seeds = pd.DataFrame(build_alert_threshold_seed_rows())
    if seeds.empty:
        return pd.DataFrame(columns=[
            "REVIEW_STATE",
            "THRESHOLD_KEY",
            "CATEGORY",
            "SIGNAL_NAME",
            "CONFIGURED_THRESHOLD",
            "WINDOW",
            "RECENT_ALERTS",
            "OPEN_ALERTS",
            "OWNER",
            "SOURCE_OBJECT",
            "NEXT_ACTION",
        ])

    source_map = {
        "COST_CORTEX_SPEND_SPIKE": "FACT_CORTEX_DAILY",
        "COST_WAREHOUSE_CREDIT_SPIKE": "FACT_WAREHOUSE_HOURLY",
        "BEHAVIOR_USER_QUERY_ANOMALY": "FACT_QUERY_DETAIL_RECENT",
        "PERF_QUEUE_PRESSURE": "FACT_WAREHOUSE_HOURLY",
        "PIPELINE_TASK_FAILURE": "FACT_TASK_RUN",
        "SECURITY_PRIVILEGE_ESCALATION": "FACT_GRANT_DAILY",
        "SECURITY_FAILED_LOGIN_SPIKE": "FACT_LOGIN_DAILY",
        "DQ_FRESHNESS_SLA": "Configured data-quality checks",
        "OPT_UNUSED_WAREHOUSE": "FACT_WAREHOUSE_HOURLY",
    }

    searchable = pd.Series(dtype=str)
    if not alerts.empty:
        text_columns = [
            "ALERT_KEY",
            "RULE_ID",
            "ALERT_TYPE",
            "SIGNAL",
            "CATEGORY",
            "MESSAGE",
            "SUGGESTED_ACTION",
            "RECOMMENDED_ACTION",
            "EVIDENCE",
        ]
        pieces = []
        for column in text_columns:
            if column in alerts.columns:
                pieces.append(alerts[column].fillna("").astype(str))
        if pieces:
            searchable = pieces[0]
            for piece in pieces[1:]:
                searchable = searchable.str.cat(piece, sep=" ")
            searchable = searchable.str.upper()
        else:
            searchable = pd.Series([""] * len(alerts), index=alerts.index, dtype=str)

    rows: list[dict[str, object]] = []
    for _, seed in seeds.iterrows():
        key = str(seed.get("THRESHOLD_KEY") or "").upper()
        signal = str(seed.get("SIGNAL_NAME") or "").upper()
        matched = pd.DataFrame()
        if not alerts.empty and len(searchable):
            mask = searchable.str.contains(key, regex=False)
            if signal:
                mask = mask | searchable.str.contains(signal, regex=False)
            matched = alerts[mask]

        recent_alerts = int(len(matched))
        open_alerts = int(_open_alert_mask(matched).sum()) if not matched.empty else 0
        critical_high = 0
        if not matched.empty and "SEVERITY" in matched.columns:
            critical_high = int(matched["SEVERITY"].fillna("").astype(str).isin(["Critical", "High"]).sum())
        if recent_alerts == 0:
            state = "No Recent Signal"
            next_action = "Run the Snowflake alert operations review before changing this threshold."
        elif critical_high or open_alerts:
            state = "Tune With Evidence"
            next_action = "Compare current value, baseline, company split, and owner route before tuning."
        else:
            state = "Watch"
            next_action = "Keep the threshold until repeated closed/noise rows prove it needs tuning."

        rule_matches = pd.DataFrame()
        if not rules.empty:
            rule_text = pd.Series([""] * len(rules), index=rules.index, dtype=str)
            for column in ["RULE_ID", "ALERT_TYPE", "CATEGORY", "RUNBOOK"]:
                if column in rules.columns:
                    rule_text = rule_text.str.cat(rules[column].fillna("").astype(str), sep=" ")
            rule_matches = rules[rule_text.str.upper().str.contains(key, regex=False)]

        rows.append({
            "REVIEW_STATE": state,
            "THRESHOLD_KEY": key,
            "CATEGORY": seed.get("CATEGORY", ""),
            "SIGNAL_NAME": seed.get("SIGNAL_NAME", ""),
            "CONFIGURED_THRESHOLD": seed.get("THRESHOLD_VALUE", ""),
            "WINDOW": f"{int(seed.get('CURRENT_WINDOW_MINUTES') or 0)}m current / {int(seed.get('BASELINE_WINDOW_DAYS') or 0)}d baseline",
            "RECENT_ALERTS": recent_alerts,
            "OPEN_ALERTS": open_alerts,
            "OWNER": seed.get("OWNER", ""),
            "SOURCE_OBJECT": source_map.get(key, "Alert mart or configuration"),
            "RULE_ROWS": int(len(rule_matches)),
            "NEXT_ACTION": next_action,
        })

    rank = {"Tune With Evidence": 0, "Watch": 1, "No Recent Signal": 2}
    result = pd.DataFrame(rows)
    result["_RANK"] = result["REVIEW_STATE"].map(rank).fillna(9)
    return result.sort_values(["_RANK", "CATEGORY", "THRESHOLD_KEY"]).drop(columns=["_RANK"]).reset_index(drop=True)


def _alert_company_scope_readiness_rows(alerts: pd.DataFrame | None, queue: pd.DataFrame | None) -> pd.DataFrame:
    """Return company/environment quality rows for alert routing and ALFA/Trexis review."""
    pd = _pd()
    alerts = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    queue = queue if isinstance(queue, pd.DataFrame) else pd.DataFrame()

    def scope_row(source_name: str, frame: pd.DataFrame) -> dict[str, object]:
        if frame.empty:
            return {
                "SOURCE": source_name,
                "STATE": "No Rows",
                "ROWS": 0,
                "COMPANY_VALUES": "none",
                "MISSING_COMPANY": 0,
                "ENVIRONMENT_VALUES": "none",
                "MISSING_ENVIRONMENT": 0,
                "NEXT_ACTION": "Load recent telemetry before company-specific routing review.",
            }
        company_values = pd.Series([""] * len(frame), index=frame.index, dtype=str)
        if "COMPANY" in frame.columns:
            company_values = frame["COMPANY"].fillna("").astype(str).str.strip()
        env_values = pd.Series([""] * len(frame), index=frame.index, dtype=str)
        if "ENVIRONMENT" in frame.columns:
            env_values = frame["ENVIRONMENT"].fillna("").astype(str).str.strip()
        missing_company = int(company_values.eq("").sum()) if "COMPANY" in frame.columns else int(len(frame))
        missing_environment = int(env_values.eq("").sum()) if "ENVIRONMENT" in frame.columns else int(len(frame))
        company_display = ", ".join(sorted({value for value in company_values if value})[:6]) or "none"
        environment_display = ", ".join(sorted({value for value in env_values if value})[:6]) or "none"
        unclassified = int(company_values.str.upper().isin({"", "SHARED/UNCLASSIFIED", "ACCOUNT-WIDE", "NO COMPANY"}).sum())
        state = "Ready"
        next_action = "Company and environment scope is usable for route review."
        if "COMPANY" not in frame.columns:
            state = "Needs Company"
            next_action = "Add or load COMPANY before ALFA/Trexis-specific alert routing."
        elif missing_company or unclassified:
            state = "Review Scope"
            next_action = "Improve role/warehouse/company mapping before treating these rows as company-specific."
        elif "ENVIRONMENT" not in frame.columns or missing_environment:
            state = "Review Environment"
            next_action = "Add environment context where the source can provide it."
        return {
            "SOURCE": source_name,
            "STATE": state,
            "ROWS": int(len(frame)),
            "COMPANY_VALUES": company_display,
            "MISSING_COMPANY": missing_company,
            "ENVIRONMENT_VALUES": environment_display,
            "MISSING_ENVIRONMENT": missing_environment,
            "NEXT_ACTION": next_action,
        }

    rows = [
        scope_row("Alert events", alerts),
        scope_row("Action queue", queue),
    ]

    if not alerts.empty and "COMPANY" in alerts.columns:
        company_values = alerts["COMPANY"].fillna("").astype(str).str.upper()
        trexis_rows = int(company_values.eq("TREXIS").sum())
        alfa_rows = int(company_values.eq("ALFA").sum())
        rows.append({
            "SOURCE": "ALFA/Trexis split",
            "STATE": "Ready" if trexis_rows or alfa_rows else "Review Scope",
            "ROWS": int(len(alerts)),
            "COMPANY_VALUES": f"ALFA={alfa_rows:,}; Trexis={trexis_rows:,}",
            "MISSING_COMPANY": int(company_values.isin({"", "SHARED/UNCLASSIFIED", "ACCOUNT-WIDE"}).sum()),
            "ENVIRONMENT_VALUES": "Alert events",
            "MISSING_ENVIRONMENT": 0,
            "NEXT_ACTION": "Use TRXS-role and warehouse mapping to explain Trexis rows; keep shared rows out of company-specific actions.",
        })

    rank = {"Review Scope": 0, "Needs Company": 0, "Review Environment": 1, "No Rows": 2, "Ready": 3}
    result = pd.DataFrame(rows)
    result["_RANK"] = result["STATE"].map(rank).fillna(9)
    return result.sort_values(["_RANK", "SOURCE"]).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _alert_operations_review_rows(
    *,
    alerts: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
    native_registry: pd.DataFrame | None = None,
    remediation_policy: pd.DataFrame | None = None,
    remediation_dry_run: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the next implementation checks for native alerts and automation readiness."""
    pd = _pd()
    alerts = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    queue = queue if isinstance(queue, pd.DataFrame) else pd.DataFrame()
    native_registry = native_registry if isinstance(native_registry, pd.DataFrame) else pd.DataFrame()
    remediation_policy = remediation_policy if isinstance(remediation_policy, pd.DataFrame) else pd.DataFrame()
    remediation_dry_run = remediation_dry_run if isinstance(remediation_dry_run, pd.DataFrame) else pd.DataFrame()

    native_ready = 0
    native_blocked = 0
    native_candidates = int(len(native_registry))
    if not native_registry.empty:
        status = native_registry.get("STATUS", pd.Series(index=native_registry.index, dtype=str)).fillna("CANDIDATE").astype(str).str.upper()
        native_ready = int(status.isin({"APPROVED", "READY", "READY_TO_DEPLOY"}).sum())
        enabled = native_registry.get("ENABLED_BY_DEFAULT", pd.Series(False, index=native_registry.index)).fillna(False).astype(bool)
        native_blocked = int(enabled.sum())

    auto_eligible = 0
    if not remediation_policy.empty and "AUTO_ELIGIBLE" in remediation_policy.columns:
        auto_eligible = int(remediation_policy["AUTO_ELIGIBLE"].fillna(False).astype(bool).sum())

    scope_rows = _alert_company_scope_readiness_rows(alerts, queue)
    scope_review_count = 0
    if not scope_rows.empty:
        scope_review_count = int(scope_rows["STATE"].isin(["Review Scope", "Needs Company", "Review Environment"]).sum())

    rows = [
        {
            "REVIEW_AREA": "Native alert promotion",
            "STATE": "Blocked" if native_blocked else ("Ready Candidate" if native_ready else "Review"),
            "COUNT": native_blocked or native_ready or native_candidates,
            "EVIDENCE": f"{native_candidates:,} registry row(s), {native_ready:,} ready, {native_blocked:,} blocked by enabled-by-default.",
            "NEXT_ACTION": "Run snowflake/OVERWATCH_ALERT_OPERATIONS_REVIEW.sql before promoting any native alert.",
        },
        {
            "REVIEW_AREA": "Threshold tuning",
            "STATE": "Review",
            "COUNT": int(len(_alert_threshold_tuning_rows(alerts, None))),
            "EVIDENCE": "Threshold seeds are app-visible; real tuning needs current mart values and baselines.",
            "NEXT_ACTION": "Use the operations review script, then tune ALERT_THRESHOLDS with DBA approval.",
        },
        {
            "REVIEW_AREA": "Company scope",
            "STATE": "Review" if scope_review_count else "Ready",
            "COUNT": scope_review_count,
            "EVIDENCE": f"{scope_review_count:,} scope row(s) need review across alert/action sources.",
            "NEXT_ACTION": "Confirm ALFA/Trexis mapping before company-specific cost, Cortex, security, or behavior actions.",
        },
        {
            "REVIEW_AREA": "Dry-run automation",
            "STATE": "Blocked" if auto_eligible else ("Ready" if not remediation_policy.empty else "Review"),
            "COUNT": auto_eligible or int(len(remediation_dry_run)),
            "EVIDENCE": f"{len(remediation_policy):,} policy row(s), {auto_eligible:,} auto-eligible, {len(remediation_dry_run):,} dry-run row(s).",
            "NEXT_ACTION": "Keep auto actions disabled until before-state, rollback, verification, and owner approvals are proven.",
        },
        {
            "REVIEW_AREA": "Dynamic table compatibility",
            "STATE": "Manual Review",
            "COUNT": 1,
            "EVIDENCE": "Secure-view dependencies can break dynamic-table marts.",
            "NEXT_ACTION": "Run snowflake/OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql before any mart rebuild.",
        },
    ]
    rank = {"Blocked": 0, "Review": 1, "Manual Review": 2, "Ready Candidate": 3, "Ready": 4}
    result = pd.DataFrame(rows)
    result["_RANK"] = result["STATE"].map(rank).fillna(9)
    return result.sort_values(["_RANK", "REVIEW_AREA"]).drop(columns=["_RANK"]).reset_index(drop=True)


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
            ("Route", "Command"),
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


def _render_alert_command_lane_board(lanes: list[dict[str, str]]) -> None:
    pd = _pd()
    lane_rows = pd.DataFrame(lanes)
    if lane_rows.empty:
        return
    _render_priority_dataframe(
        lane_rows,
        title="Alert operating lanes",
        priority_columns=["label", "value", "state", "detail"],
        raw_label="All alert operating lanes",
        height=260,
        max_rows=8,
    )


def _render_alert_domain_workbench(
    active_view: str,
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    rules: pd.DataFrame,
) -> None:
    from utils.alerts import build_section_alert_signal_board
    from sections.navigation import apply_section_workflow_navigation

    pd = _pd()
    title_map = {
        "Cost & Behavior": "Cost, Cortex, and Behavior Alerts",
        "Reliability": "Reliability Alerts",
        "Security": "Security Alerts",
    }
    st.subheader(title_map.get(active_view, f"{active_view} Alerts"))
    board = build_section_alert_signal_board(alerts, queue, section=active_view, limit=30)
    if board.empty:
        st.success(f"No loaded {active_view.lower()} alert rows are open in this scope.")
    else:
        severity = board.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str)
        sla = board.get("SLA_STATE", pd.Series(dtype=str)).fillna("").astype(str)
        focus = board.get("SECTION_FOCUS", pd.Series(dtype=str)).fillna("").astype(str)
        render_shell_snapshot((
            ("Open Signals", f"{len(board):,}"),
            ("Critical / High", f"{int(severity.isin(['Critical', 'High']).sum()):,}"),
            ("Breached SLA", f"{int(sla.isin(['Breached', 'Overdue']).sum()):,}"),
            ("Spend / Cortex", f"{int(focus.isin(['Cortex spend', 'Spend spike', 'Cost movement']).sum()):,}"),
        ))
        top = board.iloc[0]
        render_shell_status_strip(
            state=str(top.get("SECTION_FOCUS") or "Review"),
            headline=f"First move: {top.get('SIGNAL', 'Alert')} on {top.get('ENTITY', 'Snowflake account')}",
            detail=str(top.get("DRILLDOWN_HINT") or top.get("FIRST_RESPONSE") or "Open the owning workflow and confirm evidence."),
        )
        next_moves = _alert_domain_next_move_rows(board, active_view)
        if not next_moves.empty:
            _render_priority_dataframe(
                next_moves,
                title=f"{active_view} first response path",
                priority_columns=["MOVE", "STATE", "DETAIL", "NEXT_ACTION"],
                raw_label=f"All {active_view} first response steps",
                height=220,
                max_rows=4,
            )
        _render_priority_dataframe(
            board,
            title=f"{active_view} alert workbench",
            priority_columns=[
                "SECTION_FOCUS", "PRIORITY", "SEVERITY", "SLA_STATE", "CATEGORY",
                "SIGNAL", "ENTITY", "OWNER", "ROUTE", "FIRST_RESPONSE",
                "RECOMMENDED_ACTION", "IMPACT_ESTIMATE", "SOURCE_FRESHNESS",
                "OPEN_PATH", "DRILLDOWN_HINT", "AUTOMATION_READINESS",
                "REMEDIATION_MODE", "QUEUE_STATE", "TICKET_ID",
            ],
            sort_by=["PRIORITY"],
            ascending=True,
            raw_label=f"All {active_view} alert rows",
            height=420,
            max_rows=15,
        )
        cols = st.columns(2)
        with cols[0]:
            if st.button("Open Owning Section", key=f"alert_domain_open_owner_{active_view}", width="stretch"):
                apply_section_workflow_navigation(
                    str(top.get("DESTINATION_SECTION") or "Alert Center"),
                    workflow=str(top.get("DESTINATION_WORKFLOW") or ""),
                    alert_center_view=str(top.get("ALERT_CENTER_VIEW") or active_view),
                )
                st.rerun()
        with cols[1]:
            if st.button("Open Command Center", key=f"alert_domain_open_command_{active_view}", width="stretch"):
                apply_section_workflow_navigation("Alert Center", alert_center_view="Command Center")
                st.rerun()

    if rules is not None and not rules.empty:
        rule_text = pd.Series([""] * len(rules), index=rules.index, dtype=str)
        for column in ["CATEGORY", "ALERT_TYPE", "RULE_ID", "ROUTE", "RUNBOOK"]:
            if column in rules.columns:
                rule_text = rule_text + " " + rules[column].fillna("").astype(str).str.upper()
        token_map = {
            "Cost & Behavior": "COST|SPEND|CORTEX|WAREHOUSE|OPTIMIZATION|CONTRACT|CHARGEBACK",
            "Reliability": "QUERY|TASK|PIPELINE|PROCEDURE|COPY|LOAD|PERFORMANCE|WAREHOUSE",
            "Security": "SECURITY|LOGIN|GRANT|PRIVILEGE|SHARE|ACCESS|EXPORT",
        }
        token_pattern = token_map.get(active_view, "")
        visible_rules = rules[rule_text.str.contains(token_pattern, regex=True)] if token_pattern else pd.DataFrame()
        if not visible_rules.empty:
            _render_priority_dataframe(
                visible_rules,
                title=f"{active_view} rule coverage",
                priority_columns=[
                    "RULE_ID", "CATEGORY", "ALERT_TYPE", "DEFAULT_SEVERITY",
                    "SLA_HOURS", "OWNER", "ROUTE", "RUNBOOK", "IS_ACTIVE",
                ],
                raw_label=f"All {active_view} alert rules",
                height=260,
                max_rows=10,
            )


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
        route: str = ALERT_CENTER_DEFAULT_VIEW,
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
            route=ALERT_CENTER_DEFAULT_VIEW,
        )
        if "SLA_STATE" in alerts.columns:
            sla_state = alerts["SLA_STATE"].fillna("").astype(str)
            add(
                "Overdue alert SLAs",
                "High",
                int((sla_state.eq("Overdue") & open_alerts).sum()),
                "Overdue",
                "Send overdue alert rows through the digest and confirm route response.",
                route=ALERT_CENTER_DEFAULT_VIEW,
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
            route="Delivery & Automation",
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
                route="Delivery & Automation",
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
            route=ALERT_CENTER_DEFAULT_VIEW,
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
            route="Delivery & Automation",
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
    st.subheader("Alert Command Center")
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
    workflow_rows = _alert_operator_workflow_rows(
        alerts=alerts,
        queue=queue,
        delivery_log=delivery_log,
        incident_board=incident_board,
    )
    _render_priority_dataframe(
        workflow_rows,
        title="Operator workflow",
        priority_columns=["STEP", "STATE", "COUNT", "WHAT_TO_CHECK", "NEXT_ACTION", "OPERATOR_VIEW"],
        raw_label="All alert operator workflow steps",
        height=260,
        max_rows=6,
    )
    if isinstance(incident_board, pd.DataFrame) and not incident_board.empty:
        top_incident = incident_board.iloc[0]
        render_shell_status_strip(
            state=f"{top_incident.get('SEVERITY', 'Review')} / {top_incident.get('SLA_STATE', 'On Track')}",
            headline=f"Work priority 1: {top_incident.get('SIGNAL', 'Alert')} on {top_incident.get('ENTITY', 'Snowflake account')}",
            detail=str(top_incident.get("FIRST_RESPONSE") or top_incident.get("RECOMMENDED_ACTION") or "Acknowledge, route, and capture evidence."),
        )
        packet = _alert_next_incident_packet(incident_board)
        if not packet.empty:
            _render_priority_dataframe(
                packet,
                title="Next incident packet",
                priority_columns=["CHECKPOINT", "STATE", "DETAIL", "NEXT_ACTION"],
                raw_label="All next incident packet fields",
                height=240,
                max_rows=5,
            )
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
    _render_loaded_advisor_alert_candidates()


def _render_loaded_advisor_alert_candidates() -> None:
    from utils import build_loaded_advisor_signal_board

    pd = _pd()
    advisor_rows = build_loaded_advisor_signal_board(st.session_state)
    if advisor_rows.empty:
        return
    view = advisor_rows.copy()
    if "SEVERITY" in view.columns:
        severity = view["SEVERITY"].fillna("").astype(str).str.title()
        view = view[severity.isin(["Critical", "High", "Medium"])]
    if view.empty:
        return
    high = int(view["SEVERITY"].astype(str).str.title().isin(["Critical", "High"]).sum())
    savings = 0.0
    risk = 0.0
    if "EST_MONTHLY_SAVINGS_USD" in view.columns:
        savings = float(pd.to_numeric(view["EST_MONTHLY_SAVINGS_USD"], errors="coerce").fillna(0).sum())
    if "VALUE_AT_RISK_USD" in view.columns:
        risk = float(pd.to_numeric(view["VALUE_AT_RISK_USD"], errors="coerce").fillna(0).sum())
    st.markdown("**Loaded Advisor Alert Candidates**")
    render_shell_snapshot((
        ("Candidates", f"{len(view):,}"),
        ("Critical / High", f"{high:,}"),
        ("Est. Savings / Mo", f"${savings:,.0f}"),
        ("Value At Risk", f"${risk:,.0f}"),
    ))
    _render_priority_dataframe(
        view,
        title="Advisor signals that may need alert routing",
        priority_columns=[
            "SOURCE_SURFACE", "SEVERITY", "SIGNAL", "ENTITY",
            "ROUTE", "NEXT_ACTION", "TELEMETRY_BASIS",
            "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD",
        ],
        sort_by=["PRIORITY_RANK", "VALUE_AT_RISK_USD", "EST_MONTHLY_SAVINGS_USD"],
        ascending=[True, False, False],
        raw_label="All advisor alert candidate rows",
        height=300,
        max_rows=12,
    )


def _render_alert_detection_catalog() -> None:
    from utils.alerts import (
        build_alert_native_deployment_review_rows,
        build_alert_native_object_registry_seed_rows,
        build_alert_signal_query_catalog,
        load_alert_native_object_registry,
    )

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
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Load Native Registry", key="alert_catalog_load_native_registry"):
            try:
                session = _alert_center_action_session("load native alert registry")
                if session is not None:
                    st.session_state["alert_native_registry_live"] = load_alert_native_object_registry(
                        section="Alert Center",
                    )
                    st.session_state["alert_native_registry_source"] = "Live registry table"
            except Exception as exc:
                st.info(f"Native alert registry is not available in this environment yet. {_format_snowflake_error(exc)}")
                st.session_state["alert_native_registry_live"] = _pd().DataFrame()
    with c2:
        st.caption("Native registry rows are disabled-by-default implementation candidates until reviewed and enabled in Snowflake.")

    live_native_rows = st.session_state.get("alert_native_registry_live")
    registry_source = st.session_state.get("alert_native_registry_source", "Built-in seed candidates")
    native_rows = live_native_rows if isinstance(live_native_rows, _pd().DataFrame) and not live_native_rows.empty else _pd().DataFrame(build_alert_native_object_registry_seed_rows())
    if not native_rows.empty:
        native_rows = native_rows.copy()
        if "REGISTRY_SOURCE" not in native_rows.columns:
            native_rows["REGISTRY_SOURCE"] = registry_source
    if not native_rows.empty:
        _render_priority_dataframe(
            native_rows,
            title="Native Snowflake alert implementation candidates",
            priority_columns=[
                "REGISTRY_SOURCE", "STATUS", "CATEGORY", "ALERT_KEY", "ALERT_OBJECT_NAME",
                "TARGET_ROUTE", "SCHEDULE_TEXT", "CONDITION_SOURCE",
                "ACTION_SOURCE", "SAFETY_NOTE",
            ],
            raw_label="All native alert registry candidates",
            height=260,
            max_rows=8,
        )
        deployment_rows = build_alert_native_deployment_review_rows(native_rows)
        _render_priority_dataframe(
            deployment_rows,
            title="Native alert deployment review",
            priority_columns=[
                "DEPLOYMENT_STATE", "CATEGORY", "ALERT_KEY", "ALERT_OBJECT_NAME",
                "TARGET_ROUTE", "WAREHOUSE_NAME", "SCHEDULE_TEXT",
                "DEPLOYMENT_SQL_PRESENT", "ROLLBACK_SQL_PRESENT",
                "DEPLOYMENT_NEXT_STEP", "VALIDATION_SQL",
            ],
            raw_label="All native alert deployment review fields",
            height=280,
            max_rows=8,
        )
    threshold_rows = _alert_threshold_tuning_rows()
    _render_priority_dataframe(
        threshold_rows,
        title="Threshold tuning review plan",
        priority_columns=[
            "REVIEW_STATE", "THRESHOLD_KEY", "CATEGORY", "SIGNAL_NAME",
            "CONFIGURED_THRESHOLD", "WINDOW", "OWNER", "SOURCE_OBJECT",
            "NEXT_ACTION",
        ],
        raw_label="All threshold tuning fields",
        height=300,
        max_rows=9,
    )
    operations_rows = _alert_operations_review_rows(native_registry=native_rows)
    _render_priority_dataframe(
        operations_rows,
        title="Native alert operations review checklist",
        priority_columns=["STATE", "REVIEW_AREA", "COUNT", "EVIDENCE", "NEXT_ACTION"],
        raw_label="All operations review checklist rows",
        height=240,
        max_rows=5,
    )
    defer_source_note("Run snowflake/OVERWATCH_ALERT_OPERATIONS_REVIEW.sql for live threshold, company-scope, and promotion evidence.")
    defer_source_note("Detection Catalog lists alert signals and required Snowflake telemetry.")


def _render_alert_email_delivery_status(alerts: pd.DataFrame, delivery_log: pd.DataFrame) -> None:
    pd = _pd()
    st.markdown("**Notification Queue**")
    defer_source_note(
        "Rows are email-ready by default once the Snowflake email integration is enabled."
    )
    if alerts.empty:
        st.info("No email-ready alert rows found.")
    else:
        email_view = alerts.copy()
        if "EMAIL_TARGET" not in email_view.columns:
            email_view["EMAIL_TARGET"] = _alert_email_target()
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

    st.markdown("**Delivery Audit**")
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


def _render_alert_action_queue_routing(alerts: pd.DataFrame, queue: pd.DataFrame, company: str) -> None:
    pd = _pd()
    st.markdown("**Route Alerts To Action Queue**")
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


def _render_alert_notification_remediation(
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    delivery_log: pd.DataFrame,
    rules: pd.DataFrame,
    company: str,
    native_registry: pd.DataFrame | None = None,
    remediation_policy: pd.DataFrame | None = None,
    remediation_dry_run: pd.DataFrame | None = None,
) -> None:
    from utils.alerts import build_alert_remediation_contract, build_alert_remediation_policy_seed_rows

    pd = _pd()
    native_registry = native_registry if isinstance(native_registry, pd.DataFrame) else pd.DataFrame()
    remediation_policy = remediation_policy if isinstance(remediation_policy, pd.DataFrame) else pd.DataFrame()
    remediation_dry_run = remediation_dry_run if isinstance(remediation_dry_run, pd.DataFrame) else pd.DataFrame()
    st.subheader("Delivery & Automation")
    enabled_native = 0
    candidate_native = 0
    if not native_registry.empty:
        enabled_native = int(native_registry.get("ENABLED_BY_DEFAULT", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
        candidate_native = int(native_registry.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().eq("CANDIDATE").sum())
    auto_policy = 0
    if not remediation_policy.empty:
        auto_policy = int(remediation_policy.get("AUTO_ELIGIBLE", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    controls = [
        {
            "CONTROL": "Alert inbox",
            "STATE": "Ready",
            "EVIDENCE": f"{len(alerts):,} alert row(s) loaded.",
            "NEXT_ACTION": "Use alert status, acknowledgement, suppression, and action-queue routing from Alert Center.",
            "ROUTE": ALERT_CENTER_DEFAULT_VIEW,
        },
        {
            "CONTROL": "Delivery status",
            "STATE": "Ready" if not delivery_log.empty else "Review",
            "EVIDENCE": f"{len(delivery_log):,} delivery audit row(s) loaded.",
            "NEXT_ACTION": "Log delivery status for open critical/high alerts.",
            "ROUTE": "Delivery & Automation",
        },
        {
            "CONTROL": "Action queue handoff",
            "STATE": "Ready" if not queue.empty else "Review",
            "EVIDENCE": f"{len(queue):,} action queue row(s) loaded.",
            "NEXT_ACTION": "Route open alerts to queue rows and confirm ticket, due date, and closure state.",
            "ROUTE": "Delivery & Automation",
        },
        {
            "CONTROL": "Rule catalog",
            "STATE": "Ready" if not rules.empty else "Fallback",
            "EVIDENCE": f"{len(rules):,} rules loaded.",
            "NEXT_ACTION": "Use rules as monitoring context; do not change thresholds from the alert view.",
            "ROUTE": "Detection Catalog",
        },
        {
            "CONTROL": "Native alert registry",
            "STATE": "Ready" if not native_registry.empty else "Review",
            "EVIDENCE": (
                f"{len(native_registry):,} native candidate row(s); {enabled_native:,} enabled by default; {candidate_native:,} candidate(s)."
                if not native_registry.empty else "Registry table not loaded or not deployed yet."
            ),
            "NEXT_ACTION": "Review generated CREATE ALERT SQL and enable only after owner, threshold, and warehouse are approved.",
            "ROUTE": "Detection Catalog",
        },
        {
            "CONTROL": "Remediation policy",
            "STATE": "Ready" if not remediation_policy.empty and auto_policy == 0 else "Review",
            "EVIDENCE": (
                f"{len(remediation_policy):,} policy row(s); {auto_policy:,} auto-eligible."
                if not remediation_policy.empty else "Policy table not loaded or not deployed yet."
            ),
            "NEXT_ACTION": "Keep AUTO_ELIGIBLE false until dry-run evidence and rollback checks are proven.",
            "ROUTE": "Delivery & Automation",
        },
        {
            "CONTROL": "Remediation dry-runs",
            "STATE": "Ready" if not remediation_dry_run.empty else "No Rows",
            "EVIDENCE": f"{len(remediation_dry_run):,} recent dry-run row(s) loaded.",
            "NEXT_ACTION": "Use dry-runs to prove before-state, proposed action, blocker, and verification SQL before any future automation.",
            "ROUTE": "Delivery & Automation",
        },
    ]
    _render_priority_dataframe(
        pd.DataFrame(controls),
        title="Delivery and remediation status",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "ROUTE"],
        raw_label="All delivery and remediation rows",
        height=260,
    )
    operations_rows = _alert_operations_review_rows(
        alerts=alerts,
        queue=queue,
        native_registry=native_registry,
        remediation_policy=remediation_policy,
        remediation_dry_run=remediation_dry_run,
    )
    _render_priority_dataframe(
        operations_rows,
        title="Alert operations readiness",
        priority_columns=["STATE", "REVIEW_AREA", "COUNT", "EVIDENCE", "NEXT_ACTION"],
        raw_label="All alert operations readiness rows",
        height=240,
        max_rows=5,
    )
    threshold_rows = _alert_threshold_tuning_rows(alerts, rules)
    _render_priority_dataframe(
        threshold_rows,
        title="Threshold tuning from loaded alerts",
        priority_columns=[
            "REVIEW_STATE", "THRESHOLD_KEY", "CATEGORY", "SIGNAL_NAME",
            "CONFIGURED_THRESHOLD", "WINDOW", "RECENT_ALERTS", "OPEN_ALERTS",
            "OWNER", "SOURCE_OBJECT", "NEXT_ACTION",
        ],
        raw_label="All loaded threshold tuning rows",
        height=300,
        max_rows=9,
    )
    scope_rows = _alert_company_scope_readiness_rows(alerts, queue)
    _render_priority_dataframe(
        scope_rows,
        title="Company scope readiness",
        priority_columns=[
            "STATE", "SOURCE", "ROWS", "COMPANY_VALUES", "MISSING_COMPANY",
            "ENVIRONMENT_VALUES", "MISSING_ENVIRONMENT", "NEXT_ACTION",
        ],
        raw_label="All company scope readiness rows",
        height=260,
        max_rows=6,
    )
    if alerts.empty:
        st.info("Load alert history to review remediation status for real alert rows.")
    else:
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
    policy_rows = remediation_policy.copy() if not remediation_policy.empty else pd.DataFrame(build_alert_remediation_policy_seed_rows())
    if not policy_rows.empty:
        if "POLICY_SOURCE" not in policy_rows.columns:
            policy_rows["POLICY_SOURCE"] = "Live policy table" if not remediation_policy.empty else "Built-in seed policy"
        _render_priority_dataframe(
            policy_rows,
            title="Remediation policy matrix",
            priority_columns=[
                "POLICY_SOURCE", "REMEDIATION_MODE", "AUTO_ELIGIBLE", "CATEGORY", "ALERT_KEY",
                "ACTION_TYPE", "REQUIRED_REVIEW", "ROLLBACK_GUIDANCE",
                "VERIFICATION_SQL",
            ],
            raw_label="All remediation policy rows",
            height=300,
            max_rows=8,
        )
    if not native_registry.empty:
        _render_priority_dataframe(
            native_registry,
            title="Native alert deployment status",
            priority_columns=[
                "STATUS", "ENABLED_BY_DEFAULT", "CATEGORY", "ALERT_KEY",
                "ALERT_OBJECT_NAME", "TARGET_ROUTE", "WAREHOUSE_NAME",
                "SCHEDULE_TEXT", "SAFETY_NOTE",
            ],
            raw_label="All native alert registry rows",
            height=260,
            max_rows=8,
        )
    if not remediation_dry_run.empty:
        _render_priority_dataframe(
            remediation_dry_run,
            title="Recent remediation dry-runs",
            priority_columns=[
                "CREATED_AT", "DRY_RUN_STATUS", "POLICY_ID", "ALERT_KEY",
                "EXPECTED_EFFECT", "BLOCKING_REASON", "VERIFICATION_SQL",
            ],
            sort_by=["CREATED_AT"],
            ascending=False,
            raw_label="All remediation dry-run rows",
            height=260,
            max_rows=10,
        )
    _render_alert_email_delivery_status(alerts, delivery_log)
    _render_alert_action_queue_routing(alerts, queue, company)


def _render_operational_ownership_coverage(company: str, environment: str) -> None:
    from utils import load_ownership_coverage_rollup

    pd = _pd()
    coverage = load_ownership_coverage_rollup(
        company,
        environment,
        surface="Alert Center",
        days=35,
    )
    if coverage is None or getattr(coverage, "empty", True):
        st.caption("Operational ownership coverage is pending. Refresh the enterprise operating model mart to show alert route gaps.")
        return
    total = int(pd.to_numeric(coverage.get("TOTAL_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    gaps = int(pd.to_numeric(coverage.get("GAP_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    routed = int(pd.to_numeric(coverage.get("ROUTED_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    st.markdown("**Operational Ownership Coverage**")
    render_shell_snapshot((
        ("Alert Items", f"{total:,}"),
        ("Routed", f"{routed:,}"),
        ("Gaps", f"{gaps:,}"),
    ))
    view = coverage[[
        column for column in [
            "ENTITY_TYPE", "TOTAL_ITEMS", "ROUTED_ITEMS", "GAP_ITEMS",
            "COVERAGE_PCT", "TRUST_LEVEL", "CONFIDENCE", "TOP_GAP_ENTITY",
            "ROUTE", "NEXT_ACTION",
        ]
        if column in coverage.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)


def _render_operational_risk_score_explanation(company: str, environment: str) -> None:
    """Expose Operational Risk Score drivers behind an explicit Load action."""
    from utils import load_executive_scorecard_detail

    pd = _pd()
    st.markdown("**Operational Risk Score**")
    st.caption("Loads alert/action ownership risk drivers from the Executive Scorecard history.")
    if st.button("Load Operational Risk Score Drivers", key="alert_center_load_operational_score_drivers", width="stretch"):
        st.session_state["alert_center_operational_score_detail"] = load_executive_scorecard_detail(
            company,
            environment,
            score_key="OPERATIONAL_RISK",
            days=180,
        )
        st.session_state["alert_center_operational_score_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_operational_score_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_operational_score_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No Operational Risk Score driver rows are available for this scope yet.")
            return
        latest = detail.iloc[0]
        score = float(pd.to_numeric(pd.Series([latest.get("CURRENT_SCORE")]), errors="coerce").fillna(0).iloc[0])
        render_shell_snapshot((
            ("Score", f"{score:.0f}/100"),
            ("Status", str(latest.get("STATUS") or "Unknown")),
            ("Trend", str(latest.get("TREND") or "Stable")),
            ("Owner", str(latest.get("OWNER_ROUTE") or "Owner gap")),
        ))
        _render_priority_dataframe(
            detail,
            title="Operational Risk Score drivers",
            priority_columns=[
                "SNAPSHOT_TS", "CURRENT_SCORE", "STATUS", "TREND", "TOP_DRIVER",
                "RECOMMENDED_ACTION", "OWNER_ROUTE", "OWNER_GAP",
                "CONFIDENCE", "SOURCE_OBJECTS", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS"],
            ascending=False,
            raw_label="All operational risk score history rows",
            height=260,
            max_rows=8,
        )


def _render_alert_change_context(company: str, environment: str) -> None:
    """Show change correlations near Alert Center context without claiming causality."""
    from utils import load_change_correlation_detail

    pd = _pd()
    st.markdown("**Related Changes**")
    st.caption("Loads possible change correlations for alert, cost, security, and workload signals.")
    if st.button("Load Related Changes", key="alert_center_load_related_changes", width="stretch"):
        st.session_state["alert_center_change_correlation_detail"] = load_change_correlation_detail(
            company,
            environment,
            correlation_types=("Alert", "Cost", "Security", "Workload"),
            days=180,
        )
        st.session_state["alert_center_change_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_change_correlation_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_change_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No related change correlations are available for this scope yet.")
            return
        render_shell_snapshot((
            ("Possible Links", f"{len(detail):,}"),
            ("High Risk", f"{int(pd.Series(detail.get('RISK_LEVEL', [])).astype(str).isin(['Critical', 'High']).sum()):,}"),
            ("Signals", f"{int(pd.Series(detail.get('RELATED_SIGNAL', [])).dropna().nunique()):,}"),
        ))
        _render_priority_dataframe(
            detail,
            title="Related changes and possible correlations",
            priority_columns=[
                "RELATED_TS", "CORRELATION_TYPE", "CHANGE_TYPE", "OBJECT_TYPE",
                "OBJECT_NAME", "CHANGED_BY", "RELATED_SIGNAL", "RELATED_ENTITY",
                "CORRELATION_LABEL", "RISK_LEVEL", "BUSINESS_IMPACT",
                "OWNER_ROUTE", "CONFIDENCE", "EVIDENCE",
            ],
            sort_by=["RELATED_TS", "CHANGE_TS"],
            ascending=False,
            raw_label="All related change correlation rows",
            height=320,
            max_rows=12,
        )
        st.caption("These rows are timing and entity matches only. Treat them as possible correlations until evidence proves causality.")


def _render_alert_action_workflows(company: str, environment: str) -> None:
    """Show alert/incident action workflows only after the operator loads them."""
    from utils import load_closed_loop_workflow_detail

    pd = _pd()
    st.markdown("**Alert Action Workflows**")
    st.caption(
        "Loads action workflows tied to alert and incident context. "
        "Recommended SQL/action text remains review-gated and is not executed from Alert Center."
    )
    domains = ("Alert", "Cost", "Operations", "Security", "Workload")
    if st.button("Load Alert Action Workflows", key="alert_center_load_closed_loop_workflows", width="stretch"):
        st.session_state["alert_center_closed_loop_workflows"] = load_closed_loop_workflow_detail(
            company,
            environment,
            domains=domains,
            days=180,
        )
        st.session_state["alert_center_closed_loop_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_closed_loop_workflows")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_closed_loop_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No alert action workflows are available for this scope yet.")
            return
        status = detail.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        approval = detail.get("APPROVAL_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        actual = pd.to_numeric(detail.get("ACTUAL_VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        render_shell_snapshot((
            ("Actions", f"{len(detail):,}"),
            ("Need Approval", f"{int((~approval.isin(['Approved', 'Not Required'])).sum()):,}"),
            ("Verify", f"{int((~status.isin(['Verified', 'Closed'])).sum()):,}"),
            ("Verified Value", f"${float(actual.sum()):,.0f}"),
        ))
        _render_priority_dataframe(
            detail,
            title="Alert and incident action workflows",
            priority_columns=[
                "ACTION_DOMAIN", "FINDING", "SOURCE_TELEMETRY", "ENTITY_TYPE",
                "ENTITY_NAME", "RISK_LEVEL", "OWNER_ROUTE", "APPROVAL_STATUS",
                "EXECUTION_MODE", "VERIFICATION_STATUS", "EXPECTED_SAVINGS_USD",
                "ACTUAL_VERIFIED_SAVINGS_USD", "RECOMMENDED_ACTION",
                "LAST_REFRESHED_TS",
            ],
            sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
            ascending=[True, False],
            raw_label="All alert closed-loop workflow rows",
            height=320,
            max_rows=12,
        )


def _render_alert_command_findings(company: str, environment: str) -> None:
    """Show related Command Center findings for alert and incident context."""
    from utils import load_command_center_finding_detail, load_command_center_recommendation_detail

    pd = _pd()
    st.markdown("**Alert Command Findings**")
    st.caption(
        "Loads command findings tied to alerts, failures, cost, security, workload, and possible change correlations. "
        "Recommendations remain review-gated."
    )
    types = ("Failure / SLA", "Cost Spike", "Warehouse Slow", "Security Risk", "Recent Change")
    if st.button("Load Alert Command Findings", key="alert_center_load_command_findings", width="stretch"):
        st.session_state["alert_center_command_findings"] = load_command_center_finding_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["alert_center_command_recommendations"] = load_command_center_recommendation_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["alert_center_command_scope"] = (company, environment)

    if st.session_state.get("alert_center_command_scope") != (company, environment):
        return
    findings = st.session_state.get("alert_center_command_findings")
    recommendations = st.session_state.get("alert_center_command_recommendations")
    if isinstance(findings, pd.DataFrame):
        if findings.empty:
            st.info("No alert-related Command Center findings are available for this scope yet.")
        else:
            _render_priority_dataframe(
                findings,
                title="Alert-related root-cause candidates",
                priority_columns=[
                    "INVESTIGATION_TYPE", "QUESTION_TEXT", "ROOT_CAUSE_CANDIDATE",
                    "CAUSALITY_LABEL", "EVIDENCE_SUMMARY", "CONFIDENCE",
                    "OWNER_ROUTE", "RELATED_CHANGES", "RELATED_ALERTS",
                    "RELATED_SCORECARD_DRIVERS", "RELATED_FORECASTS",
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "EXECUTION_PLAN_REF",
                    "VERIFICATION_PATH", "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
                ascending=[True, False],
                raw_label="All alert command findings",
                height=320,
                max_rows=10,
            )
    if isinstance(recommendations, pd.DataFrame) and not recommendations.empty:
        _render_priority_dataframe(
            recommendations,
            title="Alert command recommendations",
            priority_columns=[
                "INVESTIGATION_TYPE", "RECOMMENDED_ACTION", "RISK_LEVEL",
                "OWNER_ROUTE", "EXECUTION_PLAN_REF", "REVIEW_REQUIRED",
                "VERIFICATION_PATH", "SAFETY_NOTE", "LAST_REFRESHED_TS",
            ],
            sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
            ascending=[True, False],
            raw_label="All alert command recommendations",
            height=260,
            max_rows=8,
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
    with st.expander("Advanced alert diagnostics and enterprise evidence", expanded=False):
        _render_operational_ownership_coverage(company, environment)
        _render_operational_risk_score_explanation(company, environment)
        _render_alert_change_context(company, environment)
        _render_alert_action_workflows(company, environment)
        _render_alert_command_findings(company, environment)

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
        _render_alert_command_lane_board(_alert_command_lanes(active_view=active_view, required_sources=required_sources))
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
        _render_alert_command_lane_board(_alert_command_lanes(active_view=active_view, required_sources=required_sources))
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
        _render_alert_command_lane_board(_alert_command_lanes(active_view=active_view, required_sources=required_sources))
        st.info(f"Load {active_view} to fetch missing input(s).")
        defer_source_note(f"Missing Alert Center input(s): {_alert_center_source_summary(set(missing_sources))}")
        return

    pd = _pd()
    alerts = data.get("alerts") if isinstance(data.get("alerts"), pd.DataFrame) else pd.DataFrame()
    queue = data.get("action_queue") if isinstance(data.get("action_queue"), pd.DataFrame) else pd.DataFrame()
    issues = data.get("issues") if isinstance(data.get("issues"), pd.DataFrame) else pd.DataFrame()
    delivery_log = data.get("delivery_log") if isinstance(data.get("delivery_log"), pd.DataFrame) else pd.DataFrame()
    rules = data.get("rules") if isinstance(data.get("rules"), pd.DataFrame) else pd.DataFrame()
    native_registry = data.get("native_registry") if isinstance(data.get("native_registry"), pd.DataFrame) else pd.DataFrame()
    remediation_policy = data.get("remediation_policy") if isinstance(data.get("remediation_policy"), pd.DataFrame) else pd.DataFrame()
    remediation_dry_run = data.get("remediation_dry_run") if isinstance(data.get("remediation_dry_run"), pd.DataFrame) else pd.DataFrame()
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
    if data.get("native_registry_error"):
        defer_source_note("Native alert registry is not available in this environment yet.", data["native_registry_error"])
    if data.get("remediation_policy_error"):
        defer_source_note("Remediation policy catalog is not available in this environment yet.", data["remediation_policy_error"])
    if data.get("remediation_dry_run_error"):
        defer_source_note("Remediation dry-run audit is not available in this environment yet.", data["remediation_dry_run_error"])
    defer_source_note(f"Loaded {data.get('loaded_at', '')}. Email target defaults to {_alert_email_target_label()}.")

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
    _render_alert_command_lane_board(
        _alert_command_lanes(
            active_view=active_view,
            required_sources=required_sources,
            alerts=alerts,
            queue=queue,
            issues=issues,
            delivery_log=delivery_log,
            loaded=True,
        )
    )
    _render_alert_center_exception_strip(exception_rows)

    if active_view == ALERT_CENTER_DEFAULT_VIEW:
        _render_active_alerts(alerts, queue, delivery_log, rules)

    elif active_view in {"Cost & Behavior", "Reliability", "Security"}:
        _render_alert_domain_workbench(active_view, alerts, queue, rules)

    elif active_view == "Delivery & Automation":
        _render_alert_notification_remediation(
            alerts,
            queue,
            delivery_log,
            rules,
            company,
            native_registry=native_registry,
            remediation_policy=remediation_policy,
            remediation_dry_run=remediation_dry_run,
        )

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
