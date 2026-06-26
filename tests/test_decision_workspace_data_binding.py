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


MOCKUP_LITERALS = (
    "$42.8K",
    "42.8K",
    "$6.4K",
    "6.4K",
    "18.2%",
    "Cortex AI represents 31%",
    "Spend is 18.2% above the prior 7 days",
    "PROD_WH drove 54%",
    "$8.1K in savings remain unverified",
    "$8.2K projected exposure",
)


def _metric(key: str, label: str, value: float, fmt: str, *, order: int, detail: str = "vs prior 7d") -> dict[str, object]:
    return {
        "METRIC_KEY": key,
        "METRIC_LABEL": label,
        "METRIC_NUMERIC_VALUE": value,
        "METRIC_FORMAT": fmt,
        "METRIC_DETAIL": detail,
        "METRIC_TONE": "neutral",
        "IS_AVAILABLE": True,
        "AVAILABILITY_STATE": "Available",
        "SOURCE_KEY": "decision_packet",
        "CONFIDENCE": "exact",
        "SORT_ORDER": order,
    }


def _packet(section: str, metrics: list[dict[str, object]], *, headline: str = "Dynamic packet headline") -> pd.DataFrame:
    return pd.DataFrame([
        {
            "BRIEF_ID": f"{section.lower().replace(' ', '-')}-packet",
            "SECTION_NAME": section,
            "COMPANY": "ALFA",
            "ENVIRONMENT": "ALL",
            "WINDOW_DAYS": 7,
            "RESOLVED_COMPANY": "ALFA",
            "RESOLVED_ENVIRONMENT": "ALL",
            "RESOLVED_WINDOW_DAYS": 7,
            "STATE": "At Risk",
            "HEADLINE": headline,
            "SUMMARY": "Values are supplied by the mocked mart Decision packet.",
            "TOP_SIGNAL": "Dynamic top signal",
            "TOP_ENTITY": "Packet entity",
            "TOP_ACTION": "Follow the packet action.",
            "SOURCE_STATUS": "Summary loaded from mart",
            "SOURCE_FRESHNESS": "8 minutes ago",
            "SOURCE_OBJECTS": "MART_SECTION_DECISION_CURRENT",
            "FRESHNESS_MINUTES": 8,
            "TARGET_FRESHNESS_MINUTES": 60,
            "IS_STALE": False,
            "CONFIDENCE": "exact",
            "REQUIRED_SOURCE_COUNT": 3,
            "AVAILABLE_SOURCE_COUNT": 3,
            "MISSING_SOURCE_COUNT": 0,
            "AVAILABLE_REQUIRED_SOURCE_COUNT": 3,
            "REQUIRED_MISSING_SOURCE_COUNT": 0,
            "REQUIRED_STALE_SOURCE_COUNT": 0,
            "OPTIONAL_SOURCE_COUNT": 1,
            "AVAILABLE_OPTIONAL_SOURCE_COUNT": 1,
            "OPTIONAL_MISSING_SOURCE_COUNT": 0,
            "OPTIONAL_STALE_SOURCE_COUNT": 0,
            "SOURCE_COVERAGE_PCT": 100,
            "DATA_AVAILABILITY_STATE": "Scheduled mart",
            "PACKET_BYTES": 2048,
            "SNAPSHOT_TS": "2026-06-25 10:00:00",
            "LOAD_TS": "2026-06-25 10:08:00",
            "METRICS": metrics,
            "EXCEPTIONS": [
                {
                    "SEVERITY": "High",
                    "SIGNAL": "Dynamic finding",
                    "ENTITY_NAME": "Packet entity",
                    "DETAIL": "Finding detail came from the packet.",
                    "ROUTE_SECTION": section,
                    "ROUTE_WORKFLOW": "Overview",
                    "OWNER_ROUTE": "Owner route",
                    "OWNER_ID": "owner-123",
                    "OWNER_NAME": "Packet Owner",
                    "OWNER_GAP": False,
                    "SLA_STATE": "Due soon",
                    "FINDING_KEY": "finding-123",
                    "DEDUPE_KEY": "dedupe-123",
                    "ENTITY_TYPE": "warehouse",
                    "ENTITY_ID": "PROD_WH",
                    "EVIDENCE_ID": "EVT-123",
                    "EVIDENCE_QUERY": "SELECT * FROM ADMIN_ONLY",
                    "FIRST_SEEN_TS": "2026-06-25 09:00:00",
                    "DUE_TS": "2026-06-25 12:00:00",
                    "AGE_MINUTES": 68,
                    "EVIDENCE_SOURCE": "FACT_QUERY_HOURLY",
                    "SORT_ORDER": 1,
                }
            ],
            "ACTIONS": [
                {
                    "ACTION_KEY": "dynamic_action",
                    "ROUTE_KEY": "executive_overview",
                    "ACTION_LABEL": "Dynamic packet action",
                    "ACTION_DETAIL": "Action detail came from the packet.",
                    "CTA_LABEL": "Open dynamic action",
                    "TARGET_SECTION": "Executive Landing",
                    "TARGET_WORKFLOW": "Overview",
                    "SORT_ORDER": 1,
                }
            ],
            "SOURCES": [
                {
                    "SOURCE_KEY": "decision_packet",
                    "SOURCE_OBJECT": "MART_SECTION_DECISION_CURRENT",
                    "REQUIRED": True,
                    "AVAILABLE": True,
                    "SOURCE_SNAPSHOT_TS": "2026-06-25 10:00:00",
                    "AGE_MINUTES": 8,
                    "TARGET_FRESHNESS_MINUTES": 60,
                    "IS_STALE": False,
                    "CONFIDENCE": "exact",
                    "GAP_REASON": "",
                }
            ],
        }
    ])


def _render_markup(brief: object) -> str:
    from sections import section_command_rendering

    def _columns(spec):
        count = int(spec) if isinstance(spec, int) else len(spec)
        return [contextlib.nullcontext() for _ in range(count)]

    with patch.object(section_command_rendering.st, "html") as html, patch.object(
        section_command_rendering.st,
        "markdown",
    ) as markdown, patch.object(
        section_command_rendering.st,
        "columns",
        side_effect=_columns,
    ), patch.object(section_command_rendering.st, "button", return_value=False), patch.object(
        section_command_rendering.st,
        "expander",
        return_value=contextlib.nullcontext(),
    ):
        section_command_rendering.render_section_command_brief(brief, key_prefix="binding")

    return "\n".join(
        [str(call.args[0]) for call in markdown.call_args_list]
        + [str(call.args[0]) for call in html.call_args_list]
    )


class DecisionWorkspaceDataBindingTests(unittest.TestCase):
    VALIDATION_SECTIONS = (
        "Executive Landing",
        "DBA Control Room",
        "Alert Center",
        "Cost & Contract",
        "Workload Operations",
        "Security Monitoring",
    )

    @classmethod
    def _valid_bootstrap_rows(cls) -> list[dict[str, object]]:
        return [
            {
                "SECTION_NAME": section,
                "COMPANY": "ALL",
                "ENVIRONMENT": "ALL",
                "WINDOW_DAYS": 7,
                "CURRENT_KEY_COUNT": 1,
                "BRIEF_ID": f"{section.lower().replace(' ', '-')}-brief",
                "MAX_PACKET_BYTES": 2048,
                "HAS_METRICS": 1,
                "SOURCE_ROW_COUNT": 3,
                "REQUIRED_SOURCE_COUNT": 3,
                "AVAILABLE_SOURCE_COUNT": 3,
                "MISSING_SOURCE_COUNT": 0,
                "AVAILABLE_REQUIRED_SOURCE_COUNT": 3,
                "REQUIRED_MISSING_SOURCE_COUNT": 0,
                "REQUIRED_STALE_SOURCE_COUNT": 0,
                "OPTIONAL_SOURCE_COUNT": 1,
                "AVAILABLE_OPTIONAL_SOURCE_COUNT": 1,
                "OPTIONAL_MISSING_SOURCE_COUNT": 0,
                "OPTIONAL_STALE_SOURCE_COUNT": 0,
                "FLATTENED_SOURCE_ROW_COUNT": 3,
                "FLATTENED_REQUIRED_SOURCE_COUNT": 3,
                "FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT": 3,
                "FLATTENED_REQUIRED_MISSING_SOURCE_COUNT": 0,
                "FLATTENED_REQUIRED_STALE_SOURCE_COUNT": 0,
                "FLATTENED_OPTIONAL_SOURCE_COUNT": 1,
                "FLATTENED_AVAILABLE_OPTIONAL_SOURCE_COUNT": 1,
                "FLATTENED_OPTIONAL_MISSING_SOURCE_COUNT": 0,
                "FLATTENED_OPTIONAL_STALE_SOURCE_COUNT": 0,
                "DUPLICATE_SOURCE_KEY_COUNT": 0,
                "SOURCE_COUNTER_MISMATCH_COUNT": 0,
                "STALE_SOURCE_COUNT": 0,
                "SOURCE_COVERAGE_PCT": 100,
                "DATA_AVAILABILITY_STATE": "READY",
                "FRESHNESS_MINUTES": 8,
                "TARGET_FRESHNESS_MINUTES": 60,
                "RESOLVED_COMPANY": "ALL",
                "RESOLVED_ENVIRONMENT": "ALL",
                "RESOLVED_WINDOW_DAYS": 7,
                "PACKET_TOO_LARGE": 0,
            }
            for section in cls.VALIDATION_SECTIONS
        ]

    def test_bootstrap_validation_requires_selected_section_packet(self):
        from sections import decision_workspace_bootstrap as bootstrap

        class ValidationSession:
            def sql(self, text: str) -> "ValidationSession":
                return self

            def collect(self) -> list[dict[str, object]]:
                return [
                    row for row in DecisionWorkspaceDataBindingTests._valid_bootstrap_rows()
                    if row["SECTION_NAME"] != "Executive Landing"
                ]

        validation = bootstrap.validate_decision_bootstrap_output(
            ValidationSession(),
            current_section="Executive Landing",
            company="ALFA",
            environment="PROD",
            window_days=7,
        )

        self.assertFalse(validation.ok)
        self.assertEqual(validation.status, "FAILED")
        self.assertFalse(validation.current_section_ok)
        self.assertFalse(validation.selected_scope_ok)
        self.assertIn("Executive Landing", validation.missing_sections)

    def test_bootstrap_validation_accepts_documented_scope_fallback(self):
        from sections import decision_workspace_bootstrap as bootstrap

        class ValidationSession:
            def sql(self, text: str) -> "ValidationSession":
                return self

            def collect(self) -> list[dict[str, object]]:
                return DecisionWorkspaceDataBindingTests._valid_bootstrap_rows()

        validation = bootstrap.validate_decision_bootstrap_output(
            ValidationSession(),
            current_section="Cost & Contract",
            company="ALFA",
            environment="PROD",
            window_days=8,
        )

        self.assertTrue(validation.ok)
        self.assertEqual(validation.status, "SUCCESS")
        self.assertTrue(validation.global_ok)
        self.assertTrue(validation.selected_scope_ok)
        self.assertEqual(validation.resolved_company, "ALL")
        self.assertEqual(validation.resolved_environment, "ALL")
        self.assertEqual(validation.resolved_window_days, 7)
        self.assertEqual(validation.validated_packet_keys, (("Cost & Contract", "ALL", "ALL", 7),))

    def test_bootstrap_validation_rejects_datagap_missing_sources_duplicates_and_size(self):
        from sections import decision_workspace_bootstrap as bootstrap

        def _validate(rows: list[dict[str, object]]):
            class ValidationSession:
                def sql(self, text: str) -> "ValidationSession":
                    return self

                def collect(self) -> list[dict[str, object]]:
                    return rows

            return bootstrap.validate_decision_bootstrap_output(
                ValidationSession(),
                current_section="Security Monitoring",
                company="ALL",
                environment="ALL",
                window_days=7,
            )

        rows = self._valid_bootstrap_rows()
        rows[5] = {**rows[5], "DATA_AVAILABILITY_STATE": "DATA GAP"}
        validation = _validate(rows)
        self.assertFalse(validation.ok)
        self.assertEqual(validation.status, "FAILED")

        rows = self._valid_bootstrap_rows()
        rows[5] = {**rows[5], "SOURCE_ROW_COUNT": 0, "REQUIRED_SOURCE_COUNT": None}
        validation = _validate(rows)
        self.assertFalse(validation.ok)
        self.assertEqual(validation.status, "FAILED")
        self.assertGreater(validation.current_section_missing_sources, 0)

        rows = self._valid_bootstrap_rows()
        rows[5] = {**rows[5], "CURRENT_KEY_COUNT": 2}
        validation = _validate(rows)
        self.assertFalse(validation.ok)
        self.assertEqual(validation.status, "FAILED")

        rows = self._valid_bootstrap_rows()
        rows[5] = {**rows[5], "MAX_PACKET_BYTES": 200000, "PACKET_TOO_LARGE": 1}
        validation = _validate(rows)
        self.assertFalse(validation.ok)
        self.assertEqual(validation.status, "FAILED")

    def test_bootstrap_validation_tristate_degraded_when_current_section_is_usable(self):
        from sections import decision_workspace_bootstrap as bootstrap

        rows = self._valid_bootstrap_rows()
        rows[1] = {**rows[1], "DATA_AVAILABILITY_STATE": "DATA GAP"}

        class ValidationSession:
            def sql(self, text: str) -> "ValidationSession":
                return self

            def collect(self) -> list[dict[str, object]]:
                return rows

        validation = bootstrap.validate_decision_bootstrap_output(
            ValidationSession(),
            current_section="Executive Landing",
            company="ALL",
            environment="ALL",
            window_days=7,
        )
        self.assertTrue(validation.ok)
        self.assertEqual(validation.status, "DEGRADED")
        self.assertEqual(validation.global_status, "DEGRADED")
        self.assertEqual(validation.selected_scope_status, "SUCCESS")
        self.assertIn("DBA Control Room", validation.degraded_sections)

    def test_bootstrap_validation_strict_required_sources(self):
        from sections import decision_workspace_bootstrap as bootstrap

        def _validate(row_updates: dict[str, object]):
            rows = self._valid_bootstrap_rows()
            rows[0] = {**rows[0], **row_updates}

            class ValidationSession:
                def sql(self, text: str) -> "ValidationSession":
                    return self

                def collect(self) -> list[dict[str, object]]:
                    return rows

            return bootstrap.validate_decision_bootstrap_output(
                ValidationSession(),
                current_section="Executive Landing",
                company="ALL",
                environment="ALL",
                window_days=7,
            )

        self.assertEqual(_validate({"SOURCE_ROW_COUNT": 0}).status, "FAILED")
        self.assertEqual(_validate({"REQUIRED_SOURCE_COUNT": 0}).status, "FAILED")
        self.assertEqual(_validate({"AVAILABLE_REQUIRED_SOURCE_COUNT": 2}).status, "FAILED")
        self.assertEqual(_validate({"REQUIRED_MISSING_SOURCE_COUNT": 1}).status, "FAILED")
        self.assertEqual(_validate({"SOURCE_COVERAGE_PCT": 99}).status, "FAILED")
        self.assertEqual(_validate({"REQUIRED_STALE_SOURCE_COUNT": 1}).status, "FAILED")
        self.assertEqual(_validate({"FLATTENED_REQUIRED_MISSING_SOURCE_COUNT": 1}).status, "FAILED")
        self.assertEqual(_validate({"FLATTENED_REQUIRED_STALE_SOURCE_COUNT": 1}).status, "FAILED")
        self.assertEqual(_validate({"SOURCE_COUNTER_MISMATCH_COUNT": 1}).status, "FAILED")
        self.assertEqual(_validate({"DUPLICATE_SOURCE_KEY_COUNT": 1}).status, "FAILED")

        optional = _validate({
            "OPTIONAL_SOURCE_COUNT": 2,
            "AVAILABLE_OPTIONAL_SOURCE_COUNT": 1,
            "OPTIONAL_MISSING_SOURCE_COUNT": 1,
            "MISSING_SOURCE_COUNT": 1,
            "FLATTENED_OPTIONAL_SOURCE_COUNT": 2,
            "FLATTENED_AVAILABLE_OPTIONAL_SOURCE_COUNT": 1,
            "FLATTENED_OPTIONAL_MISSING_SOURCE_COUNT": 1,
        })
        self.assertTrue(optional.ok)
        self.assertEqual(optional.status, "DEGRADED")
        self.assertIn("Executive Landing", optional.warning_sections)

        optional_stale = _validate({
            "OPTIONAL_STALE_SOURCE_COUNT": 1,
            "STALE_SOURCE_COUNT": 1,
            "FLATTENED_OPTIONAL_STALE_SOURCE_COUNT": 1,
        })
        self.assertTrue(optional_stale.ok)
        self.assertEqual(optional_stale.status, "DEGRADED")

        source_text_only = _validate({
            "SOURCE_ROW_COUNT": 0,
            "FLATTENED_SOURCE_ROW_COUNT": 0,
            "FLATTENED_REQUIRED_SOURCE_COUNT": 0,
            "FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT": 0,
            "REQUIRED_SOURCE_COUNT": 3,
            "AVAILABLE_REQUIRED_SOURCE_COUNT": 3,
            "REQUIRED_MISSING_SOURCE_COUNT": 0,
        })
        self.assertEqual(source_text_only.status, "FAILED")

    def test_bootstrap_validation_rejects_global_five_section_data_gap(self):
        from sections import decision_workspace_bootstrap as bootstrap

        rows = self._valid_bootstrap_rows()
        rows = [
            row if row["SECTION_NAME"] == "Executive Landing"
            else {**row, "DATA_AVAILABILITY_STATE": "DATA GAP"}
            for row in rows
        ]

        class ValidationSession:
            def sql(self, text: str) -> "ValidationSession":
                return self

            def collect(self) -> list[dict[str, object]]:
                return rows

        validation = bootstrap.validate_decision_bootstrap_output(
            ValidationSession(),
            current_section="Executive Landing",
            company="ALL",
            environment="ALL",
            window_days=7,
        )
        self.assertTrue(validation.ok)
        self.assertEqual(validation.status, "DEGRADED")
        self.assertFalse(validation.global_ok)
        self.assertEqual(len(validation.data_gap_sections), 5)

    def test_clear_last_good_only_for_validated_packet_key(self):
        from sections import decision_workspace_bootstrap as bootstrap
        from sections.section_command_brief import SectionCommandBrief

        def _brief(section: str, company: str, environment: str, window: str = "7 days") -> SectionCommandBrief:
            return SectionCommandBrief(
                section=section,
                company=company,
                environment=environment,
                window_label=window,
                state="Ready",
                headline="Last good",
                summary="Last good summary",
                source="MART_SECTION_DECISION_CURRENT",
                freshness_label="Updated",
                loaded_at="2026-06-25T10:00:00",
            )

        fixture = _brief("Cost & Contract", "ALFA", "ALL")
        object.__setattr__(fixture, "raw_payload", {"fixture_mode": True})
        state = {
            "section_command_brief::Cost & Contract::ALFA::ALL::7::last_good": _brief("Cost & Contract", "ALFA", "ALL"),
            "section_command_brief::Cost & Contract::Trexis::ALL::7::last_good": _brief("Cost & Contract", "Trexis", "ALL"),
            "section_command_brief::Cost & Contract::ALFA::PROD::7::last_good": _brief("Cost & Contract", "ALFA", "PROD"),
            "section_command_brief::Cost & Contract::ALFA::ALL::30::last_good": _brief("Cost & Contract", "ALFA", "ALL", "30 days"),
            "section_command_brief::Cost & Contract::fixture::ALL::7::last_good": fixture,
            "section_command_brief::Cost & Contract::invalid::ALL::7::last_good": object(),
        }
        with patch.object(bootstrap.st, "session_state", state):
            bootstrap._clear_command_brief_caches(
                clear_last_good=True,
                validated_packet_keys=(("Cost & Contract", "ALFA", "ALL", 7),),
            )

        self.assertNotIn("section_command_brief::Cost & Contract::ALFA::ALL::7::last_good", state)
        self.assertIn("section_command_brief::Cost & Contract::Trexis::ALL::7::last_good", state)
        self.assertIn("section_command_brief::Cost & Contract::ALFA::PROD::7::last_good", state)
        self.assertIn("section_command_brief::Cost & Contract::ALFA::ALL::30::last_good", state)
        self.assertNotIn("section_command_brief::Cost & Contract::fixture::ALL::7::last_good", state)
        self.assertNotIn("section_command_brief::Cost & Contract::invalid::ALL::7::last_good", state)

    def test_renderer_has_no_legacy_brief_helper_paths(self):
        renderer_source = (APP_ROOT / "sections" / "section_command_rendering.py").read_text(encoding="utf-8")
        legacy_names = (
            "_visible_metrics",
            "_metric_ribbon_html",
            "_priority_list_html",
            "_state_token",
            "_state_label",
            "_metric_ribbon_panel",
            "_attention_panel",
            "_trend_band",
            "_trust_footer",
        )
        for helper in legacy_names:
            with self.subTest(helper=helper):
                self.assertNotIn(f"def {helper}", renderer_source)
        self.assertNotIn("brief.next_actions", renderer_source)
        self.assertNotIn("brief.exceptions", renderer_source)
        self.assertNotIn("brief.metrics", renderer_source)

    def test_no_mockup_literals_in_production_paths(self):
        allowed = {
            APP_ROOT / "sections" / "decision_workspace_fixtures.py",
        }
        for path in APP_ROOT.rglob("*.py"):
            if path in allowed or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for literal in MOCKUP_LITERALS:
                with self.subTest(path=path.relative_to(ROOT), literal=literal):
                    self.assertNotIn(literal, text)

    def test_executive_workspace_values_come_from_packet_and_session_cache(self):
        from sections import section_command_brief as brief_module

        packet_a = _packet(
            "Executive Landing",
            [
                _metric("total_spend", "Total Spend", 12345, "currency", order=10),
                _metric("critical_high_issues", "Critical / High Alerts", 2, "integer", order=20),
                _metric("open_actions", "Open Actions", 9, "integer", order=30),
                _metric("cortex_spend", "Cortex AI Spend", 987, "currency", order=40),
            ],
            headline="Packet A headline",
        )
        state_a: dict[str, object] = {}
        with patch.object(brief_module.st, "session_state", state_a), patch.object(
            brief_module,
            "run_query",
            return_value=packet_a,
        ) as run_query:
            brief_a = brief_module.autoload_section_command_brief("Executive Landing", "ALFA", "ALL", 7)
            warm_a = brief_module.autoload_section_command_brief("Executive Landing", "ALFA", "ALL", 7)

        self.assertEqual(run_query.call_count, 1)
        self.assertEqual(brief_a.command_brief_query_count, 1)
        self.assertEqual(warm_a.command_brief_query_count, 0)
        markup_a = _render_markup(brief_a)
        self.assertIn("$12.3K", markup_a)
        self.assertIn(">2<", markup_a)
        self.assertIn(">9<", markup_a)
        self.assertIn("$987", markup_a)
        self.assertIn("Packet A headline", markup_a)
        self.assertIn("Trend data not available for this packet.", markup_a)
        self.assertNotIn("ow-trend-unavailable", markup_a)

        packet_b = _packet(
            "Executive Landing",
            [
                _metric("total_spend", "Total Spend", 765432, "currency", order=10),
                _metric("critical_high_issues", "Critical / High Alerts", 14, "integer", order=20),
                _metric("open_actions", "Open Actions", 1, "integer", order=30),
                _metric("cortex_spend", "Cortex AI Spend", 32100, "currency", order=40),
            ],
            headline="Packet B headline",
        )
        with patch.object(brief_module.st, "session_state", {}), patch.object(
            brief_module,
            "run_query",
            return_value=packet_b,
        ):
            brief_b = brief_module.autoload_section_command_brief("Executive Landing", "ALFA", "ALL", 7)
        markup_b = _render_markup(brief_b)

        self.assertIn("$765.4K", markup_b)
        self.assertIn(">14<", markup_b)
        self.assertIn(">1<", markup_b)
        self.assertIn("$32.1K", markup_b)
        self.assertIn("Packet B headline", markup_b)
        for literal in MOCKUP_LITERALS:
            self.assertNotIn(literal, markup_a)
            self.assertNotIn(literal, markup_b)

    def test_primary_sections_render_dynamic_packet_metrics_without_fixture_mode(self):
        from sections import section_command_brief as brief_module

        cases = {
            "Cost & Contract": [
                _metric("total_spend", "Total Spend", 50200, "currency", order=10),
                _metric("spend_movement_pct", "Spend Movement", 12.5, "percentage", order=20),
                _metric("cortex_spend", "Cortex AI Spend", 4100, "currency", order=30),
                _metric("forecast_run_rate", "Forecast / Run-rate", 61000, "currency", order=40),
            ],
            "Alert Center": [
                _metric("active_alerts", "Active Alerts", 11, "integer", order=10),
                _metric("critical_high", "Critical / High", 4, "integer", order=20),
                _metric("overdue_alerts", "Overdue", 3, "integer", order=30),
                _metric("cortex_predictive", "Cortex Predictive", 2, "integer", order=40),
            ],
            "DBA Control Room": [
                _metric("failed_queries", "Failed Queries", 17, "integer", order=10),
                _metric("pipeline_failures", "Pipeline Failures", 5, "integer", order=20),
                _metric("queue_pressure", "Queue Pressure", 8, "integer", order=30),
                _metric("cost_24h", "Cost 24h", 1200, "currency", order=40),
            ],
            "Workload Operations": [
                _metric("failed_queries", "Failed Queries", 18, "integer", order=10),
                _metric("pipeline_failures", "Pipeline Failures", 6, "integer", order=20),
                _metric("queue_blocked_pressure", "Queue / Blocked", 7, "integer", order=30),
                _metric("sla_risk", "SLA Risk", 3, "integer", order=40),
            ],
            "Security Monitoring": [
                _metric("failed_logins", "Failed Logins", 21, "integer", order=10),
                _metric("mfa_gaps", "MFA Gaps", 2, "integer", order=20),
                _metric("risky_grants", "Risky Grants", 10, "integer", order=30),
                _metric("sharing_exposure", "Sharing Exposure", 1, "integer", order=40),
            ],
        }
        for section, metrics in cases.items():
            with self.subTest(section=section), patch.object(brief_module.st, "session_state", {}), patch.object(
                brief_module,
                "run_query",
                return_value=_packet(section, metrics, headline=f"{section} packet headline"),
            ):
                brief = brief_module.autoload_section_command_brief(section, "ALFA", "ALL", 7)
                markup = _render_markup(brief)
                self.assertIn(f"{section.replace('&', '&amp;')} packet headline", markup)
                self.assertNotIn("FIXTURE DATA", markup)
                for literal in MOCKUP_LITERALS:
                    self.assertNotIn(literal, markup)

    def test_fixture_last_good_cache_is_discarded_in_production_mode(self):
        from sections import section_command_brief as brief_module
        from sections.section_command_brief import SectionCommandBrief

        fixture_lkg = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="FIXTURE DATA",
            headline="Fixture headline",
            summary="Fixture summary",
            source="Fixture",
            freshness_label="Fixture",
            loaded_at="2026-06-25T10:00:00",
            raw_payload={"fixture_mode": True},
        )
        state = {
            "section_command_brief::Executive Landing::ALFA::ALL::7::last_good": fixture_lkg,
        }
        with patch.object(brief_module.st, "session_state", state), patch.object(
            brief_module,
            "decision_fixture_enabled",
            return_value=False,
        ), patch.object(brief_module, "snowflake_entry_available", return_value=False), patch.object(
            brief_module,
            "run_query",
            side_effect=AssertionError("offline preflight should avoid packet query"),
        ):
            brief = brief_module.autoload_section_command_brief("Executive Landing", "ALFA", "ALL", 7)

        self.assertFalse(brief.raw_payload.get("fixture_mode"))
        self.assertNotIn("section_command_brief::Executive Landing::ALFA::ALL::7::last_good", state)

    def test_initialize_summaries_button_sets_bootstrap_request(self):
        from sections.section_command_brief import SectionCommandBrief
        from sections import section_command_rendering

        state: dict[str, object] = {}
        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="Summary not initialized",
            headline="Summary not initialized",
            summary="No current packet.",
            source="Decision packet",
            freshness_label="Setup required",
            loaded_at="2026-06-25T10:00:00",
            fallback_reason="No packet row.",
            raw_payload={"workspace_mode": "UNINITIALIZED"},
        )
        with patch.dict(os.environ, {"OVERWATCH_TEST_MODE": "1"}), patch.object(
            section_command_rendering.st,
            "session_state",
            state,
        ), patch.object(
            section_command_rendering.st,
            "html",
        ), patch.object(
            section_command_rendering.st,
            "columns",
            return_value=[contextlib.nullcontext(), contextlib.nullcontext()],
        ), patch.object(section_command_rendering.st, "button", return_value=True), patch.object(
            section_command_rendering.st,
            "rerun",
            side_effect=RuntimeError("rerun"),
        ):
            with self.assertRaises(RuntimeError):
                section_command_rendering.render_section_command_brief(brief, key_prefix="bootstrap")

        self.assertTrue(state["_overwatch_decision_bootstrap_requested"])

    def test_refresh_lives_in_hero_and_evidence_is_separate(self):
        from sections.section_command_brief import SectionCommandAction, SectionCommandBrief, SectionCommandMetric
        from sections import section_command_rendering

        state: dict[str, object] = {}
        brief = SectionCommandBrief(
            section="Alert Center",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Packet headline",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 4m ago",
            loaded_at="2026-06-25T10:00:00",
            metrics=(SectionCommandMetric("Active Alerts", "5", numeric_value=5, metric_format="integer", key="active_alerts"),),
            next_actions=(
                SectionCommandAction("Open Active Alerts", "Route only", route_key="alert_center_active", cta="Open Active Alerts"),
            ),
        )

        def _button(label, *args, **kwargs):
            return False

        with patch.object(section_command_rendering.st, "html"), patch.object(
            section_command_rendering.st,
            "markdown",
        ), patch.object(
            section_command_rendering.st,
            "columns",
            return_value=[contextlib.nullcontext(), contextlib.nullcontext()],
        ), patch.object(section_command_rendering.st, "button", side_effect=_button) as button, patch.object(
            section_command_rendering.st,
            "expander",
            return_value=contextlib.nullcontext(),
        ), patch.object(section_command_rendering.st, "rerun", side_effect=AssertionError("idle render must not rerun")):
            section_command_rendering.render_section_command_brief(
                brief,
                key_prefix="action_hierarchy",
                primary_action=lambda: state.__setitem__("force", True),
                detail_action=section_command_rendering.CommandBriefDetailAction(
                    "Load Active Alerts",
                    "Load alert rows.",
                    lambda: state.__setitem__("evidence", True),
                    key="alert_center_load",
                ),
            )

        labels = [str(call.args[0]) for call in button.call_args_list]
        self.assertIn("Refresh", labels)
        self.assertNotIn("Refresh Decision Brief", labels)
        self.assertEqual(sum(label.startswith("Open Active Alerts") for label in labels), 1)
        self.assertIn("Load Active Alerts", labels)

    def test_refresh_button_sets_packet_flag_not_evidence_flag(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandMetric
        from sections import section_command_rendering

        state: dict[str, object] = {}
        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Packet headline",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 4m ago",
            loaded_at="2026-06-25T10:00:00",
            metrics=(SectionCommandMetric("Spend", "$123", numeric_value=123, metric_format="currency", key="total_spend"),),
        )

        def _button(label, *args, **kwargs):
            return label == "Refresh"

        with patch.object(section_command_rendering.st, "html"), patch.object(
            section_command_rendering.st,
            "markdown",
        ), patch.object(
            section_command_rendering.st,
            "columns",
            return_value=[contextlib.nullcontext(), contextlib.nullcontext()],
        ), patch.object(section_command_rendering.st, "button", side_effect=_button), patch.object(
            section_command_rendering.st,
            "expander",
            return_value=contextlib.nullcontext(),
        ), patch.object(section_command_rendering.st, "rerun", side_effect=RuntimeError("rerun")):
            with self.assertRaises(RuntimeError):
                section_command_rendering.render_section_command_brief(
                    brief,
                    key_prefix="refresh_only",
                    primary_action=lambda: state.__setitem__("force", True),
                    detail_action=section_command_rendering.CommandBriefDetailAction(
                        "Load Full Executive Snapshot",
                        "Load evidence.",
                        lambda: state.__setitem__("evidence", True),
                    ),
                )

        self.assertTrue(state.get("force"))
        self.assertNotIn("evidence", state)

    def test_evidence_button_sets_evidence_flag_not_packet_refresh(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandMetric
        from sections import section_command_rendering

        state: dict[str, object] = {}
        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Packet headline",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 4m ago",
            loaded_at="2026-06-25T10:00:00",
            metrics=(SectionCommandMetric("Spend", "$123", numeric_value=123, metric_format="currency", key="total_spend"),),
        )

        def _button(label, *args, **kwargs):
            return label == "Load Full Executive Snapshot"

        with patch.object(section_command_rendering.st, "html"), patch.object(
            section_command_rendering.st,
            "markdown",
        ), patch.object(
            section_command_rendering.st,
            "columns",
            return_value=[contextlib.nullcontext(), contextlib.nullcontext()],
        ), patch.object(section_command_rendering.st, "button", side_effect=_button), patch.object(
            section_command_rendering.st,
            "expander",
            return_value=contextlib.nullcontext(),
        ), patch.object(section_command_rendering.st, "rerun", side_effect=RuntimeError("rerun")):
            with self.assertRaises(RuntimeError):
                section_command_rendering.render_section_command_brief(
                    brief,
                    key_prefix="evidence_only",
                    primary_action=lambda: state.__setitem__("force", True),
                    detail_action=section_command_rendering.CommandBriefDetailAction(
                        "Load Full Executive Snapshot",
                        "Load evidence.",
                        lambda: state.__setitem__("evidence", True),
                    ),
                )

        self.assertTrue(state.get("evidence"))
        self.assertNotIn("force", state)

    def test_bootstrap_request_is_consumed_once_and_clears_command_cache(self):
        from sections import decision_workspace_bootstrap as bootstrap

        class FakeSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "FakeSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                if self.sql_calls[-1] == "SHOW PROCEDURES LIKE 'SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS'":
                    return [object()]
                if self.sql_calls[-1] == "CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();":
                    return []
                if "FROM MART_SECTION_DECISION_CURRENT" in self.sql_calls[-1]:
                    return DecisionWorkspaceDataBindingTests._valid_bootstrap_rows()
                return []

        session = FakeSession()
        state = {
            bootstrap.BOOTSTRAP_REQUEST_KEY: True,
            "section_command_brief::Executive Landing::ALFA::ALL::7": object(),
            "section_command_brief::Executive Landing::ALFA::ALL::7::negative_until": "later",
            "section_command_brief::Executive Landing::ALFA::ALL::7::last_good": object(),
            "unrelated": "keep",
        }
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: session,
        ), patch.object(bootstrap.st, "success") as success, patch.object(bootstrap.st, "warning") as warning, patch.object(
            bootstrap.st,
            "rerun",
            side_effect=RuntimeError("rerun"),
        ) as rerun:
            with self.assertRaises(RuntimeError):
                bootstrap.maybe_run_decision_workspace_bootstrap("Executive Landing")
            bootstrap.maybe_run_decision_workspace_bootstrap()

        self.assertIn("FROM OVERWATCH_SETTINGS", session.sql_calls[0])
        self.assertIn("SHOW PROCEDURES LIKE 'SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS'", session.sql_calls)
        self.assertIn("CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();", session.sql_calls)
        self.assertTrue(any("FROM MART_SECTION_DECISION_CURRENT" in call for call in session.sql_calls))
        self.assertNotIn(bootstrap.BOOTSTRAP_REQUEST_KEY, state)
        self.assertNotIn("section_command_brief::Executive Landing::ALFA::ALL::7", state)
        self.assertNotIn("section_command_brief::Executive Landing::ALFA::ALL::7::negative_until", state)
        self.assertNotIn("section_command_brief::Executive Landing::ALFA::ALL::7::last_good", state)
        self.assertTrue(state["_executive_landing_command_brief_force_refresh"])
        self.assertEqual(state["unrelated"], "keep")
        success.assert_called_once()
        warning.assert_not_called()
        rerun.assert_called_once()

    def test_bootstrap_failure_preserves_valid_last_good(self):
        from sections import decision_workspace_bootstrap as bootstrap
        from sections.section_command_brief import SectionCommandBrief

        class FailingSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "FailingSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                if self.sql_calls[-1] == "SHOW PROCEDURES LIKE 'SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS'":
                    return [object()]
                raise RuntimeError("SQL compilation error: Unknown function SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS")

        last_good = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Last good",
            summary="Last good summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 20m ago",
            loaded_at="2026-06-25T10:00:00",
        )
        state = {
            bootstrap.BOOTSTRAP_REQUEST_KEY: True,
            "section_command_brief::Cost & Contract::ALFA::ALL::7": object(),
            "section_command_brief::Cost & Contract::ALFA::ALL::7::negative_until": "later",
            "section_command_brief::Cost & Contract::ALFA::ALL::7::last_good": last_good,
        }
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: FailingSession(),
        ), patch.object(bootstrap.st, "warning") as warning, patch.object(
            bootstrap.st,
            "rerun",
            side_effect=AssertionError("failed bootstrap must not rerun"),
        ):
            bootstrap.maybe_run_decision_workspace_bootstrap("Cost & Contract")

        self.assertIs(state["section_command_brief::Cost & Contract::ALFA::ALL::7::last_good"], last_good)
        self.assertNotIn("section_command_brief::Cost & Contract::ALFA::ALL::7", state)
        self.assertNotIn("section_command_brief::Cost & Contract::ALFA::ALL::7::negative_until", state)
        warning.assert_called_once()
        warning_text = warning.call_args.args[0]
        self.assertIn("Decision summaries are not initialized", warning_text)
        self.assertNotIn("Unknown function", warning_text)
        self.assertNotIn("SQL compilation", warning_text)

    def test_bootstrap_success_without_packets_preserves_valid_last_good(self):
        from sections import decision_workspace_bootstrap as bootstrap
        from sections.decision_workspace_setup_health import SETUP_HEALTH_KEY
        from sections.section_command_brief import SectionCommandBrief

        class EmptyValidationSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "EmptyValidationSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                if self.sql_calls[-1] == "SHOW PROCEDURES LIKE 'SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS'":
                    return [object()]
                if self.sql_calls[-1] == "CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();":
                    return []
                if "FROM MART_SECTION_DECISION_CURRENT" in self.sql_calls[-1]:
                    return []
                return []

        last_good = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="Ready",
            headline="Last good",
            summary="Last good summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated",
            loaded_at="2026-06-25T10:00:00",
        )
        state = {
            bootstrap.BOOTSTRAP_REQUEST_KEY: True,
            "section_command_brief::Executive Landing::ALFA::ALL::7": object(),
            "section_command_brief::Executive Landing::ALFA::ALL::7::negative_until": "later",
            "section_command_brief::Executive Landing::ALFA::ALL::7::last_good": last_good,
        }
        session = EmptyValidationSession()
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: session,
        ), patch.object(bootstrap.st, "warning") as warning, patch.object(
            bootstrap.st,
            "rerun",
            side_effect=AssertionError("invalid bootstrap must not rerun"),
        ):
            bootstrap.maybe_run_decision_workspace_bootstrap("Executive Landing")

        self.assertIn("CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();", session.sql_calls)
        self.assertTrue(any("FROM MART_SECTION_DECISION_CURRENT" in call for call in session.sql_calls))
        self.assertIs(state["section_command_brief::Executive Landing::ALFA::ALL::7::last_good"], last_good)
        self.assertNotIn("section_command_brief::Executive Landing::ALFA::ALL::7", state)
        self.assertNotIn("section_command_brief::Executive Landing::ALFA::ALL::7::negative_until", state)
        warning.assert_called_once()
        warning_text = warning.call_args.args[0]
        self.assertIn("Decision summaries are not initialized", warning_text)
        self.assertNotIn("CALL ", warning_text)
        self.assertIn(SETUP_HEALTH_KEY, state)
        self.assertIn("MART_SECTION_DECISION_CURRENT", state[SETUP_HEALTH_KEY]["admin_detail"])

    def test_bootstrap_uses_installed_full_refresh_fallback(self):
        from sections import decision_workspace_bootstrap as bootstrap

        class FallbackSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "FallbackSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                if self.sql_calls[-1] == "SHOW PROCEDURES LIKE 'SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL'":
                    return [object()]
                if self.sql_calls[-1] == "CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL();":
                    return []
                if "FROM MART_SECTION_DECISION_CURRENT" in self.sql_calls[-1]:
                    return DecisionWorkspaceDataBindingTests._valid_bootstrap_rows()
                return []

        session = FallbackSession()
        state = {bootstrap.BOOTSTRAP_REQUEST_KEY: True}
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: session,
        ), patch.object(bootstrap.st, "warning") as warning, patch.object(
            bootstrap.st,
            "rerun",
            side_effect=RuntimeError("rerun"),
        ):
            with self.assertRaises(RuntimeError):
                bootstrap.maybe_run_decision_workspace_bootstrap("Executive Landing")

        self.assertIn("FROM OVERWATCH_SETTINGS", session.sql_calls[0])
        self.assertIn("SHOW PROCEDURES LIKE 'SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS'", session.sql_calls)
        self.assertIn("SHOW PROCEDURES LIKE 'SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL'", session.sql_calls)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL();", session.sql_calls)
        self.assertTrue(any("FROM MART_SECTION_DECISION_CURRENT" in call for call in session.sql_calls))
        warning.assert_not_called()

    def test_bootstrap_version_marker_selects_configured_procedure_without_show(self):
        from sections import decision_workspace_bootstrap as bootstrap

        class VersionMarkerSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "VersionMarkerSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                current = self.sql_calls[-1]
                if "FROM OVERWATCH_SETTINGS" in current:
                    return [{"PROCEDURE_NAME": "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL"}]
                if current == "CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL();":
                    return []
                raise AssertionError(f"unexpected SQL: {current}")

        session = VersionMarkerSession()
        result = bootstrap._run_bootstrap_procedure(session)

        self.assertEqual(result.procedure_name, "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL")
        self.assertTrue(result.fallback_used)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL();", session.sql_calls)
        self.assertFalse(any(call.startswith("SHOW PROCEDURES") for call in session.sql_calls))

    def test_bootstrap_show_denied_calls_first_successful_candidate_only(self):
        from sections import decision_workspace_bootstrap as bootstrap

        class ShowDeniedBootstrapSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "ShowDeniedBootstrapSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                current = self.sql_calls[-1]
                if current.startswith("SHOW PROCEDURES"):
                    raise RuntimeError("not authorized to show procedures")
                if current == "CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();":
                    return []
                if "FROM MART_SECTION_DECISION_CURRENT" in current:
                    return DecisionWorkspaceDataBindingTests._valid_bootstrap_rows()
                raise AssertionError(f"unexpected SQL: {current}")

        session = ShowDeniedBootstrapSession()
        state = {bootstrap.BOOTSTRAP_REQUEST_KEY: True}
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: session,
        ), patch.object(bootstrap.st, "warning") as warning, patch.object(
            bootstrap.st,
            "rerun",
            side_effect=RuntimeError("rerun"),
        ):
            with self.assertRaises(RuntimeError):
                bootstrap.maybe_run_decision_workspace_bootstrap("Executive Landing")

        self.assertIn("CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();", session.sql_calls)
        self.assertNotIn("CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL();", session.sql_calls)
        warning.assert_not_called()

    def test_bootstrap_show_denied_tries_fallback_until_success(self):
        from sections import decision_workspace_bootstrap as bootstrap

        class ShowDeniedFallbackSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "ShowDeniedFallbackSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                current = self.sql_calls[-1]
                if current.startswith("SHOW PROCEDURES"):
                    raise RuntimeError("not authorized to show procedures")
                if current == "CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();":
                    raise RuntimeError("Unknown function")
                if current == "CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL();":
                    return []
                if "FROM MART_SECTION_DECISION_CURRENT" in current:
                    return DecisionWorkspaceDataBindingTests._valid_bootstrap_rows()
                raise AssertionError(f"unexpected SQL: {current}")

        session = ShowDeniedFallbackSession()
        state = {bootstrap.BOOTSTRAP_REQUEST_KEY: True}
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: session,
        ), patch.object(bootstrap.st, "warning") as warning, patch.object(
            bootstrap.st,
            "rerun",
            side_effect=RuntimeError("rerun"),
        ):
            with self.assertRaises(RuntimeError):
                bootstrap.maybe_run_decision_workspace_bootstrap("Executive Landing")

        self.assertIn("CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();", session.sql_calls)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL();", session.sql_calls)
        self.assertNotIn("CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS();", session.sql_calls)
        warning.assert_not_called()

    def test_bootstrap_all_candidates_fail_daily_clean_admin_detailed(self):
        from sections import decision_workspace_bootstrap as bootstrap
        from sections.decision_workspace_setup_health import SETUP_HEALTH_KEY

        class AllFailSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "AllFailSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                current = self.sql_calls[-1]
                if current.startswith("SHOW PROCEDURES"):
                    raise RuntimeError("not authorized to show procedures")
                if current.startswith("CALL "):
                    raise RuntimeError(f"SQL compilation error: Unknown function {current}")
                return []

        state = {bootstrap.BOOTSTRAP_REQUEST_KEY: True}
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: AllFailSession(),
        ), patch.object(bootstrap.st, "warning") as warning:
            bootstrap.maybe_run_decision_workspace_bootstrap("Executive Landing")

        warning.assert_called_once()
        warning_text = warning.call_args.args[0]
        self.assertIn("Decision summaries are not initialized", warning_text)
        self.assertNotIn("CALL ", warning_text)
        self.assertNotIn("SP_", warning_text)
        self.assertIn(SETUP_HEALTH_KEY, state)
        self.assertIn("SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS", state[SETUP_HEALTH_KEY]["admin_detail"])

    def test_setup_health_panel_is_admin_detail_surface(self):
        from sections import decision_workspace_setup_health as setup_health

        state = {}
        with patch.object(setup_health.st, "session_state", state):
            setup_health.record_decision_bootstrap_health(
                status="failed",
                user_message="Decision summaries are not initialized.",
                selected_procedure="SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS",
                admin_detail="MART_SECTION_DECISION_CURRENT duplicate key check failed.",
            )

        writes: list[str] = []
        with patch.object(setup_health.st, "session_state", state), patch.object(
            setup_health.st,
            "expander",
            return_value=contextlib.nullcontext(),
        ), patch.object(setup_health.st, "markdown") as markdown, patch.object(
            setup_health.st,
            "write",
            side_effect=lambda value: writes.append(str(value)),
        ), patch.object(setup_health.st, "code") as code, patch.object(setup_health.st, "info"):
            setup_health.render_decision_setup_health_panel()

        rendered = "\n".join(str(call.args[0]) for call in markdown.call_args_list) + "\n".join(writes)
        self.assertIn("Decision summaries are not initialized", rendered)
        self.assertIn("ow-setup-health-badge", rendered)
        self.assertIn("Persistence", rendered)
        self.assertIn("Global", rendered)
        self.assertIn("Selected scope", rendered)
        self.assertIn("Current section", rendered)
        self.assertIn("Degraded sections", rendered)
        self.assertIn("Invalid sections", rendered)
        self.assertIn("Warning sections", rendered)
        self.assertIn("SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS", rendered)
        self.assertGreaterEqual(code.call_count, 1)
        self.assertIn("MART_SECTION_DECISION_CURRENT", code.call_args_list[0].args[0])

    def test_setup_health_persists_and_loads_from_snowflake_when_available(self):
        from sections import decision_workspace_setup_health as setup_health

        class PersistSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "PersistSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                current = self.sql_calls[-1]
                if "ORDER BY EVENT_TS DESC" in current:
                    return [{
                        "STATUS": "SUCCESS",
                        "USER_MESSAGE": "Decision summaries initialized.",
                        "GLOBAL_STATUS": "SUCCESS",
                        "SELECTED_SCOPE_STATUS": "SUCCESS",
                        "CURRENT_SECTION_STATUS": "SUCCESS",
                        "SELECTED_PROCEDURE": "SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS",
                        "FALLBACK_USED": False,
                        "CURRENT_PACKET_COUNT": 6,
                        "SECTIONS_PRESENT": ["Executive Landing"],
                        "MISSING_SECTIONS": [],
                        "DUPLICATE_CURRENT_KEYS": 0,
                        "STALE_SECTIONS": [],
                        "DATA_GAP_SECTIONS": [],
                        "MISSING_METRIC_SECTIONS": [],
                        "DEGRADED_SECTIONS": [],
                        "INVALID_SECTIONS": [],
                        "WARNING_SECTIONS": [],
                        "MAX_PACKET_BYTES": 2048,
                        "REQUESTED_SCOPE": "ALFA / ALL / 7 days",
                        "RESOLVED_SCOPE": "ALFA / ALL / 7 days",
                        "ADMIN_DETAIL": "MART_SECTION_DECISION_CURRENT validated.",
                        "SUGGESTED_REMEDIATION": "None",
                        "ACTOR_ROLE": "SNOW_SYSADMINS",
                        "APP_VERSION": "OVERWATCH Decision Workspace",
                        "PERSISTENCE_STATUS": "persisted",
                        "PERSISTENCE_ERROR": "",
                        "RECORDED_AT": "2026-06-26 12:00:00",
                    }, {
                        "STATUS": "DEGRADED",
                        "USER_MESSAGE": "Decision summaries initialized with setup warnings.",
                        "GLOBAL_STATUS": "DEGRADED",
                        "SELECTED_SCOPE_STATUS": "SUCCESS",
                        "CURRENT_SECTION_STATUS": "SUCCESS",
                        "SELECTED_PROCEDURE": "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL",
                        "FALLBACK_USED": True,
                        "CURRENT_PACKET_COUNT": 5,
                        "SECTIONS_PRESENT": ["Executive Landing"],
                        "MISSING_SECTIONS": ["Security Monitoring"],
                        "DUPLICATE_CURRENT_KEYS": 0,
                        "STALE_SECTIONS": [],
                        "DATA_GAP_SECTIONS": ["Security Monitoring"],
                        "MISSING_METRIC_SECTIONS": [],
                        "DEGRADED_SECTIONS": ["Security Monitoring"],
                        "INVALID_SECTIONS": [],
                        "WARNING_SECTIONS": ["Security Monitoring"],
                        "MAX_PACKET_BYTES": 4096,
                        "REQUESTED_SCOPE": "ALFA / ALL / 7 days",
                        "RESOLVED_SCOPE": "ALFA / ALL / 7 days",
                        "ADMIN_DETAIL": "Historical degraded event.",
                        "SUGGESTED_REMEDIATION": "Review source health.",
                        "ACTOR_ROLE": "SNOW_SYSADMINS",
                        "APP_VERSION": "OVERWATCH Decision Workspace",
                        "PERSISTENCE_STATUS": "persisted",
                        "PERSISTENCE_ERROR": "historical persistence warning",
                        "RECORDED_AT": "2026-06-26 11:45:00",
                    }]
                return []

        state = {}
        session = PersistSession()
        with patch.object(setup_health.st, "session_state", state):
            health = setup_health.record_decision_bootstrap_health(
                status="success",
                user_message="Decision summaries initialized.",
                selected_procedure="SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS",
                admin_detail="MART_SECTION_DECISION_CURRENT validated.",
                session=session,
            )
        self.assertEqual(health.status, "SUCCESS")
        self.assertEqual(health.global_status, "UNKNOWN")
        self.assertEqual(health.persistence_status, "persisted")
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS OVERWATCH_DECISION_SETUP_HEALTH" in call for call in session.sql_calls))
        self.assertTrue(any("ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS GLOBAL_STATUS" in call for call in session.sql_calls))
        self.assertTrue(any("ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS PERSISTENCE_STATUS" in call for call in session.sql_calls))
        self.assertTrue(any("ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS PERSISTENCE_ERROR" in call for call in session.sql_calls))
        self.assertTrue(any("INSERT INTO OVERWATCH_DECISION_SETUP_HEALTH" in call for call in session.sql_calls))
        insert_sql = "\n".join(session.sql_calls)
        self.assertIn("GLOBAL_STATUS", insert_sql)
        self.assertIn("SELECTED_SCOPE_STATUS", insert_sql)
        self.assertIn("CURRENT_SECTION_STATUS", insert_sql)
        self.assertIn("DEGRADED_SECTIONS", insert_sql)
        self.assertIn("INVALID_SECTIONS", insert_sql)
        self.assertIn("WARNING_SECTIONS", insert_sql)
        self.assertIn("PERSISTENCE_STATUS", insert_sql)
        self.assertIn("PERSISTENCE_ERROR", insert_sql)

        state.clear()
        with patch.object(setup_health.st, "session_state", state):
            loaded = setup_health.load_decision_setup_health(session=session)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.selected_procedure, "SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS")
        self.assertEqual(loaded.global_status, "SUCCESS")
        self.assertEqual(loaded.selected_scope_status, "SUCCESS")
        self.assertEqual(loaded.current_section_status, "SUCCESS")
        self.assertEqual(loaded.requested_scope, "ALFA / ALL / 7 days")
        self.assertEqual(loaded.persistence_status, "persisted")
        self.assertEqual(loaded.persistence_error, "")
        history = setup_health.load_decision_setup_health_history(session=session)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].status, "SUCCESS")
        self.assertEqual(history[1].status, "DEGRADED")
        self.assertEqual(history[1].persistence_error, "historical persistence warning")

    def test_setup_health_records_local_only_and_unavailable_persistence_status(self):
        from sections import decision_workspace_setup_health as setup_health

        state: dict[str, object] = {}
        with patch.object(setup_health.st, "session_state", state):
            local = setup_health.record_decision_bootstrap_health(
                status="failed",
                user_message="Decision summaries are not initialized.",
            )
        self.assertEqual(local.status, "FAILED")
        self.assertEqual(local.persistence_status, "local_only")
        self.assertEqual(state[setup_health.SETUP_HEALTH_KEY]["persistence_status"], "local_only")

        class FailingPersistSession:
            def sql(self, text: str) -> "FailingPersistSession":
                return self

            def collect(self) -> list[object]:
                raise RuntimeError("permission denied on setup health table")

        state.clear()
        with patch.object(setup_health.st, "session_state", state):
            unavailable = setup_health.record_decision_bootstrap_health(
                status="degraded",
                user_message="Decision summaries initialized with setup warnings.",
                session=FailingPersistSession(),
            )
        self.assertEqual(unavailable.status, "DEGRADED")
        self.assertEqual(unavailable.persistence_status, "unavailable")
        self.assertIn("permission denied", unavailable.persistence_error)

    def test_fallback_open_setup_health_routes_to_settings_without_raw_sql(self):
        from runtime_state import SIDEBAR_PANEL
        from sections import section_command_rendering
        from sections.decision_workspace_setup_health import SETUP_HEALTH_PANEL_OPEN_KEY
        from sections.section_command_brief import SectionCommandBrief

        def _columns(spec):
            count = int(spec) if isinstance(spec, int) else len(spec)
            return [contextlib.nullcontext() for _ in range(count)]

        def _button(label, *args, **kwargs):
            return label == "Open Setup Health"

        state: dict[str, object] = {}
        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="8 days",
            state="Setup required",
            headline="Summary not initialized",
            summary="No packet row.",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Freshness unavailable",
            loaded_at="",
            fallback_reason="No packet row.",
        )
        with patch.dict(os.environ, {"OVERWATCH_TEST_MODE": "1"}), patch.object(
            section_command_rendering.st,
            "session_state",
            state,
        ), patch.object(
            section_command_rendering.st,
            "html",
        ) as html, patch.object(section_command_rendering.st, "columns", side_effect=_columns), patch.object(
            section_command_rendering.st,
            "button",
            side_effect=_button,
        ), patch.object(section_command_rendering.st, "rerun", side_effect=RuntimeError("rerun")):
            with self.assertRaises(RuntimeError):
                section_command_rendering.render_decision_workspace(
                    brief,
                    key_prefix="open_setup_health",
                    refresh_action=lambda: None,
                )

        rendered = "\n".join(str(call.args[0]) for call in html.call_args_list)
        self.assertEqual(state[SIDEBAR_PANEL], "settings")
        self.assertTrue(state[SETUP_HEALTH_PANEL_OPEN_KEY])
        for raw in ("CALL ", "SP_", "MART_", "FACT_", "ACCOUNT_USAGE"):
            self.assertNotIn(raw, rendered)
        self.assertNotIn("permission denied", rendered.lower())

    def test_fallback_hides_setup_health_action_for_non_admin_role(self):
        from runtime_state import CURRENT_ROLE
        from sections import section_command_rendering
        from sections.section_command_brief import SectionCommandBrief

        labels: list[str] = []

        def _columns(spec):
            count = int(spec) if isinstance(spec, int) else len(spec)
            return [contextlib.nullcontext() for _ in range(count)]

        def _button(label, *args, **kwargs):
            labels.append(str(label))
            return False

        state: dict[str, object] = {CURRENT_ROLE: "PUBLIC"}
        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="8 days",
            state="Setup required",
            headline="Summary not initialized",
            summary="No packet row.",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Freshness unavailable",
            loaded_at="",
            fallback_reason="No packet row.",
        )
        with patch.dict(os.environ, {}, clear=True), patch.object(
            section_command_rendering.st,
            "session_state",
            state,
        ), patch.object(section_command_rendering.st, "html"), patch.object(
            section_command_rendering.st,
            "columns",
            side_effect=_columns,
        ), patch.object(section_command_rendering.st, "button", side_effect=_button):
            section_command_rendering.render_decision_workspace(
                brief,
                key_prefix="no_admin_setup_health",
                refresh_action=lambda: None,
            )

        self.assertIn("Refresh", labels)
        self.assertIn("Initialize summaries", labels)
        self.assertNotIn("Open Setup Health", labels)

    def test_fallback_shows_setup_health_action_for_admin_role(self):
        from runtime_state import CURRENT_ROLE
        from sections import section_command_rendering
        from sections.section_command_brief import SectionCommandBrief

        labels: list[str] = []

        def _columns(spec):
            count = int(spec) if isinstance(spec, int) else len(spec)
            return [contextlib.nullcontext() for _ in range(count)]

        def _button(label, *args, **kwargs):
            labels.append(str(label))
            return False

        state: dict[str, object] = {CURRENT_ROLE: "SNOW_ACCOUNTADMINS"}
        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="8 days",
            state="Setup required",
            headline="Summary not initialized",
            summary="No packet row.",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Freshness unavailable",
            loaded_at="",
            fallback_reason="No packet row.",
        )
        with patch.dict(os.environ, {}, clear=True), patch.object(
            section_command_rendering.st,
            "session_state",
            state,
        ), patch.object(section_command_rendering.st, "html"), patch.object(
            section_command_rendering.st,
            "columns",
            side_effect=_columns,
        ), patch.object(section_command_rendering.st, "button", side_effect=_button):
            section_command_rendering.render_decision_workspace(
                brief,
                key_prefix="admin_setup_health",
                refresh_action=lambda: None,
            )

        self.assertIn("Open Setup Health", labels)

    def test_fallback_hides_setup_health_action_for_empty_production_role(self):
        from sections import section_command_rendering
        from sections.section_command_brief import SectionCommandBrief

        labels: list[str] = []

        def _columns(spec):
            count = int(spec) if isinstance(spec, int) else len(spec)
            return [contextlib.nullcontext() for _ in range(count)]

        def _button(label, *args, **kwargs):
            labels.append(str(label))
            return False

        state: dict[str, object] = {}
        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="8 days",
            state="Setup required",
            headline="Summary not initialized",
            summary="No packet row.",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Freshness unavailable",
            loaded_at="",
            fallback_reason="No packet row.",
        )
        with patch.dict(os.environ, {}, clear=True), patch.object(
            section_command_rendering.st,
            "session_state",
            state,
        ), patch.object(section_command_rendering.st, "html") as html, patch.object(
            section_command_rendering.st,
            "columns",
            side_effect=_columns,
        ), patch.object(section_command_rendering.st, "button", side_effect=_button):
            section_command_rendering.render_decision_workspace(
                brief,
                key_prefix="empty_role_setup_health",
                refresh_action=lambda: None,
            )

        self.assertNotIn("Open Setup Health", labels)
        rendered = "\n".join(str(call.args[0]) for call in html.call_args_list)
        self.assertIn("Ask an administrator", rendered)

    def test_bootstrap_missing_procedure_shows_clean_setup_message(self):
        from sections import decision_workspace_bootstrap as bootstrap

        class MissingProcedureSession:
            def __init__(self) -> None:
                self.sql_calls: list[str] = []

            def sql(self, text: str) -> "MissingProcedureSession":
                self.sql_calls.append(text)
                return self

            def collect(self) -> list[object]:
                return []

        session = MissingProcedureSession()
        state = {bootstrap.BOOTSTRAP_REQUEST_KEY: True}
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: session,
        ), patch.object(bootstrap.st, "warning") as warning:
            bootstrap.maybe_run_decision_workspace_bootstrap("Executive Landing")

        self.assertIn("FROM OVERWATCH_SETTINGS", session.sql_calls[0])
        self.assertIn("SHOW PROCEDURES LIKE 'SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS'", session.sql_calls)
        self.assertIn("SHOW PROCEDURES LIKE 'SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL'", session.sql_calls)
        self.assertIn("SHOW PROCEDURES LIKE 'SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS'", session.sql_calls)
        warning.assert_called_once()
        warning_text = warning.call_args.args[0]
        self.assertIn("Decision summaries are not initialized", warning_text)
        self.assertNotIn("CALL ", warning_text)
        self.assertNotIn("Unknown function", warning_text)

    def test_bootstrap_replays_stored_failure_as_clean_setup_message(self):
        from sections import decision_workspace_bootstrap as bootstrap

        state = {
            bootstrap.BOOTSTRAP_FAILURE_KEY: (
                "Decision summaries could not be initialized. Ask an administrator to run "
                "CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS(); (SQL compilation error: Unknown function "
                "SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS)"
            )
        }
        with patch.object(bootstrap.st, "session_state", state), patch.object(bootstrap.st, "warning") as warning:
            bootstrap.maybe_run_decision_workspace_bootstrap()

        warning.assert_called_once()
        warning_text = warning.call_args.args[0]
        self.assertIn("Decision summaries are not initialized", warning_text)
        self.assertNotIn("CALL ", warning_text)
        self.assertNotIn("Unknown function", warning_text)
        self.assertNotIn("SQL compilation", warning_text)

    def test_bootstrap_unauthorized_shows_compact_admin_instruction(self):
        from sections import decision_workspace_bootstrap as bootstrap

        state = {bootstrap.BOOTSTRAP_REQUEST_KEY: True}
        with patch.object(bootstrap.st, "session_state", state), patch.object(
            bootstrap,
            "lazy_util",
            return_value=lambda *args, **kwargs: None,
        ), patch.object(bootstrap.st, "warning") as warning:
            bootstrap.maybe_run_decision_workspace_bootstrap()

        warning.assert_called_once()
        self.assertIn("Decision summaries are not initialized", warning.call_args.args[0])
        self.assertNotIn("CALL ", warning.call_args.args[0])
        self.assertNotIn("FACT_", warning.call_args.args[0])

    def test_renderer_uses_view_model_not_raw_brief_payload(self):
        renderer = (APP_ROOT / "sections" / "section_command_rendering.py").read_text(encoding="utf-8")
        self.assertNotIn("def _data_trust_summary", renderer)
        self.assertNotIn("brief.freshness_minutes", renderer)
        self.assertNotIn("brief.sources", renderer)
        self.assertNotIn("brief.source_objects", renderer)
        self.assertNotIn("brief.raw_payload", renderer)
        self.assertNotIn("brief.metrics", renderer)
        self.assertNotIn("brief.exceptions", renderer)
        self.assertNotIn("brief.next_actions", renderer)
        self.assertIn("model.source_rows", renderer)
        self.assertIn("model.fallback", renderer)
        self.assertIn("model.fixture_badge_label", renderer)

    def test_decision_workspace_uses_marker_backed_streamlit_container(self):
        renderer = (APP_ROOT / "sections" / "section_command_rendering.py").read_text(encoding="utf-8")
        marker_idx = renderer.index("ow-decision-workspace-marker")
        breadcrumb_idx = renderer.index("st.html(_breadcrumb_html(parts))")
        hero_idx = renderer.index("ow-decision-hero ow-decision-hero-copy-only")
        trust_idx = renderer.index("_render_model_trust_footer(model)")
        self.assertLess(marker_idx, breadcrumb_idx)
        self.assertLess(breadcrumb_idx, hero_idx)
        self.assertLess(hero_idx, trust_idx)
        self.assertNotIn('st.markdown("</section>"', renderer)
        self.assertNotIn('<section class="ow-decision-workspace"', renderer)
        self.assertIn('role="region"', renderer)

    def test_shared_decision_evidence_panel_contract_exists_and_is_used(self):
        shell = (APP_ROOT / "sections" / "shell_helpers.py").read_text(encoding="utf-8")
        self.assertIn("def render_decision_evidence_panel", shell)
        for relative in (
            "security_posture_overview_view.py",
            "alert_center.py",
            "cost_contract_overview_floor.py",
            "dba_control_room/render.py",
        ):
            source = (APP_ROOT / "sections" / relative).read_text(encoding="utf-8")
            self.assertIn("render_decision_evidence_panel", source, relative)

    def test_daily_diagnostics_are_shared_gate_on_primary_surfaces(self):
        for relative in (
            "security_posture_overview_view.py",
            "alert_center.py",
            "cost_contract.py",
            "dba_control_room/render.py",
        ):
            source = (APP_ROOT / "sections" / relative).read_text(encoding="utf-8")
            self.assertIn("should_render_daily_diagnostics", source, relative)

    def test_renderer_uses_single_decision_workspace_control_contract(self):
        renderer = (APP_ROOT / "sections" / "section_command_rendering.py").read_text(encoding="utf-8")
        controls = (APP_ROOT / "sections" / "decision_workspace_controls.py").read_text(encoding="utf-8")
        self.assertNotIn("CommandBriefControlSet", renderer)
        self.assertIn("DecisionWorkspaceControls", renderer)
        self.assertIn("class DecisionWorkspaceControls", controls)
        self.assertIn("CommandBriefDetailAction", controls)

    def test_refresh_lives_in_hero_contract_without_detached_refresh_class(self):
        renderer = (APP_ROOT / "sections" / "section_command_rendering.py").read_text(encoding="utf-8")
        self.assertNotIn("ow-decision-hero-refresh-control", renderer)
        self.assertIn("ow-decision-refresh-inline", renderer)
        self.assertIn("controls.refresh_packet()", renderer)

    def test_fallback_panel_keeps_packet_refresh_action(self):
        from sections import section_command_rendering
        from sections.section_command_brief import SectionCommandBrief

        calls = {"refresh": 0}

        def _columns(spec):
            count = int(spec) if isinstance(spec, int) else len(spec)
            return [contextlib.nullcontext() for _ in range(count)]

        def _button(label, *args, **kwargs):
            return label == "Refresh"

        brief = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="ALL",
            window_label="8 days",
            state="Offline",
            headline="Summary unavailable",
            summary="Offline fallback",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Freshness unavailable",
            loaded_at="",
            fallback_reason="Snowflake offline",
            raw_payload={"offline": True},
        )
        with patch.object(section_command_rendering.st, "html"), patch.object(
            section_command_rendering.st,
            "columns",
            side_effect=_columns,
        ), patch.object(section_command_rendering.st, "button", side_effect=_button), patch.object(
            section_command_rendering.st,
            "rerun",
        ) as rerun:
            section_command_rendering.render_decision_workspace(
                brief,
                key_prefix="fallback_refresh",
                refresh_action=lambda: calls.__setitem__("refresh", calls["refresh"] + 1),
            )

        self.assertEqual(calls["refresh"], 1)
        rerun.assert_called()

    def test_primary_sections_do_not_render_standalone_evidence_settings(self):
        section_files = (
            "dba_control_room/render.py",
            "alert_center.py",
            "cost_contract.py",
            "workload_operations.py",
            "security_posture.py",
            "executive_landing_shell.py",
        )
        for relative in section_files:
            source = (APP_ROOT / "sections" / relative).read_text(encoding="utf-8")
            self.assertNotIn('render_evidence_settings("Evidence settings"', source, relative)
        renderer = (APP_ROOT / "sections" / "section_command_rendering.py").read_text(encoding="utf-8")
        self.assertIn("settings_renderer = controls.evidence_action.settings_renderer", renderer)

    def test_view_model_owns_source_and_fallback_display_state(self):
        view_model = (APP_ROOT / "sections" / "decision_workspace_view_model.py").read_text(encoding="utf-8")
        self.assertIn("class DecisionSourceRow", view_model)
        self.assertIn("class DecisionFallbackView", view_model)
        self.assertIn("source_rows=source_rows", view_model)
        self.assertIn("fallback=fallback", view_model)
        self.assertIn("fixture_badge_label=", view_model)

    def test_refresh_and_evidence_callbacks_touch_separate_state(self):
        from sections.decision_workspace_controls import make_decision_refresh_action, make_evidence_action

        state: dict[str, object] = {}
        with patch("sections.decision_workspace_controls.st.session_state", state):
            refresh = make_decision_refresh_action("Cost & Contract")
            refresh()
            self.assertEqual(state, {"cost_contract_command_brief_force_refresh": True})

            action = make_evidence_action(
                "Cost & Contract",
                "Cost Overview",
                label="Load Cost Evidence",
                state_key="cost_contract_command_brief_load_evidence",
            )
            self.assertIsNotNone(action)
            action.callback()

        self.assertTrue(state["cost_contract_command_brief_force_refresh"])
        self.assertTrue(state["cost_contract_command_brief_load_evidence"])

    def test_evidence_action_cannot_be_packet_refresh(self):
        from sections.decision_workspace_controls import make_evidence_action

        action = make_evidence_action(
            "Security Monitoring",
            "Security Overview",
            label="Refresh Security Summary",
            state_key="security_posture_command_brief_force_refresh",
        )
        self.assertIsNone(action)

    def test_owner_and_sla_fallbacks_are_honest(self):
        from sections.decision_workspace_view_model import build_decision_workspace_view_model
        from sections.section_command_brief import SectionCommandBrief, SectionCommandSignal

        brief = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Spend needs review",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 8m ago",
            loaded_at="2026-06-25T10:08:00",
            exceptions=(
                SectionCommandSignal(severity="High", signal="Missing owner and SLA"),
                SectionCommandSignal(severity="High", signal="Owner gap", owner_gap=True),
                SectionCommandSignal(severity="Info", signal="Explicit route", owner_route="Assigned", sla_state="On track"),
            ),
        )
        model = build_decision_workspace_view_model(brief, current_workflow="Overview")
        self.assertEqual(model.findings[0].owner, "Owner unavailable")
        self.assertEqual(model.findings[0].sla, "SLA unavailable")
        self.assertEqual(model.findings[1].owner, "Owner gap")
        self.assertEqual(model.findings[2].owner, "Assigned")
        self.assertEqual(model.findings[2].sla, "On track")
        aged = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Spend needs review",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 8m ago",
            loaded_at="2026-06-25T10:08:00",
            exceptions=(SectionCommandSignal(severity="Watch", signal="Aged without SLA", age_minutes=80),),
        )
        self.assertEqual(build_decision_workspace_view_model(aged, current_workflow="Overview").findings[0].sla, "No SLA")

    def test_decision_workspace_renders_entity_owner_age_sla_without_evidence_query(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandSignal
        from sections.decision_workspace_view_model import build_decision_workspace_view_model

        brief = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Spend needs review",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 8m ago",
            loaded_at="2026-06-25T10:08:00",
            exceptions=(
                SectionCommandSignal(
                    severity="High",
                    signal="Warehouse driver",
                    entity="PROD_WH",
                    entity_type="warehouse",
                    entity_id="PROD_WH",
                    detail="$6.7K movement",
                    owner_name="Warehouse Owner",
                    owner_id="owner-123",
                    first_seen_ts="2026-06-25 09:00:00",
                    due_ts="2026-06-25 12:00:00",
                    age_minutes=68,
                    sla_state="Due in 2h",
                    evidence_id="COST-EVIDENCE-1",
                    evidence_source="FACT_COST_DAILY",
                    evidence_query="SELECT * FROM ADMIN_ONLY",
                ),
            ),
        )
        model = build_decision_workspace_view_model(brief, current_workflow="Cost Overview")
        finding = model.findings[0]
        self.assertEqual(finding.entity_type, "warehouse")
        self.assertEqual(finding.entity_id, "PROD_WH")
        self.assertEqual(finding.owner, "Warehouse Owner")
        self.assertIn("Seen 1h ago", finding.first_seen_label)
        self.assertIn("Due in 2h", finding.due_label)
        self.assertEqual(finding.evidence_id, "COST-EVIDENCE-1")

        markup = _render_markup(brief)
        self.assertIn("PROD_WH", markup)
        self.assertIn("Warehouse Owner", markup)
        self.assertIn("Seen 1h ago", markup)
        self.assertIn("Due in 2h", markup)
        self.assertIn("Evidence COST-EVIDENCE-1", markup)
        self.assertNotIn("SELECT * FROM ADMIN_ONLY", markup)

    def test_evidence_action_applies_safe_finding_target_without_executing_query(self):
        from sections.decision_workspace_controls import apply_finding_evidence_target
        from sections.decision_workspace_view_model import DecisionFinding

        state: dict[str, object] = {}
        finding = DecisionFinding(
            severity="High",
            signal="Warehouse driver",
            entity_type="warehouse",
            entity_id="PROD_WH",
            entity_name="PROD_WH",
            evidence_id="COST-EVIDENCE-1",
            evidence_source="FACT_COST_DAILY",
            evidence_query="SELECT * FROM ADMIN_ONLY",
        )
        with patch("sections.decision_workspace_controls.st.session_state", state):
            target = apply_finding_evidence_target(finding, "Cost & Contract", "Cost Overview")
        self.assertEqual(target["evidence_id"], "COST-EVIDENCE-1")
        self.assertEqual(state["cc_explorer_lens"], "Warehouse")
        self.assertEqual(state["cost_contract_evidence_entity_filter"], "PROD_WH")
        self.assertNotIn("SELECT * FROM ADMIN_ONLY", str(state))

    def test_primary_route_action_applies_top_finding_target(self):
        from sections import section_command_rendering
        from sections.section_command_brief import SectionCommandAction, SectionCommandBrief, SectionCommandSignal

        state: dict[str, object] = {}
        brief = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Spend needs review",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 8m ago",
            loaded_at="2026-06-25T10:08:00",
            exceptions=(
                SectionCommandSignal(
                    severity="High",
                    signal="Warehouse driver",
                    entity="PROD_WH",
                    entity_type="warehouse",
                    entity_id="PROD_WH",
                    evidence_id="COST-EVIDENCE-1",
                    route_key="cost_contract_explorer_warehouse",
                    evidence_query="SELECT * FROM ADMIN_ONLY",
                ),
            ),
            next_actions=(
                SectionCommandAction(
                    "Open Warehouse Drivers",
                    "Open matching driver",
                    "Cost & Contract",
                    "Cost Explorer",
                    cta="Open Warehouse Drivers",
                    route_key="cost_contract_explorer_warehouse",
                ),
            ),
        )

        def _button(label, *args, **kwargs):
            return str(label).startswith("Open Warehouse Drivers")

        with patch.object(section_command_rendering.st, "session_state", state), patch.object(
            section_command_rendering.st,
            "html",
        ), patch.object(section_command_rendering.st, "markdown"), patch.object(
            section_command_rendering.st,
            "columns",
            side_effect=lambda spec: [contextlib.nullcontext() for _ in range(int(spec) if isinstance(spec, int) else len(spec))],
        ), patch.object(section_command_rendering.st, "button", side_effect=_button), patch.object(
            section_command_rendering,
            "apply_command_brief_route",
            return_value=True,
        ), patch.object(section_command_rendering.st, "rerun"):
            section_command_rendering.render_decision_workspace(
                brief,
                key_prefix="route_target",
                current_workflow="Cost Overview",
            )

        self.assertEqual(state["decision_workspace_evidence_target"]["entity_id"], "PROD_WH")
        self.assertEqual(state["cost_contract_evidence_entity_filter"], "PROD_WH")
        self.assertEqual(state["cc_explorer_lens"], "Warehouse")
        self.assertNotIn("SELECT * FROM ADMIN_ONLY", str(state))

    def test_secondary_route_action_applies_matching_finding_target(self):
        from sections import section_command_rendering
        from sections.section_command_brief import SectionCommandAction, SectionCommandBrief, SectionCommandSignal

        state: dict[str, object] = {}
        brief = SectionCommandBrief(
            section="Cost & Contract",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Spend needs review",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 8m ago",
            loaded_at="2026-06-25T10:08:00",
            exceptions=(
                SectionCommandSignal(
                    severity="High",
                    signal="Cortex risk",
                    entity="Cortex",
                    entity_type="service",
                    entity_id="CORTEX",
                    route_key="cost_contract_cortex_ai",
                ),
                SectionCommandSignal(
                    severity="High",
                    signal="Warehouse driver",
                    entity="PROD_WH",
                    entity_type="warehouse",
                    entity_id="PROD_WH",
                    route_key="cost_contract_explorer_warehouse",
                ),
            ),
            next_actions=(
                SectionCommandAction("Review Cortex", "Open Cortex", "Cost & Contract", "Cortex AI", cta="Review Cortex", route_key="cost_contract_cortex_ai"),
                SectionCommandAction("Open Warehouse Drivers", "Open driver", "Cost & Contract", "Cost Explorer", cta="Open Warehouse Drivers", route_key="cost_contract_explorer_warehouse"),
            ),
        )

        def _button(label, *args, **kwargs):
            return str(label).startswith("Open Warehouse Drivers")

        with patch.object(section_command_rendering.st, "session_state", state), patch.object(
            section_command_rendering.st,
            "html",
        ), patch.object(section_command_rendering.st, "markdown"), patch.object(
            section_command_rendering.st,
            "columns",
            side_effect=lambda spec: [contextlib.nullcontext() for _ in range(int(spec) if isinstance(spec, int) else len(spec))],
        ), patch.object(section_command_rendering.st, "button", side_effect=_button), patch.object(
            section_command_rendering,
            "apply_command_brief_route",
            return_value=True,
        ), patch.object(section_command_rendering.st, "rerun"):
            section_command_rendering.render_decision_workspace(
                brief,
                key_prefix="secondary_route_target",
                current_workflow="Cost Overview",
            )

        self.assertEqual(state["decision_workspace_evidence_target"]["entity_id"], "PROD_WH")
        self.assertEqual(state["cc_explorer_lens"], "Warehouse")
        self.assertNotEqual(state["decision_workspace_evidence_target"]["entity_id"], "CORTEX")

    def test_evidence_row_filter_consumes_section_targets(self):
        from sections import decision_workspace_controls as controls

        rows = pd.DataFrame(
            [
                {"EVENT_ID": "EVT-1", "ALERT_KEY": "ALERT-A", "WAREHOUSE_NAME": "DEV_WH"},
                {"EVENT_ID": "EVT-2", "ALERT_KEY": "ALERT-B", "WAREHOUSE_NAME": "PROD_WH"},
            ]
        )
        state = {
            "alert_center_evidence_target": {
                "entity_type": "alert",
                "entity_id": "ALERT-B",
                "evidence_id": "EVT-2",
            }
        }
        with patch.object(controls.st, "session_state", state):
            filtered, label = controls.filter_evidence_rows_for_target(rows, "Alert Center")
        self.assertEqual(label, "alert: ALERT-B")
        self.assertEqual(filtered["EVENT_ID"].tolist(), ["EVT-2"])

    def test_evidence_row_filter_returns_compact_empty_target_state(self):
        from sections import decision_workspace_controls as controls

        rows = pd.DataFrame([{"USER_NAME": "JDOE", "ROLE_NAME": "ANALYST"}])
        state = {
            "security_posture_evidence_target": {
                "entity_type": "role",
                "entity_id": "SECURITYADMIN",
            }
        }
        with patch.object(controls.st, "session_state", state):
            filtered, label = controls.filter_evidence_rows_for_target(rows, "Security Monitoring")
        self.assertEqual(label, "role: SECURITYADMIN")
        self.assertTrue(filtered.empty)

    def test_query_search_consumes_workload_finding_target(self):
        source = (ROOT / ".overwatch_final" / "sections" / "query_search.py").read_text(encoding="utf-8")
        self.assertIn("workload_operations_evidence_target", source)
        self.assertIn("target_warehouse", source)
        self.assertIn("target_wh_cl", source)
        self.assertIn("qs_autorun", source)
        self.assertNotIn("EVIDENCE_QUERY", source)

    def test_targeted_evidence_paths_do_not_fall_through_to_legacy_boards(self):
        cost = (ROOT / ".overwatch_final" / "sections" / "cost_contract_overview_floor.py").read_text(encoding="utf-8")
        security = (ROOT / ".overwatch_final" / "sections" / "security_posture_overview_view.py").read_text(encoding="utf-8")
        dba = (ROOT / ".overwatch_final" / "sections" / "dba_control_room" / "render.py").read_text(encoding="utf-8")

        cost_guard = cost.index("if not refresh_cost:")
        security_guard = security.index("if target_label:")
        dba_guard = dba.index("if target_label:")

        self.assertLess(cost_guard, cost.index("_render_cost_splash(", cost_guard))
        self.assertLess(security.index("return", security_guard), security.index("_render_security_watch_floor(", security_guard))
        self.assertLess(dba.index("return", dba_guard), dba.index("_render_dba_action_brief(", dba_guard))

    def test_trend_metadata_flows_into_view_model_and_markup(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandMetric
        from sections.decision_workspace_view_model import build_decision_workspace_view_model

        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="Trend quality",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 8m ago",
            loaded_at="2026-06-25T10:08:00",
            metrics=(
                SectionCommandMetric(
                    key="total_spend",
                    label="Total Spend",
                    value="",
                    numeric_value=100,
                    metric_format="currency",
                    trend_points=tuple({"ts": f"2026-06-{day:02d}", "value": day} for day in range(19, 26)),
                    trend_period="daily",
                    trend_point_count=7,
                    trend_quality="partial",
                    zero_fill_policy="count_zero_fill",
                ),
            ),
        )
        model = build_decision_workspace_view_model(brief, current_workflow="Overview")
        self.assertEqual(model.metric_cells[0].trend_period, "daily")
        self.assertEqual(model.metric_cells[0].trend_point_count, 7)
        self.assertEqual(model.metric_cells[0].trend_quality, "partial")
        self.assertEqual(model.metric_cells[0].zero_fill_policy, "count_zero_fill")
        markup = _render_markup(brief)
        self.assertEqual(markup.count("partial source history"), 1)
        self.assertIn("Trend history: 1 partial", markup)

    def test_trend_unavailable_is_single_compact_message(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandMetric

        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="7 days",
            state="At Risk",
            headline="No trend points",
            summary="Packet summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 8m ago",
            loaded_at="2026-06-25T10:08:00",
            metrics=(
                SectionCommandMetric(key="total_spend", label="Total Spend", value="", numeric_value=100, metric_format="currency"),
                SectionCommandMetric(key="open_actions", label="Open Actions", value="", numeric_value=2, metric_format="count"),
            ),
        )
        markup = _render_markup(brief)
        self.assertEqual(markup.count("Trend data not available for this packet."), 1)
        self.assertNotIn("ow-trend-unavailable", markup)

    def test_decision_window_uses_inclusive_global_dates(self):
        from datetime import date
        from sections import decision_workspace_scope

        values = {
            "global_start_date": date(2026, 6, 18),
            "global_end_date": date(2026, 6, 25),
        }
        with patch.object(decision_workspace_scope, "get_state", side_effect=lambda key, default=None: values.get(key, default)):
            self.assertEqual(decision_workspace_scope.active_decision_window_days(), 8)
        with patch.object(decision_workspace_scope, "get_state", return_value=None):
            self.assertEqual(decision_workspace_scope.active_decision_window_days(11), 11)

    def test_primary_sections_use_shared_decision_window(self):
        section_files = (
            "executive_landing_shell.py",
            "dba_control_room/render.py",
            "alert_center.py",
            "cost_contract.py",
            "workload_operations.py",
            "security_posture.py",
        )
        for relative in section_files:
            source = (APP_ROOT / "sections" / relative).read_text(encoding="utf-8")
            self.assertIn("active_decision_window_days", source, relative)
        workload = (APP_ROOT / "sections" / "workload_operations.py").read_text(encoding="utf-8")
        self.assertNotIn('autoload_section_command_brief("Workload Operations", company, environment, 7', workload)

    def test_primary_section_sources_do_not_send_users_to_another_button(self):
        forbidden = (
            "available in the Decision Brief",
            "Use Refresh Cost Summary in the Decision Brief",
            "Refresh Decision Brief",
        )
        section_files = (
            "executive_landing_shell.py",
            "dba_control_room/render.py",
            "alert_center.py",
            "cost_contract.py",
            "workload_operations.py",
            "security_posture.py",
        )
        combined = "\n".join((APP_ROOT / "sections" / relative).read_text(encoding="utf-8") for relative in section_files)
        for needle in forbidden:
            self.assertNotIn(needle, combined)

    def test_html_snapshot_fallback_has_workspace_without_legacy_instruction_copy(self):
        from sections.section_command_brief import SectionCommandAction, SectionCommandBrief, SectionCommandMetric

        brief = SectionCommandBrief(
            section="Executive Landing",
            company="ALFA",
            environment="ALL",
            window_label="8 days",
            state="At Risk",
            headline="Packet-driven headline",
            summary="Packet-driven summary",
            source="MART_SECTION_DECISION_CURRENT",
            freshness_label="Updated 8m ago",
            loaded_at="2026-06-25T10:08:00",
            metrics=(
                SectionCommandMetric(key="total_spend", label="Total Spend", value="", numeric_value=12345, metric_format="currency"),
                SectionCommandMetric(key="critical_high_issues", label="Critical / High", value="", numeric_value=2, metric_format="count"),
                SectionCommandMetric(key="open_actions", label="Open Actions", value="", numeric_value=9, metric_format="count"),
                SectionCommandMetric(key="cortex_spend", label="Cortex AI Spend", value="", numeric_value=987, metric_format="currency"),
            ),
            next_actions=(SectionCommandAction(label="Review Cortex", detail="Review Cortex details", cta="Review Cortex", route_key="cost_cortex_ai"),),
        )
        markup = _render_markup(brief)
        self.assertIn("ow-decision-workspace", markup)
        self.assertIn("What needs attention", markup)
        self.assertIn("Data Trust", markup)
        self.assertNotIn("available in the Decision Brief", markup)
        self.assertNotIn("Refresh Decision Brief", markup)

    def test_html_snapshot_all_primary_sections_have_workspace_without_legacy_card_wall(self):
        from sections.section_command_brief import SectionCommandAction, SectionCommandBrief, SectionCommandMetric

        forbidden = (
            "ow-kpi-hero-card",
            "ow-shell-snapshot-card",
            "ow-action-card",
            "ow-command-deck",
            "ow-executive-command-hero",
            "Pending",
            "available in the Decision Brief",
        )
        for section in self.VALIDATION_SECTIONS:
            with self.subTest(section=section):
                brief = SectionCommandBrief(
                    section=section,
                    company="ALFA",
                    environment="ALL",
                    window_label="8 days",
                    state="At Risk",
                    headline=f"{section} packet headline",
                    summary="Packet-driven summary",
                    source="MART_SECTION_DECISION_CURRENT",
                    freshness_label="Updated 8m ago",
                    loaded_at="2026-06-25T10:08:00",
                    metrics=(
                        SectionCommandMetric(key="total_spend", label="Total Spend", value="", numeric_value=12345, metric_format="currency"),
                        SectionCommandMetric(key="critical_high_issues", label="Critical / High", value="", numeric_value=2, metric_format="count"),
                        SectionCommandMetric(key="open_actions", label="Open Actions", value="", numeric_value=9, metric_format="count"),
                        SectionCommandMetric(key="cortex_spend", label="Cortex AI Spend", value="", numeric_value=987, metric_format="currency"),
                    ),
                    next_actions=(SectionCommandAction(label="Open detail", detail="Route", cta="Open detail", route_key="executive_overview"),),
                )
                markup = _render_markup(brief)
                self.assertIn("ow-decision-workspace", markup)
                self.assertIn("What needs attention", markup)
                self.assertIn("Recommended actions", markup)
                self.assertIn("Data Trust", markup)
                for token in forbidden:
                    self.assertNotIn(token, markup)


if __name__ == "__main__":
    unittest.main()
