from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.explicit_load import explicit_load_dataframe, render_export_controls  # noqa: E402


class ExplicitLoadTests(unittest.TestCase):
    def setUp(self):
        self._previous_state = dict(st.session_state)
        st.session_state.clear()

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self._previous_state)

    def test_loader_runs_only_after_button_click(self):
        calls = []

        def loader():
            calls.append("loaded")
            return pd.DataFrame({"VALUE": [1]})

        with patch("utils.explicit_load.st.button", return_value=False):
            result = explicit_load_dataframe(
                button_label="Load rows",
                button_key="load_rows",
                state_key="rows",
                loader=loader,
            )

        self.assertIsNone(result)
        self.assertEqual(calls, [])
        self.assertNotIn("rows", st.session_state)

        with patch("utils.explicit_load.st.button", return_value=True):
            result = explicit_load_dataframe(
                button_label="Load rows",
                button_key="load_rows",
                state_key="rows",
                loader=loader,
            )

        self.assertEqual(calls, ["loaded"])
        self.assertIsInstance(result, pd.DataFrame)
        self.assertIs(st.session_state["rows"], result)

    def test_force_runs_loader_without_button_click(self):
        calls = []

        def loader():
            calls.append("loaded")
            return pd.DataFrame({"VALUE": [2]})

        with patch("utils.explicit_load.st.button", return_value=False) as button:
            result = explicit_load_dataframe(
                button_label="Load rows",
                button_key="load_rows",
                state_key="rows",
                loader=loader,
                force=True,
            )

        button.assert_not_called()
        self.assertEqual(calls, ["loaded"])
        self.assertEqual(int(result["VALUE"].iloc[0]), 2)

    def test_cached_frame_returns_without_rerunning_loader(self):
        cached = pd.DataFrame({"VALUE": [3]})
        st.session_state["rows"] = cached

        def loader():
            raise AssertionError("loader should not run")

        with patch("utils.explicit_load.st.button", return_value=False):
            result = explicit_load_dataframe(
                button_label="Load rows",
                button_key="load_rows",
                state_key="rows",
                loader=loader,
            )

        self.assertIs(result, cached)

    def test_errors_store_empty_frame_and_call_on_error(self):
        errors = []

        def loader():
            raise ValueError("broken")

        with patch("utils.explicit_load.st.button", return_value=True):
            result = explicit_load_dataframe(
                button_label="Load rows",
                button_key="load_rows",
                state_key="rows",
                loader=loader,
                empty_factory=lambda: pd.DataFrame({"VALUE": []}),
                on_error=errors.append,
            )

        self.assertTrue(result.empty)
        self.assertIs(st.session_state["rows"], result)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)

    def test_export_controls_propagate_filename_and_skip_empty_frames(self):
        frame = pd.DataFrame({"VALUE": [1]})
        with patch("utils.downloads.download_csv") as download_csv:
            self.assertTrue(render_export_controls(frame, "rows.csv", label="Download Rows"))

        download_csv.assert_called_once()
        self.assertIs(download_csv.call_args.args[0], frame)
        self.assertEqual(download_csv.call_args.args[1], "rows.csv")
        self.assertEqual(download_csv.call_args.kwargs["label"], "Download Rows")

        with patch("utils.downloads.download_csv") as download_csv:
            self.assertFalse(render_export_controls(pd.DataFrame(), "empty.csv"))

        download_csv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
