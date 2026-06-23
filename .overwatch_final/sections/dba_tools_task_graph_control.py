# sections/dba_tools_task_graph_control.py - Task Graph Control helpers.

import pandas as pd

from sections.dba_tools_common import _qualified_name, _query_context_expr
from utils import (
    filter_existing_columns,
    get_user_company_filter_clause,
    get_wh_filter_clause,
    sql_literal,
)


def _task_query_history_columns(session) -> dict[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "QUERY_TAG"],
    ))
    return {
        "warehouse_size_expr": (
            "warehouse_size AS warehouse_size"
            if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
        ),
        "query_tag_expr": (
            "query_tag AS query_tag"
            if "QUERY_TAG" in qh_cols else "NULL::VARCHAR AS query_tag"
        ),
        "task_indicator": (
            "query_tag IS NOT NULL OR LOWER(query_text) LIKE '%execute task%'"
            if "QUERY_TAG" in qh_cols else "LOWER(query_text) LIKE '%execute task%'"
        ),
    }


def _task_running_queries_sql(
    company: str,
    qh_warehouse_size_expr: str,
    qh_query_tag_expr: str,
    qh_task_indicator: str,
) -> str:
    return f"""
        SELECT query_id, database_name, schema_name, {_query_context_expr()},
               user_name, warehouse_name, {qh_warehouse_size_expr}, execution_status,
               start_time,
               DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) AS elapsed_sec,
               {qh_query_tag_expr},
               SUBSTR(query_text, 1, 400) AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('hours', -2, CURRENT_TIMESTAMP())
          AND UPPER(execution_status) IN ('RUNNING','QUEUED','BLOCKED')
          {get_wh_filter_clause("warehouse_name")}
          {get_user_company_filter_clause("user_name", company)}
          AND ({qh_task_indicator})
        ORDER BY start_time DESC
        LIMIT 200
    """


def _cancel_task_graph_sql(graph_run_group_id: str) -> str:
    return f"SELECT SYSTEM$CANCEL_TASK_GRAPH({sql_literal(str(graph_run_group_id))})"


def _cancel_task_query_sql(query_id: str) -> str:
    return f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(str(query_id))})"


def _task_fqn(row_or_parts) -> str:
    if isinstance(row_or_parts, (pd.Series, dict)):
        return _qualified_name(
            row_or_parts.get("DATABASE_NAME", ""),
            row_or_parts.get("SCHEMA_NAME", ""),
            row_or_parts.get("NAME", ""),
        )
    parts = list(row_or_parts or [])
    return _qualified_name(*(parts[:3]))


def _root_tasks_frame(df_tasks: pd.DataFrame) -> pd.DataFrame:
    if df_tasks is None or df_tasks.empty:
        return pd.DataFrame()
    if "PREDECESSORS" not in df_tasks.columns:
        return df_tasks
    predecessors = df_tasks["PREDECESSORS"].fillna("").astype(str).str.strip()
    return df_tasks[predecessors.isin(["", "[]", "None", "nan"])].copy()


def _child_tasks_for_root(df_tasks: pd.DataFrame, root_name: str) -> pd.DataFrame:
    if df_tasks is None or df_tasks.empty or "PREDECESSORS" not in df_tasks.columns:
        return pd.DataFrame()
    return df_tasks[
        df_tasks["PREDECESSORS"].fillna("").astype(str).str.contains(str(root_name), na=False)
    ].copy()


def _normalize_task_history_for_dag(df_hist: pd.DataFrame, task_names: list[str]) -> pd.DataFrame:
    if df_hist is None or df_hist.empty:
        return pd.DataFrame()
    frame = df_hist.copy()
    if "DURATION_SEC" in frame.columns:
        frame = frame.rename(columns={"DURATION_SEC": "LAST_DURATION_SEC"})
    if "NAME" not in frame.columns and "TASK_NAME" in frame.columns:
        frame = frame.rename(columns={"TASK_NAME": "NAME"})
    if "NAME" not in frame.columns:
        return pd.DataFrame()
    frame = frame[frame["NAME"].astype(str).isin([str(name) for name in task_names])].copy()
    if "STATE" in frame.columns:
        frame = frame.rename(columns={"STATE": "LAST_RUN_STATE"})
    if "ERROR_MESSAGE" in frame.columns:
        frame = frame.rename(columns={"ERROR_MESSAGE": "LAST_ERROR"})
    if "SCHEDULED_TIME" in frame.columns:
        frame = frame.rename(columns={"SCHEDULED_TIME": "LAST_RUN_TIME"})
    if not frame.empty and "LAST_RUN_TIME" in frame.columns:
        frame = frame.sort_values("LAST_RUN_TIME", ascending=False)
    if not frame.empty:
        frame = frame.drop_duplicates("NAME")
    return frame


def _build_dag_view_frame(df_tasks: pd.DataFrame, df_hist: pd.DataFrame, root_task: str) -> pd.DataFrame:
    if df_tasks is None or df_tasks.empty or "NAME" not in df_tasks.columns:
        return pd.DataFrame()
    root_mask = df_tasks["NAME"].astype(str) == str(root_task)
    pred = (
        df_tasks["PREDECESSORS"].astype(str)
        if "PREDECESSORS" in df_tasks.columns
        else pd.Series(index=df_tasks.index, dtype=str)
    )
    df_dag = df_tasks[root_mask | pred.str.contains(str(root_task), na=False)].copy()
    if df_dag.empty or "NAME" not in df_dag.columns:
        return df_dag
    task_names = [str(v) for v in df_dag["NAME"].dropna().unique().tolist()]
    hist = _normalize_task_history_for_dag(df_hist, task_names)
    if not hist.empty and "NAME" in hist.columns:
        df_dag = df_dag.merge(hist, how="left", on="NAME")
    return df_dag
