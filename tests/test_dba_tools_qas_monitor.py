from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import dba_tools  # noqa: E402
from sections import dba_tools_qas_monitor_view as qas_monitor  # noqa: E402


class DbaToolsQasMonitorTests(unittest.TestCase):
    def test_query_history_warehouse_size_expr_uses_column_when_available(self):
        with patch.object(qas_monitor, "filter_existing_columns", return_value=["WAREHOUSE_SIZE"]):
            self.assertEqual(qas_monitor._query_history_warehouse_size_expr(object()), "warehouse_size")

    def test_query_history_warehouse_size_expr_falls_back_when_missing(self):
        with patch.object(qas_monitor, "filter_existing_columns", return_value=[]):
            self.assertEqual(
                qas_monitor._query_history_warehouse_size_expr(object()),
                "NULL::VARCHAR AS warehouse_size",
            )

    def test_qas_monitor_dispatch_contract_and_render_keys(self):
        self.assertIs(dba_tools.DBA_TOOL_RENDERERS["QAS Monitor"], qas_monitor.render_qas_monitor_tool)
        self.assertNotIn("QAS Monitor", dba_tools.INLINE_DBA_TOOL_HANDLERS)

        previous = dict(st.session_state)
        qas_df = pd.DataFrame([{
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "WAREHOUSE_SIZE": "SMALL",
            "DAY": "2026-06-23",
            "DAILY_CREDITS": 1.25,
            "QUERY_COUNT": 4,
        }])
        try:
            st.session_state.clear()
            with patch.object(qas_monitor, "_load_button", return_value=True) as load_button:
                with patch.object(qas_monitor, "day_window_selectbox", return_value=7):
                    with patch.object(qas_monitor, "_query_history_warehouse_size_expr", return_value="warehouse_size"):
                        with patch.object(qas_monitor, "run_query", return_value=qas_df):
                            with patch.object(qas_monitor, "render_priority_dataframe") as render_df:
                                qas_monitor.render_qas_monitor_tool(object(), "ALL")

            load_button.assert_called_once_with("Load QAS Data", "qas_load")
            self.assertIs(st.session_state["dba_df_qas"], qas_df)
            self.assertEqual(
                render_df.call_args.kwargs["priority_columns"],
                ["WAREHOUSE_NAME", "WAREHOUSE_SIZE", "DAY", "DAILY_CREDITS", "QUERY_COUNT"],
            )
        finally:
            st.session_state.clear()
            st.session_state.update(previous)


if __name__ == "__main__":
    unittest.main()
