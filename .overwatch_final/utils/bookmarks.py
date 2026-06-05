# utils/bookmarks.py — Saved Views / Bookmarks
# ─────────────────────────────────────────────────────────────────────────────
# Lets users save their current navigation state (section + filters) as a
# named bookmark in OVERWATCH_BOOKMARKS. Clicking loads the state in one shot.
#
# Stored state per bookmark:
#   section, company_view, active_days, wh_filter, user_filter, role_filter,
#   db_filter, global_start_date, global_end_date
# ─────────────────────────────────────────────────────────────────────────────
import json
from datetime import date, datetime
import streamlit as st
from config import ALERT_DB, ALERT_SCHEMA, normalize_section_name
from .query import format_snowflake_error, safe_identifier, sql_literal

BOOKMARK_TABLE = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier('OVERWATCH_BOOKMARKS')}"
)

# Session state keys we capture and restore
_CAPTURED_KEYS = [
    "nav_section", "active_company",
    "global_start_date", "global_end_date",
    "global_warehouse", "global_user", "global_role", "global_database",
]


def build_bookmark_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Return DDL for the bookmarks table. Run once as SYSADMIN."""
    db = safe_identifier(db)
    schema = safe_identifier(schema)
    table = f"{db}.{schema}.{safe_identifier('OVERWATCH_BOOKMARKS')}"
    return f"""-- ─────────────────────────────────────────────────────────────────
-- OVERWATCH Saved Views (Bookmarks)
-- Stores named navigation states per user.
-- Run once as SYSADMIN or role with CREATE TABLE on {db}.{schema}.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS {table} (
    BOOKMARK_ID   NUMBER AUTOINCREMENT PRIMARY KEY,
    SF_USER       VARCHAR(200),
    IS_SHARED     BOOLEAN DEFAULT FALSE,  -- TRUE = visible to all users
    BOOKMARK_NAME VARCHAR(200) NOT NULL,
    SECTION       VARCHAR(200),
    STATE_JSON    VARIANT,               -- full captured state as JSON
    CREATED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    LAST_USED_AT  TIMESTAMP_NTZ,
    USE_COUNT     NUMBER DEFAULT 0
);
"""


def _capture_state() -> dict:
    """Snapshot the current session state into a saveable dict."""
    state = {k: st.session_state.get(k) for k in _CAPTURED_KEYS if st.session_state.get(k) is not None}
    if state.get("nav_section"):
        state["nav_section"] = normalize_section_name(state["nav_section"])
    return state


def _bookmark_json_default(value):
    """Serialize Streamlit filter values such as date inputs into bookmark JSON."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _restore_state(state: dict) -> None:
    """Write a saved state dict back into session state and rerun."""
    for k, v in state.items():
        if v is not None:
            st.session_state[k] = normalize_section_name(v) if k == "nav_section" else v


def _safe_actor(session) -> str:
    return str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")


def save_bookmark(session, name: str, shared: bool = False) -> bool:
    """Write current navigation state to OVERWATCH_BOOKMARKS. Returns True on success."""
    try:
        state   = _capture_state()
        section = state.get("nav_section", "")

        sf_user = sql_literal(_safe_actor(session), max_len=200)
        bookmark_name = sql_literal(name, max_len=200)
        section_name = sql_literal(section, max_len=200)
        state_json = sql_literal(json.dumps(state, default=_bookmark_json_default), max_len=8000)
        session.sql(f"""
            INSERT INTO {BOOKMARK_TABLE}
                (SF_USER, BOOKMARK_NAME, SECTION, STATE_JSON, IS_SHARED)
            VALUES (
                {sf_user},
                {bookmark_name},
                {section_name},
                PARSE_JSON({state_json}),
                {str(shared).upper()}
            )
        """).collect()
        return True
    except Exception as e:
        st.warning(f"Bookmark save failed: {format_snowflake_error(e)}")
        return False


def load_bookmarks(session, include_shared: bool = True) -> list[dict]:
    """
    Return list of bookmark dicts for the current user (+ shared bookmarks).
    Each dict has: BOOKMARK_ID, BOOKMARK_NAME, SECTION, IS_SHARED,
                   CREATED_AT, USE_COUNT, STATE_JSON (parsed).
    """
    try:
        user = _safe_actor(session)
        user_esc = sql_literal(user, max_len=200)
        shared_clause = "OR IS_SHARED = TRUE" if include_shared else ""
        rows = session.sql(f"""
            SELECT BOOKMARK_ID, BOOKMARK_NAME, SECTION,
                   IS_SHARED, CREATED_AT, USE_COUNT,
                   STATE_JSON::VARCHAR AS state_str
            FROM {BOOKMARK_TABLE}
            WHERE (SF_USER = {user_esc} {shared_clause})
            ORDER BY LAST_USED_AT DESC NULLS LAST, CREATED_AT DESC
            LIMIT 50
        """).collect()
        result = []
        for row in rows:
            try:
                state = json.loads(row["STATE_STR"] or "{}")
            except Exception:
                state = {}
            result.append({
                "id":      row["BOOKMARK_ID"],
                "name":    row["BOOKMARK_NAME"],
                "section": normalize_section_name(row["SECTION"]),
                "shared":  row["IS_SHARED"],
                "created": str(row["CREATED_AT"])[:10],
                "uses":    row["USE_COUNT"],
                "state":   state,
            })
        return result
    except Exception:
        raise


def apply_bookmark(session, bookmark: dict) -> None:
    """Restore a bookmark's state and increment its use count."""
    try:
        bookmark_id = int(bookmark["id"])
        _restore_state(bookmark["state"])
        session.sql(f"""
            UPDATE {BOOKMARK_TABLE}
            SET USE_COUNT = USE_COUNT + 1,
                LAST_USED_AT = CURRENT_TIMESTAMP()
            WHERE BOOKMARK_ID = {bookmark_id}
        """).collect()
    except Exception:
        pass
    st.rerun()


def delete_bookmark(session, bookmark_id: int) -> bool:
    """Delete a bookmark by ID. Returns True on success."""
    try:
        session.sql(f"DELETE FROM {BOOKMARK_TABLE} WHERE BOOKMARK_ID = {int(bookmark_id)}").collect()
        return True
    except Exception as e:
        st.warning(f"Delete failed: {format_snowflake_error(e)}")
        return False
