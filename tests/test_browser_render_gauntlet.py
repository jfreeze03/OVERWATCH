from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class BrowserRenderGauntletTests(unittest.TestCase):
    def test_browser_render_requires_rendered_producer_fragment(self):
        from tools.contracts.browser_render_gauntlet import (
            BROWSER_RENDER_GATE_REL,
            BROWSER_RENDER_RESULTS_REL,
            RENDERED_FRAGMENTS_REL,
            write_browser_render_gauntlet_artifacts,
        )

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            payloads = {
                "artifacts/full_app_validation/deterministic_streamlit_render_results.json": {
                    "rows": [
                        {
                            "section": section,
                            "workflow": "Overview",
                            "source": "deterministic_streamlit_rendered",
                            "rendered": True,
                            "first_viewport_text": f"{section} summary board",
                            "summary_board_count": 1,
                            "passed": True,
                        }
                        for section in (
                            "Executive Landing",
                            "DBA Control Room",
                            "Alert Center",
                            "Cost & Contract",
                            "Workload Operations",
                            "Security Monitoring",
                            "Query Search",
                            "Advanced Scope",
                            "Settings",
                            "Settings/Admin Setup Health",
                        )
                    ]
                }
            }
            artifacts = write_browser_render_gauntlet_artifacts(root, payloads)
            results = artifacts[BROWSER_RENDER_RESULTS_REL]

            self.assertIn(BROWSER_RENDER_GATE_REL, artifacts)
            self.assertIn(RENDERED_FRAGMENTS_REL, artifacts)
            self.assertTrue(results["passed"], results)
            for row in results["rows"]:
                self.assertTrue((root / row["screenshot_or_snapshot_path"]).exists(), row)
            self.assertTrue((root / "artifacts/browser_screenshots/SKIPPED.txt").exists())

    def test_synthetic_safe_fallback_fails_under_internal_live(self):
        from tools.contracts.browser_render_gauntlet import build_browser_render_results, evaluate_browser_render_gate

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            results = build_browser_render_results(Path(tmp), payloads={}, launch_profile="internal_live")
            gate = evaluate_browser_render_gate(results)

        self.assertFalse(results["passed"])
        self.assertFalse(gate["passed"])
        self.assertGreater(gate["synthetic_fallback_count"], 0)
        self.assertTrue(all(not row["rendered"] for row in results["rows"]))

    def test_daily_diagnostic_card_fails_render_gate(self):
        from tools.contracts.browser_render_gauntlet import build_browser_render_results, evaluate_browser_render_gate

        payloads = {
            "artifacts/full_app_validation/rendered_fragments.json": [
                {
                    "section": "Executive Landing",
                    "source": "deterministic_streamlit_rendered",
                    "rendered": True,
                    "text": "Executive diagnostic card Traceback",
                }
            ]
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            results = build_browser_render_results(Path(tmp), payloads)
            gate = evaluate_browser_render_gate(results)

        self.assertFalse(results["passed"])
        self.assertFalse(gate["passed"])
        self.assertGreater(gate["failure_count"], 0)

    def test_settings_compact_text_passes(self):
        from tools.contracts.browser_render_gauntlet import build_browser_render_results

        payloads = {
            "artifacts/full_app_validation/rendered_fragments.json": [
                {
                    "section": "Settings",
                    "source": "deterministic_streamlit_rendered",
                    "rendered": True,
                    "text": "Settings. Cost estimates use configured credit rates. Open Setup Health.",
                }
            ]
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            results = build_browser_render_results(Path(tmp), payloads)
            settings = [row for row in results["rows"] if row["section"] == "Settings"][0]

        self.assertTrue(settings["passed"], settings)
        self.assertEqual(settings["raw_internal_token_count"], 0)


if __name__ == "__main__":
    unittest.main()
