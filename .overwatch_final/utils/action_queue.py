# utils/action_queue.py - persistent recommendation/action queue helpers
import hashlib
import re
import threading
import time

import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from runtime_state import CURRENT_ROLE, OVERWATCH_ACTOR, get_state, set_state
from .company_filter import get_active_company, get_active_environment, get_environment_db_patterns
from .query import run_query, safe_identifier, sql_literal
from sections.decision_workspace_target_filters import build_target_predicate_plan, evidence_target_label


ACTION_QUEUE_FQN = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier(ACTION_QUEUE_TABLE)}"
)

ACTION_QUEUE_OPTIONAL_COLUMN_TYPES = {
    "ENVIRONMENT": "VARCHAR",
    "TICKET_ID": "VARCHAR",
    "APPROVER": "VARCHAR",
    "DUE_DATE": "DATE",
    "VERIFICATION_STATUS": "VARCHAR",
    "VERIFICATION_NOTES": "VARCHAR",
    "VERIFICATION_QUERY": "VARCHAR",
    "VERIFICATION_RESULT": "VARCHAR",
    "BASELINE_VALUE": "FLOAT",
    "CURRENT_VALUE": "FLOAT",
    "MEASURED_DELTA": "FLOAT",
    "VERIFIED_BY": "VARCHAR",
    "VERIFIED_AT": "TIMESTAMP_NTZ",
    "OWNER_APPROVAL_STATUS": "VARCHAR",
    "OWNER_APPROVAL_BY": "VARCHAR",
    "OWNER_APPROVAL_AT": "TIMESTAMP_NTZ",
    "OWNER_APPROVAL_NOTE": "VARCHAR",
    "RECOVERY_SLA_STATE": "VARCHAR",
    "RECOVERY_SLA_HOURS": "FLOAT",
    "RECOVERY_SLA_TARGET_HOURS": "FLOAT",
    "RECOVERY_EVIDENCE": "VARCHAR",
    "OWNER_EMAIL": "VARCHAR",
    "ONCALL_PRIMARY": "VARCHAR",
    "ONCALL_SECONDARY": "VARCHAR",
    "APPROVAL_GROUP": "VARCHAR",
    "ESCALATION_TARGET": "VARCHAR",
    "OWNER_SOURCE": "VARCHAR",
    "OWNER_EVIDENCE": "VARCHAR",
    "RECOVERY_AUDIT_STATE": "VARCHAR",
}

ACTION_QUEUE_SEVERITY_SLA_DAYS = {
    "CRITICAL": 1,
    "HIGH": 3,
    "MEDIUM": 7,
    "LOW": 14,
}

_ACTION_QUEUE_COLUMN_CACHE_KEY = "_overwatch_action_queue_columns"
_ACTION_QUEUE_COLUMN_TTL_SECONDS = 300
_ACTION_QUEUE_PROCESS_COLUMN_CACHE: dict[str, tuple[float, set[str]]] = {}
_ACTION_QUEUE_PROCESS_COLUMN_LOCK = threading.RLock()
_ACTION_QUEUE_SHOW_LOCK = threading.Lock()


def clear_action_queue_process_cache() -> None:
    """Clear process-wide action queue metadata cache."""
    with _ACTION_QUEUE_PROCESS_COLUMN_LOCK:
        _ACTION_QUEUE_PROCESS_COLUMN_CACHE.clear()


def make_action_id(category: str, entity: str, finding: str) -> str:
    raw = f"{category}|{entity}|{finding}".upper().encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:16].upper()


def action_queue_default_due_days(severity: str) -> int:
    """Return the default DBA work SLA in calendar days for an action severity."""
    return ACTION_QUEUE_SEVERITY_SLA_DAYS.get(str(severity or "").upper(), 7)


def build_action_queue_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ACTION_QUEUE_TABLE,
) -> str:
    db = safe_identifier(db)
    schema = safe_identifier(schema)
    table = safe_identifier(table)
    fqn = f"{db}.{schema}.{table}"
    optional_alters = "\n".join(
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS {safe_identifier(column)} {column_type};"
        for column, column_type in ACTION_QUEUE_OPTIONAL_COLUMN_TYPES.items()
    )
    return f"""-- OVERWATCH persistent recommendation/action queue
CREATE DATABASE IF NOT EXISTS {db};
CREATE SCHEMA IF NOT EXISTS {db}.{schema};

CREATE TABLE IF NOT EXISTS {fqn} (
    ACTION_ID                 VARCHAR(64) PRIMARY KEY,
    CREATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SOURCE                    VARCHAR(100),
    CATEGORY                  VARCHAR(100),
    SEVERITY                  VARCHAR(20),
    ENTITY_TYPE               VARCHAR(100),
    ENTITY_NAME               VARCHAR(500),
    OWNER                     VARCHAR(200),
    STATUS                    VARCHAR(40) DEFAULT 'New',
    FINDING                   VARCHAR(4000),
    RECOMMENDED_ACTION        VARCHAR(4000),
    EST_MONTHLY_SAVINGS       FLOAT,
    GENERATED_SQL_FIX         VARCHAR(8000),
    PROOF_QUERY               VARCHAR(8000),
    COMPANY                   VARCHAR(100),
    ENVIRONMENT               VARCHAR(100),
    TICKET_ID                 VARCHAR(200),
    APPROVER                  VARCHAR(200),
    DUE_DATE                  DATE,
    VERIFICATION_STATUS       VARCHAR(40) DEFAULT 'Pending',
    VERIFICATION_NOTES        VARCHAR(4000),
    VERIFICATION_QUERY        VARCHAR(8000),
    VERIFICATION_RESULT       VARCHAR(8000),
    BASELINE_VALUE            FLOAT,
    CURRENT_VALUE             FLOAT,
    MEASURED_DELTA            FLOAT,
    VERIFIED_BY               VARCHAR(200),
    VERIFIED_AT               TIMESTAMP_NTZ,
    OWNER_APPROVAL_STATUS      VARCHAR(40),
    OWNER_APPROVAL_BY          VARCHAR(200),
    OWNER_APPROVAL_AT          TIMESTAMP_NTZ,
    OWNER_APPROVAL_NOTE        VARCHAR(2000),
    RECOVERY_SLA_STATE         VARCHAR(100),
    RECOVERY_SLA_HOURS         FLOAT,
    RECOVERY_SLA_TARGET_HOURS  FLOAT,
    RECOVERY_EVIDENCE          VARCHAR(8000),
    OWNER_EMAIL                VARCHAR(500),
    ONCALL_PRIMARY             VARCHAR(200),
    ONCALL_SECONDARY           VARCHAR(200),
    APPROVAL_GROUP             VARCHAR(200),
    ESCALATION_TARGET          VARCHAR(200),
    OWNER_SOURCE               VARCHAR(200),
    OWNER_EVIDENCE             VARCHAR(2000),
    RECOVERY_AUDIT_STATE       VARCHAR(100),
    ACKNOWLEDGED_BY           VARCHAR(200),
    ACKNOWLEDGED_AT           TIMESTAMP_NTZ,
    FIXED_BY                  VARCHAR(200),
    FIXED_AT                  TIMESTAMP_NTZ,
    IGNORED_REASON            VARCHAR(2000),
    LAST_SEEN_AT              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SEEN_COUNT                NUMBER DEFAULT 1
);

{optional_alters}"""



def _show_column_name(row) -> str:
    for key in ("column_name", "COLUMN_NAME", "name", "NAME"):
        try:
            value = row.get(key) if isinstance(row, dict) else row[key]
        except Exception:
            value = None
        if value not in (None, ""):
            return str(value).upper()
    return ""


def _action_queue_role_scope() -> str:
    try:
        return str(get_state(CURRENT_ROLE, "") or "").upper()
    except Exception:
        return ""


def _action_queue_process_cache_key() -> str:
    return f"{_action_queue_role_scope()}|{ACTION_QUEUE_FQN}"


def _action_queue_process_cached_columns() -> set[str] | None:
    key = _action_queue_process_cache_key()
    with _ACTION_QUEUE_PROCESS_COLUMN_LOCK:
        entry = _ACTION_QUEUE_PROCESS_COLUMN_CACHE.get(key)
        if not entry:
            return None
        ts, columns = entry
        if (time.monotonic() - ts) > _ACTION_QUEUE_COLUMN_TTL_SECONDS:
            _ACTION_QUEUE_PROCESS_COLUMN_CACHE.pop(key, None)
            return None
        return set(columns)


def _mark_action_queue_process_columns(columns: set[str]) -> None:
    key = _action_queue_process_cache_key()
    with _ACTION_QUEUE_PROCESS_COLUMN_LOCK:
        _ACTION_QUEUE_PROCESS_COLUMN_CACHE[key] = (time.monotonic(), set(columns))


def _action_queue_column_names(session) -> set[str]:
    """Return deployed action-queue columns using cached metadata per role."""
    cached = get_state(_ACTION_QUEUE_COLUMN_CACHE_KEY)
    if isinstance(cached, set):
        return cached
    process_cached = _action_queue_process_cached_columns()
    if process_cached is not None:
        set_state(_ACTION_QUEUE_COLUMN_CACHE_KEY, process_cached)
        return process_cached
    with _ACTION_QUEUE_SHOW_LOCK:
        process_cached = _action_queue_process_cached_columns()
        if process_cached is not None:
            set_state(_ACTION_QUEUE_COLUMN_CACHE_KEY, process_cached)
            return process_cached
        try:
            # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
            rows = session.sql(f"SHOW COLUMNS IN TABLE {ACTION_QUEUE_FQN}").collect()
        except Exception:
            rows = []
        columns = {name for row in rows for name in [_show_column_name(row)] if name}
        set_state(_ACTION_QUEUE_COLUMN_CACHE_KEY, columns)
        _mark_action_queue_process_columns(columns)
        return columns


def _action_queue_has_column(session, column: str) -> bool:
    """Return whether the deployed action queue has an optional column."""
    column = str(column or "").upper()
    if not column:
        return False
    return column in _action_queue_column_names(session)


def action_queue_environment_values(environment: str | None = None) -> list[str]:
    """Return environment values that should stay visible for the active scope."""
    env = str(environment or get_active_environment() or "").upper()
    common = ["", "ALL", "NO DATABASE CONTEXT", "OTHER / SHARED"]
    if env in ("", "ALL"):
        return common
    values = common + [env]
    patterns = get_environment_db_patterns(env)
    if patterns:
        values.extend(str(value).upper() for value in patterns)
    if env == "DEV_ALL":
        values.append("ALL DEV/SIT")
    elif env.startswith("ALFA_EDW_"):
        values.append("DEV_ALL")
    return list(dict.fromkeys(values))


def action_queue_environment_clause(column: str = "ENVIRONMENT", environment: str | None = None) -> str:
    """Build a permissive action-queue environment filter.

    Rows without database context remain visible, which prevents PROD/DEV
    filtering from hiding account-level or warehouse-only findings.
    """
    values = action_queue_environment_values(environment)
    env = str(environment or get_active_environment() or "").upper()
    if env in ("", "ALL"):
        return ""
    literals = ", ".join(sql_literal(value, 100) for value in values)
    return f"UPPER(COALESCE({column}, '')) IN ({literals})"


def action_queue_fixed_missing_fields(
    *,
    status: str,
    verification_notes: str = "",
    verification_result: str = "",
) -> list[str]:
    """Return missing fields required before an item can be closed.

    Closure is status-driven in the app; scheduled telemetry should own validation.
    """
    return []


def _queue_series(df: pd.DataFrame, column: str, default: object = "") -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)


def _text_present(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text and text.upper() not in {"N/A", "NONE", "NULL"})


def _generic_owner(value: object) -> bool:
    text = str(value or "").strip().upper()
    return text in {
        "",
        "N/A",
        "UNKNOWN",
        "UNKNOWN USER",
        "UNKNOWN WAREHOUSE",
        "DBA",
        "DBA / COST OWNER",
        "DBA / DATA ENGINEERING",
    }


def _cost_control_category(category: object) -> bool:
    value = str(category or "").strip().upper()
    return value in {"COST", "COST CONTROL", "CHARGEBACK REVIEW"} or "COST" in value or "CHARGEBACK" in value


def _task_reliability_category(category: object) -> bool:
    return str(category or "").strip().upper() == "TASK & PROCEDURE RELIABILITY"


def _row_evidence_gap(row: pd.Series) -> str:
    status = str(row.get("STATUS") or "").strip()
    status_upper = status.upper()
    verification_status = str(row.get("VERIFICATION_STATUS") or "").strip().upper()
    verification_query = str(row.get("VERIFICATION_QUERY") or row.get("PROOF_QUERY") or "").strip()

    if status_upper == "FIXED":
        if verification_status in {"VERIFIED", "VERIFIED_SAVED", "VERIFIED_NO_CHANGE"} and _text_present(row.get("VERIFICATION_RESULT")):
            return "Closed"
        return "Closed pending telemetry refresh"
    if status_upper == "IGNORED":
        return "Ignored with reason" if _text_present(row.get("IGNORED_REASON")) else "Ignored without reason"

    gaps = []
    has_owner_route = _text_present(row.get("OWNER_SOURCE")) and (
        _text_present(row.get("ONCALL_PRIMARY")) or _text_present(row.get("APPROVAL_GROUP"))
    )
    if _generic_owner(row.get("OWNER")) and not has_owner_route:
        gaps.append("needs escalation route")
    if not _text_present(row.get("TICKET_ID")):
        gaps.append("missing ticket/change ID")
    if not _text_present(row.get("APPROVER")):
        gaps.append("missing reviewer")
    if not verification_query:
        gaps.append("missing telemetry query")
    elif verification_query_safety_issues(verification_query):
        gaps.append("telemetry query unavailable")

    category = str(row.get("CATEGORY") or "").upper()
    is_cost_control = _cost_control_category(category)
    is_task_reliability = _task_reliability_category(category)
    if is_cost_control or is_task_reliability:
        if not _text_present(row.get("BASELINE_VALUE")) or not _text_present(row.get("CURRENT_VALUE")):
            gaps.append("missing baseline/current value")
    if is_cost_control:
        approval_status = str(row.get("OWNER_APPROVAL_STATUS") or "").strip().upper()
        if approval_status in {"", "PENDING", "REQUESTED", "REQUIRED"}:
            gaps.append("missing telemetry status")
        if not _text_present(row.get("RECOVERY_SLA_STATE")):
            gaps.append("missing savings/chargeback closure state")
    if is_task_reliability:
        approval_status = str(row.get("OWNER_APPROVAL_STATUS") or "").strip().upper()
        recovery_state = str(row.get("RECOVERY_SLA_STATE") or "").strip().upper()
        if approval_status in {"", "PENDING", "REQUESTED", "REQUIRED"}:
            gaps.append("missing telemetry status")
        if recovery_state in {"OPEN FAILURE", "RECOVERED LATE", "RECOVERY SLA BREACH"} and not _text_present(row.get("RECOVERY_EVIDENCE")):
            gaps.append("missing recovery status")

    return "; ".join(gaps[:3]) if gaps else "Ready to work"


def _row_next_action(row: pd.Series) -> str:
    status = str(row.get("STATUS") or "").strip().upper()
    due_state = str(row.get("DUE_STATE") or "").strip()
    evidence_gap = str(row.get("EVIDENCE_GAP") or "").strip()
    category = str(row.get("CATEGORY") or "").strip()

    if status == "FIXED":
        if evidence_gap == "Closed":
            return "No action: closure status is reflected in telemetry."
        return "Reopen the item for DBA review or wait for the next telemetry refresh."
    if status == "IGNORED":
        return "Retain the ignore reason and review if the signal reappears."
    if due_state == "Overdue":
        return "Escalate the on-call route/ticket, validate current telemetry, and move this before lower-risk work."
    if evidence_gap and evidence_gap != "Ready to work":
        return f"Complete control metadata first: {evidence_gap}."
    if _cost_control_category(category):
        return "Explain the driver, review any warehouse change, then monitor next-period credits."
    if _task_reliability_category(category):
        return "Fix root cause, retry after stability checks, then monitor the next run."
    return "Acknowledge, assign the escalation route, perform the recommended action, and monitor the resulting telemetry."


def enrich_action_queue_view(df: pd.DataFrame, today: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Add DBA triage fields to action queue rows without changing stored data."""
    if df is None or df.empty:
        return df

    view = df.copy()
    today_ts = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.today().normalize()
    due_ts = pd.to_datetime(_queue_series(view, "DUE_DATE"), errors="coerce").dt.normalize()
    status = _queue_series(view, "STATUS").fillna("").astype(str)
    status_upper = status.str.upper()
    is_closed = status_upper.isin(["FIXED", "IGNORED"])
    has_due = due_ts.notna()

    view["DUE_STATE"] = "Unscheduled"
    view.loc[is_closed, "DUE_STATE"] = "Closed"
    view.loc[~is_closed & has_due & (due_ts < today_ts), "DUE_STATE"] = "Overdue"
    view.loc[~is_closed & has_due & (due_ts == today_ts), "DUE_STATE"] = "Due today"
    view.loc[
        ~is_closed & has_due & (due_ts > today_ts) & (due_ts <= today_ts + pd.Timedelta(days=2)),
        "DUE_STATE",
    ] = "Due soon"
    view.loc[~is_closed & has_due & (due_ts > today_ts + pd.Timedelta(days=2)), "DUE_STATE"] = "Scheduled"

    days_remaining = (due_ts - today_ts).dt.days
    view["SLA_DAYS_REMAINING"] = days_remaining.where(has_due, pd.NA)
    view["EVIDENCE_GAP"] = view.apply(_row_evidence_gap, axis=1)
    view["NEXT_ACTION"] = view.apply(_row_next_action, axis=1)

    severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    status_rank = {"NEW": 0, "ACKNOWLEDGED": 1, "IN PROGRESS": 2, "FIXED": 4, "IGNORED": 5}
    due_rank = {"Overdue": -20, "Due today": -15, "Due soon": -8, "Scheduled": 0, "Unscheduled": 4, "Closed": 30}
    evidence_rank = {
        "Ready to work": 0,
        "Telemetry closure": 30,
        "Ignored with reason": 30,
    }
    view["QUEUE_PRIORITY"] = (
        status_upper.map(status_rank).fillna(3).astype(float) * 20
        + _queue_series(view, "SEVERITY").fillna("").astype(str).str.upper().map(severity_rank).fillna(4).astype(float)
        + view["DUE_STATE"].map(due_rank).fillna(0).astype(float)
        + view["EVIDENCE_GAP"].map(evidence_rank).fillna(-2).astype(float)
    )
    return view


def _strip_sql_comments(sql_text: str) -> str:
    lines = []
    for line in str(sql_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _split_first_sql_statement(sql_text: str) -> tuple[str, str]:
    """Return the first SQL statement and any trailing content."""
    text = _strip_sql_comments(sql_text)
    if not text:
        return "", ""
    in_single = False
    in_double = False
    for idx, char in enumerate(text):
        prev = text[idx - 1] if idx else ""
        if char == "'" and not in_double and prev != "\\":
            in_single = not in_single
        elif char == '"' and not in_single and prev != "\\":
            in_double = not in_double
        elif char == ";" and not in_single and not in_double:
            return text[:idx].strip(), text[idx + 1:].strip()
    return text.strip(), ""


def _first_sql_statement(sql_text: str) -> str:
    """Return the first SQL statement, respecting simple quoted strings."""
    statement, _ = _split_first_sql_statement(sql_text)
    return statement


def _mask_sql_string_literals(sql_text: str) -> str:
    """Replace quoted string contents with spaces before keyword checks."""
    text = str(sql_text or "")
    chars = list(text)
    in_single = False
    in_double = False
    idx = 0
    while idx < len(chars):
        char = chars[idx]
        next_char = chars[idx + 1] if idx + 1 < len(chars) else ""
        if char == "'" and not in_double:
            if in_single and next_char == "'":
                chars[idx] = " "
                chars[idx + 1] = " "
                idx += 2
                continue
            in_single = not in_single
            chars[idx] = " "
        elif char == '"' and not in_single:
            in_double = not in_double
            chars[idx] = " "
        elif in_single or in_double:
            chars[idx] = " "
        idx += 1
    return "".join(chars)


def _starts_with_readonly_statement(statement: str) -> bool:
    return bool(re.match(r"^\s*(SELECT|WITH|SHOW|DESCRIBE|DESC|EXPLAIN)\b", str(statement or ""), re.IGNORECASE))


def verification_query_safety_issues(sql_text: str) -> list[str]:
    """Return reasons a verification query should not be executed from the app."""
    statement, trailing = _split_first_sql_statement(sql_text)
    if not statement:
        return ["verification query is empty"]
    if trailing:
        return ["verification query must contain exactly one read-only statement"]
    if not _starts_with_readonly_statement(statement):
        return ["verification query must start with SELECT, WITH, SHOW, DESCRIBE, DESC, or EXPLAIN"]
    searchable_statement = _mask_sql_string_literals(statement)
    blocked = re.findall(
        r"\b(ALTER|INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|GRANT|REVOKE|CALL|EXECUTE|COPY|PUT|GET|TRUNCATE|UNDROP)\b",
        searchable_statement,
        flags=re.IGNORECASE,
    )
    if blocked:
        return [f"verification query contains non-read-only keyword: {sorted(set(word.upper() for word in blocked))[0]}"]
    return []


def build_safe_verification_query(sql_text: str, limit: int = 50) -> str:
    """Return the first read-only verification statement with a defensive limit."""
    issues = verification_query_safety_issues(sql_text)
    if issues:
        raise ValueError("; ".join(issues))
    statement = _first_sql_statement(sql_text)
    limit = max(1, min(int(limit or 50), 500))
    if re.match(r"^\s*(SHOW|DESCRIBE|DESC|EXPLAIN)\b", statement, re.IGNORECASE):
        return statement
    if re.search(r"\bLIMIT\s+\d+\b", statement, re.IGNORECASE):
        return statement
    return f"{statement}\nLIMIT {limit}"


def summarize_verification_frame(df: pd.DataFrame, max_rows: int = 5) -> str:
    """Build compact closure status text from a telemetry query result."""
    if df is None:
        return "Telemetry query returned no dataframe."
    if df.empty:
        return "Telemetry query returned 0 rows."
    frame = df.head(max(1, int(max_rows or 5))).copy()
    return (
        f"Telemetry query returned {len(df):,} row(s). "
        f"Sample:\n{frame.to_csv(index=False).strip()}"
    )[:8000]


def _action_value(action: dict, *keys: str, default: str = ""):
    for key in keys:
        if key in action and action.get(key) not in (None, ""):
            return action.get(key)
    return default


def _optional_column_select(session, column: str) -> str:
    column = str(column or "").upper()
    col_ident = safe_identifier(column)
    if _action_queue_has_column(session, column):
        return col_ident
    col_type = ACTION_QUEUE_OPTIONAL_COLUMN_TYPES.get(column, "VARCHAR")
    return f"NULL::{col_type} AS {col_ident}"


def _float_or_none(value: object) -> str:
    try:
        if value in (None, ""):
            return "NULL"
        return str(float(value))
    except Exception:
        return "NULL"


def _num(value: object) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def upsert_actions(session, actions: list[dict]) -> int:
    if not actions:
        return 0
    has_environment = _action_queue_has_column(session, "ENVIRONMENT")
    optional_has = {
        column: _action_queue_has_column(session, column)
        for column in ACTION_QUEUE_OPTIONAL_COLUMN_TYPES
    }
    count = 0
    for action in actions:
        action_id = sql_literal(action.get("Action ID") or make_action_id(
            action.get("Category", "General"),
            action.get("Entity", ""),
            action.get("Finding", ""),
        ), max_len=64)
        source = sql_literal(action.get("Source", "Recommendations"), max_len=100)
        category = sql_literal(action.get("Category", "General"), max_len=100)
        severity = sql_literal(action.get("Severity", "Medium"), max_len=20)
        entity_type = sql_literal(action.get("Entity Type", "Snowflake Object"), max_len=100)
        entity_name = sql_literal(action.get("Entity", ""), max_len=500)
        owner = sql_literal(
            _action_value(action, "Route", "ROUTE", "Escalation Route", "Owner", "OWNER", default="DBA"),
            max_len=200,
        )
        finding = sql_literal(action.get("Finding", ""), max_len=4000)
        recommended = sql_literal(action.get("Action", ""), max_len=4000)
        sql_fix = sql_literal(action.get("Generated SQL Fix", ""), max_len=8000)
        proof = sql_literal(
            _action_value(action, "Telemetry Query", "TELEMETRY_QUERY", "Verification Query", "VERIFICATION_QUERY", "Proof Query"),
            max_len=8000,
        )
        company = sql_literal(action.get("Company", ""), max_len=100)
        environment = sql_literal(action.get("Environment") or action.get("ENVIRONMENT") or "", max_len=100)
        ticket_id = sql_literal(_action_value(action, "Ticket ID", "TICKET_ID"), max_len=200)
        approver = sql_literal(_action_value(action, "Reviewer", "REVIEWER", "Approver", "APPROVER"), max_len=200)
        due_date = sql_literal(_action_value(action, "Due Date", "DUE_DATE"), max_len=20)
        default_due_days = action_queue_default_due_days(action.get("Severity", "Medium"))
        verification_status = sql_literal(
            _action_value(action, "Telemetry Status", "TELEMETRY_STATUS", "Verification Status", "VERIFICATION_STATUS", default="Pending"),
            max_len=40,
        )
        verification_query = sql_literal(
            _action_value(action, "Telemetry Query", "TELEMETRY_QUERY", "Verification Query", "VERIFICATION_QUERY", "Proof Query"),
            max_len=8000,
        )
        owner_approval_status = sql_literal(
            _action_value(action, "Telemetry Status", "TELEMETRY_STATUS", "Verification Status", "OWNER_APPROVAL_STATUS"),
            max_len=40,
        )
        owner_approval_by = sql_literal(
            _action_value(action, "Status By", "Telemetry By", "Verification By", "OWNER_APPROVAL_BY", "Reviewer", "Approver", "APPROVER"),
            max_len=200,
        )
        owner_approval_note = sql_literal(
            _action_value(action, "Status Note", "Telemetry Note", "Verification Note", "OWNER_APPROVAL_NOTE", "Verification State"),
            max_len=2000,
        )
        recovery_sla_state = sql_literal(
            _action_value(action, "Recovery SLA State", "RECOVERY_SLA_STATE", "RECOVERY_STATE"),
            max_len=100,
        )
        recovery_evidence = sql_literal(
            _action_value(action, "Recovery Status", "RECOVERY_STATUS", "Recovery Evidence", "RECOVERY_EVIDENCE", "Verify After Fix", "VERIFY_AFTER_FIX"),
            max_len=8000,
        )
        owner_email = sql_literal(_action_value(action, "Route Email", "ROUTE_EMAIL", "Owner Email", "OWNER_EMAIL"), max_len=500)
        oncall_primary = sql_literal(_action_value(action, "Oncall Primary", "On-Call Primary", "ONCALL_PRIMARY"), max_len=200)
        oncall_secondary = sql_literal(_action_value(action, "Oncall Secondary", "On-Call Secondary", "ONCALL_SECONDARY"), max_len=200)
        approval_group = sql_literal(_action_value(action, "Escalation", "Review Group", "APPROVAL_GROUP"), max_len=200)
        escalation_target = sql_literal(_action_value(action, "Escalation Target", "ESCALATION_TARGET"), max_len=200)
        owner_source = sql_literal(_action_value(action, "Route Basis", "ROUTE_BASIS", "Owner Source", "OWNER_SOURCE"), max_len=200)
        owner_evidence = sql_literal(_action_value(action, "Route Detail", "ROUTE_DETAIL", "Route Basis", "ROUTE_BASIS", "Owner Evidence", "OWNER_EVIDENCE"), max_len=2000)
        recovery_audit_state = sql_literal(_action_value(action, "Recovery Audit State", "RECOVERY_AUDIT_STATE"), max_len=100)
        baseline_value = _float_or_none(_action_value(action, "Baseline Value", "BASELINE_VALUE", default=None))
        current_value = _float_or_none(_action_value(action, "Current Value", "CURRENT_VALUE", default=None))
        measured_delta = _float_or_none(_action_value(action, "Measured Delta", "MEASURED_DELTA", default=None))
        recovery_sla_hours = _float_or_none(
            _action_value(action, "Recovery SLA Hours", "RECOVERY_SLA_HOURS", "Recovery Hours", "RECOVERY_HOURS", default=None)
        )
        recovery_sla_target_hours = _float_or_none(
            _action_value(
                action,
                "Recovery SLA Target Hours",
                "RECOVERY_SLA_TARGET_HOURS",
                "Recovery SLA Target",
                default=None,
            )
        )
        savings = _num(action.get("Estimated Monthly Savings", 0))
        env_update = f", ENVIRONMENT = {environment}" if has_environment else ""
        env_insert_col = ", ENVIRONMENT" if has_environment else ""
        env_insert_val = f", {environment}" if has_environment else ""
        optional_update = ""
        optional_insert_cols = ""
        optional_insert_vals = ""
        if optional_has.get("TICKET_ID"):
            optional_update += f", TICKET_ID = COALESCE(NULLIF({ticket_id}, ''), tgt.TICKET_ID)"
            optional_insert_cols += ", TICKET_ID"
            optional_insert_vals += f", {ticket_id}"
        if optional_has.get("APPROVER"):
            optional_update += f", APPROVER = COALESCE(NULLIF({approver}, ''), tgt.APPROVER)"
            optional_insert_cols += ", APPROVER"
            optional_insert_vals += f", {approver}"
        if optional_has.get("DUE_DATE"):
            optional_update += (
                f", DUE_DATE = COALESCE(TRY_TO_DATE(NULLIF({due_date}, '')), "
                f"tgt.DUE_DATE, DATEADD('day', {default_due_days}, CURRENT_DATE()))"
            )
            optional_insert_cols += ", DUE_DATE"
            optional_insert_vals += (
                f", COALESCE(TRY_TO_DATE(NULLIF({due_date}, '')), "
                f"DATEADD('day', {default_due_days}, CURRENT_DATE()))"
            )
        if optional_has.get("VERIFICATION_STATUS"):
            optional_update += ", VERIFICATION_STATUS = COALESCE(tgt.VERIFICATION_STATUS, 'Pending')"
            optional_insert_cols += ", VERIFICATION_STATUS"
            optional_insert_vals += f", {verification_status}"
        if optional_has.get("VERIFICATION_QUERY"):
            optional_update += f", VERIFICATION_QUERY = COALESCE(NULLIF({verification_query}, ''), tgt.VERIFICATION_QUERY)"
            optional_insert_cols += ", VERIFICATION_QUERY"
            optional_insert_vals += f", {verification_query}"
        if optional_has.get("BASELINE_VALUE"):
            optional_update += f", BASELINE_VALUE = COALESCE({baseline_value}, tgt.BASELINE_VALUE)"
            optional_insert_cols += ", BASELINE_VALUE"
            optional_insert_vals += f", {baseline_value}"
        if optional_has.get("CURRENT_VALUE"):
            optional_update += f", CURRENT_VALUE = COALESCE({current_value}, tgt.CURRENT_VALUE)"
            optional_insert_cols += ", CURRENT_VALUE"
            optional_insert_vals += f", {current_value}"
        if optional_has.get("MEASURED_DELTA"):
            optional_update += f", MEASURED_DELTA = COALESCE({measured_delta}, tgt.MEASURED_DELTA)"
            optional_insert_cols += ", MEASURED_DELTA"
            optional_insert_vals += f", {measured_delta}"
        if optional_has.get("OWNER_APPROVAL_STATUS"):
            optional_update += f", OWNER_APPROVAL_STATUS = COALESCE(NULLIF({owner_approval_status}, ''), tgt.OWNER_APPROVAL_STATUS)"
            optional_insert_cols += ", OWNER_APPROVAL_STATUS"
            optional_insert_vals += f", {owner_approval_status}"
        if optional_has.get("OWNER_APPROVAL_BY"):
            optional_update += f", OWNER_APPROVAL_BY = COALESCE(NULLIF({owner_approval_by}, ''), tgt.OWNER_APPROVAL_BY)"
            optional_insert_cols += ", OWNER_APPROVAL_BY"
            optional_insert_vals += f", {owner_approval_by}"
        if optional_has.get("OWNER_APPROVAL_NOTE"):
            optional_update += f", OWNER_APPROVAL_NOTE = COALESCE(NULLIF({owner_approval_note}, ''), tgt.OWNER_APPROVAL_NOTE)"
            optional_insert_cols += ", OWNER_APPROVAL_NOTE"
            optional_insert_vals += f", {owner_approval_note}"
        if optional_has.get("RECOVERY_SLA_STATE"):
            optional_update += f", RECOVERY_SLA_STATE = COALESCE(NULLIF({recovery_sla_state}, ''), tgt.RECOVERY_SLA_STATE)"
            optional_insert_cols += ", RECOVERY_SLA_STATE"
            optional_insert_vals += f", {recovery_sla_state}"
        if optional_has.get("RECOVERY_SLA_HOURS"):
            optional_update += f", RECOVERY_SLA_HOURS = COALESCE({recovery_sla_hours}, tgt.RECOVERY_SLA_HOURS)"
            optional_insert_cols += ", RECOVERY_SLA_HOURS"
            optional_insert_vals += f", {recovery_sla_hours}"
        if optional_has.get("RECOVERY_SLA_TARGET_HOURS"):
            optional_update += f", RECOVERY_SLA_TARGET_HOURS = COALESCE({recovery_sla_target_hours}, tgt.RECOVERY_SLA_TARGET_HOURS)"
            optional_insert_cols += ", RECOVERY_SLA_TARGET_HOURS"
            optional_insert_vals += f", {recovery_sla_target_hours}"
        if optional_has.get("RECOVERY_EVIDENCE"):
            optional_update += f", RECOVERY_EVIDENCE = COALESCE(NULLIF({recovery_evidence}, ''), tgt.RECOVERY_EVIDENCE)"
            optional_insert_cols += ", RECOVERY_EVIDENCE"
            optional_insert_vals += f", {recovery_evidence}"
        if optional_has.get("OWNER_EMAIL"):
            optional_update += f", OWNER_EMAIL = COALESCE(NULLIF({owner_email}, ''), tgt.OWNER_EMAIL)"
            optional_insert_cols += ", OWNER_EMAIL"
            optional_insert_vals += f", {owner_email}"
        if optional_has.get("ONCALL_PRIMARY"):
            optional_update += f", ONCALL_PRIMARY = COALESCE(NULLIF({oncall_primary}, ''), tgt.ONCALL_PRIMARY)"
            optional_insert_cols += ", ONCALL_PRIMARY"
            optional_insert_vals += f", {oncall_primary}"
        if optional_has.get("ONCALL_SECONDARY"):
            optional_update += f", ONCALL_SECONDARY = COALESCE(NULLIF({oncall_secondary}, ''), tgt.ONCALL_SECONDARY)"
            optional_insert_cols += ", ONCALL_SECONDARY"
            optional_insert_vals += f", {oncall_secondary}"
        if optional_has.get("APPROVAL_GROUP"):
            optional_update += f", APPROVAL_GROUP = COALESCE(NULLIF({approval_group}, ''), tgt.APPROVAL_GROUP)"
            optional_insert_cols += ", APPROVAL_GROUP"
            optional_insert_vals += f", {approval_group}"
        if optional_has.get("ESCALATION_TARGET"):
            optional_update += f", ESCALATION_TARGET = COALESCE(NULLIF({escalation_target}, ''), tgt.ESCALATION_TARGET)"
            optional_insert_cols += ", ESCALATION_TARGET"
            optional_insert_vals += f", {escalation_target}"
        if optional_has.get("OWNER_SOURCE"):
            optional_update += f", OWNER_SOURCE = COALESCE(NULLIF({owner_source}, ''), tgt.OWNER_SOURCE)"
            optional_insert_cols += ", OWNER_SOURCE"
            optional_insert_vals += f", {owner_source}"
        if optional_has.get("OWNER_EVIDENCE"):
            optional_update += f", OWNER_EVIDENCE = COALESCE(NULLIF({owner_evidence}, ''), tgt.OWNER_EVIDENCE)"
            optional_insert_cols += ", OWNER_EVIDENCE"
            optional_insert_vals += f", {owner_evidence}"
        if optional_has.get("RECOVERY_AUDIT_STATE"):
            optional_update += f", RECOVERY_AUDIT_STATE = COALESCE(NULLIF({recovery_audit_state}, ''), tgt.RECOVERY_AUDIT_STATE)"
            optional_insert_cols += ", RECOVERY_AUDIT_STATE"
            optional_insert_vals += f", {recovery_audit_state}"
        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
        session.sql(f"""
            MERGE INTO {ACTION_QUEUE_FQN} tgt
            USING (
                SELECT {action_id} AS action_id
            ) src
            ON tgt.action_id = src.action_id
            WHEN MATCHED THEN UPDATE SET
                UPDATED_AT = CURRENT_TIMESTAMP(),
                LAST_SEEN_AT = CURRENT_TIMESTAMP(),
                SEEN_COUNT = COALESCE(tgt.SEEN_COUNT, 0) + 1,
                SEVERITY = {severity},
                OWNER = {owner},
                FINDING = {finding},
                RECOMMENDED_ACTION = {recommended},
                EST_MONTHLY_SAVINGS = {savings},
                GENERATED_SQL_FIX = {sql_fix},
                PROOF_QUERY = {proof}
                {env_update}
                {optional_update}
            WHEN NOT MATCHED THEN INSERT (
                ACTION_ID, SOURCE, CATEGORY, SEVERITY, ENTITY_TYPE, ENTITY_NAME,
                OWNER, STATUS, FINDING, RECOMMENDED_ACTION, EST_MONTHLY_SAVINGS,
                GENERATED_SQL_FIX, PROOF_QUERY, COMPANY{env_insert_col}{optional_insert_cols}
            )
            VALUES (
                {action_id}, {source}, {category}, {severity}, {entity_type},
                {entity_name}, {owner}, 'New', {finding}, {recommended},
                {savings}, {sql_fix}, {proof}, {company}{env_insert_val}{optional_insert_vals}
            )
        """).collect()
        count += 1
    return count


def load_action_queue(session, limit: int = 500, *, target: dict | None = None, section: str = "") -> pd.DataFrame:
    company = get_active_company()
    has_environment = _action_queue_has_column(session, "ENVIRONMENT")
    where_clauses = []
    if company != "ALL":
        where_clauses.append(f"COMPANY = {sql_literal(company)}")
    if has_environment:
        env_clause = action_queue_environment_clause("ENVIRONMENT")
        if env_clause:
            where_clauses.append(env_clause)
    where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else "WHERE 1 = 1"
    optional_selects = [
        _optional_column_select(session, column)
        for column in ACTION_QUEUE_OPTIONAL_COLUMN_TYPES
    ]
    target_filter = ""
    target_hash = "none"
    target_plan = build_target_predicate_plan(str(section or "Alert Center"), target or {}, ())
    target_label = evidence_target_label(target or {})
    if target:
        try:
            target_columns = {
                "ACTION_ID",
                "ENTITY_TYPE",
                "ENTITY_NAME",
                "OWNER",
                "CATEGORY",
                "SOURCE",
            }
            optional_target_columns = {
                "TICKET_ID",
                "OWNER_SOURCE",
                "OWNER_EVIDENCE",
                "RECOVERY_EVIDENCE",
                "VERIFICATION_STATUS",
                "RECOVERY_AUDIT_STATE",
                "ALERT_ID",
                "ALERT_KEY",
                "EVENT_ID",
                "EVIDENCE_ID",
                "GRANT_ID",
            }
            for column in optional_target_columns:
                if _action_queue_has_column(session, column):
                    target_columns.add(column)
            target_plan = build_target_predicate_plan(
                str(section or "Alert Center"),
                target,
                available_columns=tuple(sorted(target_columns)),
            ).with_fingerprint()
            target_filter = target_plan.sql_filter
            target_hash = hashlib.sha1(str(target_filter or target).encode("utf-8", errors="ignore")).hexdigest()[:10]
        except Exception:
            target_filter = ""
            target_hash = "target"
    df = run_query(f"""
        SELECT ACTION_ID, CREATED_AT, UPDATED_AT, SOURCE, CATEGORY, SEVERITY,
               ENTITY_TYPE, ENTITY_NAME, OWNER, STATUS, FINDING, RECOMMENDED_ACTION,
               EST_MONTHLY_SAVINGS, GENERATED_SQL_FIX, PROOF_QUERY, COMPANY,
               {", ".join(optional_selects)},
               LAST_SEEN_AT, SEEN_COUNT
        FROM {ACTION_QUEUE_FQN}
        {where_clause}
        {target_filter}
        ORDER BY
            CASE STATUS
                WHEN 'New' THEN 1
                WHEN 'Acknowledged' THEN 2
                WHEN 'In Progress' THEN 3
                WHEN 'Fixed' THEN 4
                WHEN 'Ignored' THEN 5
                ELSE 6
            END,
            CASE SEVERITY
                WHEN 'Critical' THEN 1
                WHEN 'High' THEN 2
                WHEN 'Medium' THEN 3
                WHEN 'Low' THEN 4
                ELSE 5
            END,
            UPDATED_AT DESC
        LIMIT {int(limit)}
    """,
        ttl_key=f"action_queue_{company}_{get_active_environment()}_{int(limit)}_{target_hash}",
        tier="recent",
        section=section,
        max_rows=int(limit),
        query_boundary="evidence",
        target_label=target_label,
        target_context_present=bool(target),
        target_columns_used=target_plan.columns_used,
        target_fallback_used=target_plan.fallback_used,
        target_predicate_marker_present=bool(target_filter),
        target_predicate_plan_id=target_plan.plan_id,
    )
    return enrich_action_queue_view(df)


def _safe_actor(session) -> str:
    return str(get_state(OVERWATCH_ACTOR, "OVERWATCH") or "OVERWATCH")


def update_action_status(session, action_id: str, status: str, reason: str = "") -> None:
    return update_action_status_with_evidence(session, action_id, status, reason=reason)


def update_action_status_with_evidence(
    session,
    action_id: str,
    status: str,
    *,
    reason: str = "",
    verification_notes: str = "",
    verification_result: str = "",
    verification_query: str = "",
    ticket_id: str = "",
    approver: str = "",
    due_date: str = "",
    baseline_value=None,
    current_value=None,
    measured_delta=None,
    owner_approval_status: str = "",
    owner_approval_note: str = "",
    recovery_sla_state: str = "",
    recovery_sla_hours=None,
    recovery_sla_target_hours=None,
    recovery_evidence: str = "",
) -> None:
    missing = action_queue_fixed_missing_fields(
        status=status,
        verification_notes=verification_notes,
        verification_result=verification_result,
    )
    if missing:
        raise ValueError("Fixed status requires " + " and ".join(missing) + ".")

    action_safe = sql_literal(action_id, max_len=64)
    status_safe = sql_literal(status, max_len=40)
    reason_safe = sql_literal(reason, max_len=2000)
    actor_safe = sql_literal(_safe_actor(session), max_len=200)
    extra = ""
    if status == "Acknowledged":
        extra = f", ACKNOWLEDGED_BY = {actor_safe}, ACKNOWLEDGED_AT = CURRENT_TIMESTAMP()"
    elif status == "Fixed":
        extra = f", FIXED_BY = {actor_safe}, FIXED_AT = CURRENT_TIMESTAMP()"
    elif status == "Ignored":
        extra = f", IGNORED_REASON = {reason_safe}"
    if _action_queue_has_column(session, "TICKET_ID"):
        extra += f", TICKET_ID = COALESCE(NULLIF({sql_literal(ticket_id, 200)}, ''), TICKET_ID)"
    if _action_queue_has_column(session, "APPROVER"):
        extra += f", APPROVER = COALESCE(NULLIF({sql_literal(approver, 200)}, ''), APPROVER)"
    if _action_queue_has_column(session, "DUE_DATE"):
        extra += f", DUE_DATE = COALESCE(TRY_TO_DATE(NULLIF({sql_literal(due_date, 20)}, '')), DUE_DATE)"
    if _action_queue_has_column(session, "OWNER_APPROVAL_STATUS"):
        extra += (
            f", OWNER_APPROVAL_STATUS = COALESCE(NULLIF({sql_literal(owner_approval_status, 40)}, ''), "
            "OWNER_APPROVAL_STATUS)"
        )
    if _action_queue_has_column(session, "OWNER_APPROVAL_BY"):
        extra += (
            f", OWNER_APPROVAL_BY = CASE WHEN NULLIF({sql_literal(owner_approval_status, 40)}, '') IS NOT NULL "
            f"AND UPPER({sql_literal(owner_approval_status, 40)}) IN ('APPROVED', 'VERIFIED', 'REJECTED', 'NOT REQUIRED') "
            f"THEN {actor_safe} ELSE OWNER_APPROVAL_BY END"
        )
    if _action_queue_has_column(session, "OWNER_APPROVAL_AT"):
        extra += (
            f", OWNER_APPROVAL_AT = CASE WHEN NULLIF({sql_literal(owner_approval_status, 40)}, '') IS NOT NULL "
            f"AND UPPER({sql_literal(owner_approval_status, 40)}) IN ('APPROVED', 'VERIFIED', 'REJECTED', 'NOT REQUIRED') "
            "THEN CURRENT_TIMESTAMP() ELSE OWNER_APPROVAL_AT END"
        )
    if _action_queue_has_column(session, "OWNER_APPROVAL_NOTE"):
        extra += f", OWNER_APPROVAL_NOTE = COALESCE(NULLIF({sql_literal(owner_approval_note, 2000)}, ''), OWNER_APPROVAL_NOTE)"
    if _action_queue_has_column(session, "RECOVERY_SLA_STATE"):
        extra += f", RECOVERY_SLA_STATE = COALESCE(NULLIF({sql_literal(recovery_sla_state, 100)}, ''), RECOVERY_SLA_STATE)"
    if _action_queue_has_column(session, "RECOVERY_SLA_HOURS"):
        extra += f", RECOVERY_SLA_HOURS = COALESCE({_float_or_none(recovery_sla_hours)}, RECOVERY_SLA_HOURS)"
    if _action_queue_has_column(session, "RECOVERY_SLA_TARGET_HOURS"):
        extra += f", RECOVERY_SLA_TARGET_HOURS = COALESCE({_float_or_none(recovery_sla_target_hours)}, RECOVERY_SLA_TARGET_HOURS)"
    if _action_queue_has_column(session, "RECOVERY_EVIDENCE"):
        extra += f", RECOVERY_EVIDENCE = COALESCE(NULLIF({sql_literal(recovery_evidence, 8000)}, ''), RECOVERY_EVIDENCE)"
    if status == "Fixed":
        if _action_queue_has_column(session, "VERIFICATION_STATUS"):
            extra += ", VERIFICATION_STATUS = 'Verified'"
        if _action_queue_has_column(session, "VERIFICATION_NOTES"):
            extra += f", VERIFICATION_NOTES = {sql_literal(verification_notes, 4000)}"
        if _action_queue_has_column(session, "VERIFICATION_RESULT"):
            extra += f", VERIFICATION_RESULT = {sql_literal(verification_result, 8000)}"
        if _action_queue_has_column(session, "VERIFICATION_QUERY"):
            extra += f", VERIFICATION_QUERY = COALESCE(NULLIF({sql_literal(verification_query, 8000)}, ''), VERIFICATION_QUERY, PROOF_QUERY)"
        if _action_queue_has_column(session, "BASELINE_VALUE"):
            extra += f", BASELINE_VALUE = COALESCE({_float_or_none(baseline_value)}, BASELINE_VALUE)"
        if _action_queue_has_column(session, "CURRENT_VALUE"):
            extra += f", CURRENT_VALUE = COALESCE({_float_or_none(current_value)}, CURRENT_VALUE)"
        if _action_queue_has_column(session, "MEASURED_DELTA"):
            extra += f", MEASURED_DELTA = COALESCE({_float_or_none(measured_delta)}, MEASURED_DELTA)"
        if _action_queue_has_column(session, "VERIFIED_BY"):
            extra += f", VERIFIED_BY = {actor_safe}"
        if _action_queue_has_column(session, "VERIFIED_AT"):
            extra += ", VERIFIED_AT = CURRENT_TIMESTAMP()"
    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
    session.sql(f"""
        UPDATE {ACTION_QUEUE_FQN}
        SET STATUS = {status_safe},
            UPDATED_AT = CURRENT_TIMESTAMP()
            {extra}
        WHERE ACTION_ID = {action_safe}
    """).collect()
