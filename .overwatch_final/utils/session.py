# utils/session.py — Snowflake session management
# ─────────────────────────────────────────────────────────────────────────────
# FIXES vs previous version:
#
# 1. CONCURRENCY: get_active_session() is called on every render in SiS —
#    it returns the same server-managed session for the current user's browser
#    tab. Storing it in session_state is fine for single-user but causes
#    cross-user contamination if multiple users somehow share state (not
#    possible in SiS — each browser tab gets its own session_state).
#    The fix: validate the session is still alive with a cheap SELECT 1
#    probe rather than relying on a TTL guess.
#
# 2. SESSION KEEP-ALIVE: COMPUTE_WH has STATEMENT_TIMEOUT_IN_SECONDS=1000.
#    Snowflake's idle session timeout (SESSION_IDLE_TIMEOUT_MINS) defaults
#    to 240 min but the *warehouse* auto-suspend is separate. The session
#    itself stays alive as long as the browser tab is open in SiS — the
#    warehouse suspends independently. No keep-alive is needed for sessions.
#    What IS needed: re-creating the session object if get_active_session()
#    throws (e.g. after a server-side restart or token expiry).
#
# 3. STATEMENT TIMEOUT CONTEXT: COMPUTE_WH has timeout=1000s. Long-running
#    OVERWATCH queries (especially ACCOUNT_USAGE full scans) will be killed
#    at 1000s. The session now sets STATEMENT_TIMEOUT_IN_SECONDS=900 at the
#    SESSION level so OVERWATCH queries get 15 min max — slightly under the
#    warehouse limit, which prevents the warehouse cancelling mid-query with
#    a cryptic timeout error. Override this in config.py if needed.
#
# 4. MULTI-USER SAFETY: In SiS each browser tab = its own Python process =
#    its own session_state = its own session object. No shared mutable state
#    across users. In SPCS (multi-user container), each HTTP request hits
#    the same process, so session_state IS shared. The code handles both:
#    SiS uses get_active_session() (user-scoped by Snowflake);
#    SPCS falls back to st.connection() (per-connection pooled by Streamlit).
# ─────────────────────────────────────────────────────────────────────────────
import streamlit as st
from datetime import datetime

# How long before we force a session health check (minutes).
# Conservative: well under Snowflake's 4-hour idle session timeout.
_SESSION_TTL_MINUTES  = 55

# Query tag applied to all OVERWATCH SQL — used for cost attribution and
# filtering in QUERY_HISTORY so OVERWATCH's own queries don't pollute
# the Cost Center leaderboard.
_QUERY_TAG = "OVERWATCH:v3"

# Statement timeout set at SESSION level (seconds).
# Set to 840s (14 min) — leaves 160s buffer under COMPUTE_WH's 1000s limit.
# This prevents the warehouse from hard-killing a query mid-result; instead
# OVERWATCH's session timeout fires first with a clean Python exception.
_STMT_TIMEOUT_SECONDS = 840


def _make_session():
    """
    Create a new Snowflake session and apply OVERWATCH session parameters.
    Called on first access and after TTL expiry or health check failure.
    """
    try:
        # SiS path — Snowflake injects the active session automatically.
        # Each browser tab gets its own isolated session; no sharing between users.
        from snowflake.snowpark.context import get_active_session
        sess = get_active_session()
    except Exception:
        # SPCS / local dev path — Streamlit manages connection pooling.
        try:
            conn = st.connection("snowflake")
            sess = conn.session()
        except Exception:
            st.warning(
                "Snowflake connection is not available in this environment. "
                "Deploy OVERWATCH inside Snowflake Streamlit or configure a Streamlit Snowflake connection."
            )
            st.stop()

    # Apply session-level settings. Wrapped individually so a failure on one
    # doesn't block session creation.
    for stmt in [
        f"ALTER SESSION SET QUERY_TAG = '{_QUERY_TAG}'",
        f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {_STMT_TIMEOUT_SECONDS}",
        "ALTER SESSION SET TIMEZONE = 'UTC'",
    ]:
        try:
            sess.sql(stmt).collect()
        except Exception:
            pass  # Non-fatal — session is still usable

    return sess


def _session_is_alive(sess) -> bool:
    """
    Cheap liveness probe. Returns False if the session has been recycled
    by Snowflake (e.g. server restart, token expiry, idle timeout).
    SELECT 1 costs ~0 credits and runs in <100ms on any active warehouse.
    """
    try:
        sess.sql("SELECT 1").collect()
        return True
    except Exception:
        return False


def get_session():
    """
    Return a live, validated Snowflake session.

    Session lifecycle:
    - Created once per browser tab (SiS) or per connection (SPCS).
    - Checked for liveness every _SESSION_TTL_MINUTES.
    - Recreated automatically if the liveness probe fails.
    - Session parameters (QUERY_TAG, STATEMENT_TIMEOUT) reapplied on recreate.

    Thread safety: SiS gives each browser tab its own Python process and
    session_state, so no locking is needed. SPCS uses Streamlit's built-in
    connection pooling via st.connection().
    """
    now = datetime.now()

    # ── Check whether it's time to probe liveness ──────────────────────────
    last_created = st.session_state.get("_sf_session_created_at")
    needs_check  = True
    if last_created:
        age_min     = (now - last_created).total_seconds() / 60
        needs_check = age_min >= _SESSION_TTL_MINUTES

    # ── Liveness probe on TTL expiry ───────────────────────────────────────
    if needs_check and "sf_session" in st.session_state:
        if not _session_is_alive(st.session_state["sf_session"]):
            # Session is dead — drop it so it gets recreated below
            st.session_state.pop("sf_session", None)
        # Reset the TTL clock regardless — we just probed it
        st.session_state["_sf_session_created_at"] = now

    # ── Create session if not present ─────────────────────────────────────
    if "sf_session" not in st.session_state:
        sess = _make_session()
        st.session_state["sf_session"]            = sess
        st.session_state["_sf_session_created_at"] = now

    return st.session_state["sf_session"]


def invalidate_session():
    """
    Force-drop the current session. Called by clear_all_cache() and on
    company filter switch to ensure the next query gets a fresh session.
    """
    st.session_state.pop("sf_session", None)
    st.session_state.pop("_sf_session_created_at", None)
