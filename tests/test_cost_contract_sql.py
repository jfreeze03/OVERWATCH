from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractSqlTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_sql_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_sql

        self.assertIs(cost_contract._build_cost_cockpit_sql, cost_contract_sql._build_cost_cockpit_sql)
        self.assertIs(cost_contract._build_cost_run_rate_sql, cost_contract_sql._build_cost_run_rate_sql)
        self.assertIs(cost_contract._build_cost_splash_daily_trend_sql, cost_contract_sql._build_cost_splash_daily_trend_sql)
        self.assertIs(cost_contract._build_cost_splash_cortex_sql, cost_contract_sql._build_cost_splash_cortex_sql)
        self.assertIs(cost_contract._build_resource_monitor_guardrail_sql, cost_contract_sql._build_resource_monitor_guardrail_sql)

    def test_mart_daily_trend_sql_uses_hourly_fact_and_company_filter(self):
        from sections.cost_contract_sql import _build_cost_splash_daily_trend_sql

        sql = _build_cost_splash_daily_trend_sql("ALFA", 14, mart=True).upper()

        self.assertIn("FACT_WAREHOUSE_HOURLY", sql)
        self.assertIn("TO_DATE(HOUR_START)", sql)
        self.assertIn("WHERE HOUR_START >=", sql)
        self.assertIn("AND COMPANY = 'ALFA'", sql)

    def test_live_daily_trend_sql_uses_account_usage_and_warehouse_scope(self):
        from sections.cost_contract_sql import _build_cost_splash_daily_trend_sql

        sql = _build_cost_splash_daily_trend_sql("Trexis", 7, mart=False).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("TO_DATE(START_TIME)", sql)
        self.assertIn("WHERE START_TIME >=", sql)
        self.assertIn("WAREHOUSE_NAME", sql)
        self.assertNotIn("AND COMPANY =", sql)

    def test_cortex_mart_sql_uses_fast_summary_source(self):
        from sections.cost_contract_sql import _build_cost_splash_cortex_sql

        sql = _build_cost_splash_cortex_sql("ALFA", 30, 2.2, mart=True).upper()

        self.assertIn("FACT_CORTEX_DAILY", sql)
        self.assertIn("USER_CHART_LABEL", sql)
        self.assertIn("USER_DISPLAY_NAME", sql)
        self.assertIn("USAGE_DATE >=", sql)
        self.assertIn("FAST CORTEX SUMMARY", sql)
        self.assertIn("UPPER(COALESCE(COMPANY, '')) = UPPER('ALFA')", sql)

    def test_cortex_live_sql_uses_cortex_code_history_and_fallback_label(self):
        from sections.cost_contract_sql import _build_cost_splash_cortex_sql

        sql = _build_cost_splash_cortex_sql("Trexis", 14, 2.2, mart=False).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY", sql)
        self.assertIn("LIVE FALLBACK: CORTEX_CODE USAGE HISTORY", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.USERS", sql)
        self.assertIn("FIRST_NAME", sql)
        self.assertIn("LAST_NAME", sql)
        self.assertIn("LOGIN_NAME", sql)
        self.assertNotIn("DISPLAY_NAME", sql)

    def test_resource_monitor_guardrail_sql_is_review_only_and_complete(self):
        from sections.cost_contract_sql import _build_resource_monitor_guardrail_sql

        sql = _build_resource_monitor_guardrail_sql(
            "COMPUTE_WH",
            credit_quota=250,
            monitor_name="OVERWATCH_TEST_MONITOR",
        ).upper()

        self.assertIn("REVIEW-ONLY RESOURCE MONITOR GUARDRAIL", sql)
        self.assertIn("CREATE RESOURCE MONITOR IF NOT EXISTS OVERWATCH_TEST_MONITOR", sql)
        self.assertIn("WITH CREDIT_QUOTA = 250.00", sql)
        self.assertIn("ALTER WAREHOUSE IF EXISTS COMPUTE_WH", sql)
        self.assertIn("SET RESOURCE_MONITOR = OVERWATCH_TEST_MONITOR", sql)
        self.assertIn("SHOW RESOURCE MONITORS", sql)


if __name__ == "__main__":
    unittest.main()
