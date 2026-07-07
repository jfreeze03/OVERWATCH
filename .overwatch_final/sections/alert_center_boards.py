"""Pure Alert Center board and model helpers."""

from __future__ import annotations

import pandas as pd

from config import DEFAULT_ALERT_EMAIL
from sections.alert_center_contracts import ALERT_CENTER_DEFAULT_VIEW


def _status_key(value) -> str:
    return str(value or "New").strip().upper().replace(" ", "_")


def _alert_open_statuses() -> set[str]:
    from utils import ALERT_OPEN_STATUSES

    return ALERT_OPEN_STATUSES


def _alert_email_target() -> str:
    from utils.alert_delivery import current_alert_recipient

    return current_alert_recipient(DEFAULT_ALERT_EMAIL)


def _alert_email_target_label() -> str:
    from utils.alert_delivery import alert_recipient_label

    return alert_recipient_label(_alert_email_target())


def _open_alert_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    if "STATUS" not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    return df["STATUS"].apply(_status_key).isin(_alert_open_statuses())


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
                "primary_label": "Open Active Alerts",
                "target": ALERT_CENTER_DEFAULT_VIEW,
            }

    if overdue > 0:
        return {
            "state": "Escalate",
            "headline": "Escalate overdue alert rows first.",
            "detail": f"{overdue:,} overdue alert(s); {critical_high:,} critical/high open alert(s).",
            "primary_label": "Open Active Alerts",
            "target": ALERT_CENTER_DEFAULT_VIEW,
        }
    if critical_high > 0:
        return {
            "state": "Priority",
            "headline": "Review critical and high alert rows.",
            "detail": f"{critical_high:,} critical/high open alert(s) across {open_alerts:,} open alert(s).",
            "primary_label": "Open Active Alerts",
            "target": ALERT_CENTER_DEFAULT_VIEW,
        }
    if open_queue > 0:
        return {
            "state": "Queue",
            "headline": "Work open action queue rows.",
            "detail": f"{open_queue:,} open queue row(s) need route, ticket, due date, or closure status.",
            "primary_label": "Open Alert Settings",
            "target": "Alert Settings / Admin",
        }
    if email_ready > email_logged:
        return {
            "state": "Telemetry",
            "headline": "Log alert delivery status.",
            "detail": f"{email_ready:,} email-ready alert(s); {email_logged:,} delivery row(s) logged in this scope.",
            "primary_label": "Open Alert Settings",
            "target": "Alert Settings / Admin",
        }
    if open_issues > 0:
        return {
            "state": "Triage",
            "headline": "Review the consolidated issue inbox.",
            "detail": f"{open_issues:,} issue row(s) are loaded from alert history and action queue telemetry.",
            "primary_label": "Open Active Alerts",
            "target": ALERT_CENTER_DEFAULT_VIEW,
        }
    return {
        "state": "Clear",
        "headline": "No immediate Alert Center move.",
        "detail": "Keep the selected window loaded for delivery status, routing, and rule telemetry when new alerts arrive.",
        "primary_label": "Open Active Alerts",
        "target": ALERT_CENTER_DEFAULT_VIEW,
    }


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
            "OPERATOR_VIEW": "Active Alerts",
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
            "WHAT_TO_CHECK": "Named workflow, action queue state, ticket/reference, and review group.",
            "NEXT_ACTION": "Route rows without action queue or ticket context before escalation." if (route_needed or ticket_missing) else "Routes and references are ready for loaded incidents.",
            "OPERATOR_VIEW": "Alert Settings / Admin",
        },
        {
            "STEP": "4 Notify",
            "STATE": "Review" if delivery_gap else "Ready",
            "COUNT": delivery_gap,
            "WHAT_TO_CHECK": "Email-ready rows, delivery audit rows, and failed notification attempts.",
            "NEXT_ACTION": "Log digest delivery or investigate failed delivery attempts." if delivery_gap else "Delivery telemetry is current for the loaded scope.",
            "OPERATOR_VIEW": "Alert Settings / Admin",
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
            "OPERATOR_VIEW": "Alert Settings / Admin",
        },
        {
            "STEP": "6 Close",
            "STATE": "Review" if queue_open else "Ready",
            "COUNT": queue_open,
            "WHAT_TO_CHECK": "Closure note, ticket/reference, post-fix telemetry, rollback status, and queue status.",
            "NEXT_ACTION": "Close only after evidence and route status are recorded." if queue_open else "No open queue rows need closure in this scope.",
            "OPERATOR_VIEW": "Active Alerts",
        },
    ]
    if dry_run_count:
        rows[4]["WHAT_TO_CHECK"] = f"{rows[4]['WHAT_TO_CHECK']} {dry_run_count:,} dry-run row(s) loaded."
    return pd.DataFrame(rows)


def _alert_next_incident_packet(incident_board: pd.DataFrame) -> pd.DataFrame:
    """Return the next incident as a small DBA decision packet."""
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
            "CHECKPOINT": "Workflow and route",
            "STATE": "Ready" if owner.upper() not in {"", "DBA", "OVERWATCH"} and ticket else "Review",
            "DETAIL": f"Workflow: {owner or 'DBA'} | Route: {route} | Ticket: {ticket or 'missing'}",
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
            "DETAIL": str(top.get("REVIEW_STATUS") or "DBA Review"),
            "NEXT_ACTION": "Dry-run/status review only unless a separately approved guarded workflow executes the change.",
        },
    ])


def _alert_domain_next_move_rows(board: pd.DataFrame, active_view: str) -> pd.DataFrame:
    """Return the first domain-lane move without requiring users to scan the full table."""
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
            "MOVE": "Open workflow",
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
    from utils.alert_native_catalog import build_alert_threshold_seed_rows

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
            next_action = "Compare current value, baseline, company split, and workflow route before tuning."
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
            "NEXT_ACTION": "Keep auto actions disabled until before-state, rollback, verification, and review statuss are proven.",
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


def _alert_center_exception_rows(
    *,
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    issues: pd.DataFrame,
    delivery_log: pd.DataFrame,
    readiness_rows: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict] = []

    def add(
        signal: str,
        severity: str,
        count: int,
        state: str,
        next_action: str,
        owner: str = "DBA Review",
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
            route="Alert Settings / Admin",
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
                route="Alert Settings / Admin",
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
            owner="DBA Review",
            route="Alert Settings / Admin",
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    severity_rank = {"High": 0, "Medium": 1, "Low": 2}
    result["_SORT"] = result["SEVERITY"].map(severity_rank).fillna(9)
    result = result.sort_values(["_SORT", "COUNT", "SIGNAL"], ascending=[True, False, True])
    return result.drop(columns=["_SORT"]).reset_index(drop=True)


def _alert_workflow_route_board(alerts: pd.DataFrame, queue: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    generic_owners = {
        "",
        "DBA",
        "OVERWATCH",
        "DBA / COST ATTRIBUTION",
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
                "REVIEWED_BY": row.get("REVIEWED_BY", ""),
                "WORKFLOW_ROUTE": row.get("WORKFLOW_ROUTE", ""),
                "ALLOCATION_SOURCE": row.get("ALLOCATION_SOURCE", ""),
                "WORKFLOW_ROUTE_STATE": "Needs named route" if owner_key in generic_owners else "Named route",
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
            email_target = str(row.get("EMAIL_TARGET") or row.get("EMAIL_TARGET") or row.get("EMAIL_TARGET") or "").strip()
            rows.append({
                "ISSUE_SOURCE": "Action Queue",
                "SEVERITY": row.get("SEVERITY", ""),
                "STATUS": row.get("STATUS", "New"),
                "CATEGORY": row.get("CATEGORY", ""),
                "ENTITY": row.get("ENTITY_NAME", row.get("ENTITY", "")),
                "OWNER": owner or "DBA",
                "EMAIL_TARGET": email_target,
                "REVIEWED_BY": row.get("REVIEWED_BY", ""),
                "WORKFLOW_ROUTE": row.get("WORKFLOW_ROUTE", ""),
                "ALLOCATION_SOURCE": row.get("ALLOCATION_SOURCE", ""),
                "WORKFLOW_ROUTE_STATE": "Needs named route" if owner_key in generic_owners else "Named route",
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
            "review_pct": 100.0,
            "route_gaps": 0,
        }, board

    owner_ready = board["WORKFLOW_ROUTE_STATE"].astype(str).eq("Named route")
    email_ready = ~board["DELIVERY_ROUTE_STATE"].astype(str).str.startswith("Missing")
    review_ready = board["REVIEWED_BY"].fillna("").astype(str).str.strip().ne("")
    route_gap = (
        board["WORKFLOW_ROUTE_STATE"].astype(str).ne("Named route")
        | ~email_ready
        | ~review_ready
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
        "review_pct": round(float(review_ready.sum()) / total * 100, 1),
        "route_gaps": int(route_gap.sum()),
    }, board.reset_index(drop=True)


def _alert_lifecycle_board(alerts: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
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
            "WORKFLOW_ROUTE": row.get("WORKFLOW_ROUTE", ""),
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
        "OWNER": "DBA Review",
    })
    rows.append({
        "CONTROL": "Snowflake notification integration",
        "STATE": "Review",
        "EVIDENCE": "Email-first delivery uses configured recipients until a Snowflake notification integration exists.",
        "NEXT_ACTION": "Create email/notification integration and configure production distribution lists.",
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
        "OWNER": "DBA Review",
    })
    rows.append({
        "CONTROL": "Open alert lifecycle",
        "STATE": "Ready" if open_alert_count == 0 else "Review",
        "EVIDENCE": f"{open_alert_count:,} open alert(s) in the loaded scope.",
        "NEXT_ACTION": "Every open alert needs route, notes, delivery status, action queue state, and closure status.",
        "OWNER": "DBA Review",
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
