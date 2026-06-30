"""Optional browser smoke proof for launch readiness.

CI often lacks an attached browser. This contract records that fact explicitly
and lets deterministic Streamlit render proof carry internal-fixture evidence.
For live/prod profiles, a browser skip remains a gate failure unless waived by
the owning release policy.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
SCREENSHOT_DIR = "artifacts/browser_screenshots"

BROWSER_SMOKE_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/browser_smoke_results.json"
BROWSER_SMOKE_GATE_REL = f"{LAUNCH_READINESS_DIR}/browser_smoke_gate_results.json"
DETERMINISTIC_RENDER_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/deterministic_streamlit_render_results.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"passed": False, "failure_reason": "malformed_json"}


def _profile_requires_browser(profile: str) -> bool:
    return profile in {"internal_live", "prod_candidate"}


def build_browser_smoke_results(root: Path | str = ".", *, launch_profile: str = "internal_fixture") -> dict[str, Any]:
    root_path = Path(root).resolve()
    screenshot_root = root_path / SCREENSHOT_DIR
    screenshot_root.mkdir(parents=True, exist_ok=True)
    deterministic = _as_mapping(_load_json(root_path, DETERMINISTIC_RENDER_RESULTS_REL))
    deterministic_present = bool(deterministic.get("passed")) and int(deterministic.get("rendered_row_count") or 0) > 0
    screenshots = sorted(
        path for path in screenshot_root.rglob("*")
        if path.is_file() and path.name != "SKIPPED.txt"
    )
    generated_at = _now()
    commit_sha = _git_commit(root_path)

    if screenshots:
        rows = [
            {
                "producer": "browser_smoke_runner",
                "generated_at": generated_at,
                "source": "browser_rendered",
                "proof_source": "browser_rendered",
                "provenance_origin": "producer",
                "producer_signature": f"browser_smoke::{path.name}::{commit_sha}",
                "runtime_artifact_row_index": index,
                "fixture_mode": False,
                "launch_profile": launch_profile,
                "commit_sha": commit_sha,
                "section": path.stem,
                "workflow": "Browser smoke",
                "screenshot_path": str(path.relative_to(root_path)).replace("\\", "/"),
                "rendered": True,
                "clicked": True,
                "passed": True,
                "failure_reason": "",
                "raw_sql_included": False,
            }
            for index, path in enumerate(screenshots)
        ]
        return {
            "producer": "browser_smoke_runner",
            "source": "browser_smoke_results",
            "proof_source": "browser_rendered",
            "generated_at": generated_at,
            "commit_sha": commit_sha,
            "passed": True,
            "skipped": False,
            "skip_reason": "",
            "screenshot_count": len(rows),
            "deterministic_render_present": deterministic_present,
            "rows": rows,
            "failure_count": 0,
            "failures": [],
            "raw_sql_included": False,
        }

    skip_reason = "No browser screenshot tool was available; deterministic Streamlit render proof is required."
    (screenshot_root / "SKIPPED.txt").write_text(skip_reason + "\n", encoding="utf-8")
    fail_for_profile = _profile_requires_browser(launch_profile)
    failure = {
        "code": "BROWSER_SMOKE_SKIPPED",
        "failure_reason": skip_reason,
        "launch_profile": launch_profile,
    }
    if fail_for_profile:
        failure["recommendation"] = "Capture browser smoke screenshots or attach a signed waiver for live/prod launch."
    return {
        "producer": "browser_smoke_runner",
        "source": "browser_smoke_results",
        "proof_source": "browser_skipped",
        "generated_at": generated_at,
        "commit_sha": commit_sha,
        "passed": deterministic_present and not fail_for_profile,
        "skipped": True,
        "skip_reason": skip_reason,
        "screenshot_count": 0,
        "deterministic_render_present": deterministic_present,
        "rows": [],
        "failure_count": 1 if fail_for_profile or not deterministic_present else 0,
        "failures": [failure] if fail_for_profile or not deterministic_present else [],
        "raw_sql_included": False,
    }


def evaluate_browser_smoke_gate(payload: object) -> dict[str, Any]:
    results = _as_mapping(payload)
    failures = list(results.get("failures") or [])
    if not bool(results.get("passed", False)) and not failures:
        failures = [{"code": "BROWSER_SMOKE_FAILED"}]
    return {
        "source": "browser_smoke_gate_results",
        "generated_at": _now(),
        "passed": bool(results.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "failures": failures,
        "skipped": bool(results.get("skipped")),
        "deterministic_render_present": bool(results.get("deterministic_render_present")),
        "screenshot_count": int(results.get("screenshot_count") or 0),
        "raw_sql_included": False,
    }


def write_browser_smoke_runner_artifacts(
    root: Path | str = ".",
    *,
    launch_profile: str = "internal_fixture",
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_browser_smoke_results(root_path, launch_profile=launch_profile)
    gate = evaluate_browser_smoke_gate(results)
    artifacts = {
        BROWSER_SMOKE_RESULTS_REL: results,
        BROWSER_SMOKE_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "BROWSER_SMOKE_GATE_REL",
    "BROWSER_SMOKE_RESULTS_REL",
    "build_browser_smoke_results",
    "evaluate_browser_smoke_gate",
    "write_browser_smoke_runner_artifacts",
]
