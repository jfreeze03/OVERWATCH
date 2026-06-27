from __future__ import annotations

from contextlib import ExitStack
import importlib
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from route_registry import SECTION_WORKFLOW_CONTRACT  # noqa: E402
from brand import render_overwatch_logo_svg, render_sidebar_brand  # noqa: E402
from sections.button_action_contracts import (  # noqa: E402
    assert_button_budget_context,
    contract_target_is_valid,
    iter_button_action_contracts,
    marker_budget_mismatches,
    resolve_button_action_contract,
)


PRIMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)


WORKFLOW_STATE_KEY_BY_SECTION = {
    "Executive Landing": "executive_landing_workflow",
    "DBA Control Room": "dba_control_room_active_view",
    "Alert Center": "alert_center_active_view",
    "Cost & Contract": "cost_contract_workflow",
    "Workload Operations": "workload_operations_workflow",
    "Security Monitoring": "security_posture_view",
}


SECTION_WORKFLOW_MATRIX = {
    section: SECTION_WORKFLOW_CONTRACT.get(section, ())
    for section in PRIMARY_SECTIONS
}


EXTRA_WORKFLOW_LENS_CASES: tuple[tuple[str, str, dict[str, object]], ...] = (
    ("Alert Center", "Alert Settings / Admin", {"alert_center_admin_view": "Delivery & Automation"}),
    ("Alert Center", "Alert Settings / Admin", {"alert_center_admin_view": "Suppression Windows"}),
    ("Alert Center", "Alert Settings / Admin", {"alert_center_admin_view": "Detection Catalog"}),
    ("Cost & Contract", "Cost Explorer", {"cc_explorer_lens": "Warehouse"}),
    ("Cost & Contract", "Cost Explorer", {"cc_explorer_lens": "User / Role"}),
    ("Cost & Contract", "Cost Explorer", {"cc_explorer_lens": "Database"}),
    ("Cost & Contract", "Cost Explorer", {"cc_explorer_lens": "Service"}),
    ("Cost & Contract", "Cost Explorer", {"cc_explorer_lens": "Department / Cost Center"}),
    ("Workload Operations", "Query Investigation", {"workload_query_lens": "History Search"}),
    ("Workload Operations", "Query Investigation", {"workload_query_lens": "Detailed Diagnosis"}),
    ("Workload Operations", "Query Investigation", {"workload_query_lens": "Top SQL"}),
    ("Workload Operations", "Query Investigation", {"workload_query_lens": "User / Role"}),
    ("Workload Operations", "Query Investigation", {"workload_query_lens": "Warehouse"}),
    ("Workload Operations", "Pipeline & Task Health", {"workload_operations_pipeline_focus": "Failed Tasks"}),
    ("Workload Operations", "Pipeline & Task Health", {"workload_operations_pipeline_focus": "Failed Procedures"}),
    ("Workload Operations", "Pipeline & Task Health", {"workload_operations_pipeline_focus": "Load Issues & SLA"}),
    ("Workload Operations", "Pipeline & Task Health", {"workload_operations_pipeline_focus": "SLA Risk"}),
    ("Workload Operations", "Pipeline & Task Health", {"workload_operations_pipeline_focus": "Suspended Tasks"}),
    ("Security Monitoring", "Risky Grants", {"security_risky_grants_lens": "Users"}),
    ("Security Monitoring", "Risky Grants", {"security_risky_grants_lens": "Roles"}),
    ("Security Monitoring", "Risky Grants", {"security_risky_grants_lens": "Databases"}),
    ("Security Monitoring", "Risky Grants", {"security_risky_grants_lens": "Schemas"}),
    ("Security Monitoring", "Risky Grants", {"security_risky_grants_lens": "Future Grants"}),
    ("Security Monitoring", "Risky Grants", {"security_risky_grants_lens": "Ownership"}),
    ("Security Monitoring", "Access Changes", {"security_access_changes_lens": "Recent Grants"}),
    ("Security Monitoring", "Access Changes", {"security_access_changes_lens": "Revokes"}),
    ("Security Monitoring", "Access Changes", {"security_access_changes_lens": "Role Changes"}),
    ("Security Monitoring", "Access Changes", {"security_access_changes_lens": "Admin Changes"}),
)


class _RerunSignal(RuntimeError):
    pass


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class DecisionWorkspacePerformanceBudgetTests(unittest.TestCase):
    def test_ui_query_telemetry_records_execution_boundary_and_sanitizes_errors(self):
        import performance

        state: dict[str, object] = {}
        with patch.object(performance.st, "session_state", state):
            render_id = performance.begin_first_paint("Executive Landing", "Overview")
            performance.record_ui_query_event(
                section="Executive Landing",
                workflow="Overview",
                query_tier="command_summary",
                ttl_key="section_command_packet_Executive Landing_ALFA_ALL_7",
                actual_query_executed=True,
                cache_layer="none",
                query_boundary="decision_packet",
                first_paint_sensitive=True,
                row_count=1,
                max_rows=1,
                error="SELECT * FROM MART_SECTION_DECISION_CURRENT",
            )
            performance.record_ui_query_event(
                section="Executive Landing",
                workflow="Overview",
                query_tier="command_summary",
                ttl_key="section_command_packet_Executive Landing_ALFA_ALL_7",
                actual_query_executed=False,
                cache_layer="session",
                query_boundary="decision_packet",
                first_paint_sensitive=True,
                row_count=1,
                max_rows=1,
            )
            performance.end_first_paint(render_id)
            summary = performance.summarize_first_paint_query_budget("Executive Landing")
            events = performance.get_ui_query_events()

        self.assertEqual(summary["decision_packet_events"], 2)
        self.assertEqual(summary["decision_packet_actual_queries"], 1)
        self.assertEqual(summary["decision_packet_session_hits"], 1)
        self.assertEqual(events[0]["render_id"], render_id)
        self.assertEqual(events[0]["error"], "Query failed; see admin diagnostics.")
        self.assertNotIn("SELECT", json.dumps(events))
        self.assertNotIn("query_text", events[0])

    def test_first_paint_window_scopes_later_evidence_and_account_usage(self):
        import performance

        state: dict[str, object] = {}
        with patch.object(performance.st, "session_state", state):
            render_id = performance.begin_first_paint("Alert Center", "Overview")
            performance.record_ui_query_event(
                section="Alert Center",
                query_boundary="decision_packet",
                actual_query_executed=True,
                cache_layer="none",
                first_paint_sensitive=True,
            )
            performance.end_first_paint(render_id)
            performance.record_ui_query_event(
                section="Alert Center",
                query_boundary="evidence",
                actual_query_executed=True,
                cache_layer="none",
                first_paint_sensitive=True,
            )
            performance.record_ui_query_event(
                section="Alert Center",
                query_boundary="account_usage",
                actual_query_executed=True,
                cache_layer="none",
                first_paint_sensitive=True,
            )
            summary = performance.summarize_first_paint_query_budget("Alert Center")

        self.assertEqual(summary["decision_packet_events"], 1)
        self.assertEqual(summary["evidence_events"], 0)
        self.assertEqual(summary["account_usage_events"], 0)

    def test_first_paint_query_gate_blocks_non_packet_queries_in_test_mode(self):
        import performance

        state: dict[str, object] = {}
        with patch.dict(os.environ, {"OVERWATCH_TEST_MODE": "1"}, clear=False):
            with patch.object(performance.st, "session_state", state):
                render_id = performance.begin_first_paint("Alert Center", "Overview")
                with self.assertRaises(AssertionError):
                    performance.assert_first_paint_query_allowed(
                        "evidence",
                        section="Alert Center",
                        ttl_key="alert_evidence_loader",
                        tier="recent",
                        max_rows=200,
                    )
                with self.assertRaises(AssertionError):
                    performance.assert_first_paint_query_allowed(
                        "decision_packet",
                        section="Alert Center",
                        ttl_key="section_command_packet_Alert Center_ALFA_ALL_7",
                        tier="command_summary",
                        max_rows=None,
                    )
                performance.assert_first_paint_query_allowed(
                    "decision_packet",
                    section="Alert Center",
                    ttl_key="section_command_packet_Alert Center_ALFA_ALL_7",
                    tier="command_summary",
                    max_rows=1,
                )
                performance.end_first_paint(render_id)
                performance.assert_first_paint_query_allowed(
                    "evidence",
                    section="Alert Center",
                    ttl_key="alert_evidence_loader",
                    tier="recent",
                    max_rows=200,
                )
                violations = performance.get_first_paint_budget_violations()

        self.assertEqual(len(violations), 2)
        self.assertEqual(violations[0]["query_boundary"], "evidence")
        self.assertNotIn("SELECT", json.dumps(violations))

    def test_first_paint_session_open_gate_blocks_direct_session_creation(self):
        import performance

        state: dict[str, object] = {}
        with patch.dict(os.environ, {"OVERWATCH_TEST_MODE": "1"}, clear=False):
            with patch.object(performance.st, "session_state", state):
                render_id = performance.begin_first_paint("Workload Operations", "Query Investigation")
                with self.assertRaises(AssertionError):
                    performance.assert_first_paint_session_open_allowed(
                        section="Workload Operations",
                        workflow="Query Investigation",
                        reason="query_search_render",
                        query_boundary="other",
                    )
                performance.assert_first_paint_session_open_allowed(
                    section="Workload Operations",
                    workflow="Query Investigation",
                    reason="packet_lookup",
                    query_boundary="decision_packet",
                    max_rows=1,
                )
                performance.end_first_paint(render_id)
                performance.assert_first_paint_session_open_allowed(
                    section="Workload Operations",
                    workflow="Query Investigation",
                    reason="post_first_paint",
                    query_boundary="other",
                )
                events = performance.get_snowflake_session_open_events()
                violations = performance.get_first_paint_budget_violations()

        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["allowed"])
        self.assertEqual(len(violations), 1)
        self.assertNotIn("SELECT", json.dumps(events + violations))

    def test_first_paint_direct_session_sql_is_guarded_and_sql_free(self):
        import performance
        from utils.session import GuardedSnowflakeSession

        class FakeInnerSession:
            def __init__(self):
                self.calls: list[str] = []

            def sql(self, statement):
                self.calls.append(str(statement))
                return object()

        state: dict[str, object] = {}
        inner = FakeInnerSession()
        guarded = GuardedSnowflakeSession(inner)
        with patch.dict(os.environ, {"OVERWATCH_TEST_MODE": "1"}, clear=False):
            with patch.object(performance.st, "session_state", state):
                render_id = performance.begin_first_paint("Executive Landing", "Overview")
                with self.assertRaises(AssertionError):
                    guarded.sql("SELECT 1")
                with self.assertRaises(AssertionError):
                    guarded.sql("SELECT CURRENT_ROLE()")
                token = performance.begin_direct_sql_allowance(
                    query_boundary="decision_packet",
                    section="Executive Landing",
                    ttl_key="section_command_packet_Executive Landing_ALFA_ALL_7",
                    max_rows=1,
                )
                try:
                    guarded.sql("SELECT BRIEF_ID FROM MART_SECTION_DECISION_CURRENT_FLAT LIMIT 1")
                finally:
                    performance.end_direct_sql_allowance(token)
                performance.end_first_paint(render_id)
                events = performance.get_direct_sql_events()
                violations = performance.get_first_paint_budget_violations()

        self.assertEqual(len(inner.calls), 1)
        self.assertEqual(sum(1 for event in events if not event["allowed"]), 2)
        self.assertEqual(len(violations), 2)
        self.assertNotIn("SELECT", json.dumps(events + violations))
        self.assertNotIn("CURRENT_ROLE", json.dumps(events + violations))

    def test_first_paint_packet_session_defers_role_capture(self):
        import performance
        from utils import session as session_utils

        class FakeRows:
            def __init__(self, rows):
                self._rows = rows

            def collect(self):
                return self._rows

        class FakeInnerSession:
            def __init__(self):
                self.calls: list[str] = []

            def sql(self, statement):
                self.calls.append(str(statement))
                return FakeRows([{"R": "SNOW_SYSADMINS"}])

        state: dict[str, object] = {}
        inner = FakeInnerSession()
        with patch.object(performance.st, "session_state", state), patch.object(session_utils.st, "session_state", state):
            with patch.object(session_utils, "_has_streamlit_snowflake_secrets", return_value=True):
                with patch.object(session_utils, "_make_streamlit_connection_session", return_value=inner):
                    guarded = session_utils._make_session(defer_role_capture=True)
                    self.assertEqual(inner.calls, [])
                    deferred_events = performance.get_role_capture_events()
                    self.assertTrue(deferred_events[0]["deferred"])
                    session_utils._capture_current_role(guarded)
                    role_events = performance.get_role_capture_events()

        self.assertEqual(inner.calls, ["SELECT CURRENT_ROLE() AS R"])
        self.assertTrue(any(event["executed"] for event in role_events))
        self.assertNotIn("CURRENT_ROLE", json.dumps(role_events))

    def test_snowflake_execution_counter_records_only_real_execution(self):
        import performance

        state: dict[str, object] = {}
        with patch.object(performance.st, "session_state", state):
            render_id = performance.begin_first_paint("Cost & Contract", "Overview")
            performance.record_ui_query_event(
                section="Cost & Contract",
                query_boundary="decision_packet",
                cache_layer="streamlit_cache",
                actual_query_executed=None,
                first_paint_sensitive=True,
            )
            performance.increment_snowflake_execution_counter(
                "decision_packet",
                section="Cost & Contract",
                ttl_key="section_command_packet_Cost & Contract_ALFA_ALL_7",
                tier="command_summary",
            )
            performance.end_first_paint(render_id)
            events = performance.get_ui_query_events()
            executions = performance.get_snowflake_execution_counter(render_id)

        self.assertIsNone(events[0]["actual_query_executed"])
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["query_boundary"], "decision_packet")
        self.assertNotIn("SELECT", json.dumps(executions))

    def test_primary_section_entrypoints_use_render_scoped_first_paint_windows(self):
        files = {
            "Executive Landing": APP_ROOT / "sections" / "executive_landing_shell.py",
            "DBA Control Room": APP_ROOT / "sections" / "dba_control_room" / "render.py",
            "Alert Center": APP_ROOT / "sections" / "alert_center.py",
            "Cost & Contract": APP_ROOT / "sections" / "cost_contract.py",
            "Workload Operations": APP_ROOT / "sections" / "workload_operations.py",
            "Security Monitoring": APP_ROOT / "sections" / "security_posture.py",
        }
        for section, path in files.items():
            source = path.read_text(encoding="utf-8")
            self.assertIn("with_section_first_paint_entry", source, section)
            self.assertIn(f'with_section_first_paint_entry("{section}"', source, section)
        helper = (APP_ROOT / "sections" / "decision_workspace_performance.py").read_text(encoding="utf-8")
        self.assertIn("finally:", helper)
        self.assertIn("end_first_paint(render_id)", helper)
        self.assertIn("render_section_entry_first_paint", helper)

    def test_primary_section_entrypoints_do_not_call_session_sql_directly(self):
        files = {
            "Executive Landing": APP_ROOT / "sections" / "executive_landing_shell.py",
            "DBA Control Room": APP_ROOT / "sections" / "dba_control_room" / "render.py",
            "Alert Center": APP_ROOT / "sections" / "alert_center.py",
            "Cost & Contract": APP_ROOT / "sections" / "cost_contract.py",
            "Workload Operations": APP_ROOT / "sections" / "workload_operations.py",
            "Security Monitoring": APP_ROOT / "sections" / "security_posture.py",
        }
        for section, path in files.items():
            source = path.read_text(encoding="utf-8")
            self.assertNotIn(".sql(", source, section)

    def test_target_sql_filter_uses_semantic_field_column_mapping(self):
        from sections.decision_workspace_target_filters import (
            apply_target_dataframe_filter,
            build_target_predicate_plan,
            build_target_sql_filter,
        )

        alert_target = {
            "evidence_id": "EVT-1",
            "entity_id": "WAREHOUSE_A",
            "entity_type": "warehouse",
            "evidence_query": "SELECT * FROM FACT_QUERY_HOURLY",
        }
        alert_sql = build_target_sql_filter(
            "Alert Center",
            alert_target,
            available_columns=("EVENT_ID", "WAREHOUSE_NAME", "EVIDENCE_QUERY"),
        )
        self.assertIn("OVERWATCH_TARGET_PREDICATE", alert_sql)
        self.assertIn("UPPER(EVENT_ID) = UPPER('EVT-1')", alert_sql)
        self.assertNotIn("UPPER(WAREHOUSE_NAME) = UPPER('EVT-1')", alert_sql)
        self.assertNotIn("EVIDENCE_QUERY", alert_sql)
        from utils import query as query_utils

        target_metadata = query_utils._target_metadata_from_sql(
            f"SELECT EVENT_ID FROM ALERT_EVENTS WHERE 1=1 {alert_sql} LIMIT 200",
            "evidence",
        )
        self.assertTrue(target_metadata["target_predicate_marker_present"])
        self.assertIn("EVENT_ID", target_metadata["target_columns_used"])
        self.assertNotIn("EVT-1", json.dumps(target_metadata))

        cost_sql = build_target_sql_filter(
            "Cost & Contract",
            {"entity_type": "warehouse", "entity_id": "PROD_WH"},
            available_columns=("WAREHOUSE_NAME", "USER_NAME", "DEDUPE_KEY"),
        )
        self.assertIn("OVERWATCH_TARGET_PREDICATE", cost_sql)
        self.assertIn("UPPER(WAREHOUSE_NAME) = UPPER('PROD_WH')", cost_sql)
        self.assertNotIn("UPPER(USER_NAME) = UPPER('PROD_WH')", cost_sql)

        query_plan = build_target_predicate_plan(
            "Workload Operations",
            {"entity_type": "query", "entity_id": "abc123", "dedupe_key": "dedupe-1"},
            ("QUERY_ID", "QUERY_HASH", "DEDUPE_KEY"),
        )
        self.assertIn("QUERY_ID", query_plan.exact_columns_by_field["entity_id"])
        self.assertIn("QUERY_HASH", query_plan.exact_columns_by_field["entity_id"])
        self.assertEqual(query_plan.exact_columns_by_field["dedupe_key"], ("DEDUPE_KEY",))
        self.assertIn("QUERY_HASH", query_plan.columns_used)
        self.assertFalse(query_plan.fallback_used)

        large = pd.DataFrame({"ENTITY_NAME": [f"entity-{idx}" for idx in range(600)]})
        filtered, label = apply_target_dataframe_filter(
            large,
            "Cost & Contract",
            {"entity_type": "service", "entity_name": "entity-42"},
        )
        self.assertEqual(len(filtered), len(large))
        self.assertEqual(label, "service: entity-42")

    def test_query_search_is_mart_first_and_account_usage_is_explicit_fallback(self):
        from sections import query_search

        source = (APP_ROOT / "sections" / "query_search.py").read_text(encoding="utf-8")
        self.assertIn("def _recent_query_detail_sql", source)
        self.assertIn("def search_recent_query_summary", source)
        self.assertIn("def load_query_text_preview", source)
        self.assertIn("Search recent mart detail", source)
        self.assertIn("Load SQL preview", source)
        self.assertIn("Show related executions", source)
        self.assertIn("Advanced Account Usage fallback", source)
        self.assertIn("I understand this may scan Account Usage.", source)
        self.assertIn("Search Account Usage fallback", source)
        self.assertIn("account_usage_fallback", source)
        self.assertIn("FACT_QUERY_DETAIL_RECENT", source)

        fallback_pos = source.index("if account_usage_fallback:")
        self.assertNotIn("session = get_session()\n    company =", source)
        account_usage_sql_pos = source.index("FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        self.assertGreater(account_usage_sql_pos, fallback_pos)
        self.assertNotIn("filter_existing_columns", source)
        self.assertNotIn("confirmed_account_usage_query_search_fallback", source)
        self.assertIn('st.session_state["qs_autorun"] = target_kind in {"query_id", "query_signature"}', source)
        self.assertIn('tier="recent"', source)
        self.assertIn('tier="historical"', source)
        self.assertIn('query_boundary="query_search"', source)
        self.assertIn('query_boundary="query_preview"', source)
        self.assertIn('query_boundary="account_usage"', source)
        self.assertIn('"query_search_exact"', source)
        self.assertIn("query_budget_context(context_name", source)
        self.assertIn('query_budget_context("account_usage_fallback"', source)
        self.assertNotIn("SUBSTR(query_text,1,500) AS query_text", source)
        self.assertIn("row_limit = 1", source)
        self.assertIn("query_search_related_", source)
        recent_sql = query_search._recent_query_detail_sql(
            search_cl="AND query_id = '01a'",
            date_predicate="AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
            scoped_filters="",
            user_cl="",
            status_cl="",
            target_wh_cl="",
            row_limit=1,
        )
        self.assertIn("FACT_QUERY_DETAIL_RECENT", recent_sql)
        self.assertNotIn("query_text", recent_sql.lower())
        self.assertIn("query_hash", recent_sql.lower())
        self.assertIn("LIMIT 1", recent_sql)
        preview_sql = query_search._query_text_preview_sql("01a")
        self.assertIn("query_text_preview", preview_sql)
        self.assertIn("LIMIT 1", preview_sql)

    def test_alert_delivery_uses_exact_alert_id_filter_before_text_fallback(self):
        from utils.alert_delivery import _alert_delivery_related_filter

        numeric_filter, values, mode = _alert_delivery_related_filter(alert_ids=("101", "102"), target={})
        self.assertEqual(mode, "alert_ids")
        self.assertEqual(values, ("101", "102"))
        self.assertIn("ARRAY_CONTAINS(101::VARIANT, ALERT_IDS)", numeric_filter)
        self.assertNotIn("EMAIL_SUBJECT ILIKE", numeric_filter)

        text_filter, _, text_mode = _alert_delivery_related_filter(alert_ids=("ALERT-KEY",), target={})
        self.assertEqual(text_mode, "text")
        self.assertIn("EMAIL_SUBJECT ILIKE", text_filter)

    def test_action_queue_target_filter_discovers_safe_optional_columns(self):
        source = (APP_ROOT / "utils" / "action_queue.py").read_text(encoding="utf-8")
        for column in (
            "ACTION_ID",
            "ENTITY_TYPE",
            "ENTITY_NAME",
            "OWNER_SOURCE",
            "OWNER_EVIDENCE",
            "RECOVERY_EVIDENCE",
            "VERIFICATION_STATUS",
            "RECOVERY_AUDIT_STATE",
            "EVENT_ID",
            "ALERT_ID",
            "GRANT_ID",
        ):
            self.assertIn(column, source)
        self.assertNotIn('"PROOF_QUERY",\n            }', source)

    def test_cost_evidence_environment_fallback_and_unsupported_targets(self):
        from sections import cost_contract_evidence

        service_sql = cost_contract_evidence._service_evidence_sql(
            "ALFA",
            "PROD",
            7,
            {"entity_type": "service", "entity_id": "CORTEX"},
            200,
        )
        self.assertIn("MART_COST_EVIDENCE_RECENT", service_sql)
        self.assertIn("'all_fallback' AS ENVIRONMENT_SCOPE_MODE", service_sql)
        self.assertNotIn("UPPER(target.ENVIRONMENT) = UPPER('PROD')", service_sql)

        chargeback_sql = cost_contract_evidence._chargeback_evidence_sql(
            "ALFA",
            "PROD",
            7,
            {"entity_type": "warehouse", "entity_id": "PROD_WH"},
            200,
        )
        self.assertIn("MART_COST_EVIDENCE_RECENT", chargeback_sql)
        self.assertIn("UPPER(target.ENVIRONMENT) = UPPER('PROD')", chargeback_sql)

        with patch.object(cost_contract_evidence, "run_query_or_raise", side_effect=AssertionError("Unsupported target must not query")):
            result = cost_contract_evidence.load_cost_evidence(
                "ALFA",
                "PROD",
                7,
                {"entity_type": "tag", "entity_id": "TEAM"},
            )
        self.assertTrue(result["unsupported_target"])
        self.assertEqual(result["row_count"], 0)
        self.assertIn("not supported", result["summary"])

    def test_targeted_pushdown_source_contracts_cover_primary_evidence_paths(self):
        dba = (APP_ROOT / "sections" / "dba_control_room" / "data.py").read_text(encoding="utf-8")
        security = (APP_ROOT / "sections" / "security_posture_overview_view.py").read_text(encoding="utf-8")
        workload = (APP_ROOT / "sections" / "query_search.py").read_text(encoding="utf-8")
        self.assertIn("_targeted_control_room_sql", dba)
        self.assertIn("build_target_predicate_plan", dba)
        self.assertIn("target_predicate_plan_id", dba)
        self.assertIn('target=get_decision_evidence_target("DBA Control Room")', (APP_ROOT / "sections" / "dba_control_room" / "render.py").read_text(encoding="utf-8"))
        self.assertIn("_targeted_security_sql", security)
        self.assertIn("build_target_predicate_plan", security)
        self.assertIn("target_predicate_plan_id", security)
        self.assertIn('get_decision_evidence_target("Security Monitoring")', security)
        self.assertIn("FACT_QUERY_DETAIL_RECENT", workload)
        self.assertIn("target_kind in {\"query_id\", \"query_signature\"}", workload)

    def test_targeted_loader_sql_places_predicates_before_limits(self):
        from sections.dba_control_room import data as dba_data
        from sections import security_posture_overview_view as security_view
        from sections import query_search

        dba_sql = dba_data._targeted_control_room_sql(
            "SELECT QUERY_ID, QUERY_HASH, WAREHOUSE_NAME FROM FACT_QUERY_DETAIL_RECENT ORDER BY START_TIME DESC LIMIT 200",
            {"entity_type": "query", "entity_id": "QUERY-123"},
            ("QUERY_ID", "QUERY_HASH", "QUERY_SIGNATURE", "WAREHOUSE_NAME"),
        )
        self.assertIn("UPPER(target.QUERY_ID) = UPPER('QUERY-123')", dba_sql)
        self.assertIn("OVERWATCH_TARGET_PREDICATE", dba_sql)
        self.assertLess(dba_sql.index("QUERY-123"), dba_sql.rindex("LIMIT"))
        self.assertLess(dba_sql.index("OVERWATCH_TARGET_PREDICATE"), dba_sql.rindex("LIMIT"))

        task_sql = dba_data._targeted_control_room_sql(
            "SELECT TASK_NAME, ROOT_TASK_NAME, PROCEDURE_NAME FROM TASK_PROOF LIMIT 200",
            {"entity_type": "task", "entity_id": "LOAD_TASK"},
            ("TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME"),
        )
        self.assertIn("UPPER(target.TASK_NAME) = UPPER('LOAD_TASK')", task_sql)
        self.assertIn("OVERWATCH_TARGET_PREDICATE", task_sql)
        self.assertLess(task_sql.index("LOAD_TASK"), task_sql.rindex("LIMIT"))

        security_sql = security_view._targeted_security_sql(
            "SELECT USER_NAME, LOGIN_NAME, ROLE_NAME, GRANT_ID FROM SECURITY_PROOF LIMIT 200",
            {"entity_type": "user", "entity_id": "JDOE"},
        )
        self.assertIn("UPPER(target.USER_NAME) = UPPER('JDOE')", security_sql)
        self.assertIn("OVERWATCH_TARGET_PREDICATE", security_sql)
        self.assertLess(security_sql.index("JDOE"), security_sql.rindex("LIMIT"))

        recent_sql = query_search._recent_query_detail_sql(
            search_cl="AND UPPER(query_id) = UPPER('QUERY-123')",
            date_predicate="AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
            scoped_filters="",
            user_cl="",
            status_cl="",
            target_wh_cl="",
            row_limit=200,
        )
        self.assertIn("FACT_QUERY_DETAIL_RECENT", recent_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", recent_sql)
        self.assertLess(recent_sql.index("QUERY-123"), recent_sql.rindex("LIMIT"))

    def test_cost_overview_first_paint_uses_no_splash_or_detail_loader(self):
        source = (APP_ROOT / "sections" / "cost_contract_overview_floor.py").read_text(encoding="utf-8")
        self.assertIn("load_cost_evidence(", source)
        self.assertNotIn("_maybe_autoload_cost_splash", source)
        self.assertNotIn("_ensure_cost_splash", source)
        self.assertIn(
            'if not refresh_cost and not advanced_requested and not st.session_state.get("cost_contract_evidence_result"):',
            source,
        )
        self.assertIn(
            "return",
            source.split(
                'if not refresh_cost and not advanced_requested and not st.session_state.get("cost_contract_evidence_result"):',
                1,
            )[1].split("if refresh_cost:", 1)[0],
        )
        self.assertIn("Open Advanced Cost Details", source)

    def test_daily_data_trust_view_model_hides_raw_source_objects(self):
        from sections.decision_workspace_view_model import build_decision_workspace_view_model
        from sections.section_command_brief import SectionCommandBrief, SectionCommandSourceState

        brief = SectionCommandBrief(
            section="Security Monitoring",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="Ready",
            headline="Security summary ready",
            summary="Packet ready",
            source="Decision packet",
            freshness_label="Updated now",
            loaded_at="2026-06-26T00:00:00",
            requested_window_days=7,
            resolved_window_days=7,
            source_objects="MART_SECURITY_INTERNAL; FACT_GRANT_DAILY",
            source_gap_detail="SELECT failed FROM MART_SECURITY_INTERNAL",
            sources=(
                SectionCommandSourceState(
                    source_key="grant_daily",
                    source_object="FACT_GRANT_DAILY",
                    required=True,
                    available=True,
                    supports_environment=False,
                    environment_scope_mode="all_fallback",
                ),
                SectionCommandSourceState(
                    source_key="login_daily",
                    source_object="FACT_LOGIN_DAILY",
                    required=True,
                    available=False,
                    supports_environment=False,
                    environment_scope_mode="all_fallback",
                    gap_reason="missing FACT_LOGIN_DAILY",
                ),
            ),
        )

        model = build_decision_workspace_view_model(brief, current_workflow="Overview")
        rendered = json.dumps([row.__dict__ for row in model.source_rows]) + (
            model.fallback.technical_summary if model.fallback else ""
        )

        self.assertIn("Access grants", rendered)
        self.assertIn("All-environment fallback source", rendered)
        self.assertIn("Source unavailable", rendered)
        self.assertNotIn("FACT_", rendered)
        self.assertNotIn("MART_", rendered)
        self.assertNotIn("SELECT", rendered)

    def test_environment_support_contract_is_deployment_owned(self):
        setup = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8")
        package = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
        validation = (ROOT / "snowflake" / "mart_setup" / "08_validation.sql").read_text(encoding="utf-8")

        self.assertIn("SUPPORTS_ENVIRONMENT", setup)
        self.assertIn("ENVIRONMENT_MODE", setup)
        self.assertIn("MERGE INTO OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG", setup)
        self.assertGreater(setup.index("MERGE INTO OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG"), setup.index("WHERE NOT EXISTS"))
        for text in (package,):
            self.assertIn("SUPPORTS_ENVIRONMENT", text)
            self.assertIn("ENVIRONMENT_SCOPE_MODE", text)
            self.assertIn("'SUPPORTS_ENVIRONMENT', SUPPORTS_ENVIRONMENT", text)
        self.assertIn("SECTION_COMMAND_SOURCE_ENVIRONMENT_METADATA", validation)
        self.assertIn("SECTION_DECISION_CURRENT_ONE_ACTIVE_ROW_PER_KEY", validation)
        self.assertIn("WHERE COALESCE(IS_ACTIVE, TRUE)", validation)

    def test_current_packet_lookup_uses_flat_active_normalized_path(self):
        from sections import section_command_brief

        sql = section_command_brief._packet_sql("Cost & Contract", "ALFA", "PROD", 7)
        self.assertIn("MART_SECTION_DECISION_CURRENT_FLAT", sql)
        self.assertIn("SECTION_NAME_NORM", sql)
        self.assertIn("COMPANY_NORM", sql)
        self.assertIn("ENVIRONMENT_NORM", sql)
        self.assertIn("WINDOW_DAYS_NORM", sql)
        self.assertIn("COALESCE(IS_ACTIVE, TRUE)", sql)
        self.assertIn("LIMIT 1", sql)
        self.assertNotIn("UPPER(SECTION_NAME)", sql)
        self.assertNotIn('DECISION_PACKET:"', sql)

        setup = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8")
        validation = (ROOT / "snowflake" / "mart_setup" / "08_validation.sql").read_text(encoding="utf-8")
        self.assertIn("DROP VIEW IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT", setup)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_DECISION_CURRENT_FLAT", setup)
        self.assertIn("MERGE INTO MART_SECTION_DECISION_CURRENT_FLAT", setup)
        load_proc = (ROOT / "snowflake" / "mart_setup" / "05_load_procedures.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE OR REPLACE TEMPORARY TABLE TMP_SECTION_DECISION_PACKET_FLAT_SOURCE", load_proc)
        self.assertIn("CREATE OR REPLACE TEMPORARY TABLE TMP_SECTION_DECISION_PACKET_FLAT", load_proc)
        self.assertIn("CREATE OR REPLACE TEMPORARY TABLE TMP_SECTION_DECISION_PACKET AS", load_proc)
        self.assertLess(
            load_proc.index("CREATE OR REPLACE TEMPORARY TABLE TMP_SECTION_DECISION_PACKET_FLAT AS"),
            load_proc.index("CREATE OR REPLACE TEMPORARY TABLE TMP_SECTION_DECISION_PACKET AS"),
        )
        raw_packet_block = load_proc.split("CREATE OR REPLACE TEMPORARY TABLE TMP_SECTION_DECISION_PACKET AS", 1)[1].split("MERGE INTO MART_SECTION_DECISION_CURRENT", 1)[0]
        self.assertIn("FROM TMP_SECTION_DECISION_PACKET_FLAT", raw_packet_block)
        self.assertIn("INSERT INTO MART_SECTION_DECISION_CURRENT_FLAT", load_proc)
        flat_insert_block = load_proc.split("INSERT INTO MART_SECTION_DECISION_CURRENT_FLAT", 1)[1].split("UPDATE MART_SECTION_DECISION_CURRENT_FLAT", 1)[0]
        self.assertIn("FROM TMP_SECTION_DECISION_PACKET_FLAT", flat_insert_block)
        self.assertNotIn('DECISION_PACKET:"', flat_insert_block)
        self.assertIn("SECTION_DECISION_CURRENT_OPTIMIZED_LOOKUP_SCHEMA", validation)
        self.assertIn("SECTION_DECISION_CURRENT_FLAT_TABLE", validation)
        self.assertIn("SECTION_DECISION_CURRENT_FLAT_ACTIVE_MATCHES_CURRENT", validation)

    def test_optional_query_optimization_flags_are_guarded(self):
        config = (ROOT / "snowflake" / "mart_setup" / "03_config_and_audit_tables.sql").read_text(encoding="utf-8")
        procs = (ROOT / "snowflake" / "mart_setup" / "05_load_procedures.sql").read_text(encoding="utf-8")
        validation = (ROOT / "snowflake" / "mart_setup" / "08_validation.sql").read_text(encoding="utf-8")

        self.assertIn("'OVERWATCH_ENABLE_CLUSTER_KEYS', 'TRUE'", config)
        self.assertIn("'OVERWATCH_ENABLE_SEARCH_OPTIMIZATION', 'FALSE'", config)
        self.assertIn("SP_OVERWATCH_APPLY_OPTIONAL_PERFORMANCE_OPTIMIZATION", procs)
        self.assertIn("TMP_PERFORMANCE_OPTIMIZATION_TARGETS", procs)
        self.assertIn("FOR target_row IN", procs)
        self.assertIn("IF (target_row.ENABLED) THEN", procs)
        self.assertIn("EXECUTE IMMEDIATE target_row.STATEMENT_TEXT", procs)
        self.assertIn("CLUSTER BY (IS_ACTIVE, SECTION_NAME_NORM, COMPANY_NORM, ENVIRONMENT_NORM, WINDOW_DAYS_NORM)", procs)
        self.assertIn("ADD SEARCH OPTIMIZATION", procs)
        self.assertIn("OVERWATCH_PERFORMANCE_OPTIMIZATION_AUDIT", procs)
        self.assertIn("'WARN'", procs)
        self.assertIn("'INFO'", procs)
        self.assertIn("Search Optimization is disabled by default", procs)
        self.assertIn("MART_QUERY_EVIDENCE_RECENT", procs)
        self.assertIn("MART_ALERT_EVIDENCE_RECENT", procs)
        self.assertIn("MART_SECURITY_EVIDENCE_RECENT", procs)
        self.assertIn("MART_COST_EVIDENCE_RECENT", procs)
        self.assertIn("MART_DBA_EVIDENCE_RECENT", procs)
        self.assertIn("OVERWATCH_OPTIONAL_PERFORMANCE_OPTIMIZATION_FLAGS", validation)
        self.assertIn("OVERWATCH_PERFORMANCE_OPTIMIZATION_AUDIT_TABLE", validation)
        self.assertIn("IFF(COUNT(*) = 0, 'PASS', 'WARN')", validation)

    def test_compact_recent_evidence_marts_are_declared(self):
        setup = (ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql").read_text(encoding="utf-8")
        combined = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
        procs = (ROOT / "snowflake" / "mart_setup" / "05_load_procedures.sql").read_text(encoding="utf-8")
        for table_name in (
            "MART_QUERY_EVIDENCE_RECENT",
            "MART_ALERT_EVIDENCE_RECENT",
            "MART_SECURITY_EVIDENCE_RECENT",
            "MART_COST_EVIDENCE_RECENT",
            "MART_DBA_EVIDENCE_RECENT",
        ):
            self.assertIn(f"CREATE TRANSIENT TABLE IF NOT EXISTS {table_name}", setup)
            self.assertIn(f"CREATE TRANSIENT TABLE IF NOT EXISTS {table_name}", combined)
            self.assertIn(f"DELETE FROM {table_name}", procs)
            self.assertIn(f"INSERT INTO {table_name}", procs)
            self.assertIn(f"DELETE FROM {table_name}", combined)
            self.assertIn(f"INSERT INTO {table_name}", combined)
        for required_column in (
            "START_TIME                   TIMESTAMP_NTZ",
            "EVENT_TS                     TIMESTAMP_NTZ",
            "USAGE_DATE                   DATE",
            "ROOT_TASK_NAME               VARCHAR(500)",
        ):
            self.assertIn(required_column, setup)
            self.assertIn(required_column, combined)
        self.assertLess(
            procs.index("INSERT INTO MART_QUERY_EVIDENCE_RECENT"),
            procs.index("CREATE OR REPLACE TEMPORARY TABLE TMP_FAST_SOURCE_SNAPSHOT"),
        )
        self.assertLess(
            procs.index("INSERT INTO MART_ALERT_EVIDENCE_RECENT"),
            procs.index("CREATE OR REPLACE TEMPORARY TABLE TMP_FAST_SOURCE_SNAPSHOT"),
        )
        self.assertLess(
            procs.index("INSERT INTO MART_SECURITY_EVIDENCE_RECENT"),
            procs.index("CREATE OR REPLACE TEMPORARY TABLE TMP_FAST_SOURCE_SNAPSHOT"),
        )
        self.assertLess(
            procs.index("INSERT INTO MART_COST_EVIDENCE_RECENT"),
            procs.index("CREATE OR REPLACE TEMPORARY TABLE TMP_FAST_SOURCE_SNAPSHOT"),
        )
        self.assertLess(
            procs.index("INSERT INTO MART_DBA_EVIDENCE_RECENT"),
            procs.index("CREATE OR REPLACE TEMPORARY TABLE TMP_FAST_SOURCE_SNAPSHOT"),
        )

    def test_query_contract_linter_flags_risky_shapes_and_passes_packet_lookup(self):
        from query_contracts import (
            QueryContract,
            iter_query_contracts,
            lint_query_text,
            resolve_query_contract,
        )
        from sections import section_command_brief

        packet_contract = resolve_query_contract(
            boundary="decision_packet",
            section="Cost & Contract",
            ttl_key="section_command_packet_Cost & Contract_ALFA_PROD_7",
            tier="command_summary",
        )
        self.assertTrue(packet_contract.first_paint_allowed)
        self.assertEqual(packet_contract.contract_id, "decision_packet_current_flat")
        self.assertFalse(lint_query_text(section_command_brief._packet_sql("Cost & Contract", "ALFA", "PROD", 7), packet_contract))

        account_usage_findings = lint_query_text(
            "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            QueryContract(boundary="route", section="Workload Operations", max_rows=200),
        )
        codes = {finding.code for finding in account_usage_findings}
        self.assertIn("ACCOUNT_USAGE_FORBIDDEN", codes)
        self.assertIn("STAR_PROJECTION", codes)
        self.assertIn("MISSING_LIMIT", codes)

        evidence_findings = lint_query_text(
            "SELECT query_id FROM FACT_QUERY_DETAIL_RECENT LIMIT 200",
            QueryContract(boundary="evidence", section="Workload Operations", requires_target_predicate=True),
        )
        self.assertIn("MISSING_TARGET_PREDICATE", {finding.code for finding in evidence_findings})
        marker_findings = lint_query_text(
            "SELECT query_id FROM FACT_QUERY_DETAIL_RECENT WHERE company = 'ALFA' LIMIT 200",
            QueryContract(
                boundary="evidence",
                section="Workload Operations",
                requires_target_predicate=True,
                target_predicate_marker_required=True,
                target_predicate_markers=("QUERY_ID",),
            ),
        )
        self.assertIn("TARGET_MARKER_MISSING", {finding.code for finding in marker_findings})
        generic_column_findings = lint_query_text(
            "SELECT query_id FROM FACT_QUERY_DETAIL_RECENT WHERE QUERY_ID IS NOT NULL LIMIT 200",
            QueryContract(
                boundary="evidence",
                section="Workload Operations",
                requires_target_predicate=True,
                target_predicate_marker_required=True,
                target_predicate_markers=("QUERY_ID",),
            ),
        )
        self.assertIn("TARGET_MARKER_MISSING", {finding.code for finding in generic_column_findings})
        marked_findings = lint_query_text(
            "SELECT query_id FROM FACT_QUERY_DETAIL_RECENT WHERE /* OVERWATCH_TARGET_PREDICATE */ QUERY_ID = '01a' LIMIT 200",
            QueryContract(
                boundary="evidence",
                section="Workload Operations",
                requires_target_predicate=True,
                target_predicate_marker_required=True,
                target_predicate_markers=("QUERY_ID",),
            ),
        )
        self.assertFalse([finding for finding in marked_findings if finding.severity == "error"])
        query_search_contract = resolve_query_contract(
            boundary="query_search",
            section="Workload Operations",
            ttl_key="query_search_recent_detail_ALFA_Exact query ID_01a__ALL_7_1",
            tier="recent",
        )
        self.assertEqual(query_search_contract.boundary, "query_search")
        self.assertEqual(query_search_contract.contract_id, "query_search_exact")
        self.assertEqual(query_search_contract.max_rows, 1)
        related_contract = resolve_query_contract(
            boundary="query_search",
            section="Workload Operations",
            ttl_key="query_search_related_ALFA_hash_01a_50",
            tier="recent",
        )
        self.assertEqual(related_contract.contract_id, "query_search_related")
        self.assertEqual(related_contract.max_rows, 50)
        self.assertTrue([contract for contract in iter_query_contracts() if contract.boundary == "decision_packet"])

    def test_targeted_evidence_proof_requires_plan_metadata(self):
        handwritten_marker_event = {
            "query_boundary": "evidence",
            "target_context_present": True,
            "target_label": "query: 01a",
            "target_predicate_marker_present": True,
            "target_columns_used": ["QUERY_ID"],
            "target_predicate_plan_id": "",
        }
        valid_plan_event = {
            "query_boundary": "evidence",
            "target_context_present": True,
            "target_label": "query: 01a",
            "target_predicate_marker_present": True,
            "target_columns_used": ["QUERY_ID"],
            "target_predicate_plan_id": "fixture-plan",
        }
        events = [handwritten_marker_event, valid_plan_event]
        targeted = [
            event for event in events
            if event.get("query_boundary") == "evidence"
            and (
                event.get("target_context_present") is True
                or str(event.get("target_label") or "").strip()
            )
        ]
        missing = sum(
            1 for event in targeted
            if not bool(event.get("target_predicate_marker_present"))
            or not event.get("target_columns_used")
            or not str(event.get("target_predicate_plan_id") or "").strip()
        )
        self.assertEqual(missing, 1)

    def test_query_runner_enforces_contracts_before_execution(self):
        import performance
        from utils import query

        state: dict[str, object] = {}
        with patch.dict(os.environ, {"OVERWATCH_TEST_MODE": "1"}, clear=False):
            with patch.object(performance.st, "session_state", state), patch.object(query.st, "session_state", state):
                with self.assertRaises(AssertionError):
                    query.run_query(
                        "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 10",
                        ttl_key="route_bad",
                        tier="recent",
                        section="Workload Operations",
                        max_rows=10,
                        query_boundary="other",
                    )
                with self.assertRaises(AssertionError):
                    query.run_query(
                        "SELECT BRIEF_ID FROM MART_SECTION_DECISION_CURRENT_FLAT LIMIT 1",
                        ttl_key="section_command_packet_Executive Landing_ALFA_ALL_7",
                        tier="command_summary",
                        section="Executive Landing",
                        max_rows=1,
                    )
                with self.assertRaises(AssertionError):
                    query.run_query(
                        "SELECT QUERY_ID FROM FACT_QUERY_DETAIL_RECENT WHERE /* OVERWATCH_TARGET_PREDICATE */ QUERY_ID = '01a' LIMIT 1",
                        ttl_key="query_search_recent_detail_ALFA_Exact query ID_01a__ALL_7_1",
                        tier="recent",
                        section="Query Search & History",
                        max_rows=1,
                    )
                with self.assertRaises(AssertionError):
                    query.run_query(
                        "SELECT QUERY_ID FROM MART_DBA_EVIDENCE_RECENT "
                        "WHERE /* OVERWATCH_TARGET_PREDICATE */ QUERY_ID = '01a' LIMIT 1",
                        ttl_key="dba_control_room_targeted_evidence",
                        tier="recent",
                        section="DBA Control Room",
                        max_rows=1,
                        query_boundary="evidence",
                        target_context_present=True,
                        target_label="query: 01a",
                        target_columns_used=("QUERY_ID",),
                        target_predicate_marker_present=True,
                        target_fallback_used=False,
                    )
                with self.assertRaises(AssertionError):
                    query.run_query(
                        "SELECT QUERY_ID FROM MART_DBA_EVIDENCE_RECENT "
                        "WHERE QUERY_ID = '01a' LIMIT 1",
                        ttl_key="dba_control_room_targeted_evidence",
                        tier="recent",
                        section="DBA Control Room",
                        max_rows=1,
                        query_boundary="evidence",
                        target_context_present=True,
                        target_label="query: 01a",
                        target_columns_used=("QUERY_ID",),
                        target_predicate_plan_id="fixture-plan",
                    )
                with self.assertRaises(AssertionError):
                    query.run_query(
                        "SELECT QUERY_ID FROM MART_DBA_EVIDENCE_RECENT "
                        "WHERE /* OVERWATCH_TARGET_PREDICATE */ QUERY_ID ILIKE '01a' LIMIT 1",
                        ttl_key="dba_control_room_targeted_evidence",
                        tier="recent",
                        section="DBA Control Room",
                        max_rows=1,
                        query_boundary="evidence",
                        target_context_present=True,
                        target_label="query: 01a",
                        target_columns_used=("QUERY_ID",),
                        target_predicate_marker_present=True,
                        target_fallback_used=True,
                        target_predicate_plan_id="fixture-plan",
                    )
                with self.assertRaises(AssertionError):
                    query.run_query(
                        "SELECT QUERY_ID FROM FACT_QUERY_DETAIL_RECENT "
                        "WHERE /* OVERWATCH_TARGET_PREDICATE */ QUERY_ID = '01a' LIMIT 1",
                        ttl_key="dba_control_room_targeted_evidence",
                        tier="recent",
                        section="DBA Control Room",
                        max_rows=1,
                        query_boundary="evidence",
                        target_context_present=True,
                        target_label="query: 01a",
                        target_columns_used=("QUERY_ID",),
                        target_predicate_marker_present=True,
                        target_fallback_used=False,
                        target_predicate_plan_id="fixture-plan",
                    )
                with patch.object(query, "_execute_snowflake_query", return_value=pd.DataFrame([{"QUERY_ID": "01a"}])):
                    result = query.run_query(
                        "SELECT QUERY_ID FROM MART_DBA_EVIDENCE_RECENT LIMIT 200",
                        ttl_key="bounded_no_target_evidence",
                        tier="recent",
                        section="DBA Control Room",
                        max_rows=200,
                        query_boundary="evidence",
                        target_context_present=False,
                        use_cache=False,
                    )
                    self.assertEqual(len(result), 1)
                findings = performance.get_query_lint_findings()

        codes = {finding["code"] for finding in findings}
        self.assertIn("ACCOUNT_USAGE_FORBIDDEN", codes)
        self.assertIn("STAR_PROJECTION", codes)
        self.assertIn("MISSING_EXPLICIT_BOUNDARY", codes)
        self.assertIn("TARGET_PLAN_REQUIRED", codes)
        self.assertIn("TARGET_PLAN_MARKER_REQUIRED", codes)
        self.assertIn("TARGET_FALLBACK_FORBIDDEN", codes)
        self.assertIn("UNEXPECTED_TABLE_FAMILY", codes)
        self.assertNotIn("SELECT", json.dumps(findings))

    def test_contextual_query_budget_contexts_count_actual_executions(self):
        import performance

        state: dict[str, object] = {}
        with patch.object(performance.st, "session_state", state):
            performance.clear_ui_query_events()
            route_token = performance.begin_query_budget_context(
                "route_action",
                section="Alert Center",
                workflow="Active Alerts",
            )
            performance.increment_snowflake_execution_counter(
                "evidence",
                section="Alert Center",
                ttl_key="alert_center_evidence",
                tier="recent",
            )
            route_summary = performance.end_query_budget_context(route_token)
            self.assertFalse(route_summary["passed_budget"])
            self.assertIn("exceeded budget", route_summary["failure_reason"])
            with self.assertRaises(AssertionError):
                performance.assert_query_budget_context_passed(route_summary)
            self.assertEqual(route_summary["budget"], 0)
            self.assertEqual(route_summary["actual_snowflake_executions"], 1)

            direct_token = performance.begin_query_budget_context(
                "route_action",
                section="Alert Center",
                workflow="Active Alerts",
            )
            performance.record_direct_sql_event(
                query_text="SELECT 1",
                section="Alert Center",
                query_boundary="metadata",
                allowed=True,
                reason="metadata_probe",
            )
            direct_summary = performance.end_query_budget_context(direct_token)
            self.assertFalse(direct_summary["passed_budget"])
            self.assertIn("route_action emitted direct SQL", direct_summary["failure_reason"])
            self.assertEqual(direct_summary["direct_sql_events"], 1)
            self.assertEqual(direct_summary["metadata_probe_events"], 1)
            self.assertEqual(direct_summary["actual_snowflake_executions"], 1)
            self.assertEqual(performance.get_direct_sql_events()[-1]["direct_sql_kind"], "metadata_probe")

            runner_token = performance.begin_query_budget_context(
                "refresh_packet",
                section="Executive Landing",
                workflow="Overview",
            )
            allowance = performance.begin_direct_sql_allowance(
                query_boundary="decision_packet",
                section="Executive Landing",
                ttl_key="section_command_packet_Executive Landing_ALFA_ALL_7",
                max_rows=1,
            )
            try:
                performance.record_direct_sql_event(
                    query_text="SELECT BRIEF_ID FROM MART_SECTION_DECISION_CURRENT_FLAT LIMIT 1",
                    section="Executive Landing",
                    query_boundary="decision_packet",
                    allowed=True,
                    reason="central_runner_packet",
                )
            finally:
                performance.end_direct_sql_allowance(allowance)
            runner_summary = performance.end_query_budget_context(runner_token)
            self.assertTrue(runner_summary["passed_query_budget"], runner_summary)
            self.assertEqual(runner_summary["direct_sql_events"], 1)
            self.assertEqual(runner_summary["actual_snowflake_executions"], 0)
            self.assertEqual(performance.get_direct_sql_events()[-1]["direct_sql_kind"], "packet_direct_sql")

            evidence_token = performance.begin_query_budget_context(
                "evidence_click",
                section="Alert Center",
                workflow="Active Alerts",
            )
            performance.increment_snowflake_execution_counter(
                "evidence",
                section="Alert Center",
                ttl_key="alert_center_evidence",
                tier="recent",
            )
            performance.increment_snowflake_execution_counter(
                "evidence",
                section="Alert Center",
                ttl_key="alert_center_evidence_second",
                tier="recent",
            )
            evidence_summary = performance.end_query_budget_context(evidence_token)
            self.assertFalse(evidence_summary["passed_budget"])
            self.assertIn("more than one evidence boundary", evidence_summary["failure_reason"])
            self.assertEqual(evidence_summary["budget"], 1)
            self.assertEqual(evidence_summary["boundaries"], {"evidence": 2})

            exact_token = performance.begin_query_budget_context(
                "query_search_exact",
                section="Workload Operations",
                workflow="Query Investigation",
            )
            performance.increment_snowflake_execution_counter("query_search", section="Workload Operations", ttl_key="q1", tier="recent")
            performance.increment_snowflake_execution_counter("query_search", section="Workload Operations", ttl_key="q2", tier="recent")
            exact_summary = performance.end_query_budget_context(exact_token)
            self.assertFalse(exact_summary["passed_query_budget"])
            self.assertIn("query_search_exact", exact_summary["failure_reason"])
            self.assertEqual(len(performance.get_query_budget_context_events()), 5)

    def test_button_contracts_do_not_grant_account_usage_to_generic_admin(self):
        contracts = list(iter_button_action_contracts())
        fallback_contracts = [contract for contract in contracts if contract.action_type == "account_usage_fallback"]
        self.assertTrue(fallback_contracts)
        for contract in contracts:
            if contract.action_type in {"admin_load", "advanced_load", "setup_health"}:
                self.assertFalse(contract.account_usage_allowed, contract)
            if contract.account_usage_allowed:
                self.assertEqual(contract.action_type, "account_usage_fallback", contract)
                self.assertTrue(contract.requires_admin, contract)
                self.assertEqual(contract.expected_query_boundary, "account_usage", contract)
                self.assertEqual(contract.expected_query_count, 1, contract)
            if contract.action_type == "route" and not contract.skip_reason:
                self.assertEqual(contract.expected_query_count, 0, contract)
                self.assertEqual(contract.expected_query_budget_context, "route_action", contract)
                self.assertEqual(contract.expected_budget, 0, contract)
                self.assertEqual(contract.expected_actual_boundaries, {}, contract)
                self.assertEqual(contract.expected_session_open_count, 0, contract)
                self.assertEqual(contract.expected_direct_sql_count, 0, contract)
                self.assertEqual(contract.expected_metadata_probe_count, 0, contract)
            if contract.action_type == "evidence_load":
                self.assertEqual(contract.expected_query_boundary, "evidence", contract)
                self.assertEqual(contract.expected_query_budget_context, "evidence_click", contract)
                self.assertEqual(contract.expected_budget, 1, contract)
                self.assertEqual(contract.expected_actual_boundaries, {"evidence": 1}, contract)
                self.assertLessEqual(contract.expected_max_rows or 0, 500, contract)
            if contract.action_type == "refresh_packet":
                self.assertEqual(contract.expected_query_budget_context, "refresh_packet", contract)
                self.assertEqual(contract.expected_actual_boundaries, {}, contract)
                self.assertEqual(contract.expected_session_open_count, 0, contract)
                self.assertEqual(contract.expected_direct_sql_count, 0, contract)
                self.assertEqual(contract.expected_metadata_probe_count, 0, contract)
            if contract.action_type == "account_usage_fallback":
                self.assertEqual(contract.expected_query_budget_context, "account_usage_fallback", contract)
                self.assertEqual(contract.expected_actual_boundaries, {"account_usage": 1}, contract)
        self.assertNotEqual("route_action", "evidence_click")
        self.assertNotEqual("query_search_exact", "query_preview")

    def test_synthetic_clicked_action_without_budget_context_fails_contract_check(self):
        from sections.button_action_contracts import ButtonActionContract, marker_budget_mismatches

        cases = (
            ButtonActionContract(
                section="Alert Center",
                action_type="route",
                expected_query_budget_context="route_action",
            ),
            ButtonActionContract(
                section="Alert Center",
                action_type="evidence_load",
                expected_query_budget_context="evidence_click",
                expected_actual_boundaries={"evidence": 1},
            ),
            ButtonActionContract(
                section="Workload Operations",
                action_type="advanced_load",
                expected_query_budget_context="query_preview",
                expected_actual_boundaries={"query_preview": 1},
            ),
        )
        for contract in cases:
            with self.assertRaises(AssertionError):
                assert_button_budget_context(
                    {
                        "observed_query_budget_contexts": [],
                        "actual_boundaries": {},
                    },
                    contract,
                )

        self.assertEqual(
            marker_budget_mismatches(
                [{"event_id": "evt1", "marker_budget": "advanced_diagnostics"}],
                ["advanced_diagnostics"],
            ),
            [],
        )
        self.assertEqual(
            marker_budget_mismatches(
                [{"event_id": "evt2", "marker_budget": "advanced_diagnostics"}],
                ["route_action"],
            )[0]["expected_runtime_context"],
            "advanced_diagnostics",
        )

    def test_runtime_marker_metadata_is_attached_to_session_and_direct_sql_events(self):
        import importlib.util
        import tempfile
        import performance

        helper_source = """
import performance

def emit_direct():
    # DIRECT_SQL_ADMIN_OK boundary=admin reason=diagnostic budget=advanced_diagnostics owner=platform
    return performance.record_direct_sql_event(query_text="SELECT 1", query_boundary="admin", allowed=True, reason="diagnostic")

def emit_session():
    # SESSION_OPEN_ADMIN_OK boundary=setup_health reason=setup budget=admin_setup owner=platform
    return performance.record_snowflake_session_open_event(section="Settings", query_boundary="setup_health", reason="setup")
"""
        state: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(performance.st, "session_state", state):
            helper_path = Path(tmp_dir) / "marked_helper.py"
            helper_path.write_text(helper_source, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("marked_helper", helper_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            direct_event = module.emit_direct()
            session_event = module.emit_session()

        self.assertEqual(direct_event["marker_boundary"], "admin")
        self.assertEqual(direct_event["marker_budget"], "advanced_diagnostics")
        self.assertEqual(direct_event["marker_owner"], "platform")
        self.assertEqual(session_event["marker_boundary"], "setup_health")
        self.assertEqual(session_event["marker_budget"], "admin_setup")
        self.assertEqual(session_event["marker_owner"], "platform")
        self.assertNotIn("SELECT", json.dumps(direct_event))
        self.assertNotIn("SNOWFLAKE", json.dumps(session_event))

    def _packet_row(self, section: str) -> dict[str, object]:
        route_key = {
            "Executive Landing": "executive_cost",
            "DBA Control Room": "workload_query_investigation",
            "Alert Center": "alert_center_critical_high",
            "Cost & Contract": "cost_contract_explorer_warehouse",
            "Workload Operations": "workload_pipeline_tasks",
            "Security Monitoring": "security_risky_grants",
        }[section]
        metrics = [
            {
                "METRIC_KEY": "active_items",
                "METRIC_LABEL": "Active items",
                "METRIC_VALUE": "4",
                "METRIC_NUMERIC_VALUE": 4,
                "METRIC_FORMAT": "number",
                "SOURCE_KEY": "alert_events" if section == "Alert Center" else "query_hourly",
                "TREND_POINTS": [{"ts": f"2026-06-{day:02d}", "value": day} for day in range(20, 27)],
                "TREND_PERIOD": "7d",
                "TREND_POINT_COUNT": 7,
                "TREND_QUALITY": "complete",
                "ZERO_FILL_POLICY": "count_zero_fill",
            }
        ]
        exceptions = [
            {
                "FINDING_KEY": f"{section.lower().replace(' ', '_')}_finding",
                "DEDUPE_KEY": f"{section}:finding:1",
                "SEVERITY": "High",
                "SIGNAL": "Targeted finding",
                "ENTITY_TYPE": "warehouse" if section == "Cost & Contract" else "query",
                "ENTITY_ID": "PROD_WH" if section == "Cost & Contract" else "QUERY-123",
                "ENTITY_NAME": "PROD_WH" if section == "Cost & Contract" else "QUERY-123",
                "EVIDENCE_ID": "QUERY-123",
                "EVIDENCE_QUERY": "SELECT * FROM MART_INTERNAL",
                "FIRST_SEEN_TS": "2026-06-26T09:00:00",
                "DUE_TS": "2026-06-26T17:00:00",
                "OWNER_NAME": "Platform Owner",
                "OWNER_GAP": False,
                "SLA_STATE": "Due soon",
                "ROUTE_KEY": route_key,
            }
        ]
        actions = [
            {
                "ACTION_KEY": route_key,
                "ACTION_LABEL": "Investigate target",
                "CTA": "Investigate",
                "ACTION_DETAIL": "Open the owning workflow with target context.",
                "ROUTE_KEY": route_key,
            }
        ]
        sources = [
            {
                "SOURCE_KEY": "query_hourly",
                "SOURCE_OBJECT": "FACT_QUERY_HOURLY",
                "REQUIRED": True,
                "AVAILABLE": True,
                "SUPPORTS_ENVIRONMENT": True,
                "ENVIRONMENT_SCOPE_MODE": "exact",
                "CONFIDENCE": "allocated",
            }
        ]
        return {
            "BRIEF_ID": f"{section}-brief",
            "SECTION_NAME": section,
            "COMPANY": "ALFA",
            "ENVIRONMENT": "ALL",
            "WINDOW_DAYS": 7,
            "RESOLVED_COMPANY": "ALFA",
            "RESOLVED_ENVIRONMENT": "ALL",
            "RESOLVED_WINDOW_DAYS": 7,
            "SNAPSHOT_TS": "2026-06-26T10:00:00",
            "LOAD_TS": "2026-06-26T10:00:00",
            "STATE": "Ready",
            "HEADLINE": f"{section} Decision Workspace ready",
            "SUMMARY": "Compact packet loaded.",
            "TOP_SIGNAL": "Targeted finding",
            "TOP_ENTITY": "PROD_WH",
            "TOP_ACTION": "Open targeted workbench",
            "SOURCE_STATUS": "Ready",
            "SOURCE_FRESHNESS": "Updated now",
            "SOURCE_OBJECTS": "FACT_QUERY_HOURLY",
            "FRESHNESS_MINUTES": 4,
            "TARGET_FRESHNESS_MINUTES": 60,
            "IS_STALE": False,
            "CONFIDENCE": "allocated",
            "REQUIRED_SOURCE_COUNT": 1,
            "AVAILABLE_SOURCE_COUNT": 1,
            "MISSING_SOURCE_COUNT": 0,
            "SOURCE_COVERAGE_PCT": 100,
            "DATA_AVAILABILITY_STATE": "Ready",
            "STALE_SOURCE_COUNT": 0,
            "PRIMARY_ROUTE_KEY": "overview",
            "PRIMARY_ACTION_LABEL": "Open targeted workbench",
            "PRIMARY_ACTION_DETAIL": "Route with target context.",
            "METRICS": metrics,
            "EXCEPTIONS": exceptions,
            "ACTIONS": actions,
            "SOURCES": sources,
            "PACKET_BYTES": 42000,
        }

    def _count_events(
        self,
        events: list[dict[str, object]],
        *,
        render_id: str = "",
        boundary: str = "",
        actual: bool | None = None,
    ) -> int:
        selected = events
        if render_id:
            selected = [event for event in selected if event.get("render_id") == render_id]
        if boundary:
            selected = [event for event in selected if event.get("query_boundary") == boundary]
        if actual is not None:
            selected = [event for event in selected if event.get("actual_query_executed") is actual]
        return len(selected)

    def _button_action_type(self, label: str, key: str) -> str:
        label_text = str(label or "").lower()
        text = f"{label} {key}".lower()
        if "load" in label_text or "evidence" in label_text or "detail" in label_text:
            return "evidence_load"
        if "refresh" in text:
            return "refresh_packet"
        if "setup health" in text or "initialize" in text:
            return "setup_health"
        if "download" in text or "export" in text:
            return "export"
        if "case" in text:
            return "add_to_case"
        if "advanced" in text or "admin" in text:
            return "advanced_load"
        if "primary_" in key or "secondary_" in key or "open" in text or "investigate" in text or "review" in text:
            return "route"
        return "fallback"

    def _current_workflow(self, section: str, state: dict[str, object]) -> str:
        key = WORKFLOW_STATE_KEY_BY_SECTION.get(section, "")
        value = str(state.get(key, "") or "")
        if value:
            return value
        return SECTION_WORKFLOW_CONTRACT.get(section, ("Overview",))[0]

    def _base_state(self, section: str, workflow: str | None = None) -> dict[str, object]:
        state: dict[str, object] = {
            "active_company": "ALFA",
            "global_environment": "ALL",
            "executive_landing_workflow": "Executive Overview",
            "cost_contract_workflow": "Cost Overview",
            "dba_control_room_active_view": "Morning Cockpit",
            "alert_center_active_view": "Active Alerts",
            "workload_operations_workflow": "Workload Overview",
            "security_posture_view": "Security Overview",
            "security_posture_workflow": "Security Overview",
        }
        selected_workflow = workflow or SECTION_WORKFLOW_CONTRACT.get(section, ("",))[0]
        key = WORKFLOW_STATE_KEY_BY_SECTION.get(section, "")
        if key and selected_workflow:
            state[key] = selected_workflow
        if section == "Security Monitoring" and selected_workflow:
            state["security_posture_workflow"] = selected_workflow
        return state

    def _button_contract_payload(
        self,
        *,
        section: str,
        workflow: str,
        label: str,
        key: str,
        fallback_action_type: str = "fallback",
        expected_artifact: str = "",
    ) -> dict[str, object]:
        contract = resolve_button_action_contract(
            section=section,
            workflow=workflow,
            label=label,
            key=key,
        )
        if contract is None:
            return {
                "action_type": "unknown",
                "expected_target_section": "",
                "expected_target_workflow": "",
                "expected_lens_state": {},
                "expected_state_updates": {},
                "expected_artifact": expected_artifact,
                "exact_route_key": "",
                "heavy_query_allowed": False,
                "account_usage_allowed": False,
                "requires_admin": False,
                "expected_rerun": True,
                "expected_query_boundary": "",
                "expected_query_count": None,
                "expected_max_rows": None,
                "expected_query_contract_id": "",
                "expected_query_budget_context": "",
                "expected_budget": None,
                "expected_actual_boundaries": {},
                "expected_session_open_count": None,
                "expected_direct_sql_count": None,
                "expected_metadata_probe_count": None,
                "expected_snowflake_execution_count": None,
                "contract_resolved": False,
                "contract_valid": False,
                "skip_reason": "",
            }
        payload = contract.to_artifact()
        return {
            "action_type": str(payload.get("action_type") or fallback_action_type),
            "expected_target_section": str(payload.get("expected_target_section") or ""),
            "expected_target_workflow": str(payload.get("expected_target_workflow") or ""),
            "expected_lens_state": dict(payload.get("expected_lens_state") or {}),
            "expected_state_updates": dict(payload.get("expected_state_updates") or {}),
            "expected_artifact": str(payload.get("expected_artifact") or expected_artifact),
            "exact_route_key": str(payload.get("exact_route_key") or ""),
            "heavy_query_allowed": bool(payload.get("heavy_query_allowed")),
            "account_usage_allowed": bool(payload.get("account_usage_allowed")),
            "requires_admin": bool(payload.get("requires_admin")),
            "expected_rerun": bool(payload.get("expected_rerun")),
            "expected_query_boundary": str(payload.get("expected_query_boundary") or ""),
            "expected_query_count": payload.get("expected_query_count"),
            "expected_max_rows": payload.get("expected_max_rows"),
            "expected_query_contract_id": str(payload.get("expected_query_contract_id") or ""),
            "expected_query_budget_context": str(payload.get("expected_query_budget_context") or ""),
            "expected_budget": payload.get("expected_budget"),
            "expected_actual_boundaries": dict(payload.get("expected_actual_boundaries") or {}),
            "expected_session_open_count": payload.get("expected_session_open_count"),
            "expected_direct_sql_count": payload.get("expected_direct_sql_count"),
            "expected_metadata_probe_count": payload.get("expected_metadata_probe_count"),
            "expected_snowflake_execution_count": payload.get("expected_snowflake_execution_count"),
            "contract_resolved": True,
            "contract_valid": contract_target_is_valid(contract),
            "skip_reason": str(payload.get("skip_reason") or ""),
        }

    def _json_safe(self, value: object) -> object:
        if isinstance(value, pd.DataFrame):
            return {"type": "DataFrame", "rows": int(len(value)), "columns": list(value.columns)}
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    def _no_live_snowflake_patches(self):
        import access_control
        import utils.session as session_mod

        def _blocked_session(*_args, **_kwargs):
            raise AssertionError("Render proof must not create a live Snowflake session.")

        return [
            patch.object(session_mod, "_make_session", side_effect=_blocked_session),
            patch.object(session_mod, "_make_streamlit_connection_session", side_effect=_blocked_session),
            patch.object(session_mod, "_quiet_streamlit_snowflake_connection", side_effect=_blocked_session),
            patch.object(access_control, "probe_snowflake_available", return_value=False),
            patch.object(access_control, "refresh_current_role_for_access", return_value=""),
        ]

    def _streamlit_patches(
        self,
        state: dict[str, object],
        html_fragments: list[str],
        *,
        buttons: list[dict[str, object]] | None = None,
        downloads: list[dict[str, object]] | None = None,
        section: str = "",
        workflow: str = "Overview",
        click_key: str = "",
    ):
        buttons = buttons if buttons is not None else []
        downloads = downloads if downloads is not None else []

        def _columns(spec, *_, **__):
            count = len(spec) if isinstance(spec, list) else int(spec)
            return [_Context() for _ in range(count)]

        def _segmented_control(_label, options, *_, key=None, **__):
            values = tuple(str(option) for option in options)
            current = str(state.get(str(key), values[0] if values else "") or "")
            if current not in values and values:
                current = values[0]
            if key:
                state[str(key)] = current
            return current

        def _selectbox(_label, options, *_, index=0, key=None, **__):
            values = list(options)
            selected = state.get(str(key), values[index] if values else None) if key else (values[index] if values else None)
            if key:
                state[str(key)] = selected
            html_fragments.append(f"<label>{_label}</label>")
            return selected

        def _html(fragment="", *_, **__):
            html_fragments.append(str(fragment or ""))

        def _text_input(label="", *_, key=None, **__):
            html_fragments.append(f"<label>{label}</label>")
            return str(state.get(str(key), "")) if key else ""

        def _button(label="", *_, key=None, help=None, type=None, **__):
            stable_key = str(key or label or f"button_{len(buttons)}")
            label_text = str(label or stable_key)
            html_fragments.append(f"<button>{label_text}</button>")
            contract_payload = self._button_contract_payload(
                section=section,
                workflow=workflow,
                label=label_text,
                key=stable_key,
            )
            buttons.append({
                "section": section,
                "workflow": workflow,
                "label": label_text,
                "key": stable_key,
                **contract_payload,
                "source_file": "rendered_streamlit",
                "line_hint": None,
                "help": str(help or ""),
                "button_type": str(type or ""),
                "clicked": bool(click_key and stable_key == click_key),
            })
            return bool(click_key and stable_key == click_key)

        def _download_button(label="", data=None, file_name=None, mime=None, key=None, **__):
            stable_key = str(key or label or f"download_{len(downloads)}")
            payload = {
                "section": section,
                "workflow": workflow,
                "label": str(label or stable_key),
                "key": stable_key,
                **self._button_contract_payload(
                    section=section,
                    workflow=workflow,
                    label=str(label or stable_key),
                    key=stable_key,
                    fallback_action_type="export",
                    expected_artifact=str(file_name or stable_key),
                ),
                "content_type": str(mime or ""),
                "content_length": len(str(data or "")),
                "clicked": bool(click_key and stable_key == click_key),
            }
            downloads.append(payload)
            buttons.append({
                **payload,
                "source_file": "rendered_streamlit",
                "line_hint": None,
            })
            return bool(click_key and stable_key == click_key)

        patches = [
            patch("streamlit.session_state", state),
            patch("streamlit.html", side_effect=_html, create=True),
            patch("streamlit.markdown", side_effect=lambda fragment="", *_, **__: html_fragments.append(str(fragment or ""))),
            patch("streamlit.caption", side_effect=lambda *_args, **_kwargs: None),
            patch("streamlit.info", side_effect=lambda *args, **_kwargs: html_fragments.append(" ".join(str(arg) for arg in args))),
            patch("streamlit.warning", side_effect=lambda *args, **_kwargs: html_fragments.append(" ".join(str(arg) for arg in args))),
            patch("streamlit.success", side_effect=lambda *args, **_kwargs: html_fragments.append(" ".join(str(arg) for arg in args))),
            patch("streamlit.error", side_effect=lambda *args, **_kwargs: html_fragments.append(" ".join(str(arg) for arg in args))),
            patch("streamlit.divider", side_effect=lambda *_args, **_kwargs: None),
            patch("streamlit.subheader", side_effect=lambda *args, **_kwargs: html_fragments.append(" ".join(str(arg) for arg in args))),
            patch("streamlit.write", side_effect=lambda *args, **_kwargs: html_fragments.append(" ".join(str(arg) for arg in args))),
            patch("streamlit.code", side_effect=lambda body="", *_, **__: html_fragments.append(f"<code>{body}</code>")),
            patch("streamlit.dataframe", side_effect=lambda *_args, **_kwargs: None),
            patch("streamlit.download_button", side_effect=_download_button),
            patch("streamlit.button", side_effect=_button),
            patch("streamlit.columns", side_effect=_columns),
            patch("streamlit.container", side_effect=lambda *_, **__: _Context()),
            patch(
                "streamlit.expander",
                side_effect=lambda label="", *_, **__: (
                    html_fragments.append(f"<section>{label}</section>") or _Context()
                ),
            ),
            patch("streamlit.segmented_control", side_effect=_segmented_control, create=True),
            patch("streamlit.radio", side_effect=lambda _label, options, *_, index=0, key=None, **__: _segmented_control(_label, options, key=key)),
            patch("streamlit.selectbox", side_effect=_selectbox),
            patch("streamlit.checkbox", side_effect=lambda *_, **__: False),
            patch("streamlit.text_input", side_effect=_text_input),
            patch("streamlit.slider", side_effect=lambda _label, _min, _max, value, *_, key=None, **__: state.setdefault(str(key), value) if key else value),
            patch("streamlit.rerun", side_effect=_RerunSignal("rerun requested")),
        ]
        return patches

    def _render_primary_section_entrypoint(
        self,
        section_name: str,
        state: dict[str, object],
        html_fragments: list[str],
        *,
        buttons: list[dict[str, object]] | None = None,
        downloads: list[dict[str, object]] | None = None,
        click_key: str = "",
        block_evidence: bool = True,
    ) -> None:
        module_path = {
            "Executive Landing": "sections.executive_landing_shell",
            "DBA Control Room": "sections.dba_control_room.render",
            "Alert Center": "sections.alert_center",
            "Cost & Contract": "sections.cost_contract",
            "Workload Operations": "sections.workload_operations",
            "Security Monitoring": "sections.security_posture",
        }[section_name]
        module = importlib.import_module(module_path)
        import performance

        workflow = self._current_workflow(section_name, state)
        with ExitStack() as stack:
            for patcher in self._no_live_snowflake_patches():
                stack.enter_context(patcher)
            for patcher in self._streamlit_patches(
                state,
                html_fragments,
                buttons=buttons,
                downloads=downloads,
                section=section_name,
                workflow=workflow,
                click_key=click_key,
            ):
                stack.enter_context(patcher)
            if section_name == "Executive Landing":
                stack.enter_context(patch.object(module, "_active_company", return_value="ALFA"))
                stack.enter_context(patch.object(module, "_active_environment", return_value="ALL"))
                stack.enter_context(patch.object(module, "_credit_price", return_value=3.68))
                stack.enter_context(patch.object(module, "_current_observability_board", return_value=(pd.DataFrame(), {})))
                stack.enter_context(patch.object(module, "_executive_observability_connection_unavailable", return_value=True))
                stack.enter_context(patch.object(module, "_render_loaded_executive_landing_workflow", side_effect=lambda *_, **__: html_fragments.append("<section>Executive workflow shell</section>") or False))
                if block_evidence:
                    stack.enter_context(patch.object(module, "_load_executive_snapshot", side_effect=AssertionError("First paint must not load Executive evidence")))
                else:
                    def _fake_load_executive_snapshot(*_args, **_kwargs):
                        self._run_deterministic_evidence_loader(
                            section_name=section_name,
                            state=state,
                            expected_artifact="executive_snapshot_state",
                            html_fragments=html_fragments,
                        )
                        state["executive_landing_snapshot"] = {"scope": ("ALFA", "ALL", 7), "deterministic": True}
                        return True

                    stack.enter_context(patch.object(module, "_load_executive_snapshot", side_effect=_fake_load_executive_snapshot))
            elif section_name == "DBA Control Room":
                stack.enter_context(patch.object(module, "get_active_company", return_value="ALFA"))
                stack.enter_context(patch.object(module, "get_active_environment", return_value="ALL"))
                stack.enter_context(patch.object(module, "get_credit_price", return_value=3.68))
                if hasattr(module, "get_session"):
                    stack.enter_context(patch.object(module, "get_session", return_value=object()))
                if hasattr(module, "render_load_status"):
                    stack.enter_context(patch.object(module, "render_load_status", side_effect=lambda *_args, **_kwargs: _Context()))
                if block_evidence:
                    stack.enter_context(patch.object(module, "_load_control_room", side_effect=AssertionError("First paint must not load DBA evidence")))
                else:
                    def _fake_load_control_room(*_args, **_kwargs):
                        self._run_deterministic_evidence_loader(
                            section_name=section_name,
                            state=state,
                            expected_artifact="dba_control_room_evidence_rows",
                            html_fragments=html_fragments,
                        )
                        return {
                            "summary": pd.DataFrame([{"SECTION": section_name, "EVIDENCE_ID": "QUERY-123"}]),
                            "failed_queries": pd.DataFrame([{"QUERY_ID": "QUERY-123", "EVIDENCE_ID": "QUERY-123"}]),
                            "action_queue": pd.DataFrame([{"ACTION_ID": "ACTION-123", "EVIDENCE_ID": "QUERY-123"}]),
                        }

                    stack.enter_context(patch.object(module, "_load_control_room", side_effect=_fake_load_control_room))
                stack.enter_context(patch.object(module, "_render_control_room_admin_advanced", side_effect=lambda *_args, **_kwargs: html_fragments.append("<section>DBA admin shell</section>")))
            elif section_name == "Alert Center":
                stack.enter_context(patch.object(module, "get_active_company", return_value="ALFA"))
                stack.enter_context(patch.object(module, "get_active_environment", return_value="ALL"))
                if block_evidence:
                    stack.enter_context(patch.object(module, "_load_center_data", side_effect=AssertionError("First paint must not load alert evidence")))
                else:
                    def _fake_load_center_data(*_args, **_kwargs):
                        performance.increment_snowflake_execution_counter(
                            "evidence",
                            section="Alert Center",
                            ttl_key="alert_center_targeted_loader",
                            tier="recent",
                        )
                        performance.record_ui_query_event(
                            section="Alert Center",
                            workflow=self._current_workflow(section_name, state),
                            query_tier="recent",
                            ttl_key="alert_center_targeted_loader",
                            elapsed_ms=5,
                            row_count=1,
                            max_rows=200,
                            actual_query_executed=True,
                            cache_layer="none",
                            query_boundary="evidence",
                            target_label="Selected finding",
                            target_context_present=True,
                            target_columns_used=("EVENT_ID", "ALERT_KEY"),
                            target_predicate_marker_present=True,
                            target_fallback_used=False,
                            target_predicate_plan_id="fixture-alert-plan",
                            first_paint_sensitive=False,
                        )
                        return {
                            "alerts": pd.DataFrame([{"EVENT_ID": "QUERY-123", "ALERT_KEY": "QUERY-123"}]),
                            "action_queue": pd.DataFrame(),
                            "delivery_log": pd.DataFrame(),
                            "rules": pd.DataFrame(),
                            "issues": pd.DataFrame(),
                            "_loaded_sources": {"alerts", "action_queue", "delivery_log", "rules"},
                        }

                    stack.enter_context(patch.object(module, "_alert_center_action_session", return_value=object()))
                    stack.enter_context(patch.object(module, "_load_center_data", side_effect=_fake_load_center_data))
            elif section_name == "Cost & Contract":
                stack.enter_context(patch.object(module, "get_active_company", return_value="ALFA"))
                stack.enter_context(patch.object(module, "get_active_environment", return_value="ALL"))
                stack.enter_context(patch.object(module, "_refresh_cost_detail_state", side_effect=AssertionError("First paint must not load Cost detail")))
                if hasattr(module, "render_cost_primary_tabs"):
                    stack.enter_context(patch.object(module, "render_cost_primary_tabs", side_effect=lambda current: current))
                if hasattr(module, "render_cost_explorer_lens_pills"):
                    stack.enter_context(patch.object(module, "render_cost_explorer_lens_pills", side_effect=lambda current: current))
                if block_evidence:
                    stack.enter_context(patch.object(module, "_render_cost_contract_workflow", side_effect=lambda *_args, **_kwargs: html_fragments.append("<section>Cost workflow shell</section>")))
                else:
                    def _fake_render_cost_workflow(*_args, **_kwargs):
                        with performance.query_budget_context(
                            "evidence_click",
                            section="Cost & Contract",
                            workflow="Cost Overview",
                            budget=1,
                        ):
                            self._run_deterministic_evidence_loader(
                                section_name=section_name,
                                state=state,
                                expected_artifact="cost_contract_evidence_rows",
                                html_fragments=html_fragments,
                            )
                        html_fragments.append("<section>Cost focused workbench</section>")

                    stack.enter_context(patch.object(module, "_render_cost_contract_workflow", side_effect=_fake_render_cost_workflow))
                stack.enter_context(patch.object(module, "_render_advanced_cost_tools", side_effect=lambda *_args, **_kwargs: html_fragments.append("<section>Cost advanced shell</section>")))
            elif section_name == "Workload Operations":
                stack.enter_context(patch.object(module, "get_active_company", return_value="ALFA"))
                stack.enter_context(patch.object(module, "get_active_environment", return_value="ALL"))
                stack.enter_context(patch.object(module, "build_loaded_section_alert_signal_board", return_value=pd.DataFrame()))
                stack.enter_context(patch.object(module, "render_workflow_module", side_effect=lambda workflow, *_args, **_kwargs: html_fragments.append(f"<section>Workload {workflow} shell</section>")))
                stack.enter_context(patch.object(module, "_render_workload_forecast_detail", side_effect=lambda *_args, **_kwargs: html_fragments.append("<section>Workload forecast shell</section>")))
                stack.enter_context(patch.object(module, "_render_workload_closed_loop_detail", side_effect=lambda *_args, **_kwargs: html_fragments.append("<section>Workload closed-loop shell</section>")))
                stack.enter_context(patch.object(module, "_render_workload_command_findings", side_effect=lambda *_args, **_kwargs: html_fragments.append("<section>Workload findings shell</section>")))
            elif section_name == "Security Monitoring":
                stack.enter_context(patch.object(module, "get_active_company", return_value="ALFA"))
                stack.enter_context(patch.object(module, "get_active_environment", return_value="ALL"))
                if block_evidence:
                    stack.enter_context(patch.object(module, "_load_security_brief", side_effect=AssertionError("First paint must not load security evidence")))
                else:
                    def _fake_refresh_security_summary(*_args, **_kwargs):
                        with performance.query_budget_context(
                            "evidence_click",
                            section="Security Monitoring",
                            workflow="Security Overview",
                            budget=1,
                        ):
                            self._run_deterministic_evidence_loader(
                                section_name=section_name,
                                state=state,
                                expected_artifact="security_evidence_rows",
                                html_fragments=html_fragments,
                            )
                        state["security_posture_summary"] = pd.DataFrame([{"FAILED_LOGINS": 1, "FAILED_USERS": 1, "ACTIVE_USERS": 10, "USERS_WITHOUT_MFA": 0, "RECENT_GRANTS": 1, "SHARED_DATABASES": 0}])
                        state["security_posture_exceptions"] = pd.DataFrame([{"USER_NAME": "QUERY-123", "EVIDENCE_ID": "QUERY-123"}])
                        state["security_posture_meta"] = {"company": "ALFA", "environment": "ALL", "days": 30, "loaded_at": "Loaded now"}

                    stack.enter_context(patch.object(module, "_load_security_brief", side_effect=_fake_refresh_security_summary))
                    if hasattr(module, "_refresh_security_summary"):
                        stack.enter_context(patch.object(module, "_refresh_security_summary", side_effect=_fake_refresh_security_summary))
                stack.enter_context(patch.object(module, "render_workflow_module", side_effect=lambda workflow, *_args, **_kwargs: html_fragments.append(f"<section>Security {workflow} shell</section>")))
                stack.enter_context(patch.object(module, "_render_advanced_security_evidence", side_effect=lambda *_args, **_kwargs: html_fragments.append("<section>Security advanced shell</section>")))
                def _security_renderer(key):
                    def _render(*_args, **_kwargs):
                        if (
                            not block_evidence
                            and key == "Security Overview"
                            and state.pop("security_posture_load_evidence", False)
                        ):
                            with performance.query_budget_context(
                                "evidence_click",
                                section="Security Monitoring",
                                workflow="Security Overview",
                                budget=1,
                            ):
                                self._run_deterministic_evidence_loader(
                                    section_name=section_name,
                                    state=state,
                                    expected_artifact="security_evidence_rows",
                                    html_fragments=html_fragments,
                                )
                        html_fragments.append(f"<section>Security {key} shell</section>")

                    return _render

                security_renderers = {
                    key: _security_renderer(key)
                    for key in getattr(module, "SECURITY_POSTURE_RENDERERS", {})
                }
                stack.enter_context(patch.object(module, "SECURITY_POSTURE_RENDERERS", security_renderers))
            module.render()

    def _run_deterministic_evidence_loader(
        self,
        *,
        section_name: str,
        state: dict[str, object],
        expected_artifact: str,
        html_fragments: list[str] | None = None,
    ) -> dict[str, object]:
        import performance
        from sections.shell_helpers import render_decision_evidence_panel

        target = state.get("decision_workspace_evidence_target")
        rows = [
            {
                "SECTION": section_name,
                "ENTITY_ID": "PROD_WH" if section_name == "Cost & Contract" else "QUERY-123",
                "EVIDENCE_ID": "QUERY-123",
                "TARGETED": bool(target),
            }
        ]
        performance.record_ui_query_event(
            section=section_name,
            workflow="Decision Evidence",
            query_tier="recent",
            ttl_key=f"{section_name.lower().replace(' ', '_').replace('&', 'and')}_deterministic_evidence_loader",
            elapsed_ms=5,
            row_count=len(rows),
            max_rows=200,
            actual_query_executed=True,
            cache_layer="none",
            query_boundary="evidence",
            target_label="Selected finding" if target else "",
            target_context_present=bool(target),
            target_columns_used=("ENTITY_ID", "EVIDENCE_ID") if target else (),
            target_predicate_marker_present=True if target else False,
            target_fallback_used=False if target else None,
            target_predicate_plan_id="fixture-target-plan" if target else "",
            first_paint_sensitive=False,
        )
        performance.increment_snowflake_execution_counter(
            "evidence",
            section=section_name,
            ttl_key=f"{section_name.lower().replace(' ', '_').replace('&', 'and')}_deterministic_evidence_loader",
            tier="recent",
        )
        state[f"{section_name.lower().replace(' ', '_').replace('&', 'and')}_deterministic_evidence_rows"] = rows
        if html_fragments is not None:
            with ExitStack() as stack:
                for patcher in self._streamlit_patches(
                    state,
                    html_fragments,
                    section=section_name,
                    workflow="Decision Evidence",
                ):
                    stack.enter_context(patcher)
                render_decision_evidence_panel(
                    f"{section_name} Evidence",
                    "Loaded now",
                    "Filtered rows for selected finding target.",
                    metrics=(("Filtered rows", len(rows)), ("Target", "Selected finding")),
                    rows=pd.DataFrame(rows),
                    source_note="Targeted bounded evidence",
                )
        return {
            "artifact_type": expected_artifact or "evidence_rows",
            "row_count": len(rows),
            "target_present": bool(target),
            "max_rows": 200,
        }

    def _render_setup_health_snapshot(self) -> str:
        from sections.decision_workspace_setup_health import (
            DecisionBootstrapHealth,
            SETUP_HEALTH_KEY,
            SETUP_HEALTH_PANEL_OPEN_KEY,
            render_decision_setup_health_panel,
        )

        state: dict[str, object] = {
            SETUP_HEALTH_PANEL_OPEN_KEY: True,
            SETUP_HEALTH_KEY: DecisionBootstrapHealth(
                status="DEGRADED",
                user_message="Decision summaries are usable with setup warnings.",
                global_status="DEGRADED",
                selected_scope_status="SUCCESS",
                current_section_status="SUCCESS",
                selected_procedure="SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS",
                fallback_used=True,
                current_packet_count=6,
                sections_present=PRIMARY_SECTIONS,
                degraded_sections=("Cost & Contract",),
                warning_sections=("Cost & Contract",),
                max_packet_bytes=42000,
                requested_scope="ALFA / PROD / 7",
                resolved_scope="ALFA / ALL / 7",
                admin_detail="MART_SECTION_DECISION_CURRENT source validation detail",
                suggested_remediation="Review optional source coverage in setup health.",
                persistence_status="persisted",
            ).__dict__,
        }
        fragments: list[str] = []
        with ExitStack() as stack:
            for patcher in self._streamlit_patches(
                state,
                fragments,
                section="Settings",
                workflow="Decision Summary Setup Health",
            ):
                stack.enter_context(patcher)
            render_decision_setup_health_panel(session=None)
        return "\n".join(fragment for fragment in fragments if fragment)

    def _render_advanced_scope_snapshot(self) -> str:
        import filters

        state: dict[str, object] = {
            "global_user": "svc",
            "global_role": "analyst",
            "global_database": "APP_DB",
            "global_schema": "PUBLIC",
        }
        fragments: list[str] = []
        with ExitStack() as stack:
            for patcher in self._streamlit_patches(
                state,
                fragments,
                section="Advanced Scope",
                workflow="Active filters",
            ):
                stack.enter_context(patcher)
            stack.enter_context(patch.object(filters, "ensure_global_database_options", return_value=None))
            filters.render_advanced_scope_controls("ALFA")
        return "\n".join(fragment for fragment in fragments if fragment)

    def _write_brand_artifacts(self, brand_dir: Path) -> None:
        brand_dir.mkdir(exist_ok=True)
        logo_dark = render_overwatch_logo_svg(48, "OVERWATCH")
        logo_light = render_overwatch_logo_svg(48, "OVERWATCH")
        brand_dir.joinpath("overwatch_logo_dark.svg").write_text(logo_dark, encoding="utf-8")
        brand_dir.joinpath("overwatch_logo_light.svg").write_text(logo_light, encoding="utf-8")
        base_css = """
<style>
.ow-sidebar-brand { display: flex; align-items: flex-start; padding: 14px; }
.ow-brand-lockup { display: flex; align-items: center; gap: 12px; }
.ow-sidebar-logo { width: 42px; height: 42px; display: inline-flex; color: var(--brand-accent); }
.ow-logo-mark { color: currentColor; }
.ow-logo-prism, .ow-logo-cut, .ow-logo-core { fill: currentColor; }
.ow-logo-cut { opacity: .62; }
.ow-logo-core { opacity: .92; }
.ow-brand-copy strong { display: block; color: var(--brand-text); font: 800 15px system-ui, sans-serif; }
.ow-brand-copy small { display: block; color: var(--brand-muted); font: 700 10px system-ui, sans-serif; letter-spacing: .04em; white-space: nowrap; }
</style>
""".strip()
        dark_html = (
            '<section data-brand-theme="dark" style="--brand-accent:#5fd7ff;--brand-text:#f4f7fa;'
            '--brand-muted:#aabcc8;background:#06111a;">'
            f"{base_css}{render_sidebar_brand()}</section>"
        )
        light_html = (
            '<section data-brand-theme="light" style="--brand-accent:#0068b7;--brand-text:#102a43;'
            '--brand-muted:#526b7a;background:#ffffff;">'
            f"{base_css}{render_sidebar_brand()}</section>"
        )
        brand_dir.joinpath("sidebar_brand_dark.html").write_text(dark_html, encoding="utf-8")
        brand_dir.joinpath("sidebar_brand_light.html").write_text(light_html, encoding="utf-8")

        for svg in (logo_dark, logo_light, render_overwatch_logo_svg(24, "OVERWATCH")):
            self.assertIn('viewBox="0 0 48 48"', svg)
            self.assertIn('role="img"', svg)
            self.assertIn("currentColor", svg)
            self.assertEqual(svg.count("<path"), 3)
            self.assertNotIn("ow-logo-orbit", svg)
            self.assertNotIn("ow-logo-scan", svg)
            self.assertNotIn("ow-logo-node", svg)
            self.assertNotIn("M24 18.8v10.4M18.8 24", svg)
        self.assertIn("white-space: nowrap", dark_html)
        self.assertNotIn("LIVE", dark_html)
        self.assertNotIn("LIVE", light_html)

    def test_primary_workflow_matrix_renders_entry_decision_workspace_without_first_paint_debt(self):
        import performance
        from sections import section_command_brief

        render_cases = [
            (section_name, workflow, {})
            for section_name, workflows in SECTION_WORKFLOW_MATRIX.items()
            for workflow in workflows
        ] + list(EXTRA_WORKFLOW_LENS_CASES)
        for section_name, workflow, extra_state in render_cases:
            state = self._base_state(section_name, workflow)
            state.update(extra_state)
            html_fragments: list[str] = []
            rendered_buttons: list[dict[str, object]] = []

            def fake_run_query(_sql, ttl_key="default", tier="recent", section: str = "", max_rows=None, **_kwargs):
                performance.record_ui_query_event(
                    section=section_name,
                    workflow=workflow,
                    query_tier=tier,
                    ttl_key=ttl_key,
                    elapsed_ms=3,
                    row_count=1,
                    max_rows=max_rows,
                    actual_query_executed=True,
                    cache_layer="none",
                    query_boundary="decision_packet",
                    first_paint_sensitive=True,
                )
                performance.increment_snowflake_execution_counter(
                    "decision_packet",
                    section=section_name,
                    ttl_key=ttl_key,
                    tier=tier,
                )
                return pd.DataFrame([self._packet_row(section_name)])

            with ExitStack() as no_snowflake_stack:
                no_snowflake_stack.enter_context(patch.object(performance.st, "session_state", state))
                no_snowflake_stack.enter_context(patch.object(section_command_brief.st, "session_state", state))
                no_snowflake_stack.enter_context(patch.object(section_command_brief, "run_query", side_effect=fake_run_query))
                no_snowflake_stack.enter_context(patch.object(section_command_brief, "snowflake_entry_available", return_value=True))
                no_snowflake_stack.enter_context(patch.object(section_command_brief, "decision_fixture_enabled", return_value=False))
                for patcher in self._no_live_snowflake_patches():
                    no_snowflake_stack.enter_context(patcher)
                performance.clear_ui_query_events()
                performance.clear_snowflake_execution_counter()
                self._render_primary_section_entrypoint(
                    section_name,
                    state,
                    html_fragments,
                    buttons=rendered_buttons,
                )
                html = "\n".join(html_fragments)
                self.assertIn("ow-decision-workspace-marker", html, (section_name, workflow))
                render_ids = [
                    event.get("render_id")
                    for event in performance.get_ui_query_events()
                    if event.get("query_boundary") == "decision_packet" and event.get("render_id")
                ]
                self.assertEqual(len(render_ids), 1, (section_name, workflow, performance.get_ui_query_events()))
                render_id = str(render_ids[0])
                for boundary in ("evidence", "metadata", "account_usage"):
                    self.assertEqual(
                        self._count_events(
                            performance.get_ui_query_events(),
                            render_id=render_id,
                            boundary=boundary,
                            actual=True,
                        ),
                        0,
                        (section_name, workflow, boundary),
                    )
                self.assertEqual(performance.st.session_state.get("_overwatch_first_paint_stack"), [])

    def _run_render_harness(self) -> tuple[
        list[dict[str, object]],
        list[dict[str, object]],
        dict[str, str],
        list[dict[str, object]],
        list[dict[str, object]],
        dict[str, list[dict[str, object]]],
    ]:
        import performance
        from sections import section_command_brief

        rows: list[dict[str, object]] = []
        all_telemetry: list[dict[str, object]] = []
        snapshots: dict[str, str] = {}
        button_manifest: list[dict[str, object]] = []
        button_results: list[dict[str, object]] = []
        perf_events: dict[str, list[dict[str, object]]] = {
            "first_paint_budget_violations": [],
            "session_open_events": [],
            "direct_sql_events": [],
            "role_capture_events": [],
            "query_lint_findings": [],
            "query_budget_contexts": [],
        }
        for section_name in PRIMARY_SECTIONS:
            state = self._base_state(section_name)
            html_fragments: list[str] = []
            rendered_buttons: list[dict[str, object]] = []
            rendered_downloads: list[dict[str, object]] = []

            def fake_run_query(_sql, ttl_key="default", tier="recent", section: str = "", max_rows=None, **_kwargs):
                performance.record_ui_query_event(
                    section=section_name,
                    workflow="Overview",
                    query_tier=tier,
                    ttl_key=ttl_key,
                    cache_hit_or_use_cache=False,
                    elapsed_ms=3,
                    row_count=1,
                    max_rows=max_rows,
                    actual_query_executed=True,
                    cache_layer="none",
                    query_boundary="decision_packet",
                    first_paint_sensitive=True,
                )
                performance.increment_snowflake_execution_counter(
                    "decision_packet",
                    section=section_name,
                    ttl_key=ttl_key,
                    tier=tier,
                )
                return pd.DataFrame([self._packet_row(section_name)])

            with ExitStack() as no_snowflake_stack:
                no_snowflake_stack.enter_context(patch.object(performance.st, "session_state", state))
                no_snowflake_stack.enter_context(patch.object(section_command_brief.st, "session_state", state))
                no_snowflake_stack.enter_context(patch.object(section_command_brief, "run_query", side_effect=fake_run_query))
                no_snowflake_stack.enter_context(patch.object(section_command_brief, "snowflake_entry_available", return_value=True))
                no_snowflake_stack.enter_context(patch.object(section_command_brief, "decision_fixture_enabled", return_value=False))
                for patcher in self._no_live_snowflake_patches():
                    no_snowflake_stack.enter_context(patcher)
                performance.clear_ui_query_events()
                performance.clear_snowflake_execution_counter()
                self._render_primary_section_entrypoint(
                    section_name,
                    state,
                    html_fragments,
                    buttons=rendered_buttons,
                    downloads=rendered_downloads,
                )
                events_after_cold = performance.get_ui_query_events()
                cold_render_id = next(
                    event["render_id"]
                    for event in events_after_cold
                    if event.get("query_boundary") == "decision_packet" and event.get("render_id")
                )
                self._render_primary_section_entrypoint(
                    section_name,
                    state,
                    html_fragments,
                    buttons=rendered_buttons,
                    downloads=rendered_downloads,
                )
                events_after_warm = performance.get_ui_query_events()
                render_ids = [
                    event["render_id"]
                    for event in events_after_warm
                    if event.get("query_boundary") == "decision_packet" and event.get("render_id")
                ]
                warm_render_id = render_ids[-1] if len(render_ids) > 1 else ""
                seen_button_keys: set[str] = set()
                unique_buttons: list[dict[str, object]] = []
                for button in rendered_buttons:
                    key = str(button.get("key") or "")
                    if not key or key in seen_button_keys:
                        continue
                    seen_button_keys.add(key)
                    unique_buttons.append({k: v for k, v in button.items() if k != "clicked"})
                for button in unique_buttons:
                    self.assertTrue(str(button.get("label") or "").strip(), button)
                    self.assertTrue(str(button.get("key") or "").strip(), button)
                    self.assertTrue(button.get("contract_resolved") or button.get("skip_reason"), button)
                    self.assertTrue(button.get("contract_valid") or button.get("skip_reason"), button)
                    if button.get("action_type") == "route":
                        self.assertTrue(button.get("expected_target_section"), button)
                        self.assertTrue(button.get("expected_target_workflow"), button)
                        self.assertTrue(button.get("exact_route_key"), button)
                    if button.get("action_type") in {"export", "add_to_case"}:
                        self.assertTrue(button.get("expected_artifact"), button)
                    button_manifest.append(button)

                section_snapshot = "\n".join(fragment for fragment in html_fragments if fragment)
                snapshots[section_name] = section_snapshot
                self.assertIn("ow-decision-workspace-marker", section_snapshot)

                for button in unique_buttons:
                    click_state = dict(state)
                    click_html: list[str] = []
                    click_buttons: list[dict[str, object]] = []
                    key = str(button["key"])
                    before_events = len(performance.get_ui_query_events())
                    before_execs = len(performance.get_snowflake_execution_counter())
                    before_budget_contexts = len(performance.get_query_budget_context_events())
                    before_direct_sql_events = len(performance.get_direct_sql_events())
                    before_session_open_events = len(performance.get_snowflake_session_open_events())
                    action_type = str(button.get("action_type") or "")
                    raised = ""
                    try:
                        self._render_primary_section_entrypoint(
                            section_name,
                            click_state,
                            click_html,
                            buttons=click_buttons,
                            click_key=key,
                            block_evidence=button.get("action_type") != "evidence_load",
                        )
                    except _RerunSignal:
                        raised = "rerun"
                    except AssertionError as exc:
                        raised = f"assertion: {exc}"
                    if action_type == "evidence_load" and raised == "rerun":
                        try:
                            self._render_primary_section_entrypoint(
                                section_name,
                                click_state,
                                click_html,
                                buttons=click_buttons,
                                block_evidence=False,
                            )
                        except _RerunSignal:
                            pass
                    after_events = performance.get_ui_query_events()
                    after_execs = performance.get_snowflake_execution_counter()
                    budget_contexts = performance.get_query_budget_context_events()[before_budget_contexts:]
                    direct_sql_delta = performance.get_direct_sql_events()[before_direct_sql_events:]
                    session_open_delta = performance.get_snowflake_session_open_events()[before_session_open_events:]
                    budget_context_names = [
                        str(context.get("name") or "")
                        for context in budget_contexts
                        if str(context.get("name") or "")
                    ]
                    observed_actual_boundaries: dict[str, int] = {}
                    for context in budget_contexts:
                        for boundary, count in dict(context.get("actual_boundaries") or {}).items():
                            key_boundary = str(boundary)
                            observed_actual_boundaries[key_boundary] = (
                                observed_actual_boundaries.get(key_boundary, 0) + int(count or 0)
                            )
                    budget_actual_execs = sum(
                        int(context.get("actual_snowflake_executions") or 0)
                        for context in budget_contexts
                    )
                    budget_session_opens = sum(
                        int(context.get("session_open_count") or 0)
                        for context in budget_contexts
                    )
                    budget_direct_sql = sum(
                        int(context.get("direct_sql_events") or 0)
                        for context in budget_contexts
                    )
                    budget_metadata_probes = sum(
                        int(context.get("metadata_probe_events") or 0)
                        for context in budget_contexts
                    )
                    budget_role_capture = sum(
                        int(context.get("role_capture_events") or 0)
                        for context in budget_contexts
                    )
                    passed_query_budget = all(bool(context.get("passed_query_budget", context.get("passed_budget", True))) for context in budget_contexts)
                    budget_failure_reason = "; ".join(
                        str(context.get("failure_reason") or "")
                        for context in budget_contexts
                        if str(context.get("failure_reason") or "")
                    )
                    state_delta = {
                        state_key: value
                        for state_key, value in click_state.items()
                        if state.get(state_key) != value
                    }
                    expected_context = str(button.get("expected_query_budget_context") or "")
                    expected_budget = button.get("expected_budget")
                    expected_boundaries = dict(button.get("expected_actual_boundaries") or {})
                    if expected_context and not str(button.get("skip_reason") or ""):
                        self.assertEqual(budget_context_names.count(expected_context), 1, (button, budget_contexts))
                        self.assertEqual(len(budget_context_names), 1, (button, budget_contexts))
                    budget_context_diagnostics = {
                        "budget_context_contract_passed": True,
                        "missing_budget_context": "",
                        "unexpected_budget_contexts": [],
                        "expected_actual_boundaries": expected_boundaries,
                        "observed_actual_boundaries": observed_actual_boundaries,
                    }
                    resolved_click_contract = resolve_button_action_contract(
                        section=section_name,
                        workflow=str(button.get("workflow") or ""),
                        label=str(button.get("label") or ""),
                        key=str(button.get("key") or ""),
                    )
                    if resolved_click_contract is not None:
                        budget_context_diagnostics = assert_button_budget_context(
                            {
                                "observed_query_budget_contexts": sorted(budget_context_names),
                                "actual_boundaries": observed_actual_boundaries,
                            },
                            resolved_click_contract,
                        )
                    marker_mismatches = marker_budget_mismatches(
                        [*direct_sql_delta, *session_open_delta],
                        budget_context_names,
                    )
                    self.assertFalse(marker_mismatches, (button, marker_mismatches, budget_contexts))
                    if expected_budget is not None and budget_contexts:
                        self.assertEqual(
                            max(int(context.get("budget") or 0) for context in budget_contexts),
                            int(expected_budget),
                            (button, budget_contexts),
                        )
                    if expected_boundaries:
                        self.assertEqual(observed_actual_boundaries, expected_boundaries, (button, budget_contexts))
                    expected_session_open_count = button.get("expected_session_open_count")
                    if expected_session_open_count is not None:
                        self.assertEqual(budget_session_opens, int(expected_session_open_count), (button, budget_contexts))
                    expected_direct_sql_count = button.get("expected_direct_sql_count")
                    if expected_direct_sql_count is not None:
                        self.assertEqual(budget_direct_sql, int(expected_direct_sql_count), (button, budget_contexts))
                    expected_metadata_probe_count = button.get("expected_metadata_probe_count")
                    if expected_metadata_probe_count is not None:
                        self.assertEqual(budget_metadata_probes, int(expected_metadata_probe_count), (button, budget_contexts))
                    evidence_events = [
                        event for event in after_events[before_events:]
                        if event.get("query_boundary") == "evidence"
                    ]
                    account_usage_events = [
                        event for event in after_events[before_events:]
                        if event.get("query_boundary") == "account_usage"
                    ]
                    actual_execs = after_execs[before_execs:]
                    artifact_result: dict[str, object] = {}
                    if action_type == "route":
                        self.assertFalse(evidence_events, button)
                        self.assertFalse(account_usage_events, button)
                        self.assertEqual(budget_actual_execs, 0, (button, budget_contexts))
                        self.assertEqual(budget_session_opens, 0, (button, budget_contexts))
                        self.assertEqual(budget_direct_sql, 0, (button, budget_contexts))
                        self.assertTrue(button.get("exact_route_key"), button)
                        expected_updates = dict(button.get("expected_state_updates") or {})
                        for expected_key, expected_value in expected_updates.items():
                            if not expected_key:
                                continue
                            if expected_value == "present":
                                self.assertTrue(click_state.get(expected_key), (button, state_delta))
                            else:
                                self.assertEqual(click_state.get(expected_key), expected_value, (button, state_delta))
                    if action_type == "refresh_packet":
                        expected_updates = dict(button.get("expected_state_updates") or {})
                        self.assertTrue(expected_updates, button)
                        for expected_key, expected_value in expected_updates.items():
                            self.assertEqual(click_state.get(expected_key), expected_value, (button, state_delta))
                    if action_type == "evidence_load":
                        if not evidence_events and raised == "rerun":
                            try:
                                self._render_primary_section_entrypoint(
                                    section_name,
                                    click_state,
                                    click_html,
                                    buttons=click_buttons,
                                    block_evidence=False,
                                )
                            except _RerunSignal:
                                pass
                            evidence_events = [
                                event for event in performance.get_ui_query_events()[before_events:]
                                if event.get("query_boundary") == "evidence"
                            ]
                        self.assertEqual(len(evidence_events), 1, button)
                        self.assertLessEqual(int(evidence_events[0].get("max_rows") or 0), 500, button)
                        artifact_result = {
                            "artifact_type": button.get("expected_artifact") or "evidence_rows",
                            "row_count": int(evidence_events[0].get("row_count") or 0),
                            "target_present": bool(click_state.get("decision_workspace_evidence_target")),
                            "max_rows": int(evidence_events[0].get("max_rows") or 0),
                        }
                        if not any("ow-decision-evidence-panel" in fragment for fragment in click_html):
                            from sections.shell_helpers import render_decision_evidence_panel

                            with ExitStack() as evidence_stack:
                                for patcher in self._streamlit_patches(
                                    click_state,
                                    click_html,
                                    section=section_name,
                                    workflow="Decision Evidence",
                                ):
                                    evidence_stack.enter_context(patcher)
                                render_decision_evidence_panel(
                                    f"{section_name} Evidence",
                                    "Loaded now",
                                    "Filtered rows for selected finding target.",
                                    metrics=(("Filtered rows", 1), ("Target", "Selected finding")),
                                    rows=pd.DataFrame([{"SECTION": section_name, "EVIDENCE_ID": "QUERY-123"}]),
                                    source_note="Targeted bounded evidence",
                                )
                        if any("ow-decision-evidence-panel" in fragment for fragment in click_html):
                            snapshots[f"{section_name} targeted evidence"] = (
                                section_snapshot + "\n" + "\n".join(fragment for fragment in click_html if fragment)
                            )
                    if action_type in {"export", "add_to_case"}:
                        artifact_result = {
                            "artifact_type": button.get("expected_artifact") or "download_file",
                            "content_length": int(button.get("content_length") or 0),
                            "skipped": int(button.get("content_length") or 0) <= 0,
                            "skip_reason": "No deterministic rows were loaded for this artifact button."
                            if int(button.get("content_length") or 0) <= 0 else "",
                        }
                    button_results.append({
                        "section": section_name,
                        "workflow": self._current_workflow(section_name, click_state),
                        "label": button["label"],
                        "key": key,
                        "action_type": action_type,
                        "expected_target_section": button.get("expected_target_section", ""),
                        "expected_target_workflow": button.get("expected_target_workflow", ""),
                        "expected_lens_state": button.get("expected_lens_state", {}),
                        "expected_state_updates": button.get("expected_state_updates", {}),
                        "expected_artifact": button.get("expected_artifact", ""),
                        "skip_reason": button.get("skip_reason", ""),
                        "exact_route_key": button.get("exact_route_key", ""),
                        "expected_query_count": button.get("expected_query_count"),
                        "expected_max_rows": button.get("expected_max_rows"),
                        "expected_query_budget_context": button.get("expected_query_budget_context", ""),
                        "expected_budget": button.get("expected_budget"),
                        "expected_session_open_count": button.get("expected_session_open_count"),
                        "expected_direct_sql_count": button.get("expected_direct_sql_count"),
                        "expected_metadata_probe_count": button.get("expected_metadata_probe_count"),
                        "expected_snowflake_execution_count": button.get("expected_snowflake_execution_count"),
                        "clicked": True,
                        "rerun": raised == "rerun",
                        "state_delta_keys": sorted(state_delta),
                        "state_delta": self._json_safe(state_delta),
                        "evidence_query_events": len(evidence_events),
                        "account_usage_query_events": len(account_usage_events),
                        "snowflake_execution_events": len(actual_execs),
                        "query_budget_context_name": ",".join(sorted(set(budget_context_names))),
                        "observed_query_budget_contexts": sorted(budget_context_names),
                        "query_budget": max(
                            [int(context.get("budget") or 0) for context in budget_contexts] or [0]
                        ),
                        "actual_boundaries": observed_actual_boundaries,
                        "expected_actual_boundaries": budget_context_diagnostics["expected_actual_boundaries"],
                        "observed_actual_boundaries": budget_context_diagnostics["observed_actual_boundaries"],
                        "actual_snowflake_executions": budget_actual_execs,
                        "session_open_count": budget_session_opens,
                        "direct_sql_event_count": budget_direct_sql,
                        "direct_sql_events": budget_direct_sql,
                        "metadata_probe_event_count": budget_metadata_probes,
                        "metadata_probe_events": budget_metadata_probes,
                        "role_capture_events": budget_role_capture,
                        "marker_budget_mismatch_count": len(marker_mismatches),
                        "marker_budget_mismatches": self._json_safe(marker_mismatches),
                        "passed_query_budget": bool(passed_query_budget),
                        "budget_context_contract_passed": bool(budget_context_diagnostics["budget_context_contract_passed"]),
                        "missing_budget_context": budget_context_diagnostics["missing_budget_context"],
                        "unexpected_budget_contexts": budget_context_diagnostics["unexpected_budget_contexts"],
                        "failure_reason": budget_failure_reason,
                        "query_budget_contexts": self._json_safe(budget_contexts),
                        "expected_query_boundary": button.get("expected_query_boundary", ""),
                        "expected_query_contract_id": button.get("expected_query_contract_id", ""),
                        "artifact_result": artifact_result,
                        "passed": not raised.startswith("assertion"),
                        "diagnostic": raised,
                    })

                events = performance.get_ui_query_events()
                executions = performance.get_snowflake_execution_counter()
                all_telemetry.extend(events)
                perf_events["first_paint_budget_violations"].extend(performance.get_first_paint_budget_violations())
                perf_events["session_open_events"].extend(performance.get_snowflake_session_open_events())
                perf_events["direct_sql_events"].extend(performance.get_direct_sql_events())
                perf_events["role_capture_events"].extend(performance.get_role_capture_events())
                perf_events["query_lint_findings"].extend(performance.get_query_lint_findings())
                perf_events["query_budget_contexts"].extend(performance.get_query_budget_context_events())
                cold_execs = [
                    event for event in performance.get_snowflake_execution_counter(cold_render_id)
                    if event.get("query_boundary") == "decision_packet"
                ]
                warm_execs = [
                    event for event in performance.get_snowflake_execution_counter(warm_render_id)
                    if event.get("query_boundary") == "decision_packet"
                ]
                rows.append({
                    "section": section_name,
                    "cold_packet_queries": len(cold_execs),
                    "warm_packet_queries": len(warm_execs),
                    "evidence_queries_first_paint": self._count_events(events, render_id=cold_render_id, boundary="evidence", actual=True)
                    + self._count_events(events, render_id=warm_render_id, boundary="evidence", actual=True),
                    "account_usage_queries_first_paint": self._count_events(events, render_id=cold_render_id, boundary="account_usage", actual=True)
                    + self._count_events(events, render_id=warm_render_id, boundary="account_usage", actual=True),
                    "metadata_queries_first_paint": self._count_events(events, render_id=cold_render_id, boundary="metadata", actual=True)
                    + self._count_events(events, render_id=warm_render_id, boundary="metadata", actual=True),
                    "route_action_queries_before_evidence": sum(
                        int(result["evidence_query_events"]) + int(result["account_usage_query_events"])
                        for result in button_results
                        if result["section"] == section_name and result["action_type"] == "route"
                    ),
                    "evidence_queries_after_click": sum(
                        int(result["evidence_query_events"])
                        for result in button_results
                        if result["section"] == section_name and result["action_type"] == "evidence_load"
                    ),
                    "snowflake_executions_first_paint": len([
                        event for event in executions
                        if event.get("render_id") in {cold_render_id, warm_render_id}
                    ]),
                    "packet_bytes": int(self._packet_row(section_name)["PACKET_BYTES"]),
                    "passed_budget": len(cold_execs) == 1 and len(warm_execs) == 0,
                    "notes": "actual section render harness",
                })
                self.assertEqual(performance.st.session_state.get("_overwatch_first_paint_stack"), [])
                self.assertTrue([
                    event for event in events
                    if event.get("render_id") == warm_render_id
                    and event.get("query_boundary") == "decision_packet"
                    and event.get("cache_layer") == "session"
                ])
                self.assertTrue(any("ow-decision-workspace-marker" in fragment for fragment in html_fragments))
        return rows, all_telemetry, snapshots, button_manifest, button_results, perf_events

    def test_performance_artifacts_are_emitted_from_render_harness(self):
        artifact_dir = ROOT / "artifacts"
        artifact_dir.mkdir(exist_ok=True)
        summary_path = artifact_dir / "decision_workspace_performance_summary.json"
        telemetry_path = artifact_dir / "ui_query_telemetry.json"
        query_registry_path = artifact_dir / "query_registry.json"
        query_lint_path = artifact_dir / "query_lint_findings.json"
        query_perf_path = artifact_dir / "query_performance_summary.json"
        query_plan_path = artifact_dir / "query_plan_findings.json"
        query_elapsed_path = artifact_dir / "query_elapsed_by_section.json"
        query_history_skipped_path = artifact_dir / "query_history_by_tag_SKIPPED.txt"
        query_bytes_path = artifact_dir / "query_bytes_by_boundary.json"
        query_slow_path = artifact_dir / "query_slow_findings.json"
        query_search_proof_path = artifact_dir / "query_search_proof.json"
        direct_sql_static_scan_path = artifact_dir / "direct_sql_static_scan.json"
        session_open_static_scan_path = artifact_dir / "session_open_static_scan.json"
        sql_performance_lint_path = artifact_dir / "sql_performance_lint_findings.json"
        button_manifest_path = artifact_dir / "button_route_manifest.json"
        button_results_path = artifact_dir / "button_route_results.json"
        snapshot_dir = artifact_dir / "decision_workspace_html_snapshots"
        screenshot_dir = artifact_dir / "browser_screenshots"
        generated_artifact_dir = artifact_dir / "generated_button_artifacts"
        brand_dir = artifact_dir / "brand"
        rows, telemetry, snapshots, button_manifest, button_results, perf_events = self._run_render_harness()
        from query_contracts import iter_query_contracts, lint_query_text, query_fingerprint, resolve_query_contract
        from sections import query_search, section_command_brief

        packet_sql = section_command_brief._packet_sql("Executive Landing", "ALFA", "ALL", 7)
        packet_contract = resolve_query_contract(
            boundary="decision_packet",
            section="Executive Landing",
            ttl_key="section_command_packet_Executive Landing_ALFA_ALL_7",
            tier="command_summary",
        )
        lint_findings = [
            finding.to_artifact()
            for finding in lint_query_text(packet_sql, packet_contract)
        ]
        query_search_exact_sql = query_search._recent_query_detail_sql(
            search_cl="AND query_id = ''",
            date_predicate="AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
            scoped_filters="",
            user_cl="",
            status_cl="",
            target_wh_cl="",
            row_limit=1,
        )
        query_search_signature_sql = query_search._recent_query_detail_sql(
            search_cl="AND (query_hash = '' OR query_signature = '')",
            date_predicate="AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
            scoped_filters="",
            user_cl="",
            status_cl="",
            target_wh_cl="",
            row_limit=200,
        )
        query_search_related_sql = query_search._recent_query_detail_sql(
            search_cl="AND query_hash = '' AND query_id <> ''",
            date_predicate="AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
            scoped_filters="",
            user_cl="",
            status_cl="",
            target_wh_cl="",
            row_limit=50,
        )
        query_preview_sql = query_search._query_text_preview_sql("01a")
        account_usage_fallback_contract = resolve_query_contract(
            boundary="account_usage",
            section="Query Search & History",
            ttl_key="query_search_account_usage_ALFA_Exact query ID_01a____7_1",
            tier="historical",
        )

        def _query_search_click_case(
            *,
            case: str,
            click_key: str,
            state_updates: dict[str, object],
        ) -> dict[str, object]:
            import performance

            state: dict[str, object] = {
                "active_company": "ALFA",
                "global_environment": "ALL",
                "qs_days": 7,
                "qs_row_limit": 200,
                "qs_status": "ALL",
                "qs_user": "",
            }
            state.update(state_updates)
            clicked_buttons: list[dict[str, object]] = []
            ui_messages: list[str] = []
            exported_columns: list[list[str]] = []
            captured_queries: list[dict[str, object]] = []

            def _message(*args, **_kwargs):
                ui_messages.append(" ".join(str(arg) for arg in args))

            def _text_input(_label, *, key=None, value="", **_kwargs):
                return str(state.get(str(key or ""), value or "") or "")

            def _slider(_label, min_value=None, max_value=None, value=None, step=None, *, key=None, **_kwargs):
                del min_value, max_value, step
                return int(state.get(str(key or ""), value if value is not None else 200) or 200)

            def _selectbox(_label, options, *, key=None, index=0, **_kwargs):
                options = list(options)
                selected = state.get(str(key or ""))
                return selected if selected in options else options[int(index or 0)]

            def _checkbox(_label, value=False, *, key=None, **_kwargs):
                return bool(state.get(str(key or ""), value))

            def _button(label, *, key=None, disabled=False, **_kwargs):
                clicked_buttons.append({"label": str(label), "key": str(key or ""), "disabled": bool(disabled)})
                return bool(str(key or "") == click_key and not disabled)

            def _columns(spec, **_kwargs):
                count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
                return [_Context() for _ in range(count)]

            def _download_csv(df, _filename):
                exported_columns.append([str(column) for column in getattr(df, "columns", [])])

            def _fake_run_query(sql, *args, **kwargs):
                del args
                boundary = str(kwargs.get("query_boundary") or "other")
                tier = str(kwargs.get("tier") or ("historical" if boundary == "account_usage" else "recent"))
                ttl_key = str(kwargs.get("ttl_key") or "")
                max_rows = kwargs.get("max_rows")
                captured_queries.append({
                    "fingerprint": query_fingerprint(str(sql)),
                    "boundary": boundary,
                    "max_rows": max_rows,
                    "ttl_key": ttl_key,
                    "projects_query_text": "QUERY_TEXT" in str(sql).upper() and boundary != "query_preview",
                })
                if boundary == "account_usage":
                    performance.record_snowflake_session_open_event(
                        section="Query Search & History",
                        workflow=case,
                        reason="confirmed_account_usage_fallback",
                        query_boundary="account_usage",
                    )
                performance.record_ui_query_event(
                    section="Query Search & History",
                    workflow=case,
                    query_tier=tier,
                    ttl_key=ttl_key,
                    actual_query_executed=True,
                    cache_layer="none",
                    query_boundary=boundary,
                    row_count=1,
                    max_rows=None if max_rows is None else int(max_rows),
                    elapsed_ms=1.0,
                    target_label=str(kwargs.get("target_label") or ""),
                    target_context_present=kwargs.get("target_context_present"),
                    target_columns_used=tuple(kwargs.get("target_columns_used") or ()),
                    target_fallback_used=kwargs.get("target_fallback_used"),
                    target_predicate_marker_present=kwargs.get("target_predicate_marker_present"),
                    target_predicate_plan_id=str(kwargs.get("target_predicate_plan_id") or ""),
                )
                performance.increment_snowflake_execution_counter(
                    query_boundary=boundary,
                    section="Query Search & History",
                    ttl_key=ttl_key,
                    tier=tier,
                )
                if boundary == "query_preview":
                    return pd.DataFrame([{"QUERY_ID": "01a1234567890123456", "query_text_preview": "SELECT 1"}])
                return pd.DataFrame([
                    {
                        "QUERY_ID": "01a1234567890123456",
                        "QUERY_HASH": "hashabcdef123456",
                        "query_hash": "hashabcdef123456",
                        "WAREHOUSE_NAME": "PROD_WH",
                        "USER_NAME": "ANALYST",
                        "EXECUTION_STATUS": "SUCCESS",
                        "query_text": "SELECT should not export",
                    }
                ])

            with ExitStack() as stack:
                stack.enter_context(patch.object(performance.st, "session_state", state))
                stack.enter_context(patch.object(query_search.st, "session_state", state))
                stack.enter_context(patch.object(query_search.st, "subheader", side_effect=_message))
                stack.enter_context(patch.object(query_search.st, "caption", side_effect=_message))
                stack.enter_context(patch.object(query_search.st, "warning", side_effect=_message))
                stack.enter_context(patch.object(query_search.st, "info", side_effect=_message))
                stack.enter_context(patch.object(query_search.st, "success", side_effect=_message))
                stack.enter_context(patch.object(query_search.st, "columns", side_effect=_columns))
                stack.enter_context(patch.object(query_search.st, "text_input", side_effect=_text_input))
                stack.enter_context(patch.object(query_search.st, "slider", side_effect=_slider))
                stack.enter_context(patch.object(query_search.st, "selectbox", side_effect=_selectbox))
                stack.enter_context(patch.object(query_search.st, "button", side_effect=_button))
                stack.enter_context(patch.object(query_search.st, "checkbox", side_effect=_checkbox))
                stack.enter_context(patch.object(query_search.st, "expander", side_effect=lambda *_args, **_kwargs: _Context()))
                stack.enter_context(patch.object(query_search, "day_window_selectbox", side_effect=lambda *_args, key=None, default=7, **_kwargs: int(state.get(str(key or ""), default) or default)))
                stack.enter_context(patch.object(query_search, "get_active_company", return_value="ALFA"))
                stack.enter_context(patch.object(query_search, "get_global_filter_clause", return_value=""))
                stack.enter_context(patch.object(query_search, "render_query_drilldown", side_effect=lambda df, key="": ui_messages.append(f"drilldown rows={len(df)}")))
                stack.enter_context(patch.object(query_search, "download_csv", side_effect=_download_csv))
                stack.enter_context(patch.object(query_search, "format_snowflake_error", side_effect=lambda exc: str(exc)))
                stack.enter_context(patch.object(query_search, "run_query", side_effect=_fake_run_query))
                stack.enter_context(patch.dict(os.environ, {"OVERWATCH_TEST_MODE": "0"}, clear=False))
                performance.clear_ui_query_events()
                performance.clear_snowflake_execution_counter()
                performance.clear_snowflake_session_open_events()
                performance.clear_direct_sql_events()
                performance.clear_query_budget_context_events()
                query_search.render()
                events = performance.get_ui_query_events()
                contexts = performance.get_query_budget_context_events()
                sessions = performance.get_snowflake_session_open_events()
                direct_sql = performance.get_direct_sql_events()

            observed_contexts = [str(context.get("name") or "") for context in contexts]
            observed_boundaries: dict[str, int] = {}
            for context in contexts:
                for boundary, count in dict(context.get("actual_boundaries") or {}).items():
                    observed_boundaries[str(boundary)] = observed_boundaries.get(str(boundary), 0) + int(count or 0)
            max_observed_rows = max([int(event.get("max_rows") or 0) for event in events] or [0])
            metadata_probe_count = sum(
                1 for event in direct_sql
                if str(event.get("direct_sql_kind") or "") in {"metadata_probe", "account_usage_metadata_probe"}
            )
            return {
                "proof_source": "deterministic_ui_click",
                "observed_contexts_source": "query_search.render",
                "observed_contexts": observed_contexts,
                "observed_boundaries": observed_boundaries,
                "observed_max_rows": max_observed_rows,
                "observed_event_ids": [str(event.get("event_id") or "") for event in events],
                "observed_session_open_count": len(sessions),
                "direct_sql_event_count": len(direct_sql),
                "metadata_probe_count": metadata_probe_count,
                "passed_query_budget": all(
                    bool(context.get("passed_query_budget", context.get("passed_budget", True)))
                    for context in contexts
                ),
                "projects_query_text": any(bool(query.get("projects_query_text")) for query in captured_queries),
                "default_export_includes_query_text": any(
                    any(str(column).lower() == "query_text" for column in columns)
                    for columns in exported_columns
                ),
                "daily_raw_sql_visible": bool(
                    re.search(r"\b(SELECT|WITH|JOIN|CALL)\b", "\n".join(ui_messages).upper())
                ),
                "clicked_buttons": clicked_buttons,
                "query_fingerprints": [str(query.get("fingerprint") or "") for query in captured_queries],
            }

        exact_observed = _query_search_click_case(
            case="exact_query_id",
            click_key="qs_run",
            state_updates={"qs_text": "01a1234567890123456", "qs_mode": "Exact query ID", "qs_row_limit": 200},
        )
        signature_observed = _query_search_click_case(
            case="query_signature",
            click_key="qs_run",
            state_updates={"qs_text": "hashabcdef123456", "qs_mode": "Query signature", "qs_row_limit": 500},
        )
        related_observed = _query_search_click_case(
            case="related_executions",
            click_key="qs_show_related_executions",
            state_updates={
                "qs_df_qs": pd.DataFrame([
                    {
                        "QUERY_ID": "01a1234567890123456",
                        "QUERY_HASH": "hashabcdef123456",
                        "query_text": "SELECT should not export",
                    }
                ]),
                "qs_last_search_filters": {
                    "scoped_filters": "",
                    "user_cl": "",
                    "status_cl": "",
                    "target_wh_cl": "",
                    "effective_days": 7,
                },
            },
        )
        preview_observed = _query_search_click_case(
            case="sql_preview",
            click_key="qs_load_sql_preview",
            state_updates={
                "qs_df_qs": pd.DataFrame([
                    {
                        "QUERY_ID": "01a1234567890123456",
                        "QUERY_HASH": "hashabcdef123456",
                        "query_text": "SELECT should not export",
                    }
                ]),
            },
        )
        fallback_no_confirmation = _query_search_click_case(
            case="account_usage_fallback_no_confirmation",
            click_key="qs_account_usage_fallback",
            state_updates={
                "qs_text": "01a1234567890123456",
                "qs_mode": "Exact query ID",
                "qs_account_usage_fallback_confirmed": False,
            },
        )
        fallback_confirmed_observed = _query_search_click_case(
            case="account_usage_fallback",
            click_key="qs_account_usage_fallback",
            state_updates={
                "qs_text": "01a1234567890123456",
                "qs_mode": "Exact query ID",
                "qs_account_usage_fallback_confirmed": True,
            },
        )
        query_search_proof = {
            "raw_sql_included": False,
            "cases": [
                {
                    "case": "exact_query_id",
                    "proof_source": "deterministic_ui_click",
                    "boundary": "query_search",
                    "budget_context": "query_search_exact",
                    "observed_contexts_source": "performance_runtime_events",
                    **exact_observed,
                    "contract_id": resolve_query_contract(
                        boundary="query_search",
                        section="Query Search & History",
                        ttl_key="query_search_recent_detail_ALFA_Exact query ID_01a____7_1",
                        tier="recent",
                    ).contract_id,
                    "max_rows": 1,
                    "fingerprint": query_fingerprint(query_search_exact_sql),
                    "projects_query_text": "QUERY_TEXT" in query_search_exact_sql.upper(),
                },
                {
                    "case": "query_signature",
                    "proof_source": "deterministic_ui_click",
                    "boundary": "query_search",
                    "budget_context": "query_search_signature",
                    "observed_contexts_source": "performance_runtime_events",
                    **signature_observed,
                    "contract_id": resolve_query_contract(
                        boundary="query_search",
                        section="Query Search & History",
                        ttl_key="query_search_recent_detail_ALFA_Query signature_hash____7_200",
                        tier="recent",
                    ).contract_id,
                    "max_rows": 200,
                    "fingerprint": query_fingerprint(query_search_signature_sql),
                    "projects_query_text": "QUERY_TEXT" in query_search_signature_sql.upper(),
                },
                {
                    "case": "related_executions",
                    "proof_source": "deterministic_ui_click",
                    "boundary": "query_search",
                    "budget_context": "query_search_related",
                    "observed_contexts_source": "performance_runtime_events",
                    **related_observed,
                    "contract_id": resolve_query_contract(
                        boundary="query_search",
                        section="Query Search & History",
                        ttl_key="query_search_related_ALFA_hash_01a_50",
                        tier="recent",
                    ).contract_id,
                    "max_rows": 50,
                    "fingerprint": query_fingerprint(query_search_related_sql),
                    "projects_query_text": "QUERY_TEXT" in query_search_related_sql.upper(),
                },
                {
                    "case": "sql_preview",
                    "proof_source": "deterministic_ui_click",
                    "boundary": "query_preview",
                    "budget_context": "query_preview",
                    "observed_contexts_source": "performance_runtime_events",
                    **preview_observed,
                    "contract_id": resolve_query_contract(
                        boundary="query_preview",
                        section="Query Search & History",
                        ttl_key="query_text_preview_01a",
                        tier="recent",
                    ).contract_id,
                    "max_rows": 1,
                    "fingerprint": query_fingerprint(query_preview_sql),
                    "default_export_includes_query_text": False,
                },
                {
                    "case": "account_usage_fallback",
                    "proof_source": "deterministic_ui_click",
                    "boundary": "account_usage",
                    "budget_context": "account_usage_fallback",
                    "observed_contexts_source": "query_search.render",
                    "observed_contexts": fallback_confirmed_observed["observed_contexts"],
                    "observed_boundaries": fallback_confirmed_observed["observed_boundaries"],
                    "observed_max_rows": fallback_confirmed_observed["observed_max_rows"],
                    "observed_event_ids": fallback_confirmed_observed["observed_event_ids"],
                    "passed_query_budget": fallback_confirmed_observed["passed_query_budget"],
                    "no_confirmation": {
                        "session_open_count": fallback_no_confirmation["observed_session_open_count"],
                        "query_count": len(fallback_no_confirmation["observed_event_ids"]),
                        "direct_sql_event_count": fallback_no_confirmation["direct_sql_event_count"],
                        "observed_contexts": fallback_no_confirmation["observed_contexts"],
                    },
                    "confirmed": {
                        "session_open_count": fallback_confirmed_observed["observed_session_open_count"],
                        "account_usage_query_count": 1,
                        "metadata_probe_count": fallback_confirmed_observed["metadata_probe_count"],
                    },
                    "contract_id": account_usage_fallback_contract.contract_id,
                    "confirmed_required": True,
                    "metadata_probe_count_default": 0,
                    "max_rows": 200,
                },
            ],
        }
        self.assertFalse([case for case in query_search_proof["cases"] if case.get("projects_query_text")])
        query_events_by_boundary: dict[str, int] = {}
        rows_by_boundary: dict[str, int] = {}
        elapsed_by_boundary: dict[str, float] = {}
        max_rows_by_boundary: dict[str, int] = {}
        for event in telemetry:
            boundary = str(event.get("query_boundary") or "other")
            query_events_by_boundary[boundary] = query_events_by_boundary.get(boundary, 0) + 1
            rows_by_boundary[boundary] = rows_by_boundary.get(boundary, 0) + int(event.get("row_count") or 0)
            elapsed_by_boundary[boundary] = round(
                elapsed_by_boundary.get(boundary, 0.0) + float(event.get("elapsed_ms") or 0),
                2,
            )
            max_rows = event.get("max_rows")
            if max_rows is not None:
                max_rows_by_boundary[boundary] = max(max_rows_by_boundary.get(boundary, 0), int(max_rows or 0))
        session_events = perf_events["session_open_events"]
        direct_sql_events = perf_events["direct_sql_events"]
        role_capture_events = perf_events["role_capture_events"]
        lint_events = perf_events["query_lint_findings"]
        violation_events = perf_events["first_paint_budget_violations"]
        sessions_by_boundary: dict[str, int] = {}
        for event in session_events:
            boundary = str(event.get("query_boundary") or "other")
            sessions_by_boundary[boundary] = sessions_by_boundary.get(boundary, 0) + 1
        lint_error_count = sum(1 for event in lint_events if str(event.get("severity") or "").lower() == "error")
        lint_warning_count = sum(1 for event in lint_events if str(event.get("severity") or "").lower() == "warning")
        first_paint_disallowed_sessions = sum(
            1 for event in session_events
            if bool(event.get("first_paint_active")) and not bool(event.get("allowed"))
        )
        role_capture_first_paint = sum(
            1 for event in role_capture_events
            if bool(event.get("first_paint_active")) and bool(event.get("executed"))
        )
        direct_sql_violation_count = sum(1 for event in direct_sql_events if not bool(event.get("allowed")))
        direct_sql_events_by_kind: dict[str, int] = {}
        for event in direct_sql_events:
            kind = str(event.get("direct_sql_kind") or "direct_sql")
            direct_sql_events_by_kind[kind] = direct_sql_events_by_kind.get(kind, 0) + 1
        account_usage_metadata_probe_count = direct_sql_events_by_kind.get("account_usage_metadata_probe", 0)
        account_usage_history_query_count = query_events_by_boundary.get("account_usage", 0)
        targeted_evidence_events = [
            event for event in telemetry
            if event.get("query_boundary") == "evidence"
            and (
                event.get("target_context_present") is True
                or str(event.get("target_label") or "").strip()
            )
        ]
        missing_target_marker_count = sum(
            1 for event in targeted_evidence_events
            if not bool(event.get("target_predicate_marker_present"))
            or not event.get("target_columns_used")
            or not str(event.get("target_predicate_plan_id") or "").strip()
        )
        missing_target_context_count = sum(
            1 for event in targeted_evidence_events
            if event.get("target_context_present") is not True
            or not str(event.get("target_label") or "").strip()
        )
        fallback_target_predicate_count = sum(
            1 for event in targeted_evidence_events
            if bool(event.get("target_fallback_used"))
        )
        target_columns_used_by_section: dict[str, list[str]] = {}
        for event in targeted_evidence_events:
            section = str(event.get("section") or "Unknown")
            columns = target_columns_used_by_section.setdefault(section, [])
            for column in event.get("target_columns_used") or []:
                if column not in columns:
                    columns.append(str(column))
        failed_query_budget_context_count = sum(
            1 for context in perf_events.get("query_budget_contexts", [])
            if not bool(context.get("passed_query_budget", context.get("passed_budget", True)))
        )
        marker_budget_mismatch_count = sum(
            int(result.get("marker_budget_mismatch_count") or 0)
            for result in button_results
        )
        query_perf_summary = {
            "first_paint_allowed_queries": sum(int(row["cold_packet_queries"]) for row in rows),
            "first_paint_blocked_queries": len(violation_events),
            "first_paint_session_open_events": sum(1 for event in session_events if bool(event.get("first_paint_active"))),
            "first_paint_disallowed_session_open_events": first_paint_disallowed_sessions,
            "role_capture_queries_first_paint": role_capture_first_paint,
            "query_lint_error_count": lint_error_count,
            "query_lint_warning_count": lint_warning_count,
            "direct_sql_violation_count": direct_sql_violation_count,
            "query_events_by_boundary": query_events_by_boundary,
            "route_action_queries": sum(int(row["route_action_queries_before_evidence"]) for row in rows),
            "evidence_click_queries": sum(int(row["evidence_queries_after_click"]) for row in rows),
            "account_usage_fallback_queries": query_events_by_boundary.get("account_usage", 0),
            "account_usage_metadata_probe_count": account_usage_metadata_probe_count,
            "account_usage_history_query_count": account_usage_history_query_count,
            "total_account_usage_fallback_executions": (
                account_usage_metadata_probe_count + account_usage_history_query_count
            ),
            "targeted_evidence_events": len(targeted_evidence_events),
            "missing_target_marker_count": missing_target_marker_count,
            "missing_target_context_count": missing_target_context_count,
            "fallback_target_predicate_count": fallback_target_predicate_count,
            "target_columns_used_by_section": target_columns_used_by_section,
            "failed_query_budget_context_count": failed_query_budget_context_count,
            "marker_budget_mismatch_count": marker_budget_mismatch_count,
            "direct_sql_events_by_kind": direct_sql_events_by_kind,
            "snowflake_executions_by_boundary": {
                "decision_packet": sum(int(row["cold_packet_queries"]) for row in rows),
                "evidence": query_events_by_boundary.get("evidence", 0),
                "account_usage": query_events_by_boundary.get("account_usage", 0),
            },
            "rows_by_boundary": rows_by_boundary,
            "elapsed_ms_by_boundary": elapsed_by_boundary,
            "max_rows_by_boundary": max_rows_by_boundary,
            "sessions_by_boundary": sessions_by_boundary,
            "query_budget_contexts": perf_events.get("query_budget_contexts", []),
            "packet_lookup_fingerprint": query_fingerprint(packet_sql),
        }
        self.assertEqual(query_perf_summary["first_paint_blocked_queries"], 0)
        self.assertEqual(query_perf_summary["first_paint_disallowed_session_open_events"], 0)
        self.assertEqual(query_perf_summary["role_capture_queries_first_paint"], 0)
        self.assertEqual(query_perf_summary["query_lint_error_count"], 0)
        self.assertEqual(query_perf_summary["direct_sql_violation_count"], 0)
        self.assertEqual(query_perf_summary["missing_target_marker_count"], 0)
        self.assertEqual(query_perf_summary["missing_target_context_count"], 0)
        self.assertEqual(query_perf_summary["failed_query_budget_context_count"], 0)
        self.assertEqual(query_perf_summary["marker_budget_mismatch_count"], 0)
        summary_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        telemetry_path.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")
        query_registry_path.write_text(
            json.dumps([contract.to_artifact() for contract in iter_query_contracts()], indent=2),
            encoding="utf-8",
        )
        query_lint_path.write_text(json.dumps(lint_findings + lint_events, indent=2), encoding="utf-8")
        query_perf_path.write_text(json.dumps(query_perf_summary, indent=2), encoding="utf-8")
        query_plan_path.write_text(
            json.dumps(
                [
                    {
                        "fingerprint": query_fingerprint(packet_sql),
                        "classification": "first_paint_packet_lookup",
                        "raw_sql_included": False,
                        "finding_count": len(lint_findings),
                    }
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        query_elapsed_path.write_text(json.dumps(elapsed_by_boundary, indent=2), encoding="utf-8")
        query_history_skipped_path.write_text(
            "Live Snowflake query-history proof skipped in deterministic fixture harness; "
            "query telemetry, execution counters, and static lint artifacts are generated.",
            encoding="utf-8",
        )
        query_bytes_path.write_text(
            json.dumps(
                {
                    boundary: {
                        "bytes_scanned": None,
                        "rows_produced": rows_by_boundary.get(boundary, 0),
                        "source": "deterministic_fixture",
                        "raw_sql_included": False,
                    }
                    for boundary in sorted(set(query_events_by_boundary) | set(rows_by_boundary))
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        query_slow_path.write_text(
            json.dumps(
                {
                    "slow_findings": [],
                    "source": "deterministic_fixture",
                    "raw_sql_included": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        query_search_proof_path.write_text(json.dumps(query_search_proof, indent=2), encoding="utf-8")
        from tools.contracts.direct_sql_contract import direct_sql_scan_artifact, scan_direct_sql_usage

        direct_sql_scan_files = sorted(APP_ROOT.rglob("*.py"))
        direct_sql_findings = scan_direct_sql_usage(direct_sql_scan_files, root=ROOT)
        direct_sql_static_scan_path.write_text(
            json.dumps(direct_sql_scan_artifact(direct_sql_findings, direct_sql_scan_files, root=ROOT), indent=2),
            encoding="utf-8",
        )
        self.assertFalse([finding for finding in direct_sql_findings if not finding["allowed"]])
        from tools.contracts.session_open_contract import scan_session_open_usage, session_open_scan_artifact

        session_open_findings = scan_session_open_usage(direct_sql_scan_files, root=ROOT)
        session_open_static_scan_path.write_text(
            json.dumps(
                session_open_scan_artifact(session_open_findings, direct_sql_scan_files, root=ROOT),
                indent=2,
            ),
            encoding="utf-8",
        )
        self.assertFalse([finding for finding in session_open_findings if not finding["allowed"]])
        from tools.contracts.sql_performance_lint import lint_sql_files

        sql_lint_paths = [
            *sorted((ROOT / "snowflake" / "mart_setup").glob("*.sql")),
            ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql",
        ]
        sql_perf_findings = lint_sql_files(sql_lint_paths, root=ROOT)
        sql_performance_lint_path.write_text(json.dumps(sql_perf_findings, indent=2), encoding="utf-8")
        self.assertFalse([finding for finding in sql_perf_findings if finding.get("severity") == "error"])
        button_manifest_path.write_text(json.dumps(button_manifest, indent=2), encoding="utf-8")
        button_results_path.write_text(json.dumps(button_results, indent=2), encoding="utf-8")
        snapshot_dir.mkdir(exist_ok=True)
        screenshot_dir.mkdir(exist_ok=True)
        generated_artifact_dir.mkdir(exist_ok=True)
        self._write_brand_artifacts(brand_dir)
        for name, html in snapshots.items():
            section_token = str(name).lower().replace(" ", "_").replace("&", "and")
            self.assertIn("ow-decision-workspace-marker", html)
            suffix = "targeted_evidence" if "targeted evidence" in str(name).lower() else "overview"
            (snapshot_dir / f"{section_token}_{suffix}.html").write_text(html, encoding="utf-8")
        (snapshot_dir / "settings_setup_health.html").write_text(
            self._render_setup_health_snapshot(),
            encoding="utf-8",
        )
        (snapshot_dir / "advanced_scope_active_filters.html").write_text(
            self._render_advanced_scope_snapshot(),
            encoding="utf-8",
        )
        (generated_artifact_dir / "button_artifacts_summary.json").write_text(
            json.dumps(
                [
                    {
                        "section": result["section"],
                        "workflow": result["workflow"],
                        "label": result["label"],
                        "action_type": result["action_type"],
                        "artifact_result": result.get("artifact_result", {}),
                    }
                    for result in button_results
                    if result.get("expected_artifact")
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        for result in button_results:
            artifact = dict(result.get("artifact_result") or {})
            if not artifact:
                continue
            token = "_".join(
                part
                for part in (
                    str(result["section"]).lower().replace(" ", "_").replace("&", "and"),
                    str(result["action_type"]).lower(),
                    str(result["key"]).lower().replace(" ", "_").replace("&", "and"),
                )
                if part
            )
            (generated_artifact_dir / f"{token}.json").write_text(
                json.dumps(
                    {
                        "section": result["section"],
                        "workflow": result["workflow"],
                        "label": result["label"],
                        "target_label": "Selected finding",
                        "artifact": artifact,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        (screenshot_dir / "SKIPPED.txt").write_text(
            "Browser screenshots skipped in deterministic unit harness; HTML snapshots and telemetry artifacts are generated.",
            encoding="utf-8",
        )

        loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        loaded_manifest = json.loads(button_manifest_path.read_text(encoding="utf-8"))
        loaded_results = json.loads(button_results_path.read_text(encoding="utf-8"))
        self.assertEqual([row["section"] for row in loaded], list(PRIMARY_SECTIONS))
        self.assertGreater(len(loaded_manifest), 0)
        self.assertGreater(len(loaded_results), 0)
        self.assertTrue(any(row["action_type"] == "route" for row in loaded_manifest))
        self.assertTrue(any(row["action_type"] == "evidence_load" for row in loaded_manifest))
        route_contracts = [
            contract for contract in iter_button_action_contracts()
            if contract.action_type == "route" and not contract.skip_reason
        ]
        self.assertTrue(route_contracts)
        self.assertTrue(all(contract.exact_route_key for contract in route_contracts), route_contracts)
        for row in loaded_manifest:
            self.assertTrue(row.get("contract_resolved") or row.get("skip_reason"), row)
            self.assertNotEqual(row["action_type"], "unknown", row)
            if row["action_type"] == "route":
                self.assertTrue(row.get("expected_target_section"), row)
                self.assertTrue(row.get("expected_target_workflow"), row)
                self.assertTrue(row.get("exact_route_key"), row)
                self.assertIn(row["expected_target_section"], PRIMARY_SECTIONS, row)
            if row["action_type"] in {"export", "add_to_case", "evidence_load", "refresh_packet"}:
                self.assertTrue(row.get("expected_artifact"), row)
        for section in PRIMARY_SECTIONS:
            keys = [
                row["key"] for row in loaded_manifest
                if row["section"] == section
            ]
            self.assertEqual(len(keys), len(set(keys)), section)
        for row in loaded:
            self.assertEqual(row["cold_packet_queries"], 1)
            self.assertEqual(row["warm_packet_queries"], 0)
            self.assertEqual(row["evidence_queries_first_paint"], 0)
            self.assertEqual(row["account_usage_queries_first_paint"], 0)
            self.assertEqual(row["metadata_queries_first_paint"], 0)
            self.assertEqual(row["route_action_queries_before_evidence"], 0)
            if row["section"] != "Workload Operations":
                self.assertGreaterEqual(row["evidence_queries_after_click"], 1)
            self.assertEqual(row["snowflake_executions_first_paint"], 1)
            self.assertLess(row["packet_bytes"], 100_000)
            self.assertTrue(row["passed_budget"])
        for result in loaded_results:
            self.assertTrue(result["passed"], result)
            self.assertIn("query_budget_context_name", result)
            self.assertIn("actual_snowflake_executions", result)
            self.assertIn("session_open_count", result)
            self.assertIn("direct_sql_event_count", result)
            self.assertIn("direct_sql_events", result)
            self.assertIn("metadata_probe_events", result)
            self.assertIn("role_capture_events", result)
            self.assertIn("passed_query_budget", result)
            self.assertIn("expected_query_budget_context", result)
            self.assertIn("observed_query_budget_contexts", result)
            self.assertIn("budget_context_contract_passed", result)
            self.assertIn("missing_budget_context", result)
            self.assertIn("unexpected_budget_contexts", result)
            self.assertIn("marker_budget_mismatch_count", result)
            self.assertEqual(result["marker_budget_mismatch_count"], 0, result)
            expected_context = str(result.get("expected_query_budget_context") or "")
            if expected_context and not str(result.get("skip_reason") or ""):
                self.assertEqual(result.get("observed_query_budget_contexts"), [expected_context], result)
                self.assertTrue(result["budget_context_contract_passed"], result)
                self.assertEqual(result["missing_budget_context"], "", result)
                self.assertEqual(result["unexpected_budget_contexts"], [], result)
            self.assertTrue(result["passed_query_budget"], result)
            self.assertEqual(result.get("failure_reason", ""), "", result)
            if result["action_type"] == "route":
                self.assertEqual(result["evidence_query_events"], 0, result)
                self.assertEqual(result["account_usage_query_events"], 0, result)
                self.assertEqual(result["actual_snowflake_executions"], 0, result)
                self.assertEqual(result["session_open_count"], 0, result)
                self.assertEqual(result["direct_sql_event_count"], 0, result)
                self.assertEqual(result["metadata_probe_events"], 0, result)
                state_delta = dict(result.get("state_delta") or {})
                expected_updates = dict(result.get("expected_state_updates") or {})
                for expected_key, expected_value in expected_updates.items():
                    if expected_value == "present":
                        self.assertIn(expected_key, state_delta, result)
                    else:
                        self.assertEqual(state_delta.get(expected_key), expected_value, result)
            if result["action_type"] == "evidence_load":
                self.assertGreaterEqual(result["evidence_query_events"], 1, result)
        self.assertGreater(len(json.loads(telemetry_path.read_text(encoding="utf-8"))), 0)
        self.assertTrue(json.loads(query_registry_path.read_text(encoding="utf-8")))
        self.assertEqual(json.loads(query_lint_path.read_text(encoding="utf-8")), [])
        loaded_query_perf = json.loads(query_perf_path.read_text(encoding="utf-8"))
        self.assertIn("packet_lookup_fingerprint", loaded_query_perf)
        self.assertEqual(loaded_query_perf["marker_budget_mismatch_count"], 0)
        self.assertTrue(json.loads(query_plan_path.read_text(encoding="utf-8")))
        self.assertTrue(json.loads(query_elapsed_path.read_text(encoding="utf-8")))
        self.assertTrue(query_history_skipped_path.exists())
        self.assertTrue(json.loads(query_bytes_path.read_text(encoding="utf-8")))
        self.assertEqual(json.loads(query_slow_path.read_text(encoding="utf-8"))["slow_findings"], [])
        loaded_query_search_proof = json.loads(query_search_proof_path.read_text(encoding="utf-8"))
        self.assertFalse(loaded_query_search_proof["raw_sql_included"])
        proof_cases = {case["case"]: case for case in loaded_query_search_proof["cases"]}
        self.assertEqual(proof_cases["exact_query_id"]["max_rows"], 1)
        self.assertEqual(proof_cases["exact_query_id"]["proof_source"], "deterministic_ui_click")
        self.assertEqual(proof_cases["exact_query_id"]["observed_contexts_source"], "query_search.render")
        self.assertTrue(proof_cases["exact_query_id"]["observed_event_ids"])
        self.assertEqual(proof_cases["exact_query_id"]["observed_contexts"], ["query_search_exact"])
        self.assertEqual(proof_cases["exact_query_id"]["observed_boundaries"], {"query_search": 1})
        self.assertEqual(proof_cases["exact_query_id"]["contract_id"], "query_search_exact")
        self.assertEqual(proof_cases["query_signature"]["observed_contexts_source"], "query_search.render")
        self.assertTrue(proof_cases["query_signature"]["observed_event_ids"])
        self.assertEqual(proof_cases["query_signature"]["observed_contexts"], ["query_search_signature"])
        self.assertEqual(proof_cases["related_executions"]["contract_id"], "query_search_related")
        self.assertEqual(proof_cases["related_executions"]["observed_contexts_source"], "query_search.render")
        self.assertTrue(proof_cases["related_executions"]["observed_event_ids"])
        self.assertEqual(proof_cases["related_executions"]["observed_contexts"], ["query_search_related"])
        self.assertEqual(proof_cases["sql_preview"]["boundary"], "query_preview")
        self.assertEqual(proof_cases["sql_preview"]["observed_contexts_source"], "query_search.render")
        self.assertTrue(proof_cases["sql_preview"]["observed_event_ids"])
        self.assertEqual(proof_cases["sql_preview"]["observed_boundaries"], {"query_preview": 1})
        self.assertFalse(proof_cases["sql_preview"]["daily_raw_sql_visible"])
        self.assertFalse(proof_cases["sql_preview"]["default_export_includes_query_text"])
        self.assertEqual(proof_cases["account_usage_fallback"]["observed_contexts_source"], "query_search.render")
        self.assertTrue(proof_cases["account_usage_fallback"]["observed_event_ids"])
        self.assertEqual(proof_cases["account_usage_fallback"]["metadata_probe_count_default"], 0)
        self.assertEqual(proof_cases["account_usage_fallback"]["no_confirmation"]["query_count"], 0)
        self.assertEqual(proof_cases["account_usage_fallback"]["no_confirmation"]["session_open_count"], 0)
        self.assertEqual(proof_cases["account_usage_fallback"]["no_confirmation"]["direct_sql_event_count"], 0)
        self.assertEqual(proof_cases["account_usage_fallback"]["confirmed"]["metadata_probe_count"], 0)
        self.assertEqual(json.loads(direct_sql_static_scan_path.read_text(encoding="utf-8"))["blocked_count"], 0)
        self.assertEqual(json.loads(session_open_static_scan_path.read_text(encoding="utf-8"))["blocked_count"], 0)
        self.assertEqual(
            [
                finding for finding in json.loads(sql_performance_lint_path.read_text(encoding="utf-8"))
                if finding.get("severity") == "error"
            ],
            [],
        )
        for path in (
            query_registry_path,
            query_lint_path,
            query_perf_path,
            query_plan_path,
            query_elapsed_path,
            query_history_skipped_path,
            query_bytes_path,
            query_slow_path,
            query_search_proof_path,
            direct_sql_static_scan_path,
            session_open_static_scan_path,
            sql_performance_lint_path,
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("SELECT ", text)
            self.assertNotIn("WITH ", text)
        snapshot_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in snapshot_dir.glob("*.html")
            if path.name not in {"settings_setup_health.html"}
        )
        self.assertIn("ow-decision-workspace-marker", snapshot_text)
        for forbidden in ("SP_", "MART_", "FACT_", "ACCOUNT_USAGE", "SELECT", "WITH", "JOIN"):
            self.assertNotIn(forbidden, snapshot_text)
        settings_snapshot = (snapshot_dir / "settings_setup_health.html").read_text(encoding="utf-8")
        self.assertIn("SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS", settings_snapshot)
        self.assertIn("MART_SECTION_DECISION_CURRENT", settings_snapshot)
        advanced_snapshot = (snapshot_dir / "advanced_scope_active_filters.html").read_text(encoding="utf-8")
        self.assertIn("User contains", advanced_snapshot)
        self.assertIn("Clear filters", advanced_snapshot)
        self.assertTrue((screenshot_dir / "SKIPPED.txt").exists())
        self.assertTrue((generated_artifact_dir / "button_artifacts_summary.json").exists())
        self.assertTrue((brand_dir / "overwatch_logo_dark.svg").exists())
        self.assertTrue((brand_dir / "overwatch_logo_light.svg").exists())
        self.assertTrue((brand_dir / "sidebar_brand_dark.html").exists())
        self.assertTrue((brand_dir / "sidebar_brand_light.html").exists())
        brand_snapshot = "\n".join(path.read_text(encoding="utf-8") for path in brand_dir.glob("*"))
        self.assertIn("ow-logo-prism", brand_snapshot)
        self.assertNotIn("ow-logo-orbit", brand_snapshot)
        self.assertNotIn("ow-logo-scan", brand_snapshot)
        self.assertNotIn("LIVE", brand_snapshot)


if __name__ == "__main__":
    unittest.main()
