from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class QueryDrilldownSafetyTests(unittest.TestCase):
    def test_query_drilldown_hides_raw_statement_text(self):
        from utils import display

        captions: list[str] = []
        frame = pd.DataFrame([
            {
                "QUERY_ID": "01a1234567890123456",
                "QUERY_TEXT": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                "USER_NAME": "ANALYST",
                "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
                "ELAPSED_SEC": 1.2,
            }
        ])
        selection = SimpleNamespace(selection=SimpleNamespace(rows=[0]))

        with patch.object(display.st, "subheader"), patch.object(
            display.st,
            "dataframe",
            return_value=selection,
        ), patch.object(display.st, "expander", return_value=_Context()), patch.object(
            display,
            "render_shell_snapshot",
        ), patch.object(display.st, "markdown"), patch.object(
            display.st,
            "caption",
            side_effect=lambda text, *args, **kwargs: captions.append(str(text)),
        ), patch.object(display.st, "code") as code, patch.object(
            display.st,
            "button",
            return_value=False,
        ):
            display.render_query_drilldown(frame, key="safe_query")

        code.assert_not_called()
        rendered = "\n".join(captions)
        self.assertIn("Statement fingerprint", rendered)
        self.assertIn("Full SQL text is hidden", rendered)
        self.assertNotIn("SELECT *", rendered)
        self.assertNotIn("ACCOUNT_USAGE", rendered)

    def test_operator_stats_error_is_sanitized(self):
        import performance
        from utils import display

        state: dict[str, object] = {}
        messages: list[str] = []
        frame = pd.DataFrame([
            {
                "QUERY_ID": "01a1234567890123456",
                "QUERY_TEXT": "SELECT * FROM SECRET_TABLE WHERE PASSWORD='hidden'",
                "USER_NAME": "ANALYST",
                "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
                "ELAPSED_SEC": 1.2,
            }
        ])
        selection = SimpleNamespace(selection=SimpleNamespace(rows=[0]))
        raw_error = (
            "001040 (22023): SQL compilation error: Invalid value [profile expired] "
            "for function 'get_query_operator_stats' at position 1 SELECT * FROM SECRET_TABLE"
        )

        with patch.object(display.st, "session_state", state), patch.object(
            performance.st,
            "session_state",
            state,
        ), patch.object(display.st, "subheader"), patch.object(
            display.st,
            "dataframe",
            return_value=selection,
        ), patch.object(display.st, "expander", return_value=_Context()), patch.object(
            display,
            "render_shell_snapshot",
        ), patch.object(display.st, "markdown"), patch.object(display.st, "caption"), patch.object(
            display.st,
            "button",
            return_value=True,
        ), patch.object(
            display,
            "run_query_or_raise",
            side_effect=RuntimeError(raw_error),
        ), patch.object(
            display.st,
            "info",
            side_effect=lambda text, *args, **kwargs: messages.append(str(text)),
        ):
            display.render_query_drilldown(frame, key="safe_query")

        rendered = "\n".join(messages)
        self.assertIn("Operator stats unavailable.", rendered)
        self.assertIn("Operator profile details are not available", rendered)
        self.assertNotIn("SELECT", rendered)
        self.assertNotIn("SECRET_TABLE", rendered)
        self.assertNotIn("SQL compilation error", rendered)


if __name__ == "__main__":
    unittest.main()
