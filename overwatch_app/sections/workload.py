"""Workload Operations v2."""

from __future__ import annotations

import pandas as pd

from overwatch_app.sections._shared import section_header


WORKLOAD_METRICS = (
    "QUERY_FAILURE_RATE",
    "ERROR_CODE_FREQUENCY",
    "TOP_ERROR_CODE",
    "FAILED_QUERY_TREND",
    "P95_QUERY_DURATION",
    "REMOTE_SPILL_GB",
    "QUERIES_WAITING",
    "BLOCKED_TIME",
    "TASK_SUCCESS_RATE",
    "SLA_ATTAINMENT",
)


def detect_query_anomalies(current: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    if current is None or current.empty:
        return pd.DataFrame(columns=["QUERY_HASH", "ANOMALY_TYPE", "CONFIDENCE"])
    baseline_lookup = {}
    if baseline is not None and not baseline.empty and "QUERY_HASH" in baseline.columns:
        baseline_lookup = baseline.set_index("QUERY_HASH").to_dict("index")
    rows: list[dict] = []
    for _, row in current.iterrows():
        query_hash = row.get("QUERY_HASH", "")
        base = baseline_lookup.get(query_hash, {})
        if not base:
            rows.append({"QUERY_HASH": query_hash, "ANOMALY_TYPE": "new_query_hash_spend", "CONFIDENCE": "Medium"})
            continue
        if float(row.get("DURATION_MS", 0) or 0) >= 3 * float(base.get("DURATION_MS", 1) or 1):
            rows.append({"QUERY_HASH": query_hash, "ANOMALY_TYPE": "same_query_hash_3x_duration", "CONFIDENCE": "High"})
        if float(row.get("REMOTE_SPILL_GB", 0) or 0) > float(base.get("REMOTE_SPILL_GB", 0) or 0):
            rows.append({"QUERY_HASH": query_hash, "ANOMALY_TYPE": "spill_regression", "CONFIDENCE": "Medium"})
    return pd.DataFrame(rows)


def render_workload_overview(frame: pd.DataFrame | None = None) -> None:
    import streamlit as st

    section_header(st, "Workload Operations", "overview")
    st.dataframe(frame if frame is not None else pd.DataFrame(columns=WORKLOAD_METRICS), hide_index=True)
