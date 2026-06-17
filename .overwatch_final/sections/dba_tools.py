# sections/dba_tools.py - DBA admin toolkit
# -----------------------------------------------------------------------------
# Specialist workflows are selected by group so only one guarded tool renders at a time.
# -----------------------------------------------------------------------------
from html import escape as html_escape

import streamlit as st
import pandas as pd
from utils import (
    get_session, safe_sql, format_credits, download_csv,
    get_wh_filter_clause, get_db_filter_clause, get_user_filter_clause,
    get_active_company, get_active_environment, company_value_allowed,
    run_query, run_query_or_raise, sql_literal, safe_identifier,
    format_snowflake_error,
    run_compatibility_checks,
    build_cost_formula_audit, filter_existing_columns, build_task_history_sql,
    admin_button_disabled,
    log_admin_action,
    show_to_df, first_existing_column, ensure_column_alias,
    scope_warehouse_names, scope_metadata_df, load_task_inventory,
    load_live_task_runs, load_database_options, load_schema_options,
    load_warehouse_inventory, build_unclassified_assets_sql,
    safe_float, safe_int, render_ranked_bar_chart, day_window_selectbox,
    render_chart_with_data_toggle,
    defer_source_note,
    build_schema_migration_contract, build_schema_migration_status_sql,
)
from config import (
    ALERT_DB, ALERT_SCHEMA, ALERT_TABLE,
    ACTION_QUEUE_TABLE,
)
from sections.navigation import apply_navigation_state
from utils.dba_tool_catalog import (
    DBA_TOOL_FOCUS_GROUPS,
    DBA_TOOL_FOCUS_HINTS,
    DBA_TOOL_GROUPS,
    SCALE_OPTS as _SCALE_OPTS,
    SIZE_OPTS as _SIZE_OPTS,
    SIZE_SQL as _SIZE_SQL,
    TASK_GRAPH_CONTROL_PANES,
    WH_PARAM_HELP as _WH_PARAM_HELP,
)
from utils.workflows import render_priority_dataframe, render_workflow_selector
from sections.shell_helpers import render_shell_snapshot
from sections.shell_helpers import render_setup_health_board


def _load_button(label, key):
    return st.button(label, key=key)


SCHEMA_COMPARE_OBJECT_COVERAGE = (
    "TABLE",
    "VIEW",
    "MATERIALIZED VIEW",
    "DYNAMIC TABLE",
    "EXTERNAL TABLE",
    "STAGE",
    "FILE FORMAT",
    "PIPE",
    "STREAM",
    "TASK",
    "SEQUENCE",
    "FUNCTION",
    "PROCEDURE",
    "MASKING POLICY",
    "ROW ACCESS POLICY",
    "TAG",
)

DATA_COMPARE_EXECUTION_STAGES = (
    "metadata inventory",
    "row count",
    "explicit-column HASH_AGG",
    "bucket isolate",
    "forensic diff SQL",
)


def _typed_confirmation(prompt: str, expected: str, key: str) -> bool:
    entered = st.text_input(prompt, key=key, placeholder=expected)
    return str(st.session_state.get(key) or entered or "").strip() == expected


def _require_typed_confirmation(confirmed: bool, expected: str) -> bool:
    if confirmed:
        return True
    st.warning(f"Type `{expected}` exactly before running this action.")
    return False


ACCOUNT_PARAMETER_ADMIN_ROLES = {
    "ACCOUNTADMIN",
    "SNOW_ACCOUNTADMINS",
}


def _current_role_allows_alter_account(role: str | None = None) -> bool:
    """Return whether the active caller role is allowed to run ALTER ACCOUNT."""
    current_role = str(
        st.session_state.get("_overwatch_current_role", "") if role is None else role
    ).strip().upper()
    return current_role in ACCOUNT_PARAMETER_ADMIN_ROLES


def _scope_warehouse_names(df: pd.DataFrame, name_col: str = "name") -> pd.DataFrame:
    """Apply ALFA/Trexis warehouse visibility to SHOW-style result sets."""
    return scope_warehouse_names(df, name_col=name_col, company=get_active_company())


def _scope_metadata_df(df: pd.DataFrame) -> pd.DataFrame:
    """Apply ALFA/Trexis visibility to SHOW-style metadata result sets."""
    return scope_metadata_df(df, company=get_active_company())


def _select_option(
    label: str,
    options: list[str],
    key: str,
    fallback: str = "",
    *,
    allow_current_outside_options: bool = True,
) -> str:
    choices = list(options or [])
    current = str(st.session_state.get(key) or fallback or "").strip()
    if choices:
        if current and current not in choices:
            if allow_current_outside_options:
                choices = [current] + choices
            else:
                current = fallback if fallback in choices else choices[0]
                st.session_state[key] = current
        index = choices.index(current) if current in choices else 0
        return str(st.selectbox(label, choices, index=index, key=key))
    return str(st.text_input(label, value=current or fallback, key=key))


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _qualified_name(*parts: str) -> str:
    return ".".join(_quote_identifier(part) for part in parts if str(part or "").strip())


def _as_bool(value, default: bool = False) -> bool:
    if value is None or str(value).lower() in ("", "nan", "none"):
        return default
    return str(value).strip().lower() in ("true", "yes", "1", "on")


def _as_int(value, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _query_context_expr() -> str:
    return """
        CASE
            WHEN database_name IS NULL OR TRIM(database_name) = '' THEN 'NO DATABASE CONTEXT'
            WHEN schema_name IS NULL OR TRIM(schema_name) = '' THEN database_name
            ELSE database_name || '.' || schema_name
        END AS query_context
    """


def _prioritize_query_context(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    frame = df.copy()
    if "QUERY_CONTEXT" not in frame.columns and "DATABASE_NAME" in frame.columns:
        db = frame["DATABASE_NAME"].fillna("").astype(str).str.strip()
        schema = (
            frame["SCHEMA_NAME"].fillna("").astype(str).str.strip()
            if "SCHEMA_NAME" in frame.columns else pd.Series([""] * len(frame), index=frame.index)
        )
        frame["QUERY_CONTEXT"] = db.where(db != "", "NO DATABASE CONTEXT")
        both = (db != "") & (schema != "")
        frame.loc[both, "QUERY_CONTEXT"] = db[both] + "." + schema[both]
    first_cols = [
        "QUERY_ID", "QUERY_CONTEXT", "DATABASE_NAME", "SCHEMA_NAME",
        "EXECUTION_STATUS", "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
    ]
    ordered = [col for col in first_cols if col in frame.columns]
    ordered.extend([col for col in frame.columns if col not in ordered])
    return frame[ordered]


def _is_unknown_setting(value) -> bool:
    return value is None or str(value).strip().lower() in ("", "nan", "none", "null")


def _warehouse_size_sql(value) -> str:
    text = str(value or "").strip()
    if text in _SIZE_SQL:
        return _SIZE_SQL[text]
    compact = text.upper().replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "XSMALL": "XSMALL",
        "SMALL": "SMALL",
        "MEDIUM": "MEDIUM",
        "LARGE": "LARGE",
        "XLARGE": "XLARGE",
        "XXLARGE": "XXLARGE",
        "2XLARGE": "XXLARGE",
        "XXXLARGE": "XXXLARGE",
        "3XLARGE": "XXXLARGE",
        "X4LARGE": "X4LARGE",
        "4XLARGE": "X4LARGE",
        "X5LARGE": "X5LARGE",
        "5XLARGE": "X5LARGE",
        "X6LARGE": "X6LARGE",
        "6XLARGE": "X6LARGE",
    }
    return aliases.get(compact, compact or "XSMALL")


def _normalize_warehouse_setting(param: str, value) -> str:
    param = str(param or "").upper()
    if param == "WAREHOUSE_SIZE":
        return _warehouse_size_sql(value)
    if param in {"AUTO_RESUME", "ENABLE_QUERY_ACCELERATION"}:
        return "TRUE" if _as_bool(value) else "FALSE"
    if param == "SCALING_POLICY":
        return str(value or "STANDARD").upper()
    return str(_as_int(value, 0))


def _warehouse_setting_risk(param: str, current_sql: str, requested_sql: str) -> str:
    param = str(param or "").upper()
    if param == "WAREHOUSE_SIZE":
        return "Validate queue, spill, p95 runtime, and cost drivers before resizing."
    if param == "AUTO_SUSPEND" and requested_sql == "0":
        return "High cost risk: warehouse will never auto-suspend."
    if param == "AUTO_SUSPEND" and _as_int(requested_sql, 0) > 600:
        return "Cost risk: auto-suspend is above the 10-minute DBA guardrail."
    if param == "AUTO_RESUME" and requested_sql == "FALSE":
        return "Availability risk: users may see failures until the warehouse is resumed manually."
    if param == "MIN_CLUSTER_COUNT" and _as_int(requested_sql, 1) > 1:
        return "High cost risk: extra clusters can run continuously."
    if param == "MAX_CLUSTER_COUNT" and _as_int(requested_sql, 1) > 1:
        return "Burst cost risk: multi-cluster scaling can multiply credit burn."
    if param == "ENABLE_QUERY_ACCELERATION" and requested_sql == "TRUE":
        return "Serverless cost risk: QAS can add spend outside warehouse metering."
    if param == "QUERY_ACCELERATION_MAX_SCALE_FACTOR" and _as_int(requested_sql, 0) == 0:
        return "Serverless cost risk: QAS scale factor is unlimited."
    if param == "STATEMENT_TIMEOUT_IN_SECONDS" and requested_sql == "0":
        return "Runaway query risk: statements have no warehouse-level timeout."
    if param == "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS" and requested_sql == "0":
        return "Queue risk: statements can wait indefinitely."
    if param == "MAX_CONCURRENCY_LEVEL" and _as_int(requested_sql, 8) > 8:
        return "Pressure risk: higher concurrency can increase spill and p95 runtime."
    return "Review workload impact and status telemetry before applying."


def _warehouse_setting_review_gate(param: str, current_sql: str, requested_sql: str) -> dict:
    """Return review evidence for one changed warehouse setting."""
    param = str(param or "").upper()
    if param in {"STATEMENT_TIMEOUT_IN_SECONDS", "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"}:
        if requested_sql == "0":
            decision = "Timeout guardrail disabled"
            proof = "24h query runtime, queue, failure, and owner SLA telemetry plus rollback SQL."
            verify = "Watch for long-running or indefinitely queued queries after the change."
        elif current_sql == "0" or _as_int(requested_sql, 0) < _as_int(current_sql, 0):
            decision = "Timeout tightened"
            proof = "Representative workload runtime, queued-time distribution, owner SLA, and rollback SQL."
            verify = "Confirm expected queries are not cancelled or timed out after the change."
        else:
            decision = "Timeout loosened"
            proof = "Business reason for longer running/queued statements, recent failures, and rollback SQL."
            verify = "Confirm long-running statements remain intentional and queue pressure does not grow."
        return {
            "REVIEW_GATE": "Runaway/queue control",
            "REVIEW_DECISION": decision,
            "PROOF_REQUIRED": proof,
            "VERIFY_AFTER_CHANGE": verify,
        }
    if param in {"WAREHOUSE_SIZE", "MIN_CLUSTER_COUNT", "MAX_CLUSTER_COUNT", "SCALING_POLICY", "MAX_CONCURRENCY_LEVEL"}:
        return {
            "REVIEW_GATE": "Capacity control",
            "REVIEW_DECISION": "Capacity or concurrency setting",
            "PROOF_REQUIRED": "Queue, spill, p95 runtime, credit impact, owner route, and rollback SQL.",
            "VERIFY_AFTER_CHANGE": "Compare queue, spill, p95 runtime, failures, and credits against the baseline window.",
        }
    if param in {"AUTO_SUSPEND", "AUTO_RESUME"}:
        return {
            "REVIEW_GATE": "Availability/cost control",
            "REVIEW_DECISION": "Suspend/resume policy",
            "PROOF_REQUIRED": "Idle burn, service sensitivity, auto-resume behavior, owner route, and rollback SQL.",
            "VERIFY_AFTER_CHANGE": "Confirm idle credits fall without workload failures or manual resume incidents.",
        }
    if param in {"ENABLE_QUERY_ACCELERATION", "QUERY_ACCELERATION_MAX_SCALE_FACTOR"}:
        return {
            "REVIEW_GATE": "Serverless cost control",
            "REVIEW_DECISION": "Query Acceleration Service setting",
            "PROOF_REQUIRED": "Eligible query evidence, QAS credit exposure, owner route, and rollback SQL.",
            "VERIFY_AFTER_CHANGE": "Track QAS credits, query runtime, and warehouse credits for the same workload.",
        }
    return {
        "REVIEW_GATE": "DBA review",
        "REVIEW_DECISION": "Warehouse setting change",
        "PROOF_REQUIRED": "Current setting, requested setting, owner route, rollback SQL, and post-change telemetry.",
        "VERIFY_AFTER_CHANGE": "Compare the affected telemetry after the next complete workload window.",
    }


def _warehouse_settings_preflight_sql(warehouse_name: str) -> str:
    safe_wh = _quote_identifier(warehouse_name)
    wh_lit = sql_literal(warehouse_name, 300)
    return f"""-- Read-only pre-flight before ALTER WAREHOUSE
SELECT CURRENT_USER() AS current_user,
       CURRENT_ROLE() AS current_role,
       CURRENT_WAREHOUSE() AS current_warehouse;

SHOW GRANTS ON WAREHOUSE {safe_wh};

SHOW WAREHOUSES LIKE {wh_lit};

SELECT warehouse_name,
       SUM(credits_used) AS credits_7d,
       SUM(credits_used_compute) AS compute_credits_7d,
       SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits_7d
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
  AND warehouse_name = {wh_lit}
GROUP BY warehouse_name;

SELECT warehouse_name,
       COUNT(*) AS queries_24h,
       SUM(IFF(execution_status = 'FAILED', 1, 0)) AS failed_queries_24h,
       AVG(total_elapsed_time) / 1000 AS avg_elapsed_sec_24h,
       APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95) AS p95_elapsed_sec_24h
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
  AND warehouse_name = {wh_lit}
GROUP BY warehouse_name;

-- Confirm MODIFY privilege, status telemetry, workload impact, and rollback plan before applying.
"""


def _build_warehouse_setting_plan(
    warehouse_name: str,
    current_row: pd.Series,
    requested_settings: dict,
) -> dict:
    """Build a reviewed ALTER WAREHOUSE plan with rollback and audit context."""
    specs = [
        ("WAREHOUSE_SIZE", "size"),
        ("AUTO_SUSPEND", "auto_suspend"),
        ("AUTO_RESUME", "auto_resume"),
        ("STATEMENT_TIMEOUT_IN_SECONDS", "statement_timeout_in_seconds"),
        ("STATEMENT_QUEUED_TIMEOUT_IN_SECONDS", "statement_queued_timeout_in_seconds"),
        ("MAX_CONCURRENCY_LEVEL", "max_concurrency_level"),
        ("SCALING_POLICY", "scaling_policy"),
        ("MIN_CLUSTER_COUNT", "min_cluster_count"),
        ("MAX_CLUSTER_COUNT", "max_cluster_count"),
        ("ENABLE_QUERY_ACCELERATION", "enable_query_acceleration"),
        ("QUERY_ACCELERATION_MAX_SCALE_FACTOR", "query_acceleration_max_scale_factor"),
    ]
    changes = []
    skipped = []
    for param, column in specs:
        if param not in requested_settings:
            continue
        current_raw = current_row.get(column, None)
        if _is_unknown_setting(current_raw):
            skipped.append({
                "PARAMETER": param,
                "REASON": "Current value unavailable from SHOW WAREHOUSES; refresh metadata before changing this setting.",
            })
            continue
        current_sql = _normalize_warehouse_setting(param, current_raw)
        requested_sql = _normalize_warehouse_setting(param, requested_settings.get(param))
        if current_sql != requested_sql:
            gate = _warehouse_setting_review_gate(param, current_sql, requested_sql)
            changes.append({
                "PARAMETER": param,
                "CURRENT": current_sql,
                "REQUESTED": requested_sql,
                "RISK": _warehouse_setting_risk(param, current_sql, requested_sql),
                **gate,
            })

    safe_wh = _quote_identifier(warehouse_name)
    assignments = [f"{row['PARAMETER']} = {row['REQUESTED']}" for row in changes]
    rollback_assignments = [f"{row['PARAMETER']} = {row['CURRENT']}" for row in changes]
    alter_sql = ""
    rollback_sql = ""
    if assignments:
        alter_sql = f"ALTER WAREHOUSE {safe_wh} SET\n    " + "\n    ".join(assignments) + ";"
        rollback_sql = f"ALTER WAREHOUSE {safe_wh} SET\n    " + "\n    ".join(rollback_assignments) + ";"

    context_lines = [
        f"Warehouse: {warehouse_name}",
        "Change count: " + str(len(changes)),
    ]
    for row in changes:
        context_lines.append(
            f"{row['PARAMETER']}: {row['CURRENT']} -> {row['REQUESTED']} | "
            f"{row['REVIEW_GATE']} | {row['RISK']} | Proof: {row['PROOF_REQUIRED']}"
        )
    if rollback_sql:
        context_lines.append("Rollback plan: " + rollback_sql.replace("\n", " "))

    return {
        "warehouse": warehouse_name,
        "changes": changes,
        "skipped": skipped,
        "changes_df": pd.DataFrame(changes),
        "skipped_df": pd.DataFrame(skipped),
        "alter_sql": alter_sql,
        "rollback_sql": rollback_sql,
        "preflight_sql": _warehouse_settings_preflight_sql(warehouse_name),
        "confirmation_text": f"ALTER {warehouse_name}",
        "control_context": "\n".join(context_lines)[:4000],
    }


def _table_exists(session, db: str, schema: str, table: str):
    try:
        db_ident = safe_identifier(db)
        row = session.sql(f"""
            SELECT COUNT(*) AS CNT
            FROM {db_ident}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = {sql_literal(schema.upper())}
              AND TABLE_NAME = {sql_literal(table.upper())}
        """).collect()[0]
        return int(row["CNT"]) > 0
    except Exception:
        return None


def _task_exists(session, db: str, schema: str, task_name: str):
    try:
        schema_fqn = _qualified_name(db, schema)
        rows = session.sql(
            f"SHOW TASKS LIKE {sql_literal(task_name.upper())} IN SCHEMA {schema_fqn}"
        ).collect()
        return len(rows) > 0
    except Exception:
        return None


def _schema_compare_show_objects_sql(database: str, schema: str) -> str:
    """Return the Snowflake command that lists every object visible in a schema."""
    return f"SHOW OBJECTS IN SCHEMA {_qualified_name(database, schema)}"


def _schema_compare_columns_sql(database: str, schema: str) -> str:
    """Return account-level column metadata so object compare also catches column drift."""
    database_lit = sql_literal(database, 300)
    schema_lit = sql_literal(schema, 300)
    return f"""
SELECT
    'COLUMN' AS object_type,
    c.table_name || '.' || c.column_name AS object_name,
    c.table_name AS parent_object_name,
    COALESCE(t.table_type, 'TABLE') AS parent_object_type,
    c.ordinal_position AS ordinal_position,
    c.data_type AS data_type,
    c.character_maximum_length AS character_maximum_length,
    c.numeric_precision AS numeric_precision,
    c.numeric_scale AS numeric_scale,
    c.datetime_precision AS datetime_precision,
    c.is_nullable AS is_nullable,
    c.column_default AS column_default,
    c.comment AS comment,
    c.data_type
        || COALESCE('(' || c.character_maximum_length::VARCHAR || ')', '')
        || COALESCE(' precision=' || c.numeric_precision::VARCHAR, '')
        || COALESCE(' scale=' || c.numeric_scale::VARCHAR, '')
        || COALESCE(' datetime_precision=' || c.datetime_precision::VARCHAR, '')
        || ' nullable=' || COALESCE(c.is_nullable, 'UNKNOWN')
        || COALESCE(' default=' || c.column_default, '') AS object_signature
FROM SNOWFLAKE.ACCOUNT_USAGE.COLUMNS c
LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.TABLES t
  ON c.table_id = t.table_id
 AND t.deleted IS NULL
WHERE UPPER(c.table_catalog) = UPPER({database_lit})
  AND UPPER(c.table_schema) = UPPER({schema_lit})
  AND c.deleted IS NULL
""".strip()


def _schema_compare_normalize_kind(value: object) -> str:
    text = str(value or "OBJECT").strip().upper().replace("_", " ")
    aliases = {
        "BASE TABLE": "TABLE",
        "TEMPORARY TABLE": "TABLE",
        "TRANSIENT TABLE": "TABLE",
        "MATERIALIZED VIEW": "MATERIALIZED VIEW",
        "FILE FORMAT": "FILE FORMAT",
        "DYNAMIC TABLE": "DYNAMIC TABLE",
        "EXTERNAL TABLE": "EXTERNAL TABLE",
        "ROW ACCESS POLICY": "ROW ACCESS POLICY",
        "MASKING POLICY": "MASKING POLICY",
    }
    return aliases.get(text, text or "OBJECT")


def _schema_compare_get_ddl_type(object_type: object) -> str:
    kind = _schema_compare_normalize_kind(object_type)
    mapping = {
        "DYNAMIC TABLE": "DYNAMIC_TABLE",
        "EXTERNAL TABLE": "EXTERNAL_TABLE",
        "EVENT TABLE": "TABLE",
        "FILE FORMAT": "FILE_FORMAT",
        "MATERIALIZED VIEW": "MATERIALIZED_VIEW",
        "MASKING POLICY": "MASKING_POLICY",
        "ROW ACCESS POLICY": "ROW_ACCESS_POLICY",
    }
    if kind in mapping:
        return mapping[kind]
    if "PROCEDURE" in kind:
        return "PROCEDURE"
    if "FUNCTION" in kind:
        return "FUNCTION"
    if "VIEW" in kind:
        return "VIEW"
    if "TABLE" in kind:
        return "TABLE"
    if "STAGE" in kind:
        return "STAGE"
    if "SEQUENCE" in kind:
        return "SEQUENCE"
    if "PIPE" in kind:
        return "PIPE"
    if "STREAM" in kind:
        return "STREAM"
    if "TASK" in kind:
        return "TASK"
    if "TAG" in kind:
        return "TAG"
    return kind.replace(" ", "_")


def _first_present_column(df: pd.DataFrame, *candidates: str) -> str | None:
    columns = {str(col).upper(): str(col) for col in df.columns}
    for candidate in candidates:
        if str(candidate).upper() in columns:
            return columns[str(candidate).upper()]
    return None


def _schema_compare_normalize_show_objects(
    df: pd.DataFrame | None,
    *,
    database: str,
    schema: str,
    side: str,
) -> pd.DataFrame:
    """Normalize SHOW OBJECTS output into a compare-ready object inventory."""
    empty_cols = [
        "OBJECT_TYPE", "OBJECT_NAME", "PARENT_OBJECT_NAME", "PARENT_OBJECT_TYPE",
        "OBJECT_SIGNATURE", "OBJECT_DETAIL", "ROW_COUNT", "BYTES", "PRESENT",
        "SOURCE_SIDE", "DATABASE_NAME", "SCHEMA_NAME", "DATA_TYPE",
        "CHARACTER_MAXIMUM_LENGTH", "NUMERIC_PRECISION", "NUMERIC_SCALE",
        "DATETIME_PRECISION", "IS_NULLABLE", "COLUMN_DEFAULT", "COLUMN_COMMENT",
        "ORDINAL_POSITION",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=empty_cols)
    frame = df.copy()
    name_col = _first_present_column(frame, "NAME", "OBJECT_NAME")
    kind_col = _first_present_column(frame, "KIND", "OBJECT_TYPE", "TYPE")
    rows_col = _first_present_column(frame, "ROWS", "ROW_COUNT")
    bytes_col = _first_present_column(frame, "BYTES")
    comment_col = _first_present_column(frame, "COMMENT")
    owner_col = _first_present_column(frame, "OWNER")
    created_col = _first_present_column(frame, "CREATED_ON", "CREATED")

    rows = []
    for _, item in frame.iterrows():
        name = str(item.get(name_col, "") if name_col else "").strip()
        if not name:
            continue
        object_type = _schema_compare_normalize_kind(item.get(kind_col, "OBJECT") if kind_col else "OBJECT")
        row_count = safe_int(item.get(rows_col, 0) if rows_col else 0)
        bytes_value = safe_int(item.get(bytes_col, 0) if bytes_col else 0)
        owner = str(item.get(owner_col, "") if owner_col else "").strip()
        comment = str(item.get(comment_col, "") if comment_col else "").strip()
        created = str(item.get(created_col, "") if created_col else "").strip()
        detail_parts = [f"type={object_type}"]
        if owner:
            detail_parts.append(f"owner={owner}")
        if comment:
            detail_parts.append(f"comment={comment}")
        if created:
            detail_parts.append(f"created={created}")
        rows.append({
            "OBJECT_TYPE": object_type,
            "OBJECT_NAME": name,
            "PARENT_OBJECT_NAME": "",
            "PARENT_OBJECT_TYPE": "",
            "OBJECT_SIGNATURE": object_type,
            "OBJECT_DETAIL": "; ".join(detail_parts),
            "ROW_COUNT": row_count,
            "BYTES": bytes_value,
            "PRESENT": True,
            "SOURCE_SIDE": side,
            "DATABASE_NAME": database,
            "SCHEMA_NAME": schema,
            "DATA_TYPE": "",
            "CHARACTER_MAXIMUM_LENGTH": "",
            "NUMERIC_PRECISION": "",
            "NUMERIC_SCALE": "",
            "DATETIME_PRECISION": "",
            "IS_NULLABLE": "",
            "COLUMN_DEFAULT": "",
            "COLUMN_COMMENT": "",
            "ORDINAL_POSITION": "",
        })
    return pd.DataFrame(rows, columns=empty_cols)


def _schema_compare_normalize_columns(
    df: pd.DataFrame | None,
    *,
    database: str,
    schema: str,
    side: str,
) -> pd.DataFrame:
    """Normalize account column metadata into compare-ready child objects."""
    empty_cols = [
        "OBJECT_TYPE", "OBJECT_NAME", "PARENT_OBJECT_NAME", "PARENT_OBJECT_TYPE",
        "OBJECT_SIGNATURE", "OBJECT_DETAIL", "ROW_COUNT", "BYTES", "PRESENT",
        "SOURCE_SIDE", "DATABASE_NAME", "SCHEMA_NAME", "DATA_TYPE",
        "CHARACTER_MAXIMUM_LENGTH", "NUMERIC_PRECISION", "NUMERIC_SCALE",
        "DATETIME_PRECISION", "IS_NULLABLE", "COLUMN_DEFAULT", "COLUMN_COMMENT",
        "ORDINAL_POSITION",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=empty_cols)
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    rows = []
    for _, item in frame.iterrows():
        object_name = str(item.get("OBJECT_NAME", "") or "").strip()
        if not object_name:
            continue
        signature = str(item.get("OBJECT_SIGNATURE", "") or "").strip()
        parent_type = _schema_compare_normalize_kind(item.get("PARENT_OBJECT_TYPE", "TABLE"))
        detail_parts = [
            f"ordinal={item.get('ORDINAL_POSITION', '')}",
            f"type={item.get('DATA_TYPE', '')}",
            f"nullable={item.get('IS_NULLABLE', '')}",
        ]
        if str(item.get("COLUMN_DEFAULT", "") or "").strip():
            detail_parts.append(f"default={item.get('COLUMN_DEFAULT')}")
        if str(item.get("COMMENT", "") or "").strip():
            detail_parts.append(f"comment={item.get('COMMENT')}")
        rows.append({
            "OBJECT_TYPE": "COLUMN",
            "OBJECT_NAME": object_name,
            "PARENT_OBJECT_NAME": str(item.get("PARENT_OBJECT_NAME", "") or "").strip(),
            "PARENT_OBJECT_TYPE": parent_type,
            "OBJECT_SIGNATURE": signature,
            "OBJECT_DETAIL": "; ".join(str(part) for part in detail_parts if str(part).strip()),
            "ROW_COUNT": 0,
            "BYTES": 0,
            "PRESENT": True,
            "SOURCE_SIDE": side,
            "DATABASE_NAME": database,
            "SCHEMA_NAME": schema,
            "DATA_TYPE": str(item.get("DATA_TYPE", "") or "").strip(),
            "CHARACTER_MAXIMUM_LENGTH": item.get("CHARACTER_MAXIMUM_LENGTH", ""),
            "NUMERIC_PRECISION": item.get("NUMERIC_PRECISION", ""),
            "NUMERIC_SCALE": item.get("NUMERIC_SCALE", ""),
            "DATETIME_PRECISION": item.get("DATETIME_PRECISION", ""),
            "IS_NULLABLE": str(item.get("IS_NULLABLE", "") or "").strip(),
            "COLUMN_DEFAULT": str(item.get("COLUMN_DEFAULT", "") or "").strip(),
            "COLUMN_COMMENT": str(item.get("COMMENT", "") or "").strip(),
            "ORDINAL_POSITION": item.get("ORDINAL_POSITION", ""),
        })
    return pd.DataFrame(rows, columns=empty_cols)


def _schema_compare_inventory(
    objects_df: pd.DataFrame | None,
    columns_df: pd.DataFrame | None,
    *,
    database: str,
    schema: str,
    side: str,
) -> pd.DataFrame:
    frames = [
        _schema_compare_normalize_show_objects(objects_df, database=database, schema=schema, side=side),
        _schema_compare_normalize_columns(columns_df, database=database, schema=schema, side=side),
    ]
    inventory = pd.concat(frames, ignore_index=True)
    if inventory.empty:
        return inventory
    inventory["COMPARE_KEY"] = (
        inventory["OBJECT_TYPE"].fillna("").astype(str).str.upper()
        + "::"
        + inventory["OBJECT_NAME"].fillna("").astype(str).str.upper()
    )
    return inventory.drop_duplicates(subset=["COMPARE_KEY"], keep="first")


def _schema_compare_object_fqn(database: str, schema: str, object_name: str) -> str:
    return _qualified_name(database, schema, object_name)


def _schema_compare_numeric_text(value: object) -> str:
    try:
        if value is None or str(value).strip().lower() in {"", "nan", "none", "null"}:
            return ""
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    except Exception:
        return ""


def _schema_compare_column_type(row: pd.Series | dict, suffix: str) -> str:
    data_type = str(row.get(f"DATA_TYPE_{suffix}") or row.get("DATA_TYPE") or "").strip().upper()
    if not data_type:
        return "VARIANT"
    length = _schema_compare_numeric_text(
        row.get(f"CHARACTER_MAXIMUM_LENGTH_{suffix}") or row.get("CHARACTER_MAXIMUM_LENGTH")
    )
    precision = _schema_compare_numeric_text(
        row.get(f"NUMERIC_PRECISION_{suffix}") or row.get("NUMERIC_PRECISION")
    )
    scale = _schema_compare_numeric_text(
        row.get(f"NUMERIC_SCALE_{suffix}") or row.get("NUMERIC_SCALE")
    )
    datetime_precision = _schema_compare_numeric_text(
        row.get(f"DATETIME_PRECISION_{suffix}") or row.get("DATETIME_PRECISION")
    )
    if data_type in {"VARCHAR", "CHAR", "CHARACTER", "STRING", "TEXT", "BINARY"} and length:
        return f"{data_type}({length})"
    if data_type in {"NUMBER", "NUMERIC", "DECIMAL"} and precision and scale:
        return f"{data_type}({precision},{scale})"
    if data_type in {"NUMBER", "NUMERIC", "DECIMAL"} and precision:
        return f"{data_type}({precision})"
    if data_type.startswith("TIMESTAMP") and datetime_precision:
        return f"{data_type}({datetime_precision})"
    if data_type == "TIME" and datetime_precision:
        return f"{data_type}({datetime_precision})"
    return data_type


def _schema_compare_missing_column_ddl(
    row: pd.Series | dict,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
) -> str:
    status = str(row.get("COMPARE_STATUS") or "")
    suffix = "SOURCE" if status == "Only in source" else "TARGET"
    to_db, to_schema = (
        (target_db, target_schema)
        if status == "Only in source"
        else (source_db, source_schema)
    )
    object_name = str(row.get("OBJECT_NAME") or "").strip()
    parent_name = str(row.get("PARENT_OBJECT_NAME") or object_name.split(".", 1)[0]).strip()
    column_name = object_name.split(".", 1)[1].strip() if "." in object_name else object_name
    if not parent_name or not column_name:
        return ""
    table_fqn = _schema_compare_object_fqn(to_db, to_schema, parent_name)
    column_type = _schema_compare_column_type(row, suffix)
    nullable = str(row.get(f"IS_NULLABLE_{suffix}") or row.get("IS_NULLABLE") or "").strip().upper()
    default_value = str(row.get(f"COLUMN_DEFAULT_{suffix}") or row.get("COLUMN_DEFAULT") or "").strip()
    comment = str(row.get(f"COLUMN_COMMENT_{suffix}") or row.get("COLUMN_COMMENT") or "").strip()
    ddl_parts = [f"ALTER TABLE {table_fqn} ADD COLUMN {_quote_identifier(column_name)} {column_type}"]
    if default_value:
        ddl_parts.append(f"DEFAULT {default_value}")
    if nullable == "NO":
        ddl_parts.append("NOT NULL")
    add_column_sql = " ".join(ddl_parts) + ";"
    statements = [
        f"-- {object_name} is missing; review against existing data before executing.",
        add_column_sql,
    ]
    if comment:
        statements.append(
            f"COMMENT ON COLUMN {table_fqn}.{_quote_identifier(column_name)} IS {sql_literal(comment, 1000)};"
        )
    return "\n".join(statements)


def _schema_compare_missing_ddl(
    row: pd.Series | dict,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
) -> str:
    """Build direct DDL where safe, otherwise SQL that retrieves Snowflake DDL."""
    status = str(row.get("COMPARE_STATUS") or "")
    if status not in {"Only in source", "Only in target"}:
        return ""
    object_type = str(row.get("OBJECT_TYPE") or "OBJECT")
    object_name = str(row.get("OBJECT_NAME") or "").strip()
    if not object_name:
        return ""
    from_db, from_schema, to_db, to_schema = (
        (source_db, source_schema, target_db, target_schema)
        if status == "Only in source"
        else (target_db, target_schema, source_db, source_schema)
    )
    direction = (
        f"create in target {to_db}.{to_schema} from source {from_db}.{from_schema}"
        if status == "Only in source"
        else f"create in source {to_db}.{to_schema} from target {from_db}.{from_schema}"
    )
    from_schema_fqn = _qualified_name(from_db, from_schema)
    to_schema_fqn = _qualified_name(to_db, to_schema)

    if object_type == "COLUMN":
        return _schema_compare_missing_column_ddl(
            row,
            source_db=source_db,
            source_schema=source_schema,
            target_db=target_db,
            target_schema=target_schema,
        )

    ddl_type = _schema_compare_get_ddl_type(object_type)
    from_fqn = _schema_compare_object_fqn(from_db, from_schema, object_name)
    return (
        f"-- {object_type} {object_name} is missing; {direction}.\n"
        f"-- Review before executing. GET_DDL preserves source definition; REPLACE retargets fully qualified names.\n"
        f"SELECT REPLACE(GET_DDL({sql_literal(ddl_type)}, {sql_literal(from_fqn, 1000)}, TRUE), "
        f"{sql_literal(from_schema_fqn, 1000)}, {sql_literal(to_schema_fqn, 1000)}) AS DDL_STATEMENT;"
    )


def _schema_compare_fetch_missing_ddl_statements(
    ddl_rows: pd.DataFrame,
    *,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    max_objects: int = 100,
) -> pd.DataFrame:
    """Fetch actual GET_DDL output for missing objects and keep safe fallbacks."""
    if ddl_rows is None or ddl_rows.empty:
        return ddl_rows
    frame = ddl_rows.copy()
    statements: list[str] = []
    statuses: list[str] = []
    for idx, (_, row) in enumerate(frame.iterrows()):
        fallback = str(row.get("DDL_REVIEW_SQL") or "").strip()
        object_type = str(row.get("OBJECT_TYPE") or "").upper()
        if not fallback:
            statements.append("")
            statuses.append("No review needed")
            continue
        if object_type == "COLUMN":
            statements.append(fallback)
            statuses.append("Generated ADD COLUMN")
            continue
        if idx >= max_objects:
            statements.append(f"-- Definition fetch cap reached. Review manually:\n{fallback}")
            statuses.append("Manual object review required")
            continue
        try:
            result = run_query_or_raise(
                fallback,
                section="Schema Compare",
                ttl_key=f"schema_compare_get_ddl_{idx}_{source_db}_{source_schema}_{target_db}_{target_schema}",
                tier="metadata",
                use_cache=False,
                max_rows=5,
            )
            if result is not None and not result.empty:
                value = str(result.iloc[0].get("DDL_STATEMENT", "") or "").strip()
                if not value:
                    value = str(result.iloc[0, 0] or "").strip()
                if value:
                    statements.append(value.rstrip(";") + ";")
                    statuses.append("Fetched GET_DDL")
                    continue
        except Exception as exc:
            statuses.append(f"Manual object review required: {format_snowflake_error(exc)}")
            statements.append(f"-- Could not fetch GET_DDL automatically. Run manually:\n{fallback}")
            continue
        statements.append(f"-- Could not fetch object definition automatically. Review manually:\n{fallback}")
        statuses.append("Manual object review required")
    frame["DDL_STATEMENT"] = statements
    frame["DDL_STATUS"] = statuses
    return frame


def _schema_compare_ddl_script(
    ddl_rows: pd.DataFrame,
    *,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
) -> str:
    """Build a review-only DDL script for objects missing on one side of the compare."""
    if ddl_rows is None or ddl_rows.empty:
        return ""
    statements = [
        "-- OVERWATCH schema compare missing-object script",
        f"-- Source: {source_db}.{source_schema}",
        f"-- Target: {target_db}.{target_schema}",
        "-- Review dependencies, policies, grants, and environment-specific references before executing.",
    ]
    for _, row in ddl_rows.iterrows():
        statement = str(row.get("DDL_STATEMENT") or row.get("DDL_REVIEW_SQL") or "").strip()
        if not statement:
            continue
        object_type = str(row.get("OBJECT_TYPE") or "OBJECT").strip()
        object_name = str(row.get("OBJECT_NAME") or "").strip()
        compare_status = str(row.get("COMPARE_STATUS") or "").strip()
        if not statement.endswith(";"):
            statement += ";"
        statements.append(
            "\n".join([
                "",
                f"-- {compare_status}: {object_type} {object_name}",
                statement,
            ])
        )
    return "\n".join(statements).strip()


def _data_compare_tables_sql(database: str, schema: str) -> str:
    """Return data-bearing tables from Snowflake account metadata."""
    database_lit = sql_literal(database, 300)
    schema_lit = sql_literal(schema, 300)
    return f"""
SELECT
    table_name,
    table_type,
    row_count AS metadata_row_count,
    bytes AS metadata_bytes,
    created,
    last_altered
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
WHERE UPPER(table_catalog) = UPPER({database_lit})
  AND UPPER(table_schema) = UPPER({schema_lit})
  AND deleted IS NULL
  AND (
      UPPER(table_type) IN ('BASE TABLE', 'TRANSIENT TABLE', 'TEMPORARY TABLE', 'EXTERNAL TABLE', 'DYNAMIC TABLE', 'EVENT TABLE')
      OR UPPER(table_type) LIKE '%TABLE%'
      OR UPPER(COALESCE(is_dynamic, '')) = 'YES'
  )
ORDER BY table_name
""".strip()


def _data_compare_where_clause(raw_filter: object) -> str:
    """Return a bounded SELECT-only row filter clause."""
    text = str(raw_filter or "").strip()
    if not text:
        return ""
    upper = f" {text.upper()} "
    blocked = (";", "--", "/*", "*/", " DROP ", " ALTER ", " INSERT ", " UPDATE ", " DELETE ", " MERGE ", " COPY ", " CALL ")
    if any(token in upper for token in blocked):
        raise ValueError("Row filter can only contain one SELECT predicate. Remove comments, semicolons, or write operations.")
    return f"WHERE {text[:1200]}"


def _data_compare_parse_identifiers(value: object) -> list[str]:
    parts = []
    for raw in str(value or "").replace("\n", ",").split(","):
        text = raw.strip().strip('"')
        if not text:
            continue
        parts.append(safe_identifier(text).upper())
    return list(dict.fromkeys(parts))


def _data_compare_normalize_tables(df: pd.DataFrame | None) -> dict[str, dict]:
    if df is None or df.empty:
        return {}
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    name_col = _first_present_column(frame, "TABLE_NAME", "NAME")
    if not name_col:
        return {}
    result = {}
    for _, row in frame.iterrows():
        name = str(row.get(name_col, "") or "").strip()
        if not name:
            continue
        key = name.upper()
        result[key] = {
            "TABLE_NAME": name,
            "TABLE_TYPE": str(row.get("TABLE_TYPE", "") or "").strip(),
            "METADATA_ROW_COUNT": safe_int(row.get("METADATA_ROW_COUNT", row.get("ROW_COUNT", 0))),
            "METADATA_BYTES": safe_int(row.get("METADATA_BYTES", row.get("BYTES", 0))),
            "LAST_ALTERED": str(row.get("LAST_ALTERED", "") or ""),
        }
    return result


def _data_compare_column_rows(
    df: pd.DataFrame | None,
    table_name: str,
    excluded_columns: list[str] | None = None,
) -> list[dict]:
    if df is None or df.empty:
        return []
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    excluded = {str(col).upper() for col in (excluded_columns or [])}
    rows = []
    table_key = str(table_name or "").upper()
    for _, row in frame.iterrows():
        parent = str(row.get("PARENT_OBJECT_NAME", row.get("TABLE_NAME", "")) or "").strip()
        if parent.upper() != table_key:
            continue
        object_name = str(row.get("OBJECT_NAME", "") or "").strip()
        col_name = object_name.split(".", 1)[1] if "." in object_name else str(row.get("COLUMN_NAME", "") or "").strip()
        if not col_name or col_name.upper() in excluded:
            continue
        rows.append({
            "COLUMN_NAME": col_name,
            "COLUMN_KEY": col_name.upper(),
            "ORDINAL_POSITION": safe_int(row.get("ORDINAL_POSITION", 0)),
            "DATA_TYPE": str(row.get("DATA_TYPE", "") or "").strip().upper(),
            "COLUMN_TYPE": _schema_compare_column_type(row, ""),
            "IS_NULLABLE": str(row.get("IS_NULLABLE", "") or "").strip().upper(),
            "COLUMN_DEFAULT": str(row.get("COLUMN_DEFAULT", "") or "").strip(),
        })
    return sorted(rows, key=lambda item: (safe_int(item.get("ORDINAL_POSITION", 0)), str(item.get("COLUMN_NAME", ""))))


def _data_compare_column_signature(row: dict) -> str:
    return "|".join([
        str(row.get("COLUMN_TYPE", "")).upper(),
        str(row.get("IS_NULLABLE", "")).upper(),
        str(row.get("COLUMN_DEFAULT", "")),
    ])


def _data_compare_supported_hash_column(row: dict) -> bool:
    return str(row.get("DATA_TYPE", "") or "").upper() not in {"GEOGRAPHY", "GEOMETRY"}


def _build_data_compare_plan(
    source_tables: pd.DataFrame | None,
    target_tables: pd.DataFrame | None,
    source_columns: pd.DataFrame | None,
    target_columns: pd.DataFrame | None,
    *,
    excluded_columns: list[str] | None = None,
    table_filter: str = "",
) -> pd.DataFrame:
    source_table_map = _data_compare_normalize_tables(source_tables)
    target_table_map = _data_compare_normalize_tables(target_tables)
    filter_text = str(table_filter or "").strip().upper()
    table_names = sorted(set(source_table_map) | set(target_table_map))
    if filter_text:
        table_names = [name for name in table_names if filter_text in name]

    rows = []
    for table_key in table_names:
        source_meta = source_table_map.get(table_key, {})
        target_meta = target_table_map.get(table_key, {})
        table_name = str(source_meta.get("TABLE_NAME") or target_meta.get("TABLE_NAME") or table_key)
        source_present = bool(source_meta)
        target_present = bool(target_meta)
        source_cols = _data_compare_column_rows(source_columns, table_name, excluded_columns)
        target_cols = _data_compare_column_rows(target_columns, table_name, excluded_columns)
        source_col_map = {row["COLUMN_KEY"]: row for row in source_cols}
        target_col_map = {row["COLUMN_KEY"]: row for row in target_cols}
        source_col_keys = [row["COLUMN_KEY"] for row in source_cols]
        target_col_keys = [row["COLUMN_KEY"] for row in target_cols]
        common_keys = [key for key in source_col_keys if key in target_col_map]
        source_only = [source_col_map[key]["COLUMN_NAME"] for key in source_col_keys if key not in target_col_map]
        target_only = [target_col_map[key]["COLUMN_NAME"] for key in target_col_keys if key not in source_col_map]
        type_mismatch = [
            source_col_map[key]["COLUMN_NAME"]
            for key in common_keys
            if _data_compare_column_signature(source_col_map[key]) != _data_compare_column_signature(target_col_map[key])
        ]
        unsupported = [
            source_col_map[key]["COLUMN_NAME"]
            for key in common_keys
            if not _data_compare_supported_hash_column(source_col_map[key])
            or not _data_compare_supported_hash_column(target_col_map[key])
        ]
        comparable_keys = [
            key for key in common_keys
            if key not in {col.upper() for col in type_mismatch}
            and key not in {col.upper() for col in unsupported}
        ]
        comparable_columns = [source_col_map[key]["COLUMN_NAME"] for key in comparable_keys]
        if not source_present:
            status = "Missing in source"
        elif not target_present:
            status = "Missing in target"
        elif not comparable_columns:
            status = "No comparable columns"
        elif source_only or target_only or type_mismatch or unsupported:
            status = "Comparable with structure drift"
        else:
            status = "Ready"
        rows.append({
            "TABLE_NAME": table_name,
            "COMPARE_STATUS": status,
            "SOURCE_PRESENT": source_present,
            "TARGET_PRESENT": target_present,
            "SOURCE_METADATA_ROW_COUNT": safe_int(source_meta.get("METADATA_ROW_COUNT", 0)),
            "TARGET_METADATA_ROW_COUNT": safe_int(target_meta.get("METADATA_ROW_COUNT", 0)),
            "SOURCE_COLUMNS": len(source_cols),
            "TARGET_COLUMNS": len(target_cols),
            "COMPARABLE_COLUMN_COUNT": len(comparable_columns),
            "COMPARABLE_COLUMNS": ", ".join(comparable_columns),
            "SOURCE_ONLY_COLUMNS": ", ".join(source_only),
            "TARGET_ONLY_COLUMNS": ", ".join(target_only),
            "TYPE_MISMATCH_COLUMNS": ", ".join(type_mismatch),
            "UNSUPPORTED_HASH_COLUMNS": ", ".join(unsupported),
        })
    rank = {
        "Ready": 0,
        "Comparable with structure drift": 1,
        "No comparable columns": 2,
        "Missing in target": 3,
        "Missing in source": 4,
    }
    plan = pd.DataFrame(rows)
    if plan.empty:
        return pd.DataFrame(columns=[
            "TABLE_NAME", "COMPARE_STATUS", "COMPARABLE_COLUMNS", "SOURCE_METADATA_ROW_COUNT",
            "TARGET_METADATA_ROW_COUNT", "COMPARE_RANK",
        ])
    plan["COMPARE_RANK"] = plan["COMPARE_STATUS"].map(rank).fillna(9).astype(int)
    return plan.sort_values(["COMPARE_RANK", "TABLE_NAME"]).reset_index(drop=True)


def _data_compare_hash_sql(
    database: str,
    schema: str,
    table: str,
    columns: list[str],
    row_filter: str = "",
) -> str:
    table_fqn = _qualified_name(database, schema, table)
    where_clause = _data_compare_where_clause(row_filter)
    if columns:
        column_expr = ", ".join(_quote_identifier(col) for col in columns)
        hash_expr = f"HASH_AGG({column_expr})"
    else:
        hash_expr = "NULL"
    return f"""
SELECT
    COUNT(*) AS actual_row_count,
    {hash_expr} AS data_hash
FROM {table_fqn}
{where_clause}
""".strip()


def _data_compare_bucket_sql(
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    table: str,
    columns: list[str],
    key_columns: list[str] | None = None,
    row_filter: str = "",
    buckets: int = 128,
) -> str:
    hash_columns = list(key_columns or columns)
    if not hash_columns or not columns:
        return f"-- Bucket compare for {table} needs comparable columns."
    bucket_expr = f"MOD(ABS(HASH({', '.join(_quote_identifier(col) for col in hash_columns)})), {int(buckets)})"
    data_expr = ", ".join(_quote_identifier(col) for col in columns)
    where_clause = _data_compare_where_clause(row_filter)
    source_fqn = _qualified_name(source_db, source_schema, table)
    target_fqn = _qualified_name(target_db, target_schema, table)
    return f"""
WITH source_bucket AS (
    SELECT {bucket_expr} AS bucket_id, COUNT(*) AS source_rows, HASH_AGG({data_expr}) AS source_hash
    FROM {source_fqn}
    {where_clause}
    GROUP BY 1
),
target_bucket AS (
    SELECT {bucket_expr} AS bucket_id, COUNT(*) AS target_rows, HASH_AGG({data_expr}) AS target_hash
    FROM {target_fqn}
    {where_clause}
    GROUP BY 1
)
SELECT
    COALESCE(s.bucket_id, t.bucket_id) AS bucket_id,
    COALESCE(s.source_rows, 0) AS source_rows,
    COALESCE(t.target_rows, 0) AS target_rows,
    s.source_hash,
    t.target_hash
FROM source_bucket s
FULL OUTER JOIN target_bucket t USING (bucket_id)
WHERE COALESCE(s.source_rows, 0) <> COALESCE(t.target_rows, 0)
   OR COALESCE(s.source_hash, 0) <> COALESCE(t.target_hash, 0)
ORDER BY bucket_id;
""".strip()


def _data_compare_forensic_sql(
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    table: str,
    columns: list[str],
    key_columns: list[str] | None = None,
    row_filter: str = "",
    limit: int = 100,
) -> str:
    if not columns:
        return f"-- Forensic compare for {table} needs comparable columns."
    source_fqn = _qualified_name(source_db, source_schema, table)
    target_fqn = _qualified_name(target_db, target_schema, table)
    where_clause = _data_compare_where_clause(row_filter)
    select_cols = ", ".join(_quote_identifier(col) for col in columns)
    safe_limit = max(1, min(int(limit or 100), 1000))
    keys = list(key_columns or [])
    if keys:
        key_select = ", ".join(_quote_identifier(col) for col in keys)
        hash_select = ", ".join(_quote_identifier(col) for col in columns)
        join_clause = " AND ".join(
            f"s.{_quote_identifier(col)} IS NOT DISTINCT FROM t.{_quote_identifier(col)}"
            for col in keys
        )
        key_projection = ", ".join(f"COALESCE(s.{_quote_identifier(col)}, t.{_quote_identifier(col)}) AS {_quote_identifier(col)}" for col in keys)
        return f"""
WITH source_rows AS (
    SELECT {key_select}, HASH({hash_select}) AS source_row_hash
    FROM {source_fqn}
    {where_clause}
),
target_rows AS (
    SELECT {key_select}, HASH({hash_select}) AS target_row_hash
    FROM {target_fqn}
    {where_clause}
)
SELECT
    CASE
        WHEN s.source_row_hash IS NULL THEN 'ONLY_IN_TARGET'
        WHEN t.target_row_hash IS NULL THEN 'ONLY_IN_SOURCE'
        ELSE 'ROW_HASH_MISMATCH'
    END AS diff_type,
    {key_projection},
    s.source_row_hash,
    t.target_row_hash
FROM source_rows s
FULL OUTER JOIN target_rows t
  ON {join_clause}
WHERE s.source_row_hash IS NULL
   OR t.target_row_hash IS NULL
   OR s.source_row_hash <> t.target_row_hash
LIMIT {safe_limit};
""".strip()
    join_clause = " AND ".join(
        f"s.{_quote_identifier(col)} IS NOT DISTINCT FROM t.{_quote_identifier(col)}"
        for col in columns
    )
    projected_cols = ", ".join(
        f"COALESCE(s.{_quote_identifier(col)}, t.{_quote_identifier(col)}) AS {_quote_identifier(col)}"
        for col in columns
    )
    return f"""
WITH source_counts AS (
    SELECT {select_cols}, COUNT(*) AS source_duplicate_count
    FROM {source_fqn}
    {where_clause}
    GROUP BY {select_cols}
),
target_counts AS (
    SELECT {select_cols}, COUNT(*) AS target_duplicate_count
    FROM {target_fqn}
    {where_clause}
    GROUP BY {select_cols}
)
SELECT
    CASE
        WHEN t.target_duplicate_count IS NULL THEN 'ONLY_IN_SOURCE'
        WHEN s.source_duplicate_count IS NULL THEN 'ONLY_IN_TARGET'
        ELSE 'DUPLICATE_COUNT_MISMATCH'
    END AS diff_type,
    {projected_cols},
    COALESCE(s.source_duplicate_count, 0) AS source_duplicate_count,
    COALESCE(t.target_duplicate_count, 0) AS target_duplicate_count
FROM source_counts s
FULL OUTER JOIN target_counts t
  ON {join_clause}
WHERE COALESCE(s.source_duplicate_count, 0) <> COALESCE(t.target_duplicate_count, 0)
LIMIT {safe_limit};
""".strip()


def _schema_compare_coverage_label() -> str:
    return ", ".join(SCHEMA_COMPARE_OBJECT_COVERAGE)


def _render_schema_compare_command_model() -> None:
    render_shell_snapshot((
        ("Inventory", "SHOW OBJECTS"),
        ("Columns", "Snowflake account metadata"),
        ("Coverage", "All visible schema objects"),
        ("Missing Objects", "Review queue"),
    ))
    render_setup_health_board(
        "Schema Compare Readiness",
        (
            ("Object scope", "All visible schema objects"),
            ("Column drift", "Column signature compare"),
            ("Missing objects", "DBA review"),
            ("Coverage list", _schema_compare_coverage_label()),
        ),
        cadence="Operator-triggered metadata read",
        fallback="DBA review when metadata access is limited",
        owner="Release DBA",
    )


def _render_data_compare_command_model() -> None:
    render_shell_snapshot((
        ("Stage 1", "Metadata inventory"),
        ("Stage 2", "COUNT + HASH_AGG"),
        ("Stage 3", "Bucket isolate"),
        ("Stage 4", "Forensic diff"),
    ))
    render_setup_health_board(
        "Data Compare Readiness",
        (
            ("Scope", "Database + schema"),
            ("Detection", "Row count + hash"),
            ("Isolation", "Bucket mismatch"),
            ("Proof", "Keyed or EXCEPT-style diff"),
        ),
        cadence="Operator-triggered bounded scans",
        fallback="Reduce table count/filter for large schemas",
        owner="Release DBA / Data Owner",
    )


def _data_compare_extract_summary(df: pd.DataFrame | None) -> tuple[int | None, str]:
    if df is None or df.empty:
        return None, ""
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    row = frame.iloc[0]
    return safe_int(row.get("ACTUAL_ROW_COUNT", 0)), str(row.get("DATA_HASH", "") or "")


def _data_compare_outcome(source_count: int | None, target_count: int | None, source_hash: str, target_hash: str) -> str:
    if source_count is None or target_count is None:
        return "Unavailable"
    if source_count != target_count:
        return "Count mismatch"
    if str(source_hash) != str(target_hash):
        return "Hash mismatch"
    return "Matched"


def _sql_number_expr(value: object) -> str:
    if value is None:
        return "NULL"
    try:
        if pd.isna(value):
            return "NULL"
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return "NULL"
    try:
        number = float(text)
    except ValueError:
        return "NULL"
    if number.is_integer():
        return str(int(number))
    return str(number)


def _schema_compare_persistence_sql(
    compare: pd.DataFrame | None,
    *,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    owner: str = "",
    severity: str = "MEDIUM",
) -> str:
    rows = compare.copy() if isinstance(compare, pd.DataFrame) else pd.DataFrame()
    if rows.empty:
        return "-- No schema compare rows available to persist."
    if "COMPARE_STATUS" in rows.columns:
        rows = rows[rows["COMPARE_STATUS"].fillna("").astype(str).ne("Matched")]
    if rows.empty:
        return "-- Schema compare matched; no difference rows to persist."
    select_rows = []
    for _, row in rows.iterrows():
        generated_ddl = str(row.get("DDL_STATEMENT") or row.get("DDL_REVIEW_SQL") or "").strip()
        select_rows.append(
            "SELECT "
            f"{sql_literal(source_db, 300)} AS SOURCE_DATABASE, "
            f"{sql_literal(source_schema, 300)} AS SOURCE_SCHEMA, "
            f"{sql_literal(target_db, 300)} AS TARGET_DATABASE, "
            f"{sql_literal(target_schema, 300)} AS TARGET_SCHEMA, "
            f"{sql_literal(row.get('OBJECT_TYPE', ''), 100)} AS OBJECT_TYPE, "
            f"{sql_literal(row.get('OBJECT_NAME', ''), 1000)} AS OBJECT_NAME, "
            f"{sql_literal(row.get('COMPARE_STATUS', ''), 100)} AS DIFF_TYPE, "
            f"{sql_literal(generated_ddl, 16000)} AS GENERATED_DDL, "
            f"{sql_literal(owner, 300)} AS OWNER, "
            f"{sql_literal(str(severity or 'MEDIUM').upper(), 40)} AS SEVERITY"
        )
    select_sql = " UNION ALL\n".join(select_rows)
    return f"""
INSERT INTO OVERWATCH_SCHEMA_DIFF_RESULT (
    SOURCE_DATABASE, SOURCE_SCHEMA, TARGET_DATABASE, TARGET_SCHEMA,
    OBJECT_TYPE, OBJECT_NAME, DIFF_TYPE, GENERATED_DDL, OWNER, SEVERITY
)
{select_sql};
""".strip()


def _data_compare_persistence_sql(
    results: pd.DataFrame | None,
    *,
    check_id: int | str | None = None,
    recommended_action: str = "Review mismatches and run reviewed forensic diff before release cutover.",
) -> str:
    rows = results.copy() if isinstance(results, pd.DataFrame) else pd.DataFrame()
    if rows.empty:
        return "-- No data compare result rows available to persist."
    select_rows = []
    check_expr = "NULL" if check_id in (None, "") else f"TRY_TO_NUMBER({sql_literal(str(check_id), 100)})"
    for _, row in rows.iterrows():
        status = str(row.get("DATA_COMPARE_STATUS") or "Unavailable").strip()
        table_name = str(row.get("TABLE_NAME") or "Unknown table").strip()
        mismatch = 0 if status == "Matched" else 1
        table_action = f"{recommended_action} Table: {table_name}. Status: {status}."
        select_rows.append(
            "SELECT "
            f"{check_expr} AS CHECK_ID, "
            f"{sql_literal(status, 40)} AS RUN_STATUS, "
            f"{_sql_number_expr(row.get('SOURCE_ACTUAL_ROW_COUNT'))} AS SOURCE_ROW_COUNT, "
            f"{_sql_number_expr(row.get('TARGET_ACTUAL_ROW_COUNT'))} AS TARGET_ROW_COUNT, "
            f"{sql_literal(row.get('SOURCE_DATA_HASH', ''), 200)} AS SOURCE_HASH, "
            f"{sql_literal(row.get('TARGET_DATA_HASH', ''), 200)} AS TARGET_HASH, "
            f"{mismatch} AS MISMATCH_COUNT, "
            f"{sql_literal(row.get('FORENSIC_DIFF_SQL', ''), 16000)} AS SAMPLE_DIFF_SQL, "
            f"{sql_literal(table_action, 2000)} AS RECOMMENDED_ACTION"
        )
    select_sql = " UNION ALL\n".join(select_rows)
    return f"""
INSERT INTO OVERWATCH_RECON_RUN (
    CHECK_ID, RUN_STATUS, SOURCE_ROW_COUNT, TARGET_ROW_COUNT,
    SOURCE_HASH, TARGET_HASH, MISMATCH_COUNT, SAMPLE_DIFF_SQL, RECOMMENDED_ACTION
)
{select_sql};
""".strip()


def _recon_config_insert_sql(
    *,
    check_name: str,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    table_pattern: str = "%",
    key_columns: str = "",
    exclude_columns: str = "",
    where_clause: str = "",
    hash_bucket_count: int = 64,
    check_mode: str = "COUNT_AND_HASH",
    severity: str = "MEDIUM",
    owner: str = "Release DBA",
    enabled: bool = True,
) -> str:
    enabled_sql = "TRUE" if enabled else "FALSE"
    return f"""
INSERT INTO OVERWATCH_RECON_CONFIG (
    CHECK_NAME, SOURCE_DATABASE, SOURCE_SCHEMA, TARGET_DATABASE, TARGET_SCHEMA,
    TABLE_PATTERN, KEY_COLUMNS, EXCLUDE_COLUMNS, WHERE_CLAUSE, HASH_BUCKET_COUNT,
    CHECK_MODE, SEVERITY, OWNER, ENABLED
)
SELECT
    {sql_literal(check_name, 300)} AS CHECK_NAME,
    {sql_literal(source_db, 300)} AS SOURCE_DATABASE,
    {sql_literal(source_schema, 300)} AS SOURCE_SCHEMA,
    {sql_literal(target_db, 300)} AS TARGET_DATABASE,
    {sql_literal(target_schema, 300)} AS TARGET_SCHEMA,
    {sql_literal(table_pattern or '%', 300)} AS TABLE_PATTERN,
    {sql_literal(key_columns, 2000)} AS KEY_COLUMNS,
    {sql_literal(exclude_columns, 2000)} AS EXCLUDE_COLUMNS,
    {sql_literal(where_clause, 4000)} AS WHERE_CLAUSE,
    {max(1, int(hash_bucket_count or 64))} AS HASH_BUCKET_COUNT,
    {sql_literal(str(check_mode or 'COUNT_AND_HASH').upper(), 50)} AS CHECK_MODE,
    {sql_literal(str(severity or 'MEDIUM').upper(), 40)} AS SEVERITY,
    {sql_literal(owner, 300)} AS OWNER,
    {enabled_sql} AS ENABLED;
""".strip()


def _recon_history_sql(days: int = 30) -> str:
    days = max(1, int(days or 30))
    return f"""
SELECT
    r.RUN_ID,
    r.RUN_TS,
    c.CHECK_NAME,
    c.SOURCE_DATABASE,
    c.SOURCE_SCHEMA,
    c.TARGET_DATABASE,
    c.TARGET_SCHEMA,
    c.TABLE_PATTERN,
    c.CHECK_MODE,
    c.OWNER,
    c.SEVERITY,
    r.RUN_STATUS,
    r.SOURCE_ROW_COUNT,
    r.TARGET_ROW_COUNT,
    r.MISMATCH_COUNT,
    r.RECOMMENDED_ACTION
FROM OVERWATCH_RECON_RUN r
LEFT JOIN OVERWATCH_RECON_CONFIG c
  ON r.CHECK_ID = c.CHECK_ID
WHERE r.RUN_TS >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
ORDER BY r.RUN_TS DESC, r.RUN_ID DESC;
""".strip()


def _build_schema_compare_frame(
    source_inventory: pd.DataFrame,
    target_inventory: pd.DataFrame,
    *,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
) -> pd.DataFrame:
    source = source_inventory.copy() if source_inventory is not None else pd.DataFrame()
    target = target_inventory.copy() if target_inventory is not None else pd.DataFrame()
    for frame in (source, target):
        if "COMPARE_KEY" not in frame.columns:
            frame["COMPARE_KEY"] = pd.Series(dtype=str)
        if not frame.empty:
            frame["COMPARE_KEY"] = (
                frame["OBJECT_TYPE"].fillna("").astype(str).str.upper()
                + "::"
                + frame["OBJECT_NAME"].fillna("").astype(str).str.upper()
            )
    merged = target.merge(source, on="COMPARE_KEY", how="outer", suffixes=("_TARGET", "_SOURCE"))
    if merged.empty:
        return pd.DataFrame(columns=[
            "COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME", "ROW_COUNT_TARGET",
            "ROW_COUNT_SOURCE", "ROW_DIFF", "DDL_REVIEW_SQL",
        ])

    def _coalesce(row, name: str) -> object:
        target_value = row.get(f"{name}_TARGET")
        return target_value if pd.notna(target_value) and str(target_value).strip() else row.get(f"{name}_SOURCE")

    merged["OBJECT_TYPE"] = merged.apply(lambda row: _coalesce(row, "OBJECT_TYPE"), axis=1)
    merged["OBJECT_NAME"] = merged.apply(lambda row: _coalesce(row, "OBJECT_NAME"), axis=1)
    merged["PARENT_OBJECT_NAME"] = merged.apply(lambda row: _coalesce(row, "PARENT_OBJECT_NAME"), axis=1)
    merged["PARENT_OBJECT_TYPE"] = merged.apply(lambda row: _coalesce(row, "PARENT_OBJECT_TYPE"), axis=1)
    target_present = merged.get("PRESENT_TARGET", pd.Series([False] * len(merged), index=merged.index)).fillna(False).astype(bool)
    source_present = merged.get("PRESENT_SOURCE", pd.Series([False] * len(merged), index=merged.index)).fillna(False).astype(bool)
    target_sig = merged.get("OBJECT_SIGNATURE_TARGET", pd.Series([""] * len(merged), index=merged.index)).fillna("").astype(str)
    source_sig = merged.get("OBJECT_SIGNATURE_SOURCE", pd.Series([""] * len(merged), index=merged.index)).fillna("").astype(str)
    merged["COMPARE_STATUS"] = "Matched"
    merged.loc[source_present & ~target_present, "COMPARE_STATUS"] = "Only in source"
    merged.loc[target_present & ~source_present, "COMPARE_STATUS"] = "Only in target"
    merged.loc[source_present & target_present & target_sig.ne(source_sig), "COMPARE_STATUS"] = "Changed"
    merged["ROW_COUNT_TARGET"] = merged.get("ROW_COUNT_TARGET", pd.Series([0] * len(merged), index=merged.index)).fillna(0).astype(float).astype(int)
    merged["ROW_COUNT_SOURCE"] = merged.get("ROW_COUNT_SOURCE", pd.Series([0] * len(merged), index=merged.index)).fillna(0).astype(float).astype(int)
    merged["ROW_DIFF"] = merged["ROW_COUNT_TARGET"] - merged["ROW_COUNT_SOURCE"]
    merged["DDL_REVIEW_SQL"] = merged.apply(
        lambda row: _schema_compare_missing_ddl(
            row,
            source_db=source_db,
            source_schema=source_schema,
            target_db=target_db,
            target_schema=target_schema,
        ),
        axis=1,
    )
    status_rank = {"Only in source": 0, "Only in target": 1, "Changed": 2, "Matched": 9}
    merged["COMPARE_RANK"] = merged["COMPARE_STATUS"].map(status_rank).fillna(5).astype(int)
    columns = [
        "COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME", "PARENT_OBJECT_NAME",
        "PARENT_OBJECT_TYPE", "ROW_COUNT_TARGET", "ROW_COUNT_SOURCE", "ROW_DIFF",
        "OBJECT_DETAIL_TARGET", "OBJECT_DETAIL_SOURCE", "DDL_REVIEW_SQL", "COMPARE_RANK",
    ]
    for column in columns:
        if column not in merged.columns:
            merged[column] = ""
    return merged[columns].sort_values(["COMPARE_RANK", "OBJECT_TYPE", "OBJECT_NAME"]).reset_index(drop=True)


def _show_to_df(session, stmt: str, force_refresh: bool = False) -> pd.DataFrame:
    return show_to_df(session, stmt, force_refresh=force_refresh)


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str:
    return first_existing_column(df, candidates)


def _ensure_column_alias(df: pd.DataFrame, target: str, candidates: list[str], default="") -> pd.DataFrame:
    return ensure_column_alias(df, target, candidates, default)


def _load_task_inventory(session, force_refresh: bool = False) -> pd.DataFrame:
    return load_task_inventory(session, get_active_company(), force_refresh=force_refresh)


def _task_history_sql(session, time_predicate: str, limit: int = 500) -> str:
    """Build TASK_HISTORY SQL using only columns exposed by this account."""
    return build_task_history_sql(
        session,
        time_predicate,
        limit=limit,
        company=get_active_company(),
    )


def _setup_status_df(session) -> pd.DataFrame:
    checks = [
        ("Annotation Windows", "TABLE", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_ANNOTATIONS"),
        ("Alert History", "TABLE", ALERT_DB, ALERT_SCHEMA, ALERT_TABLE),
        ("Action Queue", "TABLE", ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE),
        ("Anomaly Alert Task", "TASK", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_ANOMALY_CHECK"),
    ]
    rows = []
    for feature, object_type, db, schema, object_name in checks:
        exists = (
            _task_exists(session, db, schema, object_name)
            if object_type == "TASK"
            else _table_exists(session, db, schema, object_name)
        )
        if exists is True:
            status = "Present"
        elif exists is False:
            status = "Missing"
        else:
            status = "Unknown"
        rows.append({
            "FEATURE": feature,
            "OBJECT_TYPE": object_type,
            "OBJECT_NAME": f"{db}.{schema}.{object_name}",
            "STATUS": status,
        })
    return pd.DataFrame(rows)


def render():
    session = get_session()
    company = get_active_company()
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "WAREHOUSE_SIZE",
            "BYTES_SCANNED",
            "QUERY_TAG",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "CREDITS_USED_CLOUD_SERVICES",
        ],
    ))
    qh_warehouse_size_expr = (
        "warehouse_size AS warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    )
    qh_max_size_expr = (
        "MAX(q.warehouse_size)"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    )
    qh_plain_size_expr = (
        "warehouse_size"
        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    )
    qh_query_tag_expr = (
        "query_tag AS query_tag"
        if "QUERY_TAG" in qh_cols else "NULL::VARCHAR AS query_tag"
    )
    qh_task_indicator = (
        "query_tag IS NOT NULL OR LOWER(query_text) LIKE '%execute task%'"
        if "QUERY_TAG" in qh_cols else "LOWER(query_text) LIKE '%execute task%'"
    )

    focus = st.session_state.get("dba_tools_focus")
    default_group = DBA_TOOL_FOCUS_GROUPS.get(str(focus), "Warehouse Ops")
    group_names = list(DBA_TOOL_GROUPS)
    focus_tool = str(st.session_state.get("dba_tools_focus_tool") or "")
    focus_tool_active = (
        focus_tool
        and default_group in DBA_TOOL_GROUPS
        and focus_tool in DBA_TOOL_GROUPS[default_group]
    )
    if focus_tool_active:
        selected_group = default_group
        tool_options = DBA_TOOL_GROUPS[selected_group]
        selected_tool = focus_tool
        focus_hint = DBA_TOOL_FOCUS_HINTS.get(
            str(focus),
            "Use the matching workflow when you need additional DBA tools.",
        )
        st.caption(f"Workflow focus: {selected_tool}. {focus_hint}")
    else:
        st.caption(
            "Guarded admin workflows are grouped to keep the high-value controls easy to find. "
            "Open a group, then choose the specific operation."
        )
        if focus:
            focus_hint = DBA_TOOL_FOCUS_HINTS.get(
                str(focus),
                "Use the matching tab group below first; other tools remain available when needed.",
            )
            st.info(f"Security Monitoring focus: {focus}. {focus_hint}")
        with st.expander("Guarded Admin Operating Model", expanded=not bool(focus)):
            risk_a, risk_b, risk_c = st.columns(3)
            with risk_a:
                st.info(
                    "Safe Observability\n\n"
                    "Read-only inventory, diagnostics, compatibility checks, schema compare, recent objects, "
                    "QAS visibility, replication, serverless costs, and action history."
                )
            with risk_b:
                st.warning(
                    "Controlled Actions\n\n"
                    "Query cancellation, task suspend/resume, warehouse setting changes, and Cortex limit updates. "
                    "These remain guarded by typed confirmation and Snowflake privileges."
                )
            with risk_c:
                st.success(
                    "Readiness and Audit\n\n"
                    "Compatibility checks, data readiness, action queue routing, and "
                    "formula audit evidence stay available without exposing deployment plumbing."
                )
        if "dba_tools_group_selector" not in st.session_state and default_group in group_names:
            st.session_state["dba_tools_group_selector"] = default_group
        selected_group = render_workflow_selector(
            "DBA workflow",
            "dba_tools_group_selector",
            group_names,
            columns=3,
            show_label=True,
        )
        tool_options = DBA_TOOL_GROUPS[selected_group]
        selected_tool = st.selectbox(
            "Open specialist tool",
            tool_options,
            key=f"dba_tools_tool_selector_{selected_group}",
        )
        st.info("Alert history, email-ready delivery rows, routing, and suppression windows now live in the consolidated Alert Center.")
        if st.button("Open Alert Center", key="dba_tools_open_alert_center"):
            apply_navigation_state("Alert Center")
            st.rerun()

    st.divider()
    if not focus_tool_active:
        st.caption(
            "Focused mode renders one specialist tool at a time. Use the workflow hubs for daily operations; "
            "use this page when you need a specific admin utility."
        )

    # -- TAB 0: QUERY KILL LIST ------------------------------------------------
    if selected_tool == "Query Kill List":
        st.subheader("Long-Running Query Kill List")
        kill_min = st.number_input("Flag queries running > (seconds)", 60, 3600, 300, key="kill_sec")
        if _load_button("Load Kill List", "kl_load"):
            try:
                df = run_query_or_raise(f"""
                    SELECT query_id, user_name, warehouse_name, {qh_warehouse_size_expr}, execution_status, start_time,
                           DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) AS elapsed_sec,
                           SUBSTR(query_text,1,500) AS query_text
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours', -2, CURRENT_TIMESTAMP())
                      AND UPPER(execution_status) IN ('RUNNING','QUEUED','BLOCKED')
                      AND DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) > {kill_min}
                      {get_wh_filter_clause("warehouse_name")}
                    ORDER BY elapsed_sec DESC
                    LIMIT 500
                """)
                st.session_state["dba_df_kl"] = df
            except Exception as e:
                st.session_state["dba_df_kl"] = pd.DataFrame()
                st.caption(f"Query activity unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("dba_df_kl") is not None and not st.session_state["dba_df_kl"].empty:
            df = st.session_state["dba_df_kl"]
            st.warning(f"{len(df)} queries running > {kill_min}s")
            render_priority_dataframe(
                df,
                title="Queries eligible for cancellation",
                priority_columns=[
                    "QUERY_ID", "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                    "EXECUTION_STATUS", "START_TIME", "ELAPSED_SEC", "QUERY_TEXT",
                ],
                sort_by=["ELAPSED_SEC", "START_TIME"],
                ascending=[False, False],
                raw_label="All kill-list query rows",
            )
            kill_id = st.selectbox("Kill query ID", df["QUERY_ID"].tolist(), key="kl_sel")
            kill_confirmed = _typed_confirmation(
                "Type CANCEL to enable query cancellation",
                "CANCEL",
                f"kl_confirm_{kill_id}",
            ) if kill_id else False
            if kill_id and st.button(
                "Cancel Query",
                type="primary",
                key="kl_kill",
                disabled=admin_button_disabled(),
            ):
                if _require_typed_confirmation(kill_confirmed, "CANCEL"):
                    try:
                        session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(kill_id)})").collect()
                        st.success(f"Cancel sent for `{kill_id}`")
                    except Exception as e:
                        st.error(f"Cancel failed: {format_snowflake_error(e)}")
        elif st.session_state.get("dba_df_kl") is not None:
            st.success(f"No queries running > {kill_min}s")

    # -- TAB 1: WAREHOUSE SETTINGS MANAGER ------------------------------------
    if selected_tool == "Warehouse Settings":
        st.subheader("Warehouse Settings Manager")
        st.caption(
            "View and interactively change all warehouse parameters - "
            "size, timeouts, auto-suspend, multi-cluster, QAS, and scaling policy. "
            "Changes are applied only after a reviewed plan, rollback SQL, typed confirmation, and audit logging."
        )

        active_company = get_active_company()
        needs_wh_load = (
            st.session_state.get("_dba_wh_cfg_company") != active_company
            or "dba_df_wh_cfg" not in st.session_state
        )
        last_failed_company = st.session_state.get("_dba_wh_cfg_failed_company")

        col_r1, col_r2 = st.columns([1, 1])
        with col_r1:
            refresh_wh = st.button("Refresh Warehouses", key="wh_cfg_load")
            if refresh_wh or (needs_wh_load and last_failed_company != active_company):
                try:
                    df_raw = load_warehouse_inventory(session, active_company, force_refresh=bool(refresh_wh))
                    df_raw.columns = [c.lower() for c in df_raw.columns]
                    st.session_state["dba_df_wh_cfg"] = df_raw
                    st.session_state["_dba_wh_cfg_company"] = active_company
                    st.session_state.pop("_dba_wh_cfg_failed_company", None)
                except Exception as e:
                    st.warning(f"Warehouse list unavailable in this role/context: {format_snowflake_error(e)}")
                    st.session_state["dba_df_wh_cfg"] = pd.DataFrame()
                    st.session_state["_dba_wh_cfg_company"] = active_company
                    st.session_state["_dba_wh_cfg_failed_company"] = active_company
        with col_r2:
            wh_filter_txt = st.text_input("Filter warehouse", key="wh_cfg_filter",
                                           placeholder="e.g. ALFA or leave blank for all")

        df_wh = st.session_state.get("dba_df_wh_cfg")
        if df_wh is not None and not df_wh.empty:
            # Apply filter
            if wh_filter_txt:
                mask   = df_wh["name"].astype(str).str.upper().str.contains(safe_sql(wh_filter_txt).upper(), na=False)
                df_wh  = df_wh[mask]

            # Summary table
            st.subheader(f"Warehouses ({len(df_wh)})")
            display_cols = [c for c in ["name","size","state","auto_suspend","auto_resume",
                                         "min_cluster_count","max_cluster_count","scaling_policy",
                                         "enable_query_acceleration","statement_timeout_in_seconds",
                                         "statement_queued_timeout_in_seconds"] if c in df_wh.columns]
            render_priority_dataframe(
                df_wh[display_cols],
                title="Warehouse settings by risk",
                priority_columns=display_cols,
                sort_by=["auto_suspend", "state", "name"],
                ascending=[False, True, True],
                raw_label="All warehouse setting rows",
                height=220,
            )

            # Flag issues
            issues = []
            for _, row in df_wh.iterrows():
                wn  = row.get("name","")
                sus = row.get("auto_suspend", 0)
                try:
                    if int(sus) > 600:
                        issues.append(f"Medium - **{wn}**: AUTO_SUSPEND={sus}s (>10 min) - wasting credits when idle")
                    if int(sus) == 0:
                        issues.append(f"High - **{wn}**: AUTO_SUSPEND=0 - warehouse never suspends")
                except Exception:
                    pass
            if issues:
                with st.expander(f"{len(issues)} configuration issue(s) detected"):
                    for i in issues:
                        st.markdown(i)

            st.divider()
            st.subheader("Edit Warehouse Settings")
            st.caption("Select a warehouse, adjust parameters, review the proposed change, then apply.")

            wh_names = df_wh["name"].tolist() if "name" in df_wh.columns else []
            sel_wh   = st.selectbox("Select warehouse to edit", wh_names, key="wh_edit_sel")

            if sel_wh:
                wh_row = df_wh[df_wh["name"] == sel_wh].iloc[0]

                def _get(col, default=""):
                    v = wh_row.get(col, default)
                    return "" if v is None or str(v).lower() in ("nan","none","") else str(v)

                st.html(
                    "<div style='line-height:1.45;margin:.15rem 0;'>"
                    f"<strong>Editing:</strong> <code>{html_escape(str(sel_wh))}</code> | "
                    f"Current state: <code>{html_escape(_get('state', 'unknown'))}</code>"
                    "</div>"
                )

                with st.form(f"wh_edit_form_{sel_wh}"):
                    c1, c2, c3 = st.columns(3)

                    with c1:
                        st.markdown("**Compute**")
                        curr_size = _get("size","X-Small")
                        new_size  = st.selectbox(
                            "Size", _SIZE_OPTS,
                            index=_SIZE_OPTS.index(curr_size) if curr_size in _SIZE_OPTS else 0,
                            key=f"wh_size_{sel_wh}",
                            help=_WH_PARAM_HELP["WAREHOUSE_SIZE"],
                        )
                        new_auto_resume = st.checkbox(
                            "Auto Resume",
                            value=_as_bool(_get("auto_resume","true"), True),
                            key=f"wh_ar_{sel_wh}",
                            help=_WH_PARAM_HELP["AUTO_RESUME"],
                        )
                        curr_sus = _as_int(_get("auto_suspend","600"), 600)
                        new_auto_suspend = st.number_input(
                            "AUTO_SUSPEND (seconds, 0=never)",
                            min_value=0, max_value=86400, value=curr_sus, step=60,
                            key=f"wh_sus_{sel_wh}",
                            help=_WH_PARAM_HELP["AUTO_SUSPEND"],
                        )

                    with c2:
                        st.markdown("**Timeouts**")
                        curr_stmt_to = _as_int(_get("statement_timeout_in_seconds","0"), 0)
                        new_stmt_timeout = st.number_input(
                            "STATEMENT_TIMEOUT (sec, 0=no limit)",
                            min_value=0, max_value=604800, value=curr_stmt_to, step=300,
                            key=f"wh_stmto_{sel_wh}",
                            help=_WH_PARAM_HELP["STATEMENT_TIMEOUT_IN_SECONDS"],
                        )
                        curr_q_to = _as_int(_get("statement_queued_timeout_in_seconds","0"), 0)
                        new_queue_timeout = st.number_input(
                            "QUEUE_TIMEOUT (sec, 0=no limit)",
                            min_value=0, max_value=86400, value=curr_q_to, step=60,
                            key=f"wh_qto_{sel_wh}",
                            help=_WH_PARAM_HELP["STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"],
                        )
                        curr_concur = _as_int(_get("max_concurrency_level","8"), 8)
                        new_concurrency = st.number_input(
                            "MAX_CONCURRENCY_LEVEL",
                            min_value=1, max_value=10, value=min(max(curr_concur,1),10),
                            key=f"wh_concur_{sel_wh}",
                            help=_WH_PARAM_HELP["MAX_CONCURRENCY_LEVEL"],
                        )

                    with c3:
                        st.markdown("**Scaling & QAS**")
                        curr_scale = _get("scaling_policy","STANDARD").upper()
                        new_scaling = st.selectbox(
                            "SCALING_POLICY",
                            _SCALE_OPTS,
                            index=_SCALE_OPTS.index(curr_scale) if curr_scale in _SCALE_OPTS else 0,
                            key=f"wh_sp_{sel_wh}",
                            help=_WH_PARAM_HELP["SCALING_POLICY"],
                        )
                        curr_min = _as_int(_get("min_cluster_count","1"), 1)
                        curr_max = _as_int(_get("max_cluster_count","1"), 1)
                        new_min_clusters = st.number_input(
                            "MIN_CLUSTER_COUNT",
                            min_value=1, max_value=10, value=max(curr_min,1),
                            key=f"wh_minc_{sel_wh}",
                            help=_WH_PARAM_HELP["MIN_CLUSTER_COUNT"],
                        )
                        new_max_clusters = st.number_input(
                            "MAX_CLUSTER_COUNT",
                            min_value=1, max_value=10, value=max(curr_max,1),
                            key=f"wh_maxc_{sel_wh}",
                            help=_WH_PARAM_HELP["MAX_CLUSTER_COUNT"],
                        )
                        curr_qas = _as_bool(_get("enable_query_acceleration","false"), False)
                        new_qas  = st.checkbox(
                            "Enable QAS",
                            value=curr_qas,
                            key=f"wh_qas_{sel_wh}",
                            help=_WH_PARAM_HELP["ENABLE_QUERY_ACCELERATION"],
                        )
                        curr_qas_sf = _as_int(_get("query_acceleration_max_scale_factor","8"), 8)
                        new_qas_sf = st.number_input(
                            "QAS Max Scale Factor (0=unlimited)",
                            min_value=0, max_value=100, value=curr_qas_sf,
                            key=f"wh_qassf_{sel_wh}",
                            help=_WH_PARAM_HELP["QUERY_ACCELERATION_MAX_SCALE_FACTOR"],
                            disabled=not new_qas,
                        )

                    preview_plan = st.form_submit_button("Preview Change Plan", type="primary")

                plan_key = f"wh_change_plan_{sel_wh}"
                if preview_plan:
                    requested = {
                        "WAREHOUSE_SIZE": new_size,
                        "AUTO_SUSPEND": int(new_auto_suspend),
                        "AUTO_RESUME": bool(new_auto_resume),
                        "STATEMENT_TIMEOUT_IN_SECONDS": int(new_stmt_timeout),
                        "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": int(new_queue_timeout),
                        "MAX_CONCURRENCY_LEVEL": int(new_concurrency),
                        "SCALING_POLICY": new_scaling,
                        "MIN_CLUSTER_COUNT": int(new_min_clusters),
                        "MAX_CLUSTER_COUNT": int(new_max_clusters),
                        "ENABLE_QUERY_ACCELERATION": bool(new_qas),
                        "QUERY_ACCELERATION_MAX_SCALE_FACTOR": int(new_qas_sf),
                    }
                    st.session_state[plan_key] = _build_warehouse_setting_plan(sel_wh, wh_row, requested)

                plan = st.session_state.get(plan_key)
                if plan:
                    st.subheader("Reviewed Warehouse Change Plan")
                    changes_df = plan.get("changes_df", pd.DataFrame())
                    skipped_df = plan.get("skipped_df", pd.DataFrame())
                    if changes_df.empty:
                        st.success("No warehouse settings changed from the loaded before-state.")
                    else:
                        render_priority_dataframe(
                            changes_df,
                            title="Before/after settings requiring review",
                            priority_columns=[
                                "REVIEW_GATE", "REVIEW_DECISION", "PARAMETER",
                                "CURRENT", "REQUESTED", "RISK",
                                "PROOF_REQUIRED", "VERIFY_AFTER_CHANGE",
                            ],
                            sort_by=["PARAMETER"],
                            ascending=True,
                            raw_label="All proposed warehouse changes",
                            height=240,
                        )
                        st.caption(
                            "Only changed parameters are included in the reviewed change plan. "
                            "Run pre-flight checks and keep rollback instructions with the change ticket."
                        )
                        render_shell_snapshot((
                            ("Pre-flight", "Required"),
                            ("Apply plan", "Review gated"),
                            ("Rollback", "Required"),
                            ("Execution", "reviewed workflow"),
                        ))

                    if not skipped_df.empty:
                        st.warning("Some settings were not included because their current values were unavailable.")
                        render_priority_dataframe(
                            skipped_df,
                            title="Skipped settings",
                            priority_columns=["PARAMETER", "REASON"],
                            sort_by=["PARAMETER"],
                            ascending=True,
                            raw_label="All skipped settings",
                            height=160,
                        )

                    if not changes_df.empty:
                        col_apply, col_audit = st.columns([1, 3])
                        with col_apply:
                            wh_confirmed = _typed_confirmation(
                                f"Type {plan['confirmation_text']} to apply this warehouse change",
                                plan["confirmation_text"],
                                f"wh_confirm_reviewed_{sel_wh}",
                            )
                            if st.button(
                                "Apply Warehouse Change",
                                type="primary",
                                key=f"wh_apply_reviewed_{sel_wh}",
                                disabled=admin_button_disabled(),
                            ):
                                if _require_typed_confirmation(wh_confirmed, plan["confirmation_text"]):
                                    try:
                                        log_admin_action(
                                            session,
                                            action_type="ALTER WAREHOUSE",
                                            target_object=sel_wh,
                                            sql_text=plan["alter_sql"],
                                            result_status="STARTED",
                                            result_message="Warehouse change submitted from OVERWATCH.",
                                            confirmation_text=plan["confirmation_text"],
                                            control_context=plan["control_context"],
                                            company=active_company,
                                            environment=get_active_environment(),
                                        )
                                        session.sql(plan["alter_sql"]).collect()
                                        audited = log_admin_action(
                                            session,
                                            action_type="ALTER WAREHOUSE",
                                            target_object=sel_wh,
                                            sql_text=plan["alter_sql"],
                                            result_status="SUCCESS",
                                            result_message="Warehouse change completed.",
                                            confirmation_text=plan["confirmation_text"],
                                            control_context=plan["control_context"],
                                            company=active_company,
                                            environment=get_active_environment(),
                                        )
                                        st.success(f"Warehouse `{sel_wh}` updated successfully.")
                                        if not audited:
                                            st.warning("The change completed, but the admin audit table was unavailable or not writable.")
                                        st.session_state.pop("dba_df_wh_cfg", None)
                                        st.session_state.pop(plan_key, None)
                                        st.rerun()
                                    except Exception as e:
                                        err = format_snowflake_error(e)
                                        log_admin_action(
                                            session,
                                            action_type="ALTER WAREHOUSE",
                                            target_object=sel_wh,
                                            sql_text=plan["alter_sql"],
                                            result_status="FAILED",
                                            result_message=err,
                                            confirmation_text=plan["confirmation_text"],
                                            control_context=plan["control_context"],
                                            company=active_company,
                                            environment=get_active_environment(),
                                        )
                                        err_str = str(e).lower()
                                        if "insufficient privilege" in err_str or "not authorized" in err_str:
                                            st.error(
                                                f"Permission denied on `{sel_wh}`. "
                                                f"ALTER WAREHOUSE requires MODIFY privilege."
                                            )
                                        elif "enterprise" in err_str or "not supported" in err_str:
                                            st.error(
                                                "Feature not available in your Snowflake edition. "
                                                "Multi-cluster and QAS require Enterprise or higher."
                                            )
                                        else:
                                            st.error(f"ALTER failed: {err}")
                        with col_audit:
                            st.caption(
                                "Audit path: OVERWATCH_ADMIN_ACTION_AUDIT captures company, environment, "
                                "Snowflake role/user, SQL hash, confirmation text, control context, and result."
                            )

    # -- TAB 2: DATA LOADING ---------------------------------------------------
    if selected_tool == "Data Loading":
        st.subheader("Data Loading Monitor")
        load_days = day_window_selectbox("Lookback", key="dl_days", default=7)
        if _load_button("Load Copy History", "dl_load"):
            try:
                st.session_state["dba_df_copy"] = run_query(f"""
                    SELECT table_name, file_name, status, row_count,
                           first_error_message, last_load_time
                    FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
                    WHERE last_load_time >= DATEADD('day', -{load_days}, CURRENT_TIMESTAMP())
                      {get_db_filter_clause("table_catalog_name")}
                    ORDER BY last_load_time DESC LIMIT 500
                """, ttl_key=f"dba_copy_{company}_{load_days}", tier="standard")
            except Exception as e:
                st.warning(f"Copy history unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_copy") is not None and not st.session_state["dba_df_copy"].empty:
            df_copy = st.session_state["dba_df_copy"]
            render_priority_dataframe(
                df_copy,
                title="Copy history rows to review",
                priority_columns=[
                    "TABLE_NAME", "FILE_NAME", "STATUS", "ROW_COUNT",
                    "FIRST_ERROR_MESSAGE", "LAST_LOAD_TIME",
                ],
                sort_by=["STATUS", "LAST_LOAD_TIME", "ROW_COUNT"],
                ascending=[True, False, False],
                raw_label="All copy history rows",
            )
            download_csv(df_copy, "copy_history.csv")

    # -- TABS 3-13: CARRIED FORWARD (abbreviated for file size) ---------------
    if selected_tool == "Network & Sessions":
        st.subheader("Network & Sessions")
        if _load_button("Load Session Data", "net_load"):
            try:
                st.session_state["dba_df_long_sess"] = run_query(f"""
                    SELECT session_id, user_name, created_on,
                           DATEDIFF('hour', created_on, CURRENT_TIMESTAMP()) AS session_hours
                    FROM SNOWFLAKE.ACCOUNT_USAGE.SESSIONS
                    WHERE created_on >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND DATEDIFF('hour', created_on, CURRENT_TIMESTAMP()) > 8
                      {get_user_filter_clause("user_name")}
                    ORDER BY session_hours DESC LIMIT 100
                """, ttl_key=f"dba_long_sessions_{company}", tier="standard")
            except Exception as e:
                st.info(f"Sessions unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_long_sess") is not None:
            render_priority_dataframe(
                st.session_state["dba_df_long_sess"],
                title="Long-running sessions",
                priority_columns=["SESSION_ID", "USER_NAME", "CREATED_ON", "SESSION_HOURS"],
                sort_by=["SESSION_HOURS"],
                ascending=False,
                raw_label="All long-session rows",
            )

    if selected_tool == "Unused Objects":
        st.subheader("Unused Objects")
        if _load_button("Find Unused Tables", "unused_load"):
            try:
                st.session_state["dba_df_unused"] = run_query(f"""
                    SELECT table_catalog, table_schema, table_name, row_count,
                           bytes/POWER(1024,3) AS table_gb, created, last_altered
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                    WHERE deleted IS NULL
                      AND last_altered < DATEADD('day', -90, CURRENT_TIMESTAMP())
                      {get_db_filter_clause("table_catalog")}
                    ORDER BY bytes DESC NULLS LAST LIMIT 200
                """, ttl_key=f"dba_unused_tables_{company}", tier="standard")
            except Exception as e:
                st.warning(f"Unused table scan unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_unused") is not None:
            render_priority_dataframe(
                st.session_state["dba_df_unused"],
                title="Unused objects by size",
                priority_columns=[
                    "TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME", "ROW_COUNT",
                    "TABLE_GB", "CREATED", "LAST_ALTERED",
                ],
                sort_by=["TABLE_GB", "ROW_COUNT"],
                ascending=[False, False],
                raw_label="All unused object rows",
            )

    if selected_tool == "Snowpipe Monitor":
        st.subheader("Snowpipe Monitor")
        sp_days = day_window_selectbox("Lookback", key="spipe_days", default=7)
        if _load_button("Load Pipe Usage", "spipe_load"):
            try:
                st.session_state["dba_df_pipe"] = run_query(f"""
                    SELECT pipe_name, DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used) AS daily_credits,
                           SUM(bytes_inserted)/POWER(1024,3) AS gb_inserted,
                           SUM(files_inserted) AS files_inserted
                    FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
                    WHERE start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                    GROUP BY pipe_name, day ORDER BY daily_credits DESC
                """, ttl_key=f"dba_pipe_{company}_{sp_days}", tier="standard")
            except Exception as e:
                st.warning(f"Snowpipe usage unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_pipe") is not None:
            render_priority_dataframe(
                st.session_state["dba_df_pipe"],
                title="Snowpipe cost and volume",
                priority_columns=["PIPE_NAME", "DAY", "DAILY_CREDITS", "GB_INSERTED", "FILES_INSERTED"],
                sort_by=["DAILY_CREDITS", "GB_INSERTED", "FILES_INSERTED"],
                ascending=[False, False, False],
                raw_label="All Snowpipe rows",
            )

    if selected_tool == "QAS Monitor":
        st.subheader("QAS Monitor")
        qas_days = day_window_selectbox("Lookback", key="qas_days", default=7)
        if _load_button("Load QAS Data", "qas_load"):
            try:
                st.session_state["dba_df_qas"] = run_query(f"""
                    WITH latest_size AS (
                        SELECT warehouse_name, warehouse_size
                        FROM (
                            SELECT warehouse_name, {qh_plain_size_expr},
                                   ROW_NUMBER() OVER (PARTITION BY warehouse_name ORDER BY start_time DESC) AS rn
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE start_time >= DATEADD('day', -{qas_days}, CURRENT_TIMESTAMP())
                              AND warehouse_name IS NOT NULL
                        )
                        WHERE rn = 1
                    )
                    SELECT q.warehouse_name, ls.warehouse_size, DATE_TRUNC('day', q.start_time) AS day,
                           SUM(q.credits_used) AS daily_credits, COUNT(*) AS query_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ACCELERATION_HISTORY q
                    LEFT JOIN latest_size ls ON q.warehouse_name = ls.warehouse_name
                    WHERE q.start_time >= DATEADD('day', -{qas_days}, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("q.warehouse_name")}
                    GROUP BY q.warehouse_name, ls.warehouse_size, day ORDER BY daily_credits DESC
                """, ttl_key=f"dba_qas_{company}_{qas_days}", tier="standard")
            except Exception as e:
                st.info(f"QAS data unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_qas") is not None:
            render_priority_dataframe(
                st.session_state["dba_df_qas"],
                title="Query Acceleration usage",
                priority_columns=["WAREHOUSE_NAME", "WAREHOUSE_SIZE", "DAY", "DAILY_CREDITS", "QUERY_COUNT"],
                sort_by=["DAILY_CREDITS", "QUERY_COUNT"],
                ascending=[False, False],
                raw_label="All QAS usage rows",
            )

    if selected_tool == "Schema Compare":
        st.subheader("Schema Compare")
        st.caption(
            "Compares every visible schema object from SHOW OBJECTS, plus table and column inventory from "
            "Snowflake account metadata. Missing objects include a DBA-reviewed create script."
        )
        _render_schema_compare_command_model()
        refresh_schema_meta = st.button("Refresh database and schema choices", key="sc_refresh_metadata")
        scope_key = f"{get_active_company()}_{get_active_environment()}"
        database_cache_key = f"sc_database_options_{scope_key}"
        if refresh_schema_meta or database_cache_key not in st.session_state:
            st.session_state[database_cache_key] = load_database_options(
                session,
                company=get_active_company(),
                force_refresh=bool(refresh_schema_meta),
            )
        database_options = list(st.session_state.get(database_cache_key) or [])
        if not database_options:
            st.info("No scoped databases were returned by SHOW DATABASES. Enter database names directly or refresh after changing role.")
        c1, c2 = st.columns(2)
        with c1:
            dev_db = _select_option(
                "Source database",
                database_options,
                "sc_dev",
                "DEV_DB",
                allow_current_outside_options=False,
            )
            source_schema_cache_key = f"sc_schema_options_source_{scope_key}_{dev_db}"
            if refresh_schema_meta or source_schema_cache_key not in st.session_state:
                st.session_state[source_schema_cache_key] = load_schema_options(
                    session,
                    dev_db,
                    company=get_active_company(),
                    force_refresh=bool(refresh_schema_meta),
                )
            dev_sch = _select_option(
                "Source schema",
                list(st.session_state.get(source_schema_cache_key) or []),
                "sc_devsch",
                "PUBLIC",
                allow_current_outside_options=False,
            )
        with c2:
            prod_db = _select_option(
                "Target database",
                database_options,
                "sc_prod",
                "PROD_DB",
                allow_current_outside_options=False,
            )
            target_schema_cache_key = f"sc_schema_options_target_{scope_key}_{prod_db}"
            if refresh_schema_meta or target_schema_cache_key not in st.session_state:
                st.session_state[target_schema_cache_key] = load_schema_options(
                    session,
                    prod_db,
                    company=get_active_company(),
                    force_refresh=bool(refresh_schema_meta),
                )
            prod_sch = _select_option(
                "Target schema",
                list(st.session_state.get(target_schema_cache_key) or []),
                "sc_prodsch",
                "PUBLIC",
                allow_current_outside_options=False,
            )
        schema_config_sql = _recon_config_insert_sql(
            check_name=f"Schema compare {dev_db}.{dev_sch} to {prod_db}.{prod_sch}",
            source_db=dev_db,
            source_schema=dev_sch,
            target_db=prod_db,
            target_schema=prod_sch,
            table_pattern="%",
            check_mode="SCHEMA_OBJECT_DDL",
            severity="MEDIUM",
            owner="Release DBA",
        )
        config_cols = st.columns([1.0, 1.0, 3.0])
        with config_cols[0]:
            st.caption("Recurring schema-pair checks are tracked through the DBA monitoring runbook.")
        with config_cols[1]:
            st.caption("Keep schema comparison telemetry with operational status when promotion depends on it.")
        with config_cols[2]:
            st.caption("Use the review table below for missing objects and drift decisions.")
        if st.button("Compare Schemas", key="sc_run"):
            try:
                dev_db_safe = safe_identifier(dev_db)
                prod_db_safe = safe_identifier(prod_db)
                if not (
                    company_value_allowed(dev_db, "database")
                    and company_value_allowed(prod_db, "database")
                ):
                    st.warning(
                        f"Schema Compare is scoped to {get_active_company()}. "
                        "Enter databases that belong to the selected company view."
                    )
                    st.stop()
                source_objects = run_query(
                    _schema_compare_show_objects_sql(dev_db, dev_sch),
                    ttl_key=f"dba_schema_objects_source_{company}_{dev_db_safe}_{dev_sch}",
                    tier="metadata",
                )
                target_objects = run_query(
                    _schema_compare_show_objects_sql(prod_db, prod_sch),
                    ttl_key=f"dba_schema_objects_target_{company}_{prod_db_safe}_{prod_sch}",
                    tier="metadata",
                )
                source_columns = run_query(
                    _schema_compare_columns_sql(dev_db, dev_sch),
                    ttl_key=f"dba_schema_columns_source_{company}_{dev_db_safe}_{dev_sch}",
                    tier="metadata",
                )
                target_columns = run_query(
                    _schema_compare_columns_sql(prod_db, prod_sch),
                    ttl_key=f"dba_schema_columns_target_{company}_{prod_db_safe}_{prod_sch}",
                    tier="metadata",
                )
                source_inventory = _schema_compare_inventory(
                    source_objects,
                    source_columns,
                    database=dev_db,
                    schema=dev_sch,
                    side="SOURCE",
                )
                target_inventory = _schema_compare_inventory(
                    target_objects,
                    target_columns,
                    database=prod_db,
                    schema=prod_sch,
                    side="TARGET",
                )
                df_cmp = _build_schema_compare_frame(
                    source_inventory,
                    target_inventory,
                    source_db=dev_db,
                    source_schema=dev_sch,
                    target_db=prod_db,
                    target_schema=prod_sch,
                )
                missing_or_changed = df_cmp[df_cmp["COMPARE_STATUS"].ne("Matched")] if not df_cmp.empty else df_cmp
                ddl_rows = df_cmp[df_cmp["DDL_REVIEW_SQL"].fillna("").astype(str).str.strip().ne("")] if not df_cmp.empty else df_cmp
                ddl_statement_rows = _schema_compare_fetch_missing_ddl_statements(
                    ddl_rows,
                    source_db=dev_db,
                    source_schema=dev_sch,
                    target_db=prod_db,
                    target_schema=prod_sch,
                ) if ddl_rows is not None and not ddl_rows.empty else ddl_rows
                render_shell_snapshot((
                    ("Compared Objects", f"{len(df_cmp):,}"),
                    ("Missing", f"{int(df_cmp['COMPARE_STATUS'].isin(['Only in source', 'Only in target']).sum()) if not df_cmp.empty else 0:,}"),
                    ("Changed", f"{int(df_cmp['COMPARE_STATUS'].eq('Changed').sum()) if not df_cmp.empty else 0:,}"),
                    ("Review Items", f"{len(ddl_statement_rows):,}" if ddl_statement_rows is not None else "0"),
                ))
                render_priority_dataframe(
                    missing_or_changed if missing_or_changed is not None and not missing_or_changed.empty else df_cmp,
                    title="Schema object differences",
                    priority_columns=[
                        "COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME", "PARENT_OBJECT_TYPE",
                        "ROW_COUNT_TARGET", "ROW_COUNT_SOURCE", "ROW_DIFF",
                        "OBJECT_DETAIL_TARGET", "OBJECT_DETAIL_SOURCE",
                    ],
                    sort_by=["COMPARE_RANK", "OBJECT_TYPE", "OBJECT_NAME"],
                    ascending=[True, True, True],
                    raw_label="All schema compare rows",
                )
                if ddl_statement_rows is not None and not ddl_statement_rows.empty:
                    review_rows = ddl_statement_rows.drop(
                        columns=["DDL_STATUS", "DDL_STATEMENT", "DDL_REVIEW_SQL"],
                        errors="ignore",
                    )
                    render_priority_dataframe(
                        review_rows,
                        title="Missing objects requiring DBA review",
                        priority_columns=[
                            "COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME",
                        ],
                        sort_by=["COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME"],
                        ascending=[True, True, True],
                        raw_label="All missing-object review rows",
                        height=260,
                    )
                    ddl_script = _schema_compare_ddl_script(
                        ddl_statement_rows,
                        source_db=dev_db,
                        source_schema=dev_sch,
                        target_db=prod_db,
                        target_schema=prod_sch,
                    )
                    if ddl_script:
                        st.text_area(
                            "Missing-object DDL script",
                            value=ddl_script,
                            height=360,
                            key="sc_missing_object_ddl_script",
                        )
                        st.download_button(
                            "Download missing-object DDL",
                            data=ddl_script,
                            file_name="schema_compare_missing_objects.sql",
                            mime="text/sql",
                            key="sc_download_missing_object_ddl",
                        )
                else:
                    st.success("No missing objects were found between the selected schemas.")
                download_csv(df_cmp, "schema_compare.csv")
                if missing_or_changed is not None and not missing_or_changed.empty:
                    persistence_rows = missing_or_changed.copy()
                    if ddl_statement_rows is not None and not ddl_statement_rows.empty:
                        ddl_lookup = {
                            (
                                str(row.get("OBJECT_TYPE") or "").upper(),
                                str(row.get("OBJECT_NAME") or "").upper(),
                            ): str(row.get("DDL_STATEMENT") or "")
                            for _, row in ddl_statement_rows.iterrows()
                        }
                        persistence_rows["DDL_STATEMENT"] = persistence_rows.apply(
                            lambda row: ddl_lookup.get(
                                (
                                    str(row.get("OBJECT_TYPE") or "").upper(),
                                    str(row.get("OBJECT_NAME") or "").upper(),
                                ),
                                str(row.get("DDL_REVIEW_SQL") or ""),
                            ),
                            axis=1,
                        )
                    schema_persist_sql = _schema_compare_persistence_sql(
                        persistence_rows,
                        source_db=dev_db,
                        source_schema=dev_sch,
                        target_db=prod_db,
                        target_schema=prod_sch,
                        owner="Release DBA",
                        severity="MEDIUM",
                    )
                    st.caption("Schema diff results are ready for the DBA monitoring log after review.")
            except Exception as e:
                st.error(f"Compare failed: {format_snowflake_error(e)}")

    if selected_tool == "Data Compare":
        st.subheader("Data Compare")
        st.caption(
            "Validates row-count sameness and data likeness between matching tables in two schemas. "
            "Quick compare runs COUNT plus explicit-column HASH_AGG; mismatch rows get bucket and forensic diff guidance for DBA review."
        )
        _render_data_compare_command_model()
        refresh_data_meta = st.button("Refresh database and schema choices", key="dc_refresh_metadata")
        scope_key = f"{get_active_company()}_{get_active_environment()}"
        database_cache_key = f"dc_database_options_{scope_key}"
        if refresh_data_meta or database_cache_key not in st.session_state:
            st.session_state[database_cache_key] = load_database_options(
                session,
                company=get_active_company(),
                force_refresh=bool(refresh_data_meta),
            )
        database_options = list(st.session_state.get(database_cache_key) or [])
        if not database_options:
            st.info("No scoped databases were returned by SHOW DATABASES. Enter database names directly or refresh after changing role.")
        src_col, tgt_col = st.columns(2)
        with src_col:
            data_src_db = _select_option(
                "Source database",
                database_options,
                "dc_source_db",
                "DEV_DB",
                allow_current_outside_options=False,
            )
            source_schema_cache_key = f"dc_schema_options_source_{scope_key}_{data_src_db}"
            if refresh_data_meta or source_schema_cache_key not in st.session_state:
                st.session_state[source_schema_cache_key] = load_schema_options(
                    session,
                    data_src_db,
                    company=get_active_company(),
                    force_refresh=bool(refresh_data_meta),
                )
            data_src_schema = _select_option(
                "Source schema",
                list(st.session_state.get(source_schema_cache_key) or []),
                "dc_source_schema",
                "PUBLIC",
                allow_current_outside_options=False,
            )
        with tgt_col:
            data_tgt_db = _select_option(
                "Target database",
                database_options,
                "dc_target_db",
                "PROD_DB",
                allow_current_outside_options=False,
            )
            target_schema_cache_key = f"dc_schema_options_target_{scope_key}_{data_tgt_db}"
            if refresh_data_meta or target_schema_cache_key not in st.session_state:
                st.session_state[target_schema_cache_key] = load_schema_options(
                    session,
                    data_tgt_db,
                    company=get_active_company(),
                    force_refresh=bool(refresh_data_meta),
                )
            data_tgt_schema = _select_option(
                "Target schema",
                list(st.session_state.get(target_schema_cache_key) or []),
                "dc_target_schema",
                "PUBLIC",
                allow_current_outside_options=False,
            )

        opt1, opt2, opt3 = st.columns([1, 1, 1])
        with opt1:
            data_table_filter = st.text_input(
                "Table contains",
                key="dc_table_filter",
                placeholder="blank = all matching tables",
            )
        with opt2:
            data_max_tables = st.number_input(
                "Max tables to scan",
                min_value=1,
                max_value=100,
                value=25,
                step=5,
                key="dc_max_tables",
                help="COUNT/HASH scans can be expensive. Start small for large schemas.",
            )
        with opt3:
            data_diff_limit = st.number_input(
                "Forensic sample limit",
                min_value=10,
                max_value=1000,
                value=100,
                step=10,
                key="dc_diff_limit",
            )
        excluded_columns_text = st.text_input(
            "Excluded columns",
            key="dc_excluded_columns",
            placeholder="LOAD_TS, UPDATED_AT, AUDIT_ID",
            help="Comma-separated columns excluded from HASH_AGG when timestamps or audit values are expected to differ.",
        )
        key_columns_text = st.text_input(
            "Key columns for forensic diff",
            key="dc_key_columns",
            placeholder="POLICY_ID, CLAIM_ID",
            help="Optional. When supplied, mismatch review uses key-based matching; otherwise it compares both directions.",
        )
        row_filter_text = st.text_input(
            "Row filter",
            key="dc_row_filter",
            placeholder="BUSINESS_DATE >= '2026-01-01'",
            help="Optional SELECT predicate applied to both sides. Leave blank for full-table compare.",
        )
        st.caption(
            "Hashing is a fast detection signal, not a destructive action. For critical mismatches, use the reviewed bucket and forensic diff runbook."
        )
        data_config_sql = _recon_config_insert_sql(
            check_name=f"Data compare {data_src_db}.{data_src_schema} to {data_tgt_db}.{data_tgt_schema}",
            source_db=data_src_db,
            source_schema=data_src_schema,
            target_db=data_tgt_db,
            target_schema=data_tgt_schema,
            table_pattern=f"%{data_table_filter.strip()}%" if str(data_table_filter or "").strip() else "%",
            key_columns=key_columns_text,
            exclude_columns=excluded_columns_text,
            where_clause=row_filter_text,
            hash_bucket_count=128,
            check_mode="COUNT_HASH_BUCKET_FORENSIC",
            severity="MEDIUM",
            owner="Release DBA",
        )
        recon_history_sql = _recon_history_sql(days=30)
        config_cols = st.columns([1.0, 1.0, 1.0, 2.0])
        with config_cols[0]:
            st.caption("Recurring data checks are tracked through the DBA monitoring runbook.")
        with config_cols[1]:
            st.caption("Recurring reconciliation history is managed through the DBA monitoring runbook.")
        with config_cols[2]:
            st.caption("Configuration changes are review-only from this page.")
        with config_cols[3]:
            st.caption("Register recurring reconciliation checks in OVERWATCH_RECON_CONFIG; review prior runs from OVERWATCH_RECON_RUN.")

        if st.button("Run Quick Data Compare", key="dc_run"):
            try:
                source_db_safe = safe_identifier(data_src_db)
                target_db_safe = safe_identifier(data_tgt_db)
                if not (
                    company_value_allowed(data_src_db, "database")
                    and company_value_allowed(data_tgt_db, "database")
                ):
                    st.warning(
                        f"Data Compare is scoped to {get_active_company()}. "
                        "Enter databases that belong to the selected company view."
                    )
                    st.stop()
                excluded_columns = _data_compare_parse_identifiers(excluded_columns_text)
                key_columns = _data_compare_parse_identifiers(key_columns_text)
                _data_compare_where_clause(row_filter_text)

                source_tables = run_query(
                    _data_compare_tables_sql(data_src_db, data_src_schema),
                    ttl_key=f"dba_data_compare_tables_source_{company}_{source_db_safe}_{data_src_schema}",
                    tier="metadata",
                )
                target_tables = run_query(
                    _data_compare_tables_sql(data_tgt_db, data_tgt_schema),
                    ttl_key=f"dba_data_compare_tables_target_{company}_{target_db_safe}_{data_tgt_schema}",
                    tier="metadata",
                )
                source_columns = run_query(
                    _schema_compare_columns_sql(data_src_db, data_src_schema),
                    ttl_key=f"dba_data_compare_columns_source_{company}_{source_db_safe}_{data_src_schema}",
                    tier="metadata",
                )
                target_columns = run_query(
                    _schema_compare_columns_sql(data_tgt_db, data_tgt_schema),
                    ttl_key=f"dba_data_compare_columns_target_{company}_{target_db_safe}_{data_tgt_schema}",
                    tier="metadata",
                )
                plan = _build_data_compare_plan(
                    source_tables,
                    target_tables,
                    source_columns,
                    target_columns,
                    excluded_columns=excluded_columns,
                    table_filter=data_table_filter,
                )
                runnable = plan[
                    plan["COMPARE_STATUS"].isin(["Ready", "Comparable with structure drift"])
                    & plan["COMPARABLE_COLUMN_COUNT"].gt(0)
                ].head(int(data_max_tables))
                result_rows = []
                scripts = []
                for _, row in runnable.iterrows():
                    table_name = str(row.get("TABLE_NAME") or "").strip()
                    columns = [col.strip() for col in str(row.get("COMPARABLE_COLUMNS") or "").split(",") if col.strip()]
                    try:
                        source_summary = run_query(
                            _data_compare_hash_sql(data_src_db, data_src_schema, table_name, columns, row_filter_text),
                            ttl_key=f"dba_data_compare_source_hash_{company}_{source_db_safe}_{data_src_schema}_{table_name}",
                            tier="historical",
                            max_rows=5,
                        )
                        target_summary = run_query(
                            _data_compare_hash_sql(data_tgt_db, data_tgt_schema, table_name, columns, row_filter_text),
                            ttl_key=f"dba_data_compare_target_hash_{company}_{target_db_safe}_{data_tgt_schema}_{table_name}",
                            tier="historical",
                            max_rows=5,
                        )
                        source_count, source_hash = _data_compare_extract_summary(source_summary)
                        target_count, target_hash = _data_compare_extract_summary(target_summary)
                        outcome = _data_compare_outcome(source_count, target_count, source_hash, target_hash)
                    except Exception as exc:
                        source_count, target_count, source_hash, target_hash = None, None, "", ""
                        outcome = f"Unavailable: {format_snowflake_error(exc)}"
                    bucket_sql = _data_compare_bucket_sql(
                        data_src_db,
                        data_src_schema,
                        data_tgt_db,
                        data_tgt_schema,
                        table_name,
                        columns,
                        key_columns=key_columns,
                        row_filter=row_filter_text,
                    )
                    forensic_sql = _data_compare_forensic_sql(
                        data_src_db,
                        data_src_schema,
                        data_tgt_db,
                        data_tgt_schema,
                        table_name,
                        columns,
                        key_columns=key_columns,
                        row_filter=row_filter_text,
                        limit=int(data_diff_limit),
                    )
                    script_block = (
                        f"-- {table_name}: {outcome}\n"
                        f"-- Bucket compare narrows the mismatch to hash buckets.\n{bucket_sql}\n\n"
                        f"-- Forensic compare returns sample mismatch rows.\n{forensic_sql}"
                    )
                    scripts.append(script_block)
                    result_rows.append({
                        "TABLE_NAME": table_name,
                        "DATA_COMPARE_STATUS": outcome,
                        "VALIDATION_STAGES": " > ".join(DATA_COMPARE_EXECUTION_STAGES),
                        "STRUCTURE_STATUS": row.get("COMPARE_STATUS", ""),
                        "SOURCE_ACTUAL_ROW_COUNT": source_count,
                        "TARGET_ACTUAL_ROW_COUNT": target_count,
                        "ROW_COUNT_DIFF": (
                            int(target_count or 0) - int(source_count or 0)
                            if source_count is not None and target_count is not None else None
                        ),
                        "SOURCE_DATA_HASH": source_hash,
                        "TARGET_DATA_HASH": target_hash,
                        "COMPARABLE_COLUMN_COUNT": row.get("COMPARABLE_COLUMN_COUNT", 0),
                        "SOURCE_ONLY_COLUMNS": row.get("SOURCE_ONLY_COLUMNS", ""),
                        "TARGET_ONLY_COLUMNS": row.get("TARGET_ONLY_COLUMNS", ""),
                        "TYPE_MISMATCH_COLUMNS": row.get("TYPE_MISMATCH_COLUMNS", ""),
                        "UNSUPPORTED_HASH_COLUMNS": row.get("UNSUPPORTED_HASH_COLUMNS", ""),
                        "BUCKET_COMPARE_SQL": bucket_sql,
                        "FORENSIC_DIFF_SQL": forensic_sql,
                    })
                results = pd.DataFrame(result_rows)
                if not plan.empty:
                    skipped = plan[~plan["TABLE_NAME"].isin(results["TABLE_NAME"].tolist() if not results.empty else [])]
                else:
                    skipped = plan
                mismatches = results[results["DATA_COMPARE_STATUS"].ne("Matched")] if not results.empty else results
                render_shell_snapshot((
                    ("Tables Planned", f"{len(plan):,}"),
                    ("Tables Scanned", f"{len(results):,}"),
                    ("Matched", f"{int(results['DATA_COMPARE_STATUS'].eq('Matched').sum()) if not results.empty else 0:,}"),
                    ("Needs Review", f"{len(mismatches):,}" if mismatches is not None else "0"),
                ))
                if not results.empty:
                    render_priority_dataframe(
                        results,
                        title="Data compare results",
                        priority_columns=[
                            "TABLE_NAME", "DATA_COMPARE_STATUS", "VALIDATION_STAGES", "STRUCTURE_STATUS",
                            "SOURCE_ACTUAL_ROW_COUNT", "TARGET_ACTUAL_ROW_COUNT", "ROW_COUNT_DIFF",
                            "COMPARABLE_COLUMN_COUNT", "SOURCE_ONLY_COLUMNS", "TARGET_ONLY_COLUMNS",
                            "TYPE_MISMATCH_COLUMNS", "UNSUPPORTED_HASH_COLUMNS",
                        ],
                        sort_by=["DATA_COMPARE_STATUS", "TABLE_NAME"],
                        ascending=[True, True],
                        raw_label="All data compare result rows",
                    )
                    download_csv(results, "data_compare_results.csv")
                    st.caption("Data compare run results are ready for the DBA monitoring log after review.")
                else:
                    st.info("No comparable tables were scanned. Check source/target schemas, table filter, or comparable columns.")
                if skipped is not None and not skipped.empty:
                    render_priority_dataframe(
                        skipped,
                        title="Tables not scanned",
                        priority_columns=[
                            "TABLE_NAME", "COMPARE_STATUS", "SOURCE_METADATA_ROW_COUNT",
                            "TARGET_METADATA_ROW_COUNT", "SOURCE_ONLY_COLUMNS",
                            "TARGET_ONLY_COLUMNS", "TYPE_MISMATCH_COLUMNS", "UNSUPPORTED_HASH_COLUMNS",
                        ],
                        sort_by=["COMPARE_RANK", "TABLE_NAME"],
                        ascending=[True, True],
                        raw_label="All planned table rows",
                        height=220,
                    )
                if scripts:
                    st.caption("Bucket and forensic diff steps are available through the DBA monitoring runbook.")
            except Exception as e:
                st.error(f"Data Compare failed: {format_snowflake_error(e)}")

    if selected_tool == "Recent Objects":
        st.subheader("Recent Objects")
        obj_days = day_window_selectbox("Created/altered within", key="obj_days", default=30)
        refresh_obj_meta = st.button("Refresh database choices", key="obj_refresh_metadata")
        if refresh_obj_meta or "obj_database_options" not in st.session_state:
            st.session_state["obj_database_options"] = load_database_options(
                session,
                company=get_active_company(),
                force_refresh=bool(refresh_obj_meta),
            )
        obj_database_options = list(st.session_state.get("obj_database_options") or [])
        if obj_database_options:
            obj_database_choices = ["All scoped databases"] + obj_database_options
            if st.session_state.get("obj_database_filter") not in obj_database_choices:
                st.session_state["obj_database_filter"] = "All scoped databases"
            obj_database = st.selectbox(
                "Database",
                obj_database_choices,
                key="obj_database_filter",
            )
            obj_db_clause = (
                f"AND table_catalog = {sql_literal(obj_database)}"
                if obj_database != "All scoped databases"
                else ""
            )
            obj_filter_key = obj_database
        else:
            obj_db_filter = st.text_input("Database contains", key="obj_db_filter")
            if obj_db_filter and not company_value_allowed(obj_db_filter, "database"):
                st.caption("Entered database text is outside the active company/environment scope and will only match if visible.")
            obj_db_clause = (
                f"AND table_catalog ILIKE {sql_literal('%' + obj_db_filter + '%')}"
                if obj_db_filter else ""
            )
            obj_filter_key = obj_db_filter
        if st.button("Load Recent Objects", key="obj_load"):
            try:
                st.session_state["dba_df_recent_objects"] = run_query(f"""
                    SELECT table_catalog AS database_name, table_schema AS schema_name,
                           table_name AS object_name, table_type, created, last_altered, table_owner AS owner
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                    WHERE deleted IS NULL
                      AND (created >= DATEADD('day', -{obj_days}, CURRENT_TIMESTAMP())
                           OR last_altered >= DATEADD('day', -{obj_days}, CURRENT_TIMESTAMP()))
                      {obj_db_clause}
                      {get_db_filter_clause("table_catalog")}
                    ORDER BY GREATEST(created, last_altered) DESC LIMIT 500
                """, ttl_key=f"dba_recent_objects_{company}_{obj_days}_{obj_filter_key}", tier="metadata")
            except Exception as e:
                st.warning(f"Recent objects unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_recent_objects") is not None:
            df_recent = st.session_state["dba_df_recent_objects"]
            render_priority_dataframe(
                df_recent,
                title="Recent object changes",
                priority_columns=[
                    "DATABASE_NAME", "SCHEMA_NAME", "OBJECT_NAME",
                    "TABLE_TYPE", "OWNER", "CREATED", "LAST_ALTERED",
                ],
                sort_by=["CREATED", "LAST_ALTERED"],
                ascending=[False, False],
                raw_label="All recent object rows",
            )
            download_csv(df_recent, "recent_objects.csv")

    if selected_tool == "Summary Status":
        st.subheader("Summary Status")
        st.caption(
            "Checks whether the Snowflake summary facts are available for fast dashboards."
        )
        mart_objects = [
            ("Control Room Snapshot", "MART_DBA_CONTROL_ROOM"),
            ("Query Detail", "FACT_QUERY_DETAIL"),
            ("Warehouse Daily", "FACT_WAREHOUSE_DAILY"),
            ("Task Runs", "FACT_TASK_RUN"),
            ("Login Daily", "FACT_LOGIN_DAILY"),
            ("Object Changes", "FACT_OBJECT_CHANGE"),
        ]
        rows = []
        for label, table_name in mart_objects:
            exists = _table_exists(session, ALERT_DB, ALERT_SCHEMA, table_name)
            rows.append({
                "FEATURE": label,
                "OBJECT_NAME": f"{ALERT_DB}.{ALERT_SCHEMA}.{table_name}",
                "STATUS": "Present" if exists is True else "Missing" if exists is False else "Unknown",
            })
        mart_df = pd.DataFrame(rows)
        present_count = int((mart_df["STATUS"] == "Present").sum())
        missing_count = int((mart_df["STATUS"] == "Missing").sum())
        render_shell_snapshot((
            ("Present", f"{present_count:,}"),
            ("Missing", f"{missing_count:,}"),
        ))
        summary_display = mart_df.drop(columns=["OBJECT_NAME"], errors="ignore")
        render_priority_dataframe(
            summary_display,
            title="Summary fact readiness",
            priority_columns=["FEATURE", "STATUS"],
            sort_by=["STATUS", "FEATURE"],
            ascending=[True, True],
            raw_label="All summary readiness rows",
        )
        if missing_count:
            st.info("Summary facts are not available yet. Ask the DBA team to refresh the Snowflake objects, then recheck.")

    if selected_tool == "Dynamic Tables":
        st.subheader("Dynamic Tables")
        if st.button("Load Dynamic Tables", key="dyn_load"):
            try:
                df_dyn = _show_to_df(session, "SHOW DYNAMIC TABLES IN ACCOUNT")
                df_dyn = _ensure_column_alias(df_dyn, "NAME", ["NAME", "DYNAMIC_TABLE_NAME"])
                df_dyn = _ensure_column_alias(df_dyn, "DATABASE_NAME", ["DATABASE_NAME", "DATABASE"])
                df_dyn = _ensure_column_alias(df_dyn, "SCHEMA_NAME", ["SCHEMA_NAME", "SCHEMA"])
                df_dyn = _scope_metadata_df(df_dyn)
                if not df_dyn.empty:
                    try:
                        refresh_object = "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY"
                        requested_cols = [
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "DYNAMIC_TABLE_NAME", "STATE_CODE",
                            "STATE_MESSAGE", "REFRESH_ACTION", "REFRESH_TRIGGER",
                            "REFRESH_START_TIME", "REFRESH_END_TIME", "TARGET_LAG_SEC", "QUERY_ID",
                        ]
                        available_cols = filter_existing_columns(session, refresh_object, requested_cols)
                        if "REFRESH_START_TIME" not in available_cols:
                            raise ValueError("Dynamic table refresh history does not expose REFRESH_START_TIME.")
                        name_expr = (
                            "NAME AS NAME"
                            if "NAME" in available_cols
                            else "DYNAMIC_TABLE_NAME AS NAME"
                            if "DYNAMIC_TABLE_NAME" in available_cols
                            else "'UNKNOWN' AS NAME"
                        )
                        select_cols = [
                            "DATABASE_NAME" if "DATABASE_NAME" in available_cols else "NULL::VARCHAR AS DATABASE_NAME",
                            "SCHEMA_NAME" if "SCHEMA_NAME" in available_cols else "NULL::VARCHAR AS SCHEMA_NAME",
                            name_expr,
                        ]
                        select_cols.extend([
                            col for col in available_cols
                            if col not in {"DATABASE_NAME", "SCHEMA_NAME", "NAME", "DYNAMIC_TABLE_NAME"}
                        ])
                        db_filter = get_db_filter_clause("database_name") if "DATABASE_NAME" in available_cols else ""
                        df_refresh = run_query_or_raise(f"""
                            SELECT {", ".join(select_cols)}
                            FROM {refresh_object}
                            WHERE refresh_start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                              {db_filter}
                            ORDER BY refresh_start_time DESC
                            LIMIT 5000
                        """)
                        if not df_refresh.empty and all(c in df_dyn.columns for c in ["DATABASE_NAME", "SCHEMA_NAME", "NAME"]):
                            refresh_cols = {
                                "STATE_CODE": "LAST_REFRESH_STATE_CODE",
                                "STATE_MESSAGE": "LAST_REFRESH_MESSAGE",
                                "REFRESH_START_TIME": "LAST_REFRESH_START_TIME",
                                "REFRESH_END_TIME": "LAST_REFRESH_END_TIME",
                                "QUERY_ID": "LAST_REFRESH_QUERY_ID",
                            }
                            df_refresh = df_refresh.rename(
                                columns={src: dst for src, dst in refresh_cols.items() if src in df_refresh.columns}
                            )
                            if "LAST_REFRESH_START_TIME" in df_refresh.columns:
                                df_refresh = df_refresh.sort_values("LAST_REFRESH_START_TIME", ascending=False)
                            keep_cols = [
                                c for c in [
                                    "DATABASE_NAME", "SCHEMA_NAME", "NAME",
                                    "LAST_REFRESH_STATE", "LAST_REFRESH_STATE_CODE", "LAST_REFRESH_MESSAGE",
                                    "REFRESH_ACTION", "REFRESH_TRIGGER",
                                    "LAST_REFRESH_START_TIME", "LAST_REFRESH_END_TIME",
                                    "TARGET_LAG_SEC", "LAST_REFRESH_QUERY_ID",
                                ]
                                if c in df_refresh.columns
                            ]
                            df_refresh = df_refresh[keep_cols].drop_duplicates(["DATABASE_NAME", "SCHEMA_NAME", "NAME"])
                            df_dyn = df_dyn.merge(
                                df_refresh,
                                how="left",
                                on=["DATABASE_NAME", "SCHEMA_NAME", "NAME"],
                            )
                    except Exception:
                        pass
                st.session_state["dba_df_dyn"] = df_dyn
            except Exception as e:
                st.info(f"Dynamic table data unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_dyn") is not None:
            df_dyn = st.session_state["dba_df_dyn"]
            render_priority_dataframe(
                df_dyn,
                title="Dynamic tables needing attention",
                priority_columns=[
                    "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                    "LAST_REFRESH_STATE_CODE", "LAST_REFRESH_MESSAGE",
                    "REFRESH_ACTION", "LAST_REFRESH_START_TIME", "TARGET_LAG_SEC",
                ],
                sort_by=["LAST_REFRESH_STATE_CODE", "LAST_REFRESH_START_TIME", "TARGET_LAG_SEC"],
                ascending=[True, False, False],
                raw_label="All dynamic table rows",
            )
            download_csv(df_dyn, "dynamic_tables.csv")

    if selected_tool == "Replication":
        st.subheader("Replication")
        repl_days = day_window_selectbox("Lookback", key="repl_days", default=30)
        if st.button("Load Replication History", key="repl_load"):
            repl_sql_primary = f"""
                SELECT database_name,
                       replication_group_name,
                       phase_name,
                       start_time,
                       end_time,
                       DATEDIFF('minute', start_time, end_time) AS duration_min,
                       credits_used,
                       bytes_transferred/POWER(1024,3) AS gb_transferred
                FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_GROUP_USAGE_HISTORY
                WHERE start_time >= DATEADD('day', -{repl_days}, CURRENT_TIMESTAMP())
                  {get_db_filter_clause("database_name")}
                ORDER BY start_time DESC
                LIMIT 500
            """
            repl_sql_fallback = f"""
                SELECT database_name,
                       replication_group_name,
                       phase_name,
                       start_time,
                       end_time,
                       DATEDIFF('minute', start_time, end_time) AS duration_min,
                       credits_used,
                       bytes_transferred/POWER(1024,3) AS gb_transferred
                FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_USAGE_HISTORY
                WHERE start_time >= DATEADD('day', -{repl_days}, CURRENT_TIMESTAMP())
                  {get_db_filter_clause("database_name")}
                ORDER BY start_time DESC
                LIMIT 500
            """
            try:
                st.session_state["dba_df_repl"] = run_query_or_raise(repl_sql_primary)
                st.session_state["dba_repl_source"] = "REPLICATION_GROUP_USAGE_HISTORY"
            except Exception as primary_error:
                try:
                    st.session_state["dba_df_repl"] = run_query_or_raise(repl_sql_fallback)
                    st.session_state["dba_repl_source"] = "REPLICATION_USAGE_HISTORY"
                except Exception as fallback_error:
                    st.info(f"Replication data unavailable: {format_snowflake_error(fallback_error)}")
                    st.caption(f"Primary view also failed: {format_snowflake_error(primary_error)}")
        if st.session_state.get("dba_df_repl") is not None and not st.session_state["dba_df_repl"].empty:
            df_repl = st.session_state["dba_df_repl"]
            st.caption(f"Measurement: {st.session_state.get('dba_repl_source', 'replication usage history')}")
            render_shell_snapshot((("Replication Credits", format_credits(df_repl["CREDITS_USED"].sum())),))
            render_priority_dataframe(
                df_repl,
                title="Replication cost and lag candidates",
                priority_columns=[
                    "DATABASE_NAME", "REPLICATION_GROUP_NAME", "PHASE_NAME",
                    "START_TIME", "END_TIME", "DURATION_MIN", "CREDITS_USED",
                    "GB_TRANSFERRED",
                ],
                sort_by=["CREDITS_USED", "DURATION_MIN", "START_TIME"],
                ascending=[False, False, False],
                raw_label="All replication history rows",
            )
            download_csv(df_repl, "replication_history.csv")

    if selected_tool == "Serverless Costs":
        st.subheader("Serverless Costs")
        if get_active_company() != "ALL":
            st.info(
                "Serverless metering is account-level in Snowflake and does not expose "
                "a reliable company, database, user, or warehouse dimension here. Switch "
                "Company View to ALL to review account-wide serverless costs."
            )
        else:
            sv_days = day_window_selectbox("Lookback", key="sv_days", default=30)
            if st.button("Load Serverless Costs", key="sv_load"):
                try:
                    st.session_state["dba_df_serverless"] = run_query(f"""
                        SELECT service_type, DATE_TRUNC('day', start_time) AS usage_date,
                               SUM(credits_used) AS daily_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                        WHERE start_time >= DATEADD('day', -{sv_days}, CURRENT_TIMESTAMP())
                          AND service_type NOT IN ('WAREHOUSE_METERING','WAREHOUSE_METERING_READER')
                        GROUP BY service_type, usage_date ORDER BY daily_credits DESC
                    """, ttl_key=f"dba_serverless_{company}_{sv_days}", tier="standard")
                except Exception as e:
                    st.warning(f"Serverless costs unavailable: {format_snowflake_error(e)}")
            if st.session_state.get("dba_df_serverless") is not None and not st.session_state["dba_df_serverless"].empty:
                df_sv = st.session_state["dba_df_serverless"]
                svc   = df_sv.groupby("SERVICE_TYPE")["DAILY_CREDITS"].sum().reset_index().sort_values("DAILY_CREDITS", ascending=False)
                render_shell_snapshot((("Total Serverless Credits", format_credits(float(svc["DAILY_CREDITS"].sum()))),))
                render_priority_dataframe(
                    svc,
                    title="Serverless service cost drivers",
                    priority_columns=["SERVICE_TYPE", "DAILY_CREDITS"],
                    sort_by=["DAILY_CREDITS"],
                    ascending=False,
                    raw_label="All serverless service totals",
                )
                serverless_trend = df_sv.pivot_table(
                    index="USAGE_DATE",
                    columns="SERVICE_TYPE",
                    values="DAILY_CREDITS",
                    aggfunc="sum",
                ).fillna(0)
                render_chart_with_data_toggle(
                    "Serverless credits trend",
                    "dba_serverless_credits_trend",
                    lambda: st.area_chart(serverless_trend),
                    df_sv,
                    priority_columns=["USAGE_DATE", "SERVICE_TYPE", "DAILY_CREDITS"],
                    sort_by=["USAGE_DATE", "DAILY_CREDITS"],
                    ascending=[False, False],
                    raw_label="All serverless daily rows",
                )
                download_csv(df_sv, "serverless_costs.csv")

    # -- TAB 14: CORTEX AI LIMITS ----------------------------------------------
    if selected_tool == "Cortex AI Limits":
        st.subheader("Cortex AI Limits")
        st.caption(
            "View and modify Cortex AI service limits for your account. "
            "These control daily token thresholds, inference rate limits, and Cortex Search/Analyst access. "
            "Requires ACCOUNTADMIN or SYSADMIN with MODIFY ACCOUNT privilege."
        )

        # -- Current parameters ------------------------------------------------
        if st.button("Load Current AI Parameters", key="cortex_params_load"):
            results = {}

            # SHOW PARAMETERS - account-level Cortex controls
            try:
                df_params = run_query_or_raise("SHOW PARAMETERS LIKE '%CORTEX%' IN ACCOUNT")
                results["cortex_params"] = df_params
            except Exception as e:
                results["cortex_params"] = pd.DataFrame()
                st.caption(f"Account parameters unavailable: {format_snowflake_error(e)}")

            # Also check AI_SERVICES parameters
            try:
                df_ai = run_query_or_raise("SHOW PARAMETERS LIKE '%AI%' IN ACCOUNT")
                results["ai_params"] = df_ai
            except Exception:
                results["ai_params"] = pd.DataFrame()

            # Cortex usage today
            try:
                df_usage = run_query("""
                    WITH combined AS (
                        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                        WHERE USAGE_TIME >= CURRENT_DATE()
                        UNION ALL
                        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                        WHERE USAGE_TIME >= CURRENT_DATE()
                    )
                    SELECT COUNT(*) AS requests_today,
                           SUM(TOKEN_CREDITS) AS credits_today,
                           SUM(TOKENS)        AS tokens_today,
                           COUNT(DISTINCT USER_ID) AS active_users
                    FROM combined
                """, ttl_key=f"dba_cortex_usage_today_{company}", tier="live")
                results["usage_today"] = df_usage
            except Exception:
                results["usage_today"] = pd.DataFrame()

            st.session_state["dba_cortex_results"] = results

        res = st.session_state.get("dba_cortex_results", {})

        # Today's usage summary
        df_u = res.get("usage_today", pd.DataFrame())
        if not df_u.empty:
            st.subheader("Today's Cortex Usage")
            render_shell_snapshot((
                ("Requests Today", f"{safe_int(df_u['REQUESTS_TODAY'].iloc[0]):,}"),
                ("AI Credits Today", f"{safe_float(df_u['CREDITS_TODAY'].iloc[0]):.4f}"),
                ("Tokens Today", f"{safe_int(df_u['TOKENS_TODAY'].iloc[0]):,}"),
                ("Active Users", f"{safe_int(df_u['ACTIVE_USERS'].iloc[0])}"),
            ))

        # Current parameters
        df_cp = res.get("cortex_params", pd.DataFrame())
        df_ai = res.get("ai_params",     pd.DataFrame())

        combined_params = pd.concat([df_cp, df_ai], ignore_index=True) if not df_cp.empty or not df_ai.empty else pd.DataFrame()
        if not combined_params.empty:
            st.subheader("Current Cortex / AI Account Parameters")
            render_priority_dataframe(
                combined_params,
                title="Cortex / AI account parameters",
                priority_columns=[
                    "key", "value", "default", "level", "description",
                    "KEY", "VALUE", "DEFAULT", "LEVEL", "DESCRIPTION",
                ],
                sort_by=["KEY", "key"],
                ascending=True,
                raw_label="All Cortex account parameters",
            )
            download_csv(combined_params, "cortex_account_params.csv")
        else:
            st.info(
                "No Cortex parameters returned from SHOW PARAMETERS. "
                "This usually means Cortex AI features are not yet enabled on this account, "
                "or the current role doesn't have SHOW PARAMETERS privilege on ACCOUNT."
            )

        st.divider()

        # -- Modify parameters -------------------------------------------------
        st.subheader("Modify Cortex AI Account Parameters")
        st.caption(
            "Only account parameters returned by Snowflake can be applied here. "
            "Cortex Search, Analyst, and Intelligence access are managed through feature availability, "
            "roles, databases, services, and Snowflake readiness evidence rather than generic account toggles."
        )

        with st.expander("Set Cortex Code quota", expanded=True):
            cortex_daily_limit = st.number_input(
                "CORTEX_CODE_DAILY_CREDIT_LIMIT",
                min_value=0, max_value=100000, value=0, step=100,
                key="cortex_daily_limit",
                help="Maximum Cortex Code credits per day across all users. Use 0 to skip SQL generation.",
            )
            generated_sql = (
                "-- Cortex Code quota\n"
                "-- Run as ACCOUNTADMIN\n"
                f"ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {int(cortex_daily_limit)};"
                if cortex_daily_limit > 0
                else (
                    "-- Cortex Code quota\n"
                    "-- No ALTER ACCOUNT statement generated. Set a positive daily limit to generate quota SQL."
                )
            )

            readiness_rows = pd.DataFrame([
                {
                    "CAPABILITY": "Cortex Code",
                    "DASHBOARD_ACTION": "Set daily account credit limit",
                    "READINESS_PATH": "Account parameter when available in SHOW PARAMETERS",
                },
                {
                    "CAPABILITY": "Cortex Search",
                    "DASHBOARD_ACTION": "Review grants and service objects",
                    "READINESS_PATH": "Create/search service readiness and role grants outside generic account parameters",
                },
                {
                    "CAPABILITY": "Cortex Analyst / Intelligence",
                    "DASHBOARD_ACTION": "Review semantic model, object grants, and approved roles",
                    "READINESS_PATH": "Feature and object readiness outside generic account parameters",
                },
            ])
            render_priority_dataframe(
                readiness_rows,
                title="Cortex feature readiness guidance",
                priority_columns=["CAPABILITY", "DASHBOARD_ACTION", "READINESS_PATH"],
                raw_label="All Cortex readiness guidance",
            )

            col_apply, col_dl = st.columns([1, 2])
            with col_apply:
                cortex_confirmed = _typed_confirmation(
                    "Type APPLY to enable account parameter changes",
                    "APPLY",
                    "cortex_apply_confirm",
                )
                if st.button("Apply Limit", type="primary", key="cortex_apply", disabled=admin_button_disabled()):
                    if _require_typed_confirmation(cortex_confirmed, "APPLY"):
                        if cortex_daily_limit <= 0:
                            st.info("Set a positive Cortex Code daily credit limit before applying.")
                            st.stop()
                        # CALLER MODE GUARD: ALTER ACCOUNT SET requires ACCOUNTADMIN.
                        # Since execute_as=CALLER, the caller's role must have this privilege.
                        # SNOW_SYSADMINS cannot run ALTER ACCOUNT; keep this blocked
                        # before Snowflake receives account-level parameter SQL.
                        _caller_role = str(st.session_state.get("_overwatch_current_role", "") or "").strip()
                        if not _current_role_allows_alter_account(_caller_role):
                            st.error(
                                f"ALTER ACCOUNT requires ACCOUNTADMIN. "
                                f"Your current role is `{_caller_role or 'unknown'}`. "
                                f"Switch to ACCOUNTADMIN in Snowflake and reload OVERWATCH, "
                                f"or ask an ACCOUNTADMIN owner to apply the approved account parameter change."
                            )
                        else:
                            applied = []
                            failed  = []
                            for stmt in [f"ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {int(cortex_daily_limit)}"]:
                                try:
                                    session.sql(stmt).collect()
                                    applied.append(stmt)
                                except Exception as e:
                                    failed.append(f"{stmt} -> {format_snowflake_error(e)}")

                            if applied:
                                st.success(f"{len(applied)} parameter(s) updated successfully.")
                            if failed:
                                for f_msg in failed:
                                    st.warning(f"{f_msg}")
                                st.info("Check SHOW PARAMETERS IN ACCOUNT and confirm the current role can modify account parameters.")
            with col_dl:
                render_shell_snapshot((
                    ("Account limit", "Status review"),
                    ("Apply path", "reviewed workflow"),
                    ("Rollback", "Runbook only"),
                    ("Telemetry", "Parameter review"),
                ))

        # -- Per-user Cortex policy (Enterprise) -------------------------------
        st.divider()
        st.subheader("Per-User / Per-Role Cortex Access and Quotas")
        st.caption(
            "Use shared AI spend thresholds and route Cortex access through a controlled role "
            "when per-user monthly quota enforcement is required."
        )
        st.info(
            "Tip: To enforce user quotas, revoke the blanket `SNOWFLAKE.CORTEX_USER` grant from PUBLIC, "
            "grant it only through an approved AI role, then use OVERWATCH to queue revoke/restore review."
        )
        with st.expander("Cortex access control status"):
            render_shell_snapshot((
                ("Approved AI role", "Required"),
                ("PUBLIC access", "Review"),
                ("Quota enforcement", "Dry-run first"),
                ("Parameter review", "On demand"),
            ))

    # -- TAB 15: TASK GRAPH CONTROL --------------------------------------------
    if selected_tool == "Task Graph Control":
        st.subheader("Task Graph Control")
        st.caption(
            "Cancel running queries spawned by tasks, cancel task graphs mid-run, "
            "suspend/resume individual tasks or entire DAG trees, and restart failed tasks. "
            "Requires OPERATE privilege on tasks or ACCOUNTADMIN."
        )

        task_graph_view = render_workflow_selector(
            "Task graph control view",
            "dba_task_graph_control_view",
            TASK_GRAPH_CONTROL_PANES,
            columns=3,
            show_label=True,
        )

        # -- Running task queries -----------------------------------------------
        if task_graph_view == "Running Task Queries":
            st.subheader("Queries Currently Running Under a Task")
            st.caption(
                "Shows recent ACCOUNT_USAGE query activity where QUERY_TAG or query text "
                "indicates task execution. You can cancel individual task-spawned queries here."
            )
            if st.button("Load Running Task Queries", key="tg_run_load"):
                try:
                    df_tq = run_query_or_raise(f"""
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
                          {get_user_filter_clause("user_name")}
                          AND ({qh_task_indicator})
                        ORDER BY start_time DESC
                        LIMIT 200
                    """)
                    df_tq = _prioritize_query_context(df_tq)
                    st.session_state["dba_df_tg_running"] = df_tq
                except Exception as e:
                    st.info(f"Task query activity is unavailable in this role/context: {format_snowflake_error(e)}")
                    st.session_state["dba_df_tg_running"] = pd.DataFrame()

            if st.session_state.get("dba_df_tg_running") is not None:
                df_tq = st.session_state["dba_df_tg_running"]
                if not df_tq.empty:
                    render_priority_dataframe(
                        df_tq,
                        title="Running task-spawned queries",
                        priority_columns=[
                            "QUERY_ID", "QUERY_CONTEXT", "DATABASE_NAME", "SCHEMA_NAME",
                            "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                            "EXECUTION_STATUS", "START_TIME", "ELAPSED_SEC",
                            "QUERY_TAG", "QUERY_TEXT",
                        ],
                        sort_by=["ELAPSED_SEC", "START_TIME"],
                        ascending=[False, False],
                        raw_label="All running task query rows",
                    )
                    cancel_qid = st.selectbox(
                        "Cancel query",
                        df_tq["QUERY_ID"].tolist(),
                        key="tg_cancel_qid_sel",
                    )
                    cancel_confirmed = _typed_confirmation(
                        "Type CANCEL to enable task-query cancellation",
                        "CANCEL",
                        f"tg_cancel_confirm_{cancel_qid}",
                    ) if cancel_qid else False
                    if cancel_qid and st.button(
                        "Cancel This Query",
                        type="primary",
                        key="tg_cancel_q",
                        disabled=admin_button_disabled(),
                    ):
                        if _require_typed_confirmation(cancel_confirmed, "CANCEL"):
                            try:
                                session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(cancel_qid)})").collect()
                                st.success(f"Cancel sent for `{cancel_qid}`")
                            except Exception as e:
                                st.error(f"Cancel failed: {format_snowflake_error(e)}")
                else:
                    st.success("No task-related queries currently running.")

        # -- Cancel graph / task ------------------------------------------------
        elif task_graph_view == "Cancel Graph / Task":
            st.subheader("Cancel a Running Task Graph or Individual Task Run")
            st.caption(
                "`SYSTEM$CANCEL_TASK_GRAPH(graph_run_id)` cancels an entire DAG run in progress. "
                "`SYSTEM$CANCEL_QUERY(query_id)` cancels the query spawned by a specific task run."
            )

            # Load recent task runs to get graph_run_id
            if st.button("Load Recent Task Runs", key="tg_runs_load"):
                try:
                    df_tasks = _load_task_inventory(session, force_refresh=True)
                    df_runs = load_live_task_runs(session, df_tasks, hours_back=6)
                    if df_runs.empty:
                        df_runs = run_query_or_raise(_task_history_sql(
                            session,
                            "scheduled_time >= DATEADD('hours', -6, CURRENT_TIMESTAMP())",
                            limit=200,
                        ))
                    st.session_state["dba_df_task_runs"] = df_runs
                except Exception as e:
                    st.warning(f"Task run history unavailable: {format_snowflake_error(e)}")

            if st.session_state.get("dba_df_task_runs") is not None and not st.session_state["dba_df_task_runs"].empty:
                df_r = st.session_state["dba_df_task_runs"]

                # Filter to running only
                running_runs = df_r[df_r["STATE"].isin(["EXECUTING","RUNNING"])] if "STATE" in df_r.columns else pd.DataFrame()

                if not running_runs.empty:
                    st.warning(f"{len(running_runs)} task run(s) currently executing or scheduled.")
                    render_priority_dataframe(
                        running_runs,
                        title="Running or scheduled task runs",
                        priority_columns=[
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                            "SCHEDULED_TIME", "QUERY_ID", "GRAPH_RUN_GROUP_ID",
                            "DURATION_SEC", "ERROR_MESSAGE",
                        ],
                        sort_by=["SCHEDULED_TIME", "DURATION_SEC"],
                        ascending=[False, False],
                        raw_label="All active task run rows",
                    )

                    # Cancel by graph run group
                    st.markdown("**Cancel by Graph Run Group ID** (cancels all tasks in that DAG run)")
                    if "GRAPH_RUN_GROUP_ID" in running_runs.columns:
                        graph_ids = running_runs["GRAPH_RUN_GROUP_ID"].dropna().unique().tolist()
                        if graph_ids:
                            sel_graph = st.selectbox(
                                "Select Graph Run Group ID to cancel",
                                graph_ids,
                                key="tg_cancel_graph_sel",
                            )
                            col_cg1, col_cg2 = st.columns([1,3])
                            with col_cg1:
                                with st.form(f"tg_cancel_graph_form_{sel_graph}"):
                                    graph_confirm_text = st.text_input(
                                        "Type CANCEL to enable graph cancellation",
                                        key=f"tg_graph_confirm_{sel_graph}",
                                        placeholder="CANCEL",
                                    )
                                    submitted = st.form_submit_button(
                                        "Cancel Graph Run",
                                        type="primary",
                                        disabled=admin_button_disabled(),
                                    )
                                if submitted:
                                    graph_confirmed = str(graph_confirm_text or "").strip() == "CANCEL"
                                    if _require_typed_confirmation(graph_confirmed, "CANCEL"):
                                        try:
                                            session.sql(
                                                f"SELECT SYSTEM$CANCEL_TASK_GRAPH({sql_literal(str(sel_graph))})"
                                            ).collect()
                                            st.success(f"Graph run `{sel_graph}` cancelled.")
                                            st.session_state.pop("dba_df_task_runs", None)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Cancel graph failed: {format_snowflake_error(e)}")
                                            st.info(
                                                "SYSTEM$CANCEL_TASK_GRAPH requires the task to be running and the caller to have "
                                                "OPERATE privilege on the root task, or ACCOUNTADMIN."
                                            )

                    # Cancel individual query from a task run
                    st.markdown("**Cancel individual task run query**")
                    if "QUERY_ID" in running_runs.columns:
                        query_ids = running_runs["QUERY_ID"].dropna().unique().tolist()
                        if query_ids:
                            sel_qid = st.selectbox("Select Query ID", query_ids, key="tg_cancel_run_qid")
                            with st.form(f"tg_cancel_run_query_form_{sel_qid}"):
                                run_confirm_text = st.text_input(
                                    "Type CANCEL to enable run-query cancellation",
                                    key=f"tg_run_confirm_{sel_qid}",
                                    placeholder="CANCEL",
                                )
                                submitted = st.form_submit_button(
                                    "Cancel Query",
                                    disabled=admin_button_disabled(),
                                )
                            if sel_qid and submitted:
                                run_confirmed = str(run_confirm_text or "").strip() == "CANCEL"
                                if _require_typed_confirmation(run_confirmed, "CANCEL"):
                                    try:
                                        session.sql(f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(str(sel_qid))})").collect()
                                        st.success(f"Cancel sent for `{sel_qid}`")
                                    except Exception as e:
                                        st.error(f"Cancel failed: {format_snowflake_error(e)}")
                else:
                    st.success("No task runs currently executing.")
                    st.subheader("Recent History (last 6h)")
                    render_priority_dataframe(
                        df_r,
                        title="Recent task run history",
                        priority_columns=[
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                            "SCHEDULED_TIME", "COMPLETED_TIME", "DURATION_SEC",
                            "QUERY_ID", "ERROR_MESSAGE",
                        ],
                        sort_by=["SCHEDULED_TIME"],
                        ascending=False,
                        max_rows=50,
                        raw_label="All recent task run rows",
                    )

        # -- Suspend / Resume --------------------------------------------------
        elif task_graph_view == "Suspend / Resume":
            st.subheader("Suspend / Resume Tasks and DAG Trees")
            st.caption(
                "Suspend or resume individual tasks or entire DAG hierarchies. "
                "Suspending a root task stops the whole graph from scheduling. "
                "Suspending a child task pauses that branch only."
            )

            # Load task list for selection
            if st.button("Load Task List", key="tg_mgmt_load"):
                try:
                    df_tasks = _load_task_inventory(session, force_refresh=True)
                    st.session_state["dba_df_tg_tasks"] = df_tasks
                except Exception as e:
                    st.warning(f"Task inventory unavailable: {format_snowflake_error(e)}")

            df_tasks = st.session_state.get("dba_df_tg_tasks", pd.DataFrame())
            if not df_tasks.empty:
                # Metrics
                started   = df_tasks[df_tasks["STATE"] == "started"]  if "STATE" in df_tasks.columns else pd.DataFrame()
                suspended = df_tasks[df_tasks["STATE"] == "suspended"] if "STATE" in df_tasks.columns else pd.DataFrame()
                render_shell_snapshot((
                    ("Total Tasks", f"{len(df_tasks):,}"),
                    ("Active", f"{len(started):,}"),
                    ("Suspended", f"{len(suspended):,}"),
                ))

                task_display_cols = (
                    ["NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "SCHEDULE", "WAREHOUSE"]
                    if all(c in df_tasks.columns for c in ["NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "SCHEDULE", "WAREHOUSE"])
                    else df_tasks.columns.tolist()
                )
                render_priority_dataframe(
                    df_tasks[task_display_cols],
                    title="Task inventory by operational state",
                    priority_columns=task_display_cols,
                    sort_by=["STATE", "DATABASE_NAME", "SCHEMA_NAME", "NAME"],
                    ascending=[True, True, True, True],
                    raw_label="All task inventory rows",
                    height=250,
                )

                st.divider()

                # Single task control
                st.subheader("Control Individual Task")
                task_names = df_tasks["NAME"].unique().tolist() if "NAME" in df_tasks.columns else []
                sel_task   = st.selectbox("Select task", task_names, key="tg_mgmt_sel")

                if sel_task:
                    task_row = df_tasks[df_tasks["NAME"] == sel_task].iloc[0]
                    db_n   = task_row.get("DATABASE_NAME","")
                    sch_n  = task_row.get("SCHEMA_NAME","")
                    state  = task_row.get("STATE","")
                    full_n = _qualified_name(db_n, sch_n, sel_task)
                    preds  = task_row.get("PREDECESSORS","")

                    st.info(f"`{full_n}` | State: **{state}** | Predecessors: `{preds or 'none (root task)'}`")
                    task_confirmed = _typed_confirmation(
                        "Type the task name to enable task controls",
                        sel_task,
                        f"tg_confirm_{sel_task}",
                    )

                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)

                    with col_s1:
                        if st.button("Suspend", key="tg_suspend", disabled=admin_button_disabled(state=="suspended")):
                            if _require_typed_confirmation(task_confirmed, sel_task):
                                try:
                                    session.sql(f"ALTER TASK {full_n} SUSPEND").collect()
                                    st.success(f"`{sel_task}` suspended.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Suspend failed: {format_snowflake_error(e)}")

                    with col_s2:
                        if st.button("Resume", key="tg_resume", disabled=admin_button_disabled(state=="started")):
                            if _require_typed_confirmation(task_confirmed, sel_task):
                                try:
                                    session.sql(f"ALTER TASK {full_n} RESUME").collect()
                                    st.success(f"`{sel_task}` resumed.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Resume failed: {format_snowflake_error(e)}")

                    with col_s3:
                        if st.button("Execute Now", key="tg_execute", disabled=admin_button_disabled()):
                            if _require_typed_confirmation(task_confirmed, sel_task):
                                try:
                                    session.sql(f"EXECUTE TASK {full_n}").collect()
                                    st.success(f"`{sel_task}` triggered.")
                                except Exception as e:
                                    st.error(f"Execute failed: {format_snowflake_error(e)}")

                    with col_s4:
                        if st.button("Retry Last Failed", key="tg_retry", disabled=admin_button_disabled()):
                            # EXECUTE TASK WITH LAST_ERROR retry pattern
                            if _require_typed_confirmation(task_confirmed, sel_task):
                                try:
                                    session.sql(f"EXECUTE TASK {full_n}").collect()
                                    st.success(f"Retry triggered for `{sel_task}`.")
                                    st.caption(
                                        "Note: Snowflake does not have a native RETRY_LAST_FAILED command. "
                                        "This re-executes the task immediately. "
                                        "For DAG-level retry, use EXECUTE TASK on the root task."
                                    )
                                except Exception as e:
                                    st.error(f"Retry failed: {format_snowflake_error(e)}")

                st.divider()

                # Bulk suspend/resume entire DAG tree
                st.subheader("Bulk Suspend / Resume Entire DAG Tree")
                st.caption(
                    "Suspending the root task stops the entire graph from scheduling. "
                    "Select a root task (one with no predecessors) below."
                )
                root_tasks = df_tasks[
                    df_tasks.get("PREDECESSORS", pd.Series()).astype(str).str.strip().isin(["","[]","None","nan"])
                ] if "PREDECESSORS" in df_tasks.columns else df_tasks

                if not root_tasks.empty:
                    root_names = root_tasks["NAME"].unique().tolist() if "NAME" in root_tasks.columns else []
                    sel_root   = st.selectbox("Select root task (suspends entire graph)", root_names, key="tg_root_sel")

                    if sel_root:
                        root_row  = df_tasks[df_tasks["NAME"] == sel_root].iloc[0]
                        root_full = _qualified_name(
                            root_row.get("DATABASE_NAME", ""),
                            root_row.get("SCHEMA_NAME", ""),
                            sel_root,
                        )

                        # Find all children
                        children = df_tasks[
                            df_tasks.get("PREDECESSORS","").astype(str).str.contains(sel_root, na=False)
                        ] if "PREDECESSORS" in df_tasks.columns else pd.DataFrame()

                        st.info(
                            f"Root: `{root_full}` | "
                            f"Child tasks in this graph: {len(children)} | "
                            f"Total tasks affected: {len(children)+1}"
                        )
                        graph_confirmed = _typed_confirmation(
                            "Type the root task name to enable graph controls",
                            sel_root,
                            f"tg_graph_confirm_{sel_root}",
                        )

                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("Suspend Entire Graph", type="primary", key="tg_bulk_suspend", disabled=admin_button_disabled()):
                                if _require_typed_confirmation(graph_confirmed, sel_root):
                                    try:
                                        session.sql(f"ALTER TASK {root_full} SUSPEND").collect()
                                        st.success(f"Root task `{sel_root}` suspended - entire graph will stop scheduling.")
                                        st.session_state.pop("dba_df_tg_tasks", None)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Suspend failed: {format_snowflake_error(e)}")
                        with b2:
                            if st.button("Resume Entire Graph", type="primary", key="tg_bulk_resume", disabled=admin_button_disabled()):
                                if _require_typed_confirmation(graph_confirmed, sel_root):
                                    errors_seen = []
                                    # Resume children first, then root
                                    for _, child in children.iterrows():
                                        full_child = _qualified_name(
                                            child.get("DATABASE_NAME", ""),
                                            child.get("SCHEMA_NAME", ""),
                                            child.get("NAME", ""),
                                        )
                                        try:
                                            session.sql(f"ALTER TASK {full_child} RESUME").collect()
                                        except Exception as e:
                                            errors_seen.append(f"{full_child}: {format_snowflake_error(e)}")
                                    try:
                                        session.sql(f"ALTER TASK {root_full} RESUME").collect()
                                    except Exception as e:
                                        errors_seen.append(f"{root_full}: {format_snowflake_error(e)}")

                                    if errors_seen:
                                        st.warning(f"Resumed with {len(errors_seen)} error(s):")
                                        for err in errors_seen:
                                            st.caption(err)
                                    else:
                                        st.success(f"Entire graph resumed. {len(children)+1} task(s) active.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()

        # -- DAG Inspector -----------------------------------------------------
        elif task_graph_view == "DAG Inspector":
            st.subheader("DAG Inspector")
            st.caption(
                "Visualise the task dependency tree for a selected root task. "
                "Shows each node's current state, last run result, and duration."
            )

            df_tasks = st.session_state.get("dba_df_tg_tasks", pd.DataFrame())
            if df_tasks.empty:
                st.info("Load the task list in the Suspend/Resume tab first.")
            else:
                root_tasks = df_tasks[
                    df_tasks.get("PREDECESSORS", pd.Series()).astype(str).str.strip().isin(["","[]","None","nan"])
                ] if "PREDECESSORS" in df_tasks.columns else df_tasks
                root_names = root_tasks["NAME"].unique().tolist() if not root_tasks.empty else df_tasks["NAME"].unique().tolist()
                sel_dag = st.selectbox("Select root task to inspect", root_names, key="tg_dag_sel")

                if sel_dag and st.button("Refresh DAG View", key="tg_dag_build"):
                    try:
                        df_dag = df_tasks[
                            (df_tasks["NAME"].astype(str) == str(sel_dag))
                            | df_tasks.get("PREDECESSORS", pd.Series(index=df_tasks.index, dtype=str)).astype(str).str.contains(str(sel_dag), na=False)
                        ].copy()
                        if not df_dag.empty:
                            task_names = [str(v) for v in df_dag["NAME"].dropna().unique().tolist()]
                            try:
                                df_hist = run_query_or_raise(_task_history_sql(
                                    session,
                                    "scheduled_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
                                    limit=500,
                                ))
                                if "DURATION_SEC" in df_hist.columns:
                                    df_hist = df_hist.rename(columns={"DURATION_SEC": "LAST_DURATION_SEC"})
                                if not df_hist.empty:
                                    if "NAME" not in df_hist.columns and "TASK_NAME" in df_hist.columns:
                                        df_hist = df_hist.rename(columns={"TASK_NAME": "NAME"})
                                    if "NAME" not in df_hist.columns:
                                        df_hist = pd.DataFrame()
                                    else:
                                        df_hist = df_hist[df_hist["NAME"].astype(str).isin(task_names)].copy()
                                    if "STATE" in df_hist.columns:
                                        df_hist = df_hist.rename(columns={"STATE": "LAST_RUN_STATE"})
                                    if "ERROR_MESSAGE" in df_hist.columns:
                                        df_hist = df_hist.rename(columns={"ERROR_MESSAGE": "LAST_ERROR"})
                                    if "SCHEDULED_TIME" in df_hist.columns:
                                        df_hist = df_hist.rename(columns={"SCHEDULED_TIME": "LAST_RUN_TIME"})
                                if not df_hist.empty and "NAME" in df_hist.columns:
                                    if "LAST_RUN_TIME" in df_hist.columns:
                                        df_hist = df_hist.sort_values("LAST_RUN_TIME", ascending=False)
                                    df_hist = df_hist.drop_duplicates("NAME")
                                    df_dag = df_dag.merge(
                                        df_hist,
                                        how="left",
                                        on="NAME",
                                    )
                            except Exception:
                                pass
                        st.session_state["dba_df_dag_view"] = df_dag
                    except Exception as e:
                        st.warning(f"DAG view unavailable in this role/context: {format_snowflake_error(e)}")

                if st.session_state.get("dba_df_dag_view") is not None and not st.session_state["dba_df_dag_view"].empty:
                    df_dag = st.session_state["dba_df_dag_view"]

                    # Visual tree using indented text
                    st.markdown("**Task Dependency Tree**")
                    for _, row in df_dag.iterrows():
                        name   = row.get("NAME","")
                        preds  = str(row.get("PREDECESSORS","") or "")
                        state  = str(row.get("STATE","")).lower()
                        lr_st  = str(row.get("LAST_RUN_STATE","") or "")
                        dur    = row.get("LAST_DURATION_SEC", 0) or 0
                        err    = str(row.get("LAST_ERROR","") or "")[:80]

                        is_root = preds.strip() in ("","[]","None","nan","")
                        indent  = "" if is_root else "- "

                        state_icon = "Started" if state=="started" else "Suspended" if state=="suspended" else "Unknown"
                        lr_icon    = "Succeeded" if lr_st=="SUCCEEDED" else ("Failed" if lr_st=="FAILED" else "Pending")

                        prefix = "    " if indent else ""
                        suffix = f" - {err}" if err and err != "nan" else ""
                        st.markdown(
                            f"{prefix}{indent}{state_icon} **{name}** | {lr_icon} last: {lr_st} "
                            f"({int(dur)}s){suffix}"
                        )

                    render_priority_dataframe(
                        df_dag,
                        title="DAG detail rows",
                        priority_columns=[
                            "NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "PREDECESSORS",
                            "LAST_RUN_STATE", "LAST_RUN_TIME", "LAST_DURATION_SEC", "LAST_ERROR",
                        ],
                        sort_by=["LAST_RUN_STATE", "LAST_DURATION_SEC", "LAST_RUN_TIME"],
                        ascending=[True, False, False],
                        raw_label="All DAG rows",
                    )
                    download_csv(df_dag, f"dag_{sel_dag}.csv")

    if selected_tool == "Operational Audit":
        st.subheader("Operational Audit")
        st.info("Operational audit details are reserved for DBA platform administrators.")

    # Cost formula audit
    if selected_tool == "Cost Formula Audit":
        st.subheader("Cost Formula Audit")
        st.caption(
            "Documents which OVERWATCH cost numbers reconcile to Snowflake billing "
            "sources and which are allocation or forecast estimates."
        )

        audit_df = build_cost_formula_audit()
        exact_count = int(audit_df["CONFIDENCE"].str.contains("Exact", case=False, na=False).sum())
        estimate_count = int(audit_df["CONFIDENCE"].str.contains("estimate|forecast|mixed|allocated", case=False, na=False).sum())
        rows_count = len(audit_df)
        render_shell_snapshot((
            ("Formula Checks", f"{rows_count:,}"),
            ("Source-of-Truth", f"{exact_count:,}"),
            ("Estimated / Allocated", f"{estimate_count:,}"),
        ))

        audit_view = audit_df.rename(columns={"CONFIDENCE": "MEASUREMENT_BASIS"})
        render_priority_dataframe(
            audit_view,
            title="Cost formula validation",
            priority_columns=["METRIC", "MEASUREMENT_BASIS", "FORMULA", "NOTES"],
            sort_by=["MEASUREMENT_BASIS", "METRIC"],
            ascending=[True, True],
            raw_label="All formula checks",
        )
        download_csv(audit_df, "overwatch_cost_formula_audit.csv")

        st.subheader("Reconciliation Checks")
        st.caption(
            "Use Snowflake billing, warehouse metering, and action-queue evidence when leadership asks why a number changed."
        )
        render_shell_snapshot((
            ("Warehouse metering", "Billing-aligned"),
            ("Account services", "Completed windows"),
            ("Currency view", "When billing access exists"),
            ("Chargeback", "Allocated / estimated"),
        ))

    # Data readiness and install readiness
    if selected_tool == "Data Health":
        st.subheader("Data Health")
        st.caption("Release health checks for access, persistent objects, formulas, and operational coverage.")
        defer_source_note(
            "Run Data Health before release promotion to check Snowflake view access, optional account columns, "
            "persistent objects, formula validation, and operational coverage."
        )

        st.subheader("Snowflake Compatibility Check")
        defer_source_note(
            "Validates required ACCOUNT_USAGE views, optional columns that vary by account, "
            "and SHOW commands used by DBA operations."
        )
        if st.button("Run Compatibility Check", key="compatibility_check_load"):
            st.session_state["dba_compatibility_status"] = run_compatibility_checks(session)

        if st.session_state.get("dba_compatibility_status") is not None:
            compat_df = st.session_state["dba_compatibility_status"]
            if not compat_df.empty:
                ready_count = int((compat_df["STATUS"] == "Ready").sum())
                limited_count = int((compat_df["STATUS"] == "Limited").sum())
                blocked_count = int((~compat_df["STATUS"].isin(["Ready", "Limited"])).sum())
                render_shell_snapshot((
                    ("Ready", f"{ready_count:,}"),
                    ("Limited", f"{limited_count:,}"),
                    ("Blocked", f"{blocked_count:,}"),
                ))
                render_priority_dataframe(
                    compat_df,
                    title="Compatibility checks needing attention",
                    priority_columns=["CATEGORY", "CHECK", "STATUS", "USED_BY", "DETAIL", "IMPACT"],
                    sort_by=["STATUS", "CATEGORY"],
                    ascending=[True, True],
                    raw_label="All compatibility checks",
                )
                download_csv(compat_df, "overwatch_compatibility_check.csv")

                blocked = compat_df[~compat_df["STATUS"].isin(["Ready", "Limited"])]
                if not blocked.empty:
                    st.warning(
                        "Some checks are blocked. Affected sections should show graceful "
                        "limited-data messages instead of crashing."
                    )

        st.divider()
        st.subheader("Company Scope Audit")
        defer_source_note(
            "Find warehouses and databases that are not matched to the ALFA or Trexis allowlists. "
            "Review this before widening company filters."
        )
        if st.button("Load Unclassified Assets", key="scope_audit_load"):
            st.session_state["dba_unclassified_assets"] = run_query(
                build_unclassified_assets_sql(30),
                ttl_key=f"dba_scope_audit_{company}",
                tier="standard",
                section="Change & Drift",
            )
        unclassified = st.session_state.get("dba_unclassified_assets")
        if unclassified is not None:
            if unclassified.empty:
                st.success("No unclassified warehouses or databases found in the last 30 days.")
            else:
                wh_count = int((unclassified["OBJECT_TYPE"] == "WAREHOUSE").sum()) if "OBJECT_TYPE" in unclassified.columns else 0
                db_count = int((unclassified["OBJECT_TYPE"] == "DATABASE").sum()) if "OBJECT_TYPE" in unclassified.columns else 0
                render_shell_snapshot((
                    ("Unclassified Warehouses", f"{wh_count:,}"),
                    ("Unclassified Databases", f"{db_count:,}"),
                ))
                render_priority_dataframe(
                    unclassified,
                    title="Unclassified scope assets",
                    priority_columns=["OBJECT_TYPE", "OBJECT_NAME", "DATABASE_NAME", "WAREHOUSE_NAME", "LAST_SEEN"],
                    sort_by=["OBJECT_TYPE", "OBJECT_NAME"],
                    ascending=[True, True],
                    raw_label="All unclassified assets",
                )
                download_csv(unclassified, "overwatch_unclassified_assets.csv")

        st.divider()
        st.subheader("Persistent Data Objects")

        c1, c2 = st.columns([1, 2])
        with c1:
            if st.button("Check Data Health", key="setup_status_load"):
                st.session_state["dba_setup_status"] = _setup_status_df(session)
        with c2:
            st.info("Snowflake object status is owned by the DBA platform team for this environment.")
            defer_source_note(
                f"Review object availability in {ALERT_DB}.{ALERT_SCHEMA} and confirm alert task route context before enabling actions."
            )

        if st.session_state.get("dba_setup_status") is not None:
            status_df = st.session_state["dba_setup_status"]
            missing_count = int((status_df["STATUS"] == "Missing").sum())
            unknown_count = int((status_df["STATUS"] == "Unknown").sum())

            render_shell_snapshot((
                ("Objects Checked", f"{len(status_df):,}"),
                ("Missing", f"{missing_count:,}"),
                ("Unknown", f"{unknown_count:,}"),
            ))
            status_display = status_df.drop(columns=["OBJECT_NAME"], errors="ignore")
            render_priority_dataframe(
                status_display,
                title="Persistent data health",
                priority_columns=["FEATURE", "STATUS"],
                sort_by=["STATUS", "FEATURE"],
                ascending=[True, True],
                raw_label="All data-health objects",
            )

        st.divider()
        st.subheader("Persistent Data Refresh Status")
        defer_source_note(
            "The migration ledger compares expected status version to the deployed summary version."
        )
        c_mig_load, c_mig_hint = st.columns([1, 2])
        with c_mig_load:
            if st.button("Check Refresh Status", key="schema_migration_status_load", width="stretch"):
                try:
                    st.session_state["dba_schema_migration_status"] = run_query(
                        build_schema_migration_status_sql(),
                        ttl_key="dba_schema_migration_status",
                        tier="recent",
                        section="Change & Drift",
                    )
                    st.session_state["dba_schema_migration_status_error"] = ""
                except Exception as exc:
                    st.session_state["dba_schema_migration_status"] = pd.DataFrame()
                    st.session_state["dba_schema_migration_status_error"] = format_snowflake_error(exc)
        with c_mig_hint:
            st.info("Use this before release promotion or after the DBA team refreshes status objects.")

        migration_status = st.session_state.get("dba_schema_migration_status")
        migration_error = st.session_state.get("dba_schema_migration_status_error", "")
        if migration_error:
            st.warning("Migration ledger is not available yet.")
            defer_source_note(migration_error)
        if isinstance(migration_status, pd.DataFrame) and not migration_status.empty:
            blockers = int(migration_status["MIGRATION_STATE"].astype(str).isin(["Blocked", "Version Drift"]).sum())
            render_shell_snapshot((
                ("Migration Rows", f"{len(migration_status):,}"),
                ("Blockers", f"{blockers:,}"),
            ))
            migration_display = migration_status.drop(
                columns=["OBJECT_NAME", "REQUIRED_VERSION", "DEPLOYED_VERSION"],
                errors="ignore",
            )
            render_priority_dataframe(
                migration_display,
                title="Deployed mart migration status",
                priority_columns=[
                    "COMPONENT", "OBJECT_STATE", "LATEST_APPLIED_AT", "MIGRATION_STATE", "NEXT_ACTION",
                ],
                sort_by=["MIGRATION_STATE", "COMPONENT"],
                ascending=[True, True],
                raw_label="All migration status rows",
            )
        else:
            render_priority_dataframe(
                build_schema_migration_contract(),
                title="Expected readiness contract",
                priority_columns=[
                    "COMPONENT", "WHY_IT_MATTERS", "READY_CRITERIA",
                ],
                raw_label="All expected readiness rows",
            )

        st.divider()
        st.subheader("Cost Formula Validation")
        cost_formula_df = build_cost_formula_audit()
        cost_formula_view = cost_formula_df.rename(columns={"CONFIDENCE": "MEASUREMENT_BASIS"})
        render_priority_dataframe(
            cost_formula_view,
            title="Cost formula validation",
            priority_columns=["METRIC", "MEASUREMENT_BASIS", "FORMULA", "NOTES"],
            sort_by=["MEASUREMENT_BASIS", "METRIC"],
            ascending=[True, True],
            raw_label="All formula checks",
        )

        st.info("Persistent object changes are owned by the DBA platform release process, outside the dashboard.")
