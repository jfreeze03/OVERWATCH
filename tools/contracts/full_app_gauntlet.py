"""Full app gauntlet entrypoint for the Decision Workspace.

The gauntlet is intentionally a wrapper around the runtime validation harness:
it must render and click the product, then assert the generated proof bundle is
complete. Static inventory can support the report, but it cannot satisfy this
gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.contracts.full_app_runtime_validation import write_full_app_validation_artifacts


REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS = {
    "artifacts/full_app_validation/app_validation_summary.json",
    "artifacts/full_app_validation/view_results.json",
    "artifacts/full_app_validation/control_inventory.json",
    "artifacts/full_app_validation/control_contract_coverage.json",
    "artifacts/full_app_validation/button_click_results.json",
    "artifacts/full_app_validation/settings_action_results.json",
    "artifacts/full_app_validation/live_feature_results.json",
    "artifacts/full_app_validation/export_results.json",
    "artifacts/full_app_validation/case_payload_results.json",
    "artifacts/full_app_validation/evidence_loader_call_matrix.json",
    "artifacts/full_app_validation/query_search_results.json",
    "artifacts/full_app_validation/stress_results.json",
    "artifacts/full_app_validation/slow_runtime_inventory.json",
    "artifacts/full_app_validation/error_inventory.json",
    "artifacts/full_app_validation/risk_inventory.json",
    "artifacts/full_app_validation/artifact_manifest.json",
}


def write_full_app_gauntlet_artifacts(root: Path | str = ".") -> dict[str, Any]:
    """Run the runtime full-app gauntlet and assert required artifacts exist."""

    root_path = Path(root).resolve()
    artifacts = write_full_app_validation_artifacts(root_path)
    missing = sorted(
        rel for rel in REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS
        if rel not in artifacts or not (root_path / rel).exists()
    )
    if missing:
        raise AssertionError(f"Missing full app gauntlet artifacts: {missing}")
    return artifacts


__all__ = [
    "REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS",
    "write_full_app_gauntlet_artifacts",
]
