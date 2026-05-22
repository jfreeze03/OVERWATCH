# utils/action_queue.py - persistent recommendation/action queue helpers
import hashlib
from datetime import datetime

import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from .data import normalize_df
from .query import safe_sql


ACTION_QUEUE_FQN = f"{ALERT_DB}.{ALERT_SCHEMA}.{ACTION_QUEUE_TABLE}"


def make_action_id(category: str, entity: str, finding: str) -> str:
    raw = f"{category}|{entity}|{finding}".upper().encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:16].upper()


def build_action_queue_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ACTION_QUEUE_TABLE,
) -> str:
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
        action_id = safe_sql(action.get("Action ID") or make_action_id(
            action.get("Category", "General"),
            action.get("Entity", ""),
            action.get("Finding", ""),
        ))
        source = safe_sql(action.get("Source", "Recommendations"))
        category = safe_sql(action.get("Category", "General"))
        severity = safe_sql(action.get("Severity", "Medium"))
        entity_type = safe_sql(action.get("Entity Type", "Snowflake Object"))
        entity_name = safe_sql(action.get("Entity", ""))
        owner = safe_sql(action.get("Owner", "DBA"))
        finding = safe_sql(action.get("Finding", ""))
        recommended = safe_sql(action.get("Action", ""))
        sql_fix = safe_sql(action.get("Generated SQL Fix", ""))
        proof = safe_sql(action.get("Proof Query", ""))
        company = safe_sql(action.get("Company", ""))
        savings = _num(action.get("Estimated Monthly Savings", 0))
        session.sql(f"""
            MERGE INTO {ACTION_QUEUE_FQN} tgt
            USING (
                SELECT '{action_id}' AS action_id
            ) src
            ON tgt.action_id = src.action_id
            WHEN MATCHED THEN UPDATE SET
                UPDATED_AT = CURRENT_TIMESTAMP(),
                LAST_SEEN_AT = CURRENT_TIMESTAMP(),
                SEEN_COUNT = COALESCE(tgt.SEEN_COUNT, 0) + 1,
                SEVERITY = '{severity}',
                OWNER = '{owner}',
                FINDING = '{finding}',
                RECOMMENDED_ACTION = '{recommended}',
                EST_MONTHLY_SAVINGS = {savings},
                GENERATED_SQL_FIX = '{sql_fix}',
                PROOF_QUERY = '{proof}'
            WHEN NOT MATCHED THEN INSERT (
                ACTION_ID, SOURCE, CATEGORY, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
                OWNER, STATUS, FINDING, RECOMMENDED_ACTION, EST_MONTHLY_SAVINGS,
                GENERATED_SQL_FIX, PROOF_QUERY, COMPANY
            )
            VALUES (
                '{action_id}', '{source}', '{category}', '{severity}', '{entity_type}',
                '{entity_name}', '{owner}', 'New', '{finding}', '{recommended}',
                {savings}, '{sql_fix}', '{proof}', '{company}'
            )
        """).collect()
        count += 1
    return count


def load_action_queue(session, limit: int = 500) -> pd.DataFrame:
    return normalize_df(session.sql(f"""
        SELECT ACTION_ID, CREATED_AT, UPDATED_AT, SOURCE, CATEGORY, SEVERITY,
               ENTITY_TYPE, ENTITY_NAME, OWNER, STATUS, FINDING, RECOMMENDED_ACTION,
               EST_MONTHLY_SAVINGS, GENERATED_SQL_FIX, PROOF_QUERY, COMPANY,
               LAST_SEEN_AT, SEEN_COUNT
        FROM {ACTION_QUEUE_FQN}
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
    """).to_pandas())


def update_action_status(session, action_id: str, status: str, reason: str = "") -> None:
    action_safe = safe_sql(action_id)
    status_safe = safe_sql(status)
    reason_safe = safe_sql(reason)
    extra = ""
    if status == "Acknowledged":
        extra = ", ACKNOWLEDGED_BY = CURRENT_USER(), ACKNOWLEDGED_AT = CURRENT_TIMESTAMP()"
    elif status == "Fixed":
        extra = ", FIXED_BY = CURRENT_USER(), FIXED_AT = CURRENT_TIMESTAMP()"
    elif status == "Ignored":
        extra = f", IGNORED_REASON = '{reason_safe}'"
    session.sql(f"""
        UPDATE {ACTION_QUEUE_FQN}
        SET STATUS = '{status_safe}',
            UPDATED_AT = CURRENT_TIMESTAMP()
            {extra}
        WHERE ACTION_ID = '{action_safe}'
    """).collect()
