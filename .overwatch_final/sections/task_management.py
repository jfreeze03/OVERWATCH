# sections/task_management.py - Task history, ETL audit framework, execute task
import re
import time

import streamlit as st
import pandas as pd
from utils.workflows import render_priority_dataframe, render_workflow_selector
from utils import (
    build_task_history_sql,
    download_csv,
    format_snowflake_error,
    get_active_company,
    get_active_environment,
    get_session,
    admin_actions_enabled,
    admin_button_disabled,
    log_admin_action,
    CREDIT_RATES,
    filter_existing_columns,
    load_task_inventory,
    make_action_id,
    build_mart_task_critical_path_sql,
    build_mart_task_inventory_sql,
    build_mart_task_history_sql,
    build_mart_query_detail_recent_sql,
    run_query,
    run_query_or_raise,
    resolve_owner_context,
    safe_identifier,
    safe_float,
    safe_int,
    render_ranked_bar_chart,
    sql_literal,
    upsert_actions,
)
from config import ALERT_DB, ALERT_SCHEMA, ETL_AUDIT_DB, ETL_AUDIT_SCHEMA, ETL_AUDIT_TABLE


TASK_CONTROL_VIEWS = (
    "Task History",
    "Failure Console",
    "SLA & Cost Drift",
    "ETL Audit",
    "Control Center",
    "Execute Task",
)

TASK_CONTROL_DETAILS = {
    "Task History": "Run history, active task count, and raw task inventory.",
    "Failure Console": "Failure patterns, query links, runbooks, and action queue handoff.",
    "SLA & Cost Drift": "Release-sensitive task duration and estimated credit regression review.",
    "ETL Audit": "Custom ETL audit table setup and recent pipeline runs.",
    "Control Center": "Guarded suspend, resume, retry, execute, and cancel workflows.",
    "Execute Task": "Focused manual task execution with pre-flight checks.",
}

TASK_FAILURE_STATES = {"FAILED", "FAILED_WITH_ERROR"}
TASK_SUCCESS_STATES = {"SUCCEEDED", "SUCCESS", "COMPLETED"}
TASK_RECOVERY_SLA_HOURS = 4


def _queue_task_findings(session, df: pd.DataFrame, source: str) -> None:
    if df is None or df.empty:
        st.info("No task findings to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in df.head(200).iterrows():
        active_env = get_active_environment()
        action_env = str(row.get("ENVIRONMENT") or (active_env if active_env != "ALL" else "") or "")
        name = str(row.get("NAME") or row.get("PIPELINE_NAME") or "Unknown task")
        err = str(row.get("ERROR_MESSAGE") or "")[:1000]
        state = str(row.get("STATE") or row.get("STATUS") or "FAILED")
        finding = f"{name} finished with {state}"
        if err:
            finding += f": {err[:250]}"
        owner_context = resolve_owner_context(
            row,
            entity=name,
            entity_type="Task",
            owner="Data Engineering",
            category="Task & Procedure Reliability",
            alert_type="Task Failure",
        )
        actions.append({
            "Action ID": make_action_id("Task Reliability", name, finding),
            "Source": source,
            "Severity": "High",
            "Category": "Reliability",
            "Entity Type": "Task/Pipeline",
            "Entity": name,
            "Owner": owner_context.get("OWNER", "Data Engineering"),
            "Owner Email": owner_context.get("OWNER_EMAIL", ""),
            "Oncall Primary": owner_context.get("ONCALL_PRIMARY", ""),
            "Oncall Secondary": owner_context.get("ONCALL_SECONDARY", ""),
            "Approval Group": owner_context.get("APPROVAL_GROUP", ""),
            "Escalation Target": owner_context.get("ESCALATION_TARGET", ""),
            "Owner Source": owner_context.get("OWNER_SOURCE", ""),
            "Owner Evidence": owner_context.get("OWNER_EVIDENCE", ""),
            "Approver": owner_context.get("APPROVAL_GROUP", ""),
            "Finding": finding,
            "Action": "Review error message, fix upstream dependency or SQL failure, then retry the task/pipeline.",
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": f"-- Review task or pipeline: {name}\n-- EXECUTE TASK <database>.<schema>.{safe_identifier(name)};",
            "Proof Query": "TASK_HISTORY or ETL audit failure row.",
            "Company": company,
            "Environment": action_env,
            "Verification Status": "Pending",
            "Verification Query": "TASK_HISTORY or ETL audit failure row.",
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} task reliability findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _qualified_name(*parts: str) -> str:
    return ".".join(f'"{str(part).replace(chr(34), chr(34) + chr(34))}"' for part in parts)


def _typed_confirmation(prompt: str, expected: str, key: str) -> bool:
    entered = st.text_input(prompt, key=key, placeholder=expected)
    return entered.strip() == expected


def _show_tasks(session, force_refresh: bool = False) -> pd.DataFrame:
    return load_task_inventory(session, get_active_company(), force_refresh=force_refresh)


ETL_AUDIT_FQN = (
    f"{safe_identifier(ETL_AUDIT_DB)}."
    f"{safe_identifier(ETL_AUDIT_SCHEMA)}."
    f"{safe_identifier(ETL_AUDIT_TABLE)}"
)

ADMIN_AUDIT_FQN = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier('OVERWATCH_ADMIN_ACTION_AUDIT')}"
)
_EXECUTION_CONTEXT_CACHE_TTL_SECONDS = 300


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
    if not text or text.upper() in {"[]", "NONE", "NULL"}:
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


def _admin_sql_for_task(row: pd.Series, action: str) -> list[str]:
    full_name = _task_full_name(row)
    action = str(action or "").upper()
    if action == "SUSPEND":
        return [f"ALTER TASK {full_name} SUSPEND"]
    if action == "RESUME":
        return [f"ALTER TASK {full_name} RESUME"]
    if action in {"EXECUTE", "RETRY"}:
        return [f"EXECUTE TASK {full_name}"]
    raise ValueError(f"Unsupported task action: {action}")


def _admin_sql_for_graph(graph_tasks: pd.DataFrame, root_name: str, action: str) -> list[str]:
    if graph_tasks is None or graph_tasks.empty:
        return []
    action = str(action or "").upper()
    root_rows = graph_tasks[graph_tasks["NAME"].astype(str) == str(root_name)] if "NAME" in graph_tasks.columns else pd.DataFrame()
    if root_rows.empty:
        return []
    root_row = root_rows.iloc[0]
    if action == "SUSPEND":
        # Suspending the root stops future graph scheduling without forcing every branch offline.
        return _admin_sql_for_task(root_row, "SUSPEND")
    if action == "EXECUTE" or action == "RETRY":
        return _admin_sql_for_task(root_row, "EXECUTE")
    if action == "RESUME":
        child_rows = graph_tasks[graph_tasks["NAME"].astype(str) != str(root_name)].copy()
        child_sql = [_admin_sql_for_task(row, "RESUME")[0] for _, row in child_rows.iterrows()]
        return child_sql + _admin_sql_for_task(root_row, "RESUME")
    raise ValueError(f"Unsupported graph action: {action}")


def _run_admin_sql_list(
    session,
    sql_statements: list[str],
    action_type: str,
    object_name: str,
    confirmation_text: str = "",
    control_context: str = "",
) -> tuple[int, list[str]]:
    errors: list[str] = []
    completed = 0
    for sql_text in sql_statements:
        try:
            session.sql(sql_text).collect()
            _log_admin_action(
                session,
                action_type,
                object_name,
                sql_text,
                "SUCCESS",
                "Statement completed.",
                confirmation_text=confirmation_text,
                control_context=control_context,
            )
            completed += 1
        except Exception as e:
            message = format_snowflake_error(e)
            _log_admin_action(
                session,
                action_type,
                object_name,
                sql_text,
                "FAILED",
                message,
                confirmation_text=confirmation_text,
                control_context=control_context,
            )
            errors.append(f"{sql_text}: {message}")
    return completed, errors


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


def _task_ops_rating(score: int) -> str:
    if score >= 90:
        return "Operational"
    if score >= 78:
        return "Watch"
    if score >= 65:
        return "Degraded"
    return "Incident Risk"


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
        return "Root-cause owner approval required"
    if "LATE" in recovery_state or "SLA" in signal:
        return "DBA lead verifies recovery evidence"
    if "SUSPENDED" in signal:
        return "Owner approval required before resume"
    if "COST" in signal or "REGRESSION" in signal:
        return "DBA release owner accepts or remediates baseline"
    return "DBA review before close"


def _task_owner_approval_status(row: pd.Series) -> str:
    state = str(row.get("OWNER_APPROVAL_STATE") or "").upper()
    if "NOT REQUIRED" in state:
        return "Not Required"
    if "APPROVAL REQUIRED" in state or "OWNER APPROVAL" in state or "ROOT-CAUSE OWNER" in state:
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
            else "Attach TASK_HISTORY evidence proving the successful recovery run and elapsed recovery time."
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
                    "Blocked - verify successful recovery run first"
                    if recovery_state == "Open Failure"
                    else "Blocked - attach late recovery evidence before close"
                ),
                "OWNER_APPROVAL_STATE": row.get("OWNER_APPROVAL_STATE", ""),
                "ONCALL_PRIMARY": row.get("ONCALL_PRIMARY", ""),
                "APPROVAL_GROUP": row.get("APPROVAL_GROUP", ""),
                "NEXT_WORKFLOW": "Failure Console",
                "NEXT_ACTION": "Attach owner-approved recovery evidence and verify the next successful task run before closure.",
                "VERIFY_AFTER_FIX": row.get("VERIFY_AFTER_FIX", "Attach TASK_HISTORY recovery proof before closure."),
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
    return "Task History"


def _task_action_for(signal: str) -> tuple[str, str]:
    signal = str(signal or "").upper()
    if "OPEN RECOVERY" in signal:
        return (
            "Keep the incident open until a successful recovery run is visible and owner approval is attached.",
            "-- Verify with TASK_HISTORY before retrying or closing the incident.",
        )
    if "RECOVERY" in signal:
        return (
            "Attach the recovery evidence, compare elapsed recovery time to SLA, and decide whether the task graph needs tuning.",
            "-- Review TASK_HISTORY failure and succeeding run timestamps.",
        )
    if "FAILED" in signal:
        return (
            "Review task error, linked query/procedure, upstream dependency, and retry the root task after correction.",
            "-- Review TASK_HISTORY failure and QUERY_HISTORY by QUERY_ID before retry.",
        )
    if "SUSPENDED" in signal:
        return (
            "Confirm suspension was intentional; resume only after owner approval and dependency check.",
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
        "Review graph dependency and procedure ownership before operational action.",
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
            "PROBABLE_CAUSE": "The task owner role or procedure execution role lacks required privileges.",
            "RECOMMENDED_ACTION": "Check task owner, procedure owner, EXECUTE privileges, warehouse USAGE, and object grants before retry.",
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
            "PROBABLE_CAUSE": "The generated SQL or stored procedure body is invalid in the current environment.",
            "RECOMMENDED_ACTION": "Open the linked query text/procedure definition, validate object names and syntax, then redeploy the procedure.",
        }
    if any(token in combined for token in ["WAREHOUSE", "STATEMENT_TIMEOUT", "TIMEOUT", "MEMORY", "SPILL", "RESOURCE"]):
        return {
            "CATEGORY": "Warehouse / Runtime Capacity",
            "PROBABLE_CAUSE": "The task may be blocked by warehouse state, timeout, memory pressure, or capacity limits.",
            "RECOMMENDED_ACTION": "Check Warehouse Health for queue/spill pressure, resume or resize only after confirming workload demand.",
        }
    if any(token in combined for token in ["LOCK", "TRANSACTION", "DEADLOCK", "BLOCKED"]):
        return {
            "CATEGORY": "Concurrency / Locking",
            "PROBABLE_CAUSE": "The task was blocked by concurrent DML/DDL or transaction contention.",
            "RECOMMENDED_ACTION": "Review overlapping task windows, query blockers, and transaction timing before retrying.",
        }
    return {
        "CATEGORY": "Unclassified Failure",
        "PROBABLE_CAUSE": "The error pattern does not match a known rule yet.",
        "RECOMMENDED_ACTION": "Review query profile, procedure code, task history, and recent Change/Drift events; add a new diagnosis rule if repeated.",
    }


def _query_detail_sql(session, query_ids: list[str]) -> str:
    clean_ids = [str(qid) for qid in query_ids if str(qid or "").strip()]
    if not clean_ids:
        return ""
    cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "QUERY_ID", "USER_NAME", "ROLE_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
            "DATABASE_NAME", "SCHEMA_NAME", "QUERY_TYPE", "EXECUTION_STATUS",
            "START_TIME", "END_TIME", "TOTAL_ELAPSED_TIME", "ERROR_CODE",
            "ERROR_MESSAGE", "QUERY_TEXT", "CREDITS_USED_CLOUD_SERVICES",
            "BYTES_SCANNED", "ROWS_PRODUCED",
        ],
    ))

    def expr(col: str, fallback: str) -> str:
        return col if col in cols else fallback

    id_list = ", ".join(sql_literal(qid, 200) for qid in clean_ids[:500])
    return f"""
        SELECT
            {expr("QUERY_ID", "NULL::VARCHAR")} AS query_id,
            {expr("USER_NAME", "NULL::VARCHAR")} AS user_name,
            {expr("ROLE_NAME", "NULL::VARCHAR")} AS role_name,
            {expr("WAREHOUSE_NAME", "NULL::VARCHAR")} AS warehouse_name,
            {expr("WAREHOUSE_SIZE", "NULL::VARCHAR")} AS warehouse_size,
            {expr("DATABASE_NAME", "NULL::VARCHAR")} AS database_name,
            {expr("SCHEMA_NAME", "NULL::VARCHAR")} AS schema_name,
            {expr("QUERY_TYPE", "NULL::VARCHAR")} AS query_type,
            {expr("EXECUTION_STATUS", "NULL::VARCHAR")} AS execution_status,
            {expr("START_TIME", "NULL::TIMESTAMP_NTZ")} AS start_time,
            {expr("END_TIME", "NULL::TIMESTAMP_NTZ")} AS end_time,
            {expr("TOTAL_ELAPSED_TIME", "0::NUMBER")} / 1000 AS query_elapsed_sec,
            {expr("CREDITS_USED_CLOUD_SERVICES", "0::FLOAT")} AS cloud_credits,
            {expr("BYTES_SCANNED", "0::NUMBER")} AS bytes_scanned,
            {expr("ROWS_PRODUCED", "0::NUMBER")} AS rows_produced,
            {expr("ERROR_CODE", "NULL::VARCHAR")} AS query_error_code,
            {expr("ERROR_MESSAGE", "NULL::VARCHAR")} AS query_error_message,
            SUBSTR({expr("QUERY_TEXT", "''")}, 1, 4000) AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE query_id IN ({id_list})
    """


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
    return "Ready after DBA owner approval"


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
        return "Blocked - verify successful recovery run first"
    if "RECOVERY" in signal:
        return "Blocked - attach late recovery evidence before close"
    if "FAILED" in signal:
        return "Blocked - fix failure root cause first"
    if "SUSPENDED" in signal:
        return "Blocked - owner approval before resume"
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
                f"- Recovery readiness: {row.get('RECOVERY_READINESS', '')}",
                f"- Recovery SLA state: {row.get('RECOVERY_STATE', '')}",
                f"- Owner approval: {row.get('OWNER_APPROVAL_STATE', '')}",
                f"- Verify after fix: {row.get('VERIFY_AFTER_FIX', '')}",
                f"- Retry SQL after fix: `{row.get('RETRY_SQL', '')}`",
                "",
            ])
    lines.extend([
        "## Evidence Limits",
        "- TASK_HISTORY and QUERY_HISTORY are ACCOUNT_USAGE-backed and can lag.",
        "- Procedure linkage is inferred from task definitions containing CALL statements.",
        "- Retry SQL is generated for review; DBAs must confirm the root cause is fixed before execution.",
    ])
    return "\n".join(lines)


def _queue_failure_findings(session, failures: pd.DataFrame) -> int:
    if failures is None or failures.empty:
        return 0
    company = get_active_company()
    actions = [
        _build_task_reliability_action(row, company, "Task Management - Failure Console")
        for _, row in failures.head(100).iterrows()
    ]
    return upsert_actions(session, actions)


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


def _task_reliability_verification_sql(row: pd.Series, lookback_days: int = 7) -> str:
    task_name = str(row.get("TASK_NAME") or row.get("NAME") or "").strip()
    task_fqn = str(row.get("TASK_FQN") or "").strip()
    name_filter = ""
    if task_name:
        name_filter = f"AND name = {sql_literal(task_name, 500)}"
    return f"""-- Task reliability proof and post-fix verification
-- Task FQN: {task_fqn or task_name or 'UNKNOWN'}
SELECT name,
       database_name,
       schema_name,
       state,
       scheduled_time,
       completed_time,
       query_id,
       error_code,
       error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE scheduled_time >= DATEADD('day', -{max(1, int(lookback_days or 7))}, CURRENT_TIMESTAMP())
  {name_filter}
ORDER BY scheduled_time DESC
LIMIT 50;

-- Verification rule: latest run should be SUCCEEDED and runtime/credits should return inside the selected SLA baseline.
"""


def _task_reliability_proof_sql(row: pd.Series, lookback_days: int = 7) -> str:
    """Return richer human proof text while keeping runnable verification separate."""
    verification_sql = _task_reliability_verification_sql(row, lookback_days).strip()
    query_id = str(row.get("QUERY_ID") or "").strip()
    if not query_id:
        return verification_sql
    return f"""{verification_sql}

-- Linked QUERY_HISTORY evidence for root-cause review:
SELECT query_id,
       execution_status,
       start_time,
       end_time,
       total_elapsed_time / 1000 AS elapsed_sec,
       error_code,
       error_message,
       SUBSTR(query_text, 1, 4000) AS query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_id = {sql_literal(query_id, 200)};
"""


def _task_reliability_generated_sql(row: pd.Series) -> str:
    retry_sql = str(row.get("RETRY_SQL") or "").strip()
    task_fqn = str(row.get("TASK_FQN") or row.get("TASK_NAME") or "UNKNOWN_TASK")
    incident_priority = str(row.get("INCIDENT_PRIORITY") or "").strip()
    recovery_readiness = str(row.get("RECOVERY_READINESS") or "").strip()
    owner_approval_state = str(row.get("OWNER_APPROVAL_STATE") or "").strip()
    if retry_sql and not retry_sql.startswith("--"):
        retry_line = retry_sql
    else:
        retry_line = f"-- EXECUTE TASK {task_fqn};"
    return (
        "-- Reviewed recovery plan. Do not execute until root cause is fixed.\n"
        f"-- Task: {task_fqn}\n"
        f"-- Priority: {incident_priority or 'Unranked'}\n"
        f"-- Recovery readiness: {recovery_readiness or 'DBA review required'}\n"
        f"-- Owner approval: {owner_approval_state or 'Required before close'}\n"
        f"-- Graph role: {row.get('GRAPH_ROLE', '')}; downstream tasks: {safe_int(row.get('DOWNSTREAM_TASK_COUNT'))}\n"
        f"-- Linked procedure: {row.get('PROCEDURE_NAME', '')}\n"
        f"-- Impact objects: {row.get('IMPACT_OBJECTS', '')}\n"
        f"{retry_line}\n"
        "-- After retry, run the verification query and attach evidence to the action queue."
    )


def _task_metric(row: pd.Series, *columns: str):
    for column in columns:
        if column in row and row.get(column) not in (None, ""):
            return safe_float(row.get(column))
    return None


def _build_task_reliability_action(row: pd.Series, company: str, source: str) -> dict:
    signal = str(row.get("SIGNAL") or row.get("FAILURE_CATEGORY") or row.get("BREACH_REASON") or "Task Reliability")
    task = str(row.get("TASK_FQN") or row.get("TASK_NAME") or row.get("NAME") or "Unknown task")
    category = str(row.get("FAILURE_CATEGORY") or signal)
    detail = str(row.get("DETAIL") or row.get("ERROR_SIGNATURE") or row.get("ERROR_MESSAGE") or "")[:700]
    action_text, _ = _task_action_for(signal)
    if row.get("RECOMMENDED_ACTION"):
        action_text = str(row.get("RECOMMENDED_ACTION"))
    if "verify" not in action_text.lower():
        action_text += " Verify the next successful run and attach TASK_HISTORY evidence before closing."
    severity = str(row.get("SEVERITY") or ("High" if category != "Unclassified Failure" else "Medium"))
    incident_priority = str(row.get("INCIDENT_PRIORITY") or "").strip()
    recovery_readiness = str(row.get("RECOVERY_READINESS") or "").strip()
    owner_approval_state = str(row.get("OWNER_APPROVAL_STATE") or "").strip()
    recovery_state = str(row.get("RECOVERY_STATE") or "").strip()
    recovery_evidence = str(row.get("VERIFY_AFTER_FIX") or "").strip()
    owner_context = resolve_owner_context(
        row,
        entity=task,
        entity_type="Task",
        owner=_task_owner(row),
        category="Task & Procedure Reliability",
        alert_type=signal,
    )
    if recovery_readiness and recovery_readiness.lower() not in action_text.lower():
        action_text += f" Recovery readiness: {recovery_readiness}."
    if owner_approval_state and owner_approval_state.lower() not in action_text.lower():
        action_text += f" Owner approval: {owner_approval_state}."
    finding_prefix = f"{incident_priority}: " if incident_priority else ""
    finding = f"{finding_prefix}{signal}: {task}. {detail}".strip()
    if recovery_state:
        finding = f"{finding} Recovery SLA state: {recovery_state}."
    verification_query = _task_reliability_verification_sql(row)[:8000]
    proof_query = _task_reliability_proof_sql(row)[:8000]
    baseline_value = _task_metric(row, "AVG_DURATION_SEC", "AVG_EXECUTION_SECONDS", "BASELINE_SECONDS")
    current_value = _task_metric(row, "DURATION_SEC", "ELAPSED_SEC", "LATEST_DURATION_SEC", "EXECUTION_SECONDS")
    measured_delta = (
        round(current_value - baseline_value, 4)
        if current_value is not None and baseline_value is not None
        else None
    )
    return {
        "Action ID": make_action_id("Task Reliability", task, finding),
        "Source": source,
        "Severity": severity,
        "Category": "Task & Procedure Reliability",
        "Entity Type": "Task/Procedure",
        "Entity": task,
        "Owner": owner_context.get("OWNER") or _task_owner(row),
        "Owner Email": owner_context.get("OWNER_EMAIL", ""),
        "Oncall Primary": owner_context.get("ONCALL_PRIMARY", ""),
        "Oncall Secondary": owner_context.get("ONCALL_SECONDARY", ""),
        "Approval Group": owner_context.get("APPROVAL_GROUP", ""),
        "Escalation Target": owner_context.get("ESCALATION_TARGET", ""),
        "Owner Source": owner_context.get("OWNER_SOURCE", ""),
        "Owner Evidence": owner_context.get("OWNER_EVIDENCE", ""),
        "Approver": owner_context.get("APPROVAL_GROUP") or row.get("APPROVER") or owner_context.get("ESCALATION_TARGET", ""),
        "Finding": finding,
        "Action": action_text,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": _task_reliability_generated_sql(row)[:8000],
        "Proof Query": proof_query,
        "Company": company,
        "Environment": _task_environment(row),
        "Verification Status": "Pending",
        "Verification Query": verification_query,
        "Baseline Value": baseline_value,
        "Current Value": current_value,
        "Measured Delta": measured_delta,
        "Owner Approval Status": _task_owner_approval_status(row),
        "Owner Approval Note": owner_approval_state,
        "Recovery SLA State": recovery_state,
        "Recovery SLA Hours": _task_metric(row, "RECOVERY_HOURS", "RECOVERY_SLA_HOURS"),
        "Recovery SLA Target Hours": _task_metric(row, "RECOVERY_SLA_TARGET_HOURS"),
        "Recovery Evidence": recovery_evidence,
        "Recovery Audit State": "Audit Required" if recovery_state else "",
    }


def _build_task_ops_markdown(
    company: str,
    days: int,
    score: int,
    summary: dict,
    exceptions: pd.DataFrame,
) -> str:
    lines = [
        f"# OVERWATCH Task Graph Operations Brief - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Operations score: {score} ({_task_ops_rating(score)})",
        f"- Task graphs/tasks: {safe_int(summary.get('TOTAL_TASKS')):,}",
        f"- Task runs: {safe_int(summary.get('TOTAL_RUNS')):,}",
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
            "This is the Informatica Monitor replacement view: use it to find broken task graphs, "
            "failed sessions, suspended jobs, slow runs, linked procedures, and retry candidates. "
            "It should be the first stop before manually executing or resuming task graphs."
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
                f"SLA state: {row.get('RECOVERY_STATE', '')} | Owner approval: {row.get('OWNER_APPROVAL_STATE', '')} | "
                f"Downstream tasks: {safe_int(row.get('DOWNSTREAM_TASK_COUNT')):,} | "
                f"Impact hints: {row.get('IMPACT_OBJECTS', '')}"
            )
    lines.extend([
        "",
        "## Evidence Limits",
        "- TASK_HISTORY columns vary by Snowflake account and role; missing columns are feature-gated.",
        "- Procedure linkage is inferred from task definition CALL statements when available.",
        "- Admin actions require the global Admin actions toggle and the Snowflake task privileges.",
    ])
    return "\n".join(lines)


def _current_execution_context(session) -> dict:
    app_user = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
    role = str(st.session_state.get("_overwatch_current_role", "") or "")
    cache_key = "_task_management_execution_context_cache"
    cached = st.session_state.get(cache_key, {})
    if cached:
        age_sec = time.time() - float(cached.get("loaded_at", 0) or 0)
        data = cached.get("data")
        if age_sec <= _EXECUTION_CONTEXT_CACHE_TTL_SECONDS and isinstance(data, dict):
            return {
                "snowflake_user": app_user,
                "snowflake_role": role,
                "snowflake_warehouse": str(data.get("snowflake_warehouse", "") or ""),
            }
    warehouse = ""
    try:
        row = session.sql("SELECT CURRENT_WAREHOUSE() AS current_warehouse").collect()[0]
        warehouse = str(row["CURRENT_WAREHOUSE"] or "")
    except Exception:
        warehouse = ""
    data = {
        "snowflake_user": app_user,
        "snowflake_role": role,
        "snowflake_warehouse": warehouse,
    }
    st.session_state[cache_key] = {"loaded_at": time.time(), "data": data}
    return data


def build_admin_preflight_sql(row: pd.Series) -> str:
    full_name = _task_full_name(row)
    database_name = safe_identifier(row.get("DATABASE_NAME", ""))
    task_name = str(row.get("NAME") or "<task_name>")
    return f"""-- Read-only pre-flight before live task action
-- CURRENT_USER() can be blocked inside Snowflake-hosted Streamlit.
SELECT CURRENT_ROLE() AS current_role,
       CURRENT_WAREHOUSE() AS current_warehouse;

SHOW GRANTS ON TASK {full_name};

SELECT *
FROM TABLE({database_name}.INFORMATION_SCHEMA.TASK_HISTORY(
    TASK_NAME => {sql_literal(task_name, 512)},
    RESULT_LIMIT => 20
))
ORDER BY SCHEDULED_TIME DESC;

-- Confirm the active role has OPERATE or OWNERSHIP on the task before ALTER/EXECUTE/CANCEL.
-- Confirm the selected company/environment is correct before running generated admin SQL.
"""


def _log_admin_action(
    session,
    action_type: str,
    object_name: str,
    sql_text: str,
    status: str,
    message: str,
    confirmation_text: str = "",
    control_context: str = "",
) -> None:
    log_admin_action(
        session,
        action_type=action_type,
        target_object=object_name,
        sql_text=sql_text,
        result_status=status,
        result_message=message,
        confirmation_text=confirmation_text,
        control_context=control_context,
        company=get_active_company(),
        environment=get_active_environment(),
    )


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
    summary = {
        "TOTAL_TASKS": len(inventory),
        "TOTAL_RUNS": len(history),
        "FAILED_RUNS": int(history_state.isin(TASK_FAILURE_STATES).sum()) if not history_state.empty else 0,
        "SUSPENDED_TASKS": int((inventory_state == "SUSPENDED").sum()),
        "LONG_RUNNING_TASKS": int((exceptions.get("SIGNAL", pd.Series(dtype=str)) == "Long Running / SLA Risk").sum()) if not exceptions.empty else 0,
        "COST_DRIFT_TASKS": int((exceptions.get("SIGNAL", pd.Series(dtype=str)) == "Cost Drift / Release Regression").sum()) if not exceptions.empty else 0,
        "PROCEDURE_LINKS": int((inventory.get("PROCEDURE_NAME", pd.Series(dtype=str)).astype(str).str.len() > 0).sum()) if not inventory.empty else 0,
        "P1_INCIDENTS": int(exceptions.get("INCIDENT_PRIORITY", pd.Series(dtype=str)).astype(str).str.startswith("P1").sum()) if not exceptions.empty else 0,
        "BLOCKED_RECOVERIES": int(exceptions.get("RECOVERY_READINESS", pd.Series(dtype=str)).astype(str).str.startswith("Blocked").sum()) if not exceptions.empty else 0,
        **_task_recovery_sla_summary(recovery),
    }
    return summary, exceptions, latest


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
            "NEXT_ACTION": "Close recoveries with proof, owner approval, and a successful next run.",
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
        "NEXT_ACTION": "Use the recovery command board before treating the task graph as healthy.",
    })
    board = pd.DataFrame(rows)
    board["_RANK"] = board["STATE"].map({"Review": 0, "Ready": 1}).fillna(9)
    score = max(0, min(100, 100 - int((board["STATE"] == "Review").sum()) * 12))
    return {
        "score": score,
        "ready": int((board["STATE"] == "Ready").sum()),
        "review": int((board["STATE"] == "Review").sum()),
    }, board.sort_values(["_RANK", "SLO"]).drop(columns=["_RANK"], errors="ignore")


def _queue_task_ops_findings(session, exceptions: pd.DataFrame) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = get_active_company()
    actions = [
        _build_task_reliability_action(row, company, "Task Management - Operations Brief")
        for _, row in exceptions.head(100).iterrows()
    ]
    return upsert_actions(session, actions)


def _load_task_ops_scope(
    session,
    days: int,
    ttl_prefix: str,
    force_inventory_refresh: bool = False,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    company = get_active_company()
    database_contains = str(st.session_state.get("global_database", "") or "").strip()
    inventory_source = "Live: SHOW TASKS IN ACCOUNT"
    history_source = "Live: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY"
    query_detail_source = "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
    critical_path_source = "Computed: task inventory + task history"
    try:
        inventory = run_query(
            build_mart_task_inventory_sql(company=company, database_contains=database_contains),
            ttl_key=f"{ttl_prefix}_inventory_mart_{company}",
            tier="metadata",
            section="Task Management",
        )
        if inventory.empty:
            inventory = _show_tasks(session, force_refresh=force_inventory_refresh)
        else:
            inventory_source = "OVERWATCH mart: DIM_TASK_SNAPSHOT"
    except Exception as e:
        try:
            inventory = _show_tasks(session, force_refresh=force_inventory_refresh)
        except Exception:
            st.info(f"Task inventory unavailable in this role/context: {format_snowflake_error(e)}")
            inventory = pd.DataFrame()
    try:
        history = run_query(
            build_mart_task_history_sql(
                days,
                company=company,
                database_contains=database_contains,
                limit=1000,
            ),
            ttl_key=f"{ttl_prefix}_history_mart_{company}_{days}",
            tier="historical",
            section="Task Management",
        )
        if history.empty:
            history = run_query_or_raise(build_task_history_sql(
                session,
                f"scheduled_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())",
                limit=1000,
                company=company,
            ))
        else:
            history_source = "OVERWATCH mart: FACT_TASK_RUN"
    except Exception as e:
        st.info(f"Task history unavailable in this role/context: {format_snowflake_error(e)}")
        history = pd.DataFrame()
    query_details = pd.DataFrame()
    if not history.empty and "QUERY_ID" in history.columns:
        qids = history["QUERY_ID"].dropna().astype(str).tolist()
        try:
            query_sql = build_mart_query_detail_recent_sql(qids)
            if query_sql:
                query_details = run_query(
                    query_sql,
                    ttl_key=f"{ttl_prefix}_query_detail_mart_{company}_{days}_{len(qids)}",
                    tier="standard",
                )
            if query_details.empty:
                query_sql = _query_detail_sql(session, qids)
                if query_sql:
                    query_details = run_query(
                        query_sql,
                        ttl_key=f"{ttl_prefix}_query_detail_live_{company}_{days}_{len(qids)}",
                        tier="standard",
                    )
            else:
                query_detail_source = "OVERWATCH mart: FACT_QUERY_DETAIL_RECENT"
        except Exception as e:
            st.info(f"Linked query cost/detail unavailable: {format_snowflake_error(e)}")
    summary, exceptions, latest = _build_task_ops_frames(inventory, history, query_details)
    try:
        critical_paths = run_query(
            build_mart_task_critical_path_sql(
                days,
                company=company,
                database_contains=database_contains,
                limit=200,
            ),
            ttl_key=f"{ttl_prefix}_critical_path_mart_{company}_{days}",
            tier="historical",
            section="Task Management",
        )
        critical_paths = _normalize_task_critical_path_mart(critical_paths)
        if critical_paths.empty:
            critical_paths = _build_task_critical_path_snapshot(inventory, history)
        else:
            critical_path_source = "OVERWATCH mart: FACT_TASK_CRITICAL_PATH"
    except Exception:
        critical_paths = _build_task_critical_path_snapshot(inventory, history)
    recovery_sla = _build_task_recovery_sla_frame(history, inventory)
    st.session_state[f"{ttl_prefix}_sources"] = {
        "inventory": inventory_source,
        "history": history_source,
        "query_detail": query_detail_source if not query_details.empty else "Not loaded",
        "critical_path": critical_path_source,
    }
    return summary, exceptions, latest, inventory, critical_paths, recovery_sla, not query_details.empty


def _render_task_ops_brief(session) -> None:
    company = get_active_company()
    st.subheader("Task Graph Operations Cockpit")
    st.caption(
        "First-stop DBA view for Snowflake task graphs: health, failures, suspended tasks, SLA drift, "
        "procedure links, impact hints, and the next operational workflow."
    )
    with st.container():
        days = st.slider("Task graph lookback (days)", 1, 30, 7, key="task_ops_days")
        if st.button("Load Task Graph Operations", key="task_ops_load"):
            summary, exceptions, latest, inventory, critical_paths, recovery_sla, details_loaded = _load_task_ops_scope(
                session, days, "task_ops", force_inventory_refresh=True
            )
            st.session_state["task_ops_summary"] = summary
            st.session_state["task_ops_exceptions"] = exceptions
            st.session_state["task_ops_latest"] = latest
            st.session_state["task_ops_inventory"] = inventory
            st.session_state["task_ops_critical_paths"] = critical_paths
            st.session_state["task_ops_recovery_sla"] = recovery_sla
            st.session_state["task_ops_query_details_loaded"] = details_loaded

        summary = st.session_state.get("task_ops_summary")
        if not summary:
            return
        exceptions = st.session_state.get("task_ops_exceptions", pd.DataFrame())
        latest = st.session_state.get("task_ops_latest", pd.DataFrame())
        inventory = st.session_state.get("task_ops_inventory", pd.DataFrame())
        critical_paths = st.session_state.get("task_ops_critical_paths", pd.DataFrame())
        recovery_sla = st.session_state.get("task_ops_recovery_sla", pd.DataFrame())
        score = _task_ops_score(
            failed_runs=safe_int(summary.get("FAILED_RUNS")),
            suspended_tasks=safe_int(summary.get("SUSPENDED_TASKS")),
            long_running_tasks=safe_int(summary.get("LONG_RUNNING_TASKS")),
            total_runs=safe_int(summary.get("TOTAL_RUNS")),
            total_tasks=safe_int(summary.get("TOTAL_TASKS")),
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Ops Score", score, _task_ops_rating(score))
        c2.metric("Tasks", f"{safe_int(summary.get('TOTAL_TASKS')):,}")
        c3.metric("Runs", f"{safe_int(summary.get('TOTAL_RUNS')):,}")
        c4.metric("Failures", f"{safe_int(summary.get('FAILED_RUNS')):,}", delta_color="inverse")
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Suspended", f"{safe_int(summary.get('SUSPENDED_TASKS')):,}", delta_color="inverse")
        c6.metric("SLA/Cost Drift", f"{safe_int(summary.get('LONG_RUNNING_TASKS')) + safe_int(summary.get('COST_DRIFT_TASKS')):,}", delta_color="inverse")
        c7.metric("Open Recovery", f"{safe_int(summary.get('OPEN_RECOVERIES')):,}", delta_color="inverse")
        c8.metric("Recovery SLA", f"{safe_int(summary.get('RECOVERY_SLA_BREACHES')):,}", delta_color="inverse")
        if safe_int(summary.get("P1_INCIDENTS")) or safe_int(summary.get("BLOCKED_RECOVERIES")):
            st.caption(
                f"P1 graph incidents: {safe_int(summary.get('P1_INCIDENTS')):,} | "
                f"Blocked recoveries: {safe_int(summary.get('BLOCKED_RECOVERIES')):,} | "
                f"Recovery target: {safe_int(summary.get('RECOVERY_SLA_TARGET_HOURS')):,}h"
            )
        task_ops_sources = st.session_state.get("task_ops_sources", {})
        if task_ops_sources:
            st.caption(
                " | ".join([
                    str(task_ops_sources.get("inventory", "")),
                    str(task_ops_sources.get("history", "")),
                    str(task_ops_sources.get("query_detail", "")),
                    str(task_ops_sources.get("critical_path", "")),
                ])
            )
        if not st.session_state.get("task_ops_query_details_loaded"):
            st.caption("Cost drift uses estimated query credits when linked QUERY_HISTORY detail is available.")
        if score < 65:
            st.error("Incident risk: task graph failures, suspensions, or SLA drift need immediate triage.")
        elif score < 78:
            st.warning("Degraded: review failed and long-running task graph runs before production handoff.")
        elif score < 90:
            st.info("Watch: task graph operations are mostly stable with exceptions to review.")
        else:
            st.success("Operational: no dominant task graph risk signal in this scope.")

        slo_summary, slo_board = _build_task_reliability_slo_board(summary, exceptions, recovery_sla)
        st.subheader("Task Reliability SLO Board")
        s1, s2, s3 = st.columns(3)
        s1.metric("SLO Score", f"{slo_summary['score']}/100")
        s2.metric("Ready", f"{slo_summary['ready']:,}")
        s3.metric("Review", f"{slo_summary['review']:,}", delta_color="inverse")
        render_priority_dataframe(
            slo_board,
            title="Task reliability SLOs and next control step",
            priority_columns=["STATE", "SLO", "EVIDENCE", "NEXT_ACTION"],
            sort_by=["STATE", "SLO"],
            ascending=[True, True],
            raw_label="All task reliability SLO rows",
            height=220,
            max_rows=10,
        )

        recovery_board = _task_recovery_command_board(exceptions, recovery_sla)
        if not recovery_board.empty:
            st.subheader("Recovery Command Board")
            r1, r2, r3, r4 = st.columns(4)
            blocked = int(recovery_board["COMMAND_STATE"].astype(str).eq("Blocked").sum())
            p1_p2 = int(recovery_board["INCIDENT_PRIORITY"].astype(str).str.startswith(("P1", "P2")).sum())
            owner_review = int(
                recovery_board["OWNER_APPROVAL_STATE"].fillna("").astype(str).str.upper().str.contains("REQUIRED|REQUESTED", na=False).sum()
            )
            r1.metric("Recovery Items", f"{len(recovery_board):,}")
            r2.metric("Blocked", f"{blocked:,}", delta_color="inverse")
            r3.metric("P1 / P2", f"{p1_p2:,}", delta_color="inverse")
            r4.metric("Owner Review", f"{owner_review:,}", delta_color="inverse")
            render_priority_dataframe(
                recovery_board,
                title="Retry and closure readiness",
                priority_columns=[
                    "COMMAND_STATE", "INCIDENT_PRIORITY", "SIGNAL", "TASK_NAME",
                    "ROOT_TASK_NAME", "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT",
                    "RECOVERY_STATE", "RECOVERY_READINESS", "OWNER_APPROVAL_STATE",
                    "ONCALL_PRIMARY", "APPROVAL_GROUP", "NEXT_WORKFLOW",
                    "NEXT_ACTION", "VERIFY_AFTER_FIX",
                ],
                sort_by=["COMMAND_STATE", "INCIDENT_PRIORITY", "DOWNSTREAM_TASK_COUNT"],
                ascending=[True, True, False],
                raw_label="All recovery command rows",
                max_rows=12,
            )

        priority = _task_ops_priority_view(exceptions).head(3)
        st.markdown("**Next DBA Moves**")
        if priority.empty:
            st.caption("No immediate task graph exceptions. Use Failure Console after an alert, or SLA & Cost Drift after a release.")
        else:
            move_cols = st.columns(len(priority))
            for idx, (_, item) in enumerate(priority.iterrows()):
                workflow = str(item.get("NEXT_WORKFLOW") or "Task History")
                task_name = str(item.get("TASK_NAME") or item.get("ROOT_TASK_NAME") or "Task graph")
                with move_cols[idx]:
                    st.markdown(f"**{item.get('SEVERITY', 'Signal')}: {task_name}**")
                    st.caption(str(item.get("SIGNAL", "")))
                    detail = str(item.get("DETAIL", "") or "")
                    if detail:
                        st.caption(detail[:220])
                    st.write(str(item.get("NEXT_ACTION", "")))
                    if st.button(f"Open {workflow}", key=f"task_ops_next_{idx}_{workflow}", width="stretch"):
                        st.session_state["task_management_view"] = workflow
                        st.rerun()

        if not critical_paths.empty:
            st.subheader("Critical Path Snapshot")
            render_priority_dataframe(
                critical_paths,
                title="Task graph paths ranked by blast radius, failures, suspension, and runtime",
                priority_columns=[
                    "CRITICAL_PATH_STATE", "ROOT_TASK_NAME", "CRITICAL_PATH_SCORE",
                    "TASK_COUNT", "DOWNSTREAM_TASK_COUNT", "SUSPENDED_TASKS",
                    "FAILURES", "RUNS", "MAX_DURATION_SEC", "LAST_RUN_AT",
                    "BLAST_RADIUS", "OWNER_ROLE", "APPROVAL_PATH", "WAREHOUSES", "PROCEDURES",
                ],
                sort_by=["CRITICAL_PATH_SCORE", "DOWNSTREAM_TASK_COUNT", "MAX_DURATION_SEC"],
                ascending=[False, False, False],
                raw_label="All critical path rows",
                max_rows=20,
            )

        if not recovery_sla.empty:
            st.subheader("Recovery SLA Verification")
            render_priority_dataframe(
                recovery_sla,
                title="Failed task graph recovery proof",
                priority_columns=[
                    "INCIDENT_PRIORITY", "RECOVERY_STATE", "TASK_NAME", "ROOT_TASK_NAME",
                    "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "LAST_FAILURE_AT", "RECOVERY_AT",
                    "RECOVERY_HOURS", "RECOVERY_SLA_TARGET_HOURS", "OWNER", "OWNER_APPROVAL_STATE",
                    "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
                    "ERROR_SIGNATURE", "VERIFY_AFTER_FIX",
                ],
                sort_by=["INCIDENT_PRIORITY", "DOWNSTREAM_TASK_COUNT", "LAST_FAILURE_AT"],
                ascending=[True, False, False],
                raw_label="All recovery SLA rows",
                max_rows=30,
            )

        if not exceptions.empty:
            st.subheader("Task Graph Exceptions")
            render_priority_dataframe(
                exceptions,
                title="Task graph exceptions to work first",
                priority_columns=[
                    "INCIDENT_PRIORITY", "SEVERITY", "SIGNAL", "TASK_NAME", "ROOT_TASK_NAME",
                    "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "BLAST_RADIUS",
                    "PROCEDURE_NAME", "RECOVERY_STATE", "RECOVERY_HOURS", "OWNER_APPROVAL_STATE",
                    "RECOVERY_READINESS", "DETAIL", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["INCIDENT_PRIORITY", "SEVERITY", "DOWNSTREAM_TASK_COUNT", "SIGNAL", "TASK_NAME"],
                ascending=[True, True, False, True, True],
                raw_label="All task graph exceptions",
            )
            if st.button("Save Task Graph Findings to Action Queue", key="task_ops_queue"):
                try:
                    saved = _queue_task_ops_findings(session, exceptions)
                    st.success(f"Saved {saved} task graph findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")

        if not inventory.empty:
            st.subheader("Task Graph / Procedure Map")
            with st.expander("Interactive DAG View", expanded=False):
                st.caption(
                    "Shows task predecessor edges from SHOW TASKS. Dashed nodes are predecessors outside the loaded scope."
                )
                max_nodes = st.slider("Max graph nodes", 10, 150, 80, key="task_ops_graph_nodes")
                st.graphviz_chart(_build_task_graph_dot(inventory, max_nodes=max_nodes), width="stretch")
            map_cols = [
                col for col in [
                    "DATABASE_NAME", "SCHEMA_NAME", "ROOT_TASK_NAME", "NAME", "STATE",
                    "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "BLAST_RADIUS",
                    "SCHEDULE", "WAREHOUSE", "PREDECESSORS", "PROCEDURE_NAME", "IMPACT_OBJECTS"
                ] if col in inventory.columns
            ]
            render_priority_dataframe(
                inventory[map_cols],
                title="Task graph and procedure map",
                priority_columns=[
                    "DATABASE_NAME", "SCHEMA_NAME", "ROOT_TASK_NAME", "NAME",
                    "STATE", "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "BLAST_RADIUS",
                    "WAREHOUSE", "PROCEDURE_NAME", "IMPACT_OBJECTS",
                ],
                sort_by=["DOWNSTREAM_TASK_COUNT", "STATE", "ROOT_TASK_NAME", "NAME"],
                ascending=[False, True, True, True],
                raw_label="Full task graph/procedure map",
                max_rows=50,
            )

        if not latest.empty:
            st.subheader("Latest Run vs Historical Average")
            latest_cols = [
                col for col in [
                    "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "STATE", "QUERY_ID",
                    "DURATION_SEC", "AVG_DURATION_SEC", "MAX_DURATION_SEC", "FAILURES",
                    "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "GRAPH_ROLE",
                    "DOWNSTREAM_TASK_COUNT", "IMPACT_OBJECTS"
                ] if col in latest.columns
            ]
            render_priority_dataframe(
                latest[latest_cols],
                title="Latest runs versus historical average",
                priority_columns=[
                    "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "STATE",
                    "DURATION_SEC", "AVG_DURATION_SEC", "FAILURES",
                    "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "GRAPH_ROLE",
                    "DOWNSTREAM_TASK_COUNT", "IMPACT_OBJECTS",
                ],
                sort_by=["FAILURES", "DOWNSTREAM_TASK_COUNT", "DURATION_SEC", "EST_TOTAL_CREDITS"],
                ascending=[False, False, False, False],
                raw_label="All latest task runs",
                max_rows=50,
            )

        st.download_button(
            "Download Task Graph Operations Brief",
            _build_task_ops_markdown(company, days, score, summary, exceptions),
            file_name=f"overwatch_task_graph_ops_{company.lower()}.md",
            mime="text/markdown",
            key="task_ops_download",
        )


def _render_sla_cost_drift_console(session) -> None:
    company = get_active_company()
    st.header("Task SLA & Cost Drift")
    st.caption(
        "Use this after product releases or stored procedure changes. It compares each task's latest run "
        "to its own historical baseline and highlights duration or estimated-credit regressions."
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        days = st.slider("Lookback (days)", 3, 45, 14, key="task_sla_days")
    with c2:
        duration_pct = st.slider("Duration drift threshold (%)", 10, 300, 50, key="task_sla_duration_pct")
    with c3:
        cost_pct = st.slider("Cost drift threshold (%)", 10, 300, 50, key="task_sla_cost_pct")
    with c4:
        min_duration_sec = st.number_input("Minimum latest runtime (sec)", min_value=0, value=300, step=60, key="task_sla_min_runtime")
    min_credits = st.number_input(
        "Minimum estimated credits before cost drift matters",
        min_value=0.0,
        value=0.01,
        step=0.01,
        format="%.4f",
        key="task_sla_min_credits",
    )
    threshold_context = {
        "Lookback Days": int(days),
        "Duration Drift Threshold %": float(duration_pct),
        "Cost Drift Threshold %": float(cost_pct),
        "Minimum Runtime Sec": float(min_duration_sec),
        "Minimum Estimated Credits": float(min_credits),
    }
    st.caption(
        "Thresholds: "
        f"runtime >= {safe_float(min_duration_sec):,.0f}s and +{safe_float(duration_pct):,.0f}% over baseline; "
        f"estimated credits >= {safe_float(min_credits):,.4f} and +{safe_float(cost_pct):,.0f}% over baseline."
    )

    if st.button("Load SLA & Cost Drift", key="task_sla_load"):
        summary, exceptions, latest, inventory, details_loaded = _load_task_ops_scope(
            session, days, "task_sla", force_inventory_refresh=True
        )
        st.session_state["task_sla_summary"] = summary
        st.session_state["task_sla_latest"] = latest
        st.session_state["task_sla_inventory"] = inventory
        st.session_state["task_sla_details_loaded"] = details_loaded
        st.session_state["task_sla_threshold_context"] = threshold_context

    latest = st.session_state.get("task_sla_latest", pd.DataFrame())
    if latest is None or latest.empty:
        st.info("Load SLA & Cost Drift to compare latest task runs to historical baselines.")
        return

    view = latest.copy()
    for col in ["DURATION_SEC", "AVG_DURATION_SEC", "EST_TOTAL_CREDITS", "AVG_EST_CREDITS"]:
        if col not in view.columns:
            view[col] = 0.0
        view[col] = pd.to_numeric(view[col], errors="coerce").fillna(0.0)
    view["DURATION_CHANGE_PCT"] = view.apply(
        lambda row: ((row["DURATION_SEC"] - row["AVG_DURATION_SEC"]) / row["AVG_DURATION_SEC"] * 100)
        if row["AVG_DURATION_SEC"] > 0 else 0.0,
        axis=1,
    )
    view["COST_CHANGE_PCT"] = view.apply(
        lambda row: ((row["EST_TOTAL_CREDITS"] - row["AVG_EST_CREDITS"]) / row["AVG_EST_CREDITS"] * 100)
        if row["AVG_EST_CREDITS"] > 0 else 0.0,
        axis=1,
    )
    view["SLA_BREACH"] = (
        (view["AVG_DURATION_SEC"] > 0)
        & (view["DURATION_SEC"] >= float(min_duration_sec))
        & (view["DURATION_CHANGE_PCT"] >= float(duration_pct))
    )
    view["COST_DRIFT"] = (
        (view["AVG_EST_CREDITS"] > 0)
        & (view["EST_TOTAL_CREDITS"] >= float(min_credits))
        & (view["COST_CHANGE_PCT"] >= float(cost_pct))
    )
    view["BREACH_REASON"] = view.apply(
        lambda row: "SLA and cost drift" if row["SLA_BREACH"] and row["COST_DRIFT"]
        else "SLA breach" if row["SLA_BREACH"]
        else "Cost drift" if row["COST_DRIFT"]
        else "Within threshold",
        axis=1,
    )
    for label, value in threshold_context.items():
        view[label.upper().replace(" ", "_").replace("%", "PCT")] = value
    breaches = (
        view[view["SLA_BREACH"] | view["COST_DRIFT"]]
        .sort_values(["SLA_BREACH", "COST_DRIFT", "DURATION_CHANGE_PCT", "COST_CHANGE_PCT"], ascending=[False, False, False, False])
    )

    summary = st.session_state.get("task_sla_summary", {})
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Tasks Compared", f"{len(view):,}")
    k2.metric("SLA Breaches", f"{int(view['SLA_BREACH'].sum()):,}", delta_color="inverse")
    k3.metric("Cost Drift", f"{int(view['COST_DRIFT'].sum()):,}", delta_color="inverse")
    k4.metric("Failures", f"{safe_int(summary.get('FAILED_RUNS')):,}", delta_color="inverse")
    k5.metric("Query Detail", "Loaded" if st.session_state.get("task_sla_details_loaded") else "Estimated")
    task_sla_sources = st.session_state.get("task_sla_sources", {})
    if task_sla_sources:
        st.caption(
            " | ".join([
                str(task_sla_sources.get("inventory", "")),
                str(task_sla_sources.get("history", "")),
                str(task_sla_sources.get("query_detail", "")),
            ])
        )
    if st.session_state.get("task_sla_details_loaded"):
        st.caption("Cost drift uses linked QUERY_HISTORY query detail and estimated task query credits.")
    else:
        st.caption("Cost drift needs linked QUERY_HISTORY detail; duration/SLA review is still available.")

    display_cols = [
        col for col in [
            "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "STATE", "QUERY_ID",
            "DURATION_SEC", "AVG_DURATION_SEC", "DURATION_CHANGE_PCT",
            "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "COST_CHANGE_PCT",
            "BREACH_REASON", "WAREHOUSE_NAME", "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT",
            "BLAST_RADIUS", "IMPACT_OBJECTS", "TASK_FQN",
        ] if col in view.columns
    ]
    if breaches.empty:
        st.success("No task runs breached the selected SLA or cost drift thresholds.")
    else:
        st.warning("Task regressions found. Review these before the next production handoff.")
        render_priority_dataframe(
            breaches[display_cols],
            title="Task SLA and cost regressions",
            priority_columns=[
                "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "BREACH_REASON",
                "DURATION_SEC", "AVG_DURATION_SEC", "DURATION_CHANGE_PCT",
                "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "COST_CHANGE_PCT",
                "WAREHOUSE_NAME", "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT",
                "BLAST_RADIUS", "IMPACT_OBJECTS",
            ],
            sort_by=["DOWNSTREAM_TASK_COUNT", "DURATION_CHANGE_PCT", "COST_CHANGE_PCT", "DURATION_SEC"],
            ascending=[False, False, False, False],
            raw_label="All task SLA/cost breach rows",
        )
        top_duration = breaches.sort_values("DURATION_CHANGE_PCT", ascending=False).head(15)
        top_cost = breaches.sort_values("COST_CHANGE_PCT", ascending=False).head(15)
        left, right = st.columns(2)
        with left:
            if "TASK_NAME" in top_duration.columns:
                render_ranked_bar_chart(
                    top_duration,
                    "TASK_NAME",
                    "DURATION_CHANGE_PCT",
                    title="Top Duration Regressions",
                    top_n=15,
                )
        with right:
            if "TASK_NAME" in top_cost.columns:
                render_ranked_bar_chart(
                    top_cost,
                    "TASK_NAME",
                    "COST_CHANGE_PCT",
                    title="Top Cost Regressions",
                    top_n=15,
                    color="#f59e0b",
                )
        queue_rows = []
        for _, row in breaches.head(100).iterrows():
            signal = "Long Running / SLA Risk" if row.get("SLA_BREACH") else "Cost Drift / Release Regression"
            if row.get("SLA_BREACH") and row.get("COST_DRIFT"):
                signal = "SLA and Cost Drift"
            queue_stub = pd.Series({
                "SIGNAL": signal,
                "DOWNSTREAM_TASK_COUNT": row.get("DOWNSTREAM_TASK_COUNT", 0),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
            })
            queue_rows.append({
                "SEVERITY": "High" if row.get("SLA_BREACH") and safe_float(row.get("DURATION_CHANGE_PCT")) >= duration_pct * 2 else "Medium",
                "SIGNAL": signal,
                "INCIDENT_PRIORITY": _task_exception_incident_priority(queue_stub),
                "RECOVERY_READINESS": _task_exception_recovery_readiness(queue_stub),
                "TASK_NAME": row.get("TASK_NAME", ""),
                "ROOT_TASK_NAME": row.get("ROOT_TASK_NAME", ""),
                "PROCEDURE_NAME": row.get("PROCEDURE_NAME", ""),
                "QUERY_ID": row.get("QUERY_ID", ""),
                "STATE": row.get("STATE", ""),
                "DETAIL": (
                    f"Latest runtime {safe_float(row.get('DURATION_SEC')):,.0f}s vs avg {safe_float(row.get('AVG_DURATION_SEC')):,.0f}s "
                    f"({safe_float(row.get('DURATION_CHANGE_PCT')):,.1f}%). "
                    f"Latest credits {safe_float(row.get('EST_TOTAL_CREDITS')):,.4f} vs avg {safe_float(row.get('AVG_EST_CREDITS')):,.4f} "
                    f"({safe_float(row.get('COST_CHANGE_PCT')):,.1f}%). "
                    f"Thresholds: runtime +{safe_float(duration_pct):,.0f}% over baseline and >= {safe_float(min_duration_sec):,.0f}s; "
                    f"cost +{safe_float(cost_pct):,.0f}% over baseline and >= {safe_float(min_credits):,.4f} credits."
                ),
                "IMPACT_OBJECTS": row.get("IMPACT_OBJECTS", ""),
                "TASK_FQN": row.get("TASK_FQN", ""),
                "GRAPH_ROLE": row.get("GRAPH_ROLE", ""),
                "DOWNSTREAM_TASK_COUNT": row.get("DOWNSTREAM_TASK_COUNT", 0),
                "BLAST_RADIUS": row.get("BLAST_RADIUS", ""),
                "RETRY_SCOPE": row.get("RETRY_SCOPE", ""),
            })
        queue_df = pd.DataFrame(queue_rows)
        if st.button("Save SLA/Cost Drift Findings to Action Queue", key="task_sla_queue"):
            try:
                saved = _queue_task_ops_findings(session, queue_df)
                st.success(f"Saved {saved} SLA/cost drift findings to the action queue.")
            except Exception as e:
                st.error(f"Could not save SLA/cost drift findings: {format_snowflake_error(e)}")
                st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")

    with st.expander("All Latest Task Runs"):
        render_priority_dataframe(
            view[display_cols],
            title="Latest task run detail",
            priority_columns=display_cols,
            sort_by=["DURATION_SEC", "EST_TOTAL_CREDITS"],
            ascending=[False, False],
            raw_label="Full latest task run detail",
            max_rows=100,
        )
    download_csv(view[display_cols], f"task_sla_cost_drift_{company.lower()}.csv")


def render():
    session = get_session()

    _render_task_ops_brief(session)
    if st.session_state.get("exceptions_only_mode"):
        st.stop()

    task_view = render_workflow_selector(
        "Task management workflow",
        "task_management_view",
        TASK_CONTROL_VIEWS,
        TASK_CONTROL_DETAILS,
        columns=3,
    )

    # -- TASK HISTORY ----------------------------------------------------------
    if task_view == "Task History":
        st.header("Task Execution History")
        th_days = st.slider("Lookback (days)", 1, 30, 7, key="th_days")

        if st.button("Load Task Data", key="th_load"):
            # Task list
            try:
                df_tl = _show_tasks(session, force_refresh=True)
                st.session_state["tg_list"] = df_tl
            except Exception:
                st.session_state["tg_list"] = pd.DataFrame()

            # Task history
            try:
                df_th = run_query_or_raise(build_task_history_sql(
                    session,
                    f"scheduled_time >= DATEADD('day', -{int(th_days)}, CURRENT_TIMESTAMP())",
                    limit=500,
                    company=st.session_state.get("active_company", "ALFA"),
                ))
                st.session_state["tg_hist"] = df_th
            except Exception as e:
                st.info(f"Task history unavailable in this role/context: {format_snowflake_error(e)}")
                st.session_state["tg_hist"] = pd.DataFrame()

        tl = st.session_state.get("tg_list", pd.DataFrame())
        th = st.session_state.get("tg_hist", pd.DataFrame())

        if not tl.empty:
            c1, c2 = st.columns(2)
            c1.metric("Total Tasks", len(tl))
            active_tasks = tl[tl["STATE"] == "started"] if "STATE" in tl.columns else pd.DataFrame()
            c2.metric("Active (started)", len(active_tasks))

        if not th.empty:
            failed_tasks = th[th["STATE"] == "FAILED"] if "STATE" in th.columns else pd.DataFrame()
            succeeded    = th[th["STATE"] == "SUCCEEDED"] if "STATE" in th.columns else pd.DataFrame()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Runs",  len(th))
            c2.metric("Succeeded",   len(succeeded))
            c3.metric("Failed",      len(failed_tasks), delta_color="inverse")

            if not failed_tasks.empty:
                st.subheader("Failed Tasks")
                render_priority_dataframe(
                    failed_tasks,
                    title="Failed task runs to triage first",
                    priority_columns=[
                        "NAME", "TASK_NAME", "ROOT_TASK_NAME", "STATE", "QUERY_ID",
                        "ERROR_MESSAGE", "SCHEDULED_TIME", "COMPLETED_TIME",
                    ],
                    sort_by=["SCHEDULED_TIME", "COMPLETED_TIME"],
                    ascending=[False, False],
                    raw_label="All failed task runs",
                    max_rows=20,
                )
                if st.button("Save failed tasks to Action Queue", key="tm_failed_queue"):
                    _queue_task_findings(session, failed_tasks, "Task Management - Task History")

            st.subheader("Full History")
            render_priority_dataframe(
                th,
                title="Recent task history",
                priority_columns=[
                    "NAME", "TASK_NAME", "ROOT_TASK_NAME", "STATE", "QUERY_ID",
                    "SCHEDULED_TIME", "COMPLETED_TIME", "DURATION_SEC", "ERROR_MESSAGE",
                ],
                sort_by=["SCHEDULED_TIME", "COMPLETED_TIME"],
                ascending=[False, False],
                raw_label="Full task history",
                max_rows=100,
                height=400,
            )
            download_csv(th, "task_history.csv")

    elif task_view == "Failure Console":
        st.header("Failure Console & Runbook")
        st.caption(
            "Diagnose failed task graph runs, link failures to query history and stored procedures, "
            "classify probable cause, and export a DBA handoff runbook."
        )
        fc_days = st.slider("Failure lookback (days)", 1, 30, 7, key="tm_failure_days")
        if st.button("Load Failure Console", key="tm_failure_load"):
            try:
                inventory = _show_tasks(session, force_refresh=True)
            except Exception as e:
                st.info(f"Task inventory unavailable: {format_snowflake_error(e)}")
                inventory = pd.DataFrame()
            try:
                history = run_query_or_raise(build_task_history_sql(
                    session,
                    f"scheduled_time >= DATEADD('day', -{int(fc_days)}, CURRENT_TIMESTAMP())",
                    limit=1000,
                    company=get_active_company(),
                ))
            except Exception as e:
                st.info(f"Task failure history unavailable: {format_snowflake_error(e)}")
                history = pd.DataFrame()

            failed_query_ids = []
            if not history.empty and "QUERY_ID" in history.columns:
                states = history.get("STATE", pd.Series([""] * len(history), index=history.index)).astype(str).str.upper()
                failed_query_ids = history.loc[states.eq("FAILED"), "QUERY_ID"].dropna().astype(str).tolist()

            query_details = pd.DataFrame()
            if failed_query_ids:
                try:
                    query_sql = _query_detail_sql(session, failed_query_ids)
                    if query_sql:
                        query_details = run_query(
                            query_sql,
                            ttl_key=f"task_failure_query_detail_{get_active_company()}_{fc_days}_{len(failed_query_ids)}",
                            tier="standard",
                        )
                except Exception as e:
                    st.info(f"Linked query detail unavailable: {format_snowflake_error(e)}")

            summary, failures, patterns = _build_failure_console_frames(history, inventory, query_details)
            st.session_state["tm_failure_summary"] = summary
            st.session_state["tm_failure_rows"] = failures
            st.session_state["tm_failure_patterns"] = patterns

        summary = st.session_state.get("tm_failure_summary")
        failures = st.session_state.get("tm_failure_rows", pd.DataFrame())
        patterns = st.session_state.get("tm_failure_patterns", pd.DataFrame())
        if summary:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Failures", f"{safe_int(summary.get('FAILURES')):,}", delta_color="inverse")
            c2.metric("Affected Tasks", f"{safe_int(summary.get('TASKS')):,}")
            c3.metric("Categories", f"{safe_int(summary.get('CATEGORIES')):,}")
            c4.metric("High Priority", f"{safe_int(summary.get('CRITICAL')):,}", delta_color="inverse")

            if failures.empty:
                st.success("No failed task runs found for the selected scope.")
            else:
                st.warning("Failed task runs found. Review probable cause before using retry controls.")
                if safe_int(summary.get("P1_INCIDENTS")) or safe_int(summary.get("BLOCKED_RECOVERIES")):
                    st.caption(
                        f"P1 graph incidents: {safe_int(summary.get('P1_INCIDENTS')):,} | "
                        f"Blocked recoveries: {safe_int(summary.get('BLOCKED_RECOVERIES')):,} | "
                        f"Open recoveries: {safe_int(summary.get('OPEN_RECOVERIES')):,} | "
                        f"Recovery SLA breaches: {safe_int(summary.get('RECOVERY_SLA_BREACHES')):,}"
                    )
                if not patterns.empty:
                    st.subheader("Common Failure Patterns")
                    render_priority_dataframe(
                        patterns,
                        title="Most common failure patterns",
                        priority_columns=[
                            "INCIDENT_PRIORITY", "FAILURE_CATEGORY", "ERROR_SIGNATURE", "FAILURE_COUNT",
                            "TASK_COUNT", "DOWNSTREAM_TASK_COUNT", "RECOVERY_READINESS",
                            "LAST_SEEN", "RECOMMENDED_ACTION",
                        ],
                        sort_by=["INCIDENT_PRIORITY", "FAILURE_COUNT", "TASK_COUNT", "DOWNSTREAM_TASK_COUNT"],
                        ascending=[True, False, False, False],
                        raw_label="All failure patterns",
                    )

                category_options = ["All"] + sorted(failures["FAILURE_CATEGORY"].dropna().astype(str).unique().tolist())
                selected_category = st.selectbox("Filter by failure category", category_options, key="tm_failure_category")
                view = failures if selected_category == "All" else failures[failures["FAILURE_CATEGORY"] == selected_category]
                display_cols = [
                    col for col in [
                        "INCIDENT_PRIORITY", "SEVERITY", "TASK_NAME", "ROOT_TASK_NAME",
                        "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "BLAST_RADIUS",
                        "PROCEDURE_NAME", "QUERY_ID",
                        "FAILURE_CATEGORY", "PROBABLE_CAUSE", "RECOMMENDED_ACTION",
                        "RECOVERY_STATE", "RECOVERY_HOURS", "RECOVERY_SLA_TARGET_HOURS",
                        "OWNER_APPROVAL_STATE", "ONCALL_PRIMARY", "APPROVAL_GROUP",
                        "OWNER_SOURCE", "RECOVERY_READINESS", "VERIFY_AFTER_FIX",
                        "STATE", "DURATION_SEC", "QUERY_ELAPSED_SEC", "WAREHOUSE_NAME",
                        "IMPACT_OBJECTS", "ERROR_SIGNATURE", "RETRY_SQL"
                    ] if col in view.columns
                ]
                st.subheader("Failure Drilldown")
                render_priority_dataframe(
                    view[display_cols],
                    title="Failure rows to resolve first",
                    priority_columns=[
                        "INCIDENT_PRIORITY", "TASK_NAME", "ROOT_TASK_NAME", "GRAPH_ROLE",
                        "DOWNSTREAM_TASK_COUNT", "PROCEDURE_NAME", "FAILURE_CATEGORY",
                        "RECOVERY_STATE", "OWNER_APPROVAL_STATE", "ONCALL_PRIMARY",
                        "APPROVAL_GROUP", "RECOVERY_READINESS",
                        "PROBABLE_CAUSE", "RECOMMENDED_ACTION", "QUERY_ID",
                        "DURATION_SEC", "QUERY_ELAPSED_SEC", "WAREHOUSE_NAME",
                    ],
                    sort_by=["INCIDENT_PRIORITY", "DOWNSTREAM_TASK_COUNT", "DURATION_SEC", "QUERY_ELAPSED_SEC"],
                    ascending=[True, False, False, False],
                    raw_label="All failure drilldown rows",
                )
                download_csv(view[display_cols], "task_failure_console.csv")

                task_options = view["TASK_NAME"].dropna().astype(str).unique().tolist() if "TASK_NAME" in view.columns else []
                if task_options:
                    selected_task = st.selectbox("Open failure runbook detail", task_options, key="tm_failure_task_detail")
                    detail = view[view["TASK_NAME"].astype(str) == selected_task].head(1)
                    if not detail.empty:
                        row = detail.iloc[0]
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            st.markdown("**Probable Cause**")
                            st.write(row.get("PROBABLE_CAUSE", ""))
                            st.markdown("**Recommended Action**")
                            st.write(row.get("RECOMMENDED_ACTION", ""))
                            st.markdown("**Recovery Readiness**")
                            st.write(row.get("RECOVERY_READINESS", ""))
                            st.markdown("**Recovery SLA**")
                            st.write(row.get("RECOVERY_STATE", ""))
                            st.markdown("**Owner Approval**")
                            st.write(row.get("OWNER_APPROVAL_STATE", ""))
                        with c2:
                            st.markdown("**Retry SQL After Fix**")
                            st.code(str(row.get("RETRY_SQL") or ""), language="sql")
                            st.markdown("**Evidence**")
                            st.caption(f"Priority: {row.get('INCIDENT_PRIORITY', '')}")
                            st.caption(f"Downstream tasks: {safe_int(row.get('DOWNSTREAM_TASK_COUNT')):,}")
                            st.caption(f"Query ID: {row.get('QUERY_ID', '')}")
                            st.caption(f"Procedure: {row.get('PROCEDURE_NAME', '')}")
                            st.caption(f"Impact hints: {row.get('IMPACT_OBJECTS', '')}")
                            st.caption(f"Signature: {row.get('ERROR_SIGNATURE', '')}")
                            st.caption(f"Verify after fix: {row.get('VERIFY_AFTER_FIX', '')}")
                        if "QUERY_TEXT" in row.index and str(row.get("QUERY_TEXT") or "").strip():
                            with st.expander("Linked Query Text"):
                                st.code(str(row.get("QUERY_TEXT")), language="sql")

                if st.button("Save Failures to Action Queue", key="tm_failure_queue"):
                    try:
                        saved = _queue_failure_findings(session, failures)
                        st.success(f"Saved {saved} failure findings to the action queue.")
                    except Exception as e:
                        st.error(f"Could not save failure findings: {format_snowflake_error(e)}")
                        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")
                st.download_button(
                    "Download Failure Runbook",
                    _build_failure_runbook_markdown(get_active_company(), fc_days, summary, failures, patterns),
                    file_name=f"overwatch_failure_runbook_{get_active_company().lower()}.md",
                    mime="text/markdown",
                    key="tm_failure_runbook_download",
                )

    # -- ETL AUDIT -------------------------------------------------------------
    elif task_view == "SLA & Cost Drift":
        _render_sla_cost_drift_console(session)

    elif task_view == "ETL Audit":
        st.header("ETL Audit Framework")
        st.caption(f"Custom ETL run tracking table: `{ETL_AUDIT_FQN}`")
        st.info("ETL audit table deployment is managed by `snowflake/OVERWATCH_MART_SETUP.sql`.")

        if st.button("Load ETL Audit Log", key="etl_load"):
            try:
                df_etl = run_query(f"""
                    SELECT
                        RUN_ID,
                        PIPELINE_NAME,
                        TASK_NAME,
                        STATUS,
                        RUN_START,
                        RUN_END,
                        ERROR_MESSAGE
                    FROM {ETL_AUDIT_FQN}
                    WHERE RUN_START >= DATEADD('day', -30, CURRENT_TIMESTAMP())
                    ORDER BY RUN_START DESC
                    LIMIT 500
                """, ttl_key="task_management_etl_audit", tier="recent", section="Task Management")
                st.session_state["tm_df_etl"] = df_etl
            except Exception as e:
                st.info(f"Audit table unavailable. Deploy `snowflake/OVERWATCH_MART_SETUP.sql`, then retry. ({format_snowflake_error(e)})")

        if st.session_state.get("tm_df_etl") is not None and not st.session_state["tm_df_etl"].empty:
            df_e = st.session_state["tm_df_etl"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Runs", len(df_e))
            ok  = df_e[df_e["STATUS"] == "SUCCESS"] if "STATUS" in df_e.columns else pd.DataFrame()
            err = df_e[df_e["STATUS"] == "FAILED"]  if "STATUS" in df_e.columns else pd.DataFrame()
            c2.metric("Success", len(ok))
            c3.metric("Failed",  len(err), delta_color="inverse")
            render_priority_dataframe(
                df_e,
                title="ETL audit runs to review first",
                priority_columns=[
                    "RUN_ID", "PIPELINE_NAME", "TASK_NAME", "STATUS",
                    "RUN_START", "RUN_END", "ERROR_MESSAGE",
                ],
                sort_by=["STATUS", "RUN_START"],
                ascending=[True, False],
                raw_label="All ETL audit rows",
                max_rows=100,
            )
            download_csv(df_e, "etl_audit.csv")
            if not err.empty and st.button("Save failed ETL runs to Action Queue", key="tm_etl_queue"):
                _queue_task_findings(session, err, "Task Management - ETL Audit")

    elif task_view == "Control Center":
        st.header("Task Graph Control Center")
        st.caption(
            "Generate and run guarded task actions from the same place you diagnose graph health. "
            "Every action is written to the OVERWATCH admin audit table when that table exists."
        )
        if not admin_actions_enabled():
            st.info("Read-only mode is active. Enable Admin actions in Settings before running operational controls.")
        st.caption("Admin action audit table deployment is managed by `snowflake/OVERWATCH_MART_SETUP.sql`.")
        exec_context = _current_execution_context(session)
        st.caption(
            "Execution context: "
            f"user `{exec_context.get('snowflake_user') or 'unknown'}` | "
            f"role `{exec_context.get('snowflake_role') or 'unknown'}` | "
            f"warehouse `{exec_context.get('snowflake_warehouse') or 'none'}`"
        )

        if st.button("Refresh Task Inventory", key="tm_control_refresh"):
            try:
                st.session_state["tg_list"] = _show_tasks(session, force_refresh=True)
                st.success("Task inventory refreshed.")
            except Exception as e:
                st.warning(f"Task inventory unavailable: {format_snowflake_error(e)}")

        tl = st.session_state.get("tg_list", pd.DataFrame())
        if tl.empty:
            st.warning("Load task inventory from this tab or Task History before using controls.")
        else:
            pred_series = tl.get("PREDECESSORS", pd.Series([""] * len(tl), index=tl.index)).astype(str).str.strip().str.upper()
            root_candidates = tl[pred_series.isin(["", "[]", "NONE", "NAN", "NULL"])] if "NAME" in tl.columns else tl
            root_names = root_candidates["NAME"].astype(str).sort_values().unique().tolist() if "NAME" in root_candidates.columns else []
            all_names = tl["NAME"].astype(str).sort_values().unique().tolist() if "NAME" in tl.columns else []

            control_mode = st.radio(
                "Control target",
                ["Graph/root task", "Individual task", "Cancel running graph/query"],
                horizontal=True,
                key="tm_control_mode",
            )

            if control_mode == "Graph/root task":
                root_name = st.selectbox("Root task", root_names or all_names, key="tm_control_root")
                root_row = tl[tl["NAME"].astype(str) == str(root_name)].iloc[0]
                graph_tasks = _collect_graph_tasks(tl, root_name)
                st.info(
                    f"Root: `{_task_full_name(root_row)}` | Tasks affected: {len(graph_tasks)} | "
                    f"Environment guard: {'PROD' if _is_prod_task(root_row) else 'Standard'}"
                )
                if _is_prod_task(root_row):
                    st.error("PROD-like task detected. Controls require the PROD confirmation phrase below.")
                with st.expander("Graph Preview", expanded=True):
                    st.graphviz_chart(_build_task_graph_dot(graph_tasks, max_nodes=120), width="stretch")
                    preview_cols = [
                        col for col in ["DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE", "SCHEDULE", "WAREHOUSE", "PROCEDURE_NAME"]
                        if col in graph_tasks.columns
                    ]
                    render_priority_dataframe(
                        graph_tasks[preview_cols],
                        title="Graph tasks affected",
                        priority_columns=preview_cols,
                        sort_by=["STATE", "DATABASE_NAME", "SCHEMA_NAME", "NAME"],
                        ascending=[True, True, True, True],
                        raw_label="All graph task rows",
                    )

                action = st.selectbox(
                    "Graph action",
                    ["EXECUTE", "RETRY", "SUSPEND", "RESUME"],
                    key="tm_graph_action",
                    help="Retry re-executes the root task. Snowflake does not expose a native retry-last-failed graph command.",
                )
                sql_list = _admin_sql_for_graph(graph_tasks, root_name, action)
                st.code(";\n".join(sql_list) + (";" if sql_list else ""), language="sql")
                with st.expander("Read-only pre-flight checks before running this action"):
                    st.code(build_admin_preflight_sql(root_row), language="sql")
                phrase = _confirmation_phrase(root_row, action)
                confirmed = _typed_confirmation(
                    f"Type `{phrase}` to enable this graph action",
                    phrase,
                    f"tm_graph_confirm_{action}_{root_name}",
                )
                if st.button(
                    f"Run graph action: {action}",
                    type="primary",
                    key="tm_graph_run",
                    disabled=admin_button_disabled(not confirmed or not sql_list),
                ):
                    completed, errors = _run_admin_sql_list(
                        session,
                        sql_list,
                        f"TASK GRAPH {action}",
                        root_name,
                        confirmation_text=phrase,
                        control_context=(
                            f"mode=Graph/root task; tasks_affected={len(graph_tasks)}; "
                            f"prod_guard={_is_prod_task(root_row)}"
                        ),
                    )
                    if errors:
                        st.warning(f"Completed {completed} statement(s) with {len(errors)} error(s).")
                        for err in errors[:10]:
                            st.caption(err)
                    else:
                        st.success(f"Completed {completed} statement(s) for graph `{root_name}`.")
                    st.session_state.pop("tg_list", None)

            elif control_mode == "Individual task":
                task_name = st.selectbox("Task", all_names, key="tm_control_task")
                row = tl[tl["NAME"].astype(str) == str(task_name)].iloc[0]
                st.info(
                    f"Task: `{_task_full_name(row)}` | State: {row.get('STATE', 'N/A')} | "
                    f"Schedule: {row.get('SCHEDULE', 'N/A')}"
                )
                if _is_prod_task(row):
                    st.error("PROD-like task detected. Controls require the PROD confirmation phrase below.")
                action = st.selectbox("Task action", ["EXECUTE", "RETRY", "SUSPEND", "RESUME"], key="tm_task_action")
                sql_list = _admin_sql_for_task(row, action)
                st.code(";\n".join(sql_list) + ";", language="sql")
                with st.expander("Read-only pre-flight checks before running this action"):
                    st.code(build_admin_preflight_sql(row), language="sql")
                phrase = _confirmation_phrase(row, action)
                confirmed = _typed_confirmation(
                    f"Type `{phrase}` to enable this task action",
                    phrase,
                    f"tm_task_confirm_{action}_{task_name}",
                )
                if st.button(
                    f"Run task action: {action}",
                    type="primary",
                    key="tm_task_run",
                    disabled=admin_button_disabled(not confirmed),
                ):
                    completed, errors = _run_admin_sql_list(
                        session,
                        sql_list,
                        f"TASK {action}",
                        task_name,
                        confirmation_text=phrase,
                        control_context=f"mode=Individual task; prod_guard={_is_prod_task(row)}",
                    )
                    if errors:
                        st.warning(f"Completed {completed} statement(s) with {len(errors)} error(s).")
                        for err in errors[:10]:
                            st.caption(err)
                    else:
                        st.success(f"Completed task action `{action}` for `{task_name}`.")
                    st.session_state.pop("tg_list", None)

            else:
                st.subheader("Cancel Running Task Graph or Query")
                st.caption(
                    "Use this only for currently running task graph executions or their spawned queries. "
                    "Snowflake privileges still apply."
                )
                if st.button("Load Recent Running Task Runs", key="tm_cancel_load"):
                    try:
                        recent_runs = run_query_or_raise(build_task_history_sql(
                            session,
                            "scheduled_time >= DATEADD('hours', -6, CURRENT_TIMESTAMP())",
                            limit=300,
                            company=get_active_company(),
                        ))
                        if "STATE" in recent_runs.columns:
                            states = recent_runs["STATE"].astype(str).str.upper()
                            recent_runs = recent_runs[states.isin(["EXECUTING", "RUNNING", "SCHEDULED"])]
                        st.session_state["tm_cancel_runs"] = recent_runs
                    except Exception as e:
                        st.warning(f"Recent task runs unavailable: {format_snowflake_error(e)}")
                        st.session_state["tm_cancel_runs"] = pd.DataFrame()
                cancel_runs = st.session_state.get("tm_cancel_runs", pd.DataFrame())
                if cancel_runs.empty:
                    st.success("No running task graph runs loaded for cancellation.")
                else:
                    render_priority_dataframe(
                        cancel_runs,
                        title="Running task graph runs",
                        priority_columns=[
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                            "SCHEDULED_TIME", "QUERY_ID", "GRAPH_RUN_GROUP_ID",
                            "DURATION_SEC", "ERROR_MESSAGE",
                        ],
                        sort_by=["SCHEDULED_TIME", "DURATION_SEC"],
                        ascending=[False, False],
                        raw_label="All cancellable task run rows",
                    )
                    cancel_type = st.radio("Cancel target", ["Graph Run Group", "Query ID"], horizontal=True, key="tm_cancel_type")
                    if cancel_type == "Graph Run Group" and "GRAPH_RUN_GROUP_ID" in cancel_runs.columns:
                        graph_ids = cancel_runs["GRAPH_RUN_GROUP_ID"].dropna().astype(str).unique().tolist()
                        selected_graph = st.selectbox("Graph run group", graph_ids, key="tm_cancel_graph")
                        sql_text = f"SELECT SYSTEM$CANCEL_TASK_GRAPH({sql_literal(selected_graph)})"
                        st.code(sql_text + ";", language="sql")
                        confirmed = _typed_confirmation("Type CANCEL GRAPH to enable cancellation", "CANCEL GRAPH", "tm_cancel_graph_confirm")
                        if st.button("Cancel graph run", type="primary", key="tm_cancel_graph_btn", disabled=admin_button_disabled(not confirmed)):
                            completed, errors = _run_admin_sql_list(
                                session,
                                [sql_text],
                                "CANCEL TASK GRAPH",
                                selected_graph,
                                confirmation_text="CANCEL GRAPH",
                                control_context="mode=Cancel running graph/query",
                            )
                            st.success("Cancel request sent.") if not errors else st.error(errors[0])
                    elif cancel_type == "Query ID" and "QUERY_ID" in cancel_runs.columns:
                        query_ids = cancel_runs["QUERY_ID"].dropna().astype(str).unique().tolist()
                        selected_query = st.selectbox("Query ID", query_ids, key="tm_cancel_query")
                        sql_text = f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(selected_query)})"
                        st.code(sql_text + ";", language="sql")
                        confirmed = _typed_confirmation("Type CANCEL QUERY to enable cancellation", "CANCEL QUERY", "tm_cancel_query_confirm")
                        if st.button("Cancel query", type="primary", key="tm_cancel_query_btn", disabled=admin_button_disabled(not confirmed)):
                            completed, errors = _run_admin_sql_list(
                                session,
                                [sql_text],
                                "CANCEL QUERY",
                                selected_query,
                                confirmation_text="CANCEL QUERY",
                                control_context="mode=Cancel running graph/query",
                            )
                            st.success("Cancel request sent.") if not errors else st.error(errors[0])
                    else:
                        st.info("The selected cancellation target is not available from this role/account metadata.")

    # -- EXECUTE TASK ----------------------------------------------------------
    elif task_view == "Execute Task":
        st.header("Execute Task On-Demand")
        st.caption("Select and manually trigger a task. Ensure dependencies are met before running.")
        if not admin_actions_enabled():
            st.info("Read-only mode is active. Enable Admin actions in Settings before executing tasks.")
        st.caption("Admin action audit table deployment is managed by `snowflake/OVERWATCH_MART_SETUP.sql`.")
        exec_context = _current_execution_context(session)
        st.caption(
            "Execution context: "
            f"user `{exec_context.get('snowflake_user') or 'unknown'}` | "
            f"role `{exec_context.get('snowflake_role') or 'unknown'}` | "
            f"warehouse `{exec_context.get('snowflake_warehouse') or 'none'}`"
        )

        tl = st.session_state.get("tg_list", pd.DataFrame())
        if tl.empty:
            st.warning("Load task data from the Task History workflow first.")
        else:
            task_names = tl["NAME"].unique().tolist() if "NAME" in tl.columns else []
            selected   = st.selectbox("Select task", task_names, key="exec_task_sel")

            if selected:
                row = tl[tl["NAME"] == selected].iloc[0] if len(tl[tl["NAME"] == selected]) else None
                if row is not None:
                    db   = row.get("DATABASE_NAME", "")
                    sch  = row.get("SCHEMA_NAME", "")
                    full = _qualified_name(db, sch, selected)
                    st.info(f"Task: `{full}` | State: {row.get('STATE','N/A')} | Schedule: {row.get('SCHEDULE','N/A')}")
                    with st.expander("Read-only pre-flight checks before executing this task"):
                        st.code(build_admin_preflight_sql(row), language="sql")
                    st.warning("This runs the task immediately regardless of schedule.")

                    exec_confirmed = st.text_input(
                        "Type EXECUTE to enable task run",
                        key=f"exec_task_confirm_{selected}",
                    ) == "EXECUTE"

                    if st.button(
                        f"Execute {selected}",
                        type="primary",
                        key="exec_task_btn",
                        disabled=admin_button_disabled(not exec_confirmed),
                    ):
                        sql_text = f"EXECUTE TASK {full}"
                        try:
                            session.sql(sql_text).collect()
                            _log_admin_action(
                                session,
                                "EXECUTE TASK",
                                full,
                                sql_text,
                                "SUCCESS",
                                "Task triggered.",
                                confirmation_text="EXECUTE",
                                control_context="mode=Execute Task On-Demand",
                            )
                            st.success(f"Task `{full}` triggered.")
                        except Exception as e:
                            message = format_snowflake_error(e)
                            _log_admin_action(
                                session,
                                "EXECUTE TASK",
                                full,
                                sql_text,
                                "FAILED",
                                message,
                                confirmation_text="EXECUTE",
                                control_context="mode=Execute Task On-Demand",
                            )
                            st.error(f"Execution failed: {message}")
