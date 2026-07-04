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
    build_runtime_event_ledger_results,
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

    def test_passing_runtime_artifacts_emit_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            with patch("tools.contracts.runtime_event_ledger._git_commit", return_value=self.commit):
                artifacts = write_runtime_event_ledger_artifacts(root)

        self.assertTrue(artifacts[RUNTIME_EVENT_LEDGER_GATE_REL]["passed"], artifacts[RUNTIME_EVENT_LEDGER_GATE_REL])

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


if __name__ == "__main__":
    unittest.main()
