from pathlib import Path
import hashlib
import json
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

    def test_gate_parses_export_file_instead_of_trusting_metadata_count(self):
        from tools.contracts.export_download_gauntlet import evaluate_export_download_gate

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            payload_path = root / "artifacts/full_app_validation/cortex.csv"
            payload_path.parent.mkdir(parents=True)
            payload_text = (
                "USER_DISPLAY_NAME,TOTAL_TOKENS,TOTAL_REQUESTS,COST_USD,TOTAL_CREDITS,"
                "TOKENS_PER_REQUEST,TOKENS_PER_DOLLAR,COST_PER_1K_TOKENS_USD,AI_CREDITS_PER_1K_TOKENS\n"
                "Jane Doe,1000,10,2.2,1,100,454.55,2.2,1\n"
            )
            payload_path.write_text(payload_text, encoding="utf-8")
            gate = evaluate_export_download_gate(
                [
                    {
                        "section": "Cortex Efficiency",
                        "workflow": "Explicit action",
                        "payload_file": "artifacts/full_app_validation/cortex.csv",
                        "sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
                        "size_bytes": len(payload_text.encode("utf-8")),
                        "content_type": "text/csv",
                        "parsed_row_count": 2,
                        "visible_row_count": 2,
                        "row_count": 2,
                        "passed": True,
                    }
                ],
                {"passed": True, "download_count": 1},
                [],
                root=root,
            )

        self.assertFalse(gate["passed"])
        self.assertTrue(any(row["code"] == "PAYLOAD_METADATA_ROW_COUNT_MISMATCH" for row in gate["failures"]))

    def test_cortex_efficiency_export_missing_token_fields_fails(self):
        from tools.contracts.export_download_gauntlet import evaluate_export_download_gate

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            payload_path = root / "artifacts/full_app_validation/cortex.csv"
            payload_path.parent.mkdir(parents=True)
            payload_text = "USER_DISPLAY_NAME,TOTAL_TOKENS\nJane Doe,1000\n"
            payload_path.write_text(payload_text, encoding="utf-8")
            gate = evaluate_export_download_gate(
                [
                    {
                        "section": "Cortex Efficiency",
                        "workflow": "Explicit action",
                        "payload_file": "artifacts/full_app_validation/cortex.csv",
                        "sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
                        "size_bytes": len(payload_text.encode("utf-8")),
                        "content_type": "text/csv",
                        "parsed_row_count": 1,
                        "visible_row_count": 1,
                        "row_count": 1,
                        "passed": True,
                    }
                ],
                {"passed": True, "download_count": 1},
                [],
                root=root,
            )

        self.assertFalse(gate["passed"])
        self.assertTrue(any("cortex efficiency export missing required columns" in row.get("failure_reason", "") for row in gate["failures"]))

    def test_case_payload_file_is_parsed_for_required_fields(self):
        from tools.contracts.export_download_gauntlet import evaluate_export_download_gate

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            payload_path = root / "artifacts/full_app_validation/case.json"
            payload_path.parent.mkdir(parents=True)
            payload_text = json.dumps({"section": "Executive Landing", "workflow": "Overview", "row_count": 1})
            payload_path.write_text(payload_text, encoding="utf-8")
            gate = evaluate_export_download_gate(
                [],
                {"passed": True, "download_count": 0},
                [
                    {
                        "section": "Executive Landing",
                        "workflow": "Overview",
                        "payload_file": "artifacts/full_app_validation/case.json",
                        "sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
                        "size_bytes": len(payload_text.encode("utf-8")),
                        "content_type": "application/json",
                        "parsed_row_count": 1,
                        "visible_row_count": 1,
                        "row_count": 1,
                        "passed": True,
                    }
                ],
                root=root,
            )

        self.assertFalse(gate["passed"])
        self.assertTrue(any(row["code"] == "PAYLOAD_SCHEMA_OR_LEAK_FAILURE" for row in gate["failures"]))

    def test_alert_cortex_workflow_is_not_token_efficiency_domain(self):
        from tools.contracts.export_download_gauntlet import evaluate_export_download_gate

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            payload_path = root / "artifacts/full_app_validation/case.json"
            payload_path.parent.mkdir(parents=True)
            payload = {
                "section": "Alert Center",
                "workflow": "Cortex Predictive Alerts",
                "scope": "ALFA / ALL / 7",
                "target": "Selected finding",
                "freshness": "Current",
                "source_family": "compact_evidence",
                "summary": "Evidence click produced filtered rows.",
                "row_count": 1,
                "visible_row_count": 1,
                "recommended_action": "Review filtered evidence.",
            }
            payload_text = json.dumps(payload, sort_keys=True)
            payload_path.write_text(payload_text, encoding="utf-8")
            gate = evaluate_export_download_gate(
                [],
                {"passed": True, "download_count": 0},
                [
                    {
                        **payload,
                        "payload_file": "artifacts/full_app_validation/case.json",
                        "sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
                        "size_bytes": len(payload_text.encode("utf-8")),
                        "content_type": "application/json",
                        "parsed_row_count": 1,
                        "passed": True,
                    }
                ],
                root=root,
            )

        self.assertTrue(gate["passed"], gate)
