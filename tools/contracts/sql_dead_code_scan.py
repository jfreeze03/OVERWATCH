"""Dead SQL/route/object cleanup scan for launch closure."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


CLEANUP_DIR = "artifacts/cleanup"

SQL_DEAD_CODE_SCAN_REL = f"{CLEANUP_DIR}/sql_dead_code_scan_results.json"

OLD_SURFACE_MARKERS = (
    "launchpad",
    "watch floor",
    "command deck",
    "lane board",
)

RETAINED_OBSOLETE_FILES: dict[str, dict[str, str]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def build_sql_dead_code_scan(root: Path) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    launch_surface_files = [
        root / ".overwatch_final/layout.py",
        root / ".overwatch_final/navigation.py",
        root / ".overwatch_final/route_registry.py",
        root / ".overwatch_final/section_dispatch.py",
    ]
    for path in launch_surface_files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for marker in OLD_SURFACE_MARKERS:
            if marker in text:
                failures.append(
                    {
                        "path": str(path.relative_to(root)).replace("\\", "/"),
                        "marker": marker,
                        "reason": "old launch surface marker appears in a launch route file",
                    }
                )
    for rel, metadata in RETAINED_OBSOLETE_FILES.items():
        path = root / rel
        if path.exists():
            row = {"path": rel, **metadata}
            retained.append(row)
            if not metadata.get("owner") or not metadata.get("reason") or not metadata.get("review"):
                failures.append({"path": rel, "reason": "retained obsolete item missing owner/reason/review"})
    return {
        "source": "sql_dead_code_scan_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "old_surface_markers": OLD_SURFACE_MARKERS,
        "retained_obsolete_items": retained,
        "retained_obsolete_count": len(retained),
        "raw_sql_included": False,
    }


def write_sql_dead_code_scan_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    payload = build_sql_dead_code_scan(root_path)
    _write_json(root_path / SQL_DEAD_CODE_SCAN_REL, payload)
    return {SQL_DEAD_CODE_SCAN_REL: payload}


__all__ = [
    "OLD_SURFACE_MARKERS",
    "RETAINED_OBSOLETE_FILES",
    "SQL_DEAD_CODE_SCAN_REL",
    "build_sql_dead_code_scan",
    "write_sql_dead_code_scan_artifacts",
]
