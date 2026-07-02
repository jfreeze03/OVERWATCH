from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"


class PrivateImportHygieneTests(unittest.TestCase):
    def test_public_display_sanitizer_replaces_shell_private_imports(self):
        offenders: list[str] = []
        for path in APP_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module == "sections.shell_helpers" and any(alias.name == "_clean_display_text" for alias in node.names):
                    offenders.append(str(path.relative_to(ROOT)).replace("\\", "/"))

        self.assertEqual(offenders, [])

        display_safety = (APP_ROOT / "utils" / "display_safety.py").read_text(encoding="utf-8")
        self.assertIn("def clean_display_text", display_safety)
        triage = (APP_ROOT / "sections" / "triage_queue.py").read_text(encoding="utf-8")
        self.assertIn("from utils.display_safety import clean_display_text", triage)
        self.assertNotIn("from sections.shell_helpers import _clean_display_text", triage)

    def test_retired_query_workbench_module_is_not_production_runtime(self):
        self.assertFalse((APP_ROOT / "sections" / "query_workbench.py").exists())
        production_refs: list[str] = []
        allowed_cleanup_refs = {"tools/contracts/delete_first_cleanup.py"}
        for base in (APP_ROOT, ROOT / "tools" / "contracts"):
            for path in base.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                if "sections.query_workbench" in text or "query_workbench.py" in text:
                    rel = str(path.relative_to(ROOT)).replace("\\", "/")
                    if rel not in allowed_cleanup_refs:
                        production_refs.append(rel)
        self.assertEqual(production_refs, [])


if __name__ == "__main__":
    unittest.main()
