from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from sections import leadership_watchlist_panels as panels  # noqa: E402


class LeadershipWatchlistPanelTests(unittest.TestCase):
    def _patch_streamlit(self):
        return (
            patch.object(panels.st, "html"),
            patch.object(panels.st, "dataframe"),
            patch.object(panels.st, "markdown"),
        )

    def test_credit_storage_and_cortex_panels_render_chart_and_table(self) -> None:
        credit = pd.DataFrame(
            [
                {
                    "USAGE_DATE": "2026-07-05",
                    "SERVICE_TYPE": "WAREHOUSE",
                    "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
                    "CREDITS_USED": 12.0,
                    "ESTIMATED_COST_USD": 26.4,
                    "UPDATED_AT": "2026-07-05 12:00:00",
                }
            ]
        )
        comparison = pd.DataFrame(
            [
                {
                    "CONTRIBUTOR_TYPE": "WAREHOUSE",
                    "CONTRIBUTOR_NAME": "WH_ALFA_OVERWATCH",
                    "CURRENT_24H_CREDITS": 12,
                    "PRIOR_24H_CREDITS": 8,
                    "CREDIT_DELTA": 4,
                    "PCT_DELTA": 0.5,
                    "UPDATED_AT": "2026-07-05 12:00:00",
                }
            ]
        )
        storage = pd.DataFrame(
            [
                {
                    "USAGE_DATE": "2026-07-05",
                    "DATABASE_NAME": "ALFA_EDW_SAN",
                    "DATABASE_TB": 1.2,
                    "FAILSAFE_TB": 0.2,
                    "TOTAL_TB": 1.4,
                    "DAILY_GROWTH_BYTES": 1024 ** 4,
                    "UPDATED_AT": "2026-07-05 12:00:00",
                }
            ]
        )
        cortex = pd.DataFrame(
            [
                {
                    "USAGE_DATE": "2026-07-05",
                    "USER_CHART_LABEL": "Jane Doe",
                    "CLIENT_SOURCE": "Snowsight",
                    "TOKEN_COUNT": 9000,
                    "CREDITS_USED": 4,
                    "ESTIMATED_COST_USD": 8.8,
                    "UPDATED_AT": "2026-07-05 12:00:00",
                }
            ]
        )
        html_patch, table_patch, markdown_patch = self._patch_streamlit()
        with (
            html_patch as html,
            table_patch as dataframe,
            markdown_patch,
            patch.object(panels.leadership_queries, "get_credit_daily", side_effect=[credit, credit]),
            patch.object(panels.leadership_queries, "get_credit_comparison_24h", return_value=comparison),
            patch.object(panels.leadership_queries, "get_storage_daily", return_value=storage),
            patch.object(panels.leadership_queries, "get_cortex_code_usage", return_value=cortex),
        ):
            panels.render_cost_leadership_panels(
                "ALFA",
                "ALL",
                start_date="2026-06-28",
                end_date="2026-07-05",
            )

        self.assertGreaterEqual(html.call_count, 5)
        self.assertGreaterEqual(dataframe.call_count, 5)
        rendered = "\n".join(str(call.args[0]) for call in html.call_args_list)
        self.assertIn("Credit Burn Rate", rendered)
        self.assertIn("YTD Credit Trend", rendered)
        self.assertIn("24h Credit Comparison", rendered)
        self.assertIn("Storage Growth", rendered)
        self.assertIn("Cortex Code Usage", rendered)

    def test_security_panels_handle_empty_and_populated_data(self) -> None:
        failed = pd.DataFrame(
            [{"USER_NAME": "JANE", "CLIENT_IP": "10.0.0.1", "FAILED_COUNT": 11, "RISK_SCORE": 90}]
        )
        login = pd.DataFrame([{"EVENT_DATE": "2026-07-05", "FAILED_COUNT": 11, "LOGIN_COUNT": 20}])
        grants = pd.DataFrame([{"ROLE_NAME": "APP_PRIVILEGED_ROLE", "GRANTEE_NAME": "ANALYST", "CREATED_ON": "2026-07-05"}])
        html_patch, table_patch, markdown_patch = self._patch_streamlit()
        with (
            html_patch as html,
            table_patch as dataframe,
            markdown_patch,
            patch.object(panels.leadership_queries, "get_failed_logins_last_hour", return_value=failed),
            patch.object(panels.leadership_queries, "get_login_security", return_value=login),
            patch.object(panels.leadership_queries, "get_suspicious_logins", return_value=pd.DataFrame()),
            patch.object(panels.leadership_queries, "get_role_grant_audit", return_value=grants),
        ):
            panels.render_security_leadership_panels("ALFA", "ALL")

        self.assertGreaterEqual(dataframe.call_count, 4)
        rendered = "\n".join(str(call.args[0]) for call in html.call_args_list)
        self.assertIn("Failed Logins - Last Hour", rendered)
        self.assertIn("Suspicious Login Attempts", rendered)
        self.assertIn("Role / Grant Audit", rendered)

    def test_workload_query_error_panels_render_frequency_and_trend(self) -> None:
        errors = pd.DataFrame(
            [
                {
                    "EVENT_HOUR": "2026-07-05 11:00:00",
                    "ERROR_CODE": "100072",
                    "ERROR_MESSAGE": "Object not found",
                    "FAILED_QUERY_COUNT": 6,
                    "TOTAL_QUERY_COUNT": 100,
                    "FAILURE_RATE": 0.06,
                    "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
                }
            ]
        )
        html_patch, table_patch, markdown_patch = self._patch_streamlit()
        with (
            html_patch as html,
            table_patch as dataframe,
            markdown_patch,
            patch.object(panels.leadership_queries, "get_query_errors", return_value=errors),
        ):
            panels.render_workload_query_error_panels("ALFA", "ALL")

        self.assertEqual(dataframe.call_count, 2)
        rendered = "\n".join(str(call.args[0]) for call in html.call_args_list)
        self.assertIn("Query Error Frequency - Last 24h", rendered)
        self.assertIn("Failed Query Trend", rendered)

    def test_alert_candidates_cover_all_manual_monitoring_categories(self) -> None:
        candidates = panels.leadership_alert_candidates()
        categories = {candidate.category for candidate in candidates}
        self.assertEqual(
            categories,
            {
                "Credit Burn Spike",
                "Failed Login Spike",
                "Suspicious Login Activity",
                "Query Error Spike",
                "Storage Growth Spike",
                "Cortex Code Spend Spike",
                "High-Risk Role Grant Change",
            },
        )

    def test_watchlist_strip_renders_six_cards(self) -> None:
        with patch.object(panels.st, "html") as html:
            panels.render_leadership_watchlist_strip()
        rendered = str(html.call_args.args[0])
        self.assertIn("Operations Watchlist", rendered)
        self.assertNotIn("TF_O_DEV", rendered)
        self.assertEqual(rendered.count("ow-lw-watch-card"), 6)


if __name__ == "__main__":
    unittest.main()
