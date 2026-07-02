from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"


class PrivateImportHygieneTests(unittest.TestCase):
    def test_public_display_sanitizer_replaces_shell_private_imports(self):
        offenders: list[str] = []
        alias_offenders: list[str] = []
        for path in APP_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module == "sections.shell_helpers" and any(alias.name == "_clean_display_text" for alias in node.names):
                    offenders.append(str(path.relative_to(ROOT)).replace("\\", "/"))
            if "_clean_display_text = clean_display_text" in text or "_clean_display_text(" in text:
                alias_offenders.append(str(path.relative_to(ROOT)).replace("\\", "/"))

        self.assertEqual(offenders, [])
        self.assertEqual(alias_offenders, [])

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

    def test_private_cross_module_imports_do_not_escape_split_packages(self):
        offenders: list[str] = []
        for path in APP_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                module = node.module or ""
                for alias in node.names:
                    if not alias.name.startswith("_") or alias.name.startswith("__"):
                        continue
                    section_split_import = rel.startswith(".overwatch_final/sections/") and module.startswith("sections.")
                    local_relative_import = node.level > 0 and (
                        rel.startswith(".overwatch_final/sections/")
                        or rel.startswith(".overwatch_final/utils/")
                    )
                    if section_split_import or local_relative_import:
                        continue
                    offenders.append(f"{rel}:{node.lineno} imports {module}.{alias.name}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
