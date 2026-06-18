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


def _validation_sql() -> str:
    return _read(ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql")


def _production_setup_block() -> str:
    sql = _setup_sql()
    start = sql.index("-- Phase 2A: live production validation")
    end = sql.index("-- Phase 2B: leadership Executive Scorecard", start)
    proc_start = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_PRODUCTION_READINESS")
    proc_end = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD", proc_start)
    return sql[start:end] + "\n" + sql[proc_start:proc_end]


class ProductionReadinessTests(unittest.TestCase):
    def test_setup_adds_phase_2a_objects_and_refresh_call(self):
        sql = _setup_sql().upper()
        for name in [
            "OVERWATCH_PRODUCTION_CHECKLIST",
            "OVERWATCH_ROLE_READINESS_REQUIREMENT",
            "OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT",
            "OVERWATCH_PRODUCTION_VALIDATION_STATUS",
            "MART_PRODUCTION_READINESS_SUMMARY",
            "SP_OVERWATCH_REFRESH_PRODUCTION_READINESS",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, sql)
        self.assertIn("2026.06.18-PRODUCTION-READINESS", sql)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_PRODUCTION_READINESS()", sql)

    def test_validation_tracks_production_readiness_contract(self):
        validation = _validation_sql().upper()
        self.assertIn("('TABLE', 83)", validation)
        self.assertIn("('PROCEDURE', 14)", validation)
        for token in [
            "PRODUCTION_READINESS_SUMMARY",
            "PRODUCTION_PRIVILEGE_BLOCKERS",
            "OVERWATCH_PRODUCTION_VALIDATION_STATUS",
            "MART_PRODUCTION_READINESS_SUMMARY",
            "MISSING_PRIVILEGES",
            "FAILED_MART_REFRESHES",
            "CONFIG_DRIFT_COUNT",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, validation)

    def test_first_paint_summary_helper_is_mart_only(self):
        helper = _read(APP_ROOT / "utils" / "production_readiness.py").upper()
        summary = helper.split("DEF LOAD_PRODUCTION_READINESS_SUMMARY", 1)[1].split(
            "DEF LOAD_PRODUCTION_VALIDATION_DETAIL", 1
        )[0]
        self.assertIn("MART_PRODUCTION_READINESS_SUMMARY", summary)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", summary)
        self.assertNotIn("INFORMATION_SCHEMA", summary)
        self.assertNotIn("SHOW ", summary)

    def test_ui_places_dashboard_and_load_gates(self):
        executive = _read(APP_ROOT / "sections" / "executive_landing.py")
        dba = _read(APP_ROOT / "sections" / "dba_control_room.py")

        self.assertIn("load_production_readiness_summary", executive)
        self.assertIn("Production Readiness", executive)
        for label in [
            "Load Production Validation Checklist",
            "Load Role Readiness",
            "Load Privilege Readiness",
            "Load Refresh Health",
        ]:
            with self.subTest(label=label):
                self.assertIn(label, dba)
        button_pos = dba.index("st.button(button_label")
        loader_pos = dba.index("load_production_validation_detail", button_pos)
        self.assertLess(button_pos, loader_pos)

    def test_phase_2a_block_has_no_silent_remediation_or_broad_live_scans(self):
        block = _production_setup_block().upper()
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", block)
        self.assertNotIn("INFORMATION_SCHEMA", block)
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

    def test_readiness_status_and_confidence_labels_are_constrained(self):
        helper = _read(APP_ROOT / "utils" / "production_readiness.py")
        block = _production_setup_block()
        self.assertIn('READINESS_STATUS_LABELS = ("Ready", "Review", "Blocked", "Unknown")', helper)
        for confidence in ["'exact'", "'allocated'", "'estimated'", "'fallback'"]:
            with self.subTest(confidence=confidence):
                self.assertIn(confidence, block)


if __name__ == "__main__":
    unittest.main()
