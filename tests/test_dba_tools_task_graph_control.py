from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import dba_tools  # noqa: E402
from sections import dba_tools_task_graph_control as task_graph  # noqa: E402
from sections import dba_tools_task_graph_control_view as task_graph_view  # noqa: E402


class DbaToolsTaskGraphControlTests(unittest.TestCase):
    def test_task_graph_renderer_is_registered(self):
        self.assertIs(
            dba_tools.DBA_TOOL_RENDERERS["Task Graph Control"],
            task_graph_view.render_task_graph_control_tool,
        )
        self.assertNotIn("Task Graph Control", dba_tools.INLINE_DBA_TOOL_HANDLERS)

    def test_root_and_child_task_detection(self):
        df_tasks = pd.DataFrame([
            {"NAME": "ROOT_EMPTY", "PREDECESSORS": ""},
            {"NAME": "ROOT_BRACKETS", "PREDECESSORS": "[]"},
            {"NAME": "ROOT_NONE", "PREDECESSORS": None},
            {"NAME": "ROOT_NAN", "PREDECESSORS": float("nan")},
            {"NAME": "CHILD_A", "PREDECESSORS": "ROOT_EMPTY"},
            {"NAME": "CHILD_B", "PREDECESSORS": '["ROOT_EMPTY"]'},
            {"NAME": "OTHER_CHILD", "PREDECESSORS": "ROOT_BRACKETS"},
        ])

        roots = task_graph._root_tasks_frame(df_tasks)
        self.assertEqual(
            set(roots["NAME"]),
            {"ROOT_EMPTY", "ROOT_BRACKETS", "ROOT_NONE", "ROOT_NAN"},
        )

        children = task_graph._child_tasks_for_root(df_tasks, "ROOT_EMPTY")
        self.assertEqual(set(children["NAME"]), {"CHILD_A", "CHILD_B"})

    def test_child_detection_uses_literal_root_names(self):
        df_tasks = pd.DataFrame([
            {"NAME": "ROOT.A[1]", "PREDECESSORS": ""},
            {"NAME": "LITERAL_CHILD", "PREDECESSORS": '["ROOT.A[1]"]'},
            {"NAME": "REGEX_LOOKALIKE", "PREDECESSORS": "ROOTXA1"},
            {"NAME": "OTHER", "PREDECESSORS": "ROOT.A[2]"},
        ])

        children = task_graph._child_tasks_for_root(df_tasks, "ROOT.A[1]")
        self.assertEqual(set(children["NAME"]), {"LITERAL_CHILD"})

    def test_task_fqn_and_cancel_sql_use_safe_quoting(self):
        self.assertEqual(
            task_graph._task_fqn({"DATABASE_NAME": "DB", "SCHEMA_NAME": "PUBLIC", "NAME": 'TASK"A'}),
            '"DB"."PUBLIC"."TASK""A"',
        )
        self.assertEqual(
            task_graph._cancel_task_graph_sql("graph'1"),
            "SELECT SYSTEM$CANCEL_TASK_GRAPH('graph''1')",
        )
        self.assertEqual(
            task_graph._cancel_task_query_sql("query'1"),
            "SELECT SYSTEM$CANCEL_QUERY('query''1')",
        )

    def test_task_mutation_sql_builders(self):
        task_fqn = task_graph._task_fqn({"DATABASE_NAME": "DB", "SCHEMA_NAME": "PUBLIC", "NAME": 'TASK"A'})
        self.assertEqual(task_fqn, '"DB"."PUBLIC"."TASK""A"')
        self.assertEqual(
            task_graph._alter_task_suspend_sql(task_fqn),
            'ALTER TASK "DB"."PUBLIC"."TASK""A" SUSPEND',
        )
        self.assertEqual(
            task_graph._alter_task_resume_sql(task_fqn),
            'ALTER TASK "DB"."PUBLIC"."TASK""A" RESUME',
        )
        self.assertEqual(
            task_graph._execute_task_sql(task_fqn),
            'EXECUTE TASK "DB"."PUBLIC"."TASK""A"',
        )

    def test_resume_task_graph_sql_orders_children_before_root(self):
        self.assertEqual(
            task_graph._resume_task_graph_sql('"DB"."PUBLIC"."ROOT"', ['"DB"."PUBLIC"."CHILD_A"', '"DB"."PUBLIC"."CHILD_B"']),
            [
                'ALTER TASK "DB"."PUBLIC"."CHILD_A" RESUME',
                'ALTER TASK "DB"."PUBLIC"."CHILD_B" RESUME',
                'ALTER TASK "DB"."PUBLIC"."ROOT" RESUME',
            ],
        )

    def test_task_running_queries_sql_contract(self):
        with patch.object(task_graph, "get_wh_filter_clause", return_value="AND warehouse_name = 'COMPUTE_WH'"):
            with patch.object(task_graph, "get_user_company_filter_clause", return_value="AND user_name LIKE 'ALFA%'"):
                sql = task_graph._task_running_queries_sql(
                    "ALFA",
                    "warehouse_size AS warehouse_size",
                    "query_tag AS query_tag",
                    "query_tag IS NOT NULL",
                ).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", sql)
        self.assertIn("QUERY_CONTEXT", sql)
        self.assertIn("AND WAREHOUSE_NAME = 'COMPUTE_WH'", sql)
        self.assertIn("AND USER_NAME LIKE 'ALFA%'", sql)
        self.assertIn("QUERY_TAG IS NOT NULL", sql)
        self.assertIn("LIMIT 200", sql)

    def test_normalize_task_history_for_dag(self):
        df_hist = pd.DataFrame([
            {
                "TASK_NAME": "LOAD_ROOT",
                "STATE": "FAILED",
                "ERROR_MESSAGE": "old",
                "SCHEDULED_TIME": "2026-06-22 01:00:00",
                "DURATION_SEC": 10,
            },
            {
                "TASK_NAME": "LOAD_ROOT",
                "STATE": "SUCCEEDED",
                "ERROR_MESSAGE": "",
                "SCHEDULED_TIME": "2026-06-23 01:00:00",
                "DURATION_SEC": 5,
            },
            {
                "TASK_NAME": "OTHER_TASK",
                "STATE": "SUCCEEDED",
                "ERROR_MESSAGE": "",
                "SCHEDULED_TIME": "2026-06-23 01:00:00",
                "DURATION_SEC": 5,
            },
        ])

        normalized = task_graph._normalize_task_history_for_dag(df_hist, ["LOAD_ROOT"])
        self.assertEqual(len(normalized), 1)
        row = normalized.iloc[0]
        self.assertEqual(row["NAME"], "LOAD_ROOT")
        self.assertEqual(row["LAST_RUN_STATE"], "SUCCEEDED")
        self.assertIn("LAST_ERROR", normalized.columns)
        self.assertIn("LAST_RUN_TIME", normalized.columns)
        self.assertIn("LAST_DURATION_SEC", normalized.columns)

    def test_build_dag_view_frame_merges_latest_history(self):
        df_tasks = pd.DataFrame([
            {"NAME": "LOAD_ROOT", "DATABASE_NAME": "DB", "SCHEMA_NAME": "PUBLIC", "PREDECESSORS": ""},
            {"NAME": "LOAD_CHILD", "DATABASE_NAME": "DB", "SCHEMA_NAME": "PUBLIC", "PREDECESSORS": "LOAD_ROOT"},
        ])
        df_hist = pd.DataFrame([
            {"TASK_NAME": "LOAD_CHILD", "STATE": "FAILED", "SCHEDULED_TIME": "2026-06-23", "DURATION_SEC": 22},
        ])

        dag = task_graph._build_dag_view_frame(df_tasks, df_hist, "LOAD_ROOT")
        self.assertEqual(set(dag["NAME"]), {"LOAD_ROOT", "LOAD_CHILD"})
        child = dag[dag["NAME"] == "LOAD_CHILD"].iloc[0]
        self.assertEqual(child["LAST_RUN_STATE"], "FAILED")


if __name__ == "__main__":
    unittest.main()
