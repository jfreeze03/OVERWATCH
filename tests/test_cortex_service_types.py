from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class CortexServiceTypeTests(unittest.TestCase):
    def test_known_cortex_service_types_count(self):
        from utils.cortex_service_types import cortex_service_type_mask

        frame = pd.DataFrame(
            {
                "SERVICE_TYPE": [
                    "CORTEX",
                    "CORTEX_AI",
                    "CORTEX_SEARCH",
                    "DOCUMENT_AI",
                    "FINE_TUNING",
                    "AI_SERVICES",
                ]
            }
        )

        self.assertEqual(cortex_service_type_mask(frame).tolist(), [True, True, True, True, True, True])

    def test_broad_ai_substring_does_not_count(self):
        from utils.cortex_service_types import cortex_service_type_mask

        frame = pd.DataFrame({"SERVICE_TYPE": ["MAINTENANCE_AI_HELPER", "EMAIL_AI_AUDIT", "WAREHOUSE_METERING"]})

        self.assertEqual(cortex_service_type_mask(frame).tolist(), [False, False, False])

    def test_unknown_service_types_are_reported(self):
        from utils.cortex_service_types import cortex_service_type_mapping_results

        results = cortex_service_type_mapping_results(
            pd.DataFrame({"SERVICE_TYPE": ["CORTEX_AI", "WAREHOUSE_METERING", "MAINTENANCE_AI_HELPER"]})
        )

        self.assertTrue(results["passed"], results)
        self.assertFalse(results["broad_ai_substring_match_enabled"])
        self.assertEqual(results["unknown_service_types"], ["MAINTENANCE_AI_HELPER", "WAREHOUSE_METERING"])


if __name__ == "__main__":
    unittest.main()
