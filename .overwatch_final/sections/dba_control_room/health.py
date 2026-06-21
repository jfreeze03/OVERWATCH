"""Source-health, evidence/release-readiness, snapshot, and control-room data-prep helpers."""
from __future__ import annotations

from datetime import date
from datetime import datetime
from utils.primitives import safe_float
from utils.primitives import safe_int
import streamlit as st
from .types import DBA_CONTROL_SCOPE_FILTER_KEYS, _dba_control_scope_value, _empty_df, _frame_or_empty, _gate_state_from_counts, _row_value, credits_to_dollars, filter_existing_columns, format_credits, get_global_filter_clause, pd, sql_literal




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


def _task_management_helpers():
    from sections.task_management import (
        _build_task_ops_frames,
        _extract_object_candidates,
        _normalize_query_details,
        _procedure_from_definition,
        _query_detail_sql,
    )

    return (
        _build_task_ops_frames,
        _extract_object_candidates,
        _normalize_query_details,
        _procedure_from_definition,
        _query_detail_sql,
    )


def _cortex_helpers():
    from sections.cortex_monitor import (
        _build_cortex_control_sql,
        _cortex_cost_rating,
        _cortex_cost_score,
    )

    return _build_cortex_control_sql, _cortex_cost_rating, _cortex_cost_score


def _procedure_helpers():
    from sections.stored_proc_tracker import (
        _build_procedure_sla_frames,
        _build_procedure_sla_sql,
        _procedure_run_estimated_credits,
        _query_history_has_root_query_id,
    )

    return (
        _build_procedure_sla_frames,
        _build_procedure_sla_sql,
        _procedure_run_estimated_credits,
        _query_history_has_root_query_id,
    )


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


def _dba_task_status_task_summary(data: dict | None) -> dict:
    """Normalize the bounded Snowflake TASK_HISTORY summary used by Workload Operations."""
    empty_summary = {
        "loaded": False,
        "task_status_rows": 0,
        "task_status_failures": 0,
        "task_status_late": 0,
        "task_status_alerts": 0,
        "task_status_watch": 0,
        "last_seen": "",
    }
    if not isinstance(data, dict):
        return empty_summary

    frame = _empty_df()
    for key in (
        "workload_task_status",
        "workload_operations_task_snapshot",
        "task_status_task_status",
        "task_status_history_summary",
    ):
        candidate = _frame_or_empty(data, key)
        if not candidate.empty:
            frame = candidate
            break
    if frame.empty:
        return empty_summary

    view = frame.copy()
    view.columns = [str(col).upper() for col in view.columns]
    row = view.iloc[0]
    return {
        "loaded": True,
        "task_status_rows": safe_int(_row_value(row, "TASK_STATUS_ROWS", default=0)),
        "task_status_failures": safe_int(_row_value(row, "TASK_STATUS_FAILURE_ROWS", default=0)),
        "task_status_late": safe_int(_row_value(row, "TASK_STATUS_LATE_ROWS", default=0)),
        "task_status_alerts": safe_int(_row_value(row, "TASK_STATUS_ALERT_ROWS", default=0)),
        "task_status_watch": safe_int(_row_value(row, "TASK_STATUS_WATCH_ROWS", default=0)),
        "last_seen": str(_row_value(row, "TASK_STATUS_LAST_SEEN_AT", "LAST_SEEN", default="") or ""),
    }


def _normalize_focus_frame(value: pd.DataFrame | None) -> pd.DataFrame:
    if value is None or not isinstance(value, pd.DataFrame) or value.empty:
        return _empty_df()
    view = value.copy()
    view.columns = [str(col).upper() for col in view.columns]
    return view


def _target_object_from_row(row: dict | pd.Series | None) -> str:
    row = row if row is not None else {}
    explicit = str(_row_value(row, "TARGET_OBJECT", "WAIT_OBJECTS", default="") or "").strip()
    if explicit:
        return explicit.split(",")[0].strip()
    parts = [
        str(_row_value(row, "DATABASE_NAME", default="") or "").strip(),
        str(_row_value(row, "SCHEMA_NAME", default="") or "").strip(),
        str(_row_value(row, "OBJECT_NAME", default="") or "").strip(),
    ]
    return ".".join(part for part in parts if part and part.upper() not in {"NAN", "NONE", "NULL"})


def _focus_context_from_row(row: dict | pd.Series | None, *, reason: str = "") -> dict[str, str]:
    row = row if row is not None else {}
    query_id = str(_row_value(
        row,
        "QUERY_ID",
        "WAITER_QUERY_ID",
        "BLOCKER_QUERY_ID",
        "TASK_QUERY_ID",
        "RUN_1_QUERY_ID",
        "RUN_2_QUERY_ID",
        default="",
    ) or "").strip()
    return {
        "FOCUS_QUERY_ID": query_id,
        "FOCUS_WAREHOUSE": str(_row_value(row, "WAREHOUSE_NAME", "WAREHOUSE", default="") or "").strip(),
        "FOCUS_USER": str(_row_value(row, "USER_NAME", "USER", default="") or "").strip(),
        "FOCUS_OBJECT": _target_object_from_row(row),
        "FOCUS_REASON": str(reason or _row_value(row, "ROOT_CAUSE", "SIGNAL", "STATE", default="") or "").strip(),
    }


def _first_focus_context(
    frame: pd.DataFrame | None,
    *,
    tokens: tuple[str, ...] = (),
    numeric_columns: tuple[str, ...] = (),
    reason: str = "",
) -> dict[str, str]:
    view = _normalize_focus_frame(frame)
    if view.empty:
        return {}
    mask = pd.Series(False, index=view.index)
    if tokens:
        text_columns = [
            column for column in (
                "ROOT_CAUSE", "SIGNAL", "STATE", "WHY_NOW", "EVIDENCE",
                "NEXT_ACTION", "IMPACT_UNIT", "ERROR_MESSAGE", "QUERY_TEXT",
            )
            if column in view.columns
        ]
        if text_columns:
            combined = view[text_columns].fillna("").astype(str).agg(" ".join, axis=1).str.upper()
            mask = mask | combined.apply(lambda text: any(token in text for token in tokens))
    for column in numeric_columns:
        if column in view.columns:
            mask = mask | pd.to_numeric(view[column], errors="coerce").fillna(0).gt(0)
    candidates = view[mask] if bool(mask.any()) else view.head(1)
    return _focus_context_from_row(candidates.iloc[0], reason=reason)


def _top_warehouse_focus_context(frame: pd.DataFrame | None, *, reason: str = "") -> dict[str, str]:
    view = _normalize_focus_frame(frame)
    if view.empty:
        return {}
    sort_cols = [
        column for column in (
            "BLOCKED_QUERIES", "QUEUED_QUERIES", "AVG_BLOCKED",
            "MAX_QUEUED_LOAD", "REMOTE_SPILL_GB", "QUERIES",
        )
        if column in view.columns
    ]
    if sort_cols:
        for column in sort_cols:
            view[column] = pd.to_numeric(view[column], errors="coerce").fillna(0)
        view = view.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    return _focus_context_from_row(view.iloc[0], reason=reason)


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


def _snapshot_metric(df: pd.DataFrame, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    return safe_float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


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


def _scalar_frame_value(data: dict, key: str, column: str, default=0):
    df = data.get(key, _empty_df())
    if df is None or df.empty or column not in df.columns:
        return default
    return df.iloc[0].get(column, default)


def _release_window_predicate(column: str, start: date, end: date) -> str:
    """Build an inclusive date-window predicate with an exclusive next-day bound."""
    start_ts = sql_literal(f"{start.isoformat()} 00:00:00")
    end_ts = sql_literal(f"{end.isoformat()} 00:00:00")
    return (
        f"{column} >= TO_TIMESTAMP_NTZ({start_ts}) "
        f"AND {column} < DATEADD('day', 1, TO_TIMESTAMP_NTZ({end_ts}))"
    )


def _clean_release_text(values: pd.Series, limit: int = 5) -> str:
    if values is None or values.empty:
        return ""
    seen: list[str] = []
    for raw in values.dropna().astype(str):
        for piece in raw.split(","):
            item = piece.strip()
            if item and item not in seen:
                seen.append(item)
            if len(seen) >= limit:
                return ", ".join(seen)
    return ", ".join(seen)


def _aggregate_release_window(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """Normalize task/procedure run rows into comparable release-window metrics."""
    if df is None or df.empty:
        return pd.DataFrame()
    prepared = df.copy()
    prepared.columns = [str(col).upper() for col in prepared.columns]
    key_col = key_col.upper()
    if key_col not in prepared.columns:
        return pd.DataFrame()

    duration_col = "TOTAL_ELAPSED_SEC" if "TOTAL_ELAPSED_SEC" in prepared.columns else "DURATION_SEC"
    if duration_col not in prepared.columns:
        prepared[duration_col] = 0
    prepared[duration_col] = pd.to_numeric(prepared[duration_col], errors="coerce").fillna(0)
    if "EST_TOTAL_CREDITS" not in prepared.columns:
        prepared["EST_TOTAL_CREDITS"] = 0
    prepared["EST_TOTAL_CREDITS"] = pd.to_numeric(prepared["EST_TOTAL_CREDITS"], errors="coerce").fillna(0)
    if "STATE" not in prepared.columns:
        prepared["STATE"] = ""
    if "ERROR_CODE" not in prepared.columns:
        prepared["ERROR_CODE"] = ""
    if "PROCEDURE_NAME" not in prepared.columns:
        prepared["PROCEDURE_NAME"] = ""
    if "IMPACT_OBJECTS" not in prepared.columns:
        prepared["IMPACT_OBJECTS"] = ""

    prepared[key_col] = prepared[key_col].fillna("").astype(str).str.strip()
    prepared = prepared[prepared[key_col] != ""]
    if prepared.empty:
        return pd.DataFrame()

    failure_mask = (
        prepared["STATE"].fillna("").astype(str).str.upper().isin(["FAILED", "FAILED_WITH_ERROR"])
        | (prepared["ERROR_CODE"].fillna("").astype(str).str.strip() != "")
    )
    prepared["FAILED_RUN"] = failure_mask.astype(int)

    grouped = prepared.groupby(key_col, dropna=False).agg(
        RUNS=(key_col, "count"),
        FAILURES=("FAILED_RUN", "sum"),
        AVG_DURATION_SEC=(duration_col, "mean"),
        P95_DURATION_SEC=(duration_col, lambda s: float(s.quantile(0.95)) if len(s) else 0.0),
        MAX_DURATION_SEC=(duration_col, "max"),
        EST_CREDITS=("EST_TOTAL_CREDITS", "sum"),
    ).reset_index()
    grouped["PROCEDURE_NAME"] = prepared.groupby(key_col)["PROCEDURE_NAME"].apply(_clean_release_text).values
    grouped["IMPACT_OBJECTS"] = prepared.groupby(key_col)["IMPACT_OBJECTS"].apply(_clean_release_text).values
    grouped = grouped.rename(columns={key_col: "ENTITY"})
    return grouped


def _pct_change(before: float, after: float) -> float:
    before = safe_float(before)
    after = safe_float(after)
    if before == 0:
        return 100.0 if after > 0 else 0.0
    return round((after - before) / before * 100, 1)


def _release_signal(
    row: pd.Series,
    runtime_pct_threshold: float = 25,
    runtime_delta_sec_threshold: float = 30,
    credit_pct_threshold: float = 25,
    credit_delta_threshold: float = 0,
) -> tuple[str, str]:
    failure_delta = safe_int(row.get("FAILURES_DELTA"))
    runtime_pct = safe_float(row.get("AVG_DURATION_CHANGE_PCT"))
    credit_pct = safe_float(row.get("EST_CREDITS_CHANGE_PCT"))
    runtime_delta = safe_float(row.get("AVG_DURATION_DELTA_SEC"))
    credit_delta = safe_float(row.get("EST_CREDITS_DELTA"))

    signals = []
    if failure_delta > 0:
        signals.append(f"{failure_delta} more failures")
    if runtime_pct >= safe_float(runtime_pct_threshold) and runtime_delta >= safe_float(runtime_delta_sec_threshold):
        signals.append(f"runtime +{runtime_pct:.1f}%")
    if credit_pct >= safe_float(credit_pct_threshold) and credit_delta > safe_float(credit_delta_threshold):
        signals.append(f"credits +{credit_pct:.1f}%")
    if not signals:
        return "Stable", "No material release-window regression detected."

    severity = (
        "High"
        if failure_delta > 0
        or runtime_pct >= safe_float(runtime_pct_threshold) * 2
        or credit_pct >= safe_float(credit_pct_threshold) * 2
        else "Medium"
    )
    return severity, "; ".join(signals)


def _compare_release_windows(
    before: pd.DataFrame,
    after: pd.DataFrame,
    key_col: str,
    runtime_pct_threshold: float = 25,
    runtime_delta_sec_threshold: float = 30,
    credit_pct_threshold: float = 25,
    credit_delta_threshold: float = 0,
) -> pd.DataFrame:
    before_agg = _aggregate_release_window(before, key_col)
    after_agg = _aggregate_release_window(after, key_col)
    if before_agg.empty and after_agg.empty:
        return pd.DataFrame()

    merged = before_agg.merge(after_agg, on="ENTITY", how="outer", suffixes=("_BEFORE", "_AFTER")).fillna(0)
    for col in ["PROCEDURE_NAME", "IMPACT_OBJECTS"]:
        before_col = f"{col}_BEFORE"
        after_col = f"{col}_AFTER"
        if before_col not in merged.columns:
            merged[before_col] = ""
        if after_col not in merged.columns:
            merged[after_col] = ""
        merged[col] = [
            _clean_release_text(pd.Series([left, right]))
            for left, right in zip(merged[before_col], merged[after_col])
        ]

    for col in ["RUNS", "FAILURES", "AVG_DURATION_SEC", "P95_DURATION_SEC", "MAX_DURATION_SEC", "EST_CREDITS"]:
        before_col = f"{col}_BEFORE"
        after_col = f"{col}_AFTER"
        if before_col not in merged.columns:
            merged[before_col] = 0
        if after_col not in merged.columns:
            merged[after_col] = 0
        merged[f"{col}_DELTA"] = pd.to_numeric(merged[after_col], errors="coerce").fillna(0) - pd.to_numeric(
            merged[before_col], errors="coerce"
        ).fillna(0)

    merged["AVG_DURATION_CHANGE_PCT"] = [
        _pct_change(before, after)
        for before, after in zip(merged["AVG_DURATION_SEC_BEFORE"], merged["AVG_DURATION_SEC_AFTER"])
    ]
    merged["EST_CREDITS_CHANGE_PCT"] = [
        _pct_change(before, after)
        for before, after in zip(merged["EST_CREDITS_BEFORE"], merged["EST_CREDITS_AFTER"])
    ]
    signal_data = merged.apply(
        _release_signal,
        axis=1,
        runtime_pct_threshold=runtime_pct_threshold,
        runtime_delta_sec_threshold=runtime_delta_sec_threshold,
        credit_pct_threshold=credit_pct_threshold,
        credit_delta_threshold=credit_delta_threshold,
    )
    merged["SEVERITY"] = [item[0] for item in signal_data]
    merged["SIGNAL"] = [item[1] for item in signal_data]
    merged["RUNTIME_THRESHOLD_PCT"] = safe_float(runtime_pct_threshold)
    merged["RUNTIME_DELTA_THRESHOLD_SEC"] = safe_float(runtime_delta_sec_threshold)
    merged["CREDIT_THRESHOLD_PCT"] = safe_float(credit_pct_threshold)
    merged["CREDIT_DELTA_THRESHOLD"] = safe_float(credit_delta_threshold)
    return merged.sort_values(
        by=["SEVERITY", "FAILURES_DELTA", "AVG_DURATION_CHANGE_PCT", "EST_CREDITS_CHANGE_PCT"],
        ascending=[True, False, False, False],
    )


def _prepare_task_release_runs(inventory: pd.DataFrame, history: pd.DataFrame, query_details: pd.DataFrame) -> pd.DataFrame:
    _, _extract_object_candidates, _normalize_query_details, _procedure_from_definition, _ = _task_management_helpers()
    runs = history.copy() if history is not None else pd.DataFrame()
    if runs.empty:
        return runs
    runs.columns = [str(col).upper() for col in runs.columns]
    details = _normalize_query_details(query_details)
    if not details.empty and "QUERY_ID" in runs.columns and "QUERY_ID" in details.columns:
        keep = [
            col for col in [
                "QUERY_ID", "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "DATABASE_NAME", "SCHEMA_NAME",
                "QUERY_ELAPSED_SEC", "CLOUD_CREDITS", "EST_TOTAL_CREDITS", "QUERY_TEXT"
            ] if col in details.columns
        ]
        runs = runs.merge(details[keep], on="QUERY_ID", how="left", suffixes=("", "_QUERY"))
    if "EST_TOTAL_CREDITS" not in runs.columns:
        runs["EST_TOTAL_CREDITS"] = 0.0
    if "QUERY_TEXT" in runs.columns:
        runs["IMPACT_OBJECTS"] = runs["QUERY_TEXT"].apply(_extract_object_candidates)
    else:
        runs["IMPACT_OBJECTS"] = ""

    inv = inventory.copy() if inventory is not None else pd.DataFrame()
    if not inv.empty:
        inv.columns = [str(col).upper() for col in inv.columns]
        name_col = "NAME" if "NAME" in inv.columns else "TASK_NAME" if "TASK_NAME" in inv.columns else ""
        if name_col:
            inv["PROCEDURE_NAME"] = inv.get("DEFINITION", pd.Series([""] * len(inv), index=inv.index)).apply(_procedure_from_definition)
            inv["TASK_IMPACT_OBJECTS"] = inv.get("DEFINITION", pd.Series([""] * len(inv), index=inv.index)).apply(_extract_object_candidates)
            runs = runs.merge(
                inv[[name_col, "PROCEDURE_NAME", "TASK_IMPACT_OBJECTS"]].rename(columns={name_col: "TASK_NAME"}),
                on="TASK_NAME",
                how="left",
            )
            runs["IMPACT_OBJECTS"] = [
                _clean_release_text(pd.Series([query_objects, task_objects]))
                for query_objects, task_objects in zip(runs.get("IMPACT_OBJECTS", ""), runs.get("TASK_IMPACT_OBJECTS", ""))
            ]
    return runs


def _build_procedure_release_sql(session, company: str, start: date, end: date, has_root_query_id: bool) -> str:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    root_expr = "COALESCE(q.root_query_id, q.query_id)" if has_root_query_id else "q.query_id"
    call_wh_size_expr = "warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    child_wh_size_expr = "q.warehouse_size AS warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    child_cloud_expr = (
        "q.credits_used_cloud_services AS credits_used_cloud_services"
        if "CREDITS_USED_CLOUD_SERVICES" in qh_cols else "0::FLOAT AS credits_used_cloud_services"
    )
    call_filters = get_global_filter_clause(
        date_col="",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
        schema_col="schema_name",
    )
    child_filters = get_global_filter_clause(
        date_col="",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
        schema_col="q.schema_name",
    )
    call_window = _release_window_predicate("start_time", start, end)
    child_window = _release_window_predicate("q.start_time", start, end)
    return f"""
        WITH calls AS (
            SELECT query_id AS root_query_id,
                   REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) AS procedure_name,
                   user_name,
                   role_name,
                   warehouse_name,
                   {call_wh_size_expr},
                   start_time,
                   SUBSTR(query_text, 1, 1000) AS call_text
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE query_type = 'CALL'
              AND {call_window}
              {call_filters}
        ),
        children AS (
            SELECT {root_expr} AS root_query_id,
                   q.query_id,
                   q.total_elapsed_time,
                   {child_cloud_expr},
                   {child_wh_size_expr}
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE {child_window}
              {child_filters}
        )
        SELECT c.procedure_name,
               c.root_query_id,
               c.user_name,
               c.role_name,
               c.warehouse_name,
               COALESCE(MAX(ch.warehouse_size), MAX(c.warehouse_size)) AS warehouse_size,
               c.start_time,
               c.call_text,
               COUNT(DISTINCT ch.query_id) AS downstream_query_count,
               SUM(COALESCE(ch.total_elapsed_time, 0)) / 1000 AS total_elapsed_sec,
               SUM(COALESCE(ch.credits_used_cloud_services, 0)) AS cloud_credits
        FROM calls c
        LEFT JOIN children ch ON c.root_query_id = ch.root_query_id
        GROUP BY c.procedure_name, c.root_query_id, c.user_name, c.role_name,
                 c.warehouse_name, c.start_time, c.call_text
        ORDER BY c.start_time DESC
        LIMIT 2000
    """


def _prepare_procedure_release_runs(runs: pd.DataFrame) -> pd.DataFrame:
    _, _extract_object_candidates, _, _, _ = _task_management_helpers()
    _, _, _procedure_run_estimated_credits, _ = _procedure_helpers()
    prepared = runs.copy() if runs is not None else pd.DataFrame()
    if prepared.empty:
        return prepared
    prepared.columns = [str(col).upper() for col in prepared.columns]
    prepared["TOTAL_ELAPSED_SEC"] = pd.to_numeric(prepared.get("TOTAL_ELAPSED_SEC", 0), errors="coerce").fillna(0)
    prepared["CLOUD_CREDITS"] = pd.to_numeric(prepared.get("CLOUD_CREDITS", 0), errors="coerce").fillna(0)
    prepared["EST_TOTAL_CREDITS"] = prepared.apply(_procedure_run_estimated_credits, axis=1)
    prepared["IMPACT_OBJECTS"] = prepared.get("CALL_TEXT", pd.Series([""] * len(prepared), index=prepared.index)).apply(
        _extract_object_candidates
    )
    return prepared


def _build_release_compare_report(company: str, release_data: dict, credit_price: float) -> str:
    task_compare = release_data.get("task_compare", _empty_df())
    proc_compare = release_data.get("procedure_compare", _empty_df())
    before_label = release_data.get("before_label", "before")
    after_label = release_data.get("after_label", "after")
    thresholds = release_data.get("thresholds", {})

    task_regressions = task_compare[task_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])] if not task_compare.empty else pd.DataFrame()
    proc_regressions = proc_compare[proc_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])] if not proc_compare.empty else pd.DataFrame()
    total_credit_delta = (
        safe_float(task_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not task_compare.empty else 0)
        + safe_float(proc_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not proc_compare.empty else 0)
    )
    lines = [
        f"# OVERWATCH Release Compare - {company}",
        "",
        f"- Before window: {before_label}",
        f"- After window: {after_label}",
        (
            "- Thresholds: "
            f"runtime +{safe_float(thresholds.get('runtime_pct_threshold', 25)):,.0f}% "
            f"and +{safe_float(thresholds.get('runtime_delta_sec_threshold', 30)):,.0f}s; "
            f"credits +{safe_float(thresholds.get('credit_pct_threshold', 25)):,.0f}% "
            f"and +{safe_float(thresholds.get('credit_delta_threshold', 0)):,.4f} credits"
        ),
        f"- Task regressions: {len(task_regressions):,}",
        f"- Procedure regressions: {len(proc_regressions):,}",
        f"- Estimated credit delta: {format_credits(total_credit_delta)} (${credits_to_dollars(total_credit_delta, credit_price):,.2f})",
        "",
        "## Highest-Risk Task Changes",
    ]
    if task_regressions.empty:
        lines.append("- No material task runtime/cost/failure regressions detected.")
    else:
        for _, row in task_regressions.head(10).iterrows():
            lines.append(
                f"- {row.get('ENTITY', '')}: {row.get('SIGNAL', '')}; "
                f"after avg {safe_float(row.get('AVG_DURATION_SEC_AFTER')):,.1f}s; "
                f"procedure {row.get('PROCEDURE_NAME', '')}; impact {row.get('IMPACT_OBJECTS', '')}"
            )
    lines.extend(["", "## Highest-Risk Procedure Changes"])
    if proc_regressions.empty:
        lines.append("- No material stored procedure runtime/cost/failure regressions detected.")
    else:
        for _, row in proc_regressions.head(10).iterrows():
            lines.append(
                f"- {row.get('ENTITY', '')}: {row.get('SIGNAL', '')}; "
                f"after avg {safe_float(row.get('AVG_DURATION_SEC_AFTER')):,.1f}s; "
                f"credit delta {format_credits(row.get('EST_CREDITS_DELTA', 0))}"
            )
    return "\n".join(lines)


def _finalize_control_room_data(
    data: dict[str, pd.DataFrame],
    source_rows: list[dict],
    credit_price: float,
    cortex_budget_usd: float,
) -> dict[str, pd.DataFrame]:
    data["_loaded_at"] = pd.DataFrame({"LOADED_AT": [datetime.now().isoformat()]})
    data["_credit_price"] = pd.DataFrame({"CREDIT_PRICE": [credit_price]})
    data["_cortex_budget_usd"] = pd.DataFrame({"BUDGET_USD": [safe_float(cortex_budget_usd)]})
    data["_source_modes"] = pd.DataFrame(source_rows)
    return data


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


def _control_room_score(
    exceptions: pd.DataFrame,
    row: pd.Series | dict,
    credit_delta: float,
    regression_count: int,
    cortex_exception_count: int,
) -> int:
    if exceptions is None or exceptions.empty:
        high_count = medium_count = 0
    else:
        severities = exceptions.get("Severity", pd.Series(dtype=str)).astype(str)
        high_count = int((severities == "High").sum())
        medium_count = int((severities == "Medium").sum())
    failed_queries = safe_int(row.get("FAILED_QUERIES", 0))
    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    remote_spill = safe_int(row.get("REMOTE_SPILL_QUERIES", 0))
    penalty = (
        high_count * 12
        + medium_count * 6
        + min(failed_queries / 10, 10)
        + min(queued_queries / 10, 8)
        + min(remote_spill / 20, 8)
        + min(max(credit_delta, 0) / 5, 10)
        + min(safe_int(regression_count) * 3, 12)
        + min(safe_int(cortex_exception_count) * 2, 10)
    )
    return max(0, min(100, int(round(100 - penalty))))
