# sections/security_posture_data.py - Security Monitoring load helpers
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.security_posture_models import _hide_security_proof_tables, _security_scope_meta
from sections.shell_helpers import with_loaded_at


pd = lazy_pandas()

build_shared_security_mart_brief_sql = _lazy_util("build_shared_security_mart_brief_sql")
build_shared_security_summary_sql = _lazy_util("build_shared_security_summary_sql")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_session = _lazy_util("get_session")
run_query = _lazy_util("run_query")


def _build_security_summary_sql(session, days: int, company: str) -> tuple[str, str]:
    return build_shared_security_summary_sql(session, days, company)


def _build_security_mart_brief_sql(session, days: int, company: str) -> tuple[str, str]:
    return build_shared_security_mart_brief_sql(session, days, company)


def _clear_security_exception_state() -> None:
    st.session_state.pop("security_posture_exceptions", None)
    st.session_state.pop("security_posture_exception_source", None)
    st.session_state.pop("security_posture_exception_error", None)


def _store_security_summary(
    *,
    summary,
    meta: dict,
    source: str,
    summary_sql: str | None = None,
    exceptions_sql: str | None = None,
) -> None:
    st.session_state["security_posture_summary"] = summary
    st.session_state["security_posture_meta"] = with_loaded_at(meta, source=source)
    st.session_state["security_posture_source"] = source
    st.session_state.pop("security_posture_summary_error", None)
    _clear_security_exception_state()
    _hide_security_proof_tables()
    if summary_sql is not None and exceptions_sql is not None:
        st.session_state["security_posture_proof_sql"] = {
            "summary": summary_sql,
            "exceptions": exceptions_sql,
        }


def _load_security_brief(
    *,
    days: int,
    company: str,
    environment: str,
    allow_live_fallback: bool = True,
    quiet: bool = False,
) -> None:
    session = None
    try:
        session = get_session()
        summary_sql, exceptions_sql = _build_security_mart_brief_sql(session, days, company)
        summary = run_query(
            summary_sql,
            ttl_key=f"security_posture_summary_mart_{company}_{environment}_{days}",
            tier="standard",
        )
        source = "Fast security summary; MFA/sharing: account history"
        _store_security_summary(
            summary=summary,
            meta=_security_scope_meta(company, environment, days),
            source=source,
            summary_sql=summary_sql,
            exceptions_sql=exceptions_sql,
        )
    except Exception as exc:
        if not allow_live_fallback:
            st.session_state["security_posture_summary"] = pd.DataFrame()
            st.session_state["security_posture_meta"] = with_loaded_at(
                _security_scope_meta(company, environment, days),
                source="Fast security summary unavailable",
            )
            st.session_state["security_posture_source"] = "Fast security summary unavailable"
            st.session_state["security_posture_summary_error"] = format_snowflake_error(exc)
            _clear_security_exception_state()
            _hide_security_proof_tables()
            if not quiet:
                st.info(
                    "Fast security summary is unavailable for this scope. "
                    "Use Refresh Security Summary for bounded live account-history telemetry."
                )
            return
        try:
            session = session or get_session()
            summary_sql, exceptions_sql = _build_security_summary_sql(session, days, company)
            summary = run_query(
                summary_sql,
                ttl_key=f"security_posture_summary_live_{company}_{environment}_{days}",
                tier="standard",
            )
            source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE"
            _store_security_summary(
                summary=summary,
                meta=_security_scope_meta(company, environment, days),
                source=source,
                summary_sql=summary_sql,
                exceptions_sql=exceptions_sql,
            )
            if not quiet:
                st.info(
                    "Security summary unavailable from the fast summary; used bounded live account history. "
                    f"{format_snowflake_error(exc)}"
                )
        except Exception as live_exc:
            st.session_state["security_posture_summary"] = pd.DataFrame()
            _clear_security_exception_state()
            st.error(f"Unable to load security summary: {format_snowflake_error(live_exc)}")


__all__ = [
    "_build_security_summary_sql",
    "_build_security_mart_brief_sql",
    "_clear_security_exception_state",
    "_store_security_summary",
    "_load_security_brief",
]
