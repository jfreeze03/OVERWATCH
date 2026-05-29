from pathlib import Path
import sys
import unittest

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import COMPANY_CONFIG  # noqa: E402
from utils.company_filter import company_value_allowed, get_wh_filter_clause  # noqa: E402
from utils.cost import build_cost_reconciliation_sql  # noqa: E402
from utils.compatibility import filter_existing_columns  # noqa: E402
from utils.metadata import build_unclassified_assets_sql  # noqa: E402


class CompanyScopeAndCostTests(unittest.TestCase):
    def test_alfa_warehouse_scope_is_not_broad_match_all(self):
        self.assertNotIn("%", COMPANY_CONFIG["ALFA"]["wh_patterns"])
        self.assertTrue(company_value_allowed("WH_ALFA_ADHOC", "warehouse", "ALFA"))
        self.assertTrue(company_value_allowed("BI_COMPUTE_WH", "warehouse", "ALFA"))
        self.assertFalse(company_value_allowed("WH_TRXS_REPORTING", "warehouse", "ALFA"))
        self.assertFalse(company_value_allowed("WH_RANDOM_VENDOR", "warehouse", "ALFA"))

    def test_company_scope_sql_excludes_trexis_for_alfa(self):
        clause = get_wh_filter_clause("warehouse_name", company="ALFA")
        self.assertIn("WH_TRXS_%", clause)
        self.assertIn("NOT", clause.upper())
        self.assertNotIn("LIKE '%'", clause.upper())

    def test_cost_reconciliation_sql_uses_metering_and_variance(self):
        sql = build_cost_reconciliation_sql(30).upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("EXACT_METERED_CREDITS", sql)
        self.assertIn("ALLOCATED_QUERY_CREDITS", sql)
        self.assertIn("VARIANCE_CREDITS", sql)

    def test_unclassified_asset_sql_uses_explicit_allowlists(self):
        sql = build_unclassified_assets_sql(30).upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("DATABASES", sql)
        self.assertIn("DOES NOT MATCH ANY COMPANY ALLOWLIST", sql)
        self.assertNotIn("ILIKE '%'", sql)

    def test_optional_column_probe_degrades_when_view_is_unavailable(self):
        class BrokenSession:
            calls = 0

            def sql(self, _statement):
                self.calls += 1
                raise RuntimeError("not authorized")

        st.session_state.pop("_overwatch_unavailable_column_views", None)
        session = BrokenSession()
        self.assertEqual(
            filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE"],
            ),
            [],
        )
        self.assertEqual(
            filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE"],
            ),
            [],
        )
        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
