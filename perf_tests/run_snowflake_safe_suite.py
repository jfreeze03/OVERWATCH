#!/usr/bin/env python
"""Run the safe Snowflake-side OVERWATCH performance suite.

This runner executes only the guarded metadata-scale scripts:

1. sql/01_perf_test_setup.sql
2. CALL SP_PERF_TEST_GUARDRAIL_CHECK('LIGHTWEIGHT_METADATA', FALSE)
3. sql/02_generate_synthetic_light_medium.sql
4. sql/04_benchmark_report.sql

The physical 5 TB script is intentionally never executed by this runner.
Connection settings are read from Snowflake connector environment variables.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SQL_DIR = pathlib.Path(__file__).resolve().parent / "sql"
DEFAULT_OUTPUT_DIR = pathlib.Path(__file__).resolve().parent / "results"
SAFE_SQL_FILES = (
    "01_perf_test_setup.sql",
    "02_generate_synthetic_light_medium.sql",
    "04_benchmark_report.sql",
)
REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER")


def env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def connection_kwargs(args: argparse.Namespace) -> dict:
    kwargs = {
        "account": env_value("SNOWFLAKE_ACCOUNT", "SF_ACCOUNT"),
        "user": env_value("SNOWFLAKE_USER", "SF_USER"),
        "password": env_value("SNOWFLAKE_PASSWORD", "SF_PASSWORD"),
        "role": env_value("SNOWFLAKE_ROLE", "SF_ROLE"),
        "warehouse": args.warehouse or env_value("SNOWFLAKE_WAREHOUSE", "SF_WAREHOUSE") or "WH_ALFA_OVERWATCH",
        "database": args.database or env_value("SNOWFLAKE_DATABASE", "SF_DATABASE") or "DBA_MAINT_DB",
        "schema": args.schema or env_value("SNOWFLAKE_SCHEMA", "SF_SCHEMA") or "OVERWATCH",
        "client_session_keep_alive": False,
        "session_parameters": {
            "QUERY_TAG": f"OVERWATCH|PERF_SAFE_SUITE|PERF:{args.run_id}",
            "STATEMENT_TIMEOUT_IN_SECONDS": args.statement_timeout,
        },
    }
    authenticator = env_value("SNOWFLAKE_AUTHENTICATOR", "SF_AUTHENTICATOR")
    if authenticator:
        kwargs["authenticator"] = authenticator
    private_key_file = env_value("SNOWFLAKE_PRIVATE_KEY_FILE", "SF_PRIVATE_KEY_FILE")
    if private_key_file:
        kwargs["private_key_file"] = private_key_file
    return {key: value for key, value in kwargs.items() if value not in ("", None)}


def missing_connection_inputs(kwargs: dict) -> list[str]:
    missing = []
    for env_name in REQUIRED_ENV:
        field = env_name.replace("SNOWFLAKE_", "").lower()
        if not kwargs.get(field):
            missing.append(env_name)
    has_password = bool(
        kwargs.get("password")
        or kwargs.get("authenticator")
        or kwargs.get("private_key_file")
    )
    if not has_password:
        missing.append("SNOWFLAKE_PASSWORD or SNOWFLAKE_AUTHENTICATOR or SNOWFLAKE_PRIVATE_KEY_FILE")
    return missing


def execute_sql_file(connection, path: pathlib.Path) -> int:
    statements = 0
    with path.open("r", encoding="utf-8") as handle:
        for cursor in connection.execute_stream(handle, remove_comments=True):
            statements += 1
            try:
                cursor.fetchall()
            except Exception:
                pass
    return statements


def fetch_one(connection, sql: str):
    cursor = connection.cursor()
    try:
        cursor.execute(sql)
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()


def fetch_rows(connection, sql: str) -> list[dict]:
    cursor = connection.cursor()
    try:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description or []]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def write_report(args: argparse.Namespace, payload: dict) -> pathlib.Path:
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{args.run_id}_snowflake_safe_suite.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def run_suite(args: argparse.Namespace) -> dict:
    try:
        import snowflake.connector
    except Exception as exc:
        return {
            "run_id": args.run_id,
            "state": "SKIPPED",
            "error": f"snowflake.connector is unavailable: {exc}",
            "next_action": "Install snowflake-connector-python in the local test environment.",
        }

    kwargs = connection_kwargs(args)
    missing = missing_connection_inputs(kwargs)
    if missing:
        return {
            "run_id": args.run_id,
            "state": "SKIPPED",
            "error": "Missing Snowflake connection settings: " + ", ".join(missing),
            "next_action": (
                "Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and an authentication method, "
                "then rerun perf_tests/run_snowflake_safe_suite.py."
            ),
        }

    sql_dir = pathlib.Path(args.sql_dir)
    for file_name in SAFE_SQL_FILES:
        if not (sql_dir / file_name).exists():
            return {
                "run_id": args.run_id,
                "state": "FAIL",
                "error": f"Missing SQL file: {sql_dir / file_name}",
                "next_action": "Restore the perf_tests/sql suite before running Snowflake-side validation.",
            }

    started = dt.datetime.now(dt.timezone.utc)
    executed: list[dict] = []
    conn = snowflake.connector.connect(**kwargs)
    try:
        setup_path = sql_dir / "01_perf_test_setup.sql"
        executed.append({"file": setup_path.name, "statements": execute_sql_file(conn, setup_path)})

        guard_message = str(fetch_one(conn, "CALL SP_PERF_TEST_GUARDRAIL_CHECK('LIGHTWEIGHT_METADATA', FALSE)") or "")
        if not guard_message.upper().startswith("OK:"):
            return {
                "run_id": args.run_id,
                "state": "BLOCKED",
                "guardrail": guard_message,
                "executed": executed,
                "next_action": "Fix the warehouse size/auto-suspend guardrail before generating synthetic perf data.",
            }

        for file_name in SAFE_SQL_FILES[1:]:
            path = sql_dir / file_name
            executed.append({"file": path.name, "statements": execute_sql_file(conn, path)})

        readiness = fetch_rows(conn, "SELECT * FROM PERF_TEST_PRODUCTION_READINESS_V")
        scale = fetch_rows(conn, "SELECT * FROM PERF_TEST_SCALE_SUMMARY_V")
        expensive = fetch_rows(conn, "SELECT * FROM PERF_TEST_EXPENSIVE_QUERY_CANDIDATES_V LIMIT 20")
        ended = dt.datetime.now(dt.timezone.utc)
        return {
            "run_id": args.run_id,
            "state": "PASS",
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "elapsed_sec": round((ended - started).total_seconds(), 3),
            "guardrail": guard_message,
            "executed": executed,
            "readiness": readiness,
            "scale_summary": scale,
            "expensive_candidates_sample": expensive,
            "next_action": "Review PERF_TEST_PRODUCTION_READINESS_V and expensive-query candidates before release.",
        }
    except Exception as exc:
        return {
            "run_id": args.run_id,
            "state": "FAIL",
            "error": str(exc)[:1000],
            "executed": executed,
            "next_action": "Fix the Snowflake-side failure, then rerun the safe suite.",
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run guarded Snowflake-side OVERWATCH perf SQL.")
    default_run_id = f"PERF_SQL_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    parser.add_argument("--run-id", default=default_run_id)
    parser.add_argument("--sql-dir", default=str(DEFAULT_SQL_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--warehouse", default="")
    parser.add_argument("--database", default="")
    parser.add_argument("--schema", default="")
    parser.add_argument("--statement-timeout", type=int, default=840)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_suite(args)
    report_path = write_report(args, payload)
    payload["report_path"] = str(report_path)
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("state") in {"PASS", "SKIPPED"} else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
