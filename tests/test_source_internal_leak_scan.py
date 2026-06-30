from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SourceInternalLeakScanTests(unittest.TestCase):
    def test_daily_source_internal_wording_fails(self):
        from tools.contracts.source_internal_leak_scan import build_source_internal_leak_scan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / ".overwatch_final"
            app.mkdir()
            (app / "layout.py").write_text("st.caption('diagnostic card')\n", encoding="utf-8")
            result = build_source_internal_leak_scan(root, {})

        self.assertFalse(result["passed"])
        self.assertGreater(result["source_internal_leak_count"], 0)

    def test_clean_daily_source_passes(self):
        from tools.contracts.source_internal_leak_scan import build_source_internal_leak_scan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / ".overwatch_final"
            app.mkdir()
            (app / "layout.py").write_text("st.caption('Cost estimates use configured credit rates.')\n", encoding="utf-8")
            result = build_source_internal_leak_scan(root, {})

        self.assertTrue(result["passed"], result)

