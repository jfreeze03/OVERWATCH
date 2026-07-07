from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class MetricRenderMappingAuditTests(unittest.TestCase):
    def test_every_command_brief_metric_has_a_source_mapping(self):
        from tools.contracts.metric_render_mapping_audit import (
            build_metric_render_mapping_results,
            evaluate_metric_render_mapping_gate,
        )

        results = build_metric_render_mapping_results(ROOT)
        gate = evaluate_metric_render_mapping_gate(results)

        self.assertTrue(results["passed"], results["failures"][:5])
        self.assertTrue(gate["passed"], gate["failures"][:5])
        self.assertGreaterEqual(results["row_count"], 291)
        self.assertGreaterEqual(results["semantic_catalog_count"], 216)
        self.assertEqual(results["runtime_model_mapping_count"], 6)
        self.assertEqual(results["summary_mart_mapping_count"], 7)
        for section in (
            "Executive Landing",
            "DBA Control Room",
            "Alert Center",
            "Cost & Contract",
            "Workload Operations",
            "Security Monitoring",
        ):
            with self.subTest(section=section):
                self.assertGreater(results["section_counts"].get(section, 0), 0)

    def test_executive_credit_panels_are_accounted_for(self):
        from tools.contracts.metric_render_mapping_audit import build_metric_render_mapping_results

        results = build_metric_render_mapping_results(ROOT)
        rows = {
            (row["section"], row["surface"], row["metric_key"]): row
            for row in results["rows"]
        }
        for surface, metric_key, required_fields in (
            ("Daily Credit Consumption", "daily_credit_consumption", ("USAGE_DATE", "CREDITS_USED")),
            ("Top Warehouses by Credits", "top_warehouses_by_credits", ("WAREHOUSE_NAME", "CREDITS_USED")),
        ):
            row = rows[("Executive Landing", surface, metric_key)]
            self.assertEqual(row["source_key"], "warehouse_credits")
            for field in required_fields:
                self.assertIn(field, row["source_fields"])
            self.assertEqual(row["mapping_type"], "runtime_model_mapping")

    def test_subsection_summary_marts_are_accounted_for(self):
        from tools.contracts.metric_render_mapping_audit import build_metric_render_mapping_results

        results = build_metric_render_mapping_results(ROOT)
        rows = {
            row["metric_key"]: row
            for row in results["rows"]
            if row.get("mapping_type") == "summary_mart_mapping"
        }

        for key in (
            "query_daily_summary",
            "warehouse_daily_credits",
            "cortex_daily_usage",
            "login_security_daily",
            "task_status_daily",
            "security_posture_daily",
            "executive_packet_current",
        ):
            with self.subTest(metric_key=key):
                self.assertIn(key, rows)
                self.assertTrue(rows[key]["source_object"].startswith("V_"))
                self.assertIn("UPDATED_AT", rows[key]["source_fields"])
                self.assertIn("sections.summary_mart_loaders.", rows[key]["render_path"])

    def test_semantic_registry_metrics_are_all_accounted_for(self):
        from sections.metric_semantic_registry import all_metric_semantics
        from tools.contracts.metric_render_mapping_audit import build_metric_render_mapping_results

        results = build_metric_render_mapping_results(ROOT)
        semantic_keys = {(row.section, row.metric_key) for row in all_metric_semantics()}
        catalog_keys = {
            (row["section"], row["metric_key"])
            for row in results["rows"]
            if row["mapping_type"] == "semantic_catalog"
        }

        self.assertEqual(semantic_keys, catalog_keys)
        for row in results["rows"]:
            if row["mapping_type"] == "semantic_catalog":
                self.assertTrue(row["visible_label"])
                self.assertTrue(row["source_family"])
                self.assertTrue(row["source_object"])
                self.assertTrue(row["surface"])


if __name__ == "__main__":
    unittest.main()
