from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.contracts.plan_adherence_report import (
    PHASES,
    PLAN_ADHERENCE_REPORT_REL,
    build_plan_adherence_report,
    write_plan_adherence_report,
)


class PlanAdherenceReportTests(unittest.TestCase):
    commit = "abc123"

    def _write_json(self, root: Path, rel: str, payload: object) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_phase_artifacts(self, root: Path) -> None:
        for phase in PHASES:
            for rel in phase.artifacts:
                self._write_json(
                    root,
                    rel,
                    {
                        "source": Path(rel).stem,
                        "producer": Path(rel).stem,
                        "producer_signature": "sig",
                        "commit_sha": self.commit,
                        "passed": True,
                        "failure_count": 0,
                        "rows": [{"row_id": Path(rel).stem, "passed": True}],
                        "raw_sql_included": False,
                    },
                )

    def test_plan_adherence_report_passes_when_all_phase_artifacts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_phase_artifacts(root)
            with patch("tools.contracts.plan_adherence_report._git_commit", return_value=self.commit):
                artifacts = write_plan_adherence_report(root)

        report = artifacts[PLAN_ADHERENCE_REPORT_REL]
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["phase_count"], len(PHASES))
        self.assertEqual(report["failure_count"], 0)
        self.assertTrue(all(row["raw_sql_included"] is False for row in report["rows"]))

    def test_missing_phase_artifact_blocks_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_phase_artifacts(root)
            missing = PHASES[0].artifacts[0]
            (root / missing).unlink()
            with patch("tools.contracts.plan_adherence_report._git_commit", return_value=self.commit):
                report = build_plan_adherence_report(root)

        self.assertFalse(report["passed"])
        self.assertEqual(report["failure_count"], 1)
        self.assertIn(missing, report["failures"][0]["blockers"][0])


if __name__ == "__main__":
    unittest.main()
