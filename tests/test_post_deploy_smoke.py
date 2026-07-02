from pathlib import Path
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class PostDeploySmokeTests(unittest.TestCase):
    def _payloads(self) -> dict[str, object]:
        return {
            "artifacts/launch_readiness/rendered_ui_leak_gate_results.json": {"passed": True},
            "artifacts/launch_readiness/app_entry_smoke_gate_results.json": {"passed": True},
            "artifacts/launch_readiness/settings_live_feature_gate_results.json": {"passed": True},
            "artifacts/launch_readiness/export_download_gate_results.json": {"passed": True},
            "artifacts/launch_readiness/action_click_gate_results.json": {"passed": True},
        }

    def test_post_deploy_smoke_passes_with_primary_sections_and_required_gates(self):
        from tools.contracts.full_app_launch_gauntlet import PRIMARY_SECTIONS
        from tools.contracts.post_deploy_smoke import (
            build_post_deploy_smoke_results,
            evaluate_post_deploy_smoke_gate,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_json(
                root / "artifacts" / "full_app_validation" / "view_results.json",
                [{"section": section, "command_brief_count": 1} for section in PRIMARY_SECTIONS],
            )
            _write_json(
                root / "artifacts" / "full_app_validation" / "first_paint_performance_results.json",
                {"rows": [{"section": section, "passed": True} for section in PRIMARY_SECTIONS]},
            )
            _write_json(root / "artifacts" / "release_candidate" / "artifact_hashes.json", {"hashes": []})
            results = build_post_deploy_smoke_results(root, self._payloads())
            gate = evaluate_post_deploy_smoke_gate(results)

        self.assertTrue(results["passed"], results)
        self.assertTrue(gate["passed"], gate)
        self.assertEqual(results["primary_section_count"], len(PRIMARY_SECTIONS))

    def test_missing_export_gate_fails_post_deploy_smoke(self):
        from tools.contracts.full_app_launch_gauntlet import PRIMARY_SECTIONS
        from tools.contracts.post_deploy_smoke import build_post_deploy_smoke_results

        payloads = self._payloads()
        payloads.pop("artifacts/launch_readiness/export_download_gate_results.json")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_json(
                root / "artifacts" / "full_app_validation" / "view_results.json",
                [{"section": section, "command_brief_count": 1} for section in PRIMARY_SECTIONS],
            )
            _write_json(
                root / "artifacts" / "full_app_validation" / "first_paint_performance_results.json",
                {"rows": [{"section": section, "passed": True} for section in PRIMARY_SECTIONS]},
            )
            _write_json(root / "artifacts" / "release_candidate" / "artifact_hashes.json", {"hashes": []})
            results = build_post_deploy_smoke_results(root, payloads)

        self.assertFalse(results["passed"], results)
        self.assertTrue(any(row["check"] == "export_case_files" for row in results["failures"]))


if __name__ == "__main__":
    unittest.main()
