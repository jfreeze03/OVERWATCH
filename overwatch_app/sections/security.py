"""Security Monitoring v2."""

from __future__ import annotations

import pandas as pd

from overwatch_app.sections._shared import section_header


SECURITY_RETENTION_SETTINGS = {
    "SECURITY_RETENTION_DAYS": 365,
    "LOGIN_RETENTION_DAYS": 365,
    "GRANT_RETENTION_DAYS": 365,
}


def suspicious_login_heuristics(events: pd.DataFrame) -> pd.DataFrame:
    columns = ["RULE_NAME", "THRESHOLD", "EVIDENCE_COUNT", "CONFIDENCE", "SOURCE_LATENCY"]
    if events is None or events.empty:
        return pd.DataFrame(columns=columns)
    rows = [
        ("failed_login_spike_vs_baseline", "failures >= 2x baseline and >= 5", int(events.get("FAILED", pd.Series(dtype=int)).sum()), "Medium"),
        ("same_ip_multiple_users", "ip touches >= 3 users", int(events.groupby("CLIENT_IP")["USER_NAME"].nunique().ge(3).sum()) if {"CLIENT_IP", "USER_NAME"}.issubset(events.columns) else 0, "High"),
        ("same_user_multiple_ips", "user touches >= 3 IPs", int(events.groupby("USER_NAME")["CLIENT_IP"].nunique().ge(3).sum()) if {"CLIENT_IP", "USER_NAME"}.issubset(events.columns) else 0, "Medium"),
        ("failures_followed_by_success", "success within suspicious window", int(events.get("FAILURE_THEN_SUCCESS", pd.Series(dtype=int)).sum()), "High"),
        ("unusual_client_type", "client not in historical profile", int(events.get("UNUSUAL_CLIENT_TYPE", pd.Series(dtype=int)).sum()), "Medium"),
        ("privileged_user_involvement", "privileged user event count > 0", int(events.get("PRIVILEGED_USER", pd.Series(dtype=int)).sum()), "High"),
        ("off_hours_signal", "outside configured business hours", int(events.get("OFF_HOURS", pd.Series(dtype=int)).sum()), "Low"),
    ]
    frame = pd.DataFrame(rows, columns=["RULE_NAME", "THRESHOLD", "EVIDENCE_COUNT", "CONFIDENCE"])
    frame["SOURCE_LATENCY"] = "ACCOUNT_USAGE latency disclosed"
    return frame[columns]


def render_security_overview(frame: pd.DataFrame | None = None) -> None:
    import streamlit as st

    section_header(st, "Security Monitoring", "overview")
    st.dataframe(suspicious_login_heuristics(frame if frame is not None else pd.DataFrame()), hide_index=True)
