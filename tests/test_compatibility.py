from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class _FakeQuery:
    def __init__(self, session, sql: str):
        self._session = session
        self._sql = sql

    def to_pandas(self):
        self._session.executed.append(self._sql)
        return pd.DataFrame(columns=["A", "B", "C", "D", "E", "F", "G"])

    def collect(self):
        self._session.executed.append(self._sql)
        return []


class _FakeSession:
    def __init__(self):
        self.executed = []

    def sql(self, sql: str):
        return _FakeQuery(self, sql)


class CompatibilityMetadataProbeTests(unittest.TestCase):
    def setUp(self):
        import streamlit as st
        from utils.compatibility import clear_compatibility_process_cache

        self._previous_state = dict(st.session_state)
        st.session_state.clear()
        clear_compatibility_process_cache()

    def tearDown(self):
        import streamlit as st
        from utils.compatibility import clear_compatibility_process_cache

        clear_compatibility_process_cache()
        st.session_state.clear()
        st.session_state.update(self._previous_state)

    def test_filter_existing_columns_uses_one_object_probe_and_warm_cache(self):
        from utils.compatibility import filter_existing_columns

        session = _FakeSession()
        columns = filter_existing_columns(session, "DB.SCHEMA.OBJECT_NAME", ["A", "B", "C", "D", "E", "F", "G"])
        warm_columns = filter_existing_columns(session, "DB.SCHEMA.OBJECT_NAME", ["A", "G"])

        self.assertEqual(columns, ["A", "B", "C", "D", "E", "F", "G"])
        self.assertEqual(warm_columns, ["A", "G"])
        self.assertEqual(len(session.executed), 1)
        self.assertIn("LIMIT 0", session.executed[0])


if __name__ == "__main__":
    unittest.main()
