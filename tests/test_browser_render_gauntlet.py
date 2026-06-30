from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class BrowserRenderGauntletTests(unittest.TestCase):
    def test_browser_render_writes_snapshots_and_fragments(self):
        from tools.contracts.browser_render_gauntlet import (
            BROWSER_RENDER_GATE_REL,
            BROWSER_RENDER_RESULTS_REL,
            RENDERED_FRAGMENTS_REL,
            write_browser_render_gauntlet_artifacts,
        )

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifacts = write_browser_render_gauntlet_artifacts(root)
            results = artifacts[BROWSER_RENDER_RESULTS_REL]

            self.assertIn(BROWSER_RENDER_GATE_REL, artifacts)
            self.assertIn(RENDERED_FRAGMENTS_REL, artifacts)
            self.assertTrue(results["passed"], results)
            for row in results["rows"]:
                self.assertTrue((root / row["screenshot_or_snapshot_path"]).exists(), row)
            self.assertTrue((root / "artifacts/browser_screenshots/SKIPPED.txt").exists())

    def test_daily_diagnostic_card_fails_render_gate(self):
        from tools.contracts.browser_render_gauntlet import build_browser_render_results, evaluate_browser_render_gate

        payloads = {
            "artifacts/full_app_validation/rendered_fragments.json": [
                {
                    "section": "Executive Landing",
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
