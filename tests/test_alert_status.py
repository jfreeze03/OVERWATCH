from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils.alert_status import (  # noqa: E402
    ALERT_CLOSED_STATUSES,
    ALERT_OPEN_STATUSES,
    ALERT_SEVERITY_RANKS,
    ALERT_SLA_HOURS,
    ALERT_STATUS_CHOICES,
    alert_severity_rank,
    normalize_alert_severity,
    normalize_alert_status,
    normalize_command_center_alert_status,
)


class AlertStatusTests(unittest.TestCase):
    def test_triage_status_normalizer_preserves_operational_labels(self):
        cases = {
            None: "New",
            "": "New",
            "new": "New",
            "open": "Open",
            "active": "Active",
            "acknowledged": "Acknowledged",
            "in_progress": "In Progress",
            "email_ready": "Email Ready",
            "email queued": "Email Queued",
            "config_required": "Config Required",
            "fixed": "Fixed",
            "resolved": "Fixed",
            "ignored": "Ignored",
            "suppressed": "Suppressed",
            "custom operator hold": "Custom Operator Hold",
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_alert_status(raw), expected)

    def test_command_center_status_normalizer_collapses_unknown_values_to_new(self):
        cases = {
            None: "New",
            "": "New",
            "in_progress": "In Progress",
            "in-progress": "In Progress",
            "email_ready": "Email Ready",
            "email queued": "Email Queued",
            "acknowledged": "Acknowledged",
            "fixed": "Fixed",
            "resolved": "Fixed",
            "ignored": "Ignored",
            "suppressed": "Ignored",
            "config_required": "New",
            "custom operator hold": "New",
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_command_center_alert_status(raw), expected)

    def test_severity_normalization_and_ranking_remain_stable(self):
        self.assertEqual(normalize_alert_severity("critical"), "Critical")
        self.assertEqual(normalize_alert_severity("HIGH"), "High")
        self.assertEqual(normalize_alert_severity("medium"), "Medium")
        self.assertEqual(normalize_alert_severity("low"), "Low")
        self.assertEqual(normalize_alert_severity("unknown"), "Medium")
        self.assertEqual(normalize_alert_severity(None), "Medium")

        self.assertEqual(alert_severity_rank("critical"), 0)
        self.assertEqual(alert_severity_rank("high"), 1)
        self.assertEqual(alert_severity_rank("medium"), 2)
        self.assertEqual(alert_severity_rank("low"), 3)
        self.assertEqual(alert_severity_rank("unknown"), 2)

        self.assertEqual(ALERT_STATUS_CHOICES, ("Acknowledged", "In Progress", "Fixed", "Ignored"))
        self.assertIn("EMAIL_READY", ALERT_OPEN_STATUSES)
        self.assertEqual(ALERT_CLOSED_STATUSES, {"FIXED", "IGNORED", "RESOLVED"})
        self.assertEqual(ALERT_SLA_HOURS, {"Critical": 4, "High": 8, "Medium": 24, "Low": 72})
        self.assertEqual(ALERT_SEVERITY_RANKS, {"Critical": 0, "High": 1, "Medium": 2, "Low": 3})


if __name__ == "__main__":
    unittest.main()
