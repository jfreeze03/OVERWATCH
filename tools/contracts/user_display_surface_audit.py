"""Audit daily user display surfaces for friendly labels and raw-ID leaks."""

from __future__ import annotations

from pathlib import Path

from tools.contracts.security_credential_validation import (
    USER_DISPLAY_SURFACE_GATE_REL,
    USER_DISPLAY_SURFACE_REL,
    _evaluate_simple_gate,
    _write_json,
    build_user_display_surface_results,
)


def write_user_display_surface_audit_artifacts(root: Path | str = ".") -> dict[str, object]:
    root_path = Path(root).resolve()
    results = build_user_display_surface_results(root_path)
    gate = _evaluate_simple_gate(
        results,
        source="user_display_surface_gate_results",
        passed_key="user_display_surface_gate_passed",
    )
    artifacts: dict[str, object] = {
        USER_DISPLAY_SURFACE_REL: results,
        USER_DISPLAY_SURFACE_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


def main() -> int:
    artifacts = write_user_display_surface_audit_artifacts(Path.cwd())
    gate = artifacts[USER_DISPLAY_SURFACE_GATE_REL]
    return 0 if isinstance(gate, dict) and bool(gate.get("passed")) else 1


__all__ = [
    "build_user_display_surface_results",
    "main",
    "write_user_display_surface_audit_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
