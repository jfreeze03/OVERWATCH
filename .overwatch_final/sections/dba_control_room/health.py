"""Source-health, scope/meta, evidence freshness, and release-readiness helpers."""
from __future__ import annotations

import streamlit as st
from sections.shell_helpers import (
    render_shell_snapshot,
)
from utils.primitives import (
    safe_float,
    safe_int,
)
from .types import (
    DBA_CONTROL_SCOPE_FILTER_KEYS,
    _empty_df,
    _frame_or_empty,
    _gate_state_from_counts,
    _jump,
    _row_value,
    _snapshot_metric,
    pd,
)
from .types import (
    download_csv,
    render_priority_dataframe,
)
from .types import pd

def _dba_control_ops_scope_key(
    company: str,
    environment: str,
    lookback_hours: int,
    cortex_budget_usd: float,
    include_deep_evidence: bool,
    allow_live_fallback: bool,
    loaded_meta: dict | None,
) -> tuple:
    meta_items = tuple(sorted((str(k), _dba_control_scope_value(v)) for k, v in (loaded_meta or {}).items()))
    return (
        str(company),
        str(environment),
        int(lookback_hours),
        round(safe_float(cortex_budget_usd), 2),
        bool(include_deep_evidence),
        bool(allow_live_fallback),
        meta_items,
    )


def _dba_control_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _dba_control_scope_meta(
    company: str,
    environment: str,
    lookback_hours: int | None = None,
    cortex_budget_usd: float | None = None,
    include_deep_evidence: bool | None = None,
    allow_live_fallback: bool | None = None,
    state: dict | None = None,
) -> dict:
    """Return the exact operator scope a loaded DBA Control Room surface must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _dba_control_scope_value(company),
        "environment": _dba_control_scope_value(environment),
    }
    if lookback_hours is not None:
        meta["lookback_hours"] = int(lookback_hours)
    if cortex_budget_usd is not None:
        meta["cortex_budget_usd"] = round(safe_float(cortex_budget_usd), 2)
    if include_deep_evidence is not None:
        meta["include_deep_evidence"] = bool(include_deep_evidence)
    if allow_live_fallback is not None:
        meta["allow_live_fallback"] = bool(allow_live_fallback)
    for key in DBA_CONTROL_SCOPE_FILTER_KEYS:
        meta[key] = _dba_control_scope_value(state.get(key))
    return meta


def _dba_control_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key == "lookback_hours":
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif key == "cortex_budget_usd":
            if round(safe_float(actual), 2) != round(safe_float(expected_value), 2):
                return False
        elif isinstance(expected_value, bool):
            if bool(actual) != expected_value:
                return False
        elif _dba_control_scope_value(actual) != _dba_control_scope_value(expected_value):
            return False
    return True


def _dba_snapshot_scope_compatible(environment: str, state: dict | None = None) -> bool:
    """Fast snapshot is company-level only; scoped DBA telemetry needs detail load."""
    state = state if state is not None else st.session_state
    if str(environment or "ALL").upper() != "ALL":
        return False
    return not any(_dba_control_scope_value(state.get(key)) for key in DBA_CONTROL_SCOPE_FILTER_KEYS)


def _dba_control_source_health_rows(
    data: dict,
    state: dict,
    company: str,
    environment: str,
    lookback_hours: int,
    cortex_budget_usd: float,
    include_deep_evidence: bool,
    allow_live_fallback: bool,
) -> pd.DataFrame:
    """Summarize control-room telemetry freshness, source mode, and actionability."""
    if not isinstance(data, dict) or not data:
        return _empty_df()
    expected_meta = _dba_control_scope_meta(
        company,
        environment,
        lookback_hours,
        cortex_budget_usd,
        include_deep_evidence,
        allow_live_fallback,
        state=state,
    )
    loaded_meta = state.get("dba_control_room_meta", {})
    source_modes = data.get("_source_modes", _empty_df())
    mode_map = {}
    if source_modes is not None and not source_modes.empty and "Source" in source_modes.columns:
        for _, source_row in source_modes.iterrows():
            mode_map[str(source_row.get("Source"))] = {
                "Mode": str(source_row.get("Mode", "")),
                "Mode Message": str(source_row.get("Message", "")),
            }
    source_aliases = {
        "task_sla_cost": "task_sla_history",
        "task_latest_runs": "task_sla_history",
        "procedure_sla_cost": "procedure_sla",
        "procedure_latest_runs": "procedure_sla",
        "cortex_summary": "cortex_cost",
        "cortex_exceptions": "cortex_cost",
    }
    rows = []
    for key, value in data.items():
        if key.startswith("_") or key.endswith("_error"):
            continue
        source_key = source_aliases.get(key, key)
        mode_info = mode_map.get(str(source_key), mode_map.get(str(key), {}))
        mode = mode_info.get("Mode", "Live or local")
        err = data.get(f"{key}_error", _empty_df())
        message = "" if err is None or err.empty else str(err["ERROR"].iloc[0])
        if not message and mode_info.get("Mode Message", "").lower() not in ("", "nan", "none"):
            message = mode_info["Mode Message"]
        loaded = isinstance(value, pd.DataFrame)
        mode_lower = str(mode).lower()
        if mode_lower == "deferred" or "deferred" in mode_lower:
            state_label = "Deferred"
        elif "unavailable" in mode_lower:
            state_label = "Unavailable"
        elif err is not None and not err.empty:
            state_label = "Unavailable"
        elif not loaded:
            state_label = "On demand"
        elif not _dba_control_meta_matches(loaded_meta, expected_meta):
            state_label = "Stale"
        elif value.empty:
            state_label = "No Rows"
        else:
            state_label = "Loaded"
        if state_label == "Stale":
            next_action = "Reload DBA Control Room after changing company, environment, lookback, spend threshold, or triage filters."
        elif state_label == "Unavailable":
            next_action = "Deploy or refresh the summary/source before relying on this surface."
        elif state_label == "Deferred":
            next_action = "Load deep telemetry only when this source is needed for the current investigation."
        elif state_label == "No Rows":
            next_action = "Confirm the selected scope has relevant events or summary rows."
        elif "fallback" in mode_lower:
            next_action = "Use for investigation; prefer summary refresh for repeated morning triage."
        else:
            next_action = "Current for the active DBA control-room scope."
        rows.append({
            "SURFACE": key,
            "STATE": state_label,
            "STATE_RANK": {
                "Unavailable": 0,
                "Stale": 1,
                "Loaded": 2,
                "No Rows": 3,
                "Deferred": 4,
                "On demand": 5,
            }.get(state_label, 9),
            "MODE": mode,
            "ROWS": 0 if value is None or not hasattr(value, "empty") or value.empty else len(value),
            "SCOPE": f"{company} / {environment} / {int(lookback_hours)}h",
            "MESSAGE": message,
            "NEXT_ACTION": next_action,
        })
    return pd.DataFrame(rows)


def _task_failure_root_cause(error_text: object, query_text: object = "") -> dict:
    signal = f"{error_text or ''} {query_text or ''}".upper()
    if any(token in signal for token in [
        "DOES NOT EXIST", "NOT AUTHORIZED", "INSUFFICIENT PRIVILEGE", "SQL ACCESS CONTROL", "OBJECT"
    ]):
        return {
            "ROOT_CAUSE_SIGNAL": "Object/RBAC drift",
            "NEXT_ACTION": "Check that the object exists, confirm grants, then rerun the failed task before resuming schedules.",
            "BLOCKS_RELEASE": "Yes",
        }
    if any(token in signal for token in ["WAREHOUSE", "TIMEOUT", "TIMED OUT", "OUT OF MEMORY", "RESOURCE"]):
        return {
            "ROOT_CAUSE_SIGNAL": "Warehouse/runtime pressure",
            "NEXT_ACTION": "Check warehouse pressure, timeout settings, and query profile before retrying the task.",
            "BLOCKS_RELEASE": "Review",
        }
    if any(token in signal for token in ["SYNTAX", "COMPILATION", "INVALID IDENTIFIER", "NUMERIC", "CAST"]):
        return {
            "ROOT_CAUSE_SIGNAL": "SQL/procedure logic regression",
            "NEXT_ACTION": "Inspect the deployed SQL or procedure change and validate with a controlled rerun.",
            "BLOCKS_RELEASE": "Yes",
        }
    if any(token in signal for token in ["CANCELED", "CANCELLED", "ABORTED"]):
        return {
            "ROOT_CAUSE_SIGNAL": "Canceled or interrupted run",
            "NEXT_ACTION": "Confirm whether the cancel was intentional, then rerun only after downstream impact is known.",
            "BLOCKS_RELEASE": "Review",
        }
    return {
        "ROOT_CAUSE_SIGNAL": "Unclassified task failure",
        "NEXT_ACTION": "Open Task Failures, inspect TASK_HISTORY and linked QUERY_HISTORY, then add a diagnosis rule if repeated.",
        "BLOCKS_RELEASE": "Review",
    }


def _build_task_failure_root_cause_timeline(
    data: dict,
    *,
    company: str = "ALFA",
    environment: str = "ALL",
    lookback_hours: int = 24,
    max_tasks: int = 5,
) -> pd.DataFrame:
    """Build an automatic task-failure timeline from loaded Control Room telemetry."""
    task_failures = _frame_or_empty(data, "task_failures")
    task_sla_cost = _frame_or_empty(data, "task_sla_cost")
    object_changes = _frame_or_empty(data, "object_changes")
    failed_queries = _frame_or_empty(data, "failed_queries")
    rows: list[dict] = []
    event_order = 1

    if task_failures is not None and not task_failures.empty:
        failures = task_failures.copy()
        failures.columns = [str(col).upper() for col in failures.columns]
        if "FAILURES" in failures.columns:
            failures["_FAILURE_SORT"] = pd.to_numeric(failures["FAILURES"], errors="coerce").fillna(1)
        else:
            failures["_FAILURE_SORT"] = 1
        sort_cols = [col for col in ["_FAILURE_SORT", "LAST_FAILURE", "SCHEDULED_TIME"] if col in failures.columns]
        failures = failures.sort_values(sort_cols, ascending=[False] * len(sort_cols)).head(max_tasks)
        for _, failure in failures.iterrows():
            task_name = str(_row_value(failure, "TASK_NAME", "NAME", "ENTITY", default="Unknown task"))
            root_task = str(_row_value(failure, "ROOT_TASK_NAME", "ROOT_TASK", default=task_name))
            event_ts = _row_value(failure, "LAST_FAILURE", "SCHEDULED_TIME", "START_TIME", default="")
            error_text = _row_value(failure, "LAST_ERROR", "ERROR_MESSAGE", "QUERY_ERROR_MESSAGE", default="")
            query_text = _row_value(failure, "QUERY_TEXT", default="")
            diagnosis = _task_failure_root_cause(error_text, query_text)
            failure_count = safe_int(_row_value(failure, "FAILURES", "FAILURE_COUNT", default=1), 1)
            query_id = str(_row_value(failure, "QUERY_ID", default=""))
            rows.extend([
                {
                    "EVENT_ORDER": event_order,
                    "TIMELINE_STAGE": "Failure detected",
                    "EVENT_TS": event_ts,
                    "TASK_NAME": task_name,
                    "ROOT_TASK_NAME": root_task,
                    "ROOT_CAUSE_SIGNAL": diagnosis["ROOT_CAUSE_SIGNAL"],
                    "EVIDENCE": f"{failure_count:,} failed run(s). {str(error_text)[:220]}",
                    "NEXT_ACTION": "Keep release blocked until the failure has an explained cause and a clean rerun.",
                    "SOURCE": "Task failure mart",
                    "BLOCKS_RELEASE": "Yes",
                },
                {
                    "EVENT_ORDER": event_order + 1,
                    "TIMELINE_STAGE": "Probable root cause",
                    "EVENT_TS": event_ts,
                    "TASK_NAME": task_name,
                    "ROOT_TASK_NAME": root_task,
                    "ROOT_CAUSE_SIGNAL": diagnosis["ROOT_CAUSE_SIGNAL"],
                    "EVIDENCE": f"Query ID: {query_id or 'not captured'}; signature: {str(error_text)[:180]}",
                    "NEXT_ACTION": diagnosis["NEXT_ACTION"],
                    "SOURCE": "Error signature",
                    "BLOCKS_RELEASE": diagnosis["BLOCKS_RELEASE"],
                },
                {
                    "EVENT_ORDER": event_order + 2,
                    "TIMELINE_STAGE": "Recovery gate",
                    "EVENT_TS": "",
                    "TASK_NAME": task_name,
                    "ROOT_TASK_NAME": root_task,
                    "ROOT_CAUSE_SIGNAL": diagnosis["ROOT_CAUSE_SIGNAL"],
                    "EVIDENCE": "Production change can proceed only after TASK_HISTORY shows a successful rerun and downstream data refresh.",
                    "NEXT_ACTION": "Confirm a clean rerun before resuming or closing the operational item.",
                    "SOURCE": "Derived operational status",
                    "BLOCKS_RELEASE": "Yes" if diagnosis["BLOCKS_RELEASE"] == "Yes" else "Review",
                },
            ])
            event_order += 3

    if not task_sla_cost.empty:
        view = task_sla_cost.copy()
        view.columns = [str(col).upper() for col in view.columns]
        for _, item in view.head(max_tasks).iterrows():
            rows.append({
                "EVENT_ORDER": event_order,
                "TIMELINE_STAGE": "Runtime or cost regression",
                "EVENT_TS": _row_value(item, "SCHEDULED_TIME", "START_TIME", default=""),
                "TASK_NAME": str(_row_value(item, "TASK_NAME", "ENTITY", default="Task graph")),
                "ROOT_TASK_NAME": str(_row_value(item, "ROOT_TASK_NAME", "TASK_NAME", default="Task graph")),
                "ROOT_CAUSE_SIGNAL": str(_row_value(item, "SIGNAL", default="Task regression")),
                "EVIDENCE": str(_row_value(item, "DETAIL", "EVIDENCE", "IMPACT_OBJECTS", default="Regression signal detected."))[:260],
                "NEXT_ACTION": "Compare to the release window and validate query/procedure changes before accepting the new baseline.",
                "SOURCE": "Task SLA/cost mart",
                "BLOCKS_RELEASE": "Review",
            })
            event_order += 1

    if rows and not object_changes.empty:
        change = object_changes.copy()
        change.columns = [str(col).upper() for col in change.columns]
        latest = change.head(1).iloc[0]
        rows.append({
            "EVENT_ORDER": event_order,
            "TIMELINE_STAGE": "Recent change context",
            "EVENT_TS": _row_value(latest, "START_TIME", "EVENT_TS", default=""),
            "TASK_NAME": "Release scope",
            "ROOT_TASK_NAME": "",
            "ROOT_CAUSE_SIGNAL": str(_row_value(latest, "QUERY_TYPE", "SIGNAL", default="Object change")),
            "EVIDENCE": str(_row_value(latest, "QUERY_PREVIEW", "QUERY_TEXT", "EVIDENCE", default="Recent object or grant change."))[:260],
            "NEXT_ACTION": "Check whether this object/grant change touched the failed task dependency path.",
            "SOURCE": "Object change mart",
            "BLOCKS_RELEASE": "Review",
        })
        event_order += 1

    if rows and not failed_queries.empty:
        query = failed_queries.copy()
        query.columns = [str(col).upper() for col in query.columns]
        latest = query.head(1).iloc[0]
        rows.append({
            "EVENT_ORDER": event_order,
            "TIMELINE_STAGE": "Linked query failure context",
            "EVENT_TS": _row_value(latest, "START_TIME", "EVENT_TIMESTAMP", default=""),
            "TASK_NAME": str(_row_value(latest, "QUERY_ID", default="Failed query")),
            "ROOT_TASK_NAME": "",
            "ROOT_CAUSE_SIGNAL": str(_row_value(latest, "ERROR_CODE", default="Query failure")),
            "EVIDENCE": str(_row_value(latest, "ERROR_MESSAGE", default="Recent failed query in same lookback."))[:260],
            "NEXT_ACTION": "Open query diagnosis and compare query error signature with the failed task.",
            "SOURCE": "Query failure mart",
            "BLOCKS_RELEASE": "Review",
        })

    if not rows:
        return pd.DataFrame([{
            "EVENT_ORDER": 1,
            "TIMELINE_STAGE": "No task failure signal",
            "EVENT_TS": "",
            "TASK_NAME": f"{company} / {environment}",
            "ROOT_TASK_NAME": "",
            "ROOT_CAUSE_SIGNAL": "No loaded failure telemetry",
            "EVIDENCE": f"No task failures or task SLA/cost regressions found in the loaded {lookback_hours}h scope.",
            "NEXT_ACTION": "Keep monitoring; review workload comparison after product releases that change task or procedure logic.",
            "SOURCE": "Derived operational status",
            "BLOCKS_RELEASE": "No",
        }])
    return pd.DataFrame(rows).sort_values("EVENT_ORDER").reset_index(drop=True)


def _build_auto_release_readiness_gate(
    data: dict,
    source_health: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Return automatic production-change blockers from object, data, and task telemetry."""
    rows: list[dict] = []
    migration = _frame_or_empty(data, "schema_migration_status")
    migration_error = _frame_or_empty(data, "schema_migration_status_error")
    if migration.empty:
        if not migration_error.empty:
            rows.append({
                "GATE": "Release status",
                "STATE": "Review",
                "SEVERITY": "Medium",
                "EVIDENCE": str(migration_error.iloc[0].get("ERROR", "Schema migration status unavailable."))[:260],
                "NEXT_ACTION": "Run the reviewed release remediation or ask the DBA on-call to refresh status telemetry, then reload Control Room.",
                "ROUTE": "DBA Control Room",
                "PROOF_REQUIRED": "release status telemetry is current and complete",
            })
        else:
            rows.append({
                "GATE": "Release status",
                "STATE": "On demand",
                "SEVERITY": "Low",
                "EVIDENCE": "Release status telemetry is available after Control Room refresh.",
                "NEXT_ACTION": "Refresh DBA Control Room triage before approving a release.",
                "ROUTE": "DBA Control Room",
                "PROOF_REQUIRED": "release status telemetry",
            })
    else:
        view = migration.copy()
        view.columns = [str(col).upper() for col in view.columns]
        state_series = view.get("MIGRATION_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
        blockers = view[~state_series.str.upper().isin(["READY", "NO ACTION", "NO ACTION."])]
        if blockers.empty:
            rows.append({
                "GATE": "Deployment contract",
                "STATE": "Ready",
                "SEVERITY": "Low",
                "EVIDENCE": f"{len(view):,} required release object(s) present and version-aligned.",
                "NEXT_ACTION": "Keep the migration ledger with the release artifact.",
                "ROUTE": "DBA Control Room",
                "PROOF_REQUIRED": "current OVERWATCH_SCHEMA_MIGRATION row",
            })
        else:
            for _, item in blockers.head(10).iterrows():
                state = str(item.get("MIGRATION_STATE") or "Review")
                rows.append({
                    "GATE": f"Deployment object: {item.get('OBJECT_NAME', '')}",
                    "STATE": "Blocked" if state == "Blocked" else "Review",
                    "SEVERITY": "High" if state == "Blocked" else "Medium",
                    "EVIDENCE": (
                        f"{item.get('COMPONENT', '')}; object_state={item.get('OBJECT_STATE', '')}; "
                        f"deployed={item.get('DEPLOYED_VERSION', '')}; required={item.get('REQUIRED_VERSION', '')}"
                    ),
                    "NEXT_ACTION": str(item.get("NEXT_ACTION") or "Apply release remediation and reload status."),
                    "ROUTE": "DBA Control Room",
                    "PROOF_REQUIRED": "object exists and ledger version matches the app release",
                })

    task_failures = _frame_or_empty(data, "task_failures")
    if not task_failures.empty:
        failures = task_failures.copy()
        failures.columns = [str(col).upper() for col in failures.columns]
        failure_total = safe_int(pd.to_numeric(failures.get("FAILURES", pd.Series([1] * len(failures))), errors="coerce").fillna(1).sum())
        names = ", ".join(dict.fromkeys(failures.get("TASK_NAME", pd.Series(dtype=str)).dropna().astype(str).head(4)))
        rows.append({
            "GATE": "Task failure recovery",
            "STATE": "Blocked",
            "SEVERITY": "Critical" if failure_total >= 3 else "High",
            "EVIDENCE": f"{failure_total:,} failed task run(s) across {len(failures):,} grouped task(s). {names}",
            "NEXT_ACTION": "Use the task root-cause timeline, confirm a clean rerun, then decide whether schedules can resume.",
            "ROUTE": "Workload Operations",
            "PROOF_REQUIRED": "TASK_HISTORY success after the latest failure and downstream summary refresh status",
        })

    task_sla_cost = _frame_or_empty(data, "task_sla_cost")
    if not task_sla_cost.empty:
        rows.append({
            "GATE": "Task release regression",
            "STATE": "Review",
            "SEVERITY": "High",
            "EVIDENCE": f"{len(task_sla_cost):,} task runtime or cost regression candidate(s).",
            "NEXT_ACTION": "Run Release Compare and confirm task/procedure baselines before accepting the release.",
            "ROUTE": "Workload Operations",
            "PROOF_REQUIRED": "before/after task graph comparison and baseline decision",
        })

    latest_runs = _frame_or_empty(data, "task_latest_runs")
    if not latest_runs.empty:
        latest = latest_runs.copy()
        latest.columns = [str(col).upper() for col in latest.columns]
        states = latest.get("STATE", pd.Series([""] * len(latest), index=latest.index)).fillna("").astype(str).str.upper()
        suspended = int(states.eq("SUSPENDED").sum())
        if suspended:
            rows.append({
                "GATE": "Suspended scheduled work",
                "STATE": "Review",
                "SEVERITY": "High",
                "EVIDENCE": f"{suspended:,} latest task run(s) or inventory row(s) are suspended.",
                "NEXT_ACTION": "Confirm review status and dependency impact before resuming scheduled work.",
                "ROUTE": "Workload Operations",
                "PROOF_REQUIRED": "SHOW TASKS state, review status, and post-resume TASK_HISTORY success",
            })

    if source_health is not None and not source_health.empty and "STATE" in source_health.columns:
        source_gate_summary, source_gate = _build_evidence_freshness_gate(source_health)
        blocking_sources = safe_int(source_gate_summary.get("blocked"))
        review_sources = safe_int(source_gate_summary.get("review"))
        if blocking_sources or review_sources:
            top_sources = ", ".join(
                dict.fromkeys(
                    source_gate[
                        source_gate["GATE_STATE"].astype(str).isin(["Blocked", "Review"])
                    ]["SURFACE"].astype(str).head(5).tolist()
                )
            )
            rows.append({
            "GATE": "Telemetry status",
                "STATE": "Blocked" if blocking_sources else "Review",
                "SEVERITY": "High" if blocking_sources else "Medium",
                "EVIDENCE": (
                    f"{blocking_sources:,} blocked; {review_sources:,} review; "
                    f"state {_gate_state_from_counts(blocking_sources, review_sources)}. {top_sources}"
                ),
                "NEXT_ACTION": (
                    "Refresh unavailable core telemetry before release review."
                    if blocking_sources
                    else "Reload stale data-health inputs or confirm the deferred deep checks are not needed for this release."
                ),
                "ROUTE": "Data Health",
                "PROOF_REQUIRED": "current data health for the active scope and required release surfaces",
            })

    if not rows:
        rows.append({
            "GATE": "Release status",
            "STATE": "Ready",
            "SEVERITY": "Low",
            "EVIDENCE": "No deployment, source, task failure, or release-regression blockers found in loaded telemetry.",
            "NEXT_ACTION": "Keep monitoring and rerun release checks before production changes.",
            "ROUTE": "DBA Control Room",
            "PROOF_REQUIRED": "fresh Control Room load",
        })

    gate = pd.DataFrame(rows)
    state_rank = {"Blocked": 0, "Review": 1, "On demand": 2, "Ready": 4}
    severity_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 4}
    gate["STATE_RANK"] = gate["STATE"].map(state_rank).fillna(9)
    gate["SEVERITY_RANK"] = gate["SEVERITY"].map(severity_rank).fillna(9)
    gate = gate.sort_values(["STATE_RANK", "SEVERITY_RANK", "GATE"]).reset_index(drop=True)
    summary = {
        "blocked": int(gate["STATE"].eq("Blocked").sum()),
        "review": int(gate["STATE"].eq("Review").sum()),
        "ready": int(gate["STATE"].eq("Ready").sum()),
        "not_loaded": int(gate["STATE"].eq("On demand").sum()),
        "score": max(0, min(100, 100 - int(gate["STATE"].eq("Blocked").sum()) * 30 - int(gate["STATE"].eq("Review").sum()) * 12 - int(gate["STATE"].eq("On demand").sum()) * 6)),
    }
    return summary, gate.drop(columns=["STATE_RANK", "SEVERITY_RANK"], errors="ignore")


def _evidence_surface_route(surface: object) -> tuple[str, str, str]:
    text = str(surface or "").lower()
    if "schema" in text or "migration" in text:
        return (
            "DBA Control Room",
            "Operations Detail",
            "object status and required monitoring objects",
        )
    if "task" in text or "procedure" in text:
        return (
            "Workload Operations",
            "Task and procedure reliability",
            "TASK_HISTORY, procedure runs, and clean rerun telemetry",
        )
    if "warehouse" in text:
        return (
            "Cost & Contract",
            "Recommendations and action queue",
            "warehouse overview, pressure, settings, and metering telemetry",
        )
    if "credit" in text or "cost" in text or "cortex" in text:
        return (
            "Cost & Contract",
            "Cost Cockpit",
            "current credit, cost-driver, spend threshold, and attribution telemetry",
        )
    if "object" in text or "change" in text or "grant" in text:
        return (
            "Security Monitoring",
            "Object and access changes",
            "object-change, grant-change, ticket, and blast-radius telemetry",
        )
    if "login" in text or "security" in text:
        return (
            "Security Monitoring",
            "Security Posture",
            "login, privilege, MFA, and access-review telemetry",
        )
    if "alert" in text or "action_queue" in text or "action queue" in text:
        return (
            "Alert Center",
            "Alert lifecycle",
            "alert lifecycle, routing, closure, and delivery telemetry",
        )
    return (
        "DBA Control Room",
        "Data Health",
        "fresh data health for the active company, environment, lookback, spend threshold, and filters",
    )


def _evidence_freshness_core_surface(surface: object) -> bool:
    text = str(surface or "").lower()
    if text in {
        "summary",
        "credits",
        "task_failures",
        "failed_queries",
        "warehouse_pressure",
        "action_queue",
    }:
        return True
    return any(
        token in text
        for token in (
            "schema_migration",
        )
    )


def _build_evidence_freshness_gate(source_health: pd.DataFrame | None) -> tuple[dict, pd.DataFrame]:
    """Score loaded Control Room telemetry coverage."""
    if source_health is None or source_health.empty:
        return {
            "surfaces": 0,
            "blocked": 0,
            "review": 0,
            "deferred": 0,
            "ready": 0,
            "score": 100,
        }, _empty_df()

    view = source_health.copy()
    view.columns = [str(col).upper() for col in view.columns]
    rows: list[dict] = []
    for _, item in view.iterrows():
        surface = str(item.get("SURFACE") or "")
        state = str(item.get("STATE") or "On demand")
        mode = str(item.get("MODE") or "")
        rows_count = safe_int(item.get("ROWS"))
        message = str(item.get("MESSAGE") or "")
        next_action = str(item.get("NEXT_ACTION") or "")
        route, workflow, proof_required = _evidence_surface_route(surface)
        core_surface = _evidence_freshness_core_surface(surface)
        state_upper = state.upper()

        if state_upper == "UNAVAILABLE" and core_surface:
            gate_state = "Blocked"
            severity = "High"
            release_impact = "Yes"
            rank = 0
            action = next_action or "Refresh or deploy the missing data input before release review."
        elif state_upper == "UNAVAILABLE":
            gate_state = "Review"
            severity = "Medium"
            release_impact = "Review"
            rank = 2
            action = next_action or "Refresh the unavailable telemetry before relying on this specialist surface."
        elif state_upper == "STALE":
            gate_state = "Review"
            severity = "High" if core_surface else "Medium"
            release_impact = "Review"
            rank = 1 if core_surface else 3
            action = next_action or "Reload telemetry for the active scope before release review."
        elif state_upper == "NOT LOADED" and core_surface:
            gate_state = "Review"
            severity = "Medium"
            release_impact = "Review"
            rank = 4
            action = next_action or "Load this core telemetry surface before production signoff."
        elif state_upper == "DEFERRED":
            gate_state = "Deferred"
            severity = "Low"
            release_impact = "No"
            rank = 7
            action = next_action or "Load deep telemetry only if this release touches the route."
        elif state_upper in {"LOADED", "NO ROWS"}:
            gate_state = "Ready"
            severity = "Low"
            release_impact = "No"
            rank = 8
            action = next_action or "Telemetry is current for the active scope."
        else:
            gate_state = "On demand"
            severity = "Low"
            release_impact = "No"
            rank = 9
            action = next_action or "Load telemetry if this source is needed for the release."

        rows.append({
            "SURFACE": surface,
            "GATE_STATE": gate_state,
            "SEVERITY": severity,
            "SOURCE_STATE": state,
            "MODE": mode,
            "ROWS": rows_count,
            "RELEASE_IMPACT": release_impact,
            "ROUTE": route,
            "WORKFLOW": workflow,
            "PROOF_REQUIRED": proof_required,
            "EVIDENCE": (
                f"{surface}; state={state}; mode={mode or 'unknown'}; rows={rows_count:,}; "
                f"{message[:180]}"
            ).strip(),
            "NEXT_ACTION": action,
            "GATE_RANK": rank,
        })

    board = pd.DataFrame(rows).sort_values(
        ["GATE_RANK", "SURFACE"],
        ascending=[True, True],
    ).reset_index(drop=True)
    blocked = int(board["GATE_STATE"].eq("Blocked").sum())
    review = int(board["GATE_STATE"].eq("Review").sum())
    deferred = int(board["GATE_STATE"].eq("Deferred").sum())
    ready = int(board["GATE_STATE"].eq("Ready").sum())
    score = max(0, min(100, 100 - blocked * 22 - review * 8 - deferred * 1))
    summary = {
        "surfaces": int(len(board)),
        "blocked": blocked,
        "review": review,
        "deferred": deferred,
        "ready": ready,
        "score": score,
    }
    return summary, board


def _control_room_snapshot_to_data(snapshot: pd.DataFrame) -> dict:
    """Convert the lightweight summary snapshot into the data shape used by the page.

    The summary snapshot is intentionally small: it supports the watch floor and
    morning triage metrics, while deep telemetry tables still load on demand.
    """
    if snapshot is None or snapshot.empty:
        return {}
    latest = snapshot.copy()
    latest.columns = [str(col).upper() for col in latest.columns]
    worst_score = safe_float(pd.to_numeric(latest.get("HEALTH_SCORE", pd.Series([100])), errors="coerce").min())
    failed_queries = _snapshot_metric(latest, "FAILED_QUERIES_24H")
    failed_tasks = _snapshot_metric(latest, "FAILED_TASKS_24H")
    queued_ms = _snapshot_metric(latest, "QUEUED_MS_24H")
    credits = _snapshot_metric(latest, "CREDITS_24H")
    cortex_cost = _snapshot_metric(latest, "CORTEX_COST_7D_USD")
    security_events = _snapshot_metric(latest, "SECURITY_EVENTS_24H")
    object_changes = _snapshot_metric(latest, "OBJECT_CHANGES_24H")

    top_risks = [
        str(value)
        for value in latest.get("TOP_RISK", pd.Series(dtype=str)).dropna().astype(str).tolist()
        if str(value).strip() and str(value).strip().lower() != "no immediate exception"
    ]
    summary = pd.DataFrame([{
        "TOTAL_QUERIES": 0,
        "FAILED_QUERIES": failed_queries,
        "QUEUED_QUERIES": 1 if queued_ms > 0 else 0,
        "REMOTE_SPILL_QUERIES": 0,
        "AVG_ELAPSED_SEC": 0,
        "P95_ELAPSED_SEC": 0,
        "ACTIVE_WAREHOUSES": 0,
        "ACTIVE_USERS": 0,
        "MART_HEALTH_SCORE": worst_score,
        "MART_TOP_RISK": ", ".join(dict.fromkeys(top_risks)) or "No immediate exception",
    }])
    credits_df = pd.DataFrame([{"PERIOD_CREDITS": credits, "PRIOR_CREDITS": 0}])
    task_failures = pd.DataFrame(
        [{"TASK_NAME": "Mart summary", "FAILURES": failed_tasks}]
    ) if failed_tasks > 0 else _empty_df()
    failed_logins = pd.DataFrame(
        [{"SIGNAL": "Failed login/security events", "EVENTS": security_events}]
    ) if security_events > 0 else _empty_df()
    object_df = pd.DataFrame(
        [{"SIGNAL": "Object or grant changes", "CHANGES": object_changes}]
    ) if object_changes > 0 else _empty_df()
    cortex_summary = pd.DataFrame([{
        "PROJECTED_30D_COST": cortex_cost / 7 * 30 if cortex_cost > 0 else 0,
        "TOTAL_COST": cortex_cost,
    }])
    return {
        "summary": summary,
        "credits": credits_df,
        "task_failures": task_failures,
        "failed_logins": failed_logins,
        "object_changes": object_df,
        "cortex_summary": cortex_summary,
        "_mart_snapshot": latest,
        "_source_modes": pd.DataFrame([
            {
                "Source": "mart_snapshot",
                "Mode": "Fast summary snapshot",
                "Message": "Company-level snapshot; use scoped detail load when environment or triage filters are active.",
            },
            {"Source": "summary", "Mode": "Fast summary snapshot"},
            {"Source": "credits", "Mode": "Fast summary snapshot"},
            {"Source": "task_failures", "Mode": "Fast summary snapshot"},
            {"Source": "failed_logins", "Mode": "Fast summary snapshot"},
            {"Source": "object_changes", "Mode": "Fast summary snapshot"},
            {"Source": "cortex_cost", "Mode": "Fast summary snapshot"},
        ]),
    }


def _dba_source_health_deployment_gate(source_health: pd.DataFrame | None) -> dict:
    """Return a global source-health gate for effective readiness."""
    if source_health is None or source_health.empty or "STATE" not in source_health.columns:
        return {
            "score": 100,
            "label": "Data Health",
            "reason": "",
        }
    states = source_health["STATE"].fillna("").astype(str)
    unavailable = int(states.isin(["Unavailable"]).sum())
    stale = int(states.isin(["Stale"]).sum())
    not_loaded = int(states.isin(["On demand"]).sum())
    if unavailable:
        return {
            "score": 86,
            "label": "Data Health",
            "reason": f"{unavailable:,} required data input(s) unavailable.",
        }
    if stale:
        return {
            "score": 90,
            "label": "Data Health",
            "reason": f"{stale:,} data input(s) stale for the active scope.",
        }
    if not_loaded:
        return {
            "score": 94,
            "label": "Data Health",
            "reason": f"{not_loaded:,} signal group(s) available after refresh.",
        }
    return {
        "score": 100,
        "label": "Data Health",
        "reason": "",
    }


def _render_control_room_source_health(
    data: dict,
    company: str,
    environment: str,
    lookback_hours: int,
    cortex_budget_usd: float,
    include_deep_evidence: bool,
    allow_live_fallback: bool,
) -> pd.DataFrame:
    source_health = _dba_control_source_health_rows(
        data,
        st.session_state,
        company,
        environment,
        lookback_hours,
        cortex_budget_usd,
        include_deep_evidence,
        allow_live_fallback,
    )
    if source_health.empty:
        st.info("No data health rows are available yet.")
        return source_health
    current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
    stale = int(source_health["STATE"].eq("Stale").sum())
    unavailable = int(source_health["STATE"].eq("Unavailable").sum())
    fast_summary = int(
        source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["MODE"].astype(str).str.contains("fast summary", case=False, regex=False)
        ].shape[0]
    )
    render_shell_snapshot((
        ("Current Surfaces", f"{current}/{len(source_health)}"),
        ("Fast Summary", f"{fast_summary:,}"),
        ("Stale", f"{stale:,}"),
        ("Unavailable", f"{unavailable:,}"),
    ))
    st.caption(
        "Use this before acting from the Control Room. Stale rows mean telemetry was loaded under a different "
        "company, environment, lookback, spend threshold, fallback mode, or triage filter scope."
    )
    render_priority_dataframe(
        source_health,
        title="Control-room telemetry freshness and data mode",
        priority_columns=["STATE", "SURFACE", "MODE", "ROWS", "SCOPE", "MESSAGE", "NEXT_ACTION"],
        sort_by=["STATE_RANK", "SURFACE"],
        ascending=[True, True],
        raw_label="All control-room data-health rows",
        height=360,
    )
    return source_health


def _render_release_readiness_gate(
    data: dict,
    source_health: pd.DataFrame | None,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    summary, gate = _build_auto_release_readiness_gate(data, source_health)
    timeline = _build_task_failure_root_cause_timeline(
        data,
        company=company,
        environment=environment,
        lookback_hours=lookback_hours,
    )
    render_shell_snapshot((
        ("Gate State", _gate_state_from_counts(safe_int(summary.get("blocked")), safe_int(summary.get("review")))),
        ("Blocked", f"{safe_int(summary.get('blocked')):,}"),
        ("Review", f"{safe_int(summary.get('review')):,}"),
        ("Ready", f"{safe_int(summary.get('ready')):,}"),
        ("Timeline Events", f"{len(timeline):,}"),
    ))
    if safe_int(summary.get("blocked")):
        st.error("Change path is blocked by release or task recovery telemetry.")
    elif safe_int(summary.get("review")) or safe_int(summary.get("not_loaded")):
        st.warning("Change review needs status confirmation before production change.")
    else:
        st.success("Loaded operational telemetry is clear.")

    render_priority_dataframe(
        gate,
        title="Operational status gate",
        priority_columns=["GATE", "STATE", "SEVERITY", "EVIDENCE", "NEXT_ACTION", "ROUTE", "PROOF_REQUIRED"],
        sort_by=["STATE", "SEVERITY", "GATE"],
        ascending=[True, True, True],
        raw_label="All operational status rows",
        height=300,
    )
    download_csv(gate, "overwatch_auto_release_gate.csv")

    source_gate_summary, source_gate = _build_evidence_freshness_gate(source_health)
    if not source_gate.empty:
        st.markdown("**Telemetry Status Gate**")
        render_shell_snapshot((
            ("Telemetry State", _gate_state_from_counts(safe_int(source_gate_summary.get("blocked")), safe_int(source_gate_summary.get("review")))),
            ("Blocked Inputs", f"{safe_int(source_gate_summary.get('blocked')):,}"),
            ("Review Inputs", f"{safe_int(source_gate_summary.get('review')):,}"),
            ("Deferred Inputs", f"{safe_int(source_gate_summary.get('deferred')):,}"),
        ))
        render_priority_dataframe(
            source_gate,
            title="Operational telemetry status by input",
            priority_columns=[
                "SURFACE", "GATE_STATE", "SEVERITY", "SOURCE_STATE", "MODE", "ROWS",
                "RELEASE_IMPACT", "ROUTE", "WORKFLOW", "NEXT_ACTION",
            ],
            sort_by=["GATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All operational telemetry status rows",
            height=300,
            max_rows=12,
        )
        download_csv(source_gate, "overwatch_release_evidence_freshness.csv")

    st.markdown("**Task Failure Root-Cause Timeline**")
    render_priority_dataframe(
        timeline,
        title="Task failure root-cause timeline",
        priority_columns=[
            "EVENT_ORDER", "TIMELINE_STAGE", "EVENT_TS", "TASK_NAME", "ROOT_TASK_NAME",
            "ROOT_CAUSE_SIGNAL", "EVIDENCE", "NEXT_ACTION", "SOURCE", "BLOCKS_RELEASE",
        ],
        sort_by=["EVENT_ORDER"],
        ascending=[True],
        raw_label="All task failure timeline rows",
        height=340,
    )
    download_csv(timeline, "overwatch_task_failure_root_cause_timeline.csv")
    r1, r2, r3 = st.columns(3)
    with r1:
        if st.button("Open Workload Operations", key="dba_release_gate_open_workload", width="stretch"):
            _jump("Workload Operations", workflow="Task graphs")
            st.rerun()
    with r2:
        if st.button("Open Security Monitoring", key="dba_release_gate_open_change", width="stretch"):
            _jump("Security Monitoring", workflow="Object and access changes")
            st.rerun()
    with r3:
        if st.button("Open Operations Detail", key="dba_release_gate_open_operations", width="stretch"):
            st.session_state["dba_control_room_active_view"] = "Operations Detail"
            st.rerun()
    return summary, gate, timeline

