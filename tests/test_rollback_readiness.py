from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RollbackReadinessTests(unittest.TestCase):
    def test_current_repo_rollback_readiness_passes(self):
        from tools.contracts.rollback_readiness import (
            build_rollback_readiness_results,
            evaluate_rollback_readiness_gate,
        )

        results = build_rollback_readiness_results(ROOT)
        gate = evaluate_rollback_readiness_gate(results)

        self.assertTrue(results["passed"], results)
        self.assertTrue(gate["passed"], gate)
        self.assertTrue(gate["rollback_ready"], gate)
        self.assertGreater(results["drop_target_count"], 0)
        self.assertEqual(results["broad_drop_count"], 0)
        self.assertTrue(results["destructive_mode_required"])

    def test_broad_drop_fails(self):
        from tools.contracts.rollback_readiness import build_rollback_readiness_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "snowflake" / "OVERWATCH_MART_DROP.sql",
                """
-- OVERWATCH_DESTRUCTIVE_MODE=TRUE
DROP DATABASE IF EXISTS DBA_MAINT_DB;
DROP TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF;
""",
            )
            _write(
                root / "docs" / "OVERWATCH_RECOVERY_RUNBOOK.md",
                "Rollback idempotent OVERWATCH_SCHEMA_MIGRATION",
            )
            results = build_rollback_readiness_results(root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["broad_drop_count"], 0)

    def test_audit_drop_without_destructive_marker_fails(self):
        from tools.contracts.rollback_readiness import build_rollback_readiness_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "snowflake" / "OVERWATCH_MART_DROP.sql",
                "DROP TABLE IF EXISTS OVERWATCH_ACTION_EVIDENCE;",
            )
            _write(
                root / "docs" / "OVERWATCH_RECOVERY_RUNBOOK.md",
                "Rollback idempotent OVERWATCH_SCHEMA_MIGRATION",
            )
            results = build_rollback_readiness_results(root)

        self.assertFalse(results["passed"])
        checks = {row["check"]: row for row in results["failures"]}
        self.assertIn("destructive_mode_required", checks)
        self.assertIn("protected_history_requires_destructive_mode", checks)


if __name__ == "__main__":
    unittest.main()
