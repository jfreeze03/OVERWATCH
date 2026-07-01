from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / ".overwatch_final"
for path in (ROOT, APP):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class DecisionWorkspaceTargetFilterTests(unittest.TestCase):
    def test_structured_filter_uses_exact_allowlisted_columns(self):
        from sections.decision_workspace_target_filters import build_target_sql_filter_contract

        contract = build_target_sql_filter_contract(
            "Workload Operations",
            {"entity_type": "query_id", "entity_id": "01abc"},
            alias="q",
            available_columns=("QUERY_ID", "QUERY_TEXT"),
        )

        self.assertEqual(contract.match_mode, "exact")
        self.assertIn("OVERWATCH_TARGET_PREDICATE", contract.sql_fragment)
        self.assertIn("QUERY_ID", contract.sql_fragment)
        self.assertNotIn("QUERY_TEXT", contract.sql_fragment)
        self.assertEqual(contract.matched_columns, ("QUERY_ID",))
        self.assertFalse(contract.raw_sql_included)

    def test_display_fallback_is_explicit_and_allowlisted(self):
        from sections.decision_workspace_target_filters import build_target_sql_filter_contract

        contract = build_target_sql_filter_contract(
            "Cost & Contract",
            {"entity_type": "service", "entity_name": "Cortex AI"},
            available_columns=("ENTITY_NAME", "QUERY_TEXT"),
        )

        self.assertEqual(contract.match_mode, "allowed_ilike")
        self.assertIn("ILIKE", contract.sql_fragment)
        self.assertEqual(contract.matched_columns, ("ENTITY_NAME",))

    def test_no_allowlisted_target_returns_none_mode(self):
        from sections.decision_workspace_target_filters import build_target_sql_filter_contract

        contract = build_target_sql_filter_contract(
            "Security Monitoring",
            {"entity_type": "unknown", "entity_id": "value"},
            available_columns=("QUERY_TEXT",),
        )

        self.assertEqual(contract.match_mode, "none")
        self.assertEqual(contract.sql_fragment, "")


if __name__ == "__main__":
    unittest.main()
