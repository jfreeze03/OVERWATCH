from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.command_center_models import build_executive_command_center_model  # noqa: E402
from sections.section_command_brief import (  # noqa: E402
    SectionCommandAction,
    SectionCommandBrief,
    SectionCommandMetric,
    SectionCommandSignal,
)


def _brief(**overrides) -> SectionCommandBrief:
    values = {
        "section": "Executive Landing",
        "company": "ALFA",
        "environment": "ALL",
        "window_label": "7 days",
        "state": "Ready",
        "headline": "Account health is steady",
        "summary": "Packet-backed leadership summary.",
        "source": "Packet",
        "freshness_label": "Current",
        "loaded_at": "2026-07-05T11:19:00",
        "metrics": (
            SectionCommandMetric(
                key="account_health",
                label="Account Health",
                value="98",
                detail="Excellent",
                tone="healthy",
                trend_points=({"value": 92}, {"value": 96}, {"value": 98}),
            ),
            SectionCommandMetric(
                key="warehouse_credits",
                label="Credits Used",
                value="12,842",
                trend_points=({"value": 10000}, {"value": 11500}, {"value": 12842}),
            ),
        ),
        "exceptions": (
            SectionCommandSignal(
                severity="High",
                signal="Warehouse suspended unexpectedly",
                detail="Investigate resume policy.",
                owner_name="DBA On-Call",
                sla_state="Due today",
                age_minutes=2,
            ),
        ),
        "next_actions": (
            SectionCommandAction(
                label="Review open actions",
                detail="Open the action queue.",
                action_key="review_open_actions",
            ),
        ),
        "data_availability_state": "Ready",
    }
    values.update(overrides)
    return SectionCommandBrief(**values)


class ExecutiveCommandCenterTests(unittest.TestCase):
    def test_model_builds_six_packet_backed_kpis(self):
        model = build_executive_command_center_model(_brief(), company="ALFA", environment="ALL", days=7)
        self.assertEqual([card.label for card in model.kpis], [
            "Summary Status",
            "Source Status",
            "Evidence Status",
            "Account Health",
            "Open Actions",
            "Freshness / SLA",
        ])
        self.assertEqual(model.health_value, "98/100")
        self.assertEqual(model.summary_headline, "Account health is steady")
        self.assertEqual(model.evidence_status, "On request")
        self.assertEqual(model.total_credits_text, "12,842")
        self.assertLessEqual(max(len(card.value) for card in model.kpis), 28)

    def test_warehouse_split_is_not_synthesized_when_absent(self):
        model = build_executive_command_center_model(_brief(), company="ALFA", environment="ALL", days=7)
        self.assertEqual(model.warehouse_slices, ())

    def test_warehouse_split_uses_packet_payload_when_present(self):
        model = build_executive_command_center_model(
            _brief(
                raw_payload={
                    "warehouse_slices": [
                        {"warehouse_name": "COMPUTE_WH", "credits_used": 120.25, "pct_of_total": 55.5},
                        {"warehouse_name": "ETL_WH", "credits_used": 80.0, "pct_of_total": 37.0},
                    ]
                }
            ),
            company="ALFA",
            environment="ALL",
            days=7,
        )
        self.assertEqual([row.warehouse for row in model.warehouse_slices], ["COMPUTE_WH", "ETL_WH"])
        self.assertEqual(model.warehouse_slices[0].credits_text, "120.2")
        self.assertEqual(model.warehouse_slices[0].pct_text, "55.5%")

    def test_pending_packet_is_enriched_from_compact_summary_mart(self):
        summary_frame = pd.DataFrame(
            [
                {
                    "WAREHOUSE_NAME": "COMPUTE_WH",
                    "CREDITS_USED": 10.0,
                    "UPDATED_AT": "2026-07-05T11:19:00",
                },
                {
                    "WAREHOUSE_NAME": "ETL_WH",
                    "CREDITS_USED": 5.0,
                    "UPDATED_AT": "2026-07-05T11:19:00",
                },
            ]
        )

        model = build_executive_command_center_model(
            _brief(
                state="Summary pending",
                headline="Summary pending",
                summary="Waiting for the current summary packet.",
                freshness_label="Packet pending",
                data_availability_state="Unavailable",
                metrics=(),
                raw_payload={},
            ),
            company="ALFA",
            environment="ALL",
            days=7,
            summary_frame=summary_frame,
        )

        self.assertEqual(model.summary_state, "Summary loaded")
        self.assertEqual(model.summary_headline, "Operating summary loaded")
        self.assertEqual(model.source_status, "Available")
        self.assertEqual(model.total_credits_text, "15.0")
        self.assertEqual([row.warehouse for row in model.warehouse_slices], ["COMPUTE_WH", "ETL_WH"])

    def test_long_packet_headline_is_not_used_as_compact_kpi_value(self):
        model = build_executive_command_center_model(
            _brief(
                state="Ready",
                headline="Spend increased by $466.2 in the selected window.",
                summary="Managed Snowflake object movement stayed inside review range.",
            ),
            company="ALFA",
            environment="ALL",
            days=7,
        )

        summary_card = next(card for card in model.kpis if card.key == "summary_status")
        self.assertEqual(summary_card.value, "+$466")
        self.assertEqual(summary_card.subtitle, "Spend movement")
        self.assertNotIn("selected window", summary_card.value)


if __name__ == "__main__":
    unittest.main()
