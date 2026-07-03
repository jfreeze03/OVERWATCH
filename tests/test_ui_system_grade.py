from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class UiSystemGradeTests(unittest.TestCase):
    def _write_minimal_ui_files(self, root: Path, *, skip_link: bool = True) -> None:
        (root / ".overwatch_final").mkdir(parents=True)
        (root / ".streamlit").mkdir(parents=True)
        (root / ".overwatch_final" / "theme.py").write_text(
            ".ow-decision-brief {}\n"
            ".ow-skip-to-main {}\n"
            "@media (prefers-reduced-motion: reduce) { * { transition-duration: 0.01ms; } }\n",
            encoding="utf-8",
        )
        shell_text = (
            "def render():\n"
            "    return 'ow-skip-to-main #overwatch-active-section-body'\n"
            if skip_link
            else "def render():\n    return ''\n"
        )
        (root / ".overwatch_final" / "shell.py").write_text(shell_text, encoding="utf-8")
        (root / ".overwatch_final" / "layout.py").write_text(
            "def marker():\n    return 'overwatch-active-section-body'\n",
            encoding="utf-8",
        )
        (root / ".streamlit" / "config.toml").write_text("[theme]\nprimaryColor = '#00AEEF'\n", encoding="utf-8")

    def test_accessibility_baseline_passes(self):
        from tools.contracts.ui_system_grade import evaluate_ui_system_grade

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_ui_files(root)
            results = evaluate_ui_system_grade(root)

        self.assertTrue(results["passed"], results.get("failures"))

    def test_missing_skip_link_is_release_blocking(self):
        from tools.contracts.ui_system_grade import evaluate_ui_system_grade

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_ui_files(root, skip_link=False)
            results = evaluate_ui_system_grade(root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
