from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.contracts.export_case_parity import (
    CASE_PAYLOAD_RESULTS_REL,
    DOWNLOAD_RESULTS_REL,
    EXPORT_CASE_PARITY_GATE_REL,
    EXPORT_RESULTS_REL,
    build_export_case_parity_results,
    write_export_case_parity_artifacts,
)


class ExportCaseParityTests(unittest.TestCase):
    commit = "abc123"

    def _write_json(self, root: Path, rel: str, payload: object) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_payload(self, root: Path, rel: str, text: str) -> tuple[str, int]:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size

    def _base_row(self, payload_file: str, sha: str, size: int, *, content_type: str = "text/csv") -> dict[str, object]:
        return {
            "payload_file": payload_file,
            "sha256": sha,
            "size_bytes": size,
            "content_type": content_type,
            "visible_row_count": 1,
            "parsed_row_count": 1,
            "commit_sha": self.commit,
            "producer": "runtime",
            "producer_signature": "sig",
            "passed": True,
            "raw_sql_included": False,
            "rendered_action_id": "rendered-action",
            "clicked_action_id": "clicked-action",
            "section": "Executive Landing",
            "workflow": "Overview",
        }

    def _seed_passing(self, root: Path) -> None:
        export_rel = "artifacts/full_app_validation/generated_exports/export.csv"
        download_rel = "artifacts/full_app_validation/generated_exports/download.csv"
        case_rel = "artifacts/full_app_validation/generated_exports/case.json"
        export_sha, export_size = self._write_payload(root, export_rel, "Metric,Value\nSpend,10\n")
        download_sha, download_size = self._write_payload(root, download_rel, "Metric,Value\nSpend,10\n")
        case_payload = {
            "section": "Executive Landing",
            "workflow": "Overview",
            "scope": "ALFA",
            "target": "overview",
            "freshness": "Current",
            "source_family": "executive",
            "summary": "Summary",
            "row_count": 1,
            "visible_row_count": 1,
            "recommended_action": "Review",
        }
        case_sha, case_size = self._write_payload(root, case_rel, json.dumps(case_payload))
        self._write_json(root, EXPORT_RESULTS_REL, [self._base_row(export_rel, export_sha, export_size)])
        self._write_json(root, DOWNLOAD_RESULTS_REL, {"rows": [self._base_row(download_rel, download_sha, download_size)]})
        self._write_json(
            root,
            CASE_PAYLOAD_RESULTS_REL,
            [self._base_row(case_rel, case_sha, case_size, content_type="application/json")],
        )

    def test_passing_file_backed_payloads_emit_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            with patch("tools.contracts.export_case_parity._git_commit", return_value=self.commit):
                artifacts = write_export_case_parity_artifacts(root)

        self.assertTrue(artifacts[EXPORT_CASE_PARITY_GATE_REL]["passed"], artifacts[EXPORT_CASE_PARITY_GATE_REL])

    def test_visible_row_count_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            rows = json.loads((root / EXPORT_RESULTS_REL).read_text(encoding="utf-8"))
            rows[0]["visible_row_count"] = 2
            self._write_json(root, EXPORT_RESULTS_REL, rows)
            with patch("tools.contracts.export_case_parity._git_commit", return_value=self.commit):
                results = build_export_case_parity_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("visible_row_count mismatch", json.dumps(results["failures"]))

    def test_default_export_user_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_passing(root)
            rel = "artifacts/full_app_validation/generated_exports/export.csv"
            sha, size = self._write_payload(root, rel, "USER_ID,Value\n123,10\n")
            rows = json.loads((root / EXPORT_RESULTS_REL).read_text(encoding="utf-8"))
            rows[0].update({"sha256": sha, "size_bytes": size})
            self._write_json(root, EXPORT_RESULTS_REL, rows)
            with patch("tools.contracts.export_case_parity._git_commit", return_value=self.commit):
                results = build_export_case_parity_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("USER_ID", json.dumps(results["failures"]))


if __name__ == "__main__":
    unittest.main()
