"""Runtime proof for access-control and first-paint session boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping
from unittest.mock import patch


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

ACCESS_CONTROL_RUNTIME_RESULTS_REL = f"{FULL_APP_DIR}/access_control_runtime_results.json"
ACCESS_CONTROL_RUNTIME_GATE_REL = f"{LAUNCH_READINESS_DIR}/access_control_runtime_gate_results.json"

PRIMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)

FORBIDDEN_ERROR_TOKENS = (
    "token",
    "password",
    "secret",
    "private key",
    "credwrite",
    "traceback",
    ".sql",
    ".txt",
    ":\\",
    ":/",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "checks", "results", "sections"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _restore_state(st: Any, snapshot: Mapping[str, Any]) -> None:
    try:
        st.session_state.clear()
        st.session_state.update(snapshot)
    except Exception:
        pass


def _function_probe_rows(root: Path) -> list[dict[str, Any]]:
    app_root = root / ".overwatch_final"
    app_root_text = str(app_root)
    if app_root_text not in sys.path:
        sys.path.insert(0, app_root_text)
    import streamlit as st  # noqa: PLC0415
    import access_control  # noqa: PLC0415
    from runtime_state import ADMIN_CONNECTION_TEST_COUNT  # noqa: PLC0415

    snapshot = {str(key): value for key, value in dict(st.session_state).items()}
    rows: list[dict[str, Any]] = []

    def row(name: str, passed: bool, reason: str = "", **extra: Any) -> None:
        rows.append(
            {
                "id": f"access_control::{name}",
                "section": "Settings/Admin Setup Health" if "admin" in name else "Shell",
                "workflow": name,
                "producer": "access_control_runtime",
                "producer_signature": "access_control_runtime::runtime_probe",
                "provenance_origin": "producer",
                "runtime_source": "access_control_runtime",
                "proof_source": "runtime_probe",
                "source": "access_control_runtime",
                "generated_at": _now(),
                "commit_sha": _git_commit(root),
                "passed": bool(passed),
                "failure_reason": reason,
                "raw_sql_included": False,
                **extra,
            }
        )

    try:
        st.session_state.clear()
        access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE = None
        with patch.object(access_control, "_declared_snowflake_connection_configured", return_value=False):
            with patch.object(access_control, "get_session", side_effect=AssertionError("non-forced probe opened session")):
                available = access_control.probe_snowflake_available(force=False)
        row(
            "probe_force_false_no_session",
            not available and ADMIN_CONNECTION_TEST_COUNT not in st.session_state,
            "non-forced probe opened a session or stamped admin counter"
            if available or ADMIN_CONNECTION_TEST_COUNT in st.session_state
            else "",
            pre_first_paint_session_open_count=0,
            shell_session_open_count=0,
            active_session_probe_count=0,
            admin_connection_test_count=_as_int(st.session_state.get(ADMIN_CONNECTION_TEST_COUNT)),
            explicit_connection_test_count=_as_int(st.session_state.get(ADMIN_CONNECTION_TEST_COUNT)),
            access_gate_state=str(st.session_state.get("_overwatch_access_gate_state") or ""),
        )

        st.session_state.clear()
        access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE = None
        with patch.object(access_control, "_declared_snowflake_connection_configured", return_value=False):
            with patch.object(access_control, "get_session", side_effect=AssertionError("cached/declaration path opened session")):
                available = access_control.cached_or_declared_snowflake_available(default=False)
        row(
            "cached_or_declared_no_session",
            not available and ADMIN_CONNECTION_TEST_COUNT not in st.session_state,
            "cached/declaration availability opened a session or stamped admin counter"
            if available or ADMIN_CONNECTION_TEST_COUNT in st.session_state
            else "",
            pre_first_paint_session_open_count=0,
            shell_session_open_count=0,
            active_session_probe_count=0,
            admin_connection_test_count=_as_int(st.session_state.get(ADMIN_CONNECTION_TEST_COUNT)),
            explicit_connection_test_count=_as_int(st.session_state.get(ADMIN_CONNECTION_TEST_COUNT)),
            access_gate_state=str(st.session_state.get("_overwatch_access_gate_state") or ""),
        )

        st.session_state.clear()
        with patch.object(access_control, "get_session", side_effect=AssertionError("role refresh opened session")):
            role = access_control.refresh_current_role_for_access(connection_available=True)
        row(
            "refresh_role_no_session",
            role == "",
            "refresh_current_role_for_access opened or required a Snowflake session" if role else "",
            pre_first_paint_session_open_count=0,
            shell_session_open_count=0,
            active_session_probe_count=0,
            admin_connection_test_count=_as_int(st.session_state.get(ADMIN_CONNECTION_TEST_COUNT)),
            explicit_connection_test_count=_as_int(st.session_state.get(ADMIN_CONNECTION_TEST_COUNT)),
            access_gate_state=str(st.session_state.get("_overwatch_access_gate_state") or ""),
        )

        st.session_state.clear()
        access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE = None
        with patch.object(access_control, "get_session", return_value=object()) as mocked:
            available = access_control.probe_snowflake_available(force=True)
        admin_count = _as_int(st.session_state.get(ADMIN_CONNECTION_TEST_COUNT))
        row(
            "forced_probe_uses_explicit_admin_test",
            available and mocked.call_count == 1 and admin_count == 1,
            "force=True did not route through exactly one explicit admin connection test"
            if not (available and mocked.call_count == 1 and admin_count == 1)
            else "",
            pre_first_paint_session_open_count=0,
            shell_session_open_count=0,
            active_session_probe_count=0,
            admin_connection_test_count=admin_count,
            explicit_connection_test_count=admin_count,
            access_gate_state=str(st.session_state.get("_overwatch_access_gate_state") or ""),
        )

        sanitized = access_control._sanitize_connection_error(  # type: ignore[attr-defined]
            RuntimeError("Traceback token password CredWrite C:/tmp/overwatch.sql")
        )
        leaked = [token for token in FORBIDDEN_ERROR_TOKENS if token.lower() in sanitized.lower()]
        row(
            "connection_error_sanitized",
            not leaked,
            f"sanitized connection error leaked: {', '.join(leaked)}" if leaked else "",
            connection_test_sanitized_error_present=bool(sanitized),
            sanitized_error=sanitized,
        )
    finally:
        access_control._SNOWFLAKE_AVAILABLE_PROCESS_CACHE = None
        _restore_state(st, snapshot)
    return rows


def _first_paint_rows(first_paint_payload: Any, root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_rows = _rows(first_paint_payload)
    by_section = {str(row.get("section") or ""): row for row in source_rows}
    for section in PRIMARY_SECTIONS:
        source_row = by_section.get(section, {})
        missing = not bool(source_row)
        admin = _as_int(source_row.get("admin_connection_test_count"))
        explicit = _as_int(source_row.get("explicit_connection_test_count"))
        pre = _as_int(source_row.get("pre_first_paint_session_open_count"))
        shell = _as_int(source_row.get("shell_session_open_count"))
        active = _as_int(source_row.get("active_session_probe_count"))
        reasons: list[str] = []
        if missing:
            reasons.append("missing first-paint access-control telemetry row")
        if pre:
            reasons.append("session opened before first-paint boundary")
        if shell:
            reasons.append("shell opened a Snowflake session")
        if active:
            reasons.append("shell performed an active-session probe")
        if admin:
            reasons.append("admin connection test ran on primary overview first paint")
        if explicit:
            reasons.append("explicit connection test ran on primary overview first paint")
        rows.append(
            {
                "id": f"access_control_first_paint::{section.lower().replace(' ', '_').replace('&', 'and')}",
                "section": section,
                "workflow": str(source_row.get("workflow") or "Overview"),
                "producer": "access_control_runtime",
                "producer_signature": "access_control_runtime::first_paint_telemetry",
                "provenance_origin": "producer",
                "runtime_source": str(source_row.get("runtime_source") or "first_paint_performance_results"),
                "proof_source": "runtime_telemetry",
                "source": "access_control_runtime",
                "generated_at": _now(),
                "commit_sha": str(source_row.get("commit_sha") or _git_commit(root)),
                "pre_first_paint_session_open_count": pre,
                "shell_session_open_count": shell,
                "active_session_probe_count": active,
                "admin_connection_test_count": admin,
                "explicit_connection_test_count": explicit,
                "access_gate_state": str(source_row.get("access_gate_state") or ""),
                "connection_test_sanitized_error_present": bool(source_row.get("connection_test_sanitized_error_present", True)),
                "passed": not reasons,
                "failure_reason": "; ".join(reasons),
                "raw_sql_included": False,
            }
        )
    return rows


def evaluate_access_control_runtime(first_paint_payload: Any, *, root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    rows = [*_function_probe_rows(root_path), *_first_paint_rows(first_paint_payload, root_path)]
    failures = [row for row in rows if not bool(row.get("passed"))]
    return {
        "source": "access_control_runtime_results",
        "producer": "access_control_runtime",
        "producer_signature": "access_control_runtime::v1",
        "provenance_origin": "producer",
        "runtime_source": "access_control_runtime",
        "proof_source": "runtime_probe_and_first_paint_telemetry",
        "generated_at": _now(),
        "commit_sha": _git_commit(root_path),
        "passed": not failures,
        "failure_count": len(failures),
        "pre_first_paint_session_open_count": sum(_as_int(row.get("pre_first_paint_session_open_count")) for row in rows),
        "shell_session_open_count": sum(_as_int(row.get("shell_session_open_count")) for row in rows),
        "active_session_probe_count": sum(_as_int(row.get("active_session_probe_count")) for row in rows),
        "admin_connection_test_count": sum(_as_int(row.get("admin_connection_test_count")) for row in rows),
        "explicit_connection_test_count": sum(_as_int(row.get("explicit_connection_test_count")) for row in rows),
        "rows": rows,
        "proof_rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_access_control_runtime_gate(payload: Any) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = results.get("failures") if isinstance(results.get("failures"), list) else []
    return {
        "source": "access_control_runtime_gate_results",
        "producer": "access_control_runtime",
        "producer_signature": "access_control_runtime_gate::v1",
        "provenance_origin": "producer",
        "commit_sha": str(results.get("commit_sha") or ""),
        "generated_at": _now(),
        "passed": bool(results.get("passed")) and not failures,
        "failure_count": len(failures) if failures else _as_int(results.get("failure_count")),
        "pre_first_paint_session_open_count": _as_int(results.get("pre_first_paint_session_open_count")),
        "shell_session_open_count": _as_int(results.get("shell_session_open_count")),
        "active_session_probe_count": _as_int(results.get("active_session_probe_count")),
        "admin_connection_test_count": _as_int(results.get("admin_connection_test_count")),
        "explicit_connection_test_count": _as_int(results.get("explicit_connection_test_count")),
        "proof_rows": results.get("proof_rows") or results.get("rows") or [],
        "failures": failures,
        "raw_sql_included": False,
    }


def write_access_control_runtime_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    first_paint = _load_json(root_path / f"{FULL_APP_DIR}/first_paint_performance_results.json")
    results = evaluate_access_control_runtime(first_paint, root=root_path)
    gate = evaluate_access_control_runtime_gate(results)
    _write_json(root_path / ACCESS_CONTROL_RUNTIME_RESULTS_REL, results)
    _write_json(root_path / ACCESS_CONTROL_RUNTIME_GATE_REL, gate)
    return {
        ACCESS_CONTROL_RUNTIME_RESULTS_REL: results,
        ACCESS_CONTROL_RUNTIME_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_access_control_runtime_artifacts(Path("."))
    if not bool(artifacts[ACCESS_CONTROL_RUNTIME_GATE_REL].get("passed")):
        raise SystemExit(1)


__all__ = [
    "ACCESS_CONTROL_RUNTIME_GATE_REL",
    "ACCESS_CONTROL_RUNTIME_RESULTS_REL",
    "evaluate_access_control_runtime",
    "evaluate_access_control_runtime_gate",
    "write_access_control_runtime_artifacts",
]
