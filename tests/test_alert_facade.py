from pathlib import Path
import ast
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import alerts  # noqa: E402
from utils import alert_action_queue  # noqa: E402
from utils import alert_annotations  # noqa: E402
from utils import alert_boards  # noqa: E402
from utils import alert_catalog  # noqa: E402
from utils import alert_command_center  # noqa: E402
from utils import alert_delivery  # noqa: E402
from utils import alert_lifecycle  # noqa: E402
from utils import alert_native_catalog  # noqa: E402
from utils import alert_triage  # noqa: E402


class AlertFacadeCompatibilityTests(unittest.TestCase):
    def test_representative_imports_still_work_from_utils_alerts(self):
        from utils.alerts import (  # noqa: F401
            ALERT_STATUS_CHOICES,
            DEFAULT_ALERT_RECIPIENT,
            alert_history_to_actions,
            alert_rule_catalog,
            alert_table_fqn,
            annotate_alert_triage_frame,
            build_alert_command_center_summary,
            build_alert_data_quality_checks_ddl,
            build_alert_digest_summary,
            build_alert_email_body,
            build_alert_event_materialization_sql,
            build_alert_incident_action_board,
            build_alert_insert_sql,
            build_alert_native_registry_ddl,
            build_alert_remediation_contract,
            build_alert_status_update_sql,
            build_alert_triage_view_sql,
            build_annotation_ddl,
            build_dashboard_issue_rows,
            current_alert_recipient,
            load_alert_history,
            mark_alerts_routed,
            normalize_alert_status,
            update_alert_status,
        )

        self.assertTrue(callable(build_alert_insert_sql))
        self.assertTrue(callable(build_alert_command_center_summary))
        self.assertTrue(callable(load_alert_history))
        self.assertEqual(ALERT_STATUS_CHOICES, ("Acknowledged", "In Progress", "Fixed", "Ignored"))

    def test_facade_points_to_focused_modules_for_representative_exports(self):
        expected = {
            "alert_history_to_actions": alert_action_queue.alert_history_to_actions,
            "mark_alerts_routed": alert_action_queue.mark_alerts_routed,
            "build_annotation_ddl": alert_annotations.build_annotation_ddl,
            "build_alert_triage_view_sql": alert_annotations.build_alert_triage_view_sql,
            "build_alert_command_center_summary": alert_boards.build_alert_command_center_summary,
            "build_alert_incident_action_board": alert_boards.build_alert_incident_action_board,
            "build_section_alert_signal_board": alert_boards.build_section_alert_signal_board,
            "build_alert_remediation_contract": alert_boards.build_alert_remediation_contract,
            "alert_rule_catalog": alert_catalog.alert_rule_catalog,
            "build_alert_rule_update_sql": alert_catalog.build_alert_rule_update_sql,
            "build_alert_event_materialization_sql": alert_command_center.build_alert_event_materialization_sql,
            "build_alert_signal_query_catalog": alert_command_center.build_alert_signal_query_catalog,
            "build_alert_email_body": alert_delivery.build_alert_email_body,
            "current_alert_recipient": alert_delivery.current_alert_recipient,
            "build_alert_insert_sql": alert_lifecycle.build_alert_insert_sql,
            "update_alert_status": alert_lifecycle.update_alert_status,
            "build_alert_data_quality_checks_ddl": alert_native_catalog.build_alert_data_quality_checks_ddl,
            "load_alert_native_object_registry": alert_native_catalog.load_alert_native_object_registry,
            "load_alert_history": alert_triage.load_alert_history,
            "normalize_alert_status": alert_triage.normalize_alert_status,
        }

        for name, target in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(alerts, name), target)

    def test_no_internal_direct_private_imports_from_alert_facade(self):
        offenders: list[str] = []
        scan_roots = [APP_ROOT / "sections", APP_ROOT / "utils", ROOT / "tests"]
        for root in scan_roots:
            paths = root.rglob("*.py") if root.is_dir() else []
            for path in paths:
                if path == APP_ROOT / "utils" / "alerts.py":
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ImportFrom):
                        continue
                    if node.module != "utils.alerts":
                        continue
                    private_names = [alias.name for alias in node.names if alias.name.startswith("_")]
                    if private_names:
                        offenders.append(f"{path.relative_to(ROOT)}: {', '.join(private_names)}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
