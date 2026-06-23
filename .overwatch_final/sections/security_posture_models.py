# sections/security_posture_models.py - Security Monitoring model and scoring helpers
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas
from utils.primitives import safe_float, safe_int


pd = lazy_pandas()

SECURITY_SCOPE_FILTER_KEYS = (
    "global_user",
    "global_database",
    "global_role",
    "global_start_date",
    "global_end_date",
)
_SECURITY_PROOF_TABLES_KEY = "security_posture_show_proof_tables"
_SECURITY_PROOF_TABLES_SCOPE_KEY = "security_posture_proof_tables_scope"


def _security_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _security_scope_meta(
    company: str,
    environment: str,
    days: int | None = None,
    state: dict | None = None,
) -> dict:
    """Return the filter scope that loaded Security Posture telemetry must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _security_scope_value(company),
        "environment": _security_scope_value(environment),
    }
    if days is not None:
        meta["days"] = int(days)
    for key in SECURITY_SCOPE_FILTER_KEYS:
        meta[key] = _security_scope_value(state.get(key))
    return meta


def _security_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key == "days":
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif _security_scope_value(actual) != _security_scope_value(expected_value):
            return False
    return True


def _security_proof_tables_visible(company: str, environment: str, days: int) -> bool:
    return bool(st.session_state.get(_SECURITY_PROOF_TABLES_KEY)) and _security_meta_matches(
        st.session_state.get(_SECURITY_PROOF_TABLES_SCOPE_KEY),
        _security_scope_meta(company, environment, days),
    )


def _show_security_proof_tables(company: str, environment: str, days: int) -> None:
    st.session_state[_SECURITY_PROOF_TABLES_KEY] = True
    st.session_state[_SECURITY_PROOF_TABLES_SCOPE_KEY] = _security_scope_meta(company, environment, days)


def _hide_security_proof_tables() -> None:
    st.session_state[_SECURITY_PROOF_TABLES_KEY] = False
    st.session_state.pop(_SECURITY_PROOF_TABLES_SCOPE_KEY, None)


def _security_frame_rows(frame) -> int:
    return len(frame) if isinstance(frame, pd.DataFrame) else 0


def _security_source_confidence(source: str, default: str) -> str:
    source_lower = str(source or "").lower()
    if ("fast" in source_lower and "summary" in source_lower) or "mart" in source_lower or "fact_" in source_lower:
        return "Fast summary"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower:
        return "Live ACCOUNT_USAGE"
    return default


def _security_source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or triage filters."
    if state == "Unavailable":
        return "Deploy or refresh the summary/grants before relying on this surface."
    if state == "On demand":
        return "Refresh only when this workflow is part of the current security investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent security events, review rows, or summary rows."
    if "fallback" in source_lower:
        return "Use for investigation; prefer summary refresh for repeated daily access control."
    return "Current for the active security scope."


def _security_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Security Posture telemetry freshness and source strategy."""
    definitions = [
        {
            "surface": "Security summary",
            "frame_key": "security_posture_summary",
            "source_key": "security_posture_source",
            "meta_key": "security_posture_meta",
            "days_key": "security_posture_brief_days",
            "default_days": 30,
            "source": "Fast security summary or live account history",
            "confidence": "Mixed",
        },
        {
            "surface": "Security exceptions",
            "frame_key": "security_posture_exceptions",
            "source_key": "security_posture_source",
            "meta_key": "security_posture_meta",
            "days_key": "security_posture_brief_days",
            "default_days": 30,
            "source": "Fast security summary or live account history",
            "confidence": "Mixed",
        },
        {
            "surface": "Control summary",
            "frame_key": "security_operability_fact",
            "meta_key": "security_operability_fact_meta",
            "days_key": "security_posture_brief_days",
            "default_days": 30,
            "source": "Fast security control summary",
            "confidence": "Fast summary",
            "error_key": "security_operability_fact_error",
        },
        {
            "surface": "Privileged grants",
            "frame_key": "security_privileged_grants",
            "meta_key": "security_privileged_grants_meta",
            "days_key": "security_priv_grant_days",
            "default_days": 30,
            "source": "Live ACCOUNT_USAGE grants with route status annotation",
            "confidence": "Live ACCOUNT_USAGE",
        },
        {
            "surface": "Access review trend",
            "frame_key": "security_access_review_trend",
            "meta_key": "security_access_review_trend_meta",
            "days_key": "security_access_review_trend_days",
            "default_days": 30,
            "source": "Workflow telemetry",
            "confidence": "Workflow telemetry",
        },
        {
            "surface": "Closure analytics",
            "frame_key": "security_action_closure",
            "meta_key": "security_action_closure_meta",
            "days_key": "security_action_closure_days",
            "default_days": 30,
            "source": "Action queue closure status",
            "confidence": "Workflow telemetry",
        },
    ]
    rows = []
    for item in definitions:
        source_key = item.get("source_key")
        source = str((state.get(source_key, item["source"]) if source_key else item["source"]) or item["source"])
        frame = state.get(item["frame_key"])
        error_key = item.get("error_key")
        error = state.get(error_key) if error_key else None
        days_key = item.get("days_key")
        days = state.get(days_key, item.get("default_days")) if days_key else item.get("default_days")
        expected_meta = _security_scope_meta(company, environment, days=days, state=state)
        loaded = isinstance(frame, pd.DataFrame)
        if error:
            status = "Unavailable"
        elif not loaded:
            status = "On demand"
        elif not _security_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif frame.empty:
            status = "No Rows"
        else:
            status = "Loaded"
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": {
                "Unavailable": 0,
                "Stale": 1,
                "Loaded": 2,
                "No Rows": 3,
                "On demand": 4,
            }.get(status, 9),
            "SOURCE": source,
            "CONFIDENCE": _security_source_confidence(source, item["confidence"]),
            "ROWS": _security_frame_rows(frame),
            "SCOPE": f"{company} / {environment} / {int(days)}d",
            "NEXT_ACTION": _security_source_next_action(status, source),
        })
    return pd.DataFrame(rows)


def _security_score(
    *,
    failed_logins: int,
    failed_users: int,
    users_without_mfa: int,
    active_users: int,
    recent_grants: int,
    shared_databases: int,
) -> int:
    """Weighted DBA posture score; failures and MFA gaps matter more than volume."""
    active_users = max(safe_int(active_users), 1)
    failed_login_penalty = min(25, safe_float(failed_logins) * 0.25 + safe_float(failed_users) * 2)
    mfa_penalty = min(35, (safe_float(users_without_mfa) / active_users) * 100)
    grant_penalty = min(20, safe_float(recent_grants) * 1.5)
    exposure_penalty = min(20, safe_float(shared_databases) * 3)
    return max(0, min(100, int(round(100 - failed_login_penalty - mfa_penalty - grant_penalty - exposure_penalty))))


def _security_rating(score: int) -> str:
    if score >= 95:
        return "Strong"
    if score >= 85:
        return "Watch"
    if score >= 70:
        return "Elevated"
    return "High Risk"


__all__ = [
    "SECURITY_SCOPE_FILTER_KEYS",
    "_SECURITY_PROOF_TABLES_KEY",
    "_SECURITY_PROOF_TABLES_SCOPE_KEY",
    "_security_scope_value",
    "_security_scope_meta",
    "_security_meta_matches",
    "_security_proof_tables_visible",
    "_show_security_proof_tables",
    "_hide_security_proof_tables",
    "_security_frame_rows",
    "_security_source_confidence",
    "_security_source_next_action",
    "_security_source_health_rows",
    "_security_score",
    "_security_rating",
]
