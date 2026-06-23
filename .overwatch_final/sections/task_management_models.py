# sections/task_management_models.py - Task Management dataframe/model helpers
import re

import pandas as pd

from sections.task_management_contracts import (
    TASK_FAILURE_STATES,
    TASK_SUCCESS_STATES,
    TASK_RUNNING_STATES,
    TASK_RECOVERY_SLA_HOURS,
)
from sections.task_management_common import _qualified_name
from utils import CREDIT_RATES, get_active_environment, resolve_owner_context, safe_float, safe_int

def _procedure_from_definition(definition: object) -> str:
    text = str(definition or "")
    match = re.search(r"\bCALL\s+([A-Za-z0-9_.$\"]+)", text, flags=re.IGNORECASE)
    return match.group(1).replace('"', "") if match else ""

def _extract_object_candidates(text: object, limit: int = 12) -> str:
    """Best-effort dependency hints from visible SQL text.

    Snowflake does not expose a complete object dependency graph for every
    procedure body in ACCOUNT_USAGE, so this intentionally stays conservative:
    it extracts obvious object references from task definitions and query text
    for DBA triage, not as a source of record.
    """
    sql = re.sub(r"\s+", " ", str(text or " "))
    patterns = [
        r"\bFROM\s+([A-Za-z0-9_.$\"]+)",
        r"\bJOIN\s+([A-Za-z0-9_.$\"]+)",
        r"\bUSING\s+([A-Za-z0-9_.$\"]+)",
        r"\bINTO\s+([A-Za-z0-9_.$\"]+)",
        r"\bUPDATE\s+([A-Za-z0-9_.$\"]+)",
        r"\bMERGE\s+INTO\s+([A-Za-z0-9_.$\"]+)",
        r"\bDELETE\s+FROM\s+([A-Za-z0-9_.$\"]+)",
        r"\bTRUNCATE\s+TABLE\s+([A-Za-z0-9_.$\"]+)",
        r"\bCREATE(?:\s+OR\s+REPLACE)?\s+(?:TRANSIENT\s+|TEMP(?:ORARY)?\s+)?TABLE\s+([A-Za-z0-9_.$\"]+)",
        r"\bCALL\s+([A-Za-z0-9_.$\"]+)",
    ]
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, sql, flags=re.IGNORECASE):
            obj = match.group(1).strip().strip(";,()").replace('"', "")
            if obj and obj.upper() not in {"SELECT", "TABLE", "VALUES"} and obj not in found:
                found.append(obj)
            if len(found) >= limit:
                return ", ".join(found)
    return ", ".join(found)

def _task_root_name(row: pd.Series) -> str:
    predecessors = str(row.get("PREDECESSORS") or "").strip()
    if not predecessors or predecessors.upper() in {"[]", "NONE", "NULL"}:
        return str(row.get("NAME") or "")
    cleaned = re.sub(r"[\[\]'\"\s]", "", predecessors)
    first = cleaned.split(",")[0]
    return first.split(".")[-1] if first else str(row.get("NAME") or "")

def _df_col(df: pd.DataFrame, column: str, default: object = "") -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)

def _blankish_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.upper().isin({"", "NONE", "NULL", "NAN"})

def _task_failure_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    state = _df_col(df, "STATE").fillna("").astype(str).str.upper()
    error_text = _df_col(df, "ERROR_MESSAGE")
    return state.isin(TASK_FAILURE_STATES) | ~_blankish_series(error_text)

def _task_success_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    return _df_col(df, "STATE").fillna("").astype(str).str.upper().isin(TASK_SUCCESS_STATES)

def _parse_task_predecessors(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text or text.upper() in {"[]", "NONE", "NULL", "NAN"}:
        return []
    cleaned = re.sub(r"[\[\]'\"\s]", "", text)
    return [part.split(".")[-1] for part in cleaned.split(",") if part]

def _annotate_task_graph_impact(inventory: pd.DataFrame) -> pd.DataFrame:
    """Add task graph blast-radius context used for DBA incident triage."""
    if inventory is None or inventory.empty or "NAME" not in inventory.columns:
        return inventory
    annotated = inventory.copy()
    names = set(_df_col(annotated, "NAME").astype(str))
    children: dict[str, set[str]] = {name: set() for name in names}
    predecessor_map: dict[str, list[str]] = {}
    for _, row in annotated.iterrows():
        name = str(row.get("NAME") or "")
        predecessors = [pred for pred in _parse_task_predecessors(row.get("PREDECESSORS")) if pred]
        predecessor_map[name] = predecessors
        for pred in predecessors:
            children.setdefault(pred, set()).add(name)

    downstream_counts: list[int] = []
    graph_roles: list[str] = []
    blast_radius: list[str] = []
    retry_scope: list[str] = []
    for _, row in annotated.iterrows():
        name = str(row.get("NAME") or "")
        seen: set[str] = set()
        stack = list(children.get(name, set()))
        while stack:
            child = stack.pop()
            if child in seen:
                continue
            seen.add(child)
            stack.extend(children.get(child, set()))
        downstream = len(seen)
        predecessors = predecessor_map.get(name, [])
        has_in_scope_predecessor = any(pred in names for pred in predecessors)
        has_child = bool(children.get(name))
        role = "Root" if not has_in_scope_predecessor else "Leaf" if not has_child else "Intermediate"
        downstream_counts.append(downstream)
        graph_roles.append(role)
        blast_radius.append("High" if downstream >= 5 else "Medium" if downstream >= 1 else "Local")
        retry_scope.append("Root graph retry" if role == "Root" else "Targeted task retry")

    annotated["DOWNSTREAM_TASK_COUNT"] = downstream_counts
    annotated["GRAPH_ROLE"] = graph_roles
    annotated["BLAST_RADIUS"] = blast_radius
    annotated["RETRY_SCOPE"] = retry_scope
    return annotated

def _task_full_name(row: pd.Series) -> str:
    return _qualified_name(row.get("DATABASE_NAME", ""), row.get("SCHEMA_NAME", ""), row.get("NAME", ""))

def _is_prod_task(row: pd.Series) -> bool:
    env = str(get_active_environment() or "").upper()
    db = str(row.get("DATABASE_NAME") or "").upper()
    schema = str(row.get("SCHEMA_NAME") or "").upper()
    return "PROD" in {env, db, schema} or "_PROD" in db or db.endswith("PROD")

def _confirmation_phrase(row: pd.Series, action: str) -> str:
    name = str(row.get("NAME") or "")
    return f"PROD {action} {name}" if _is_prod_task(row) else f"{action} {name}"

def _collect_graph_tasks(inventory: pd.DataFrame, root_name: str) -> pd.DataFrame:
    if inventory is None or inventory.empty or "NAME" not in inventory.columns:
        return pd.DataFrame()
    names_seen = {str(root_name)}
    changed = True
    while changed:
        changed = False
        for _, row in inventory.iterrows():
            name = str(row.get("NAME") or "")
            preds = set(_parse_task_predecessors(row.get("PREDECESSORS")))
            if name and name not in names_seen and preds.intersection(names_seen):
                names_seen.add(name)
                changed = True
    return inventory[inventory["NAME"].astype(str).isin(names_seen)].copy()

def _build_task_graph_dot(inventory: pd.DataFrame, max_nodes: int = 80) -> str:
    if inventory is None or inventory.empty:
        return "digraph TaskGraph { label=\"No task metadata loaded\"; }"

    scoped = inventory.head(max(1, int(max_nodes))).copy()
    lines = [
        "digraph TaskGraph {",
        "  rankdir=LR;",
        "  graph [bgcolor=\"transparent\", pad=\"0.2\", nodesep=\"0.45\", ranksep=\"0.7\"];",
        "  node [shape=box, style=\"rounded,filled\", fontname=\"Arial\", fontsize=10, color=\"#5DADE2\", fillcolor=\"#102338\", fontcolor=\"#F5F7FA\"];",
        "  edge [color=\"#7FB3D5\", arrowsize=0.7];",
    ]
    task_names = set(_df_col(scoped, "NAME").astype(str))
    for _, row in scoped.iterrows():
        name = str(row.get("NAME") or "UNKNOWN_TASK")
        state = str(row.get("STATE") or "").upper()
        color = "#246B45" if state in {"STARTED", "RESUMED", "SUCCEEDED"} else "#7A3B3B" if state in {"FAILED", "SUSPENDED"} else "#102338"
        label = name.replace('"', "'")
        lines.append(f'  "{label}" [fillcolor="{color}", tooltip="{state or "UNKNOWN"}"];')
        for pred in _parse_task_predecessors(row.get("PREDECESSORS")):
            pred_label = pred.replace('"', "'")
            if pred not in task_names:
                lines.append(f'  "{pred_label}" [style="rounded,dashed,filled", fillcolor="#26364A", tooltip="Predecessor outside loaded scope"];')
            lines.append(f'  "{pred_label}" -> "{label}";')
    lines.append("}")
    return "\n".join(lines)

def _task_ops_score(
    failed_runs: int,
    suspended_tasks: int,
    long_running_tasks: int,
    total_runs: int,
    total_tasks: int,
) -> int:
    run_base = max(safe_int(total_runs), 1)
    task_base = max(safe_int(total_tasks), 1)
    failed_pct = safe_float(failed_runs) / run_base * 100
    suspended_pct = safe_float(suspended_tasks) / task_base * 100
    long_pct = safe_float(long_running_tasks) / run_base * 100
    penalty = min(failed_pct * 2.4, 36) + min(suspended_pct * 1.8, 28) + min(long_pct * 1.6, 24)
    return max(0, min(100, int(round(100 - penalty))))

def _task_time_series(df: pd.DataFrame, *columns: str) -> pd.Series:
    values = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for column in columns:
        if column in df.columns:
            parsed = pd.to_datetime(df[column], errors="coerce")
            values = values.combine_first(parsed)
    return values

def _normalize_task_history_for_recovery(history: pd.DataFrame) -> pd.DataFrame:
    hist = history.copy() if history is not None else pd.DataFrame()
    if hist.empty:
        return hist
    task_names = _df_col(hist, "TASK_NAME")
    if _blankish_series(task_names).all() and "NAME" in hist.columns:
        task_names = hist["NAME"]
    hist["TASK_NAME"] = task_names.fillna("").astype(str)
    hist["STATE"] = _df_col(hist, "STATE").fillna("").astype(str).str.upper()
    hist["EVENT_TIME"] = _task_time_series(hist, "COMPLETED_TIME", "QUERY_START_TIME", "SCHEDULED_TIME")
    hist["SCHEDULED_EVENT_TIME"] = _task_time_series(hist, "SCHEDULED_TIME", "QUERY_START_TIME", "COMPLETED_TIME")
    hist["DURATION_SEC"] = pd.to_numeric(_df_col(hist, "DURATION_SEC", 0), errors="coerce").fillna(0.0)
    hist["IS_FAILED"] = _task_failure_mask(hist)
    hist["IS_SUCCEEDED"] = _task_success_mask(hist)
    return hist[hist["TASK_NAME"].astype(str).str.strip().ne("")].copy()

def _recovery_state_rank(value: object) -> int:
    state = str(value or "").upper()
    if "OPEN" in state:
        return 0
    if "LATE" in state or "BREACH" in state:
        return 1
    if "WITHIN" in state:
        return 2
    return 9

def _task_recovery_priority(state: str, downstream: int) -> str:
    state_upper = str(state or "").upper()
    if "OPEN" in state_upper and downstream >= 3:
        return "P1 - Open Graph Recovery"
    if "OPEN" in state_upper:
        return "P2 - Open Recovery"
    if ("LATE" in state_upper or "BREACH" in state_upper) and downstream >= 3:
        return "P2 - Late Graph Recovery"
    if "LATE" in state_upper or "BREACH" in state_upper:
        return "P3 - Late Recovery"
    return "P4 - Verified Recovery"

def _task_owner_approval_state(row: pd.Series) -> str:
    recovery_state = str(row.get("RECOVERY_STATE") or "").upper()
    signal = str(row.get("SIGNAL") or row.get("FAILURE_CATEGORY") or "").upper()
    if "OPEN" in recovery_state or "FAILED" in signal:
        return "Root-cause review required"
    if "LATE" in recovery_state or "SLA" in signal:
        return "DBA lead checks recovery telemetry"
    if "SUSPENDED" in signal:
        return "Review required before resume"
    if "COST" in signal or "REGRESSION" in signal:
        return "DBA release owner accepts or remediates baseline"
    return "DBA review before close"

def _task_owner_approval_status(row: pd.Series) -> str:
    state = str(row.get("OWNER_APPROVAL_STATE") or "").upper()
    if "NOT REQUIRED" in state:
        return "Not Required"
    if "APPROVAL REQUIRED" in state or "Verification" in state or "ROOT-CAUSE OWNER" in state:
        return "Requested"
    if "VERIFIES" in state or "ACCEPTS" in state:
        return "Requested"
    return "Requested"

def _build_task_recovery_sla_frame(
    history: pd.DataFrame,
    inventory: pd.DataFrame,
    target_hours: int = TASK_RECOVERY_SLA_HOURS,
    current_time: object | None = None,
) -> pd.DataFrame:
    hist = _normalize_task_history_for_recovery(history)
    if hist.empty or "TASK_NAME" not in hist.columns:
        return pd.DataFrame()

    inv = _prepare_inventory_for_failures(inventory)
    inv_lookup = {}
    if inv is not None and not inv.empty and "NAME" in inv.columns:
        inv_lookup = {
            str(row.get("NAME") or ""): row
            for _, row in inv.drop_duplicates("NAME", keep="last").iterrows()
        }

    now = pd.to_datetime(current_time, errors="coerce") if current_time is not None else pd.Timestamp.now(tz="UTC")
    if pd.isna(now):
        now = pd.Timestamp.now(tz="UTC")
    if getattr(now, "tzinfo", None) is not None:
        now = now.tz_localize(None)
    target_hours = max(1, safe_int(target_hours) or TASK_RECOVERY_SLA_HOURS)
    rows: list[dict] = []

    for task_name, group in hist.sort_values("EVENT_TIME").groupby("TASK_NAME", dropna=False):
        group = group.copy()
        failures = group[group["IS_FAILED"] & group["EVENT_TIME"].notna()]
        if failures.empty:
            continue
        latest_failure = failures.sort_values("EVENT_TIME").iloc[-1]
        failure_at = latest_failure.get("EVENT_TIME")
        after_success = group[
            group["IS_SUCCEEDED"]
            & group["EVENT_TIME"].notna()
            & (group["EVENT_TIME"] > failure_at)
        ].sort_values("EVENT_TIME")
        recovery_at = after_success.iloc[0].get("EVENT_TIME") if not after_success.empty else pd.NaT
        latest_run = group.sort_values("EVENT_TIME").iloc[-1]

        if pd.notna(recovery_at):
            recovery_hours = max(0.0, (recovery_at - failure_at).total_seconds() / 3600.0)
            recovery_state = "Recovered Within SLA" if recovery_hours <= target_hours else "Recovered Late"
        else:
            recovery_hours = max(0.0, (now - failure_at).total_seconds() / 3600.0) if pd.notna(failure_at) else None
            recovery_state = "Open Failure"

        meta = inv_lookup.get(str(task_name), pd.Series(dtype=object))
        downstream = safe_int(meta.get("DOWNSTREAM_TASK_COUNT", 0) if not meta.empty else 0)
        task_fqn = str(meta.get("TASK_FQN") or "").strip() if not meta.empty else ""
        if not task_fqn:
            db_name = latest_failure.get("DATABASE_NAME") or meta.get("DATABASE_NAME", "") if not meta.empty else latest_failure.get("DATABASE_NAME", "")
            schema_name = latest_failure.get("SCHEMA_NAME") or meta.get("SCHEMA_NAME", "") if not meta.empty else latest_failure.get("SCHEMA_NAME", "")
            if str(db_name or "").strip() and str(schema_name or "").strip():
                task_fqn = f"{db_name}.{schema_name}.{task_name}"

        base_owner = _task_owner(meta if not meta.empty else latest_failure)
        owner_context = resolve_owner_context(
            {
                "TASK_NAME": str(task_name),
                "TASK_FQN": task_fqn,
                "OWNER": base_owner,
                "CATEGORY": "Task & Procedure Reliability",
                "ALERT_TYPE": "Task Recovery",
            },
            entity=task_fqn or str(task_name),
            entity_type="Task",
            owner=base_owner,
            category="Task & Procedure Reliability",
            alert_type="Task Recovery",
        )

        row = {
            "TASK_NAME": str(task_name),
            "ROOT_TASK_NAME": meta.get("ROOT_TASK_NAME", str(task_name)) if not meta.empty else str(task_name),
            "PROCEDURE_NAME": meta.get("PROCEDURE_NAME", "") if not meta.empty else "",
            "TASK_FQN": task_fqn,
            "OWNER": owner_context.get("OWNER", base_owner),
            "OWNER_EMAIL": owner_context.get("OWNER_EMAIL", ""),
            "ONCALL_PRIMARY": owner_context.get("ONCALL_PRIMARY", ""),
            "ONCALL_SECONDARY": owner_context.get("ONCALL_SECONDARY", ""),
            "APPROVAL_GROUP": owner_context.get("APPROVAL_GROUP", ""),
            "ESCALATION_TARGET": owner_context.get("ESCALATION_TARGET", ""),
            "OWNER_SOURCE": owner_context.get("OWNER_SOURCE", ""),
            "OWNER_EVIDENCE": owner_context.get("OWNER_EVIDENCE", ""),
            "GRAPH_ROLE": meta.get("GRAPH_ROLE", "Unknown") if not meta.empty else "Unknown",
            "DOWNSTREAM_TASK_COUNT": downstream,
            "BLAST_RADIUS": meta.get("BLAST_RADIUS", "Unknown") if not meta.empty else "Unknown",
            "LAST_FAILURE_AT": failure_at,
            "RECOVERY_AT": recovery_at if pd.notna(recovery_at) else pd.NaT,
            "RECOVERY_HOURS": round(float(recovery_hours), 2) if recovery_hours is not None else None,
            "RECOVERY_SLA_TARGET_HOURS": target_hours,
            "RECOVERY_STATE": recovery_state,
            "RECOVERY_SLA_BREACH": recovery_state in {"Open Failure", "Recovered Late"},
            "LATEST_STATE": latest_run.get("STATE", ""),
            "FAILURE_QUERY_ID": latest_failure.get("QUERY_ID", ""),
            "LATEST_QUERY_ID": latest_run.get("QUERY_ID", ""),
            "ERROR_SIGNATURE": _failure_signature(latest_failure.get("ERROR_MESSAGE")),
        }
        row["INCIDENT_PRIORITY"] = _task_recovery_priority(recovery_state, downstream)
        row["OWNER_APPROVAL_STATE"] = _task_owner_approval_state(pd.Series(row))
        row["VERIFY_AFTER_FIX"] = (
            "Latest TASK_HISTORY run succeeds after the failure and recovery time is inside the configured SLA."
            if recovery_state == "Open Failure"
            else "Record TASK_HISTORY telemetry showing the successful recovery run and elapsed recovery time."
        )
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["_RECOVERY_RANK"] = frame["RECOVERY_STATE"].apply(_recovery_state_rank)
    return frame.sort_values(
        ["_RECOVERY_RANK", "DOWNSTREAM_TASK_COUNT", "LAST_FAILURE_AT"],
        ascending=[True, False, False],
    ).drop(columns=["_RECOVERY_RANK"], errors="ignore")

def _task_recovery_sla_summary(recovery: pd.DataFrame, target_hours: int = TASK_RECOVERY_SLA_HOURS) -> dict:
    if recovery is None or recovery.empty:
        return {
            "RECOVERY_TASKS": 0,
            "OPEN_RECOVERIES": 0,
            "RECOVERY_SLA_BREACHES": 0,
            "VERIFIED_RECOVERIES": 0,
            "RECOVERY_SLA_TARGET_HOURS": max(1, safe_int(target_hours) or TASK_RECOVERY_SLA_HOURS),
        }
    states = recovery.get("RECOVERY_STATE", pd.Series(dtype=str)).astype(str)
    open_mask = states.eq("Open Failure")
    late_mask = states.eq("Recovered Late")
    verified_mask = states.eq("Recovered Within SLA")
    return {
        "RECOVERY_TASKS": len(recovery),
        "OPEN_RECOVERIES": int(open_mask.sum()),
        "RECOVERY_SLA_BREACHES": int((open_mask | late_mask).sum()),
        "VERIFIED_RECOVERIES": int(verified_mask.sum()),
        "RECOVERY_SLA_TARGET_HOURS": max(1, safe_int(target_hours) or TASK_RECOVERY_SLA_HOURS),
    }

def _build_task_critical_path_snapshot(inventory: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    inv = _prepare_inventory_for_failures(inventory)
    if inv is None or inv.empty or "NAME" not in inv.columns:
        return pd.DataFrame()
    hist = _normalize_task_history_for_recovery(history)
    root_lookup = dict(zip(inv["NAME"].astype(str), inv["ROOT_TASK_NAME"].fillna(inv["NAME"]).astype(str)))
    if not hist.empty:
        hist["ROOT_TASK_NAME"] = hist["TASK_NAME"].map(root_lookup).fillna(hist["TASK_NAME"])
        hist_summary = hist.groupby("ROOT_TASK_NAME", dropna=False).agg(
            RUNS=("TASK_NAME", "count"),
            FAILURES=("IS_FAILED", lambda s: int(pd.Series(s).fillna(False).sum())),
            SUCCESSES=("IS_SUCCEEDED", lambda s: int(pd.Series(s).fillna(False).sum())),
            LAST_RUN_AT=("EVENT_TIME", "max"),
            MAX_DURATION_SEC=("DURATION_SEC", "max"),
        ).reset_index()
    else:
        hist_summary = pd.DataFrame(columns=["ROOT_TASK_NAME", "RUNS", "FAILURES", "SUCCESSES", "LAST_RUN_AT", "MAX_DURATION_SEC"])

    inv_state = _df_col(inv, "STATE").fillna("").astype(str).str.upper()
    inv = inv.copy()
    inv["IS_SUSPENDED"] = inv_state.eq("SUSPENDED")
    graph_summary = inv.groupby("ROOT_TASK_NAME", dropna=False).agg(
        TASK_COUNT=("NAME", "nunique"),
        SUSPENDED_TASKS=("IS_SUSPENDED", lambda s: int(pd.Series(s).fillna(False).sum())),
        DOWNSTREAM_TASK_COUNT=("DOWNSTREAM_TASK_COUNT", "max"),
        BLAST_RADIUS=("BLAST_RADIUS", lambda s: next((str(v) for v in s if str(v or "").strip()), "Unknown")),
        WAREHOUSES=("WAREHOUSE", lambda s: ", ".join(sorted({str(v) for v in s if str(v or "").strip()})[:5]) if "WAREHOUSE" in inv.columns else ""),
        PROCEDURES=("PROCEDURE_NAME", lambda s: ", ".join(sorted({str(v) for v in s if str(v or "").strip()})[:5])),
    ).reset_index()
    snapshot = graph_summary.merge(hist_summary, on="ROOT_TASK_NAME", how="left")
    for col in ["RUNS", "FAILURES", "SUCCESSES", "MAX_DURATION_SEC", "SUSPENDED_TASKS", "DOWNSTREAM_TASK_COUNT"]:
        if col not in snapshot.columns:
            snapshot[col] = 0
        snapshot[col] = pd.to_numeric(snapshot[col], errors="coerce").fillna(0)
    snapshot["CRITICAL_PATH_SCORE"] = (
        snapshot["FAILURES"] * 12
        + snapshot["SUSPENDED_TASKS"] * 10
        + snapshot["DOWNSTREAM_TASK_COUNT"] * 5
        + (snapshot["MAX_DURATION_SEC"] / 300).clip(upper=20)
    ).round(1)
    snapshot["CRITICAL_PATH_STATE"] = snapshot.apply(
        lambda row: "Incident Path" if safe_int(row.get("FAILURES")) > 0 or safe_int(row.get("SUSPENDED_TASKS")) > 0
        else "Watch Path" if safe_int(row.get("DOWNSTREAM_TASK_COUNT")) >= 3 or safe_float(row.get("MAX_DURATION_SEC")) >= 900
        else "Stable Path",
        axis=1,
    )
    return snapshot.sort_values(
        ["CRITICAL_PATH_SCORE", "DOWNSTREAM_TASK_COUNT", "MAX_DURATION_SEC"],
        ascending=[False, False, False],
    )

def _normalize_task_critical_path_mart(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    frame = df.copy()
    rename = {
        "critical_path_state": "CRITICAL_PATH_STATE",
        "critical_path_score": "CRITICAL_PATH_SCORE",
        "root_task_name": "ROOT_TASK_NAME",
        "task_count": "TASK_COUNT",
        "downstream_task_count": "DOWNSTREAM_TASK_COUNT",
        "suspended_tasks": "SUSPENDED_TASKS",
        "failures": "FAILURES",
        "runs": "RUNS",
        "successes": "SUCCESSES",
        "max_duration_sec": "MAX_DURATION_SEC",
        "last_run_at": "LAST_RUN_AT",
        "blast_radius": "BLAST_RADIUS",
        "warehouses": "WAREHOUSES",
        "procedures": "PROCEDURES",
        "owner_role": "OWNER_ROLE",
        "approval_path": "APPROVAL_PATH",
        "source_freshness": "SOURCE_FRESHNESS",
        "snapshot_ts": "SNAPSHOT_TS",
        "company": "COMPANY",
        "environment": "ENVIRONMENT",
        "database_name": "DATABASE_NAME",
    }
    frame = frame.rename(columns={col: rename.get(str(col), str(col).upper()) for col in frame.columns})
    for col in [
        "CRITICAL_PATH_SCORE", "TASK_COUNT", "DOWNSTREAM_TASK_COUNT", "SUSPENDED_TASKS",
        "FAILURES", "RUNS", "SUCCESSES", "MAX_DURATION_SEC",
    ]:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0)
    return frame.sort_values(
        ["CRITICAL_PATH_SCORE", "DOWNSTREAM_TASK_COUNT", "MAX_DURATION_SEC"],
        ascending=[False, False, False],
    )

def _task_ops_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = exceptions.copy()
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(3)
    if "INCIDENT_PRIORITY" in view.columns:
        view["_INCIDENT_RANK"] = view["INCIDENT_PRIORITY"].astype(str).str.extract(r"P(\d)", expand=False).fillna("9").astype(int)
    else:
        view["_INCIDENT_RANK"] = 9
    view["NEXT_WORKFLOW"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(_task_ops_workflow_for)
    view["NEXT_ACTION"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(lambda signal: _task_action_for(signal)[0])
    return view.sort_values(["_INCIDENT_RANK", "_RANK", "SIGNAL", "TASK_NAME"]).drop(
        columns=["_RANK", "_INCIDENT_RANK"], errors="ignore"
    )

def _task_recovery_command_board(exceptions: pd.DataFrame, recovery_sla: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    seen_tasks: set[str] = set()
    if exceptions is not None and not exceptions.empty:
        for _, row in _task_ops_priority_view(exceptions).head(50).iterrows():
            task_name = str(row.get("TASK_NAME") or row.get("ROOT_TASK_NAME") or "").strip()
            if task_name:
                seen_tasks.add(task_name)
            readiness = str(row.get("RECOVERY_READINESS") or _task_exception_recovery_readiness(row)).strip()
            owner_state = str(row.get("OWNER_APPROVAL_STATE") or _task_owner_approval_state(row)).strip()
            rows.append({
                "INCIDENT_PRIORITY": row.get("INCIDENT_PRIORITY", ""),
                "COMMAND_STATE": "Blocked" if readiness.upper().startswith("BLOCKED") else "Ready for DBA review",
                "SIGNAL": row.get("SIGNAL", ""),
                "TASK_NAME": task_name,
                "ROOT_TASK_NAME": row.get("ROOT_TASK_NAME", ""),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
                "DOWNSTREAM_TASK_COUNT": safe_int(row.get("DOWNSTREAM_TASK_COUNT")),
                "RECOVERY_STATE": row.get("RECOVERY_STATE", ""),
                "RECOVERY_READINESS": readiness,
                "OWNER_APPROVAL_STATE": owner_state,
                "ONCALL_PRIMARY": row.get("ONCALL_PRIMARY", ""),
                "APPROVAL_GROUP": row.get("APPROVAL_GROUP", ""),
                "NEXT_WORKFLOW": row.get("NEXT_WORKFLOW", _task_ops_workflow_for(row.get("SIGNAL", ""))),
                "NEXT_ACTION": row.get("NEXT_ACTION", _task_action_for(row.get("SIGNAL", ""))[0]),
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", "Verify the next successful TASK_HISTORY run before closure."),
            })

    if recovery_sla is not None and not recovery_sla.empty:
        for _, row in recovery_sla.iterrows():
            task_name = str(row.get("TASK_NAME") or "").strip()
            recovery_state = str(row.get("RECOVERY_STATE") or "").strip()
            if task_name in seen_tasks or recovery_state == "Recovered Within SLA":
                continue
            rows.append({
                "INCIDENT_PRIORITY": row.get("INCIDENT_PRIORITY", ""),
                "COMMAND_STATE": "Blocked" if recovery_state in {"Open Failure", "Recovered Late"} else "Ready for DBA review",
                "SIGNAL": "Open Recovery SLA" if recovery_state == "Open Failure" else "Recovery SLA Review",
                "TASK_NAME": task_name,
                "ROOT_TASK_NAME": row.get("ROOT_TASK_NAME", ""),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
                "DOWNSTREAM_TASK_COUNT": safe_int(row.get("DOWNSTREAM_TASK_COUNT")),
                "RECOVERY_STATE": recovery_state,
                "RECOVERY_READINESS": (
                    "Blocked - confirm successful recovery run first"
                    if recovery_state == "Open Failure"
                    else "Blocked - record late recovery telemetry before close"
                ),
                "OWNER_APPROVAL_STATE": row.get("OWNER_APPROVAL_STATE", ""),
                "ONCALL_PRIMARY": row.get("ONCALL_PRIMARY", ""),
                "APPROVAL_GROUP": row.get("APPROVAL_GROUP", ""),
                "NEXT_WORKFLOW": "Failure Console",
                "NEXT_ACTION": "Record recovery telemetry and confirm the next successful task run before closure.",
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", "Record TASK_HISTORY recovery telemetry before closure."),
            })

    board = pd.DataFrame(rows)
    if board.empty:
        return board
    priority_rank = board["INCIDENT_PRIORITY"].astype(str).str.extract(r"P(\d)", expand=False).fillna("9").astype(int)
    board["_PRIORITY_RANK"] = priority_rank
    board["_COMMAND_RANK"] = board["COMMAND_STATE"].map({"Blocked": 0, "Ready for DBA review": 1}).fillna(9)
    return board.sort_values(
        ["_COMMAND_RANK", "_PRIORITY_RANK", "DOWNSTREAM_TASK_COUNT", "TASK_NAME"],
        ascending=[True, True, False, True],
    ).drop(columns=["_COMMAND_RANK", "_PRIORITY_RANK"], errors="ignore").reset_index(drop=True)

def _task_ops_workflow_for(signal: str) -> str:
    signal = str(signal or "").upper()
    if "FAILED" in signal:
        return "Failure Console"
    if "LONG" in signal or "SLA" in signal or "COST" in signal or "REGRESSION" in signal:
        return "SLA & Cost Drift"
    if "SUSPENDED" in signal:
        return "Control Center"
    return "Job Status Brief"

def _task_action_for(signal: str) -> tuple[str, str]:
    signal = str(signal or "").upper()
    if "OPEN RECOVERY" in signal:
        return (
            "Keep the incident open until a successful recovery run is visible and telemetry status is recorded.",
            "-- Confirm with TASK_HISTORY before retrying or closing the incident.",
        )
    if "RECOVERY" in signal:
        return (
            "Record the recovery telemetry, compare elapsed recovery time to SLA, and decide whether the task graph needs tuning.",
            "-- Review TASK_HISTORY failure and succeeding run timestamps.",
        )
    if "FAILED" in signal:
        return (
            "Review task error, linked query/procedure, upstream dependency, and retry the root task after correction.",
            "-- Review TASK_HISTORY failure and QUERY_HISTORY by QUERY_ID before retry.",
        )
    if "SUSPENDED" in signal:
        return (
            "Confirm suspension was intentional; resume only after review and dependency check.",
            "ALTER TASK <db>.<schema>.<task_name> RESUME;",
        )
    if "LONG" in signal or "SLA" in signal:
        return (
            "Compare latest duration to historical average, inspect child task bottlenecks, and tune the procedure/query path.",
            "-- Review task duration trend and query profile for the linked QUERY_ID.",
        )
    if "COST" in signal or "REGRESSION" in signal:
        return (
            "Compare the latest run to the pre-release baseline, inspect linked query profile, and validate warehouse/procedure changes.",
            "-- Review estimated credits, cloud services credits, warehouse size, and procedure code changes before the next scheduled run.",
        )
    return (
        "Review graph dependency and procedure execution context before operational action.",
        "-- Inspect SHOW TASKS, TASK_HISTORY, and linked CALL history.",
    )

def _failure_signature(text: object) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    cleaned = re.sub(r"\b[0-9a-f]{8,}[-0-9a-f]*\b", "<id>", cleaned, flags=re.IGNORECASE)
    return cleaned[:180] or "No error text"

def _failure_diagnosis(error_text: object, query_text: object = "") -> dict[str, str]:
    err = str(error_text or "")
    query = str(query_text or "")
    combined = f"{err}\n{query}".upper()

    if any(token in combined for token in ["INSUFFICIENT PRIVILEGE", "NOT AUTHORIZED", "ACCESS DENIED", "PERMISSION", "PRIVILEGE"]):
        return {
            "CATEGORY": "Privilege / RBAC",
            "PROBABLE_CAUSE": "The task execution role or procedure execution role lacks required privileges.",
            "RECOMMENDED_ACTION": "Check task role, procedure role, EXECUTE privileges, warehouse USAGE, and object grants before retry.",
        }
    if any(token in combined for token in ["INVALID IDENTIFIER", "DOES NOT EXIST", "NOT EXIST", "OBJECT", "UNKNOWN TABLE", "UNKNOWN VIEW"]):
        return {
            "CATEGORY": "Object Dependency / Drift",
            "PROBABLE_CAUSE": "A referenced object, column, schema, or dependency changed or is not visible to the task role.",
            "RECOMMENDED_ACTION": "Compare recent object changes, validate fully qualified object names, and confirm grants on upstream objects.",
        }
    if any(token in combined for token in ["NUMERIC VALUE", "DATE", "TIMESTAMP", "BOOLEAN", "CAST", "CONVERT", "TRUNCATED", "INVALID VALUE"]):
        return {
            "CATEGORY": "Data Quality / Type Conversion",
            "PROBABLE_CAUSE": "Input data no longer matches the stored procedure's conversion assumptions.",
            "RECOMMENDED_ACTION": "Find the source rows causing conversion failure, add TRY_* conversion safeguards, and document the data contract gap.",
        }
    if any(token in combined for token in ["SQL COMPILATION", "SYNTAX", "UNEXPECTED", "PARSE"]):
        return {
            "CATEGORY": "SQL / Procedure Code",
            "PROBABLE_CAUSE": "The task statement or stored procedure body is invalid in the current environment.",
            "RECOMMENDED_ACTION": "Open the linked query text/procedure definition, validate object names and syntax, then redeploy the procedure.",
        }
    if any(token in combined for token in ["WAREHOUSE", "STATEMENT_TIMEOUT", "TIMEOUT", "MEMORY", "SPILL", "RESOURCE"]):
        return {
            "CATEGORY": "Warehouse / Runtime Capacity",
            "PROBABLE_CAUSE": "The task may be blocked by warehouse state, timeout, memory pressure, or capacity limits.",
            "RECOMMENDED_ACTION": "Check Cost & Contract warehouse capacity telemetry for queue/spill pressure; resume or resize only after confirming workload demand.",
        }
    if any(token in combined for token in ["LOCK", "TRANSACTION", "DEADLOCK", "BLOCKED"]):
        return {
            "CATEGORY": "Concurrency / Locking",
            "PROBABLE_CAUSE": "The task was blocked by concurrent data/object changes or transaction contention.",
            "RECOMMENDED_ACTION": "Review overlapping task windows, query blockers, and transaction timing before retrying.",
        }
    return {
        "CATEGORY": "Unclassified Failure",
        "PROBABLE_CAUSE": "The error pattern does not match a known rule yet.",
        "RECOMMENDED_ACTION": "Review query profile, procedure code, task history, and recent Change/Drift events; add a new diagnosis rule if repeated.",
    }

def _estimate_query_credits(row: pd.Series) -> tuple[float, float]:
    size = str(row.get("WAREHOUSE_SIZE") or row.get("WAREHOUSE_SIZE_QUERY") or "").strip()
    elapsed = safe_float(row.get("QUERY_ELAPSED_SEC") or row.get("DURATION_SEC") or 0)
    compute = CREDIT_RATES.get(size, CREDIT_RATES.get(size.title(), 1)) * elapsed / 3600 if elapsed > 0 else 0.0
    cloud = safe_float(row.get("CLOUD_CREDITS"))
    return round(compute, 6), round(compute + cloud, 6)

def _normalize_query_details(query_details: pd.DataFrame) -> pd.DataFrame:
    qd = query_details.copy() if query_details is not None else pd.DataFrame()
    if qd.empty:
        return qd
    qd.columns = [str(col).upper() for col in qd.columns]
    for col in ["QUERY_ELAPSED_SEC", "CLOUD_CREDITS", "BYTES_SCANNED", "ROWS_PRODUCED"]:
        if col not in qd.columns:
            qd[col] = 0
        qd[col] = pd.to_numeric(qd[col], errors="coerce").fillna(0)
    estimates = qd.apply(_estimate_query_credits, axis=1)
    qd["EST_COMPUTE_CREDITS"] = [item[0] for item in estimates]
    qd["EST_TOTAL_CREDITS"] = [item[1] for item in estimates]
    return qd

def _prepare_inventory_for_failures(inventory: pd.DataFrame) -> pd.DataFrame:
    prepared = inventory.copy() if inventory is not None else pd.DataFrame()
    if prepared.empty:
        return prepared
    prepared["PROCEDURE_NAME"] = _df_col(prepared, "DEFINITION").apply(_procedure_from_definition)
    prepared["IMPACT_OBJECTS"] = _df_col(prepared, "DEFINITION").apply(_extract_object_candidates)
    prepared["ROOT_TASK_NAME"] = prepared.apply(_task_root_name, axis=1)
    prepared["TASK_FQN"] = prepared.apply(_task_full_name, axis=1)
    return _annotate_task_graph_impact(prepared)

def _failure_incident_priority(row: pd.Series) -> str:
    category = str(row.get("FAILURE_CATEGORY") or "").upper()
    downstream = safe_int(row.get("DOWNSTREAM_TASK_COUNT"))
    pattern_failures = safe_int(row.get("PATTERN_FAILURE_COUNT"))
    pattern_tasks = safe_int(row.get("PATTERN_TASK_COUNT"))
    duration = safe_float(row.get("DURATION_SEC") or row.get("QUERY_ELAPSED_SEC"))
    critical_categories = {"PRIVILEGE / RBAC", "OBJECT DEPENDENCY / DRIFT", "WAREHOUSE / RUNTIME CAPACITY"}
    if category in critical_categories and (downstream >= 3 or pattern_tasks >= 2 or pattern_failures >= 3):
        return "P1 - Graph Incident"
    if category in critical_categories or downstream >= 1 or pattern_failures >= 3:
        return "P2 - Production Risk"
    if "DATA QUALITY" in category or duration >= 300:
        return "P3 - Pipeline Defect"
    return "P4 - Review"

def _failure_recovery_readiness(row: pd.Series) -> str:
    category = str(row.get("FAILURE_CATEGORY") or "").upper()
    retry_sql = str(row.get("RETRY_SQL") or "").strip()
    if not retry_sql or retry_sql.startswith("--"):
        return "Blocked - task FQN missing"
    if "PRIVILEGE" in category:
        return "Blocked - grant or role fix first"
    if "OBJECT DEPENDENCY" in category:
        return "Blocked - object dependency fix first"
    if "WAREHOUSE" in category or "RUNTIME CAPACITY" in category:
        return "Blocked - warehouse or capacity review first"
    if "DATA QUALITY" in category:
        return "Blocked - data correction first"
    return "Ready after DBA review"

def _verification_after_failure(row: pd.Series) -> str:
    signature = str(row.get("ERROR_SIGNATURE") or "").strip()
    if signature and signature != "No error text":
        return f"Latest TASK_HISTORY run succeeds and no longer shows signature: {signature[:120]}"
    return "Latest TASK_HISTORY run succeeds and linked QUERY_HISTORY has no error_code/error_message."

def _task_exception_incident_priority(row: pd.Series) -> str:
    signal = str(row.get("SIGNAL") or "").upper()
    downstream = safe_int(row.get("DOWNSTREAM_TASK_COUNT"))
    graph_role = str(row.get("GRAPH_ROLE") or "").upper()
    if "OPEN RECOVERY" in signal and downstream >= 3:
        return "P1 - Open Graph Recovery"
    if "OPEN RECOVERY" in signal:
        return "P2 - Open Recovery"
    if "RECOVERY" in signal and downstream >= 3:
        return "P2 - Late Graph Recovery"
    if "RECOVERY" in signal:
        return "P3 - Late Recovery"
    if "FAILED" in signal and downstream >= 3:
        return "P1 - Graph Incident"
    if "FAILED" in signal or ("SUSPENDED" in signal and (downstream >= 1 or graph_role == "ROOT")):
        return "P2 - Production Risk"
    if "LONG" in signal or "SLA" in signal or "COST" in signal or "REGRESSION" in signal:
        return "P3 - Performance Regression"
    return "P4 - Review"

def _task_exception_recovery_readiness(row: pd.Series) -> str:
    signal = str(row.get("SIGNAL") or "").upper()
    if "OPEN RECOVERY" in signal:
        return "Blocked - confirm successful recovery run first"
    if "RECOVERY" in signal:
        return "Blocked - record late recovery telemetry before close"
    if "FAILED" in signal:
        return "Blocked - fix failure root cause first"
    if "SUSPENDED" in signal:
        return "Blocked - review before resume"
    if "LONG" in signal or "SLA" in signal:
        return "Blocked - tune or capacity-review before next release handoff"
    if "COST" in signal or "REGRESSION" in signal:
        return "Blocked - explain cost driver before accepting baseline"
    return "Ready after DBA review"

def _build_failure_console_frames(
    history: pd.DataFrame,
    inventory: pd.DataFrame,
    query_details: pd.DataFrame,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    hist = history.copy() if history is not None else pd.DataFrame()
    inv = _prepare_inventory_for_failures(inventory)
    qd = query_details.copy() if query_details is not None else pd.DataFrame()
    if hist.empty:
        return {"FAILURES": 0, "CATEGORIES": 0, "TASKS": 0, "CRITICAL": 0}, pd.DataFrame(), pd.DataFrame()

    hist["STATE"] = _df_col(hist, "STATE").astype(str).str.upper()
    failures = hist[_task_failure_mask(hist)].copy()
    if failures.empty:
        return {"FAILURES": 0, "CATEGORIES": 0, "TASKS": 0, "CRITICAL": 0}, failures, pd.DataFrame()

    if not inv.empty:
        join_cols = [
            col for col in [
            "NAME", "DATABASE_NAME", "SCHEMA_NAME", "ROOT_TASK_NAME",
                "PROCEDURE_NAME", "TASK_FQN", "WAREHOUSE", "DEFINITION", "IMPACT_OBJECTS",
                "DOWNSTREAM_TASK_COUNT", "GRAPH_ROLE", "BLAST_RADIUS", "RETRY_SCOPE",
            ] if col in inv.columns
        ]
        failures = failures.merge(
            inv[join_cols].rename(columns={"NAME": "INV_TASK_NAME", "WAREHOUSE": "TASK_WAREHOUSE"}),
            left_on="TASK_NAME",
            right_on="INV_TASK_NAME",
            how="left",
        )

    if not qd.empty and "QUERY_ID" in failures.columns and "QUERY_ID" in qd.columns:
        failures = failures.merge(
            qd,
            left_on="QUERY_ID",
            right_on="QUERY_ID",
            how="left",
            suffixes=("", "_QUERY"),
        )

    diagnoses = []
    for _, row in failures.iterrows():
        error_text = row.get("ERROR_MESSAGE") or row.get("QUERY_ERROR_MESSAGE") or ""
        diagnosis = _failure_diagnosis(error_text, row.get("QUERY_TEXT", ""))
        diagnoses.append(diagnosis)
    diag_df = pd.DataFrame(diagnoses, index=failures.index)
    failures["FAILURE_CATEGORY"] = diag_df["CATEGORY"]
    failures["PROBABLE_CAUSE"] = diag_df["PROBABLE_CAUSE"]
    failures["RECOMMENDED_ACTION"] = diag_df["RECOMMENDED_ACTION"]
    failures["ERROR_SIGNATURE"] = failures.apply(
        lambda row: _failure_signature(row.get("ERROR_MESSAGE") or row.get("QUERY_ERROR_MESSAGE")),
        axis=1,
    )
    failures["RETRY_SQL"] = failures.apply(
        lambda row: f"EXECUTE TASK {row.get('TASK_FQN')};" if str(row.get("TASK_FQN") or "").strip() else "-- Task FQN unavailable; reload task inventory.",
        axis=1,
    )
    if "IMPACT_OBJECTS" not in failures.columns:
        failures["IMPACT_OBJECTS"] = ""
    failures["IMPACT_OBJECTS"] = [
        existing if str(existing or "").strip() else _extract_object_candidates(query_text)
        for existing, query_text in zip(_df_col(failures, "IMPACT_OBJECTS"), _df_col(failures, "QUERY_TEXT"))
    ]
    for col in ["DOWNSTREAM_TASK_COUNT"]:
        if col not in failures.columns:
            failures[col] = 0
        failures[col] = pd.to_numeric(failures[col], errors="coerce").fillna(0).astype(int)
    for col, default in [
        ("GRAPH_ROLE", "Unknown"),
        ("BLAST_RADIUS", "Unknown"),
        ("RETRY_SCOPE", "Targeted task retry"),
    ]:
        if col not in failures.columns:
            failures[col] = default
        failures[col] = failures[col].fillna(default).astype(str)
    pattern_keys = ["FAILURE_CATEGORY", "ERROR_SIGNATURE"]
    failures["PATTERN_FAILURE_COUNT"] = failures.groupby(pattern_keys, dropna=False)["TASK_NAME"].transform("count")
    failures["PATTERN_TASK_COUNT"] = failures.groupby(pattern_keys, dropna=False)["TASK_NAME"].transform("nunique")
    failures["INCIDENT_PRIORITY"] = failures.apply(_failure_incident_priority, axis=1)
    failures["RECOVERY_READINESS"] = failures.apply(_failure_recovery_readiness, axis=1)
    failures["VERIFY_AFTER_FIX"] = failures.apply(_verification_after_failure, axis=1)
    recovery = _build_task_recovery_sla_frame(hist, inv)
    if not recovery.empty:
        recovery_cols = [
            col for col in [
                "TASK_NAME", "RECOVERY_STATE", "RECOVERY_HOURS", "RECOVERY_SLA_TARGET_HOURS",
                "RECOVERY_AT", "OWNER_APPROVAL_STATE",
            ] if col in recovery.columns
        ]
        failures = failures.merge(recovery[recovery_cols], on="TASK_NAME", how="left")
        failures["RECOVERY_STATE"] = failures["RECOVERY_STATE"].fillna("No recent recovery signal")
        failures["OWNER_APPROVAL_STATE"] = failures.apply(
            lambda row: row.get("OWNER_APPROVAL_STATE") or _task_owner_approval_state(row),
            axis=1,
        )
        failures["VERIFY_AFTER_FIX"] = failures.apply(
            lambda row: (
                f"{row.get('VERIFY_AFTER_FIX')} Recovery SLA: {row.get('RECOVERY_STATE')} "
                f"against {safe_int(row.get('RECOVERY_SLA_TARGET_HOURS'))}h target."
            ),
            axis=1,
        )
    else:
        failures["RECOVERY_STATE"] = "No recent recovery signal"
        failures["OWNER_APPROVAL_STATE"] = failures.apply(_task_owner_approval_state, axis=1)
    failures["SEVERITY"] = failures["INCIDENT_PRIORITY"].apply(
        lambda value: "Critical" if str(value).startswith("P1")
        else "High" if str(value).startswith("P2")
        else "Medium" if str(value).startswith("P3")
        else "Low"
    )
    failures["RUNBOOK_NOTE"] = failures.apply(
        lambda row: (
            f"{row.get('INCIDENT_PRIORITY', 'Priority pending')} | {row.get('TASK_NAME', 'Unknown task')} failed. "
            f"Category: {row.get('FAILURE_CATEGORY')}. "
            f"Recovery: {row.get('RECOVERY_READINESS')}. "
            f"Next action: {row.get('RECOMMENDED_ACTION')}"
        ),
        axis=1,
    )

    patterns = failures.groupby(["FAILURE_CATEGORY", "ERROR_SIGNATURE"], dropna=False).agg(
        FAILURE_COUNT=("TASK_NAME", "count"),
        TASK_COUNT=("TASK_NAME", "nunique"),
        TASKS=("TASK_NAME", lambda s: ", ".join(sorted(set(s.astype(str)))[:8])),
        INCIDENT_PRIORITY=("INCIDENT_PRIORITY", lambda s: sorted(set(s.astype(str)))[0]),
        RECOVERY_READINESS=("RECOVERY_READINESS", lambda s: sorted(set(s.astype(str)))[0]),
        RECOMMENDED_ACTION=("RECOMMENDED_ACTION", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
        DOWNSTREAM_TASK_COUNT=("DOWNSTREAM_TASK_COUNT", "max"),
        FIRST_SEEN=("SCHEDULED_TIME", "min") if "SCHEDULED_TIME" in failures.columns else ("TASK_NAME", "count"),
        LAST_SEEN=("SCHEDULED_TIME", "max") if "SCHEDULED_TIME" in failures.columns else ("TASK_NAME", "count"),
    ).reset_index().sort_values(["INCIDENT_PRIORITY", "FAILURE_COUNT", "TASK_COUNT"], ascending=[True, False, False])

    critical_categories = {"Privilege / RBAC", "Object Dependency / Drift", "Warehouse / Runtime Capacity"}
    summary = {
        "FAILURES": len(failures),
        "CATEGORIES": failures["FAILURE_CATEGORY"].nunique(),
        "TASKS": failures["TASK_NAME"].nunique() if "TASK_NAME" in failures.columns else 0,
        "CRITICAL": int(
            failures["INCIDENT_PRIORITY"].astype(str).str.startswith("P1").sum()
            + failures["INCIDENT_PRIORITY"].astype(str).str.startswith("P2").sum()
        ),
        "P1_INCIDENTS": int(failures["INCIDENT_PRIORITY"].astype(str).str.startswith("P1").sum()),
        "BLOCKED_RECOVERIES": int(failures["RECOVERY_READINESS"].astype(str).str.startswith("Blocked").sum()),
        **_task_recovery_sla_summary(recovery),
    }
    return summary, failures, patterns

def _build_failure_runbook_markdown(company: str, days: int, summary: dict, failures: pd.DataFrame, patterns: pd.DataFrame) -> str:
    lines = [
        f"# OVERWATCH Failure Runbook - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Failures: {safe_int(summary.get('FAILURES')):,}",
        f"- Affected tasks: {safe_int(summary.get('TASKS')):,}",
        f"- Failure categories: {safe_int(summary.get('CATEGORIES')):,}",
        f"- High-priority findings: {safe_int(summary.get('CRITICAL')):,}",
        f"- P1 graph incidents: {safe_int(summary.get('P1_INCIDENTS')):,}",
        f"- Blocked recoveries: {safe_int(summary.get('BLOCKED_RECOVERIES')):,}",
        f"- Open recoveries: {safe_int(summary.get('OPEN_RECOVERIES')):,}",
        f"- Recovery SLA breaches: {safe_int(summary.get('RECOVERY_SLA_BREACHES')):,}",
        "",
        "## Common Failure Patterns",
    ]
    if patterns is None or patterns.empty:
        lines.append("- No failed task patterns found.")
    else:
        for _, row in patterns.head(10).iterrows():
            lines.append(
                "- "
                f"{row.get('INCIDENT_PRIORITY', '')} | {safe_int(row.get('FAILURE_COUNT'))}x | {row.get('FAILURE_CATEGORY')} | "
                f"{row.get('ERROR_SIGNATURE')} | Tasks: {row.get('TASKS')}"
            )
    lines.extend(["", "## DBA Triage Steps"])
    if failures is not None and not failures.empty:
        for _, row in failures.head(10).iterrows():
            lines.extend([
                f"### {row.get('TASK_NAME', 'Unknown task')}",
                f"- Query ID: {row.get('QUERY_ID', '')}",
                f"- Procedure: {row.get('PROCEDURE_NAME', '')}",
                f"- Priority: {row.get('INCIDENT_PRIORITY', '')}",
                f"- Graph role: {row.get('GRAPH_ROLE', '')}",
                f"- Downstream tasks: {safe_int(row.get('DOWNSTREAM_TASK_COUNT')):,}",
                f"- Category: {row.get('FAILURE_CATEGORY', '')}",
                f"- Impact hints: {row.get('IMPACT_OBJECTS', '')}",
                f"- Probable cause: {row.get('PROBABLE_CAUSE', '')}",
                f"- Recommended action: {row.get('RECOMMENDED_ACTION', '')}",
                f"- Recovery status: {row.get('RECOVERY_READINESS', '')}",
                f"- Recovery SLA state: {row.get('RECOVERY_STATE', '')}",
                f"- Status: {row.get('OWNER_APPROVAL_STATE', '')}",
                f"- Confirm after fix: {row.get('VERIFY_AFTER_FIX', '')}",
                "- Retry plan after fix: reviewed runbook action",
                "",
            ])
    lines.extend([
        "## Telemetry Limits",
        "- TASK_HISTORY and QUERY_HISTORY are ACCOUNT_USAGE-backed and can lag.",
        "- Procedure linkage is inferred from task definitions containing CALL statements.",
        "- Retry is review-gated; DBAs must confirm the root cause is fixed before execution.",
    ])
    return "\n".join(lines)

def _task_owner(row: pd.Series) -> str:
    return str(
        row.get("OWNER")
        or row.get("OWNER_ROLE")
        or row.get("PROCEDURE_OWNER")
        or row.get("ROLE_NAME")
        or row.get("USER_NAME")
        or "DBA / Data Engineering"
    )

def _task_environment(row: pd.Series) -> str:
    active_env = get_active_environment()
    return str(row.get("ENVIRONMENT") or (active_env if active_env != "ALL" else "") or "")

def _task_metric(row: pd.Series, *columns: str):
    for column in columns:
        if column in row and row.get(column) not in (None, ""):
            return safe_float(row.get(column))
    return None

def _build_task_ops_markdown(
    company: str,
    days: int,
    score: int,
    summary: dict,
    exceptions: pd.DataFrame,
) -> str:
    handoff_state, handoff_note = _task_task_status_handoff_state(summary)
    lines = [
        f"# OVERWATCH Task Graph Operations Brief - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Snowflake task handoff state: {handoff_state}",
        f"- Handoff note: {handoff_note}",
        f"- Pipeline tasks: {safe_int(summary.get('TOTAL_TASKS')):,}",
        f"- Task runs: {safe_int(summary.get('TOTAL_RUNS')):,}",
        f"- Running tasks: {safe_int(summary.get('RUNNING_TASKS')):,}",
        f"- Latest failed tasks: {safe_int(summary.get('LATEST_FAILED_TASKS')):,}",
        f"- Failed runs: {safe_int(summary.get('FAILED_RUNS')):,}",
        f"- Suspended tasks: {safe_int(summary.get('SUSPENDED_TASKS')):,}",
        f"- Long-running/SLA candidates: {safe_int(summary.get('LONG_RUNNING_TASKS')):,}",
        f"- Cost drift/release-regression candidates: {safe_int(summary.get('COST_DRIFT_TASKS')):,}",
        f"- P1 graph incidents: {safe_int(summary.get('P1_INCIDENTS')):,}",
        f"- Blocked recoveries: {safe_int(summary.get('BLOCKED_RECOVERIES')):,}",
        f"- Open recoveries: {safe_int(summary.get('OPEN_RECOVERIES')):,}",
        f"- Recovery SLA breaches: {safe_int(summary.get('RECOVERY_SLA_BREACHES')):,}",
        f"- Recovery SLA target: {safe_int(summary.get('RECOVERY_SLA_TARGET_HOURS')):,} hours",
        "",
        "## DBA Narrative",
        (
            "This Snowflake task operations view helps find broken task graphs, "
            "failed sessions, suspended jobs, slow runs, linked procedures, and retry candidates. "
            "It should be the first stop before on-demand execution, resuming task graphs, or handing "
            "job status to Snowflake task."
        ),
        "",
        "## Top Operational Exceptions",
    ]
    if exceptions is None or exceptions.empty:
        lines.append("- No task graph exceptions found for the selected scope.")
    else:
        for _, row in exceptions.head(10).iterrows():
            lines.append(
                "- "
                f"{row.get('INCIDENT_PRIORITY', row.get('SEVERITY', 'Watch'))} | "
                f"{row.get('SIGNAL', 'Unknown')} | "
                f"{row.get('TASK_NAME', '')} | {row.get('PROCEDURE_NAME', '')} | "
                f"{row.get('DETAIL', '')} | Recovery: {row.get('RECOVERY_READINESS', '')} | "
                f"SLA state: {row.get('RECOVERY_STATE', '')} | Status: {row.get('OWNER_APPROVAL_STATE', '')} | "
                f"Downstream tasks: {safe_int(row.get('DOWNSTREAM_TASK_COUNT')):,} | "
                f"Impact hints: {row.get('IMPACT_OBJECTS', '')}"
            )
    lines.extend([
        "",
        "## Telemetry Limits",
        "- TASK_HISTORY columns vary by Snowflake account and role; missing columns are feature-gated.",
        "- Procedure linkage is inferred from task definition CALL statements when available.",
        "- Admin actions require Snowflake task privileges and typed confirmation where prompted.",
    ])
    return "\n".join(lines)

def _build_task_ops_frames(
    tl: pd.DataFrame,
    th: pd.DataFrame,
    query_details: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    inventory = tl.copy() if tl is not None else pd.DataFrame()
    history = th.copy() if th is not None else pd.DataFrame()
    qd = _normalize_query_details(query_details)
    if not inventory.empty:
        inventory["PROCEDURE_NAME"] = _df_col(inventory, "DEFINITION").apply(_procedure_from_definition)
        inventory["IMPACT_OBJECTS"] = _df_col(inventory, "DEFINITION").apply(_extract_object_candidates)
        inventory["ROOT_TASK_NAME"] = inventory.apply(_task_root_name, axis=1)
        inventory["TASK_FQN"] = (
            _df_col(inventory, "DATABASE_NAME").astype(str) + "."
            + _df_col(inventory, "SCHEMA_NAME").astype(str) + "."
            + _df_col(inventory, "NAME").astype(str)
        )
        inventory = _annotate_task_graph_impact(inventory)
    if not history.empty:
        history["DURATION_SEC"] = pd.to_numeric(_df_col(history, "DURATION_SEC", 0), errors="coerce").fillna(0)
        history["STATE"] = _df_col(history, "STATE").astype(str).str.upper()
        if not qd.empty and "QUERY_ID" in history.columns and "QUERY_ID" in qd.columns:
            qd_cols = [
                col for col in [
                    "QUERY_ID", "USER_NAME", "ROLE_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                    "DATABASE_NAME", "SCHEMA_NAME", "QUERY_TYPE", "EXECUTION_STATUS",
                    "QUERY_ELAPSED_SEC", "CLOUD_CREDITS", "EST_COMPUTE_CREDITS",
                    "EST_TOTAL_CREDITS", "BYTES_SCANNED", "ROWS_PRODUCED", "QUERY_TEXT",
                ] if col in qd.columns
            ]
            history = history.merge(qd[qd_cols], on="QUERY_ID", how="left", suffixes=("", "_QUERY"))
        if "EST_TOTAL_CREDITS" not in history.columns:
            history["EST_TOTAL_CREDITS"] = 0.0
        history["EST_TOTAL_CREDITS"] = pd.to_numeric(history["EST_TOTAL_CREDITS"], errors="coerce").fillna(0.0)
        latest_idx = history.groupby("TASK_NAME")["SCHEDULED_TIME"].idxmax() if "TASK_NAME" in history.columns else []
        latest = history.loc[latest_idx].copy() if len(latest_idx) else pd.DataFrame()
        trend = history.groupby("TASK_NAME", dropna=False).agg(
            RUNS=("TASK_NAME", "count"),
            FAILURES=("STATE", lambda s: int(s.astype(str).str.upper().isin(TASK_FAILURE_STATES).sum())),
            AVG_DURATION_SEC=("DURATION_SEC", "mean"),
            MAX_DURATION_SEC=("DURATION_SEC", "max"),
            AVG_EST_CREDITS=("EST_TOTAL_CREDITS", "mean"),
            MAX_EST_CREDITS=("EST_TOTAL_CREDITS", "max"),
        ).reset_index()
        latest = latest.merge(trend, on="TASK_NAME", how="left") if not latest.empty else pd.DataFrame()
    else:
        latest = pd.DataFrame()

    if not latest.empty and not inventory.empty:
        inventory_merge_cols = [
            col for col in [
                "NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "TASK_FQN", "STATE", "IMPACT_OBJECTS",
                "DOWNSTREAM_TASK_COUNT", "GRAPH_ROLE", "BLAST_RADIUS", "RETRY_SCOPE",
            ] if col in inventory.columns
        ]
        latest = latest.merge(
            inventory[inventory_merge_cols].rename(
                columns={"NAME": "INV_TASK_NAME", "STATE": "INVENTORY_STATE"}
            ),
            left_on="TASK_NAME",
            right_on="INV_TASK_NAME",
            how="left",
        )
    if not latest.empty:
        query_text = _df_col(latest, "QUERY_TEXT")
        task_objects = _df_col(latest, "IMPACT_OBJECTS")
        combined_objects = []
        for existing, sql_text in zip(task_objects, query_text):
            objects: list[str] = []
            for chunk in [existing, _extract_object_candidates(sql_text)]:
                for item in str(chunk or "").split(","):
                    cleaned = item.strip()
                    if cleaned and cleaned not in objects:
                        objects.append(cleaned)
            combined_objects.append(", ".join(objects[:12]))
        latest["IMPACT_OBJECTS"] = combined_objects

    exception_rows = []
    recovery = _build_task_recovery_sla_frame(history, inventory)
    if not latest.empty:
        for _, row in latest.iterrows():
            duration = safe_float(row.get("DURATION_SEC"))
            avg_duration = safe_float(row.get("AVG_DURATION_SEC"))
            est_credits = safe_float(row.get("EST_TOTAL_CREDITS"))
            avg_credits = safe_float(row.get("AVG_EST_CREDITS"))
            state = str(row.get("STATE", "")).upper()
            error_text = str(row.get("ERROR_MESSAGE") or "").strip().upper()
            has_error_text = error_text not in {"", "NONE", "NULL", "NAN"}
            duration_change_pct = ((duration - avg_duration) / avg_duration * 100) if avg_duration > 0 else 0.0
            cost_change_pct = ((est_credits - avg_credits) / avg_credits * 100) if avg_credits > 0 else 0.0
            common = {
                "TASK_NAME": row.get("TASK_NAME", ""),
                "ROOT_TASK_NAME": row.get("ROOT_TASK_NAME", ""),
                "PROCEDURE_NAME": row.get("PROCEDURE_NAME", ""),
                "QUERY_ID": row.get("QUERY_ID", ""),
                "STATE": state,
                "DURATION_SEC": duration,
                "AVG_DURATION_SEC": avg_duration,
                "DURATION_CHANGE_PCT": round(duration_change_pct, 1),
                "EST_TOTAL_CREDITS": est_credits,
                "AVG_EST_CREDITS": avg_credits,
                "COST_CHANGE_PCT": round(cost_change_pct, 1),
                "IMPACT_OBJECTS": row.get("IMPACT_OBJECTS", ""),
                "TASK_FQN": row.get("TASK_FQN", ""),
                "DOWNSTREAM_TASK_COUNT": safe_int(row.get("DOWNSTREAM_TASK_COUNT")),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
                "BLAST_RADIUS": row.get("BLAST_RADIUS", ""),
                "RETRY_SCOPE": row.get("RETRY_SCOPE", ""),
            }
            if state in TASK_FAILURE_STATES or has_error_text:
                exception_rows.append({
                    **common,
                    "SEVERITY": "High",
                    "SIGNAL": "Failed Task Run",
                    "DETAIL": str(row.get("ERROR_MESSAGE") or "")[:500],
                })
            if avg_duration > 0 and duration > avg_duration * 1.5 and duration > 300:
                exception_rows.append({
                    **common,
                    "SEVERITY": "High" if duration > avg_duration * 2 else "Medium",
                    "SIGNAL": "Long Running / SLA Risk",
                    "DETAIL": f"Latest {duration:,.0f}s vs avg {avg_duration:,.0f}s ({duration_change_pct:,.1f}% change)",
                })
            if avg_credits > 0 and est_credits > avg_credits * 1.5 and est_credits >= 0.01:
                exception_rows.append({
                    **common,
                    "SEVERITY": "High" if est_credits > avg_credits * 2 else "Medium",
                    "SIGNAL": "Cost Drift / Release Regression",
                    "DETAIL": f"Latest {est_credits:,.4f} credits vs avg {avg_credits:,.4f} ({cost_change_pct:,.1f}% change)",
                })
    if not inventory.empty and "STATE" in inventory.columns:
        suspended = inventory[inventory["STATE"].astype(str).str.upper().isin(["SUSPENDED"])]
        for _, row in suspended.iterrows():
            exception_rows.append({
                "SEVERITY": "Medium",
                "SIGNAL": "Suspended Task",
                "TASK_NAME": row.get("NAME", ""),
                "ROOT_TASK_NAME": row.get("ROOT_TASK_NAME", ""),
                "PROCEDURE_NAME": row.get("PROCEDURE_NAME", ""),
                "QUERY_ID": "",
                "STATE": row.get("STATE", ""),
                "DURATION_SEC": 0,
                "AVG_DURATION_SEC": 0,
                "DURATION_CHANGE_PCT": 0,
                "EST_TOTAL_CREDITS": 0,
                "AVG_EST_CREDITS": 0,
                "COST_CHANGE_PCT": 0,
                "IMPACT_OBJECTS": row.get("IMPACT_OBJECTS", ""),
                "DETAIL": "Task is suspended in SHOW TASKS.",
                "TASK_FQN": row.get("TASK_FQN", ""),
                "DOWNSTREAM_TASK_COUNT": safe_int(row.get("DOWNSTREAM_TASK_COUNT")),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
                "BLAST_RADIUS": row.get("BLAST_RADIUS", ""),
                "RETRY_SCOPE": row.get("RETRY_SCOPE", ""),
            })
    existing_failed_tasks = {
        str(row.get("TASK_NAME") or "")
        for row in exception_rows
        if str(row.get("SIGNAL") or "") == "Failed Task Run"
    }
    if not recovery.empty:
        for _, row in recovery.iterrows():
            recovery_state = str(row.get("RECOVERY_STATE") or "")
            if recovery_state == "Recovered Within SLA":
                continue
            if recovery_state == "Open Failure" and str(row.get("TASK_NAME") or "") in existing_failed_tasks:
                continue
            exception_rows.append({
                "SEVERITY": "High" if str(row.get("INCIDENT_PRIORITY") or "").startswith(("P1", "P2")) else "Medium",
                "SIGNAL": "Open Recovery SLA" if recovery_state == "Open Failure" else "Recovery SLA Breach",
                "TASK_NAME": row.get("TASK_NAME", ""),
                "ROOT_TASK_NAME": row.get("ROOT_TASK_NAME", ""),
                "PROCEDURE_NAME": row.get("PROCEDURE_NAME", ""),
                "QUERY_ID": row.get("FAILURE_QUERY_ID", ""),
                "STATE": row.get("LATEST_STATE", ""),
                "DURATION_SEC": 0,
                "AVG_DURATION_SEC": 0,
                "DURATION_CHANGE_PCT": 0,
                "EST_TOTAL_CREDITS": 0,
                "AVG_EST_CREDITS": 0,
                "COST_CHANGE_PCT": 0,
                "IMPACT_OBJECTS": "",
                "TASK_FQN": row.get("TASK_FQN", ""),
                "DOWNSTREAM_TASK_COUNT": safe_int(row.get("DOWNSTREAM_TASK_COUNT")),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
                "BLAST_RADIUS": row.get("BLAST_RADIUS", ""),
                "RETRY_SCOPE": "Root graph retry" if row.get("GRAPH_ROLE") == "Root" else "Targeted task retry",
                "DETAIL": (
                    f"{recovery_state}: recovery time {safe_float(row.get('RECOVERY_HOURS')):,.2f}h "
                    f"vs {safe_int(row.get('RECOVERY_SLA_TARGET_HOURS'))}h target."
                ),
            })
    exceptions = pd.DataFrame(exception_rows)
    if not exceptions.empty:
        if "DOWNSTREAM_TASK_COUNT" not in exceptions.columns:
            exceptions["DOWNSTREAM_TASK_COUNT"] = 0
        exceptions["DOWNSTREAM_TASK_COUNT"] = pd.to_numeric(
            exceptions["DOWNSTREAM_TASK_COUNT"], errors="coerce"
        ).fillna(0).astype(int)
        for col, default in [
            ("GRAPH_ROLE", "Unknown"),
            ("BLAST_RADIUS", "Unknown"),
            ("RETRY_SCOPE", "Targeted task retry"),
        ]:
            if col not in exceptions.columns:
                exceptions[col] = default
            exceptions[col] = exceptions[col].fillna(default).astype(str)
        if not recovery.empty and "TASK_NAME" in exceptions.columns:
            recovery_by_task = recovery.drop_duplicates("TASK_NAME", keep="last").set_index("TASK_NAME")
            for col in [
                "RECOVERY_STATE", "RECOVERY_HOURS", "RECOVERY_SLA_TARGET_HOURS",
                "RECOVERY_AT", "LAST_FAILURE_AT", "OWNER_APPROVAL_STATE",
            ]:
                if col in recovery_by_task.columns:
                    mapped = exceptions["TASK_NAME"].map(recovery_by_task[col])
                    if col in exceptions.columns:
                        exceptions[col] = exceptions[col].combine_first(mapped)
                    else:
                        exceptions[col] = mapped
        exceptions["INCIDENT_PRIORITY"] = exceptions.apply(_task_exception_incident_priority, axis=1)
        exceptions["RECOVERY_READINESS"] = exceptions.apply(_task_exception_recovery_readiness, axis=1)
        owner_approval = exceptions.get("OWNER_APPROVAL_STATE", pd.Series([""] * len(exceptions), index=exceptions.index))
        missing_owner_approval = owner_approval.fillna("").astype(str).str.strip().eq("")
        exceptions["OWNER_APPROVAL_STATE"] = owner_approval
        exceptions.loc[missing_owner_approval, "OWNER_APPROVAL_STATE"] = exceptions.loc[missing_owner_approval].apply(
            _task_owner_approval_state,
            axis=1,
        )
        exceptions["VERIFY_AFTER_FIX"] = exceptions.apply(
            lambda row: "Latest TASK_HISTORY run succeeds and runtime/credits return within baseline."
            if "FAILED" in str(row.get("SIGNAL") or "").upper()
            else "Next scheduled run remains within the selected SLA/cost threshold.",
            axis=1,
        )
        exceptions["SEVERITY"] = exceptions.apply(
            lambda row: "Critical" if str(row.get("INCIDENT_PRIORITY")).startswith("P1")
            else row.get("SEVERITY", "Medium"),
            axis=1,
        )
        exceptions["NEXT_WORKFLOW"] = exceptions["SIGNAL"].apply(_task_ops_workflow_for)
        exceptions["NEXT_ACTION"] = exceptions["SIGNAL"].apply(lambda signal: _task_action_for(signal)[0])
    history_state = history.get("STATE", pd.Series(dtype=str)).astype(str).str.upper() if not history.empty else pd.Series(dtype=str)
    inventory_state = inventory.get("STATE", pd.Series(dtype=str)).astype(str).str.upper() if not inventory.empty else pd.Series(dtype=str)
    latest_state = latest.get("STATE", pd.Series(dtype=str)).astype(str).str.upper() if not latest.empty else pd.Series(dtype=str)
    summary = {
        "TOTAL_TASKS": len(inventory),
        "TOTAL_RUNS": len(history),
        "FAILED_RUNS": int(history_state.isin(TASK_FAILURE_STATES).sum()) if not history_state.empty else 0,
        "LATEST_FAILED_TASKS": int(latest_state.isin(TASK_FAILURE_STATES).sum()) if not latest_state.empty else 0,
        "RUNNING_TASKS": int(latest_state.isin(TASK_RUNNING_STATES).sum()) if not latest_state.empty else 0,
        "LATEST_SUCCESS_TASKS": int(latest_state.isin(TASK_SUCCESS_STATES).sum()) if not latest_state.empty else 0,
        "SUSPENDED_TASKS": int((inventory_state == "SUSPENDED").sum()),
        "LONG_RUNNING_TASKS": int((exceptions.get("SIGNAL", pd.Series(dtype=str)) == "Long Running / SLA Risk").sum()) if not exceptions.empty else 0,
        "COST_DRIFT_TASKS": int((exceptions.get("SIGNAL", pd.Series(dtype=str)) == "Cost Drift / Release Regression").sum()) if not exceptions.empty else 0,
        "PROCEDURE_LINKS": int((inventory.get("PROCEDURE_NAME", pd.Series(dtype=str)).astype(str).str.len() > 0).sum()) if not inventory.empty else 0,
        "P1_INCIDENTS": int(exceptions.get("INCIDENT_PRIORITY", pd.Series(dtype=str)).astype(str).str.startswith("P1").sum()) if not exceptions.empty else 0,
        "BLOCKED_RECOVERIES": int(exceptions.get("RECOVERY_READINESS", pd.Series(dtype=str)).astype(str).str.startswith("Blocked").sum()) if not exceptions.empty else 0,
        **_task_recovery_sla_summary(recovery),
    }
    return summary, exceptions, latest

def _task_task_status_handoff_state(summary: dict) -> tuple[str, str]:
    if safe_int(summary.get("P1_INCIDENTS")) or safe_int(summary.get("LATEST_FAILED_TASKS")):
        return "Needs Triage", "Latest task job status includes failed production telemetry."
    if safe_int(summary.get("FAILED_RUNS")) or safe_int(summary.get("BLOCKED_RECOVERIES")):
        return "Needs Triage", "Recent failures or blocked recoveries need route-ready telemetry before Snowflake task handoff."
    if (
        safe_int(summary.get("SUSPENDED_TASKS"))
        or safe_int(summary.get("LONG_RUNNING_TASKS"))
        or safe_int(summary.get("COST_DRIFT_TASKS"))
        or safe_int(summary.get("RECOVERY_SLA_BREACHES"))
    ):
        return "Watch", "Task jobs are running, but performance, suspension, or recovery indicators need review."
    return "Ready", "Task jobs are ready for Snowflake task handoff in this scope."

def _state_distribution_text(df: pd.DataFrame, *, limit: int = 4) -> str:
    if df is None or df.empty or "STATE" not in df.columns:
        return "No live task status rows loaded."
    counts = df["STATE"].fillna("UNKNOWN").astype(str).str.upper().value_counts()
    return "; ".join(f"{state}: {count:,}" for state, count in counts.head(limit).items())

def _latest_task_timestamp(latest: pd.DataFrame) -> str:
    if latest is None or latest.empty:
        return ""
    for column in ["SCHEDULED_TIME", "QUERY_START_TIME", "COMPLETED_TIME"]:
        if column not in latest.columns:
            continue
        values = pd.to_datetime(latest[column], errors="coerce").dropna()
        if not values.empty:
            return str(values.max())
    return ""

def _first_task_value(row: pd.Series, *columns: str) -> object:
    for column in columns:
        value = row.get(column)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if str(value).strip().upper() not in {"", "NONE", "NULL", "NAN", "NAT"}:
            return value
    return ""

def _build_task_status_job_status_board(
    summary: dict,
    latest: pd.DataFrame,
    exceptions: pd.DataFrame,
) -> pd.DataFrame:
    handoff_state, handoff_note = _task_task_status_handoff_state(summary)
    perf_indicators = safe_int(summary.get("LONG_RUNNING_TASKS")) + safe_int(summary.get("COST_DRIFT_TASKS"))
    error_rows = _build_task_status_error_board(exceptions, latest)
    latest_timestamp = _latest_task_timestamp(latest)
    running = safe_int(summary.get("RUNNING_TASKS"))
    state_rank = {
        "Needs Triage": 0,
        "Alert": 0,
        "Watch": 1,
        "Running": 2,
        "Ready": 3,
    }
    rows = [
        {
            "TASK_STATUS_VIEW": "Job Status",
            "STATE": handoff_state,
            "INDICATOR": "Latest task job state",
            "COUNT": safe_int(summary.get("TOTAL_TASKS")),
            "EVIDENCE": _state_distribution_text(latest),
            "LAST_SEEN": latest_timestamp,
            "NEXT_ACTION": handoff_note,
        },
        {
            "TASK_STATUS_VIEW": "Performance Indicators",
            "STATE": "Watch" if perf_indicators else ("Running" if running else "Ready"),
            "INDICATOR": "Runtime or estimated-credit drift",
            "COUNT": perf_indicators,
            "EVIDENCE": (
                f"Long-running={safe_int(summary.get('LONG_RUNNING_TASKS')):,}; "
                f"cost drift={safe_int(summary.get('COST_DRIFT_TASKS')):,}; "
                f"running={running:,}."
            ),
            "LAST_SEEN": latest_timestamp,
            "NEXT_ACTION": "Review latest duration, query profile, warehouse, and release changes before handoff.",
        },
        {
            "TASK_STATUS_VIEW": "Errors",
            "STATE": "Alert" if not error_rows.empty else "Ready",
            "INDICATOR": "Recent task errors",
            "COUNT": len(error_rows),
            "EVIDENCE": (
                "; ".join(error_rows["ERROR_SIGNATURE"].dropna().astype(str).head(3).tolist())
                if not error_rows.empty
                else "No failed latest-run or exception error signatures loaded."
            ),
            "LAST_SEEN": latest_timestamp,
            "NEXT_ACTION": "Open Failure Console, confirm root cause, then record successful TASK_HISTORY telemetry.",
        },
        {
            "TASK_STATUS_VIEW": "Recovery",
            "STATE": "Alert" if safe_int(summary.get("BLOCKED_RECOVERIES")) else (
                "Watch" if safe_int(summary.get("OPEN_RECOVERIES")) or safe_int(summary.get("RECOVERY_SLA_BREACHES")) else "Ready"
            ),
            "INDICATOR": "Open or blocked recovery",
            "COUNT": safe_int(summary.get("OPEN_RECOVERIES")),
            "EVIDENCE": (
                f"Blocked={safe_int(summary.get('BLOCKED_RECOVERIES')):,}; "
                f"SLA breaches={safe_int(summary.get('RECOVERY_SLA_BREACHES')):,}; "
                f"target={safe_int(summary.get('RECOVERY_SLA_TARGET_HOURS')):,}h."
            ),
            "LAST_SEEN": latest_timestamp,
            "NEXT_ACTION": "Keep Snowflake task closure blocked until recovery telemetry and status are visible.",
        },
    ]
    board = pd.DataFrame(rows)
    board["_RANK"] = board["STATE"].map(state_rank).fillna(9)
    return board.sort_values(["_RANK", "TASK_STATUS_VIEW"]).drop(columns=["_RANK"], errors="ignore")

def _build_task_status_error_board(exceptions: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_row(row: pd.Series, *, source: str) -> None:
        task_name = str(row.get("TASK_NAME") or row.get("NAME") or "").strip()
        state = str(row.get("STATE") or "").strip().upper()
        detail = str(row.get("ERROR_MESSAGE") or row.get("DETAIL") or "").strip()
        signal = str(row.get("SIGNAL") or "").strip()
        if not detail and state not in TASK_FAILURE_STATES and "FAILED" not in signal.upper():
            return
        signature = _failure_signature(detail or signal or state)
        query_id = str(row.get("QUERY_ID") or row.get("FAILURE_QUERY_ID") or "").strip()
        key = (task_name.upper(), query_id.upper(), signature.upper())
        if key in seen:
            return
        seen.add(key)
        rows.append({
            "SOURCE": source,
            "SEVERITY": row.get("SEVERITY", "High" if state in TASK_FAILURE_STATES else "Medium"),
            "INCIDENT_PRIORITY": row.get("INCIDENT_PRIORITY", ""),
            "TASK_NAME": task_name,
            "ROOT_TASK_NAME": row.get("ROOT_TASK_NAME", ""),
            "STATE": state,
            "ERROR_SIGNATURE": signature,
            "ERROR_MESSAGE": detail[:500],
            "QUERY_ID": query_id,
            "LAST_SEEN": _first_task_value(row, "SCHEDULED_TIME", "LAST_FAILURE_AT", "COMPLETED_TIME"),
            "EST_TOTAL_CREDITS": safe_float(row.get("EST_TOTAL_CREDITS")),
            "NEXT_ACTION": row.get("NEXT_ACTION") or _task_action_for(signal or state)[0],
        })

    if exceptions is not None and not exceptions.empty:
        for _, row in _task_ops_priority_view(exceptions).head(100).iterrows():
            add_row(row, source="Task exceptions")

    if latest is not None and not latest.empty:
        latest_errors = latest[_task_failure_mask(latest)]
        for _, row in latest_errors.head(100).iterrows():
            add_row(row, source="Latest task run")

    board = pd.DataFrame(rows)
    if board.empty:
        return board
    priority_rank = board["INCIDENT_PRIORITY"].astype(str).str.extract(r"P(\d)", expand=False).fillna("9").astype(int)
    severity_rank = board["SEVERITY"].astype(str).str.upper().map({
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
    }).fillna(4)
    board["_PRIORITY_RANK"] = priority_rank
    board["_SEVERITY_RANK"] = severity_rank
    return board.sort_values(
        ["_PRIORITY_RANK", "_SEVERITY_RANK", "LAST_SEEN", "TASK_NAME"],
        ascending=[True, True, False, True],
    ).drop(columns=["_PRIORITY_RANK", "_SEVERITY_RANK"], errors="ignore").reset_index(drop=True)

def _build_task_reliability_slo_board(summary: dict, exceptions: pd.DataFrame, recovery_sla: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Condense task graph and recovery reliability into a DBA control board."""
    rows = [
        {
            "SLO": "Failed runs",
            "STATE": "Ready" if safe_int(summary.get("FAILED_RUNS")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('FAILED_RUNS')):,} failed run(s).",
            "NEXT_ACTION": "Triage failures before the next production handoff.",
        },
        {
            "SLO": "Suspended tasks",
            "STATE": "Ready" if safe_int(summary.get("SUSPENDED_TASKS")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('SUSPENDED_TASKS')):,} suspended task(s).",
            "NEXT_ACTION": "Resume or retire suspended tasks only after checking downstream impact.",
        },
        {
            "SLO": "Runtime drift",
            "STATE": "Ready" if safe_int(summary.get("LONG_RUNNING_TASKS")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('LONG_RUNNING_TASKS')):,} long-running task(s).",
            "NEXT_ACTION": "Compare the latest run to the historical baseline and isolate regressions.",
        },
        {
            "SLO": "Cost drift",
            "STATE": "Ready" if safe_int(summary.get("COST_DRIFT_TASKS")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('COST_DRIFT_TASKS')):,} cost-drift candidate(s).",
            "NEXT_ACTION": "Check warehouse size, release changes, and child-query spill before closing.",
        },
        {
            "SLO": "Open recovery",
            "STATE": "Ready" if safe_int(summary.get("OPEN_RECOVERIES")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('OPEN_RECOVERIES')):,} open recovery item(s).",
            "NEXT_ACTION": "Close recoveries with telemetry, status review, and a successful next run.",
        },
        {
            "SLO": "Recovery SLA",
            "STATE": "Ready" if safe_int(summary.get("RECOVERY_SLA_BREACHES")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('RECOVERY_SLA_BREACHES')):,} recovery SLA breach(es).",
            "NEXT_ACTION": "Escalate breaches that exceed the recovery target hours.",
        },
    ]
    if exceptions is not None and not exceptions.empty:
        p1 = int(exceptions.get("INCIDENT_PRIORITY", pd.Series(dtype=str)).astype(str).str.startswith("P1").sum())
        blocked = int(exceptions.get("RECOVERY_READINESS", pd.Series(dtype=str)).astype(str).str.startswith("Blocked").sum())
    else:
        p1 = 0
        blocked = 0
    if recovery_sla is not None and not recovery_sla.empty:
        recovery_breaches = int(recovery_sla.get("RECOVERY_STATE", pd.Series(dtype=str)).astype(str).str.contains("Breach|Open Failure", case=False, na=False).sum())
    else:
        recovery_breaches = 0
    rows.append({
        "SLO": "Critical path risk",
        "STATE": "Ready" if p1 == 0 and blocked == 0 and recovery_breaches == 0 else "Review",
        "EVIDENCE": f"P1 incidents={p1:,}; blocked recoveries={blocked:,}; recovery breaches={recovery_breaches:,}.",
        "NEXT_ACTION": "Use the recovery summary before treating the task graph as healthy.",
    })
    board = pd.DataFrame(rows)
    board["_RANK"] = board["STATE"].map({"Review": 0, "Ready": 1}).fillna(9)
    score = max(0, min(100, 100 - int((board["STATE"] == "Review").sum()) * 12))
    return {
        "score": score,
        "ready": int((board["STATE"] == "Ready").sum()),
        "review": int((board["STATE"] == "Review").sum()),
    }, board.sort_values(["_RANK", "SLO"]).drop(columns=["_RANK"], errors="ignore")

__all__ = ['_procedure_from_definition', '_extract_object_candidates', '_task_root_name', '_df_col', '_blankish_series', '_task_failure_mask', '_task_success_mask', '_parse_task_predecessors', '_annotate_task_graph_impact', '_task_full_name', '_is_prod_task', '_confirmation_phrase', '_collect_graph_tasks', '_build_task_graph_dot', '_task_ops_score', '_task_time_series', '_normalize_task_history_for_recovery', '_recovery_state_rank', '_task_recovery_priority', '_task_owner_approval_state', '_task_owner_approval_status', '_build_task_recovery_sla_frame', '_task_recovery_sla_summary', '_build_task_critical_path_snapshot', '_normalize_task_critical_path_mart', '_task_ops_priority_view', '_task_recovery_command_board', '_task_ops_workflow_for', '_task_action_for', '_failure_signature', '_failure_diagnosis', '_estimate_query_credits', '_normalize_query_details', '_prepare_inventory_for_failures', '_failure_incident_priority', '_failure_recovery_readiness', '_verification_after_failure', '_task_exception_incident_priority', '_task_exception_recovery_readiness', '_build_failure_console_frames', '_build_failure_runbook_markdown', '_task_owner', '_task_environment', '_task_metric', '_build_task_ops_markdown', '_build_task_ops_frames', '_task_task_status_handoff_state', '_state_distribution_text', '_latest_task_timestamp', '_first_task_value', '_build_task_status_job_status_board', '_build_task_status_error_board', '_build_task_reliability_slo_board']
