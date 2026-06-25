from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class MissionControlQueueTests(unittest.TestCase):
    def test_triage_queue_module_is_query_free(self):
        source = (APP_ROOT / "sections" / "triage_queue.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\brun_query(?:_or_raise)?\b")
        self.assertNotRegex(source, r"\bget_session(?:_for_action)?\b")
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", source)

    def test_builds_cross_section_items_from_session_only(self):
        from sections.triage_queue import build_mission_control_items

        state = {
            "alert_center_data": {
                "alerts": pd.DataFrame([
                    {"SEVERITY": "Critical", "STATUS": "New", "SLA_STATE": "Overdue"},
                    {"SEVERITY": "Low", "STATUS": "Closed", "SLA_STATE": "Ready"},
                ]),
                "action_queue": pd.DataFrame([{"STATUS": "New"}]),
                "_freshness_meta": {"loaded_at": "2026-06-24T12:00:00"},
            },
            "cost_contract_cockpit": pd.DataFrame([{
                "CURRENT_CREDITS": 150.0,
                "PRIOR_CREDITS": 100.0,
                "TOP_INCREASE_WAREHOUSE": "COMPUTE_WH",
            }]),
            "cost_contract_cockpit_meta": {"loaded_at": "2026-06-24T12:05:00"},
            "security_posture_summary": pd.DataFrame([{
                "FAILED_LOGINS": 10,
                "USERS_WITHOUT_MFA": 2,
                "RECENT_GRANTS": 1,
            }]),
            "security_posture_meta": {"loaded_at": "2026-06-24T12:10:00"},
        }

        items = build_mission_control_items(state, company="ALFA", environment="PROD")
        sections = [item["section"] for item in items]

        self.assertIn("Alert Center", sections)
        self.assertIn("Cost & Contract", sections)
        self.assertIn("Security Monitoring", sections)
        self.assertEqual(items[0]["section"], "Alert Center")
        self.assertIn("critical/high", items[0]["signal"].lower())

    def test_empty_queue_prompts_explicit_loads(self):
        from sections.triage_queue import build_mission_control_items

        items = build_mission_control_items({}, company="ALFA", environment="PROD")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["section"], "Mission Control")
        self.assertIn("Load Active Alerts", items[0]["next_action"])

    def test_render_queue_escapes_html(self):
        from sections import triage_queue

        with patch.object(triage_queue.st, "html") as html:
            triage_queue.render_mission_control_queue(
                {},
                company="<script>alert(1)</script>",
                environment="PROD",
            )

        markup = html.call_args.args[0]
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", markup)
        self.assertNotIn("<script>", markup)


if __name__ == "__main__":
    unittest.main()
