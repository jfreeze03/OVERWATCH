from pathlib import Path
import sys
import unittest

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import COMPANY_CONFIG, TREXIS_DATABASES, TREXIS_DEV_DATABASES, TREXIS_PROD_DATABASES, TREXIS_WAREHOUSES  # noqa: E402
from utils.company_filter import (  # noqa: E402
    company_value_allowed,
    environment_value_allowed,
    get_combined_filter_clause,
    get_company_case_expr,
    get_db_filter_clause,
    get_environment_filter_clause,
    get_environment_label,
    get_environment_options_for_company,
    get_global_filter_clause,
    get_global_schema_filter_clause,
    get_role_filter_clause,
    get_user_company_filter_clause,
    get_wh_filter_clause,
)
from utils.cost import build_cost_reconciliation_sql  # noqa: E402
from utils.compatibility import clear_compatibility_process_cache, filter_existing_columns  # noqa: E402
from utils.data import normalize_df  # noqa: E402
from utils.metadata import (  # noqa: E402
    build_unclassified_assets_sql,
    scope_metadata_df,
    scope_warehouse_names,
)
from sections.cost_center import _annotate_allocation_quality  # noqa: E402


class CompanyScopeAndCostTests(unittest.TestCase):
    def test_normalize_df_uses_fast_path_when_no_conversion_or_scope_needed(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            df = pd.DataFrame({"LABEL": ["ok"], "DETAIL": ["ready"]})

            normalized = normalize_df(df)

            self.assertIs(normalized, df)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_alfa_warehouse_scope_is_not_broad_match_all(self):
        self.assertEqual(COMPANY_CONFIG["Trexis"]["wh_patterns"], list(TREXIS_WAREHOUSES))
        self.assertEqual(COMPANY_CONFIG["ALFA"]["wh_exclude_patterns"], list(TREXIS_WAREHOUSES))
        self.assertEqual(COMPANY_CONFIG["Trexis"]["db_patterns"], list(TREXIS_DATABASES))
        self.assertNotIn("%", COMPANY_CONFIG["ALFA"]["wh_patterns"])
        self.assertTrue(company_value_allowed("WH_ALFA_ADHOC", "warehouse", "ALFA"))
        self.assertTrue(company_value_allowed("BI_COMPUTE_WH", "warehouse", "ALFA"))
        self.assertTrue(company_value_allowed("OVERWATCH_WH", "warehouse", "ALFA"))
        self.assertTrue(company_value_allowed("WH_TRXS_REPORTING", "warehouse", "ALFA"))
        self.assertTrue(company_value_allowed("WH_RANDOM_VENDOR", "warehouse", "ALFA"))
        self.assertFalse(company_value_allowed("WH_TRXS_LOAD", "warehouse", "ALFA"))
        self.assertTrue(company_value_allowed("WH_TRXS_LOAD", "warehouse", "Trexis"))
        self.assertFalse(company_value_allowed("WH_TRXS_REPORTING", "warehouse", "Trexis"))

    def test_company_scope_sql_excludes_trexis_for_alfa(self):
        clause = get_wh_filter_clause("warehouse_name", company="ALFA")
        self.assertIn("WH_TRXS_LOAD", clause)
        self.assertIn("WH_TRXS_UNLOAD", clause)
        self.assertIn("NOT", clause.upper())
        self.assertNotIn("WH_TRXS_%", clause)
        self.assertNotIn("LIKE '%'", clause.upper())

    def test_combined_scope_uses_any_company_signal_with_exclusions(self):
        clause = get_combined_filter_clause(
            "q.database_name",
            "q.warehouse_name",
            "q.user_name",
            "q.role_name",
            company="ALFA",
        )
        upper = clause.upper()
        self.assertIn(" OR ", upper)
        self.assertIn("Q.WAREHOUSE_NAME IS NOT NULL", upper)
        self.assertIn("Q.DATABASE_NAME IS NOT NULL", upper)
        self.assertIn("WH_TRXS_LOAD", upper)
        self.assertNotIn("WH_TRXS_%", upper)
        self.assertIn("%TRXS%", upper)
        self.assertIn("Q.ROLE_NAME", upper)

    def test_company_case_uses_exact_trexis_warehouse_list(self):
        expr = get_company_case_expr("q.warehouse_name", "q.database_name", "q.user_name", "q.role_name").upper()
        self.assertIn("WH_TRXS_LOAD", expr)
        self.assertIn("WH_TRXS_UNLOAD", expr)
        self.assertIn("TRXS_EDW_PRD", expr)
        self.assertIn("TRXS_GW_DATA_SIT", expr)
        self.assertIn("UPPER(Q.WAREHOUSE_NAME)", expr)
        self.assertIn("UPPER(Q.DATABASE_NAME)", expr)
        self.assertIn("Q.USER_NAME ILIKE 'TRXS_%'", expr)
        self.assertIn("Q.ROLE_NAME ILIKE '%TRXS%'", expr)
        self.assertIn("NULLIF(TRIM(TO_VARCHAR(Q.WAREHOUSE_NAME))", expr)
        self.assertNotIn("Q.DATABASE_NAME ILIKE 'TRXS_%'", expr)
        self.assertNotIn("WH_TRXS_%", expr)

    def test_role_scope_uses_trxs_moniker(self):
        trexis_clause = get_role_filter_clause("q.role_name", company="Trexis").upper()
        alfa_clause = get_role_filter_clause("q.role_name", company="ALFA").upper()

        self.assertIn("Q.ROLE_NAME ILIKE '%TRXS%'", trexis_clause)
        self.assertIn("Q.ROLE_NAME NOT ILIKE '%TRXS%'", alfa_clause)

    def test_user_company_scope_uses_active_role_membership(self):
        trexis_clause = get_user_company_filter_clause("u.name", company="Trexis").upper()
        alfa_clause = get_user_company_filter_clause("u.name", company="ALFA").upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS", trexis_clause)
        self.assertIn("ROLE_SCOPE.\"ROLE\" ILIKE '%TRXS%'", trexis_clause)
        self.assertIn("ROLE_SCOPE.GRANTEE_NAME", trexis_clause)
        self.assertIn("NOT EXISTS", alfa_clause)
        self.assertIn("ROLE_SCOPE.\"ROLE\" ILIKE '%TRXS%'", alfa_clause)

    def test_app_surfaces_use_role_aware_user_scope(self):
        offenders = []
        for path in APP_ROOT.rglob("*.py"):
            rel = path.relative_to(APP_ROOT).as_posix()
            if rel == "utils/company_filter.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "get_user_filter_clause(" in text:
                offenders.append(rel)

        self.assertEqual(offenders, [])

    def test_mart_setup_uses_exact_trexis_warehouse_list(self):
        sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        self.assertIn("WH_TRXS_LOAD", sql)
        self.assertIn("WH_TRXS_UNLOAD", sql)
        self.assertIn("TRXS_EDW_PRD", sql)
        self.assertIn("TRXS_GW_DATA_SIT", sql)
        self.assertIn("UPPER(COALESCE(WAREHOUSE_NAME, '')) IN", sql)
        self.assertIn("UPPER(COALESCE(DATABASE_NAME, '')) IN", sql)
        self.assertIn("ROLE_NAME ILIKE '%TRXS%'", sql)
        self.assertNotIn("OVERWATCH_COMPANY_SCOPE", sql)
        self.assertNotIn("SCOPE_PATTERN = 'WH_TRXS_%'", sql)
        self.assertNotIn("SCOPE_PATTERN = 'TRXS_%'", sql)
        self.assertNotIn("WAREHOUSE_NAME ILIKE 'WH_TRXS_%'", sql)
        self.assertNotIn("Q.WAREHOUSE_NAME ILIKE 'WH_TRXS_%'", sql)
        self.assertNotIn("DATABASE_NAME ILIKE 'TRXS_%'", sql)
        self.assertNotIn("Q.DATABASE_NAME ILIKE 'TRXS_%'", sql)

    def test_global_filter_clause_can_avoid_duplicate_scope_predicates(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "PROD"
            st.session_state["global_user"] = "ETL"
            st.session_state["global_schema"] = "PUBLIC"

            scoped = get_global_filter_clause(
                "q.start_time",
                "q.warehouse_name",
                "q.user_name",
                "q.role_name",
                "q.database_name",
                "q.schema_name",
            ).upper()
            ui_only = get_global_filter_clause(
                "q.start_time",
                "q.warehouse_name",
                "q.user_name",
                "q.role_name",
                "q.database_name",
                "q.schema_name",
                include_company_scope=False,
                include_environment_scope=False,
            ).upper()

            self.assertIn("WH_TRXS_LOAD", scoped)
            self.assertIn("ALFA_EDW_PROD", scoped)
            self.assertIn("Q.USER_NAME ILIKE '%ETL%'", scoped)
            self.assertIn("Q.SCHEMA_NAME ILIKE '%PUBLIC%'", scoped)
            self.assertNotIn("WH_TRXS_LOAD", ui_only)
            self.assertNotIn("ALFA_EDW_PROD", ui_only)
            self.assertIn("Q.USER_NAME ILIKE '%ETL%'", ui_only)
            self.assertIn("Q.SCHEMA_NAME ILIKE '%PUBLIC%'", ui_only)
            self.assertEqual(get_global_schema_filter_clause("q.schema_name").upper(), "AND Q.SCHEMA_NAME ILIKE '%PUBLIC%'")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_global_environment_filter_can_preserve_account_level_rows(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "PROD"

            clause = get_global_filter_clause(
                date_col="",
                wh_col="q.warehouse_name",
                user_col="q.user_name",
                role_col="",
                db_col="q.database_name",
                preserve_no_database_context=True,
            ).upper()

            self.assertIn("Q.DATABASE_NAME IS NULL", clause)
            self.assertIn("ALFA_EDW_PROD", clause)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_database_scope_includes_selected_environment(self):
        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "PROD"

            clause = get_db_filter_clause("database_name", company="ALFA").upper()
            self.assertIn("ALFA_EDW_PROD", clause)
            self.assertTrue(environment_value_allowed("ALFA_EDW_PROD", company="ALFA"))
            self.assertFalse(environment_value_allowed("ALFA_EDW_DEV", company="ALFA"))

            trexis_clause = get_db_filter_clause("database_name", company="Trexis").upper()
            self.assertNotIn("ALFA_EDW_PROD", trexis_clause)
            self.assertIn("TRXS_EDW_PRD", trexis_clause)
            trexis_prod_env_clause = get_environment_filter_clause("database_name", company="Trexis").upper()
            self.assertIn("TRXS_EDW_PRD", trexis_prod_env_clause)
            self.assertNotIn("TRXS_EDW_DEV", trexis_prod_env_clause)

            st.session_state["global_environment"] = "DEV_ALL"
            trexis_dev_clause = get_environment_filter_clause("database_name", company="Trexis").upper()
            for db_name in TREXIS_DEV_DATABASES:
                self.assertIn(db_name, trexis_dev_clause)
            for db_name in TREXIS_PROD_DATABASES:
                self.assertNotIn(db_name, trexis_dev_clause)
            self.assertTrue(environment_value_allowed("TRXS_EDW_DEV", company="Trexis"))
            self.assertTrue(environment_value_allowed("TRXS_EDW_SIT", company="Trexis"))
            self.assertFalse(environment_value_allowed("TRXS_EDW_PRD", company="Trexis"))
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_trexis_environment_options_are_prod_and_dev_sit_only(self):
        self.assertEqual(get_environment_options_for_company("Trexis"), ("ALL", "PROD", "DEV_ALL"))
        self.assertEqual(get_environment_label("DEV_ALL", "Trexis"), "All DEV/SIT")

    def test_cost_reconciliation_sql_uses_metering_and_variance(self):
        sql = build_cost_reconciliation_sql(30).upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("EXACT_METERED_CREDITS", sql)
        self.assertIn("ALLOCATED_QUERY_CREDITS", sql)
        self.assertIn("VARIANCE_CREDITS", sql)

    def test_cost_allocation_quality_rolls_up_alfa_prod_and_dev(self):
        rows = pd.DataFrame(
            [
                {"COMPANY": "ALFA", "ENVIRONMENT": "PROD", "DATABASE_NAME": "ALFA_EDW_PROD"},
                {"COMPANY": "ALFA", "ENVIRONMENT": "ALFA_EDW_DEV", "DATABASE_NAME": "ALFA_EDW_DEV"},
                {"COMPANY": "ALFA", "ENVIRONMENT": "ALFA_EDW_SAN", "DATABASE_NAME": "ALFA_EDW_SAN"},
                {"COMPANY": "Trexis", "ENVIRONMENT": "PROD", "DATABASE_NAME": "TRXS_EDW_PRD"},
                {"COMPANY": "Trexis", "ENVIRONMENT": "DEV_ALL", "DATABASE_NAME": "TRXS_EDW_SIT"},
            ]
        )

        annotated = _annotate_allocation_quality(rows)

        self.assertEqual(annotated["ENVIRONMENT_ROLLUP"].tolist(), ["PROD", "DEV_ALL", "DEV_ALL", "PROD", "DEV_ALL"])
        self.assertEqual(set(annotated["ALLOCATION_CONFIDENCE"]), {"Allocated / Estimated"})
        self.assertEqual(set(annotated["CHARGEBACK_READY"]), {"Directional"})

    def test_cost_allocation_quality_promotes_owner_tagged_chargeback_rows(self):
        rows = pd.DataFrame(
            [
                {
                    "COMPANY": "ALFA",
                    "ENVIRONMENT": "PROD",
                    "DATABASE_NAME": "ALFA_EDW_PROD",
                    "COST_OWNER": "FINANCE_ANALYTICS",
                    "OWNER_SOURCE": "DATABASE_TAG:COST_OWNER",
                    "OWNER_EVIDENCE": "Database owner tag COST_OWNER=FINANCE_ANALYTICS.",
                },
                {
                    "COMPANY": "ALFA",
                    "ENVIRONMENT": "ALFA_EDW_DEV",
                    "DATABASE_NAME": "ALFA_EDW_DEV",
                    "COST_OWNER": "EDW_DEV_TEAM",
                    "OWNER_SOURCE": "WAREHOUSE_TAG:COST_OWNER",
                    "OWNER_EVIDENCE": "Warehouse owner tag COST_OWNER=EDW_DEV_TEAM.",
                },
            ]
        )

        annotated = _annotate_allocation_quality(rows)

        self.assertEqual(annotated["ENVIRONMENT_ROLLUP"].tolist(), ["PROD", "DEV_ALL"])
        self.assertEqual(set(annotated["CHARGEBACK_READY"]), {"Ready"})
        self.assertIn("route-tag telemetry is attached", annotated.iloc[0]["ALLOCATION_BASIS"])
        self.assertEqual(annotated.iloc[0]["COST_OWNER"], "FINANCE_ANALYTICS")
        self.assertEqual(annotated.iloc[1]["OWNER_SOURCE"], "WAREHOUSE_TAG:COST_OWNER")

    def test_cost_allocation_quality_rejects_missing_database_chargeback(self):
        rows = pd.DataFrame(
            [
                {
                    "COMPANY": "ALFA",
                    "ENVIRONMENT": "No Database Context",
                    "DATABASE_NAME": "NO_DATABASE_CONTEXT",
                },
                {
                    "COMPANY": "ALFA",
                    "ENVIRONMENT": "Other / Shared",
                    "DATABASE_NAME": "SHARED_ANALYTICS",
                },
            ]
        )

        annotated = _annotate_allocation_quality(rows)

        self.assertEqual(annotated.iloc[0]["ALLOCATION_CONFIDENCE"], "Account-wide / Shared")
        self.assertEqual(annotated.iloc[0]["CHARGEBACK_READY"], "No")
        self.assertEqual(annotated.iloc[1]["ALLOCATION_CONFIDENCE"], "Shared / Needs route")
        self.assertEqual(annotated.iloc[1]["CHARGEBACK_READY"], "Review")

    def test_unclassified_asset_sql_uses_explicit_allowlists(self):
        sql = build_unclassified_assets_sql(30).upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("DATABASES", sql)
        self.assertIn("DOES NOT MATCH ANY COMPANY ALLOWLIST", sql)
        self.assertIn("AND 1=0", sql)
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
        clear_compatibility_process_cache()
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
        clear_compatibility_process_cache()

        session = Session()
        existing = filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            ["QUERY_ID", "WAREHOUSE_SIZE"],
        )

        self.assertEqual(existing, ["QUERY_ID", "WAREHOUSE_SIZE"])
        self.assertEqual(len(session.statements), 2)
        self.assertIn("SELECT QUERY_ID, WAREHOUSE_SIZE", session.statements[1])

        for key in (
            "_overwatch_available_columns",
            "_overwatch_unavailable_column_views",
            "_overwatch_column_probe",
        ):
            st.session_state.pop(key, None)
        second_session = Session()
        existing_again = filter_existing_columns(
            second_session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            ["QUERY_ID", "WAREHOUSE_SIZE"],
        )

        self.assertEqual(existing_again, ["QUERY_ID", "WAREHOUSE_SIZE"])
        self.assertEqual(second_session.statements, [])

    def test_metadata_scope_uses_active_company_when_no_company_passed(self):
        previous_company = st.session_state.get("active_company")
        st.session_state["active_company"] = "Trexis"
        try:
            warehouses = pd.DataFrame({"NAME": ["BI_COMPUTE_WH", "WH_TRXS_LOAD", "WH_TRXS_REPORTING"]})
            scoped_warehouses = scope_warehouse_names(warehouses, "NAME")
            self.assertEqual(scoped_warehouses["NAME"].tolist(), ["WH_TRXS_LOAD"])

            objects = pd.DataFrame(
                {
                    "DATABASE_NAME": ["ALFA_EDW_DEV_BI", "TRXS_EDW_PRD", "ALFA_EDW_PROD"],
                    "WAREHOUSE_NAME": ["BI_COMPUTE_WH", "WH_TRXS_LOAD", "WH_TRXS_REPORTING"],
                }
            )
            scoped_objects = scope_metadata_df(objects)
            self.assertEqual(scoped_objects["DATABASE_NAME"].tolist(), ["TRXS_EDW_PRD"])
        finally:
            if previous_company is None:
                st.session_state.pop("active_company", None)
            else:
                st.session_state["active_company"] = previous_company


if __name__ == "__main__":
    unittest.main()
