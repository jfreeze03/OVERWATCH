from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DeleteFirstCleanupTests(unittest.TestCase):
    def test_old_surface_module_is_delete_candidate_with_plan(self):
        from tools.contracts.delete_first_cleanup import build_delete_first_inventory

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sections = root / ".overwatch_final" / "sections"
            sections.mkdir(parents=True)
            (sections / "old_launchpad.py").write_text("TITLE = 'launchpad'\n", encoding="utf-8")

            inventory = build_delete_first_inventory(root)

        row = inventory["rows"][0]
        self.assertEqual(row["classification"], "delete_obsolete")
        self.assertTrue(row["delete_plan"])
        self.assertTrue(inventory["passed"])

    def test_unknown_sql_path_blocks_gate(self):
        from tools.contracts.delete_first_cleanup import build_delete_first_inventory, evaluate_delete_first_cleanup_gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql_dir = root / "snowflake"
            sql_dir.mkdir()
            (sql_dir / "mystery.sql").write_text("select 1;", encoding="utf-8")

            inventory = build_delete_first_inventory(root)
            gate = evaluate_delete_first_cleanup_gate(inventory)

        self.assertFalse(gate["passed"])
        self.assertIn("unclassified", gate["failures"][0]["reason"])

    def test_retired_query_workbench_module_blocks_gate(self):
        from tools.contracts.delete_first_cleanup import build_delete_first_inventory, evaluate_delete_first_cleanup_gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sections = root / ".overwatch_final" / "sections"
            sections.mkdir(parents=True)
            (sections / "query_workbench.py").write_text("# retired module\n", encoding="utf-8")

            inventory = build_delete_first_inventory(root)
            gate = evaluate_delete_first_cleanup_gate(inventory)

        self.assertFalse(gate["passed"])
        self.assertTrue(
            any("retired query_workbench" in failure["reason"] for failure in gate["failures"])
        )

    def test_query_root_cause_module_is_governed_explicit_action(self):
        from tools.contracts.delete_first_cleanup import build_delete_first_inventory

        inventory = build_delete_first_inventory(ROOT)
        rows = {row["path"]: row for row in inventory["rows"]}
        row = rows[".overwatch_final/sections/query_investigation_root_cause.py"]

        self.assertEqual(row["classification"], "keep_runtime")
        self.assertEqual(row["owner"], "Workload Operations")
        self.assertIn("explicit_action", row["runtime_path"])
        self.assertTrue(row["daily_safe"])


if __name__ == "__main__":
    unittest.main()
