from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.contracts.route_action_replay import (
    ACTION_CLICK_REL,
    COST_NO_AUTOLOAD_REL,
    FIRST_PAINT_REL,
    PRIMARY_SECTIONS,
    QUERY_SEARCH_AUTORUN_REL,
    ROUTE_ACTION_REPLAY_GATE_REL,
    SETTINGS_ACTION_REL,
    build_route_action_replay_results,
    write_route_action_replay_artifacts,
)


class RouteActionReplayTests(unittest.TestCase):
    commit = "abc123"

    def _write_json(self, root: Path, rel: str, payload: object) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_passing(self, root: Path) -> None:
        self._write_json(
            root,
            FIRST_PAINT_REL,
            {
                "rows": [
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
                    }
                    for section in PRIMARY_SECTIONS
                ]
            },
        )
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
                        "stable_key": "review_credential_expirations",
                        "commit_sha": self.commit,
                        "passed": True,
                        "query_count": 0,
                        "session_open_count": 0,
                        "direct_sql_count": 0,
                        "account_usage_count": 0,
                    },
                    {
                        "section": "Security Monitoring",
                        "workflow": "Credential Expirations",
                        "action_area": "evidence_action",
                        "clicked": True,
                        "stable_key": "load_security_evidence",
                        "commit_sha": self.commit,
                        "passed": True,
                        "query_count": 1,
                        "session_open_count": 0,
                        "direct_sql_count": 0,
                        "account_usage_count": 0,
                    },
                ]
            },
        )
        self._write_json(
            root,
            QUERY_SEARCH_AUTORUN_REL,
            {
                "rows": [
                    {"case": case, "commit_sha": self.commit, "passed": True}
                    for case in ("render_no_click", "warehouse_prefill_no_autorun", "text_contains_no_autorun", "exact_query_id")
                ]
            },
        )
        self._write_json(
            root,
            COST_NO_AUTOLOAD_REL,
            {"rows": [{"id": "cost", "commit_sha": self.commit, "passed": True, "autoload_violation_count": 0}]},
        )
        self._write_json(root, SETTINGS_ACTION_REL, {"rows": [{"clicked": True}]})

    def test_passing_replay_artifacts_emit_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            with patch("tools.contracts.route_action_replay._git_commit", return_value=self.commit):
                artifacts = write_route_action_replay_artifacts(root)

        self.assertTrue(artifacts[ROUTE_ACTION_REPLAY_GATE_REL]["passed"], artifacts[ROUTE_ACTION_REPLAY_GATE_REL])

    def test_route_action_sql_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            payload = json.loads((root / ACTION_CLICK_REL).read_text(encoding="utf-8"))
            payload["actions"][0]["direct_sql_count"] = 1
            self._write_json(root, ACTION_CLICK_REL, payload)
            with patch("tools.contracts.route_action_replay._git_commit", return_value=self.commit):
                results = build_route_action_replay_results(root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["route_action_sql_violation_count"], 0)


if __name__ == "__main__":
    unittest.main()
