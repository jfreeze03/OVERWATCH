from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _setup_sql() -> str:
    return _read(ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql")


def _drop_sql() -> str:
    return _read(ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql")


def _validation_sql() -> str:
    return _read(ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql")


def _forecast_setup_block() -> str:
    sql = _setup_sql()
    start = sql.index("-- Phase 2C: leadership forecasting")
    end = sql.index("-- Existing installs may have been created", start)
    proc_start = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_FORECASTING")
    proc_end = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY", proc_start)
    return sql[start:end] + "\n" + sql[proc_start:proc_end]


class ForecastingTests(unittest.TestCase):
    def test_setup_drop_and_validation_cover_forecasting_objects(self):
        setup = _setup_sql().upper()
        drop = _drop_sql().upper()
        validation = _validation_sql().upper()
        for name in [
            "OVERWATCH_FORECAST_CONFIG",
            "OVERWATCH_FORECAST_HISTORY",
            "MART_EXECUTIVE_FORECAST_SUMMARY",
            "SP_OVERWATCH_REFRESH_FORECASTING",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, setup)
                self.assertIn(name, drop)
                self.assertIn(name, validation)
        self.assertIn("2026.06.18-EXECUTIVE-FORECASTING", setup)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_FORECASTING()", setup)
        self.assertIn("('TABLE', 79)", validation)
        self.assertIn("('PROCEDURE', 13)", validation)

    def test_forecast_labels_and_keys_are_constrained(self):
        from utils.forecasting import FORECAST_CONFIDENCE_LABELS, FORECAST_KEYS, FORECAST_TREND_LABELS

        self.assertEqual(
            FORECAST_KEYS,
            (
                "EOM_SPEND",
                "EOQ_SPEND",
                "CONTRACT_BURN",
                "CREDIT_ANOMALY",
                "STORAGE_GROWTH",
                "WAREHOUSE_PRESSURE",
                "SLA_RISK",
            ),
        )
        self.assertEqual(FORECAST_CONFIDENCE_LABELS, ("High", "Medium", "Low"))
        self.assertEqual(FORECAST_TREND_LABELS, ("Up", "Down", "Flat", "Unknown"))

    def test_first_paint_helper_reads_summary_mart_only(self):
        helper = _read(APP_ROOT / "utils" / "forecasting.py").upper()
        summary = helper.split("DEF LOAD_EXECUTIVE_FORECAST_SUMMARY", 1)[1].split(
            "DEF LOAD_FORECAST_DETAIL", 1
        )[0]
        self.assertIn("MART_EXECUTIVE_FORECAST_SUMMARY", summary)
        self.assertNotIn("OVERWATCH_FORECAST_HISTORY", summary)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", summary)
        self.assertNotIn("INFORMATION_SCHEMA", summary)
        self.assertNotIn("SHOW ", summary)

    def test_detail_helper_is_history_only_and_not_live_account_usage(self):
        helper = _read(APP_ROOT / "utils" / "forecasting.py").upper()
        detail = helper.split("DEF LOAD_FORECAST_DETAIL", 1)[1]
        self.assertIn("OVERWATCH_FORECAST_HISTORY", detail)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", detail)
        self.assertNotIn("INFORMATION_SCHEMA", detail)
        self.assertNotIn("SHOW ", detail)

    def test_ui_places_forecasting_in_approved_sections(self):
        executive = _read(APP_ROOT / "sections" / "executive_landing.py")
        dba = _read(APP_ROOT / "sections" / "dba_control_room.py")
        cost = _read(APP_ROOT / "sections" / "cost_contract.py")
        workload = _read(APP_ROOT / "sections" / "workload_operations.py")

        self.assertIn("load_executive_forecast_summary", executive)
        self.assertIn("Executive Forecasting", executive)
        self.assertIn("Load Forecast Exceptions", dba)
        self.assertIn("Load Cost Forecast Drivers", cost)
        self.assertIn("Load Workload Forecast Drivers", workload)

    def test_detail_panels_are_explicitly_load_gated(self):
        checks = [
            (APP_ROOT / "sections" / "dba_control_room.py", "Load Forecast Exceptions", "load_forecast_detail"),
            (APP_ROOT / "sections" / "cost_contract.py", "Load Cost Forecast Drivers", "load_forecast_detail"),
            (APP_ROOT / "sections" / "workload_operations.py", "Load Workload Forecast Drivers", "load_forecast_detail"),
        ]
        for path, button, loader in checks:
            with self.subTest(path=path.name, button=button):
                source = _read(path)
                button_pos = source.index(button)
                loader_pos = source.index(loader, button_pos)
                self.assertLess(button_pos, loader_pos)

    def test_validation_checks_forecast_coverage_labels_and_methodology(self):
        validation = _validation_sql().upper()
        for token in [
            "EXECUTIVE_FORECASTING_SUMMARY",
            "EXECUTIVE_FORECASTING_LABELS",
            "EOM_SPEND",
            "EOQ_SPEND",
            "CONTRACT_BURN",
            "WAREHOUSE_PRESSURE",
            "SLA_RISK",
            "CONFIDENCE NOT IN ('HIGH', 'MEDIUM', 'LOW')",
            "TREND_DIRECTION NOT IN ('UP', 'DOWN', 'FLAT', 'UNKNOWN')",
            "EMPTY_METHODOLOGY_ROWS",
            "FORECASTS_NOT_VERIFIED_VALUE",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, validation)

    def test_forecast_block_has_no_silent_remediation_or_broad_live_scans(self):
        block = _forecast_setup_block().upper()
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", block)
        self.assertNotIn("INFORMATION_SCHEMA", block)
        self.assertNotIn("SHOW ", block)
        for forbidden in [
            "ALTER WAREHOUSE",
            "DROP USER",
            "REVOKE ",
            "GRANT OWNERSHIP",
            "EXECUTE IMMEDIATE",
            "SYSTEM$SEND_EMAIL",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, block)

    def test_documentation_covers_forecasting_contract(self):
        docs = "\n".join(
            _read(ROOT / "docs" / name)
            for name in ["FORECASTING.md", "DATA_MODEL.md", "ENTERPRISE_OPERATING_MODEL.md", "APP_ARCHITECTURE.md"]
        ).upper()
        for token in [
            "MART_EXECUTIVE_FORECAST_SUMMARY",
            "OVERWATCH_FORECAST_HISTORY",
            "SP_OVERWATCH_REFRESH_FORECASTING",
            "END-OF-MONTH SPEND",
            "WAREHOUSE PRESSURE",
            "SLA RISK",
            "EXPLICIT LOAD",
            "NOT VERIFIED SAVINGS",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, docs)


if __name__ == "__main__":
    unittest.main()
