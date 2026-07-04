from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class QueryBoundaryLintTests(unittest.TestCase):
    def test_critical_run_query_requires_query_boundary(self):
        from tools.contracts.query_boundary_lint import lint_query_boundary_paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / ".overwatch_final" / "sections" / "query_search.py"
            target.parent.mkdir(parents=True)
            target.write_text(
                "from utils.query import run_query\n"
                "def ok():\n"
                "    return run_query('select 1', query_boundary='query_search')\n"
                "def bad():\n"
                "    return run_query('select 2')\n",
                encoding="utf-8",
            )

            results = lint_query_boundary_paths(root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["missing_query_boundary_count"], 1)

    def test_all_critical_boundaries_pass(self):
        from tools.contracts.query_boundary_lint import lint_query_boundary_paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / ".overwatch_final" / "sections" / "query_search.py"
            target.parent.mkdir(parents=True)
            target.write_text(
                "from utils.query import run_query\n"
                "def ok():\n"
                "    return run_query('select 1', query_boundary='query_search')\n",
                encoding="utf-8",
            )

            results = lint_query_boundary_paths(root)

        self.assertTrue(results["passed"], results.get("failures"))

    def test_aliased_run_query_requires_query_boundary(self):
        from tools.contracts.query_boundary_lint import lint_query_boundary_paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / ".overwatch_final" / "sections" / "query_search.py"
            target.parent.mkdir(parents=True)
            target.write_text(
                "from utils.query import run_query as rq\n"
                "runner = rq\n"
                "def bad():\n"
                "    return runner('select 1')\n",
                encoding="utf-8",
            )

            results = lint_query_boundary_paths(root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["missing_query_boundary_count"], 1)
        self.assertIn("aliases_detected", results["rows"][0])

    def test_direct_session_sql_in_shell_path_fails(self):
        from tools.contracts.query_boundary_lint import lint_query_boundary_paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / ".overwatch_final" / "shell.py"
            target.parent.mkdir(parents=True)
            target.write_text(
                "def bad(session):\n"
                "    return session.sql('select 1').collect()\n",
                encoding="utf-8",
            )

            results = lint_query_boundary_paths(root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["direct_session_sql_violation_count"], 1)


if __name__ == "__main__":
    unittest.main()
