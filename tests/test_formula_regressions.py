from pathlib import Path
import math
import re
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.account_health import _live_query_status_sql  # noqa: E402
from sections.adoption_analytics import _metric as adoption_metric  # noqa: E402
from sections.cost_center import (  # noqa: E402
    _bill_driver_summary,
    _build_bill_waterfall,
    _build_finance_movement_summary,
    _service_cost_category,
)
from sections.service_health import _value as service_value  # noqa: E402
from sections.usage_overview import _first_number as usage_first_number  # noqa: E402
from utils.cost import build_metered_credit_cte  # noqa: E402


def _python_sources():
    return [
        path
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


class FormulaRegressionTests(unittest.TestCase):
    def test_metered_credit_cte_uses_compute_credits_with_total_fallback(self):
        sql = build_metered_credit_cte(hours_back=24, include_recent=True).upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("COALESCE(CREDITS_USED_COMPUTE, CREDITS_USED)", sql)
        self.assertIn("AS HOURLY_COMPUTE_CREDITS", sql)
        self.assertNotIn("SUM(CREDITS_USED)               AS HOURLY_COMPUTE_CREDITS", sql)

    def test_account_health_live_counts_prefer_information_schema(self):
        sql = _live_query_status_sql("", "", "").upper()
        self.assertIn("INFORMATION_SCHEMA.QUERY_HISTORY", sql)
        self.assertIn("QUEUED_OVERLOAD_TIME", sql)
        self.assertIn("QUEUED_PROVISIONING_TIME", sql)
        self.assertIn("QUEUED_REPAIR_TIME", sql)
        self.assertIn("RESUMING_WAREHOUSE", sql)

    def test_company_scope_does_not_default_missing_company_to_alfa(self):
        offenders = []
        for path in _python_sources():
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "COALESCE(COMPANY, 'ALFA')" in text or 'COALESCE(COMPANY, "ALFA")' in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_status_comparisons_are_case_safe_for_account_usage(self):
        bad_patterns = [
            r"(?<!UPPER\()execution_status\s*=\s*'FAILED_WITH_ERROR'",
            r"(?<!UPPER\()execution_status\s*=\s*'SUCCESS'",
            r"(?<!UPPER\()execution_status\s+IN\s*\('RUNNING','QUEUED','BLOCKED'",
        ]
        offenders = []
        for path in _python_sources():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in bad_patterns:
                if re.search(pattern, text):
                    offenders.append(f"{path.relative_to(ROOT)} :: {pattern}")
        self.assertEqual(offenders, [])

    def test_cloud_service_credit_sums_are_null_safe(self):
        offenders = []
        pattern = re.compile(r"SUM\(\s*credits_used_cloud_services\s*\)", re.IGNORECASE)
        for path in _python_sources():
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_dashboard_metric_helpers_do_not_emit_nan(self):
        df = pd.DataFrame({"VALUE": [math.nan]})
        self.assertEqual(adoption_metric(df, "VALUE"), 0.0)
        self.assertEqual(service_value(df, "VALUE"), 0.0)
        self.assertEqual(usage_first_number(df, "VALUE"), 0.0)

    def test_usage_overview_storage_sums_are_null_safe(self):
        text = (APP_ROOT / "sections" / "usage_overview.py").read_text(encoding="utf-8")
        self.assertIn("SUM(COALESCE(c.average_database_bytes, 0))", text)
        self.assertIn("SUM(COALESCE(c.average_failsafe_bytes, 0))", text)
        self.assertNotIn("SUM(c.average_database_bytes)", text)
        self.assertNotIn("SUM(c.average_failsafe_bytes)", text)

    def test_bill_driver_summary_handles_missing_baseline_and_empty_drivers(self):
        summary = _bill_driver_summary(
            delta_credits=10.0,
            current_credits=10.0,
            prior_credits=0.0,
            unallocated_pct=30.0,
            warehouse_deltas=pd.DataFrame(),
            user_drivers=pd.DataFrame(),
            query_type_drivers=pd.DataFrame(),
        )
        self.assertEqual(summary["severity"], "Watch")
        self.assertIn("new/no baseline", summary["headline"])
        self.assertIn("unallocated gap", summary["caveat"])

    def test_bill_waterfall_balances_to_current_total(self):
        wh = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["WH_A", "WH_B", "WH_C"],
                "CREDIT_DELTA": [20.0, -5.0, 2.0],
            }
        )
        wf = _build_bill_waterfall(
            wh,
            prior_credits=100.0,
            current_credits=117.0,
            credit_price=3.0,
            top_n=2,
        )
        self.assertEqual(wf.iloc[0]["Driver"], "Prior baseline")
        self.assertEqual(wf.iloc[-1]["Driver"], "Current total")
        self.assertAlmostEqual(float(wf.iloc[-1]["Credits"]), 117.0)
        movement = wf[~wf["Type"].isin(["Baseline", "Current"])]["Credits"].sum()
        self.assertAlmostEqual(float(movement), 17.0)

    def test_service_cost_categories_are_business_readable(self):
        self.assertEqual(_service_cost_category("SNOWPIPE"), "Data loading / ingestion")
        self.assertEqual(_service_cost_category("CORTEX_SEARCH"), "AI / Cortex")
        self.assertEqual(_service_cost_category("AUTO_CLUSTERING"), "Serverless features")
        self.assertEqual(_service_cost_category("CLOUD_SERVICES"), "Cloud services / metadata")

    def test_finance_movement_summary_separates_confidence_levels(self):
        service_df = pd.DataFrame(
            {
                "PERIOD": ["CURRENT", "PRIOR", "CURRENT"],
                "SERVICE_TYPE": ["SNOWPIPE", "SNOWPIPE", "CORTEX"],
                "CREDITS": [8.0, 3.0, 2.0],
            }
        )
        summary = _build_finance_movement_summary(
            current_credits=100.0,
            prior_credits=80.0,
            allocated_credits=70.0,
            unallocated_credits=30.0,
            service_drivers=service_df,
            credit_price=3.0,
            budget=250.0,
        )
        categories = set(summary["Category"])
        self.assertIn("Warehouse metering", categories)
        self.assertIn("Query-attributed workload", categories)
        self.assertIn("Unallocated / idle / overhead", categories)
        self.assertIn("Data loading / ingestion", categories)
        self.assertIn("AI / Cortex", categories)
        self.assertIn("Budget variance", categories)
        confidence = dict(zip(summary["Category"], summary["Confidence"]))
        self.assertEqual(confidence["Warehouse metering"], "Exact")
        self.assertEqual(confidence["Query-attributed workload"], "Allocated")
        self.assertEqual(confidence["Data loading / ingestion"], "Account-wide")


if __name__ == "__main__":
    unittest.main()
