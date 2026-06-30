from pathlib import Path
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class BrowserSmokeRunnerTests(unittest.TestCase):
    def test_internal_fixture_skip_passes_with_deterministic_render(self):
        from tools.contracts.browser_smoke_runner import build_browser_smoke_results, evaluate_browser_smoke_gate

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/deterministic_streamlit_render_results.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"passed": True, "rendered_row_count": 6}), encoding="utf-8")
            results = build_browser_smoke_results(root, launch_profile="internal_fixture")
            gate = evaluate_browser_smoke_gate(results)

        self.assertTrue(results["skipped"])
        self.assertTrue(results["passed"], results)
        self.assertTrue(gate["passed"], gate)
        self.assertFalse(results["rows"])

    def test_internal_live_skip_fails_without_browser(self):
        from tools.contracts.browser_smoke_runner import build_browser_smoke_results

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/full_app_validation/deterministic_streamlit_render_results.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"passed": True, "rendered_row_count": 6}), encoding="utf-8")
            results = build_browser_smoke_results(root, launch_profile="internal_live")

        self.assertTrue(results["skipped"])
        self.assertFalse(results["passed"])
        self.assertEqual(results["failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
