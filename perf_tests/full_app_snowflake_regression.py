#!/usr/bin/env python
"""Run a bounded Snowflake regression pass for OVERWATCH.

This is intentionally not a mock test. It attempts a real Snowflake connection
using either SNOWFLAKE_* environment variables or the local Streamlit
``connections.snowflake`` secrets, then validates the objects that support the
six-section operator workflow. The SQL probes stay small: metadata checks,
one-row mart reads, and freshness maxes when a freshness column exists.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
import traceback
from typing import Any

try:
    import tomllib
except Exception:  # pragma: no cover - Python 3.11 supplies tomllib.
    tomllib = None  # type: ignore[assignment]


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
RESULTS_DIR = ROOT / "perf_tests" / "results"
RESULTS_DOC = ROOT / "docs" / "OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md"
sys.path.insert(0, str(APP_ROOT))

from workflow_contracts import (  # noqa: E402
    ABANDONED_PRIMARY_SECTION_TITLES,
    PRIMARY_SECTION_TITLES,
    SECTION_WORKFLOW_CONTRACT,
)

SUMMARY_MARTS = (
    "MART_DBA_CONTROL_ROOM",
    "MART_EXECUTIVE_OBSERVABILITY",
    "MART_DATA_TRUST_SUMMARY",
    "MART_OPERATIONAL_OWNER_COVERAGE",
    "MART_EXECUTIVE_VALUE_LEDGER",
    "MART_APP_OBSERVABILITY_SUMMARY",
    "MART_PRODUCTION_READINESS_SUMMARY",
    "MART_EXECUTIVE_SCORECARD_SUMMARY",
    "MART_EXECUTIVE_FORECAST_SUMMARY",
    "MART_CHANGE_INTELLIGENCE_SUMMARY",
    "MART_CLOSED_LOOP_OPERATIONS_SUMMARY",
    "MART_COMMAND_CENTER_SUMMARY",
)

REFRESH_PROCEDURES = (
    "SP_OVERWATCH_REFRESH_CONTROL_ROOM",
    "SP_OVERWATCH_REFRESH_COST_MONITORING",
    "SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY",
    "SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL",
    "SP_OVERWATCH_REFRESH_PRODUCTION_READINESS",
    "SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD",
    "SP_OVERWATCH_REFRESH_FORECASTING",
    "SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE",
    "SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS",
    "SP_OVERWATCH_REFRESH_COMMAND_CENTER",
)


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _load_streamlit_connection() -> dict[str, Any]:
    if tomllib is None:
        return {}
    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return {}
    try:
        data = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    connections = data.get("connections", {})
    snowflake = connections.get("snowflake", {}) if isinstance(connections, dict) else {}
    return dict(snowflake) if isinstance(snowflake, dict) else {}


def connection_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    secrets = _load_streamlit_connection()
    kwargs: dict[str, Any] = {
        "account": _env("SNOWFLAKE_ACCOUNT", "SF_ACCOUNT") or secrets.get("account"),
        "user": _env("SNOWFLAKE_USER", "SF_USER") or secrets.get("user"),
        "password": _env("SNOWFLAKE_PASSWORD", "SF_PASSWORD") or secrets.get("password"),
        "authenticator": _env("SNOWFLAKE_AUTHENTICATOR", "SF_AUTHENTICATOR") or secrets.get("authenticator"),
        "role": args.role or _env("SNOWFLAKE_ROLE", "SF_ROLE") or secrets.get("role") or "SNOW_SYSADMINS",
        "warehouse": args.warehouse or _env("SNOWFLAKE_WAREHOUSE", "SF_WAREHOUSE") or secrets.get("warehouse") or "COMPUTE_WH",
        "database": args.database or _env("SNOWFLAKE_DATABASE", "SF_DATABASE") or secrets.get("database") or "DBA_MAINT_DB",
        "schema": args.schema or _env("SNOWFLAKE_SCHEMA", "SF_SCHEMA") or secrets.get("schema") or "OVERWATCH",
        "login_timeout": args.login_timeout,
        "network_timeout": args.network_timeout,
        "client_session_keep_alive": False,
    }
    return {key: value for key, value in kwargs.items() if value not in ("", None)}


def redact_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    hidden = dict(kwargs)
    if hidden.get("password"):
        hidden["password"] = "***"
    return hidden


def timed_sql(conn, name: str, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    started = time.perf_counter()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description or []]
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return {
            "name": name,
            "status": "PASS",
            "elapsed_ms": elapsed,
            "row_count": len(rows),
            "columns": columns,
            "sample": [dict(zip(columns, row)) for row in rows[:3]],
        }
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return {
            "name": name,
            "status": "FAIL",
            "elapsed_ms": elapsed,
            "error": str(exc)[:1000],
        }
    finally:
        cursor.close()


def object_inventory(conn, database: str, schema: str) -> dict[str, Any]:
    placeholders = ", ".join(["%s"] * len(SUMMARY_MARTS))
    table_rows = timed_sql(
        conn,
        "summary_mart_inventory",
        f"""
        SELECT table_name, table_type, row_count, last_altered
        FROM {database}.information_schema.tables
        WHERE table_schema = %s
          AND table_name IN ({placeholders})
        ORDER BY table_name
        """,
        (schema.upper(), *SUMMARY_MARTS),
    )
    proc_placeholders = ", ".join(["%s"] * len(REFRESH_PROCEDURES))
    proc_rows = timed_sql(
        conn,
        "refresh_procedure_inventory",
        f"""
        SELECT procedure_name, argument_signature, created, last_altered
        FROM {database}.information_schema.procedures
        WHERE procedure_schema = %s
          AND procedure_name IN ({proc_placeholders})
        ORDER BY procedure_name
        """,
        (schema.upper(), *REFRESH_PROCEDURES),
    )
    return {"summary_marts": table_rows, "refresh_procedures": proc_rows}


def mart_probes(conn, database: str, schema: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for mart in SUMMARY_MARTS:
        fq = f"{database}.{schema}.{mart}"
        probe = timed_sql(conn, f"{mart}_preview", f"SELECT * FROM {fq} LIMIT 1")
        results.append(probe)
        if probe.get("status") != "PASS":
            continue
        columns = {str(col).upper() for col in probe.get("columns", [])}
        freshness_column = next(
            (col for col in ("LAST_REFRESHED_TS", "SNAPSHOT_TS", "REFRESH_TS", "CREATED_AT") if col in columns),
            "",
        )
        if freshness_column:
            results.append(
                timed_sql(
                    conn,
                    f"{mart}_freshness",
                    f"SELECT MAX({freshness_column}) AS MAX_REFRESH_TS FROM {fq}",
                )
            )
    return results


def account_usage_probes(conn) -> list[dict[str, Any]]:
    return [
        timed_sql(
            conn,
            "account_usage_warehouse_access",
            """
            SELECT warehouse_name, event_state
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
            LIMIT 5
            """,
        ),
        timed_sql(
            conn,
            "account_usage_recent_metering_access",
            """
            SELECT warehouse_name, credits_used
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('DAY', -1, CURRENT_TIMESTAMP())
            LIMIT 5
            """,
        ),
    ]


def static_workflow_checks() -> dict[str, Any]:
    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (APP_ROOT / "sections").rglob("*.py")
    )
    missing: dict[str, list[str]] = {}
    for section, workflows in SECTION_WORKFLOW_CONTRACT.items():
        absent = [workflow for workflow in workflows if workflow not in source_text]
        if absent:
            missing[section] = absent
    primary_nav_violations = [
        item for item in ABANDONED_PRIMARY_SECTION_TITLES
        if item in PRIMARY_SECTION_TITLES
    ]
    stale_chart_refs = []
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in ("see chart A", "see chart B", "see chart C", "see chart D", "chart A", "chart B", "chart C", "chart D"):
            if token in text:
                stale_chart_refs.append({"file": str(path.relative_to(ROOT)), "token": token})
    return {
        "status": "PASS" if not missing and not primary_nav_violations and not stale_chart_refs else "FAIL",
        "sections": PRIMARY_SECTION_TITLES,
        "expected_workflows": SECTION_WORKFLOW_CONTRACT,
        "missing_workflows": missing,
        "primary_nav_violations": primary_nav_violations,
        "stale_chart_refs": stale_chart_refs,
    }


def run_regression(args: argparse.Namespace) -> dict[str, Any]:
    started = dt.datetime.now(dt.timezone.utc)
    payload: dict[str, Any] = {
        "run_id": args.run_id,
        "started_at": started.isoformat(),
        "static_workflow_checks": static_workflow_checks(),
        "connection": {},
        "snowflake_checks": [],
        "object_inventory": {},
        "mart_probes": [],
        "account_usage_probes": [],
    }
    try:
        import snowflake.connector
    except Exception as exc:
        payload.update({
            "status": "SKIPPED",
            "failure": f"snowflake.connector import failed: {exc}",
            "next_action": "Install snowflake-connector-python in the test environment and rerun.",
        })
        return payload

    kwargs = connection_kwargs(args)
    payload["connection"] = redact_kwargs(kwargs)
    missing = [name for name in ("account", "user") if not kwargs.get(name)]
    if not (kwargs.get("password") or kwargs.get("authenticator") or kwargs.get("private_key_file")):
        missing.append("password/authenticator/private_key_file")
    if missing:
        payload.update({
            "status": "SKIPPED",
            "failure": "Missing Snowflake connection input: " + ", ".join(missing),
            "next_action": "Set SNOWFLAKE_* environment variables or local Streamlit Snowflake secrets.",
        })
        return payload

    conn = None
    try:
        conn = snowflake.connector.connect(**kwargs)
        database = str(kwargs.get("database") or "DBA_MAINT_DB").upper()
        schema = str(kwargs.get("schema") or "OVERWATCH").upper()
        payload["snowflake_checks"].extend([
            timed_sql(conn, "current_session", "SELECT CURRENT_ACCOUNT(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()"),
            timed_sql(conn, "overwatch_schema_access", f"SELECT COUNT(*) AS OBJECT_COUNT FROM {database}.information_schema.tables WHERE table_schema = %s", (schema,)),
        ])
        payload["object_inventory"] = object_inventory(conn, database, schema)
        payload["mart_probes"] = mart_probes(conn, database, schema)
        payload["account_usage_probes"] = account_usage_probes(conn)
        all_checks = (
            payload["snowflake_checks"]
            + list(payload["object_inventory"].values())
            + payload["mart_probes"]
            + payload["account_usage_probes"]
        )
        failed = [check for check in all_checks if check.get("status") != "PASS"]
        payload["status"] = "FAIL" if failed or payload["static_workflow_checks"]["status"] != "PASS" else "PASS"
        payload["failures"] = failed
        payload["next_action"] = (
            "Fix failing Snowflake checks and rerun regression."
            if failed else "Review warnings, then run section smoke and full unit regression."
        )
    except Exception as exc:
        payload.update({
            "status": "FAIL",
            "failure": str(exc)[:1200],
            "traceback_tail": traceback.format_exc(limit=5),
            "next_action": "Fix connection/privilege issue, then rerun this regression.",
        })
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return payload


def write_reports(payload: dict[str, Any]) -> tuple[pathlib.Path, pathlib.Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"{payload['run_id']}_full_app_snowflake_regression.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# OVERWATCH Snowflake Regression Results",
        "",
        f"- Run ID: `{payload.get('run_id')}`",
        f"- Timestamp: `{payload.get('started_at')}`",
        f"- Status: `{payload.get('status', 'UNKNOWN')}`",
        f"- Environment: `{payload.get('connection', {}).get('account', 'unknown')}`",
        f"- Role: `{payload.get('connection', {}).get('role', 'unknown')}`",
        f"- Warehouse: `{payload.get('connection', {}).get('warehouse', 'unknown')}`",
        f"- Database/schema: `{payload.get('connection', {}).get('database', 'unknown')}.{payload.get('connection', {}).get('schema', 'unknown')}`",
        f"- JSON evidence: `{json_path}`",
        "",
        "## Sections Tested",
    ]
    for section in PRIMARY_SECTION_TITLES:
        lines.append(f"- {section}")
    lines.extend(["", "## Workflows Tested"])
    for section, workflows in SECTION_WORKFLOW_CONTRACT.items():
        lines.append(f"- {section}: {', '.join(workflows)}")
    static = payload.get("static_workflow_checks", {})
    lines.extend([
        "",
        "## Static Route / Label Checks",
        f"- Status: `{static.get('status', 'UNKNOWN')}`",
        f"- Missing workflows: `{static.get('missing_workflows', {})}`",
        f"- Primary nav violations: `{static.get('primary_nav_violations', [])}`",
        f"- Stale chart references: `{static.get('stale_chart_refs', [])}`",
        "",
        "## Snowflake Checks",
    ])
    if payload.get("failure"):
        lines.append(f"- Failure: `{payload.get('failure')}`")
    for group_name in ("snowflake_checks", "mart_probes", "account_usage_probes"):
        checks = payload.get(group_name, [])
        lines.append(f"- {group_name}: {len(checks)} checks")
        for check in checks[:20]:
            lines.append(
                f"  - `{check.get('name')}`: `{check.get('status')}` "
                f"({check.get('elapsed_ms', 'n/a')} ms)"
            )
            if check.get("error"):
                lines.append(f"    - Error: `{check.get('error')}`")
    inventory = payload.get("object_inventory", {})
    lines.extend(["", "## Object Inventory"])
    for name, check in inventory.items():
        lines.append(f"- `{name}`: `{check.get('status', 'UNKNOWN')}`, rows `{check.get('row_count', 0)}`")
        if check.get("error"):
            lines.append(f"  - Error: `{check.get('error')}`")
    lines.extend([
        "",
        "## Failures",
    ])
    failures = payload.get("failures", [])
    if failures:
        for failure in failures:
            lines.append(f"- `{failure.get('name')}`: {failure.get('error', 'failed')}")
    elif payload.get("failure"):
        lines.append(f"- {payload.get('failure')}")
    else:
        lines.append("- None recorded.")
    lines.extend([
        "",
        "## Recommended Fixes",
        f"- {payload.get('next_action', 'Review results and rerun after fixes.')}",
    ])
    RESULTS_DOC.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return json_path, RESULTS_DOC


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    parser = argparse.ArgumentParser(description="Run bounded OVERWATCH Snowflake regression checks.")
    parser.add_argument("--run-id", default=f"SNOWFLAKE_REGRESSION_{now}")
    parser.add_argument("--warehouse", default="")
    parser.add_argument("--database", default="")
    parser.add_argument("--schema", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--login-timeout", type=int, default=20)
    parser.add_argument("--network-timeout", type=int, default=30)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_regression(args)
    json_path, doc_path = write_reports(payload)
    payload["json_path"] = str(json_path)
    payload["doc_path"] = str(doc_path)
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
