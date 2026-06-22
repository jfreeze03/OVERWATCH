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


def _command_center_setup_block() -> str:
    sql = _setup_sql()
    start = sql.index("-- Phase 2F: Command Center")
    end = sql.index("-- Existing installs may have been created", start)
    proc_start = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_COMMAND_CENTER")
    proc_end = sql.index("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY", proc_start)
    return sql[start:end] + "\n" + sql[proc_start:proc_end]


class CommandCenterTests(unittest.TestCase):
    def test_setup_drop_and_validation_cover_command_center_objects(self):
        setup = _setup_sql().upper()
        drop = _drop_sql().upper()
        validation = _validation_sql().upper()
        for name in [
            "OVERWATCH_COMMAND_CENTER_QUESTION",
            "OVERWATCH_COMMAND_CENTER_FINDING",
            "OVERWATCH_COMMAND_CENTER_EVIDENCE",
            "OVERWATCH_COMMAND_CENTER_RECOMMENDATION",
            "MART_COMMAND_CENTER_SUMMARY",
            "SP_OVERWATCH_REFRESH_COMMAND_CENTER",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, setup)
                self.assertIn(name, drop)
                self.assertIn(name, validation)
        self.assertIn("2026.06.18-COMMAND-CENTER", setup)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_COMMAND_CENTER()", setup)
        self.assertIn("('TABLE', 94)", validation)
        self.assertIn("('PROCEDURE', 17)", validation)

    def test_command_center_labels_are_constrained(self):
        from utils.command_center import (
            COMMAND_CENTER_CAUSALITY_LABELS,
            COMMAND_CENTER_CONFIDENCE_LABELS,
            COMMAND_CENTER_INVESTIGATION_TYPES,
            COMMAND_CENTER_RISK_LABELS,
        )

        self.assertEqual(
            COMMAND_CENTER_INVESTIGATION_TYPES,
            (
                "ALL",
                "Cost Spike",
                "Warehouse Slow",
                "Recent Change",
                "Failure / SLA",
                "Security Risk",
                "Executive Risk",
            ),
        )
        self.assertEqual(COMMAND_CENTER_RISK_LABELS, ("Critical", "High", "Medium", "Low"))
        self.assertEqual(COMMAND_CENTER_CONFIDENCE_LABELS, ("exact", "allocated", "estimated", "fallback"))
        self.assertEqual(
            COMMAND_CENTER_CAUSALITY_LABELS,
            ("root-cause candidate", "likely driver", "possible correlation"),
        )

    def test_first_paint_helper_reads_summary_mart_only(self):
        helper = _read(APP_ROOT / "utils" / "command_center.py").upper()
        summary = helper.split("DEF LOAD_COMMAND_CENTER_SUMMARY", 1)[1].split(
            "DEF LOAD_COMMAND_CENTER_FINDING_DETAIL", 1
        )[0]
        self.assertIn("MART_COMMAND_CENTER_SUMMARY", summary)
        self.assertNotIn("OVERWATCH_COMMAND_CENTER_FINDING", summary)
        self.assertNotIn("OVERWATCH_COMMAND_CENTER_EVIDENCE", summary)
        self.assertNotIn("OVERWATCH_COMMAND_CENTER_RECOMMENDATION", summary)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", summary)
        self.assertNotIn("INFORMATION_SCHEMA", summary)
        self.assertNotIn("SHOW ", summary)

    def test_detail_helpers_are_command_center_marts_only(self):
        helper = _read(APP_ROOT / "utils" / "command_center.py").upper()
        finding = helper.split("DEF LOAD_COMMAND_CENTER_FINDING_DETAIL", 1)[1].split(
            "DEF LOAD_COMMAND_CENTER_EVIDENCE_DETAIL", 1
        )[0]
        evidence = helper.split("DEF LOAD_COMMAND_CENTER_EVIDENCE_DETAIL", 1)[1].split(
            "DEF LOAD_COMMAND_CENTER_RECOMMENDATION_DETAIL", 1
        )[0]
        recommendation = helper.split("DEF LOAD_COMMAND_CENTER_RECOMMENDATION_DETAIL", 1)[1]
        self.assertIn("OVERWATCH_COMMAND_CENTER_FINDING", finding)
        self.assertIn("OVERWATCH_COMMAND_CENTER_EVIDENCE", evidence)
        self.assertIn("OVERWATCH_COMMAND_CENTER_RECOMMENDATION", recommendation)
        for block in (finding, evidence, recommendation):
            with self.subTest(block=block[:40]):
                self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", block)
                self.assertNotIn("INFORMATION_SCHEMA", block)
                self.assertNotIn("SHOW ", block)

    def test_ui_places_command_center_in_approved_sections(self):
        executive = _read(APP_ROOT / "sections" / "executive_landing.py")
        dba = _read(APP_ROOT / "sections" / "dba_control_room.py")
        cost = _read(APP_ROOT / "sections" / "cost_contract.py")
        workload = _read(APP_ROOT / "sections" / "workload_operations.py")
        security = _read(APP_ROOT / "sections" / "security_posture.py")
        alert = _read(APP_ROOT / "sections" / "alert_center.py")

        self.assertIn("load_command_center_summary", executive)
        self.assertIn("Correlated Investigations", executive)
        self.assertIn("Load Correlated Investigations", dba)
        self.assertIn("Load Cost Investigation Findings", cost)
        self.assertIn("Load Workload Investigation Findings", workload)
        self.assertIn("Load Security Investigation Findings", security)
        self.assertIn("Load Alert Investigation Findings", alert)

    def test_detail_panels_are_explicitly_load_gated(self):
        checks = [
            (APP_ROOT / "sections" / "dba_control_room.py", "Load Correlated Investigations", "load_command_center_finding_detail"),
            (APP_ROOT / "sections" / "cost_contract.py", "Load Cost Investigation Findings", "load_command_center_finding_detail"),
            (APP_ROOT / "sections" / "workload_operations.py", "Load Workload Investigation Findings", "load_command_center_finding_detail"),
            (APP_ROOT / "sections" / "security_posture.py", "Load Security Investigation Findings", "load_command_center_finding_detail"),
            (APP_ROOT / "sections" / "alert_center.py", "Load Alert Investigation Findings", "load_command_center_finding_detail"),
        ]
        for path, button, loader in checks:
            with self.subTest(path=path.name, button=button):
                source = _read(path)
                button_pos = source.index(button)
                loader_pos = source.index(f"{loader}(", button_pos)
                self.assertLess(button_pos, loader_pos)

    def test_validation_checks_wording_confidence_and_safety(self):
        validation = _validation_sql().upper()
        for token in [
            "COMMAND_CENTER_SUMMARY",
            "COMMAND_CENTER_LABELS_AND_WORDING",
            "COMMAND_CENTER_EVIDENCE_AND_RECOMMENDATIONS",
            "COMMAND_CENTER_NO_SILENT_REMEDIATION",
            "BAD_CAUSALITY_ROWS",
            "OVERCLAIMED_ROOT_CAUSE_ROWS",
            "ROOT-CAUSE CANDIDATE",
            "LIKELY DRIVER",
            "POSSIBLE CORRELATION",
            "NOT_REVIEW_GATED_ROWS",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, validation)

    def test_command_center_derives_trust_issue_count_from_trust_rows(self):
        block = _command_center_setup_block().upper()
        trust_block = block.split("TRUST_RISK AS (", 1)[1].split("),\n  READINESS AS", 1)[0]
        self.assertIn("COUNT_IF(UPPER(COALESCE(STATUS, 'UNKNOWN'))", trust_block)
        self.assertIn("AS ISSUE_COUNT", trust_block)
        self.assertIn("FROM MART_DATA_TRUST_SUMMARY", trust_block)
        self.assertNotIn("ORDER BY ISSUE_COUNT", trust_block)

    def test_command_center_normalizes_forecast_confidence_labels(self):
        block = _command_center_setup_block()
        self.assertIn("WHEN COALESCE(CONFIDENCE, '') IN ('High', 'Medium', 'Low')", block)
        self.assertIn("THEN 'estimated'", block)

    def test_command_center_block_has_no_silent_remediation_or_live_scans(self):
        block = _command_center_setup_block().upper()
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", block)
        self.assertNotIn("INFORMATION_SCHEMA", block)
        self.assertNotIn("SHOW ", block)
        for forbidden in [
            "EXECUTE IMMEDIATE",
            "SYSTEM$SEND_EMAIL",
            "ALTER WAREHOUSE",
            "DROP USER",
            "GRANT OWNERSHIP",
            "REVOKE ",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, block)
        self.assertIn("REVIEW_REQUIRED", block)
        self.assertIn("NO REMEDIATION SQL WAS EXECUTED", block)

    def test_documentation_covers_command_center_contract(self):
        docs = "\n".join(
            _read(ROOT / "docs" / name)
            for name in [
                "COMMAND_CENTER.md",
                "DATA_MODEL.md",
                "ENTERPRISE_OPERATING_MODEL.md",
                "APP_ARCHITECTURE.md",
            ]
        ).upper()
        for token in [
            "MART_COMMAND_CENTER_SUMMARY",
            "OVERWATCH_COMMAND_CENTER_FINDING",
            "OVERWATCH_COMMAND_CENTER_EVIDENCE",
            "OVERWATCH_COMMAND_CENTER_RECOMMENDATION",
            "SP_OVERWATCH_REFRESH_COMMAND_CENTER",
            "ROOT-CAUSE CANDIDATE",
            "POSSIBLE CORRELATION",
            "EXPLICIT LOAD",
            "NO SILENT REMEDIATION",
            "NON-AI",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, docs)


if __name__ == "__main__":
    unittest.main()
