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


def _drop_sql() -> str:
    return _read(ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql")


def _validation_sql() -> str:
    return _read(ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql")


def _cost_contract_surface() -> str:
    return "\n".join(
        _read(path)
        for path in (
            APP_ROOT / "sections" / "cost_contract.py",
            APP_ROOT / "sections" / "cost_contract_evidence_panels.py",
        )
    )


def _scorecard_setup_block() -> str:
    sql = _setup_sql()
    start = sql.index("-- Phase 2B: leadership Executive Scorecard")
    end = sql.index("-- Phase 2C: leadership forecasting", start)
    proc_start = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD")
    proc_end = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_FORECASTING", proc_start)
    return sql[start:end] + "\n" + sql[proc_start:proc_end]


class ExecutiveScorecardTests(unittest.TestCase):
    def test_setup_drop_and_validation_cover_scorecard_objects(self):
        setup = _setup_sql().upper()
        drop = _drop_sql().upper()
        validation = _validation_sql().upper()
        for name in [
            "OVERWATCH_EXECUTIVE_SCORECARD_CONFIG",
            "OVERWATCH_EXECUTIVE_SCORECARD_HISTORY",
            "MART_EXECUTIVE_SCORECARD_SUMMARY",
            "SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, setup)
                self.assertIn(name, drop)
                self.assertIn(name, validation)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD()", setup)
        self.assertIn("('TABLE', 102)", validation)
        self.assertIn("('PROCEDURE', 17)", validation)

    def test_score_labels_thresholds_and_keys_are_constrained(self):
        from utils.executive_scorecard import SCORE_KEYS, SCORE_STATUS_LABELS, score_status_for_value

        self.assertEqual(
            SCORE_KEYS,
            (
                "SNOWFLAKE_HEALTH",
                "COST_EFFICIENCY",
                "SECURITY",
                "OPERATIONAL_RISK",
                "DATA_TRUST",
                "PRODUCTION_READINESS",
            ),
        )
        self.assertEqual(SCORE_STATUS_LABELS, ("Green", "Yellow", "Red", "Unknown"))
        self.assertEqual(score_status_for_value(95), "Green")
        self.assertEqual(score_status_for_value(80), "Yellow")
        self.assertEqual(score_status_for_value(60), "Red")
        self.assertEqual(score_status_for_value("not-a-score"), "Unknown")

    def test_first_paint_helper_reads_summary_mart_only(self):
        helper = _read(APP_ROOT / "utils" / "executive_scorecard.py").upper()
        summary = helper.split("DEF LOAD_EXECUTIVE_SCORECARD_SUMMARY", 1)[1].split(
            "DEF LOAD_EXECUTIVE_SCORECARD_DETAIL", 1
        )[0]
        self.assertIn("MART_EXECUTIVE_SCORECARD_SUMMARY", summary)
        self.assertNotIn("OVERWATCH_EXECUTIVE_SCORECARD_HISTORY", summary)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", summary)
        self.assertNotIn("INFORMATION_SCHEMA", summary)
        self.assertNotIn("SHOW ", summary)

    def test_detail_helper_is_history_only_and_not_live_account_usage(self):
        helper = _read(APP_ROOT / "utils" / "executive_scorecard.py").upper()
        detail = helper.split("DEF LOAD_EXECUTIVE_SCORECARD_DETAIL", 1)[1]
        self.assertIn("OVERWATCH_EXECUTIVE_SCORECARD_HISTORY", detail)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", detail)
        self.assertNotIn("INFORMATION_SCHEMA", detail)
        self.assertNotIn("SHOW ", detail)

    def test_ui_places_scorecard_in_approved_sections(self):
        executive = _read(APP_ROOT / "sections" / "executive_landing_admin_view.py")
        dba = _read(APP_ROOT / "sections" / "dba_control_room.py")
        cost = _cost_contract_surface()
        security = _read(APP_ROOT / "sections" / "security_posture_admin_view.py")
        alert = _read(APP_ROOT / "sections" / "alert_center_diagnostics_view.py")

        self.assertIn("load_executive_scorecard_summary", executive)
        self.assertIn("Executive Scorecard", executive)
        self.assertIn("Load Executive Scorecard Drivers", dba)
        self.assertIn("Load Cost Efficiency Score Drivers", cost)
        self.assertIn("Load Security Score Drivers", security)
        self.assertIn("Load Operational Risk Score Drivers", alert)

    def test_scorecard_detail_panels_are_explicitly_load_gated(self):
        checks = [
            (APP_ROOT / "sections" / "dba_control_room.py", "Load Executive Scorecard Drivers", "load_executive_scorecard_detail"),
            (APP_ROOT / "sections" / "cost_contract_evidence_panels.py", "Load Cost Efficiency Score Drivers", "load_executive_scorecard_detail"),
            (APP_ROOT / "sections" / "security_posture_admin_view.py", "Load Security Score Drivers", "load_executive_scorecard_detail"),
            (APP_ROOT / "sections" / "alert_center_diagnostics_view.py", "Load Operational Risk Score Drivers", "load_executive_scorecard_detail"),
        ]
        for path, button, loader in checks:
            with self.subTest(path=path.name, button=button):
                source = _read(path)
                button_pos = source.index(button)
                loader_pos = source.index(loader, button_pos)
                self.assertLess(button_pos, loader_pos)

    def test_validation_checks_score_coverage_bounds_and_labels(self):
        validation = _validation_sql().upper()
        for token in [
            "EXECUTIVE_SCORECARD_SUMMARY",
            "EXECUTIVE_SCORECARD_LABELS",
            "SNOWFLAKE_HEALTH",
            "COST_EFFICIENCY",
            "OPERATIONAL_RISK",
            "CURRENT_SCORE < 0 OR CURRENT_SCORE > 100",
            "STATUS NOT IN ('GREEN', 'YELLOW', 'RED')",
            "LOWER(COALESCE(CONFIDENCE, '')) NOT IN ('EXACT', 'ALLOCATED', 'ESTIMATED', 'FALLBACK')",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, validation)

    def test_scorecard_block_has_no_silent_remediation_or_live_scans(self):
        block = _scorecard_setup_block().upper()
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

    def test_documentation_covers_scorecard_contract(self):
        docs = "\n".join(
            _read(ROOT / "docs" / name)
            for name in ["EXECUTIVE_SCORECARD.md", "DATA_MODEL.md", "ENTERPRISE_OPERATING_MODEL.md"]
        ).upper()
        for token in [
            "MART_EXECUTIVE_SCORECARD_SUMMARY",
            "OVERWATCH_EXECUTIVE_SCORECARD_HISTORY",
            "SNOWFLAKE HEALTH SCORE",
            "COST EFFICIENCY SCORE",
            "PRODUCTION READINESS SCORE",
            "EXPLICIT LOAD",
            "NO BROAD FIRST-PAINT",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, docs)


if __name__ == "__main__":
    unittest.main()
