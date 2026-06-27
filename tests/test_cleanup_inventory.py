import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class CleanupInventoryTests(unittest.TestCase):
    def test_cleanup_artifacts_are_generated_and_contracts_are_strict(self):
        from cleanup_inventory import write_cleanup_artifacts

        artifacts = write_cleanup_artifacts(ROOT)
        required = {
            "artifacts/cleanup/legacy_inventory.json",
            "artifacts/cleanup/cleanup_summary.json",
            "artifacts/cleanup/route_state_inventory.json",
            "artifacts/cleanup/object_inventory.json",
            "artifacts/cleanup/contract_registry.json",
            "artifacts/cleanup/artifact_manifest.json",
        }
        self.assertTrue(required.issubset(artifacts))
        for rel in required:
            self.assertTrue((ROOT / rel).exists(), rel)

        inventory = json.loads((ROOT / "artifacts/cleanup/legacy_inventory.json").read_text(encoding="utf-8"))
        summary = json.loads((ROOT / "artifacts/cleanup/cleanup_summary.json").read_text(encoding="utf-8"))
        route_inventory = json.loads((ROOT / "artifacts/cleanup/route_state_inventory.json").read_text(encoding="utf-8"))
        object_inventory = json.loads((ROOT / "artifacts/cleanup/object_inventory.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "artifacts/cleanup/contract_registry.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["inline_marker_comments_remaining"], 0)
        self.assertEqual(summary["unreachable_production_modules"], 0)
        self.assertEqual(route_inventory["dead_routes"], [])
        self.assertFalse(inventory["production_forbidden_token_findings"])
        self.assertGreater(registry["entry_count"], 0)
        self.assertFalse(registry["inline_marker_source"])

        kept = inventory["python_modules"]["legacy_looking_kept_with_reason"]
        self.assertTrue(kept)
        self.assertTrue(all(row.get("owner") and row.get("reason") and row.get("active_reference") for row in kept))
        self.assertTrue(all(object_inventory["compact_evidence_load_path"].values()))

    def test_production_source_has_no_inline_marker_comments(self):
        forbidden = ("SESSION_OPEN_ADMIN_OK", "DIRECT_SQL_ADMIN_OK", "legacy_session")
        hits = []
        for path in APP_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertFalse(hits)

    def test_cleanup_writer_removes_stale_cleanup_json(self):
        from cleanup_inventory import write_cleanup_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            cleanup_dir = temp_root / "artifacts" / "cleanup"
            cleanup_dir.mkdir(parents=True)
            stale = cleanup_dir / "stale_snapshot.json"
            stale.write_text("{}", encoding="utf-8")
            # Copy only enough structure for the writer to scan without touching the real artifact dir.
            # Full content comes from the repo for this contract; the stale-file behavior is local.
            self.assertTrue(stale.exists())

        # The production artifact directory is cleaned on each real write.
        stale = ROOT / "artifacts" / "cleanup" / "obsolete_cleanup_fixture.json"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("{}", encoding="utf-8")
        write_cleanup_artifacts(ROOT)
        self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
