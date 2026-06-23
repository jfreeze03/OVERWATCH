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


def _change_intelligence_setup_block() -> str:
    sql = _setup_sql()
    start = sql.index("-- Phase 2D: Change Intelligence")
    end = sql.index("-- Phase 2E: Closed Loop Operations", start)
    proc_start = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE")
    proc_end = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS", proc_start)
    return sql[start:end] + "\n" + sql[proc_start:proc_end]


class ChangeIntelligenceTests(unittest.TestCase):
    def test_setup_drop_and_validation_cover_change_intelligence_objects(self):
        setup = _setup_sql().upper()
        drop = _drop_sql().upper()
        validation = _validation_sql().upper()
        for name in [
            "OVERWATCH_CHANGE_RULE",
            "OVERWATCH_CHANGE_EVENT",
            "OVERWATCH_CHANGE_CORRELATION",
            "MART_CHANGE_INTELLIGENCE_SUMMARY",
            "SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, setup)
                self.assertIn(name, drop)
                self.assertIn(name, validation)
        self.assertIn("2026.06.18-CHANGE-INTELLIGENCE", setup)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE()", setup)
        self.assertIn("('TABLE', 94)", validation)
        self.assertIn("('PROCEDURE', 17)", validation)

    def test_change_labels_and_categories_are_constrained(self):
        from utils.change_intelligence import (
            CHANGE_CONFIDENCE_LABELS,
            CHANGE_CORRELATION_LABELS,
            CHANGE_RISK_LABELS,
            CHANGE_TYPES,
        )

        self.assertEqual(
            CHANGE_TYPES,
            (
                "WAREHOUSE_CHANGE",
                "ROLE_CHANGE",
                "GRANT_CHANGE",
                "TASK_CHANGE",
                "PROCEDURE_CHANGE",
                "NETWORK_POLICY_CHANGE",
                "INTEGRATION_CHANGE",
                "OBJECT_CHANGE",
                "SECURITY_SENSITIVE_CHANGE",
            ),
        )
        self.assertEqual(CHANGE_RISK_LABELS, ("Critical", "High", "Medium", "Low"))
        self.assertEqual(CHANGE_CONFIDENCE_LABELS, ("exact", "allocated", "estimated", "fallback"))
        self.assertEqual(CHANGE_CORRELATION_LABELS, ("possible correlation",))

    def test_first_paint_helper_reads_summary_mart_only(self):
        helper = _read(APP_ROOT / "utils" / "change_intelligence.py").upper()
        summary = helper.split("DEF LOAD_CHANGE_INTELLIGENCE_SUMMARY", 1)[1].split(
            "DEF LOAD_CHANGE_EVENT_DETAIL", 1
        )[0]
        self.assertIn("MART_CHANGE_INTELLIGENCE_SUMMARY", summary)
        self.assertNotIn("OVERWATCH_CHANGE_EVENT", summary)
        self.assertNotIn("OVERWATCH_CHANGE_CORRELATION", summary)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", summary)
        self.assertNotIn("INFORMATION_SCHEMA", summary)
        self.assertNotIn("SHOW ", summary)

    def test_detail_helpers_are_mart_only_and_not_live_scans(self):
        helper = _read(APP_ROOT / "utils" / "change_intelligence.py").upper()
        event_detail = helper.split("DEF LOAD_CHANGE_EVENT_DETAIL", 1)[1].split(
            "DEF LOAD_CHANGE_CORRELATION_DETAIL", 1
        )[0]
        correlation_detail = helper.split("DEF LOAD_CHANGE_CORRELATION_DETAIL", 1)[1]
        self.assertIn("OVERWATCH_CHANGE_EVENT", event_detail)
        self.assertIn("OVERWATCH_CHANGE_CORRELATION", correlation_detail)
        for block in (event_detail, correlation_detail):
            with self.subTest(block=block[:40]):
                self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", block)
                self.assertNotIn("INFORMATION_SCHEMA", block)
                self.assertNotIn("SHOW ", block)

    def test_ui_places_change_intelligence_in_approved_sections(self):
        executive = _read(APP_ROOT / "sections" / "executive_landing.py")
        dba = _read(APP_ROOT / "sections" / "dba_control_room.py")
        cost = _cost_contract_surface()
        workload = _read(APP_ROOT / "sections" / "workload_operations.py")
        security = _read(APP_ROOT / "sections" / "security_posture_access_changes_view.py")
        alert = _read(APP_ROOT / "sections" / "alert_center_diagnostics_view.py")

        self.assertIn("load_change_intelligence_summary", executive)
        self.assertIn("Change Intelligence", executive)
        self.assertIn("Load Change Intelligence", dba)
        self.assertIn("Load Cost-Related Changes", cost)
        self.assertIn("Load Workload Changes", workload)
        self.assertIn("Load Security-Sensitive Changes", security)
        self.assertIn("Load Related Changes", alert)

    def test_detail_panels_are_explicitly_load_gated(self):
        checks = [
            (APP_ROOT / "sections" / "dba_control_room.py", "Load Change Intelligence", "load_change_event_detail"),
            (APP_ROOT / "sections" / "cost_contract_evidence_panels.py", "Load Cost-Related Changes", "load_change_correlation_detail"),
            (APP_ROOT / "sections" / "workload_operations.py", "Load Workload Changes", "load_change_event_detail"),
            (APP_ROOT / "sections" / "security_posture_access_changes_view.py", "Load Security-Sensitive Changes", "load_change_event_detail"),
            (APP_ROOT / "sections" / "alert_center_diagnostics_view.py", "Load Related Changes", "load_change_correlation_detail"),
        ]
        for path, button, loader in checks:
            with self.subTest(path=path.name, button=button):
                source = _read(path)
                button_pos = source.index(button)
                loader_pos = source.index(loader, button_pos)
                self.assertLess(button_pos, loader_pos)

    def test_validation_checks_change_coverage_labels_and_causality_safety(self):
        validation = _validation_sql().upper()
        for token in [
            "CHANGE_INTELLIGENCE_SUMMARY",
            "CHANGE_INTELLIGENCE_LABELS",
            "CHANGE_CORRELATION_SAFETY",
            "WAREHOUSE_CHANGE",
            "ROLE_CHANGE",
            "GRANT_CHANGE",
            "TASK_CHANGE",
            "PROCEDURE_CHANGE",
            "NETWORK_POLICY_CHANGE",
            "INTEGRATION_CHANGE",
            "OBJECT_CHANGE",
            "SECURITY_SENSITIVE_CHANGE",
            "POSSIBLE CORRELATION",
            "RISK_LEVEL NOT IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')",
            "LOWER(COALESCE(CONFIDENCE, '')) NOT IN ('EXACT', 'ALLOCATED', 'ESTIMATED', 'FALLBACK')",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, validation)

    def test_change_intelligence_block_has_no_silent_remediation_or_live_scans(self):
        block = _change_intelligence_setup_block().upper()
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", block)
        self.assertNotIn("INFORMATION_SCHEMA", block)
        self.assertNotIn("SHOW ", block)
        for forbidden in [
            "EXECUTE IMMEDIATE",
            "SYSTEM$SEND_EMAIL",
            "CREATE TASK",
            "SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN",
            "ALERT_REMEDIATION_LOG",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, block)

    def test_documentation_covers_change_intelligence_contract(self):
        docs = "\n".join(
            _read(ROOT / "docs" / name)
            for name in ["CHANGE_INTELLIGENCE.md", "DATA_MODEL.md", "ENTERPRISE_OPERATING_MODEL.md", "APP_ARCHITECTURE.md"]
        ).upper()
        for token in [
            "MART_CHANGE_INTELLIGENCE_SUMMARY",
            "OVERWATCH_CHANGE_EVENT",
            "OVERWATCH_CHANGE_CORRELATION",
            "SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE",
            "WAREHOUSE CHANGES",
            "SECURITY-SENSITIVE CHANGES",
            "POSSIBLE CORRELATION",
            "EXPLICIT LOAD",
            "NO SILENT REMEDIATION",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, docs)


if __name__ == "__main__":
    unittest.main()
