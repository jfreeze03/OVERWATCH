# sections/stored_proc_tracker.py - Stored procedure and UDF cost tracking
import re

import streamlit as st
import pandas as pd
from utils import (
    get_session,
    filter_existing_columns,
    run_query,
    format_snowflake_error,
    format_credits,
    credits_to_dollars,
    defer_source_note,
    metric_confidence_label,
    freshness_note,
    download_csv,
    build_metered_credit_cte,
    render_query_drilldown,
    render_priority_dataframe,
    sql_literal,
    resolve_owner_context,
    get_global_filter_clause,
    get_active_company,
    get_active_environment,
    get_db_filter_clause,
    load_task_inventory,
    build_mart_procedure_inventory_sql,
    build_mart_procedure_calls_sql,
    build_mart_procedure_sla_sql,
    safe_float,
    safe_int,
    CREDIT_RATES,
    add_signal_routes,
    make_action_id,
    upsert_actions,
)


PROCEDURE_SIGNAL_ROUTES = {
    "Orphan Procedure Candidate": (
        "Stored procedures",
        "Confirm owner and retirement status; if still production, link it to a task graph or document why it remains ad-hoc.",
    ),
    "Procedure Runs Outside Task Graph": (
        "Stored procedures",
        "Validate whether manual execution is expected; if it is a production workflow, move it into task orchestration or add an approved exception.",
    ),
    "Procedure Behind Suspended Task": (
        "Task graphs",
        "Open Task Graph Control, confirm the suspension reason, then resume only after dependency and downstream checks.",
    ),
    "Procedure Runtime SLA Breach": (
        "Task graphs",
        "Compare the latest run with the release window, inspect child queries and operator stats, then decide whether to tune SQL or resize/schedule the warehouse.",
    ),
    "Procedure Cost Regression": (
        "Cost & Contract",
        "Break down child-query credits, warehouse size, Cortex/serverless calls, and release changes before approving the next run.",
    ),
}


def _procedure_key(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value or "").replace('"', "").upper().strip()
    if not text:
        return ""
    return text.split("(")[0].split(".")[-1]


def _procedure_from_task_definition(definition: object) -> str:
    match = re.search(r"\bCALL\s+([A-Za-z0-9_.$\"]+)", str(definition or ""), flags=re.IGNORECASE)
    return match.group(1).replace('"', "") if match else ""


def _procedure_name_parts(value: object) -> tuple[str, str, str]:
    if pd.isna(value):
        return "", "", ""
    text = str(value or "").replace('"', "").strip()
    text = text.split("(")[0].strip()
    parts = [part.strip() for part in text.split(".") if part.strip()]
    if len(parts) >= 3:
        return parts[-3].upper(), parts[-2].upper(), parts[-1].upper()
    if len(parts) == 2:
        return "", parts[-2].upper(), parts[-1].upper()
    return "", "", (parts[-1].upper() if parts else "")


def _add_procedure_context_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    frame = df.copy()
    name_source = "PROCEDURE_NAME" if "PROCEDURE_NAME" in frame.columns else "NAME" if "NAME" in frame.columns else ""
    parsed = frame[name_source].apply(_procedure_name_parts) if name_source else pd.Series([("", "", "")] * len(frame), index=frame.index)
    parsed_db = parsed.apply(lambda item: item[0])
    parsed_schema = parsed.apply(lambda item: item[1])
    parsed_name = parsed.apply(lambda item: item[2])

    if "DATABASE_NAME" not in frame.columns:
        if "PROCEDURE_CATALOG" in frame.columns:
            frame["DATABASE_NAME"] = frame["PROCEDURE_CATALOG"]
        else:
            frame["DATABASE_NAME"] = parsed_db
    else:
        frame["DATABASE_NAME"] = frame["DATABASE_NAME"].fillna("")
        frame.loc[frame["DATABASE_NAME"].astype(str).str.strip().eq("") & parsed_db.astype(str).str.strip().ne(""), "DATABASE_NAME"] = parsed_db

    if "SCHEMA_NAME" not in frame.columns:
        if "PROCEDURE_SCHEMA" in frame.columns:
            frame["SCHEMA_NAME"] = frame["PROCEDURE_SCHEMA"]
        else:
            frame["SCHEMA_NAME"] = parsed_schema
    else:
        frame["SCHEMA_NAME"] = frame["SCHEMA_NAME"].fillna("")
        frame.loc[frame["SCHEMA_NAME"].astype(str).str.strip().eq("") & parsed_schema.astype(str).str.strip().ne(""), "SCHEMA_NAME"] = parsed_schema

    if "PROCEDURE_CATALOG" not in frame.columns:
        frame["PROCEDURE_CATALOG"] = frame["DATABASE_NAME"]
    if "PROCEDURE_SCHEMA" not in frame.columns:
        frame["PROCEDURE_SCHEMA"] = frame["SCHEMA_NAME"]
    if name_source and "PROCEDURE_NAME" in frame.columns:
        blank_names = frame["PROCEDURE_NAME"].fillna("").astype(str).str.strip().eq("")
        frame.loc[blank_names & parsed_name.astype(str).str.strip().ne(""), "PROCEDURE_NAME"] = parsed_name

    db = frame["DATABASE_NAME"].fillna("").astype(str).str.strip()
    schema = frame["SCHEMA_NAME"].fillna("").astype(str).str.strip()
    proc = frame.get("PROCEDURE_NAME", pd.Series([""] * len(frame), index=frame.index)).fillna("").astype(str).str.strip()
    context_proc = parsed_name.where(parsed_name.astype(str).str.strip().ne(""), proc).astype(str).str.strip()
    has_proc = context_proc.ne("")
    frame["PROCEDURE_CONTEXT"] = context_proc.where(has_proc, "")
    has_db = db.ne("")
    has_schema = schema.ne("")
    full_context = has_db & has_schema & has_proc
    db_only_context = has_db & ~has_schema & has_proc
    schema_only_context = ~has_db & has_schema & has_proc
    frame.loc[full_context, "PROCEDURE_CONTEXT"] = db[full_context] + "." + schema[full_context] + "." + context_proc[full_context]
    frame.loc[db_only_context, "PROCEDURE_CONTEXT"] = db[db_only_context] + "." + context_proc[db_only_context]
    frame.loc[schema_only_context, "PROCEDURE_CONTEXT"] = schema[schema_only_context] + "." + context_proc[schema_only_context]
    return frame


def _procedure_scope_key(row: pd.Series) -> str:
    proc = _procedure_key(row.get("PROCEDURE_NAME") or row.get("NAME"))
    db = str(row.get("DATABASE_NAME") or row.get("PROCEDURE_CATALOG") or "").replace('"', "").upper().strip()
    schema = str(row.get("SCHEMA_NAME") or row.get("PROCEDURE_SCHEMA") or "").replace('"', "").upper().strip()
    if db or schema:
        return ".".join(part for part in [db, schema, proc] if part)
    return proc


def _build_procedure_ops_frames(
    procedures: pd.DataFrame,
    task_inventory: pd.DataFrame,
    call_usage: pd.DataFrame,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    procs = _add_procedure_context_columns(procedures.copy()) if procedures is not None else pd.DataFrame()
    tasks = _add_procedure_context_columns(task_inventory.copy()) if task_inventory is not None else pd.DataFrame()
    calls = _add_procedure_context_columns(call_usage.copy()) if call_usage is not None else pd.DataFrame()

    if not tasks.empty:
        if "PROCEDURE_NAME" not in tasks.columns:
            tasks["PROCEDURE_NAME"] = tasks.get("DEFINITION", pd.Series([""] * len(tasks), index=tasks.index)).apply(
                _procedure_from_task_definition
            )
        tasks = _add_procedure_context_columns(tasks)
        tasks["PROC_SCOPE_KEY"] = tasks.apply(_procedure_scope_key, axis=1)
        tasks_by_proc = tasks.groupby("PROC_SCOPE_KEY", dropna=False).agg(
            DATABASE_NAME=("DATABASE_NAME", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
            SCHEMA_NAME=("SCHEMA_NAME", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
            PROCEDURE_NAME=("PROCEDURE_NAME", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
            PROCEDURE_CONTEXT=("PROCEDURE_CONTEXT", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
            TASK_COUNT=("NAME", "nunique"),
            TASKS=("NAME", lambda s: ", ".join(sorted(set(s.astype(str)))[:8])),
            SUSPENDED_TASKS=("STATE", lambda s: int((s.astype(str).str.upper() == "SUSPENDED").sum())),
        ).reset_index()
    else:
        tasks_by_proc = pd.DataFrame(columns=["PROC_SCOPE_KEY", "TASK_COUNT", "TASKS", "SUSPENDED_TASKS"])

    if not calls.empty:
        calls["PROC_SCOPE_KEY"] = calls.apply(_procedure_scope_key, axis=1)
        call_aggs = {
            "DATABASE_NAME": ("DATABASE_NAME", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
            "SCHEMA_NAME": ("SCHEMA_NAME", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
            "PROCEDURE_NAME": ("PROCEDURE_NAME", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
            "PROCEDURE_CONTEXT": ("PROCEDURE_CONTEXT", lambda s: next((str(v) for v in s if str(v or "").strip()), "")),
            "CALL_COUNT": ("CALL_COUNT", "sum"),
            "DOWNSTREAM_QUERY_COUNT": ("DOWNSTREAM_QUERY_COUNT", "sum"),
            "LAST_CALL": ("LAST_CALL", "max"),
        }
        if "TOTAL_CREDITS" in calls.columns:
            call_aggs["TOTAL_CREDITS"] = ("TOTAL_CREDITS", "sum")
        if "CLOUD_CREDITS" in calls.columns:
            call_aggs["CLOUD_CREDITS"] = ("CLOUD_CREDITS", "sum")
        calls_by_proc = calls.groupby("PROC_SCOPE_KEY", dropna=False).agg(**call_aggs).reset_index()
    else:
        calls_by_proc = pd.DataFrame(columns=["PROC_SCOPE_KEY", "CALL_COUNT", "DOWNSTREAM_QUERY_COUNT", "TOTAL_CREDITS", "CLOUD_CREDITS", "LAST_CALL"])

    if not procs.empty:
        name_col = "PROCEDURE_NAME" if "PROCEDURE_NAME" in procs.columns else "NAME"
        procs["PROCEDURE_NAME"] = procs.get(name_col, pd.Series([""] * len(procs), index=procs.index))
        procs["PROC_SCOPE_KEY"] = procs.apply(_procedure_scope_key, axis=1)
        context_cols = ["DATABASE_NAME", "SCHEMA_NAME", "PROCEDURE_NAME", "PROCEDURE_CONTEXT"]
        task_join = tasks_by_proc.drop(columns=context_cols, errors="ignore")
        call_join = calls_by_proc.drop(columns=context_cols, errors="ignore")
        joined = procs.merge(task_join, on="PROC_SCOPE_KEY", how="left").merge(call_join, on="PROC_SCOPE_KEY", how="left")
    else:
        if tasks_by_proc.empty:
            joined = calls_by_proc
        elif calls_by_proc.empty:
            joined = tasks_by_proc
        else:
            call_join = calls_by_proc.drop(
                columns=["DATABASE_NAME", "SCHEMA_NAME", "PROCEDURE_NAME", "PROCEDURE_CONTEXT"],
                errors="ignore",
            )
            joined = tasks_by_proc.merge(call_join, on="PROC_SCOPE_KEY", how="outer")
    joined = _add_procedure_context_columns(joined)
    if "PROC_KEY" not in joined.columns:
        joined["PROC_KEY"] = joined.get(
            "PROCEDURE_NAME",
            pd.Series([""] * len(joined), index=joined.index),
        ).apply(_procedure_key)

    for col in ["TASK_COUNT", "SUSPENDED_TASKS", "CALL_COUNT", "DOWNSTREAM_QUERY_COUNT"]:
        if col not in joined.columns:
            joined[col] = 0
        joined[col] = pd.to_numeric(joined[col], errors="coerce").fillna(0).astype(int)
    if "TOTAL_CREDITS" not in joined.columns:
        joined["TOTAL_CREDITS"] = 0.0
    joined["TOTAL_CREDITS"] = pd.to_numeric(joined["TOTAL_CREDITS"], errors="coerce").fillna(0.0)
    if "CLOUD_CREDITS" not in joined.columns:
        joined["CLOUD_CREDITS"] = 0.0
    joined["CLOUD_CREDITS"] = pd.to_numeric(joined["CLOUD_CREDITS"], errors="coerce").fillna(0.0)
    joined["ORCHESTRATION_STATUS"] = joined.apply(
        lambda row: "Task blocked - suspended"
        if safe_int(row.get("SUSPENDED_TASKS")) > 0
        else "Task-managed"
        if safe_int(row.get("TASK_COUNT")) > 0
        else "Manual CALL only"
        if safe_int(row.get("CALL_COUNT")) > 0
        else "No recent execution evidence",
        axis=1,
    )
    joined["OWNER_REVIEW"] = joined["ORCHESTRATION_STATUS"].apply(
        lambda status: "Required" if status != "Task-managed" else "Routine"
    )
    joined["OPERATING_RISK"] = joined.apply(
        lambda row: "High"
        if row.get("ORCHESTRATION_STATUS") == "Task blocked - suspended"
        else "Medium"
        if row.get("ORCHESTRATION_STATUS") in {"Manual CALL only", "No recent execution evidence"}
        else "Low",
        axis=1,
    )
    joined["OPERATING_RISK_RANK"] = joined["OPERATING_RISK"].map({"High": 0, "Medium": 1, "Low": 2}).fillna(3).astype(int)

    exceptions = []
    for _, row in joined.iterrows():
        proc = str(row.get("PROCEDURE_CONTEXT") or row.get("PROCEDURE_NAME") or row.get("PROC_SCOPE_KEY") or "UNKNOWN_PROCEDURE")
        if safe_int(row.get("TASK_COUNT")) == 0 and safe_int(row.get("CALL_COUNT")) == 0:
            exceptions.append({
                "SEVERITY": "Medium",
                "SIGNAL": "Orphan Procedure Candidate",
                "PROCEDURE": proc,
                "PROCEDURE_NAME": proc,
                "DATABASE_NAME": row.get("DATABASE_NAME", ""),
                "SCHEMA_NAME": row.get("SCHEMA_NAME", ""),
                "PROCEDURE_CONTEXT": row.get("PROCEDURE_CONTEXT", proc),
                "DETAIL": "Procedure has no detected task link and no recent CALL history in the selected lookback.",
                "ORCHESTRATION_STATUS": row.get("ORCHESTRATION_STATUS", ""),
                "OWNER_REVIEW": row.get("OWNER_REVIEW", ""),
                "OPERATING_RISK": row.get("OPERATING_RISK", ""),
                "OPERATING_RISK_RANK": row.get("OPERATING_RISK_RANK", 3),
                "TASKS": "",
                "LAST_CALL": row.get("LAST_CALL", ""),
            })
        elif safe_int(row.get("TASK_COUNT")) == 0 and safe_int(row.get("CALL_COUNT")) > 0:
            exceptions.append({
                "SEVERITY": "Low",
                "SIGNAL": "Procedure Runs Outside Task Graph",
                "PROCEDURE": proc,
                "PROCEDURE_NAME": proc,
                "DATABASE_NAME": row.get("DATABASE_NAME", ""),
                "SCHEMA_NAME": row.get("SCHEMA_NAME", ""),
                "PROCEDURE_CONTEXT": row.get("PROCEDURE_CONTEXT", proc),
                "DETAIL": "Recent CALL history exists but no task definition references this procedure.",
                "ORCHESTRATION_STATUS": row.get("ORCHESTRATION_STATUS", ""),
                "OWNER_REVIEW": row.get("OWNER_REVIEW", ""),
                "OPERATING_RISK": row.get("OPERATING_RISK", ""),
                "OPERATING_RISK_RANK": row.get("OPERATING_RISK_RANK", 3),
                "TASKS": "",
                "LAST_CALL": row.get("LAST_CALL", ""),
            })
        elif safe_int(row.get("SUSPENDED_TASKS")) > 0:
            exceptions.append({
                "SEVERITY": "Medium",
                "SIGNAL": "Procedure Behind Suspended Task",
                "PROCEDURE": proc,
                "PROCEDURE_NAME": proc,
                "DATABASE_NAME": row.get("DATABASE_NAME", ""),
                "SCHEMA_NAME": row.get("SCHEMA_NAME", ""),
                "PROCEDURE_CONTEXT": row.get("PROCEDURE_CONTEXT", proc),
                "DETAIL": f"{safe_int(row.get('SUSPENDED_TASKS'))} linked task(s) are suspended.",
                "ORCHESTRATION_STATUS": row.get("ORCHESTRATION_STATUS", ""),
                "OWNER_REVIEW": row.get("OWNER_REVIEW", ""),
                "OPERATING_RISK": row.get("OPERATING_RISK", ""),
                "OPERATING_RISK_RANK": row.get("OPERATING_RISK_RANK", 3),
                "TASKS": row.get("TASKS", ""),
                "LAST_CALL": row.get("LAST_CALL", ""),
            })

    summary = {
        "PROCEDURES": len(joined),
        "LINKED_TO_TASKS": int((joined["TASK_COUNT"] > 0).sum()) if not joined.empty else 0,
        "RECENT_CALLS": int(joined["CALL_COUNT"].sum()) if not joined.empty else 0,
        "ORPHAN_CANDIDATES": sum(1 for row in exceptions if row["SIGNAL"] == "Orphan Procedure Candidate"),
        "OWNER_REVIEW_REQUIRED": int((joined["OWNER_REVIEW"] == "Required").sum()) if not joined.empty else 0,
        "MANUAL_ONLY": int((joined["ORCHESTRATION_STATUS"] == "Manual CALL only").sum()) if not joined.empty else 0,
        "BLOCKED_BY_SUSPENDED_TASK": int((joined["ORCHESTRATION_STATUS"] == "Task blocked - suspended").sum()) if not joined.empty else 0,
    }
    exception_df = add_signal_routes(pd.DataFrame(exceptions), PROCEDURE_SIGNAL_ROUTES)
    return summary, exception_df, joined


def _build_procedure_inventory_sql(days: int) -> tuple[str, str]:
    db_scope = get_db_filter_clause("procedure_catalog")
    procedure_sql = f"""
        SELECT procedure_catalog,
               procedure_schema,
               procedure_name,
               argument_signature,
               procedure_owner,
               procedure_language,
               created,
               last_altered
        FROM SNOWFLAKE.ACCOUNT_USAGE.PROCEDURES
        WHERE deleted IS NULL
          AND procedure_catalog NOT ILIKE 'SNOWFLAKE%'
          {db_scope}
        ORDER BY last_altered DESC
        LIMIT 500
    """
    call_scope = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
        schema_col="schema_name",
    )
    call_sql = f"""
        WITH calls AS (
            SELECT REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) AS procedure_name,
                   database_name,
                   schema_name,
                   query_id,
                   start_time,
                   total_elapsed_time,
                   credits_used_cloud_services
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE query_type = 'CALL'
              AND start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {call_scope}
        )
        SELECT database_name,
               schema_name,
               procedure_name,
               COUNT(*) AS call_count,
               COUNT(DISTINCT query_id) AS downstream_query_count,
               ROUND(SUM(COALESCE(credits_used_cloud_services, 0)), 4) AS cloud_credits,
               MAX(start_time) AS last_call,
               AVG(total_elapsed_time) / 1000 AS avg_elapsed_sec
        FROM calls
        GROUP BY database_name, schema_name, procedure_name
        ORDER BY call_count DESC
        LIMIT 500
    """
    return procedure_sql, call_sql


def _build_procedure_sla_sql(session, days: int, has_root_query_id: bool) -> str:
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
    proc_filters_plain = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
        schema_col="schema_name",
    )
    proc_filters_q = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
        schema_col="q.schema_name",
    )
    return f"""
        WITH calls AS (
            SELECT query_id AS root_query_id,
                   REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) AS procedure_name,
                   database_name,
                   schema_name,
                   user_name,
                   role_name,
                   warehouse_name,
                   {call_wh_size_expr},
                   start_time,
                   SUBSTR(query_text, 1, 1000) AS call_text
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE query_type = 'CALL'
              AND start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {proc_filters_plain}
        ),
        children AS (
            SELECT {root_expr} AS root_query_id,
                   q.query_id,
                   q.total_elapsed_time,
                   {child_cloud_expr},
                   {child_wh_size_expr}
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {proc_filters_q}
        )
        SELECT c.procedure_name,
               c.database_name,
               c.schema_name,
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
                 c.database_name, c.schema_name, c.warehouse_name, c.start_time, c.call_text
        ORDER BY c.start_time DESC
        LIMIT 1000
    """


def _procedure_run_estimated_credits(row: pd.Series) -> float:
    elapsed = safe_float(row.get("TOTAL_ELAPSED_SEC"))
    size = str(row.get("WAREHOUSE_SIZE") or "").strip()
    compute = CREDIT_RATES.get(size, CREDIT_RATES.get(size.title(), 1)) * elapsed / 3600 if elapsed > 0 else 0.0
    return round(compute + safe_float(row.get("CLOUD_CREDITS")), 6)


def _build_procedure_sla_frames(runs: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    df = runs.copy() if runs is not None else pd.DataFrame()
    if df.empty:
        return {"RUNS": 0, "PROCEDURES": 0, "SLA_BREACHES": 0, "COST_BREACHES": 0}, pd.DataFrame(), pd.DataFrame()
    df.columns = [str(col).upper() for col in df.columns]
    df = _add_procedure_context_columns(df)
    df["TOTAL_ELAPSED_SEC"] = pd.to_numeric(df.get("TOTAL_ELAPSED_SEC", 0), errors="coerce").fillna(0)
    df["CLOUD_CREDITS"] = pd.to_numeric(df.get("CLOUD_CREDITS", 0), errors="coerce").fillna(0)
    df["START_TIME"] = pd.to_datetime(df.get("START_TIME"), errors="coerce")
    if "EST_TOTAL_CREDITS" in df.columns:
        df["EST_TOTAL_CREDITS"] = pd.to_numeric(df["EST_TOTAL_CREDITS"], errors="coerce").fillna(0)
        if df["EST_TOTAL_CREDITS"].sum() <= 0:
            df["EST_TOTAL_CREDITS"] = df.apply(_procedure_run_estimated_credits, axis=1)
    else:
        df["EST_TOTAL_CREDITS"] = df.apply(_procedure_run_estimated_credits, axis=1)
    df["PROC_SCOPE_KEY"] = df.apply(_procedure_scope_key, axis=1)

    latest_idx = df.groupby("PROC_SCOPE_KEY")["START_TIME"].idxmax()
    latest = df.loc[latest_idx].copy() if len(latest_idx) else pd.DataFrame()
    baselines = df.groupby("PROC_SCOPE_KEY", dropna=False).agg(
        RUNS=("ROOT_QUERY_ID", "nunique"),
        AVG_ELAPSED_SEC=("TOTAL_ELAPSED_SEC", "mean"),
        MAX_ELAPSED_SEC=("TOTAL_ELAPSED_SEC", "max"),
        AVG_EST_CREDITS=("EST_TOTAL_CREDITS", "mean"),
        MAX_EST_CREDITS=("EST_TOTAL_CREDITS", "max"),
    ).reset_index()
    latest = latest.merge(baselines, on="PROC_SCOPE_KEY", how="left") if not latest.empty else pd.DataFrame()
    if not latest.empty:
        latest["RUNTIME_CHANGE_PCT"] = latest.apply(
            lambda row: round(((safe_float(row.get("TOTAL_ELAPSED_SEC")) - safe_float(row.get("AVG_ELAPSED_SEC"))) / safe_float(row.get("AVG_ELAPSED_SEC")) * 100), 1)
            if safe_float(row.get("AVG_ELAPSED_SEC")) > 0 else 0,
            axis=1,
        )
        latest["COST_CHANGE_PCT"] = latest.apply(
            lambda row: round(((safe_float(row.get("EST_TOTAL_CREDITS")) - safe_float(row.get("AVG_EST_CREDITS"))) / safe_float(row.get("AVG_EST_CREDITS")) * 100), 1)
            if safe_float(row.get("AVG_EST_CREDITS")) > 0 else 0,
            axis=1,
        )

    exceptions = []
    for _, row in latest.iterrows():
        elapsed = safe_float(row.get("TOTAL_ELAPSED_SEC"))
        avg_elapsed = safe_float(row.get("AVG_ELAPSED_SEC"))
        credits = safe_float(row.get("EST_TOTAL_CREDITS"))
        avg_credits = safe_float(row.get("AVG_EST_CREDITS"))
        runtime_change = ((elapsed - avg_elapsed) / avg_elapsed * 100) if avg_elapsed > 0 else 0
        cost_change = ((credits - avg_credits) / avg_credits * 100) if avg_credits > 0 else 0
        common = {
            "PROCEDURE_NAME": row.get("PROCEDURE_NAME", ""),
            "DATABASE_NAME": row.get("DATABASE_NAME", ""),
            "SCHEMA_NAME": row.get("SCHEMA_NAME", ""),
            "PROCEDURE_CONTEXT": row.get("PROCEDURE_CONTEXT", ""),
            "ROOT_QUERY_ID": row.get("ROOT_QUERY_ID", ""),
            "WAREHOUSE_NAME": row.get("WAREHOUSE_NAME", ""),
            "WAREHOUSE_SIZE": row.get("WAREHOUSE_SIZE", ""),
            "LATEST_ELAPSED_SEC": elapsed,
            "AVG_ELAPSED_SEC": avg_elapsed,
            "RUNTIME_CHANGE_PCT": round(runtime_change, 1),
            "EST_TOTAL_CREDITS": credits,
            "AVG_EST_CREDITS": avg_credits,
            "COST_CHANGE_PCT": round(cost_change, 1),
            "DOWNSTREAM_QUERY_COUNT": safe_int(row.get("DOWNSTREAM_QUERY_COUNT")),
        }
        if avg_elapsed > 0 and elapsed > avg_elapsed * 1.5 and elapsed > 300:
            exceptions.append({
                **common,
                "SEVERITY": "High" if elapsed > avg_elapsed * 2 else "Medium",
                "SIGNAL": "Procedure Runtime SLA Breach",
                "RECOMMENDED_ACTION": "Compare this run to the last product release, inspect child queries, and validate changed procedure logic.",
            })
        if avg_credits > 0 and credits > avg_credits * 1.5 and credits >= 0.01:
            exceptions.append({
                **common,
                "SEVERITY": "High" if credits > avg_credits * 2 else "Medium",
                "SIGNAL": "Procedure Cost Regression",
                "RECOMMENDED_ACTION": "Review warehouse size, child-query scan volume, Cortex/serverless calls, and recent procedure changes.",
            })
    exception_df = add_signal_routes(pd.DataFrame(exceptions), PROCEDURE_SIGNAL_ROUTES)
    summary = {
        "RUNS": len(df),
        "PROCEDURES": df["PROC_SCOPE_KEY"].nunique(),
        "SLA_BREACHES": int((exception_df.get("SIGNAL", pd.Series(dtype=str)) == "Procedure Runtime SLA Breach").sum()) if not exception_df.empty else 0,
        "COST_BREACHES": int((exception_df.get("SIGNAL", pd.Series(dtype=str)) == "Procedure Cost Regression").sum()) if not exception_df.empty else 0,
    }
    return summary, exception_df, latest


def _procedure_owner(row: pd.Series) -> str:
    return str(
        row.get("PROCEDURE_OWNER")
        or row.get("OWNER_ROLE")
        or row.get("ROLE_NAME")
        or row.get("USER_NAME")
        or "DBA / Data Engineering"
    )


def _procedure_environment(row: pd.Series) -> str:
    active_env = get_active_environment()
    return str(row.get("ENVIRONMENT") or (active_env if active_env != "ALL" else "") or "")


def _procedure_verification_sql(row: pd.Series, lookback_days: int = 7) -> str:
    proc = str(row.get("PROCEDURE_NAME") or row.get("PROCEDURE") or "").strip()
    root_query_id = str(row.get("ROOT_QUERY_ID") or "").strip()
    proc_filter = f"AND query_text ILIKE {sql_literal('%' + proc + '%', 600)}" if proc else ""
    root_filter = f"OR query_id = {sql_literal(root_query_id, 200)}" if root_query_id else ""
    return f"""-- Stored procedure reliability proof and post-fix verification
SELECT query_id,
       user_name,
       role_name,
       warehouse_name,
       start_time,
       execution_status,
       total_elapsed_time / 1000 AS elapsed_sec,
       credits_used_cloud_services,
       error_code,
       error_message,
       SUBSTR(query_text, 1, 4000) AS query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('day', -{max(1, int(lookback_days or 7))}, CURRENT_TIMESTAMP())
  AND (
        query_type = 'CALL'
        {proc_filter}
        {root_filter}
      )
ORDER BY start_time DESC
LIMIT 50;

-- Verification rule: next procedure run should return within runtime and estimated-credit baseline.
"""


def _procedure_metric(row: pd.Series, *columns: str):
    for column in columns:
        if column in row and row.get(column) not in (None, ""):
            return safe_float(row.get(column))
    return None


def _build_procedure_reliability_action(row: pd.Series, company: str, source: str) -> dict:
    signal = str(row.get("SIGNAL") or "Procedure Reliability")
    proc = str(row.get("PROCEDURE_NAME") or row.get("PROCEDURE") or "Unknown procedure")
    severity = str(row.get("SEVERITY") or "Medium")
    runtime_pct = safe_float(row.get("RUNTIME_CHANGE_PCT"))
    cost_pct = safe_float(row.get("COST_CHANGE_PCT"))
    detail = (
        f"runtime change={runtime_pct:,.1f}%, cost change={cost_pct:,.1f}%, "
        f"root_query_id={row.get('ROOT_QUERY_ID', '')}, "
        f"orchestration={row.get('ORCHESTRATION_STATUS', '')}, owner_review={row.get('OWNER_REVIEW', '')}"
    )
    action = str(row.get("RECOMMENDED_ACTION") or "Review procedure regression and linked task graph.")
    if "verify" not in action.lower():
        action += " Verify the next run against the baseline and attach QUERY_HISTORY evidence before closing."
    if str(row.get("OWNER_REVIEW") or "").upper() == "REQUIRED" and "owner review" not in action.lower():
        action += " Owner review is required before treating this procedure as production-safe."
    generated_sql = (
        "-- Reviewed procedure reliability plan. Do not redeploy or retry blindly.\n"
        f"-- Procedure: {proc}\n"
        f"-- Signal: {signal}\n"
        f"-- Root query: {row.get('ROOT_QUERY_ID', '')}\n"
        f"-- Orchestration status: {row.get('ORCHESTRATION_STATUS', '')}\n"
        f"-- Owner review: {row.get('OWNER_REVIEW', '')}\n"
        "-- Inspect child queries, recent procedure changes, warehouse size, and task graph schedule.\n"
        "-- If code changed, redeploy through the approved release path; if runtime capacity changed, use Warehouse Health first."
    )
    finding = f"{signal}: {proc}. {detail}"
    verification_query = _procedure_verification_sql(row)[:8000]
    baseline_value = _procedure_metric(row, "AVG_ELAPSED_SEC", "AVG_EXECUTION_SECONDS", "AVG_DURATION_SEC", "BASELINE_SECONDS")
    current_value = _procedure_metric(row, "LATEST_ELAPSED_SEC", "TOTAL_ELAPSED_SEC", "EXECUTION_SECONDS", "ELAPSED_SEC", "LATEST_DURATION_SEC")
    measured_delta = (
        round(current_value - baseline_value, 4)
        if current_value is not None and baseline_value is not None
        else None
    )
    owner_context = resolve_owner_context(
        row,
        entity=proc,
        entity_type="Procedure",
        owner=_procedure_owner(row),
        category="Task & Procedure Reliability",
        alert_type=signal,
    )
    recovery_state = "Procedure Cost Review Required" if "COST" in signal.upper() else "Procedure Recovery Review Required"
    recovery_target_hours = 8.0 if severity.upper() in {"CRITICAL", "HIGH"} else 24.0
    approval_group = owner_context.get("APPROVAL_GROUP") or owner_context.get("ESCALATION_TARGET") or _procedure_owner(row)
    return {
        "Action ID": make_action_id("Procedure Reliability", proc, finding),
        "Source": source,
        "Severity": severity,
        "Category": "Task & Procedure Reliability",
        "Entity Type": "Stored Procedure",
        "Entity": proc,
        "Owner": owner_context.get("OWNER") or _procedure_owner(row),
        "Owner Email": owner_context.get("OWNER_EMAIL", ""),
        "Oncall Primary": owner_context.get("ONCALL_PRIMARY", ""),
        "Oncall Secondary": owner_context.get("ONCALL_SECONDARY", ""),
        "Approval Group": approval_group,
        "Escalation Target": owner_context.get("ESCALATION_TARGET", ""),
        "Owner Source": owner_context.get("OWNER_SOURCE", ""),
        "Owner Evidence": owner_context.get("OWNER_EVIDENCE", ""),
        "Approver": approval_group,
        "Finding": finding,
        "Action": action,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": generated_sql[:8000],
        "Proof Query": verification_query,
        "Company": company,
        "Environment": _procedure_environment(row),
        "Verification Status": "Pending",
        "Verification Query": verification_query,
        "Baseline Value": baseline_value,
        "Current Value": current_value,
        "Measured Delta": measured_delta,
        "Owner Approval Status": "Requested",
        "Owner Approval Note": (
            "Procedure reliability action requires owner approval, release/change context, and post-fix QUERY_HISTORY "
            "evidence before closure."
        ),
        "Recovery SLA State": recovery_state,
        "Recovery SLA Target Hours": recovery_target_hours,
        "Recovery Evidence": (
            "Required closure evidence: owner approval, release/change ticket, successful next CALL or task run, "
            "and runtime/cost values back within baseline tolerance."
        ),
        "Recovery Audit State": "Audit Required",
    }


def _queue_procedure_reliability_findings(
    session,
    exceptions: pd.DataFrame,
    *,
    company: str,
    source: str,
) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    actions = [
        _build_procedure_reliability_action(row, company, source)
        for _, row in exceptions.head(100).iterrows()
    ]
    return upsert_actions(session, actions)


def _build_procedure_reliability_slo_board(summary: dict, exceptions: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Condense stored-procedure reliability into a compact DBA control board."""
    rows = [
        {
            "SLO": "Procedure runs",
            "STATE": "Ready" if safe_int(summary.get("RUNS")) > 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('RUNS')):,} run(s) in the selected window.",
            "NEXT_ACTION": "Load procedure evidence before declaring the surface healthy.",
        },
        {
            "SLO": "Runtime regressions",
            "STATE": "Ready" if safe_int(summary.get("SLA_BREACHES")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('SLA_BREACHES')):,} runtime breach(es).",
            "NEXT_ACTION": "Compare the latest CALL against the historical baseline and fix the root cause.",
        },
        {
            "SLO": "Cost regressions",
            "STATE": "Ready" if safe_int(summary.get("COST_BREACHES")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('COST_BREACHES')):,} cost regression(s).",
            "NEXT_ACTION": "Check child-query scan volume, warehouse size, and release drift.",
        },
        {
            "SLO": "Owner review",
            "STATE": "Ready" if safe_int(summary.get("OWNER_REVIEW_REQUIRED")) == 0 else "Review",
            "EVIDENCE": f"{safe_int(summary.get('OWNER_REVIEW_REQUIRED')):,} procedure(s) require owner review.",
            "NEXT_ACTION": "Get the owner to approve before treating the procedure as production-safe.",
        },
        {
            "SLO": "Suspended-task dependency",
            "STATE": "Ready" if safe_int(summary.get("BLOCKED_BY_SUSPENDED_TASK")) == 0 else "Blocked",
            "EVIDENCE": f"{safe_int(summary.get('BLOCKED_BY_SUSPENDED_TASK')):,} procedure(s) blocked by suspended task(s).",
            "NEXT_ACTION": "Restore the task graph dependency before retrying the procedure.",
        },
    ]
    if exceptions is not None and not exceptions.empty:
        p1 = int(exceptions.get("SEVERITY", pd.Series(dtype=str)).astype(str).str.upper().eq("CRITICAL").sum())
        manual_only = int(exceptions.get("ORCHESTRATION_STATUS", pd.Series(dtype=str)).astype(str).str.contains("MANUAL", case=False, na=False).sum())
    else:
        p1 = 0
        manual_only = 0
    rows.append({
        "SLO": "Critical procedure path risk",
        "STATE": "Ready" if p1 == 0 and manual_only == 0 else "Review",
        "EVIDENCE": f"Critical exceptions={p1:,}; manual-call-only procedures={manual_only:,}.",
        "NEXT_ACTION": "Use the operations brief before relying on the task graph as production control.",
    })
    board = pd.DataFrame(rows)
    board["_RANK"] = board["STATE"].map({"Blocked": 0, "Review": 1, "Ready": 2}).fillna(9)
    score = max(0, min(100, 100 - int((board["STATE"] != "Ready").sum()) * 12))
    return {
        "score": score,
        "ready": int((board["STATE"] == "Ready").sum()),
        "review": int((board["STATE"] == "Review").sum()),
        "blocked": int((board["STATE"] == "Blocked").sum()),
    }, board.sort_values(["_RANK", "SLO"]).drop(columns=["_RANK"], errors="ignore")


def _query_history_has_root_query_id(session) -> bool:
    return bool(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["ROOT_QUERY_ID"],
    ))


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()

    st.header("Stored Proc & UDF Cost Tracker")
    st.caption("CALL queries plus downstream child SQL where ROOT_QUERY_ID is populated.")

    sp_days = st.slider("Lookback (days)", 1, 30, 7, key="sp_tracker_days")
    proc_filters_plain = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
        schema_col="schema_name",
    )
    proc_filters_q = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
        schema_col="q.schema_name",
    )

    with st.expander("Procedure Operations Brief", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        st.caption(
            "Informatica workflow replacement view: procedure inventory, task linkage, recent CALL activity, "
            "and orphan/suspended-task risk."
        )
        if st.button("Load Procedure Operations", key="sp_ops_load"):
            proc_inventory_source = "OVERWATCH mart: DIM_PROCEDURE_SNAPSHOT"
            proc_call_source = "OVERWATCH mart: FACT_PROCEDURE_RUN"
            try:
                df_procs = run_query(
                    build_mart_procedure_inventory_sql(
                        company=company,
                        database_contains=str(st.session_state.get("global_database", "") or "").strip(),
                    ),
                    ttl_key=f"procedure_inventory_mart_schema_context_v1_{company}_{sp_days}",
                    tier="metadata",
                )
                if df_procs.empty:
                    procedure_sql, _ = _build_procedure_inventory_sql(sp_days)
                    df_procs = run_query(
                        procedure_sql,
                        ttl_key=f"procedure_inventory_live_schema_context_v1_{company}_{sp_days}",
                        tier="metadata",
                    )
                    proc_inventory_source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.PROCEDURES"
            except Exception as e:
                st.info(f"Procedure inventory unavailable: {format_snowflake_error(e)}")
                df_procs = pd.DataFrame()
                proc_inventory_source = "Unavailable"
            try:
                df_tasks = load_task_inventory(session, company, force_refresh=True)
            except Exception as e:
                st.info(f"Task inventory unavailable: {format_snowflake_error(e)}")
                df_tasks = pd.DataFrame()
            try:
                df_calls = run_query(
                    build_mart_procedure_calls_sql(sp_days, company=company),
                    ttl_key=f"procedure_recent_calls_mart_schema_context_v1_{company}_{sp_days}",
                    tier="standard",
                )
                if df_calls.empty:
                    _, call_sql = _build_procedure_inventory_sql(sp_days)
                    df_calls = run_query(
                        call_sql,
                        ttl_key=f"procedure_recent_calls_live_schema_context_v1_{company}_{sp_days}",
                        tier="standard",
                    )
                    proc_call_source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
            except Exception as e:
                st.info(f"Recent CALL history unavailable: {format_snowflake_error(e)}")
                df_calls = pd.DataFrame()
                proc_call_source = "Unavailable"

            summary, exceptions, joined = _build_procedure_ops_frames(df_procs, df_tasks, df_calls)
            st.session_state["sp_ops_summary"] = summary
            st.session_state["sp_ops_exceptions"] = exceptions
            st.session_state["sp_ops_joined"] = joined
            st.session_state["sp_ops_sources"] = {
                "inventory": proc_inventory_source,
                "calls": proc_call_source,
                "tasks": "Live: SHOW TASKS IN ACCOUNT",
            }

        summary = st.session_state.get("sp_ops_summary")
        if summary:
            exceptions = st.session_state.get("sp_ops_exceptions", pd.DataFrame())
            joined = st.session_state.get("sp_ops_joined", pd.DataFrame())
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Procedures", f"{safe_int(summary.get('PROCEDURES')):,}")
            c2.metric("Linked to Tasks", f"{safe_int(summary.get('LINKED_TO_TASKS')):,}")
            c3.metric("Recent Calls", f"{safe_int(summary.get('RECENT_CALLS')):,}")
            c4.metric("Orphan Candidates", f"{safe_int(summary.get('ORPHAN_CANDIDATES')):,}", delta_color="inverse")
            if safe_int(summary.get("OWNER_REVIEW_REQUIRED")) or safe_int(summary.get("BLOCKED_BY_SUSPENDED_TASK")):
                st.caption(
                    f"Owner review required: {safe_int(summary.get('OWNER_REVIEW_REQUIRED')):,} | "
                    f"Manual-call only: {safe_int(summary.get('MANUAL_ONLY')):,} | "
                    f"Blocked by suspended task: {safe_int(summary.get('BLOCKED_BY_SUSPENDED_TASK')):,}"
                )
            sources = st.session_state.get("sp_ops_sources", {})
            if sources:
                defer_source_note(*[str(v) for v in sources.values()])
            if not exceptions.empty:
                st.warning("Procedure operations has exceptions to review before relying on task graphs as production workflow control.")
                slo_summary, slo_board = _build_procedure_reliability_slo_board(summary, exceptions)
                st.subheader("Procedure Reliability SLO Board")
                s1, s2, s3 = st.columns(3)
                s1.metric("Ready", f"{slo_summary['ready']:,}")
                s2.metric("Review", f"{slo_summary['review']:,}", delta_color="inverse")
                s3.metric("Blocked", f"{slo_summary['blocked']:,}", delta_color="inverse")
                render_priority_dataframe(
                    slo_board,
                    title="Procedure reliability SLOs and next control step",
                    priority_columns=["STATE", "SLO", "EVIDENCE", "NEXT_ACTION"],
                    sort_by=["STATE", "SLO"],
                    ascending=[True, True],
                    raw_label="All procedure reliability SLO rows",
                    height=220,
                    max_rows=10,
                )
                render_priority_dataframe(
                    exceptions,
                    title="Procedure operations exceptions",
                    priority_columns=[
                        "OPERATING_RISK", "SIGNAL", "SEVERITY", "DATABASE_NAME", "SCHEMA_NAME",
                        "PROCEDURE_CONTEXT", "PROCEDURE_NAME", "PROCEDURE_SCHEMA",
                        "ORCHESTRATION_STATUS", "OWNER_REVIEW",
                        "TASK_COUNT", "SUSPENDED_TASKS", "CALL_COUNT",
                        "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["OPERATING_RISK_RANK", "SEVERITY", "CALL_COUNT"],
                    ascending=[True, True, False],
                    raw_label="All procedure operation exceptions",
                )
                if st.button("Save Procedure Operations Findings to Action Queue", key="sp_ops_queue"):
                    try:
                        saved = _queue_procedure_reliability_findings(
                            session,
                            exceptions,
                            company=company,
                            source="Stored Procedures - Operations Brief",
                        )
                        st.success(f"Saved {saved} procedure operation finding(s) to the action queue.")
                    except Exception as e:
                        st.error(f"Could not save procedure operation findings: {format_snowflake_error(e)}")
            else:
                st.success("No procedure/task linkage exceptions found in the selected scope.")
            if not joined.empty:
                display_cols = [
                    col for col in [
                        "DATABASE_NAME", "SCHEMA_NAME", "PROCEDURE_CONTEXT",
                        "PROCEDURE_CATALOG", "PROCEDURE_SCHEMA", "PROCEDURE_NAME",
                        "PROCEDURE_OWNER", "PROCEDURE_LANGUAGE", "LAST_ALTERED",
                        "ORCHESTRATION_STATUS", "OWNER_REVIEW", "OPERATING_RISK", "OPERATING_RISK_RANK",
                        "TASK_COUNT", "TASKS", "SUSPENDED_TASKS", "CALL_COUNT",
                        "DOWNSTREAM_QUERY_COUNT", "CLOUD_CREDITS", "LAST_CALL"
                    ] if col in joined.columns
                ]
                render_priority_dataframe(
                    joined[display_cols],
                    title="Procedure inventory and task linkage",
                    priority_columns=[
                        "DATABASE_NAME", "SCHEMA_NAME", "PROCEDURE_CONTEXT",
                        "PROCEDURE_CATALOG", "PROCEDURE_SCHEMA", "PROCEDURE_NAME",
                        "ORCHESTRATION_STATUS", "OWNER_REVIEW", "OPERATING_RISK",
                        "TASK_COUNT", "SUSPENDED_TASKS", "CALL_COUNT",
                        "DOWNSTREAM_QUERY_COUNT", "CLOUD_CREDITS", "LAST_CALL",
                    ],
                    sort_by=["OPERATING_RISK_RANK", "CLOUD_CREDITS", "DOWNSTREAM_QUERY_COUNT", "CALL_COUNT"],
                    ascending=[True, False, False, False],
                    raw_label="All procedure inventory rows",
                    max_rows=50,
                )
                download_csv(joined[display_cols], "procedure_operations.csv")

    with st.expander("Procedure SLA & Cost Regression Watch", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        st.caption(
            "Detects stored procedure runs whose latest elapsed time or estimated credits jumped versus their own recent baseline. "
            "This is designed to catch product-release regressions before the next executive cost/performance review."
        )
        if st.button("Load Procedure SLA/Cost Watch", key="sp_sla_load"):
            try:
                df_proc_runs = run_query(
                    build_mart_procedure_sla_sql(sp_days, company=company),
                    ttl_key=f"procedure_sla_watch_mart_schema_context_v1_{company}_{sp_days}",
                    tier="standard",
                )
                proc_sla_source = "OVERWATCH mart: FACT_PROCEDURE_RUN"
                has_root_query_id = True
                if df_proc_runs.empty:
                    has_root_query_id = _query_history_has_root_query_id(session)
                    df_proc_runs = run_query(
                        _build_procedure_sla_sql(session, sp_days, has_root_query_id),
                        ttl_key=f"procedure_sla_watch_live_schema_context_v1_{company}_{sp_days}_{has_root_query_id}",
                        tier="standard",
                    )
                    proc_sla_source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                summary, exceptions, latest = _build_procedure_sla_frames(df_proc_runs)
                st.session_state["sp_sla_summary"] = summary
                st.session_state["sp_sla_exceptions"] = exceptions
                st.session_state["sp_sla_latest"] = latest
                st.session_state["sp_sla_root_available"] = has_root_query_id
                st.session_state["sp_sla_source"] = proc_sla_source
            except Exception as e:
                st.info(f"Procedure SLA/cost watch unavailable: {format_snowflake_error(e)}")

        summary = st.session_state.get("sp_sla_summary")
        if summary:
            exceptions = st.session_state.get("sp_sla_exceptions", pd.DataFrame())
            latest = st.session_state.get("sp_sla_latest", pd.DataFrame())
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Procedure Runs", f"{safe_int(summary.get('RUNS')):,}")
            c2.metric("Procedures", f"{safe_int(summary.get('PROCEDURES')):,}")
            c3.metric("Runtime SLA Breaches", f"{safe_int(summary.get('SLA_BREACHES')):,}", delta_color="inverse")
            c4.metric("Cost Regressions", f"{safe_int(summary.get('COST_BREACHES')):,}", delta_color="inverse")
            sla_source = str(st.session_state.get("sp_sla_source", "Source unavailable"))
            using_mart_sla = "mart:" in sla_source.lower()
            confidence = "allocated" if using_mart_sla or st.session_state.get("sp_sla_root_available") else "estimated"
            credit_note = (
                "credits come from FACT_PROCEDURE_RUN procedure attribution"
                if using_mart_sla
                else "credits are estimated from warehouse size, elapsed seconds, and cloud services credits"
            )
            defer_source_note(metric_confidence_label(confidence), sla_source, f"{credit_note}.")
            if exceptions.empty:
                st.success("No procedure runtime or cost regressions crossed the default thresholds.")
            else:
                st.warning("Procedure SLA/cost regressions detected. Review these before the next scheduled task graph run.")
                render_priority_dataframe(
                    exceptions,
                    title="Procedure SLA and cost regressions",
                    priority_columns=[
                        "SIGNAL", "SEVERITY", "DATABASE_NAME", "SCHEMA_NAME",
                        "PROCEDURE_CONTEXT", "PROCEDURE_NAME", "ROOT_QUERY_ID",
                        "TOTAL_ELAPSED_SEC", "AVG_ELAPSED_SEC", "RUNTIME_CHANGE_PCT",
                        "EST_TOTAL_CREDITS", "COST_CHANGE_PCT", "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["SEVERITY", "RUNTIME_CHANGE_PCT", "COST_CHANGE_PCT"],
                    ascending=[True, False, False],
                    raw_label="All procedure SLA/cost exceptions",
                )
                download_csv(exceptions, "procedure_sla_cost_exceptions.csv")
                if st.button("Save Procedure SLA/Cost Findings to Action Queue", key="sp_sla_queue"):
                    try:
                        saved = _queue_procedure_reliability_findings(
                            session,
                            exceptions,
                            company=company,
                            source="Stored Procedures - SLA & Cost Watch",
                        )
                        st.success(f"Saved {saved} procedure SLA/cost finding(s) to the action queue.")
                    except Exception as e:
                        st.error(f"Could not save procedure SLA/cost findings: {format_snowflake_error(e)}")
            if not latest.empty and not st.session_state.get("exceptions_only_mode"):
                latest_cols = [
                    col for col in [
                        "DATABASE_NAME", "SCHEMA_NAME", "PROCEDURE_CONTEXT",
                        "PROCEDURE_NAME", "ROOT_QUERY_ID", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                        "TOTAL_ELAPSED_SEC", "AVG_ELAPSED_SEC", "RUNTIME_CHANGE_PCT",
                        "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "COST_CHANGE_PCT",
                        "DOWNSTREAM_QUERY_COUNT", "START_TIME"
                    ] if col in latest.columns
                ]
                render_priority_dataframe(
                    latest[latest_cols],
                    title="Latest procedure runs",
                    priority_columns=[
                        "DATABASE_NAME", "SCHEMA_NAME", "PROCEDURE_CONTEXT",
                        "PROCEDURE_NAME", "ROOT_QUERY_ID", "WAREHOUSE_NAME",
                        "TOTAL_ELAPSED_SEC", "AVG_ELAPSED_SEC", "RUNTIME_CHANGE_PCT",
                        "EST_TOTAL_CREDITS", "COST_CHANGE_PCT", "START_TIME",
                    ],
                    sort_by=["TOTAL_ELAPSED_SEC", "EST_TOTAL_CREDITS"],
                    ascending=[False, False],
                    raw_label="All latest procedure runs",
                    max_rows=50,
                )

    if st.button("Load Stored Proc Usage", key="sp_load"):
        try:
            has_root_query_id = _query_history_has_root_query_id(session)
            qh_cols = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE", "BYTES_SCANNED", "CREDITS_USED_CLOUD_SERVICES"],
            ))
            root_expr = "COALESCE(q.root_query_id, q.query_id)" if has_root_query_id else "q.query_id"
            call_wh_size_expr = (
                "warehouse_size"
                if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
            )
            child_bytes_expr = (
                "q.bytes_scanned AS bytes_scanned"
                if "BYTES_SCANNED" in qh_cols else "0::NUMBER AS bytes_scanned"
            )
            child_cloud_expr = (
                "q.credits_used_cloud_services AS credits_used_cloud_services"
                if "CREDITS_USED_CLOUD_SERVICES" in qh_cols else "0::FLOAT AS credits_used_cloud_services"
            )
            df_sp = run_query(f"""
                WITH {build_metered_credit_cte(days_back=sp_days, include_recent=True)},
                calls AS (
                    SELECT query_id AS root_query_id,
                           user_name,
                           role_name,
                           warehouse_name,
                           database_name,
                           schema_name,
                           {call_wh_size_expr},
                           start_time,
                           REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) AS procedure_name,
                           SUBSTR(query_text, 1, 500) AS call_text
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE query_type = 'CALL'
                      AND start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      {proc_filters_plain}
                ),
                children AS (
                    SELECT {root_expr} AS root_query_id,
                           q.query_id,
                           q.query_type,
                           q.total_elapsed_time,
                           {child_bytes_expr},
                           {child_cloud_expr},
                           pqc.metered_credits,
                           SUBSTR(q.query_text, 1, 500) AS child_query_text
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      {proc_filters_q}
                )
                SELECT c.procedure_name,
                       c.database_name,
                       c.schema_name,
                       c.user_name,
                       c.role_name,
                       c.warehouse_name,
                       MAX(c.warehouse_size) AS warehouse_size,
                       c.call_text AS query_text,
                       COUNT(DISTINCT c.root_query_id) AS call_count,
                       COUNT(DISTINCT ch.query_id) AS downstream_query_count,
                       AVG(ch.total_elapsed_time)/1000 AS avg_elapsed_sec,
                       SUM(ch.total_elapsed_time)/1000 AS total_elapsed_sec,
                       ROUND(SUM(COALESCE(ch.metered_credits,0)), 4) AS metered_credits,
                       ROUND(SUM(COALESCE(ch.credits_used_cloud_services, 0)), 4) AS cloud_credits,
                       ROUND(SUM(ch.bytes_scanned)/POWER(1024,3), 2) AS gb_scanned,
                       MAX(c.start_time) AS last_call
                FROM calls c
                LEFT JOIN children ch ON c.root_query_id = ch.root_query_id
                GROUP BY c.procedure_name, c.database_name, c.schema_name, c.user_name, c.role_name, c.warehouse_name,
                         c.call_text
                ORDER BY metered_credits DESC, total_elapsed_sec DESC
                LIMIT 200
            """, ttl_key=f"stored_proc_usage_schema_context_v1_{company}_{sp_days}_{has_root_query_id}", tier="standard")
            st.session_state["spt_df_sp_tracker"] = df_sp
            st.session_state["spt_has_root_query_id"] = has_root_query_id
        except Exception as e:
            st.warning(f"Stored procedure cost data unavailable: {format_snowflake_error(e)}")

    if st.session_state.get("spt_df_sp_tracker") is not None and not st.session_state["spt_df_sp_tracker"].empty:
        df_sp = st.session_state["spt_df_sp_tracker"]
        if not st.session_state.get("spt_has_root_query_id", False):
            st.info("ROOT_QUERY_ID is not available in this Snowflake account. Showing outer CALL cost only.")
        total_credits = df_sp["METERED_CREDITS"].sum() + df_sp["CLOUD_CREDITS"].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Proc Signatures", df_sp["QUERY_TEXT"].nunique())
        c2.metric("Calls", f"{int(df_sp['CALL_COUNT'].sum()):,}")
        c3.metric("Child Queries", f"{int(df_sp['DOWNSTREAM_QUERY_COUNT'].sum()):,}")
        c4.metric("Credits", format_credits(total_credits))
        lineage_confidence = "allocated" if st.session_state.get("spt_has_root_query_id", False) else "estimated"
        defer_source_note(
            metric_confidence_label(lineage_confidence),
            freshness_note("QUERY_HISTORY"),
            "Child-query coverage depends on ROOT_QUERY_ID availability.",
        )
        df_sp["EST_COST"] = (df_sp["METERED_CREDITS"] + df_sp["CLOUD_CREDITS"]).apply(
            lambda x: credits_to_dollars(x, credit_price)
        )
        df_sp = _add_procedure_context_columns(df_sp)
        render_priority_dataframe(
            df_sp,
            title="Stored procedure cost drivers",
            priority_columns=[
                "DATABASE_NAME", "SCHEMA_NAME", "PROCEDURE_CONTEXT",
                "PROCEDURE_NAME", "USER_NAME", "WAREHOUSE_NAME", "CALL_COUNT",
                "DOWNSTREAM_QUERY_COUNT", "TOTAL_ELAPSED_SEC", "METERED_CREDITS",
                "CLOUD_CREDITS", "EST_COST", "LAST_CALL",
            ],
            sort_by=["EST_COST", "METERED_CREDITS", "TOTAL_ELAPSED_SEC"],
            ascending=[False, False, False],
            raw_label="All stored procedure usage rows",
            max_rows=50,
        )
        download_csv(df_sp, "stored_proc_usage.csv")

        st.divider()
        proc_options = df_sp["PROCEDURE_NAME"].fillna(df_sp["QUERY_TEXT"]).astype(str).tolist()
        selected_proc = st.selectbox("Open downstream query detail", proc_options, key="sp_downstream_select")
        if selected_proc and st.button("Load Downstream Queries", key="sp_downstream_load"):
            try:
                has_root_query_id = st.session_state.get("spt_has_root_query_id")
                if has_root_query_id is None:
                    has_root_query_id = _query_history_has_root_query_id(session)
                qh_cols = set(filter_existing_columns(
                    session,
                    "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                    ["WAREHOUSE_SIZE", "BYTES_SCANNED"],
                ))
                root_expr = "COALESCE(q.root_query_id, q.query_id)" if has_root_query_id else "q.query_id"
                child_wh_size_expr = (
                    "q.warehouse_size AS warehouse_size"
                    if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
                )
                child_gb_expr = (
                    "q.bytes_scanned/POWER(1024,3) AS gb_scanned"
                    if "BYTES_SCANNED" in qh_cols else "0::FLOAT AS gb_scanned"
                )
                proc_exact = sql_literal(selected_proc)
                proc_like = sql_literal('%' + selected_proc + '%')
                df_child = run_query(f"""
                WITH roots AS (
                    SELECT query_id AS root_query_id
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE query_type = 'CALL'
                      AND start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      {proc_filters_plain}
                      AND (REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) = {proc_exact}
                           OR query_text ILIKE {proc_like})
                )
                SELECT q.query_id, q.user_name, q.warehouse_name, {child_wh_size_expr}, q.execution_status,
                       q.database_name, q.schema_name, q.query_type, q.start_time,
                       q.total_elapsed_time/1000 AS elapsed_sec,
                       {child_gb_expr},
                       SUBSTR(q.query_text,1,4000) AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                JOIN roots r ON {root_expr} = r.root_query_id
                WHERE 1=1
                  {proc_filters_q}
                ORDER BY q.start_time
                LIMIT 500
                """, ttl_key=f"stored_proc_child_schema_context_v1_{company}_{sp_days}_{selected_proc}", tier="standard")
                render_query_drilldown(df_child, key="sp_child_queries", title="Stored procedure child-query drill-down")
            except Exception as e:
                st.info(f"Downstream detail unavailable: {format_snowflake_error(e)}")
