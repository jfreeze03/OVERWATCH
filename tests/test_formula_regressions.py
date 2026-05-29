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


if __name__ == "__main__":
    unittest.main()
