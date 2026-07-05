from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FirstPaintSloTests(unittest.TestCase):
    def _rows(
        self,
        *,
        elapsed_ms: int = 50,
        warm_queries: int = 0,
        shell_sessions: int = 0,
        active_session_probes: int = 0,
        metadata_probe_violations: int = 0,
        cost_autoload: int = 0,
        query_search_broad: int = 0,
        commit_sha: str = "",
    ):
        from tools.contracts.first_paint_slo import PRIMARY_SECTIONS

        return {
            "rows": [
                {
                    "section": section,
                    "commit_sha": commit_sha,
                    "workflow": "Overview",
                    "elapsed_ms": elapsed_ms,
                    "cold_first_paint_packet_query_count": 1,
                    "query_boundary": "decision_packet",
                    "warm_first_paint_query_count": warm_queries,
                    "evidence_query_count": 0,
                    "account_usage_count": 0,
                    "detail_query_count": 0,
                    "cost_workbench_query_count": 0,
                    "query_search_query_count": 0,
                    "direct_sql_count": 0,
                    "pre_first_paint_session_open_count": 0,
                    "shell_session_open_count": shell_sessions,
                    "active_session_probe_count": active_session_probes,
                    "admin_connection_test_count": 0,
                    "explicit_connection_test_count": 0,
                    "metadata_probe_count": 0,
                    "metadata_probe_violation_count": metadata_probe_violations,
                    "cost_overview_autoload_violation_count": cost_autoload,
                    "query_search_broad_autorun_count": query_search_broad,
                    "target_pushdown_violation_count": 0,
                    "packet_cache_hit": True,
                    "packet_size_bytes": 42_000,
                    "passed": True,
                }
                for section in PRIMARY_SECTIONS
            ]
        }

    def _support_artifacts(self, *, commit_sha: str = ""):
        return {
            "access_control_payload": {
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
            },
            "cost_overview_payload": {
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
            },
            "target_pushdown_payload": {
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
            },
            "query_search_autorun_payload": {
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
            },
            "query_boundary_lint_payload": {
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
            },
            "runtime_event_ledger_payload": {
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
            },
            "source_runtime_event_ledger_payload": {
                "commit_sha": commit_sha,
                "producer": "full_app_runtime_validation",
                "producer_signature": "source_runtime_event_ledger::v1",
                "passed": True,
                "failure_count": 0,
                "event_count": 6,
                "first_paint_source_event_count": 6,
                "decision_packet_source_event_count": 6,
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
                    }
                ],
                "raw_sql_included": False,
            },
        }

    def test_primary_packet_rows_under_slo_pass(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        gate = evaluate_first_paint_slo(
            self._rows(commit_sha="current"),
            packet_size_payload={"max_packet_bytes": 42_000},
            **self._support_artifacts(commit_sha="current"),
        )

        self.assertTrue(gate["passed"], gate.get("failures"))
        self.assertTrue(gate["first_paint_slo_passed"])

    def test_supporting_runtime_artifacts_are_consumed(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        gate = evaluate_first_paint_slo(
            self._rows(commit_sha="current"),
            packet_size_payload={"max_packet_bytes": 42_000},
            **self._support_artifacts(commit_sha="current"),
        )

        self.assertTrue(gate["passed"], gate.get("failures"))
        self.assertTrue(gate["access_control_runtime_passed"])
        self.assertTrue(gate["cost_no_autoload_passed"])
        self.assertTrue(gate["target_pushdown_passed"])
        self.assertTrue(gate["query_search_autorun_passed"])

    def test_allowed_admin_connection_probe_row_does_not_fail_slo(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        artifacts = self._support_artifacts(commit_sha="current")
        artifacts["access_control_payload"]["admin_connection_test_count"] = 1
        artifacts["access_control_payload"]["explicit_connection_test_count"] = 1
        artifacts["access_control_payload"]["rows"].append(
            {
                "id": "access_control::forced_probe_uses_explicit_admin_test",
                "commit_sha": "current",
                "producer": "access_control_runtime",
                "producer_signature": "access_control_runtime::runtime_probe",
                "passed": True,
                "raw_sql_included": False,
            }
        )

        gate = evaluate_first_paint_slo(
            self._rows(commit_sha="current"),
            packet_size_payload={"max_packet_bytes": 42_000},
            **artifacts,
        )

        self.assertTrue(gate["passed"], gate.get("failures"))
        self.assertTrue(gate["access_control_runtime_passed"])

    def test_missing_supporting_runtime_artifact_fails(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        artifacts = self._support_artifacts(commit_sha="current")
        artifacts["access_control_payload"] = {}
        gate = evaluate_first_paint_slo(
            self._rows(commit_sha="current"),
            packet_size_payload={"max_packet_bytes": 42_000},
            **artifacts,
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(row["failure_reason"] for row in gate["failures"])
        self.assertIn("missing Access control runtime proof artifact", reasons)

    def test_supporting_runtime_artifact_wrong_commit_fails(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        artifacts = self._support_artifacts(commit_sha="old")
        gate = evaluate_first_paint_slo(
            self._rows(commit_sha="current"),
            packet_size_payload={"max_packet_bytes": 42_000},
            **artifacts,
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(row["failure_reason"] for row in gate["failures"])
        self.assertIn("commit_sha mismatch", reasons)

    def test_supporting_runtime_artifact_failure_count_and_raw_sql_fail(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        artifacts = self._support_artifacts(commit_sha="current")
        artifacts["query_boundary_lint_payload"]["failure_count"] = 1
        artifacts["query_boundary_lint_payload"]["raw_sql_included"] = True
        gate = evaluate_first_paint_slo(
            self._rows(commit_sha="current"),
            packet_size_payload={"max_packet_bytes": 42_000},
            **artifacts,
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(row["failure_reason"] for row in gate["failures"])
        self.assertIn("failure_count=1", reasons)
        self.assertIn("raw_sql_included=true", reasons)

    def test_missing_packet_size_fails(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        payload = self._rows()
        for row in payload["rows"]:
            row.pop("packet_size_bytes", None)
        gate = evaluate_first_paint_slo(payload)

        self.assertFalse(gate["passed"])
        self.assertIn("packet size", " ".join(row["failure_reason"] for row in gate["failures"]))

    def test_slow_or_warm_query_row_fails(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        gate = evaluate_first_paint_slo(self._rows(elapsed_ms=2_000, warm_queries=1), packet_size_payload={"max_packet_bytes": 42_000})

        self.assertFalse(gate["passed"])
        reasons = " ".join(row["failure_reason"] for row in gate["failures"])
        self.assertIn("1.5s", reasons)
        self.assertIn("warm", reasons)

    def test_missing_first_paint_probe_telemetry_fails(self):
        from tools.contracts.first_paint_slo import PRIMARY_SECTIONS, evaluate_first_paint_slo

        gate = evaluate_first_paint_slo(
            {
                "rows": [
                    {
                        "section": section,
                        "workflow": "Overview",
                        "elapsed_ms": 50,
                        "cold_first_paint_packet_query_count": 1,
                        "warm_first_paint_query_count": 0,
                    }
                    for section in PRIMARY_SECTIONS
                ]
            },
            packet_size_payload={"max_packet_bytes": 42_000},
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(row["failure_reason"] for row in gate["failures"])
        self.assertIn("missing first-paint telemetry fields", reasons)

    def test_non_decision_packet_query_boundary_fails(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        payload = self._rows()
        payload["rows"][0]["query_boundary"] = "compact_evidence"

        gate = evaluate_first_paint_slo(payload, packet_size_payload={"max_packet_bytes": 42_000})

        self.assertFalse(gate["passed"])
        reasons = " ".join(row["failure_reason"] for row in gate["failures"])
        self.assertIn("decision_packet", reasons)

    def test_shell_session_probe_or_autoload_counters_fail(self):
        from tools.contracts.first_paint_slo import evaluate_first_paint_slo

        gate = evaluate_first_paint_slo(
            self._rows(
                shell_sessions=1,
                active_session_probes=1,
                metadata_probe_violations=1,
                cost_autoload=1,
                query_search_broad=1,
            ),
            packet_size_payload={"max_packet_bytes": 42_000},
        )

        self.assertFalse(gate["passed"])
        reasons = " ".join(row["failure_reason"] for row in gate["failures"])
        self.assertIn("shell opened", reasons)
        self.assertIn("active-session probe", reasons)
        self.assertIn("Cost Overview", reasons)
        self.assertIn("Query Search broad", reasons)


if __name__ == "__main__":
    unittest.main()
