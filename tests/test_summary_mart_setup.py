from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from tools.contracts.summary_mart_setup import (
    EXPECTED_SUMMARY_MARTS,
    SUMMARY_MART_SETUP_GATE_REL,
    SUMMARY_MART_SQL_REL,
    build_summary_mart_setup_results,
    write_summary_mart_setup_artifacts,
)


class SummaryMartSetupTests(unittest.TestCase):
    def _write_minimal_sql(self, root: Path, *, omit_object: str = "", select_star: bool = False) -> None:
        chunks: list[str] = []
        for spec in EXPECTED_SUMMARY_MARTS:
            object_name = str(spec["object_name"])
            if object_name == omit_object:
                continue
            columns = ",\n  ".join(f"{column} STRING" for column in spec["required_columns"])
            chunks.append(
                f"CREATE TABLE IF NOT EXISTS {object_name} (\n"
                f"  {columns},\n"
                f"  SOURCE_FAMILY STRING DEFAULT '{spec['source_family']}'\n"
                ");"
            )
        if select_star:
            chunks.append("SELECT * FROM BAD_SOURCE;")
        path = root / SUMMARY_MART_SQL_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n\n".join(chunks), encoding="utf-8")

    def test_repo_summary_mart_sql_passes(self) -> None:
        results = build_summary_mart_setup_results(Path.cwd())

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertEqual(results["summary_mart_count"], len(EXPECTED_SUMMARY_MARTS))

    def test_missing_object_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_sql(root, omit_object="OVERWATCH_CORTEX_DAILY_USAGE")

            results = build_summary_mart_setup_results(root)

        self.assertFalse(results["passed"])
        self.assertIn("OVERWATCH_CORTEX_DAILY_USAGE", str(results["failures"]))

    def test_select_star_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_sql(root, select_star=True)

            results = build_summary_mart_setup_results(root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["select_star_count"], 0)

    def test_written_gate_has_proof_rows_and_no_raw_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_sql(root)

            artifacts = write_summary_mart_setup_artifacts(root)

        gate = artifacts[SUMMARY_MART_SETUP_GATE_REL]
        self.assertTrue(gate["passed"], gate.get("failures"))
        self.assertEqual(gate["proof_row_count"], len(EXPECTED_SUMMARY_MARTS))
        self.assertFalse(gate["raw_sql_included"])
        self.assertNotIn("CREATE TABLE", str(gate))


if __name__ == "__main__":
    unittest.main()
