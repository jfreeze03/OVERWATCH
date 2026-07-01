from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class QuerySearchPerformanceRuleTests(unittest.TestCase):
    def test_only_exact_query_or_signature_targets_autorun(self):
        source = (ROOT / ".overwatch_final" / "sections" / "query_search.py").read_text(encoding="utf-8")

        self.assertIn('target_kind in {"query_id", "query_signature"}', source)
        self.assertNotRegex(source, r"qs_autorun[^\n]+warehouse")
        self.assertNotRegex(source, r"qs_autorun[^\n]+text")

    def test_deep_history_requires_confirmation_and_explicit_click(self):
        source = (ROOT / ".overwatch_final" / "sections" / "query_search.py").read_text(encoding="utf-8")

        self.assertIn("qs_account_usage_fallback_confirmed", source)
        self.assertIn("qs_account_usage_fallback", source)
        self.assertRegex(source, re.compile(r"account_usage_requested\s+and\s+not\s+fallback_confirmed"))
        self.assertIn('query_budget_context("account_usage_fallback"', source)


if __name__ == "__main__":
    unittest.main()
