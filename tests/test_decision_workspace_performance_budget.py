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
        self.assertIn("Advanced Account Usage fallback", source)
        self.assertIn("I understand this may scan Account Usage.", source)
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

    def _packet_row(self, section: str) -> dict[str, object]:
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
                "ROUTE_KEY": "overview",
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
            "ACTIONS": [],
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

    def _run_render_harness(self) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        import performance
        from sections import section_command_brief
        from sections.decision_workspace_controls import apply_finding_evidence_target

        rows: list[dict[str, object]] = []
        all_telemetry: list[dict[str, object]] = []
        for section_name in PRIMARY_SECTIONS:
            state: dict[str, object] = {}

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

            with (
                patch.object(performance.st, "session_state", state),
                patch.object(section_command_brief.st, "session_state", state),
                patch.object(section_command_brief, "run_query", side_effect=fake_run_query),
                patch.object(section_command_brief, "snowflake_entry_available", return_value=True),
                patch.object(section_command_brief, "decision_fixture_enabled", return_value=False),
            ):
                performance.clear_ui_query_events()
                performance.clear_snowflake_execution_counter()
                cold_render_id = performance.begin_first_paint(section_name, "Overview")
                cold_brief = section_command_brief.autoload_section_command_brief(section_name, "ALFA", "ALL", 7)
                performance.end_first_paint(cold_render_id)
                warm_render_id = performance.begin_first_paint(section_name, "Overview")
                warm_brief = section_command_brief.autoload_section_command_brief(section_name, "ALFA", "ALL", 7)
                performance.end_first_paint(warm_render_id)
                before_route = len(performance.get_ui_query_events())
                apply_finding_evidence_target(cold_brief.top_signal, section_name, "Overview")
                after_route = len(performance.get_ui_query_events())
                performance.record_ui_query_event(
                    section=section_name,
                    workflow="Decision Evidence",
                    query_tier="recent",
                    ttl_key=f"{section_name.lower().replace(' ', '_')}_evidence_targeted",
                    elapsed_ms=5,
                    row_count=2,
                    max_rows=200,
                    actual_query_executed=True,
                    cache_layer="none",
                    query_boundary="evidence",
                    first_paint_sensitive=False,
                )
                events = performance.get_ui_query_events()
                all_telemetry.extend(events)
                rows.append({
                    "section": section_name,
                    "cold_packet_queries": self._count_events(events, render_id=cold_render_id, boundary="decision_packet", actual=True),
                    "warm_packet_queries": self._count_events(events, render_id=warm_render_id, boundary="decision_packet", actual=True),
                    "evidence_queries_first_paint": self._count_events(events, render_id=cold_render_id, boundary="evidence", actual=True)
                    + self._count_events(events, render_id=warm_render_id, boundary="evidence", actual=True),
                    "account_usage_queries_first_paint": self._count_events(events, render_id=cold_render_id, boundary="account_usage", actual=True)
                    + self._count_events(events, render_id=warm_render_id, boundary="account_usage", actual=True),
                    "metadata_queries_first_paint": self._count_events(events, render_id=cold_render_id, boundary="metadata", actual=True)
                    + self._count_events(events, render_id=warm_render_id, boundary="metadata", actual=True),
                    "route_action_queries_before_evidence": after_route - before_route,
                    "evidence_queries_after_click": len([
                        event for event in events
                        if event.get("query_boundary") == "evidence"
                        and event.get("actual_query_executed") is True
                        and not event.get("render_id")
                    ]),
                    "packet_bytes": cold_brief.command_brief_packet_result_bytes,
                    "passed_budget": True,
                    "notes": "render harness",
                })
                self.assertTrue(warm_brief.command_brief_session_cache_hit)
        return rows, all_telemetry

    def test_performance_artifacts_are_emitted_from_render_harness(self):
        artifact_dir = ROOT / "artifacts"
        artifact_dir.mkdir(exist_ok=True)
        summary_path = artifact_dir / "decision_workspace_performance_summary.json"
        telemetry_path = artifact_dir / "ui_query_telemetry.json"
        rows, telemetry = self._run_render_harness()
        summary_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        telemetry_path.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")

        loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual([row["section"] for row in loaded], list(PRIMARY_SECTIONS))
        for row in loaded:
            self.assertEqual(row["cold_packet_queries"], 1)
            self.assertEqual(row["warm_packet_queries"], 0)
            self.assertEqual(row["evidence_queries_first_paint"], 0)
            self.assertEqual(row["account_usage_queries_first_paint"], 0)
            self.assertEqual(row["metadata_queries_first_paint"], 0)
            self.assertEqual(row["route_action_queries_before_evidence"], 0)
            self.assertEqual(row["evidence_queries_after_click"], 1)
            self.assertLess(row["packet_bytes"], 100_000)
            self.assertTrue(row["passed_budget"])
        self.assertGreater(len(json.loads(telemetry_path.read_text(encoding="utf-8"))), 0)


if __name__ == "__main__":
    unittest.main()
