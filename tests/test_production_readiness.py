from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


def _read(path: Path) -> str:
    if path.suffix == ".py" and not path.exists():
        pkg = path.with_suffix("")
        if pkg.is_dir():
            return "\n".join(
                p.read_text(encoding="utf-8") for p in sorted(pkg.rglob("*.py"))
            )
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


def _executive_landing_surface() -> str:
    return "\n".join(
        _read(path)
        for path in sorted((APP_ROOT / "sections").glob("executive_landing*.py"))
    )


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
        self.assertIn("2026.06.18-GOVERNANCE-ALIGNMENT-RC", sql)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_PRODUCTION_READINESS()", sql)

    def test_validation_tracks_production_readiness_contract(self):
        validation = _validation_sql().upper()
        self.assertIn("('TABLE', 102)", validation)
        self.assertIn("('PROCEDURE', 21)", validation)
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
        executive = _executive_landing_surface()
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

    def test_refresh_health_uses_latest_status_per_load_name(self):
        block = _production_setup_block().upper()
        self.assertIn("LATEST_LOAD_STATUS", block)
        self.assertIn("PARTITION BY LOAD_NAME", block)
        self.assertIn("ORDER BY LOAD_STARTED_AT DESC", block)
        self.assertIn("FROM LATEST_LOAD_STATUS", block)

    def test_alert_email_not_configured_is_explicit(self):
        setup = _setup_sql().upper()
        layout = _read(APP_ROOT / "layout.py").upper()

        self.assertIn("DEFAULT_ALERT_EMAIL', 'JDEES@ALFAINS.COM'", setup)
        self.assertIn("DEFAULT_ALERT_EMAIL=", setup)
        self.assertIn("CONFIG_REQUIRED", setup)
        self.assertIn("ALERT EMAIL IS NOT CONFIGURED", layout)
        self.assertNotIn("DBA-ALERTS@YOURCOMPANY.COM", setup)

    def test_governance_alignment_roles_and_trexis_are_explicit(self):
        block = _production_setup_block().upper()

        self.assertIn("APPROVED TARGET OVERWATCH ROLE", block)
        self.assertIn("APPROVED TRANSITIONAL ACCESS MODEL", block)
        self.assertIn("DO NOT EXECUTE GRANTS AUTOMATICALLY", block)
        self.assertIn("TREXIS IS GOVERNED WITH ALFA-EQUIVALENT COVERAGE EXPECTATIONS", block)
        self.assertIn("TREXIS_GAP_COUNT", block)
        self.assertIn("REVIEW TRUE TELEMETRY FRESHNESS GAPS", block)

    def test_cleanup_validation_outputs_drift_freshness_and_grant_proof(self):
        validation = _validation_sql().upper()
        cleanup = _read(ROOT / "docs" / "PRODUCTION_READINESS_CLEANUP.md").upper()

        for token in [
            "KNOWN_DRIFT",
            "REVIEWABLE_SQL",
            "GRANT_PROOF",
            "OVERWATCH_VIEWER",
            "OVERWATCH_OPERATOR",
            "OVERWATCH_ADMIN",
            "SNOW_ACCOUNTADMINS",
            "SNOW_SYSADMINS",
            "FACT_TASK_RUN",
            "RUNBOOK_GUIDANCE",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, validation)

        self.assertIn("DO NOT EXECUTE GRANTS", cleanup)
        self.assertIn("94 / REVIEW", cleanup)
        self.assertIn("GOVERNANCE ALIGNMENT RELEASE CANDIDATE", cleanup)
        self.assertIn("APPROVED LEGACY", validation)
        self.assertIn("MIGRATION CANDIDATE", validation)
        self.assertIn("CLEANUP CANDIDATE", validation)
        self.assertIn("REQUIRED RETENTION", validation)
        self.assertIn("DEFAULT_ALERT_EMAIL", cleanup)


if __name__ == "__main__":
    unittest.main()

