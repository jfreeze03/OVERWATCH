from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import dba_tools  # noqa: E402
from sections import dba_tools_query_kill_view as query_kill  # noqa: E402


class DbaToolsQueryKillTests(unittest.TestCase):
    def test_query_kill_renderer_is_registered(self):
        self.assertIs(dba_tools.DBA_TOOL_RENDERERS["Query Kill List"], query_kill.render_query_kill_list_tool)
        self.assertNotIn("Query Kill List", dba_tools.INLINE_DBA_TOOL_HANDLERS)

    def test_query_history_warehouse_size_expr(self):
        with patch.object(query_kill, "filter_existing_columns", return_value=["WAREHOUSE_SIZE"]):
            self.assertEqual(
                query_kill._query_history_warehouse_size_expr(object()),
                "warehouse_size AS warehouse_size",
            )
        with patch.object(query_kill, "filter_existing_columns", return_value=[]):
            self.assertEqual(
                query_kill._query_history_warehouse_size_expr(object()),
                "NULL::VARCHAR AS warehouse_size",
            )

    def test_query_kill_list_sql_contract(self):
        with patch.object(query_kill, "get_wh_filter_clause", return_value="AND warehouse_name = 'COMPUTE_WH'"):
            sql = query_kill._query_kill_list_sql(300, "warehouse_size AS warehouse_size").upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", sql)
        self.assertIn("'RUNNING','QUEUED','BLOCKED'", sql)
        self.assertIn("> 300", sql)
        self.assertIn("AND WAREHOUSE_NAME = 'COMPUTE_WH'", sql)
        self.assertIn("LIMIT 500", sql)

    def test_cancel_query_sql_uses_safe_literal(self):
        sql = query_kill._cancel_query_sql("abc'123")
        self.assertEqual(sql, "SELECT SYSTEM$CANCEL_QUERY('abc''123')")


if __name__ == "__main__":
    unittest.main()
