# sections/query_analysis.py - Bottlenecks, plan steps, pattern degradation, AI diagnosis
import re

import pandas as pd
import streamlit as st
from sections.shell_helpers import render_shell_snapshot
from utils import (
    defer_source_note,
    day_window_selectbox,
    get_session_for_action, run_query, sql_literal,
    format_credits, download_csv,
    render_query_drilldown, build_metered_credit_cte, get_active_company, get_global_filter_clause,
    render_priority_dataframe,
    filter_existing_columns, format_snowflake_error,
    build_mart_query_bottleneck_sql, build_mart_query_degradation_sql,
    render_load_status,
    render_workflow_selector,
    CortexRateLimitError,
    run_cortex_completion,
    safe_float,
)
from config import THRESHOLDS


QUERY_ANALYSIS_PANES = (
    "Bottlenecks",
    "Pattern Degradation",
    "Root-Cause Brief",
    "Detailed Diagnosis",
    "Plan Steps",
    "History Search",
    "AI Diagnosis",
)
QUERY_ANALYSIS_EMBEDDED_LENS_KEY = "query_analysis_embedded_single_lens"
QUERY_ANALYSIS_PANE_ALIASES = {
    "Query Search": "History Search",
    "Query Search & History": "History Search",
    "History search": "History Search",
    "Top SQL": "Bottlenecks",
    "Patterns": "Pattern Degradation",
    "User / Role": "History Search",
    "Warehouse": "History Search",
}


def _coerce_query_analysis_view(value: object) -> str:
    text = str(value or "").strip()
    canonical = QUERY_ANALYSIS_PANE_ALIASES.get(text, text)
    if canonical in QUERY_ANALYSIS_PANES:
        return canonical
    return QUERY_ANALYSIS_PANES[0]


def _annotate_bottleneck_routes(df):
    if df is None or getattr(df, "empty", True):
        return df

    def _signal(row):
        if safe_float(row.get("QUEUED_SEC")) > 30:
            return "Warehouse Queue Pressure"
        if safe_float(row.get("REMOTE_SPILL_GB")) > THRESHOLDS["spill_warning_gb"]:
            return "Remote Spill"
        if safe_float(row.get("PARTITION_PCT")) > THRESHOLDS["partition_scan_warning_pct"]:
            return "Full/High Partition Scan"
        return "Slow Query"

    def _workflow(signal):
        if signal in ("Warehouse Queue Pressure", "Remote Spill"):
            return "Warehouse health"
        if signal == "Full/High Partition Scan":
            return "Change & drift"
        return "Query workbench"

    def _action(signal):
        if signal == "Warehouse Queue Pressure":
            return "Check concurrent load, queue trend, warehouse size/clusters, and task schedule overlap before resizing."
        if signal == "Remote Spill":
            return "Open operator stats, identify spill-heavy joins/sorts, and validate warehouse memory pressure before rerun."
        if signal == "Full/High Partition Scan":
            return "Inspect pruning, clustering/search optimization fit, recent object growth, and query predicates."
        return "Review query text, elapsed trend, warehouse context, and owner before tuning or escalation."

    routed = df.copy()
    routed["PRIMARY_SIGNAL"] = routed.apply(_signal, axis=1)
    routed["NEXT_WORKFLOW"] = routed["PRIMARY_SIGNAL"].apply(_workflow)
    routed["NEXT_ACTION"] = routed["PRIMARY_SIGNAL"].apply(_action)
    return routed


def _annotate_degradation_routes(df):
    if df is None or getattr(df, "empty", True):
        return df
    routed = df.copy()
    routed["PRIMARY_SIGNAL"] = "Query Pattern Regression"
    routed["NEXT_WORKFLOW"] = "Query workbench"
    routed["NEXT_ACTION"] = (
        "Compare this signature to the release/change window, inspect plans for representative query IDs, "
        "and confirm whether data volume or logic changed."
    )
    return routed


def _row_value(row: dict, *names: str, default=""):
    for name in names:
        if name in row:
            value = row.get(name)
            try:
                if pd.isna(value):
                    continue
            except Exception:
                pass
            return value
        upper_name = name.upper()
        if upper_name in row:
            value = row.get(upper_name)
            try:
                if pd.isna(value):
                    continue
            except Exception:
                pass
            return value
    return default


def _safe_query_key(query_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(query_id or "query")).strip("_")[:90] or "query"


def _build_ai_query_history_sql(query_id: str, exprs: dict[str, str]) -> str:
    return f"""
        SELECT
            q.query_id,
            q.user_name,
            q.role_name,
            q.warehouse_name,
            {exprs["wh_size_expr"]},
            q.database_name,
            q.schema_name,
            q.execution_status,
            q.start_time,
            q.total_elapsed_time/1000 AS elapsed_sec,
            q.compilation_time/1000 AS compile_sec,
            q.execution_time/1000 AS exec_sec,
            {exprs["queued_expr"]},
            {exprs["blocked_expr"]},
            {exprs["gb_expr"]},
            {exprs["spill_expr"]},
            {exprs["partition_expr"]},
            {exprs["rows_expr"]},
            COALESCE(q.error_message, '') AS error_message,
            SUBSTR(q.query_text, 1, 12000) AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.query_id = {sql_literal(query_id, 200)}
        LIMIT 1
    """


def _build_ai_operator_stats_sql(query_id: str) -> str:
    return f"""
        SELECT
            OPERATOR_ID,
            OPERATOR_TYPE,
            PARENT_OPERATORS,
            OPERATOR_STATISTICS,
            EXECUTION_TIME_BREAKDOWN
        FROM TABLE(GET_QUERY_OPERATOR_STATS({sql_literal(query_id, 200)}))
        ORDER BY OPERATOR_ID
        LIMIT 80
    """


def _query_evidence_from_history(df) -> dict:
    if df is None or getattr(df, "empty", True):
        return {}
    row = df.iloc[0].to_dict()
    return {
        "QUERY_ID": str(_row_value(row, "QUERY_ID")),
        "USER_NAME": str(_row_value(row, "USER_NAME")),
        "ROLE_NAME": str(_row_value(row, "ROLE_NAME")),
        "WAREHOUSE_NAME": str(_row_value(row, "WAREHOUSE_NAME")),
        "WAREHOUSE_SIZE": str(_row_value(row, "WAREHOUSE_SIZE")),
        "DATABASE_NAME": str(_row_value(row, "DATABASE_NAME")),
        "SCHEMA_NAME": str(_row_value(row, "SCHEMA_NAME")),
        "EXECUTION_STATUS": str(_row_value(row, "EXECUTION_STATUS")),
        "START_TIME": str(_row_value(row, "START_TIME")),
        "ELAPSED_SEC": safe_float(_row_value(row, "ELAPSED_SEC")),
        "COMPILE_SEC": safe_float(_row_value(row, "COMPILE_SEC")),
        "EXEC_SEC": safe_float(_row_value(row, "EXEC_SEC")),
        "QUEUED_SEC": safe_float(_row_value(row, "QUEUED_SEC")),
        "BLOCKED_SEC": safe_float(_row_value(row, "BLOCKED_SEC")),
        "BYTES_SCANNED_GB": safe_float(_row_value(row, "GB_SCANNED")),
        "REMOTE_SPILL_GB": safe_float(_row_value(row, "REMOTE_SPILL_GB")),
        "PARTITION_PCT": safe_float(_row_value(row, "PARTITION_PCT")),
        "ROWS_PRODUCED": safe_float(_row_value(row, "ROWS_PRODUCED")),
        "ERROR_MESSAGE": str(_row_value(row, "ERROR_MESSAGE")),
        "QUERY_TEXT": str(_row_value(row, "QUERY_TEXT"))[:12000],
    }


def _extract_query_objects(query_text: str) -> list[str]:
    objects = []
    pattern = re.compile(
        r"\b(?:FROM|JOIN|UPDATE|INTO|MERGE\s+INTO|DELETE\s+FROM)\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*){0,2})",
        re.IGNORECASE,
    )
    for match in pattern.finditer(str(query_text or "")):
        obj = match.group(1).strip().strip('"')
        if obj and obj.upper() not in {"SELECT", "TABLE", "LATERAL"} and obj not in objects:
            objects.append(obj)
    return objects[:8]


def _query_uses_function_wrapped_predicate(query_text: str) -> bool:
    text = re.sub(r"\s+", " ", str(query_text or "")).upper()
    where_match = re.search(r"\bWHERE\b(.+?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bQUALIFY\b|\bLIMIT\b|$)", text)
    if not where_match:
        return False
    where_text = where_match.group(1)
    return bool(re.search(r"\b(?:TO_DATE|DATE_TRUNC|CAST|UPPER|LOWER|COALESCE|NVL)\s*\(", where_text))


def _extract_function_wrapped_predicate_columns(query_text: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(query_text or ""))
    where_match = re.search(r"\bWHERE\b(.+?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bQUALIFY\b|\bLIMIT\b|$)", text, re.IGNORECASE)
    if not where_match:
        return []
    where_text = where_match.group(1)
    columns: list[str] = []
    patterns = (
        r"\b(?:TO_DATE|CAST|UPPER|LOWER|COALESCE|NVL)\s*\(\s*([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
        r"\bDATE_TRUNC\s*\(\s*[^,]+,\s*([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, where_text, re.IGNORECASE):
            column = match.group(1).strip()
            if column and column.upper() not in {"SELECT", "CURRENT_DATE", "CURRENT_TIMESTAMP"} and column not in columns:
                columns.append(column)
    return columns[:4]


def _extract_text_search_columns(query_text: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(query_text or ""))
    columns: list[str] = []
    for match in re.finditer(
        r"([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)\s+(?:ILIKE|LIKE)\s+['\"]%",
        text,
        re.IGNORECASE,
    ):
        column = match.group(1).strip()
        if column and column not in columns:
            columns.append(column)
    return columns[:4]


def _add_query_candidate(candidates: list[dict], signal: str, evidence: str, recommendation: str, verify: str) -> None:
    candidates.append({
        "PRIORITY": len(candidates) + 1,
        "SIGNAL": signal,
        "EVIDENCE": evidence,
        "SPECIFIC_RECOMMENDATION": recommendation,
        "VERIFY_AFTER_FIX": verify,
    })


def _build_query_optimization_candidates(query_text: str, evidence: dict | None = None) -> list[dict]:
    evidence = evidence or {}
    text = str(query_text or "")
    upper = text.upper()
    objects = _extract_query_objects(text)
    object_hint = objects[0] if objects else "<target_table>"
    candidates: list[dict] = []

    queued_sec = safe_float(evidence.get("QUEUED_SEC"))
    blocked_sec = safe_float(evidence.get("BLOCKED_SEC") or evidence.get("BLOCKED_SECONDS"))
    remote_spill_gb = safe_float(evidence.get("REMOTE_SPILL_GB"))
    partition_pct = safe_float(evidence.get("PARTITION_PCT"))
    gb_scanned = safe_float(evidence.get("BYTES_SCANNED_GB"))
    rows_produced = safe_float(evidence.get("ROWS_PRODUCED"))
    elapsed_sec = safe_float(evidence.get("ELAPSED_SEC"))
    query_id = str(evidence.get("QUERY_ID") or "").strip()
    observed = str(evidence.get("OPERATOR_NOTES") or "")

    if blocked_sec >= 5 or re.search(r"\b(lock|blocked|blocking|contention|overlap|overlapping)\b", observed, re.IGNORECASE):
        observed_evidence = f"Transaction blocked time is {blocked_sec:,.1f}s."
        if blocked_sec < 5:
            observed_evidence = "Observed symptoms mention lock/contention/task overlap."
        _add_query_candidate(
            candidates,
            "Lock/write contention",
            observed_evidence,
            f"Open Contention Center for {query_id or '<query_id>'}; run active locks, identify the blocker and shared target object, then serialize final writes through a single publish task or batch the DML by date/hash/batch key. Do not resize compute solely on blocked seconds.",
            "Check QUERY_HISTORY TRANSACTION_BLOCKED_TIME and LOCK_WAIT_HISTORY wait seconds return to zero for the query pattern; confirm task overlap is gone in TASK_HISTORY.",
        )

    if queued_sec >= 30:
        _add_query_candidate(
            candidates,
            "Warehouse queue pressure",
            f"Queued overload is {queued_sec:,.1f}s.",
            "Separate compute contention from SQL shape first: open Live triage/Cost & Contract, compare active queries on the same warehouse, and check WAREHOUSE_LOAD_HISTORY before resizing or rewriting SQL.",
            "Check QUEUED_OVERLOAD_TIME drops for the rerun and p95 queue stays below the local SLA.",
        )
    if remote_spill_gb >= max(THRESHOLDS["spill_warning_gb"], 1):
        _add_query_candidate(
            candidates,
            "Remote spill",
            f"Remote spill is {remote_spill_gb:,.2f} GB.",
            f"Use GET_QUERY_OPERATOR_STATS for {query_id or '<query_id>'} and fix the spill-heavy JOIN, SORT, or AGGREGATE step by pre-filtering {object_hint}, reducing projected columns, or pre-aggregating before the wide join. Test warehouse memory only after SQL-shape telemetry is captured.",
            "Rerun and compare BYTES_SPILLED_TO_REMOTE_STORAGE plus operator-level spill in GET_QUERY_OPERATOR_STATS.",
        )
    if partition_pct >= THRESHOLDS["partition_scan_warning_pct"]:
        _add_query_candidate(
            candidates,
            "Full/high partition scan",
            f"Partition scan is {partition_pct:,.1f}%.",
            f"Check pruning on {object_hint}; rewrite date/range predicates so the column is not wrapped in a function, and evaluate CLUSTER BY or Search Optimization only for the specific predicate columns used by this SQL.",
            f"Run SYSTEM$CLUSTERING_INFORMATION('{object_hint}') where applicable and compare PARTITIONS_SCANNED / PARTITIONS_TOTAL on rerun.",
        )
    if gb_scanned >= 25 and (rows_produced <= 100000 or rows_produced / max(gb_scanned, 1) < 5000):
        _add_query_candidate(
            candidates,
            "High scan with low output",
            f"Scanned {gb_scanned:,.1f} GB for {rows_produced:,.0f} output rows.",
            "Push filters into the earliest table scans, replace wide projections with required columns, and materialize a narrow candidate set before joins or window functions.",
            "Check BYTES_SCANNED and ROWS_PRODUCED/GB improve for the same query pattern.",
        )
    if re.search(r"\bSELECT\s+\*", upper):
        _add_query_candidate(
            candidates,
            "Wide SELECT star",
            "SQL includes SELECT *.",
            "Replace SELECT * with the columns consumed downstream. If this feeds a BI/export workflow, create a narrow view for the consumer instead of scanning unused columns.",
            "Compare BYTES_SCANNED and compilation/execution time before and after the projection change.",
        )
    if re.search(r"\b(?:ILIKE|LIKE)\s+['\"]%", upper):
        _add_query_candidate(
            candidates,
            "Leading wildcard text search",
            "SQL has LIKE/ILIKE with a leading wildcard.",
            f"If this is a selective text lookup on {object_hint}, test Search Optimization on the searched text column; otherwise route to a staged search table or normalized token column instead of scanning every micro-partition.",
            "Check search selectivity, Search Optimization maintenance cost, and BYTES_SCANNED on the same predicate.",
        )
    if _query_uses_function_wrapped_predicate(text):
        _add_query_candidate(
            candidates,
            "Function-wrapped predicate",
            "WHERE clause wraps a filtered column with a function.",
            "Move functions to the constant side or persist a normalized/date bucket column so Snowflake can prune micro-partitions on the raw filtered column.",
            "Compare PARTITIONS_SCANNED and elapsed time for the rewritten predicate.",
        )
    join_count = len(re.findall(r"\bJOIN\b", upper))
    if join_count >= 4:
        _add_query_candidate(
            candidates,
            "Large join graph",
            f"SQL has {join_count} JOIN clauses.",
            "Identify the largest build/probe sides in operator stats, filter each base table before joining, and pre-aggregate many-to-one dimensions before the wide fact join.",
            "Check join operator rows, spill, and elapsed time drop in GET_QUERY_OPERATOR_STATS.",
        )
    if re.search(r"\bORDER\s+BY\b", upper) and not re.search(r"\bLIMIT\b", upper):
        _add_query_candidate(
            candidates,
            "Unbounded sort",
            "SQL sorts without a LIMIT.",
            "If this is an inspection/export query, add a LIMIT or sort only the final reduced result. If ordering is required for downstream logic, materialize the filtered result first.",
            "Check sort operator time and remote spill in operator stats.",
        )
    if re.search(r"\bCOUNT\s*\(\s*DISTINCT\b|\bSELECT\s+DISTINCT\b", upper):
        _add_query_candidate(
            candidates,
            "Distinct-heavy aggregation",
            "SQL uses DISTINCT or COUNT(DISTINCT).",
            "Pre-aggregate at the business grain before joining, remove duplicate-generating joins, or use APPROX_COUNT_DISTINCT only when the business question allows approximation.",
            "Check aggregate operator time, rows before aggregate, and output accuracy.",
        )
    if re.search(r"\b(MERGE|UPDATE|DELETE)\b", upper):
        _add_query_candidate(
            candidates,
            "Write-path contention risk",
            "SQL is DML that can lock tables or overlap with task windows.",
            "Open Contention Center before rerun; batch by partition/date key, shorten transaction scope, and reschedule overlapping tasks that write the same target object.",
            "Check LOCK_WAIT_HISTORY, task overlap, and rerun duration after the schedule or batching change.",
        )
    if elapsed_sec >= 300 and not candidates:
        _add_query_candidate(
            candidates,
            "Long runtime needs operator telemetry",
            f"Elapsed time is {elapsed_sec:,.1f}s but no obvious SQL-shape signal was detected.",
            "Load GET_QUERY_OPERATOR_STATS and classify the dominant operator before changing SQL, clustering, or warehouse size.",
            "Check the dominant operator's execution-time share falls on rerun.",
        )
    return candidates[:8]


def _build_query_diagnosis_action_contract(
    candidates: list[dict],
    evidence: dict | None = None,
    query_text: str = "",
) -> list[dict]:
    evidence = evidence or {}
    query_id = str(evidence.get("QUERY_ID") or "").strip() or "<query_id>"
    warehouse = str(evidence.get("WAREHOUSE_NAME") or "").strip() or "<warehouse>"
    objects = _extract_query_objects(query_text)
    object_hint = objects[0] if objects else str(evidence.get("OBJECT_HINTS") or "").split(",")[0].strip()
    object_hint = object_hint or "<target_object>"
    function_columns = _extract_function_wrapped_predicate_columns(query_text)
    text_columns = _extract_text_search_columns(query_text)
    function_hint = ", ".join(function_columns) if function_columns else "the wrapped filter column"
    text_hint = ", ".join(text_columns) if text_columns else "the searched text column"

    contract: list[dict] = []
    for item in candidates or []:
        signal = str(item.get("SIGNAL") or "").strip()
        verify = str(item.get("VERIFY_AFTER_FIX") or "").strip()
        evidence_line = str(item.get("EVIDENCE") or "").strip()

        root_cause = "SQL shape"
        action_decision = "Tune after telemetry review"
        first_move = f"Load GET_QUERY_OPERATOR_STATS for {query_id} and identify the dominant operator."
        exact_change = str(item.get("SPECIFIC_RECOMMENDATION") or "").strip()
        do_not_do = "Do not change warehouse size or rewrite SQL until the dominant telemetry is named."
        owner_handoff = "Query route / DBA"

        if signal == "Lock/write contention":
            root_cause = "Concurrency and write lock contention"
            action_decision = "Route to Contention Center before SQL tuning"
            first_move = (
                f"Open Contention Center for {query_id}; identify blocker transaction, blocked query, "
                f"task overlap, and shared target object."
            )
            exact_change = (
                "Serialize final writes, shorten the transaction, or batch MERGE/UPDATE/DELETE work by "
                "date/hash/key after blocker telemetry is confirmed."
            )
            do_not_do = "Do not resize the warehouse or rewrite joins while blocked time is the primary wait."
            owner_handoff = "DBA plus task/job route"
        elif signal == "Warehouse queue pressure":
            root_cause = "Warehouse concurrency pressure"
            action_decision = "Route to Cost & Contract"
            first_move = (
                f"Check WAREHOUSE_LOAD_HISTORY and active queries on {warehouse}; compare queue time to "
                "concurrent task/job windows."
            )
            exact_change = (
                "Stagger overlapping jobs, move one workload class to separate compute, or evaluate multi-cluster/"
                "resize only after queue telemetry shows compute contention."
            )
            do_not_do = "Do not rewrite SQL as the first fix when queued overload is the dominant signal."
            owner_handoff = "Warehouse route / scheduler route"
        elif signal == "Remote spill":
            root_cause = "Memory pressure inside query operators"
            action_decision = "Inspect operator stats before rerun"
            first_move = f"Run GET_QUERY_OPERATOR_STATS for {query_id}; sort JOIN, SORT, and AGGREGATE operators by spill/time."
            exact_change = (
                f"Pre-filter {object_hint}, project only required columns, and pre-aggregate before the widest join; "
                "test warehouse memory only after the spill-heavy operator is named."
            )
            do_not_do = "Do not blindly resize without preserving the before/after spill operator telemetry."
            owner_handoff = "Query route / DBA"
        elif signal == "Full/high partition scan":
            root_cause = "Micro-partition pruning gap"
            action_decision = "Fix pruning telemetry"
            first_move = f"Check PARTITIONS_SCANNED/TOTAL and SYSTEM$CLUSTERING_INFORMATION for {object_hint}."
            exact_change = (
                f"Rewrite predicates on {function_hint} so Snowflake can prune {object_hint}; evaluate CLUSTER BY "
                "or Search Optimization only for columns used by this query."
            )
            do_not_do = "Do not add broad clustering/search optimization without proving the predicate columns and maintenance cost."
            owner_handoff = "DBA plus data route"
        elif signal == "High scan with low output":
            root_cause = "Late filtering or over-wide scan"
            action_decision = "Push selectivity earlier"
            first_move = f"Identify the base scan on {object_hint} and confirm filters are applied before joins/windows."
            exact_change = (
                "Push filters into the earliest scan, materialize a narrow candidate set, and remove unused columns "
                "before high-cardinality joins."
            )
            do_not_do = "Do not optimize downstream joins before proving scan volume drops."
            owner_handoff = "Query route"
        elif signal == "Wide SELECT star":
            root_cause = "Projection over-scan"
            action_decision = "Narrow projection"
            first_move = "List the downstream columns actually consumed by the report/job."
            exact_change = "Replace SELECT * with required columns or create a narrow view for the consumer."
            do_not_do = "Do not keep SELECT * in scheduled or BI extracts unless column drift is the explicit requirement."
            owner_handoff = "Query route / consuming team"
        elif signal == "Leading wildcard text search":
            root_cause = "Non-sargable text scan"
            action_decision = "Redesign text lookup"
            first_move = f"Confirm selectivity and business need for leading-wildcard search on {text_hint}."
            exact_change = (
                f"For {text_hint}, test Search Optimization only if the predicate is selective; otherwise create a "
                "normalized token/search table."
            )
            do_not_do = "Do not enable Search Optimization across a full table without selectivity and cost telemetry."
            owner_handoff = "DBA plus application route"
        elif signal == "Function-wrapped predicate":
            root_cause = "Predicate disables pruning"
            action_decision = "Rewrite predicate"
            first_move = f"Identify the wrapped filter column: {function_hint}."
            exact_change = (
                f"Move conversion functions off {function_hint} or persist a normalized/date bucket column and filter "
                "that column directly."
            )
            do_not_do = "Do not tune warehouse size before proving partitions scanned drop after the predicate rewrite."
            owner_handoff = "Query route / data model route"
        elif signal == "Large join graph":
            root_cause = "Join shape and cardinality"
            action_decision = "Reduce join inputs"
            first_move = f"Use GET_QUERY_OPERATOR_STATS for {query_id} to find the largest build/probe sides."
            exact_change = (
                "Filter each base table before joining, pre-aggregate dimensions/facts to the required grain, "
                "and remove duplicate-generating joins."
            )
            do_not_do = "Do not reorder joins by intuition without operator row counts."
            owner_handoff = "Query route / data model route"
        elif signal == "Unbounded sort":
            root_cause = "Sort over unreduced result"
            action_decision = "Reduce before sort"
            first_move = "Confirm whether ORDER BY is for inspection/export or required business logic."
            exact_change = "Add LIMIT for inspection, or sort only after filtering/materializing the reduced result."
            do_not_do = "Do not sort wide intermediate results if only the final reduced rowset needs ordering."
            owner_handoff = "Query route"
        elif signal == "Distinct-heavy aggregation":
            root_cause = "High-cardinality aggregation"
            action_decision = "Pre-aggregate at business grain"
            first_move = "Find duplicate-generating joins and rows entering the aggregate operator."
            exact_change = (
                "Pre-aggregate before joins or use APPROX_COUNT_DISTINCT only when the business result allows "
                "approximation."
            )
            do_not_do = "Do not replace exact counts with approximations without business review."
            owner_handoff = "Query route / business route"
        elif signal == "Write-path contention risk":
            root_cause = "DML lock and task overlap risk"
            action_decision = "Check write schedule before rerun"
            first_move = f"Open Contention Center and TASK_HISTORY for the target object used by {query_id}."
            exact_change = (
                "Batch DML by partition/date/key, shorten transaction scope, and reschedule overlapping tasks "
                "that write the same target object."
            )
            do_not_do = "Do not rerun overlapping DML until the lock window and owning job are known."
            owner_handoff = "DBA plus scheduler route"
        elif signal == "Long runtime needs operator telemetry":
            root_cause = "Insufficient telemetry"
            action_decision = "Load operator telemetry"
            first_move = f"Load GET_QUERY_OPERATOR_STATS for {query_id} before choosing SQL, clustering, or compute changes."
            exact_change = "Classify dominant operator first; then apply only the matching tuning path."
            do_not_do = "Do not ask Cortex for a final fix without query ID metrics or operator notes."
            owner_handoff = "DBA"

        contract.append({
            "PRIORITY": item.get("PRIORITY", len(contract) + 1),
            "SIGNAL": signal,
            "ROOT_CAUSE_CLASS": root_cause,
            "ACTION_DECISION": action_decision,
            "FIRST_OPERATOR_MOVE": first_move,
            "EXACT_CHANGE": exact_change,
            "DO_NOT_DO": do_not_do,
            "VERIFY_AFTER_FIX": verify,
            "OWNER_HANDOFF": owner_handoff,
            "EVIDENCE": evidence_line,
        })
    return contract[:8]


def _summarize_operator_stats(df, *, limit: int = 12) -> str:
    if df is None or getattr(df, "empty", True):
        return "Operator stats available after refresh."
    rows = []
    for row in df.head(limit).to_dict("records"):
        rows.append(
            "- "
            f"operator={_row_value(row, 'OPERATOR_TYPE', default='unknown')}; "
            f"id={_row_value(row, 'OPERATOR_ID', default='')}; "
            f"stats={str(_row_value(row, 'OPERATOR_STATISTICS', default=''))[:700]}; "
            f"time={str(_row_value(row, 'EXECUTION_TIME_BREAKDOWN', default=''))[:500]}"
        )
    return "\n".join(rows)


def _format_ai_evidence_for_prompt(evidence: dict) -> str:
    if not evidence:
        return "No ACCOUNT_USAGE telemetry loaded. Use SQL text and operator notes only."
    ordered_keys = (
        "QUERY_ID", "USER_NAME", "ROLE_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
        "DATABASE_NAME", "SCHEMA_NAME", "EXECUTION_STATUS", "START_TIME",
        "ELAPSED_SEC", "COMPILE_SEC", "EXEC_SEC", "QUEUED_SEC", "BLOCKED_SEC",
        "BYTES_SCANNED_GB", "REMOTE_SPILL_GB", "PARTITION_PCT", "ROWS_PRODUCED",
        "ERROR_MESSAGE", "OBJECT_HINTS", "OPERATOR_NOTES",
    )
    lines = []
    for key in ordered_keys:
        value = evidence.get(key)
        if value not in (None, ""):
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "No structured telemetry loaded."


def _format_candidates_for_prompt(candidates: list[dict]) -> str:
    if not candidates:
        return "No deterministic candidate was detected; ask for query ID telemetry before making tuning claims."
    return "\n".join(
        (
            f"{item['PRIORITY']}. {item['SIGNAL']} | Telemetry: {item['EVIDENCE']} | "
            f"Recommendation: {item['SPECIFIC_RECOMMENDATION']} | Status check: {item['VERIFY_AFTER_FIX']}"
        )
        for item in candidates
    )


def _format_action_contract_for_prompt(action_contract: list[dict]) -> str:
    if not action_contract:
        return "No operator action contract is available yet."
    return "\n".join(
        (
            f"{item['PRIORITY']}. {item['SIGNAL']} | Decision: {item['ACTION_DECISION']} | "
            f"Root cause: {item['ROOT_CAUSE_CLASS']} | First move: {item['FIRST_OPERATOR_MOVE']} | "
            f"Exact change: {item['EXACT_CHANGE']} | Do not do: {item['DO_NOT_DO']} | "
            f"Status check: {item['VERIFY_AFTER_FIX']}"
        )
        for item in action_contract
    )


def _build_ai_query_diagnosis_prompt(
    query_text: str,
    evidence: dict,
    candidates: list[dict],
    operator_summary: str,
) -> str:
    action_contract = _build_query_diagnosis_action_contract(candidates, evidence, query_text)
    return f"""You are OVERWATCH's Snowflake DBA query optimization model.

Your job is to produce specific, telemetry-bound optimization recommendations for one Snowflake query.

Hard rules:
- Every recommendation must cite exact telemetry from the query text, ACCOUNT_USAGE metrics, operator stats, or deterministic candidates below.
- Use the Query Investigation action contract below as the priority order and do not skip a higher-priority contention or queueing signal.
- Do not recommend indexes. Snowflake does not use traditional indexes for this tuning path.
- Do not say generic phrases such as "optimize the query", "review joins", or "improve performance" unless you name the exact join/filter/sort/aggregate telemetry.
- Separate warehouse contention from SQL-shape problems. If QUEUED_SEC is high, say that SQL tuning may not fix the bottleneck.
- If BLOCKED_SEC or TRANSACTION_BLOCKED_TIME is present, prioritize lock/write contention fixes before SQL rewrites or warehouse resize.
- Include Snowflake-specific syntax only when it fits the telemetry, such as GET_QUERY_OPERATOR_STATS, SYSTEM$CLUSTERING_INFORMATION, CLUSTER BY, Search Optimization, QUALIFY, or a rewritten predicate.
- Do not invent table names, column names, warehouses, routes, query IDs, or tasks that are not present in the SQL text or telemetry; say "unknown" and request the missing telemetry.
- If telemetry is missing, say what to load next instead of guessing.

Return this exact structure:
1. DBA verdict: one sentence.
2. Priority table with columns: Priority | Telemetry | Root cause | Action decision | Exact change | Status check.
3. Safe rollout notes: risk, team handoff, rollback, and status check.

Structured telemetry:
{_format_ai_evidence_for_prompt(evidence)}

Deterministic candidates:
{_format_candidates_for_prompt(candidates)}

Query Investigation action contract:
{_format_action_contract_for_prompt(action_contract)}

Operator stats sample:
{operator_summary}

SQL:
```sql
{str(query_text or '')[:6000]}
```"""


def _render_ai_evidence_snapshot(evidence: dict) -> None:
    if not evidence:
        render_shell_snapshot((
            ("Telemetry", "Paste SQL"),
            ("Query ID", "Optional"),
            ("Operator Stats", "Optional"),
            ("Cortex", "Details available when needed"),
        ))
        return
    render_shell_snapshot((
        ("Elapsed", f"{safe_float(evidence.get('ELAPSED_SEC')):,.1f}s"),
        ("Queue", f"{safe_float(evidence.get('QUEUED_SEC')):,.1f}s"),
        ("Blocked", f"{safe_float(evidence.get('BLOCKED_SEC')):,.1f}s"),
        ("Remote Spill", f"{safe_float(evidence.get('REMOTE_SPILL_GB')):,.2f} GB"),
    ))


def render():
    session = None
    company = get_active_company()
    qh_exprs = None

    def _action_session(action: str = "load query investigation telemetry"):
        nonlocal session
        if session is None:
            session = get_session_for_action(
                action,
                surface="Workload Operations / Query Investigation",
                offline_note="Query Investigation controls remain available; load telemetry after the connection is ready.",
            )
        return session

    def _query_history_exprs() -> dict[str, str]:
        nonlocal qh_exprs
        if qh_exprs is not None:
            return qh_exprs
        action_session = _action_session("inspect query history columns")
        if action_session is None:
            qh_exprs = {
                "wh_size_expr": "NULL::VARCHAR AS warehouse_size",
                "queued_expr": "0::FLOAT AS queued_sec",
                "blocked_expr": "0::FLOAT AS blocked_sec",
                "gb_expr": "0::FLOAT AS gb_scanned",
                "spill_expr": "0::FLOAT AS remote_spill_gb",
                "partition_expr": "0::FLOAT AS partition_pct",
                "rows_expr": "0::NUMBER AS rows_produced",
            }
            return qh_exprs
        try:
            qh_cols = set(filter_existing_columns(
                action_session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                [
                    "WAREHOUSE_SIZE",
                    "QUEUED_OVERLOAD_TIME",
                    "BYTES_SCANNED",
                    "BYTES_SPILLED_TO_REMOTE_STORAGE",
                    "PARTITIONS_SCANNED",
                    "PARTITIONS_TOTAL",
                    "ROWS_PRODUCED",
                    "TRANSACTION_BLOCKED_TIME",
                ],
            ))
        except Exception:
            qh_cols = set()
        qh_exprs = {
            "wh_size_expr": "q.warehouse_size AS warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size",
            "queued_expr": "q.queued_overload_time/1000 AS queued_sec" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0::FLOAT AS queued_sec",
            "blocked_expr": (
                "q.transaction_blocked_time/1000 AS blocked_sec"
                if "TRANSACTION_BLOCKED_TIME" in qh_cols else "0::FLOAT AS blocked_sec"
            ),
            "gb_expr": "q.bytes_scanned/POWER(1024,3) AS gb_scanned" if "BYTES_SCANNED" in qh_cols else "0::FLOAT AS gb_scanned",
            "spill_expr": (
                "q.bytes_spilled_to_remote_storage/POWER(1024,3) AS remote_spill_gb"
                if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols else "0::FLOAT AS remote_spill_gb"
            ),
            "partition_expr": (
                "q.partitions_scanned * 100.0 / NULLIF(q.partitions_total,0) AS partition_pct"
                if {"PARTITIONS_SCANNED", "PARTITIONS_TOTAL"}.issubset(qh_cols)
                else "0::FLOAT AS partition_pct"
            ),
            "rows_expr": "q.rows_produced AS rows_produced" if "ROWS_PRODUCED" in qh_cols else "0::NUMBER AS rows_produced",
        }
        return qh_exprs

    if st.session_state.get(QUERY_ANALYSIS_EMBEDDED_LENS_KEY):
        active_view = _coerce_query_analysis_view(st.session_state.get("query_analysis_active_view"))
        st.session_state["query_analysis_active_view"] = active_view
    else:
        active_view = render_workflow_selector(
            "Query analysis view",
            "query_analysis_active_view",
            QUERY_ANALYSIS_PANES,
            columns=3,
            show_label=True,
        )

    # Bottlenecks
    if active_view == "Bottlenecks":
        st.subheader("Query Bottleneck Analysis")
        days = day_window_selectbox("Lookback", key="qa_days", default=7)
        qa_filters = get_global_filter_clause(
            date_col="q.start_time",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
            schema_col="q.schema_name",
        )

        if st.button("Load Bottlenecks", key="qa_load"):
            with render_load_status("Loading query bottlenecks", "Query bottlenecks ready"):
                try:
                    try:
                        df_qa = run_query(
                            build_mart_query_bottleneck_sql(
                                days_back=days,
                                min_elapsed_ms=THRESHOLDS["query_duration_alert_sec"] * 1000,
                                company=company,
                                extra_filter=qa_filters,
                            ),
                            ttl_key=f"query_analysis_bottlenecks_mart_{company}_{days}",
                            tier="historical",
                        )
                        st.session_state["qa_bottleneck_source"] = "Fast query detail summary"
                    except Exception:
                        exprs = _query_history_exprs()
                        wh_size_expr = exprs["wh_size_expr"]
                        queued_expr = exprs["queued_expr"]
                        gb_expr = exprs["gb_expr"]
                        spill_expr = exprs["spill_expr"]
                        partition_expr = exprs["partition_expr"]
                        rows_expr = exprs["rows_expr"]
                        df_qa = run_query(f"""
                WITH {build_metered_credit_cte(days_back=days, include_recent=True)}
                SELECT
                    q.query_id,
                    q.user_name,
                    q.warehouse_name,
                    {wh_size_expr},
                    q.execution_status,
                    q.start_time,
                    q.total_elapsed_time/1000             AS elapsed_sec,
                    q.compilation_time/1000               AS compile_sec,
                    q.execution_time/1000                 AS exec_sec,
                    {queued_expr},
                    {gb_expr},
                    {spill_expr},
                    {partition_expr},
                    {rows_expr},
                    COALESCE(pqc.metered_credits, 0)       AS metered_credits,
                    SUBSTR(q.query_text,1,500)             AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {qa_filters}
                  AND q.total_elapsed_time > {THRESHOLDS['query_duration_alert_sec'] * 1000}
                ORDER BY q.total_elapsed_time DESC
                LIMIT 500
                        """, ttl_key=f"query_analysis_bottlenecks_live_{company}_{days}", tier="standard")
                        st.session_state["qa_bottleneck_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                    st.session_state["qa_df_qa"] = _annotate_bottleneck_routes(df_qa)
                except Exception as e:
                    st.warning(f"Bottleneck data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("qa_df_qa") is not None and not st.session_state["qa_df_qa"].empty:
            df = st.session_state["qa_df_qa"]
            render_shell_snapshot((
                ("Slow Queries", f"{len(df):,}"),
                ("Avg Elapsed (s)", f"{df['ELAPSED_SEC'].mean():.1f}"),
                ("Total Remote Spill", f"{df['REMOTE_SPILL_GB'].sum():.1f} GB"),
                ("Total Credits", format_credits(df["METERED_CREDITS"].sum())),
            ))
            defer_source_note(st.session_state.get("qa_bottleneck_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

            # Flag high-impact queries
            flagged = df[
                (df["REMOTE_SPILL_GB"] > THRESHOLDS["spill_warning_gb"]) |
                (df["PARTITION_PCT"] > THRESHOLDS["partition_scan_warning_pct"]) |
                (df["QUEUED_SEC"] > 30)
            ]
            if not flagged.empty:
                st.warning(f"{len(flagged)} queries with spill, full-scan, or heavy queue time.")

            render_query_drilldown(df, key="qa_bottleneck")
            download_csv(df, "bottleneck_queries.csv")

    # Pattern degradation
    elif active_view == "Pattern Degradation":
        st.subheader("Query Pattern Degradation")
        st.caption("Compare query execution time this week vs prior week by query signature.")

        if st.button("Detect Degradation", key="deg_load"):
            with render_load_status("Detecting query degradation", "Query degradation scan ready"):
                try:
                    qa_filters = get_global_filter_clause(
                        date_col="q.start_time",
                        wh_col="q.warehouse_name",
                        user_col="q.user_name",
                        role_col="q.role_name",
                        db_col="q.database_name",
                        schema_col="q.schema_name",
                    )
                    try:
                        df_deg = run_query(
                            build_mart_query_degradation_sql(company=company, extra_filter=qa_filters),
                            ttl_key=f"query_analysis_degradation_mart_{company}",
                            tier="historical",
                        )
                        st.session_state["qa_degradation_source"] = "Fast query detail summary"
                    except Exception:
                        df_deg = run_query(f"""
                    WITH sig_recent AS (
                        SELECT SUBSTR(q.query_text,1,200) AS sig,
                               AVG(q.total_elapsed_time)/1000 AS avg_sec,
                               COUNT(*) AS cnt
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {qa_filters}
                        GROUP BY sig HAVING cnt >= 5
                    ),
                    sig_prior AS (
                        SELECT SUBSTR(q.query_text,1,200) AS sig,
                               AVG(q.total_elapsed_time)/1000 AS avg_sec,
                               COUNT(*) AS cnt
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('day',-14,CURRENT_TIMESTAMP())
                          AND q.start_time <  DATEADD('day',-7,CURRENT_TIMESTAMP())
                          AND q.warehouse_name IS NOT NULL
                          {qa_filters}
                        GROUP BY sig HAVING cnt >= 5
                    )
                    SELECT r.sig, r.avg_sec AS recent_sec, p.avg_sec AS prior_sec,
                           ROUND((r.avg_sec - p.avg_sec)/NULLIF(p.avg_sec,0)*100, 1) AS pct_change
                    FROM sig_recent r
                    JOIN sig_prior p ON r.sig = p.sig
                    WHERE r.avg_sec > p.avg_sec * 1.25
                      AND r.avg_sec > 5
                    ORDER BY pct_change DESC LIMIT 50
                        """, ttl_key=f"query_analysis_degradation_live_{company}", tier="standard")
                        st.session_state["qa_degradation_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                    st.session_state["qa_df_deg"] = _annotate_degradation_routes(df_deg)
                except Exception as e:
                    st.warning(f"Pattern degradation data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("qa_df_deg") is not None:
            df_d = st.session_state["qa_df_deg"]
            if not df_d.empty:
                st.warning(f"Warning: {len(df_d)} query patterns degraded >25% vs prior week.")
                defer_source_note(st.session_state.get("qa_degradation_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
                render_priority_dataframe(
                    df_d,
                    title="Query regressions to investigate first",
                    priority_columns=[
                        "SIG", "RECENT_SEC", "PRIOR_SEC", "PCT_CHANGE",
                        "PRIMARY_SIGNAL", "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["PCT_CHANGE", "RECENT_SEC"],
                    ascending=[False, False],
                    raw_label="All degraded query patterns",
                )
                download_csv(df_d, "pattern_degradation.csv")
            else:
                st.success("No significant query pattern degradation detected.")

    # Plan steps
    elif active_view == "Root-Cause Brief":
        import importlib

        root_cause = importlib.import_module("sections.query_investigation_root_cause")
        root_cause.render_root_cause_brief(session)

    elif active_view == "Detailed Diagnosis":
        import importlib

        detailed_diagnosis = importlib.import_module("sections.detailed_diagnosis")
        detailed_diagnosis.render()

    elif active_view == "Plan Steps":
        st.subheader("Query Plan Steps")
        st.caption("Enter a Query ID to inspect operator-level statistics.")

        qid_input = st.text_input("Query ID", key="planstep_qid")
        if qid_input and st.button("Load Plan Steps", key="planstep_load"):
            try:
                df_ops = run_query(
                    f"SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS({sql_literal(qid_input)}))",
                    ttl_key=f"query_analysis_plan_{company}_{qid_input}",
                    tier="standard",
                )
                render_priority_dataframe(
                    df_ops,
                    title="Operator steps to inspect first",
                    priority_columns=[
                        "OPERATOR_ID", "OPERATOR_TYPE", "PARENT_OPERATORS",
                        "OPERATOR_STATISTICS", "EXECUTION_TIME_BREAKDOWN",
                    ],
                    raw_label="All operator stats",
                )
                download_csv(df_ops, f"plan_steps_{qid_input}.csv")
            except Exception as e:
                st.warning(f"Operator stats unavailable: {format_snowflake_error(e)}")

    elif active_view == "History Search":
        import importlib

        query_search = importlib.import_module("sections.query_search")
        query_search.render()

    # AI diagnosis
    elif active_view == "AI Diagnosis":
        st.subheader("Query Investigation Assistant")
        st.caption("Use query telemetry and Cortex to generate Snowflake tuning recommendations.")

        qid_input = st.text_input("Query ID (optional)", key="ai_query_id")
        load_query_evidence = st.button(
            "Load Query Telemetry",
            key="ai_load_query_evidence",
            help="Loads ACCOUNT_USAGE query metrics and GET_QUERY_OPERATOR_STATS for this query ID.",
            disabled=not bool(qid_input),
            width="stretch",
        )
        if load_query_evidence:
            with render_load_status("Loading AI query telemetry", "AI query telemetry ready"):
                try:
                    if _action_session("load AI query telemetry") is None:
                        return
                    query_key = _safe_query_key(qid_input)
                    df_evidence = run_query(
                        _build_ai_query_history_sql(qid_input, _query_history_exprs()),
                        ttl_key=f"query_analysis_ai_evidence_{company}_{query_key}",
                        tier="standard",
                    )
                    evidence = _query_evidence_from_history(df_evidence)
                    if evidence:
                        st.session_state["ai_query_evidence"] = evidence
                        if evidence.get("QUERY_TEXT"):
                            st.session_state["ai_query_text"] = str(evidence["QUERY_TEXT"])
                    else:
                        st.session_state["ai_query_evidence"] = {}
                        st.warning("No ACCOUNT_USAGE query row found for that query ID.")
                    try:
                        operator_stats = run_query(
                            _build_ai_operator_stats_sql(qid_input),
                            ttl_key=f"query_analysis_ai_operator_stats_{company}_{query_key}",
                            tier="standard",
                        )
                        st.session_state["ai_query_operator_stats"] = operator_stats
                    except Exception as op_exc:
                        st.session_state["ai_query_operator_stats"] = pd.DataFrame()
                        st.info(f"Operator stats unavailable for this query ID: {format_snowflake_error(op_exc)}")
                except Exception as e:
                    st.session_state["ai_query_evidence"] = {}
                    st.warning(f"Query telemetry unavailable: {format_snowflake_error(e)}")

        evidence = dict(st.session_state.get("ai_query_evidence") or {})
        operator_stats = st.session_state.get("ai_query_operator_stats")
        _render_ai_evidence_snapshot(evidence)

        query_text = st.text_area("SQL to diagnose", height=220, key="ai_query_text")
        with st.expander("Optional diagnosis context", expanded=False):
            wh_ctx = st.text_input(
                "Warehouse override",
                value=str(evidence.get("WAREHOUSE_NAME") or ""),
                key="ai_wh_ctx",
            )
            object_ctx = st.text_input(
                "Known objects or hot tables",
                key="ai_object_ctx",
                help="Example: PROD_DB.CORE.FACT_POLICY, STAGE_DB.RAW.CLAIMS",
            )
            observed_ctx = st.text_area(
                "Observed symptoms",
                key="ai_observed_ctx",
                height=90,
                help="Queue, spill, lock waits, task overlap, SLA miss, release window, or business owner notes.",
            )
        if wh_ctx:
            evidence["WAREHOUSE_NAME"] = wh_ctx
        if object_ctx:
            evidence["OBJECT_HINTS"] = object_ctx
        if observed_ctx:
            evidence["OPERATOR_NOTES"] = observed_ctx[:1200]

        candidates = _build_query_optimization_candidates(query_text, evidence) if query_text else []
        action_contract = _build_query_diagnosis_action_contract(candidates, evidence, query_text) if candidates else []
        if action_contract:
            render_priority_dataframe(
                pd.DataFrame(action_contract),
                title="Operator action contract",
                priority_columns=[
                    "PRIORITY", "SIGNAL", "ACTION_DECISION",
                    "ROOT_CAUSE_CLASS", "FIRST_OPERATOR_MOVE", "VERIFY_AFTER_FIX",
                ],
                raw_label="Full query diagnosis action contract",
            )
            with st.expander("Telemetry details for Cortex", expanded=False):
                render_priority_dataframe(
                    pd.DataFrame(candidates),
                    title="Telemetry-bound optimization candidates",
                    priority_columns=[
                        "PRIORITY", "SIGNAL", "EVIDENCE",
                        "SPECIFIC_RECOMMENDATION", "VERIFY_AFTER_FIX",
                    ],
                    raw_label="All AI diagnosis candidates",
                )
        elif query_text:
            st.info("No deterministic tuning candidate found yet. Load a query ID or add observed symptoms before asking Cortex.")

        if operator_stats is not None and not getattr(operator_stats, "empty", True):
            with st.expander("Loaded operator stats sample", expanded=False):
                render_priority_dataframe(
                    operator_stats,
                    title="Operator stats loaded for Cortex context",
                    priority_columns=[
                        "OPERATOR_ID", "OPERATOR_TYPE", "PARENT_OPERATORS",
                        "OPERATOR_STATISTICS", "EXECUTION_TIME_BREAKDOWN",
                    ],
                    raw_label="All loaded operator stats",
                )

        diagnose_with_cortex = st.button(
            "Diagnose with Cortex",
            key="ai_diagnose",
            help=(
                "Runs one throttled Cortex completion against loaded query telemetry, operator stats, and deterministic "
                "candidates. Identical telemetry reuses the cached answer. Telemetry stores feature, timing, and "
                "prompt hash only; prompt text is not stored."
            ),
            disabled=not bool(query_text),
            width="stretch",
        )
        if diagnose_with_cortex:
            with render_load_status("Running Cortex query analysis", "Cortex query analysis ready"):
                try:
                    action_session = _action_session("run Cortex query analysis")
                    if action_session is None:
                        return
                    prompt = _build_ai_query_diagnosis_prompt(
                        query_text,
                        evidence,
                        candidates,
                        _summarize_operator_stats(operator_stats),
                    )
                    answer = run_cortex_completion(
                        action_session,
                        prompt,
                        alias="ANSWER",
                        prompt_limit=8000,
                        feature="query_analysis_ai_diagnosis",
                    )
                    st.markdown(answer)
                except CortexRateLimitError as e:
                    st.info(format_snowflake_error(e))
                except Exception as e:
                    st.info(f"Cortex AI unavailable. {format_snowflake_error(e)} Ensure Cortex functions are enabled in your account.")
