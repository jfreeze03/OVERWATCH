from pathlib import Path
import importlib
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


FACADE_THRESHOLDS = {
    "sections.task_management": 150,
    "sections.cost_center": 150,
    "sections.security_posture": 250,
    "sections.alert_center": 1000,
    "sections.dba_tools": 350,
    "sections.warehouse_health": 300,
    "sections.cost_contract": 300,
    "utils.shared_metrics": 250,
    "utils.alerts": 160,
}


FORBIDDEN_BY_MODULE = {
    "sections.task_management": (
        "SNOWFLAKE.ACCOUNT_USAGE",
        "INFORMATION_SCHEMA.QUERY_HISTORY",
        "run_query(",
        "run_query_or_raise(",
        "pd.DataFrame(",
        "ALTER TASK",
        "EXECUTE TASK",
        "SYSTEM$CANCEL",
        'elif task_view == "',
    ),
    "sections.cost_center": (
        "SNOWFLAKE.ACCOUNT_USAGE",
        "run_query(",
        "pd.DataFrame(",
        "CREATE TABLE",
        "INSERT INTO",
        'elif cost_view == "',
        "filter_existing_columns(",
    ),
    "sections.security_posture": (
        "SNOWFLAKE.ACCOUNT_USAGE",
        "run_query(",
        "run_query_or_raise(",
        "pd.DataFrame(",
        "CREATE TABLE",
        "INSERT INTO",
        "ALTER TABLE",
        "def _security_exception_verification_sql",
    ),
    "sections.alert_center": (
        "SNOWFLAKE.ACCOUNT_USAGE",
        "INFORMATION_SCHEMA.QUERY_HISTORY",
        "run_query(",
        "run_query_or_raise(",
        "CREATE TABLE",
        "ALTER TABLE",
        "INSERT INTO",
    ),
    "sections.dba_tools": (
        "SNOWFLAKE.ACCOUNT_USAGE",
        "INFORMATION_SCHEMA.QUERY_HISTORY",
        "run_query(",
        "run_query_or_raise(",
        "pd.DataFrame(",
        "ALTER TASK",
        "EXECUTE TASK",
        "SYSTEM$CANCEL",
        "ALTER ACCOUNT",
    ),
    "sections.warehouse_health": (
        "SNOWFLAKE.ACCOUNT_USAGE",
        "INFORMATION_SCHEMA.QUERY_HISTORY",
        "run_query(",
        "run_query_or_raise(",
        "pd.DataFrame(",
        "CREATE TABLE",
        "ALTER TABLE",
        "INSERT INTO",
    ),
    "sections.cost_contract": (
        "SNOWFLAKE.ACCOUNT_USAGE",
        "run_query(",
        "run_query_or_raise(",
        "pd.DataFrame(",
        "CREATE TABLE",
        "ALTER TABLE",
        "INSERT INTO",
    ),
    "utils.shared_metrics": (
        "SNOWFLAKE.ACCOUNT_USAGE",
        "run_query(",
        "run_query_or_raise(",
        "def load_shared_",
        "def build_shared_",
        "pd.DataFrame(",
    ),
    "utils.alerts": (
        "run_query(",
        "run_query_or_raise(",
        "pd.DataFrame(",
    ),
}


class FacadeNoCreepTests(unittest.TestCase):
    def test_completed_facades_stay_small_and_reexport_valid_names(self):
        for module_name, max_lines in FACADE_THRESHOLDS.items():
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                source_path = Path(module.__file__)
                source = source_path.read_text(encoding="utf-8")
                self.assertTrue(source_path.exists())
                self.assertLess(len(source.splitlines()), max_lines)
                for fragment in FORBIDDEN_BY_MODULE.get(module_name, ()):
                    with self.subTest(module=module_name, fragment=fragment):
                        self.assertNotIn(fragment, source)
                if hasattr(module, "__all__"):
                    for name in module.__all__:
                        with self.subTest(module=module_name, name=name):
                            self.assertTrue(hasattr(module, name))

    def test_renderer_maps_cover_contracts(self):
        task_management = importlib.import_module("sections.task_management")
        self.assertEqual(set(task_management.TASK_MANAGEMENT_RENDERERS), set(task_management.TASK_CONTROL_VIEWS))

        executive_landing_shell = importlib.import_module("sections.executive_landing_shell")
        executive_contracts = importlib.import_module("sections.executive_landing_contracts")
        self.assertEqual(
            set(executive_landing_shell.EXECUTIVE_LANDING_RENDERER_PATHS),
            set(executive_contracts.EXECUTIVE_LANDING_WORKFLOWS),
        )

        cost_center = importlib.import_module("sections.cost_center")
        self.assertEqual(set(cost_center.COST_CENTER_RENDERERS), set(cost_center.COST_CENTER_VIEWS))

        security_posture = importlib.import_module("sections.security_posture")
        covered_security = set(security_posture.SECURITY_POSTURE_RENDERERS) | set(security_posture.WORKFLOW_MODULES)
        self.assertEqual(covered_security, set(security_posture.SECURITY_POSTURE_VIEWS))

        alert_center = importlib.import_module("sections.alert_center")
        self.assertEqual(set(alert_center.ALERT_CENTER_RENDERERS), set(alert_center.ALERT_CENTER_PANES))
        self.assertEqual(set(alert_center.ALERT_CENTER_ADMIN_RENDERERS), set(alert_center.ALERT_CENTER_ADMIN_VIEWS))

        dba_tools = importlib.import_module("sections.dba_tools")
        catalog_tools = {tool for tools in dba_tools.DBA_TOOL_GROUPS.values() for tool in tools}
        self.assertEqual(set(dba_tools.DBA_TOOL_RENDERERS), catalog_tools)


if __name__ == "__main__":
    unittest.main()
