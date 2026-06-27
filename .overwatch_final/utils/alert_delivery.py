"""Alert delivery helpers for OVERWATCH.

This module owns recipient resolution, email/webhook payload construction,
delivery audit DDL/DML, and delivery log reads. It intentionally does not own
alert triage, alert catalog, native alert deployment, or action-queue routing.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

import pandas as pd
import streamlit as st

from runtime_state import ALERT_EMAIL_TARGETS, get_state

from config import (
    ALERT_DB,
    ALERT_DELIVERY_METHOD,
    ALERT_SCHEMA,
    ALERT_TABLE,
    DEFAULT_ALERT_EMAIL,
)

from .compatibility import filter_existing_columns
from .alert_status import normalize_alert_severity as _normalize_alert_severity
from .query import format_snowflake_error, run_query, safe_identifier
from .sql_safe import sql_literal
from sections.decision_workspace_target_filters import (
    TARGET_PREDICATE_MARKER,
    build_target_predicate_plan,
    evidence_target_label,
)


ALERT_DELIVERY_LOG_TABLE = "OVERWATCH_ALERT_DELIVERY_LOG"
DEFAULT_ALERT_RECIPIENT = DEFAULT_ALERT_EMAIL


def current_alert_recipient(default: str = DEFAULT_ALERT_RECIPIENT) -> str:
    """Return the deployment-configured alert recipient when Streamlit state exists."""
    try:
        configured = str(get_state(ALERT_EMAIL_TARGETS, "") or "").strip()
    except Exception:
        configured = ""
    return configured or default


def alert_recipient_label(recipient: str | None = None) -> str:
    target = str(current_alert_recipient(recipient or "") or "").strip()
    return target or "not configured"


def alert_delivery_status_for_target(recipient: str | None = None) -> str:
    return "EMAIL_READY" if str(recipient or "").strip() else "CONFIG_REQUIRED"


def _row_value(row: Any, *names: str, default: str = "") -> str:
    for name in names:
        try:
            value = row.get(name)
        except AttributeError:
            value = None
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = str(value).strip()
        if text:
            return text
    return default


def _numeric_alert_ids(df_or_ids: Any) -> list[int]:
    if df_or_ids is None:
        return []
    if isinstance(df_or_ids, pd.DataFrame):
        if "ALERT_ID" not in df_or_ids.columns:
            return []
        values = df_or_ids["ALERT_ID"].dropna().astype(str).tolist()
    elif isinstance(df_or_ids, pd.Series):
        values = df_or_ids.dropna().astype(str).tolist()
    else:
        values = list(df_or_ids)
    clean: list[int] = []
    for value in values:
        text = str(value).strip()
        if text.isdigit():
            clean.append(int(text))
    return list(dict.fromkeys(clean))


def send_teams_alert(webhook_url: str, message: str, title: str = "OVERWATCH Alert") -> bool:
    """Send a Microsoft Teams message via incoming webhook.

    Kept for future Teams support, but the active framework is email-first.
    """
    if not webhook_url:
        return False
    payload = json.dumps({
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": "38BDF8",
        "title": title,
        "text": message,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        st.warning(f"Teams alert failed: {format_snowflake_error(e)}")
        return False


def alert_delivery_log_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_DELIVERY_LOG_TABLE,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"
    return f"{db}.{schema}.{table}"


def build_alert_email_subject(row: pd.Series | dict, company: str = "ALFA") -> str:
    severity = _normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium"))
    category = _row_value(row, "CATEGORY", "ALERT_TYPE", "DOMAIN", "SIGNAL", default="Alert")
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
    company_text = _row_value(row, "COMPANY", default=company)
    return f"OVERWATCH {severity}: {category} - {entity} ({company_text})"


def build_alert_email_body(row: pd.Series | dict, company: str = "ALFA") -> str:
    company_text = _row_value(row, "COMPANY", default=company)
    environment = _row_value(row, "ENVIRONMENT", default="No Database Context")
    category = _row_value(row, "CATEGORY", "ALERT_TYPE", "DOMAIN", "SIGNAL", default="Alert")
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
    severity = _normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium"))
    message = _row_value(row, "MESSAGE", "DETAIL", default="No alert detail captured.")
    action = _row_value(row, "SUGGESTED_ACTION", "NEXT_ACTION", default="Review the Alert Center issue and route it through the DBA action queue.")
    proof = _row_value(row, "PROOF_QUERY", default="No telemetry query captured.")
    return "\n".join([
        f"Company: {company_text}",
        f"Environment: {environment}",
        f"Severity: {severity}",
        f"Alert: {category}",
        f"Entity: {entity}",
        "",
        "Detail:",
        message,
        "",
        "Next action:",
        action,
        "",
        "Telemetry query:",
        proof,
    ])


def build_alert_delivery_log_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(ALERT_DELIVERY_LOG_TABLE)} (
    DELIVERY_ID      NUMBER AUTOINCREMENT PRIMARY KEY,
    DELIVERY_TS      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY          VARCHAR(100),
    ENVIRONMENT      VARCHAR(100),
    ALERT_IDS        VARIANT,
    ALERT_COUNT      NUMBER,
    DELIVERY_METHOD  VARCHAR(40) DEFAULT 'EMAIL',
    DELIVERY_TARGET  VARCHAR(500),
    EMAIL_SUBJECT    VARCHAR(1000),
    EMAIL_BODY       VARCHAR(16000),
    DELIVERY_STATUS  VARCHAR(100),
    DELIVERY_BY      VARCHAR(200),
    DELIVERY_NOTES   VARCHAR(4000)
);"""


def build_alert_delivery_log_insert_sql(
    *,
    alert_ids: list[int | str],
    company: str,
    environment: str,
    delivery_target: str,
    email_subject: str,
    email_body: str,
    actor: str,
    notes: str,
    delivery_status: str = "EMAIL_LOGGED",
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    clean_ids = _numeric_alert_ids(alert_ids)
    if not clean_ids:
        raise ValueError("At least one numeric alert id is required for delivery logging.")
    if not str(delivery_target or "").strip():
        raise ValueError("Delivery target is required.")
    if len(str(notes or "").strip()) < 10:
        raise ValueError("Delivery notes must explain where/how the email was handled.")
    alert_json = json.dumps(clean_ids)
    return f"""
INSERT INTO {alert_delivery_log_fqn(db=db, schema=schema, quoted=True)}
    (COMPANY, ENVIRONMENT, ALERT_IDS, ALERT_COUNT, DELIVERY_METHOD, DELIVERY_TARGET,
     EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS, DELIVERY_BY, DELIVERY_NOTES)
VALUES
    ({sql_literal(company, 100)}, {sql_literal(environment, 100)}, PARSE_JSON({sql_literal(alert_json, 16000)}),
     {len(clean_ids)}, {sql_literal(ALERT_DELIVERY_METHOD, 40)}, {sql_literal(delivery_target, 500)},
     {sql_literal(email_subject, 1000)}, {sql_literal(email_body, 16000)}, {sql_literal(delivery_status, 100)},
     {sql_literal(actor, 200)}, {sql_literal(notes, 4000)})
""".strip()


def build_alert_delivery_mark_sql(
    *,
    alert_ids: list[int | str],
    delivery_target: str,
    actor: str,
    columns: set[str] | None = None,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
) -> str:
    clean_ids = _numeric_alert_ids(alert_ids)
    if not clean_ids:
        raise ValueError("At least one numeric alert id is required.")
    available = {column.upper() for column in (columns or set())}
    set_parts = []
    if "DELIVERY_STATUS" in available:
        set_parts.append("DELIVERY_STATUS = 'EMAIL_LOGGED'")
    if "DELIVERY_TARGET" in available:
        set_parts.append(f"DELIVERY_TARGET = {sql_literal(delivery_target, 500)}")
    if "EMAIL_TARGET" in available:
        set_parts.append(f"EMAIL_TARGET = COALESCE(NULLIF(EMAIL_TARGET, ''), {sql_literal(delivery_target, 500)})")
    if "LAST_DELIVERY_AT" in available:
        set_parts.append("LAST_DELIVERY_AT = CURRENT_TIMESTAMP()")
    if "LAST_DELIVERY_BY" in available:
        set_parts.append(f"LAST_DELIVERY_BY = {sql_literal(actor, 200)}")
    if "DELIVERY_LOG_COUNT" in available:
        set_parts.append("DELIVERY_LOG_COUNT = COALESCE(DELIVERY_LOG_COUNT, 0) + 1")
    if "ESCALATED_TO" in available:
        set_parts.append(
            "ESCALATED_TO = COALESCE(ESCALATED_TO, "
            "CASE WHEN UPPER(COALESCE(SEVERITY, 'Medium')) IN ('CRITICAL', 'HIGH') THEN 'DBA Lead' ELSE COALESCE(OWNER, 'DBA') END)"
        )
    if "ESCALATED_AT" in available:
        set_parts.append("ESCALATED_AT = COALESCE(ESCALATED_AT, CURRENT_TIMESTAMP())")
    if "LAST_STATUS_BY" in available:
        set_parts.append(f"LAST_STATUS_BY = {sql_literal(actor, 200)}")
    if "LAST_STATUS_AT" in available:
        set_parts.append("LAST_STATUS_AT = CURRENT_TIMESTAMP()")
    if not set_parts:
        raise ValueError("OVERWATCH_ALERTS does not expose delivery audit columns.")
    return f"""
UPDATE {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}
SET {", ".join(set_parts)}
WHERE ALERT_ID IN ({", ".join(str(value) for value in clean_ids)})
""".strip()


def log_alert_digest_delivery(
    session,
    df_alerts: pd.DataFrame,
    *,
    company: str,
    environment: str,
    delivery_target: str,
    email_subject: str,
    email_body: str,
    actor: str,
    notes: str,
) -> int:
    clean_ids = _numeric_alert_ids(df_alerts)
    if not clean_ids:
        raise ValueError("No alert rows with numeric ALERT_ID values are available to log.")
    columns = set(filter_existing_columns(
        session,
        f"{ALERT_DB}.{ALERT_SCHEMA}.{ALERT_TABLE}",
        [
            "DELIVERY_STATUS",
            "DELIVERY_TARGET",
            "EMAIL_TARGET",
            "LAST_DELIVERY_AT",
            "LAST_DELIVERY_BY",
            "DELIVERY_LOG_COUNT",
            "ESCALATED_TO",
            "ESCALATED_AT",
            "LAST_STATUS_BY",
            "LAST_STATUS_AT",
        ],
    ))
    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
    session.sql(build_alert_delivery_log_insert_sql(
        alert_ids=clean_ids,
        company=company,
        environment=environment,
        delivery_target=delivery_target,
        email_subject=email_subject,
        email_body=email_body,
        actor=actor,
        notes=notes,
    )).collect()
    if columns:
        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
        session.sql(build_alert_delivery_mark_sql(
            alert_ids=clean_ids,
            delivery_target=delivery_target,
            actor=actor,
            columns=columns,
        )).collect()
    return len(clean_ids)


def build_alert_email_delivery_procedure_sql(
    *,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
    notification_integration: str = "OVERWATCH_EMAIL_INT",
    email_target: str = DEFAULT_ALERT_RECIPIENT,
) -> str:
    """Return optional Snowflake email delivery procedure with replay audit."""
    db_safe = safe_identifier(db)
    schema_safe = safe_identifier(schema)
    table_safe = safe_identifier(table)
    proc_fqn = f"{db_safe}.{schema_safe}.SP_OVERWATCH_SEND_ALERT_DIGEST"
    integration = str(notification_integration or "OVERWATCH_EMAIL_INT").replace("'", "''")
    default_recipient = sql_literal(email_target, 500)
    return f"""-- Optional reviewed email sender for Alert Center.
-- Prerequisite: create and approve notification integration {integration} outside OVERWATCH.
-- Keep P_DRY_RUN => TRUE until the integration and recipient allow-list are verified.
CREATE OR REPLACE PROCEDURE {proc_fqn}(
    P_COMPANY VARCHAR DEFAULT 'ALFA',
    P_ENVIRONMENT VARCHAR DEFAULT 'ALL',
    P_RECIPIENT VARCHAR DEFAULT {default_recipient},
    P_DRY_RUN BOOLEAN DEFAULT TRUE
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    alert_count NUMBER DEFAULT 0;
    alert_ids VARIANT DEFAULT PARSE_JSON('[]');
    subject VARCHAR DEFAULT '';
    body VARCHAR DEFAULT '';
    delivery_status VARCHAR DEFAULT 'EMAIL_DRY_RUN';
BEGIN
    CREATE OR REPLACE TEMPORARY TABLE TMP_OVERWATCH_ALERT_DIGEST AS
    SELECT
        ALERT_ID,
        COMPANY,
        ENVIRONMENT,
        SEVERITY,
        CATEGORY,
        ALERT_TYPE,
        ENTITY_NAME,
        OWNER,
        COALESCE(EMAIL_SUBJECT, 'OVERWATCH ' || COALESCE(SEVERITY, 'Medium') || ' alert digest') AS EMAIL_SUBJECT,
        COALESCE(
            EMAIL_BODY,
            COALESCE(SEVERITY, 'Medium') || ' | ' || COALESCE(CATEGORY, 'Alert') || ' | ' ||
            COALESCE(ALERT_TYPE, CATEGORY, 'Alert') || ' | ' || COALESCE(ENTITY_NAME, ENTITY, 'Snowflake account') ||
            '\\nAction: ' || COALESCE(SUGGESTED_ACTION, 'Review in Alert Center.')
        ) AS EMAIL_BODY
    FROM {db_safe}.{schema_safe}.{table_safe}
    WHERE UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_')) IN ('NEW', 'OPEN', 'ACTIVE', 'EMAIL_READY', 'EMAIL_QUEUED', 'PENDING', 'ACKNOWLEDGED', 'IN_PROGRESS')
      AND (P_COMPANY = 'ALL' OR COMPANY = P_COMPANY)
      AND (
          P_ENVIRONMENT = 'ALL'
          OR COALESCE(ENVIRONMENT, 'No Database Context') = P_ENVIRONMENT
          OR (P_ENVIRONMENT = 'DEV_ALL' AND COALESCE(ENVIRONMENT, '') IN ('DEV_ALL', 'ALFA_EDW_DEV', 'ALFA_EDW_SAN', 'ALFA_EDW_PHX', 'ALFA_EDW_SEA', 'ALFA_EDW_SIT', 'OTHER ALFA NON-PROD'))
      )
    ORDER BY
        CASE UPPER(COALESCE(SEVERITY, 'Medium'))
            WHEN 'CRITICAL' THEN 0
            WHEN 'HIGH' THEN 1
            WHEN 'MEDIUM' THEN 2
            WHEN 'LOW' THEN 3
            ELSE 4
        END,
        ALERT_TS DESC
    LIMIT 25;

    SELECT
        COUNT(*),
        TO_VARIANT(ARRAY_AGG(ALERT_ID)),
        'OVERWATCH alert digest - ' || P_COMPANY || ' / ' || P_ENVIRONMENT || ' - ' || COUNT(*) || ' open issue(s)',
        LISTAGG(
            '[' || COALESCE(SEVERITY, 'Medium') || '] ' || COALESCE(ALERT_TYPE, CATEGORY, 'Alert') ||
            ' | ' || COALESCE(ENTITY_NAME, 'Snowflake account') ||
            ' | Owner: ' || COALESCE(OWNER, 'DBA') ||
            '\\n' || EMAIL_BODY,
            '\\n\\n---\\n\\n'
        ) WITHIN GROUP (ORDER BY ALERT_ID)
    INTO :alert_count, :alert_ids, :subject, :body
    FROM TMP_OVERWATCH_ALERT_DIGEST;

    IF (alert_count = 0) THEN
        RETURN 'No open OVERWATCH alerts matched the requested scope.';
    END IF;

    IF (P_DRY_RUN) THEN
        delivery_status := 'EMAIL_DRY_RUN';
    ELSE
        CALL SYSTEM$SEND_EMAIL('{integration}', :P_RECIPIENT, :subject, :body);
        delivery_status := 'EMAIL_SENT';
    END IF;

    INSERT INTO {alert_delivery_log_fqn(db=db, schema=schema, quoted=True)}
        (COMPANY, ENVIRONMENT, ALERT_IDS, ALERT_COUNT, DELIVERY_METHOD, DELIVERY_TARGET,
         EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS, DELIVERY_BY, DELIVERY_NOTES)
    VALUES
        (P_COMPANY, P_ENVIRONMENT, alert_ids, alert_count, 'EMAIL', P_RECIPIENT,
         subject, body, delivery_status, CURRENT_USER(),
         IFF(P_DRY_RUN, 'Dry-run replay package prepared; SYSTEM$SEND_EMAIL was not called.',
                       'Delivered through Snowflake email notification integration {integration}.'));

    UPDATE {db_safe}.{schema_safe}.{table_safe}
    SET
        DELIVERY_STATUS = delivery_status,
        DELIVERY_TARGET = P_RECIPIENT,
        EMAIL_TARGET = COALESCE(NULLIF(EMAIL_TARGET, ''), P_RECIPIENT),
        LAST_DELIVERY_AT = CURRENT_TIMESTAMP(),
        LAST_DELIVERY_BY = CURRENT_USER(),
        DELIVERY_LOG_COUNT = COALESCE(DELIVERY_LOG_COUNT, 0) + 1,
        LAST_STATUS_BY = CURRENT_USER(),
        LAST_STATUS_AT = CURRENT_TIMESTAMP()
    WHERE ARRAY_CONTAINS(ALERT_ID::VARIANT, alert_ids);

    RETURN 'OVERWATCH alert digest ' || delivery_status || ': ' || alert_count || ' alert(s) for ' || P_RECIPIENT;
END;
$$;"""


def _alert_delivery_related_filter(
    *,
    target: dict | None = None,
    alert_ids: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...], str]:
    """Return a safe bounded delivery-log predicate, preferring exact alert-id array matches."""
    target = target or {}
    explicit_values = [str(value).strip() for value in alert_ids if str(value or "").strip()]
    numeric_alert_ids = tuple(dict.fromkeys(value for value in explicit_values if re.fullmatch(r"\d+", value)))[:25]
    if numeric_alert_ids:
        predicates = [f"ARRAY_CONTAINS({int(value)}::VARIANT, ALERT_IDS)" for value in numeric_alert_ids]
        return f"AND {TARGET_PREDICATE_MARKER} (" + " OR ".join(predicates) + ")", numeric_alert_ids, "alert_ids"

    related_values = [value for value in explicit_values if value not in numeric_alert_ids]
    for key in ("evidence_id", "entity_id", "entity_name"):
        value = str(target.get(key) or "").strip()
        if value:
            related_values.append(value)
    related_values = tuple(dict.fromkeys(related_values))[:25]
    if not related_values:
        return "", (), "none"
    predicates = [
        f"EMAIL_SUBJECT ILIKE '%' || {sql_literal(value, 300)} || '%'"
        f" OR DELIVERY_NOTES ILIKE '%' || {sql_literal(value, 300)} || '%'"
        for value in related_values
    ]
    return f"AND {TARGET_PREDICATE_MARKER} (" + " OR ".join(f"({predicate})" for predicate in predicates) + ")", related_values, "text"


def load_alert_delivery_log(
    *,
    days: int = 14,
    limit: int = 100,
    section: str = "Alert Center",
    target: dict | None = None,
    alert_ids: tuple[str, ...] = (),
) -> pd.DataFrame:
    days = max(1, min(int(days), 365))
    limit = max(1, min(int(limit), 1000))
    related_filter, related_values, related_mode = _alert_delivery_related_filter(target=target, alert_ids=alert_ids)
    target_plan = build_target_predicate_plan(
        "Alert Center",
        target or {},
        available_columns=("ALERT_ID", "ALERT_KEY", "EVENT_ID", "ACTION_ID", "ENTITY_NAME"),
    ).with_fingerprint()
    target_label = evidence_target_label(target or {}) or (f"alert ids: {len(alert_ids)}" if alert_ids else "")
    target_columns = target_plan.columns_used or (("ALERT_IDS",) if related_values else ())
    target_hash = str(abs(hash((related_mode, tuple(related_values)))))[:10] if related_values else "none"
    return run_query(f"""
        SELECT
            DELIVERY_ID,
            DELIVERY_TS,
            COMPANY,
            ENVIRONMENT,
            ALERT_IDS,
            ALERT_COUNT,
            DELIVERY_METHOD,
            DELIVERY_TARGET,
            EMAIL_SUBJECT,
            DELIVERY_STATUS,
            DELIVERY_BY,
            DELIVERY_NOTES
        FROM {alert_delivery_log_fqn(quoted=True)}
        WHERE DELIVERY_TS >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {related_filter}
        ORDER BY DELIVERY_TS DESC
        LIMIT {limit}
    """,
        ttl_key=f"alert_delivery_log_{days}_{limit}_{target_hash}",
        tier="recent",
        section=section,
        max_rows=limit,
        query_boundary="evidence",
        target_label=target_label,
        target_context_present=bool(target or alert_ids),
        target_columns_used=target_columns,
        target_fallback_used=related_mode == "text",
        target_predicate_marker_present=bool(related_filter),
        target_predicate_plan_id=target_plan.plan_id or target_hash,
    )
