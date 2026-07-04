from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _first_paint_row(section: str, **overrides):
    row = {
        "section": section,
        "workflow": "Overview",
        "product_boundary": "first_paint_packet",
        "execution_boundary": "decision_packet",
        "query_boundary": "decision_packet",
        "cold_first_paint_packet_query_count": 1,
        "warm_first_paint_query_count": 0,
        "non_packet_first_paint_event_count": 0,
        "evidence_query_count": 0,
        "account_usage_count": 0,
        "detail_query_count": 0,
        "cost_workbench_query_count": 0,
        "query_search_query_count": 0,
        "direct_sql_count": 0,
        "session_open_count": 0,
        "pre_first_paint_session_open_count": 0,
        "shell_session_open_count": 0,
        "active_session_probe_count": 0,
        "admin_connection_test_count": 0,
        "explicit_connection_test_count": 0,
        "metadata_probe_count": 0,
        "metadata_probe_violation_count": 0,
        "cost_overview_autoload_violation_count": 0,
        "query_search_broad_autorun_count": 0,
        "target_pushdown_violation_count": 0,
        "packet_cache_hit": True,
        "packet_size_bytes": 42000,
        "elapsed_ms": 10,
        "passed": True,
    }
    row.update(overrides)
    return row


def _access_control_artifact(**overrides):
    payload = {
        "producer": "access_control_runtime",
        "producer_signature": "access_control_runtime::v1",
        "passed": True,
        "failure_count": 0,
        "pre_first_paint_session_open_count": 0,
        "shell_session_open_count": 0,
        "active_session_probe_count": 0,
        "admin_connection_test_count": 0,
        "explicit_connection_test_count": 0,
        "rows": [
            {
                "id": "access_control::shell_first_paint_no_get_session",
                "passed": True,
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }
    payload.update(overrides)
    return payload


class PerformanceBudgetGateTests(unittest.TestCase):
    def test_primary_first_paint_packet_only_passes(self):
        from tools.contracts.performance_budget_gate import PRIMARY_SECTIONS, evaluate_performance_budget_gate

        payload = {
            "rows": [_first_paint_row(section) for section in PRIMARY_SECTIONS]
        }

        gate = evaluate_performance_budget_gate(payload, {"rows": []}, access_control_payload=_access_control_artifact())

        self.assertTrue(gate["passed"], gate.get("failures"))

    def test_first_paint_evidence_and_account_usage_fail(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {
                "rows": [
                    _first_paint_row(
                        "Executive Landing",
                        evidence_query_count=1,
                        account_usage_count=1,
                        passed=False,
                    )
                ]
            },
            {"rows": []},
            access_control_payload=_access_control_artifact(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("evidence", reasons)
        self.assertIn("Account Usage", reasons)

    def test_route_and_no_click_query_budget_failures(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {"rows": []},
            {
                "rows": [
                    {"section": "Cost & Contract", "boundary": "route_action", "query_count": 1},
                    {"section": "Workload Operations", "boundary": "query_search_no_click", "query_count": 1},
                ]
            },
            access_control_payload=_access_control_artifact(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("route action", reasons)
        self.assertIn("no-click", reasons)

    def test_missing_first_paint_rows_fail(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate({"rows": []}, {"rows": []}, access_control_payload=_access_control_artifact())

        self.assertFalse(gate["passed"])
        self.assertGreaterEqual(len(gate["failures"]), 6)

    def test_first_paint_row_missing_boundary_fails(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {
                "rows": [
                    {
                        key: value
                        for key, value in _first_paint_row("Executive Landing").items()
                        if key not in {"product_boundary", "execution_boundary"}
                    }
                ]
            },
            {"rows": []},
            access_control_payload=_access_control_artifact(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("boundary", reasons)

    def test_first_paint_row_wrong_query_boundary_fails(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {"rows": [_first_paint_row("Executive Landing", query_boundary="compact_evidence")]},
            {"rows": []},
            access_control_payload=_access_control_artifact(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("decision_packet", reasons)

    def test_cost_overview_autoload_artifact_blocks_performance_gate(self):
        from tools.contracts.performance_budget_gate import (
            PRIMARY_SECTIONS,
            evaluate_cost_overview_no_autoload_gate,
            evaluate_performance_budget_gate,
        )

        first_paint = {
            "rows": [
                _first_paint_row(
                    section,
                    workflow="Cost Overview" if section == "Cost & Contract" else "Overview",
                )
                for section in PRIMARY_SECTIONS
            ]
        }

        gate = evaluate_performance_budget_gate(
            first_paint,
            {"rows": []},
            {
                "passed": False,
                "cost_overview_autoload_violation_count": 1,
                "rows": [
                    {
                        "section": "Cost & Contract",
                        "workflow": "Cost Overview",
                        "failure_reason": "Cost Overview first paint autoloaded evidence/workbench/detail.",
                    }
                ],
            },
            access_control_payload=_access_control_artifact(),
        )

        self.assertFalse(gate["passed"])
        self.assertEqual(gate["cost_overview_autoload_violation_count"], 1)
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("Cost Overview", reasons)
        cost_gate = evaluate_cost_overview_no_autoload_gate({
            "passed": False,
            "cost_overview_autoload_violation_count": 1,
            "rows": [
                {
                    "section": "Cost & Contract",
                    "workflow": "Cost Overview",
                    "failure_reason": "Cost Overview first paint autoloaded evidence/workbench/detail.",
                    "passed": False,
                }
            ],
        })
        self.assertFalse(cost_gate["passed"])
        self.assertEqual(cost_gate["cost_overview_autoload_violation_count"], 1)

    def test_cost_overview_no_autoload_gate_requires_runtime_artifact(self):
        from tools.contracts.performance_budget_gate import evaluate_cost_overview_no_autoload_gate

        gate = evaluate_cost_overview_no_autoload_gate({})

        self.assertFalse(gate["passed"])
        self.assertEqual(gate["cost_overview_autoload_violation_count"], 1)

    def test_pre_first_paint_shell_session_and_metadata_probe_fail(self):
        from tools.contracts.performance_budget_gate import PRIMARY_SECTIONS, evaluate_performance_budget_gate

        first_paint = {
            "rows": [
                _first_paint_row(
                    section,
                    session_open_count=1,
                    pre_first_paint_session_open_count=1 if section == "Executive Landing" else 0,
                    shell_session_open_count=1 if section == "DBA Control Room" else 0,
                    metadata_probe_count=2 if section == "Alert Center" else 0,
                )
                for section in PRIMARY_SECTIONS
            ]
        }

        gate = evaluate_performance_budget_gate(first_paint, {"rows": []}, access_control_payload=_access_control_artifact())

        self.assertFalse(gate["passed"])
        self.assertEqual(gate["pre_first_paint_session_open_count"], 1)
        self.assertEqual(gate["shell_session_open_count"], 1)
        self.assertEqual(gate["metadata_probe_violation_count"], 1)
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("before first-paint", reasons)
        self.assertIn("metadata", reasons)

    def test_missing_access_control_artifact_blocks_performance_gate(self):
        from tools.contracts.performance_budget_gate import PRIMARY_SECTIONS, evaluate_performance_budget_gate

        first_paint = {"rows": [_first_paint_row(section) for section in PRIMARY_SECTIONS]}

        gate = evaluate_performance_budget_gate(first_paint, {"rows": []}, access_control_payload={})

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("Access control runtime", reasons)


if __name__ == "__main__":
    unittest.main()
