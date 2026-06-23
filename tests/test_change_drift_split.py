from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import change_drift  # noqa: E402
from sections import change_drift_action_queue as action_queue  # noqa: E402
from sections import change_drift_brief_view as brief_view  # noqa: E402
from sections import change_drift_common as common  # noqa: E402
from sections import change_drift_contracts as contracts  # noqa: E402
from sections import change_drift_models as models  # noqa: E402
from sections import change_drift_sql as sql_helpers  # noqa: E402
from sections import change_drift_workflows_view as workflows_view  # noqa: E402


class ChangeDriftSplitTests(unittest.TestCase):
    def setUp(self):
        self._session_state = dict(st.session_state)
        st.session_state.clear()

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self._session_state)

    def test_change_drift_contracts_stay_stable(self):
        self.assertEqual(change_drift.CHANGE_DRIFT_VIEWS, ("Change Brief", "Change Workflows"))
        self.assertEqual(set(change_drift.CHANGE_DRIFT_VIEWS), set(change_drift.CHANGE_DRIFT_VIEW_DETAILS))
        self.assertEqual(change_drift.CHANGE_DRIFT_BRIEF_FIRST_VERSION, 2)
        self.assertEqual(
            change_drift.WORKFLOWS,
            (
                "Object and access changes",
                "Schema and object drift",
                "Data movement and replication",
                "Stored procedure lineage",
                "Controlled DBA actions",
            ),
        )
        self.assertEqual(set(change_drift.WORKFLOWS), set(change_drift.WORKFLOW_DETAILS))
        self.assertEqual(change_drift.WORKFLOW_MODULES["Object and access changes"], "sections.object_change_monitor")
        self.assertEqual(change_drift.WORKFLOW_MODULES["Stored procedure lineage"], "sections.stored_proc_tracker")
        self.assertEqual(change_drift.WORKFLOW_MODULES["Schema and object drift"], "sections.dba_tools")
        self.assertEqual(change_drift.WORKFLOW_MODULES["Data movement and replication"], "sections.dba_tools")
        self.assertEqual(change_drift.WORKFLOW_MODULES["Controlled DBA actions"], "sections.dba_tools")
        self.assertEqual(change_drift.CHANGE_CONTROL_EVIDENCE_TABLE, "OVERWATCH_CHANGE_CONTROL_EVIDENCE")
        self.assertEqual(change_drift.CHANGE_CONTROL_OPERABILITY_FACT_TABLE, "FACT_CHANGE_CONTROL_OPERABILITY_DAILY")
        self.assertEqual(
            change_drift.CHANGE_SCOPE_FILTER_KEYS,
            (
                "global_warehouse",
                "global_user",
                "global_role",
                "global_database",
                "global_start_date",
                "global_end_date",
            ),
        )
        for row in change_drift.CHANGE_BRIEF_WORKFLOWS:
            for key in ("WORKFLOW", "BUTTON_LABEL", "DBA_MOVE", "WHEN"):
                self.assertIn(key, row)

    def test_change_drift_facade_reexports_focused_modules(self):
        for module in (contracts, common, sql_helpers, models, action_queue, brief_view, workflows_view):
            for name in module.__all__:
                with self.subTest(module=module.__name__, name=name):
                    self.assertIs(getattr(change_drift, name), getattr(module, name))
        for name in change_drift.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(change_drift, name))

    def test_change_drift_renderer_map_and_facade_no_creep(self):
        self.assertEqual(set(change_drift.CHANGE_DRIFT_VIEWS), set(change_drift.CHANGE_DRIFT_RENDERERS))
        self.assertIs(change_drift.CHANGE_DRIFT_RENDERERS["Change Brief"], brief_view.render_change_brief)
        self.assertIs(change_drift.CHANGE_DRIFT_RENDERERS["Change Workflows"], workflows_view.render_change_workflows)
        source = Path(change_drift.__file__).read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 500)
        for fragment in (
            "CREATE TABLE IF NOT EXISTS",
            "ALTER TABLE",
            "INSERT INTO",
            "def build_change_control_evidence_ddl",
            "def build_change_control_operability_fact_ddl",
            "def _change_ticket_id",
            'if active_view == "Change Brief"',
            'elif active_view == "Change Workflows"',
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

    def test_change_drift_view_sources_preserve_keys_and_workflow_buttons(self):
        brief_source = Path(brief_view.__file__).read_text(encoding="utf-8")
        workflow_source = Path(workflows_view.__file__).read_text(encoding="utf-8")
        self.assertIn('row["BUTTON_LABEL"]', brief_source)
        self.assertIn("change_brief_", brief_source)
        for key in (
            "change_drift_brief_load",
            "change_drift_evidence_snapshot",
            "change_drift_evidence_trend_load",
            "change_action_closure_load",
            "change_drift_queue",
            "change_drift_download",
        ):
            self.assertIn(key, brief_source)
        self.assertIn("change_drift_workflow", workflow_source)
        self.assertIn("dba_tools_focus", workflow_source)

    def test_common_scope_and_confidence_helpers(self):
        self.assertEqual(change_drift.get_active_company(), "ALFA")
        self.assertEqual(change_drift.get_active_environment(), "ALL")
        st.session_state["active_company"] = "Trexis"
        st.session_state["global_environment"] = "prod"
        self.assertEqual(change_drift.get_active_company(), "Trexis")
        self.assertEqual(change_drift.get_active_environment(), "prod")

        self.assertIn("INFORMATION_SCHEMA", change_drift._freshness_note("information_schema.task_history"))
        self.assertIn("45-90", change_drift._freshness_note("ACCOUNT_USAGE.QUERY_HISTORY"))
        self.assertIn("fast summary", change_drift._freshness_note("mart object"))
        self.assertIn("depends", change_drift._freshness_note("unknown").lower())
        self.assertEqual(change_drift._metric_confidence_label("exact"), "Measurement: Exact")
        self.assertIn("Allocated", change_drift._metric_confidence_label("allocated"))
        self.assertIn("Estimated", change_drift._metric_confidence_label("estimated"))
        self.assertIn("depends", change_drift._metric_confidence_label("other").lower())

    def test_render_workflow_module_warns_or_dispatches(self):
        with patch("sections.change_drift_common.st.warning") as warning:
            change_drift.render_workflow_module("Missing", {})
        warning.assert_called_once()

        module = Mock()
        module.render = Mock()
        with patch("sections.change_drift_common.import_module", return_value=module):
            change_drift.render_workflow_module("Object and access changes", {
                "Object and access changes": "sections.object_change_monitor"
            })
        module.render.assert_called_once()

        module_without_render = Mock(spec=[])
        with (
            patch("sections.change_drift_common.import_module", return_value=module_without_render),
            patch("sections.change_drift_common.st.warning") as warning,
        ):
            change_drift.render_workflow_module("Object and access changes", {
                "Object and access changes": "sections.object_change_monitor"
            })
        warning.assert_called_once()

    def test_change_control_sql_contracts(self):
        fqn = change_drift.change_control_evidence_fqn("DB", "SCHEMA", "TAB")
        self.assertIn("DB", fqn)
        self.assertIn("SCHEMA", fqn)
        self.assertIn("TAB", fqn)
        ddl = change_drift.build_change_control_evidence_ddl("DB", "SCHEMA", "TAB")
        for column in (
            "CHANGE_TICKET_ID",
            "APPROVAL_ROUTE_READY",
            "CHANGE_EVIDENCE_READINESS",
            "VERIFICATION_QUERY",
            "BLAST_RADIUS_QUERY",
        ):
            self.assertIn(column, ddl)
        migrations = change_drift.build_change_control_evidence_migration_sql("DB", "SCHEMA", "TAB")
        self.assertTrue(all("ADD COLUMN IF NOT EXISTS" in sql for sql in migrations))

        with patch("sections.change_drift_sql.mart_object_name", return_value="MART.FACT_CHANGE"):
            self.assertEqual(change_drift.change_control_operability_fact_fqn(), "MART.FACT_CHANGE")
            fact_ddl = change_drift.build_change_control_operability_fact_ddl()
            fact_migrations = change_drift.build_change_control_operability_fact_migration_sql()
        for column in ("CONTROL_STATE", "CONTROL_RANK", "NEXT_CONTROL_ACTION"):
            self.assertIn(column, fact_ddl)
        self.assertTrue(all("ADD COLUMN IF NOT EXISTS" in sql for sql in fact_migrations))

    def test_change_ticket_and_qualified_name_parsing(self):
        cases = [
            {"QUERY_TAG": "deploy CHG-1234"},
            {"QUERY_TEXT": "/* INC9876 */ select 1"},
            {"PROOF_QUERY": "RFC_444 update"},
            {"QUERY_TAG": "ABC-123 issue"},
        ]
        for row in cases:
            with self.subTest(row=row):
                self.assertTrue(change_drift._change_ticket_id(row))
        self.assertEqual(change_drift._change_ticket_id({"QUERY_TEXT": "select 1"}), "")
        self.assertEqual(
            change_drift._split_snowflake_qualified_name('"DB"."SCHEMA.WITH.DOT"."OBJ""Q"'),
            ["DB", "SCHEMA.WITH.DOT", 'OBJ"Q'],
        )

    def test_change_action_queue_payloads_remain_review_only(self):
        row = pd.Series({
            "FINDING_TYPE": "Policy or Tag Change",
            "ENTITY": "DB.PUBLIC.TABLE_A",
            "USER_NAME": "ANALYST",
            "SEVERITY": "High",
            "QUERY_ID": "01abc",
            "QUERY_TAG": "CHG-1234",
            "DATABASE_NAME": "ALFA_PROD",
        })
        with (
            patch("sections.change_drift_action_queue.make_action_id", return_value="CHANGE-ACTION"),
            patch("sections.change_drift_models.resolve_owner_context", return_value={"OWNER": "Security Route"}),
        ):
            payload = change_drift._change_action_payload(row, "ALFA", "PROD")
        self.assertEqual(payload["Action ID"], "CHANGE-ACTION")
        self.assertEqual(payload["Source"], "Change & Drift - Brief")
        self.assertEqual(payload["Category"], "Object Change Monitoring")
        self.assertEqual(payload["Entity"], "DB.PUBLIC.TABLE_A")
        self.assertEqual(payload["Ticket ID"], "CHG-1234")
        self.assertIn("Do not execute state-changing SQL", payload["Generated SQL Fix"])
        for forbidden in ("ALTER TABLE", "DROP TABLE", "CREATE TABLE"):
            self.assertNotIn(forbidden, payload["Generated SQL Fix"].upper())

    def test_change_queue_writer_empty_and_session_passthrough(self):
        with (
            patch("sections.change_drift_action_queue.st.info"),
            patch("sections.change_drift_action_queue.upsert_actions") as upsert,
        ):
            change_drift._queue_change_exceptions(object(), pd.DataFrame())
        upsert.assert_not_called()

        session = object()
        frame = pd.DataFrame([{"FINDING_TYPE": "Object Change", "ENTITY": "DB.PUBLIC.T", "SEVERITY": "Low"}])
        with (
            patch("sections.change_drift_action_queue.get_active_company", return_value="ALFA"),
            patch("sections.change_drift_action_queue.get_active_environment", return_value="ALL"),
            patch("sections.change_drift_action_queue._change_action_payload", return_value={"Action ID": "A1"}),
            patch("sections.change_drift_action_queue.upsert_actions", return_value=1) as upsert,
            patch("sections.change_drift_action_queue.st.success"),
        ):
            change_drift._queue_change_exceptions(session, frame)
        upsert.assert_called_once()
        self.assertIs(upsert.call_args.args[0], session)


if __name__ == "__main__":
    unittest.main()
