from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from runtime_state import SF_SESSION  # noqa: E402
from utils import alert_delivery  # noqa: E402
from utils import settings_provider  # noqa: E402


class _FakeSqlResult:
    def __init__(self, rows):
        self._rows = rows

    def collect(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.sql_texts: list[str] = []

    def sql(self, sql_text: str):
        self.sql_texts.append(sql_text)
        return _FakeSqlResult(self.rows)


class SettingsProviderTests(unittest.TestCase):
    def test_missing_session_returns_fallback_without_query(self):
        cache: dict[str, object] = {}
        with (
            patch("utils.settings_provider._cache", return_value=cache),
            patch("utils.settings_provider.is_first_paint_active", return_value=False),
            patch("utils.settings_provider.get_state", return_value=None),
        ):
            self.assertEqual(
                settings_provider.get_default_alert_recipient("fallback@example.com"),
                "fallback@example.com",
            )

    def test_existing_session_reads_default_alert_recipients_from_settings(self):
        cache: dict[str, object] = {}
        session = _FakeSession(
            [
                {
                    "SETTING_VALUE": '["ops@example.com", "dba@example.com"]',
                    "VALUE_TYPE": "JSON",
                }
            ]
        )

        def fake_get_state(key, default=None):
            return session if key == SF_SESSION else default

        with (
            patch("utils.settings_provider._cache", return_value=cache),
            patch("utils.settings_provider.is_first_paint_active", return_value=False),
            patch("utils.settings_provider.get_state", side_effect=fake_get_state),
        ):
            recipient = settings_provider.get_default_alert_recipient("fallback@example.com")

        self.assertEqual(recipient, "ops@example.com,dba@example.com")
        self.assertEqual(len(session.sql_texts), 1)
        sql_text = session.sql_texts[0].upper()
        self.assertIn("FROM OVERWATCH_SETTINGS", sql_text)
        self.assertIn("WHERE UPPER(SETTING_NAME)", sql_text)
        self.assertNotIn("SELECT *", sql_text)

    def test_first_paint_returns_fallback_without_settings_query(self):
        cache: dict[str, object] = {}
        session = _FakeSession([{"SETTING_VALUE": '["ops@example.com"]', "VALUE_TYPE": "JSON"}])

        def fake_get_state(key, default=None):
            return session if key == SF_SESSION else default

        with (
            patch("utils.settings_provider._cache", return_value=cache),
            patch("utils.settings_provider.is_first_paint_active", return_value=True),
            patch("utils.settings_provider.get_state", side_effect=fake_get_state),
        ):
            recipient = settings_provider.get_default_alert_recipient("fallback@example.com")

        self.assertEqual(recipient, "fallback@example.com")
        self.assertEqual(session.sql_texts, [])

    def test_alert_delivery_uses_settings_provider_when_state_value_absent(self):
        with (
            patch("utils.alert_delivery.get_state", return_value=""),
            patch("utils.alert_delivery.get_default_alert_recipient", return_value="settings@example.com") as provider,
        ):
            self.assertEqual(alert_delivery.current_alert_recipient("fallback@example.com"), "settings@example.com")
        provider.assert_called_once_with("fallback@example.com")


if __name__ == "__main__":
    unittest.main()
