from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.alert_center_contracts import ALERT_CENTER_DEFAULT_VIEW  # noqa: E402


class AlertCenterDefaultTests(unittest.TestCase):
    def test_default_alert_center_route_is_active_inbox(self) -> None:
        contracts = (APP_ROOT / "sections" / "alert_center_contracts.py").read_text(encoding="utf-8")
        alert_source = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")

        self.assertEqual(ALERT_CENTER_DEFAULT_VIEW, "Active Alerts")
        self.assertIn('ALERT_CENTER_DEFAULT_VIEW = "Active Alerts"', contracts)
        self.assertIn('st.session_state.get("alert_center_active_view", ALERT_CENTER_DEFAULT_VIEW)', alert_source)

    def test_default_first_paint_renders_inbox_and_intelligence_not_lanes(self) -> None:
        inbox_source = (APP_ROOT / "sections" / "alert_center_inbox_shell.py").read_text(encoding="utf-8")
        alert_source = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        default_surface = alert_source + "\n" + inbox_source

        self.assertIn("Alert Inbox", inbox_source)
        self.assertIn("Alert Intelligence", inbox_source)
        self.assertIn("ow-coco-filter-chip", inbox_source)
        self.assertIn("render_alert_inbox_shell", alert_source)
        self.assertNotIn("lane-column", default_surface)
        self.assertNotIn("alert-lane", default_surface)
        self.assertNotIn("Kanban", default_surface)
        self.assertNotIn("Boards", default_surface)
        self.assertNotIn(">Owner<", inbox_source)


if __name__ == "__main__":
    unittest.main()
