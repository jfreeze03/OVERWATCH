from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import dba_tools  # noqa: E402
from sections import dba_tools_cortex_limits_view as cortex_limits  # noqa: E402


class DbaToolsCortexLimitsTests(unittest.TestCase):
    def test_cortex_renderer_is_registered(self):
        self.assertIs(dba_tools.DBA_TOOL_RENDERERS["Cortex AI Limits"], cortex_limits.render_cortex_ai_limits_tool)
        self.assertNotIn("Cortex AI Limits", dba_tools.INLINE_DBA_TOOL_HANDLERS)

    def test_cortex_quota_sql_contract(self):
        self.assertNotIn("ALTER ACCOUNT SET", cortex_limits._cortex_code_quota_sql(0))
        self.assertIn(
            "ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = 500;",
            cortex_limits._cortex_code_quota_sql(500),
        )

    def test_cortex_apply_guard_preserves_accountadmin_gate(self):
        for role in ("ACCOUNTADMIN", "SNOW_ACCOUNTADMINS"):
            with self.subTest(role=role):
                allowed, message = cortex_limits._can_apply_cortex_limit(role, 100)
                self.assertTrue(allowed)
                self.assertEqual(message, "")

        for role in ("", "SYSADMIN", "SNOW_SYSADMINS", "SECURITYADMIN", "APP_READONLY"):
            with self.subTest(role=role):
                allowed, message = cortex_limits._can_apply_cortex_limit(role, 100)
                self.assertFalse(allowed)
                self.assertIn("ALTER ACCOUNT requires ACCOUNTADMIN", message)

        allowed, message = cortex_limits._can_apply_cortex_limit("ACCOUNTADMIN", 0)
        self.assertFalse(allowed)
        self.assertIn("positive Cortex Code daily credit limit", message)

    def test_cortex_readiness_rows_contract(self):
        rows = cortex_limits._cortex_readiness_rows()
        self.assertEqual(
            list(rows["CAPABILITY"]),
            ["Cortex Code", "Cortex Search", "Cortex Analyst / Intelligence"],
        )


if __name__ == "__main__":
    unittest.main()
