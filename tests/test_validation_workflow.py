from pathlib import Path
import re
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
            "push:",
            'branches: ["main"]',
            "pull_request:",
            "permissions:",
            "contents: read",
            "name: Python validation",
            "uses: actions/checkout@v4",
            "uses: actions/setup-python@v6",
            'python-version: "3.12"',
            'cache: "pip"',
            "python -m pip install -r requirements.txt",
            "python -m pip install -r requirements-dev.txt",
            "python -m ruff check .overwatch_final tests",
            "python -m mypy",
            "python -m compileall .overwatch_final tests",
            "python -m unittest tests.test_deployment_contract",
            "python -m unittest tests.test_cortex_guard",
            "python -m unittest tests.test_decision_workspace_data_binding",
            "python -m unittest tests.test_theme_registry",
            "python -m unittest tests.test_snowflake_execution_validation",
            "python -m unittest tests.test_encoding_hygiene",
            "python -m unittest discover -s tests",
            "python -m tools.contracts.encoding_hygiene",
            "artifacts/encoding_hygiene_results.json",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_timeout_stays_within_validation_budget(self):
        text = _workflow_text()
        match = re.search(r"timeout-minutes:\s*(\d+)", text)
        self.assertIsNotNone(match)
        self.assertLessEqual(int(match.group(1)), 35)

    def test_production_shell_guards_remain_targeted(self):
        text = _workflow_text()
        guard_step = text[text.index("Run production shell guards") : text.index("Run Cortex guardrails")]
        expected_tests = (
            "tests.test_navigation_integrity.NavigationIntegrityTests.test_streamlit_deployment_entrypoints_are_pinned",
            "tests.test_navigation_integrity.NavigationIntegrityTests.test_app_shell_header_renders_before_sidebar_hydration",
            "tests.test_navigation_integrity.NavigationIntegrityTests.test_workflow_hubs_replace_scattered_operational_pages",
            "tests.test_navigation_integrity.NavigationIntegrityTests.test_dead_ui_helpers_stay_removed",
        )
        for test_name in expected_tests:
            with self.subTest(test_name=test_name):
                self.assertIn(test_name, guard_step)

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
        decision_index = text.index("python -m unittest tests.test_decision_workspace_data_binding")
        theme_index = text.index("python -m unittest tests.test_theme_registry")
        snowflake_index = text.index("python -m unittest tests.test_snowflake_execution_validation")
        encoding_test_index = text.index("python -m unittest tests.test_encoding_hygiene")
        discovery_index = text.index("python -m unittest discover -s tests")
        encoding_gate_index = text.index("python -m tools.contracts.encoding_hygiene")
        upload_index = text.index("Upload Decision Workspace proof artifacts")

        self.assertLess(deployment_index, discovery_index)
        self.assertLess(cortex_index, discovery_index)
        self.assertLess(decision_index, discovery_index)
        self.assertLess(theme_index, discovery_index)
        self.assertLess(snowflake_index, discovery_index)
        self.assertLess(encoding_test_index, discovery_index)
        self.assertLess(discovery_index, encoding_gate_index)
        self.assertLess(encoding_gate_index, upload_index)


if __name__ == "__main__":
    unittest.main()
