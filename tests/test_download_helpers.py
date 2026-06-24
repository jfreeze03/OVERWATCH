from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import downloads  # noqa: E402


class DownloadHelperTests(unittest.TestCase):
    def setUp(self):
        self._previous_state = dict(st.session_state)
        st.session_state.clear()

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self._previous_state)

    def test_download_keys_are_stable_and_do_not_use_object_identity(self):
        key_a = downloads._download_key("rows.csv", "Export CSV")
        key_b = downloads._download_key("rows.csv", "Export CSV")

        self.assertEqual(key_a, key_b)
        self.assertTrue(key_a.startswith("dl_"))
        self.assertNotIn("0x", key_a)

    def test_download_csv_is_gated_until_operator_opens_export(self):
        frame = pd.DataFrame([{"A": 1}])
        with patch("utils.downloads.st.button", return_value=False) as button:
            with patch("utils.downloads.st.download_button") as download_button:
                rendered = downloads.download_csv(frame, "rows.csv")

        self.assertTrue(rendered)
        button.assert_called_once()
        download_button.assert_not_called()

    def test_download_csv_renders_stable_button_after_gate(self):
        frame = pd.DataFrame([{"A": 1}])
        with patch("utils.downloads.st.button", return_value=True):
            with patch("utils.downloads.st.download_button") as download_button:
                rendered = downloads.download_csv(frame, "rows.csv")

        self.assertTrue(rendered)
        download_button.assert_called_once()
        kwargs = download_button.call_args.kwargs
        self.assertEqual(kwargs["file_name"], "rows.csv")
        self.assertEqual(kwargs["mime"], "text/csv")
        self.assertEqual(kwargs["key"], downloads._download_key("rows.csv", "Export CSV"))


if __name__ == "__main__":
    unittest.main()
