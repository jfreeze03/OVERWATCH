# utils/action_queue.py - persistent recommendation/action queue helpers
import hashlib

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from .company_filter import get_active_company, get_active_environment, get_environment_cfg
from .query import run_query, safe_identifier, sql_literal


ACTION_QUEUE_FQN = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier(ACTION_QUEUE_TABLE)}"
)

ACTION_QUEUE_OPTIONAL_COLUMN_TYPES = {
    "ENVIRONMENT": "VARCHAR",
    "TICKET_ID": "VARCHAR",
    "APPROVER": "VARCHAR",
    "DUE_DATE": "DATE",
    "VERIFICATION_STATUS": "VARCHAR",
    "VERIFICATION_NOTES": "VARCHAR",
    "VERIFICATION_QUERY": "VARCHAR",
    "VERIFICATION_RESULT": "VARCHAR",
    "BASELINE_VALUE": "FLOAT",
    "CURRENT_VALUE": "FLOAT",
    "MEASURED_DELTA": "FLOAT",
    "VERIFIED_BY": "VARCHAR",
    "VERIFIED_AT": "TIMESTAMP_NTZ",
}


def make_action_id(category: str, entity: str, finding: str) -> str:
    raw = f"{category}|{entity}|{finding}".upper().encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:16].upper()


def build_action_queue_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ACTION_QUEUE_TABLE,
) -> str:
    db = safe_identifier(db)
    schema = safe_identifier(schema)
    table = safe_identifier(table)
    fqn = f"{db}.{schema}.{table}"
    return f"""-- OVERWATCH persistent recommendation/action queue
CREATE DATABASE IF NOT EXISTS {db};
CREATE SCHEMA IF NOT EXISTS {db}.{schema};

CREATE TABLE IF NOT EXISTS {fqn} (
    ACTION_ID                 VARCHAR(64) PRIMARY KEY,
    CREATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SOURCE                    VARCHAR(100),
    CATEGORY                  VARCHAR(100),
    SEVERITY                  VARCHAR(20),
    ENTITY_TYPE               VARCHAR(100),
    ENTITY_NAME               VARCHAR(500),
    OWNER                     VARCHAR(200),
    STATUS                    VARCHAR(40) DEFAULT 'New',
    FINDING                   VARCHAR(4000),
    RECOMMENDED_ACTION        VARCHAR(4000),
    EST_MONTHLY_SAVINGS       FLOAT,
    GENERATED_SQL_FIX         VARCHAR(8000),
    PROOF_QUERY               VARCHAR(8000),
    COMPANY                   VARCHAR(100),
    ENVIRONMENT               VARCHAR(100),
    TICKET_ID                 VARCHAR(200),
    APPROVER                  VARCHAR(200),
    DUE_DATE                  DATE,
    VERIFICATION_STATUS       VARCHAR(40) DEFAULT 'Pending',
    VERIFICATION_NOTES        VARCHAR(4000),
    VERIFICATION_QUERY        VARCHAR(8000),
    VERIFICATION_RESULT       VARCHAR(8000),
    BASELINE_VALUE            FLOAT,
    CURRENT_VALUE             FLOAT,
    MEASURED_DELTA            FLOAT,
    VERIFIED_BY               VARCHAR(200),
    VERIFIED_AT               TIMESTAMP_NTZ,
    ACKNOWLEDGED_BY           VARCHAR(200),
    ACKNOWLEDGED_AT           TIMESTAMP_NTZ,
    FIXED_BY                  VARCHAR(200),
    FIXED_AT                  TIMESTAMP_NTZ,
    IGNORED_REASON            VARCHAR(2000),
    LAST_SEEN_AT              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SEEN_COUNT                NUMBER DEFAULT 1
);"""


def _action_queue_has_column(session, column: str) -> bool:
    """Return whether the deployed action queue has an optional column."""
    column = str(column or "").upper()
    if not column:
        return False
    cache_key = f"_overwatch_action_queue_has_{column.lower()}"
    if cache_key in st.session_state:
        return bool(st.session_state[cache_key])
    try:
        rows = session.sql(
            f"SHOW COLUMNS LIKE {sql_literal(column, 200)} IN TABLE {ACTION_QUEUE_FQN}"
        ).collect()
        found = bool(rows)
    except Exception:
        found = False
    st.session_state[cache_key] = found
    return found


def action_queue_environment_values(environment: str | None = None) -> list[str]:
    """Return environment values that should stay visible for the active scope."""
    env = str(environment or get_active_environment() or "").upper()
    common = ["", "ALL", "NO DATABASE CONTEXT", "OTHER / SHARED"]
    if env in ("", "ALL"):
        return common
    values = common + [env]
    if env == "DEV_ALL":
        values.extend(str(value).upper() for value in get_environment_cfg("DEV_ALL").get("db_patterns", []))
    elif env.startswith("ALFA_EDW_"):
        values.append("DEV_ALL")
    return list(dict.fromkeys(values))


def action_queue_environment_clause(column: str = "ENVIRONMENT", environment: str | None = None) -> str:
    """Build a permissive action-queue environment filter.

    Rows without database context remain visible, which prevents PROD/DEV
    filtering from hiding account-level or warehouse-only findings.
    """
    values = action_queue_environment_values(environment)
    env = str(environment or get_active_environment() or "").upper()
    if env in ("", "ALL"):
        return ""
    literals = ", ".join(sql_literal(value, 100) for value in values)
    return f"UPPER(COALESCE({column}, '')) IN ({literals})"


def action_queue_fixed_missing_fields(
    *,
    status: str,
    verification_notes: str = "",
    verification_result: str = "",
) -> list[str]:
    """Return missing evidence fields required before an item can be closed."""
    if str(status or "").strip() != "Fixed":
        return []
    missing = []
    if len(str(verification_notes or "").strip()) < 15:
        missing.append("verification notes")
    if len(str(verification_result or "").strip()) < 15:
        missing.append("verification result")
    return missing


def _action_value(action: dict, *keys: str, default: str = ""):
    for key in keys:
        if key in action and action.get(key) not in (None, ""):
            return action.get(key)
    return default


def _optional_column_select(session, column: str) -> str:
    column = str(column or "").upper()
    col_ident = safe_identifier(column)
    if _action_queue_has_column(session, column):
        return col_ident
    col_type = ACTION_QUEUE_OPTIONAL_COLUMN_TYPES.get(column, "VARCHAR")
    return f"NULL::{col_type} AS {col_ident}"


def _float_or_none(value: object) -> str:
    try:
        if value in (None, ""):
            return "NULL"
        return str(float(value))
    except Exception:
        return "NULL"


def _num(value: object) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def upsert_actions(session, actions: list[dict]) -> int:
    if not actions:
        return 0
    has_environment = _action_queue_has_column(session, "ENVIRONMENT")
    optional_has = {
        column: _action_queue_has_column(session, column)
        for column in ACTION_QUEUE_OPTIONAL_COLUMN_TYPES
    }
    count = 0
    for action in actions:
        action_id = sql_literal(action.get("Action ID") or make_action_id(
            action.get("Category", "General"),
            action.get("Entity", ""),
            action.get("Finding", ""),
        ), max_len=64)
        source = sql_literal(action.get("Source", "Recommendations"), max_len=100)
        category = sql_literal(action.get("Category", "General"), max_len=100)
        severity = sql_literal(action.get("Severity", "Medium"), max_len=20)
        entity_type = sql_literal(action.get("Entity Type", "Snowflake Object"), max_len=100)
        entity_name = sql_literal(action.get("Entity", ""), max_len=500)
        owner = sql_literal(action.get("Owner", "DBA"), max_len=200)
        finding = sql_literal(action.get("Finding", ""), max_len=4000)
        recommended = sql_literal(action.get("Action", ""), max_len=4000)
        sql_fix = sql_literal(action.get("Generated SQL Fix", ""), max_len=8000)
        proof = sql_literal(action.get("Proof Query", ""), max_len=8000)
        company = sql_literal(action.get("Company", ""), max_len=100)
        environment = sql_literal(action.get("Environment") or action.get("ENVIRONMENT") or "", max_len=100)
        ticket_id = sql_literal(_action_value(action, "Ticket ID", "TICKET_ID"), max_len=200)
        approver = sql_literal(_action_value(action, "Approver", "APPROVER"), max_len=200)
        due_date = sql_literal(_action_value(action, "Due Date", "DUE_DATE"), max_len=20)
        verification_status = sql_literal(
            _action_value(action, "Verification Status", "VERIFICATION_STATUS", default="Pending"),
            max_len=40,
        )
        verification_query = sql_literal(
            _action_value(action, "Verification Query", "VERIFICATION_QUERY", "Proof Query"),
            max_len=8000,
        )
        baseline_value = _float_or_none(_action_value(action, "Baseline Value", "BASELINE_VALUE", default=None))
        current_value = _float_or_none(_action_value(action, "Current Value", "CURRENT_VALUE", default=None))
        measured_delta = _float_or_none(_action_value(action, "Measured Delta", "MEASURED_DELTA", default=None))
        savings = _num(action.get("Estimated Monthly Savings", 0))
        env_update = f", ENVIRONMENT = {environment}" if has_environment else ""
        env_insert_col = ", ENVIRONMENT" if has_environment else ""
        env_insert_val = f", {environment}" if has_environment else ""
        optional_update = ""
        optional_insert_cols = ""
        optional_insert_vals = ""
        if optional_has.get("TICKET_ID"):
            optional_update += f", TICKET_ID = COALESCE(NULLIF({ticket_id}, ''), tgt.TICKET_ID)"
            optional_insert_cols += ", TICKET_ID"
            optional_insert_vals += f", {ticket_id}"
        if optional_has.get("APPROVER"):
            optional_update += f", APPROVER = COALESCE(NULLIF({approver}, ''), tgt.APPROVER)"
            optional_insert_cols += ", APPROVER"
            optional_insert_vals += f", {approver}"
        if optional_has.get("DUE_DATE"):
            optional_update += f", DUE_DATE = COALESCE(TRY_TO_DATE(NULLIF({due_date}, '')), tgt.DUE_DATE)"
            optional_insert_cols += ", DUE_DATE"
            optional_insert_vals += f", TRY_TO_DATE(NULLIF({due_date}, ''))"
        if optional_has.get("VERIFICATION_STATUS"):
            optional_update += ", VERIFICATION_STATUS = COALESCE(tgt.VERIFICATION_STATUS, 'Pending')"
            optional_insert_cols += ", VERIFICATION_STATUS"
            optional_insert_vals += f", {verification_status}"
        if optional_has.get("VERIFICATION_QUERY"):
            optional_update += f", VERIFICATION_QUERY = COALESCE(NULLIF({verification_query}, ''), tgt.VERIFICATION_QUERY)"
            optional_insert_cols += ", VERIFICATION_QUERY"
            optional_insert_vals += f", {verification_query}"
        if optional_has.get("BASELINE_VALUE"):
            optional_update += f", BASELINE_VALUE = COALESCE({baseline_value}, tgt.BASELINE_VALUE)"
            optional_insert_cols += ", BASELINE_VALUE"
            optional_insert_vals += f", {baseline_value}"
        if optional_has.get("CURRENT_VALUE"):
            optional_update += f", CURRENT_VALUE = COALESCE({current_value}, tgt.CURRENT_VALUE)"
            optional_insert_cols += ", CURRENT_VALUE"
            optional_insert_vals += f", {current_value}"
        if optional_has.get("MEASURED_DELTA"):
            optional_update += f", MEASURED_DELTA = COALESCE({measured_delta}, tgt.MEASURED_DELTA)"
            optional_insert_cols += ", MEASURED_DELTA"
            optional_insert_vals += f", {measured_delta}"
        session.sql(f"""
            MERGE INTO {ACTION_QUEUE_FQN} tgt
            USING (
                SELECT {action_id} AS action_id
            ) src
            ON tgt.action_id = src.action_id
            WHEN MATCHED THEN UPDATE SET
                UPDATED_AT = CURRENT_TIMESTAMP(),
                LAST_SEEN_AT = CURRENT_TIMESTAMP(),
                SEEN_COUNT = COALESCE(tgt.SEEN_COUNT, 0) + 1,
                SEVERITY = {severity},
                OWNER = {owner},
                FINDING = {finding},
                RECOMMENDED_ACTION = {recommended},
                EST_MONTHLY_SAVINGS = {savings},
                GENERATED_SQL_FIX = {sql_fix},
                PROOF_QUERY = {proof}
                {env_update}
                {optional_update}
            WHEN NOT MATCHED THEN INSERT (
                ACTION_ID, SOURCE, CATEGORY, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
                OWNER, STATUS, FINDING, RECOMMENDED_ACTION, EST_MONTHLY_SAVINGS,
                GENERATED_SQL_FIX, PROOF_QUERY, COMPANY{env_insert_col}{optional_insert_cols}
            )
            VALUES (
                {action_id}, {source}, {category}, {severity}, {entity_type},
                {entity_name}, {owner}, 'New', {finding}, {recommended},
                {savings}, {sql_fix}, {proof}, {company}{env_insert_val}{optional_insert_vals}
            )
        """).collect()
        count += 1
    return count


def load_action_queue(session, limit: int = 500) -> pd.DataFrame:
    company = get_active_company()
    has_environment = _action_queue_has_column(session, "ENVIRONMENT")
    where_clauses = []
    if company != "ALL":
        where_clauses.append(f"COMPANY = {sql_literal(company)}")
    if has_environment:
        env_clause = action_queue_environment_clause("ENVIRONMENT")
        if env_clause:
            where_clauses.append(env_clause)
    where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    optional_selects = [
        _optional_column_select(session, column)
        for column in ACTION_QUEUE_OPTIONAL_COLUMN_TYPES
    ]
    return run_query(f"""
        SELECT ACTION_ID, CREATED_AT, UPDATED_AT, SOURCE, CATEGORY, SEVERITY,
               ENTITY_TYPE, ENTITY_NAME, OWNER, STATUS, FINDING, RECOMMENDED_ACTION,
               EST_MONTHLY_SAVINGS, GENERATED_SQL_FIX, PROOF_QUERY, COMPANY,
               {", ".join(optional_selects)},
               LAST_SEEN_AT, SEEN_COUNT
        FROM {ACTION_QUEUE_FQN}
        {where_clause}
        ORDER BY
            CASE STATUS
                WHEN 'New' THEN 1
                WHEN 'Acknowledged' THEN 2
                WHEN 'In Progress' THEN 3
                WHEN 'Fixed' THEN 4
                WHEN 'Ignored' THEN 5
                ELSE 6
            END,
            CASE SEVERITY
                WHEN 'Critical' THEN 1
                WHEN 'High' THEN 2
                WHEN 'Medium' THEN 3
                WHEN 'Low' THEN 4
                ELSE 5
            END,
            UPDATED_AT DESC
        LIMIT {int(limit)}
    """, ttl_key=f"action_queue_{company}_{get_active_environment()}_{int(limit)}", tier="recent")


def _safe_actor(session) -> str:
    return str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")


def update_action_status(session, action_id: str, status: str, reason: str = "") -> None:
    return update_action_status_with_evidence(session, action_id, status, reason=reason)


def update_action_status_with_evidence(
    session,
    action_id: str,
    status: str,
    *,
    reason: str = "",
    verification_notes: str = "",
    verification_result: str = "",
    verification_query: str = "",
    ticket_id: str = "",
    approver: str = "",
    baseline_value=None,
    current_value=None,
    measured_delta=None,
) -> None:
    missing = action_queue_fixed_missing_fields(
        status=status,
        verification_notes=verification_notes,
        verification_result=verification_result,
    )
    if missing:
        raise ValueError("Fixed status requires " + " and ".join(missing) + ".")

    action_safe = sql_literal(action_id, max_len=64)
    status_safe = sql_literal(status, max_len=40)
    reason_safe = sql_literal(reason, max_len=2000)
    actor_safe = sql_literal(_safe_actor(session), max_len=200)
    extra = ""
    if status == "Acknowledged":
        extra = f", ACKNOWLEDGED_BY = {actor_safe}, ACKNOWLEDGED_AT = CURRENT_TIMESTAMP()"
    elif status == "Fixed":
        extra = f", FIXED_BY = {actor_safe}, FIXED_AT = CURRENT_TIMESTAMP()"
    elif status == "Ignored":
        extra = f", IGNORED_REASON = {reason_safe}"
    if _action_queue_has_column(session, "TICKET_ID"):
        extra += f", TICKET_ID = COALESCE(NULLIF({sql_literal(ticket_id, 200)}, ''), TICKET_ID)"
    if _action_queue_has_column(session, "APPROVER"):
        extra += f", APPROVER = COALESCE(NULLIF({sql_literal(approver, 200)}, ''), APPROVER)"
    if status == "Fixed":
        if _action_queue_has_column(session, "VERIFICATION_STATUS"):
            extra += ", VERIFICATION_STATUS = 'Verified'"
        if _action_queue_has_column(session, "VERIFICATION_NOTES"):
            extra += f", VERIFICATION_NOTES = {sql_literal(verification_notes, 4000)}"
        if _action_queue_has_column(session, "VERIFICATION_RESULT"):
            extra += f", VERIFICATION_RESULT = {sql_literal(verification_result, 8000)}"
        if _action_queue_has_column(session, "VERIFICATION_QUERY"):
            extra += f", VERIFICATION_QUERY = COALESCE(NULLIF({sql_literal(verification_query, 8000)}, ''), VERIFICATION_QUERY, PROOF_QUERY)"
        if _action_queue_has_column(session, "BASELINE_VALUE"):
            extra += f", BASELINE_VALUE = COALESCE({_float_or_none(baseline_value)}, BASELINE_VALUE)"
        if _action_queue_has_column(session, "CURRENT_VALUE"):
            extra += f", CURRENT_VALUE = COALESCE({_float_or_none(current_value)}, CURRENT_VALUE)"
        if _action_queue_has_column(session, "MEASURED_DELTA"):
            extra += f", MEASURED_DELTA = COALESCE({_float_or_none(measured_delta)}, MEASURED_DELTA)"
        if _action_queue_has_column(session, "VERIFIED_BY"):
            extra += f", VERIFIED_BY = {actor_safe}"
        if _action_queue_has_column(session, "VERIFIED_AT"):
            extra += ", VERIFIED_AT = CURRENT_TIMESTAMP()"
    session.sql(f"""
        UPDATE {ACTION_QUEUE_FQN}
        SET STATUS = {status_safe},
            UPDATED_AT = CURRENT_TIMESTAMP()
            {extra}
        WHERE ACTION_ID = {action_safe}
    """).collect()
