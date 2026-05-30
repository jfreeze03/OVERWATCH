from pathlib import Path
import sys
import unittest

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import COMPANY_CONFIG  # noqa: E402
from utils.company_filter import (  # noqa: E402
    company_value_allowed,
    get_combined_filter_clause,
    get_wh_filter_clause,
)
from utils.cost import build_cost_reconciliation_sql  # noqa: E402
from utils.compatibility import filter_existing_columns  # noqa: E402
from utils.metadata import (  # noqa: E402
    build_unclassified_assets_sql,
    scope_metadata_df,
    scope_warehouse_names,
)


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

    def test_combined_scope_uses_any_company_signal_with_exclusions(self):
        clause = get_combined_filter_clause("q.database_name", "q.warehouse_name", "q.user_name", company="ALFA")
        upper = clause.upper()
        self.assertIn(" OR ", upper)
        self.assertIn("Q.WAREHOUSE_NAME IS NOT NULL", upper)
        self.assertIn("Q.DATABASE_NAME IS NOT NULL", upper)
        self.assertIn("WH_TRXS_%", upper)
        self.assertIn("TRXS_%", upper)

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

        for key in (
            "_overwatch_available_columns",
            "_overwatch_unavailable_column_views",
            "_overwatch_column_probe",
        ):
            st.session_state.pop(key, None)
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

    def test_optional_column_probe_batches_columns_after_metadata_lookup(self):
        class Result:
            def __init__(self, columns=None):
                self.columns = columns or []

            def to_pandas(self):
                return pd.DataFrame(columns=self.columns)

            def collect(self):
                return []

        class Session:
            def __init__(self):
                self.statements = []

            def sql(self, statement):
                self.statements.append(statement)
                if statement.startswith("SELECT *"):
                    return Result(["QUERY_ID", "WAREHOUSE_SIZE"])
                return Result()

        for key in (
            "_overwatch_available_columns",
            "_overwatch_unavailable_column_views",
            "_overwatch_column_probe",
        ):
            st.session_state.pop(key, None)

        session = Session()
        existing = filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            ["QUERY_ID", "WAREHOUSE_SIZE"],
        )

        self.assertEqual(existing, ["QUERY_ID", "WAREHOUSE_SIZE"])
        self.assertEqual(len(session.statements), 2)
        self.assertIn("SELECT QUERY_ID, WAREHOUSE_SIZE", session.statements[1])

    def test_metadata_scope_uses_active_company_when_no_company_passed(self):
        previous_company = st.session_state.get("active_company")
        st.session_state["active_company"] = "Trexis"
        try:
            warehouses = pd.DataFrame({"NAME": ["BI_COMPUTE_WH", "WH_TRXS_REPORTING"]})
            scoped_warehouses = scope_warehouse_names(warehouses, "NAME")
            self.assertEqual(scoped_warehouses["NAME"].tolist(), ["WH_TRXS_REPORTING"])

            objects = pd.DataFrame(
                {
                    "DATABASE_NAME": ["ALFA_EDW_DEV_BI", "TRXS_ANALYTICS"],
                    "WAREHOUSE_NAME": ["BI_COMPUTE_WH", "WH_TRXS_REPORTING"],
                }
            )
            scoped_objects = scope_metadata_df(objects)
            self.assertEqual(scoped_objects["DATABASE_NAME"].tolist(), ["TRXS_ANALYTICS"])
        finally:
            if previous_company is None:
                st.session_state.pop("active_company", None)
            else:
                st.session_state["active_company"] = previous_company


if __name__ == "__main__":
    unittest.main()
