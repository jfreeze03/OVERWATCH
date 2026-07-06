# sections/warehouse_health_dataframes.py - Warehouse Health dataframe helpers.
from __future__ import annotations

import pandas as pd

from config import DEFAULTS, THRESHOLDS
from sections.warehouse_health_contracts import WAREHOUSE_SCOPE_FILTER_KEYS
from utils.primitives import safe_float, safe_int


def _scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _warehouse_scope_meta(
    company: str,
    environment: str,
    days: int | None = None,
    state: dict | None = None,
) -> dict:
    """Return the filter scope that loaded Warehouse Health telemetry must match."""
    state = state if state is not None else {}
    meta = {
        "company": _scope_value(company),
        "environment": _scope_value(environment),
    }
    if days is not None:
        meta["days"] = int(days)
    for key in WAREHOUSE_SCOPE_FILTER_KEYS:
        meta[key] = _scope_value(state.get(key))
    return meta


def _warehouse_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key == "days":
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif _scope_value(actual) != _scope_value(expected_value):
            return False
    return True


def _warehouse_looks_like_frame(frame) -> bool:
    return hasattr(frame, "empty") and hasattr(frame, "columns")


def _warehouse_frame_has_rows(frame) -> bool:
    return _warehouse_looks_like_frame(frame) and not frame.empty


def _warehouse_frame_len(frame) -> int:
    if not _warehouse_looks_like_frame(frame):
        return 0
    try:
        return int(len(frame))
    except TypeError:
        return 0


def _warehouse_column_sum(frame, column: str) -> float:
    if not _warehouse_frame_has_rows(frame) or column not in frame.columns:
        return 0.0
    try:
        return float(frame[column].fillna(0).sum())
    except Exception:
        return sum(safe_float(value) for value in frame[column].tolist())


def _warehouse_column_average(frame, column: str) -> float:
    if not _warehouse_frame_has_rows(frame) or column not in frame.columns:
        return 0.0
    try:
        return float(frame[column].fillna(0).mean())
    except Exception:
        values = [safe_float(value) for value in frame[column].tolist()]
        return sum(values) / len(values) if values else 0.0


def _warehouse_value_count(frame, column: str, values: set[str]) -> int:
    if not _warehouse_frame_has_rows(frame) or column not in frame.columns:
        return 0
    normalized = {str(value).upper() for value in values}
    try:
        return int(frame[column].fillna("").astype(str).str.upper().isin(normalized).sum())
    except Exception:
        return sum(1 for value in frame[column].tolist() if str(value).upper() in normalized)


def _frame_row_count(frame) -> int:
    return len(frame) if isinstance(frame, pd.DataFrame) else 0


def _source_confidence(source: str, default: str) -> str:
    source_lower = str(source or "").lower()
    if ("fast" in source_lower and "summary" in source_lower) or "mart" in source_lower or "fact_" in source_lower:
        return "Fast summary"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower:
        return "Live ACCOUNT_USAGE"
    return default


def _source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or triage filters."
    if state == "Unavailable":
        return "Deploy or refresh the summary/grants before relying on this surface."
    if state == "Details available when needed":
        return "Refresh only when this workflow is part of the current DBA investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent warehouse activity or summary rows."
    if "fallback" in source_lower:
        return "Use for investigation; prefer summary refresh for repeated daily control."
    return "Current for the active DBA scope."


def _warehouse_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Warehouse Health telemetry freshness and source strategy."""
    definitions = [
        {
            "surface": "Capacity brief",
            "frame_key": "wh_capacity_summary",
            "meta_key": "wh_capacity_meta",
            "days_key": "wh_capacity_days",
            "default_days": 7,
            "source": "Live ACCOUNT_USAGE: QUERY_HISTORY + WAREHOUSE_METERING_HISTORY",
            "confidence": "Live aggregate",
        },
        {
            "surface": "Control summary",
            "frame_key": "wh_operability_fact",
            "meta_key": "wh_capacity_meta",
            "days_key": "wh_capacity_days",
            "default_days": 7,
            "source": "Fast warehouse control summary",
            "confidence": "Fast summary",
            "error_key": "wh_operability_fact_error",
        },
        {
            "surface": "Overview",
            "frame_key": "wh_df_wh",
            "source_key": "wh_df_wh_source",
            "meta_key": "wh_df_wh_meta",
            "days_key": "wh_days",
            "default_days": 7,
            "source": "Fast warehouse summary or live warehouse overview",
            "confidence": "Mixed",
        },
        {
            "surface": "Scaling events",
            "frame_key": "wh_scaling",
            "source_key": "wh_scaling_source",
            "meta_key": "wh_scaling_meta",
            "days_key": "wh_days",
            "default_days": 7,
            "source": "Fast warehouse summary or live metering history",
            "confidence": "Mixed",
        },
        {
            "surface": "Efficiency",
            "frame_key": "wh_efficiency",
            "meta_key": "wh_efficiency_meta",
            "days_key": "wh_eff_days",
            "default_days": 7,
            "source": "Live ACCOUNT_USAGE + allocated per-query credits",
            "confidence": "Allocated",
        },
        {
            "surface": "Spill & memory",
            "frame_key": "wh_df_sp",
            "meta_key": "wh_df_sp_meta",
            "days_key": "sp_days",
            "default_days": 7,
            "source": "Live ACCOUNT_USAGE.QUERY_HISTORY",
            "confidence": "Live ACCOUNT_USAGE",
        },
        {
            "surface": "Workload heatmap",
            "frame_key": "wh_df_hm",
            "meta_key": "wh_df_hm_meta",
            "days_key": "hm_days",
            "default_days": 30,
            "source": "Live ACCOUNT_USAGE.QUERY_HISTORY",
            "confidence": "Live ACCOUNT_USAGE",
        },
        {
            "surface": "Closure analytics",
            "frame_key": "wh_action_closure",
            "meta_key": "wh_action_closure_meta",
            "days_key": "wh_action_closure_days",
            "default_days": 30,
            "source": "Action queue closure status",
            "confidence": "Workflow telemetry",
        },
        {
            "surface": "Execution audit",
            "frame_key": "wh_setting_execution_audit",
            "meta_key": "wh_setting_execution_audit_meta",
            "days": 30,
            "source": "Warehouse setting review + DBA admin audit",
            "confidence": "Audit telemetry",
        },
    ]
    rows = []
    for item in definitions:
        source_key = item.get("source_key")
        source = str((state.get(source_key, item["source"]) if source_key else item["source"]) or item["source"])
        frame = state.get(item["frame_key"])
        error_key = item.get("error_key")
        error = state.get(error_key) if error_key else None
        days_key = item.get("days_key")
        days = item["days"] if "days" in item else (state.get(days_key, item.get("default_days")) if days_key else item.get("default_days"))
        expected_meta = _warehouse_scope_meta(company, environment, days=days, state=state)
        loaded = isinstance(frame, pd.DataFrame)
        if error:
            status = "Unavailable"
        elif not loaded:
            status = "Details available when needed"
        elif not _warehouse_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif frame.empty:
            status = "No Rows"
        else:
            status = "Loaded"
        state_rank = {
            "Unavailable": 0,
            "Stale": 1,
            "Loaded": 2,
            "No Rows": 3,
            "Details available when needed": 4,
        }.get(status, 9)
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": state_rank,
            "SOURCE": source,
            "CONFIDENCE": _source_confidence(source, item["confidence"]),
            "ROWS": _frame_row_count(frame),
            "SCOPE": (
                f"{company} / {environment} / {int(days)}d"
                if days is not None
                else f"{company} / {environment}"
            ),
            "NEXT_ACTION": _source_next_action(status, source),
        })
    return pd.DataFrame(rows)


def _warehouse_upper_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    view = frame.copy()
    view.columns = [str(col).upper() for col in view.columns]
    return view


def _warehouse_text(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
    except (TypeError, ValueError):
        if value is None:
            return ""
    return str(value).strip()


def _warehouse_row_by_name(frame: pd.DataFrame, preferred_name_col: str = "WAREHOUSE_NAME") -> dict[str, pd.Series]:
    if frame.empty:
        return {}
    name_col = preferred_name_col if preferred_name_col in frame.columns else "NAME" if "NAME" in frame.columns else ""
    if not name_col:
        return {}
    return {
        _warehouse_text(row.get(name_col)).upper(): row
        for _, row in frame.iterrows()
        if _warehouse_text(row.get(name_col))
    }


def _warehouse_first_setting(row: pd.Series | dict, columns: tuple[str, ...]) -> tuple[object, bool]:
    for column in columns:
        if column in row:
            return row.get(column), True
    return "", False


def _warehouse_setting_present(value: object) -> bool:
    try:
        if value is None or pd.isna(value):
            return False
    except (TypeError, ValueError):
        if value is None:
            return False
    if isinstance(value, str) and not value.strip():
        return False
    text = str(value).strip()
    return bool(text) and text.upper() not in {"NONE", "NULL", "NAN", "NOT SET", "UNSET"}


def _warehouse_bool_setting(value: object) -> bool | None:
    """Parse SHOW WAREHOUSES boolean-like settings."""
    if not _warehouse_setting_present(value):
        return None
    text = str(value).strip().upper()
    if text in {"TRUE", "T", "YES", "Y", "1", "ON"}:
        return True
    if text in {"FALSE", "F", "NO", "N", "0", "OFF"}:
        return False
    return None


def _warehouse_frame_sum(frame: pd.DataFrame | None, column: str) -> int:
    if frame is None or frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _warehouse_state_count(frame: pd.DataFrame | None, column: str, states: set[str]) -> int:
    if frame is None or frame.empty or column not in frame.columns:
        return 0
    normalized = {state.upper() for state in states}
    return int(frame[column].fillna("").astype(str).str.upper().isin(normalized).sum())


def _warehouse_operator_next_moves(
    *,
    score: int | float,
    exceptions: pd.DataFrame | None,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    execution_audit: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a no-query decision gate for the loaded warehouse telemetry."""
    exception_count = 0 if exceptions is None or exceptions.empty else int(len(exceptions))
    control = pd.DataFrame() if control_board is None else control_board.copy()
    close = pd.DataFrame() if closure is None else closure.copy()
    audit = pd.DataFrame() if execution_audit is None else execution_audit.copy()
    fact = pd.DataFrame() if operability_fact is None else operability_fact.copy()
    for frame in (control, close, audit, fact):
        if not frame.empty:
            frame.columns = [str(col).upper() for col in frame.columns]

    overdue = max(
        _warehouse_frame_sum(control, "OVERDUE"),
        _warehouse_frame_sum(close, "OVERDUE_OPEN"),
        _warehouse_frame_sum(fact, "OVERDUE_OPEN"),
    )
    fixed_without_verification = max(
        _warehouse_frame_sum(control, "FIXED_WITHOUT_VERIFICATION"),
        _warehouse_frame_sum(close, "FIXED_WITHOUT_VERIFICATION"),
        _warehouse_frame_sum(fact, "FIXED_WITHOUT_VERIFICATION"),
    )
    recovery_risk = max(
        _warehouse_frame_sum(close, "RECOVERY_RISK_ROWS"),
        _warehouse_frame_sum(fact, "RECOVERY_RISK_ROWS"),
    )
    closure_blockers = max(
        _warehouse_frame_sum(control, "CLOSURE_BLOCKERS"),
        _warehouse_frame_sum(close, "CLOSURE_BLOCKER_ROWS"),
        overdue + fixed_without_verification + recovery_risk,
    )
    failed_changes = max(
        _warehouse_frame_sum(control, "FAILED_CHANGES"),
        _warehouse_frame_sum(audit, "FAILED_CHANGES"),
    )
    audit_rows = max(
        _warehouse_frame_sum(control, "AUDIT_ROWS"),
        _warehouse_frame_sum(audit, "AUDIT_ROWS"),
    )
    route_blocks = (
        _warehouse_state_count(control, "CONTROL_STATE", {"Route Metadata Blocked", "Pre-Change Blocked"})
        + _warehouse_state_count(control, "AUDIT_READINESS", {"Route Metadata Blocked", "Pre-Change Blocked"})
        + _warehouse_frame_sum(fact, "APPROVAL_REQUIRED_ROWS")
        + _warehouse_frame_sum(fact, "ROLLBACK_REQUIRED_ROWS")
    )
    pressure_rows = max(
        exception_count,
        _warehouse_frame_sum(fact, "QUEUE_PRESSURE_ROWS") + _warehouse_frame_sum(fact, "SPILL_PRESSURE_ROWS"),
    )

    rows: list[dict] = []
    if closure_blockers:
        state = "Blocked"
        rank = 0
        next_action = "Escalate overdue or telemetry-pending warehouse capacity work before planning more setting changes."
        count = closure_blockers
    elif exception_count and close.empty:
        state = "Load Closure Analytics"
        rank = 4
        next_action = "Load closure analytics before closing or declaring capacity actions controlled."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "Keep closure status visible with the setting review history."
        count = _warehouse_frame_sum(close, "VERIFIED_CLOSURES") + _warehouse_frame_sum(fact, "VERIFIED_CLOSURES")
    rows.append({
        "GATE": "Closure status",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "route, ticket/change ID, telemetry status, recovery state",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if failed_changes:
        state = "Failed Execution"
        rank = 1
        next_action = "Review failed ALTER WAREHOUSE audit rows and confirm rollback or no-op state."
        count = failed_changes
    elif exception_count and not audit_rows:
        state = "Load Execution Audit"
        rank = 3
        next_action = "Load execution audit before planning warehouse changes or claiming measured savings."
        count = exception_count
    elif audit_rows:
        state = "Audit Linked"
        rank = 7
        next_action = "Confirm SQL hash, executor, rollback SQL, and post-change telemetry remain current."
        count = audit_rows
    else:
        state = "No Change Detail Needed"
        rank = 9
        next_action = "No capacity exception currently requires warehouse setting audit detail."
        count = 0
    rows.append({
        "GATE": "Execution audit",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "SQL hash, executor, review state, rollback SQL, post-change pressure check",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if route_blocks:
        state = "Review Route Blocked"
        rank = 2
        next_action = "Complete ticket, rollback, telemetry, and escalation route before execution."
        count = route_blocks
    elif exception_count:
        state = "Ready for Review"
        rank = 6
        next_action = "Save the setting review snapshot, then work only changed settings through the guarded warehouse settings workflow."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "Keep warehouse monitoring telemetry current for future capacity exceptions."
        count = 0
    rows.append({
        "GATE": "Telemetry route",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "ticket, reviewer, rollback requirement, and impact telemetry requirement",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if pressure_rows:
        if safe_float(score) < 65:
            state, rank = "High Pressure", 1
        elif safe_float(score) < 90:
            state, rank = "Watch Pressure", 5
        else:
            state, rank = "Exceptions Present", 6
        next_action = "Confirm queue, spill, latency, and credit pressure before changing warehouse settings."
        count = pressure_rows
    else:
        state = "Clear"
        rank = 8
        next_action = "No pressured warehouse crossed the current threshold."
        count = 0
    rows.append({
        "GATE": "Capacity pressure",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "queued queries, spill queries, p95 latency, metered credits, setting candidate",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    metered_credits = 0.0
    credit_spike_rows = 0
    savings_required = 0
    if exceptions is not None and not exceptions.empty:
        metered_credits = float(pd.to_numeric(
            exceptions.get("METERED_CREDITS", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0).sum())
        credit_spike_rows = int(
            exceptions.get("SIGNAL", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains("CREDIT").sum()
        )
        if "IMPACT_TELEMETRY_REQUIRED" in exceptions.columns:
            savings_required = int(
                exceptions["IMPACT_TELEMETRY_REQUIRED"].fillna("").astype(str).str.upper().eq("YES").sum()
            )
    if not control.empty and "IMPACT_TELEMETRY_REQUIRED" in control.columns:
        savings_required = max(
            savings_required,
            int(control["IMPACT_TELEMETRY_REQUIRED"].fillna("").astype(str).str.upper().eq("YES").sum()),
        )

    if credit_spike_rows or savings_required:
        state = "Cost Impact Review"
        rank = 3
        count = max(credit_spike_rows, savings_required)
        next_action = "Review credit delta, savings hypothesis, and post-change telemetry before changing settings."
    elif metered_credits > 0 and exception_count:
        state = "Estimated Cost Watch"
        rank = 6
        count = exception_count
        next_action = "Keep warehouse metering and setting-review telemetry together before claiming DBA savings."
    else:
        state = "Clear"
        rank = 8
        count = 0
        next_action = "No loaded warehouse action needs cost-impact detail."
    rows.append({
        "GATE": "Cost guardrail",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "metered credits, cost delta, savings hypothesis, post-change telemetry",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    return pd.DataFrame(rows).sort_values(["GATE_RANK", "COUNT"], ascending=[True, False]).reset_index(drop=True)


def _warehouse_period_movement(df: pd.DataFrame | None) -> pd.DataFrame:
    """Return warehouse current/prior movement rows for the overview board."""
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame()
    required = {"WAREHOUSE_NAME", "METERED_CREDITS", "PRIOR_METERED_CREDITS", "CREDIT_DELTA"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    movement = df.copy()
    movement["CREDIT_DELTA_ABS"] = pd.to_numeric(movement["CREDIT_DELTA"], errors="coerce").fillna(0).abs()
    movement["MOVEMENT_STATE"] = movement.apply(
        lambda row: (
            "New or no prior baseline"
            if safe_float(row.get("PRIOR_METERED_CREDITS")) <= 0
            else "Higher than prior"
            if safe_float(row.get("CREDIT_DELTA")) > 0
            else "Lower than prior"
            if safe_float(row.get("CREDIT_DELTA")) < 0
            else "Stable"
        ),
        axis=1,
    )
    movement["NEXT_ACTION"] = movement.apply(
        lambda row: (
            "Review queue, spill, p95, and settings before changing capacity."
            if safe_float(row.get("CREDIT_DELTA")) > 0
            else "Confirm the lower burn did not coincide with failures, queueing, or delayed tasks."
            if safe_float(row.get("CREDIT_DELTA")) < 0
            else "Keep monitoring; no material period movement loaded."
        ),
        axis=1,
    )
    sort_cols = ["CREDIT_DELTA_ABS", "METERED_CREDITS"]
    return movement.sort_values(sort_cols, ascending=[False, False]).drop(columns=["CREDIT_DELTA_ABS"], errors="ignore")


def _warehouse_overview_exceptions(df: pd.DataFrame | None) -> list[dict[str, str]]:
    """Return the short list of warehouse overview issues worth showing first."""
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, str]] = []
    spill_threshold = safe_float(THRESHOLDS.get("spill_warning_gb"), 5.0)
    for _, row in df.iterrows():
        warehouse = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        queued = safe_float(row.get("AVG_QUEUED_SEC"))
        remote_spill = safe_float(row.get("TOTAL_REMOTE_SPILL_GB"))
        p95_elapsed = safe_float(row.get("P95_ELAPSED_SEC"))
        credit_delta = safe_float(row.get("CREDIT_DELTA"))
        issues: list[str] = []
        rank = 4
        if queued > 10:
            issues.append(f"queue average {queued:,.1f}s")
            rank = min(rank, 1)
        elif queued > 2:
            issues.append(f"queue average {queued:,.1f}s")
            rank = min(rank, 2)
        if remote_spill > max(10.0, spill_threshold):
            issues.append(f"remote spill {remote_spill:,.1f} GB")
            rank = min(rank, 1)
        elif remote_spill > spill_threshold:
            issues.append(f"remote spill {remote_spill:,.1f} GB")
            rank = min(rank, 2)
        if p95_elapsed > 300:
            issues.append(f"p95 elapsed {p95_elapsed:,.0f}s")
            rank = min(rank, 2)
        if credit_delta > 25:
            issues.append(f"credit movement +{credit_delta:,.1f}")
            rank = min(rank, 3)
        if issues:
            rows.append({
                "rank": rank,
                "warehouse": warehouse,
                "severity": "Critical" if rank == 1 else "High" if rank == 2 else "Review",
                "signal": " | ".join(issues),
                "next_action": "Open detailed telemetry before resizing, suspending, or changing clusters.",
            })
    rows.sort(key=lambda item: (safe_int(item.get("rank"), 9), item.get("warehouse", "")))
    return rows[:4]
