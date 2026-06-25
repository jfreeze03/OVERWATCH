from pathlib import Path
import contextlib
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class SectionCommandBriefTests(unittest.TestCase):
    def test_contracts_cover_all_primary_sections(self):
        from route_registry import PRIMARY_SECTION_TITLES
        from sections.section_command_contracts import SECTION_COMMAND_CONTRACTS

        self.assertEqual(tuple(SECTION_COMMAND_CONTRACTS), PRIMARY_SECTION_TITLES)
        source = (APP_ROOT / "sections" / "section_command_contracts.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", source)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", source)
        self.assertNotRegex(source, r"\brun_query(?:_or_raise)?\s*\(")
        for section, contract in SECTION_COMMAND_CONTRACTS.items():
            with self.subTest(section=section):
                self.assertEqual(contract.section, section)
                self.assertGreaterEqual(len(contract.metric_labels), 4)
                self.assertTrue(contract.detail_cta)
                self.assertTrue(contract.source_table)
                self.assertTrue(contract.next_actions)

    def test_loader_uses_mart_rows_and_does_not_require_detail_load(self):
        from sections import section_command_brief as brief_module

        brief_rows = pd.DataFrame([{
            "SECTION_NAME": "Cost & Contract",
            "COMPANY": "ALFA",
            "ENVIRONMENT": "ALL",
            "WINDOW_DAYS": 7,
            "STATE": "Summary loaded",
            "HEADLINE": "Cost movement needs review.",
            "SUMMARY": "Cortex cost is the top movement.",
            "TOP_SIGNAL": "Cortex AI spend",
            "TOP_ENTITY": "Cortex",
            "TOP_ACTION": "Review Cortex AI Costs",
            "SOURCE_STATUS": "Summary loaded from mart",
            "SOURCE_FRESHNESS": "5 minutes ago",
            "SNAPSHOT_TS": "2026-06-25 10:00:00",
            "LOAD_TS": "2026-06-25 10:05:00",
        }])
        metric_rows = pd.DataFrame([
            {"METRIC_LABEL": "Total spend", "METRIC_VALUE": "$120", "METRIC_DETAIL": "7d", "SORT_ORDER": 10},
            {"METRIC_LABEL": "Cortex AI spend", "METRIC_VALUE": "$42", "METRIC_DETAIL": "35%", "METRIC_TONE": "cortex", "SORT_ORDER": 20},
        ])
        exception_rows = pd.DataFrame([{
            "SEVERITY": "High",
            "SIGNAL": "Cortex AI spend",
            "ENTITY_NAME": "Cortex",
            "DETAIL": "Spend accelerated.",
            "ROUTE_SECTION": "Cost & Contract",
            "ROUTE_WORKFLOW": "Cortex AI",
            "SORT_ORDER": 1,
        }])
        action_rows = pd.DataFrame([{
            "ACTION_LABEL": "Review Cortex AI Costs",
            "ACTION_DETAIL": "Open the Cortex lane.",
            "TARGET_SECTION": "Cost & Contract",
            "TARGET_WORKFLOW": "Cortex AI",
            "SESSION_STATE_UPDATES_JSON": '{"cost_contract_workflow":"Cortex AI"}',
            "SORT_ORDER": 1,
        }])

        with patch.object(brief_module.st, "session_state", {}), patch.object(
            brief_module,
            "run_query",
            side_effect=[brief_rows, metric_rows, exception_rows, action_rows],
        ) as run_query:
            brief = brief_module.autoload_section_command_brief("Cost & Contract", "ALFA", "ALL", 7)

        self.assertEqual(brief.state, "Summary loaded")
        self.assertEqual(brief.headline, "Cost movement needs review.")
        self.assertEqual(brief.metrics[0].label, "Total spend")
        self.assertEqual(brief.metrics[1].tone, "cortex")
        self.assertEqual(brief.top_signal.signal, "Cortex AI spend")
        self.assertEqual(brief.next_actions[0].target_workflow, "Cortex AI")
        self.assertEqual(run_query.call_count, 4)

    def test_loader_fallback_is_non_crashing_when_mart_unavailable(self):
        from sections import section_command_brief as brief_module

        with patch.object(brief_module.st, "session_state", {}), patch.object(
            brief_module,
            "run_query",
            side_effect=RuntimeError("table missing"),
        ):
            brief = brief_module.autoload_section_command_brief("Security Monitoring", "ALFA", "PROD", 30)

        self.assertEqual(brief.state, "Summary unavailable")
        self.assertIn("Mart summary unavailable", brief.fallback_reason)
        self.assertGreaterEqual(len(brief.metrics), 4)
        self.assertEqual(brief.detail_cta, "Refresh Security Summary")

    def test_renderer_idle_actions_do_not_load_or_query(self):
        from sections.section_command_brief import SectionCommandAction, SectionCommandBrief, SectionCommandMetric, SectionCommandSignal
        from sections import section_command_rendering

        brief = SectionCommandBrief(
            section="Alert Center",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="Summary loaded",
            headline="Alerts need review.",
            summary="Critical family is highest.",
            source="MART_SECTION_COMMAND_BRIEF",
            freshness_label="Loaded 2 minutes ago",
            loaded_at="2026-06-25T10:00:00",
            metrics=(SectionCommandMetric("Active alerts", "5"),),
            top_signal=SectionCommandSignal("High", "Critical alerts", "Alert Center", "Review active alerts."),
            next_actions=(SectionCommandAction("Open Active Alerts", "Route only", "Alert Center", "Active Alerts"),),
            detail_cta="Load Active Alerts",
            detail_available=True,
        )

        with patch.object(section_command_rendering.st, "html") as html, patch.object(
            section_command_rendering.st,
            "columns",
            return_value=[contextlib.nullcontext()],
        ), patch.object(section_command_rendering.st, "button", return_value=False) as button, patch.object(
            section_command_rendering.st,
            "rerun",
            side_effect=AssertionError("idle command brief must not rerun"),
        ):
            section_command_rendering.render_section_command_brief(brief, key_prefix="test_alert_brief")

        markup = "\n".join(call.args[0] for call in html.call_args_list)
        self.assertIn("ow-command-brief", markup)
        self.assertIn("Load Active Alerts", markup)
        button.assert_called_once()

    def test_primary_sections_import_command_brief_path(self):
        required = {
            "executive_landing_shell.py": "Executive Landing",
            "dba_control_room/render.py": "DBA Control Room",
            "alert_center.py": "Alert Center",
            "cost_contract.py": "Cost & Contract",
            "workload_operations.py": "Workload Operations",
            "security_posture.py": "Security Monitoring",
        }
        for rel_path, section in required.items():
            with self.subTest(section=section):
                source = (APP_ROOT / "sections" / rel_path).read_text(encoding="utf-8")
                self.assertIn("autoload_section_command_brief", source)
                self.assertIn("render_section_command_brief", source)
                self.assertIn(section, source)

    def test_snowflake_setup_declares_command_brief_marts(self):
        setup = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8")
        validation = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(encoding="utf-8")
        for name in (
            "MART_SECTION_COMMAND_BRIEF",
            "MART_SECTION_COMMAND_METRIC",
            "MART_SECTION_COMMAND_EXCEPTION",
            "MART_SECTION_COMMAND_ACTION",
        ):
            self.assertIn(name, setup)
            self.assertIn(name, validation)


if __name__ == "__main__":
    unittest.main()
