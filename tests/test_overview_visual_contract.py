from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


import theme as theme_module  # noqa: E402


class OverviewVisualContractTests(unittest.TestCase):
    def test_view_all_priorities_is_real_button_contract(self):
        from route_registry import SECTION_WORKFLOW_CONTRACT
        from sections.button_action_contracts import resolve_button_action_contract
        from sections.metric_semantic_registry import PRIMARY_METRIC_KEYS

        rendering_text = (APP_ROOT / "sections" / "section_command_rendering.py").read_text(encoding="utf-8")
        self.assertNotIn('<a class="ow-decision-view-all"', rendering_text)
        self.assertIn("_view_all_priorities", rendering_text)
        for section in PRIMARY_METRIC_KEYS:
            workflow = SECTION_WORKFLOW_CONTRACT[section][0]
            key = f"{section.lower().replace(' ', '_').replace('&', 'and')}_view_all_priorities"
            contract = resolve_button_action_contract(
                section=section,
                workflow=workflow,
                label="View all priorities",
                key=key,
            )
            self.assertIsNotNone(contract, section)
            assert contract is not None
            self.assertEqual(contract.action_type, "route")
            self.assertEqual(contract.expected_query_count, 0)
            self.assertEqual(contract.expected_session_open_count, 0)
            self.assertEqual(contract.expected_direct_sql_count, 0)
            self.assertEqual(contract.expected_snowflake_execution_count, 0)

    def test_attention_grid_matches_rendered_cell_count(self):
        theme_text = theme_module._combined_theme_css("carbon")
        self.assertIn("grid-template-columns: 28px 56px minmax(180px, 1fr)", theme_text)
        self.assertIn("white-space: nowrap", theme_text)

    def test_sql_headlines_do_not_start_with_raw_counts(self):
        for relative in ("snowflake/mart_setup/05_load_procedures.sql", "snowflake/OVERWATCH_MART_SETUP.sql"):
            sql = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("workload failure signals need triage", sql)
            self.assertNotIn("DBA failure signals need triage", sql)
            self.assertIn("Workload failed SQL needs triage.", sql)
            self.assertIn("Pipeline failures need triage.", sql)

    def test_sla_risk_is_score_not_failure_count(self):
        for relative in ("snowflake/mart_setup/05_load_procedures.sql", "snowflake/OVERWATCH_MART_SETUP.sql"):
            sql = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("'sla_risk', 'Pipeline Failure Risk'", sql)
            self.assertIn("'percentage', 'risk_score'", sql)
            self.assertIn("proxy risk score", sql)
            self.assertNotIn("'sla_risk', 'Pipeline Failure Risk',\n           TO_VARCHAR(IFF", sql)


if __name__ == "__main__":
    unittest.main()
