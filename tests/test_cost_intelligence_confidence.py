from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from sections.cost_contract_intelligence import (  # noqa: E402
    _build_cost_spike_root_cause_board,
    _cost_correlation_confidence_score,
    top_cost_correlation_findings,
)


class CostIntelligenceConfidenceTests(unittest.TestCase):
    def test_confidence_score_and_label_are_present(self) -> None:
        score = _cost_correlation_confidence_score(
            cost_delta=2500,
            cost_delta_pct=35,
            time_proximity_minutes=30,
            matched_signal_count=3,
            source_object_count=3,
            baseline_history_days=30,
            direct_entity_match=True,
        )

        self.assertGreaterEqual(score, 60)

    def test_findings_include_confidence_fields_and_caveat(self) -> None:
        cockpit = pd.DataFrame([{
            "CURRENT_CREDITS": 120.0,
            "PRIOR_CREDITS": 80.0,
            "TOP_INCREASE_WAREHOUSE": "WH_ALFA_OVERWATCH",
            "TOP_INCREASE_CREDITS": 25.0,
        }])
        run_rate = pd.DataFrame([{
            "AVG_DAILY_7D": 14.0,
            "AVG_DAILY_30D": 10.0,
            "PCT_VS_30D_AVG": 40.0,
            "YOY_7D_PCT": 10.0,
        }])

        _summary, board = _build_cost_spike_root_cause_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=pd.DataFrame(),
            credit_price=4.0,
            state={},
        )

        required = {
            "FINDING_ID",
            "HEADLINE",
            "CONCISE_EXPLANATION",
            "CONFIDENCE_SCORE",
            "CONFIDENCE_LABEL",
            "CORRELATION_TYPE",
            "DRIVER_TYPE",
            "DRIVER_NAME",
            "COST_DELTA",
            "COST_DELTA_PCT",
            "MATCHED_SIGNALS",
            "MATCHED_SIGNAL_COUNT",
            "SOURCE_OBJECTS",
            "CAVEATS",
            "RECOMMENDED_WORKFLOW",
            "DETAILS_AVAILABLE",
        }
        self.assertTrue(required.issubset(board.columns))
        self.assertTrue(board["CONFIDENCE_SCORE"].between(0, 100).all())
        self.assertTrue(set(board["CONFIDENCE_LABEL"]).issubset({"High", "Medium", "Low", "Directional"}))

    def test_low_confidence_text_avoids_causal_language(self) -> None:
        rows = pd.DataFrame([{
            "DRIVER": "Role / user / department",
            "ENTITY": "Details available when needed",
            "EVIDENCE": "Human driver rows are available after refresh.",
            "VALUE_AT_RISK_USD": 0.0,
            "ROUTE": "Cost & Contract > Cost Explorer",
        }])

        first_paint = top_cost_correlation_findings(rows, limit=3, details_available=False)
        low_rows = first_paint[first_paint["CONFIDENCE_LABEL"].isin(["Low", "Medium", "Directional"])]
        text = " ".join(
            str(value).lower()
            for value in low_rows[["CONCISE_EXPLANATION", "CAVEATS"]].to_numpy().ravel()
        )

        for forbidden in ("caused", "causes", "root cause is", "because of"):
            self.assertNotIn(forbidden, text)
        self.assertIn("correlation only", text)

    def test_first_paint_limits_top_three_and_hides_details(self) -> None:
        rows = pd.DataFrame(
            [
                {"DRIVER": f"Driver {idx}", "ENTITY": f"Entity {idx}", "VALUE_AT_RISK_USD": idx * 100}
                for idx in range(6)
            ]
        )

        first_paint = top_cost_correlation_findings(rows, limit=3, details_available=False)

        self.assertEqual(len(first_paint), 3)
        self.assertFalse(first_paint["DETAILS_AVAILABLE"].any())


if __name__ == "__main__":
    unittest.main()
