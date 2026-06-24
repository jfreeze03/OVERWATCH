from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import executive_landing  # noqa: E402
from sections import executive_landing_actions_view as actions_view  # noqa: E402
from sections import executive_landing_admin_view as admin_view  # noqa: E402
from sections import executive_landing_change_view as change_view  # noqa: E402
from sections import executive_landing_common as common  # noqa: E402
from sections import executive_landing_contracts as contracts  # noqa: E402
from sections import executive_landing_cost_view as cost_view  # noqa: E402
from sections import executive_landing_data as data  # noqa: E402
from sections import executive_landing_data_health_view as data_health_view  # noqa: E402
from sections import executive_landing_models as models  # noqa: E402
from sections import executive_landing_operational_view as operational_view  # noqa: E402
from sections import executive_landing_overview_view as overview_view  # noqa: E402
from sections import executive_landing_security_view as security_view  # noqa: E402


class ExecutiveLandingSplitTests(unittest.TestCase):
    def setUp(self):
        self._previous_state = dict(st.session_state)
        st.session_state.clear()

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self._previous_state)

    def test_executive_landing_contracts_stay_stable(self):
        self.assertEqual(contracts.EXECUTIVE_OVERVIEW_WORKFLOW, "Executive Overview")
        self.assertEqual(contracts.EXECUTIVE_COST_MOVEMENT_WORKFLOW, "Cost Movement")
        self.assertEqual(contracts.EXECUTIVE_OPERATIONAL_RISK_WORKFLOW, "Operational Risk")
        self.assertEqual(contracts.EXECUTIVE_SECURITY_RISK_WORKFLOW, "Security Risk")
        self.assertEqual(contracts.EXECUTIVE_CHANGE_SUMMARY_WORKFLOW, "Change Summary")
        self.assertEqual(contracts.EXECUTIVE_ACTIONS_WORKFLOW, "Executive Actions")
        self.assertEqual(contracts.EXECUTIVE_ADMIN_WORKFLOW, "Executive Admin / Advanced")
        self.assertEqual(
            contracts.EXECUTIVE_LANDING_WORKFLOWS,
            (
                "Executive Overview",
                "Cost Movement",
                "Operational Risk",
                "Security Risk",
                "Change Summary",
                "Executive Actions",
                "Executive Admin / Advanced",
            ),
        )
        expected_aliases = {
            "Executive Briefing": "Executive Overview",
            "Executive Summary": "Executive Overview",
            "Adoption Analytics": "Executive Admin / Advanced",
            "Executive Scorecard": "Executive Admin / Advanced",
            "Scorecard Formulas": "Executive Admin / Advanced",
            "Value Ledger": "Executive Admin / Advanced",
            "Production Readiness": "Executive Admin / Advanced",
            "Data Trust": "Executive Admin / Advanced",
            "Command Center": "Executive Overview",
            "Forecasting": "Cost Movement",
        }
        self.assertEqual(contracts.EXECUTIVE_LANDING_LEGACY_WORKFLOW_ALIASES, expected_aliases)
        for alias, canonical in expected_aliases.items():
            self.assertEqual(common.normalize_executive_landing_workflow(alias), canonical)
        self.assertEqual(common.normalize_executive_landing_workflow("unknown"), "Executive Overview")

    def test_facade_reexports_focused_module_names(self):
        for module in (
            contracts,
            common,
            models,
            data,
            overview_view,
            cost_view,
            operational_view,
            security_view,
            change_view,
            actions_view,
            admin_view,
            data_health_view,
        ):
            for name in module.__all__:
                with self.subTest(module=module.__name__, name=name):
                    self.assertIs(getattr(executive_landing, name), getattr(module, name))
        for name in executive_landing.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(executive_landing, name))

    def test_pure_scoring_and_filter_helpers(self):
        self.assertEqual(models._platform_score_state(94), "Ready")
        self.assertEqual(models._platform_score_state(85), "Watch")
        self.assertEqual(models._platform_score_state(72), "Needs DBA Review")
        self.assertEqual(models._platform_score_state(20), "Executive Escalation")
        self.assertEqual(models._pressure_level(80), "Critical")
        self.assertEqual(models._pressure_level(45), "Review")
        self.assertEqual(models._pressure_level(5), "Watch")
        self.assertEqual(models._pressure_level(0), "Clear")
        driver = models._score_driver("Telemetry", penalty=4.4, evidence="one gap", next_action="load data", cap=82)
        self.assertEqual(driver["STATE"], "Review")
        self.assertEqual(driver["SCORE_IMPACT"], -4.4)
        self.assertEqual(driver["SCORE_CAP"], 82)

        queue = pd.DataFrame({"STATUS": ["New", "Fixed", "Ignored", "Closed", "In Progress"]})
        self.assertEqual(models._open_action_mask(queue).tolist(), [True, False, False, False, True])
        self.assertEqual(models._executive_snapshot_scope("ALFA", "PROD", 7), ("ALFA", "PROD", 7))

        frame = pd.DataFrame({"CATEGORY": ["Security"], "ALERT_TYPE": ["Login"], "ENTITY_NAME": ["USER_A"]})
        filtered = common._filter_frame_by_tokens(frame, ("LOGIN",), ("CATEGORY", "ALERT_TYPE", "ENTITY_NAME"))
        self.assertEqual(len(filtered), 1)

    def test_platform_operating_score_caps_and_drivers(self):
        source_health = pd.DataFrame([
            {"SOURCE": "Cost cockpit", "STATE": "Loaded"},
            {"SOURCE": "Alert evidence", "STATE": "Limited"},
        ])
        score = models._build_platform_operating_score(
            {
                "current_credits": 150.0,
                "prior_credits": 100.0,
                "cost_delta": 50.0,
                "critical_high_alerts": 2,
                "open_actions": 5,
                "high_actions": 2,
                "migration_blockers": 1,
                "advisor_findings": 4,
                "advisor_high_findings": 1,
                "advisor_value_at_risk_usd": 5000.0,
            },
            source_health,
        )
        self.assertLessEqual(score["score_cap"], 74)
        self.assertIn("platform_score_drivers", score)
        self.assertIn("Monitoring Coverage", set(score["platform_score_drivers"]["DRIVER"]))

    def test_data_loader_preserves_offline_shell_behavior(self):
        with patch("sections.executive_landing_data.get_session_for_action", return_value=None):
            self.assertFalse(data._load_executive_snapshot("ALFA", "PROD", 7))

    def test_scope_filter_sql_helpers_use_active_scope(self):
        st.session_state["active_company"] = "Trexis"
        st.session_state["global_environment"] = "prod"
        self.assertIn("x.COMPANY = 'Trexis'", data._company_filter_sql("x"))
        self.assertIn("UPPER(COALESCE(x.ENVIRONMENT, 'ALL')) = 'PROD'", data._environment_filter_sql("x"))
        st.session_state["active_company"] = "ALL"
        st.session_state["global_environment"] = "ALL"
        self.assertEqual(data._company_filter_sql("x"), "")
        self.assertEqual(data._environment_filter_sql("x"), "")

    def test_renderer_maps_cover_every_workflow(self):
        self.assertEqual(set(contracts.EXECUTIVE_LANDING_WORKFLOWS), set(executive_landing.EXECUTIVE_LANDING_RENDERERS))
        self.assertIs(executive_landing.EXECUTIVE_LANDING_RENDERERS["Executive Overview"], overview_view.render_executive_overview)
        self.assertIs(executive_landing.EXECUTIVE_LANDING_RENDERERS["Cost Movement"], cost_view.render_executive_cost_movement)
        self.assertIs(executive_landing.EXECUTIVE_LANDING_RENDERERS["Operational Risk"], operational_view.render_executive_operational_risk)
        self.assertIs(executive_landing.EXECUTIVE_LANDING_RENDERERS["Security Risk"], security_view.render_executive_security_risk)
        self.assertIs(executive_landing.EXECUTIVE_LANDING_RENDERERS["Change Summary"], change_view.render_executive_change_summary)
        self.assertIs(executive_landing.EXECUTIVE_LANDING_RENDERERS["Executive Actions"], actions_view.render_executive_actions)
        self.assertIs(executive_landing.EXECUTIVE_LANDING_RENDERERS["Executive Admin / Advanced"], admin_view.render_executive_admin_advanced)

    def test_dispatch_helper_calls_registered_renderer(self):
        calls = []

        def fake_renderer(**kwargs):
            calls.append(kwargs)
            return True

        original = executive_landing.EXECUTIVE_LANDING_RENDERERS.copy()
        try:
            executive_landing.EXECUTIVE_LANDING_RENDERERS["Executive Overview"] = fake_renderer
            result = executive_landing._render_loaded_executive_landing_workflow(
                "Executive Overview",
                summary={"state": "Ready"},
                company="ALFA",
                environment="PROD",
                days=7,
                credit_price=3.68,
                board=pd.DataFrame(),
                board_payload={},
                snapshot=None,
                source_health=None,
            )
        finally:
            executive_landing.EXECUTIVE_LANDING_RENDERERS.clear()
            executive_landing.EXECUTIVE_LANDING_RENDERERS.update(original)
        self.assertTrue(result)
        self.assertEqual(calls[0]["company"], "ALFA")
        self.assertEqual(calls[0]["days"], 7)

    def test_view_source_preserves_keys_and_navigation_targets(self):
        expected_tokens = {
            "executive_landing.py": [
                "executive_landing_observability_refresh",
                "_executive_landing_observability_autoload_scope",
                "executive_landing_snapshot",
            ],
            "executive_landing_data.py": [
                "_OBS_COLUMNS",
                "_obs_rows",
                "_normalise_observability_frame",
                "_observability_status_frame",
            ],
            "executive_landing_overview_view.py": [
                "executive_landing_load",
                "executive_landing_show_workflow_shortcuts",
                "Snowflake Observability Wall",
                "Executive decisions to make first",
            ],
            "executive_landing_common.py": ["executive_nav_"],
            "executive_landing_data_health_view.py": [
                "executive_alert_open_command",
                "executive_alert_open_impacted_section",
            ],
            "executive_landing_admin_view.py": [
                "Scorecard formulas",
                "value ledger",
                "Production Readiness",
                "telemetry trust detail",
                "Correlated Investigations",
            ],
        }
        for file_name, tokens in expected_tokens.items():
            source = (APP_ROOT / "sections" / file_name).read_text(encoding="utf-8")
            for token in tokens:
                with self.subTest(file=file_name, token=token):
                    self.assertIn(token, source)

    def test_executive_overview_detail_grid_is_explicit_after_first_paint(self):
        source = (APP_ROOT / "sections" / "executive_landing_overview_view.py").read_text(encoding="utf-8")

        detail_button_pos = source.index("executive_landing_show_summary_detail")
        detail_gate_pos = source.index("if detail_open or isinstance(snapshot, dict):")
        table_pos = source.index("render_priority_dataframe(", detail_gate_pos)
        loaded_alert_context_pos = source.index("_render_loaded_executive_alert_context()")
        snapshot_gate_pos = source.index("if isinstance(snapshot, dict):")

        self.assertLess(detail_button_pos, detail_gate_pos)
        self.assertLess(detail_gate_pos, table_pos)
        self.assertLess(snapshot_gate_pos, loaded_alert_context_pos)

    def test_executive_workflow_shortcuts_are_explicit_after_first_paint(self):
        source = (APP_ROOT / "sections" / "executive_landing_overview_view.py").read_text(encoding="utf-8")

        shortcut_button_pos = source.index("executive_landing_show_workflow_shortcuts")
        next_click_pos = source.index("        _render_executive_next_clicks()")
        snapshot_prompt_pos = source.index("_render_snapshot_prompt(EXECUTIVE_OVERVIEW_WORKFLOW")

        self.assertLess(shortcut_button_pos, next_click_pos)
        self.assertLess(next_click_pos, snapshot_prompt_pos)

    def test_executive_landing_facade_remains_thin(self):
        source = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 200)
        for fragment in [
            "def _build_platform_operating_score",
            "def _load_executive_snapshot",
            "def _render_executive_admin_advanced",
            "def _render_cost_movement",
            "def _render_operational_risk",
            "def _render_security_risk",
            "SNOWFLAKE.ACCOUNT_USAGE",
            "run_query(",
            "pd.DataFrame(",
            'elif active_workflow == "',
        ]:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
