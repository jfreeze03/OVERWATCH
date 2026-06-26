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
from sections import security_posture_access_review as access_review  # noqa: E402
from sections import security_posture_action_queue as action_queue  # noqa: E402
from sections import security_posture_access_changes_view as access_changes_view  # noqa: E402
from sections import security_posture_admin_view as admin_view  # noqa: E402
from sections import security_posture_alerts_view as alerts_view  # noqa: E402
from sections import security_posture_common as common  # noqa: E402
from sections import security_posture_contracts as contracts  # noqa: E402
from sections import security_posture_data as data  # noqa: E402
from sections import security_posture_models as models  # noqa: E402
from sections import security_posture_overview_view as overview_view  # noqa: E402
from sections import security_posture_privilege_sprawl_view as privilege_view  # noqa: E402


class _UiBlock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def container(self):
        return self


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
        for module in (overview_view, access_review, action_queue, privilege_view):
            for name in module.__all__:
                with self.subTest(module=module.__name__, name=name):
                    self.assertTrue(hasattr(security_posture, name))
                    self.assertIs(getattr(security_posture, name), getattr(module, name))

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
        self.assertIs(
            security_posture.SECURITY_POSTURE_RENDERERS["Security Overview"],
            overview_view.render_security_overview,
        )
        self.assertIs(
            security_posture.SECURITY_POSTURE_RENDERERS["Privilege Sprawl"],
            privilege_view.render_security_privilege_sprawl,
        )

    def test_access_changes_view_does_not_duplicate_change_loader_key(self):
        with patch.object(security_posture, "_render_security_change_detail") as change_detail, patch.object(
            security_posture,
            "_render_advanced_security_evidence",
        ) as advanced:
            security_posture.render_security_access_changes("ALFA", "PROD", 30)

        change_detail.assert_called_once_with(
            "ALFA",
            "PROD",
            button_key="security_load_access_changes_intelligence",
        )
        advanced.assert_called_once_with("ALFA", "PROD", skip_change_detail=True)

    def test_advanced_security_evidence_skips_change_loader_by_default(self):
        patches = [
            patch.object(admin_view.st, "divider"),
            patch.object(admin_view.st, "expander", return_value=_UiBlock()),
            patch.object(admin_view, "render_operator_briefing"),
            patch.object(admin_view, "render_workflow_guide"),
            patch.object(admin_view, "_render_security_ownership_coverage"),
            patch.object(admin_view, "_render_security_score_explanation"),
            patch.object(admin_view, "_render_security_change_detail"),
            patch.object(admin_view, "_render_security_action_approval"),
            patch.object(admin_view, "_render_security_command_findings"),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as change_detail, patches[7], patches[8]:
            admin_view._render_advanced_security_evidence("ALFA", "PROD")
            change_detail.assert_not_called()

            admin_view._render_advanced_security_evidence("ALFA", "PROD", skip_change_detail=False)
            change_detail.assert_called_once_with("ALFA", "PROD")

    def test_security_posture_shell_is_shrinking_without_moved_definitions(self):
        source = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 250)
        for fragment in [
            "SNOWFLAKE.ACCOUNT_USAGE",
            "run_query(",
            "run_query_or_raise(",
            "pd.DataFrame(",
            "CREATE TABLE",
            "INSERT INTO",
            "ALTER TABLE",
            "SECURITY_POSTURE_VIEWS = (",
            "SECURITY_VIEW_ALIASES = {",
            "def build_security_access_review_ddl",
            "def _security_access_review_insert_sql",
            "def _security_exception_verification_sql",
            "def _queue_security_exceptions",
            "def _queue_privileged_grant_actions",
            "def _render_privileged_grant_readiness",
            "def _render_security_overview_entry",
            "def _security_action_brief",
            "def _render_loaded_security_alert_context",
            "def _render_security_change_detail",
            "def _render_security_source_health",
            "def _render_advanced_security_evidence",
            "def _load_security_brief",
            "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
            "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS",
            "SNOWFLAKE.ACCOUNT_USAGE.DATABASES",
        ]:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

    def test_security_posture_facade_all_names_exist(self):
        self.assertIn("render", security_posture.__all__)
        self.assertIn("SECURITY_POSTURE_RENDERERS", security_posture.__all__)
        for name in security_posture.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(security_posture, name))

    def test_security_posture_render_has_no_unreachable_overview_block(self):
        source = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
        self.assertNotIn("if active_view == SECURITY_OVERVIEW_WORKFLOW and not security_current", source)
        self.assertNotIn("if active_view == SECURITY_OVERVIEW_WORKFLOW:\n        _render_security_overview_entry", source)
        self.assertIn("make_decision_refresh_action", source)
        self.assertNotIn("security_posture_brief_load", source)
        self.assertIn("SECURITY_POSTURE_RENDERERS.get(active_view)", source)

    def test_security_posture_route_shell_does_not_call_security_loaders(self):
        rendered = []

        def _record_renderer(company, environment, days):
            rendered.append((company, environment, days))

        with patch.object(security_posture, "get_active_company", return_value="ALFA"), patch.object(
            security_posture,
            "get_active_environment",
            return_value="PROD",
        ), patch.object(security_posture, "render_signal_confidence"), patch.object(
            security_posture,
            "day_window_selectbox",
            return_value=30,
        ), patch.object(
            security_posture,
            "render_primary_section_tabs",
            return_value=security_posture.SECURITY_OVERVIEW_WORKFLOW,
        ), patch.object(
            security_posture,
            "render_section_command_brief",
        ) as render_brief, patch.object(
            security_posture,
            "autoload_section_command_brief",
            return_value="brief",
        ) as autoload, patch.object(
            security_posture,
            "_load_security_brief",
            side_effect=AssertionError("Security route shell must not load security evidence directly"),
        ), patch(
            "sections.security_posture_overview_view._load_security_brief",
            side_effect=AssertionError("Security overview loader should stay behind the delegated renderer in this test"),
        ), patch.dict(
            security_posture.SECURITY_POSTURE_RENDERERS,
            {security_posture.SECURITY_OVERVIEW_WORKFLOW: _record_renderer},
        ):
            security_posture.render()

        autoload.assert_called_once_with("Security Monitoring", "ALFA", "PROD", 30, force=False)
        render_brief.assert_called_once()
        args, kwargs = render_brief.call_args
        self.assertEqual(args, ("brief",))
        self.assertEqual(kwargs["key_prefix"], "security_monitoring_command_brief")
        self.assertIn("primary_action", kwargs)
        self.assertNotIn("detail_action", kwargs)
        self.assertFalse(kwargs["compact"])
        self.assertEqual(rendered, [])

    def test_security_overview_cold_first_paint_does_not_auto_load(self):
        button_labels: list[str] = []

        def _button(label, **_kwargs):
            button_labels.append(str(label))
            return False

        with patch.object(
            overview_view,
            "_load_security_brief",
            side_effect=AssertionError("Security overview first paint must not auto-load"),
        ) as load_brief, patch.object(
            overview_view,
            "run_query",
            side_effect=AssertionError("Security overview first paint must not run live SQL"),
        ), patch.object(
            overview_view,
            "get_session",
            side_effect=AssertionError("Security overview first paint must not request a session"),
        ), patch.object(overview_view.st, "empty", return_value=_UiBlock()), patch.object(
            overview_view.st,
            "columns",
            side_effect=lambda spec: [_UiBlock() for _ in range(len(spec) if isinstance(spec, list) else spec)],
        ), patch.object(overview_view.st, "button", side_effect=_button), patch.object(
            overview_view.st,
            "expander",
            return_value=_UiBlock(),
        ), patch.object(overview_view.st, "markdown"), patch.object(overview_view.st, "caption"), patch.object(
            overview_view,
            "_render_security_action_brief",
        ) as action_brief, patch.object(
            overview_view,
            "_render_security_operating_snapshot",
        ) as operating_snapshot, patch.object(
            overview_view,
            "_render_security_brief_launchpad",
        ), patch.object(overview_view, "_render_advanced_security_evidence"), patch.object(
            overview_view,
            "render_add_to_case_button",
            side_effect=AssertionError("Security Add to Case should wait for a loaded summary"),
        ):
            overview_view.render_security_overview("ALFA", "PROD", 30)

        load_brief.assert_not_called()
        self.assertNotIn("Refresh Security Summary", button_labels)
        self.assertEqual(action_brief.call_args.args[0]["state"], "Summary unavailable")
        self.assertEqual(operating_snapshot.call_args.args[0]["evidence"], "Summary unavailable")

    def test_security_overview_uses_scope_compatible_summary_without_refresh(self):
        summary = pd.DataFrame([{
            "FAILED_LOGINS": 0,
            "FAILED_USERS": 0,
            "ACTIVE_USERS": 4,
            "USERS_WITHOUT_MFA": 0,
            "RECENT_GRANTS": 0,
            "SHARED_DATABASES": 0,
        }])
        meta = models._security_scope_meta("ALFA", "PROD", 30)
        st.session_state["security_posture_summary"] = summary
        st.session_state["security_posture_exceptions"] = pd.DataFrame()
        st.session_state["security_posture_meta"] = meta
        st.session_state["security_posture_source"] = "Session security summary"
        button_labels: list[str] = []

        def _button(label, **_kwargs):
            button_labels.append(str(label))
            return False

        with patch.object(
            overview_view,
            "_load_security_brief",
            side_effect=AssertionError("Cached security summary should not refresh automatically"),
        ) as load_brief, patch.object(overview_view.st, "empty", return_value=_UiBlock()), patch.object(
            overview_view.st,
            "columns",
            side_effect=lambda spec: [_UiBlock() for _ in range(len(spec) if isinstance(spec, list) else spec)],
        ), patch.object(overview_view.st, "button", side_effect=_button), patch.object(
            overview_view.st,
            "expander",
            return_value=_UiBlock(),
        ), patch.object(overview_view.st, "markdown"), patch.object(overview_view.st, "caption"), patch.object(
            overview_view.st,
            "success",
        ), patch.object(overview_view.st, "divider"), patch.object(
            overview_view,
            "_render_security_brief_launchpad",
        ), patch.object(
            overview_view,
            "_render_security_watch_floor",
        ) as watch_floor, patch.object(
            overview_view,
            "_render_security_operability_fact_gate",
        ) as fact_gate, patch.object(
            overview_view,
            "_render_security_exceptions_gate",
        ) as exception_gate, patch.object(overview_view, "download_text"), patch.object(
            overview_view,
            "_render_advanced_security_evidence",
        ), patch.object(overview_view, "render_data_freshness") as freshness:
            overview_view.render_security_overview("ALFA", "PROD", 30)

        load_brief.assert_not_called()
        self.assertNotIn("Refresh Security Summary", button_labels)
        watch_floor.assert_called_once()
        fact_gate.assert_called_once_with("ALFA", "PROD", 30)
        exception_gate.assert_called_once_with("ALFA", "PROD", 30)
        freshness.assert_called_once()

    def test_overview_refresh_helper_calls_live_fallback_loader(self):
        with patch("sections.security_posture_overview_view._load_security_brief") as load_brief:
            overview_view._refresh_security_summary("ALFA", "PROD", 30)
        load_brief.assert_called_once_with(
            days=30,
            company="ALFA",
            environment="PROD",
            allow_live_fallback=True,
            quiet=False,
        )

    def test_overview_exception_rows_and_stale_brief(self):
        meta = models._security_scope_meta("ALFA", "PROD", 30, state={})
        summary = pd.DataFrame([{
            "FAILED_LOGINS": 2,
            "FAILED_USERS": 1,
            "USERS_WITHOUT_MFA": 0,
            "RECENT_GRANTS": 0,
            "SHARED_DATABASES": 0,
        }])
        exceptions = pd.DataFrame([{
            "SEVERITY": "High",
            "FINDING_TYPE": "Failed Login Spike",
            "ENTITY": "USER_A",
            "EVENT_COUNT": 4,
            "LAST_SEEN": "2026-06-23",
        }])
        rows = overview_view._security_exception_strip_rows(summary, exceptions, meta, "ALFA", "PROD", 30)
        self.assertEqual(rows[0]["route"], "Failed Logins")
        stale = overview_view._security_action_brief(summary, exceptions, {**meta, "days": 14}, "ALFA", "PROD", 30)
        self.assertEqual(stale["state"], "Stale")

    def test_overview_source_keeps_refresh_and_proof_gate_keys(self):
        overview_source = (APP_ROOT / "sections" / "security_posture_overview_view.py").read_text(encoding="utf-8")
        route_source = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
        self.assertNotIn("security_posture_brief_load", route_source)
        self.assertIn("make_decision_refresh_action", route_source)
        for token in [
            "security_posture_load_exceptions",
            "security_posture_queue",
            "security_posture_hide_proof_tables",
            "security_posture_load_proof_tables",
            "_security_proof_tables_visible",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, overview_source)

    def test_security_access_changes_uses_distinct_change_loader_keys(self):
        route_source = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
        change_source = (APP_ROOT / "sections" / "security_posture_access_changes_view.py").read_text(encoding="utf-8")
        admin_source = (APP_ROOT / "sections" / "security_posture_admin_view.py").read_text(encoding="utf-8")

        self.assertIn('button_key: str = "security_load_change_intelligence"', change_source)
        self.assertEqual(route_source.count('button_key="security_load_access_changes_intelligence"'), 1)
        self.assertIn("_render_advanced_security_evidence(company, environment, skip_change_detail=True)", route_source)
        default_admin_block = admin_source.split("if not skip_change_detail:", 1)[1].split("def ", 1)[0]
        self.assertIn("_render_security_change_detail(company, environment)", default_admin_block)

    def test_access_review_sql_builders_and_readiness_contracts(self):
        ddl = access_review.build_security_access_review_ddl(db="APP_DB", schema="SECURITY", table="REVIEW")
        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        self.assertIn("APP_DB.SECURITY.REVIEW", ddl)
        self.assertIn("VERIFICATION_QUERY", ddl)
        self.assertTrue(all("ADD COLUMN IF NOT EXISTS" in sql for sql in access_review.build_security_access_review_migration_sql()))

        login_sql = access_review._security_exception_verification_sql({
            "FINDING_TYPE": "Failed Login",
            "ENTITY": "O'HARE_USER",
        })
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY", login_sql)
        self.assertIn("O''HARE_USER", login_sql)

        review = pd.DataFrame([{
            "FINDING_TYPE": "Failed Login",
            "SEVERITY": "High",
            "ENTITY_TYPE": "User/Auth",
            "ENTITY": "O'HARE_USER",
            "EVENT_COUNT": 2,
            "DISTINCT_SOURCES": 1,
            "LAST_SEEN": "2026-06-23",
            "OWNER": "Owner's Team",
            "ESCALATION_TARGET": "DBA",
            "APPROVER": "IAM",
            "ACCESS_REVIEW_STATE": "Identity investigation required",
            "ROLE_CAPABILITY_STATE": "Not required",
            "TICKET_REQUIRED": "Yes",
            "REVIEW_BY_REQUIRED": "Yes",
            "PROOF_REQUIRED": "Owner's proof",
            "VERIFICATION_QUERY": "SELECT 'x'",
            "REVIEW_READINESS": "Ready for Action Queue",
        }])
        insert_sql = access_review._security_access_review_insert_sql(
            review,
            company="ALFA",
            environment="PROD",
            source="Owner's source",
            snapshot_id="SNAP'1",
        )
        self.assertIn("SNAP''1", insert_sql)
        self.assertIn("O''HARE_USER", insert_sql)
        self.assertIn("Owner''s Team", insert_sql)
        self.assertIn("Owner''s source", insert_sql)

        history_sql = access_review._security_access_review_history_sql(14, "ALFA", "PROD")
        self.assertIn("DATEADD('day', -14", history_sql)
        self.assertIn("COMPANY = 'ALFA'", history_sql)
        self.assertIn("ENVIRONMENT = 'PROD'", history_sql)

        readiness = access_review._security_access_review_readiness_for_row({
            "SEVERITY": "High",
            "OWNER": "",
            "TICKET_REQUIRED": "Yes",
            "REVIEW_BY_REQUIRED": "Yes",
            "VERIFICATION_QUERY": "",
        })
        self.assertEqual(readiness["REVIEW_READINESS"], "Assignment Blocked")
        self.assertIn("route/on-call context", readiness["REVIEW_BLOCKERS"])

    def test_action_queue_writers_preserve_payload_contracts(self):
        exceptions = pd.DataFrame([{
            "FINDING_TYPE": "Failed Login",
            "SEVERITY": "High",
            "ENTITY": "USER_A",
            "EVENT_COUNT": 3,
            "DISTINCT_SOURCES": 1,
            "LAST_SEEN": "2026-06-23",
        }])
        with patch("sections.security_posture_access_review.resolve_owner_context", return_value={
            "OWNER": "IAM",
            "OWNER_EMAIL": "iam@example.com",
            "ESCALATION_TARGET": "Security",
            "OWNER_SOURCE": "test",
        }), patch("sections.security_posture_action_queue.make_action_id", return_value="ACT-1"), patch(
            "sections.security_posture_action_queue.upsert_actions", return_value=1
        ) as upsert, patch("sections.security_posture_action_queue.st.success"):
            action_queue._queue_security_exceptions("SESSION", exceptions)
        upsert.assert_called_once()
        self.assertIs(upsert.call_args.args[0], "SESSION")
        action = upsert.call_args.args[1][0]
        self.assertEqual(action["Category"], "Security")
        self.assertEqual(action["Severity"], "High")
        self.assertEqual(action["Entity"], "USER_A")
        self.assertIn("Review-only", action["Generated SQL Fix"])

        grants = pd.DataFrame([{
            "GRANT_REVIEW_READINESS": "Review Ready",
            "FINDING_TYPE": "Privileged Grant",
            "SEVERITY": "High",
            "ENTITY": "ROLE_A",
            "ROLE_NAME": "ACCOUNTADMIN",
            "PRIVILEGE": "USAGE",
            "DATABASE_CONTEXT": False,
            "OWNER": "Security",
            "OWNER_EMAIL": "sec@example.com",
            "ESCALATION_TARGET": "DBA",
            "GRANT_REVIEW_STATE": "Tier 0 role grant",
            "SCOPE_CONFIDENCE": "Account/User Context",
            "PROOF_REQUIRED": "grant proof",
            "NEXT_GRANT_ACTION": "Review",
        }])
        with patch("sections.security_posture_action_queue.make_action_id", return_value="ACT-2"), patch(
            "sections.security_posture_action_queue.upsert_actions", return_value=1
        ) as upsert_grants, patch("sections.security_posture_action_queue.st.success"):
            action_queue._queue_privileged_grant_actions("SESSION2", grants, company="ALFA", environment="PROD")
        self.assertIs(upsert_grants.call_args.args[0], "SESSION2")
        grant_action = upsert_grants.call_args.args[1][0]
        self.assertEqual(grant_action["Source"], "Security Posture - Privileged Grant Status")
        self.assertEqual(grant_action["Category"], "Security Access Review")
        self.assertEqual(grant_action["Owner"], "Security")

    def test_empty_action_queue_frames_do_not_call_upsert(self):
        with patch("sections.security_posture_action_queue.upsert_actions") as upsert, patch(
            "sections.security_posture_action_queue.st.info"
        ):
            action_queue._queue_security_exceptions("SESSION", pd.DataFrame())
            action_queue._queue_privileged_grant_actions("SESSION", pd.DataFrame(), company="ALFA", environment="PROD")
        upsert.assert_not_called()

    def test_privilege_sprawl_renderer_contract(self):
        self.assertIs(
            security_posture.SECURITY_POSTURE_RENDERERS["Privilege Sprawl"],
            privilege_view.render_security_privilege_sprawl,
        )
        source = (APP_ROOT / "sections" / "security_posture_privilege_sprawl_view.py").read_text(encoding="utf-8")
        for token in [
            "security_privilege_sprawl_load",
            "security_priv_grants_queue",
            "security_priv_grant_days",
            "security_privileged_grants",
            "security_privileged_grants_meta",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, source)

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
