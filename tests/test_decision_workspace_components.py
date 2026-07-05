from pathlib import Path
import math
import sys
import unittest
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class DecisionWorkspaceComponentsTests(unittest.TestCase):
    def test_command_brief_renders_core_surfaces_without_raw_sources(self):
        from sections.decision_workspace_components import render_command_brief

        model = SimpleNamespace(
            section="Cost & Contract",
            workflow="Overview",
            state="Watch",
            summary="Spend is inside the current action threshold.",
            metric_cells=(
                SimpleNamespace(label="Total Spend", value="$12.4K", detail="MART_COST_DAILY"),
                SimpleNamespace(label="Cortex AI Spend", value="$430", detail="FACT_CORTEX_DAILY", tone="cortex"),
                SimpleNamespace(label="Open Actions", value="3", detail="Evidence loads on request"),
            ),
            findings=(
                SimpleNamespace(
                    severity="High",
                    signal="Warehouse pressure",
                    detail="Review queue and spill evidence",
                    entity_name="WH_XS",
                    owner="Cost",
                    sla="Due soon",
                ),
            ),
            actions=(SimpleNamespace(label="Load Cost Evidence", cta="Load Cost Evidence"),),
            trust=SimpleNamespace(
                mode_label="Packet",
                freshness_label="Updated 8m ago",
                target_label="Target freshness: 60m",
                coverage_label="4/4 required sources",
                quality_label="High",
            ),
            source_rows=(SimpleNamespace(source_key="MART_COST_DAILY", source_object="MART_COST_DAILY"),),
        )

        html = render_command_brief(model)

        self.assertIn("ow-kit-command-brief", html)
        self.assertEqual(html.count("ow-kit-command-brief"), 1)
        self.assertIn("Spend is inside the current action threshold.", html)
        self.assertIn("Cost &amp; Contract", html)
        self.assertIn("Total Spend", html)
        self.assertIn("What needs attention", html)
        self.assertIn("What changed", html)
        self.assertNotIn("ow-kit-action-panel", html)
        self.assertNotIn('data-action-like="false"', html)
        self.assertIn("Data Trust", html)
        self.assertIn("Evidence cache", html)
        self.assertNotIn("MART_COST_DAILY", html)
        self.assertNotIn("FACT_CORTEX_DAILY", html)

    def test_metric_row_allows_three_to_five_metrics(self):
        from sections.decision_workspace_components import render_metric_row

        metrics = tuple(SimpleNamespace(label=f"Metric {idx}", value=idx, detail="Packet") for idx in range(5))
        html = render_metric_row(metrics)

        self.assertIn('data-metric-count="5"', html)
        self.assertEqual(html.count("ow-kit-metric-card"), 5)

    def test_evidence_empty_state_is_compact_and_daily_safe(self):
        from sections.decision_workspace_components import render_evidence_empty_state

        html = render_evidence_empty_state(detail="Rows load from MART_ALERT_EVIDENCE_RECENT after click.")

        self.assertIn("Evidence loads on request", html)
        self.assertIn("Evidence cache", html)
        self.assertNotIn("MART_ALERT_EVIDENCE_RECENT", html)

    def test_ranked_and_area_panels_emit_streamlit_safe_markup(self):
        from sections.decision_workspace_components import render_area_trend_panel, render_ranked_bar_panel

        ranked = render_ranked_bar_panel(
            "Top drivers",
            [{"label": "Warehouse A", "value": 10}, {"label": "Warehouse B", "value": 5}],
        )
        area = render_area_trend_panel("Spend movement", [{"value": 1}, {"value": 2}, {"value": 3}])

        self.assertIn("ow-kit-ranked-panel", ranked)
        self.assertIn("ow-kit-ranked-row", ranked)
        self.assertIn("ow-kit-area-panel", area)
        self.assertIn("<svg", area)

    def test_change_panel_respects_governed_trend_metadata(self):
        from sections.decision_workspace_components import render_change_panel

        model = SimpleNamespace(
            trends=(
                SimpleNamespace(
                    label="Spend movement",
                    value="+4.2%",
                    detail="Run-rate only",
                    trend_period="7d",
                    trend_point_count=0,
                    trend_quality="partial",
                    zero_fill_policy="explicit zero only",
                ),
            )
        )

        html = render_change_panel(model)

        self.assertIn("Spend movement", html)
        self.assertIn("Run-rate only", html)
        self.assertIn("Period: 7d", html)
        self.assertIn("Trend unavailable", html)
        self.assertIn("Zero policy: explicit zero only", html)
        self.assertIn("partial source history", html)

    def test_change_panel_without_trends_does_not_imply_history(self):
        from sections.decision_workspace_components import render_change_panel

        html = render_change_panel(SimpleNamespace(trends=()))

        self.assertIn("Trend unavailable", html)
        self.assertIn("No governed trend metadata", html)

    def test_command_view_model_treats_nan_packet_values_as_unavailable(self):
        from sections.decision_workspace_view_model import build_decision_workspace_view_model

        brief = SimpleNamespace(
            section="Alert Center",
            state="Ready",
            stale=False,
            fallback_reason="",
            headline="Alert Center ready",
            summary="Review alert activity.",
            freshness_minutes=math.nan,
            target_freshness_minutes=math.nan,
            missing_source_count=math.nan,
            required_source_count=1,
            available_source_count=1,
            confidence="",
            data_availability_state="",
            raw_payload={},
            metrics=(
                SimpleNamespace(
                    key="active_alerts",
                    label="Active alerts",
                    numeric_value=math.nan,
                    text_value="",
                    value="",
                    metric_format="count",
                    delta_percent=math.nan,
                    trend_point_count=math.nan,
                    trend_points=(),
                ),
            ),
            exceptions=(SimpleNamespace(signal="Alert review", age_minutes=math.nan),),
            next_actions=(),
            sources=(
                SimpleNamespace(
                    source_key="alert_events",
                    available=True,
                    stale=False,
                    age_minutes=math.nan,
                    target_freshness_minutes=math.nan,
                    required=True,
                    confidence="",
                    supports_environment=True,
                    environment_scope_mode="exact",
                    gap_reason="",
                ),
            ),
        )

        model = build_decision_workspace_view_model(brief, current_workflow="Open")

        self.assertEqual(model.trust.freshness_label, "Freshness unavailable")
        self.assertEqual(model.metric_cells[0].value, "Unavailable")
        self.assertEqual(model.source_rows[0].age_label, "unknown age")
        self.assertEqual(model.findings[0].first_seen_label, "")

    def test_time_series_chart_omits_null_title(self):
        import pandas as pd
        from utils.display import build_time_series_chart, time_series_chart_frame

        frame = time_series_chart_frame(
            pd.DataFrame({"DAY": ["2026-07-01"], "VALUE": [1.5]}),
            "DAY",
            "VALUE",
        )

        chart = build_time_series_chart(frame, "DAY", "VALUE", title="")
        spec = chart.to_dict(validate=True)

        self.assertNotIn("title", spec)


if __name__ == "__main__":
    unittest.main()
