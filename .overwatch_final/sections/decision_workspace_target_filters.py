"""Safe SQL and dataframe filters for Decision Workspace evidence targets."""

from __future__ import annotations

from typing import Any
import re

import streamlit as st

from performance import TARGETED_EVIDENCE_DEFAULT_LIMIT, TARGETED_EVIDENCE_MAX_LIMIT
from utils.sql_safe import sql_literal


SECTION_TARGET_KEYS: dict[str, str] = {
    "Alert Center": "alert_center_evidence_target",
    "Cost & Contract": "cost_contract_evidence_target",
    "DBA Control Room": "dba_control_room_evidence_target",
    "Workload Operations": "workload_operations_evidence_target",
    "Security Monitoring": "security_posture_evidence_target",
}

SECTION_TARGET_COLUMNS: dict[str, tuple[str, ...]] = {
    "Alert Center": (
        "EVENT_ID",
        "ALERT_ID",
        "ALERT_KEY",
        "ALERT_FAMILY",
        "ALERT_TYPE",
        "FAMILY",
        "CATEGORY",
        "ENTITY_NAME",
        "ENTITY_ID",
        "WAREHOUSE_NAME",
        "DATABASE_NAME",
        "USER_NAME",
        "ROLE_NAME",
        "ACTION_ID",
    ),
    "Cost & Contract": (
        "WAREHOUSE_NAME",
        "WAREHOUSE",
        "SERVICE_CATEGORY",
        "SERVICE_TYPE",
        "DATABASE_NAME",
        "USER_NAME",
        "ROLE_NAME",
        "TAG_VALUE",
        "DEPARTMENT",
        "APPLICATION",
        "DRIVER",
        "DIMENSION",
        "ENTITY_NAME",
        "ENTITY_ID",
    ),
    "DBA Control Room": (
        "QUERY_ID",
        "QUERY_HASH",
        "QUERY_SIGNATURE",
        "WAREHOUSE_NAME",
        "TASK_NAME",
        "ROOT_TASK_NAME",
        "PROCEDURE_NAME",
        "DATABASE_NAME",
        "ENTITY_NAME",
        "ENTITY_ID",
    ),
    "Workload Operations": (
        "QUERY_ID",
        "QUERY_HASH",
        "QUERY_SIGNATURE",
        "WAREHOUSE_NAME",
        "TASK_NAME",
        "ROOT_TASK_NAME",
        "PROCEDURE_NAME",
        "PIPELINE_NAME",
        "ENTITY_NAME",
        "ENTITY_ID",
    ),
    "Security Monitoring": (
        "USER_NAME",
        "LOGIN_NAME",
        "ROLE_NAME",
        "GRANTEE_NAME",
        "GRANTED_TO",
        "GRANTED_ON",
        "DATABASE_NAME",
        "SHARE_NAME",
        "OBJECT_NAME",
        "ENTITY_NAME",
        "ENTITY_ID",
        "GRANT_ID",
    ),
}

ENTITY_COLUMN_PRIORITY: dict[str, tuple[str, ...]] = {
    "alert": ("EVENT_ID", "ALERT_ID", "ALERT_KEY"),
    "event": ("EVENT_ID", "ALERT_ID", "ALERT_KEY"),
    "action": ("ACTION_ID", "WORKFLOW_ID"),
    "warehouse": ("WAREHOUSE_NAME", "WAREHOUSE"),
    "warehouse_name": ("WAREHOUSE_NAME", "WAREHOUSE"),
    "query": ("QUERY_ID", "QUERY_HASH", "QUERY_SIGNATURE"),
    "query_id": ("QUERY_ID",),
    "query_signature": ("QUERY_SIGNATURE", "QUERY_HASH"),
    "task": ("TASK_NAME", "ROOT_TASK_NAME"),
    "procedure": ("PROCEDURE_NAME",),
    "pipeline": ("PIPELINE_NAME", "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME"),
    "service": ("SERVICE_CATEGORY", "SERVICE_TYPE"),
    "cortex": ("SERVICE_CATEGORY", "SERVICE_TYPE", "APPLICATION"),
    "user": ("USER_NAME", "LOGIN_NAME", "GRANTEE_NAME"),
    "role": ("ROLE_NAME", "GRANTEE_NAME", "GRANTED_TO"),
    "database": ("DATABASE_NAME",),
    "grant": ("GRANT_ID", "ROLE_NAME", "GRANTEE_NAME", "GRANTED_ON"),
    "share": ("SHARE_NAME", "DATABASE_NAME", "OBJECT_NAME"),
    "tag": ("TAG_VALUE", "DEPARTMENT", "APPLICATION"),
    "department": ("DEPARTMENT", "TAG_VALUE"),
    "application": ("APPLICATION", "TAG_VALUE"),
}

DISPLAY_FALLBACK_COLUMNS = {
    "ALERT_FAMILY",
    "ALERT_TYPE",
    "FAMILY",
    "CATEGORY",
    "ENTITY_NAME",
    "DRIVER",
    "DIMENSION",
    "OBJECT_NAME",
    "APPLICATION",
}


def get_decision_evidence_target(section: str) -> dict[str, str]:
    target = st.session_state.get(SECTION_TARGET_KEYS.get(str(section), ""))
    if not isinstance(target, dict):
        target = st.session_state.get("decision_workspace_evidence_target")
    if not isinstance(target, dict):
        return {}
    return {str(key): str(value) for key, value in target.items() if str(value or "").strip()}


def clear_decision_evidence_target(section: str) -> None:
    key = SECTION_TARGET_KEYS.get(str(section))
    if key:
        st.session_state.pop(key, None)
    st.session_state.pop("decision_workspace_evidence_target", None)


def evidence_target_label(target: dict[str, str]) -> str:
    if not target:
        return ""
    entity_type = str(target.get("entity_type") or "target").strip()
    value = str(
        target.get("entity_name")
        or target.get("entity_id")
        or target.get("evidence_id")
        or target.get("dedupe_key")
        or ""
    ).strip()
    if not value:
        return ""
    return f"{entity_type}: {value}"


def target_values(target: dict[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("evidence_id", "entity_id", "entity_name", "dedupe_key", "finding_key"):
        value = str(target.get(key) or "").strip()
        if value and value.upper() not in {item.upper() for item in values}:
            values.append(value)
    return tuple(values)


def evidence_row_limit(limit: int | None = None) -> int:
    raw = TARGETED_EVIDENCE_DEFAULT_LIMIT if limit is None else int(limit)
    return max(1, min(raw, TARGETED_EVIDENCE_MAX_LIMIT))


def _normalize_columns(columns: tuple[str, ...] | list[str] | set[str]) -> set[str]:
    return {str(column).upper() for column in columns}


def _alias(alias: str) -> str:
    text = str(alias or "").strip()
    if not text:
        return ""
    return text if text.endswith(".") else f"{text}."


def _candidate_columns(section: str, target: dict[str, str], available_columns: tuple[str, ...] | list[str] | set[str]) -> list[str]:
    available = _normalize_columns(available_columns)
    allowed = SECTION_TARGET_COLUMNS.get(str(section), ())
    entity_type = str(target.get("entity_type") or "").lower()
    preferred = [col for col in ENTITY_COLUMN_PRIORITY.get(entity_type, ()) if col in allowed]
    ordered = preferred + [col for col in allowed if col not in preferred]
    if available:
        ordered = [col for col in ordered if col.upper() in available]
    return ordered


def build_target_sql_filter(
    section: str,
    target: dict[str, str] | None,
    alias: str = "",
    available_columns: tuple[str, ...] | list[str] | set[str] = (),
) -> str:
    """Return a SQL predicate for an allowlisted finding target."""
    target = target or {}
    if not target:
        return ""
    values = target_values(target)
    if not values:
        return ""
    columns = _candidate_columns(str(section), target, available_columns)
    if not columns:
        return ""
    exact_columns = [column for column in columns if column not in DISPLAY_FALLBACK_COLUMNS]
    display_columns = [column for column in columns if column in DISPLAY_FALLBACK_COLUMNS]
    prefix = _alias(alias)
    exact_predicates = [
        f"UPPER({prefix}{column}) = UPPER({sql_literal(value, 500)})"
        for column in exact_columns
        for value in values
    ]
    if exact_predicates:
        return "AND (" + " OR ".join(exact_predicates) + ")"
    display_predicates = [
        f"{prefix}{column} ILIKE '%' || {sql_literal(value, 500)} || '%'"
        for column in display_columns
        for value in values
    ]
    if display_predicates:
        return "AND (" + " OR ".join(display_predicates) + ")"
    return ""


def apply_target_dataframe_filter(rows: object, section: str, target: dict[str, str] | None = None) -> tuple[object, str]:
    """Vectorized fallback filter for small evidence dataframes."""
    target = target or get_decision_evidence_target(section)
    label = evidence_target_label(target)
    values = target_values(target)
    if not values or rows is None or not hasattr(rows, "empty") or getattr(rows, "empty", True):
        return rows, label
    try:
        columns = [str(column) for column in rows.columns]
    except Exception:
        return rows, label
    preferred = _candidate_columns(str(section), target, columns)
    if not preferred:
        return rows, label

    upper_values = [value.upper() for value in values]
    contains_pattern = "|".join(re.escape(value) for value in values if value)
    mask = None
    for column in preferred:
        series = rows[column].fillna("").astype(str)
        if column in DISPLAY_FALLBACK_COLUMNS:
            column_mask = series.str.contains(contains_pattern, case=False, regex=True, na=False)
        else:
            column_mask = series.str.upper().isin(upper_values)
        mask = column_mask if mask is None else (mask | column_mask)
    if mask is None:
        return rows, label
    return rows[mask].copy(), label


__all__ = [
    "SECTION_TARGET_COLUMNS",
    "TARGETED_EVIDENCE_DEFAULT_LIMIT",
    "TARGETED_EVIDENCE_MAX_LIMIT",
    "apply_target_dataframe_filter",
    "build_target_sql_filter",
    "clear_decision_evidence_target",
    "evidence_row_limit",
    "evidence_target_label",
    "get_decision_evidence_target",
    "target_values",
]
