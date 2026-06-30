import unittest

from tools.contracts.packet_availability_live_validation import (
    completed_window_days_from_range,
    evaluate_packet_availability,
    normalize_packet_window_days,
)


class PacketAvailabilityLiveValidationTests(unittest.TestCase):
    def test_inclusive_eight_date_range_maps_to_seven_completed_days(self):
        self.assertEqual(completed_window_days_from_range("2026-06-21", "2026-06-28"), 7)
        self.assertEqual(normalize_packet_window_days(8), 7)

    def test_selected_eight_day_scope_finds_seven_day_packet(self):
        result = evaluate_packet_availability(
            [
                {
                    "section_name": "Executive Landing",
                    "company": "ALFA",
                    "environment": "ALL",
                    "window_days": 7,
                    "active_current_count": 1,
                    "flat_current_count": 1,
                    "last_good_count": 0,
                    "latest_snapshot_ts": "2026-06-28T17:43:00Z",
                }
            ],
            selected_company="ALFA",
            selected_environment="ALL",
            selected_window_days=8,
            sections=("Executive Landing",),
        )

        self.assertTrue(result["passed"], result)
        row = result["rows"][0]
        self.assertTrue(row["exact_packet_exists"])
        self.assertEqual(row["normalized_window_days"], 7)
        self.assertIn("normalized", row["missing_reason"])

    def test_missing_exact_scope_reports_all_company_fallback(self):
        result = evaluate_packet_availability(
            [
                {
                    "section_name": "Cost & Contract",
                    "company": "ALL",
                    "environment": "ALL",
                    "window_days": 7,
                    "active_current_count": 1,
                    "flat_current_count": 1,
                    "last_good_count": 0,
                }
            ],
            selected_company="ALFA",
            selected_environment="ALL",
            selected_window_days=7,
            sections=("Cost & Contract",),
        )

        self.assertFalse(result["passed"], result)
        row = result["rows"][0]
        self.assertFalse(row["exact_packet_exists"])
        self.assertTrue(row["all_company_packet_exists"])
        self.assertIn("ALL-company", row["missing_reason"])

    def test_current_packet_without_flat_packet_fails(self):
        result = evaluate_packet_availability(
            [
                {
                    "section_name": "Alert Center",
                    "company": "ALFA",
                    "environment": "ALL",
                    "window_days": 7,
                    "active_current_count": 1,
                    "flat_current_count": 0,
                    "last_good_count": 0,
                }
            ],
            selected_company="ALFA",
            selected_environment="ALL",
            selected_window_days=7,
            sections=("Alert Center",),
        )

        self.assertFalse(result["passed"], result)
        self.assertIn("flat packet", result["rows"][0]["missing_reason"])


if __name__ == "__main__":
    unittest.main()
