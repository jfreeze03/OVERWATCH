from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from sections import summary_mart_loaders as loaders  # noqa: E402


class SummaryResultStateTests(unittest.TestCase):
    def _result_with_probe(self, probe: loaders.SourceProbeResult) -> loaders.SummaryResult:
        with patch.object(loaders, "run_query", return_value=pd.DataFrame()), patch.object(
            loaders,
            "probe_summary_source",
            return_value=probe,
        ):
            return loaders._summary_result(
                section="Cost & Contract",
                workflow="Cost Overview",
                ttl_key="unit_scope",
                sql="SELECT COST_USD FROM V_WAREHOUSE_DAILY_CREDITS LIMIT 1",
                limit=25,
            )

    def test_object_missing_maps_to_setup_required(self) -> None:
        result = self._result_with_probe(loaders.SourceProbeResult(False, None, None, None, None))

        self.assertEqual(result.state, loaders.DataState.SETUP_REQUIRED)
        self.assertTrue(result.is_fallback)

    def test_global_empty_maps_to_refresh_required(self) -> None:
        result = self._result_with_probe(loaders.SourceProbeResult(True, 0, 0, None, None))

        self.assertEqual(result.state, loaders.DataState.REFRESH_REQUIRED)

    def test_scoped_empty_maps_to_no_rows_for_scope(self) -> None:
        result = self._result_with_probe(loaders.SourceProbeResult(True, 12, 0, None, None))

        self.assertEqual(result.state, loaders.DataState.NO_ROWS_FOR_SCOPE)

    def test_stale_row_maps_to_loaded_stale(self) -> None:
        stale_ts = datetime.now(UTC) - timedelta(minutes=loaders.SUMMARY_STALE_MINUTES + 30)
        frame = pd.DataFrame([{"COST_USD": 42.0, "UPDATED_AT": stale_ts.isoformat()}])

        with patch.object(loaders, "run_query", return_value=frame):
            result = loaders._summary_result(
                section="Cost & Contract",
                workflow="Cost Overview",
                ttl_key="unit_stale",
                sql="SELECT COST_USD, UPDATED_AT FROM V_WAREHOUSE_DAILY_CREDITS LIMIT 1",
                limit=25,
            )

        self.assertEqual(result.state, loaders.DataState.LOADED_STALE)
        self.assertGreater(result.freshness_minutes or 0, loaders.SUMMARY_STALE_MINUTES)

    def test_query_failure_maps_to_query_failed(self) -> None:
        with patch.object(loaders, "run_query", side_effect=RuntimeError("permission denied")):
            result = loaders._summary_result(
                section="Cost & Contract",
                workflow="Cost Overview",
                ttl_key="unit_failure",
                sql="SELECT COST_USD FROM V_WAREHOUSE_DAILY_CREDITS LIMIT 1",
                limit=25,
            )

        self.assertEqual(result.state, loaders.DataState.QUERY_FAILED)


if __name__ == "__main__":
    unittest.main()
