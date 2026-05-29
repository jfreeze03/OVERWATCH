# utils/action_queue.py - persistent recommendation/action queue helpers
import hashlib

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from .company_filter import get_active_company
from .query import run_query, safe_identifier, sql_literal


ACTION_QUEUE_FQN = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier(ACTION_QUEUE_TABLE)}"
)


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
    ACKNOWLEDGED_BY           VARCHAR(200),
    ACKNOWLEDGED_AT           TIMESTAMP_NTZ,
    FIXED_BY                  VARCHAR(200),
    FIXED_AT                  TIMESTAMP_NTZ,
    IGNORED_REASON            VARCHAR(2000),
    LAST_SEEN_AT              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SEEN_COUNT                NUMBER DEFAULT 1
);"""


def _num(value: object) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def upsert_actions(session, actions: list[dict]) -> int:
    if not actions:
        return 0
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
        savings = _num(action.get("Estimated Monthly Savings", 0))
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
            WHEN NOT MATCHED THEN INSERT (
                ACTION_ID, SOURCE, CATEGORY, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
                OWNER, STATUS, FINDING, RECOMMENDED_ACTION, EST_MONTHLY_SAVINGS,
                GENERATED_SQL_FIX, PROOF_QUERY, COMPANY
            )
            VALUES (
                {action_id}, {source}, {category}, {severity}, {entity_type},
                {entity_name}, {owner}, 'New', {finding}, {recommended},
                {savings}, {sql_fix}, {proof}, {company}
            )
        """).collect()
        count += 1
    return count


def load_action_queue(session, limit: int = 500) -> pd.DataFrame:
    company = get_active_company()
    company_clause = "" if company == "ALL" else f"WHERE COMPANY = {sql_literal(company)}"
    return run_query(f"""
        SELECT ACTION_ID, CREATED_AT, UPDATED_AT, SOURCE, CATEGORY, SEVERITY,
               ENTITY_TYPE, ENTITY_NAME, OWNER, STATUS, FINDING, RECOMMENDED_ACTION,
               EST_MONTHLY_SAVINGS, GENERATED_SQL_FIX, PROOF_QUERY, COMPANY,
               LAST_SEEN_AT, SEEN_COUNT
        FROM {ACTION_QUEUE_FQN}
        {company_clause}
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
    """, ttl_key=f"action_queue_{company}_{int(limit)}", tier="recent")


def _safe_actor(session) -> str:
    return str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")


def update_action_status(session, action_id: str, status: str, reason: str = "") -> None:
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
    session.sql(f"""
        UPDATE {ACTION_QUEUE_FQN}
        SET STATUS = {status_safe},
            UPDATED_AT = CURRENT_TIMESTAMP()
            {extra}
        WHERE ACTION_ID = {action_safe}
    """).collect()
