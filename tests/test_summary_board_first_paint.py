import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class SummaryBoardFirstPaintTests(unittest.TestCase):
    def _payloads(self):
        from sections.summary_board_contract import PRIMARY_SUMMARY_SECTIONS, PRIMARY_SUMMARY_WORKFLOWS

        return {
            "artifacts/full_app_validation/view_results.json": [
                {
                    "id": section.lower().replace(" ", "_"),
                    "section": section,
                    "workflow": PRIMARY_SUMMARY_WORKFLOWS[section],
                    "rendered_fragment_count": 1,
                    "raised": "",
                    "elapsed_ms": 25,
                    "first_paint": {
                        "observed_packet_queries": 1,
                        "observed_non_packet_first_paint_events": 0,
                        "observed_warm_packet_queries": 0,
                        "observed_session_opens": 0,
                        "observed_direct_sql_events": 0,
                    },
                }
                for section in PRIMARY_SUMMARY_SECTIONS
            ],
            "artifacts/full_app_validation/rendered_fragments.json": [
                {
                    "id": section.lower().replace(" ", "_"),
                    "section": section,
                    "text": f"{section} summary ready. Evidence available behind explicit action.",
                }
                for section in PRIMARY_SUMMARY_SECTIONS
            ],
        }

    def test_summary_boards_pass_packet_only_first_paint(self):
        from sections.summary_board_contract import build_summary_board_query_budget_results, build_summary_board_rows

        rows = build_summary_board_rows(self._payloads())
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["passed"] for row in rows), rows)
        budget = build_summary_board_query_budget_results(rows)
        self.assertTrue(budget["passed"], budget)

    def test_summary_board_fails_on_account_usage_first_paint(self):
        from sections.summary_board_contract import build_summary_board_rows

        payloads = self._payloads()
        payloads["artifacts/full_app_validation/view_results.json"][0]["first_paint"]["first_paint_account_usage"] = 1
        rows = build_summary_board_rows(payloads)
        first = rows[0]
        self.assertFalse(first["passed"], first)
        self.assertIn("account_usage_on_first_paint", first["failed_checks"])

    def test_summary_board_fails_on_old_surface_marker(self):
        from sections.summary_board_contract import build_summary_board_rows

        payloads = self._payloads()
        payloads["artifacts/full_app_validation/rendered_fragments.json"][0]["text"] = "legacy command deck"
        rows = build_summary_board_rows(payloads)
        first = rows[0]
        self.assertFalse(first["passed"], first)
        self.assertIn("old_surface_marker_visible", first["failed_checks"])

    def test_summary_board_artifacts_are_written(self):
        from sections.summary_board_contract import write_summary_board_artifacts

        payloads = self._payloads()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "artifacts" / "full_app_validation"
            out.mkdir(parents=True)
            (out / "view_results.json").write_text(
                json.dumps(payloads["artifacts/full_app_validation/view_results.json"]),
                encoding="utf-8",
            )
            (out / "rendered_fragments.json").write_text(
                json.dumps(payloads["artifacts/full_app_validation/rendered_fragments.json"]),
                encoding="utf-8",
            )
            artifacts = write_summary_board_artifacts(root)
            self.assertIn("artifacts/full_app_validation/summary_board_results.json", artifacts)
            self.assertTrue((out / "summary_board_query_budget_results.json").exists())


if __name__ == "__main__":
    unittest.main()
