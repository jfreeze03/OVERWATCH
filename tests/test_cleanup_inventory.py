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
    def test_ci_only_contract_modules_are_outside_runtime_package(self):
        forbidden_modules = {
            "cleanup_inventory.py",
            "direct_sql_contract.py",
            "session_open_contract.py",
            "sql_performance_lint.py",
        }
        runtime_hits = [path.name for path in APP_ROOT.glob("*.py") if path.name in forbidden_modules]
        self.assertFalse(runtime_hits)

        import_hits = []
        forbidden_imports = (
            "cleanup_inventory",
            "direct_sql_contract",
            "session_open_contract",
            "sql_performance_lint",
            "tools.contracts",
        )
        for path in APP_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden_imports:
                if token in text:
                    import_hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertFalse(import_hits)

    def test_cleanup_artifacts_are_generated_and_contracts_are_strict(self):
        from tools.contracts.cleanup_inventory import write_cleanup_artifacts

        artifacts = write_cleanup_artifacts(ROOT)
        required = {
            "artifacts/cleanup/legacy_inventory.json",
            "artifacts/cleanup/module_inventory.json",
            "artifacts/cleanup/retained_runtime_modules.json",
            "artifacts/cleanup/deleted_modules.json",
            "artifacts/cleanup/cleanup_summary.json",
            "artifacts/cleanup/deletion_candidates.json",
            "artifacts/cleanup/deleted_routes.json",
            "artifacts/cleanup/retained_routes.json",
            "artifacts/cleanup/route_state_inventory.json",
            "artifacts/cleanup/object_inventory.json",
            "artifacts/cleanup/sql_object_inventory.json",
            "artifacts/cleanup/drop_plan.json",
            "artifacts/cleanup/deleted_sql_objects.json",
            "artifacts/cleanup/sql_drop_plan.sql",
            "artifacts/cleanup/query_path_inventory.json",
            "artifacts/cleanup/forbidden_token_scan.json",
            "artifacts/cleanup/test_inventory.json",
            "artifacts/cleanup/test_reduction_summary.json",
            "artifacts/cleanup/deleted_tests.json",
            "artifacts/cleanup/deleted_artifacts.json",
            "artifacts/cleanup/contract_registry.json",
            "artifacts/cleanup/artifact_manifest.json",
        }
        self.assertTrue(required.issubset(artifacts))
        for rel in required:
            self.assertTrue((ROOT / rel).exists(), rel)

        inventory = json.loads((ROOT / "artifacts/cleanup/legacy_inventory.json").read_text(encoding="utf-8"))
        summary = json.loads((ROOT / "artifacts/cleanup/cleanup_summary.json").read_text(encoding="utf-8"))
        route_inventory = json.loads((ROOT / "artifacts/cleanup/route_state_inventory.json").read_text(encoding="utf-8"))
        deleted_routes = json.loads((ROOT / "artifacts/cleanup/deleted_routes.json").read_text(encoding="utf-8"))
        retained_routes = json.loads((ROOT / "artifacts/cleanup/retained_routes.json").read_text(encoding="utf-8"))
        object_inventory = json.loads((ROOT / "artifacts/cleanup/object_inventory.json").read_text(encoding="utf-8"))
        deleted_sql = json.loads((ROOT / "artifacts/cleanup/deleted_sql_objects.json").read_text(encoding="utf-8"))
        query_paths = json.loads((ROOT / "artifacts/cleanup/query_path_inventory.json").read_text(encoding="utf-8"))
        module_inventory = json.loads((ROOT / "artifacts/cleanup/module_inventory.json").read_text(encoding="utf-8"))
        retained_modules = json.loads((ROOT / "artifacts/cleanup/retained_runtime_modules.json").read_text(encoding="utf-8"))
        deleted_modules = json.loads((ROOT / "artifacts/cleanup/deleted_modules.json").read_text(encoding="utf-8"))
        deletion_candidates = json.loads((ROOT / "artifacts/cleanup/deletion_candidates.json").read_text(encoding="utf-8"))
        drop_plan = json.loads((ROOT / "artifacts/cleanup/drop_plan.json").read_text(encoding="utf-8"))
        forbidden_scan = json.loads((ROOT / "artifacts/cleanup/forbidden_token_scan.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "artifacts/cleanup/contract_registry.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "artifacts/cleanup/artifact_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["inline_marker_comments_remaining"], 0)
        self.assertEqual(summary["unreachable_production_modules"], 0)
        self.assertEqual(summary["deletion_candidate_count"], 0)
        self.assertEqual(summary["retained_generic_reason_count"], 0)
        self.assertEqual(summary["unknown_sql_object_count"], 0)
        self.assertEqual(summary["stale_generated_artifact_count"], 0)
        release_rows = [
            row for row in inventory["artifacts"]["artifacts"]
            if row["path"].startswith("artifacts/release_candidate/")
        ]
        self.assertTrue(release_rows)
        self.assertTrue(all(row["category"] == "CI proof artifact" for row in release_rows))
        self.assertEqual(route_inventory["dead_routes"], [])
        self.assertEqual(deleted_routes["dead_routes"], [])
        self.assertEqual(retained_routes["dead_route_count"], 0)
        self.assertFalse(inventory["production_forbidden_token_findings"])
        self.assertEqual(deletion_candidates["candidate_count"], 0)
        self.assertEqual(forbidden_scan["blocked_count"], 0)
        self.assertGreater(registry["entry_count"], 0)
        self.assertFalse(registry["inline_marker_source"])
        self.assertIn("drop_plan", drop_plan)
        self.assertIn("artifacts/cleanup/deletion_candidates.json", manifest["files"])
        self.assertIn("artifacts/cleanup/module_inventory.json", manifest["files"])
        self.assertIn("artifacts/cleanup/deleted_routes.json", manifest["files"])
        self.assertIn("artifacts/cleanup/sql_drop_plan.sql", manifest["files"])
        self.assertFalse(retained_modules["broad_prefix_rules_allowed"])
        self.assertIn("deleted_modules", deleted_modules)
        self.assertEqual(deleted_sql["active_drop_collision_count"], 0)
        self.assertFalse(query_paths["account_usage_normal_evidence_allowed"])
        self.assertTrue((ROOT / "artifacts/cleanup/sql_drop_plan.sql").read_text(encoding="utf-8").startswith("-- OVERWATCH"))
        cleanup_source = (ROOT / "tools" / "contracts" / "cleanup_inventory.py").read_text(encoding="utf-8")
        self.assertNotIn("ACTIVE_ADMIN_MODULE_PREFIXES", cleanup_source)
        self.assertNotIn("ACTIVE_CONTRACT_MODULE_PREFIXES", cleanup_source)

        kept = inventory["python_modules"]["legacy_looking_kept_with_reason"]
        self.assertTrue(kept)
        generic = ("compatibility", "legacy retained", "route/admin/test inventory", "historical", "just in case")
        for row in kept:
            self.assertIn(row.get("classification"), {
                "active_primary_surface",
                "active_admin_setup_surface",
                "active_deployment_bootstrap",
                "active_contract_test",
                "active_contract_runtime",
                "active_compact_evidence",
                "deleted",
            })
            self.assertTrue(row.get("owner"), row)
            self.assertTrue(row.get("current_route_or_test"), row)
            self.assertTrue(row.get("reason"), row)
            self.assertTrue(row.get("expiration_or_review_note"), row)
            self.assertTrue(row.get("deletion_blocker"), row)
            reason_text = " ".join(str(row.get(key, "")) for key in ("reason", "current_route_or_test", "deletion_blocker")).lower()
            self.assertFalse(any(token in reason_text for token in generic), row)
        for route in route_inventory["routes"]:
            if route["category"] == "active_alias_route":
                self.assertTrue(route["owner"], route)
                self.assertTrue(route["reason"], route)
                self.assertTrue(route["active_source_button_or_deep_link"], route)
                self.assertTrue(route["expiration_or_review_note"], route)
        for entry in [*registry["direct_sql_allowlist"], *registry["session_open_allowlist"]]:
            self.assertTrue(entry.get("expiration_or_review_note"), entry)
            self.assertTrue(entry.get("active_ui_action_or_admin_route"), entry)
            self.assertIn("deletion_candidate", entry)
        for entry in retained_modules["retained_modules"]:
            self.assertTrue(entry.get("module"), entry)
            self.assertIn(entry.get("category"), {"active_admin_setup_surface", "active_contract_runtime"}, entry)
            self.assertTrue(entry.get("owning_section_or_admin_route"), entry)
            self.assertTrue(entry.get("active_button_key_or_route_key"), entry)
            self.assertTrue(entry.get("owner"), entry)
            self.assertTrue(entry.get("reason"), entry)
            self.assertTrue(entry.get("expiration_or_review_note"), entry)
            self.assertTrue(entry.get("runtime_budget_context"), entry)
        retained_names = {entry["module"] for entry in retained_modules["retained_modules"]}
        self.assertIn("sections.summary_board_contract", retained_names)
        self.assertIn("utils.billing_reconciliation", retained_names)
        self.assertIn("utils.shared_metrics_billing", retained_names)
        for row in module_inventory["retained_legacy_looking_modules"]:
            if row["classification"] != "active_primary_surface":
                self.assertIn(row["module"], retained_names, row)
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
        from tools.contracts.cleanup_inventory import write_cleanup_artifacts

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
