from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import route_registry  # noqa: E402


class ProductionReadinessContractTests(unittest.TestCase):
    def _readiness_text(self) -> str:
        return (ROOT / "docs" / "OVERWATCH_PRODUCTION_READINESS.md").read_text(encoding="utf-8")

    def test_production_readiness_doc_covers_release_gates(self):
        doc_path = ROOT / "docs" / "OVERWATCH_PRODUCTION_READINESS.md"
        self.assertTrue(doc_path.exists())
        text = self._readiness_text()

        for fragment in (
            "Green Validate workflow",
            "tests.test_deployment_contract",
            "STREAMLIT_CLOUD_DEPLOY.md",
            "snowflake/OVERWATCH_MART_SETUP.sql",
            "snowflake/OVERWATCH_MART_DROP.sql",
            "perf_tests/README.md",
            "docs/OVERWATCH_RELEASE_MANIFEST.md",
            "Release evidence must match the release manifest commit SHA",
            "Historical evidence",
            "do not run live Snowflake regression unless credentials/auth are available",
            "No credentials, tokens, private keys",
            "Action queue previews stay review-only",
            "Typed confirmations still require exact operator text",
            "`admin_button_disabled()` guarded actions remain disabled for unauthorized users",
            "12-heavy-power-user benchmark",
            "perf_tests/profiles/12_power_users.json",
            "perf_tests/power_user_review.py",
            "must not click mutation controls",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_browser_sanity_uses_six_primary_routes(self):
        text = self._readiness_text()
        self.assertIn("six-section model", text)
        self.assertIn("route_registry.PRIMARY_SECTION_TITLES", text)

        for section in route_registry.PRIMARY_SECTION_TITLES:
            with self.subTest(section=section):
                self.assertIn(f"- {section}", text)

    def test_legacy_routes_are_compatibility_deep_link_checks(self):
        text = self._readiness_text()
        self.assertIn("Compatibility/deep-link routes normalize to current workflow locations", text)
        for fragment in (
            "Cost Center -> Cost & Contract workflow",
            "Account Health -> DBA Control Room workflow",
            "Security Posture -> Security Monitoring workflow",
            "Task Management -> Workload Operations workflow",
            "Change Drift / Change & Drift -> Workload Operations delegated workflow path",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_static_release_gate_artifacts_exist_and_are_referenced(self):
        text = self._readiness_text()
        for relative_path in (
            ".github/workflows/validate.yml",
            "STREAMLIT_CLOUD_DEPLOY.md",
            "perf_tests/README.md",
            "docs/OVERWATCH_RELEASE_MANIFEST.md",
            "snowflake/OVERWATCH_MART_SETUP.sql",
            "snowflake/OVERWATCH_MART_DROP.sql",
        ):
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).exists())
                self.assertIn(relative_path, text)

    def test_release_evidence_template_covers_required_sections(self):
        template_path = ROOT / "docs" / "OVERWATCH_RELEASE_EVIDENCE_TEMPLATE.md"
        self.assertTrue(template_path.exists())
        text = template_path.read_text(encoding="utf-8")

        for heading in (
            "## Commit",
            "## Validation Commands",
            "## Deployment Contract",
            "## Mart Setup",
            "## Browser Sanity",
            "## Performance Smoke",
            "## 12 Power User Performance",
            "## Guarded Operations",
            "## Live Snowflake Regression",
            "## Secrets Check",
            "## Rollback / Reset",
            "## Deferred Items",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, text)

        for fragment in (
            "Do not claim live Snowflake regression passed unless it was actually run",
            "STREAMLIT_CLOUD_DEPLOY.md",
            "snowflake/OVERWATCH_MART_DROP.sql",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
