# sections/security_posture.py - Consolidated security and access workflow
from __future__ import annotations

from datetime import datetime
from importlib import import_module

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE, DEFAULT_COMPANY, DEFAULT_ENVIRONMENT
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    render_signal_lane_board,
    with_loaded_at,
)
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note


pd = lazy_pandas()

action_queue_environment_clause = _lazy_util("action_queue_environment_clause")
environment_label_for_database = _lazy_util("environment_label_for_database")
filter_existing_columns = _lazy_util("filter_existing_columns")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_db_filter_clause = _lazy_util("get_db_filter_clause")
get_environment_case_expr = _lazy_util("get_environment_case_expr")
get_environment_filter_clause = _lazy_util("get_environment_filter_clause")
get_session = _lazy_util("get_session")
get_user_filter_clause = _lazy_util("get_user_filter_clause")
mart_object_name = _lazy_util("mart_object_name")
make_action_id = _lazy_util("make_action_id")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
render_mode_selector = _lazy_util("render_mode_selector")
render_workflow_selector = _lazy_util("render_workflow_selector")
day_window_selectbox = _lazy_util("day_window_selectbox")
resolve_owner_context = _lazy_util("resolve_owner_context")
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")
upsert_actions = _lazy_util("upsert_actions")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def _mfa_count_expr(user_cols: set[str]) -> str:
    normalized = {str(col or "").upper() for col in user_cols}
    if "HAS_MFA" in normalized:
        return "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_mfa)), FALSE) = FALSE)"
    if "EXT_AUTHN_DUO" in normalized:
        return "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(ext_authn_duo)), FALSE) = FALSE)"
    return "NULL::NUMBER"


def _mfa_gap_predicate(user_cols: set[str], alias: str = "u") -> str:
    normalized = {str(col or "").upper() for col in user_cols}
    prefix = f"{alias}." if alias else ""
    if "HAS_MFA" in normalized:
        return f"AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR({prefix}has_mfa)), FALSE) = FALSE"
    if "EXT_AUTHN_DUO" in normalized:
        return f"AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR({prefix}ext_authn_duo)), FALSE) = FALSE"
    return "AND 1 = 0"


def _mfa_proof_label(user_cols: set[str]) -> str:
    normalized = {str(col or "").upper() for col in user_cols}
    if "HAS_MFA" in normalized:
        return "ACCOUNT_USAGE.USERS HAS_MFA signal"
    if "EXT_AUTHN_DUO" in normalized:
        return "ACCOUNT_USAGE.USERS EXT_AUTHN_DUO signal"
    return "ACCOUNT_USAGE.USERS MFA signal unavailable"


def _freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "account_usage" in source_key:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "mart" in source_key or "overwatch" in source_key:
        return "Freshness: fast summary refresh cadence"
    return "Freshness: depends on source view availability"


def _metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Measurement: Exact",
        "allocated": "Measurement: Allocated from source records",
        "estimated": "Measurement: Estimated",
    }
    return labels.get(str(kind or "").lower(), "Measurement depends on available account metadata")


def render_signal_confidence(*, source: str = "ACCOUNT_USAGE", confidence: str = "exact", scope_note: str = "") -> None:
    parts = [_freshness_note(source), _metric_confidence_label(confidence)]
    if scope_note:
        parts.append(scope_note)
    defer_source_note(*parts)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    _ = columns
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def render_workflow_guide(summary: str, rows) -> None:
    defer_section_note(summary)
    for trigger, action in rows:
        defer_section_note(f"{trigger}: {action}")


def render_workflow_module(workflow: str, workflow_modules: dict[str, str]) -> None:
    module_name = workflow_modules.get(str(workflow))
    if not module_name:
        st.warning(f"No module registered for workflow: {workflow}")
        return
    module = import_module(module_name)
    render = getattr(module, "render", None)
    if not callable(render):
        st.warning(f"Workflow module has no render() function: {module_name}")
        return
    render()

SECURITY_POSTURE_VIEWS = ("Security Brief", "Data Health", "Security Workflows")
SECURITY_POSTURE_VIEW_DETAILS = {
    "Security Brief": "Default cockpit: status strip, KPI row, and exception-first access workflow grid.",
    "Data Health": "Source health, privileged-grant status, control telemetry, and audit trust boundaries.",
    "Security Workflows": "Open privileged grants, dormant users, MFA/login risk, and data sharing telemetry.",
}

WORKFLOWS = ("Access posture", "Privilege sprawl", "Data sharing exposure")

WORKFLOW_DETAILS = {
    "Access posture": "Failed logins, MFA gaps, grants, role risk, and security exceptions.",
    "Privilege sprawl": "Admin roles, ownership grants, grant-option exposure, and telemetry gaps.",
    "Data sharing exposure": "Shares, imported databases, exposed datasets, and route follow-up.",
}

SECURITY_BRIEF_WORKFLOWS = (
    {
        "WORKFLOW": "Access posture",
        "BUTTON_LABEL": "Open Access",
        "DBA_MOVE": "Start with failed logins, MFA gaps, and user-level access signals.",
        "WHEN": "Morning triage, identity incidents, or audit prep.",
    },
    {
        "WORKFLOW": "Privilege sprawl",
        "BUTTON_LABEL": "Open Privileges",
        "DBA_MOVE": "Review admin roles, ownership, grant option, and review blockers.",
        "WHEN": "Role cleanup, least-privilege review, or elevated-access questions.",
    },
    {
        "WORKFLOW": "Data sharing exposure",
        "BUTTON_LABEL": "Open Sharing",
        "DBA_MOVE": "Validate shared databases, imported data, consumers, and ownership.",
        "WHEN": "External exposure, vendor access, or data-sharing audit review.",
    },
)

WORKFLOW_MODULES = {
    "Access posture": "sections.security_access",
    "Data sharing exposure": "sections.data_sharing",
}

SECURITY_ACCESS_REVIEW_TABLE = "OVERWATCH_SECURITY_ACCESS_REVIEW"
SECURITY_OPERABILITY_FACT_TABLE = "FACT_SECURITY_OPERABILITY_DAILY"
SECURITY_SCOPE_FILTER_KEYS = (
    "global_user",
    "global_database",
    "global_role",
    "global_start_date",
    "global_end_date",
)
_SECURITY_PROOF_TABLES_KEY = "security_posture_show_proof_tables"
_SECURITY_PROOF_TABLES_SCOPE_KEY = "security_posture_proof_tables_scope"


def security_access_review_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = SECURITY_ACCESS_REVIEW_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def build_security_access_review_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = SECURITY_ACCESS_REVIEW_TABLE,
) -> str:
    fqn = security_access_review_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID             VARCHAR(64),
    SNAPSHOT_TS             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY                 VARCHAR(100),
    ENVIRONMENT             VARCHAR(100),
    DATABASE_CONTEXT        BOOLEAN,
    FINDING_TYPE            VARCHAR(120),
    SEVERITY                VARCHAR(40),
    ENTITY_TYPE             VARCHAR(120),
    ENTITY                  VARCHAR(500),
    EVENT_COUNT             NUMBER,
    DISTINCT_SOURCES        NUMBER,
    LAST_SEEN               VARCHAR(100),
    OWNER                   VARCHAR(200),
    ESCALATION_TARGET       VARCHAR(200),
    OWNER_SOURCE            VARCHAR(200),
    APPROVER                VARCHAR(200),
    OWNER_APPROVAL_STATUS   VARCHAR(40),
    ACCESS_REVIEW_STATE     VARCHAR(160),
    ROLE_CAPABILITY_STATE   VARCHAR(200),
    TICKET_REQUIRED         VARCHAR(20),
    REVIEW_BY_REQUIRED      VARCHAR(20),
    PROOF_REQUIRED          VARCHAR(2000),
    VERIFICATION_QUERY      VARCHAR(8000),
    ACCESS_TICKET_ID        VARCHAR(200),
    REVIEW_BY_DATE          VARCHAR(100),
    IAM_APPROVAL_STATE      VARCHAR(120),
    REVIEW_READINESS        VARCHAR(100),
    REVIEW_BLOCKERS         VARCHAR(2000),
    REVIEW_SLA_HOURS        NUMBER,
    VERIFICATION_STATUS     VARCHAR(80),
    VERIFICATION_RESULT     VARCHAR(4000),
    CONTROL_READINESS       VARCHAR(100),
    CONTROL_BLOCKERS        VARCHAR(2000),
    NEXT_CONTROL_ACTION     VARCHAR(4000),
    NEXT_ACTION             VARCHAR(4000),
    PROOF_QUERY             VARCHAR(4000),
    SOURCE                  VARCHAR(500)
);"""


def build_security_access_review_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = SECURITY_ACCESS_REVIEW_TABLE,
) -> list[str]:
    fqn = security_access_review_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ACCESS_TICKET_ID VARCHAR(200)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_BY_DATE VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS IAM_APPROVAL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_READINESS VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_SLA_HOURS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS VERIFICATION_STATUS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS VERIFICATION_RESULT VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_READINESS VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]


def security_operability_fact_fqn(table: str = SECURITY_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)


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
            "surface": "Security brief",
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


def build_security_operability_fact_ddl(table: str = SECURITY_OPERABILITY_FACT_TABLE) -> str:
    fqn = security_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE                   DATE,
    COMPANY                         VARCHAR(100),
    ENVIRONMENT                     VARCHAR(100),
    CONTROL_SOURCE                  VARCHAR(80),
    FINDING_TYPE                    VARCHAR(120),
    ENTITY                          VARCHAR(500),
    ENTITY_TYPE                     VARCHAR(120),
    SEVERITY                        VARCHAR(40),
    CONTROL_STATE                   VARCHAR(120),
    CONTROL_RANK                    NUMBER,
    EVENT_ROWS                      NUMBER,
    REVIEW_ROWS                     NUMBER,
    REVIEW_BLOCKER_ROWS             NUMBER,
    TICKET_REQUIRED_ROWS            NUMBER,
    REVIEW_BY_REQUIRED_ROWS         NUMBER,
    CAPABILITY_PROOF_ROWS           NUMBER,
    NO_DATABASE_CONTEXT_ROWS        NUMBER,
    OPEN_ACTIONS                    NUMBER,
    OVERDUE_OPEN                    NUMBER,
    FIXED_WITHOUT_VERIFICATION      NUMBER,
    VERIFIED_CLOSURES               NUMBER,
    OWNER_APPROVAL_GAP_ROWS         NUMBER,
    NEXT_CONTROL_ACTION             VARCHAR(4000),
    LAST_ACTIVITY_TS                TIMESTAMP_NTZ,
    LOAD_TS                         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""


def build_security_operability_fact_migration_sql(
    table: str = SECURITY_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = security_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EVENT_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_BLOCKER_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS TICKET_REQUIRED_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_BY_REQUIRED_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CAPABILITY_PROOF_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NO_DATABASE_CONTEXT_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]


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


def _security_action_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "failed login" in value:
        return (
            "User/Auth",
            "Validate whether attempts are expected; compare with IAM logs, source IP, and recent changes before locking or disabling the user.",
            "-- Detail: LOGIN_HISTORY grouped by user, source IP, client, and error code.",
        )
    if "mfa" in value:
        return (
            "User/Auth",
            "Confirm the user authentication path, then enforce MFA through Snowflake or the identity provider.",
            "-- Detail: ACCOUNT_USAGE.USERS MFA/ext_authn_duo signal.",
        )
    if "grant" in value:
        return (
            "Grant/Role",
            "Confirm the grant route, business justification, and role hierarchy before revoking or narrowing access.",
            "-- Detail: ACCOUNT_USAGE.GRANTS_TO_USERS active grants created in the selected window.",
        )
    if "shared" in value or "database exposure" in value:
        return (
            "Shared Data",
            "Validate the consumer, route, contract, and data classification before leaving the share active.",
            "-- Detail: ACCOUNT_USAGE.DATABASES imported/share metadata.",
        )
    return (
        "User/Access",
        "Validate with IAM/Snowflake history, confirm the route, then remediate access or authentication configuration.",
        "-- Review telemetry query and route before revoking grants, disabling users, or enforcing MFA.",
    )


def _security_exception_has_database_context(row: pd.Series | dict) -> bool:
    if _security_exception_database(row):
        return True
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    return "shared" in finding_type or "database exposure" in finding_type or "object grant" in finding_type


def _security_exception_database(row: pd.Series | dict) -> str:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    if "failed login" in finding_type or "mfa" in finding_type or finding_type == "recent grant":
        return ""
    for key in ("DATABASE_NAME", "OBJECT_DATABASE", "TABLE_CATALOG"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    entity = str(row.get("ENTITY") or "").strip()
    if "." in entity:
        return entity.split(".", 1)[0].strip('"')
    if entity.upper().startswith(("ALFA_", "TRXS_")):
        return entity.strip('"')
    return ""


def _security_exception_environment(row: pd.Series | dict, environment: str = "ALL") -> str:
    if not _security_exception_has_database_context(row):
        return "No Database Context"
    database_name = _security_exception_database(row)
    if database_name:
        return environment_label_for_database(database_name)
    return str(environment or "").strip() or "ALL"


def _security_owner_context(row: pd.Series | dict) -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    entity = str(row.get("ENTITY") or "").upper()
    if "failed login" in finding_type or "mfa" in finding_type:
        base = {
            "owner": "IAM / Security Route",
            "escalation": "Security / DBA Route",
            "source": "Security route map",
        }
    elif "grant" in finding_type:
        if any(token in entity for token in ("ADMIN", "SECURITY", "SYSADMIN", "ACCOUNTADMIN")):
            base = {
                "owner": "Security Route",
                "escalation": "DBA / Security Route",
                "source": "Admin-role route hint",
            }
        else:
            base = {
                "owner": "Access Route / DBA Security",
                "escalation": "Data / Security Route",
                "source": "Security route map",
            }
    elif "shared" in finding_type or "exposure" in finding_type:
        base = {
            "owner": "Data / Security Route",
                "escalation": "Data Steward / Legal",
            "source": "Shared-data route map",
        }
    else:
        base = {
            "owner": "Security/DBA",
            "escalation": "DBA Lead",
            "source": "Default security route",
        }
    directory_context = resolve_owner_context(
        row,
        entity=entity,
        entity_type="SECURITY",
        owner=base["owner"],
        category=finding_type or "Security",
    )
    return {
        "owner": directory_context.get("OWNER") or base["owner"],
        "escalation": base["escalation"] or directory_context.get("ESCALATION_TARGET", ""),
        "source": f"{base['source']}; {directory_context.get('OWNER_SOURCE', '')}".strip("; "),
        "owner_email": directory_context.get("OWNER_EMAIL", ""),
        "oncall_primary": directory_context.get("ONCALL_PRIMARY", ""),
        "oncall_secondary": directory_context.get("ONCALL_SECONDARY", ""),
        "approval_group": "",
        "owner_evidence": directory_context.get("OWNER_EVIDENCE", ""),
    }


def _security_review_context(row: pd.Series | dict) -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    if "failed login" in finding_type:
        return {
            "reviewer": "IAM / Security",
            "review_state": "Identity investigation required",
            "role_capability_state": "Not required",
            "proof_required": "user, source IP/client, error code, IAM corroboration, disposition",
        }
    if "mfa" in finding_type:
        return {
            "reviewer": "IAM / Security",
            "review_state": "MFA enforcement review required",
            "role_capability_state": "Not required",
            "proof_required": "user, auth path, MFA/SSO posture, exception note if any",
        }
    if "grant" in finding_type:
        return {
            "reviewer": "Access / Security",
            "review_state": "Access review required",
            "role_capability_state": "MANAGE GRANTS or role capability check required before change",
            "proof_required": "role, grantee, requester, ticket/reference, review/expiry date, telemetry status",
        }
    if "shared" in finding_type or "exposure" in finding_type:
        return {
            "reviewer": "Data Steward / Security",
            "review_state": "External sharing review required",
            "role_capability_state": "OWNERSHIP / IMPORTED PRIVILEGES capability check required for remediation",
            "proof_required": "consumer, provider, data classification, contract, review date",
        }
    return {
        "reviewer": "Security",
        "review_state": "Security review required",
        "role_capability_state": "Capability check depends on remediation",
        "proof_required": "finding telemetry, reviewer, ticket/reference, status",
    }


def _security_exception_verification_sql(row: pd.Series | dict) -> str:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    entity = str(row.get("ENTITY") or "").strip()
    entity_lit = sql_literal(entity, 500)
    if "failed login" in finding_type:
        return f"""
SELECT
    user_name,
    event_timestamp,
    client_ip,
    reported_client_type,
    error_code,
    error_message,
    is_success
FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
WHERE event_timestamp >= DATEADD('day', -14, CURRENT_TIMESTAMP())
  AND UPPER(user_name) = UPPER({entity_lit})
  AND is_success = 'NO'
ORDER BY event_timestamp DESC
LIMIT 100""".strip()
    if "mfa" in finding_type:
        return f"""
SELECT
    name AS user_name,
    disabled,
    has_password,
    ext_authn_duo,
    last_success_login,
    owner,
    created_on
FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
WHERE UPPER(name) = UPPER({entity_lit})
LIMIT 50""".strip()
    if "grant" in finding_type:
        database_name = _security_exception_database(row)
        if database_name:
            db_lit = sql_literal(database_name, 300)
            return f"""
SELECT
    created_on,
    privilege,
    granted_on,
    name,
    table_catalog AS database_name,
    table_schema AS schema_name,
    granted_to,
    grantee_name,
    grant_option,
    granted_by,
    deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
WHERE deleted_on IS NULL
  AND UPPER(table_catalog) = UPPER({db_lit})
ORDER BY created_on DESC
LIMIT 100""".strip()
        return f"""
SELECT
    grantee_name,
    role,
    granted_to,
    granted_by,
    created_on,
    deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
WHERE UPPER(grantee_name) = UPPER({entity_lit})
  AND deleted_on IS NULL
ORDER BY created_on DESC
LIMIT 100""".strip()
    if "shared" in finding_type or "exposure" in finding_type:
        return f"""
SELECT
    database_name,
    database_owner,
    type,
    origin,
    owner,
    comment,
    created
FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES
WHERE UPPER(database_name) = UPPER({entity_lit})
  AND deleted IS NULL
LIMIT 50""".strip()
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS verification_ts,
    {sql_literal(str(row.get('FINDING_TYPE') or 'Security Finding'), 200)} AS finding_type,
    {entity_lit} AS entity
LIMIT 50""".strip()


def _security_access_review_sla_hours(severity: str) -> int:
    value = str(severity or "").upper()
    if value == "CRITICAL":
        return 8
    if value == "HIGH":
        return 24
    if value == "MEDIUM":
        return 72
    return 168


def _security_access_review_readiness_for_row(row: pd.Series | dict) -> dict:
    """Return ticket/reference, telemetry, and blocker state for a security finding."""
    owner = str(row.get("OWNER") or "").strip()
    owner_source = str(row.get("OWNER_SOURCE") or "").strip()
    owner_email = str(row.get("OWNER_EMAIL") or "").strip()
    oncall = str(row.get("ONCALL_PRIMARY") or "").strip()
    escalation = str(row.get("ESCALATION_TARGET") or "").strip()
    owner_upper = owner.upper()
    route_ready = bool(owner) and owner_upper not in {"UNKNOWN", "N/A", "NONE"} and bool(
        owner_email
        or oncall
        or escalation
        or "SECURITY" in owner_upper
        or "IAM" in owner_upper
    )

    ticket_id = str(row.get("ACCESS_TICKET_ID") or row.get("TICKET_ID") or "").strip()
    review_by = str(row.get("REVIEW_BY_DATE") or row.get("REVIEW_BY") or row.get("REVIEW_DATE") or "").strip()
    verification_status = str(row.get("VERIFICATION_STATUS") or "Pending").strip()
    verification_result = str(row.get("VERIFICATION_RESULT") or "").strip()
    verification_query = str(row.get("VERIFICATION_QUERY") or "").strip()
    ticket_required = str(row.get("TICKET_REQUIRED") or "Yes").strip().upper() == "YES"
    review_required = str(row.get("REVIEW_BY_REQUIRED") or "Yes").strip().upper() == "YES"

    blockers: list[str] = []
    if not route_ready:
        blockers.append("route/on-call context")
    if ticket_required and not ticket_id:
        blockers.append("access ticket")
    if review_required and not review_by:
        blockers.append("review/expiry date")
    if not verification_query:
        blockers.append("telemetry query")

    verified = (
        verification_status.upper() == "VERIFIED"
        and len(verification_result) >= 15
    )
    if verified and not blockers:
        readiness = "Verified"
        rank = 8
        next_action = "Keep IAM/Snowflake telemetry with the access-review snapshot."
    elif "route/on-call context" in blockers:
        readiness = "Assignment Blocked"
        rank = 0
        next_action = "Assign this finding before queueing closure."
    elif "access ticket" in blockers or "review/expiry date" in blockers:
        readiness = "Ticket / Review Date Blocked"
        rank = 1
        next_action = "Add the access ticket and review/expiry date before treating this finding as controlled."
    elif "telemetry query" in blockers:
        readiness = "Telemetry Pending"
        rank = 3
        next_action = "Load the read-only Snowflake telemetry query before queueing the action."
    else:
        readiness = "Ready for Action Queue"
        rank = 4
        next_action = "Queue or work the security action, then monitor the resulting telemetry."

    return {
        "ACCESS_TICKET_ID": ticket_id,
        "REVIEW_BY_DATE": review_by,
        "IAM_REVIEW_STATE": "Review Required",
        "REVIEW_READINESS": readiness,
        "REVIEW_RANK": rank,
        "REVIEW_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "REVIEW_SLA_HOURS": _security_access_review_sla_hours(str(row.get("SEVERITY") or "")),
        "VERIFICATION_STATUS": verification_status or "Pending",
        "VERIFICATION_RESULT": verification_result,
        "CONTROL_READINESS": readiness,
        "CONTROL_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "NEXT_CONTROL_ACTION": next_action,
    }


def _build_security_access_review(exceptions: pd.DataFrame, environment: str = "ALL") -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    view = _security_priority_view(exceptions).copy()
    owner_contexts = view.apply(_security_owner_context, axis=1)
    review_contexts = view.apply(_security_review_context, axis=1)
    view["OWNER"] = owner_contexts.apply(lambda item: item["owner"])
    view["ESCALATION_TARGET"] = owner_contexts.apply(lambda item: item["escalation"])
    view["OWNER_SOURCE"] = owner_contexts.apply(lambda item: item["source"])
    view["OWNER_EMAIL"] = owner_contexts.apply(lambda item: item.get("owner_email", ""))
    view["ONCALL_PRIMARY"] = owner_contexts.apply(lambda item: item.get("oncall_primary", ""))
    view["ONCALL_SECONDARY"] = owner_contexts.apply(lambda item: item.get("oncall_secondary", ""))
    view["APPROVAL_GROUP"] = ""
    view["OWNER_EVIDENCE"] = owner_contexts.apply(lambda item: item.get("owner_evidence", ""))
    view["APPROVER"] = review_contexts.apply(lambda item: item["reviewer"])
    view["OWNER_APPROVAL_STATUS"] = ""
    view["ACCESS_REVIEW_STATE"] = review_contexts.apply(lambda item: item["review_state"])
    view["ROLE_CAPABILITY_STATE"] = review_contexts.apply(lambda item: item["role_capability_state"])
    view["TICKET_REQUIRED"] = "Yes"
    view["REVIEW_BY_REQUIRED"] = "Yes"
    view["PROOF_REQUIRED"] = review_contexts.apply(lambda item: item["proof_required"])
    view["VERIFICATION_QUERY"] = view.apply(_security_exception_verification_sql, axis=1)
    view["DATABASE_CONTEXT"] = view.apply(_security_exception_has_database_context, axis=1)
    view["DATABASE_NAME"] = view.apply(_security_exception_database, axis=1)
    view["ENVIRONMENT"] = view.apply(lambda row: _security_exception_environment(row, environment), axis=1)
    view["SCOPE_CONFIDENCE"] = view["DATABASE_CONTEXT"].map({True: "Database Context", False: "Account/User Context"})
    view["SCOPE_EVIDENCE"] = view.apply(
        lambda row: (
            f"Database={row.get('DATABASE_NAME')}; environment={row.get('ENVIRONMENT')}"
            if bool(row.get("DATABASE_CONTEXT"))
            else "No database context; company/user scope only"
        ),
        axis=1,
    )
    readiness_contexts = view.apply(_security_access_review_readiness_for_row, axis=1)
    for column in [
        "ACCESS_TICKET_ID",
        "REVIEW_BY_DATE",
        "IAM_APPROVAL_STATE",
        "REVIEW_READINESS",
        "REVIEW_RANK",
        "REVIEW_BLOCKERS",
        "REVIEW_SLA_HOURS",
        "VERIFICATION_STATUS",
        "VERIFICATION_RESULT",
        "CONTROL_READINESS",
        "CONTROL_BLOCKERS",
        "NEXT_CONTROL_ACTION",
    ]:
        view[column] = readiness_contexts.apply(lambda item, col=column: item.get(col, ""))
    return view


def _security_privileged_grant_review_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Return high-risk account-role and object grants with environment-aware object scope."""
    days = max(1, min(int(days or 30), 90))
    user_filter = get_user_filter_clause("gtu.grantee_name")
    object_env_filter = get_environment_filter_clause(
        "gor.table_catalog",
        environment=environment,
        company=company,
    )
    object_env_expr = get_environment_case_expr("gor.table_catalog")
    return f"""WITH privileged_role_grants AS (
    SELECT
        'Privileged Role Grant' AS finding_type,
        IFF(UPPER(gtu.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN'), 'Critical', 'High') AS severity,
        gtu.grantee_name AS entity,
        gtu.role AS role_name,
        NULL::VARCHAR AS privilege,
        FALSE AS grant_option,
        NULL::VARCHAR AS object_name,
        NULL::VARCHAR AS database_name,
        FALSE AS database_context,
        'No Database Context' AS environment,
        'ACCOUNT_USAGE.GRANTS_TO_USERS privileged role grants' AS proof_query,
        gtu.granted_by,
        gtu.created_on,
        DATEDIFF('day', gtu.created_on, CURRENT_TIMESTAMP()) AS grant_age_days,
        'Business justification, ticket/reference, review-by date, and telemetry status required.' AS proof_required,
        'Review account-level privileged role grant; do not hide this row behind a database environment filter.' AS next_action
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS gtu
    WHERE gtu.deleted_on IS NULL
      AND (
          UPPER(gtu.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN')
          OR UPPER(gtu.role) ILIKE '%ADMIN%'
          OR UPPER(gtu.role) ILIKE '%SECURITY%'
      )
      {user_filter}
),
object_privilege_grants AS (
    SELECT
        'Privileged Object Grant' AS finding_type,
        IFF(
            UPPER(gor.privilege) IN ('OWNERSHIP', 'APPLY MASKING POLICY', 'APPLY ROW ACCESS POLICY')
            OR COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true',
            'High',
            'Medium'
        ) AS severity,
        gor.grantee_name AS entity,
        NULL::VARCHAR AS role_name,
        gor.privilege AS privilege,
        COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true' AS grant_option,
        gor.name AS object_name,
        gor.table_catalog AS database_name,
        TRUE AS database_context,
        {object_env_expr} AS environment,
        'ACCOUNT_USAGE.GRANTS_TO_ROLES privileged object grants' AS proof_query,
        gor.granted_by,
        gor.created_on,
        DATEDIFF('day', gor.created_on, CURRENT_TIMESTAMP()) AS grant_age_days,
        'Privilege justification, ticket/reference, review-by date, and rollback status required.' AS proof_required,
        'Review database-scoped object privilege before revoke/narrowing action.' AS next_action
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
    WHERE gor.deleted_on IS NULL
      AND gor.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND gor.table_catalog IS NOT NULL
      AND (
          UPPER(gor.privilege) IN (
              'OWNERSHIP',
              'MANAGE GRANTS',
              'APPLY MASKING POLICY',
              'APPLY ROW ACCESS POLICY',
              'CREATE DATABASE ROLE',
              'CREATE SCHEMA',
              'CREATE TABLE',
              'CREATE VIEW'
          )
          OR COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true'
      )
      {object_env_filter}
)
SELECT
    finding_type,
    severity,
    entity,
    role_name,
    privilege,
    grant_option,
    object_name,
    database_name,
    database_context,
    environment,
    proof_query,
    granted_by,
    created_on,
    grant_age_days,
    proof_required,
    next_action
FROM privileged_role_grants
UNION ALL
SELECT
    finding_type,
    severity,
    entity,
    role_name,
    privilege,
    grant_option,
    object_name,
    database_name,
    database_context,
    environment,
    proof_query,
    granted_by,
    created_on,
    grant_age_days,
    proof_required,
    next_action
FROM object_privilege_grants
ORDER BY
    CASE severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
    created_on DESC
LIMIT 200""".strip()


def _annotate_security_privileged_grant_readiness(grants: pd.DataFrame) -> pd.DataFrame:
    """Add route and review status fields to privileged grant rows."""
    if grants is None or grants.empty:
        return pd.DataFrame() if grants is None else grants
    view = grants.copy()
    view.columns = [str(col).upper() for col in view.columns]
    rows = []
    for _, row in view.iterrows():
        context = _security_owner_context({
            "FINDING_TYPE": row.get("FINDING_TYPE", "Privileged Grant"),
            "ENTITY": row.get("ENTITY", ""),
            "DATABASE_NAME": row.get("DATABASE_NAME", ""),
        })
        route_ready = bool(context.get("owner_email") or context.get("oncall_primary") or context.get("escalation"))
        database_context = bool(row.get("DATABASE_CONTEXT"))
        role_name = str(row.get("ROLE_NAME") or "").strip().upper()
        object_name = str(row.get("OBJECT_NAME") or "").strip()
        severity = str(row.get("SEVERITY") or "").strip().upper()
        if role_name in {"ACCOUNTADMIN", "ORGADMIN", "SECURITYADMIN"}:
            review_state = "Tier 0 role grant"
        elif role_name:
            review_state = "Privileged role grant"
        elif object_name:
            review_state = "Privileged object grant"
        else:
            review_state = "Grant review"
        if not route_ready:
            readiness = "Assignment Blocked"
            rank = 0
            next_action = "Assign this privileged-access finding before changing access."
        elif severity in {"CRITICAL", "HIGH"}:
            readiness = "Telemetry Pending"
            rank = 1
            next_action = "Load ticket/reference, impact note, and rollback status before revoke or narrowing action."
        else:
            readiness = "Review Ready"
            rank = 2
            next_action = "Validate business justification and monitor telemetry before closure."
        rows.append({
            "OWNER": context.get("owner", ""),
            "OWNER_EMAIL": context.get("owner_email", ""),
            "ONCALL_PRIMARY": context.get("oncall_primary", ""),
            "APPROVAL_GROUP": "",
            "ESCALATION_TARGET": context.get("escalation", ""),
            "OWNER_SOURCE": context.get("source", ""),
            "OWNER_EVIDENCE": context.get("owner_evidence", ""),
            "OWNER_ROUTE_READY": "Yes" if route_ready else "No",
            "GRANT_REVIEW_STATE": review_state,
            "GRANT_REVIEW_READINESS": readiness,
            "GRANT_REVIEW_RANK": rank,
            "DATABASE_CONTEXT": database_context,
            "SCOPE_CONFIDENCE": "Database Context" if database_context else "Account/User Context",
            "NEXT_GRANT_ACTION": next_action,
        })
    annotated = pd.concat([view.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    return annotated.sort_values(
        ["GRANT_REVIEW_RANK", "SEVERITY", "CREATED_ON"],
        ascending=[True, True, False],
    )


def _privilege_sprawl_summary(grants: pd.DataFrame | None) -> dict:
    """Summarize privileged access sprawl without requiring another Snowflake query."""
    if grants is None or not isinstance(grants, pd.DataFrame) or grants.empty:
        return {
            "total": 0,
            "tier0": 0,
            "admin_role_grants": 0,
            "object_privileges": 0,
            "ownership_or_grant_option": 0,
            "verification_required": 0,
            "route_blocked": 0,
            "account_scope": 0,
            "stale_admin_grants": 0,
        }
    frame = grants.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    def _column(name: str, default=None) -> pd.Series:
        value = frame.get(name)
        if isinstance(value, pd.DataFrame):
            return value.iloc[:, -1]
        if isinstance(value, pd.Series):
            return value
        return pd.Series([default] * len(frame))

    role = _column("ROLE_NAME", "").fillna("").astype(str).str.upper()
    privilege = _column("PRIVILEGE", "").fillna("").astype(str).str.upper()
    grant_option = _column("GRANT_OPTION", False).fillna(False)
    if not isinstance(grant_option, pd.Series):
        grant_option = pd.Series(dtype=bool)
    grant_option_flag = grant_option.astype(str).str.lower().isin(["true", "1", "yes"])
    readiness = _column("GRANT_REVIEW_READINESS", "").fillna("").astype(str)
    database_context = _column("DATABASE_CONTEXT", False).fillna(False)
    age_days = pd.to_numeric(_column("GRANT_AGE_DAYS", 0), errors="coerce").fillna(0)
    tier0_roles = {"ACCOUNTADMIN", "ORGADMIN", "SECURITYADMIN"}
    admin_role_mask = role.ne("")
    object_privilege_mask = privilege.ne("")
    tier0_mask = role.isin(tier0_roles)
    ownership_or_grant_option = privilege.isin(["OWNERSHIP", "MANAGE GRANTS"]) | grant_option_flag
    return {
        "total": int(len(frame)),
        "tier0": int(tier0_mask.sum()),
        "admin_role_grants": int(admin_role_mask.sum()),
        "object_privileges": int(object_privilege_mask.sum()),
        "ownership_or_grant_option": int(ownership_or_grant_option.sum()),
        "verification_required": int(readiness.eq("Telemetry Pending").sum()),
        "route_blocked": int(readiness.eq("Assignment Blocked").sum()),
        "account_scope": int((~database_context.astype(bool)).sum()),
        "stale_admin_grants": int((admin_role_mask & (age_days >= 90)).sum()),
    }


def _privileged_grant_verification_sql(row: pd.Series | dict) -> str:
    """Return read-only telemetry detail for a privileged grant review row."""
    entity = str(row.get("ENTITY") or "").strip()
    role_name = str(row.get("ROLE_NAME") or "").strip()
    object_name = str(row.get("OBJECT_NAME") or "").strip()
    database_name = str(row.get("DATABASE_NAME") or "").strip()
    entity_lit = sql_literal(entity, 500)
    if role_name:
        role_lit = sql_literal(role_name, 300)
        return f"""
SELECT
    grantee_name,
    role,
    granted_by,
    created_on,
    deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
WHERE deleted_on IS NULL
  AND UPPER(grantee_name) = UPPER({entity_lit})
  AND UPPER(role) = UPPER({role_lit})
ORDER BY created_on DESC
LIMIT 100""".strip()
    if object_name:
        object_lit = sql_literal(object_name, 800)
        db_clause = ""
        if database_name:
            db_clause = f"\n  AND UPPER(table_catalog) = UPPER({sql_literal(database_name, 300)})"
        return f"""
SELECT
    created_on,
    privilege,
    granted_on,
    name,
    table_catalog AS database_name,
    table_schema AS schema_name,
    granted_to,
    grantee_name,
    grant_option,
    granted_by,
    deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
WHERE deleted_on IS NULL
  AND UPPER(grantee_name) = UPPER({entity_lit})
  AND UPPER(name) = UPPER({object_lit}){db_clause}
ORDER BY created_on DESC
LIMIT 100""".strip()
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS verification_ts,
    {entity_lit} AS grantee_name,
    'Privileged grant review row did not include a role or object name.' AS review_note
LIMIT 50""".strip()


def _privileged_grant_action_payload(row: pd.Series | dict, *, company: str, environment: str) -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "Privileged Grant")
    entity = str(row.get("ENTITY") or "Unknown")
    role_name = str(row.get("ROLE_NAME") or "").strip()
    object_name = str(row.get("OBJECT_NAME") or "").strip()
    database_name = str(row.get("DATABASE_NAME") or "").strip()
    severity = str(row.get("SEVERITY") or "High")
    target = role_name or object_name or database_name or entity
    finding = f"{finding_type}: {entity} has privileged access to {target}"
    verification_query = _privileged_grant_verification_sql(row)
    row_environment = str(row.get("ENVIRONMENT") or environment or "ALL")
    return {
        "Action ID": make_action_id("Security Privileged Grant", entity, target),
        "Source": "Security Posture - Privileged Grant Status",
        "Severity": severity,
        "Category": "Security Access Review",
        "Entity Type": "Privileged Grant",
        "Entity": entity,
        "Owner": row.get("OWNER", "Security/DBA"),
        "Owner Email": row.get("OWNER_EMAIL", ""),
        "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
        "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
        "Review Group": row.get("ESCALATION_TARGET", "Security"),
        "Escalation Target": row.get("ESCALATION_TARGET", "DBA / Security Route"),
        "Owner Source": row.get("OWNER_SOURCE", ""),
        "Owner Evidence": row.get("OWNER_EVIDENCE", ""),
        "Finding": finding,
        "Action": (
            "Review privileged grant before granting, revoking, or narrowing access. "
            f"Status={row.get('GRANT_REVIEW_READINESS', '')}; "
            f"state={row.get('GRANT_REVIEW_STATE', '')}; telemetry basis={row.get('PROOF_REQUIRED', '')}."
        ),
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": "\n".join([
            "-- Review-only privileged grant control row.",
            "-- Do not grant, revoke, or narrow access from OVERWATCH; use Snowflake/IAM operational change paths.",
            f"-- Role: {role_name or 'N/A'}",
            f"-- Object: {object_name or 'N/A'}",
            f"-- Database: {database_name or 'No database context'}",
            f"-- Environment: {row_environment}",
            "-- Use the telemetry query and ticket/reference before remediation.",
        ]),
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Ticket ID": "",
        "Reviewer": row.get("ESCALATION_TARGET", "Security"),
        "Review Status": "Requested",
        "Review Note": (
            f"{row.get('GRANT_REVIEW_STATE', '')}; status {row.get('GRANT_REVIEW_READINESS', '')}; "
            f"assignment ready {row.get('OWNER_ROUTE_READY', '')}; scope {row.get('SCOPE_CONFIDENCE', '')}."
        ),
        "Recovery Evidence": (
            f"Telemetry basis: {row.get('PROOF_REQUIRED', '')}. "
            "Track ticket/reference, rollback note, and post-change grant status."
        ),
        "Recovery Audit State": row.get("GRANT_REVIEW_READINESS", "Telemetry Pending"),
        "Recovery SLA Target Hours": 24 if str(severity).upper() in {"CRITICAL", "HIGH"} else 72,
        "Company": company,
        "Environment": row_environment,
    }


def _security_workflow_for(finding_type: str) -> str:
    value = str(finding_type or "").lower()
    if "shared" in value or "exposure" in value:
        return "Data sharing exposure"
    if "privileged" in value or "grant" in value:
        return "Privilege sprawl"
    return "Access posture"


def _security_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = exceptions.copy()
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["NEXT_WORKFLOW"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(_security_workflow_for)
    view["ENTITY_TYPE"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _security_action_for(value)[0])
    view["NEXT_ACTION"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _security_action_for(value)[1])
    return view.sort_values(["_RANK", "EVENT_COUNT", "LAST_SEEN"], ascending=[True, False, False]).drop(columns=["_RANK"], errors="ignore")


def _render_security_watch_floor(score: int, exceptions: pd.DataFrame, row) -> None:
    priority = _security_priority_view(exceptions).head(3)
    failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
    users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
    shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
    render_shell_snapshot((
        ("Priority Findings", f"{len(priority):,}"),
        ("Identity Signals", f"{failed_logins + users_without_mfa:,}"),
        ("Shared DBs", f"{shared_databases:,}"),
    ))
    if priority.empty:
        st.success("No urgent security findings crossed the brief thresholds.")
    else:
        first = priority.iloc[0]
        st.warning(
            f"First move: {first.get('FINDING_TYPE', 'Security finding')} for "
            f"{first.get('ENTITY', 'unknown')} -> {first.get('NEXT_ACTION', 'Review access telemetry.')}"
        )

    st.markdown("**Security Watch Floor**")
    if priority.empty:
        if shared_databases:
            st.caption("No urgent findings, but shared/imported database exposure exists. Review routes and consumers periodically.")
        else:
            st.caption("No immediate security cards. Use Access posture for audit telemetry or Data sharing exposure for external-consumer review.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Access posture")
        with cols[idx]:
            st.markdown(f"**{item.get('SEVERITY', 'Medium')}: {item.get('FINDING_TYPE', '')}**")
            st.caption(f"{item.get('ENTITY_TYPE', 'Access')}: {item.get('ENTITY', 'unknown')}")
            next_action = str(item.get("NEXT_ACTION", "") or "")
            proof_query = str(item.get("PROOF_QUERY", "") or "")
            help_text = " ".join(part for part in (next_action, proof_query) if part).strip()
            if st.button(
                f"Open {workflow}",
                key=f"security_watch_floor_{idx}_{workflow}",
                help=help_text or None,
                width="stretch",
            ):
                entity = str(item.get("ENTITY") or "").strip()
                if workflow == "Data sharing exposure":
                    if entity and entity.lower() != "unknown":
                        st.session_state["global_database"] = entity.split(".")[0]
                    for stale_key in ("ds_df_dt", "ds_df_shared_db"):
                        st.session_state.pop(stale_key, None)
                else:
                    if entity and entity.lower() != "unknown":
                        st.session_state["global_user"] = entity
                    for stale_key in (
                        "sec_df_login_sum",
                        "sec_df_failed_logins",
                        "sec_df_login_trend",
                        "sec_df_grants",
                        "sec_df_dom",
                        "sec_df_mfa",
                        "sec_df_exfil",
                        "sec_df_lin",
                        ):
                        st.session_state.pop(stale_key, None)
                _queue_security_workflow(workflow)


def _security_exception_strip_rows(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> list[dict]:
    expected_meta = _security_scope_meta(company, environment, days)
    loaded = (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, expected_meta)
    )
    if not loaded:
        return []
    priority = _security_priority_view(exceptions).head(4)
    if priority is not None and not priority.empty:
        rows = []
        for _, finding in priority.iterrows():
            rows.append({
                "severity": str(finding.get("SEVERITY") or "Medium"),
                "signal": str(finding.get("FINDING_TYPE") or "Security finding"),
                "entity": str(finding.get("ENTITY") or "unknown"),
                "detail": (
                    f"{safe_int(finding.get('EVENT_COUNT', 0)):,} event(s); "
                    f"{finding.get('NEXT_ACTION') or _security_action_for(finding.get('FINDING_TYPE', ''))[1]}"
                ),
                "route": str(finding.get("NEXT_WORKFLOW") or _security_workflow_for(finding.get("FINDING_TYPE", ""))),
            })
        return rows

    row = summary.iloc[0]
    failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
    failed_users = safe_int(row.get("FAILED_USERS", 0))
    users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
    recent_grants = safe_int(row.get("RECENT_GRANTS", 0))
    shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
    rows: list[dict] = []
    if users_without_mfa:
        rows.append({
            "severity": "High",
            "signal": "MFA gaps",
            "entity": "Users",
            "detail": f"{users_without_mfa:,} user(s) missing MFA signal in the selected scope.",
            "route": "Access posture",
        })
    if failed_logins:
        rows.append({
            "severity": "High" if failed_logins >= 25 or failed_users >= 5 else "Medium",
            "signal": "Failed logins",
            "entity": "Identity",
            "detail": f"{failed_logins:,} failed login(s) across {failed_users:,} user(s).",
            "route": "Access posture",
        })
    if recent_grants >= 25:
        rows.append({
            "severity": "Medium",
            "signal": "Grant-change volume",
            "entity": "Roles",
            "detail": f"{recent_grants:,} grant change(s) in the lookback window.",
            "route": "Privilege sprawl",
        })
    if shared_databases:
        rows.append({
            "severity": "Watch",
            "signal": "Shared data exposure",
            "entity": "Databases",
            "detail": f"{shared_databases:,} shared/imported database(s) need route and consumer validation.",
            "route": "Data sharing exposure",
        })
    return rows[:4]


def _render_security_exception_strip(rows: list[dict], *, loaded: bool = False) -> None:
    if not loaded:
        return
    st.markdown("**Exception Strip**")
    if not rows:
        st.success("No immediate security exceptions in the loaded summary.")
        return
    for row in rows[:4]:
        severity = str(row.get("severity") or "Watch")
        signal = str(row.get("signal") or "Security signal")
        entity = str(row.get("entity") or "Scope")
        detail = str(row.get("detail") or "")
        route = str(row.get("route") or "Security Monitoring / Access")
        if route == "Security Posture":
            route = "Security Monitoring / Access"
        if severity.lower() in {"critical", "high"}:
            st.warning(f"{severity}: {signal} - {entity}. {detail} Route: {route}.")
        else:
            st.info(f"{severity}: {signal} - {entity}. {detail} Route: {route}.")


def _security_action_brief(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> dict:
    expected_meta = _security_scope_meta(company, environment, days)
    loaded = (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, expected_meta)
    )
    if not loaded:
        if summary is not None and not getattr(summary, "empty", True):
            return {
                "state": "Stale",
                "headline": "Reload the security brief before acting.",
                "detail": "Loaded telemetry does not match the active company, environment, filters, or lookback.",
            }
        return {
            "state": "Fast Summary",
            "headline": "Security posture is ready for review.",
            "detail": "Fast security facts are attempted automatically; live account-history proof stays behind refresh.",
        }

    row = summary.iloc[0]
    failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
    users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
    recent_grants = safe_int(row.get("RECENT_GRANTS", 0))
    shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
    priority_count = len(_security_priority_view(exceptions).head(3))
    if users_without_mfa:
        return {
            "state": "MFA Watch",
            "headline": "Review users without MFA before calling posture clean.",
            "detail": f"{users_without_mfa:,} MFA gap(s), {failed_logins:,} failed login(s), and {recent_grants:,} recent grant change(s).",
        }
    if priority_count:
        return {
            "state": "Review",
            "headline": "Validate priority security exceptions.",
            "detail": f"{priority_count:,} priority finding(s) surfaced across access, login, grant, or sharing telemetry.",
        }
    if shared_databases:
        return {
            "state": "Exposure Check",
            "headline": "Validate shared database ownership and consumers.",
            "detail": f"{shared_databases:,} shared database(s) present in the selected window.",
        }
    return {
        "state": "Clear",
        "headline": "No immediate security blocker in the loaded brief.",
        "detail": f"{failed_logins:,} failed login(s) and {recent_grants:,} recent grant change(s) in scope.",
    }


def _render_security_action_brief(brief: dict) -> None:
    render_shell_status_strip(
        state=brief.get("state") or "Review",
        headline=brief.get("headline") or "Review security telemetry.",
        detail=brief.get("detail") or "",
    )


def _security_operating_snapshot(summary, meta: dict, company: str, environment: str, days: int) -> dict:
    loaded = (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, _security_scope_meta(company, environment, days))
    )
    if not loaded:
        return {
            "loaded": False,
            "scope": str(company or "All"),
            "window": f"{safe_int(days, 30):d}d",
            "evidence": "Fast facts pending",
            "focus": "Access",
        }
    row = summary.iloc[0]
    return {
        "loaded": True,
        "failed": safe_int(row.get("FAILED_LOGINS", 0)),
        "mfa_gaps": safe_int(row.get("USERS_WITHOUT_MFA", 0)),
        "grant_changes": safe_int(row.get("RECENT_GRANTS", 0)),
        "shared_databases": safe_int(row.get("SHARED_DATABASES", 0)),
    }


def _render_security_operating_snapshot(snapshot: dict) -> None:
    loaded = bool(snapshot.get("loaded"))
    if not loaded:
        render_shell_kpi_row((
            ("Scope", str(snapshot.get("scope") or "All")),
            ("Window", str(snapshot.get("window") or "30d")),
            ("Telemetry", str(snapshot.get("evidence") or "Fast facts pending")),
        ))
        return
    render_shell_kpi_row((
        ("Failed", f"{safe_int(snapshot.get('failed')):,}"),
        ("MFA Gaps", f"{safe_int(snapshot.get('mfa_gaps')):,}"),
        ("Grant Changes", f"{safe_int(snapshot.get('grant_changes')):,}"),
        ("Shared DBs", f"{safe_int(snapshot.get('shared_databases')):,}"),
    ))


def _security_command_lanes(snapshot: dict) -> list[dict[str, str]]:
    """Return Security Monitoring first-paint lanes."""
    if not snapshot.get("loaded"):
        return [
            {
                "label": "Failed logins",
                "value": "Pending",
                "state": "Identity",
                "detail": "Fast summary checks login spikes, unusual sources, and failed auth before live proof.",
            },
            {
                "label": "MFA gaps",
                "value": "Pending",
                "state": "Access",
                "detail": "Review active users without exposed MFA signal.",
            },
            {
                "label": "Grant changes",
                "value": "Pending",
                "state": "Privilege",
                "detail": "Admin grants, ownership, and future grants route here.",
            },
            {
                "label": "Shared data",
                "value": "Pending",
                "state": "Exposure",
                "detail": "Shares, external stages, and broad grants stay visible for review.",
            },
            {
                "label": "Policy posture",
                "value": "On demand",
                "state": "Security",
                "detail": "Masking, row access, network policy, and integration drift.",
            },
            {
                "label": "Sensitive access",
                "value": "On demand",
                "state": "Audit",
                "detail": "ACCESS_HISTORY and bytes-written signals identify risky access.",
            },
            {
                "label": "Access review",
                "value": "On demand",
                "state": "Review",
                "detail": "Privileged grants need review context before action.",
            },
            {
                "label": "Closure status",
                "value": "On demand",
                "state": "Audit",
                "detail": "Investigation notes, action status, and telemetry stay logged.",
            },
        ]
    return [
        {
            "label": "Failed logins",
            "value": f"{safe_int(snapshot.get('failed')):,}",
            "state": "Identity" if safe_int(snapshot.get("failed")) else "Clear",
            "detail": "Inspect spikes, service accounts, unusual sources, and business-hour drift.",
        },
        {
            "label": "MFA gaps",
            "value": f"{safe_int(snapshot.get('mfa_gaps')):,}",
            "state": "Access" if safe_int(snapshot.get("mfa_gaps")) else "Clear",
            "detail": "Prioritize active users and privileged roles.",
        },
        {
            "label": "Grant changes",
            "value": f"{safe_int(snapshot.get('grant_changes')):,}",
            "state": "Privilege" if safe_int(snapshot.get("grant_changes")) else "Clear",
            "detail": "Review ACCOUNTADMIN/SYSADMIN/SECURITYADMIN and ownership drift.",
        },
        {
            "label": "Shared data",
            "value": f"{safe_int(snapshot.get('shared_databases')):,}",
            "state": "Exposure" if safe_int(snapshot.get("shared_databases")) else "Clear",
            "detail": "Validate consumers, access purpose, and data classification.",
        },
        {
            "label": "Policy posture",
            "value": "Open workflow",
            "state": "Security",
            "detail": "Masking, row access, network policies, integrations, and shares.",
        },
        {
            "label": "Sensitive access",
            "value": "Open workflow",
            "state": "Audit",
            "detail": "ACCESS_HISTORY and output-volume anomalies need exact telemetry.",
        },
        {
            "label": "Access review",
            "value": "Open workflow",
            "state": "Review",
            "detail": "Use Privilege sprawl before revoking or narrowing grants.",
        },
        {
            "label": "Closure status",
            "value": "Queue/audit",
            "state": "Audit",
            "detail": "Every fix needs action status, before/after state, and telemetry.",
        },
    ]


def _queue_security_workflow(workflow: str) -> None:
    if workflow in WORKFLOWS:
        st.session_state["security_posture_requested_view"] = "Security Workflows"
        st.session_state["security_posture_requested_workflow"] = workflow
        st.rerun()


def _apply_queued_security_workflow() -> None:
    requested_view = st.session_state.pop("security_posture_requested_view", None)
    requested_workflow = st.session_state.pop("security_posture_requested_workflow", None)
    if requested_view in SECURITY_POSTURE_VIEWS:
        st.session_state["security_posture_view"] = requested_view
    if requested_workflow in WORKFLOWS:
        st.session_state["security_posture_workflow"] = requested_workflow


def _security_brief_workflow_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in SECURITY_BRIEF_WORKFLOWS:
        workflow = str(item["WORKFLOW"])
        rows.append({
            "WORKFLOW": workflow,
            "BUTTON_LABEL": str(item["BUTTON_LABEL"]),
            "DBA_MOVE": str(item["DBA_MOVE"]),
            "WHEN": str(item["WHEN"]),
            "SOURCES": WORKFLOW_DETAILS.get(workflow, "Security workflow detail"),
        })
    return rows


def _render_security_brief_launchpad() -> None:
    with st.expander("Security drilldowns", expanded=False):
        rows = _security_brief_workflow_rows()
        cols = st.columns(3)
        for col, row in zip(cols, rows):
            with col:
                st.markdown(f"**{row['WORKFLOW']}**")
                help_text = f"{row['DBA_MOVE']} When: {row['WHEN']}"
                if st.button(
                    row["BUTTON_LABEL"],
                    key=f"security_brief_{row['WORKFLOW']}",
                    help=help_text,
                    width="stretch",
                ):
                    _queue_security_workflow(row["WORKFLOW"])


def _paint_security_brief_chrome(
    brief_slot,
    snapshot_slot,
    exception_slot,
    summary,
    exceptions,
    meta: dict,
    company: str,
    environment: str,
    days: int,
) -> None:
    with brief_slot.container():
        _render_security_action_brief(
            _security_action_brief(summary, exceptions, meta, company, environment, days)
        )
    with snapshot_slot.container():
        snapshot = _security_operating_snapshot(summary, meta, company, environment, days)
        _render_security_operating_snapshot(
            snapshot
        )
        render_signal_lane_board(
            "Security Signal Summary",
            _security_command_lanes(snapshot),
            max_lanes=8,
        )
    if exception_slot is not None:
        loaded = (
            summary is not None
            and not getattr(summary, "empty", True)
            and _security_meta_matches(meta, _security_scope_meta(company, environment, days))
        )
        with exception_slot.container():
            _render_security_exception_strip(
                _security_exception_strip_rows(summary, exceptions, meta, company, environment, days),
                loaded=loaded,
            )


def _render_security_operability_fact_gate(company: str, environment: str, days: int) -> None:
    fact_meta_expected = _security_scope_meta(company, environment, days)
    fact_col, note_col = st.columns([1.3, 3.7])
    with fact_col:
        if st.button("Load Security Control Facts", key="security_operability_fact_load"):
            try:
                operability_sql = _security_operability_fact_sql(days, company, environment)
                st.session_state["security_operability_fact_sql"] = operability_sql
                st.session_state["security_operability_fact"] = run_query(
                    operability_sql,
                    ttl_key=f"security_operability_fact_{company}_{environment}_{days}",
                    tier="standard",
                    section="Security Posture",
                )
                st.session_state["security_operability_fact_meta"] = fact_meta_expected
                st.session_state.pop("security_operability_fact_error", None)
            except Exception as fact_exc:
                st.session_state["security_operability_fact"] = pd.DataFrame()
                st.session_state["security_operability_fact_error"] = format_snowflake_error(fact_exc)
    with note_col:
        st.caption(
            "Security control facts stay unloaded until you need blocker, closure, or telemetry detail."
        )

    operability_fact = st.session_state.get("security_operability_fact")
    if (
        operability_fact is not None
        and not _security_meta_matches(
            st.session_state.get("security_operability_fact_meta"),
            fact_meta_expected,
        )
    ):
        st.info("Loaded security control facts are stale for the active scope. Reload before acting.")
        return
    if operability_fact is not None and not operability_fact.empty:
        st.subheader("Security Control Summary")
        blocked_states = operability_fact["CONTROL_STATE"].astype(str).str.contains(
            "Blocked|Overdue|Required", case=False, na=False
        )
        render_shell_snapshot((
            ("Rows", f"{len(operability_fact):,}"),
            ("Blocked", f"{int(blocked_states.sum()):,}"),
            ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
            ("Verified", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
        ))
        render_priority_dataframe(
            operability_fact,
            title="Security blockers",
            priority_columns=[
                "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "SEVERITY",
                "FINDING_TYPE", "ENTITY", "ENTITY_TYPE", "ENVIRONMENT",
                "EVENT_ROWS", "REVIEW_ROWS", "REVIEW_BLOCKER_ROWS",
                "TICKET_REQUIRED_ROWS", "REVIEW_BY_REQUIRED_ROWS",
                "CAPABILITY_PROOF_ROWS", "NO_DATABASE_CONTEXT_ROWS",
                "OPEN_ACTIONS", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION",
                "VERIFIED_CLOSURES", "OWNER_APPROVAL_GAP_ROWS", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "REVIEW_BLOCKER_ROWS"],
            ascending=[True, False, False, False],
            raw_label="All security control rows",
            height=320,
        )
        with st.expander("Security Control Status", expanded=False):
            render_shell_snapshot((
                ("Control summary", "Ready"),
                ("Escalation route", "Review"),
                ("Closure status", "Required"),
                ("Execution", "Runbook only"),
            ))
    elif st.session_state.get("security_operability_fact_error"):
        defer_source_note(
            "Security control summary is not available yet. Ask the DBA team to enable the fast blocker surface."
        )


def _render_security_exceptions_gate(company: str, environment: str, days: int) -> None:
    exceptions_loaded = "security_posture_exceptions" in st.session_state
    exceptions = st.session_state.get("security_posture_exceptions")
    if not exceptions_loaded:
        load_col, note_col = st.columns([1.2, 3.8])
        with load_col:
            if st.button("Load Security Exceptions", key="security_posture_load_exceptions"):
                session = None
                try:
                    session = get_session()
                    proof_sql = st.session_state.get("security_posture_proof_sql") or {}
                    exceptions_sql = str(proof_sql.get("exceptions") or "")
                    preferred_source = str(st.session_state.get("security_posture_source") or "")
                    if not exceptions_sql:
                        _, exceptions_sql = _build_security_mart_brief_sql(session, days, company)
                        preferred_source = "Fast security summary; MFA/sharing: account history"
                    source_kind = "live" if "live" in preferred_source.lower() else "mart"
                    st.session_state["security_posture_exceptions"] = run_query(
                        exceptions_sql,
                        ttl_key=f"security_posture_exceptions_{source_kind}_{company}_{environment}_{days}",
                        tier="standard",
                    )
                    st.session_state["security_posture_exception_source"] = preferred_source
                    st.session_state.pop("security_posture_exception_error", None)
                    proof_sql["exceptions"] = exceptions_sql
                    st.session_state["security_posture_proof_sql"] = proof_sql
                except Exception as exc:
                    try:
                        session = session or get_session()
                        _, exceptions_sql = _build_security_summary_sql(session, days, company)
                        st.session_state["security_posture_exceptions"] = run_query(
                            exceptions_sql,
                            ttl_key=f"security_posture_exceptions_live_{company}_{environment}_{days}",
                            tier="standard",
                        )
                        st.session_state["security_posture_exception_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE"
                        st.session_state.pop("security_posture_exception_error", None)
                        proof_sql = st.session_state.get("security_posture_proof_sql") or {}
                        proof_sql["exceptions"] = exceptions_sql
                        st.session_state["security_posture_proof_sql"] = proof_sql
                        st.info(f"Security summary unavailable from the fast summary; used bounded live account history. {format_snowflake_error(exc)}")
                    except Exception as live_exc:
                        st.session_state.pop("security_posture_exceptions", None)
                        st.session_state["security_posture_exception_error"] = format_snowflake_error(live_exc)
        with note_col:
            st.caption("Security exceptions stay unloaded until you need user/IP, MFA, grant, or sharing detail rows.")
        if st.session_state.get("security_posture_exception_error"):
            st.warning(f"Unable to load security exceptions: {st.session_state['security_posture_exception_error']}")
        return

    if exceptions is not None and getattr(exceptions, "empty", True):
        st.success("No security exceptions crossed the loaded thresholds for this scope.")
    if st.session_state.get("security_posture_exception_source"):
        defer_source_note(str(st.session_state.get("security_posture_exception_source")))


def _build_security_brief_markdown(
    *,
    company: str,
    days: int,
    score: int,
    summary_row,
    exceptions: pd.DataFrame,
) -> str:
    failed_logins = safe_int(summary_row.get("FAILED_LOGINS", 0))
    failed_users = safe_int(summary_row.get("FAILED_USERS", 0))
    active_users = safe_int(summary_row.get("ACTIVE_USERS", 0))
    users_without_mfa = safe_int(summary_row.get("USERS_WITHOUT_MFA", 0))
    recent_grants = safe_int(summary_row.get("RECENT_GRANTS", 0))
    shared_databases = safe_int(summary_row.get("SHARED_DATABASES", 0))
    exception_lines = []
    if exceptions is not None and not exceptions.empty:
        for _, row in exceptions.head(10).iterrows():
            exception_lines.append(
                f"- {row.get('SEVERITY', 'Medium')}: {row.get('FINDING_TYPE', 'Security finding')} "
                f"for {row.get('ENTITY', 'Unknown')} ({safe_int(row.get('EVENT_COUNT', 0))} events)."
            )
    else:
        exception_lines.append("- No security exceptions crossed the configured thresholds.")
    lines = [
        f"# OVERWATCH Security Brief - {company}",
        "",
        f"Lookback window: {days} day(s).",
        f"Security state: {_security_rating(score)}.",
        "",
        "## Key Metrics",
        f"- Active users: {active_users:,}",
        f"- Failed logins: {failed_logins:,} across {failed_users:,} user(s)",
        f"- Users without MFA signal: {users_without_mfa:,}",
        f"- Recent active grants: {recent_grants:,}",
        f"- Shared/imported databases: {shared_databases:,}",
        "",
        "## Exceptions",
        *exception_lines,
        "",
        "## DBA Follow-Up",
        "- Validate failed-login spikes against IAM and network context.",
        "- Prioritize MFA gaps before lower-risk grant cleanup.",
        "- Review shared/imported databases with the data route and contract context.",
        "- Save material findings to the OVERWATCH Action Queue for status tracking.",
        "",
        "## Data Notes",
        "Company scope uses user/database naming where Snowflake does not expose direct company routing.",
    ]
    return "\n".join(lines)


def _build_security_summary_sql(session, days: int, company: str) -> tuple[str, str]:
    user_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ["HAS_MFA", "EXT_AUTHN_DUO", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
    ))
    mfa_count_expr = _mfa_count_expr(user_cols)
    mfa_gap_predicate = _mfa_gap_predicate(user_cols)
    mfa_proof = _mfa_proof_label(user_cols)
    password_count_expr = (
        "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_password)), FALSE) = TRUE)"
        if "HAS_PASSWORD" in user_cols else "NULL::NUMBER"
    )
    last_seen_expr = "u.last_success_login" if "LAST_SUCCESS_LOGIN" in user_cols else "u.created_on"
    user_filter_lh = get_user_filter_clause("lh.user_name")
    user_filter_u = get_user_filter_clause("u.name")
    user_filter_g = get_user_filter_clause("g.grantee_name")
    db_filter = get_db_filter_clause("d.database_name")
    object_grant_db_filter = get_db_filter_clause("gor.table_catalog")
    summary_sql = f"""
    WITH login_events AS (
        SELECT
            COUNT(*) AS login_events,
            COUNT_IF(lh.is_success = 'NO') AS failed_logins,
            COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.user_name, NULL)) AS failed_users,
            COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
        WHERE lh.event_timestamp >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_lh}
    ),
    users AS (
        SELECT
            COUNT(*) AS active_users,
            {mfa_count_expr} AS users_without_mfa,
            {password_count_expr} AS password_users
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
    ),
    recent_grants AS (
        SELECT COUNT(*) AS recent_grants
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
        WHERE g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_g}
    ),
    shared_dbs AS (
        SELECT COUNT(*) AS shared_databases
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT
        '{company}' AS company,
        login_events.login_events,
        login_events.failed_logins,
        login_events.failed_users,
        login_events.failed_ips,
        users.active_users,
        users.users_without_mfa,
        users.password_users,
        recent_grants.recent_grants AS recent_grants,
        shared_dbs.shared_databases
    FROM login_events, users, recent_grants, shared_dbs
    """
    exceptions_sql = f"""
    WITH failed_logins AS (
        SELECT
            'Failed Login' AS finding_type,
            IFF(COUNT(*) >= 25 OR COUNT(DISTINCT client_ip) >= 5, 'High', 'Medium') AS severity,
            user_name AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT client_ip) AS distinct_sources,
            MAX(event_timestamp) AS last_seen,
            'LOGIN_HISTORY failed login attempts by user/IP' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
        WHERE lh.event_timestamp >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND lh.is_success = 'NO'
          {user_filter_lh}
        GROUP BY user_name
        HAVING COUNT(*) >= 3
    ),
    mfa_gaps AS (
        SELECT
            'MFA Gap' AS finding_type,
            'High' AS severity,
            u.name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            COALESCE({last_seen_expr}, u.created_on) AS last_seen,
            '{mfa_proof}' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
          {mfa_gap_predicate}
    ),
    recent_grants AS (
        SELECT
            'Recent Grant' AS finding_type,
            IFF(COUNT(*) >= 10, 'Medium', 'Low') AS severity,
            g.grantee_name AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT g.role) AS distinct_sources,
            MAX(g.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_USERS active grants created recently' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
        WHERE g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_g}
        GROUP BY g.grantee_name
        HAVING COUNT(*) >= 3
    ),
    object_grants AS (
        SELECT
            'Object Grant' AS finding_type,
            IFF(COUNT(*) >= 10 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0, 'High', 'Medium') AS severity,
            COALESCE(gor.table_catalog || '.' || gor.table_schema || '.' || gor.name, gor.table_catalog, gor.name) AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT gor.grantee_name) AS distinct_sources,
            MAX(gor.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_ROLES object grants by database/schema/object' AS proof_query,
            gor.table_catalog AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
        WHERE gor.deleted_on IS NULL
          AND gor.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND gor.table_catalog IS NOT NULL
          {object_grant_db_filter}
        GROUP BY gor.table_catalog, gor.table_schema, gor.name
        HAVING COUNT(*) >= 3 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0
    ),
    shared_exposure AS (
        SELECT
            'Shared Database Exposure' AS finding_type,
            'Medium' AS severity,
            d.database_name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            d.created AS last_seen,
            'ACCOUNT_USAGE.DATABASES imported database/share metadata' AS proof_query,
            d.database_name AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT * FROM failed_logins
    UNION ALL
    SELECT * FROM mfa_gaps
    UNION ALL
    SELECT * FROM recent_grants
    UNION ALL
    SELECT * FROM object_grants
    UNION ALL
    SELECT * FROM shared_exposure
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        event_count DESC,
        last_seen DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def _build_security_mart_brief_sql(session, days: int, company: str) -> tuple[str, str]:
    """Build the security brief with mart-backed login aggregates and live security metadata."""
    user_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ["HAS_MFA", "EXT_AUTHN_DUO", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
    ))
    mfa_count_expr = _mfa_count_expr(user_cols)
    mfa_gap_predicate = _mfa_gap_predicate(user_cols)
    mfa_proof = _mfa_proof_label(user_cols)
    password_count_expr = (
        "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_password)), FALSE) = TRUE)"
        if "HAS_PASSWORD" in user_cols else "NULL::NUMBER"
    )
    last_seen_expr = "u.last_success_login" if "LAST_SUCCESS_LOGIN" in user_cols else "u.created_on"
    user_filter_lh = get_user_filter_clause("lh.user_name")
    user_filter_u = get_user_filter_clause("u.name")
    user_filter_g = get_user_filter_clause("g.grantee_name")
    db_filter = get_db_filter_clause("d.database_name")
    object_grant_db_filter = get_db_filter_clause("gor.table_catalog")
    login_table = mart_object_name("FACT_LOGIN_DAILY")
    grant_table = mart_object_name("FACT_GRANT_DAILY")
    login_company_filter = "" if str(company or "").upper() == "ALL" else f"AND lh.company = {sql_literal(company, 100)}"
    grant_company_filter = "" if str(company or "").upper() == "ALL" else f"AND g.company = {sql_literal(company, 100)}"
    company_label = sql_literal(company, 100)
    summary_sql = f"""
    WITH login_events AS (
        SELECT
            COALESCE(SUM(success_count), 0) + COALESCE(SUM(failure_count), 0) AS login_events,
            COALESCE(SUM(failure_count), 0) AS failed_logins,
            COUNT(DISTINCT IFF(COALESCE(failure_count, 0) > 0, lh.user_name, NULL)) AS failed_users,
            COUNT(DISTINCT IFF(COALESCE(failure_count, 0) > 0, lh.client_ip, NULL)) AS failed_ips
        FROM {login_table} lh
        WHERE lh.login_date >= DATEADD('day', -{int(days)}, CURRENT_DATE())
          {login_company_filter}
          {user_filter_lh}
    ),
    users AS (
        SELECT
            COUNT(*) AS active_users,
            {mfa_count_expr} AS users_without_mfa,
            {password_count_expr} AS password_users
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
    ),
    recent_grants AS (
        SELECT COALESCE(SUM(grant_count), 0) AS recent_grants
        FROM {grant_table} g
        WHERE 1 = 1
          {grant_company_filter}
          AND g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_g}
    ),
    shared_dbs AS (
        SELECT COUNT(*) AS shared_databases
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT
        {company_label} AS company,
        login_events.login_events,
        login_events.failed_logins,
        login_events.failed_users,
        login_events.failed_ips,
        users.active_users,
        users.users_without_mfa,
        users.password_users,
        recent_grants.recent_grants AS recent_grants,
        shared_dbs.shared_databases
    FROM login_events, users, recent_grants, shared_dbs
    """
    exceptions_sql = f"""
    WITH failed_logins AS (
        SELECT
            'Failed Login' AS finding_type,
            IFF(SUM(failure_count) >= 25 OR COUNT(DISTINCT client_ip) >= 5, 'High', 'Medium') AS severity,
            user_name AS entity,
            COALESCE(SUM(failure_count), 0) AS event_count,
            COUNT(DISTINCT client_ip) AS distinct_sources,
            MAX(login_date)::TIMESTAMP_NTZ AS last_seen,
            'FACT_LOGIN_DAILY failed login attempts by user/IP' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM {login_table} lh
        WHERE lh.login_date >= DATEADD('day', -{int(days)}, CURRENT_DATE())
          {login_company_filter}
          AND COALESCE(failure_count, 0) > 0
          {user_filter_lh}
        GROUP BY user_name
        HAVING COALESCE(SUM(failure_count), 0) >= 3
    ),
    mfa_gaps AS (
        SELECT
            'MFA Gap' AS finding_type,
            'High' AS severity,
            u.name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            COALESCE({last_seen_expr}, u.created_on) AS last_seen,
            '{mfa_proof}' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
          {mfa_gap_predicate}
    ),
    recent_grants AS (
        SELECT
            'Recent Grant' AS finding_type,
            IFF(SUM(grant_count) >= 10, 'Medium', 'Low') AS severity,
            g.grantee_name AS entity,
            COALESCE(SUM(grant_count), 0) AS event_count,
            COUNT(DISTINCT g.role_name) AS distinct_sources,
            MAX(g.created_on) AS last_seen,
            'FACT_GRANT_DAILY active grants created recently' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM {grant_table} g
        WHERE 1 = 1
          {grant_company_filter}
          AND g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_g}
        GROUP BY g.grantee_name
        HAVING COALESCE(SUM(grant_count), 0) >= 3
    ),
    object_grants AS (
        SELECT
            'Object Grant' AS finding_type,
            IFF(COUNT(*) >= 10 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0, 'High', 'Medium') AS severity,
            COALESCE(gor.table_catalog || '.' || gor.table_schema || '.' || gor.name, gor.table_catalog, gor.name) AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT gor.grantee_name) AS distinct_sources,
            MAX(gor.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_ROLES object grants by database/schema/object' AS proof_query,
            gor.table_catalog AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
        WHERE gor.deleted_on IS NULL
          AND gor.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND gor.table_catalog IS NOT NULL
          {object_grant_db_filter}
        GROUP BY gor.table_catalog, gor.table_schema, gor.name
        HAVING COUNT(*) >= 3 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0
    ),
    shared_exposure AS (
        SELECT
            'Shared Database Exposure' AS finding_type,
            'Medium' AS severity,
            d.database_name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            d.created AS last_seen,
            'ACCOUNT_USAGE.DATABASES imported database/share metadata' AS proof_query,
            d.database_name AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT * FROM failed_logins
    UNION ALL
    SELECT * FROM mfa_gaps
    UNION ALL
    SELECT * FROM recent_grants
    UNION ALL
    SELECT * FROM object_grants
    UNION ALL
    SELECT * FROM shared_exposure
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        event_count DESC,
        last_seen DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def _security_access_review_insert_sql(
    review: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
    snapshot_id: str = "",
) -> str:
    if review is None or review.empty:
        raise ValueError("Security access review snapshot has no rows to save.")
    view = (
        _build_security_access_review(review, environment)
        if "ACCESS_REVIEW_STATE" not in review.columns or "REVIEW_READINESS" not in review.columns
        else review.copy()
    )
    fqn = security_access_review_fqn()
    snap = snapshot_id or make_action_id(
        "Security Access Review Snapshot",
        company,
        f"{environment or 'ALL'}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    selects = []
    for _, row in view.head(200).iterrows():
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(row.get('ENVIRONMENT', _security_exception_environment(row, environment)), 100)} AS ENVIRONMENT, "
            f"{'TRUE' if bool(row.get('DATABASE_CONTEXT', _security_exception_has_database_context(row))) else 'FALSE'} AS DATABASE_CONTEXT, "
            f"{sql_literal(row.get('FINDING_TYPE', ''), 120)} AS FINDING_TYPE, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('ENTITY_TYPE', ''), 120)} AS ENTITY_TYPE, "
            f"{sql_literal(row.get('ENTITY', ''), 500)} AS ENTITY, "
            f"{safe_int(row.get('EVENT_COUNT'))}::NUMBER AS EVENT_COUNT, "
            f"{safe_int(row.get('DISTINCT_SOURCES'))}::NUMBER AS DISTINCT_SOURCES, "
            f"{sql_literal(row.get('LAST_SEEN', ''), 100)} AS LAST_SEEN, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('APPROVER', ''), 200)} AS APPROVER, "
            f"{sql_literal(row.get('OWNER_APPROVAL_STATUS', ''), 40)} AS OWNER_APPROVAL_STATUS, "
            f"{sql_literal(row.get('ACCESS_REVIEW_STATE', ''), 160)} AS ACCESS_REVIEW_STATE, "
            f"{sql_literal(row.get('ROLE_CAPABILITY_STATE', ''), 200)} AS ROLE_CAPABILITY_STATE, "
            f"{sql_literal(row.get('TICKET_REQUIRED', ''), 20)} AS TICKET_REQUIRED, "
            f"{sql_literal(row.get('REVIEW_BY_REQUIRED', ''), 20)} AS REVIEW_BY_REQUIRED, "
            f"{sql_literal(row.get('PROOF_REQUIRED', ''), 2000)} AS PROOF_REQUIRED, "
            f"{sql_literal(row.get('VERIFICATION_QUERY', ''), 8000)} AS VERIFICATION_QUERY, "
            f"{sql_literal(row.get('ACCESS_TICKET_ID', ''), 200)} AS ACCESS_TICKET_ID, "
            f"{sql_literal(row.get('REVIEW_BY_DATE', ''), 100)} AS REVIEW_BY_DATE, "
            f"{sql_literal(row.get('IAM_APPROVAL_STATE', row.get('OWNER_APPROVAL_STATUS', 'Requested')), 120)} AS IAM_APPROVAL_STATE, "
            f"{sql_literal(row.get('REVIEW_READINESS', ''), 100)} AS REVIEW_READINESS, "
            f"{sql_literal(row.get('REVIEW_BLOCKERS', ''), 2000)} AS REVIEW_BLOCKERS, "
            f"{safe_int(row.get('REVIEW_SLA_HOURS'))}::NUMBER AS REVIEW_SLA_HOURS, "
            f"{sql_literal(row.get('VERIFICATION_STATUS', 'Pending'), 80)} AS VERIFICATION_STATUS, "
            f"{sql_literal(row.get('VERIFICATION_RESULT', ''), 4000)} AS VERIFICATION_RESULT, "
            f"{sql_literal(row.get('CONTROL_READINESS', row.get('REVIEW_READINESS', '')), 100)} AS CONTROL_READINESS, "
            f"{sql_literal(row.get('CONTROL_BLOCKERS', row.get('REVIEW_BLOCKERS', '')), 2000)} AS CONTROL_BLOCKERS, "
            f"{sql_literal(row.get('NEXT_CONTROL_ACTION', ''), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{sql_literal(row.get('NEXT_ACTION', ''), 4000)} AS NEXT_ACTION, "
            f"{sql_literal(row.get('PROOF_QUERY', ''), 4000)} AS PROOF_QUERY, "
            f"{sql_literal(source, 500)} AS SOURCE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, DATABASE_CONTEXT,
    FINDING_TYPE, SEVERITY, ENTITY_TYPE, ENTITY, EVENT_COUNT, DISTINCT_SOURCES,
    LAST_SEEN, OWNER, ESCALATION_TARGET, OWNER_SOURCE, APPROVER,
    OWNER_APPROVAL_STATUS, ACCESS_REVIEW_STATE, ROLE_CAPABILITY_STATE,
    TICKET_REQUIRED, REVIEW_BY_REQUIRED, PROOF_REQUIRED, VERIFICATION_QUERY,
    ACCESS_TICKET_ID, REVIEW_BY_DATE, IAM_APPROVAL_STATE, REVIEW_READINESS,
    REVIEW_BLOCKERS, REVIEW_SLA_HOURS, VERIFICATION_STATUS, VERIFICATION_RESULT,
    CONTROL_READINESS, CONTROL_BLOCKERS, NEXT_CONTROL_ACTION,
    NEXT_ACTION, PROOF_QUERY, SOURCE
)
{" UNION ALL ".join(selects)}""".strip()


def _security_access_review_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = security_access_review_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        # Login-only and account-role rows have no database context; keep them visible under environment filters.
        where.append(f"(ENVIRONMENT = {sql_literal(env_value, 100)} OR DATABASE_CONTEXT = FALSE)")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    FINDING_TYPE,
    SEVERITY,
    OWNER,
    ESCALATION_TARGET,
    COUNT(*) AS REVIEW_ROWS,
    SUM(EVENT_COUNT) AS TOTAL_EVENTS,
    COUNT_IF(TICKET_REQUIRED = 'Yes') AS TICKET_REQUIRED_ROWS,
    COUNT_IF(REVIEW_BY_REQUIRED = 'Yes') AS REVIEW_BY_REQUIRED_ROWS,
    COUNT_IF(ROLE_CAPABILITY_STATE ILIKE '%required%') AS CAPABILITY_PROOF_ROWS,
    COUNT_IF(DATABASE_CONTEXT = FALSE) AS NO_DATABASE_CONTEXT_ROWS,
    COUNT_IF(REVIEW_READINESS ILIKE '%Blocked%') AS REVIEW_BLOCKER_ROWS,
    COUNT_IF(VERIFICATION_STATUS = 'Verified' AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15) AS VERIFIED_REVIEW_ROWS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(ACCESS_REVIEW_STATE, SNAPSHOT_TS) AS LAST_ACCESS_REVIEW_STATE,
    MAX_BY(REVIEW_READINESS, SNAPSHOT_TS) AS LAST_REVIEW_READINESS,
    MAX_BY(CONTROL_READINESS, SNAPSHOT_TS) AS LAST_CONTROL_READINESS,
    MAX_BY(ROLE_CAPABILITY_STATE, SNAPSHOT_TS) AS LAST_ROLE_CAPABILITY_STATE,
    MAX_BY(PROOF_REQUIRED, SNAPSHOT_TS) AS LAST_PROOF_REQUIRED,
    MAX_BY(NEXT_CONTROL_ACTION, SNAPSHOT_TS) AS NEXT_CONTROL_ACTION
FROM {fqn}
WHERE {where_clause}
GROUP BY FINDING_TYPE, SEVERITY, OWNER, ESCALATION_TARGET
ORDER BY
    REVIEW_BLOCKER_ROWS DESC,
    TICKET_REQUIRED_ROWS DESC,
    CAPABILITY_PROOF_ROWS DESC,
    TOTAL_EVENTS DESC,
    LAST_SNAPSHOT_TS DESC
LIMIT 100""".strip()


def _security_action_queue_closure_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"
    where = [
        "SOURCE IN ('Security Posture - Security Brief', 'Security Posture - Privileged Grant Status')",
        f"COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_TIMESTAMP())",
    ]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
WITH scoped_actions AS (
    SELECT
        COALESCE(CATEGORY, 'Security') AS CATEGORY,
        COALESCE(ENTITY_TYPE, 'Security Finding') AS ENTITY_TYPE,
        COALESCE(ENTITY_NAME, 'Unknown') AS ENTITY,
        COALESCE(OWNER, '') AS OWNER,
        COALESCE(APPROVER, '') AS APPROVER,
        COALESCE(STATUS, 'New') AS STATUS,
        COALESCE(SEVERITY, 'Medium') AS SEVERITY,
        COALESCE(TICKET_ID, '') AS TICKET_ID,
        DUE_DATE,
        COALESCE(VERIFICATION_STATUS, '') AS VERIFICATION_STATUS,
        COALESCE(VERIFICATION_QUERY, PROOF_QUERY, '') AS VERIFICATION_QUERY,
        COALESCE(VERIFICATION_RESULT, '') AS VERIFICATION_RESULT,
        COALESCE(OWNER_APPROVAL_STATUS, '') AS OWNER_APPROVAL_STATUS,
        COALESCE(RECOVERY_SLA_STATE, '') AS RECOVERY_SLA_STATE,
        COALESCE(RECOVERY_EVIDENCE, '') AS RECOVERY_EVIDENCE,
        COALESCE(UPDATED_AT, CREATED_AT) AS LAST_ACTIVITY_TS
    FROM {fqn}
    WHERE {where_clause}
),
rollup AS (
    SELECT
        CATEGORY,
        ENTITY_TYPE,
        ENTITY,
        MAX_BY(OWNER, LAST_ACTIVITY_TS) AS OWNER,
        MAX_BY(APPROVER, LAST_ACTIVITY_TS) AS APPROVER,
        COUNT(*) AS TOTAL_ACTIONS,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
        COUNT_IF(UPPER(STATUS) = 'FIXED') AS FIXED_ACTIONS,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND UPPER(VERIFICATION_STATUS) = 'VERIFIED'
            AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15
        ) AS VERIFIED_CLOSURES,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND (
                UPPER(VERIFICATION_STATUS) <> 'VERIFIED'
                OR LENGTH(TRIM(VERIFICATION_RESULT)) < 15
            )
        ) AS FIXED_WITHOUT_VERIFICATION,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
        COUNT_IF(UPPER(OWNER) IN ('', 'SECURITY/DBA', 'DBA', 'UNKNOWN', 'N/A')) AS OWNER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(STATUS) = 'FIXED'
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) < 15
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY CATEGORY, ENTITY_TYPE, ENTITY
)
SELECT
    CATEGORY,
    ENTITY_TYPE,
    ENTITY,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Overdue closure'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Status needs telemetry'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Telemetry closure'
        ELSE 'No recent action'
    END AS CLOSURE_READINESS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 0
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 1
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 2
        WHEN OPEN_ACTIONS > 0 THEN 3
        WHEN VERIFIED_CLOSURES > 0 THEN 8
        ELSE 9
    END AS CLOSURE_RANK,
    OWNER,
    APPROVER,
    TOTAL_ACTIONS,
    OPEN_ACTIONS,
    FIXED_ACTIONS,
    VERIFIED_CLOSURES,
    FIXED_WITHOUT_VERIFICATION,
    OVERDUE_OPEN,
    OWNER_GAP_ROWS,
    TICKET_GAP_ROWS,
    APPROVER_GAP_ROWS,
    VERIFICATION_QUERY_GAP_ROWS,
    OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_DUE_DATE,
    LAST_STATUS,
    LAST_SEVERITY,
    LAST_ACTIVITY_TS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate the security route and ticket before lower-risk access cleanup.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Reopen the security action or wait for telemetry to confirm closure.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete route, ticket, reviewer, and telemetry metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open security action and retain IAM/Snowflake telemetry.'
        ELSE 'Keep closure status visible for audit review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _security_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read security review and action-queue control blockers from the fast summary."""
    table = security_operability_fact_fqn()
    where = [f"SNAPSHOT_DATE >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_DATE())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
SELECT
    SNAPSHOT_DATE,
    COMPANY,
    ENVIRONMENT,
    CONTROL_SOURCE,
    FINDING_TYPE,
    ENTITY,
    ENTITY_TYPE,
    SEVERITY,
    CONTROL_STATE,
    CONTROL_RANK,
    EVENT_ROWS,
    REVIEW_ROWS,
    REVIEW_BLOCKER_ROWS,
    TICKET_REQUIRED_ROWS,
    REVIEW_BY_REQUIRED_ROWS,
    CAPABILITY_PROOF_ROWS,
    NO_DATABASE_CONTEXT_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    REVIEW_BLOCKER_ROWS DESC,
    EVENT_ROWS DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _security_control_board(
    access_review: pd.DataFrame,
    closure: pd.DataFrame | None = None,
    trend: pd.DataFrame | None = None,
    environment: str = "ALL",
) -> pd.DataFrame:
    """Combine current findings, closure state, and snapshot trend into one DBA control board."""
    if access_review is None or access_review.empty:
        return pd.DataFrame()

    base = (
        _build_security_access_review(access_review, environment)
        if "REVIEW_READINESS" not in access_review.columns
        else access_review.copy()
    )
    base.columns = [str(col).upper() for col in base.columns]

    closure_view = pd.DataFrame() if closure is None else closure.copy()
    if not closure_view.empty:
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
    trend_view = pd.DataFrame() if trend is None else trend.copy()
    if not trend_view.empty:
        trend_view.columns = [str(col).upper() for col in trend_view.columns]

    closure_by_entity = {
        str(row.get("ENTITY") or "").upper(): row
        for _, row in closure_view.iterrows()
    } if not closure_view.empty else {}
    trend_by_finding = {
        str(row.get("FINDING_TYPE") or "").upper(): row
        for _, row in trend_view.iterrows()
    } if not trend_view.empty else {}

    rows: list[dict] = []
    for _, row in base.iterrows():
        entity = str(row.get("ENTITY") or "")
        finding_type = str(row.get("FINDING_TYPE") or "")
        close = closure_by_entity.get(entity.upper(), {})
        trend_row = trend_by_finding.get(finding_type.upper(), {})
        review_readiness = str(row.get("REVIEW_READINESS") or row.get("CONTROL_READINESS") or "")
        review_rank = safe_int(row.get("REVIEW_RANK", 4))
        open_actions = safe_int(close.get("OPEN_ACTIONS", 0))
        overdue = safe_int(close.get("OVERDUE_OPEN", 0))
        fixed_without_verification = safe_int(close.get("FIXED_WITHOUT_VERIFICATION", 0))
        recovery_risk = safe_int(close.get("RECOVERY_RISK_ROWS", 0))
        verified = safe_int(close.get("VERIFIED_CLOSURES", 0))
        closure_rank = safe_int(close.get("CLOSURE_RANK", 9))
        review_rows = safe_int(trend_row.get("REVIEW_ROWS", 0))
        blocker_rows = safe_int(trend_row.get("REVIEW_BLOCKER_ROWS", 0))
        severity = str(row.get("SEVERITY") or "Medium")

        if overdue:
            state, rank = "Closure Overdue", 0
            blockers = str(close.get("CLOSURE_READINESS") or "overdue action")
            next_action = str(close.get("NEXT_ACTION") or "Escalate route and ticket before accepting the security control.")
        elif fixed_without_verification or recovery_risk or closure_rank in {1, 2}:
            state, rank = "Closure Status Pending", 1
            blockers = str(close.get("CLOSURE_READINESS") or "closure status gap")
            next_action = str(close.get("NEXT_ACTION") or "Reopen the security action or wait for telemetry to confirm closure.")
        elif "BLOCKED" in review_readiness.upper():
            state, rank = review_readiness, min(review_rank, 3)
            blockers = str(row.get("REVIEW_BLOCKERS") or row.get("CONTROL_BLOCKERS") or "review metadata gap")
            next_action = str(row.get("NEXT_CONTROL_ACTION") or "Complete review metadata before queueing closure.")
        elif open_actions > 0:
            state, rank = "Work Open Action", 4
            blockers = "Open action queue item"
            next_action = str(close.get("NEXT_ACTION") or "Work open security action and retain IAM/Snowflake telemetry.")
        elif severity.upper() in {"CRITICAL", "HIGH"} and not open_actions and not verified:
            state, rank = "Queue Required", 5
            blockers = "High-risk finding is not represented by an open action"
            next_action = "Save this security finding to the Action Queue with assignment, ticket/reference, and verification context."
        elif blocker_rows or review_rows > 1:
            state, rank = "Recurring Access Watch", 6
            blockers = f"{review_rows:,} snapshot row(s), {blocker_rows:,} blocker row(s)"
            next_action = "Review repeated security snapshots and convert recurring access risk into a durable control."
        elif verified:
            state, rank = "Verified Closure", 8
            blockers = "None"
            next_action = "Keep closure status visible for audit review."
        else:
            state, rank = "Controlled", 9
            blockers = str(row.get("CONTROL_BLOCKERS") or "None")
            next_action = str(row.get("NEXT_CONTROL_ACTION") or "No immediate DBA action for this finding.")

        rows.append({
            "CONTROL_STATE": state,
            "CONTROL_RANK": rank,
            "SEVERITY": severity,
            "FINDING_TYPE": finding_type,
            "ENTITY": entity,
            "ENTITY_TYPE": row.get("ENTITY_TYPE", ""),
            "ENVIRONMENT": row.get("ENVIRONMENT", ""),
            "DATABASE_CONTEXT": bool(row.get("DATABASE_CONTEXT")),
            "SCOPE_CONFIDENCE": row.get("SCOPE_CONFIDENCE", ""),
            "OWNER": row.get("OWNER", close.get("OWNER", "")),
            "ESCALATION_TARGET": row.get("ESCALATION_TARGET", ""),
            "APPROVER": row.get("APPROVER", close.get("APPROVER", "")),
            "REVIEW_READINESS": review_readiness,
            "REVIEW_BLOCKERS": row.get("REVIEW_BLOCKERS", ""),
            "ACCESS_TICKET_ID": row.get("ACCESS_TICKET_ID", ""),
            "REVIEW_BY_DATE": row.get("REVIEW_BY_DATE", ""),
            "IAM_APPROVAL_STATE": row.get("IAM_APPROVAL_STATE", ""),
            "REVIEW_SLA_HOURS": safe_int(row.get("REVIEW_SLA_HOURS", 0)),
            "OPEN_ACTIONS": open_actions,
            "OVERDUE_OPEN": overdue,
            "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
            "VERIFIED_CLOSURES": verified,
            "REVIEW_SNAPSHOTS": review_rows,
            "CONTROL_BLOCKERS": blockers,
            "NEXT_CONTROL_ACTION": next_action,
        })

    return pd.DataFrame(rows).sort_values(
        [
            "CONTROL_RANK",
            "OVERDUE_OPEN",
            "FIXED_WITHOUT_VERIFICATION",
            "OPEN_ACTIONS",
            "SEVERITY",
            "FINDING_TYPE",
            "ENTITY",
        ],
        ascending=[True, False, False, False, True, True, True],
    ).reset_index(drop=True)


def _save_security_access_review_snapshot(
    session,
    review: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
) -> None:
    try:
        session.sql(build_security_access_review_ddl()).collect()
        for migration_sql in build_security_access_review_migration_sql():
            session.sql(migration_sql).collect()
        session.sql(_security_access_review_insert_sql(
            review,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the Security Access Review snapshot for route, ticket, and telemetry tracking.")
    except Exception as exc:
        st.error(f"Could not save Security Access Review snapshot: {format_snowflake_error(exc)}")
        st.info("Security access review history is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _queue_security_exceptions(session, exceptions: pd.DataFrame) -> None:
    if exceptions is None or exceptions.empty:
        st.info("No security exceptions to queue.")
        return
    company = get_active_company()
    environment = get_active_environment()
    review = _build_security_access_review(exceptions, environment)
    actions = []
    for _, row in review.head(100).iterrows():
        finding_type = str(row.get("FINDING_TYPE") or "Security Finding")
        entity = str(row.get("ENTITY") or "Unknown")
        severity = str(row.get("SEVERITY") or "Medium")
        event_count = safe_int(row.get("EVENT_COUNT", 0))
        finding = f"{finding_type}: {entity} has {event_count} event(s) requiring review"
        entity_type, action, generated_sql = _security_action_for(finding_type)
        verification_query = str(row.get("VERIFICATION_QUERY") or _security_exception_verification_sql(row))
        actions.append({
            "Action ID": make_action_id("Security Posture", entity, finding),
            "Source": "Security Posture - Security Brief",
            "Severity": severity,
            "Category": "Security",
            "Entity Type": entity_type,
            "Entity": entity,
            "Owner": row.get("OWNER", "Security/DBA"),
            "Owner Email": row.get("OWNER_EMAIL", ""),
            "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
            "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
            "Review Group": row.get("ESCALATION_TARGET", row.get("APPROVER", "Security")),
            "Escalation Target": row.get("ESCALATION_TARGET", "DBA Lead"),
            "Owner Source": row.get("OWNER_SOURCE", ""),
            "Owner Evidence": row.get("OWNER_EVIDENCE", ""),
            "Finding": finding,
            "Action": (
                f"{action} Review with {row.get('APPROVER', 'Security')} is required; "
                f"telemetry basis: {row.get('PROOF_REQUIRED', 'security telemetry and status')}."
            ),
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "\n".join([
                "-- Review-only security/access record. Do not revoke, disable, or grant access from this row.",
                generated_sql,
                f"-- Access review state: {row.get('ACCESS_REVIEW_STATE', '')}.",
                f"-- Role/capability state: {row.get('ROLE_CAPABILITY_STATE', '')}.",
                f"-- Environment context: {row.get('ENVIRONMENT', _security_exception_environment(row, environment))}.",
            ]),
            "Proof Query": verification_query,
            "Verification Query": verification_query,
            "Verification Status": row.get("VERIFICATION_STATUS", "Pending"),
            "Ticket ID": row.get("ACCESS_TICKET_ID", ""),
            "Reviewer": row.get("APPROVER", "Security"),
            "Review Status": row.get("IAM_REVIEW_STATE", "Requested"),
            "Review Note": (
                f"{row.get('ACCESS_REVIEW_STATE', '')}; status {row.get('REVIEW_READINESS', '')}; "
                f"blockers {row.get('REVIEW_BLOCKERS', '')}; escalation {row.get('ESCALATION_TARGET', 'DBA Lead')}; "
                f"ticket required {row.get('TICKET_REQUIRED', 'Yes')}; review-by required {row.get('REVIEW_BY_REQUIRED', 'Yes')}."
            ),
            "Recovery Evidence": (
                f"Telemetry basis: {row.get('PROOF_REQUIRED', '')}. "
                f"Role capability: {row.get('ROLE_CAPABILITY_STATE', '')}. "
                f"Review SLA hours: {safe_int(row.get('REVIEW_SLA_HOURS', 0))}."
            ),
            "Recovery Audit State": row.get("CONTROL_READINESS", "Security Review Telemetry Pending"),
            "Recovery SLA Target Hours": safe_int(row.get("REVIEW_SLA_HOURS", 24 if severity.upper() in {"CRITICAL", "HIGH"} else 72)),
            "Company": company,
            "Environment": row.get("ENVIRONMENT", _security_exception_environment(row, environment)),
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} security exceptions to the action queue.")
    except Exception as e:
        st.error(f"Could not save security exceptions: {format_snowflake_error(e)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _queue_privileged_grant_actions(
    session,
    grants: pd.DataFrame,
    *,
    company: str,
    environment: str,
) -> None:
    if grants is None or grants.empty:
        st.info("No privileged grant rows to queue.")
        return
    actionable = grants[
        grants.get("GRANT_REVIEW_READINESS", pd.Series(dtype=str)).astype(str).isin([
            "Assignment Blocked",
            "Telemetry Pending",
            "Review Ready",
        ])
    ].copy()
    if actionable.empty:
        st.info("No privileged grant rows need action-queue tracking for the selected scope.")
        return
    actions = [
        _privileged_grant_action_payload(row, company=company, environment=environment)
        for _, row in actionable.head(100).iterrows()
    ]
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} privileged grant review rows to the action queue.")
    except Exception as exc:
        st.error(f"Could not save privileged grant actions: {format_snowflake_error(exc)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _render_privileged_grant_readiness(
    company: str,
    environment: str,
    days: int,
    *,
    as_expander: bool = True,
    expanded: bool = False,
    title: str = "Privileged Grant Status",
    load_label: str = "Load Privileged Grant Status",
    load_key: str = "security_priv_grant_load",
) -> None:
    def _body() -> None:
        st.caption(
            "Reviews account-level admin role grants and database-scoped object privileges before DBA grant/revoke work. "
            "Account-role grants stay visible under PROD/DEV filters because they have no database context."
        )
        grant_days = day_window_selectbox(
            "Privileged grant lookback",
            key="security_priv_grant_days",
            default=max(7, int(days or 30)),
        )
        if st.button(load_label, key=load_key, type="primary" if not as_expander else "secondary"):
            try:
                grant_sql = _security_privileged_grant_review_sql(grant_days, company, environment)
                grant_rows = run_query(
                    grant_sql,
                    ttl_key=f"security_privileged_grants_{company}_{environment}_{grant_days}",
                    tier="standard",
                    section="Security Posture",
                )
                st.session_state["security_privileged_grants"] = _annotate_security_privileged_grant_readiness(grant_rows)
                st.session_state["security_privileged_grants_sql"] = grant_sql
                st.session_state["security_privileged_grants_meta"] = _security_scope_meta(
                    company, environment, grant_days
                )
            except Exception as exc:
                st.session_state["security_privileged_grants"] = pd.DataFrame()
                st.warning(f"Privileged grant status unavailable: {format_snowflake_error(exc)}")

        grants = st.session_state.get("security_privileged_grants")
        if grants is None:
            st.info("Load this before granting, revoking, or narrowing high-risk roles and object privileges.")
            with st.expander("Privileged Grant Status", expanded=False):
                render_shell_snapshot((
                    ("Scope", "On demand"),
                    ("Escalation route", "Required"),
                    ("Review", "Required"),
                    ("Execution", "Runbook only"),
                ))
            return
        if not _security_meta_matches(
            st.session_state.get("security_privileged_grants_meta"),
            _security_scope_meta(company, environment, grant_days),
        ):
            st.info("Loaded privileged grant status is stale for the active scope. Reload before granting, revoking, or narrowing access.")
            with st.expander("Privileged Grant Status", expanded=False):
                render_shell_snapshot((
                    ("Scope", "Stale"),
                    ("Refresh", "Required"),
                    ("Approval", "Required"),
                    ("Execution", "Runbook only"),
                ))
            return
        if grants.empty:
            st.success("No privileged grant rows found for the selected scope and lookback.")
            return

        summary = _privilege_sprawl_summary(grants)
        blocked = grants[grants["GRANT_REVIEW_READINESS"] == "Assignment Blocked"]
        approval = grants[grants["GRANT_REVIEW_READINESS"] == "Telemetry Pending"]
        account_scope = grants[~grants["DATABASE_CONTEXT"]]
        render_shell_snapshot((
            ("Privileged Grants", f"{len(grants):,}"),
            ("Telemetry", f"{len(approval):,}"),
            ("Assignment Blocked", f"{len(blocked):,}"),
            ("Account Scope", f"{len(account_scope):,}"),
        ))
        if not as_expander:
            render_shell_snapshot((
                ("Tier 0", f"{summary['tier0']:,}"),
                ("Admin Roles", f"{summary['admin_role_grants']:,}"),
                ("Grant Option", f"{summary['ownership_or_grant_option']:,}"),
                ("Stale Admin", f"{summary['stale_admin_grants']:,}"),
            ))

        render_priority_dataframe(
            grants,
            title="Privileged grant review before access changes",
            priority_columns=[
                "SEVERITY", "GRANT_REVIEW_READINESS", "GRANT_REVIEW_STATE",
                "FINDING_TYPE", "ENTITY", "ROLE_NAME", "PRIVILEGE", "GRANT_OPTION",
                "OBJECT_NAME", "DATABASE_NAME", "GRANT_AGE_DAYS",
                "ENVIRONMENT", "SCOPE_CONFIDENCE", "OWNER", "OWNER_ROUTE_READY",
                "ONCALL_PRIMARY", "APPROVAL_GROUP", "GRANTED_BY", "CREATED_ON",
                "PROOF_REQUIRED", "NEXT_GRANT_ACTION",
            ],
            sort_by=["GRANT_REVIEW_RANK", "SEVERITY", "CREATED_ON"],
            ascending=[True, True, False],
            raw_label="All privileged grant status rows",
            height=320,
        )
        if st.button("Save Privileged Grants to Action Queue", key="security_priv_grants_queue"):
            _queue_privileged_grant_actions(get_session(), grants, company=company, environment=environment)
        with st.expander("Privileged Grant Status", expanded=False):
            render_shell_snapshot((
                ("Grant review", "Ready"),
                ("Telemetry", "Required"),
                ("Queue action", "Available"),
                ("Execution", "Runbook only"),
            ))

    if as_expander:
        with st.expander(title, expanded=expanded):
            _body()
    else:
        st.markdown(f"**{title}**")
        _body()


def _render_privilege_sprawl_workflow(company: str, environment: str, days: int) -> None:
    _render_privileged_grant_readiness(
        company,
        environment,
        days,
        as_expander=False,
        title="Privilege Sprawl",
        load_label="Load Privilege Sprawl",
        load_key="security_privilege_sprawl_load",
    )


def _render_security_source_health(company: str, environment: str) -> None:
    source_health = _security_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Security Data Health", expanded=False):
        current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        fast_summary = int(
            source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["CONFIDENCE"].astype(str).str.contains("Fast summary", case=False, regex=False)
        ].shape[0]
        )
        render_shell_snapshot((
            ("Current Surfaces", f"{current}/{len(source_health)}"),
            ("Fast Summary", f"{fast_summary:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        defer_source_note(
            "Use this before acting on access findings. Login-only telemetry keeps account scope, while database-scoped "
            "telemetry follows the selected company and environment."
        )
        render_priority_dataframe(
            source_health,
            title="Security telemetry freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All security data-health rows",
            height=300,
        )


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    if st.session_state.get("_security_posture_brief_first_version") != 1:
        if (
            st.session_state.get("exceptions_only_mode")
            and st.session_state.get("security_posture_view") == "Access Workflows"
        ):
            st.session_state["security_posture_view"] = "Security Brief"
        st.session_state["_security_posture_brief_first_version"] = 1
    if st.session_state.get("exceptions_only_mode") and "security_posture_workflow" not in st.session_state:
        st.session_state["security_posture_workflow"] = "Access posture"
    if st.session_state.get("exceptions_only_mode") and "security_posture_view" not in st.session_state:
        st.session_state["security_posture_view"] = "Security Brief"
    if st.session_state.get("security_posture_view") not in SECURITY_POSTURE_VIEWS:
        st.session_state["security_posture_view"] = SECURITY_POSTURE_VIEWS[0]
    _apply_queued_security_workflow()
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="exact",
        scope_note="Company scope uses user/database naming where Snowflake does not expose company routing.",
    )
    render_operator_briefing(
        [
            ("First move", "Separate noisy login volume from real identity or access risk."),
            ("Telemetry", "Tie users, IPs, grants, MFA posture, and shared data to source detail."),
            ("Control", "Escalate to IAM, revoke/narrow access, or validate business route."),
            ("Output", "Produce an audit posture brief with routes and remediation status."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Landing default: prioritize failed logins, MFA gaps, risky grants, and external exposure.")
    render_workflow_guide(
        "Start with identity/access posture, open privilege sprawl for high-risk grants, "
        "then inspect data sharing when the question is external exposure or audit telemetry.",
        [
            ("Login failures, MFA, grants, or risky access", "Use Access posture."),
            ("Admin roles, ownership, grant option, or route blockers", "Use Privilege sprawl."),
            ("External consumers or shared data exposure", "Use Data sharing exposure."),
        ],
    )

    days = day_window_selectbox(
        "Security brief lookback",
        key="security_posture_brief_days",
        default=30,
    )
    active_view = render_mode_selector(
        "Access & Security view",
        "security_posture_view",
        SECURITY_POSTURE_VIEWS,
        default=SECURITY_POSTURE_VIEWS[0],
        details=SECURITY_POSTURE_VIEW_DETAILS,
        columns=3,
    )
    if active_view == "Security Brief":
        summary = st.session_state.get("security_posture_summary")
        exceptions = st.session_state.get("security_posture_exceptions")
        meta = st.session_state.get("security_posture_meta", {})
        brief_slot = st.empty()
        snapshot_slot = st.empty()
        exception_slot = st.empty()
        _paint_security_brief_chrome(
            brief_slot,
            snapshot_slot,
            exception_slot,
            summary,
            exceptions,
            meta,
            company,
            environment,
            days,
        )
    if active_view in {"Data Health"}:
        _render_security_source_health(company, environment)
        _render_privileged_grant_readiness(company, environment, days)
        return
    if active_view == "Access Workflows":
        workflow = render_workflow_selector(
            "Security workflow",
            "security_posture_workflow",
            WORKFLOWS,
            WORKFLOW_DETAILS,
            columns=3,
        )
        if workflow == "Privilege sprawl":
            _render_privilege_sprawl_workflow(company, environment, days)
            return
        render_workflow_module(workflow, WORKFLOW_MODULES)
        return

    def _load_security_brief(*, allow_live_fallback: bool = True, quiet: bool = False) -> None:
        session = None
        try:
            session = get_session()
            summary_sql, exceptions_sql = _build_security_mart_brief_sql(session, days, company)
            st.session_state["security_posture_summary"] = run_query(
                summary_sql,
                ttl_key=f"security_posture_summary_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            source = "Fast security summary; MFA/sharing: account history"
            st.session_state["security_posture_meta"] = with_loaded_at(
                _security_scope_meta(company, environment, days),
                source=source,
            )
            st.session_state["security_posture_source"] = source
            st.session_state.pop("security_posture_summary_error", None)
            st.session_state.pop("security_posture_exceptions", None)
            st.session_state.pop("security_posture_exception_source", None)
            st.session_state.pop("security_posture_exception_error", None)
            _hide_security_proof_tables()
            st.session_state["security_posture_proof_sql"] = {
                "summary": summary_sql,
                "exceptions": exceptions_sql,
            }
        except Exception as exc:
            if not allow_live_fallback:
                st.session_state["security_posture_summary"] = pd.DataFrame()
                st.session_state["security_posture_meta"] = with_loaded_at(
                    _security_scope_meta(company, environment, days),
                    source="Fast security summary unavailable",
                )
                st.session_state["security_posture_source"] = "Fast security summary unavailable"
                st.session_state["security_posture_summary_error"] = format_snowflake_error(exc)
                st.session_state.pop("security_posture_exceptions", None)
                st.session_state.pop("security_posture_exception_source", None)
                st.session_state.pop("security_posture_exception_error", None)
                _hide_security_proof_tables()
                if not quiet:
                    st.info(
                        "Fast security summary is unavailable for this scope. "
                        "Use Refresh Security Brief for bounded live account-history proof."
                    )
                return
            try:
                session = session or get_session()
                summary_sql, exceptions_sql = _build_security_summary_sql(session, days, company)
                st.session_state["security_posture_summary"] = run_query(
                    summary_sql,
                    ttl_key=f"security_posture_summary_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE"
                st.session_state["security_posture_meta"] = with_loaded_at(
                    _security_scope_meta(company, environment, days),
                    source=source,
                )
                st.session_state["security_posture_source"] = source
                st.session_state.pop("security_posture_summary_error", None)
                st.session_state.pop("security_posture_exceptions", None)
                st.session_state.pop("security_posture_exception_source", None)
                st.session_state.pop("security_posture_exception_error", None)
                _hide_security_proof_tables()
                st.session_state["security_posture_proof_sql"] = {
                    "summary": summary_sql,
                    "exceptions": exceptions_sql,
                }
                if not quiet:
                    st.info(f"Security summary unavailable from the fast summary; used bounded live account history. {format_snowflake_error(exc)}")
            except Exception as live_exc:
                st.session_state["security_posture_summary"] = pd.DataFrame()
                st.session_state.pop("security_posture_exceptions", None)
                st.session_state.pop("security_posture_exception_source", None)
                st.session_state.pop("security_posture_exception_error", None)
                st.error(f"Unable to load security brief: {format_snowflake_error(live_exc)}")

    security_expected_meta = _security_scope_meta(company, environment, days)
    summary = st.session_state.get("security_posture_summary")
    meta = st.session_state.get("security_posture_meta", {})
    security_current = (
        summary is not None
        and not summary.empty
        and _security_meta_matches(meta, security_expected_meta)
    )
    if active_view == "Security Brief" and not security_current:
        _load_security_brief(allow_live_fallback=False, quiet=True)
        summary = st.session_state.get("security_posture_summary")
        exceptions = st.session_state.get("security_posture_exceptions")
        meta = st.session_state.get("security_posture_meta", {})
        security_current = (
            summary is not None
            and not summary.empty
            and _security_meta_matches(meta, security_expected_meta)
        )
        _paint_security_brief_chrome(
            brief_slot,
            snapshot_slot,
            exception_slot,
            summary,
            exceptions,
            meta,
            company,
            environment,
            days,
        )
    if consume_section_autoload_request("Security Posture") and not security_current:
        st.caption("Access & Security opened with fast security facts. Refresh the security brief when current account-history proof is needed.")
    render_data_freshness(
        meta if security_current else {},
        source=st.session_state.get("security_posture_source", "Security brief"),
        target_minutes=60,
        delayed_note="Security summary uses fast OVERWATCH rows when available; live ACCOUNT_USAGE refresh is explicit.",
    )

    summary_error = str(st.session_state.get("security_posture_summary_error", "") or "")
    if summary_error and not security_current:
        defer_source_note(f"Fast security summary unavailable: {summary_error}")

    if st.button("Refresh Security Brief", key="security_posture_brief_load", type="primary"):
        _load_security_brief(allow_live_fallback=True, quiet=False)
        summary = st.session_state.get("security_posture_summary")
        exceptions = st.session_state.get("security_posture_exceptions")
        meta = st.session_state.get("security_posture_meta", {})
        _paint_security_brief_chrome(
            brief_slot,
            snapshot_slot,
            exception_slot,
            summary,
            exceptions,
            meta,
            company,
            environment,
            days,
        )

    _render_security_brief_launchpad()

    summary = st.session_state.get("security_posture_summary")
    exceptions = st.session_state.get("security_posture_exceptions")
    meta = st.session_state.get("security_posture_meta", {})
    if (
        summary is not None
        and not summary.empty
        and _security_meta_matches(meta, _security_scope_meta(company, environment, days))
    ):
        row = summary.iloc[0]
        failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
        failed_users = safe_int(row.get("FAILED_USERS", 0))
        active_users = safe_int(row.get("ACTIVE_USERS", 0))
        users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
        recent_grants = safe_int(row.get("RECENT_GRANTS", 0))
        shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
        score = _security_score(
            failed_logins=failed_logins,
            failed_users=failed_users,
            users_without_mfa=users_without_mfa,
            active_users=active_users,
            recent_grants=recent_grants,
            shared_databases=shared_databases,
        )
        if score < 85:
            st.warning("Access & Security needs DBA review before this can be called clean.")
        elif score < 95:
            st.info("Access & Security is usable, but there are findings worth reviewing.")
        else:
            st.success("Access & Security is strong for the selected window.")
        defer_source_note(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE"))
        st.divider()
        with st.expander("Load Secondary Security Details", expanded=False):
            _render_security_operability_fact_gate(company, environment, days)
            _render_security_exceptions_gate(company, environment, days)
        exceptions = st.session_state.get("security_posture_exceptions")
        with exception_slot.container():
            _render_security_exception_strip(
                _security_exception_strip_rows(summary, exceptions, meta, company, environment, days),
                loaded=True,
            )
        if exceptions is not None and not exceptions.empty:
            st.subheader("Security Exceptions")
            priority_exceptions = _security_priority_view(exceptions)
            render_priority_dataframe(
                priority_exceptions,
                title="Security exceptions to validate first",
                priority_columns=[
                    "SEVERITY", "FINDING_TYPE", "ENTITY", "EVENT_COUNT",
                    "DISTINCT_SOURCES", "DATABASE_NAME", "LAST_SEEN", "ENTITY_TYPE",
                    "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["SEVERITY", "EVENT_COUNT", "LAST_SEEN"],
                ascending=[True, False, False],
                raw_label="All security exceptions",
            )

            queue_col, proof_col, _spacer_col = st.columns([1.25, 1.25, 2.5])
            with queue_col:
                if st.button("Save Security Exceptions to Action Queue", key="security_posture_queue"):
                    _queue_security_exceptions(get_session(), exceptions)
            proof_tables_visible = _security_proof_tables_visible(company, environment, days)
            with proof_col:
                if proof_tables_visible:
                    if st.button("Hide Security Detail Tables", key="security_posture_hide_proof_tables"):
                        _hide_security_proof_tables()
                        st.rerun()
                elif st.button("Load Security Detail Tables", key="security_posture_load_proof_tables"):
                    _show_security_proof_tables(company, environment, days)
                    st.rerun()
            if not proof_tables_visible:
                st.caption("Security detail tables stay unloaded until row-level user, grant, or sharing context is needed.")
            else:
                access_review = _build_security_access_review(exceptions, environment)
                security_board = _security_control_board(
                    access_review,
                    closure=st.session_state.get("security_action_closure"),
                    trend=st.session_state.get("security_access_review_trend"),
                    environment=environment,
                )
                if not security_board.empty:
                    st.subheader("Security Control Board")
                    blocked_states = security_board["CONTROL_STATE"].astype(str).str.contains("Blocked|Overdue|Required", case=False, na=False)
                    render_shell_snapshot((
                        ("Control Rows", f"{len(security_board):,}"),
                        ("Blocked", f"{int(blocked_states.sum()):,}"),
                        ("Overdue", f"{int(security_board.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                        ("Verified", f"{int(security_board.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
                    ))
                    render_priority_dataframe(
                        security_board,
                        title="Security issues blocking DBA closure",
                        priority_columns=[
                            "CONTROL_STATE", "SEVERITY", "FINDING_TYPE", "ENTITY",
                            "ENVIRONMENT", "DATABASE_CONTEXT", "OWNER", "APPROVER",
                            "REVIEW_READINESS", "REVIEW_BLOCKERS", "ACCESS_TICKET_ID",
                            "REVIEW_BY_DATE", "IAM_APPROVAL_STATE", "REVIEW_SLA_HOURS",
                            "OPEN_ACTIONS", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION",
                            "VERIFIED_CLOSURES", "CONTROL_BLOCKERS", "NEXT_CONTROL_ACTION",
                        ],
                        sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All security control rows",
                        height=340,
                    )
                render_priority_dataframe(
                    access_review,
                    title="Security access-review status before queueing",
                    priority_columns=[
                        "SEVERITY", "REVIEW_READINESS", "ACCESS_REVIEW_STATE", "FINDING_TYPE", "ENTITY",
                        "OWNER", "ESCALATION_TARGET", "APPROVER", "ROLE_CAPABILITY_STATE",
                        "ACCESS_TICKET_ID", "REVIEW_BY_DATE", "IAM_APPROVAL_STATE",
                        "REVIEW_BLOCKERS", "REVIEW_SLA_HOURS", "TICKET_REQUIRED", "REVIEW_BY_REQUIRED", "DATABASE_CONTEXT",
                        "DATABASE_NAME", "ENVIRONMENT", "SCOPE_CONFIDENCE", "SCOPE_EVIDENCE",
                        "PROOF_REQUIRED", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["REVIEW_RANK", "SEVERITY", "ENTITY"],
                    ascending=[True, True, True],
                    raw_label="Full security access review",
                )

                if st.button("Save Access Review Snapshot", key="security_posture_access_review_snapshot"):
                    _save_security_access_review_snapshot(
                        get_session(),
                        access_review,
                        company=company,
                        environment=environment,
                        source=meta.get("source", ""),
                    )

                with st.expander("Security Access Review Trend", expanded=False):
                    trend_days = day_window_selectbox(
                        "Access review history lookback",
                        key="security_access_review_trend_days",
                        default=30,
                    )
                    if st.button("Load Access Review Trend", key="security_access_review_trend_load"):
                        try:
                            trend_sql = _security_access_review_history_sql(trend_days, company, environment)
                            st.session_state["security_access_review_trend_sql"] = trend_sql
                            st.session_state["security_access_review_trend"] = run_query(
                                trend_sql,
                                ttl_key=f"security_access_review_trend_{company}_{environment}_{trend_days}",
                                tier="standard",
                                section="Security Posture",
                            )
                            st.session_state["security_access_review_trend_meta"] = _security_scope_meta(
                                company, environment, trend_days
                            )
                        except Exception as exc:
                            st.session_state["security_access_review_trend"] = pd.DataFrame()
                            st.error(f"Could not load security access-review history: {format_snowflake_error(exc)}")
                            st.info("Security access review history is not available in this environment yet. Ask the DBA team to enable it, then reload.")
                    trend = st.session_state.get("security_access_review_trend")
                    if (
                        trend is not None
                        and not _security_meta_matches(
                            st.session_state.get("security_access_review_trend_meta"),
                            _security_scope_meta(company, environment, trend_days),
                        )
                    ):
                        st.info("Loaded security access-review trend is stale for the active scope. Reload before acting.")
                    elif trend is not None and not trend.empty:
                        render_priority_dataframe(
                            trend,
                            title="Security review findings still needing DBA status",
                            priority_columns=[
                                "FINDING_TYPE", "SEVERITY", "OWNER", "ESCALATION_TARGET",
                                "REVIEW_ROWS", "TOTAL_EVENTS", "TICKET_REQUIRED_ROWS",
                                "REVIEW_BY_REQUIRED_ROWS", "CAPABILITY_PROOF_ROWS",
                                "REVIEW_BLOCKER_ROWS", "VERIFIED_REVIEW_ROWS",
                                "NO_DATABASE_CONTEXT_ROWS", "LAST_ACCESS_REVIEW_STATE",
                                "LAST_REVIEW_READINESS", "LAST_CONTROL_READINESS",
                                "LAST_ROLE_CAPABILITY_STATE", "NEXT_CONTROL_ACTION",
                            ],
                            sort_by=["REVIEW_BLOCKER_ROWS", "TICKET_REQUIRED_ROWS", "CAPABILITY_PROOF_ROWS", "TOTAL_EVENTS"],
                            ascending=[False, False, False, False],
                            raw_label="Access review history",
                        )
                        with st.expander("Access Review Status", expanded=False):
                            render_shell_snapshot((
                                ("Trend status", "Ready"),
                                ("Owner review", "Required"),
                                ("Closure status", "Required"),
                                ("Execution", "Runbook only"),
                            ))
                    elif trend is not None:
                        st.info("No saved security access-review snapshots found for the selected scope.")
                with st.expander("Security Action Closure Analytics", expanded=False):
                    defer_source_note(
                        "Uses Access & Security action-queue rows to show open, overdue, telemetry-pending, "
                        "or recently closed security work."
                    )
                    closure_days = day_window_selectbox(
                        "Security closure window",
                        key="security_action_closure_days",
                        default=30,
                    )
                    if st.button("Load Security Closure Analytics", key="security_action_closure_load"):
                        try:
                            closure_sql = _security_action_queue_closure_sql(closure_days, company, environment)
                            st.session_state["security_action_closure_sql"] = closure_sql
                            st.session_state["security_action_closure"] = run_query(
                                closure_sql,
                                ttl_key=f"security_action_closure_{company}_{environment}_{closure_days}",
                                tier="standard",
                                section="Security Posture",
                            )
                            st.session_state["security_action_closure_meta"] = _security_scope_meta(
                                company, environment, closure_days
                            )
                        except Exception as exc:
                            st.session_state["security_action_closure"] = pd.DataFrame()
                            st.warning(f"Security closure analytics unavailable: {format_snowflake_error(exc)}")
                    closure = st.session_state.get("security_action_closure")
                    if (
                        closure is not None
                        and not _security_meta_matches(
                            st.session_state.get("security_action_closure_meta"),
                            _security_scope_meta(company, environment, closure_days),
                        )
                    ):
                        st.info("Loaded security closure analytics are stale for the active scope. Reload before acting.")
                    elif closure is not None and not closure.empty:
                        render_priority_dataframe(
                            closure,
                            title="Security closure status gaps",
                            priority_columns=[
                                "CATEGORY", "ENTITY_TYPE", "ENTITY", "CLOSURE_READINESS",
                                "OWNER", "APPROVER", "TOTAL_ACTIONS", "OPEN_ACTIONS",
                                "OVERDUE_OPEN", "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                                "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                                "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                                "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                            ],
                            sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                            ascending=[True, False, False, False],
                            raw_label="All security closure rows",
                            height=300,
                        )
                        with st.expander("Security Closure Status", expanded=False):
                            render_shell_snapshot((
                                ("Closure status", "Ready"),
                                ("Telemetry", "Review"),
                                ("Telemetry", "Required"),
                                ("Execution", "Runbook only"),
                            ))
                    elif closure is not None:
                        st.info("No Access & Security action-queue rows found for the selected scope.")
        elif exceptions is not None:
            st.success("No security exceptions crossed the default thresholds.")
        brief_md = _build_security_brief_markdown(
            company=company,
            days=days,
            score=score,
            summary_row=row,
            exceptions=exceptions,
        )
        dl1, dl2 = st.columns([1, 3])
        with dl1:
            st.download_button(
                "Download Security Brief",
                brief_md,
                file_name=f"overwatch_security_brief_{company.lower()}.md",
                mime="text/markdown",
                key="security_posture_download",
            )
        with dl2:
            with st.expander("Data Health", expanded=False):
                defer_source_note("Use reviewed source telemetry when an auditor or security partner asks where a number came from.")
                render_shell_snapshot((
                    ("Summary telemetry", "Ready after refresh"),
                    ("Exception telemetry", "Ready after refresh"),
                    ("Route review", "Required"),
                    ("Execution", "Runbook only"),
                ))
        if st.session_state.get("exceptions_only_mode"):
            st.stop()
    elif summary is not None and not summary.empty:
        st.info("Loaded security brief is stale for the active scope. Reload Security Brief before acting.")
