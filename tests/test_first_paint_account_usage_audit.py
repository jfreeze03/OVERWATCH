from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
DOC = ROOT / "docs" / "FIRST_PAINT_ACCOUNT_USAGE_AUDIT.md"
sys.path.insert(0, str(APP_ROOT))


FIRST_PAINT_MODULES = (
    "sections/first_paint_contracts.py",
    "sections/section_command_brief.py",
    "sections/section_command_rendering.py",
    "sections/summary_board_contract.py",
    "sections/summary_mart_loaders.py",
    "sections/alert_center_inbox_shell.py",
)

SUMMARY_ENTRY_MODULES = (
    "sections/section_command_brief.py",
    "sections/summary_mart_loaders.py",
)


def _read_app(rel: str) -> str:
    return (APP_ROOT / rel).read_text(encoding="utf-8")


class FirstPaintAccountUsageAuditTests(unittest.TestCase):
    def test_every_app_account_usage_file_is_classified_in_audit_doc(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        offenders = []
        for path in sorted(APP_ROOT.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "SNOWFLAKE.ACCOUNT_USAGE" not in text.upper():
                continue
            rel = f".overwatch_final/{path.relative_to(APP_ROOT).as_posix()}"
            if rel not in doc:
                offenders.append(rel)
        self.assertEqual(offenders, [])
        self.assertIn("unknown | PASS", doc)

    def test_first_paint_modules_do_not_reference_raw_account_usage(self) -> None:
        for rel in FIRST_PAINT_MODULES:
            with self.subTest(module=rel):
                text = _read_app(rel).upper()
                self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", text)

    def test_summary_loaders_do_not_reference_raw_account_usage(self) -> None:
        text = _read_app("sections/summary_mart_loaders.py").upper()
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", text)
        self.assertIn("PROBE_SUMMARY_SOURCE", text)
        self.assertIn("SOURCEPROBERESULT", text)

    def test_first_paint_summary_entry_paths_use_app_facing_marts(self) -> None:
        section_brief = _read_app("sections/section_command_brief.py")
        summary_loaders = _read_app("sections/summary_mart_loaders.py")

        self.assertIn('mart_object_name("MART_SECTION_DECISION_CURRENT_FLAT")', section_brief)
        self.assertIn("MART_SECTION_DECISION_CURRENT", section_brief)
        self.assertNotIn("INFORMATION_SCHEMA", section_brief.upper())
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", section_brief.upper())
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", summary_loaders.upper())

        for rel in SUMMARY_ENTRY_MODULES:
            with self.subTest(module=rel):
                text = _read_app(rel).upper()
                self.assertTrue("MART_" in text or "SUMMARY" in text)


if __name__ == "__main__":
    unittest.main()
