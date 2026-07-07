"""Guard against empty placeholder files and inert test scaffolding."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / ".overwatch_final", ROOT / "tools", ROOT / "tests")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if root.exists():
            files.extend(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    return sorted(files)


def _has_real_test_or_assertion(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    has_test = False
    has_assertion = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            has_test = True
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("Test") or any(
                isinstance(base, ast.Attribute) and base.attr == "TestCase"
                for base in node.bases
            ):
                has_test = True
        elif isinstance(node, ast.Assert):
            has_assertion = True
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr.startswith("assert"):
                has_assertion = True
    return has_test and has_assertion


def _is_placeholder_only(path: Path) -> bool:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return True
    tree = ast.parse(text, filename=str(path))
    body = [node for node in tree.body if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant)]
    if not body:
        return True
    return all(isinstance(node, ast.Pass) for node in body)


class NoPlaceholderFilesTest(unittest.TestCase):
    def test_no_empty_python_files_in_active_roots(self) -> None:
        empty = [str(path.relative_to(ROOT)) for path in _python_files() if path.stat().st_size == 0]
        self.assertEqual(empty, [])

    def test_test_modules_have_real_tests_and_assertions(self) -> None:
        inert = [
            str(path.relative_to(ROOT))
            for path in sorted((ROOT / "tests").glob("test_*.py"))
            if not _has_real_test_or_assertion(path)
        ]
        self.assertEqual(inert, [])

    def test_app_modules_are_not_placeholder_only(self) -> None:
        placeholders = [
            str(path.relative_to(ROOT))
            for path in sorted((ROOT / ".overwatch_final").rglob("*.py"))
            if "__pycache__" not in path.parts and _is_placeholder_only(path)
        ]
        self.assertEqual(placeholders, [])


if __name__ == "__main__":
    unittest.main()
