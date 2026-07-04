from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from runtime_state import clear_runtime_event_ledger, get_runtime_event_ledger  # noqa: E402
from utils import query as query_utils  # noqa: E402


class RuntimeSourceEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_state = dict(st.session_state)
        st.session_state.clear()
        clear_runtime_event_ledger()

    def tearDown(self) -> None:
        st.session_state.clear()
        st.session_state.update(self.previous_state)

    def test_run_query_records_source_boundary_without_sql(self) -> None:
        with (
            patch(
                "utils.query._run_query_base",
                return_value=(
                    pd.DataFrame({"VALUE": [1]}),
                    {
                        "actual_query_executed": False,
                        "cache_layer": "test",
                        "query_boundary": "cost_evidence",
                        "query_contract_id": "contract",
                        "first_paint_sensitive": False,
                    },
                ),
            ),
            patch("utils.query._record_query_telemetry"),
            patch("utils.query.record_ui_query_event"),
        ):
            result = query_utils.run_query(
                "select 1",
                section="Cost & Contract",
                ttl_key="cost_evidence",
                query_boundary="cost_evidence",
                use_cache=False,
            )

        self.assertEqual(len(result), 1)
        rows = get_runtime_event_ledger()
        source_rows = [row for row in rows if row["event_type"] == "run_query_source"]
        self.assertEqual(len(source_rows), 1)
        self.assertEqual(source_rows[0]["execution_boundary"], "cost_evidence")
        self.assertEqual(source_rows[0]["source_module"], "utils.query")
        self.assertTrue(source_rows[0]["cost_evidence_marker_present"])
        self.assertFalse(source_rows[0]["raw_sql_included"])
        self.assertNotIn("select 1", str(source_rows[0]))


if __name__ == "__main__":
    unittest.main()
