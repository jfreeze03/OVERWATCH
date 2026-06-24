"""Shift handoff and DBA morning brief construction and rendering."""
from __future__ import annotations

from datetime import datetime
import streamlit as st
from sections.shell_helpers import (
    _clean_display_text,
    render_shell_snapshot,
)
from utils.primitives import (
    safe_float,
    safe_int,
)
from utils.downloads import (
    download_text,
)
from .types import (
    _canonical_dba_route,
    _command_queue_route,
    _dba_section_proof_required,
    _empty_df,
    _frame_or_empty,
    _jump,
    _row_value,
    normalize_dba_control_room_pane,
    pd,
)
from .queue import (
    _priority_exceptions,
)
from .incidents import (
    _dba_runbook_route_templates,
)
from .types import (
    download_csv,
    render_priority_dataframe,
)

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


def _dba_workload_morning_lanes(
    data: dict | None,
    exceptions: pd.DataFrame | None = None,
    *,
    max_rows: int = 4,
) -> pd.DataFrame:
    """Build workload-specific Daily Brief lanes from already-loaded telemetry."""
    data = data or {}
    summary = data.get("summary", _empty_df())
    row = summary.iloc[0] if summary is not None and not summary.empty else {}
    warehouse_pressure = data.get("warehouse_pressure", _empty_df())
    failed_queries = data.get("failed_queries", _empty_df())
    task_failures = data.get("task_failures", _empty_df())
    task_sla_cost = data.get("task_sla_cost", _empty_df())
    procedure_sla_cost = data.get("procedure_sla_cost", _empty_df())
    task_status_summary = _dba_task_status_task_summary(data)
    exception_context = _normalize_focus_frame(exceptions)

    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    failed_count = safe_int(row.get("FAILED_QUERIES", 0))
    spill_count = safe_int(row.get("REMOTE_SPILL_QUERIES", 0))
    p95_runtime = safe_float(row.get("P95_ELAPSED_SEC", 0))
    if not failed_count and failed_queries is not None and not failed_queries.empty:
        failed_count = len(failed_queries)

    warehouse_count = 0 if warehouse_pressure is None or warehouse_pressure.empty else len(warehouse_pressure)
    queued_warehouses = 0
    remote_spill_gb = 0.0
    if warehouse_pressure is not None and not warehouse_pressure.empty:
        if "QUEUED_QUERIES" in warehouse_pressure.columns:
            queued_warehouses = int(
                (pd.to_numeric(warehouse_pressure["QUEUED_QUERIES"], errors="coerce").fillna(0) > 0).sum()
            )
        if "REMOTE_SPILL_GB" in warehouse_pressure.columns:
            remote_spill_gb = float(pd.to_numeric(warehouse_pressure["REMOTE_SPILL_GB"], errors="coerce").fillna(0).sum())

    rows: list[dict] = []

    def add_lane(
        workflow: str,
        *,
        state: str,
        why_now: str,
        first_move: str,
        proof_required: str,
        priority_score: float,
        owner_route: str = "Workload route / DBA on-call",
        go_no_go: str = "Go only through Workload Operations after telemetry is current.",
        source_signals: str = "DBA Control Room workload telemetry",
        focus_context: dict[str, str] | None = None,
    ) -> None:
        focus_context = focus_context or {}
        rows.append({
            "ROUTE": "Workload Operations",
            "WORKFLOW": workflow,
            "STATE": state,
            "WHY_NOW": why_now,
            "FIRST_MOVE": first_move,
            "OWNER_ROUTE": owner_route,
            "GO_NO_GO": go_no_go,
            "PROOF_REQUIRED": proof_required,
            "SOURCE_SIGNALS": source_signals,
            "PRIORITY_SCORE": safe_float(priority_score),
            "FOCUS_QUERY_ID": str(focus_context.get("FOCUS_QUERY_ID", "")),
            "FOCUS_WAREHOUSE": str(focus_context.get("FOCUS_WAREHOUSE", "")),
            "FOCUS_USER": str(focus_context.get("FOCUS_USER", "")),
            "FOCUS_OBJECT": str(focus_context.get("FOCUS_OBJECT", "")),
            "FOCUS_REASON": str(focus_context.get("FOCUS_REASON", "")),
        })

    if task_failures is not None and not task_failures.empty:
        task_names = ", ".join(
            dict.fromkeys(
                task_failures.get("TASK_NAME", pd.Series(dtype=str)).dropna().astype(str).head(3)
            )
        )
        add_lane(
            "Pipeline & Task Health",
            state="Blocked Workload",
            why_now=f"{len(task_failures):,} failed task group(s){f': {task_names}' if task_names else ''}.",
            first_move=(
                "Open Pipeline & Task Health, inspect the latest TASK_HISTORY failure, confirm Snowflake task downstream state, "
                "then protect late SLAs before retrying."
            ),
            proof_required="TASK_HISTORY success after latest failure, Snowflake task rerun/late state, and downstream refresh status.",
            priority_score=96,
            owner_route="Task route / Snowflake task operator / DBA on-call",
            go_no_go="No-Go for dependent loads until clean rerun and downstream status are current.",
            source_signals="Task failures: mart/TASK_HISTORY",
        )

    if (
        (task_failures is None or task_failures.empty)
        and task_status_summary.get("loaded")
        and (
            safe_int(task_status_summary.get("task_status_failures"))
            or safe_int(task_status_summary.get("task_status_late"))
            or safe_int(task_status_summary.get("task_status_alerts"))
            or safe_int(task_status_summary.get("task_status_watch"))
        )
    ):
        task_status_rows = safe_int(task_status_summary.get("task_status_rows"))
        task_status_failures = safe_int(task_status_summary.get("task_status_failures"))
        task_status_late = safe_int(task_status_summary.get("task_status_late"))
        task_status_alerts = safe_int(task_status_summary.get("task_status_alerts"))
        task_status_watch = safe_int(task_status_summary.get("task_status_watch"))
        last_seen = str(task_status_summary.get("last_seen") or "").strip()
        if task_status_failures:
            state = "Blocked Scheduler Work"
            priority = 97
            go_no_go = "No-Go for dependent loads until failed/blocked Snowflake task jobs are explained and recovered."
        elif task_status_late:
            state = "Scheduler SLA Risk"
            priority = 92
            go_no_go = "No-Go for SLA-complete claims until late or missed Snowflake task jobs are closed or rerouted."
        elif task_status_alerts:
            state = "Scheduler Alert"
            priority = 86
            go_no_go = "Go only after high-severity Snowflake task alert rows have DBA acknowledgement."
        else:
            state = "Scheduler Watch"
            priority = 74
            go_no_go = "Go for monitoring; escalate if watch rows become failed, blocked, late, or missed."
        evidence_bits = [
            f"feed rows={task_status_rows:,}",
            f"failed/blocked={task_status_failures:,}",
            f"late/missed={task_status_late:,}",
            f"alerts={task_status_alerts:,}",
            f"watch={task_status_watch:,}",
        ]
        if last_seen:
            evidence_bits.append(f"last_seen={last_seen}")
        add_lane(
            "Pipeline & Task Health",
            state=state,
            why_now=f"Snowflake TASK_HISTORY: {'; '.join(evidence_bits)}.",
            first_move=(
                "Open Pipeline & Task Health, match the Snowflake task job/run state to Snowflake TASK_HISTORY, identify downstream "
                "SLA impact, then choose retry, reroute, or hold only with review status."
            ),
            proof_required=(
                "Snowflake TASK_HISTORY run/status, downstream dependency/SLA impact, "
                "review status, and recovery SLA telemetry."
            ),
            priority_score=priority,
            owner_route="Snowflake task operator / task route / DBA on-call",
            go_no_go=go_no_go,
            source_signals="Snowflake TASK_HISTORY summary",
        )

    if task_sla_cost is not None and not task_sla_cost.empty:
        signals = task_sla_cost.get("SIGNAL", pd.Series(dtype=str)).astype(str)
        sla_count = int((signals == "Long Running / SLA Risk").sum())
        cost_count = int((signals == "Cost Drift / Release Regression").sum())
        add_lane(
            "Pipeline & Task Health",
            state="SLA Risk",
            why_now=f"{sla_count:,} runtime breach(es); {cost_count:,} cost regression candidate(s).",
            first_move="Compare current task graph runs to baseline, isolate the changed task/query, and assign route status.",
            proof_required="Task baseline comparison, latest successful run, cost/runtime delta, and review status for schedule changes.",
            priority_score=90 if cost_count or sla_count >= 3 else 76,
            owner_route="Task graph route / DBA release reviewer",
            source_signals="Task SLA/cost telemetry",
        )

    if queued_queries or queued_warehouses or warehouse_count:
        contention_context = _first_focus_context(
            exception_context,
            tokens=("LOCK", "BLOCK", "CONTENTION", "QUEUE"),
            numeric_columns=("BLOCKED_SEC", "BLOCKED_SECONDS", "TRANSACTION_BLOCKED_TIME"),
            reason="Morning contention focus",
        )
        warehouse_context = _top_warehouse_focus_context(
            warehouse_pressure,
            reason="Morning warehouse pressure focus",
        )
        contention_context = {**warehouse_context, **{k: v for k, v in contention_context.items() if str(v).strip()}}
        add_lane(
            "Contention Center",
            state="Contention Triage",
            why_now=(
                f"{queued_queries:,} queued query row(s); {queued_warehouses:,} queued warehouse(s); "
                f"{warehouse_count:,} pressure row(s)."
            ),
            first_move=(
                "Open Contention Center before resizing: check active locks, task overlap, long DML, "
                "then separate lock waits from warehouse queueing."
            ),
            proof_required="SHOW LOCKS/LOCK_WAIT_HISTORY, task-overlap telemetry, QUERY_HISTORY blocked seconds, and WAREHOUSE_LOAD_HISTORY.",
            priority_score=94 if queued_queries >= 20 or queued_warehouses else 82,
            owner_route="DBA on-call / workload route / warehouse route",
            go_no_go="No-Go for warehouse resizing until lock waits and overlapping writers are ruled out.",
            source_signals="Warehouse pressure and queue telemetry",
            focus_context=contention_context,
        )

    if failed_count or spill_count or remote_spill_gb or p95_runtime >= 120:
        query_context = _first_focus_context(
            failed_queries,
            tokens=("FAILED", "ERROR", "SPILL", "SLOW", "SCAN"),
            numeric_columns=("REMOTE_SPILL_GB", "ELAPSED_SEC", "ELAPSED_SECONDS"),
            reason="Morning query diagnosis focus",
        ) or _first_focus_context(
            exception_context,
            tokens=("FAILED", "ERROR", "SPILL", "SLOW", "SCAN"),
            numeric_columns=("REMOTE_SPILL_GB", "ELAPSED_SEC", "ELAPSED_SECONDS"),
            reason="Morning query diagnosis focus",
        )
        reason_bits = []
        if failed_count:
            reason_bits.append(f"{failed_count:,} failed query row(s)")
        if spill_count:
            reason_bits.append(f"{spill_count:,} remote-spill query row(s)")
        if remote_spill_gb:
            reason_bits.append(f"{remote_spill_gb:,.2f} GB remote spill")
        if p95_runtime >= 120:
            reason_bits.append(f"p95 {p95_runtime:,.0f}s")
        add_lane(
            "Query Investigation",
            state="Query Investigation",
            why_now="; ".join(reason_bits) or "Slow or failed query telemetry needs diagnosis.",
            first_move=(
                "Open Query Investigation, load the query ID/operator stats, then use AI-assisted diagnosis only after "
                "queue/spill/scan telemetry is current."
            ),
            proof_required="Query ID, warehouse/user/role/database context, operator stats, specific recommendation, and rerun comparison.",
            priority_score=88 if failed_count >= 10 or spill_count or p95_runtime >= 300 else 72,
            owner_route="Query route / DBA performance reviewer",
            source_signals="Failed, spilling, or long-running query telemetry",
            focus_context=query_context,
        )

    if procedure_sla_cost is not None and not procedure_sla_cost.empty:
        signals = procedure_sla_cost.get("SIGNAL", pd.Series(dtype=str)).astype(str)
        runtime_count = int((signals == "Procedure Runtime SLA Breach").sum())
        cost_count = int((signals == "Procedure Cost Regression").sum())
        add_lane(
            "Stored procedures",
            state="Procedure Regression",
            why_now=f"{runtime_count:,} runtime breach(es); {cost_count:,} cost regression candidate(s).",
            first_move="Open Stored procedures, compare latest CALL duration/cost to baseline, and confirm release linkage.",
            proof_required="Procedure run baseline, latest CALL query ID, route, ticket/change ID, and post-fix runtime/cost telemetry.",
            priority_score=84 if cost_count or runtime_count >= 3 else 70,
            owner_route="Procedure route / DBA release reviewer",
            source_signals="Stored procedure SLA/cost telemetry",
        )

    if not rows:
        return _empty_df()
    return pd.DataFrame(rows).sort_values(
        ["PRIORITY_SCORE", "WORKFLOW"],
        ascending=[False, True],
    ).head(max_rows).reset_index(drop=True)


def _dba_morning_brief_rows(
    priority_index: pd.DataFrame | None,
    escalation_packet: pd.DataFrame | None,
    handoff_rows: pd.DataFrame | None,
    workload_lanes: pd.DataFrame | None = None,
    *,
    max_rows: int = 5,
) -> pd.DataFrame:
    """Create a concise morning operating brief from loaded Control Room telemetry."""
    rows: list[dict] = []
    seen_routes: set[str] = set()

    def add_row(
        route: object,
        *,
        state: object,
        why_now: object,
        first_move: object,
        owner_route: object = "",
        go_no_go: object = "",
        proof_required: object = "",
        source_signals: object = "",
        priority_score: object = 0,
        workflow: object = "",
        focus_query_id: object = "",
        focus_warehouse: object = "",
        focus_user: object = "",
        focus_object: object = "",
        focus_reason: object = "",
    ) -> None:
        route_text = str(route or "DBA Control Room").strip() or "DBA Control Room"
        workflow_text = str(workflow or "").strip()
        route_key = f"{route_text.upper()}|{workflow_text.upper()}" if workflow_text else route_text.upper()
        if route_key in seen_routes:
            return
        seen_routes.add(route_key)
        rows.append({
            "MORNING_RANK": 0,
            "ROUTE": route_text,
            "WORKFLOW": workflow_text,
            "STATE": str(state or "Review"),
            "WHY_NOW": str(why_now or "Loaded Control Room telemetry requires review."),
            "FIRST_MOVE": str(first_move or "Open the guarded drilldown workflow and validate telemetry."),
            "OWNER_ROUTE": str(owner_route or _dba_runbook_route_templates(route_text, 24)["owner_route"]),
            "GO_NO_GO": str(go_no_go or "Go only through the guarded drilldown workflow."),
            "PROOF_REQUIRED": str(proof_required or _dba_section_proof_required(route_text)),
            "SOURCE_SIGNALS": str(source_signals or "Control Room"),
            "PRIORITY_SCORE": safe_float(priority_score),
            "FOCUS_QUERY_ID": str(focus_query_id or ""),
            "FOCUS_WAREHOUSE": str(focus_warehouse or ""),
            "FOCUS_USER": str(focus_user or ""),
            "FOCUS_OBJECT": str(focus_object or ""),
            "FOCUS_REASON": str(focus_reason or ""),
        })

    packet = escalation_packet.copy() if escalation_packet is not None and not escalation_packet.empty else _empty_df()
    if not packet.empty:
        packet.columns = [str(col).upper() for col in packet.columns]
        sort_cols = [col for col in ["PRIORITY_SCORE", "ROUTE"] if col in packet.columns]
        ordered_packet = packet.sort_values(sort_cols, ascending=[False, True][: len(sort_cols)]) if sort_cols else packet
        for _, item in ordered_packet.iterrows():
            add_row(
                item.get("ROUTE"),
                state=item.get("ESCALATION_LEVEL") or item.get("STATE"),
                why_now=item.get("WHY_NOW") or item.get("EVIDENCE_PACKET"),
                first_move=item.get("FIRST_MOVE"),
                owner_route=item.get("OWNER_ROUTE"),
                go_no_go=item.get("GO_NO_GO"),
                proof_required=item.get("PROOF_REQUIRED"),
                source_signals=item.get("SOURCE_SIGNALS"),
                priority_score=item.get("PRIORITY_SCORE"),
                workflow=item.get("WORKFLOW"),
                focus_query_id=item.get("FOCUS_QUERY_ID"),
                focus_warehouse=item.get("FOCUS_WAREHOUSE"),
                focus_user=item.get("FOCUS_USER"),
                focus_object=item.get("FOCUS_OBJECT"),
                focus_reason=item.get("FOCUS_REASON"),
            )

    workload = workload_lanes.copy() if workload_lanes is not None and not workload_lanes.empty else _empty_df()
    if not workload.empty:
        workload.columns = [str(col).upper() for col in workload.columns]
        sort_cols = [col for col in ["PRIORITY_SCORE", "WORKFLOW"] if col in workload.columns]
        ordered_workload = workload.sort_values(sort_cols, ascending=[False, True][: len(sort_cols)]) if sort_cols else workload
        for _, item in ordered_workload.iterrows():
            add_row(
                item.get("ROUTE") or "Workload Operations",
                state=item.get("STATE"),
                why_now=item.get("WHY_NOW"),
                first_move=item.get("FIRST_MOVE"),
                owner_route=item.get("OWNER_ROUTE"),
                go_no_go=item.get("GO_NO_GO"),
                proof_required=item.get("PROOF_REQUIRED"),
                source_signals=item.get("SOURCE_SIGNALS"),
                priority_score=item.get("PRIORITY_SCORE"),
                workflow=item.get("WORKFLOW"),
                focus_query_id=item.get("FOCUS_QUERY_ID"),
                focus_warehouse=item.get("FOCUS_WAREHOUSE"),
                focus_user=item.get("FOCUS_USER"),
                focus_object=item.get("FOCUS_OBJECT"),
                focus_reason=item.get("FOCUS_REASON"),
            )

    priority = priority_index.copy() if priority_index is not None and not priority_index.empty else _empty_df()
    if not priority.empty:
        priority.columns = [str(col).upper() for col in priority.columns]
        sort_cols = [col for col in ["PRIORITY_SCORE", "SECTION"] if col in priority.columns]
        ordered_priority = priority.sort_values(sort_cols, ascending=[False, True][: len(sort_cols)]) if sort_cols else priority
        for _, item in ordered_priority.iterrows():
            add_row(
                item.get("SECTION"),
                state=item.get("OPERATIONS_PRIORITY_STATE"),
                why_now=item.get("WHY_NOW") or item.get("WORST_SIGNAL"),
                first_move=item.get("FIRST_MOVE"),
                go_no_go="Go only through the owning specialist workflow.",
                proof_required=item.get("PROOF_REQUIRED"),
                source_signals=f"Operations Priority: {item.get('WORST_SIGNAL') or item.get('WHY_NOW') or item.get('SECTION')}",
                priority_score=item.get("PRIORITY_SCORE"),
            )

    handoff = handoff_rows.copy() if handoff_rows is not None and not handoff_rows.empty else _empty_df()
    if not handoff.empty:
        handoff.columns = [str(col).upper() for col in handoff.columns]
        rank = pd.to_numeric(handoff.get("PRIORITY_RANK", pd.Series([9] * len(handoff))), errors="coerce").fillna(9)
        important = handoff.assign(_MORNING_SORT=rank).sort_values(["_MORNING_SORT", "LANE"], ascending=[True, True])
        for _, item in important.iterrows():
            lane = str(item.get("LANE") or "DBA Control Room")
            go_no_go = (
                "No-Go until handoff blocker telemetry is current."
                if safe_int(item.get("_MORNING_SORT"), 9) <= 1
                else "Go for DBA review through the routed workflow."
            )
            add_row(
                lane,
                state=item.get("STATE"),
                why_now=item.get("EVIDENCE"),
                first_move=item.get("NEXT_ACTION"),
                owner_route=item.get("OWNER_OR_ROUTE"),
                go_no_go=go_no_go,
                proof_required=item.get("PROOF_REQUIRED"),
                source_signals=f"Shift Handoff: {item.get('SOURCE') or lane}",
                priority_score=max(0, 70 - safe_int(item.get("_MORNING_SORT"), 9) * 10),
            )

    if not rows:
        add_row(
            "DBA Control Room",
            state="Monitor",
            why_now="No loaded blocker, escalation, or handoff row for the current scope.",
            first_move="Keep Morning Cockpit current and review Alert Center for newly routed issues.",
            owner_route="On-call DBA / platform route",
            go_no_go="Go for monitoring only.",
            proof_required="fresh Control Room load and current Alert Center review",
            source_signals="Daily Brief: routine watch",
            priority_score=0,
        )

    result = pd.DataFrame(rows).sort_values(
        ["PRIORITY_SCORE", "ROUTE", "WORKFLOW"],
        ascending=[False, True, True],
    ).head(max_rows).reset_index(drop=True)
    result["MORNING_RANK"] = range(1, len(result) + 1)
    result = _add_dba_morning_decision_contract(result)
    return result


def _dba_morning_decision_contract(row: dict | pd.Series | None) -> dict[str, str]:
    """Return the operator contract for one Daily Brief row."""
    row = row if row is not None else {}
    state = str(_row_value(row, "STATE", default="Review") or "Review")
    route = str(_row_value(row, "ROUTE", default="DBA Control Room") or "DBA Control Room")
    workflow = str(_row_value(row, "WORKFLOW", default="") or "").strip()
    go_no_go = str(_row_value(row, "GO_NO_GO", default="") or "")
    proof = str(_row_value(row, "PROOF_REQUIRED", default="") or "")
    owner = str(_row_value(row, "OWNER_ROUTE", default="") or "")
    score = safe_float(_row_value(row, "PRIORITY_SCORE", default=0))
    combined = f"{state} {go_no_go} {proof}".upper()

    if "NO-GO" in combined or "ESCALATE NOW" in combined or score >= 95:
        decision = "No-Go / contain now"
        sla_clock = "15 min containment; 30 min route update"
        next_checkpoint = "Confirm blocker route, telemetry source, and containment path before lower-priority work."
        stop_rule = "Do not release, resize, close, or retry until blocker telemetry is current."
    elif any(token in combined for token in ("BLOCKED", "OVERDUE", "UNAVAILABLE", "STALE")) or score >= 85:
        decision = "Contain same shift"
        sla_clock = "30 min triage; same-shift mitigation"
        next_checkpoint = "Assign DBA route and determine whether this is service risk, source drift, or queue backlog."
        stop_rule = "Do not close the route until ticket and telemetry status are present."
    elif any(token in combined for token in ("SLA", "RISK", "REVIEW", "DIAGNOSIS", "CONTENTION")) or score >= 70:
        decision = "Triage today"
        sla_clock = "Same business day"
        next_checkpoint = "Load the guarded drilldown workflow and inspect the first telemetry row before changing settings."
        stop_rule = "Do not make state-changing fixes from the brief alone."
    else:
        decision = "Monitor"
        sla_clock = "Next DBA review"
        next_checkpoint = "Keep Morning Cockpit and Alert Center current."
        stop_rule = "Escalate only if new telemetry raises the route priority."

    proof_l = proof.lower()
    owner_l = owner.lower()
    proof_tokens = (
        "route", "review", "ticket", "telemetry", "query", "source",
        "current", "fresh", "rollback", "status", "ledger",
    )
    owner_named = bool(owner.strip()) and owner_l not in {"nan", "none", "unassigned"}
    proof_named = any(token in proof_l for token in proof_tokens)
    if owner_named and proof_named:
        owner_proof_state = "Route/telemetry named"
    elif owner_named:
        owner_proof_state = "Telemetry gap"
    elif proof_named:
        owner_proof_state = "Route gap"
    else:
        owner_proof_state = "Route/telemetry gap"

    route_action = f"Open {route}{f' / {workflow}' if workflow else ''}; keep execution, rollback, and telemetry in the guarded drilldown workflow."
    return {
        "MORNING_DECISION": decision,
        "SLA_CLOCK": sla_clock,
        "OWNER_PROOF_STATE": owner_proof_state,
        "ROUTE_TELEMETRY_STATE": owner_proof_state,
        "ROUTE_ACTION": route_action,
        "NEXT_CHECKPOINT": next_checkpoint,
        "STOP_RULE": stop_rule,
    }


def _add_dba_morning_decision_contract(brief: pd.DataFrame) -> pd.DataFrame:
    """Attach concise decision metadata to Daily Brief rows."""
    if brief is None or brief.empty:
        return _empty_df()
    view = brief.copy()
    contracts = [
        _dba_morning_decision_contract(row)
        for row in view.to_dict("records")
    ]
    contract_df = pd.DataFrame(contracts)
    for column in contract_df.columns:
        view[column] = contract_df[column].values
    execution_contracts = [
        _dba_morning_execution_contract(row)
        for row in view.to_dict("records")
    ]
    execution_df = pd.DataFrame(execution_contracts)
    for column in execution_df.columns:
        view[column] = execution_df[column].values
    return view


def _dba_morning_execution_contract(row: dict | pd.Series | None) -> dict[str, str]:
    """Return review, telemetry, status, and execution boundaries for one morning row."""
    row = row if row is not None else {}
    route = str(_row_value(row, "ROUTE", default="DBA Control Room") or "DBA Control Room")
    workflow = str(_row_value(row, "WORKFLOW", default="") or "").strip()
    state = str(_row_value(row, "STATE", default="Review") or "Review")
    first_move = str(_row_value(row, "FIRST_MOVE", default="Open the guarded drilldown workflow and validate telemetry.") or "")
    proof = str(_row_value(row, "PROOF_REQUIRED", default="fresh source telemetry") or "")
    owner = str(_row_value(row, "OWNER_ROUTE", default="DBA on-call") or "DBA on-call")
    focus_query = str(_row_value(row, "FOCUS_QUERY_ID", default="") or "").strip()
    focus_warehouse = str(_row_value(row, "FOCUS_WAREHOUSE", default="") or "").strip()
    focus_object = str(_row_value(row, "FOCUS_OBJECT", default="") or "").strip()

    approval_gate = f"{owner} review and telemetry status before operational change."
    evidence_package = proof or "current source telemetry, route, ticket, and status."
    verify_next = "Re-open the guarded drilldown workflow and confirm the signal cleared before closing the row."
    execution_boundary = "Daily Brief is routing only; execute reviewed changes inside the guarded drilldown workflow."

    if workflow == "Contention Center":
        try:
            from sections.contention_center import build_contention_safe_action_contract

            contention_row = {
                "SIGNAL": "Blocked query / lock contention",
                "QUERY_ID": focus_query,
                "WAREHOUSE_NAME": focus_warehouse,
                "TARGET_OBJECT": focus_object,
                "OWNER_ROUTE": "Contention Center",
                "BLOCKED_SECONDS": 1 if focus_query else 0,
            }
            contract = build_contention_safe_action_contract(contention_row, "Blocked query / lock contention")
            approval_gate = str(contract.get("REVIEW_GATE") or contract.get("APPROVAL_GATE") or approval_gate)
            evidence_package = str(contract.get("AUDIT_EVIDENCE_REQUIRED") or evidence_package)
            verify_next = str(contract.get("RECOVERY_PLAN") or contract.get("VERIFY_AFTER_CLEANUP") or verify_next)
            execution_boundary = str(contract.get("EXECUTION_BOUNDARY") or execution_boundary)
        except Exception:
            approval_gate = "DBA on-call review and incident/ticket status before cancel/abort/schedule action."
            evidence_package = "SHOW LOCKS, LOCK_WAIT_HISTORY, blocked query, target object, telemetry, and post-action status."
            verify_next = "Confirm blocked seconds stop increasing and dependent workload recovers before closure."
            execution_boundary = "No cleanup from Daily Brief; open Contention Center for governed SQL and telemetry review."
    elif workflow in {"Task graphs", "Pipeline & Task Health"}:
        approval_gate = "Snowflake task operator and DBA on-call review before retry, resume, or schedule change."
        evidence_package = (
            "TASK_HISTORY failure/recovery rows, Snowflake task failed/blocked/late state, telemetry, "
            "downstream refresh status, and recovery SLA status."
        )
        verify_next = (
            "Confirm next TASK_HISTORY run succeeded, Snowflake task job is closed or rerouted, and recovery SLA status "
            "is present."
        )
        execution_boundary = "No task retry/resume from the daily brief; use Pipeline & Task Health guarded controls and status prechecks."
    elif workflow in {"Query diagnosis", "Query Investigation"}:
        approval_gate = "DBA performance review before SQL, clustering, or warehouse changes."
        evidence_package = (
            "Query ID, query text/profile, operator stats, warehouse/user/role/database context, and deterministic "
            "optimization finding."
        )
        verify_next = "Compare rerun elapsed time, queue, spill, scan, and cost against the original query telemetry."
        execution_boundary = "Query Investigation is advisory; no query changes are executed from the brief."
    elif workflow == "Stored procedures":
        approval_gate = "Procedure route and DBA release review before procedure or schedule changes."
        evidence_package = "Procedure run baseline, latest CALL query ID, change/ticket context, telemetry, and rollback path."
        verify_next = "Confirm latest CALL returns inside runtime/cost baseline and dependent task graph remains clean."
        execution_boundary = "Do not alter procedure code from Daily Brief; route through Stored procedures and Security Monitoring."
    elif route == "Security Monitoring":
        approval_gate = "DBA access review and telemetry status before access remediation."
        evidence_package = "Grant diff, requester context, least-privilege check, rollback plan, and post-action telemetry."
        verify_next = "Reload security telemetry; grant, role, and login signals must show the intended state."
        execution_boundary = "Do not execute access changes from Daily Brief; use Security Monitoring for telemetry and reviewed commands."
    elif route in {"Warehouse Health", "Cost & Contract"}:
        approval_gate = "DBA capacity review before resize, isolation, or monitor changes."
        evidence_package = "Warehouse load, queue/spill trend, metering impact, telemetry, rollback setting, and post-change status."
        verify_next = "Confirm queued load, spill, and cost movement after the capacity or isolation decision."
        execution_boundary = "No warehouse setting changes from Daily Brief; use Cost & Contract guarded capacity workflow."

    closure_rule = (
        f"{state}: keep this row open until review telemetry package and status are current."
        if state not in {"Monitor", "Ready"}
        else "Close only after the next DBA review confirms no new exception telemetry."
    )
    return {
        "APPROVAL_GATE": approval_gate,
        "EVIDENCE_PACKAGE": evidence_package,
        "VERIFY_NEXT": verify_next,
        "EXECUTION_BOUNDARY": execution_boundary,
        "CLOSURE_RULE": closure_rule,
    }


def _dba_morning_focus_note(row: dict | pd.Series | None) -> str:
    row = row if row is not None else {}
    parts = [
        ("query", _row_value(row, "FOCUS_QUERY_ID", default="")),
        ("warehouse", _row_value(row, "FOCUS_WAREHOUSE", default="")),
        ("user", _row_value(row, "FOCUS_USER", default="")),
        ("object", _row_value(row, "FOCUS_OBJECT", default="")),
        ("reason", _row_value(row, "FOCUS_REASON", default="")),
    ]
    return "; ".join(
        f"{label}={str(value).strip()}"
        for label, value in parts
        if str(value or "").strip()
    )


def _dba_morning_command_queue(brief: pd.DataFrame | None, max_rows: int = 3) -> pd.DataFrame:
    """Return the compact first-screen command queue for the DBA Daily Brief."""
    if brief is None or brief.empty:
        return _empty_df()
    view = brief.copy()
    if "MORNING_RANK" in view.columns:
        view = view.sort_values("MORNING_RANK", ascending=True)
    rows: list[dict[str, object]] = []
    for _, row in view.head(max_rows).iterrows():
        route = str(row.get("ROUTE") or "DBA Control Room").strip()
        workflow = str(row.get("WORKFLOW") or "").strip()
        focus = _dba_morning_focus_note(row)
        rows.append({
            "MORNING_RANK": safe_int(row.get("MORNING_RANK")),
            "MORNING_DECISION": _clean_display_text(row.get("MORNING_DECISION", "")),
            "TARGET": _clean_display_text(f"{route} / {workflow}" if workflow else route),
            "ACTION": _clean_display_text(row.get("FIRST_MOVE", "")),
            "SLA_CLOCK": _clean_display_text(row.get("SLA_CLOCK", "")),
            "FOCUS": focus or "No focused query/object",
            "GATE": _clean_display_text(row.get("GO_NO_GO") or row.get("STOP_RULE", "")),
            "APPROVAL_GATE": _clean_display_text(row.get("APPROVAL_GATE", "")),
            "EVIDENCE_PACKAGE": _clean_display_text(row.get("EVIDENCE_PACKAGE", "")),
            "VERIFY_NEXT": _clean_display_text(row.get("VERIFY_NEXT", "")),
            "EXECUTION_BOUNDARY": _clean_display_text(row.get("EXECUTION_BOUNDARY", "")),
            "ROUTE_TELEMETRY_STATE": _clean_display_text(
                row.get("ROUTE_TELEMETRY_STATE", row.get("OWNER_PROOF_STATE", ""))
            ),
            "SOURCE_SIGNALS": _clean_display_text(row.get("SOURCE_SIGNALS", "")),
        })
    return pd.DataFrame(rows)


def _dba_morning_brief_detail_view(brief: pd.DataFrame | None) -> pd.DataFrame:
    """Return Daily Brief detail rows with unique operator-facing columns."""
    if brief is None or brief.empty:
        return _empty_df()
    brief_view = brief.copy()
    for column in list(brief_view.columns):
        if brief_view[column].dtype == object:
            brief_view[column] = brief_view[column].map(_clean_display_text)
    rename_pairs = (
        ("OWNER_PROOF_STATE", "ROUTE_TELEMETRY_STATE"),
        ("OWNER_ROUTE", "ESCALATION_ROUTE"),
    )
    for source, target in rename_pairs:
        if target in brief_view.columns:
            brief_view = brief_view.drop(columns=[source], errors="ignore")
        else:
            brief_view = brief_view.rename(columns={source: target})
    return brief_view.loc[:, ~brief_view.columns.duplicated()]


def _build_dba_morning_brief_markdown(
    brief: pd.DataFrame,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
) -> str:
    """Create a concise markdown packet for the DBA morning brief."""
    rows = brief if brief is not None and not brief.empty else _empty_df()
    lines = [
        "# OVERWATCH DBA Daily Brief",
        f"Scope: {company} / {environment} / {safe_int(lookback_hours, 24)}h",
        "Mode: Telemetry-ranked operating brief",
        "",
    ]
    if rows.empty:
        lines.append("- No morning brief rows were available.")
    else:
        for _, row in rows.sort_values("MORNING_RANK").iterrows():
            workflow = _clean_display_text(row.get("WORKFLOW", "")).strip()
            workflow_note = f" / {workflow}" if workflow else ""
            focus_note = _dba_morning_focus_note(row)
            focus_sentence = f" Target signal: {focus_note}." if focus_note else ""
            lines.append(
                f"- {safe_int(row.get('MORNING_RANK'))}. [{_clean_display_text(row.get('STATE', ''))}] "
                f"{_clean_display_text(row.get('ROUTE', ''))}{workflow_note}: {_clean_display_text(row.get('FIRST_MOVE', ''))} "
                f"Decision: {_clean_display_text(row.get('MORNING_DECISION', ''))}. "
                f"SLA: {_clean_display_text(row.get('SLA_CLOCK', ''))}. "
                f"Why: {_clean_display_text(row.get('WHY_NOW', ''))}. "
                f"Gate: {_clean_display_text(row.get('GO_NO_GO', ''))}. "
                f"Telemetry basis: {_clean_display_text(row.get('PROOF_REQUIRED', ''))}. "
                f"Review gate: {_clean_display_text(row.get('APPROVAL_GATE', ''))}. "
                f"Telemetry package: {_clean_display_text(row.get('EVIDENCE_PACKAGE', ''))}. "
                f"Confirm next: {_clean_display_text(row.get('VERIFY_NEXT', ''))}. "
                f"Boundary: {_clean_display_text(row.get('EXECUTION_BOUNDARY', ''))}. "
                f"Stop: {_clean_display_text(row.get('STOP_RULE', ''))}."
                f"{focus_sentence}"
            )
    lines.extend([
        "",
        "Rules:",
        "- No irreversible DBA action from the brief alone.",
        "- Use the guarded drilldown workflow for execution, rollback, and telemetry review.",
        "- Treat No-Go rows as blocked until source telemetry is current.",
    ])
    return "\n".join(lines).strip()


def _seed_dba_morning_route_context(row: dict | pd.Series | None) -> None:
    """Carry Daily Brief context into the guarded drilldown before navigation."""
    row = row if row is not None else {}
    workflow = str(_row_value(row, "WORKFLOW", default="") or "").strip()
    query_id = str(_row_value(row, "FOCUS_QUERY_ID", default="") or "").strip()
    warehouse = str(_row_value(row, "FOCUS_WAREHOUSE", default="") or "").strip()
    user = str(_row_value(row, "FOCUS_USER", default="") or "").strip()
    target_object = str(_row_value(row, "FOCUS_OBJECT", default="") or "").strip()

    if warehouse:
        st.session_state["global_warehouse"] = warehouse
        st.session_state["wh_filter"] = warehouse
    if user:
        st.session_state["global_user"] = user
    if workflow == "Contention Center":
        st.session_state["contention_center_view"] = "Brief"
        st.session_state["contention_active_view"] = "Brief"
        if query_id:
            st.session_state["contention_focus_query_id"] = query_id
        if warehouse:
            st.session_state["contention_live_warehouse"] = warehouse
    elif workflow in {"Query diagnosis", "Query Investigation"}:
        if query_id:
            st.session_state["query_analysis_active_view"] = "History Search"
            st.session_state["qs_text"] = query_id
            st.session_state["qs_status"] = "ALL"
            st.session_state["qs_autorun"] = True
            st.session_state["ai_query_id"] = query_id
        if target_object:
            st.session_state["ai_object_ctx"] = target_object


def _render_dba_morning_brief(brief: pd.DataFrame, markdown: str) -> None:
    if brief is None or brief.empty:
        return
    top = brief.iloc[0]
    st.markdown("**DBA Daily Brief**")
    render_shell_snapshot((
        ("First Route", str(top.get("ROUTE") or "DBA Control Room")),
        ("No-Go", f"{int(brief['GO_NO_GO'].astype(str).str.contains('No-Go', case=False, regex=False).sum()):,}"),
        ("Escalate Now", f"{int(brief['STATE'].astype(str).eq('Escalate Now').sum()):,}"),
        ("Routes", f"{len(brief):,}"),
    ))
    command_queue = _dba_morning_command_queue(brief)
    render_priority_dataframe(
        command_queue,
        title="Morning command queue",
        priority_columns=[
            "MORNING_RANK", "MORNING_DECISION", "TARGET", "ACTION",
            "SLA_CLOCK", "FOCUS", "APPROVAL_GATE", "VERIFY_NEXT",
            "EXECUTION_BOUNDARY", "ROUTE_TELEMETRY_STATE",
        ],
        sort_by=["MORNING_RANK"],
        ascending=[True],
        raw_label="All morning command rows",
        height=220,
        max_rows=3,
    )
    first_moves = brief.head(3)
    move_cols = st.columns(max(1, len(first_moves)))
    for idx, (_, row) in enumerate(first_moves.iterrows()):
        route = str(row.get("ROUTE") or "DBA Control Room")
        workflow = str(row.get("WORKFLOW") or "").strip()
        label = f"Open {workflow or route}"
        focus_note = _dba_morning_focus_note(row)
        help_lines = [
            f"{row.get('STATE', 'Review')}: {row.get('WHY_NOW', '')}",
            f"Decision: {row.get('MORNING_DECISION', '')}",
            f"SLA: {row.get('SLA_CLOCK', '')}",
            f"First move: {row.get('FIRST_MOVE', '')}",
            f"Route action: {row.get('ROUTE_ACTION', '')}",
            f"Telemetry basis: {row.get('PROOF_REQUIRED', '')}",
            f"Review gate: {row.get('APPROVAL_GATE', '')}",
            f"Telemetry package: {row.get('EVIDENCE_PACKAGE', '')}",
            f"Confirm next: {row.get('VERIFY_NEXT', '')}",
            f"Execution boundary: {row.get('EXECUTION_BOUNDARY', '')}",
            f"Closure rule: {row.get('CLOSURE_RULE', '')}",
            f"Stop rule: {row.get('STOP_RULE', '')}",
        ]
        if focus_note:
            help_lines.append(f"Target signal: {focus_note}")
        help_text = "\n".join(help_lines)
        with move_cols[idx]:
            if st.button(label, key=f"dba_morning_open_{idx}_{route}_{workflow}", help=help_text, width="stretch"):
                if route == "DBA Control Room":
                    st.session_state["dba_control_room_active_view"] = normalize_dba_control_room_pane(workflow)
                    st.rerun()
                else:
                    _seed_dba_morning_route_context(row)
                    _jump(route, workflow=workflow)
    with st.expander("Brief telemetry detail", expanded=False):
        brief_view = _dba_morning_brief_detail_view(brief)
        render_priority_dataframe(
            brief_view,
            title="DBA daily brief telemetry",
            priority_columns=[
                "MORNING_RANK", "MORNING_DECISION", "SLA_CLOCK", "ROUTE", "WORKFLOW",
                "STATE", "WHY_NOW", "FIRST_MOVE", "ROUTE_TELEMETRY_STATE", "ESCALATION_ROUTE",
                "GO_NO_GO", "PROOF_REQUIRED", "APPROVAL_GATE", "EVIDENCE_PACKAGE",
                "VERIFY_NEXT", "EXECUTION_BOUNDARY", "CLOSURE_RULE", "SOURCE_SIGNALS",
                "FOCUS_QUERY_ID", "FOCUS_WAREHOUSE", "FOCUS_OBJECT",
            ],
            sort_by=["MORNING_RANK"],
            ascending=[True],
            raw_label="All DBA daily brief rows",
            height=300,
            max_rows=5,
        )
    with st.expander("Daily brief packet", expanded=False):
        st.code(markdown, language="markdown")
        download_text(
            markdown,
            "dba_daily_brief.md",
            label="Download DBA Daily Brief",
            mime="text/markdown",
            key="dba_daily_brief_download",
        )
    download_csv(brief_view if "brief_view" in locals() else brief, "dba_morning_brief.csv")


def _dba_handoff_rows(
    exceptions: pd.DataFrame | None,
    command_queue: pd.DataFrame | None,
    closure_rollup: pd.DataFrame | None,
    source_health: pd.DataFrame | None,
    advisor_rows: pd.DataFrame | None = None,
    *,
    max_rows: int = 14,
) -> pd.DataFrame:
    """Build an operational shift handoff from already-loaded Control Room telemetry."""
    rows: list[dict] = []

    priority_exceptions = _priority_exceptions(exceptions if exceptions is not None else _empty_df())
    for _, item in priority_exceptions.head(5).iterrows():
        severity = str(item.get("Severity") or item.get("SEVERITY") or "Medium")
        route = str(item.get("Route") or item.get("ROUTE") or item.get("Domain") or "DBA Control Room")
        signal = str(item.get("Signal") or item.get("SIGNAL") or "Control-room exception")
        workflow = str(item.get("Workflow") or "")
        rows.append({
            "PRIORITY_RANK": 0 if severity.upper() in {"CRITICAL", "HIGH"} else 3,
            "LANE": route,
            "STATE": f"{severity} Exception",
            "EVIDENCE": str(item.get("Evidence") or item.get("DETAIL") or signal),
            "OWNER_OR_ROUTE": f"{route}{' / ' + workflow if workflow else ''}",
            "NEXT_ACTION": str(item.get("Action") or item.get("NEXT_ACTION") or "Open the routed workflow and validate telemetry."),
            "PROOF_REQUIRED": _dba_section_proof_required(route),
            "SOURCE": "Watch Floor",
        })

    queue = command_queue.copy() if command_queue is not None and not command_queue.empty else _empty_df()
    if not queue.empty:
        queue.columns = [str(col).upper() for col in queue.columns]
        due_state = queue.get("DUE_STATE", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
        gate = queue.get("COMMAND_EXECUTION_GATE", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
        severity = queue.get("SEVERITY", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str).str.upper()
        important = queue[
            due_state.eq("Overdue")
            | gate.str.startswith("Blocked")
            | severity.isin(["CRITICAL", "HIGH"])
        ].head(5)
        for _, item in important.iterrows():
            route = str(item.get("ROUTE") or _command_queue_route(item.get("CATEGORY")) or "DBA Control Room")
            entity = str(item.get("ENTITY_NAME") or item.get("ENTITY") or item.get("CATEGORY") or "queued item")
            owner = str(item.get("OWNER") or item.get("OWNER_EMAIL") or item.get("APPROVAL_GROUP") or route)
            evidence_required = str(item.get("COMMAND_EVIDENCE_REQUIRED") or item.get("EVIDENCE_GAP") or "")
            rows.append({
                "PRIORITY_RANK": 0 if str(item.get("DUE_STATE")) == "Overdue" else 1 if str(item.get("COMMAND_EXECUTION_GATE", "")).startswith("Blocked") else 2,
                "LANE": route,
                "STATE": str(item.get("COMMAND_STATE") or item.get("COMMAND_EXECUTION_GATE") or "Queued Action"),
                "EVIDENCE": f"{entity}; due={item.get('DUE_STATE', '')}; gate={item.get('COMMAND_EXECUTION_GATE', '')}",
                "OWNER_OR_ROUTE": owner,
                "NEXT_ACTION": str(item.get("NEXT_ACTION") or "Complete the queue row, then monitor telemetry before closure."),
                "PROOF_REQUIRED": evidence_required or _dba_section_proof_required(route),
                "SOURCE": "Action Queue",
            })

    closure = closure_rollup.copy() if closure_rollup is not None and not closure_rollup.empty else _empty_df()
    if not closure.empty:
        closure.columns = [str(col).upper() for col in closure.columns]
        blocked = closure[
            (pd.to_numeric(closure.get("CLOSURE_RANK", pd.Series([9] * len(closure))), errors="coerce").fillna(9) <= 3)
            | (pd.to_numeric(closure.get("CLOSURE_BLOCKER_ROWS", pd.Series([0] * len(closure))), errors="coerce").fillna(0) > 0)
        ].head(5)
        for _, item in blocked.iterrows():
            route = _canonical_dba_route(item.get("ROUTE") or "DBA Control Room")
            rows.append({
                "PRIORITY_RANK": safe_int(item.get("CLOSURE_RANK", 3)),
                "LANE": route,
                "STATE": str(item.get("CLOSURE_READINESS") or "Closure Blocked"),
                "EVIDENCE": (
                    f"{safe_int(item.get('OPEN_ACTIONS')):,} open; "
                    f"{safe_int(item.get('OVERDUE_OPEN')):,} overdue; "
                    f"{safe_int(item.get('FIXED_WITHOUT_VERIFICATION')):,} closed pending telemetry"
                ),
                "OWNER_OR_ROUTE": str(item.get("OWNER") or route),
                "NEXT_ACTION": str(item.get("NEXT_CONTROL_ACTION") or "Confirm closure status before accepting the work as done."),
                "PROOF_REQUIRED": _dba_section_proof_required(route),
                "SOURCE": "Closure Rollup",
            })

    sources = source_health.copy() if source_health is not None and not source_health.empty else _empty_df()
    if not sources.empty:
        sources.columns = [str(col).upper() for col in sources.columns]
        source_blocks = sources[
            sources.get("STATE", pd.Series([""] * len(sources), index=sources.index)).fillna("").astype(str).isin(["Unavailable", "Stale"])
        ].head(4)
        for _, item in source_blocks.iterrows():
            state = str(item.get("STATE") or "Source Check")
            surface = str(item.get("SURFACE") or "Telemetry surface")
            rows.append({
                "PRIORITY_RANK": 1 if state == "Unavailable" else 2,
                "LANE": "Data Health",
                "STATE": state,
                "EVIDENCE": f"{surface}; rows={safe_int(item.get('ROWS')):,}; scope={item.get('SCOPE', '')}",
                "OWNER_OR_ROUTE": "DBA / Platform",
                "NEXT_ACTION": str(item.get("NEXT_ACTION") or "Reload or refresh this telemetry before acting."),
                "PROOF_REQUIRED": "current data health for active company, environment, lookback, spend threshold, and triage filters",
                "SOURCE": "Data Health",
            })

    advisors = advisor_rows.copy() if advisor_rows is not None and not advisor_rows.empty else _empty_df()
    if not advisors.empty:
        advisors.columns = [str(col).upper() for col in advisors.columns]
        for _, item in advisors.head(5).iterrows():
            severity = str(item.get("SEVERITY") or "Medium").title()
            route = str(item.get("ROUTE") or "DBA Control Room")
            entity = str(item.get("ENTITY") or "Advisor finding")
            signal = str(item.get("SIGNAL") or item.get("SOURCE_SURFACE") or "Loaded advisor")
            savings = safe_float(item.get("EST_MONTHLY_SAVINGS_USD"))
            risk = safe_float(item.get("VALUE_AT_RISK_USD"))
            value = []
            if savings > 0:
                value.append(f"${savings:,.0f}/mo savings")
            if risk > 0:
                value.append(f"${risk:,.0f} value at risk")
            value_text = "; ".join(value) if value else str(item.get("DETAIL") or "loaded advisor telemetry")
            rows.append({
                "PRIORITY_RANK": 1 if severity in {"Critical", "High"} else 2 if severity == "Medium" else 4,
                "LANE": route,
                "STATE": f"{severity} Advisor",
                "EVIDENCE": f"{signal} on {entity}; {value_text}",
                "OWNER_OR_ROUTE": route,
                "NEXT_ACTION": str(item.get("NEXT_ACTION") or "Open the owning monitoring section and review loaded telemetry."),
                "PROOF_REQUIRED": str(item.get("TELEMETRY_BASIS") or _dba_section_proof_required(route)),
                "SOURCE": str(item.get("SOURCE_SURFACE") or "Loaded Advisor"),
            })

    if not rows:
        rows.append({
            "PRIORITY_RANK": 8,
            "LANE": "DBA Control Room",
            "STATE": "Routine Watch",
            "EVIDENCE": "No loaded exceptions, open command blockers, closure blockers, or stale telemetry surfaces.",
            "OWNER_OR_ROUTE": "On-call DBA",
            "NEXT_ACTION": "Keep the fast snapshot current and review Alert Center for new routed issues.",
            "PROOF_REQUIRED": "fresh Control Room load and current Alert Center review",
            "SOURCE": "Handoff",
        })

    return pd.DataFrame(rows).sort_values(
        ["PRIORITY_RANK", "LANE", "STATE"],
        ascending=[True, True, True],
    ).head(max_rows).reset_index(drop=True)


def _build_dba_shift_handoff_markdown(
    handoff_rows: pd.DataFrame,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
    source_mode: str,
) -> str:
    """Create an email-friendly DBA shift handoff packet."""
    rows = handoff_rows if handoff_rows is not None and not handoff_rows.empty else _empty_df()
    lines = [
        "# OVERWATCH DBA Shift Handoff",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Scope: {company} / {environment}",
        f"Lookback: {int(lookback_hours)} hours",
        f"Source mode: {source_mode}",
        "",
        "## Work First",
    ]
    if rows.empty:
        lines.append("- No handoff rows were available.")
    else:
        for _, row in rows.iterrows():
            lines.append(
                f"- [{row.get('STATE', '')}] {row.get('LANE', '')}: {row.get('EVIDENCE', '')}. "
                f"Route: {_clean_display_text(row.get('OWNER_OR_ROUTE', ''))}. "
                f"Next: {_clean_display_text(row.get('NEXT_ACTION', ''))}. "
                f"Telemetry basis: {_clean_display_text(row.get('PROOF_REQUIRED', ''))}."
            )
    lines.extend([
        "",
        "## Closure Standard",
        "- Do not mark work done unless route, ticket/change ID, telemetry status, and recovery status are present where applicable.",
        "- Treat shared warehouse cost attribution as allocated/estimated unless confirmed against billing or finance data.",
        "- Reload stale telemetry after changing company, environment, lookback, spend threshold, or triage filters.",
    ])
    return "\n".join(lines)


def _render_shift_handoff_panel(
    handoff_rows: pd.DataFrame,
    handoff_md: str,
    *,
    company: str,
    environment: str,
) -> None:
    if handoff_rows is None or handoff_rows.empty:
        return
    st.markdown("**DBA Shift Handoff**")
    render_shell_snapshot((
        ("Handoff Items", f"{len(handoff_rows):,}"),
        ("Escalate", f"{int((handoff_rows['PRIORITY_RANK'] <= 1).sum()):,}"),
        (
            "Telemetry Blocks",
            f"{int(handoff_rows['STATE'].astype(str).str.contains('Blocked|Overdue|Unavailable|Stale', case=False, regex=True).sum()):,}",
        ),
        ("Input Issues", f"{int(handoff_rows['SOURCE'].astype(str).eq('Data Health').sum()):,}"),
    ))
    render_priority_dataframe(
        handoff_rows.rename(columns={"OWNER_OR_ROUTE": "ROUTE"}),
        title="Incoming DBA handoff queue",
        priority_columns=[
            "LANE", "STATE", "EVIDENCE", "ROUTE",
            "NEXT_ACTION", "PROOF_REQUIRED", "SOURCE",
        ],
        sort_by=["PRIORITY_RANK", "LANE", "STATE"],
        ascending=[True, True, True],
        raw_label="All DBA handoff rows",
        height=300,
        max_rows=12,
    )
    download_text(
        handoff_md,
        f"overwatch_dba_shift_handoff_{company.lower()}_{environment.lower()}.md",
        label="Download DBA Shift Handoff",
        mime="text/markdown",
        key="dba_shift_handoff_download",
    )

