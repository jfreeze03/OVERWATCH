from pathlib import Path
import contextlib
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class OperatorCaseTests(unittest.TestCase):
    def test_operator_case_module_has_no_query_imports(self):
        source = (APP_ROOT / "sections" / "operator_case.py").read_text(encoding="utf-8")

        self.assertNotRegex(source, r"\brun_query(?:_or_raise)?\b")
        self.assertNotRegex(source, r"\bget_session(?:_for_action)?\b")
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", source)
        self.assertNotIn("_load_", source)

    def test_add_case_evidence_uses_explicit_item(self):
        from sections.operator_case import add_case_evidence, current_case_items, make_case_evidence

        state: dict[str, object] = {}
        item = make_case_evidence(
            section="Alert Center",
            workflow="Active Alerts",
            scope="ALFA / PROD",
            freshness="Loaded 20:00",
            source="ALERTS",
            summary="2 critical alerts",
            next_action="Route the critical alert.",
            evidence_rows_preview=({"SEVERITY": "Critical", "ALERT": "Warehouse queue"},),
        )

        self.assertEqual(add_case_evidence(item, state), 1)
        items = current_case_items(state)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].section, "Alert Center")
        self.assertEqual(items[0].evidence_rows_preview[0]["SEVERITY"], "Critical")

    def test_markdown_export_includes_handoff_fields(self):
        from sections.operator_case import build_case_markdown, make_case_evidence

        item = make_case_evidence(
            section="Security Monitoring",
            workflow="Security Overview",
            scope="ALFA / PROD / 30 days",
            freshness="Loaded security summary",
            source="Security summary",
            summary="Security score 92",
            next_action="Review risky grants.",
            evidence_rows_preview=({"ENTITY": "USER_A", "FINDING": "MFA gap"},),
        )

        markdown = build_case_markdown((item,))

        self.assertIn("# OVERWATCH Operator Case File", markdown)
        self.assertIn("Security Monitoring", markdown)
        self.assertIn("ALFA / PROD / 30 days", markdown)
        self.assertIn("Loaded security summary", markdown)
        self.assertIn("Review risky grants.", markdown)
        self.assertIn("| ENTITY | FINDING |", markdown)

    def test_case_drawer_handles_empty_and_multi_section_cases(self):
        from sections import operator_case
        from sections.operator_case import make_case_evidence

        empty_context = contextlib.nullcontext()
        with patch.object(operator_case.st, "expander", return_value=empty_context), patch.object(
            operator_case,
            "current_case_items",
            return_value=(),
        ), patch.object(operator_case.st, "caption") as caption, patch.object(
            operator_case,
            "download_text",
            side_effect=AssertionError("empty drawer should not render an export"),
        ):
            operator_case.render_case_drawer()
        caption.assert_called()

        items = (
            make_case_evidence(
                section="Alert Center",
                workflow="Active Alerts",
                scope="ALFA",
                freshness="Loaded",
                source="Alerts",
                summary="One alert",
                next_action="Route alert.",
            ),
            make_case_evidence(
                section="Cost & Contract",
                workflow="Cost Overview",
                scope="ALFA",
                freshness="Loaded",
                source="Cost",
                summary="Spend up",
                next_action="Review warehouse.",
            ),
        )
        with patch.object(operator_case.st, "expander", return_value=contextlib.nullcontext()), patch.object(
            operator_case,
            "current_case_items",
            return_value=items,
        ), patch.object(operator_case.st, "caption"), patch.object(operator_case.st, "markdown"), patch.object(
            operator_case.st,
            "button",
            return_value=False,
        ), patch.object(operator_case, "download_text") as download:
            operator_case.render_case_drawer()

        download.assert_called_once()
        self.assertIn("overwatch_operator_case_file.md", download.call_args.args)

    def test_ux_guidelines_document_operator_case_file(self):
        docs = (ROOT / "UX_PRODUCTION_GUIDELINES.md").read_text(encoding="utf-8")

        self.assertIn("Operator Case File", docs)
        self.assertIn("already-loaded evidence", docs)
        self.assertIn("does not query Snowflake", docs)
        self.assertIn("freshness/source notes", docs)


if __name__ == "__main__":
    unittest.main()
