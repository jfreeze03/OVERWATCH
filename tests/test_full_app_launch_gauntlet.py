from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PRIMARY_SECTIONS = [
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
]


class FullAppLaunchGauntletTests(unittest.TestCase):
    def _payloads(self):
        return {
            "artifacts/full_app_validation/view_results.json": [
                {
                    "section": section,
                    "workflow": "Overview",
                    "passed": True,
                    "first_paint": {
                        "observed_packet_queries": 1,
                        "warm_packet_queries": 0,
                        "evidence_query_count": 0,
                        "account_usage_query_count": 0,
                        "detail_query_count": 0,
                        "observed_session_opens": 0,
                        "observed_direct_sql_events": 0,
                        "elapsed_ms": 120,
                    },
                }
                for section in PRIMARY_SECTIONS
            ],
            "artifacts/full_app_validation/button_click_results.json": [
                {"section": "Executive Landing", "workflow": "Overview", "label": "View all priorities", "clicked": True, "passed": True}
            ],
            "artifacts/full_app_validation/settings_action_results.json": [
                {"control_key": "theme_picker", "clicked": True, "passed": True}
            ],
            "artifacts/full_app_validation/live_feature_results.json": [
                {
                    "feature": "Snowflake CLI validation",
                    "clicked": True,
                    "passed": True,
                    "first_paint_invocation": False,
                    "route_invocation": False,
                }
            ],
            "artifacts/full_app_validation/export_results.json": [
                {
                    "section": "Query Search",
                    "workflow": "Default export",
                    "passed": True,
                    "payload_file": "artifacts/full_app_validation/query_export.csv",
                    "row_count": 1,
                    "visible_row_count": 1,
                    "sha256": "abc",
                    "contains_query_text": False,
                }
            ],
            "artifacts/full_app_validation/case_payload_results.json": [
                {
                    "section": "Cost & Contract",
                    "workflow": "Case",
                    "scope": "ALFA",
                    "target": "cost",
                    "freshness": "current",
                    "source": "packet",
                    "summary": "ready",
                    "row_count": 1,
                    "visible_row_count": 1,
                    "passed": True,
                }
            ],
            "artifacts/full_app_validation/query_search_results.json": [
                {"case": "render_no_click", "passed": True, "snowflake_execution_count": 0, "clicked": False}
            ],
            "artifacts/full_app_validation/evidence_loader_call_matrix.json": [
                {"section": "Executive Landing", "workflow": "Evidence", "passed": True, "clicked": True}
            ],
            "artifacts/full_app_validation/stress_results.json": [
                {"scenario": "rapid_section_switching", "passed": True}
            ],
            "artifacts/full_app_validation/summary_board_results.json": [
                {
                    "section": section,
                    "passed": True,
                    "summary_board_count": 1,
                    "diagnostic_card_count": 0,
                    "unavailable_tile_count": 0,
                    "old_board_marker_count": 0,
                    "action_contract_passed": True,
                    "headline_raw_number": False,
                }
                for section in PRIMARY_SECTIONS
            ],
        }

    def test_launch_gauntlet_requires_primary_sections(self):
        from tools.contracts.full_app_launch_gauntlet import build_full_app_launch_gauntlet

        payloads = self._payloads()
        results, failures, rows = build_full_app_launch_gauntlet(payloads, ROOT)

        self.assertTrue(results["passed"], failures)
        self.assertGreater(len(rows), 6)

        payloads["artifacts/full_app_validation/view_results.json"] = payloads[
            "artifacts/full_app_validation/view_results.json"
        ][:-1]
        results, failures, _rows = build_full_app_launch_gauntlet(payloads, ROOT)
        self.assertFalse(results["passed"])
        self.assertTrue(any(row["failure_reason"] == "missing_primary_section" for row in failures["failures"]))

    def test_settings_wording_is_compact_and_setup_health_not_sidebar_default(self):
        from tools.contracts.full_app_launch_gauntlet import build_settings_wording_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = root / ".overwatch_final/layout.py"
            layout.parent.mkdir(parents=True)
            layout.write_text('st.caption("Cost estimates use configured credit rates.")\n', encoding="utf-8")
            admin = root / ".overwatch_final" / "sections" / "decision_workspace_setup_health.py"
            admin.parent.mkdir(parents=True, exist_ok=True)
            admin.write_text(
                '"""Admin-only setup health."""\n\ndef render_decision_setup_health_panel():\n    pass\n',
                encoding="utf-8",
            )
            result = build_settings_wording_results(root)
        self.assertTrue(result["passed"], result)
