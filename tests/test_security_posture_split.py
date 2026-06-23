from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import security_posture  # noqa: E402
from sections import security_posture_access_changes_view as access_changes_view  # noqa: E402
from sections import security_posture_admin_view as admin_view  # noqa: E402
from sections import security_posture_alerts_view as alerts_view  # noqa: E402
from sections import security_posture_common as common  # noqa: E402
from sections import security_posture_contracts as contracts  # noqa: E402
from sections import security_posture_data as data  # noqa: E402
from sections import security_posture_models as models  # noqa: E402


class SecurityPostureSplitTests(unittest.TestCase):
    def setUp(self):
        self._previous_state = dict(st.session_state)
        st.session_state.clear()

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self._previous_state)

    def test_security_posture_workflow_contract_stays_stable(self):
        expected = (
            "Security Overview",
            "Failed Logins",
            "Risky Grants",
            "Privilege Sprawl",
            "Access Changes",
            "Data Sharing Exposure",
            "Security Alerts",
            "Security Admin / Advanced",
        )
        self.assertEqual(security_posture.SECURITY_POSTURE_VIEWS, expected)
        self.assertIs(security_posture.WORKFLOWS, security_posture.SECURITY_POSTURE_VIEWS)
        self.assertEqual(set(expected), set(security_posture.WORKFLOW_DETAILS))
        self.assertEqual(set(expected), set(security_posture.SECURITY_POSTURE_VIEW_DETAILS))

    def test_security_posture_contracts_reexport_focused_module(self):
        for name in contracts.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(security_posture, name))
                self.assertIs(getattr(security_posture, name), getattr(contracts, name))

    def test_security_posture_common_helpers_reexport_focused_module(self):
        for name in common.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(security_posture, name))
                self.assertIs(getattr(security_posture, name), getattr(common, name))

    def test_security_posture_models_reexport_focused_module(self):
        for name in models.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(security_posture, name))
                self.assertIs(getattr(security_posture, name), getattr(models, name))

    def test_security_posture_data_helpers_reexport_focused_module(self):
        for name in data.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(security_posture, name))
                self.assertIs(getattr(security_posture, name), getattr(data, name))

    def test_security_posture_view_helpers_reexport_focused_modules(self):
        self.assertIs(
            security_posture._render_loaded_security_alert_context,
            alerts_view._render_loaded_security_alert_context,
        )
        self.assertIs(
            security_posture._render_security_change_detail,
            access_changes_view._render_security_change_detail,
        )
        for name in admin_view.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(security_posture, name))
                self.assertIs(getattr(security_posture, name), getattr(admin_view, name))

    def test_security_posture_renderer_map_covers_owned_and_delegated_workflows(self):
        owned = set(security_posture.SECURITY_POSTURE_RENDERERS)
        delegated = set(security_posture.WORKFLOW_MODULES)
        self.assertEqual(set(security_posture.SECURITY_POSTURE_VIEWS), owned | delegated)
        self.assertFalse(owned & delegated)
        for workflow, renderer in security_posture.SECURITY_POSTURE_RENDERERS.items():
            with self.subTest(workflow=workflow):
                self.assertTrue(callable(renderer))
        self.assertIs(
            security_posture.SECURITY_POSTURE_RENDERERS["Security Alerts"],
            security_posture.render_security_alerts,
        )
        self.assertIs(
            security_posture.SECURITY_POSTURE_RENDERERS["Access Changes"],
            security_posture.render_security_access_changes,
        )

    def test_security_posture_shell_is_shrinking_without_moved_definitions(self):
        source = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 2800)
        for fragment in [
            "SECURITY_POSTURE_VIEWS = (",
            "SECURITY_VIEW_ALIASES = {",
            "def _render_loaded_security_alert_context",
            "def _render_security_change_detail",
            "def _render_security_source_health",
            "def _render_advanced_security_evidence",
            "def _load_security_brief",
        ]:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

    def test_security_scope_metadata_matching(self):
        state = {
            "global_user": "ANALYST",
            "global_database": "ALFA_PROD",
            "global_role": "SYSADMIN",
            "global_start_date": "2026-06-01",
            "global_end_date": "2026-06-23",
        }
        meta = models._security_scope_meta("ALFA", "PROD", 30, state=state)
        self.assertTrue(models._security_meta_matches(dict(meta), meta))
        self.assertFalse(models._security_meta_matches({**meta, "days": 14}, meta))
        self.assertFalse(models._security_meta_matches({**meta, "global_role": "ANALYST"}, meta))

    def test_security_score_decreases_as_risk_increases(self):
        clean = models._security_score(
            failed_logins=0,
            failed_users=0,
            users_without_mfa=0,
            active_users=100,
            recent_grants=0,
            shared_databases=0,
        )
        risky = models._security_score(
            failed_logins=40,
            failed_users=6,
            users_without_mfa=20,
            active_users=100,
            recent_grants=8,
            shared_databases=4,
        )
        self.assertGreater(clean, risky)
        self.assertEqual(models._security_rating(clean), "Strong")
        self.assertIn(models._security_rating(risky), {"Watch", "Elevated", "High Risk"})

    def test_security_proof_tables_visibility_uses_scope(self):
        st.session_state["global_role"] = "SYSADMIN"
        models._show_security_proof_tables("ALFA", "PROD", 30)
        self.assertTrue(models._security_proof_tables_visible("ALFA", "PROD", 30))
        self.assertFalse(models._security_proof_tables_visible("TREXIS", "PROD", 30))
        models._hide_security_proof_tables()
        self.assertFalse(models._security_proof_tables_visible("ALFA", "PROD", 30))

    def test_security_source_health_rows_classify_loaded_stale_and_unavailable(self):
        current_meta = models._security_scope_meta("ALFA", "PROD", 30, state={"security_posture_brief_days": 30})
        rows = models._security_source_health_rows(
            {
                "security_posture_brief_days": 30,
                "security_posture_summary": pd.DataFrame([{"FAILED_LOGINS": 1}]),
                "security_posture_meta": current_meta,
                "security_posture_source": "Fast security summary; MFA/sharing: account history",
                "security_operability_fact_error": "missing table",
            },
            "ALFA",
            "PROD",
        )
        state_by_surface = dict(zip(rows["SURFACE"], rows["STATE"]))
        self.assertEqual(state_by_surface["Security summary"], "Loaded")
        self.assertEqual(state_by_surface["Control summary"], "Unavailable")
        self.assertEqual(state_by_surface["Privileged grants"], "On demand")

    def test_security_summary_loader_mart_success_stores_state_and_proof_sql(self):
        summary = pd.DataFrame([{"FAILED_LOGINS": 3}])
        with patch("sections.security_posture_data.get_session", return_value=object()), patch(
            "sections.security_posture_data._build_security_mart_brief_sql",
            return_value=("SELECT MART_SUMMARY", "SELECT MART_EXCEPTIONS"),
        ), patch("sections.security_posture_data.run_query", return_value=summary) as run_query:
            data._load_security_brief(days=30, company="ALFA", environment="PROD", quiet=True)

        run_query.assert_called_once_with(
            "SELECT MART_SUMMARY",
            ttl_key="security_posture_summary_mart_ALFA_PROD_30",
            tier="standard",
        )
        self.assertIs(st.session_state["security_posture_summary"], summary)
        self.assertEqual(st.session_state["security_posture_source"], "Fast security summary; MFA/sharing: account history")
        self.assertEqual(
            st.session_state["security_posture_proof_sql"],
            {"summary": "SELECT MART_SUMMARY", "exceptions": "SELECT MART_EXCEPTIONS"},
        )
        self.assertNotIn("security_posture_exceptions", st.session_state)
        self.assertNotIn("security_posture_summary_error", st.session_state)

    def test_security_summary_loader_mart_failure_without_fallback_records_error(self):
        with patch("sections.security_posture_data.get_session", return_value=object()), patch(
            "sections.security_posture_data._build_security_mart_brief_sql",
            side_effect=RuntimeError("missing mart"),
        ), patch("sections.security_posture_data.format_snowflake_error", return_value="formatted mart error"):
            data._load_security_brief(
                days=14,
                company="TREXIS",
                environment="DEV",
                allow_live_fallback=False,
                quiet=True,
            )

        self.assertTrue(st.session_state["security_posture_summary"].empty)
        self.assertEqual(st.session_state["security_posture_source"], "Fast security summary unavailable")
        self.assertEqual(st.session_state["security_posture_summary_error"], "formatted mart error")
        self.assertNotIn("security_posture_exceptions", st.session_state)

    def test_security_summary_loader_live_fallback_success_preserves_source_and_ttl(self):
        summary = pd.DataFrame([{"FAILED_LOGINS": 5}])
        with patch("sections.security_posture_data.get_session", return_value=object()), patch(
            "sections.security_posture_data._build_security_mart_brief_sql",
            side_effect=RuntimeError("missing mart"),
        ), patch(
            "sections.security_posture_data._build_security_summary_sql",
            return_value=("SELECT LIVE_SUMMARY", "SELECT LIVE_EXCEPTIONS"),
        ), patch("sections.security_posture_data.run_query", return_value=summary) as run_query, patch(
            "sections.security_posture_data.format_snowflake_error",
            return_value="formatted mart error",
        ):
            data._load_security_brief(days=7, company="ALFA", environment="ALL", quiet=True)

        run_query.assert_called_once_with(
            "SELECT LIVE_SUMMARY",
            ttl_key="security_posture_summary_live_ALFA_ALL_7",
            tier="standard",
        )
        self.assertIs(st.session_state["security_posture_summary"], summary)
        self.assertEqual(st.session_state["security_posture_source"], "Live fallback: SNOWFLAKE.ACCOUNT_USAGE")
        self.assertEqual(
            st.session_state["security_posture_proof_sql"],
            {"summary": "SELECT LIVE_SUMMARY", "exceptions": "SELECT LIVE_EXCEPTIONS"},
        )
        self.assertNotIn("security_posture_summary_error", st.session_state)

    def test_security_summary_loader_live_fallback_failure_records_empty_summary(self):
        with patch("sections.security_posture_data.get_session", return_value=object()), patch(
            "sections.security_posture_data._build_security_mart_brief_sql",
            side_effect=RuntimeError("missing mart"),
        ), patch(
            "sections.security_posture_data._build_security_summary_sql",
            side_effect=RuntimeError("live unavailable"),
        ), patch("sections.security_posture_data.format_snowflake_error", return_value="formatted live error"), patch(
            "sections.security_posture_data.st.error"
        ) as error:
            data._load_security_brief(days=7, company="ALFA", environment="ALL", quiet=True)

        self.assertTrue(st.session_state["security_posture_summary"].empty)
        self.assertNotIn("security_posture_exceptions", st.session_state)
        error.assert_called_once()
        self.assertIn("formatted live error", error.call_args.args[0])

    def test_freshness_and_confidence_labels_stay_stable(self):
        self.assertIn("ACCOUNT_USAGE can lag", common._freshness_note("SNOWFLAKE.ACCOUNT_USAGE"))
        self.assertIn("live INFORMATION_SCHEMA", common._freshness_note("INFORMATION_SCHEMA"))
        self.assertIn("fast summary", common._freshness_note("OVERWATCH mart"))
        self.assertEqual(common._metric_confidence_label("exact"), "Measurement: Exact")
        self.assertEqual(common._metric_confidence_label("allocated"), "Measurement: Allocated from source records")
        self.assertEqual(common._metric_confidence_label("estimated"), "Measurement: Estimated")

    def test_mfa_helpers_delegate_to_shared_metrics_contract(self):
        with patch("sections.security_posture_common.shared_mfa_count_expr", return_value="MFA_COUNT") as count_expr:
            self.assertEqual(common._mfa_count_expr({"EXT_AUTHN_DUO"}), "MFA_COUNT")
        count_expr.assert_called_once_with({"EXT_AUTHN_DUO"})

        with patch("sections.security_posture_common.shared_mfa_gap_predicate", return_value="MFA_GAP") as gap_predicate:
            self.assertEqual(common._mfa_gap_predicate({"EXT_AUTHN_DUO"}, alias="usr"), "MFA_GAP")
        gap_predicate.assert_called_once_with({"EXT_AUTHN_DUO"}, "usr")

        with patch("sections.security_posture_common.shared_mfa_proof_label", return_value="MFA_PROOF") as proof_label:
            self.assertEqual(common._mfa_proof_label({"EXT_AUTHN_DUO"}), "MFA_PROOF")
        proof_label.assert_called_once_with({"EXT_AUTHN_DUO"})

    def test_security_posture_aliases_normalize_to_canonical_workflows(self):
        expected = {
            "Security Posture": "Security Overview",
            "Access Posture": "Security Overview",
            "Login Audit": "Failed Logins",
            "Roles & Grants": "Risky Grants",
            "Privilege sprawl": "Privilege Sprawl",
            "Data Sharing": "Data Sharing Exposure",
            "Security Summary": "Security Alerts",
            "Advanced Security Diagnostics": "Security Admin / Advanced",
        }
        for alias, canonical in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(security_posture.SECURITY_VIEW_ALIASES[alias], canonical)

    def test_security_posture_delegated_modules_stay_registered(self):
        self.assertEqual(security_posture.WORKFLOW_MODULES["Failed Logins"], "sections.security_access")
        self.assertEqual(security_posture.WORKFLOW_MODULES["Risky Grants"], "sections.security_access")
        self.assertEqual(security_posture.WORKFLOW_MODULES["Data Sharing Exposure"], "sections.data_sharing")

    def test_render_workflow_module_calls_registered_render(self):
        module = SimpleNamespace(render=lambda: None)
        with patch("sections.security_posture_common.import_module", return_value=module) as import_module, patch.object(
            module, "render"
        ) as render:
            security_posture.render_workflow_module("Failed Logins", {"Failed Logins": "sections.fake_security"})

        import_module.assert_called_once_with("sections.fake_security")
        render.assert_called_once_with()

    def test_render_workflow_module_warns_for_missing_render(self):
        with patch("sections.security_posture_common.import_module", return_value=SimpleNamespace()), patch(
            "sections.security_posture_common.st.warning"
        ) as warning:
            security_posture.render_workflow_module("Failed Logins", {"Failed Logins": "sections.fake_security"})

        warning.assert_called_once()
        self.assertIn("has no render", warning.call_args.args[0])

    def test_render_workflow_module_warns_for_unregistered_workflow(self):
        with patch("sections.security_posture_common.st.warning") as warning:
            security_posture.render_workflow_module("Missing", {})

        warning.assert_called_once()
        self.assertIn("No module registered", warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
