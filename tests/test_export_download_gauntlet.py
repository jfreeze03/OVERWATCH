from pathlib import Path
import hashlib
import sys
import tempfile
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

    def test_download_requires_real_file_and_matching_hash(self):
        from tools.contracts.full_app_launch_gauntlet import build_download_results

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            payload_path = root / "artifacts/full_app_validation/export.csv"
            payload_path.parent.mkdir(parents=True)
            payload_path.write_text("QUERY_ID,QUERY_HASH\n01abc,hash\n", encoding="utf-8")
            sha256 = hashlib.sha256(payload_path.read_bytes()).hexdigest()

            results = build_download_results(
                {
                    "artifacts/full_app_validation/export_results.json": [
                        {
                            "section": "Query Search",
                            "workflow": "Default export",
                            "payload_file": "artifacts/full_app_validation/export.csv",
                            "row_count": 1,
                            "visible_row_count": 1,
                            "sha256": sha256,
                            "content_type": "text/csv",
                            "query_text_included": False,
                            "passed": True,
                        }
                    ]
                },
                root,
            )

        self.assertTrue(results["passed"], results)
        self.assertTrue(results["rows"][0]["payload_file_exists"])
        self.assertTrue(results["rows"][0]["hash_matches"])

    def test_hash_mismatch_fails_download_results(self):
        from tools.contracts.full_app_launch_gauntlet import build_download_results

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            payload_path = root / "artifacts/full_app_validation/export.csv"
            payload_path.parent.mkdir(parents=True)
            payload_path.write_text("QUERY_ID\n01abc\n", encoding="utf-8")
            results = build_download_results(
                {
                    "artifacts/full_app_validation/export_results.json": [
                        {
                            "section": "Query Search",
                            "workflow": "Default export",
                            "payload_file": "artifacts/full_app_validation/export.csv",
                            "row_count": 1,
                            "visible_row_count": 1,
                            "sha256": "wrong",
                            "content_type": "text/csv",
                            "query_text_included": False,
                            "passed": True,
                        }
                    ]
                },
                root,
            )

        self.assertFalse(results["passed"])
        self.assertFalse(results["rows"][0]["hash_matches"])

    def test_cost_export_missing_bridge_fields_fails(self):
        from tools.contracts.full_app_launch_gauntlet import build_download_results

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            payload_path = root / "artifacts/full_app_validation/cost.csv"
            payload_path.parent.mkdir(parents=True)
            payload_path.write_text("ACCOUNT_BILLED_COST_USD\n10\n", encoding="utf-8")
            sha256 = hashlib.sha256(payload_path.read_bytes()).hexdigest()
            results = build_download_results(
                {
                    "artifacts/full_app_validation/export_results.json": [
                        {
                            "section": "Cost & Contract",
                            "workflow": "Overview export",
                            "payload_file": "artifacts/full_app_validation/cost.csv",
                            "row_count": 1,
                            "visible_row_count": 1,
                            "sha256": sha256,
                            "content_type": "text/csv",
                            "query_text_included": False,
                            "passed": True,
                        }
                    ]
                },
                root,
            )

        self.assertFalse(results["passed"])
        self.assertIn("BILLING_BRIDGE_STATUS", results["rows"][0]["cost_required_missing"])

    def test_case_payload_missing_required_field_fails_gate(self):
        from tools.contracts.export_download_gauntlet import evaluate_export_download_gate

        gate = evaluate_export_download_gate(
            {"passed": True, "export_count": 1},
            {"passed": True, "download_count": 1},
            [{"section": "Cost & Contract", "row_count": 1, "passed": True}],
        )

        self.assertFalse(gate["passed"])
