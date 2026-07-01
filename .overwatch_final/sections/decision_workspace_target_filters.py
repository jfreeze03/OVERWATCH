"""Safe SQL and dataframe filters for Decision Workspace evidence targets."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any

import streamlit as st

from performance import (
    TARGETED_EVIDENCE_DEFAULT_LIMIT,
    TARGETED_EVIDENCE_MAX_LIMIT,
    record_ui_query_event,
)
from utils.sql_safe import sql_literal

TARGET_PREDICATE_MARKER = "/* OVERWATCH_TARGET_PREDICATE */"


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
        "ACTION_ID",
        "DEDUPE_KEY",
        "FINDING_KEY",
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
        "DEDUPE_KEY",
        "FINDING_KEY",
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
        "EVIDENCE_ID",
        "DEDUPE_KEY",
        "FINDING_KEY",
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
        "EVIDENCE_ID",
        "DEDUPE_KEY",
        "FINDING_KEY",
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
        "CREDENTIAL_ID",
        "CREDENTIAL_NAME",
        "ENTITY_NAME",
        "ENTITY_ID",
        "EVIDENCE_ID",
        "GRANT_ID",
        "ACTION_ID",
        "DEDUPE_KEY",
        "FINDING_KEY",
    ),
}

EVIDENCE_ID_COLUMNS = ("EVENT_ID", "ALERT_ID", "ALERT_KEY", "QUERY_ID", "GRANT_ID", "ACTION_ID")

ENTITY_ID_COLUMNS: dict[str, tuple[str, ...]] = {
    "alert": ("EVENT_ID", "ALERT_ID", "ALERT_KEY"),
    "event": ("EVENT_ID", "ALERT_ID", "ALERT_KEY"),
    "action": ("ACTION_ID",),
    "warehouse": ("WAREHOUSE_NAME", "WAREHOUSE"),
    "warehouse_name": ("WAREHOUSE_NAME", "WAREHOUSE"),
    "query": ("QUERY_ID", "QUERY_HASH", "QUERY_SIGNATURE"),
    "query_id": ("QUERY_ID",),
    "query_signature": ("QUERY_SIGNATURE", "QUERY_HASH"),
    "task": ("TASK_NAME", "ROOT_TASK_NAME"),
    "procedure": ("PROCEDURE_NAME",),
    "pipeline": ("PIPELINE_NAME", "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME"),
    "service": ("SERVICE_CATEGORY", "SERVICE_TYPE"),
    "service_category": ("SERVICE_CATEGORY", "SERVICE_TYPE"),
    "service_type": ("SERVICE_TYPE", "SERVICE_CATEGORY"),
    "cortex": ("SERVICE_CATEGORY", "SERVICE_TYPE", "APPLICATION", "USER_NAME"),
    "cortex_service": ("SERVICE_CATEGORY", "SERVICE_TYPE", "APPLICATION"),
    "user": ("USER_NAME", "LOGIN_NAME", "GRANTEE_NAME"),
    "user_credential": ("USER_NAME", "CREDENTIAL_ID", "CREDENTIAL_NAME", "EVIDENCE_ID"),
    "role": ("ROLE_NAME", "GRANTEE_NAME", "GRANTED_TO"),
    "database": ("DATABASE_NAME",),
    "grant": ("GRANT_ID",),
    "share": ("SHARE_NAME", "DATABASE_NAME", "OBJECT_NAME"),
    "tag": ("TAG_VALUE",),
    "department": ("DEPARTMENT", "TAG_VALUE"),
    "application": ("APPLICATION", "TAG_VALUE"),
}

ENTITY_DISPLAY_COLUMNS: dict[str, tuple[str, ...]] = {
    "alert": ("ALERT_FAMILY", "ALERT_TYPE", "FAMILY", "CATEGORY", "ENTITY_NAME"),
    "event": ("ALERT_FAMILY", "ALERT_TYPE", "FAMILY", "CATEGORY", "ENTITY_NAME"),
    "action": ("ENTITY_NAME",),
    "warehouse": ("ENTITY_NAME", "DRIVER", "DIMENSION"),
    "warehouse_name": ("ENTITY_NAME", "DRIVER", "DIMENSION"),
    "service": ("ENTITY_NAME", "DRIVER", "DIMENSION", "SERVICE_CATEGORY", "SERVICE_TYPE"),
    "service_category": ("ENTITY_NAME", "DRIVER", "DIMENSION", "SERVICE_CATEGORY"),
    "service_type": ("ENTITY_NAME", "DRIVER", "DIMENSION", "SERVICE_TYPE"),
    "query": ("ENTITY_NAME",),
    "query_id": ("ENTITY_NAME",),
    "query_signature": ("ENTITY_NAME",),
    "task": ("ENTITY_NAME",),
    "procedure": ("ENTITY_NAME",),
    "pipeline": ("ENTITY_NAME",),
    "user": ("ENTITY_NAME", "USER_NAME", "LOGIN_NAME", "GRANTEE_NAME"),
    "user_credential": ("ENTITY_NAME", "USER_NAME", "CREDENTIAL_NAME"),
    "role": ("ENTITY_NAME", "ROLE_NAME", "GRANTEE_NAME", "GRANTED_TO"),
    "database": ("ENTITY_NAME", "DATABASE_NAME"),
    "grant": ("ENTITY_NAME", "GRANTED_ON", "ROLE_NAME", "GRANTEE_NAME"),
    "share": ("ENTITY_NAME", "SHARE_NAME", "OBJECT_NAME"),
    "tag": ("TAG_VALUE", "ENTITY_NAME", "DRIVER", "DIMENSION"),
    "department": ("DEPARTMENT", "TAG_VALUE", "ENTITY_NAME", "DRIVER", "DIMENSION"),
    "application": ("APPLICATION", "TAG_VALUE", "ENTITY_NAME", "DRIVER", "DIMENSION"),
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


@dataclass(frozen=True)
class TargetPredicatePlan:
    exact_predicates: tuple[str, ...] = ()
    display_predicates: tuple[str, ...] = ()
    exact_columns_by_field: dict[str, tuple[str, ...]] | None = None
    display_columns_by_field: dict[str, tuple[str, ...]] | None = None
    columns_used: tuple[str, ...] = ()
    values_count: int = 0
    fallback_used: bool = False
    predicate_kind: str = ""
    plan_id: str = ""
    target_marker: str = TARGET_PREDICATE_MARKER

    @property
    def sql_filter(self) -> str:
        if self.exact_predicates:
            return f"AND {self.target_marker} (" + " OR ".join(self.exact_predicates) + ")"
        if self.display_predicates:
            return f"AND {self.target_marker} (" + " OR ".join(self.display_predicates) + ")"
        return ""

    def with_fingerprint(self) -> "TargetPredicatePlan":
        basis = "|".join([
            self.predicate_kind or ("exact" if self.exact_predicates else "display" if self.display_predicates else "none"),
            ",".join(self.columns_used),
            str(self.values_count),
            "fallback" if self.fallback_used else "exact",
        ])
        return TargetPredicatePlan(
            exact_predicates=self.exact_predicates,
            display_predicates=self.display_predicates,
            exact_columns_by_field=self.exact_columns_by_field,
            display_columns_by_field=self.display_columns_by_field,
            columns_used=self.columns_used,
            values_count=self.values_count,
            fallback_used=self.fallback_used,
            predicate_kind=self.predicate_kind or ("exact" if self.exact_predicates else "display" if self.display_predicates else "none"),
            plan_id=self.plan_id or sha1(basis.encode("utf-8", errors="ignore")).hexdigest()[:12],
            target_marker=self.target_marker,
        )


@dataclass(frozen=True)
class TargetSqlFilter:
    sql_fragment: str = ""
    safe_literals: tuple[str, ...] = ()
    bind_values: tuple[str, ...] = ()
    matched_columns: tuple[str, ...] = ()
    match_mode: str = "none"
    reason: str = ""
    plan_id: str = ""
    raw_sql_included: bool = False


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


def _available_columns(section: str, available_columns: tuple[str, ...] | list[str] | set[str]) -> set[str]:
    allowed = set(SECTION_TARGET_COLUMNS.get(str(section), ()))
    available = _normalize_columns(available_columns)
    return allowed & available if available else allowed


def _entity_type(target: dict[str, str]) -> str:
    return str(target.get("entity_type") or "").strip().lower()


def _columns_for_field(
    section: str,
    field: str,
    target: dict[str, str],
    available_columns: tuple[str, ...] | list[str] | set[str],
    *,
    display: bool = False,
) -> tuple[str, ...]:
    available = _available_columns(section, available_columns)
    entity_type = _entity_type(target)
    if field == "evidence_id":
        candidates = EVIDENCE_ID_COLUMNS
    elif field == "dedupe_key":
        candidates = ("DEDUPE_KEY",)
    elif field == "finding_key":
        candidates = ("FINDING_KEY",)
    elif field == "entity_id":
        candidates = ENTITY_ID_COLUMNS.get(entity_type, ("ENTITY_ID",))
    elif field == "entity_name":
        candidates = ENTITY_DISPLAY_COLUMNS.get(entity_type, ("ENTITY_NAME",)) if display else ENTITY_ID_COLUMNS.get(entity_type, ())
    else:
        candidates = ()
    return tuple(column for column in candidates if column in available)


def _predicate(column: str, value: str, alias: str = "", *, display: bool = False) -> str:
    prefix = _alias(alias)
    if display:
        return f"{prefix}{column} ILIKE '%' || {sql_literal(value, 500)} || '%'"
    return f"UPPER({prefix}{column}) = UPPER({sql_literal(value, 500)})"


def build_target_predicate_plan(
    section: str,
    target: dict[str, str] | None,
    available_columns: tuple[str, ...] | list[str] | set[str] = (),
    *,
    alias: str = "",
) -> TargetPredicatePlan:
    target = target or {}
    if not target:
        return TargetPredicatePlan()
    exact_predicates: list[str] = []
    display_predicates: list[str] = []
    exact_columns_by_field: dict[str, tuple[str, ...]] = {}
    display_columns_by_field: dict[str, tuple[str, ...]] = {}

    for field in ("evidence_id", "entity_id", "dedupe_key", "finding_key", "entity_name"):
        value = str(target.get(field) or "").strip()
        if not value:
            continue
        columns = _columns_for_field(section, field, target, available_columns)
        if columns:
            exact_columns_by_field[field] = columns
            exact_predicates.extend(_predicate(column, value, alias) for column in columns)

    if exact_predicates:
        columns_used = tuple(sorted({column for columns in exact_columns_by_field.values() for column in columns}))
        return TargetPredicatePlan(
            exact_predicates=tuple(exact_predicates),
            exact_columns_by_field=exact_columns_by_field,
            display_columns_by_field={},
            columns_used=columns_used,
            values_count=sum(1 for field in exact_columns_by_field if str(target.get(field) or "").strip()),
            fallback_used=False,
            predicate_kind="exact",
        ).with_fingerprint()

    value = str(target.get("entity_name") or "").strip()
    if value:
        display_columns = _columns_for_field(section, "entity_name", target, available_columns, display=True)
        if display_columns:
            display_columns_by_field["entity_name"] = display_columns
            display_predicates.extend(_predicate(column, value, alias, display=True) for column in display_columns)

    return TargetPredicatePlan(
        display_predicates=tuple(display_predicates),
        exact_columns_by_field={},
        display_columns_by_field=display_columns_by_field,
        columns_used=tuple(sorted({column for columns in display_columns_by_field.values() for column in columns})),
        values_count=sum(1 for field in display_columns_by_field if str(target.get(field) or "").strip()),
        fallback_used=bool(display_predicates),
        predicate_kind="display" if display_predicates else "none",
    ).with_fingerprint()


def build_target_sql_filter(
    section: str,
    target: dict[str, str] | None,
    alias: str = "",
    available_columns: tuple[str, ...] | list[str] | set[str] = (),
) -> str:
    """Return a SQL predicate for an allowlisted finding target."""
    return build_target_predicate_plan(section, target, available_columns, alias=alias).sql_filter


def build_target_sql_filter_contract(
    section: str,
    target: dict[str, str] | None,
    alias: str = "",
    available_columns: tuple[str, ...] | list[str] | set[str] = (),
) -> TargetSqlFilter:
    """Return a structured proof that target filtering is pushed into SQL safely."""
    plan = build_target_predicate_plan(section, target, available_columns, alias=alias).with_fingerprint()
    values = target_values(target or {})
    if plan.predicate_kind == "exact":
        match_mode = "exact"
        reason = "Target filter uses allowlisted exact-match columns before evidence load."
    elif plan.predicate_kind == "display":
        match_mode = "allowed_ilike"
        reason = "Target filter uses approved display columns with bounded SQL ILIKE fallback."
    else:
        match_mode = "none"
        reason = "No allowlisted target values or columns were available."
    return TargetSqlFilter(
        sql_fragment=plan.sql_filter,
        safe_literals=values,
        bind_values=(),
        matched_columns=plan.columns_used,
        match_mode=match_mode,
        reason=reason,
        plan_id=plan.plan_id,
        raw_sql_included=False,
    )


def _series_mask(rows: Any, column: str, value: str, *, display: bool = False):
    series = rows[column].fillna("").astype(str)
    if display:
        return series.str.contains(value, case=False, regex=False, na=False)
    return series.str.upper().isin([value.upper()])


def apply_target_dataframe_filter(rows: object, section: str, target: dict[str, str] | None = None) -> tuple[object, str]:
    """Vectorized fallback filter for evidence dataframes."""
    target = target or get_decision_evidence_target(section)
    label = evidence_target_label(target)
    if rows is None or not hasattr(rows, "empty") or getattr(rows, "empty", True):
        return rows, label
    try:
        columns = [str(column) for column in rows.columns]
    except Exception:
        return rows, label
    plan = build_target_predicate_plan(str(section), target, columns)
    mask = None
    for field, field_columns in (plan.exact_columns_by_field or {}).items():
        value = str(target.get(field) or "").strip()
        if not value:
            continue
        for column in field_columns:
            column_mask = _series_mask(rows, column, value)
            mask = column_mask if mask is None else (mask | column_mask)
    if mask is not None:
        return rows[mask].copy(), label

    display_columns_by_field = plan.display_columns_by_field or {}
    if not display_columns_by_field:
        return rows, label
    try:
        row_count = len(rows)
    except Exception:
        row_count = 0
    if row_count > TARGETED_EVIDENCE_MAX_LIMIT:
        record_ui_query_event(
            section=str(section),
            workflow="Decision Evidence",
            query_tier="target_filter",
            ttl_key="large_dataframe_display_filter_skipped",
            cache_hit_or_use_cache="dataframe",
            elapsed_ms=0,
            row_count=row_count,
            max_rows=TARGETED_EVIDENCE_MAX_LIMIT,
            error="Display target fallback skipped for large evidence frame.",
            actual_query_executed=False,
            cache_layer="none",
            query_boundary="evidence",
            first_paint_sensitive=False,
        )
        return rows, label

    for field, field_columns in display_columns_by_field.items():
        value = str(target.get(field) or "").strip()
        if not value:
            continue
        for column in field_columns:
            column_mask = _series_mask(rows, column, value, display=True)
            mask = column_mask if mask is None else (mask | column_mask)
    if mask is None:
        return rows, label
    return rows[mask].copy(), label


__all__ = [
    "SECTION_TARGET_COLUMNS",
    "TARGETED_EVIDENCE_DEFAULT_LIMIT",
    "TARGETED_EVIDENCE_MAX_LIMIT",
    "TARGET_PREDICATE_MARKER",
    "TargetPredicatePlan",
    "TargetSqlFilter",
    "apply_target_dataframe_filter",
    "build_target_predicate_plan",
    "build_target_sql_filter",
    "build_target_sql_filter_contract",
    "clear_decision_evidence_target",
    "evidence_row_limit",
    "evidence_target_label",
    "get_decision_evidence_target",
    "target_values",
]
