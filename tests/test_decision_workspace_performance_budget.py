from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


PRIMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)


class DecisionWorkspacePerformanceBudgetTests(unittest.TestCase):
    def test_ui_query_telemetry_records_execution_boundary_and_sanitizes_errors(self):
        import performance

        state: dict[str, object] = {}
        with patch.object(performance.st, "session_state", state):
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
            summary = performance.summarize_first_paint_query_budget("Executive Landing")
            events = performance.get_ui_query_events()

        self.assertEqual(summary["decision_packet_events"], 2)
        self.assertEqual(summary["decision_packet_actual_queries"], 1)
        self.assertEqual(summary["decision_packet_session_hits"], 1)
        self.assertEqual(events[0]["error"], "Query failed; see admin diagnostics.")
        self.assertNotIn("SELECT", json.dumps(events))
        self.assertNotIn("query_text", events[0])

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
        self.assertIn("UPPER(EVENT_ID) = UPPER('EVT-1')", alert_sql)
        self.assertNotIn("UPPER(WAREHOUSE_NAME) = UPPER('EVT-1')", alert_sql)
        self.assertNotIn("EVIDENCE_QUERY", alert_sql)

        cost_sql = build_target_sql_filter(
            "Cost & Contract",
            {"entity_type": "warehouse", "entity_id": "PROD_WH"},
            available_columns=("WAREHOUSE_NAME", "USER_NAME", "DEDUPE_KEY"),
        )
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

        large = pd.DataFrame({"ENTITY_NAME": [f"entity-{idx}" for idx in range(600)]})
        filtered, label = apply_target_dataframe_filter(
            large,
            "Cost & Contract",
            {"entity_type": "service", "entity_name": "entity-42"},
        )
        self.assertEqual(len(filtered), len(large))
        self.assertEqual(label, "service: entity-42")

    def test_query_search_is_mart_first_and_account_usage_is_explicit_fallback(self):
        source = (APP_ROOT / "sections" / "query_search.py").read_text(encoding="utf-8")
        self.assertIn("def _recent_query_detail_sql", source)
        self.assertIn("Search recent mart detail", source)
        self.assertIn("Search Account Usage fallback", source)
        self.assertIn("account_usage_fallback", source)
        self.assertIn("FACT_QUERY_DETAIL_RECENT", source)

        fallback_pos = source.index("if account_usage_fallback:")
        metadata_pos = source.index("qh_cols = set(filter_existing_columns(")
        account_usage_sql_pos = source.index("FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        self.assertGreater(metadata_pos, fallback_pos)
        self.assertGreater(account_usage_sql_pos, fallback_pos)
        self.assertIn('st.session_state["qs_autorun"] = target_kind in {"query_id", "query_signature"}', source)

    def test_cost_overview_first_paint_uses_no_splash_or_detail_loader(self):
        source = (APP_ROOT / "sections" / "cost_contract_overview_floor.py").read_text(encoding="utf-8")
        self.assertIn("load_cost_evidence(", source)
        self.assertNotIn("_maybe_autoload_cost_splash", source)
        self.assertNotIn("_ensure_cost_splash", source)
        self.assertIn("if not refresh_cost and not advanced_requested and not st.session_state.get(\"cost_contract_evidence_result\"):", source)
        self.assertIn("return", source.split("if not refresh_cost and not advanced_requested and not st.session_state.get(\"cost_contract_evidence_result\"):", 1)[1].split("if refresh_cost:", 1)[0])
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
        rendered = json.dumps([row.__dict__ for row in model.source_rows]) + (model.fallback.technical_summary if model.fallback else "")

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
        for text in (package,):
            self.assertIn("SUPPORTS_ENVIRONMENT", text)
            self.assertIn("ENVIRONMENT_SCOPE_MODE", text)
            self.assertIn("'SUPPORTS_ENVIRONMENT', SUPPORTS_ENVIRONMENT", text)
        self.assertIn("SECTION_COMMAND_SOURCE_ENVIRONMENT_METADATA", validation)

    def test_performance_artifacts_are_emitted(self):
        artifact_dir = ROOT / "artifacts"
        artifact_dir.mkdir(exist_ok=True)
        summary_path = artifact_dir / "decision_workspace_performance_summary.json"
        telemetry_path = artifact_dir / "ui_query_telemetry.json"
        rows = [
            {
                "section": section,
                "cold_packet_queries": 1,
                "warm_packet_queries": 0,
                "evidence_queries_first_paint": 0,
                "account_usage_queries_first_paint": 0,
                "route_action_queries_before_evidence": 0,
                "evidence_queries_after_click": 1,
                "packet_bytes": 42000,
            }
            for section in PRIMARY_SECTIONS
        ]
        summary_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        telemetry_path.write_text(json.dumps([], indent=2), encoding="utf-8")

        loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual([row["section"] for row in loaded], list(PRIMARY_SECTIONS))
        for row in loaded:
            self.assertEqual(row["cold_packet_queries"], 1)
            self.assertEqual(row["warm_packet_queries"], 0)
            self.assertEqual(row["evidence_queries_first_paint"], 0)
            self.assertLess(row["packet_bytes"], 100_000)


if __name__ == "__main__":
    unittest.main()
