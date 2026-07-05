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


def _query_boundary_artifact(**overrides):
    commit_sha = str(overrides.get("commit_sha") or "")
    payload = {
        "commit_sha": commit_sha,
        "producer": "query_boundary_lint",
        "producer_signature": "query_boundary_lint::v2",
        "passed": True,
        "failure_count": 0,
        "rows": [
            {
                "id": "query_boundary_lint::repo_scan",
                "commit_sha": commit_sha,
                "producer": "query_boundary_lint",
                "producer_signature": "query_boundary_lint::ast_scan",
                "passed": True,
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }
    payload.update(overrides)
    return payload


def _access_control_artifact(**overrides):
    commit_sha = str(overrides.get("commit_sha") or "")
    payload = {
        "commit_sha": commit_sha,
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
                "commit_sha": commit_sha,
                "producer": "access_control_runtime",
                "producer_signature": "access_control_runtime::runtime_probe",
                "passed": True,
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }
    payload.update(overrides)
    return payload


def _cost_no_autoload_artifact(**overrides):
    commit_sha = str(overrides.get("commit_sha") or "")
    payload = {
        "commit_sha": commit_sha,
        "producer": "full_app_runtime_validation",
        "producer_signature": "cost_overview_no_autoload::v1",
        "passed": True,
        "failure_count": 0,
        "cost_overview_autoload_violation_count": 0,
        "rows": [
            {
                "id": "cost_overview_no_autoload::cost_contract",
                "commit_sha": commit_sha,
                "producer": "full_app_runtime_validation",
                "producer_signature": "cost_overview_no_autoload::runtime_row",
                "passed": True,
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }
    payload.update(overrides)
    return payload


def _target_pushdown_artifact(**overrides):
    commit_sha = str(overrides.get("commit_sha") or "")
    payload = {
        "commit_sha": commit_sha,
        "producer": "targeted_evidence_sql_pushdown",
        "producer_signature": "targeted_evidence_sql_pushdown::v1",
        "passed": True,
        "failure_count": 0,
        "target_pushdown_violation_count": 0,
        "rows": [
            {
                "id": "target_pushdown::alert_center_finding",
                "commit_sha": commit_sha,
                "producer": "targeted_evidence_sql_pushdown",
                "producer_signature": "targeted_evidence_sql_pushdown::v1",
                "passed": True,
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }
    payload.update(overrides)
    return payload


def _query_search_autorun_artifact(**overrides):
    commit_sha = str(overrides.get("commit_sha") or "")
    payload = {
        "commit_sha": commit_sha,
        "producer": "query_search_autorun",
        "producer_signature": "query_search_autorun::v1",
        "passed": True,
        "failure_count": 0,
        "query_search_broad_autorun_count": 0,
        "rows": [
            {
                "id": "query_search_autorun::render_no_click",
                "commit_sha": commit_sha,
                "producer": "query_search_autorun",
                "producer_signature": "query_search_autorun::v1",
                "passed": True,
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }
    payload.update(overrides)
    return payload


def _runtime_event_ledger_artifact(**overrides):
    commit_sha = str(overrides.get("commit_sha") or "")
    payload = {
        "commit_sha": commit_sha,
        "producer": "runtime_event_ledger",
        "producer_signature": "runtime_event_ledger::v1",
        "passed": True,
        "failure_count": 0,
        "event_count": 6,
        "pre_first_paint_session_open_count": 0,
        "shell_session_open_count": 0,
        "active_session_probe_count": 0,
        "admin_connection_test_count": 0,
        "explicit_connection_test_count": 0,
        "evidence_query_count_before_first_paint": 0,
        "account_usage_query_count_before_first_paint": 0,
        "cost_overview_autoload_violation_count": 0,
        "query_search_broad_autorun_count": 0,
        "target_pushdown_violation_count": 0,
        "route_action_sql_violation_count": 0,
        "rows": [
            {
                "id": "runtime_event_ledger::repo_scan",
                "commit_sha": commit_sha,
                "producer": "runtime_event_ledger",
                "producer_signature": "runtime_event_ledger::row",
                "passed": True,
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }
    payload.update(overrides)
    return payload


def _source_runtime_event_ledger_artifact(**overrides):
    commit_sha = str(overrides.get("commit_sha") or "")
    payload = {
        "commit_sha": commit_sha,
        "producer": "full_app_runtime_validation",
        "producer_signature": "source_runtime_event_ledger::v1",
        "passed": True,
        "failure_count": 0,
        "event_count": 6,
        "first_paint_source_event_count": 6,
        "decision_packet_source_event_count": 6,
        "section_summary_autoload_source_event_count": 1,
        "session_open_count": 0,
        "active_session_probe_count": 0,
        "direct_sql_count": 0,
        "account_usage_count": 0,
        "rows": [
            {
                "id": "source_runtime_event::first_paint",
                "commit_sha": commit_sha,
                "producer": "runtime_state",
                "producer_signature": "runtime_state::row",
                "passed": True,
                "raw_sql_included": False,
            },
            {
                "id": "source_runtime_event::section_summary_autoload",
                "commit_sha": commit_sha,
                "producer": "runtime_state",
                "producer_signature": "runtime_state::row",
                "event_type": "section_summary_autoload",
                "execution_boundary": "section_summary_autoload",
                "section": "Cost & Contract",
                "workflow": "Cost Overview",
                "query_tier": "section_summary",
                "ttl_key": "section_summary_cost_current_summary",
                "query_count_delta": 1,
                "max_rows": 200,
                "row_count": 12,
                "user_initiated": True,
                "passed": True,
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }
    payload.update(overrides)
    return payload


def _support_kwargs(commit_sha: str = "", **overrides):
    support = {
        "access_control_payload": _access_control_artifact(commit_sha=commit_sha),
        "cost_overview_payload": _cost_no_autoload_artifact(commit_sha=commit_sha),
        "target_pushdown_payload": _target_pushdown_artifact(commit_sha=commit_sha),
        "query_search_autorun_payload": _query_search_autorun_artifact(commit_sha=commit_sha),
        "query_boundary_lint_payload": _query_boundary_artifact(commit_sha=commit_sha),
        "runtime_event_ledger_payload": _runtime_event_ledger_artifact(commit_sha=commit_sha),
        "source_runtime_event_ledger_payload": _source_runtime_event_ledger_artifact(commit_sha=commit_sha),
    }
    support.update(overrides)
    return support


class PerformanceBudgetGateTests(unittest.TestCase):
    def test_primary_first_paint_packet_only_passes(self):
        from tools.contracts.performance_budget_gate import PRIMARY_SECTIONS, evaluate_performance_budget_gate

        payload = {
            "rows": [_first_paint_row(section) for section in PRIMARY_SECTIONS]
        }

        gate = evaluate_performance_budget_gate(
            payload,
            {"rows": []},
            **_support_kwargs(),
        )

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
            **_support_kwargs(),
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
            **_support_kwargs(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("route action", reasons)
        self.assertIn("no-click", reasons)

    def test_section_summary_autoload_budget_passes_when_user_initiated_and_bounded(self):
        from tools.contracts.performance_budget_gate import PRIMARY_SECTIONS, evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {"rows": [_first_paint_row(section) for section in PRIMARY_SECTIONS]},
            {
                "rows": [
                    {
                        "section": "Cost & Contract",
                        "workflow": "Cost Overview",
                        "boundary": "section_summary_autoload",
                        "query_count": 1,
                        "max_rows": 200,
                        "user_initiated": True,
                        "before_first_paint": False,
                        "account_usage_count": 0,
                        "direct_sql_count": 0,
                    }
                ]
            },
            **_support_kwargs(),
        )

        self.assertTrue(gate["passed"], gate.get("failures"))

    def test_section_summary_autoload_requires_user_navigation_context(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {"rows": []},
            {
                "rows": [
                    {
                        "section": "Cost & Contract",
                        "workflow": "Cost Overview",
                        "boundary": "section_summary_autoload",
                        "query_count": 1,
                        "max_rows": 200,
                        "user_initiated": False,
                    }
                ]
            },
            **_support_kwargs(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("user-initiated navigation", reasons)

    def test_section_summary_autoload_blocks_account_usage_and_oversized_rows(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {"rows": []},
            {
                "rows": [
                    {
                        "section": "Security Monitoring",
                        "workflow": "Security Overview",
                        "boundary": "section_summary_autoload",
                        "query_count": 1,
                        "max_rows": 201,
                        "user_initiated": True,
                        "account_usage_count": 1,
                    }
                ]
            },
            **_support_kwargs(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("row cap", reasons)
        self.assertIn("Account Usage", reasons)

    def test_section_summary_autoload_cannot_run_during_first_paint(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {"rows": []},
            {
                "rows": [
                    {
                        "section": "DBA Control Room",
                        "workflow": "Overview",
                        "boundary": "section_summary_autoload",
                        "query_count": 1,
                        "max_rows": 200,
                        "user_initiated": True,
                        "before_first_paint": True,
                    }
                ]
            },
            **_support_kwargs(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("first paint", reasons)

    def test_missing_first_paint_rows_fail(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {"rows": []},
            {"rows": []},
            **_support_kwargs(),
        )

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
            **_support_kwargs(),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("boundary", reasons)

    def test_first_paint_row_wrong_query_boundary_fails(self):
        from tools.contracts.performance_budget_gate import evaluate_performance_budget_gate

        gate = evaluate_performance_budget_gate(
            {"rows": [_first_paint_row("Executive Landing", query_boundary="compact_evidence")]},
            {"rows": []},
            **_support_kwargs(),
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
            **{
                key: value
                for key, value in _support_kwargs().items()
                if key != "cost_overview_payload"
            },
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

        gate = evaluate_performance_budget_gate(
            first_paint,
            {"rows": []},
            **_support_kwargs(),
        )

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

        gate = evaluate_performance_budget_gate(
            first_paint,
            {"rows": []},
            access_control_payload={},
            **{
                key: value
                for key, value in _support_kwargs().items()
                if key != "access_control_payload"
            },
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("Access control runtime", reasons)

    def test_wrong_commit_support_artifact_blocks_performance_gate(self):
        from tools.contracts.performance_budget_gate import PRIMARY_SECTIONS, evaluate_performance_budget_gate

        first_paint = {"rows": [_first_paint_row(section, commit_sha="current") for section in PRIMARY_SECTIONS]}

        gate = evaluate_performance_budget_gate(
            first_paint,
            {"rows": []},
            access_control_payload=_access_control_artifact(commit_sha="old"),
            **{
                key: value
                for key, value in _support_kwargs("current").items()
                if key != "access_control_payload"
            },
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("commit_sha mismatch", reasons)

    def test_query_boundary_artifact_failure_count_blocks_performance_gate(self):
        from tools.contracts.performance_budget_gate import PRIMARY_SECTIONS, evaluate_performance_budget_gate

        first_paint = {"rows": [_first_paint_row(section, commit_sha="current") for section in PRIMARY_SECTIONS]}

        gate = evaluate_performance_budget_gate(
            first_paint,
            {"rows": []},
            **_support_kwargs(
                "current",
                query_boundary_lint_payload=_query_boundary_artifact(commit_sha="current", failure_count=1),
            ),
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(str(row.get("failure_reason")) for row in gate["failures"])
        self.assertIn("failure_count=1", reasons)


if __name__ == "__main__":
    unittest.main()
