from pathlib import Path
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
        self.assertIn("What to do next", html)
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


if __name__ == "__main__":
    unittest.main()
