from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SnowflakeCredentialValidationTests(unittest.TestCase):
    def test_static_credential_and_user_display_artifacts_pass(self):
        from tools.contracts.security_credential_validation import (
            build_credential_expiration_live_results,
            build_credential_expiration_validation,
            build_credential_rendered_leak_gate,
            build_credential_sql_inventory_gate,
            build_cortex_user_label_results,
            build_security_credential_evidence_results,
            build_security_credential_export_results,
            build_security_credential_first_paint_results,
            build_security_credential_render_results,
            build_user_display_dimension_validation,
            build_user_display_dimension_live_results,
            build_user_display_surface_results,
        )

        credential = build_credential_expiration_validation(ROOT)
        credential_live = build_credential_expiration_live_results(ROOT, "internal_fixture")
        user_display = build_user_display_dimension_validation(ROOT)
        user_display_live = build_user_display_dimension_live_results(ROOT, "internal_fixture")
        user_surface = build_user_display_surface_results(ROOT)
        cortex_labels = build_cortex_user_label_results(ROOT)
        credential_export = build_security_credential_export_results(ROOT)
        credential_render = build_security_credential_render_results(ROOT)
        credential_evidence = build_security_credential_evidence_results(ROOT)
        credential_first_paint = build_security_credential_first_paint_results(ROOT)
        credential_sql_inventory = build_credential_sql_inventory_gate(ROOT)
        credential_rendered_leak = build_credential_rendered_leak_gate(ROOT)

        self.assertTrue(credential["passed"], credential.get("failures"))
        self.assertTrue(credential_live["passed"], credential_live.get("failures"))
        self.assertTrue(credential_live["live_skipped"])
        self.assertFalse(credential_live["live_passed"])
        self.assertTrue(user_display["passed"], user_display.get("failures"))
        self.assertTrue(user_display_live["passed"], user_display_live.get("failures"))
        self.assertTrue(user_display_live["live_skipped"])
        self.assertFalse(user_display_live["live_passed"])
        self.assertTrue(user_surface["passed"], user_surface.get("failures"))
        self.assertTrue(cortex_labels["passed"], cortex_labels.get("failures"))
        self.assertTrue(credential_export["passed"], credential_export.get("failures"))
        self.assertTrue(credential_render["passed"], credential_render.get("failures"))
        self.assertTrue(credential_evidence["passed"], credential_evidence.get("failures"))
        self.assertTrue(credential_first_paint["passed"], credential_first_paint.get("failures"))
        self.assertTrue(credential_sql_inventory["passed"], credential_sql_inventory.get("failures"))
        self.assertTrue(credential_rendered_leak["passed"], credential_rendered_leak.get("failures"))

    def test_launch_gates_fail_when_artifact_has_failures(self):
        from tools.contracts.security_credential_validation import (
            evaluate_security_credential_expiration_gate,
            evaluate_security_credential_expiration_live_gate,
            evaluate_user_display_name_gate,
            evaluate_user_display_name_live_gate,
        )

        credential_gate = evaluate_security_credential_expiration_gate(
            {"passed": False, "failures": [{"check": "missing"}]}
        )
        user_gate = evaluate_user_display_name_gate(
            {"passed": False, "failures": [{"check": "missing"}]}
        )
        credential_live_gate = evaluate_security_credential_expiration_live_gate(
            {"live_skipped": True, "live_validation_status": "not_executed_static_contract"},
            "internal_live",
        )
        user_live_gate = evaluate_user_display_name_live_gate(
            {"live_skipped": True, "live_validation_status": "not_executed_static_contract"},
            "internal_live",
        )

        self.assertFalse(credential_gate["passed"])
        self.assertFalse(user_gate["passed"])
        self.assertFalse(credential_live_gate["passed"])
        self.assertFalse(user_live_gate["passed"])

    def test_launch_readiness_requires_credential_and_user_display_gates(self):
        from tools.contracts.launch_readiness import REQUIRED_LAUNCH_READINESS_ARTIFACTS
        from tools.contracts.security_credential_validation import (
            CORTEX_USER_LABEL_GATE_REL,
            SECURITY_CREDENTIAL_EVIDENCE_GATE_REL,
            SECURITY_CREDENTIAL_GATE_REL,
            SECURITY_CREDENTIAL_EXPORT_GATE_REL,
            SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL,
            SECURITY_CREDENTIAL_LIVE_GATE_REL,
            SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL,
            SECURITY_CREDENTIAL_RENDER_GATE_REL,
            SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL,
            USER_DISPLAY_NAME_GATE_REL,
            USER_DISPLAY_NAME_LIVE_GATE_REL,
            USER_DISPLAY_SURFACE_GATE_REL,
        )

        self.assertIn(SECURITY_CREDENTIAL_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SECURITY_CREDENTIAL_LIVE_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(USER_DISPLAY_NAME_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(USER_DISPLAY_NAME_LIVE_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(USER_DISPLAY_SURFACE_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(CORTEX_USER_LABEL_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SECURITY_CREDENTIAL_EXPORT_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SECURITY_CREDENTIAL_RENDER_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SECURITY_CREDENTIAL_EVIDENCE_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)

    def test_validation_sql_contains_required_objects_and_fields(self):
        validation_sql = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(
            encoding="utf-8"
        ).upper()
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(
            encoding="utf-8"
        ).upper()

        required_tokens = [
            "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT",
            "MART_USER_DIM_CURRENT",
            "SECURITY_CREDENTIALS_EXPIRING_30D_COUNT",
            "SECURITY_CREDENTIAL_EXPIRATION_FINDINGS",
            "USER_DISPLAY_NAME",
            "USER_CHART_LABEL",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, validation_sql)
                self.assertIn(token, setup_sql)

    def test_sql_value_inventory_has_owned_credential_paths(self):
        from tools.contracts.sql_value_inventory import build_sql_value_inventory

        inventory = build_sql_value_inventory(ROOT)
        rows = {row["path_id"]: row for row in inventory["rows"]}
        for path_id in (
            "credential_expiration_refresh_source",
            "credential_expiration_compact_mart",
            "user_display_dimension_refresh_source",
            "credential_expiration_compact_evidence",
            "credential_expiration_evidence",
            "credential_expiration_security_packet",
            "credential_expiration_alert_action",
            "credential_expiration_live_validation",
            "cortex_user_label_source",
            "cortex_user_label_export_sanitizer",
        ):
            with self.subTest(path_id=path_id):
                self.assertIn(path_id, rows)
                self.assertEqual(rows[path_id]["owner"], "Security Monitoring")
                self.assertTrue(rows[path_id]["daily_safe"])
        self.assertEqual(
            rows["credential_expiration_security_packet"]["account_usage_use"],
            "none",
        )


if __name__ == "__main__":
    unittest.main()
