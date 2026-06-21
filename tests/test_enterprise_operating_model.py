from pathlib import Path
import re
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


def _enterprise_setup_block() -> str:
    sql = _setup_sql()
    start = sql.index("-- Enterprise operating model")
    end = sql.index("-- Phase 2A: live production validation", start)
    proc_start = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL")
    proc_end = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_PRODUCTION_READINESS", proc_start)
    return sql[start:end] + "\n" + sql[proc_start:proc_end]


class EnterpriseOperatingModelTests(unittest.TestCase):
    def test_setup_adds_enterprise_operating_model_objects(self):
        sql = _setup_sql().upper()
        for name in [
            "OVERWATCH_DATA_TRUST_SOURCE",
            "OVERWATCH_DATA_TRUST_STATUS",
            "MART_DATA_TRUST_SUMMARY",
            "OVERWATCH_OPERATIONAL_OWNER_MAP",
            "MART_OPERATIONAL_OWNER_COVERAGE",
            "OVERWATCH_VALUE_LEDGER",
            "MART_EXECUTIVE_VALUE_LEDGER",
            "OVERWATCH_APP_OBSERVABILITY",
            "MART_APP_OBSERVABILITY_SUMMARY",
            "SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, sql)
        self.assertIn("FINDING -> OWNER -> TRUST LEVEL -> BUSINESS IMPACT -> ACTION -> VALUE VERIFIED", sql)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL()", sql)

    def test_validation_contract_tracks_new_objects_and_confidence_labels(self):
        validation = _validation_sql().upper()
        self.assertIn("('TABLE', 94)", validation)
        self.assertIn("('PROCEDURE', 16)", validation)
        for name in [
            "MART_DATA_TRUST_SUMMARY",
            "MART_OPERATIONAL_OWNER_COVERAGE",
            "MART_EXECUTIVE_VALUE_LEDGER",
            "MART_APP_OBSERVABILITY_SUMMARY",
            "CONFIDENCE_LABELS",
            "UNVERIFIED_VALUE_NOT_REALIZED",
            "ENTERPRISE_REMEDIATION_SAFETY",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, validation)
        for label in ["exact", "allocated", "estimated", "fallback"]:
            self.assertIn(label.upper(), validation)

    def test_enterprise_first_paint_helpers_are_mart_only(self):
        helper = _read(APP_ROOT / "utils" / "enterprise_operating_model.py").upper()
        rollup_source = helper.split("DEF LOAD_ENTERPRISE_OPERATING_ROLLUPS", 1)[1].split("DEF LOAD_DATA_TRUST_DETAIL", 1)[0]
        self.assertIn("MART_DATA_TRUST_SUMMARY", rollup_source)
        self.assertIn("MART_OPERATIONAL_OWNER_COVERAGE", rollup_source)
        self.assertIn("MART_EXECUTIVE_VALUE_LEDGER", rollup_source)
        self.assertIn("MART_APP_OBSERVABILITY_SUMMARY", rollup_source)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", rollup_source)
        self.assertNotIn("INFORMATION_SCHEMA", rollup_source)

    def test_ui_places_capabilities_in_approved_sections(self):
        executive = _read(APP_ROOT / "sections" / "executive_landing.py")
        dba = _read(APP_ROOT / "sections" / "dba_control_room.py")
        alert = _read(APP_ROOT / "sections" / "alert_center.py")
        security = _read(APP_ROOT / "sections" / "security_posture.py")
        cost = _read(APP_ROOT / "sections" / "cost_contract.py")

        self.assertIn("load_enterprise_operating_rollups", executive)
        self.assertIn("Enterprise Operating Model", executive)
        self.assertIn("Load Data Trust Diagnostics", dba)
        self.assertIn("Load App Observability Detail", dba)
        self.assertIn('surface="Alert Center"', alert)
        self.assertIn("Operational Ownership Coverage", alert)
        self.assertIn('surface="Security Monitoring"', security)
        self.assertIn("Security Ownership Coverage", security)
        self.assertIn("Executive Value Ledger", cost)
        self.assertIn("Load Value Ledger Detail", cost)

    def test_detail_panels_are_explicitly_load_gated(self):
        dba = _read(APP_ROOT / "sections" / "dba_control_room.py")
        cost = _read(APP_ROOT / "sections" / "cost_contract.py")

        for button, loader in [
            ("Load Data Trust Diagnostics", "load_data_trust_detail"),
            ("Load App Observability Detail", "load_app_observability_detail"),
        ]:
            with self.subTest(button=button):
                button_pos = dba.index(f'st.button("{button}"')
                loader_pos = dba.index(loader, button_pos)
                self.assertLess(button_pos, loader_pos)

        button_pos = cost.index('st.button("Load Value Ledger Detail"')
        loader_pos = cost.index("load_value_ledger_detail", button_pos)
        self.assertLess(button_pos, loader_pos)

    def test_enterprise_block_has_no_silent_remediation_or_live_scans(self):
        block = _enterprise_setup_block().upper()
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

    def test_value_ledger_keeps_unverified_savings_separate(self):
        block = _enterprise_setup_block().upper()
        self.assertIn("UNVERIFIED_ESTIMATE_USD", block)
        self.assertIn("DO NOT COUNT EXPECTED SAVINGS AS REALIZED", block)
        verified_assignments = re.findall(r"VERIFIED_SAVINGS_USD", block)
        self.assertGreaterEqual(len(verified_assignments), 3)

    def test_sparse_activity_still_populates_company_rollup_baselines(self):
        block = _enterprise_setup_block().upper()
        for marker in [
            "NO ACTIVE OWNERSHIP ITEMS FOR THIS COMPANY/SURFACE",
            "NO ACTIVE VALUE-LEDGER ROWS WERE FOUND FOR THIS COMPANY/WINDOW",
            "FALLBACK APP-OBSERVABILITY ROW",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, block)

        self.assertIn("FROM VALUES ('ALL'), ('ALFA'), ('TREXIS')", block)
        self.assertIn("NO ACTIVE VALUE ITEMS", block)

    def test_executive_observability_populates_source_status_panel(self):
        sql = _setup_sql().upper()
        proc_start = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY")
        proc_end = sql.index("-- -----------------------------------------------------------------------------\n-- 5. ALERT FRAMEWORK", proc_start)
        proc = sql[proc_start:proc_end]

        self.assertIn("'SOURCE_STATUS' AS PANEL", proc)
        self.assertIn("MART_DATA_TRUST_SUMMARY", proc)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL()", proc)


if __name__ == "__main__":
    unittest.main()
