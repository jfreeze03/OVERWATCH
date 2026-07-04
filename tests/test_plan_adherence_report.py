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
            self._write_json(
                root,
                "artifacts/release_candidate/release_notes.json",
                {"validation_commands": ["python -m unittest tests.test_plan_adherence_report"]},
            )
            changed = {
                *[item for phase in PHASES for item in phase.files_changed],
                *[item for phase in PHASES for item in phase.tests_added_or_updated],
            }
            with (
                patch("tools.contracts.plan_adherence_report._git_commit", return_value=self.commit),
                patch("tools.contracts.plan_adherence_report._git_changed_files", return_value=changed),
            ):
                artifacts = write_plan_adherence_report(root)

        report = artifacts[PLAN_ADHERENCE_REPORT_REL]
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["phase_count"], len(PHASES))
        self.assertEqual(report["failure_count"], 0)
        self.assertTrue(all(row["raw_sql_included"] is False for row in report["rows"]))
        self.assertTrue(all("actual_changed_files" in row for row in report["rows"]))
        self.assertTrue(all("actual_tests_added_or_updated" in row for row in report["rows"]))
        self.assertTrue(all("commands_run" in row for row in report["rows"]))
        self.assertTrue(all(row["commands_run"] for row in report["rows"]))

    def test_missing_phase_artifact_blocks_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_phase_artifacts(root)
            missing = PHASES[0].artifacts[0]
            (root / missing).unlink()
            with (
                patch("tools.contracts.plan_adherence_report._git_commit", return_value=self.commit),
                patch("tools.contracts.plan_adherence_report._git_changed_files", return_value=set()),
            ):
                report = build_plan_adherence_report(root)

        self.assertFalse(report["passed"])
        self.assertEqual(report["failure_count"], 1)
        self.assertIn(missing, report["failures"][0]["blockers"][0])

    def test_false_deployable_summary_blocks_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_phase_artifacts(root)
            (root / PHASES[0].artifacts[0]).unlink()
            self._write_json(
                root,
                "artifacts/release_candidate/release_candidate_summary.json",
                {"production_deployable": True, "a_grade_ready": True},
            )
            with (
                patch("tools.contracts.plan_adherence_report._git_commit", return_value=self.commit),
                patch("tools.contracts.plan_adherence_report._git_changed_files", return_value=set()),
            ):
                report = build_plan_adherence_report(root)

        self.assertFalse(report["passed"])
        self.assertTrue(report["production_deployable_blocked_by_plan"])
        reasons = json.dumps(report["failures"])
        self.assertIn("production_deployable=true", reasons)
        self.assertIn("a_grade_ready=true", reasons)

    def test_unrecorded_deviation_summary_blocks_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_phase_artifacts(root)
            self._write_json(
                root,
                "artifacts/release_candidate/release_candidate_summary.json",
                {"unrecorded_deviation_count": 1},
            )
            changed = {
                *[item for phase in PHASES for item in phase.files_changed],
                *[item for phase in PHASES for item in phase.tests_added_or_updated],
            }
            with (
                patch("tools.contracts.plan_adherence_report._git_commit", return_value=self.commit),
                patch("tools.contracts.plan_adherence_report._git_changed_files", return_value=changed),
            ):
                report = build_plan_adherence_report(root)

        self.assertFalse(report["passed"])
        self.assertIn("unrecorded deviations", json.dumps(report["failures"]))


if __name__ == "__main__":
    unittest.main()
