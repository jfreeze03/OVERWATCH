from pathlib import Path
import contextlib
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
                    "SLA_STATE": "Due soon",
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

    with patch.object(section_command_rendering.st, "html") as html, patch.object(
        section_command_rendering.st,
        "markdown",
    ), patch.object(
        section_command_rendering.st,
        "columns",
        return_value=[contextlib.nullcontext(), contextlib.nullcontext()],
    ), patch.object(section_command_rendering.st, "button", return_value=False), patch.object(
        section_command_rendering.st,
        "expander",
        return_value=contextlib.nullcontext(),
    ):
        section_command_rendering.render_section_command_brief(brief, key_prefix="binding")

    return "\n".join(str(call.args[0]) for call in html.call_args_list)


class DecisionWorkspaceDataBindingTests(unittest.TestCase):
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
        self.assertIn("Trend unavailable", markup_a)

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
        with patch.object(section_command_rendering.st, "session_state", state), patch.object(
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

        self.assertEqual(session.sql_calls, ["CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();"])
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
            def sql(self, text: str) -> "FailingSession":
                return self

            def collect(self) -> list[object]:
                raise RuntimeError("no grant")

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
        self.assertIn("CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();", warning.call_args.args[0])
        self.assertNotIn("FACT_", warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
