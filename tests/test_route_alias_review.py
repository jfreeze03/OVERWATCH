from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import route_registry  # noqa: E402


DOC = ROOT / "docs" / "ROUTE_ALIAS_REVIEW.md"


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _row_pattern(*cells: str) -> re.Pattern[str]:
    escaped = [re.escape(cell) for cell in cells]
    return re.compile(r"^\| " + r" \| ".join(escaped) + r" \| .* \| KEEP \|$", re.MULTILINE)


class RouteAliasReviewTests(unittest.TestCase):
    def test_route_alias_review_documents_every_registered_alias(self) -> None:
        text = _doc_text()
        self.assertIn("test_route_alias_review_documents_every_registered_alias", text)
        self.assertIn("| Alias | Canonical Section | Reason To Keep |", text)
        self.assertIn("| Alias | Canonical Section | Canonical Workflow |", text)

        for alias, target in route_registry.LEGACY_SECTION_ALIASES.items():
            with self.subTest(kind="section", alias=alias):
                self.assertRegex(text, _row_pattern(alias, target))

        for section, aliases in route_registry.WORKFLOW_ALIASES_BY_SECTION.items():
            for alias, workflow in aliases.items():
                with self.subTest(kind="workflow", section=section, alias=alias):
                    self.assertRegex(text, _row_pattern(alias, section, workflow))

    def test_route_alias_review_keeps_retired_alias_bucket_empty(self) -> None:
        text = _doc_text()
        self.assertEqual(route_registry.RETIRED_SECTION_ALIASES, {})
        self.assertIn("Retired primary-section redirect bucket", text)
        self.assertIn("DELETE", text)
        self.assertNotIn("ABANDONED_PRIMARY_SECTION_TITLES", (APP_ROOT / "route_registry.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
