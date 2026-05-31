# utils/logging.py — Structured usage logging for OVERWATCH
# ─────────────────────────────────────────────────────────────────────────────
# Writes one row per section load to OVERWATCH_USAGE_LOG.
# Wrapped in try/except everywhere — never blocks the UI.
#
# Schema: RUN_ID, LOG_TIME, SF_USER, SF_ROLE, COMPANY_VIEW,
#         SECTION, QUERY_DURATION_MS, APP_VERSION, SESSION_ID
#
# Setup: deploy snowflake/OVERWATCH_MART_SETUP.sql; this module only writes usage rows.
# Usage: wrap each section render with SectionTimer, or call log_section_load().
# ─────────────────────────────────────────────────────────────────────────────
import time
import streamlit as st
from config import ALERT_DB, ALERT_SCHEMA
from .query import safe_identifier, sql_literal

LOG_TABLE = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier('OVERWATCH_USAGE_LOG')}"
)
APP_VERSION = "3.0"
_ENABLED_KEY = "_logging_enabled"
_QUERY_ENABLED_KEY = "_query_logging_enabled"


def build_usage_log_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Return DDL to create the usage log table and summary view. Run once."""
    db = safe_identifier(db)
    schema = safe_identifier(schema)
    log_table = f"{db}.{schema}.{safe_identifier('OVERWATCH_USAGE_LOG')}"
    summary_view = f"{db}.{schema}.{safe_identifier('OVERWATCH_USAGE_SUMMARY')}"
    return f"""-- ─────────────────────────────────────────────────────────────────
-- OVERWATCH Usage Log
-- Tracks section loads, users, roles, and query durations.
-- Run once as SYSADMIN or role with CREATE TABLE on {db}.{schema}.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS {log_table} (
    RUN_ID           NUMBER AUTOINCREMENT PRIMARY KEY,
    LOG_TIME         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SF_USER          VARCHAR(200),
    SF_ROLE          VARCHAR(200),
    COMPANY_VIEW     VARCHAR(50),
    SECTION          VARCHAR(200),
    QUERY_DURATION_MS NUMBER,
    APP_VERSION      VARCHAR(20) DEFAULT {sql_literal(APP_VERSION, 20)},
    SESSION_ID       VARCHAR(200),
    EVENT_TYPE       VARCHAR(50) DEFAULT 'SECTION_LOAD',
    QUERY_HASH       VARCHAR(80),
    CACHE_KEY        VARCHAR(300),
    CACHE_TIER       VARCHAR(50),
    ROW_COUNT        NUMBER,
    RESULT_MB        NUMBER(18,4),
    USED_CACHE       BOOLEAN,
    MESSAGE          VARCHAR(1000)
);

ALTER TABLE {log_table} ADD COLUMN IF NOT EXISTS EVENT_TYPE VARCHAR(50) DEFAULT 'SECTION_LOAD';
ALTER TABLE {log_table} ADD COLUMN IF NOT EXISTS QUERY_HASH VARCHAR(80);
ALTER TABLE {log_table} ADD COLUMN IF NOT EXISTS CACHE_KEY VARCHAR(300);
ALTER TABLE {log_table} ADD COLUMN IF NOT EXISTS CACHE_TIER VARCHAR(50);
ALTER TABLE {log_table} ADD COLUMN IF NOT EXISTS ROW_COUNT NUMBER;
ALTER TABLE {log_table} ADD COLUMN IF NOT EXISTS RESULT_MB NUMBER(18,4);
ALTER TABLE {log_table} ADD COLUMN IF NOT EXISTS USED_CACHE BOOLEAN;
ALTER TABLE {log_table} ADD COLUMN IF NOT EXISTS MESSAGE VARCHAR(1000);

-- Adoption summary view (last 30 days)
CREATE OR REPLACE VIEW {summary_view} AS
SELECT
    DATE_TRUNC('day', log_time) AS log_date,
    sf_user,
    sf_role,
    company_view,
    section,
    COUNT(*)                    AS load_count,
    ROUND(AVG(query_duration_ms))    AS avg_duration_ms,
    MAX(query_duration_ms)      AS max_duration_ms
FROM {log_table}
WHERE log_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
  AND COALESCE(event_type, 'SECTION_LOAD') = 'SECTION_LOAD'
GROUP BY log_date, sf_user, sf_role, company_view, section
ORDER BY log_date DESC, load_count DESC;
"""


def is_logging_enabled() -> bool:
    return st.session_state.get(_ENABLED_KEY, False)


def set_logging_enabled(enabled: bool) -> None:
    st.session_state[_ENABLED_KEY] = enabled


def is_query_logging_enabled() -> bool:
    return st.session_state.get(_QUERY_ENABLED_KEY, False)


def set_query_logging_enabled(enabled: bool) -> None:
    st.session_state[_QUERY_ENABLED_KEY] = bool(enabled)


def log_section_load(section: str, duration_ms: int = 0) -> None:
    """
    Write one row to OVERWATCH_USAGE_LOG. Never raises — silently no-ops
    if the table doesn't exist or logging is disabled.

    Direct usage:
        from utils.logging import log_section_load
        log_section_load("🏠 Account Health")

    Timed usage via SectionTimer context manager is preferred.
    """
    if not is_logging_enabled():
        return
    try:
        from utils.session import get_session
        session = get_session()

        user = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
        role = str(st.session_state.get("_overwatch_current_role", "") or "")
        company = st.session_state.get("active_company", "ALFA")
        sess_id = st.session_state.get("_session_id", "")

        session.sql(f"""
            INSERT INTO {LOG_TABLE}
                (SF_USER, SF_ROLE, COMPANY_VIEW, SECTION, QUERY_DURATION_MS, SESSION_ID)
            VALUES (
                {sql_literal(user, 200)},
                {sql_literal(role, 200)},
                {sql_literal(company, 50)},
                {sql_literal(section, 200)},
                {int(duration_ms)},
                {sql_literal(sess_id, 200)}
            )
        """).collect()
    except Exception:
        pass


def log_query_event(
    section: str,
    query_hash: str,
    cache_key: str = "",
    cache_tier: str = "",
    elapsed_ms: float = 0,
    row_count: int = 0,
    result_mb: float = 0,
    used_cache: bool = True,
    message: str = "",
) -> None:
    """Persist one query telemetry event when the usage log table is upgraded."""
    if not is_query_logging_enabled():
        return
    try:
        from utils.session import get_session
        session = get_session()

        user = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
        role = str(st.session_state.get("_overwatch_current_role", "") or "")
        company = st.session_state.get("active_company", "ALFA")
        sess_id = st.session_state.get("_session_id", "")
        used_cache_sql = "TRUE" if used_cache else "FALSE"

        session.sql(f"""
            INSERT INTO {LOG_TABLE}
                (
                    SF_USER, SF_ROLE, COMPANY_VIEW, SECTION, QUERY_DURATION_MS,
                    SESSION_ID, EVENT_TYPE, QUERY_HASH, CACHE_KEY, CACHE_TIER,
                    ROW_COUNT, RESULT_MB, USED_CACHE, MESSAGE
                )
            VALUES (
                {sql_literal(user, 200)},
                {sql_literal(role, 200)},
                {sql_literal(company, 50)},
                {sql_literal(section, 200)},
                {int(float(elapsed_ms or 0))},
                {sql_literal(sess_id, 200)},
                'QUERY_RUN',
                {sql_literal(query_hash, 80)},
                {sql_literal(cache_key, 300)},
                {sql_literal(cache_tier, 50)},
                {int(row_count or 0)},
                {round(float(result_mb or 0), 4)},
                {used_cache_sql},
                {sql_literal(message, 1000)}
            )
        """).collect()
    except Exception:
        pass


class SectionTimer:
    """
    Context manager: times a section render and logs it automatically.

    Usage in any section render():
        from utils.logging import SectionTimer
        with SectionTimer("🏠 Account Health"):
            ... all render code ...
    """
    def __init__(self, section: str):
        self.section = section
        self._start  = None

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, *args):
        ms = int((time.time() - self._start) * 1000)
        log_section_load(self.section, ms)
