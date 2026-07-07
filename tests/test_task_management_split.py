from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import task_management  # noqa: E402
from sections import task_management_action_queue as action_queue  # noqa: E402
from sections import task_management_common as common  # noqa: E402
from sections import task_management_contracts as contracts  # noqa: E402
from sections import task_management_control_view as control_view  # noqa: E402
from sections import task_management_etl_audit_view as etl_audit_view  # noqa: E402
from sections import task_management_execute_view as execute_view  # noqa: E402
from sections import task_management_failure_console_view as failure_view  # noqa: E402
from sections import task_management_history_view as history_view  # noqa: E402
from sections import task_management_job_status_view as job_status_view  # noqa: E402
from sections import task_management_models as models  # noqa: E402
from sections import task_management_sla_cost_view as sla_cost_view  # noqa: E402
from sections import task_management_sql as sql_helpers  # noqa: E402


class TaskManagementSplitTests(unittest.TestCase):
    def test_task_management_contracts_stay_stable(self):
        self.assertEqual(
            task_management.TASK_CONTROL_VIEWS,
            (
                "Job Status Brief",
                "Failure Console",
                "SLA & Cost Drift",
                "Task History",
                "ETL Audit",
                "Control Center",
                "Execute Task",
            ),
        )
        self.assertEqual(set(task_management.TASK_CONTROL_VIEWS), set(task_management.TASK_CONTROL_DETAILS))
        self.assertEqual(task_management.TASK_FAILURE_STATES, {"FAILED", "FAILED_WITH_ERROR"})
        self.assertEqual(task_management.TASK_SUCCESS_STATES, {"SUCCEEDED", "SUCCESS", "COMPLETED"})
        self.assertEqual(task_management.TASK_RUNNING_STATES, {"EXECUTING", "RUNNING"})
        self.assertEqual(task_management.TASK_RECOVERY_SLA_HOURS, 4)

    def test_task_management_facade_reexports_focused_modules(self):
        for module in (
            contracts,
            common,
            models,
            sql_helpers,
            action_queue,
            job_status_view,
            failure_view,
            sla_cost_view,
            history_view,
            etl_audit_view,
            control_view,
            execute_view,
        ):
            for name in module.__all__:
                with self.subTest(module=module.__name__, name=name):
                    self.assertIs(getattr(task_management, name), getattr(module, name))
        for name in task_management.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(task_management, name))

    def test_task_management_renderer_map_covers_catalog(self):
        self.assertEqual(set(task_management.TASK_CONTROL_VIEWS), set(task_management.TASK_MANAGEMENT_RENDERERS))
        self.assertIs(task_management.TASK_MANAGEMENT_RENDERERS["Job Status Brief"], job_status_view.render_task_job_status_brief)
        self.assertIs(task_management.TASK_MANAGEMENT_RENDERERS["Failure Console"], failure_view.render_task_failure_console)
        self.assertIs(task_management.TASK_MANAGEMENT_RENDERERS["SLA & Cost Drift"], sla_cost_view.render_task_sla_cost_drift)
        self.assertIs(task_management.TASK_MANAGEMENT_RENDERERS["Task History"], history_view.render_task_history)
        self.assertIs(task_management.TASK_MANAGEMENT_RENDERERS["ETL Audit"], etl_audit_view.render_task_etl_audit)
        self.assertIs(task_management.TASK_MANAGEMENT_RENDERERS["Control Center"], control_view.render_task_control_center)
        self.assertIs(task_management.TASK_MANAGEMENT_RENDERERS["Execute Task"], execute_view.render_task_execute_task)

    def test_task_management_active_marker_is_rendered_before_session_load(self):
        source = Path(task_management.__file__).read_text(encoding="utf-8")

        self.assertIn("def _render_task_management_active_marker", source)
        self.assertIn("ow-task-management-selector", source)
        self.assertLess(
            source.index("_render_task_management_active_marker(task_view)"),
            source.index("get_session_for_action("),
        )

    def test_task_management_view_key_strings_are_preserved(self):
        sources = {
            "history": Path(history_view.__file__).read_text(encoding="utf-8"),
            "failure": Path(failure_view.__file__).read_text(encoding="utf-8"),
            "etl": Path(etl_audit_view.__file__).read_text(encoding="utf-8"),
            "control": Path(control_view.__file__).read_text(encoding="utf-8"),
            "execute": Path(execute_view.__file__).read_text(encoding="utf-8"),
        }
        for key in ("th_days", "th_load", "tg_list", "tg_hist", "tm_failed_queue"):
            self.assertIn(key, sources["history"])
        for key in (
            "tm_failure_days",
            "tm_failure_load",
            "tm_failure_category",
            "tm_failure_task_detail",
            "tm_failure_queue",
            "tm_failure_runbook_download",
        ):
            self.assertIn(key, sources["failure"])
        for key in ("etl_load", "tm_df_etl", "tm_etl_queue"):
            self.assertIn(key, sources["etl"])
        for key in (
            "tm_control_refresh",
            "tg_list",
            "tm_control_mode",
            "tm_control_root",
            "tm_graph_action",
            "tm_graph_confirm_",
            "tm_graph_run",
            "tm_task_action",
            "tm_task_confirm_",
            "tm_task_run",
        ):
            self.assertIn(key, sources["control"])
        for key in ("exec_task_sel", "exec_task_confirm_", "exec_task_btn"):
            self.assertIn(key, sources["execute"])
        self.assertIn("_cancel_task_graph_sql", sources["control"])
        self.assertIn("_cancel_task_query_sql", sources["control"])
        self.assertNotIn("SYSTEM$CANCEL_TASK_GRAPH(", sources["control"])
        self.assertNotIn("SYSTEM$CANCEL_QUERY(", sources["control"])
        self.assertIn("_execute_task_sql", sources["execute"])
        self.assertNotIn('f"EXECUTE TASK {full}"', sources["execute"])

    def test_task_management_facade_no_implementation_creep(self):
        source = Path(task_management.__file__).read_text(encoding="utf-8")
        self.assertLess(source.count("\n") + 1, 150)
        self.assertIn("TASK_MANAGEMENT_RENDERERS", source)
        self.assertIn("render_workflow_selector", source)
        for fragment in (
            "SNOWFLAKE.ACCOUNT_USAGE",
            "INFORMATION_SCHEMA.QUERY_HISTORY",
            "run_query(",
            "run_query_or_raise(",
            "pd.DataFrame(",
            "CREATE TABLE",
            "ALTER TABLE",
            "INSERT INTO",
            "ALTER TASK",
            "EXECUTE TASK",
            "SYSTEM$CANCEL",
            'elif task_view == "',
            'elif task_view == "ETL Audit"',
            'elif task_view == "Control Center"',
            'elif task_view == "Execute Task"',
            "# -- ETL AUDIT",
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

    def test_task_model_helpers_preserve_graph_contracts(self):
        self.assertEqual(task_management._qualified_name("DB", 'SC"H', "TASK"), '"DB"."SC""H"."TASK"')
        self.assertEqual(
            task_management._procedure_from_definition("CALL ALFA_DB.PUBLIC.SP_LOAD_POLICY();"),
            "ALFA_DB.PUBLIC.SP_LOAD_POLICY",
        )
        self.assertEqual(task_management._procedure_from_definition("SELECT 1"), "")
        candidates = task_management._extract_object_candidates(
            "SELECT * FROM RAW.A JOIN B.C ON 1=1; UPDATE D.E SET X=1; MERGE INTO F.G USING H.I; CALL J.K();"
        )
        for token in ("RAW.A", "B.C", "D.E", "F.G", "H.I", "J.K"):
            with self.subTest(token=token):
                self.assertIn(token, candidates)
        self.assertEqual(task_management._parse_task_predecessors(""), [])
        self.assertEqual(task_management._parse_task_predecessors("[]"), [])
        self.assertEqual(task_management._parse_task_predecessors(None), [])
        self.assertEqual(task_management._parse_task_predecessors("nan"), [])
        self.assertEqual(task_management._parse_task_predecessors("['DB.SCHEMA.ROOT_TASK']"), ["ROOT_TASK"])
        self.assertEqual(
            task_management._task_root_name(pd.Series({"NAME": "CHILD", "PREDECESSORS": "DB.SCHEMA.ROOT"})),
            "ROOT",
        )
        self.assertEqual(task_management._task_root_name(pd.Series({"NAME": "ROOT", "PREDECESSORS": "[]"})), "ROOT")

    def test_task_masks_and_graph_impact(self):
        frame = pd.DataFrame({
            "STATE": ["FAILED", "SUCCEEDED", "RUNNING", "OK"],
            "ERROR_MESSAGE": ["", "", "boom", "nan"],
        })
        self.assertEqual(task_management._task_failure_mask(frame).tolist(), [True, False, True, False])
        self.assertEqual(task_management._task_success_mask(frame).tolist(), [False, True, False, False])
        self.assertEqual(task_management._blankish_series(pd.Series(["", None, "nan", "ok"])).tolist(), [True, True, True, False])

        inventory = pd.DataFrame({
            "DATABASE_NAME": ["DB", "DB", "DB"],
            "SCHEMA_NAME": ["PUBLIC", "PUBLIC", "PUBLIC"],
            "NAME": ["ROOT", "CHILD", "LEAF"],
            "PREDECESSORS": ["[]", "DB.PUBLIC.ROOT", "DB.PUBLIC.CHILD"],
            "STATE": ["started", "started", "suspended"],
        })
        annotated = task_management._annotate_task_graph_impact(inventory)
        by_name = {row["NAME"]: row for _, row in annotated.iterrows()}
        self.assertEqual(by_name["ROOT"]["GRAPH_ROLE"], "Root")
        self.assertEqual(by_name["CHILD"]["GRAPH_ROLE"], "Intermediate")
        self.assertEqual(by_name["LEAF"]["GRAPH_ROLE"], "Leaf")
        self.assertGreaterEqual(int(by_name["ROOT"]["DOWNSTREAM_TASK_COUNT"]), 2)
        self.assertIn("graph", str(by_name["ROOT"]["RETRY_SCOPE"]).lower())

    def test_admin_sql_and_confirmation_contracts(self):
        row = pd.Series({"DATABASE_NAME": "ALFA_PROD", "SCHEMA_NAME": "PUBLIC", "NAME": "ROOT_TASK"})
        self.assertEqual(task_management._task_full_name(row), '"ALFA_PROD"."PUBLIC"."ROOT_TASK"')
        self.assertTrue(task_management._is_prod_task(row))
        self.assertTrue(task_management._confirmation_phrase(row, "SUSPEND").startswith("PROD "))
        self.assertEqual(task_management._admin_sql_for_task(row, "EXECUTE"), ['EXECUTE TASK "ALFA_PROD"."PUBLIC"."ROOT_TASK"'])
        graph = pd.DataFrame({
            "DATABASE_NAME": ["ALFA_PROD", "ALFA_PROD"],
            "SCHEMA_NAME": ["PUBLIC", "PUBLIC"],
            "NAME": ["ROOT_TASK", "CHILD_TASK"],
            "PREDECESSORS": ["[]", "ALFA_PROD.PUBLIC.ROOT_TASK"],
        })
        resume_sql = task_management._admin_sql_for_graph(graph, "ROOT_TASK", "RESUME")
        self.assertTrue(resume_sql[-1].endswith('"ROOT_TASK" RESUME'))
        self.assertIn('"CHILD_TASK" RESUME', resume_sql[0])
        suspend_sql = task_management._admin_sql_for_graph(graph, "ROOT_TASK", "SUSPEND")
        self.assertEqual(suspend_sql, ['ALTER TASK "ALFA_PROD"."PUBLIC"."ROOT_TASK" SUSPEND'])

        graph_cancel_sql = task_management._cancel_task_graph_sql("O'HARE")
        self.assertIn("SYSTEM$CANCEL_TASK_GRAPH", graph_cancel_sql)
        self.assertIn("'O''HARE'", graph_cancel_sql)
        query_cancel_sql = task_management._cancel_task_query_sql("01a'b")
        self.assertIn("SYSTEM$CANCEL_QUERY", query_cancel_sql)
        self.assertIn("'01a''b'", query_cancel_sql)
        self.assertEqual(
            task_management._execute_task_sql('"ALFA_PROD"."PUBLIC"."ROOT_TASK"'),
            'EXECUTE TASK "ALFA_PROD"."PUBLIC"."ROOT_TASK"',
        )

    def test_task_action_queue_payloads_are_review_only(self):
        row = pd.Series({
            "TASK_FQN": '"DB"."PUBLIC"."TASK_A"',
            "TASK_NAME": "TASK_A",
            "FAILURE_CATEGORY": "Task Failure",
            "ERROR_MESSAGE": "failed",
            "INCIDENT_PRIORITY": "P1",
            "RECOVERY_READINESS": "Blocked: workflow route required",
            "REVIEW_STATE": "Review Required",
            "ENVIRONMENT": "PROD",
            "RETRY_SQL": "EXECUTE TASK \"DB\".\"PUBLIC\".\"TASK_A\"",
        })
        with (
            patch("sections.task_management_action_queue.resolve_owner_context", return_value={"OWNER": "Data Engineering"}),
            patch("sections.task_management_action_queue.make_action_id", return_value="TASK-ACTION"),
        ):
            payload = task_management._build_task_reliability_action(row, "ALFA", "Task Management")
        self.assertEqual(payload["Source"], "Task Management")
        self.assertEqual(payload["Category"], "Task & Procedure Reliability")
        self.assertEqual(payload["Entity"], '"DB"."PUBLIC"."TASK_A"')
        self.assertIn("Do not execute until root cause is fixed", payload["Generated SQL Fix"])
        self.assertIn("EXECUTE TASK", payload["Generated SQL Fix"])
        self.assertIn("TASK_HISTORY", payload["Proof Query"].upper())

    def test_empty_queue_writers_do_not_call_upsert_actions(self):
        with (
            patch("sections.task_management_action_queue.st.info"),
            patch("sections.task_management_action_queue.upsert_actions") as upsert,
        ):
            task_management._queue_task_findings(object(), pd.DataFrame(), "Task Management")
        upsert.assert_not_called()
        with patch("sections.task_management_action_queue._queue_task_ops_findings") as queue_ops:
            self.assertEqual(task_management._queue_failure_findings(object(), pd.DataFrame()), 0)
        queue_ops.assert_not_called()


if __name__ == "__main__":
    unittest.main()
