import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EncodingHygieneTests(unittest.TestCase):
    def test_repo_encoding_hygiene_artifact_passes(self):
        from tools.contracts.encoding_hygiene import ROOT_ARTIFACT, write_encoding_hygiene_artifacts

        artifacts = write_encoding_hygiene_artifacts(ROOT)
        payload = artifacts[ROOT_ARTIFACT]
        self.assertTrue(payload["passed"], payload)
        self.assertEqual(payload["blocked_count"], 0, payload)
        self.assertGreater(payload["scanned_file_count"], 0)
        self.assertTrue((ROOT / ROOT_ARTIFACT).exists())
        written = json.loads((ROOT / ROOT_ARTIFACT).read_text(encoding="utf-8"))
        self.assertFalse(written["raw_sql_included"])

    def test_literal_mojibake_source_fails_but_escaped_fixture_passes(self):
        from tools.contracts.encoding_hygiene import evaluate_encoding_hygiene

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "bad.py").write_text("BROKEN = '" + "\u00e2\u20ac\u2122" + "'\n", encoding="utf-8")
            payload = evaluate_encoding_hygiene(root)
            self.assertFalse(payload["passed"], payload)
            self.assertTrue(any(row["code"].startswith("MOJIBAKE_") for row in payload["findings"]))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "ok.py").write_text("BROKEN = '\\\\u00e2\\\\u20ac\\\\u2122'\n", encoding="utf-8")
            payload = evaluate_encoding_hygiene(root)
            self.assertTrue(payload["passed"], payload)

    def test_sql_bom_and_replacement_character_fail(self):
        from tools.contracts.encoding_hygiene import evaluate_encoding_hygiene

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql_dir = root / "snowflake"
            sql_dir.mkdir()
            (sql_dir / "bom.sql").write_bytes(b"\xef\xbb\xbfSELECT 1;\n")
            (sql_dir / "replacement.sql").write_text("SELECT '" + "\ufffd" + "';\n", encoding="utf-8")
            payload = evaluate_encoding_hygiene(root)
            codes = {row["code"] for row in payload["findings"]}
            self.assertFalse(payload["passed"], payload)
            self.assertIn("UTF8_BOM", codes)
            self.assertIn("REPLACEMENT_CHARACTER", codes)

    def test_generated_artifact_with_mojibake_fails(self):
        from tools.contracts.encoding_hygiene import evaluate_encoding_hygiene

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "artifacts" / "full_app_validation"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "bad.json").write_text('{"label":"' + "\u00e2\u20ac\u2122" + '"}\n', encoding="utf-8")
            payload = evaluate_encoding_hygiene(root)
            self.assertFalse(payload["passed"], payload)
            self.assertTrue(any(row["file"] == "artifacts/full_app_validation/bad.json" for row in payload["findings"]))

    def test_manual_snowflake_run_transcripts_are_not_release_encoding_targets(self):
        from tools.contracts.encoding_hygiene import evaluate_encoding_hygiene

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manual_dir = root / "artifacts" / "snowflake_validation" / "manual_runs"
            manual_dir.mkdir(parents=True)
            (manual_dir / "local_cli.out.txt").write_bytes(b"\xff\xfeS\x00K\x00I\x00P\x00P\x00E\x00D\x00")

            payload = evaluate_encoding_hygiene(root)

        self.assertTrue(payload["passed"], payload)
        self.assertFalse(payload["findings"])

    def test_encoding_hygiene_outputs_do_not_scan_themselves(self):
        from tools.contracts.encoding_hygiene import LAUNCH_ARTIFACT, ROOT_ARTIFACT, evaluate_encoding_hygiene

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root_artifact = root / ROOT_ARTIFACT
            launch_artifact = root / LAUNCH_ARTIFACT
            root_artifact.parent.mkdir(parents=True, exist_ok=True)
            launch_artifact.parent.mkdir(parents=True, exist_ok=True)
            root_artifact.write_text('{"label":"' + "\u00e2\u20ac\u2122" + '"}\n', encoding="utf-8")
            launch_artifact.write_text('{"label":"' + "\u00e2\u20ac\u2122" + '"}\n', encoding="utf-8")

            payload = evaluate_encoding_hygiene(root)

        self.assertTrue(payload["passed"], payload)
        self.assertFalse(payload["findings"])


if __name__ == "__main__":
    unittest.main()
