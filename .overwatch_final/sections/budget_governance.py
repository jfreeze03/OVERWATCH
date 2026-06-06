# sections/budget_governance.py - Snowflake budget and AI quota governance
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE, DEFAULT_ALERT_EMAIL
from utils import (
    get_active_company,
    get_active_environment,
    get_ai_credit_price,
    get_credit_price,
    run_query,
    safe_float,
    safe_identifier,
    safe_int,
    sql_literal,
    format_snowflake_error,
)
from utils.workflows import (
    render_operator_briefing,
    render_priority_dataframe,
    render_signal_confidence,
)


BUDGET_GOVERNANCE_VERSION = "2026-06-02-summit-budget-controls-v1"
AI_BUDGET_TAG = "OVERWATCH_BUDGET_SCOPE"
AI_QUOTA_TABLE = "OVERWATCH_AI_USER_QUOTA"
AI_USAGE_VIEW = "OVERWATCH_AI_USER_MONTHLY_USAGE_V"
AI_QUOTA_ACTION_VIEW = "OVERWATCH_AI_USER_QUOTA_ACTIONS_V"
AI_QUOTA_TASK = "OVERWATCH_AI_QUOTA_REVIEW"
BUDGET_ACTION_PROC = "SP_OVERWATCH_BUDGET_CUSTOM_ACTION"
BUDGET_ACTION_BRIDGE = "OVERWATCH_BUDGET_ACTION_BRIDGE"


SUMMIT_CAPABILITIES = (
    {
        "CAPABILITY": "Cost Controls for AI",
        "STATE": "Ready to Deploy",
        "OVERWATCH_CONTROL": "Cortex budget cockpit, shared AI budget DDL, per-user quota action feed.",
        "SNOWFLAKE_NATIVE": "Custom budget, shared AI resources, Cortex AI usage history.",
        "STRICT_GAP": "Needs approved budget objects and verified email recipients before enforcement.",
        "DBA_NEXT_MOVE": "Create AI budgets, tag users, then queue over-budget users through the quota view.",
        "WEIGHT": 20,
    },
    {
        "CAPABILITY": "Org-Level Controls",
        "STATE": "Ready to Deploy",
        "OVERWATCH_CONTROL": "Account root budget runbook plus Cost & Contract 7d/YOY and action queue.",
        "SNOWFLAKE_NATIVE": "SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET methods.",
        "STRICT_GAP": "Account budget limit must be approved against the contract and renewal forecast.",
        "DBA_NEXT_MOVE": "Set the account budget limit and notification threshold after FinOps approval.",
        "WEIGHT": 16,
    },
    {
        "CAPABILITY": "Per-User Quota",
        "STATE": "Control Pattern",
        "OVERWATCH_CONTROL": "Monthly user quota table, usage rollup, enforcement SQL, and action queue bridge.",
        "SNOWFLAKE_NATIVE": "Cortex user grants and Cortex AI Function usage history.",
        "STRICT_GAP": "Requires revoking PUBLIC Cortex access and routing AI access through a controlled role.",
        "DBA_NEXT_MOVE": "Deploy quota table and run dry-run enforcement before enabling revokes.",
        "WEIGHT": 18,
    },
    {
        "CAPABILITY": "Shared Resource Budgets",
        "STATE": "Ready to Deploy",
        "OVERWATCH_CONTROL": "Shared AI budget DDL for AI FUNCTION, CORTEX CODE, CORTEX AGENT, and SNOWFLAKE INTELLIGENCE.",
        "SNOWFLAKE_NATIVE": "SET_USER_TAGS and ADD_SHARED_RESOURCE.",
        "STRICT_GAP": "Only tagged users count against shared resources, so user tag hygiene is mandatory.",
        "DBA_NEXT_MOVE": "Create budget tag, tag approved users, and verify GET_SHARED_RESOURCES.",
        "WEIGHT": 18,
    },
    {
        "CAPABILITY": "Budget Custom Actions",
        "STATE": "Ready to Deploy",
        "OVERWATCH_CONTROL": "Owner-rights procedure that writes budget threshold events into OVERWATCH_ACTION_QUEUE.",
        "SNOWFLAKE_NATIVE": "ADD_CUSTOM_ACTION with PROJECTED and ACTUAL thresholds.",
        "STRICT_GAP": "Procedure reference and SNOWFLAKE application grants must be validated after deployment.",
        "DBA_NEXT_MOVE": "Attach projected 75% and actual 90% custom actions to each custom budget.",
        "WEIGHT": 18,
    },
    {
        "CAPABILITY": "Anomaly Explanations",
        "STATE": "Partial",
        "OVERWATCH_CONTROL": "Budget action bridge captures threshold, budget, scope, owner route, and proof SQL.",
        "SNOWFLAKE_NATIVE": "Budget notifications plus spending history; OVERWATCH adds DBA explanation context.",
        "STRICT_GAP": "Root-cause explanation quality depends on budget events being joined to Cost Explorer and Cortex facts.",
        "DBA_NEXT_MOVE": "Use budget custom actions to create explainable budget incidents in Alert Center and Cost & Contract.",
        "WEIGHT": 14,
    },
)


def _budget_db_schema(db: str = ALERT_DB, schema: str = ALERT_SCHEMA) -> tuple[str, str]:
    return safe_identifier(db), safe_identifier(schema)


def _object_fqn(db: str, schema: str, name: str) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(name)}"


def _company_targets(company: str) -> list[str]:
    value = str(company or "ALFA").strip().upper()
    if value == "ALL":
        return ["ALFA", "TREXIS"]
    if value == "TREXIS":
        return ["TREXIS"]
    return ["ALFA"]


def _default_ai_budget_usd(company: str) -> float:
    value = str(company or "ALFA").strip().upper()
    if value == "TREXIS":
        return 1500.0
    if value == "ALL":
        return 5000.0
    return 3500.0


def _budget_governance_score(board: pd.DataFrame) -> dict:
    if board is None or board.empty:
        return {"score": 0, "ready": 0, "pattern": 0, "partial": 0, "gap": 0}
    weights = pd.to_numeric(board.get("WEIGHT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    total_weight = max(float(weights.sum()), 1.0)
    state_score = {
        "READY TO DEPLOY": 1.0,
        "IMPLEMENTED": 1.0,
        "CONTROL PATTERN": 0.78,
        "PARTIAL": 0.55,
        "GAP": 0.0,
    }
    states = board.get("STATE", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
    score = int(round(sum(weights.iloc[idx] * state_score.get(states.iloc[idx], 0.35) for idx in range(len(board))) / total_weight * 100))
    return {
        "score": max(0, min(100, score)),
        "ready": int(states.isin(["READY TO DEPLOY", "IMPLEMENTED"]).sum()),
        "pattern": int(states.eq("CONTROL PATTERN").sum()),
        "partial": int(states.eq("PARTIAL").sum()),
        "gap": int(states.eq("GAP").sum()),
    }


def _build_budget_governance_board() -> tuple[dict, pd.DataFrame]:
    board = pd.DataFrame(SUMMIT_CAPABILITIES)
    board["_STATE_RANK"] = board["STATE"].map({
        "Gap": 0,
        "Partial": 1,
        "Control Pattern": 2,
        "Ready to Deploy": 3,
        "Implemented": 4,
    }).fillna(9)
    return _budget_governance_score(board), board.sort_values(["_STATE_RANK", "CAPABILITY"]).drop(columns=["_STATE_RANK"]).reset_index(drop=True)


def _build_budget_policy_frame(
    company: str,
    credit_price: float,
    *,
    ai_credit_price: float | None = None,
    ai_budget_usd: float | None = None,
    per_user_limit_usd: float = 250.0,
    account_budget_usd: float | None = None,
    email_target: str = DEFAULT_ALERT_EMAIL,
) -> pd.DataFrame:
    credits_per_dollar = 1 / max(safe_float(credit_price), 0.01)
    ai_credits_per_dollar = 1 / max(safe_float(ai_credit_price, 2.20), 0.01)
    ai_budget = safe_float(ai_budget_usd) or _default_ai_budget_usd(company)
    per_user = max(safe_float(per_user_limit_usd), 1.0)
    account_budget = safe_float(account_budget_usd) if account_budget_usd is not None else max(ai_budget * 10, 25000.0)
    rows: list[dict] = []

    for idx, target in enumerate(_company_targets(company), start=1):
        label = "Trexis" if target == "TREXIS" else "ALFA"
        tag_value = f"{target}_AI"
        budget_name = safe_identifier(f"{target}_AI_SHARED_BUDGET")
        rows.append({
            "PRIORITY": idx,
            "CONTROL": f"{label} shared AI resource budget",
            "SCOPE": label,
            "BUDGET_NAME": budget_name,
            "TAG_VALUE": tag_value,
            "CONTROL_TYPE": "SHARED_AI_RESOURCE_BUDGET",
            "MONTHLY_LIMIT_USD": round(ai_budget / len(_company_targets(company)), 2),
            "MONTHLY_LIMIT_CREDITS": round((ai_budget / len(_company_targets(company))) * ai_credits_per_dollar, 2),
            "CREDIT_TYPE": "Cortex AI credits",
            "RATE_USD": round(1 / ai_credits_per_dollar, 2),
            "TRIGGER": "Projected 75%, actual 90%",
            "SNOWFLAKE_NATIVE_METHOD": "CREATE BUDGET, SET_USER_TAGS, ADD_SHARED_RESOURCE",
            "OVERWATCH_ACTION": "Route threshold event to action queue and Cortex spend cockpit.",
            "ALERT_TARGET": email_target,
            "OWNER": "DBA / FinOps",
            "STATUS": "Ready to Deploy",
        })
        rows.append({
            "PRIORITY": idx + 10,
            "CONTROL": f"{label} per-user AI monthly quota",
            "SCOPE": label,
            "BUDGET_NAME": f"{target}_AI_USER_QUOTA",
            "TAG_VALUE": tag_value,
            "CONTROL_TYPE": "PER_USER_AI_QUOTA",
            "MONTHLY_LIMIT_USD": round(per_user, 2),
            "MONTHLY_LIMIT_CREDITS": round(per_user * ai_credits_per_dollar, 2),
            "CREDIT_TYPE": "Cortex AI credits",
            "RATE_USD": round(1 / ai_credits_per_dollar, 2),
            "TRIGGER": "User actual usage over monthly quota",
            "SNOWFLAKE_NATIVE_METHOD": "Cortex usage history plus controlled SNOWFLAKE.CORTEX_USER grants",
            "OVERWATCH_ACTION": "Queue revoke/restore review SQL; enforcement stays dry-run until approved.",
            "ALERT_TARGET": email_target,
            "OWNER": "DBA / AI Governance",
            "STATUS": "Control Pattern",
        })

    rows.append({
        "PRIORITY": 50,
        "CONTROL": "Account root budget",
        "SCOPE": "ALL",
        "BUDGET_NAME": "SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET",
        "TAG_VALUE": "ALL",
        "CONTROL_TYPE": "ACCOUNT_ROOT_BUDGET",
        "MONTHLY_LIMIT_USD": round(account_budget, 2),
        "MONTHLY_LIMIT_CREDITS": round(account_budget * credits_per_dollar, 2),
        "CREDIT_TYPE": "Snowflake credits",
        "RATE_USD": round(1 / credits_per_dollar, 2),
        "TRIGGER": "Projected 75%",
        "SNOWFLAKE_NATIVE_METHOD": "ACCOUNT_ROOT_BUDGET SET_SPENDING_LIMIT",
        "OVERWATCH_ACTION": "Use Cost & Contract 7d/YOY and queue to explain movement.",
        "ALERT_TARGET": email_target,
        "OWNER": "DBA / FinOps",
        "STATUS": "Ready to Deploy",
    })
    rows.append({
        "PRIORITY": 60,
        "CONTROL": "Budget custom action bridge",
        "SCOPE": "ALL",
        "BUDGET_NAME": BUDGET_ACTION_PROC,
        "TAG_VALUE": "ALL",
        "CONTROL_TYPE": "CUSTOM_ACTION_BRIDGE",
        "MONTHLY_LIMIT_USD": 0.0,
        "MONTHLY_LIMIT_CREDITS": 0.0,
        "CREDIT_TYPE": "N/A",
        "RATE_USD": 0.0,
        "TRIGGER": "Budget projected/actual threshold",
        "SNOWFLAKE_NATIVE_METHOD": "ADD_CUSTOM_ACTION",
        "OVERWATCH_ACTION": "Insert budget event into OVERWATCH_ACTION_QUEUE with proof query.",
        "ALERT_TARGET": email_target,
        "OWNER": "DBA / FinOps",
        "STATUS": "Ready to Deploy",
    })
    return pd.DataFrame(rows).sort_values(["PRIORITY", "CONTROL"]).reset_index(drop=True)


def _build_native_budget_sql(
    policy: pd.DataFrame,
    *,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    email_target: str = DEFAULT_ALERT_EMAIL,
    notification_integration: str = "OVERWATCH_EMAIL_INT",
) -> str:
    db_safe, schema_safe = _budget_db_schema(db, schema)
    tag_fqn = _object_fqn(db_safe, schema_safe, AI_BUDGET_TAG)
    email = sql_literal(email_target, 500)
    integration = safe_identifier(notification_integration)
    lines = [
        "-- Snowflake native budget control setup for OVERWATCH.",
        "-- Review limits with FinOps before running. Email recipients must be verified in Snowflake.",
        f"CREATE DATABASE IF NOT EXISTS {db_safe};",
        f"CREATE SCHEMA IF NOT EXISTS {db_safe}.{schema_safe};",
        f"CREATE TAG IF NOT EXISTS {tag_fqn};",
        f"-- Optional if using notification integration {integration}:",
        f"-- GRANT USAGE ON INTEGRATION {integration} TO APPLICATION SNOWFLAKE;",
        "",
        "-- Account-level guardrail.",
    ]

    if isinstance(policy, pd.DataFrame) and not policy.empty:
        account = policy[policy.get("CONTROL_TYPE", "").astype(str).eq("ACCOUNT_ROOT_BUDGET")]
    else:
        account = pd.DataFrame()
    if not account.empty:
        row = account.iloc[0]
        account_credits = max(safe_float(row.get("MONTHLY_LIMIT_CREDITS")), 1.0)
        lines.extend([
            f"CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!SET_SPENDING_LIMIT({account_credits:.2f});",
            "CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!SET_NOTIFICATION_THRESHOLD(75);",
            f"CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!SET_EMAIL_NOTIFICATIONS({email});",
            "CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!GET_CONFIG();",
            "",
        ])

    budget_rows = policy[policy.get("CONTROL_TYPE", "").astype(str).eq("SHARED_AI_RESOURCE_BUDGET")] if isinstance(policy, pd.DataFrame) and not policy.empty else pd.DataFrame()
    for _, row in budget_rows.iterrows():
        budget_fqn = _object_fqn(db_safe, schema_safe, str(row.get("BUDGET_NAME") or "OVERWATCH_AI_SHARED_BUDGET"))
        credits = max(safe_float(row.get("MONTHLY_LIMIT_CREDITS")), 1.0)
        tag_value = str(row.get("TAG_VALUE") or "AI").upper()
        lines.extend([
            f"-- {row.get('CONTROL', 'Shared AI resource budget')}",
            f"CREATE SNOWFLAKE.CORE.BUDGET IF NOT EXISTS {budget_fqn}();",
            f"CALL {budget_fqn}!SET_SPENDING_LIMIT({credits:.2f});",
            f"CALL {budget_fqn}!SET_NOTIFICATION_THRESHOLD(75);",
            f"CALL {budget_fqn}!SET_EMAIL_NOTIFICATIONS({email});",
            f"CALL {budget_fqn}!SET_USER_TAGS(",
            "  [",
            f"    [(SELECT SYSTEM$REFERENCE('TAG', '{tag_fqn}', 'SESSION', 'APPLYBUDGET')), {sql_literal(tag_value, 100)}]",
            "  ],",
            "  'UNION');",
            f"CALL {budget_fqn}!ADD_SHARED_RESOURCE('AI FUNCTION');",
            f"CALL {budget_fqn}!ADD_SHARED_RESOURCE('CORTEX CODE');",
            f"CALL {budget_fqn}!ADD_SHARED_RESOURCE('CORTEX AGENT');",
            f"CALL {budget_fqn}!ADD_SHARED_RESOURCE('SNOWFLAKE INTELLIGENCE');",
            f"CALL {budget_fqn}!GET_BUDGET_SCOPE();",
            f"CALL {budget_fqn}!GET_SHARED_RESOURCES();",
            f"-- Example after approval: ALTER USER <USER_NAME> SET TAG {tag_fqn} = {sql_literal(tag_value, 100)};",
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def _build_per_user_quota_sql(
    *,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    quota_table: str = AI_QUOTA_TABLE,
    ai_role: str = "OVERWATCH_AI_FUNCTIONS_USER_ROLE",
    default_limit_usd: float = 250.0,
    credit_price: float | None = None,
    ai_credit_price: float | None = None,
) -> str:
    db_safe, schema_safe = _budget_db_schema(db, schema)
    quota_fqn = _object_fqn(db_safe, schema_safe, quota_table)
    usage_fqn = _object_fqn(db_safe, schema_safe, AI_USAGE_VIEW)
    actions_fqn = _object_fqn(db_safe, schema_safe, AI_QUOTA_ACTION_VIEW)
    queue_fqn = _object_fqn(db_safe, schema_safe, ACTION_QUEUE_TABLE)
    role_safe = safe_identifier(ai_role)
    task_fqn = _object_fqn(db_safe, schema_safe, AI_QUOTA_TASK)
    ai_rate = safe_float(ai_credit_price, safe_float(credit_price, 2.20))
    limit_usd = max(safe_float(default_limit_usd), 1.0)
    limit_credits = limit_usd / max(ai_rate, 0.01)
    return f"""-- Per-user Cortex AI monthly quota pattern.
-- Dry-run first. Enforcement only works if PUBLIC no longer has blanket Cortex access.
CREATE DATABASE IF NOT EXISTS {db_safe};
CREATE SCHEMA IF NOT EXISTS {db_safe}.{schema_safe};

CREATE ROLE IF NOT EXISTS {role_safe};
REVOKE DATABASE ROLE SNOWFLAKE.CORTEX_USER FROM ROLE PUBLIC;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE {role_safe};

CREATE TABLE IF NOT EXISTS {quota_fqn} (
    USER_NAME VARCHAR PRIMARY KEY,
    COMPANY VARCHAR(100),
    MONTHLY_LIMIT_USD FLOAT DEFAULT {limit_usd:.2f},
    MONTHLY_LIMIT_CREDITS FLOAT DEFAULT {limit_credits:.4f},
    ENFORCEMENT_STATE VARCHAR(40) DEFAULT 'Monitor',
    OWNER VARCHAR(200) DEFAULT 'DBA / AI Governance',
    APPROVER VARCHAR(200) DEFAULT 'FinOps Lead / DBA Lead',
    EXEMPTION_REASON VARCHAR(2000),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE VIEW {usage_fqn} AS
WITH cortex_code AS (
    SELECT
        COALESCE(u.NAME, TO_VARCHAR(c.USER_ID), 'UNKNOWN') AS USER_NAME,
        'CORTEX CODE' AS USAGE_SOURCE,
        c.USAGE_TIME AS USAGE_TS,
        COALESCE(c.TOKEN_CREDITS, 0) AS CREDITS_USED
    FROM (
        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
        UNION ALL
        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
    ) c
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
    WHERE c.USAGE_TIME >= DATE_TRUNC('MONTH', CURRENT_DATE())
),
ai_functions AS (
    SELECT
        COALESCE(u.NAME, TO_VARCHAR(f.USER_ID), 'UNKNOWN') AS USER_NAME,
        'AI FUNCTION' AS USAGE_SOURCE,
        f.START_TIME AS USAGE_TS,
        COALESCE(f.CREDITS, 0) AS CREDITS_USED
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY f
    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON f.USER_ID = u.USER_ID
    WHERE f.START_TIME >= DATE_TRUNC('MONTH', CURRENT_DATE())
)
SELECT
    USER_NAME,
    MIN(USAGE_TS) AS FIRST_USAGE_TS,
    MAX(USAGE_TS) AS LAST_USAGE_TS,
    COUNT(*) AS REQUESTS,
    ROUND(SUM(CREDITS_USED), 6) AS MONTHLY_CREDITS,
    ROUND(SUM(CREDITS_USED) * {ai_rate:.4f}, 2) AS MONTHLY_COST_USD,
    LISTAGG(DISTINCT USAGE_SOURCE, ', ') WITHIN GROUP (ORDER BY USAGE_SOURCE) AS USAGE_SOURCES
FROM (
    SELECT * FROM cortex_code
    UNION ALL
    SELECT * FROM ai_functions
)
GROUP BY USER_NAME;

CREATE OR REPLACE VIEW {actions_fqn} AS
SELECT
    u.USER_NAME,
    q.COMPANY,
    q.MONTHLY_LIMIT_USD,
    q.MONTHLY_LIMIT_CREDITS,
    u.MONTHLY_COST_USD,
    u.MONTHLY_CREDITS,
    u.FIRST_USAGE_TS,
    u.LAST_USAGE_TS,
    u.USAGE_SOURCES,
    CASE
        WHEN u.MONTHLY_CREDITS >= q.MONTHLY_LIMIT_CREDITS THEN 'Over Quota'
        WHEN u.MONTHLY_CREDITS >= q.MONTHLY_LIMIT_CREDITS * 0.80 THEN 'Near Quota'
        ELSE 'Within Quota'
    END AS QUOTA_STATE,
    'REVOKE ROLE {role_safe} FROM USER ' || USER_NAME || ';' AS ENFORCEMENT_SQL,
    'GRANT ROLE {role_safe} TO USER ' || USER_NAME || ';' AS RESTORE_SQL
FROM {usage_fqn} u
JOIN {quota_fqn} q
  ON UPPER(q.USER_NAME) = UPPER(u.USER_NAME)
WHERE COALESCE(q.ENFORCEMENT_STATE, 'Monitor') <> 'Exempt';

CREATE OR REPLACE TASK {task_fqn}
    WAREHOUSE = COMPUTE_WH
    SCHEDULE = 'USING CRON 5 * * * * America/Chicago'
AS
INSERT INTO {queue_fqn} (
    ACTION_ID, SOURCE, CATEGORY, SEVERITY, ENTITY_TYPE, ENTITY_NAME, OWNER, STATUS,
    FINDING, RECOMMENDED_ACTION, GENERATED_SQL_FIX, PROOF_QUERY, COMPANY, ENVIRONMENT,
    APPROVER, OWNER_APPROVAL_STATUS, RECOVERY_SLA_STATE, RECOVERY_SLA_TARGET_HOURS
)
SELECT
    SHA1_HEX('AI_QUOTA|' || USER_NAME || '|' || QUOTA_STATE),
    'Cost & Contract - Budget Governance',
    'AI Cost Control',
    IFF(QUOTA_STATE = 'Over Quota', 'High', 'Medium'),
    'USER',
    USER_NAME,
    'DBA / AI Governance',
    'New',
    QUOTA_STATE || ': ' || USER_NAME || ' has used $' || MONTHLY_COST_USD || ' against monthly quota $' || MONTHLY_LIMIT_USD,
    'Review usage source, owner approval, and whether to revoke AI access until next monthly cycle.',
    ENFORCEMENT_SQL || '\\n-- Restore after approval or new month:\\n' || RESTORE_SQL,
    'SELECT * FROM {actions_fqn} WHERE USER_NAME = ''' || REPLACE(USER_NAME, '''', '''''') || ''';',
    COALESCE(COMPANY, 'ALL'),
    'No Database Context',
    'FinOps Lead / DBA Lead',
    'Requested',
    'AI Quota Review',
    24
FROM {actions_fqn}
WHERE QUOTA_STATE IN ('Near Quota', 'Over Quota')
  AND NOT EXISTS (
      SELECT 1
      FROM {queue_fqn} q
      WHERE q.ACTION_ID = SHA1_HEX('AI_QUOTA|' || USER_NAME || '|' || QUOTA_STATE)
        AND UPPER(COALESCE(q.STATUS, 'New')) NOT IN ('FIXED', 'IGNORED')
  );

-- Review generated ENFORCEMENT_SQL before executing any revokes.
-- Resume after dry-run review: ALTER TASK {task_fqn} RESUME;
"""


def _build_budget_custom_action_sql(
    policy: pd.DataFrame,
    *,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    email_target: str = DEFAULT_ALERT_EMAIL,
) -> str:
    db_safe, schema_safe = _budget_db_schema(db, schema)
    proc_fqn = _object_fqn(db_safe, schema_safe, BUDGET_ACTION_PROC)
    queue_fqn = _object_fqn(db_safe, schema_safe, ACTION_QUEUE_TABLE)
    bridge_fqn = _object_fqn(db_safe, schema_safe, BUDGET_ACTION_BRIDGE)
    email = sql_literal(email_target, 500)
    lines = [f"""-- Budget custom action bridge. Creates action queue incidents when native Snowflake budgets cross thresholds.
CREATE DATABASE IF NOT EXISTS {db_safe};
CREATE SCHEMA IF NOT EXISTS {db_safe}.{schema_safe};

CREATE TABLE IF NOT EXISTS {bridge_fqn} (
    EVENT_ID VARCHAR(64) PRIMARY KEY,
    EVENT_TS TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    BUDGET_NAME VARCHAR(500),
    BUDGET_SCOPE VARCHAR(200),
    TRIGGER_TYPE VARCHAR(40),
    THRESHOLD NUMBER,
    RECIPIENT VARCHAR(500),
    ACTION_QUEUE_ID VARCHAR(64),
    EVENT_STATUS VARCHAR(40),
    EVENT_NOTES VARCHAR(4000)
);

CREATE OR REPLACE PROCEDURE {proc_fqn}(
    P_BUDGET_NAME VARCHAR,
    P_BUDGET_SCOPE VARCHAR,
    P_TRIGGER_TYPE VARCHAR,
    P_THRESHOLD NUMBER,
    P_RECIPIENT VARCHAR DEFAULT {email},
    P_DRY_RUN BOOLEAN DEFAULT TRUE
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    event_id VARCHAR DEFAULT SHA1_HEX('BUDGET|' || COALESCE(P_BUDGET_NAME, '') || '|' || COALESCE(P_TRIGGER_TYPE, '') || '|' || COALESCE(P_THRESHOLD::VARCHAR, ''));
    severity VARCHAR DEFAULT IFF(UPPER(COALESCE(P_TRIGGER_TYPE, 'PROJECTED')) = 'ACTUAL' OR P_THRESHOLD >= 90, 'Critical', 'High');
BEGIN
    INSERT INTO {bridge_fqn} (
        EVENT_ID, BUDGET_NAME, BUDGET_SCOPE, TRIGGER_TYPE, THRESHOLD, RECIPIENT,
        ACTION_QUEUE_ID, EVENT_STATUS, EVENT_NOTES
    )
    SELECT
        event_id, P_BUDGET_NAME, P_BUDGET_SCOPE, P_TRIGGER_TYPE, P_THRESHOLD, P_RECIPIENT,
        event_id, IFF(P_DRY_RUN, 'DRY_RUN', 'QUEUED'),
        'Snowflake budget custom action invoked. Review Cost & Contract and budget spending history.'
    WHERE NOT EXISTS (SELECT 1 FROM {bridge_fqn} WHERE EVENT_ID = event_id);

    INSERT INTO {queue_fqn} (
        ACTION_ID, SOURCE, CATEGORY, SEVERITY, ENTITY_TYPE, ENTITY_NAME, OWNER, STATUS,
        FINDING, RECOMMENDED_ACTION, EST_MONTHLY_SAVINGS, GENERATED_SQL_FIX, PROOF_QUERY,
        COMPANY, ENVIRONMENT, APPROVER, OWNER_APPROVAL_STATUS, RECOVERY_SLA_STATE,
        RECOVERY_SLA_TARGET_HOURS, OWNER_EMAIL, APPROVAL_GROUP, OWNER_SOURCE, OWNER_EVIDENCE
    )
    SELECT
        event_id,
        'Cost & Contract - Budget Governance',
        'Budget Control',
        severity,
        'BUDGET',
        P_BUDGET_NAME,
        'DBA / FinOps',
        'New',
        'Budget ' || P_BUDGET_NAME || ' crossed ' || P_TRIGGER_TYPE || ' threshold ' || P_THRESHOLD || '% for ' || COALESCE(P_BUDGET_SCOPE, 'ALL') || '.',
        'Explain the budget movement, confirm owner demand, and decide whether to throttle AI access, suspend non-critical workloads, or raise the limit with approval.',
        0,
        'CALL ' || P_BUDGET_NAME || '!GET_SPENDING_HISTORY();\\nCALL ' || P_BUDGET_NAME || '!GET_CONFIG();\\nCALL ' || P_BUDGET_NAME || '!GET_CUSTOM_ACTIONS();',
        'SELECT * FROM {bridge_fqn} WHERE EVENT_ID = ''' || event_id || ''';',
        IFF(UPPER(COALESCE(P_BUDGET_SCOPE, 'ALL')) LIKE '%TREXIS%', 'Trexis', IFF(UPPER(COALESCE(P_BUDGET_SCOPE, 'ALL')) LIKE '%ALFA%', 'ALFA', 'ALL')),
        'No Database Context',
        'FinOps Lead / DBA Lead',
        'Requested',
        'Budget Threshold Review',
        24,
        P_RECIPIENT,
        'DBA Lead / FinOps Lead',
        'SNOWFLAKE_BUDGET_CUSTOM_ACTION',
        'Native budget threshold event captured by OVERWATCH custom action bridge.'
    WHERE NOT EXISTS (
        SELECT 1 FROM {queue_fqn} q
        WHERE q.ACTION_ID = event_id
          AND UPPER(COALESCE(q.STATUS, 'New')) NOT IN ('FIXED', 'IGNORED')
    );

    RETURN IFF(P_DRY_RUN, 'Budget custom action dry-run captured: ' || event_id, 'Budget custom action queued: ' || event_id);
END;
$$;

GRANT USAGE ON PROCEDURE {proc_fqn}(VARCHAR, VARCHAR, VARCHAR, NUMBER, VARCHAR, BOOLEAN) TO APPLICATION SNOWFLAKE;
"""]

    budget_rows = policy[policy.get("CONTROL_TYPE", "").astype(str).eq("SHARED_AI_RESOURCE_BUDGET")] if isinstance(policy, pd.DataFrame) and not policy.empty else pd.DataFrame()
    for _, row in budget_rows.iterrows():
        budget_fqn = _object_fqn(db_safe, schema_safe, str(row.get("BUDGET_NAME") or "OVERWATCH_AI_SHARED_BUDGET"))
        scope = str(row.get("TAG_VALUE") or row.get("SCOPE") or "AI")
        lines.extend([
            f"-- Attach projected and actual custom actions to {budget_fqn}.",
            f"CALL {budget_fqn}!ADD_CUSTOM_ACTION(",
            f"  SYSTEM$REFERENCE('PROCEDURE', '{proc_fqn}(VARCHAR, VARCHAR, VARCHAR, NUMBER, VARCHAR, BOOLEAN)', 'SESSION', 'USAGE'),",
            f"  ARRAY_CONSTRUCT('{budget_fqn}', {sql_literal(scope, 200)}, 'PROJECTED', 75, {email}, TRUE),",
            "  'PROJECTED',",
            "  75);",
            f"CALL {budget_fqn}!ADD_CUSTOM_ACTION(",
            f"  SYSTEM$REFERENCE('PROCEDURE', '{proc_fqn}(VARCHAR, VARCHAR, VARCHAR, NUMBER, VARCHAR, BOOLEAN)', 'SESSION', 'USAGE'),",
            f"  ARRAY_CONSTRUCT('{budget_fqn}', {sql_literal(scope, 200)}, 'ACTUAL', 90, {email}, TRUE),",
            "  'ACTUAL',",
            "  90);",
            f"CALL {budget_fqn}!GET_CUSTOM_ACTIONS();",
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def _build_budget_inventory_sql(db: str = ALERT_DB, schema: str = ALERT_SCHEMA) -> str:
    db_safe, schema_safe = _budget_db_schema(db, schema)
    return f"""
SELECT SYSTEM$SHOW_BUDGETS_IN_ACCOUNT() AS BUDGETS_IN_ACCOUNT;
CALL SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET!GET_CONFIG();
-- For each custom budget returned above, run:
-- CALL {db_safe}.{schema_safe}.<BUDGET_NAME>!GET_CONFIG();
-- CALL {db_safe}.{schema_safe}.<BUDGET_NAME>!GET_SPENDING_HISTORY();
-- CALL {db_safe}.{schema_safe}.<BUDGET_NAME>!GET_SHARED_RESOURCES();
-- CALL {db_safe}.{schema_safe}.<BUDGET_NAME>!GET_CUSTOM_ACTIONS();
""".strip()


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    credit_price = safe_float(get_credit_price()) or 3.68
    ai_credit_price = safe_float(get_ai_credit_price()) or 2.20
    summary, board = _build_budget_governance_board()

    render_signal_confidence(
        source="Snowflake Budgets + ACCOUNT_USAGE",
        confidence="governed",
        scope_note="Budget controls are generated for DBA review; no budget DDL runs from this page.",
    )
    render_operator_briefing(
        [
            ("Native control", "Use Snowflake Budgets for spend thresholds and shared AI resources."),
            ("DBA control", "Use OVERWATCH for routing, approval, anomaly explanation, and quota review."),
            ("AI access", "Per-user quotas require Cortex access through a controlled role."),
            ("Alert path", f"Email-first target: {DEFAULT_ALERT_EMAIL}."),
        ],
        title="Budget Governance Brief",
        columns=4,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Native Ready", f"{summary['ready']:,}")
    c2.metric("Patterns", f"{summary['pattern']:,}")
    c3.metric("Partial", f"{summary['partial']:,}", delta_color="inverse")
    c4.metric("Controls", f"{len(board):,}")

    policy_defaults = _default_ai_budget_usd(company)
    p1, p2, p3 = st.columns(3)
    with p1:
        ai_budget_usd = st.number_input(
            "AI shared budget",
            min_value=100.0,
            value=float(policy_defaults),
            step=100.0,
            format="%.2f",
            key="budget_governance_ai_budget_usd",
        )
    with p2:
        per_user_limit_usd = st.number_input(
            "Per-user AI quota",
            min_value=10.0,
            value=250.0,
            step=25.0,
            format="%.2f",
            key="budget_governance_user_quota_usd",
        )
    with p3:
        budget_email = st.text_input(
            "Budget email",
            value=DEFAULT_ALERT_EMAIL,
            key="budget_governance_email_target",
        )

    policy = _build_budget_policy_frame(
        company,
        credit_price,
        ai_credit_price=ai_credit_price,
        ai_budget_usd=safe_float(ai_budget_usd),
        per_user_limit_usd=safe_float(per_user_limit_usd),
        email_target=budget_email,
    )

    render_priority_dataframe(
        board,
        title="Summit capability coverage",
        priority_columns=["STATE", "CAPABILITY", "OVERWATCH_CONTROL", "STRICT_GAP", "DBA_NEXT_MOVE"],
        sort_by=["STATE", "CAPABILITY"],
        ascending=[True, True],
        raw_label="All budget governance capabilities",
        max_rows=6,
        height=260,
    )

    st.markdown("**Budget Policies**")
    render_priority_dataframe(
        policy,
        title=f"{company} budget policy map ({environment})",
        priority_columns=[
            "STATUS", "CONTROL", "SCOPE", "MONTHLY_LIMIT_USD", "MONTHLY_LIMIT_CREDITS",
            "CREDIT_TYPE", "RATE_USD",
            "TRIGGER", "SNOWFLAKE_NATIVE_METHOD", "OVERWATCH_ACTION",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All budget policy rows",
        max_rows=8,
        height=300,
    )

    with st.expander("Deployment SQL", expanded=False):
        sql_view = st.selectbox(
            "SQL package",
            ["Native budgets", "Per-user quota", "Custom actions", "Inventory check"],
            key="budget_governance_sql_package",
        )
        if sql_view == "Native budgets":
            st.code(_build_native_budget_sql(policy, email_target=budget_email), language="sql")
        elif sql_view == "Per-user quota":
            st.code(
                _build_per_user_quota_sql(
                    default_limit_usd=safe_float(per_user_limit_usd),
                    ai_credit_price=ai_credit_price,
                ),
                language="sql",
            )
        elif sql_view == "Custom actions":
            st.code(_build_budget_custom_action_sql(policy, email_target=budget_email), language="sql")
        else:
            st.code(_build_budget_inventory_sql(), language="sql")

    with st.expander("Live budget inventory", expanded=False):
        if st.button("Load Budget Inventory", key="budget_governance_load_inventory"):
            try:
                st.session_state["budget_governance_inventory"] = run_query(
                    "SELECT SYSTEM$SHOW_BUDGETS_IN_ACCOUNT() AS BUDGETS_IN_ACCOUNT",
                    ttl_key="budget_governance_inventory",
                    tier="recent",
                    section="Cost & Contract",
                )
                st.session_state["budget_governance_inventory_error"] = ""
            except Exception as exc:
                st.session_state["budget_governance_inventory"] = pd.DataFrame()
                st.session_state["budget_governance_inventory_error"] = format_snowflake_error(exc)
        err = st.session_state.get("budget_governance_inventory_error", "")
        if err:
            st.warning(f"Budget inventory unavailable: {err}")
        inventory = st.session_state.get("budget_governance_inventory")
        if isinstance(inventory, pd.DataFrame) and not inventory.empty:
            st.dataframe(inventory, width="stretch", hide_index=True)
        else:
            st.caption("Inventory is optional and only runs when loaded.")
