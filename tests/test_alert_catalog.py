from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import alert_catalog  # noqa: E402
from utils import alerts  # noqa: E402


class _FakeSqlResult:
    def collect(self):
        return []


class _FakeSession:
    def __init__(self):
        self.sql_texts: list[str] = []

    def sql(self, sql_text: str):
        self.sql_texts.append(sql_text)
        return _FakeSqlResult()


class AlertCatalogTests(unittest.TestCase):
    def test_alerts_facade_reexports_catalog_functions(self):
        for name in (
            "alert_rule_audit_fqn",
            "alert_rule_catalog",
            "normalize_alert_rule_frame",
            "load_alert_rule_catalog",
            "build_alert_rule_audit_ddl",
            "build_alert_rule_audit_insert_sql",
            "load_alert_rule_audit",
            "build_alert_rule_update_sql",
            "update_alert_rule",
        ):
            self.assertIs(getattr(alerts, name), getattr(alert_catalog, name))

    def test_default_rule_catalog_and_normalization_contract(self):
        catalog = alerts.alert_rule_catalog()
        self.assertIn("RULE_ID", catalog.columns)
        self.assertIn("TASK_FAILURE", set(catalog["RULE_ID"]))

        normalized = alerts.normalize_alert_rule_frame(pd.DataFrame([{
            "RULE_ID": "TEST_RULE",
            "CATEGORY": "Reliability",
            "ALERT_TYPE": "Task Failure",
            "DEFAULT_SEVERITY": "critical",
            "SLA_HOURS": "999",
            "OWNER": None,
            "ROUTE": "Workload Operations",
            "RUNBOOK": "Review task telemetry and route to the owning pipeline team.",
            "IS_ACTIVE": "false",
        }]), source="Unit")

        row = normalized.iloc[0].to_dict()
        self.assertEqual(row["DEFAULT_SEVERITY"], "Critical")
        self.assertEqual(row["SLA_HOURS"], 168)
        self.assertEqual(row["OWNER"], "DBA")
        self.assertFalse(row["IS_ACTIVE"])
        self.assertEqual(row["RULE_SOURCE"], "Unit")

    def test_rule_update_and_audit_sql_contract(self):
        ddl = alerts.build_alert_rule_audit_ddl().upper()
        update_sql = alerts.build_alert_rule_update_sql(
            rule_id="task_failure",
            default_severity="critical",
            sla_hours=4,
            owner="DBA / Pipeline",
            route="Workload Operations",
            runbook="Review task graph impact and confirm safe recovery before retry.",
            actor="DBA_TEST",
        )
        audit_sql = alerts.build_alert_rule_audit_insert_sql(
            rule_id="task_failure",
            default_severity="critical",
            sla_hours=4,
            owner="DBA / Pipeline",
            route="Workload Operations",
            runbook="Review task graph impact and confirm safe recovery before retry.",
            actor="DBA_TEST",
            reason="Unit test catalog update.",
        )

        self.assertIn("CREATE TABLE IF NOT EXISTS DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERT_RULE_AUDIT", ddl)
        self.assertIn("UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERT_RULES", update_sql)
        self.assertIn("DEFAULT_SEVERITY = 'Critical'", update_sql)
        self.assertIn("SLA_HOURS = 4", update_sql)
        self.assertIn("WHERE RULE_ID = 'TASK_FAILURE'", update_sql)
        self.assertIn("INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERT_RULE_AUDIT", audit_sql)
        self.assertIn("'Unit test catalog update.'", audit_sql)

    def test_update_alert_rule_applies_audit_before_update(self):
        session = _FakeSession()

        alerts.update_alert_rule(
            session,
            rule_id="task_failure",
            default_severity="critical",
            sla_hours=4,
            owner="DBA / Pipeline",
            route="Workload Operations",
            runbook="Review task graph impact and confirm safe recovery before retry.",
            actor="DBA_TEST",
            reason="Unit test catalog update.",
        )

        self.assertEqual(len(session.sql_texts), 3)
        self.assertIn("CREATE TABLE IF NOT EXISTS", session.sql_texts[0])
        self.assertIn("INSERT INTO", session.sql_texts[1])
        self.assertIn("UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERT_RULES", session.sql_texts[2])

    def test_load_rule_catalog_falls_back_to_static_defaults(self):
        with patch("utils.alert_catalog.run_query", side_effect=RuntimeError("missing table")):
            catalog = alerts.load_alert_rule_catalog(section="Alert Center")

        self.assertFalse(catalog.empty)
        self.assertIn("Static Default", set(catalog["RULE_SOURCE"]))


if __name__ == "__main__":
    unittest.main()
