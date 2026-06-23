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


def _closed_loop_setup_block() -> str:
    sql = _setup_sql()
    start = sql.index("-- Phase 2E: Closed Loop Operations")
    end = sql.index("-- Phase 2F: Command Center", start)
    proc_start = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS")
    proc_end = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_COMMAND_CENTER", proc_start)
    return sql[start:end] + "\n" + sql[proc_start:proc_end]


class ClosedLoopOperationsTests(unittest.TestCase):
    def test_setup_drop_and_validation_cover_closed_loop_objects(self):
        setup = _setup_sql().upper()
        drop = _drop_sql().upper()
        validation = _validation_sql().upper()
        for name in [
            "OVERWATCH_ACTION_WORKFLOW",
            "OVERWATCH_ACTION_APPROVAL",
            "OVERWATCH_ACTION_EXECUTION_PLAN",
            "OVERWATCH_ACTION_VERIFICATION",
            "OVERWATCH_ACTION_EVIDENCE",
            "MART_CLOSED_LOOP_OPERATIONS_SUMMARY",
            "SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, setup)
                self.assertIn(name, drop)
                self.assertIn(name, validation)
        self.assertIn("2026.06.18-CLOSED-LOOP-OPERATIONS", setup)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS()", setup)
        self.assertIn("('TABLE', 94)", validation)
        self.assertIn("('PROCEDURE', 17)", validation)

    def test_closed_loop_labels_are_constrained(self):
        from utils.closed_loop_operations import (
            CLOSED_LOOP_CONFIDENCE_LABELS,
            CLOSED_LOOP_DOMAINS,
            CLOSED_LOOP_EXECUTION_MODES,
            CLOSED_LOOP_RISK_LABELS,
        )

        self.assertEqual(CLOSED_LOOP_DOMAINS, ("ALL", "Cost", "Operations", "Security", "Workload", "Alert"))
        self.assertEqual(CLOSED_LOOP_RISK_LABELS, ("Critical", "High", "Medium", "Low"))
        self.assertEqual(
            CLOSED_LOOP_EXECUTION_MODES,
            (
                "REVIEW_SQL_ONLY",
                "MANUAL_REVIEW",
                "RECOMMEND_ONLY",
                "DRY_RUN_ONLY",
                "EXTERNAL_EXECUTION_RECORDED",
            ),
        )
        self.assertEqual(CLOSED_LOOP_CONFIDENCE_LABELS, ("exact", "allocated", "estimated", "fallback"))

    def test_first_paint_helper_reads_summary_mart_only(self):
        helper = _read(APP_ROOT / "utils" / "closed_loop_operations.py").upper()
        summary = helper.split("DEF LOAD_CLOSED_LOOP_SUMMARY", 1)[1].split(
            "DEF LOAD_CLOSED_LOOP_WORKFLOW_DETAIL", 1
        )[0]
        self.assertIn("MART_CLOSED_LOOP_OPERATIONS_SUMMARY", summary)
        self.assertNotIn("OVERWATCH_ACTION_WORKFLOW", summary)
        self.assertNotIn("OVERWATCH_ACTION_EXECUTION_PLAN", summary)
        self.assertNotIn("OVERWATCH_ACTION_VERIFICATION", summary)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", summary)
        self.assertNotIn("INFORMATION_SCHEMA", summary)
        self.assertNotIn("SHOW ", summary)

    def test_detail_helpers_are_closed_loop_marts_only(self):
        helper = _read(APP_ROOT / "utils" / "closed_loop_operations.py").upper()
        workflow = helper.split("DEF LOAD_CLOSED_LOOP_WORKFLOW_DETAIL", 1)[1].split(
            "DEF LOAD_CLOSED_LOOP_EXECUTION_PLAN_DETAIL", 1
        )[0]
        execution = helper.split("DEF LOAD_CLOSED_LOOP_EXECUTION_PLAN_DETAIL", 1)[1].split(
            "DEF LOAD_CLOSED_LOOP_VERIFICATION_DETAIL", 1
        )[0]
        verification = helper.split("DEF LOAD_CLOSED_LOOP_VERIFICATION_DETAIL", 1)[1]
        self.assertIn("OVERWATCH_ACTION_WORKFLOW", workflow)
        self.assertIn("OVERWATCH_ACTION_EXECUTION_PLAN", execution)
        self.assertIn("OVERWATCH_ACTION_VERIFICATION", verification)
        for block in (workflow, execution, verification):
            with self.subTest(block=block[:40]):
                self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", block)
                self.assertNotIn("INFORMATION_SCHEMA", block)
                self.assertNotIn("SHOW ", block)

    def test_ui_places_closed_loop_in_approved_sections(self):
        executive = _read(APP_ROOT / "sections" / "executive_landing_admin_view.py")
        dba = _read(APP_ROOT / "sections" / "dba_control_room.py")
        cost = _cost_contract_surface()
        workload = _read(APP_ROOT / "sections" / "workload_operations.py")
        security = _read(APP_ROOT / "sections" / "security_posture_admin_view.py")
        alert = _read(APP_ROOT / "sections" / "alert_center_diagnostics_view.py")

        self.assertIn("load_closed_loop_summary", executive)
        self.assertIn("Closed Loop Operations", executive)
        self.assertIn("Load Closed-Loop Actions", dba)
        self.assertIn("Load Savings Verification", cost)
        self.assertIn("Load Operational Actions", workload)
        self.assertIn("Load Security Approvals", security)
        self.assertIn("Load Alert Action Workflows", alert)

    def test_detail_panels_are_explicitly_load_gated(self):
        checks = [
            (APP_ROOT / "sections" / "dba_control_room.py", "Load Closed-Loop Actions", "load_closed_loop_workflow_detail"),
            (APP_ROOT / "sections" / "cost_contract_evidence_panels.py", "Load Savings Verification", "load_closed_loop_verification_detail"),
            (APP_ROOT / "sections" / "workload_operations.py", "Load Operational Actions", "load_closed_loop_workflow_detail"),
            (APP_ROOT / "sections" / "security_posture_admin_view.py", "Load Security Approvals", "load_closed_loop_workflow_detail"),
            (APP_ROOT / "sections" / "alert_center_diagnostics_view.py", "Load Alert Action Workflows", "load_closed_loop_workflow_detail"),
        ]
        for path, button, loader in checks:
            with self.subTest(path=path.name, button=button):
                source = _read(path)
                button_pos = source.index(button)
                loader_pos = source.index(f"{loader}(", button_pos)
                self.assertLess(button_pos, loader_pos)

    def test_validation_checks_lifecycle_savings_and_execution_safety(self):
        validation = _validation_sql().upper()
        for token in [
            "CLOSED_LOOP_OPERATIONS_SUMMARY",
            "CLOSED_LOOP_LIFECYCLE_LABELS",
            "CLOSED_LOOP_EXECUTION_SAFETY",
            "CLOSED_LOOP_VERIFIED_SAVINGS_SAFETY",
            "CLOSED_LOOP_NO_SILENT_REMEDIATION",
            "EXECUTION_ALLOWED_IN_APP",
            "DANGEROUS_ACTION_FLAG",
            "ACTUAL_GT_EXPECTED_ROWS",
            "BAD_APPROVAL_STATUS_ROWS",
            "BAD_VERIFICATION_STATUS_ROWS",
            "REQUESTED",
            "APPROVAL NOT REQUIRED",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, validation)

    def test_closed_loop_block_has_no_silent_execution(self):
        block = _closed_loop_setup_block().upper()
        self.assertIn("FALSE AS EXECUTION_ALLOWED_IN_APP", block)
        self.assertIn("'NOT EXECUTED' AS EXECUTION_STATUS", block)
        self.assertIn("DANGEROUS_ACTION_FLAG", block)
        self.assertNotIn("EXECUTE IMMEDIATE", block)
        self.assertNotIn("SYSTEM$SEND_EMAIL", block)
        self.assertNotIn("EXECUTION_ALLOWED_IN_APP = TRUE", block)
        self.assertNotIn("'EXECUTED' AS EXECUTION_STATUS", block)

    def test_closed_loop_numeric_savings_fields_do_not_use_try_to_number(self):
        block = _closed_loop_setup_block()
        self.assertIn("COALESCE(EST_MONTHLY_SAVINGS, 0) AS EXPECTED_SAVINGS_USD", block)
        self.assertIn("GREATEST(MEASURED_DELTA, 0)", block)
        self.assertNotIn("TRY_TO_NUMBER(EST_MONTHLY_SAVINGS)", block)
        self.assertNotIn("TRY_TO_NUMBER(MEASURED_DELTA)", block)

    def test_documentation_covers_closed_loop_contract(self):
        docs = "\n".join(
            _read(ROOT / "docs" / name)
            for name in [
                "CLOSED_LOOP_OPERATIONS.md",
                "DATA_MODEL.md",
                "ENTERPRISE_OPERATING_MODEL.md",
                "APP_ARCHITECTURE.md",
            ]
        ).upper()
        for token in [
            "MART_CLOSED_LOOP_OPERATIONS_SUMMARY",
            "OVERWATCH_ACTION_WORKFLOW",
            "OVERWATCH_ACTION_APPROVAL",
            "OVERWATCH_ACTION_EXECUTION_PLAN",
            "OVERWATCH_ACTION_VERIFICATION",
            "OVERWATCH_ACTION_EVIDENCE",
            "SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS",
            "REVIEW-GATED",
            "NO SILENT EXECUTION",
            "ACTUAL VERIFIED SAVINGS",
            "EXPLICIT LOAD",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, docs)


if __name__ == "__main__":
    unittest.main()
