"""Guards keeping audit/test scaffolding out of active app runtime."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
LAYOUT = APP_ROOT / "layout.py"


class NoTestArtifactsInAppRuntimeTest(unittest.TestCase):
    def test_runtime_modules_do_not_import_test_or_audit_roots(self) -> None:
        forbidden_prefixes = ("tests", "perf_tests", "artifacts", "docs")
        offenders: list[str] = []
        for path in sorted(APP_ROOT.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] in forbidden_prefixes:
                        offenders.append(f"{path.relative_to(ROOT)} imports {name}")
        self.assertEqual(offenders, [])

    def test_sidebar_audit_matches_layout_implementation(self) -> None:
        layout_text = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("def render_sidebar_utilities", layout_text)
        self.assertIn("APP CONTROLS", layout_text)
        audit_text = (ROOT / "docs" / "UI_SNAPSHOT_AUDIT.md").read_text(encoding="utf-8")
        if "APP CONTROLS" in audit_text or "UTILITIES" in audit_text:
            self.assertIn("render_sidebar_utilities", layout_text)


if __name__ == "__main__":
    unittest.main()
