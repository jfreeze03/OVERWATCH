from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


class ValidationWorkflowTests(unittest.TestCase):
    def test_validate_workflow_contract(self):
        text = _workflow_text()

        expected_fragments = (
            "name: Validate",
            "name: Python validation",
            "uses: actions/checkout@v4",
            "uses: actions/setup-python@v6",
            'python-version: "3.12"',
            'cache: "pip"',
            "python -m ruff check .overwatch_final tests",
            "python -m mypy",
            "python -m compileall .overwatch_final tests",
            "python -m unittest tests.test_deployment_contract",
            "python -m unittest tests.test_cortex_guard",
            "python -m unittest discover -s tests",
            'Path(".overwatch_final")',
            'Path("tests")',
            'Path(".github")',
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_lint_runs_before_typecheck_and_compile(self):
        text = _workflow_text()
        ruff_index = text.index("python -m ruff check .overwatch_final tests")
        mypy_index = text.index("python -m mypy")
        compile_index = text.index("python -m compileall .overwatch_final tests")

        self.assertLess(ruff_index, mypy_index)
        self.assertLess(ruff_index, compile_index)

    def test_unit_discovery_remains_after_targeted_guards(self):
        text = _workflow_text()
        deployment_index = text.index("python -m unittest tests.test_deployment_contract")
        cortex_index = text.index("python -m unittest tests.test_cortex_guard")
        discovery_index = text.index("python -m unittest discover -s tests")
        mojibake_index = text.index("Scan for mojibake characters")

        self.assertLess(deployment_index, discovery_index)
        self.assertLess(cortex_index, discovery_index)
        self.assertLess(discovery_index, mojibake_index)


if __name__ == "__main__":
    unittest.main()
