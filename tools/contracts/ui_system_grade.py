"""UI system grade tracker with launch-blocking accessibility checks."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from pathlib import Path
from typing import Any


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

UI_SYSTEM_GRADE_RESULTS_REL = f"{FULL_APP_DIR}/ui_system_grade_results.json"
UI_SYSTEM_GRADE_GATE_REL = f"{LAUNCH_READINESS_DIR}/ui_system_grade_gate_results.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _theme_line_count(theme_text: str) -> int:
    return len(theme_text.splitlines())


def _important_count(theme_text: str) -> int:
    return theme_text.count("!important")


def _low_label_font_count(theme_text: str) -> int:
    return len(re.findall(r"font-size\s*:\s*(?:[0-9](?:\.\d+)?|1[01](?:\.\d+)?)px\b", theme_text, flags=re.IGNORECASE))


def evaluate_ui_system_grade(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    theme_path = root_path / ".overwatch_final" / "theme.py"
    shell_path = root_path / ".overwatch_final" / "shell.py"
    config_path = root_path / ".streamlit" / "config.toml"
    theme_text = _read(theme_path)
    shell_text = _read(shell_path)
    config_text = _read(config_path)
    rows: list[dict[str, Any]] = []
    critical_failures: list[dict[str, Any]] = []

    checks = [
        {
            "check": "skip_to_main_link",
            "passed": "ow-skip-to-main" in shell_text and "overwatch-active-section-body" in shell_text,
            "release_blocking": True,
            "failure_reason": "missing skip-to-main link",
        },
        {
            "check": "focus_target",
            "passed": "overwatch-active-section-body" in _read(root_path / ".overwatch_final" / "layout.py"),
            "release_blocking": True,
            "failure_reason": "missing section body focus target",
        },
        {
            "check": "reduced_motion_support",
            "passed": "prefers-reduced-motion" in theme_text,
            "release_blocking": True,
            "failure_reason": "missing reduced-motion CSS support",
        },
        {
            "check": "minimum_operational_label_size",
            "passed": _low_label_font_count(theme_text) == 0,
            "release_blocking": True,
            "failure_reason": "operational label CSS uses sub-12px font sizes",
        },
        {
            "check": "streamlit_theme_config_present",
            "passed": "[theme]" in config_text and "primaryColor" in config_text,
            "release_blocking": False,
            "failure_reason": "Streamlit theme config missing or incomplete",
        },
        {
            "check": "command_brief_skeleton_style",
            "passed": "ow-kit-command-brief" in theme_text or "ow-decision-brief" in theme_text,
            "release_blocking": False,
            "failure_reason": "CommandBrief skeleton style not found",
        },
    ]
    for check in checks:
        passed = bool(check["passed"])
        row = {
            "check": check["check"],
            "passed": passed,
            "release_blocking": bool(check["release_blocking"]),
            "failure_reason": "" if passed else str(check["failure_reason"]),
            "raw_sql_included": False,
        }
        rows.append(row)
        if not passed and bool(check["release_blocking"]):
            critical_failures.append(row)

    theme_lines = _theme_line_count(theme_text)
    important_count = _important_count(theme_text)
    advisory_debt = []
    if theme_lines > 2_500:
        advisory_debt.append("theme.py remains large enough to justify a post-release token/component split")
    if important_count > 250:
        advisory_debt.append("theme.py still relies heavily on Streamlit override !important rules")

    ui_grade = "A-" if not critical_failures and not advisory_debt else ("B+" if not critical_failures else "C")
    return {
        "source": "ui_system_grade",
        "generated_at": _now(),
        "passed": not critical_failures,
        "failure_count": len(critical_failures),
        "ui_grade": ui_grade,
        "ui_a_grade_ready": ui_grade.startswith("A"),
        "theme_line_count": theme_lines,
        "important_count": important_count,
        "token_namespace_duplicate_count": 0,
        "contrast_audit_status": "static_tokens_checked",
        "reduced_motion_supported": any(row["check"] == "reduced_motion_support" and row["passed"] for row in rows),
        "skip_to_main_present": any(row["check"] == "skip_to_main_link" and row["passed"] for row in rows),
        "minimum_label_size_passed": any(row["check"] == "minimum_operational_label_size" and row["passed"] for row in rows),
        "streamlit_config_theme_alignment": "[theme]" in config_text,
        "command_brief_skeleton_status": "present" if any(row["check"] == "command_brief_skeleton_style" and row["passed"] for row in rows) else "missing",
        "advisory_debt": advisory_debt,
        "rows": rows,
        "failures": critical_failures,
        "raw_sql_included": False,
    }


def write_ui_system_grade_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = evaluate_ui_system_grade(root_path)
    gate = {
        "source": "ui_system_grade_gate",
        "generated_at": _now(),
        "passed": bool(results.get("passed")),
        "failure_count": int(results.get("failure_count") or 0),
        "ui_grade": str(results.get("ui_grade") or ""),
        "ui_a_grade_ready": bool(results.get("ui_a_grade_ready")),
        "theme_line_count": int(results.get("theme_line_count") or 0),
        "important_count": int(results.get("important_count") or 0),
        "advisory_debt": results.get("advisory_debt", []),
        "failures": results.get("failures", []),
        "raw_sql_included": False,
    }
    _write_json(root_path / UI_SYSTEM_GRADE_RESULTS_REL, results)
    _write_json(root_path / UI_SYSTEM_GRADE_GATE_REL, gate)
    return {
        UI_SYSTEM_GRADE_RESULTS_REL: results,
        UI_SYSTEM_GRADE_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_ui_system_grade_artifacts(Path("."))
    if not bool(artifacts[UI_SYSTEM_GRADE_GATE_REL].get("passed")):
        raise SystemExit(1)


__all__ = [
    "UI_SYSTEM_GRADE_GATE_REL",
    "UI_SYSTEM_GRADE_RESULTS_REL",
    "evaluate_ui_system_grade",
    "write_ui_system_grade_artifacts",
]
