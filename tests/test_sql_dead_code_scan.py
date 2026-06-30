from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SqlDeadCodeScanTests(unittest.TestCase):
    def test_old_surface_marker_fails(self):
        from tools.contracts.sql_dead_code_scan import build_sql_dead_code_scan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / ".overwatch_final"
            app.mkdir()
            (app / "layout.py").write_text("TITLE = 'command deck'\n", encoding="utf-8")
            result = build_sql_dead_code_scan(root)

        self.assertFalse(result["passed"])
        self.assertEqual(result["failures"][0]["marker"], "command deck")

