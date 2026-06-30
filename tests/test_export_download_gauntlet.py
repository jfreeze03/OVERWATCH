from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ExportDownloadGauntletTests(unittest.TestCase):
    def test_query_text_export_fails_download_results(self):
        from tools.contracts.full_app_launch_gauntlet import build_download_results

        results = build_download_results(
            {
                "artifacts/full_app_validation/export_results.json": [
                    {
                        "section": "Query Search",
                        "workflow": "Default export",
                        "artifact_path": "artifacts/full_app_validation/query.csv",
                        "row_count": 1,
                        "visible_row_count": 1,
                        "sha256": "abc",
                        "contains_query_text": True,
                        "passed": True,
                    }
                ]
            }
        )

        self.assertFalse(results["passed"])

    def test_case_payload_missing_required_field_fails_gate(self):
        from tools.contracts.export_download_gauntlet import evaluate_export_download_gate

        gate = evaluate_export_download_gate(
            {"passed": True, "export_count": 1},
            {"passed": True, "download_count": 1},
            [{"section": "Cost & Contract", "row_count": 1, "passed": True}],
        )

        self.assertFalse(gate["passed"])

