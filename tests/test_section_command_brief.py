from pathlib import Path
import contextlib
import os
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
        generated = (APP_ROOT / "sections" / "section_command_contracts_generated.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", source)
        self.assertNotIn("import streamlit", generated)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", source)
        self.assertNotRegex(source, r"\brun_query(?:_or_raise)?\s*\(")
        for section, contract in SECTION_COMMAND_CONTRACTS.items():
            with self.subTest(section=section):
                self.assertEqual(contract.section, section)
                self.assertGreaterEqual(len(contract.metric_labels), 4)
                self.assertTrue(contract.detail_cta)
                self.assertTrue(contract.source_table)
                self.assertTrue(contract.next_actions)

    def test_decision_brief_generated_contract_artifacts_are_current(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_decision_brief_contracts.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_loader_uses_mart_rows_and_does_not_require_detail_load(self):
        from sections import section_command_brief as brief_module

        packet_rows = pd.DataFrame([{
            "BRIEF_ID": "brief-1",
            "SECTION_NAME": "Cost & Contract",
            "COMPANY": "ALFA",
            "ENVIRONMENT": "ALL",
            "WINDOW_DAYS": 7,
            "RESOLVED_COMPANY": "ALFA",
            "RESOLVED_ENVIRONMENT": "ALL",
            "RESOLVED_WINDOW_DAYS": 7,
            "STATE": "Summary loaded",
            "HEADLINE": "Cost movement needs review.",
            "SUMMARY": "Cortex cost is the top movement.",
            "TOP_SIGNAL": "Cortex AI spend",
            "TOP_ENTITY": "Cortex",
            "TOP_ACTION": "Review Cortex AI Costs",
            "SOURCE_STATUS": "Summary loaded from mart",
            "SOURCE_FRESHNESS": "5 minutes ago",
            "SOURCE_OBJECTS": "FACT_COST_DAILY; FACT_CORTEX_DAILY",
            "FRESHNESS_MINUTES": 5,
            "TARGET_FRESHNESS_MINUTES": 60,
            "IS_STALE": False,
            "CONFIDENCE": "allocated",
            "REQUIRED_SOURCE_COUNT": 2,
            "AVAILABLE_SOURCE_COUNT": 2,
            "MISSING_SOURCE_COUNT": 0,
            "SOURCE_COVERAGE_PCT": 100,
            "DATA_AVAILABILITY_STATE": "Scheduled mart",
            "STALE_SOURCE_COUNT": 0,
            "SOURCE_GAP_DETAIL": "",
            "PACKET_BYTES": 4096,
            "SNAPSHOT_TS": "2026-06-25 10:00:00",
            "LOAD_TS": "2026-06-25 10:05:00",
            "METRICS": [
                {
                    "METRIC_KEY": "total_spend",
                    "METRIC_LABEL": "Total spend",
                    "METRIC_NUMERIC_VALUE": 120,
                    "METRIC_FORMAT": "currency",
                    "METRIC_DETAIL": "7d",
                    "IS_AVAILABLE": True,
                    "AVAILABILITY_STATE": "Available",
                    "SOURCE_KEY": "cost_daily",
                    "CONFIDENCE": "allocated",
                    "TREND_POINTS": [
                        {"ts": "2026-06-18", "value": 101},
                        {"ts": "2026-06-25", "value": 120},
                    ],
                    "DELTA_PERCENT": 18.8,
                    "SORT_ORDER": 10,
                },
                {
                    "METRIC_KEY": "cortex_spend",
                    "METRIC_LABEL": "Cortex AI spend",
                    "METRIC_NUMERIC_VALUE": 42,
                    "METRIC_FORMAT": "currency",
                    "METRIC_DETAIL": "35%",
                    "METRIC_TONE": "cortex",
                    "IS_AVAILABLE": True,
                    "AVAILABILITY_STATE": "Available",
                    "SOURCE_KEY": "cortex_daily",
                    "CONFIDENCE": "estimated",
                    "SORT_ORDER": 20,
                },
                {
                    "METRIC_KEY": "forecast_run_rate",
                    "METRIC_LABEL": "Forecast / Run-rate",
                    "METRIC_VALUE": "Unavailable",
                    "METRIC_FORMAT": "currency",
                    "METRIC_DETAIL": "Forecast mart has no current row",
                    "IS_AVAILABLE": False,
                    "AVAILABILITY_STATE": "Unavailable",
                    "UNAVAILABLE_REASON": "Forecast mart has no current row",
                    "SOURCE_KEY": "forecast",
                    "SORT_ORDER": 30,
                },
            ],
            "EXCEPTIONS": [{
                "SEVERITY": "High",
                "SIGNAL": "Cortex AI spend",
                "ENTITY_NAME": "Cortex",
                "DETAIL": "Spend accelerated.",
                "ROUTE_SECTION": "Cost & Contract",
                "ROUTE_WORKFLOW": "Cortex AI",
                "PRIORITY_SCORE": 95,
                "IMPACT_VALUE": 42,
                "IMPACT_UNIT": "USD",
                "OWNER_ROUTE": "DBA / AI cost route",
                "OWNER_GAP": False,
                "SORT_ORDER": 1,
            }],
            "ACTIONS": [{
                "ACTION_KEY": "review_cortex_costs",
                "ROUTE_KEY": "cost_contract_cortex_ai",
                "ACTION_LABEL": "Review Cortex AI Costs",
                "ACTION_DETAIL": "Open the Cortex lane.",
                "CTA_LABEL": "Review Cortex",
                "TARGET_SECTION": "Cost & Contract",
                "TARGET_WORKFLOW": "Cortex AI",
                "SORT_ORDER": 1,
            }],
            "SOURCES": [{
                "SOURCE_KEY": "cost_daily",
                "SOURCE_OBJECT": "FACT_COST_DAILY",
                "REQUIRED": True,
                "AVAILABLE": True,
                "SOURCE_SNAPSHOT_TS": "2026-06-25 10:00:00",
                "AGE_MINUTES": 5,
                "TARGET_FRESHNESS_MINUTES": 60,
                "IS_STALE": False,
                "CONFIDENCE": "allocated",
                "GAP_REASON": "",
            }, {
                "SOURCE_KEY": "cortex_daily",
                "SOURCE_OBJECT": "FACT_CORTEX_DAILY",
                "REQUIRED": True,
                "AVAILABLE": True,
                "SOURCE_SNAPSHOT_TS": "2026-06-25 10:00:00",
                "AGE_MINUTES": 5,
                "TARGET_FRESHNESS_MINUTES": 60,
                "IS_STALE": False,
                "CONFIDENCE": "estimated",
                "GAP_REASON": "",
            }],
        }])

        with patch.object(brief_module.st, "session_state", {}), patch.object(
            brief_module,
            "run_query",
            return_value=packet_rows,
        ) as run_query:
            brief = brief_module.autoload_section_command_brief("Cost & Contract", "ALFA", "ALL", 7)

        self.assertEqual(brief.state, "Summary loaded")
        self.assertEqual(brief.headline, "Cost movement needs review.")
        self.assertEqual(brief.metrics[0].label, "Total spend")
        self.assertEqual(brief.metrics[0].numeric_value, 120)
        self.assertTrue(brief.metrics[0].available)
        self.assertEqual(brief.metrics[0].source_key, "cost_daily")
        self.assertEqual(
            brief.metrics[0].trend_points,
            ({"ts": "2026-06-18", "value": 101.0}, {"ts": "2026-06-25", "value": 120.0}),
        )
        metrics_by_key = {metric.key: metric for metric in brief.metrics}
        self.assertEqual(metrics_by_key["cortex_spend"].tone, "cortex")
        self.assertFalse(metrics_by_key["forecast_run_rate"].available)
        self.assertEqual(metrics_by_key["forecast_run_rate"].unavailable_reason, "Forecast mart has no current row")
        self.assertEqual(brief.top_signal.signal, "Cortex AI spend")
        self.assertEqual(brief.top_signal.priority_score, 95)
        self.assertEqual(brief.top_signal.owner_route, "DBA / AI cost route")
        self.assertEqual(brief.next_actions[0].target_workflow, "Cortex AI")
        self.assertEqual(brief.resolved_company, "ALFA")
        self.assertEqual(brief.source, "MART_SECTION_DECISION_CURRENT")
        self.assertEqual(brief.source_objects, "FACT_COST_DAILY; FACT_CORTEX_DAILY")
        self.assertEqual(brief.source_coverage_pct, 100)
        self.assertEqual(brief.command_brief_packet_result_bytes, 4096)
        self.assertEqual(len(brief.sources), 2)
        self.assertEqual(brief.sources[0].source_key, "cost_daily")
        self.assertEqual(brief.sources[1].confidence, "estimated")
        self.assertEqual(brief.data_availability_state, "Scheduled mart")
        self.assertEqual(brief.command_brief_query_count, 1)
        self.assertEqual(run_query.call_count, 1)

    def test_trust_reconciliation_fails_closed_when_parent_disagrees(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandSourceState, reconcile_decision_brief_trust

        brief = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="PROD",
            window_label="7 days",
            state="Healthy",
            headline="Cost posture is clear.",
            summary="Parent row incorrectly claimed all sources were fresh.",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Summary loaded",
            loaded_at="2026-06-25T10:00:00",
            required_source_count=2,
            available_source_count=2,
            missing_source_count=0,
            source_coverage_pct=100,
            data_availability_state="Scheduled mart",
            sources=(
                SectionCommandSourceState("cost_daily", "FACT_COST_DAILY", True, True, age_minutes=8, target_freshness_minutes=60),
                SectionCommandSourceState("cortex_daily", "FACT_CORTEX_DAILY", True, False, target_freshness_minutes=60),
            ),
        )

        reconciled = reconcile_decision_brief_trust(brief)

        self.assertEqual(reconciled.state, "Data Gap")
        self.assertEqual(reconciled.missing_source_count, 1)
        self.assertEqual(reconciled.source_coverage_pct, 50.0)
        self.assertIn("FACT_CORTEX_DAILY", reconciled.source_gap_detail)
        self.assertEqual(reconciled.raw_payload["trust_reconciliation"], "parent_packet_disagreed_with_sources")

    def test_loader_session_cache_hit_uses_zero_queries(self):
        from sections import section_command_brief as brief_module

        packet_rows = pd.DataFrame([{
            "BRIEF_ID": "brief-cache",
            "SECTION_NAME": "Alert Center",
            "COMPANY": "ALFA",
            "ENVIRONMENT": "ALL",
            "WINDOW_DAYS": 7,
            "RESOLVED_COMPANY": "ALFA",
            "RESOLVED_ENVIRONMENT": "ALL",
            "RESOLVED_WINDOW_DAYS": 7,
            "STATE": "Summary loaded",
            "HEADLINE": "Alerts are current.",
            "SUMMARY": "Critical alerts are summarized from the mart.",
            "TOP_SIGNAL": "Critical / high alerts",
            "TOP_ENTITY": "Alert Center",
            "TOP_ACTION": "Load Active Alerts",
            "SOURCE_STATUS": "Summary loaded from mart",
            "SOURCE_FRESHNESS": "2 minutes ago",
            "SOURCE_OBJECTS": "ALERT_EVENTS",
            "FRESHNESS_MINUTES": 2,
            "TARGET_FRESHNESS_MINUTES": 15,
            "IS_STALE": False,
            "CONFIDENCE": "exact",
            "REQUIRED_SOURCE_COUNT": 1,
            "AVAILABLE_SOURCE_COUNT": 1,
            "MISSING_SOURCE_COUNT": 0,
            "SOURCE_COVERAGE_PCT": 100,
            "DATA_AVAILABILITY_STATE": "Scheduled mart",
            "SNAPSHOT_TS": "2026-06-25 10:00:00",
            "LOAD_TS": "2026-06-25 10:02:00",
            "METRICS": [{"METRIC_LABEL": "Active alerts", "METRIC_VALUE": "4", "SORT_ORDER": 10}],
            "EXCEPTIONS": [],
            "ACTIONS": [],
        }])

        session_state = {}
        with patch.object(brief_module.st, "session_state", session_state), patch.object(
            brief_module,
            "run_query",
            return_value=packet_rows,
        ) as run_query:
            first = brief_module.autoload_section_command_brief("Alert Center", "ALFA", "ALL", 7)
            second = brief_module.autoload_section_command_brief("Alert Center", "ALFA", "ALL", 7)

        self.assertEqual(first.command_brief_query_count, 1)
        self.assertFalse(first.command_brief_cache_hit)
        self.assertEqual(second.command_brief_query_count, 0)
        self.assertTrue(second.command_brief_cache_hit)
        self.assertEqual(run_query.call_count, 1)

    def test_loader_fallback_is_non_crashing_when_mart_unavailable(self):
        from sections import section_command_brief as brief_module

        with patch.object(brief_module.st, "session_state", {}), patch.object(
            brief_module,
            "run_query",
            side_effect=RuntimeError("table missing"),
        ):
            brief = brief_module.autoload_section_command_brief("Security Monitoring", "ALFA", "PROD", 30)

        self.assertEqual(brief.state, "Summary not initialized")
        self.assertIn("Mart summary unavailable", brief.fallback_reason)
        self.assertEqual(len(brief.metrics), 0)
        self.assertEqual(brief.detail_cta, "Load Security Evidence")
        self.assertEqual(brief.raw_payload.get("workspace_mode"), "UNINITIALIZED")

    def test_loader_skips_query_when_snowflake_entry_is_unavailable(self):
        from sections import section_command_brief as brief_module

        with patch.object(brief_module.st, "session_state", {}), patch.object(
            brief_module,
            "snowflake_entry_available",
            return_value=False,
        ), patch.object(
            brief_module,
            "run_query",
            side_effect=AssertionError("offline entry must not call the stopping query path"),
        ):
            brief = brief_module.autoload_section_command_brief("Cost & Contract", "ALFA", "ALL", 7)

        self.assertEqual(brief.raw_payload.get("workspace_mode"), "OFFLINE")
        self.assertEqual(brief.command_brief_query_count, 0)
        self.assertIn("Snowflake session is unavailable", brief.fallback_reason)

    def test_snowflake_entry_preflight_ignores_configured_secrets_without_active_session(self):
        import builtins
        from sections import decision_workspace_state as state_module

        real_import = builtins.__import__

        def _no_snowflake_context_import(name, *args, **kwargs):
            if name == "snowflake.snowpark.context":
                raise ImportError("no active Snowflake context")
            return real_import(name, *args, **kwargs)

        with patch.object(state_module.st, "session_state", {}), patch.object(
            state_module.st,
            "secrets",
            {"connections": {"snowflake": {"account": "example"}}},
        ), patch("builtins.__import__", side_effect=_no_snowflake_context_import):
            self.assertFalse(state_module.snowflake_entry_available())

    def test_fixture_mode_is_restricted_to_explicit_env_gate(self):
        from sections import decision_workspace_state as state_module

        with patch.dict(os.environ, {}, clear=True), patch.object(
            state_module.st,
            "session_state",
            {"OVERWATCH_UI_FIXTURE_MODE": True},
        ):
            self.assertFalse(state_module.decision_fixture_enabled())

        with patch.dict(os.environ, {"OVERWATCH_UI_FIXTURE_MODE": "1"}, clear=True), patch.object(
            state_module.st,
            "session_state",
            {},
        ):
            self.assertTrue(state_module.decision_fixture_enabled())

        with patch.dict(
            os.environ,
            {
                "OVERWATCH_UI_FIXTURE_MODE": "1",
                "OVERWATCH_ALLOW_FIXTURE_MODE": "1",
                "SNOWFLAKE_NATIVE_APP": "1",
            },
            clear=True,
        ), patch.object(state_module.st, "session_state", {}):
            self.assertFalse(state_module.decision_fixture_enabled())

    def test_fixture_mode_returns_populated_demo_brief_without_query(self):
        from sections import section_command_brief as brief_module

        with patch.dict(os.environ, {"OVERWATCH_UI_FIXTURE_MODE": "1"}, clear=True), patch.object(
            brief_module.st,
            "session_state",
            {},
        ), patch.object(
            brief_module,
            "run_query",
            side_effect=AssertionError("fixture mode must not query Snowflake"),
        ):
            brief = brief_module.autoload_section_command_brief("Cost & Contract", "ALFA", "ALL", 7)

        self.assertEqual(brief.raw_payload.get("workspace_mode"), "READY")
        self.assertTrue(brief.raw_payload.get("fixture_mode"))
        self.assertGreaterEqual(len(brief.metrics), 4)
        self.assertIn("Cortex AI", " ".join(metric.label for metric in brief.metrics))

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
            next_actions=(SectionCommandAction("Open Active Alerts", "Route only", "Alert Center", "Active Alerts", route_key="alert_center_active", cta="Open Active Alerts"),),
            detail_cta="Load Active Alerts",
            detail_available=True,
        )

        with patch.object(section_command_rendering.st, "html") as html, patch.object(
            section_command_rendering.st,
            "markdown",
        ) as markdown, patch.object(
            section_command_rendering.st,
            "columns",
            return_value=[contextlib.nullcontext(), contextlib.nullcontext()],
        ), patch.object(section_command_rendering.st, "button", return_value=False) as button, patch.object(
            section_command_rendering.st,
            "rerun",
            side_effect=AssertionError("idle command brief must not rerun"),
        ):
            section_command_rendering.render_section_command_brief(brief, key_prefix="test_alert_brief")
            section_command_rendering.render_section_command_brief(
                brief,
                key_prefix="test_alert_brief",
                detail_action=section_command_rendering.CommandBriefDetailAction(
                    "Load Active Alerts",
                    "Load rows.",
                    lambda: None,
                ),
            )

        markup = "\n".join(
            [call.args[0] for call in markdown.call_args_list]
            + [call.args[0] for call in html.call_args_list]
        )
        self.assertIn("ow-decision-workspace", markup)
        self.assertIn("ow-decision-hero", markup)
        self.assertIn("WHAT NEEDS ATTENTION".lower(), markup.lower())
        self.assertIn("ow-decision-metric-ribbon", markup)
        labels = [call.args[0] for call in button.call_args_list]
        self.assertTrue(any(str(label).startswith("Open Active Alerts") for label in labels))
        self.assertIn("Load Active Alerts", labels)

    def test_renderer_fallback_is_compact_and_hides_raw_objects(self):
        from sections.section_command_brief import SectionCommandBrief
        from sections import section_command_rendering

        brief = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="PROD",
            window_label="7 days",
            state="Summary not initialized",
            headline="Summary not initialized",
            summary="No current Decision packet exists.",
            source="Decision packet",
            freshness_label="Setup required",
            loaded_at="2026-06-25T10:00:00",
            fallback_reason="MART_SECTION_DECISION_CURRENT has no row for FACT_COST_DAILY.",
            source_gap_detail="FACT_COST_DAILY; FACT_CORTEX_DAILY",
            raw_payload={"workspace_mode": "UNINITIALIZED"},
        )

        with patch.object(section_command_rendering.st, "html") as html, patch.object(
            section_command_rendering.st,
            "columns",
            return_value=[contextlib.nullcontext(), contextlib.nullcontext()],
        ), patch.object(section_command_rendering.st, "button", return_value=False), patch.object(
            section_command_rendering.st,
            "expander",
            return_value=contextlib.nullcontext(),
        ):
            section_command_rendering.render_section_command_brief(brief, key_prefix="fallback")

        first_markup = html.call_args_list[0].args[0]
        self.assertNotIn("SUMMARY UNAVAILABLE", first_markup)
        self.assertIn("Summary not initialized", first_markup)
        self.assertNotIn("MART_SECTION_DECISION_CURRENT", first_markup)
        self.assertNotIn("FACT_COST_DAILY", first_markup)
        renderer_source = (APP_ROOT / "sections" / "section_command_rendering.py").read_text(encoding="utf-8")
        self.assertNotIn('"Technical details"', renderer_source)
        self.assertIn("ow-decision-trust-footer", renderer_source)

    def test_command_actions_are_deduped_and_unknown_routes_removed(self):
        from sections.section_command_brief import SectionCommandAction
        from sections.section_command_rendering import dedupe_command_actions

        actions = (
            SectionCommandAction("Review Cortex", "Dynamic top action", route_key="cost_contract_cortex_ai", cta="Review Cortex"),
            SectionCommandAction("Review Cortex Duplicate", "Duplicate", route_key="cost_contract_cortex_ai", cta="Review Cortex Again"),
            SectionCommandAction("Unknown", "Bad route", route_key="not_real", cta="Bad"),
            SectionCommandAction("Open Drivers", "Secondary", route_key="cost_contract_explorer_warehouse", cta="Open Drivers"),
            SectionCommandAction("Check Budget", "Secondary", route_key="cost_contract_budget", cta="Check Budget"),
            SectionCommandAction("Extra", "Too many", route_key="alert_center_active", cta="Extra"),
        )

        selected = dedupe_command_actions(actions, "Cost & Contract", "Overview")

        self.assertEqual([action.route_key for action in selected], [
            "cost_contract_cortex_ai",
            "cost_contract_explorer_warehouse",
            "cost_contract_budget",
        ])

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
        combined_setup = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
        modular_validation = (ROOT / "snowflake" / "mart_setup" / "08_validation.sql").read_text(encoding="utf-8")
        validation = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(encoding="utf-8")
        drop = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8")
        for name in (
            "MART_SECTION_COMMAND_BRIEF",
            "MART_SECTION_COMMAND_METRIC",
            "MART_SECTION_COMMAND_EXCEPTION",
            "MART_SECTION_COMMAND_ACTION",
            "MART_SECTION_COMMAND_SOURCE",
            "MART_SECTION_DECISION_CURRENT",
            "MART_SECTION_DECISION_LAST_GOOD",
            "OVERWATCH_DECISION_SETUP_HEALTH",
            "MART_EXECUTIVE_DECISION_INBOX",
        ):
            self.assertIn(name, setup)
            self.assertIn(name, combined_setup)
            self.assertIn(name, modular_validation)
            self.assertIn(name, validation)
        self.assertIn("DROP TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH", drop)

    def test_command_brief_sql_pipeline_is_wired(self):
        tables = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8").upper()
        procs = (ROOT / "snowflake" / "mart_setup" / "05_load_procedures.sql").read_text(encoding="utf-8").upper()
        tasks = (ROOT / "snowflake" / "mart_setup" / "07_tasks.sql").read_text(encoding="utf-8").upper()
        validation = (ROOT / "snowflake" / "mart_setup" / "08_validation.sql").read_text(encoding="utf-8").upper()
        drop = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8").upper()

        for token in (
            "BRIEF_ID",
            "SOURCE_OBJECTS",
            "SOURCE_SNAPSHOT_TS",
            "FRESHNESS_MINUTES",
            "METRIC_NUMERIC_VALUE",
            "IS_AVAILABLE",
            "AVAILABILITY_STATE",
            "UNAVAILABLE_REASON",
            "SOURCE_KEY",
            "TREND_POINTS",
            "PRIORITY_SCORE",
            "SOURCE_COVERAGE_PCT",
            "ACTION_KEY",
            "ROUTE_KEY",
            "CTA_LABEL",
            "OVERWATCH_DECISION_SETUP_HEALTH",
        ):
            self.assertIn(token, tables)
        setup_health_block = tables.split("CREATE TABLE IF NOT EXISTS OVERWATCH_DECISION_SETUP_HEALTH", 1)[1].split(");", 1)[0]
        for column in (
            "EVENT_ID",
            "EVENT_TS",
            "STATUS",
            "USER_MESSAGE",
            "GLOBAL_STATUS",
            "SELECTED_SCOPE_STATUS",
            "CURRENT_SECTION_STATUS",
            "SELECTED_PROCEDURE",
            "FALLBACK_USED",
            "CURRENT_PACKET_COUNT",
            "SECTIONS_PRESENT",
            "MISSING_SECTIONS",
            "DUPLICATE_CURRENT_KEYS",
            "STALE_SECTIONS",
            "DATA_GAP_SECTIONS",
            "MISSING_METRIC_SECTIONS",
            "DEGRADED_SECTIONS",
            "INVALID_SECTIONS",
            "WARNING_SECTIONS",
            "MAX_PACKET_BYTES",
            "REQUESTED_SCOPE",
            "RESOLVED_SCOPE",
            "ADMIN_DETAIL",
            "SUGGESTED_REMEDIATION",
            "ACTOR_ROLE",
            "APP_VERSION",
            "PERSISTENCE_STATUS",
            "LOAD_TS",
        ):
            self.assertIn(column, setup_health_block)
            self.assertIn(column, tables)
            self.assertIn(column, validation)
        for column in (
            "AVAILABLE_REQUIRED_SOURCE_COUNT",
            "REQUIRED_MISSING_SOURCE_COUNT",
            "REQUIRED_STALE_SOURCE_COUNT",
            "OPTIONAL_SOURCE_COUNT",
            "AVAILABLE_OPTIONAL_SOURCE_COUNT",
            "OPTIONAL_MISSING_SOURCE_COUNT",
            "OPTIONAL_STALE_SOURCE_COUNT",
        ):
            self.assertIn(column, tables)
            self.assertIn(column, procs)
            self.assertIn(column, validation)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS()", procs)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST()", procs)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL()", procs)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS()", procs)
        self.assertIn("TMP_DECISION_SOURCE_WATERMARK", procs)
        self.assertIn("MART_SECTION_COMMAND_BRIEF", procs)
        self.assertIn("MART_SECTION_COMMAND_METRIC", procs)
        self.assertIn("MART_SECTION_COMMAND_EXCEPTION", procs)
        self.assertIn("MART_SECTION_COMMAND_ACTION", procs)
        self.assertIn("MART_SECTION_COMMAND_SOURCE", procs)
        self.assertIn("MART_SECTION_DECISION_CURRENT", procs)
        self.assertIn("MART_SECTION_DECISION_LAST_GOOD", procs)
        self.assertIn("SOURCES", procs)
        self.assertIn("PACKET_BYTES", procs)
        self.assertIn("COUNT_IF(REQUIRED AND SOURCE_SNAPSHOT_TS IS NULL) AS REQUIRED_MISSING_SOURCE_COUNT", procs)
        self.assertIn("COUNT_IF(NOT REQUIRED AND SOURCE_SNAPSHOT_TS IS NULL) AS OPTIONAL_MISSING_SOURCE_COUNT", procs)
        self.assertIn("DECISION_PACKET:\"REQUIRED_MISSING_SOURCE_COUNT\"::NUMBER", procs)
        self.assertNotIn('WHERE COALESCE(DECISION_PACKET:"MISSING_SOURCE_COUNT"::NUMBER, 0) = 0', procs)
        config_tables = (ROOT / "snowflake" / "mart_setup" / "03_config_and_audit_tables.sql").read_text(encoding="utf-8").upper()
        self.assertIn("AUTO_BOOTSTRAP_DECISION_BRIEFS", config_tables)
        self.assertIn("DECISION_BRIEF_BOOTSTRAP_PROCEDURE", config_tables)
        self.assertIn("DECISION_BRIEF_WAREHOUSE", config_tables)
        self.assertIn("ARRAY_SIZE(COALESCE(DECISION_PACKET:\"METRICS\", ARRAY_CONSTRUCT())) > 0", procs)
        self.assertNotIn("DELETE FROM OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG", procs)
        self.assertNotIn("DELETE FROM MART_SECTION_DECISION_CURRENT;", procs)
        self.assertNotIn("'TOP_DRIVER'", procs)
        for builder in (
            "EXECUTIVE_DECISION",
            "DBA_DECISION",
            "ALERT_DECISION",
            "COST_DECISION",
            "WORKLOAD_DECISION",
            "SECURITY_DECISION",
        ):
            self.assertIn(builder, procs)
        self.assertIn("DECISION_STATE AS STATE", procs)
        self.assertIn("FROM TMP_SECTION_DECISION_LOGIC", procs)
        self.assertIn("WHERE DECISION_SEVERITY <> 'CLEAR'", procs)
        self.assertIn("OBJECT_CONSTRUCT_KEEP_NULL", procs)
        self.assertIn("'TS'", procs)
        self.assertIn("SETTING_NAME) = 'CREDIT_PRICE_USD'", procs)
        self.assertNotIn("SETTING_KEY) = 'CREDIT_PRICE_USD'", procs)
        self.assertIn("CREATE OR REPLACE TASK OVERWATCH_SECTION_COMMAND_BRIEF_REFRESH", tasks)
        self.assertIn("SCHEDULE = '15 MINUTE'", tasks)
        self.assertIn("ALLOW_OVERLAPPING_EXECUTION = FALSE", tasks)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS()", validation)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST()", validation)
        self.assertIn("CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS()", validation)
        self.assertIn("SECTION_DECISION_LAST_GOOD_PACKET_COVERAGE", validation)
        self.assertIn("SECTION_COMMAND_BRIEF_METRIC_AVAILABILITY", validation)
        self.assertIn("SECTION_DECISION_CURRENT_PACKET_COVERAGE", validation)
        self.assertIn("SECTION_COMMAND_SOURCE_ROWS", validation)
        self.assertIn("SECTION_COMMAND_BRIEF_ORPHAN_CHILD_ROWS", validation)
        self.assertIn("SECTION_COMMAND_BRIEF_CANONICAL_WINDOWS", validation)
        self.assertIn("DROP TASK IF EXISTS OVERWATCH_SECTION_COMMAND_BRIEF_REFRESH", drop)
        self.assertIn("DROP TASK IF EXISTS OVERWATCH_DECISION_BRIEF_FULL_REFRESH", drop)
        self.assertIn("DROP PROCEDURE IF EXISTS SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS()", drop)
        self.assertIn("DROP PROCEDURE IF EXISTS SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST()", drop)
        self.assertIn("DROP TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH", drop)
        self.assertIn("DROP TABLE IF EXISTS MART_SECTION_DECISION_LAST_GOOD", drop)

        fast_block = procs.split("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST()", 1)[1].split("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL()", 1)[0]
        full_block = procs.split("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL()", 1)[1].split("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS()", 1)[0]
        self.assertIn("WINDOW_DAYS NOT IN (1, 7)", fast_block)
        self.assertNotIn("WINDOW_DAYS NOT IN (1, 7)", full_block)
        self.assertIn("SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST", fast_block)
        self.assertIn("SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL", full_block)

    def test_loader_builds_single_packet_query(self):
        from sections import section_command_brief as brief_module

        sql = brief_module._packet_sql("Cost & Contract", "ALFA", "ALL", 7).upper()
        self.assertIn("MART_SECTION_DECISION_CURRENT", sql)
        self.assertIn("DECISION_PACKET", sql)
        self.assertIn("BRIEF_ID", sql)
        self.assertIn("METRICS", sql)
        self.assertIn("EXCEPTIONS", sql)
        self.assertIn("ACTIONS", sql)
        self.assertIn("SOURCES", sql)
        self.assertIn("PACKET_BYTES", sql)
        self.assertIn("AVAILABLE_REQUIRED_SOURCE_COUNT", sql)
        self.assertIn("REQUIRED_MISSING_SOURCE_COUNT", sql)
        self.assertIn("REQUIRED_STALE_SOURCE_COUNT", sql)
        self.assertIn("OPTIONAL_SOURCE_COUNT", sql)
        self.assertIn("OPTIONAL_MISSING_SOURCE_COUNT", sql)
        self.assertNotIn("ARRAY_AGG", sql)

    def test_sql_emits_every_contract_metric_key(self):
        from sections.section_command_contracts import SECTION_COMMAND_CONTRACTS

        procs = (ROOT / "snowflake" / "mart_setup" / "05_load_procedures.sql").read_text(encoding="utf-8")
        upper = procs.upper()
        for section, contract in SECTION_COMMAND_CONTRACTS.items():
            for metric_key in contract.metric_keys:
                with self.subTest(section=section, metric_key=metric_key):
                    self.assertIn(f"'{metric_key.upper()}'", upper)

    def test_contract_metric_keys_are_explicit_and_primary(self):
        from sections.section_command_contracts import SECTION_COMMAND_CONTRACTS

        required = {
            "Executive Landing": ("platform_health", "spend_movement_pct", "critical_high_issues", "open_actions"),
            "DBA Control Room": ("failed_queries", "pipeline_failures", "queue_pressure", "cost_24h"),
            "Alert Center": ("active_alerts", "critical_high", "overdue_alerts", "cortex_predictive"),
            "Cost & Contract": ("total_spend", "spend_movement_pct", "forecast_run_rate", "cortex_spend_share"),
            "Workload Operations": ("failed_queries", "pipeline_failures", "queue_blocked_pressure", "sla_risk"),
            "Security Monitoring": ("failed_logins", "mfa_gaps", "risky_grants", "sharing_exposure"),
        }
        for section, keys in required.items():
            with self.subTest(section=section):
                contract = SECTION_COMMAND_CONTRACTS[section]
                self.assertEqual(contract.primary_metric_keys, keys)
                self.assertTrue(set(keys).issubset(set(contract.metric_keys)))
                self.assertTrue(contract.source_configs)
                self.assertTrue(contract.fallback_route_keys)

    def test_command_brief_routes_are_allowlisted_and_apply_after_defaults(self):
        from sections import command_brief_routes

        emitted_route_keys = (
            "executive_overview",
            "dba_overview",
            "dba_failures",
            "dba_performance",
            "alert_center_active",
            "alert_center_critical_high",
            "alert_cortex_predictive",
            "alert_center_cost",
            "alert_center_security",
            "cost_contract_overview",
            "cost_contract_cortex_ai",
            "cost_contract_explorer_warehouse",
            "cost_contract_budget",
            "workload_query_investigation",
            "workload_pipeline_tasks",
            "workload_performance",
            "security_overview",
            "security_risky_grants",
            "security_access_changes",
            "security_alerts",
            "security_failed_logins",
        )
        for route_key in emitted_route_keys:
            with self.subTest(route_key=route_key):
                self.assertIn(route_key, command_brief_routes.COMMAND_BRIEF_ROUTES)

        state = {}
        with patch.object(command_brief_routes.st, "session_state", state), patch.object(
            command_brief_routes,
            "queue_section_navigation",
        ) as queue:
            self.assertTrue(command_brief_routes.apply_command_brief_route("cost_contract_explorer_user_role"))

        queue.assert_called_once_with("Cost & Contract")
        self.assertEqual(state["cost_contract_workflow"], "Cost Explorer")
        self.assertEqual(state["cc_explorer_lens"], "User / Role")

        with patch.object(command_brief_routes.st, "session_state", {}), patch.object(
            command_brief_routes,
            "queue_section_navigation",
        ) as queue:
            self.assertFalse(command_brief_routes.apply_command_brief_route("not_real"))
        queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
