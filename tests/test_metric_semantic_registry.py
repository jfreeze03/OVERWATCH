from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class MetricSemanticRegistryTests(unittest.TestCase):
    def test_all_primary_metrics_have_semantic_entries(self):
        from sections.metric_semantic_registry import PRIMARY_METRIC_KEYS, get_metric_semantic

        missing = [
            (section, metric_key)
            for section, metric_keys in PRIMARY_METRIC_KEYS.items()
            for metric_key in metric_keys
            if get_metric_semantic(section, metric_key) is None
        ]
        self.assertEqual(missing, [])

    def test_workload_pipeline_failure_outlier_is_blocked(self):
        from sections.section_command_brief import SectionCommandMetric
        from sections.metric_semantic_registry import validate_metric_semantics

        rows = validate_metric_semantics(
            "Workload Operations",
            (
                SectionCommandMetric(
                    key="pipeline_failures",
                    label="Pipeline / Task Failures",
                    value="8B",
                    numeric_value=8_206_653_619,
                    metric_format="integer",
                    unit="events",
                ),
            ),
        )
        pipeline = next(row for row in rows if row["metric_key"] == "pipeline_failures")
        self.assertFalse(pipeline["passed"], pipeline)
        self.assertIn("semantic_outlier", pipeline["failures"])

    def test_workload_queue_pressure_uses_duration_semantics(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandMetric
        from sections.decision_workspace_view_model import build_decision_workspace_view_model

        brief = SectionCommandBrief(
            "Workload Operations",
            "ALFA",
            "ALL",
            "8 days",
            "Watch",
            "Workload pressure is elevated.",
            "Operational view",
            "fixture",
            "Updated now",
            "2026-06-28T00:00:00",
            metrics=(
                SectionCommandMetric(
                    key="failed_queries",
                    label="Failed SQL",
                    value="",
                    numeric_value=2,
                    metric_format="integer",
                    unit="queries",
                ),
                SectionCommandMetric(
                    key="pipeline_failures",
                    label="Pipeline / Task Failures",
                    value="",
                    numeric_value=3,
                    metric_format="integer",
                    unit="events",
                ),
                SectionCommandMetric(
                    key="queue_blocked_pressure",
                    label="Queue / Blocked Pressure",
                    value="",
                    numeric_value=1152,
                    metric_format="integer",
                    unit="events",
                ),
                SectionCommandMetric(
                    key="sla_risk",
                    label="Pipeline Failure Risk",
                    value="",
                    numeric_value=45,
                    metric_format="integer",
                    unit="items",
                ),
            ),
        )

        model = build_decision_workspace_view_model(brief, current_workflow="Workload Overview")
        by_key = {metric.key: metric for metric in model.metric_cells}

        self.assertEqual(by_key["queue_blocked_pressure"].value, "19.2m")
        self.assertEqual(by_key["sla_risk"].value, "45.0%")
        self.assertEqual(by_key["sla_risk"].label, "Pipeline Failure Risk")
        self.assertIn("proxy", by_key["sla_risk"].detail)

    def test_cost_total_pending_state_when_account_billing_metric_unavailable(self):
        from sections.section_command_brief import SectionCommandBrief, SectionCommandMetric
        from sections.decision_workspace_view_model import build_decision_workspace_view_model

        brief = SectionCommandBrief(
            "Cost & Contract",
            "ALFA",
            "ALL",
            "8 days",
            "Watch",
            "Cost posture is inside the current action threshold.",
            "Financial view",
            "fixture",
            "Updated now",
            "2026-06-28T00:00:00",
            metrics=(
                SectionCommandMetric(
                    key="total_spend",
                    label="Total Spend",
                    value="$0",
                    numeric_value=0,
                    metric_format="currency",
                    available=False,
                    availability_state="Billing reconciliation pending",
                ),
                SectionCommandMetric(
                    key="spend_movement_pct",
                    label="Spend Movement",
                    value="0%",
                    numeric_value=0,
                    metric_format="percentage",
                ),
                SectionCommandMetric(
                    key="cortex_spend",
                    label="Cortex AI Spend",
                    value="",
                    numeric_value=7600,
                    metric_format="currency",
                ),
                SectionCommandMetric(
                    key="forecast_run_rate",
                    label="Forecast / Run-rate",
                    value="",
                    numeric_value=1100,
                    metric_format="currency",
                ),
            ),
        )

        model = build_decision_workspace_view_model(brief, current_workflow="Cost Overview")
        by_key = {metric.key: metric for metric in model.metric_cells}
        self.assertEqual(by_key["total_spend"].value, "Billing reconciliation pending")
        self.assertEqual(by_key["cortex_spend"].value, "$7.6K")


if __name__ == "__main__":
    unittest.main()
