# sections/dba_tools_warehouse_settings.py - Review-only warehouse setting plans.

import pandas as pd

from sections.dba_tools_common import _as_bool, _as_int, _quote_identifier
from utils import sql_literal
from utils.dba_tool_catalog import SIZE_SQL as _SIZE_SQL

def _is_unknown_setting(value) -> bool:
    return value is None or str(value).strip().lower() in ("", "nan", "none", "null")


def _warehouse_size_sql(value) -> str:
    text = str(value or "").strip()
    if text in _SIZE_SQL:
        return _SIZE_SQL[text]
    compact = text.upper().replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "XSMALL": "XSMALL",
        "SMALL": "SMALL",
        "MEDIUM": "MEDIUM",
        "LARGE": "LARGE",
        "XLARGE": "XLARGE",
        "XXLARGE": "XXLARGE",
        "2XLARGE": "XXLARGE",
        "XXXLARGE": "XXXLARGE",
        "3XLARGE": "XXXLARGE",
        "X4LARGE": "X4LARGE",
        "4XLARGE": "X4LARGE",
        "X5LARGE": "X5LARGE",
        "5XLARGE": "X5LARGE",
        "X6LARGE": "X6LARGE",
        "6XLARGE": "X6LARGE",
    }
    return aliases.get(compact, compact or "XSMALL")


def _normalize_warehouse_setting(param: str, value) -> str:
    param = str(param or "").upper()
    if param == "WAREHOUSE_SIZE":
        return _warehouse_size_sql(value)
    if param in {"AUTO_RESUME", "ENABLE_QUERY_ACCELERATION"}:
        return "TRUE" if _as_bool(value) else "FALSE"
    if param == "SCALING_POLICY":
        return str(value or "STANDARD").upper()
    return str(_as_int(value, 0))


def _warehouse_setting_risk(param: str, current_sql: str, requested_sql: str) -> str:
    param = str(param or "").upper()
    if param == "WAREHOUSE_SIZE":
        return "Validate queue, spill, p95 runtime, and cost drivers before resizing."
    if param == "AUTO_SUSPEND" and requested_sql == "0":
        return "High cost risk: warehouse will never auto-suspend."
    if param == "AUTO_SUSPEND" and _as_int(requested_sql, 0) > 600:
        return "Cost risk: auto-suspend is above the 10-minute DBA guardrail."
    if param == "AUTO_RESUME" and requested_sql == "FALSE":
        return "Availability risk: users may see failures until the warehouse is resumed manually."
    if param == "MIN_CLUSTER_COUNT" and _as_int(requested_sql, 1) > 1:
        return "High cost risk: extra clusters can run continuously."
    if param == "MAX_CLUSTER_COUNT" and _as_int(requested_sql, 1) > 1:
        return "Burst cost risk: multi-cluster scaling can multiply credit burn."
    if param == "ENABLE_QUERY_ACCELERATION" and requested_sql == "TRUE":
        return "Serverless cost risk: QAS can add spend outside warehouse metering."
    if param == "QUERY_ACCELERATION_MAX_SCALE_FACTOR" and _as_int(requested_sql, 0) == 0:
        return "Serverless cost risk: QAS scale factor is unlimited."
    if param == "STATEMENT_TIMEOUT_IN_SECONDS" and requested_sql == "0":
        return "Runaway query risk: statements have no warehouse-level timeout."
    if param == "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS" and requested_sql == "0":
        return "Queue risk: statements can wait indefinitely."
    if param == "MAX_CONCURRENCY_LEVEL" and _as_int(requested_sql, 8) > 8:
        return "Pressure risk: higher concurrency can increase spill and p95 runtime."
    return "Review workload impact and status telemetry before applying."


def _warehouse_setting_review_gate(param: str, current_sql: str, requested_sql: str) -> dict:
    """Return review evidence for one changed warehouse setting."""
    param = str(param or "").upper()
    if param in {"STATEMENT_TIMEOUT_IN_SECONDS", "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"}:
        if requested_sql == "0":
            decision = "Timeout guardrail disabled"
            proof = "24h query runtime, queue, failure, and owner SLA telemetry plus rollback SQL."
            verify = "Watch for long-running or indefinitely queued queries after the change."
        elif current_sql == "0" or _as_int(requested_sql, 0) < _as_int(current_sql, 0):
            decision = "Timeout tightened"
            proof = "Representative workload runtime, queued-time distribution, owner SLA, and rollback SQL."
            verify = "Confirm expected queries are not cancelled or timed out after the change."
        else:
            decision = "Timeout loosened"
            proof = "Business reason for longer running/queued statements, recent failures, and rollback SQL."
            verify = "Confirm long-running statements remain intentional and queue pressure does not grow."
        return {
            "REVIEW_GATE": "Runaway/queue control",
            "REVIEW_DECISION": decision,
            "PROOF_REQUIRED": proof,
            "VERIFY_AFTER_CHANGE": verify,
        }
    if param in {"WAREHOUSE_SIZE", "MIN_CLUSTER_COUNT", "MAX_CLUSTER_COUNT", "SCALING_POLICY", "MAX_CONCURRENCY_LEVEL"}:
        return {
            "REVIEW_GATE": "Capacity control",
            "REVIEW_DECISION": "Capacity or concurrency setting",
            "PROOF_REQUIRED": "Queue, spill, p95 runtime, credit impact, workflow route, and rollback SQL.",
            "VERIFY_AFTER_CHANGE": "Compare queue, spill, p95 runtime, failures, and credits against the baseline window.",
        }
    if param in {"AUTO_SUSPEND", "AUTO_RESUME"}:
        return {
            "REVIEW_GATE": "Availability/cost control",
            "REVIEW_DECISION": "Suspend/resume policy",
            "PROOF_REQUIRED": "Idle burn, service sensitivity, auto-resume behavior, workflow route, and rollback SQL.",
            "VERIFY_AFTER_CHANGE": "Confirm idle credits fall without workload failures or manual resume incidents.",
        }
    if param in {"ENABLE_QUERY_ACCELERATION", "QUERY_ACCELERATION_MAX_SCALE_FACTOR"}:
        return {
            "REVIEW_GATE": "Serverless cost control",
            "REVIEW_DECISION": "Query Acceleration Service setting",
            "PROOF_REQUIRED": "Eligible query evidence, QAS credit exposure, workflow route, and rollback SQL.",
            "VERIFY_AFTER_CHANGE": "Track QAS credits, query runtime, and warehouse credits for the same workload.",
        }
    return {
        "REVIEW_GATE": "DBA review",
        "REVIEW_DECISION": "Warehouse setting change",
        "PROOF_REQUIRED": "Current setting, requested setting, workflow route, rollback SQL, and post-change telemetry.",
        "VERIFY_AFTER_CHANGE": "Compare the affected telemetry after the next complete workload window.",
    }


def _warehouse_settings_preflight_sql(warehouse_name: str) -> str:
    safe_wh = _quote_identifier(warehouse_name)
    wh_lit = sql_literal(warehouse_name, 300)
    return f"""-- Read-only pre-flight before ALTER WAREHOUSE
SELECT CURRENT_USER() AS current_user,
       CURRENT_ROLE() AS current_role,
       CURRENT_WAREHOUSE() AS current_warehouse;

SHOW GRANTS ON WAREHOUSE {safe_wh};

SHOW WAREHOUSES LIKE {wh_lit};

SELECT warehouse_name,
       SUM(credits_used) AS credits_7d,
       SUM(credits_used_compute) AS compute_credits_7d,
       SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits_7d
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
  AND warehouse_name = {wh_lit}
GROUP BY warehouse_name;

SELECT warehouse_name,
       COUNT(*) AS queries_24h,
       SUM(IFF(execution_status = 'FAILED', 1, 0)) AS failed_queries_24h,
       AVG(total_elapsed_time) / 1000 AS avg_elapsed_sec_24h,
       APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95) AS p95_elapsed_sec_24h
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
  AND warehouse_name = {wh_lit}
GROUP BY warehouse_name;

-- Confirm MODIFY privilege, status telemetry, workload impact, and rollback plan before applying.
"""


def _build_warehouse_setting_plan(
    warehouse_name: str,
    current_row: pd.Series,
    requested_settings: dict,
) -> dict:
    """Build a reviewed ALTER WAREHOUSE plan with rollback and audit context."""
    specs = [
        ("WAREHOUSE_SIZE", "size"),
        ("AUTO_SUSPEND", "auto_suspend"),
        ("AUTO_RESUME", "auto_resume"),
        ("STATEMENT_TIMEOUT_IN_SECONDS", "statement_timeout_in_seconds"),
        ("STATEMENT_QUEUED_TIMEOUT_IN_SECONDS", "statement_queued_timeout_in_seconds"),
        ("MAX_CONCURRENCY_LEVEL", "max_concurrency_level"),
        ("SCALING_POLICY", "scaling_policy"),
        ("MIN_CLUSTER_COUNT", "min_cluster_count"),
        ("MAX_CLUSTER_COUNT", "max_cluster_count"),
        ("ENABLE_QUERY_ACCELERATION", "enable_query_acceleration"),
        ("QUERY_ACCELERATION_MAX_SCALE_FACTOR", "query_acceleration_max_scale_factor"),
    ]
    changes = []
    skipped = []
    for param, column in specs:
        if param not in requested_settings:
            continue
        current_raw = current_row.get(column, None)
        if _is_unknown_setting(current_raw):
            skipped.append({
                "PARAMETER": param,
                "REASON": "Current value unavailable from SHOW WAREHOUSES; refresh metadata before changing this setting.",
            })
            continue
        current_sql = _normalize_warehouse_setting(param, current_raw)
        requested_sql = _normalize_warehouse_setting(param, requested_settings.get(param))
        if current_sql != requested_sql:
            gate = _warehouse_setting_review_gate(param, current_sql, requested_sql)
            changes.append({
                "PARAMETER": param,
                "CURRENT": current_sql,
                "REQUESTED": requested_sql,
                "RISK": _warehouse_setting_risk(param, current_sql, requested_sql),
                **gate,
            })

    safe_wh = _quote_identifier(warehouse_name)
    assignments = [f"{row['PARAMETER']} = {row['REQUESTED']}" for row in changes]
    rollback_assignments = [f"{row['PARAMETER']} = {row['CURRENT']}" for row in changes]
    alter_sql = ""
    rollback_sql = ""
    if assignments:
        alter_sql = f"ALTER WAREHOUSE {safe_wh} SET\n    " + "\n    ".join(assignments) + ";"
        rollback_sql = f"ALTER WAREHOUSE {safe_wh} SET\n    " + "\n    ".join(rollback_assignments) + ";"

    context_lines = [
        f"Warehouse: {warehouse_name}",
        "Change count: " + str(len(changes)),
    ]
    for row in changes:
        context_lines.append(
            f"{row['PARAMETER']}: {row['CURRENT']} -> {row['REQUESTED']} | "
            f"{row['REVIEW_GATE']} | {row['RISK']} | Proof: {row['PROOF_REQUIRED']}"
        )
    if rollback_sql:
        context_lines.append("Rollback plan: " + rollback_sql.replace("\n", " "))

    return {
        "warehouse": warehouse_name,
        "changes": changes,
        "skipped": skipped,
        "changes_df": pd.DataFrame(changes),
        "skipped_df": pd.DataFrame(skipped),
        "alter_sql": alter_sql,
        "rollback_sql": rollback_sql,
        "preflight_sql": _warehouse_settings_preflight_sql(warehouse_name),
        "confirmation_text": f"ALTER {warehouse_name}",
        "control_context": "\n".join(context_lines)[:4000],
    }
