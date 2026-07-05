from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.contracts.runtime_event_ledger import (
    ACTION_CLICK_REL,
    ACCESS_CONTROL_RUNTIME_REL,
    COST_NO_AUTOLOAD_REL,
    FIRST_PAINT_REL,
    PRIMARY_SECTIONS,
    QUERY_SEARCH_AUTORUN_REL,
    RUNTIME_EVENT_LEDGER_GATE_REL,
    SOURCE_RUNTIME_EVENT_LEDGER_REL,
    build_runtime_event_ledger_results,
    build_source_runtime_event_ledger_payload,
    write_runtime_event_ledger_artifacts,
)


class RuntimeEventLedgerTests(unittest.TestCase):
    commit = "abc123"

    def _write_json(self, root: Path, rel: str, payload: object) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_passing(self, root: Path) -> None:
        first_paint_rows = [
            {
                "section": section,
                "workflow": "Overview",
                "commit_sha": self.commit,
                "passed": True,
                "cold_first_paint_packet_query_count": 1,
                "warm_first_paint_query_count": 0,
                "evidence_query_count": 0,
                "account_usage_count": 0,
                "detail_query_count": 0,
                "cost_workbench_query_count": 0,
                "query_search_query_count": 0,
                "direct_sql_count": 0,
                "non_packet_first_paint_event_count": 0,
                "pre_first_paint_session_open_count": 0,
                "shell_session_open_count": 0,
                "active_session_probe_count": 0,
                "query_boundary": "decision_packet",
                "producer": "runtime",
                "producer_signature": "sig",
                "raw_sql_included": False,
            }
            for section in PRIMARY_SECTIONS
        ]
        self._write_json(root, FIRST_PAINT_REL, {"rows": first_paint_rows})
        self._write_json(
            root,
            ACTION_CLICK_REL,
            {
                "actions": [
                    {
                        "section": "Alert Center",
                        "workflow": "Overview",
                        "action_area": "route_action",
                        "clicked": True,
                        "stable_key": "view_all_priorities",
                        "commit_sha": self.commit,
                        "passed": True,
                        "query_count": 0,
                        "session_open_count": 0,
                        "direct_sql_count": 0,
                        "account_usage_count": 0,
                        "producer": "runtime",
                        "producer_signature": "sig",
                        "raw_sql_included": False,
                    }
                ]
            },
        )
        self._write_json(
            root,
            QUERY_SEARCH_AUTORUN_REL,
            {
                "rows": [
                    {"case": case, "commit_sha": self.commit, "passed": True, "producer": "runtime", "producer_signature": "sig", "raw_sql_included": False}
                    for case in ("render_no_click", "warehouse_prefill_no_autorun", "text_contains_no_autorun", "exact_query_id")
                ]
            },
        )
        self._write_json(
            root,
            COST_NO_AUTOLOAD_REL,
            {
                "rows": [
                    {
                        "id": "cost-overview",
                        "section": "Cost & Contract",
                        "workflow": "Cost Overview",
                        "commit_sha": self.commit,
                        "passed": True,
                        "autoload_violation_count": 0,
                        "evidence_query_count": 0,
                        "cost_workbench_query_count": 0,
                        "detail_query_count": 0,
                        "account_usage_count": 0,
                        "direct_sql_count": 0,
                        "producer": "runtime",
                        "producer_signature": "sig",
                        "raw_sql_included": False,
                    }
                ]
            },
        )
        self._write_json(
            root,
            ACCESS_CONTROL_RUNTIME_REL,
            {
                "rows": [
                    {
                        "row_id": "shell-no-session",
                        "commit_sha": self.commit,
                        "passed": True,
                        "shell_session_open_count": 0,
                        "active_session_probe_count": 0,
                        "pre_first_paint_session_open_count": 0,
                        "producer": "runtime",
                        "producer_signature": "sig",
                        "raw_sql_included": False,
                    }
                ]
            },
        )
        source_rows = [
            {
                "event_id": f"source-query-{section.lower().replace(' ', '-')}",
                "event_type": "query",
                "section": section,
                "workflow": "Overview",
                "execution_boundary": "decision_packet",
                "query_tier": "command_summary",
                "ttl_key": "decision_packet",
                "query_count_delta": 1,
                "session_open_count_delta": 0,
                "direct_sql_count_delta": 0,
                "account_usage_count_delta": 0,
                "metadata_probe_count_delta": 0,
                "before_first_paint": True,
                "account_usage_marker_present": False,
                "producer": "runtime_state",
                "producer_signature": "sig",
                "commit_sha": self.commit,
                "raw_sql_included": False,
            }
            for section in PRIMARY_SECTIONS
        ]
        source_rows.append(
            {
                "event_id": "source-summary-cost",
                "event_type": "section_summary_autoload",
                "section": "Cost & Contract",
                "workflow": "Cost Overview",
                "execution_boundary": "section_summary_autoload",
                "query_tier": "section_summary",
                "ttl_key": "section_summary_cost_current_summary",
                "query_count_delta": 1,
                "session_open_count_delta": 0,
                "direct_sql_count_delta": 0,
                "account_usage_count_delta": 0,
                "metadata_probe_count_delta": 0,
                "max_rows": 200,
                "row_count": 12,
                "before_first_paint": False,
                "after_first_paint": True,
                "user_initiated": True,
                "account_usage_marker_present": False,
                "evidence_loader_marker_present": False,
                "source_object_marker_present": False,
                "producer": "runtime_state",
                "producer_signature": "sig",
                "commit_sha": self.commit,
                "raw_sql_included": False,
            }
        )
        self._write_json(
            root,
            SOURCE_RUNTIME_EVENT_LEDGER_REL,
            {
                "producer": "full_app_runtime_validation",
                "producer_signature": "sig",
                "commit_sha": self.commit,
                "passed": True,
                "rows": source_rows,
                "event_count": len(source_rows),
                "first_paint_source_event_count": len(source_rows),
                "decision_packet_source_event_count": len(source_rows),
                "section_summary_autoload_source_event_count": 1,
                "raw_sql_included": False,
            },
        )

    def test_passing_runtime_artifacts_emit_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                artifacts = write_runtime_event_ledger_artifacts(root)

        self.assertTrue(artifacts[RUNTIME_EVENT_LEDGER_GATE_REL]["passed"], artifacts[RUNTIME_EVENT_LEDGER_GATE_REL])
        source_gate = artifacts["artifacts/launch_readiness/source_runtime_event_ledger_gate_results.json"]
        self.assertTrue(source_gate["passed"], source_gate)
        self.assertGreater(len(source_gate["proof_rows"]), 0)

    def test_missing_first_paint_row_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / FIRST_PAINT_REL).read_text(encoding="utf-8"))
            payload["rows"] = payload["rows"][1:]
            self._write_json(root, FIRST_PAINT_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("missing first-paint", json.dumps(results["failures"]))

    def test_extra_first_paint_session_open_fails_runtime_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / FIRST_PAINT_REL).read_text(encoding="utf-8"))
            payload["rows"][0]["session_open_count"] = 2
            self._write_json(root, FIRST_PAINT_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("session_open_count=1", json.dumps(results["failures"]))
        self.assertGreater(results["pre_first_paint_session_open_count"], 0)

    def test_route_action_query_violation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / ACTION_CLICK_REL).read_text(encoding="utf-8"))
            payload["actions"][0]["query_count"] = 1
            self._write_json(root, ACTION_CLICK_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["route_action_sql_violation_count"], 0)

    def test_missing_source_runtime_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            (root / SOURCE_RUNTIME_EVENT_LEDGER_REL).unlink()
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("source runtime event", json.dumps(results["failures"]))

    def test_source_runtime_markers_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"].append(
                {
                    "event_id": "source-admin-1",
                    "event_type": "explicit_admin_connection_test",
                    "section": "Settings/Admin Setup Health",
                    "workflow": "Setup Health",
                    "execution_boundary": "explicit_connection_test",
                    "session_open_count_delta": 1,
                    "active_session_probe_count_delta": 0,
                    "setup_live_validation_marker_present": True,
                    "producer": "runtime_state",
                    "producer_signature": "sig",
                    "commit_sha": self.commit,
                    "raw_sql_included": False,
                }
            )
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        source_rows = [
            row for row in results["rows"]
            if row["row_id"].startswith("source_runtime_event::source-admin-1")
        ]
        self.assertEqual(len(source_rows), 1)
        self.assertTrue(source_rows[0]["setup_live_validation_marker_present"])
        self.assertEqual(source_rows[0]["session_open_count_delta"], 1)

    def test_source_runtime_route_action_ids_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"].append(
                {
                    "event_id": "route-action-ids",
                    "event_type": "route_action",
                    "section": "Alert Center",
                    "workflow": "Overview",
                    "execution_boundary": "metadata_bounded",
                    "action_id": "view_all_priorities",
                    "stable_key": "view_all_priorities",
                    "rendered_action_id": "alert_center::overview::view_all_priorities",
                    "clicked_action_id": "alert_center::overview::view_all_priorities",
                    "producer": "runtime_state",
                    "producer_signature": "sig",
                    "commit_sha": self.commit,
                    "raw_sql_included": False,
                }
            )
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            source_payload = build_source_runtime_event_ledger_payload(
                payload["rows"],
                commit_sha=self.commit,
                root=root,
            )

        source_rows = [
            row for row in source_payload["rows"]
            if row["row_id"].startswith("source_runtime_event::route-action-ids")
        ]
        self.assertEqual(len(source_rows), 1)
        self.assertEqual(source_rows[0]["stable_key"], "view_all_priorities")
        self.assertEqual(source_rows[0]["rendered_action_id"], "alert_center::overview::view_all_priorities")
        self.assertEqual(source_rows[0]["clicked_action_id"], "alert_center::overview::view_all_priorities")

    def test_source_runtime_raw_sql_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"][0]["raw_sql_included"] = True
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("raw SQL", json.dumps(results["failures"]))

    def test_source_runtime_wrong_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"][0]["commit_sha"] = "old"
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("commit_sha mismatch", json.dumps(results["failures"]))

    def test_source_runtime_first_paint_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"].append(
                {
                    "event_id": "source-evidence-first-paint",
                    "event_type": "query",
                    "section": "Alert Center",
                    "workflow": "Overview",
                    "execution_boundary": "evidence_targeted",
                    "before_first_paint": True,
                    "query_count_delta": 1,
                    "producer": "runtime_state",
                    "producer_signature": "sig",
                    "commit_sha": self.commit,
                    "raw_sql_included": False,
                }
            )
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("loaded evidence before first paint", json.dumps(results["failures"]))

    def test_source_runtime_route_action_sql_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"].append(
                {
                    "event_id": "source-route-query",
                    "event_type": "route_action",
                    "section": "Alert Center",
                    "workflow": "Overview",
                    "execution_boundary": "metadata_bounded",
                    "route_action_marker_present": True,
                    "query_count_delta": 1,
                    "user_initiated": True,
                    "producer": "runtime_state",
                    "producer_signature": "sig",
                    "commit_sha": self.commit,
                    "raw_sql_included": False,
                }
            )
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("route action crossed", json.dumps(results["failures"]))

    def test_source_runtime_query_search_broad_without_click_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"].append(
                {
                    "event_id": "source-query-search-broad",
                    "event_type": "query",
                    "section": "Query Search",
                    "workflow": "No click",
                    "execution_boundary": "query_search_broad_explicit",
                    "query_count_delta": 1,
                    "user_initiated": False,
                    "producer": "runtime_state",
                    "producer_signature": "sig",
                    "commit_sha": self.commit,
                    "raw_sql_included": False,
                }
            )
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("broad path ran without explicit click", json.dumps(results["failures"]))

    def test_source_runtime_cost_evidence_before_click_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"].append(
                {
                    "event_id": "source-cost-evidence",
                    "event_type": "query",
                    "section": "Cost & Contract",
                    "workflow": "Cost Overview",
                    "execution_boundary": "evidence_targeted",
                    "ttl_key": "cost_targeted_evidence",
                    "before_first_paint": True,
                    "query_count_delta": 1,
                    "producer": "runtime_state",
                    "producer_signature": "sig",
                    "commit_sha": self.commit,
                    "raw_sql_included": False,
                }
            )
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("Cost evidence before explicit click", json.dumps(results["failures"]))

    def test_missing_summary_autoload_event_fails_source_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            payload["rows"] = [
                row
                for row in payload["rows"]
                if row.get("event_type") != "section_summary_autoload"
            ]
            payload["section_summary_autoload_source_event_count"] = 0
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("section_summary_autoload", json.dumps(results["failures"]))

    def test_summary_autoload_without_user_navigation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            summary = next(row for row in payload["rows"] if row.get("event_type") == "section_summary_autoload")
            summary["user_initiated"] = False
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("user-initiated navigation", json.dumps(results["failures"]))

    def test_summary_autoload_account_usage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            summary = next(row for row in payload["rows"] if row.get("event_type") == "section_summary_autoload")
            summary["account_usage_marker_present"] = True
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("summary autoload crossed Account Usage", json.dumps(results["failures"]))

    def test_summary_autoload_row_cap_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / SOURCE_RUNTIME_EVENT_LEDGER_REL).read_text(encoding="utf-8"))
            summary = next(row for row in payload["rows"] if row.get("event_type") == "section_summary_autoload")
            summary["max_rows"] = 201
            self._write_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL, payload)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                results = build_runtime_event_ledger_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("max_rows=201", json.dumps(results["failures"]))


if __name__ == "__main__":
    unittest.main()
