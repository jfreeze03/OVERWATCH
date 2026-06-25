from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class CostContractSplashMonitoringLoaderTests(unittest.TestCase):
    def test_cost_contract_reexports_moved_splash_and_monitoring_helpers(self):
        from sections import cost_contract
        from sections import cost_contract_loader
        from sections import cost_contract_monitoring
        from sections import cost_contract_splash

        self.assertIs(cost_contract._cost_splash_meta, cost_contract_splash._cost_splash_meta)
        self.assertIs(cost_contract._empty_cost_splash, cost_contract_splash._empty_cost_splash)
        self.assertIs(cost_contract._cached_cost_splash, cost_contract_splash._cached_cost_splash)
        self.assertIs(cost_contract._ensure_cost_splash, cost_contract_splash._ensure_cost_splash)
        self.assertIs(cost_contract._maybe_autoload_cost_splash, cost_contract_splash._maybe_autoload_cost_splash)
        self.assertIs(cost_contract._cost_splash_summary, cost_contract_splash._cost_splash_summary)
        self.assertIs(cost_contract._render_cost_splash, cost_contract_splash._render_cost_splash)
        self.assertIs(cost_contract._build_cost_monitoring_alert_rows, cost_contract_monitoring._build_cost_monitoring_alert_rows)
        self.assertIs(cost_contract._build_cost_incident_timeline, cost_contract_monitoring._build_cost_incident_timeline)
        self.assertIs(cost_contract._build_cost_monitoring_mart_operability, cost_contract_monitoring._build_cost_monitoring_mart_operability)
        self.assertIs(cost_contract._refresh_cost_detail_state, cost_contract_loader._refresh_cost_detail_state)

    def test_cost_splash_meta_empty_and_cache_behavior_stays_stable(self):
        from sections import cost_contract_splash
        from sections.cost_contract_contracts import _COST_SPLASH_KEY

        meta = cost_contract_splash._cost_splash_meta("ALFA", 7, 4.0)
        self.assertEqual(meta, {"company": "ALFA", "days": 7, "credit_price": 4.0})

        empty = cost_contract_splash._empty_cost_splash("ALFA", 7, 4.0)
        self.assertFalse(empty["loaded"])
        self.assertEqual(empty["meta"], meta)
        self.assertEqual(empty["source"], "")
        self.assertEqual(empty["errors"], [])
        self.assertIsNone(empty["cockpit"])

        cached = {"meta": meta, "loaded": True, "source": "Fast summary"}
        state = {_COST_SPLASH_KEY: cached}
        with patch.object(cost_contract_splash.st, "session_state", state):
            self.assertIs(cost_contract_splash._cached_cost_splash("ALFA", 7, 4.0), cached)
            miss = cost_contract_splash._cached_cost_splash("Trexis", 7, 4.0)

        self.assertFalse(miss["loaded"])
        self.assertEqual(miss["meta"]["company"], "Trexis")

    def test_navigation_autoload_request_keeps_cost_splash_on_demand(self):
        from sections import cost_contract_splash
        from sections.cost_contract_contracts import (
            _COST_SPLASH_AUTOLOAD_SCOPE_KEY,
            _COST_SPLASH_KEY,
        )

        state = {
            "_overwatch_pending_autoload_section": "Cost & Contract",
            "_overwatch_pending_autoload_started_at": "2026-06-24T00:00:00",
        }
        with patch.object(cost_contract_splash.st, "session_state", state), patch.object(
            cost_contract_splash.st,
            "caption",
        ) as caption, patch.object(
            cost_contract_splash,
            "get_session_for_action",
            side_effect=AssertionError("Cost first paint must not request Snowflake"),
        ), patch.object(
            cost_contract_splash,
            "run_query_or_raise",
            side_effect=AssertionError("Cost first paint must not query Snowflake"),
        ):
            splash = cost_contract_splash._maybe_autoload_cost_splash("ALFA", 7, 4.0)

        self.assertFalse(splash["loaded"])
        self.assertNotIn(_COST_SPLASH_KEY, state)
        self.assertNotIn("_overwatch_pending_autoload_section", state)
        self.assertNotIn("_overwatch_pending_autoload_started_at", state)
        self.assertEqual(
            state[_COST_SPLASH_AUTOLOAD_SCOPE_KEY],
            {"company": "ALFA", "days": 7, "credit_price": 4.0},
        )
        caption.assert_called_once()
        self.assertIn("without loading cost facts", caption.call_args.args[0])

    def test_cost_splash_summary_preserves_service_total_and_warehouse_basis(self):
        from sections.cost_contract_splash import _cost_splash_summary

        service_splash = {
            "cockpit": pd.DataFrame([{
                "CURRENT_CREDITS": 8.0,
                "PRIOR_CREDITS": 4.0,
                "ACTIVE_WAREHOUSES": 1,
                "TOP_INCREASE_WAREHOUSE": "COMPUTE_WH",
                "TOP_INCREASE_CREDITS": 2.0,
            }]),
            "trend": pd.DataFrame([{"DAILY_CREDITS": 2.0, "DAILY_SPEND_USD": 9.0}]),
            "warehouse_delta": pd.DataFrame([{
                "WAREHOUSE_NAME": "COMPUTE_WH",
                "CURRENT_CREDITS": 8.0,
                "PRIOR_CREDITS": 4.0,
                "CREDIT_DELTA": 4.0,
            }]),
            "service_costs": pd.DataFrame([
                {
                    "SERVICE_TYPE": "WAREHOUSE_METERING",
                    "CREDITS_BILLED": 10.0,
                    "CREDITS_BILLED_PRIOR": 5.0,
                    "ESTIMATED_COST_USD": 40.0,
                    "PRIOR_ESTIMATED_COST_USD": 20.0,
                    "CREDITS_USED_COMPUTE": 8.0,
                    "CREDITS_USED_CLOUD_SERVICES": 2.0,
                },
                {
                    "SERVICE_TYPE": "CLOUD_SERVICES",
                    "CREDITS_BILLED": 3.0,
                    "CREDITS_BILLED_PRIOR": 1.0,
                    "ESTIMATED_COST_USD": 12.0,
                    "PRIOR_ESTIMATED_COST_USD": 4.0,
                    "CREDITS_USED_COMPUTE": 0.0,
                    "CREDITS_USED_CLOUD_SERVICES": 3.0,
                },
            ]),
            "cortex": pd.DataFrame([{
                "CORTEX_SPEND_USD": 7.5,
                "CORTEX_CREDITS": 1.5,
                "CORTEX_REQUESTS": 12,
                "TOP_CORTEX_USER": "USER_A",
                "TOP_CORTEX_USER_SPEND_USD": 5.0,
            }]),
            "run_rate": pd.DataFrame([{
                "PROJECTED_30D_FROM_7D": 30.0,
                "AVG_DAILY_7D": 1.0,
                "RUN_RATE_STATE": "Rising",
                "YOY_STATE": "No YOY baseline",
                "YOY_7D_PCT": None,
            }]),
        }

        service_summary = _cost_splash_summary(service_splash, credit_price=4.0, days=7)
        self.assertEqual(service_summary["cost_basis"], "Official account service total")
        self.assertEqual(service_summary["current_credits"], 13.0)
        self.assertEqual(service_summary["spend"], 52.0)
        self.assertEqual(service_summary["prior_spend"], 24.0)
        self.assertEqual(service_summary["top_service"], "WAREHOUSE_METERING")
        self.assertEqual(service_summary["active_services"], 2)

        warehouse_splash = dict(service_splash)
        warehouse_splash["service_costs"] = pd.DataFrame()
        warehouse_summary = _cost_splash_summary(warehouse_splash, credit_price=4.0, days=7)
        self.assertEqual(warehouse_summary["cost_basis"], "Warehouse metering total")
        self.assertEqual(warehouse_summary["spend"], 32.0)
        self.assertEqual(warehouse_summary["prior_spend"], 16.0)

    def test_cost_monitoring_alert_rows_keep_alert_center_contract_and_dedupe(self):
        from sections import cost_contract_monitoring

        root_cause = pd.DataFrame([
            {
                "SEVERITY": "Critical",
                "ENTITY": "COMPUTE_WH",
                "EVIDENCE": "Spend jumped",
                "NEXT_ACTION": "Review warehouse.",
                "PROOF_REQUIRED": "Metering proof",
                "ROUTE": "Cost & Contract > Cost by Warehouse",
                "VALUE_AT_RISK_USD": 250.25,
            },
            {
                "SEVERITY": "Critical",
                "ENTITY": "COMPUTE_WH",
                "EVIDENCE": "Spend jumped",
                "NEXT_ACTION": "Review warehouse.",
                "PROOF_REQUIRED": "Metering proof",
                "ROUTE": "Cost & Contract > Cost by Warehouse",
                "VALUE_AT_RISK_USD": 250.25,
            },
        ])
        correlation = pd.DataFrame([{
            "SEVERITY": "High",
            "ENTITY": "TASK_A",
            "EVIDENCE": "Deployment aligned to spike",
            "NEXT_ACTION": "Compare change telemetry.",
            "PROOF_REQUIRED": "Change proof",
            "ROUTE": "Security Monitoring",
        }])

        with patch.object(cost_contract_monitoring, "alert_delivery_status_for_target", return_value="Configured"):
            summary, board = cost_contract_monitoring._build_cost_monitoring_alert_rows(
                root_cause=root_cause,
                correlation=correlation,
                email_target="jdees@alfains.com",
            )

        self.assertEqual(summary["alert_count"], 2)
        self.assertEqual(summary["critical_high"], 2)
        self.assertEqual(board["CATEGORY"].unique().tolist(), ["Cost Control"])
        self.assertEqual(board["STATUS"].unique().tolist(), ["New"])
        self.assertEqual(board["DELIVERY_STATUS"].unique().tolist(), ["Configured"])
        self.assertEqual(board.iloc[0]["SEVERITY"], "Critical")
        self.assertEqual(board.iloc[0]["ALERT_TYPE"], "Cost Root Cause Candidate")

    def test_cost_incident_timeline_preserves_five_steps_and_routes(self):
        from sections.cost_contract_monitoring import _build_cost_incident_timeline

        cockpit = pd.DataFrame([{
            "CURRENT_CREDITS": 40.0,
            "PRIOR_CREDITS": 20.0,
            "TOP_INCREASE_WAREHOUSE": "COMPUTE_WH",
            "TOP_INCREASE_CREDITS": 10.0,
        }])
        run_rate = pd.DataFrame([{"PCT_VS_30D_AVG": 30.0}])
        queue = pd.DataFrame([{"CATEGORY": "Cost", "STATUS": "New"}])

        summary, timeline = _build_cost_incident_timeline(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            alert_rows=pd.DataFrame(),
            state={},
        )

        self.assertEqual(summary["event_count"], 5)
        self.assertEqual(timeline["INCIDENT_STEP"].tolist(), [
            "Cost movement detected",
            "Root cause candidate",
            "Change correlation checked",
            "Alert routed",
            "DBA action and measurement",
        ])
        self.assertEqual(timeline["ROUTE"].tolist(), [
            "Cost & Contract > Cost Explorer > Warehouse",
            "Cost & Contract",
            "Security Monitoring",
            "Alert Center",
            "Cost & Contract > Cost Recommendations",
        ])

    def test_refresh_cost_detail_state_writes_success_keys(self):
        from sections.cost_contract_loader import _refresh_cost_detail_state

        state = {}

        def _run_query(sql, **_kwargs):
            return pd.DataFrame([{"SQL": sql}])

        def _run_query_or_raise(sql, **_kwargs):
            return pd.DataFrame([{"SQL": sql}])

        _refresh_cost_detail_state(
            state,
            session=object(),
            company="ALFA",
            days=7,
            credit_price=4.0,
            run_query_func=_run_query,
            run_query_or_raise_func=_run_query_or_raise,
            load_action_queue_func=lambda _session: pd.DataFrame([{"CATEGORY": "Cost"}]),
            service_lens_loader=lambda *args, **kwargs: SimpleNamespace(
                data=pd.DataFrame([{"SERVICE_TYPE": "WAREHOUSE_METERING"}]),
                message="",
                source="service lens",
            ),
            mart_cockpit_sql_builder=lambda company, days: "mart cockpit",
            live_cockpit_sql_builder=lambda company, days: "live cockpit",
            mart_run_rate_sql_builder=lambda company: "mart run",
            live_run_rate_sql_builder=lambda company: "live run",
            reconciliation_sql_builder=lambda days, prefer_query_attribution=True: "reconcile",
            efficiency_summary_sql_builder=lambda *args, **kwargs: "efficiency",
            warehouse_efficiency_sql_builder=lambda *args, **kwargs: "warehouse efficiency",
            clustering_cost_sql_builder=lambda *args, **kwargs: "clustering",
            ai_credit_price_func=lambda: 2.0,
            loaded_at_func=lambda meta, source: {**meta, "source": source, "loaded_at": "now"},
        )

        self.assertEqual(state["cost_contract_cockpit_source"], "Fast warehouse cost summary")
        self.assertEqual(state["cost_contract_cockpit_meta"]["source"], "Fast warehouse cost summary")
        self.assertEqual(state["cost_contract_cockpit_error"], "")
        self.assertEqual(state["cost_contract_run_rate_source"], "Fast run-rate summary")
        self.assertEqual(state["cost_contract_queue_error"], "")
        self.assertEqual(state["cost_contract_attribution_source"], "SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY + WAREHOUSE_METERING_HISTORY")
        self.assertEqual(state["cost_contract_service_lens_source"], "service lens")
        self.assertEqual(state["cost_contract_efficiency_summary_error"], "")
        self.assertEqual(state["cost_contract_warehouse_efficiency_error"], "")
        self.assertEqual(state["cost_contract_clustering_cost_error"], "")

    def test_refresh_cost_detail_state_writes_failure_keys(self):
        from sections.cost_contract_loader import _refresh_cost_detail_state

        state = {}

        def _run_query(_sql, **_kwargs):
            raise RuntimeError("query failed")

        def _run_query_or_raise(_sql, **_kwargs):
            raise RuntimeError("detail failed")

        def _load_action_queue(_session):
            raise RuntimeError("queue failed")

        def _service_lens(*_args, **_kwargs):
            raise RuntimeError("service failed")

        _refresh_cost_detail_state(
            state,
            session=object(),
            company="ALFA",
            days=7,
            credit_price=4.0,
            run_query_func=_run_query,
            run_query_or_raise_func=_run_query_or_raise,
            load_action_queue_func=_load_action_queue,
            service_lens_loader=_service_lens,
            mart_cockpit_sql_builder=lambda company, days: "mart cockpit",
            live_cockpit_sql_builder=lambda company, days: "live cockpit",
            mart_run_rate_sql_builder=lambda company: "mart run",
            live_run_rate_sql_builder=lambda company: "live run",
            reconciliation_sql_builder=lambda days, prefer_query_attribution=True: "reconcile",
            efficiency_summary_sql_builder=lambda *args, **kwargs: "efficiency",
            warehouse_efficiency_sql_builder=lambda *args, **kwargs: "warehouse efficiency",
            clustering_cost_sql_builder=lambda *args, **kwargs: "clustering",
            snowflake_error_formatter=lambda exc: f"ERR:{exc}",
            ai_credit_price_func=lambda: 2.0,
            loaded_at_func=lambda meta, source: {**meta, "source": source, "loaded_at": "now"},
        )

        self.assertIn("Fast summary unavailable: ERR:query failed; live fallback failed: ERR:query failed", state["cost_contract_cockpit_error"])
        self.assertIn("Fast summary unavailable: ERR:query failed; live fallback failed: ERR:query failed", state["cost_contract_run_rate_error"])
        self.assertEqual(state["cost_contract_queue_error"], "ERR:queue failed")
        self.assertEqual(state["cost_contract_attribution_error"], "ERR:detail failed")
        self.assertEqual(state["cost_contract_service_lens_error"], "ERR:service failed")
        self.assertEqual(state["cost_contract_efficiency_summary_error"], "ERR:detail failed")
        self.assertEqual(state["cost_contract_warehouse_efficiency_error"], "ERR:detail failed")
        self.assertEqual(state["cost_contract_clustering_cost_error"], "ERR:detail failed")


if __name__ == "__main__":
    unittest.main()
