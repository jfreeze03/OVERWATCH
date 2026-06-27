"""Alert lifecycle SQL and mutation helpers.

This module owns inserts into OVERWATCH_ALERTS plus review-gated status and
escalation acknowledgement updates. It deliberately does not render alert UI
or load alert history.
"""
from __future__ import annotations

from config import ALERT_DB, ALERT_DELIVERY_METHOD, ALERT_SCHEMA, ALERT_TABLE
from .alert_delivery import (
    DEFAULT_ALERT_RECIPIENT,
    alert_delivery_status_for_target,
    build_alert_email_body,
    build_alert_email_subject,
)
from .alert_status import (
    ALERT_STATUS_CHOICES,
    normalize_alert_severity,
    normalize_alert_status,
)
from .alert_triage import alert_table_fqn
from .compatibility import filter_existing_columns
from .query import safe_identifier, sql_literal


def build_alert_insert_sql(
    *,
    company: str,
    category: str,
    severity: str,
    entity_name: str,
    message: str,
    suggested_action: str = "",
    proof_query: str = "",
    owner: str = "DBA",
    environment: str = "No Database Context",
    email_target: str = DEFAULT_ALERT_RECIPIENT,
) -> str:
    row = {
        "COMPANY": company,
        "ENVIRONMENT": environment,
        "CATEGORY": category,
        "SEVERITY": severity,
        "ENTITY_NAME": entity_name,
        "MESSAGE": message,
        "SUGGESTED_ACTION": suggested_action,
        "PROOF_QUERY": proof_query,
        "OWNER": owner,
        "EMAIL_TARGET": email_target,
    }
    return f"""
INSERT INTO {alert_table_fqn(quoted=True)}
    (COMPANY, ENVIRONMENT, CATEGORY, ALERT_TYPE, SEVERITY, ENTITY_NAME, ENTITY,
     MESSAGE, DETAIL, SUGGESTED_ACTION, PROOF_QUERY, OWNER, STATUS,
     DELIVERY_METHOD, DELIVERY_TARGET, EMAIL_TARGET, EMAIL_SUBJECT, EMAIL_BODY,
     DELIVERY_STATUS)
VALUES
    ({sql_literal(company)}, {sql_literal(environment)}, {sql_literal(category)}, {sql_literal(category)},
     {sql_literal(normalize_alert_severity(severity))}, {sql_literal(entity_name, 500)}, {sql_literal(entity_name, 500)},
     {sql_literal(message, 4000)}, {sql_literal(message, 4000)}, {sql_literal(suggested_action, 2000)},
     {sql_literal(proof_query, 8000)}, {sql_literal(owner, 200)}, 'New',
     {sql_literal(ALERT_DELIVERY_METHOD)}, {sql_literal(email_target, 500)}, {sql_literal(email_target, 500)},
     {sql_literal(build_alert_email_subject(row, company), 1000)},
     {sql_literal(build_alert_email_body(row, company), 16000)},
     {sql_literal(alert_delivery_status_for_target(email_target))});
""".strip()


def build_alert_status_update_sql(
    *,
    alert_id: int | str,
    status: str,
    reason: str = "",
    actor: str = "OVERWATCH",
    columns: set[str] | None = None,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
) -> str:
    status_clean = normalize_alert_status(status)
    if status_clean not in ALERT_STATUS_CHOICES:
        raise ValueError(f"Unsupported alert status: {status}")
    alert_id_int = int(alert_id)
    available = {column.upper() for column in (columns or set())}
    set_parts = [f"STATUS = {sql_literal(status_clean, 40)}"]
    if "RESOLVED" in available:
        set_parts.append(f"RESOLVED = {'TRUE' if status_clean == 'Fixed' else 'FALSE'}")
    if "ACKNOWLEDGED_BY" in available and status_clean in {"Acknowledged", "In Progress", "Fixed", "Ignored"}:
        set_parts.append(f"ACKNOWLEDGED_BY = COALESCE(ACKNOWLEDGED_BY, {sql_literal(actor, 200)})")
    if "ACKNOWLEDGED_AT" in available and status_clean in {"Acknowledged", "In Progress", "Fixed", "Ignored"}:
        set_parts.append("ACKNOWLEDGED_AT = COALESCE(ACKNOWLEDGED_AT, CURRENT_TIMESTAMP())")
    if "STATUS_REASON" in available:
        set_parts.append(f"STATUS_REASON = {sql_literal(reason, 2000)}")
    if "LAST_STATUS_BY" in available:
        set_parts.append(f"LAST_STATUS_BY = {sql_literal(actor, 200)}")
    if "LAST_STATUS_AT" in available:
        set_parts.append("LAST_STATUS_AT = CURRENT_TIMESTAMP()")
    return f"""
UPDATE {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}
SET {", ".join(set_parts)}
WHERE ALERT_ID = {alert_id_int}
""".strip()


def update_alert_status(
    session,
    alert_id: int | str,
    status: str,
    *,
    reason: str = "",
    actor: str = "OVERWATCH",
) -> None:
    columns = set(filter_existing_columns(
        session,
        alert_table_fqn(),
        [
            "STATUS",
            "RESOLVED",
            "ACKNOWLEDGED_BY",
            "ACKNOWLEDGED_AT",
            "STATUS_REASON",
            "LAST_STATUS_BY",
            "LAST_STATUS_AT",
        ],
    ))
    if "STATUS" not in columns:
        raise ValueError("OVERWATCH_ALERTS does not expose STATUS for alert lifecycle updates.")
    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
    session.sql(build_alert_status_update_sql(
        alert_id=alert_id,
        status=status,
        reason=reason,
        actor=actor,
        columns=columns,
    )).collect()


def build_alert_escalation_ack_sql(
    *,
    alert_id: int | str,
    actor: str,
    note: str,
    columns: set[str] | None = None,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
) -> str:
    if len(str(note or "").strip()) < 10:
        raise ValueError("Escalation acknowledgment requires a note with telemetry or route context.")
    alert_id_int = int(alert_id)
    available = {column.upper() for column in (columns or set())}
    set_parts = []
    if "STATUS" in available:
        set_parts.append(
            "STATUS = CASE "
            "WHEN STATUS IS NULL OR UPPER(REPLACE(STATUS, ' ', '_')) IN ('NEW', 'EMAIL_READY', 'EMAIL_QUEUED', 'OPEN', 'ACTIVE', 'PENDING') "
            "THEN 'Acknowledged' ELSE STATUS END"
        )
    if "ACKNOWLEDGED_BY" in available:
        set_parts.append(f"ACKNOWLEDGED_BY = COALESCE(ACKNOWLEDGED_BY, {sql_literal(actor, 200)})")
    if "ACKNOWLEDGED_AT" in available:
        set_parts.append("ACKNOWLEDGED_AT = COALESCE(ACKNOWLEDGED_AT, CURRENT_TIMESTAMP())")
    if "ESCALATION_ACK_BY" in available:
        set_parts.append(f"ESCALATION_ACK_BY = {sql_literal(actor, 200)}")
    if "ESCALATION_ACK_AT" in available:
        set_parts.append("ESCALATION_ACK_AT = CURRENT_TIMESTAMP()")
    if "ESCALATION_ACK_NOTE" in available:
        set_parts.append(f"ESCALATION_ACK_NOTE = {sql_literal(note, 2000)}")
    if "LAST_STATUS_BY" in available:
        set_parts.append(f"LAST_STATUS_BY = {sql_literal(actor, 200)}")
    if "LAST_STATUS_AT" in available:
        set_parts.append("LAST_STATUS_AT = CURRENT_TIMESTAMP()")
    if not set_parts:
        raise ValueError("OVERWATCH_ALERTS does not expose escalation acknowledgment columns.")
    return f"""
UPDATE {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}
SET {", ".join(set_parts)}
WHERE ALERT_ID = {alert_id_int}
""".strip()


def acknowledge_alert_escalation(
    session,
    alert_id: int | str,
    *,
    actor: str,
    note: str,
) -> None:
    columns = set(filter_existing_columns(
        session,
        alert_table_fqn(),
        [
            "STATUS",
            "ACKNOWLEDGED_BY",
            "ACKNOWLEDGED_AT",
            "ESCALATION_ACK_BY",
            "ESCALATION_ACK_AT",
            "ESCALATION_ACK_NOTE",
            "LAST_STATUS_BY",
            "LAST_STATUS_AT",
        ],
    ))
    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
    session.sql(build_alert_escalation_ack_sql(
        alert_id=alert_id,
        actor=actor,
        note=note,
        columns=columns,
    )).collect()
