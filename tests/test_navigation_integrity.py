from pathlib import Path
import ast
import importlib.util
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import (  # noqa: E402
    ALL_SECTIONS,
    ARCHITECTURE_OBJECTIVES,
    NAV_GROUPS,
    ROLE_SECTIONS,
    SECTION_ALIASES,
    SECTION_BY_TITLE,
    SECTION_DEFINITIONS,
    SECTION_MODULES,
    SECTION_REDIRECTS,
    EXPERIENCE_VIEW_SECTIONS,
    normalize_section_name,
)
from utils.section_guidance import (  # noqa: E402
    SECTION_EVIDENCE_CONTRACT,
    SECTION_OPERATING_GUIDE,
)
from utils.scorecards import DBA_CONTROL_PLANE_SECTION_BASELINE  # noqa: E402


class NavigationIntegrityTests(unittest.TestCase):
    def test_section_registry_matches_navigation(self):
        flattened = [section for sections in NAV_GROUPS.values() for section in sections]
        defined = [section.label for section in SECTION_DEFINITIONS]
        self.assertEqual(ALL_SECTIONS, flattened)
        self.assertEqual(ALL_SECTIONS, defined)
        self.assertEqual(set(ALL_SECTIONS), set(SECTION_MODULES))
        self.assertEqual(
            SECTION_MODULES,
            {section.label: section.module for section in SECTION_DEFINITIONS},
        )
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        self.assertEqual(config_text.count("ROLE_SECTIONS = {"), 1)

    def test_section_definitions_are_complete(self):
        for section in SECTION_DEFINITIONS:
            with self.subTest(section=section.title):
                self.assertTrue(section.group)
                self.assertTrue(section.icon)
                self.assertTrue(section.title)
                self.assertTrue(section.module)
                self.assertEqual(section.label, section.title)

    def test_registered_modules_exist(self):
        missing = [
            module_path
            for module_path in SECTION_MODULES.values()
            if importlib.util.find_spec(module_path) is None
        ]
        self.assertEqual(missing, [])

    def test_dba_control_room_uses_fast_shell_module(self):
        self.assertEqual(SECTION_MODULES["DBA Control Room"], "sections.dba_control_room_shell")
        shell_text = (APP_ROOT / "sections" / "dba_control_room_shell.py").read_text(encoding="utf-8")
        full_workspace_text = (APP_ROOT / "sections" / "dba_control_room.py").read_text(encoding="utf-8")
        shell_import_block = shell_text.split("def _delegate_full_workspace", 1)[0]

        self.assertIn("def _delegate_full_workspace", shell_text)
        self.assertIn("from sections import dba_control_room", shell_text)
        self.assertIn("_FULL_WORKSPACE_KEY", shell_text)
        self.assertNotIn("import pandas", shell_import_block)
        self.assertNotIn("from utils", shell_import_block)
        self.assertNotIn("import utils", shell_import_block)
        self.assertNotIn("st.number_input", shell_text)
        self.assertIn("DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS = 24", full_workspace_text)
        self.assertIn("DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS", full_workspace_text)
        self.assertIn("Use live 24h checks when needed", full_workspace_text)
        self.assertNotIn("Allow live ACCOUNT_USAGE fallback queries", full_workspace_text)

    def test_roles_and_aliases_resolve_to_visible_sections(self):
        for role, sections in ROLE_SECTIONS.items():
            with self.subTest(role=role):
                self.assertTrue(sections)
                self.assertLessEqual(set(sections), set(ALL_SECTIONS))

        self.assertEqual(set(SECTION_BY_TITLE), set(ALL_SECTIONS))
        self.assertLessEqual(set(SECTION_ALIASES.values()), set(ALL_SECTIONS))
        self.assertLessEqual(set(SECTION_REDIRECTS.values()), set(ALL_SECTIONS))
        for alias, target in SECTION_REDIRECTS.items():
            with self.subTest(alias=alias):
                self.assertEqual(SECTION_ALIASES[alias], target)
                self.assertEqual(normalize_section_name(alias), target)
                self.assertNotIn(alias, SECTION_BY_TITLE)
        self.assertEqual(SECTION_ALIASES["Credit Contract"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Cost Center"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Security & Access"], SECTION_BY_TITLE["Security Posture"])
        self.assertEqual(SECTION_ALIASES["DBA Tools"], SECTION_BY_TITLE["Change & Drift"])
        self.assertEqual(SECTION_ALIASES["Optimization"], SECTION_BY_TITLE["Warehouse Health"])
        self.assertEqual(SECTION_ALIASES["Architecture"], SECTION_BY_TITLE["Architecture Readiness"])
        self.assertEqual(SECTION_ALIASES["Disaster Recovery"], SECTION_BY_TITLE["Architecture Readiness"])
        self.assertEqual(SECTION_ALIASES["Executive Briefing"], SECTION_BY_TITLE["Executive Landing"])
        self.assertNotIn("LEGACY_SECTION_ALIASES", (APP_ROOT / "config.py").read_text(encoding="utf-8"))

    def test_experience_views_are_registered(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")

        self.assertIn("Executive Landing", ALL_SECTIONS)
        self.assertEqual(SECTION_MODULES["Executive Landing"], "sections.executive_landing")
        self.assertIn("EXPERIENCE_VIEW_SECTIONS", config_text)
        self.assertIn("Experience View", app_text)
        self.assertIn("_sync_experience_navigation", app_text)
        self.assertIn("on_change=_sync_experience_navigation", app_text)
        for profile, sections in EXPERIENCE_VIEW_SECTIONS.items():
            with self.subTest(profile=profile):
                self.assertTrue(sections)
                self.assertLessEqual(set(sections), set(ALL_SECTIONS))
        self.assertIn("Executive Landing", EXPERIENCE_VIEW_SECTIONS["Executive"])
        self.assertIn("Cost & Contract", EXPERIENCE_VIEW_SECTIONS["FinOps"])
        self.assertIn("Security Posture", EXPERIENCE_VIEW_SECTIONS["Security"])

    def test_executive_landing_routes_to_workflow_panes(self):
        executive_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")

        self.assertIn("_source_health_rows", executive_text)
        self.assertIn("Executive source health", executive_text)
        self.assertIn('"alert_center_active_view": "Automation Readiness"', executive_text)
        self.assertIn('workflow_key="cost_contract_workflow"', executive_text)
        self.assertIn('workflow="FinOps Control Center"', executive_text)
        self.assertIn('workflow_key="change_drift_workflow"', executive_text)
        self.assertIn('workflow="Controlled DBA actions"', executive_text)
        self.assertIn('"dba_tools_group_selector": "Cost & Setup"', executive_text)
        self.assertIn('"dba_tools_tool_selector_Cost & Setup": "Setup Status"', executive_text)

    def test_section_alias_literal_has_no_duplicate_keys(self):
        config_tree = ast.parse((APP_ROOT / "config.py").read_text(encoding="utf-8"))
        alias_dict = None
        for node in config_tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "SECTION_ALIASES" for target in node.targets)
                and isinstance(node.value, ast.Dict)
            ):
                alias_dict = node.value
                break

        self.assertIsNotNone(alias_dict)
        literal_keys = [
            key.value
            for key in alias_dict.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
        duplicates = sorted({key for key in literal_keys if literal_keys.count(key) > 1})
        self.assertEqual(duplicates, [])

    def test_ask_overwatch_is_evidence_grounded_without_raw_cortex_call(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"ask_overwatch_panel_toggle"', app_text)
        self.assertIn('st.expander("Ask OVERWATCH", expanded=True)', app_text)
        self.assertIn("answer_ask_overwatch(", app_text)
        self.assertIn('"rec_automation_board"', (APP_ROOT / "utils" / "ask_overwatch.py").read_text(encoding="utf-8"))
        self.assertIn('"arch_futures_board"', (APP_ROOT / "utils" / "ask_overwatch.py").read_text(encoding="utf-8"))
        self.assertNotIn("Ask OVERWATCH (Evidence Mode)", app_text)
        self.assertNotIn("SNOWFLAKE.CORTEX.COMPLETE", app_text)

    def test_workflow_hubs_replace_scattered_operational_pages(self):
        visible_titles = {section.title for section in SECTION_DEFINITIONS}
        self.assertIn("Alert Center", visible_titles)
        self.assertIn("Workload Operations", visible_titles)
        self.assertIn("Cost & Contract", visible_titles)
        self.assertIn("Security Posture", visible_titles)
        self.assertIn("Change & Drift", visible_titles)
        self.assertIn("Architecture Readiness", visible_titles)
        for retired_title in (
            "Query Workbench",
            "Live Monitor",
            "Detailed Diagnosis",
            "Query Analysis",
            "Query Search & History",
            "Task Management",
            "Pipeline Health",
            "Cost Center",
            "Recommendations & Anomalies",
            "Security & Access",
            "Who Changed What?",
            "DBA Tools",
        ):
            with self.subTest(retired_title=retired_title):
                self.assertNotIn(retired_title, visible_titles)

    def test_visible_sections_have_strict_scorecard_baselines(self):
        self.assertEqual(set(ALL_SECTIONS), set(DBA_CONTROL_PLANE_SECTION_BASELINE))

    def test_dba_control_room_does_not_render_admin_readiness_panel(self):
        dba_control_text = (APP_ROOT / "sections" / "dba_control_room.py").read_text(encoding="utf-8")

        self.assertNotIn("_render_admin_readiness_panel", dba_control_text)
        self.assertNotIn("Admin Readiness to 95", dba_control_text)
        self.assertNotIn("Average Readiness", dba_control_text)
        self.assertNotIn("Sections At 95", dba_control_text)
        self.assertNotIn("dba_control_plane_component_rows", dba_control_text)

    def test_dba_control_room_uses_shared_company_scope_and_cached_release_inventory(self):
        dba_control_text = (APP_ROOT / "sections" / "dba_control_room.py").read_text(encoding="utf-8")

        self.assertIn('get_active_company = _lazy_util("get_active_company")', dba_control_text)
        self.assertIn("company = get_active_company()", dba_control_text)
        self.assertNotIn('st.session_state.get("active_company", "ALFA")', dba_control_text)
        self.assertNotIn("load_task_inventory(session, company, force_refresh=True)", dba_control_text)

    def test_streamlit_width_uses_current_api(self):
        deprecated = []
        for path in APP_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "use_container_width=" in text:
                deprecated.append(str(path.relative_to(APP_ROOT)))

        self.assertEqual(deprecated, [])

    def test_streamlit_manifest_uses_dedicated_app_warehouse(self):
        manifest = (APP_ROOT / "snowflake.yml").read_text(encoding="utf-8")
        self.assertIn("query_warehouse: OVERWATCH_WH", manifest)
        self.assertNotIn("query_warehouse: COMPUTE_WH", manifest)
        self.assertIn("execute_as: CALLER", manifest)
        self.assertIn("main_file: app.py", manifest)
        self.assertIn('title: "OVERWATCH - Snowflake DBA Monitor"', manifest)

    def test_streamlit_deployment_entrypoints_are_pinned(self):
        wrapper = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        cloud_docs = (ROOT / "STREAMLIT_CLOUD_DEPLOY.md").read_text(encoding="utf-8")

        self.assertIn('APP_DIR = Path(__file__).resolve().parent / ".overwatch_final"', wrapper)
        self.assertIn('runpy.run_path(str(APP_DIR / "app.py"), run_name="__main__")', wrapper)
        self.assertIn("showSidebarNavigation = false", config)
        self.assertIn("gatherUsageStats = false", config)
        self.assertIn("Main file path: `streamlit_app.py`", cloud_docs)

    def test_deployment_text_files_do_not_contain_mojibake(self):
        bad_patterns = (
            "\u00e2", "\u00f0", "\ufffd", "\u00c3", "\u00c2",
            "\u20ac\u2122", "\u20ac", "\u0153", "\u017d", "\u0178",
            "\u009d", "\u0090", "\u008d",
        )
        for path in (
            ROOT / "README.md",
            ROOT / "STREAMLIT_CLOUD_DEPLOY.md",
            ROOT / "OVERWATCH_DOCUMENTATION.md",
            ROOT / "OVERWATCH_MANUAL_INPUTS_AND_DDL_RUNBOOK.md",
            APP_ROOT / "snowflake.yml",
        ):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertFalse(any(pattern in text for pattern in bad_patterns))

    def test_local_secret_files_are_ignored(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (
            ".streamlit/secrets.toml",
            ".streamlit/*.toml",
            "!.streamlit/config.toml",
            ".env",
            ".env.*",
            "*.pem",
            "*.key",
        ):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, gitignore)

    def test_architecture_objectives_cover_alfa_prod_dev_and_execution_warehouse(self):
        objectives = {
            (row["ENTITY_TYPE"], row["ENTITY_PATTERN"]): row
            for row in ARCHITECTURE_OBJECTIVES
        }
        self.assertEqual(objectives[("DATABASE", "ALFA_EDW_PROD")]["EXPECTED_ENVIRONMENT"], "PROD")
        self.assertEqual(objectives[("DATABASE", "ALFA_EDW_DEV")]["EXPECTED_ENVIRONMENT"], "DEV_ALL")
        self.assertEqual(objectives[("WAREHOUSE", "OVERWATCH_WH")]["WORKLOAD_CLASS"], "OVERWATCH app execution compute")
        self.assertIn("Dedicated Streamlit app execution warehouse", objectives[("WAREHOUSE", "OVERWATCH_WH")]["ISOLATION_POLICY"])
        self.assertEqual(objectives[("WAREHOUSE", "COMPUTE_WH")]["WORKLOAD_CLASS"], "OVERWATCH mart refresh and utility compute")
        self.assertIn("monitor cost separately", objectives[("WAREHOUSE", "COMPUTE_WH")]["ISOLATION_POLICY"])

    def test_workflow_hubs_expose_expected_subworkflows(self):
        from sections import change_drift, cost_contract, security_posture, workload_operations

        self.assertIn("Query diagnosis", workload_operations.WORKFLOWS)
        self.assertIn("Task graphs", workload_operations.WORKFLOWS)
        self.assertIn("Stored procedures", workload_operations.WORKFLOWS)
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Query diagnosis"], "sections.query_analysis")
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Task graphs"], "sections.task_management")
        self.assertIn("Recommendations and action queue", cost_contract.WORKFLOWS)
        self.assertIn("Budget governance", cost_contract.WORKFLOWS)
        self.assertEqual(cost_contract.WORKFLOW_MODULES["Budget governance"], "sections.budget_governance")
        self.assertEqual(cost_contract.WORKFLOW_MODULES["AI and Cortex spend"], "sections.cortex_monitor")
        self.assertEqual(SECTION_ALIASES["Alerts"], SECTION_BY_TITLE["Alert Center"])
        self.assertIn("Access posture", security_posture.WORKFLOWS)
        self.assertEqual(security_posture.WORKFLOW_MODULES["Access posture"], "sections.security_access")
        self.assertIn("Terraform evidence", change_drift.WORKFLOWS)
        self.assertIn("Jira evidence", change_drift.WORKFLOWS)
        self.assertIn("Schema and object drift", change_drift.WORKFLOWS)
        self.assertIn("Data movement and replication", change_drift.WORKFLOWS)
        self.assertIn("Controlled DBA actions", change_drift.WORKFLOWS)
        self.assertEqual(change_drift.WORKFLOW_MODULES["Controlled DBA actions"], "sections.dba_tools")
        self.assertEqual(change_drift.WORKFLOWS[-1], "Controlled DBA actions")

    def test_workflow_hubs_lazy_load_specialist_modules(self):
        hub_files = {
            "workload_operations.py": [
                "from sections import",
                "live_monitor.render()",
                "task_management.render()",
                "query_search.render()",
            ],
            "cost_contract.py": [
                "from sections import",
                "cost_center.render()",
                "recommendations.render()",
                "cortex_monitor.render()",
            ],
            "security_posture.py": [
                "from sections import",
                "security_access.render()",
                "data_sharing.render()",
            ],
            "change_drift.py": [
                "from sections import",
                "object_change_monitor.render()",
                "stored_proc_tracker.render()",
                "dba_tools.render()",
            ],
        }
        for file_name, removed_patterns in hub_files.items():
            text = (APP_ROOT / "sections" / file_name).read_text(encoding="utf-8")
            with self.subTest(file_name=file_name):
                self.assertIn("WORKFLOW_MODULES", text)
                self.assertIn("render_workflow_module(", text)
                for pattern in removed_patterns:
                    self.assertNotIn(pattern, text)

    def test_cost_contract_detail_workspace_is_opened_on_demand(self):
        text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")

        self.assertIn('_DETAIL_WORKFLOW_KEY = "_cost_contract_detail_workflow"', text)
        self.assertIn('_FULL_COCKPIT_BOARDS_KEY = "_cost_contract_full_cockpit_boards"', text)
        self.assertIn('st.button("Open detail"', text)
        self.assertIn('st.button("Open full cockpit boards"', text)
        self.assertIn("st.session_state.pop(_FULL_COCKPIT_BOARDS_KEY, None)", text)
        self.assertIn("if open_workflow == workflow:", text)
        self.assertIn("render_workflow_module(workflow, WORKFLOW_MODULES)", text)

    def test_navigation_labels_are_plain_titles(self):
        for section in ALL_SECTIONS:
            with self.subTest(section=section):
                self.assertEqual(section, section.strip())
                self.assertTrue(all(ord(ch) < 128 for ch in section))

    def test_global_filter_and_metric_changes_clear_loaded_state(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        cache_text = (APP_ROOT / "utils" / "cache.py").read_text(encoding="utf-8")
        query_text = (APP_ROOT / "utils" / "query.py").read_text(encoding="utf-8")
        state_keys_text = (APP_ROOT / "utils" / "state_keys.py").read_text(encoding="utf-8")
        self.assertIn("def _global_filter_signature", app_text)
        self.assertIn("def _metric_settings_signature", app_text)
        self.assertIn("previous_filter_signature != current_filter_signature", app_text)
        self.assertIn("previous_metric_signature != current_metric_signature", app_text)
        self.assertIn("clear_all_cache()", app_text)
        self.assertIn("clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)", app_text)
        self.assertIn("bump_global_cache_salt", cache_text)
        self.assertIn('st.session_state["_refresh_salt_global"]', cache_text)
        self.assertNotIn("st.cache_data.clear()", cache_text)
        self.assertIn('st.session_state.get("_refresh_salt_global"', query_text)
        self.assertIn('st.session_state.get("global_environment"', query_text)
        self.assertNotIn('st.session_state.get("exceptions_only_mode"', query_text)
        self.assertIn('st.session_state.get("_overwatch_current_role"', query_text)
        self.assertIn("_query_tag", query_text)
        for prefix in (
            '"task_ops_"',
            '"task_sla_"',
            '"sp_ops_"',
            '"sp_sla_"',
            '"alert_center_"',
            '"cost_contract_"',
            '"pipe_"',
            '"qw_"',
            '"sf_value_"',
            '"arch_"',
            '"change_drift_summary"',
            '"security_posture_summary"',
        ):
            with self.subTest(prefix=prefix):
                self.assertIn(prefix, cache_text)
        self.assertIn('"_prev_global_filter_signature"', state_keys_text)
        self.assertIn('"_prev_metric_settings_signature"', state_keys_text)

    def test_current_role_is_seeded_from_snowflake_secrets(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("def _seed_current_role_from_secrets", app_text)
        self.assertIn('snowflake_cfg.get("role")', app_text)
        self.assertIn("_seed_current_role_from_secrets()", app_text)

    def test_sidebar_saved_views_are_explicit_load_only(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        bookmarks_text = (APP_ROOT / "utils" / "bookmarks.py").read_text(encoding="utf-8")
        self.assertIn("_overwatch_saved_views_loaded", app_text)
        self.assertIn("_overwatch_saved_views_cache", app_text)
        self.assertIn("Saved views are skipped during normal reruns", app_text)
        self.assertNotIn("bookmarks = load_bookmarks(_session) if _session else []", app_text)
        self.assertIn('bookmark_name = str(st.session_state.get("bm_name_input") or new_bm_name or "").strip()', app_text)
        self.assertIn("Enter a bookmark name before saving.", app_text)
        self.assertNotIn("disabled=not new_bm_name", app_text)
        self.assertIn("raise", bookmarks_text.split("def load_bookmarks", 1)[1].split("def apply_bookmark", 1)[0])

    def test_section_switches_clear_stale_body_during_render(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")

        self.assertIn("def _queue_section_navigation", app_text)
        self.assertIn('CONNECTION_OPTIONAL_SECTIONS = {"Alert Center"}', app_text)
        self.assertIn("def _section_requires_connection", app_text)
        self.assertIn("_overwatch_pending_section", app_text)
        self.assertIn("def _section_render_signature", app_text)
        self.assertIn("_overwatch_last_section_render_signature", app_text)
        self.assertIn("def _should_show_section_transition", app_text)
        self.assertIn('has_prior_render = "_overwatch_last_section_render_signature" in st.session_state', app_text)
        self.assertIn('has_pending_navigation = "_overwatch_pending_section" in st.session_state', app_text)
        self.assertIn("transition_slot = st.empty()", app_text)
        self.assertIn("section_slot = st.empty()", app_text)
        self.assertIn("_render_section_transition_state(active_section)", app_text)
        self.assertIn("with section_slot.container():", app_text)
        self.assertIn("sections.dispatch(active_section)", app_text)
        self.assertIn("needs_connection = _section_requires_connection(active_section)", app_text)
        self.assertIn("if needs_connection and (not connection_available", app_text)
        self.assertIn("transition_slot.empty()", app_text)
        self.assertIn(".ow-section-transition", theme_text)
        self.assertIn("position: fixed", theme_text)

    def test_app_shell_header_renders_before_sidebar_hydration(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")

        header_index = app_text.index("_render_app_header(active_section, active_company, credit_price, current_role)")
        sidebar_index = app_text.index("with st.sidebar:")
        self.assertLess(header_index, sidebar_index)
        self.assertIn("def _current_active_section", app_text)
        self.assertIn("def _current_credit_price", app_text)
        self.assertIn("def _sidebar_panel_toggle", app_text)
        self.assertIn('if _sidebar_panel_toggle("Saved Views", "saved_views")', app_text)
        self.assertIn('if _sidebar_panel_toggle("Global Filters", "global_filters")', app_text)
        self.assertIn('if _sidebar_panel_toggle("Settings", "settings")', app_text)
        self.assertEqual(app_text.count('if _sidebar_panel_toggle("Global Filters", "global_filters")'), 1)
        self.assertNotIn("Command Palette", app_text)
        self.assertNotIn("command_palette", app_text)
        self.assertNotIn('with st.expander("Saved Views", expanded=False)', app_text)
        self.assertNotIn('with st.expander("Global Filters", expanded=False)', app_text)
        self.assertNotIn('with st.expander("Settings", expanded=False)', app_text)
        self.assertLess(app_text.index('"Company view"'), app_text.index('if _sidebar_panel_toggle("Global Filters", "global_filters")'))
        self.assertLess(app_text.index('if _sidebar_panel_toggle("Global Filters", "global_filters")'), app_text.index('"Exceptions-only mode"'))
        self.assertLess(app_text.index('"Exceptions-only mode"'), app_text.index('if _sidebar_panel_toggle("Saved Views", "saved_views")'))
        self.assertLess(app_text.index('if _sidebar_panel_toggle("Saved Views", "saved_views")'), app_text.index('if _sidebar_panel_toggle("Settings", "settings")'))

    def test_sidebar_collapse_reopen_control_remains_visible(self):
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")

        self.assertNotIn('[data-testid="stHeader"],\n[data-testid="stToolbar"]', theme_text)
        self.assertIn('[data-testid="stHeader"] {', theme_text)
        self.assertIn('[data-testid="stSidebarCollapsedControl"]', theme_text)
        self.assertIn('[data-testid="stSidebarCollapseButton"]', theme_text)
        self.assertIn('[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarCollapseButton"]', theme_text)
        self.assertIn('[data-testid="stSidebar"][aria-expanded="false"] {', theme_text)
        self.assertIn("width: 3.25rem !important;", theme_text)
        self.assertIn("transform: none !important;", theme_text)
        self.assertIn("pointer-events: auto !important;", theme_text)
        self.assertIn("min-width: 2.25rem !important;", theme_text)

    def test_current_sections_have_operating_guides(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")

        self.assertNotIn("render_section_operating_guide(active_section)", app_text)
        self.assertIn("clear_deferred_section_notes(active_section)", app_text)
        self.assertIn("render_deferred_section_notes(active_section)", app_text)
        self.assertNotIn("render_section_reference(active_section)", app_text)
        self.assertEqual(set(ALL_SECTIONS), set(SECTION_OPERATING_GUIDE))
        for section, guide in SECTION_OPERATING_GUIDE.items():
            with self.subTest(section=section):
                self.assertEqual(
                    set(guide),
                    {"first_move", "evidence", "closure", "guardrail"},
                )
                for value in guide.values():
                    self.assertGreaterEqual(len(str(value).split()), 7)
                self.assertNotIn("best practice", " ".join(guide.values()).lower())
        self.assertIn("Database-attributed cost is Allocated/Estimated", SECTION_OPERATING_GUIDE["Cost & Contract"]["guardrail"])
        self.assertIn("Email is the active channel", SECTION_OPERATING_GUIDE["Alert Center"]["guardrail"])
        self.assertIn("Login-only findings have no database context", SECTION_OPERATING_GUIDE["Account Health"]["guardrail"])
        self.assertIn("clustering-depth", SECTION_OPERATING_GUIDE["Architecture Readiness"]["guardrail"])
        self.assertIn(".ow-section-guide", theme_text)

    def test_current_sections_have_evidence_contracts(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        guidance_text = (APP_ROOT / "utils" / "section_guidance.py").read_text(encoding="utf-8")

        self.assertNotIn("render_section_confidence_meter(active_section", app_text)
        self.assertNotIn("render_section_operating_guide(active_section)", app_text)
        self.assertIn("render_deferred_section_notes(active_section)", app_text)
        self.assertNotIn("render_section_reference(active_section)", app_text)
        self.assertNotIn("render_section_evidence_contract(active_section)", app_text)
        self.assertIn('st.expander("Notes / Evidence", expanded=False)', guidance_text)
        self.assertEqual(set(ALL_SECTIONS), set(SECTION_EVIDENCE_CONTRACT))
        for section, rows in SECTION_EVIDENCE_CONTRACT.items():
            with self.subTest(section=section):
                self.assertGreaterEqual(len(rows), 2)
                for row in rows:
                    self.assertEqual(
                        set(row),
                        {"source", "confidence", "decision_use", "invalid_use", "proof"},
                    )
                    self.assertTrue(str(row["source"]).strip())
                    self.assertTrue(str(row["confidence"]).strip())
                    for key in ("decision_use", "invalid_use", "proof"):
                        self.assertGreaterEqual(len(str(row[key]).split()), 3)
        self.assertIn("Allocated/Estimated", SECTION_EVIDENCE_CONTRACT["Cost & Contract"][1]["confidence"])
        self.assertIn("Email-first", SECTION_EVIDENCE_CONTRACT["Alert Center"][1]["confidence"])
        self.assertIn("Do not apply environment filters", SECTION_EVIDENCE_CONTRACT["Account Health"][0]["invalid_use"])
        self.assertIn("Do not split exact spend by database", SECTION_EVIDENCE_CONTRACT["Warehouse Health"][0]["invalid_use"])
        architecture_invalid_uses = " ".join(
            row["invalid_use"] for row in SECTION_EVIDENCE_CONTRACT["Architecture Readiness"]
        )
        self.assertIn("Do not run clustering-depth", architecture_invalid_uses)
        self.assertIn("Do not auto-change agents", architecture_invalid_uses)
        self.assertIn(".ow-evidence-contract", theme_text)
        self.assertIn("lru_cache", guidance_text)
        self.assertIn("@lru_cache(maxsize=16)", guidance_text)
        self.assertNotIn("build_section_confidence_meter", guidance_text)
        self.assertNotIn("render_section_confidence_meter", guidance_text)
        self.assertNotIn("SECTION_SOURCE_HEALTH_STATE_KEYS", guidance_text)
        self.assertNotIn("_SOURCE_HEALTH_FALLBACK_SCAN_LIMIT", guidance_text)
        self.assertNotIn(".ow-confidence-gauge-track", theme_text)
        self.assertNotIn(".ow-confidence-gauge-marker", theme_text)
        self.assertNotIn(".ow-confidence-mix-item", theme_text)
        self.assertNotIn(".ow-confidence-meter", theme_text)
        self.assertNotIn("ow-confidence-chip", theme_text)
        self.assertNotIn("ow-confidence-chip", guidance_text)
        self.assertNotIn("ow-confidence-card-detail", theme_text)
        self.assertNotIn("ow-confidence-card-detail", guidance_text)
        self.assertNotIn("The OVERWATCH shell is loaded", app_text)

    def test_priority_tables_defer_full_raw_detail_rendering(self):
        workflows_text = (APP_ROOT / "utils" / "workflows.py").read_text(encoding="utf-8")
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        stored_proc_text = (APP_ROOT / "sections" / "stored_proc_tracker.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        self.assertIn("Full detail rendering is deferred", workflows_text)
        self.assertIn('st.button("Render full detail"', workflows_text)
        self.assertIn('CONTEXT_PRIORITY_COLUMNS = ("ENVIRONMENT", "DATABASE_NAME", "SCHEMA_NAME")', workflows_text)
        self.assertIn("def prioritize_context_columns", workflows_text)
        self.assertIn("prioritize_context_columns(df)", workflows_text)
        self.assertIn("from .workflows import prioritize_context_columns", display_text)
        self.assertIn('grid_df = prioritize_context_columns(df.head(1000), leading_columns=("QUERY_ID",))', display_text)
        self.assertIn("database_name, schema_name", display_text)
        self.assertIn("def _procedure_scope_key", stored_proc_text)
        self.assertIn("PROCEDURE_CONTEXT", stored_proc_text)
        self.assertIn("Proc Signatures", stored_proc_text)
        self.assertNotIn("Unique Proc Signatures", stored_proc_text)
        self.assertIn("white-space: normal", theme_text)
        self.assertIn("overflow-wrap: anywhere", theme_text)
        self.assertIn("def render_ranked_bar_chart", display_text)
        self.assertIn("sort=alt.SortField(field=measure, order=\"descending\")", display_text)
        self.assertIn("y=alt.Y(", display_text)
        self.assertIn('st.button("Load"', display_text)
        self.assertIn("requested_key", display_text)
        self.assertIn("if requested != selected:", display_text)

    def test_ranked_chart_frame_orders_metrics_descending(self):
        from utils.display import rank_chart_frame

        df = pd.DataFrame({
            "NAME": ["Small", "Large", "Small", "Medium"],
            "VALUE": [2, 9, 3, 5],
        })
        ranked = rank_chart_frame(df, "NAME", "VALUE", top_n=3)
        self.assertEqual(ranked["NAME"].tolist(), ["Large", "Small", "Medium"])
        self.assertEqual(ranked["VALUE"].tolist(), [9, 5, 5])

    def test_workflow_helpers_keep_landing_pages_compact(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        sections_text = (APP_ROOT / "sections" / "__init__.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        workflows_text = (APP_ROOT / "utils" / "workflows.py").read_text(encoding="utf-8")

        self.assertIn("WORKFLOWS_VERSION", workflows_text)
        self.assertIn("WORKFLOWS_VERSION", app_text)
        self.assertIn("reload_loaded_sections()", app_text)
        self.assertIn("def reload_loaded_sections()", sections_text)
        self.assertIn("help=details.get(workflow) or None", workflows_text)
        self.assertNotIn("st.caption(details[workflow])", workflows_text)
        self.assertIn("from .section_guidance import defer_section_note", workflows_text)
        self.assertIn("defer_source_note", workflows_text)
        self.assertIn("defer_section_note(summary)", workflows_text)
        self.assertIn("defer_source_note(*parts)", workflows_text)
        self.assertNotIn("with st.expander(str(title), expanded=False)", workflows_text)
        self.assertNotIn("ow-brief-strip-collapsed", workflows_text)
        self.assertNotIn("ow-brief-title", workflows_text)
        self.assertNotIn("ow-brief-title", theme_text)
        duplicate_headers = [
            ("dba_control_room.py", 'st.header("DBA Control Room")'),
            ("alert_center.py", 'st.header("Alert Center")'),
            ("cost_contract.py", 'st.header("Cost & Contract")'),
            ("workload_operations.py", 'st.header("Workload Operations")'),
            ("security_posture.py", 'st.header("Security Posture")'),
            ("change_drift.py", 'st.header("Change & Drift")'),
            ("architecture_readiness.py", 'st.header("Architecture Readiness")'),
            ("architecture_readiness.py", 'st.header("Snowflake Architecture Readiness")'),
            ("account_health.py", 'st.header("Account Health - Command Center")'),
        ]
        for filename, marker in duplicate_headers:
            with self.subTest(filename=filename):
                section_text = (APP_ROOT / "sections" / filename).read_text(encoding="utf-8")
                self.assertNotIn(marker, section_text)

    def test_app_performance_hot_paths_are_deferred_or_cached(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        query_text = (APP_ROOT / "utils" / "query.py").read_text(encoding="utf-8")
        session_text = (APP_ROOT / "utils" / "session.py").read_text(encoding="utf-8")
        logging_text = (APP_ROOT / "utils" / "logging.py").read_text(encoding="utf-8")
        metadata_text = (APP_ROOT / "utils" / "metadata.py").read_text(encoding="utf-8")
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        cache_text = (APP_ROOT / "utils" / "cache.py").read_text(encoding="utf-8")
        cost_center_text = (APP_ROOT / "sections" / "cost_center.py").read_text(encoding="utf-8")
        cost_contract_text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        executive_landing_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")
        cortex_text = (APP_ROOT / "sections" / "cortex_monitor.py").read_text(encoding="utf-8")
        account_health_text = (APP_ROOT / "sections" / "account_health.py").read_text(encoding="utf-8")
        warehouse_health_text = (APP_ROOT / "sections" / "warehouse_health.py").read_text(encoding="utf-8")
        change_drift_text = (APP_ROOT / "sections" / "change_drift.py").read_text(encoding="utf-8")
        alert_center_text = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        dba_control_text = (APP_ROOT / "sections" / "dba_control_room.py").read_text(encoding="utf-8")
        security_posture_text = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
        security_posture_import_block = security_posture_text.split("SECURITY_POSTURE_VIEWS", 1)[0]
        security_access_text = (APP_ROOT / "sections" / "security_access.py").read_text(encoding="utf-8")
        recommendations_text = (APP_ROOT / "sections" / "recommendations.py").read_text(encoding="utf-8")
        live_monitor_text = (APP_ROOT / "sections" / "live_monitor.py").read_text(encoding="utf-8")
        query_analysis_text = (APP_ROOT / "sections" / "query_analysis.py").read_text(encoding="utf-8")
        query_workbench_text = (APP_ROOT / "sections" / "query_workbench.py").read_text(encoding="utf-8")
        query_search_text = (APP_ROOT / "sections" / "query_search.py").read_text(encoding="utf-8")
        pipeline_health_text = (APP_ROOT / "sections" / "pipeline_health.py").read_text(encoding="utf-8")
        workload_operations_text = (APP_ROOT / "sections" / "workload_operations.py").read_text(encoding="utf-8")
        workload_operations_import_block = workload_operations_text.split("WORKLOAD_OPERATIONS_VIEWS", 1)[0]
        spcs_text = (APP_ROOT / "sections" / "spcs_tracker.py").read_text(encoding="utf-8")
        data_sharing_text = (APP_ROOT / "sections" / "data_sharing.py").read_text(encoding="utf-8")
        object_change_text = (APP_ROOT / "sections" / "object_change_monitor.py").read_text(encoding="utf-8")
        adoption_text = (APP_ROOT / "sections" / "adoption_analytics.py").read_text(encoding="utf-8")
        platform_text = (APP_ROOT / "sections" / "platform_topology.py").read_text(encoding="utf-8")
        architecture_text = (APP_ROOT / "sections" / "architecture_readiness.py").read_text(encoding="utf-8")
        usage_overview_text = (APP_ROOT / "sections" / "usage_overview.py").read_text(encoding="utf-8")
        optimization_text = (APP_ROOT / "utils" / "optimization_advisor.py").read_text(encoding="utf-8")
        downloads_text = (APP_ROOT / "utils" / "downloads.py").read_text(encoding="utf-8")
        dba_tool_catalog_text = (APP_ROOT / "utils" / "dba_tool_catalog.py").read_text(encoding="utf-8")
        dba_tools_text = (APP_ROOT / "sections" / "dba_tools.py").read_text(encoding="utf-8")
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        task_management_text = (APP_ROOT / "sections" / "task_management.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        data_text = (APP_ROOT / "utils" / "data.py").read_text(encoding="utf-8")
        top_import_block = app_text.split("def _snapshot_ask_overwatch_state", 1)[0]

        self.assertIn("Query activity summaries are rendered on demand", app_text)
        self.assertIn('st.button("Render query activity summary"', app_text)
        self.assertNotIn("from utils.ask_overwatch import answer_ask_overwatch", top_import_block)
        self.assertIn("from utils.ask_overwatch import answer_ask_overwatch", app_text)
        self.assertNotIn("from utils.bookmarks import (", top_import_block)
        self.assertIn("def _load_bookmark_helpers", app_text)
        self.assertNotIn("import utils.display as display_module", top_import_block)
        self.assertNotIn("import utils.workflows as workflows_module", top_import_block)
        self.assertIn("def _maybe_reload_dev_helpers", app_text)
        self.assertIn('st.session_state.get("_overwatch_dev_reload_helpers", False)', app_text)
        self.assertIn('st.session_state["_logging_enabled"] = False', app_text)
        self.assertIn('"Record section runtime"', app_text)
        self.assertIn('"Record query activity"', app_text)
        self.assertIn("section_render_started = time.perf_counter()", app_text)
        self.assertIn("log_section_load(active_section, duration_ms)", app_text)
        self.assertIn('st.session_state["_detailed_query_tags_enabled"] = False', app_text)
        self.assertIn('"Detailed Snowflake query tags"', app_text)
        self.assertIn("import threading", query_text)
        self.assertIn("_QUERY_CACHE_LOCKS", query_text)
        self.assertIn("def _get_query_cache_lock", query_text)
        self.assertIn("with _get_query_cache_lock(executable_query, context, cache_salt, tier):", query_text)
        self.assertIn("def _cached_raise_historical", query_text)
        self.assertIn("_RAISE_TIER_FN", query_text)
        self.assertIn("use_cache: bool = True", query_text)
        self.assertIn("fn = _RAISE_TIER_FN.get(tier, _cached_raise_recent)", query_text)
        self.assertIn("st.session_state.get(_ENABLED_KEY, False)", logging_text)
        self.assertIn("if not is_query_logging_enabled():", logging_text)
        self.assertNotIn("not is_logging_enabled() or not is_query_logging_enabled()", logging_text)
        self.assertIn("_overwatch_show_statement_cache", metadata_text)
        self.assertIn("_SHOW_CACHE_TTL_SECONDS = 300", metadata_text)
        self.assertIn("force_refresh: bool = False", metadata_text)
        self.assertIn("return frame.copy()", metadata_text)
        self.assertIn("force_refresh=bool(refresh_wh)", dba_tools_text)
        self.assertIn("force_inventory_refresh=True", task_management_text)
        self.assertIn("def load_live_task_runs", metadata_text)
        self.assertIn("INFORMATION_SCHEMA.TASK_HISTORY", metadata_text)
        self.assertIn("TASK_NAME =>", metadata_text)
        self.assertIn("session.sql(sql).collect()", metadata_text)
        self.assertIn("pd.DataFrame([row.as_dict() for row in rows])", metadata_text)
        self.assertIn("load_live_task_runs(session, tl, hours_back=6)", task_management_text)
        self.assertIn("load_live_task_runs(session, df_tasks, hours_back=6)", dba_tools_text)
        self.assertIn('st.form(f"tm_cancel_query_form_{selected_query}")', task_management_text)
        self.assertIn('st.form(f"tm_cancel_graph_form_{selected_graph}")', task_management_text)
        self.assertIn('st.form(f"tg_cancel_run_query_form_{sel_qid}")', dba_tools_text)
        self.assertIn('st.form(f"tg_cancel_graph_form_{sel_graph}")', dba_tools_text)
        self.assertIn("_task_management_execution_context_cache", task_management_text)
        self.assertIn("_EXECUTION_CONTEXT_CACHE_TTL_SECONDS = 300", task_management_text)
        self.assertIn("def _require_typed_confirmation", dba_tools_text)
        self.assertIn("def _require_typed_confirmation", task_management_text)
        self.assertNotIn("disabled=admin_button_disabled(not wh_confirmed)", dba_tools_text)
        self.assertNotIn("disabled=admin_button_disabled(not cortex_confirmed)", dba_tools_text)
        self.assertNotIn("disabled=admin_button_disabled(not task_confirmed)", dba_tools_text)
        self.assertNotIn("disabled=admin_button_disabled(not graph_confirmed)", dba_tools_text)
        self.assertNotIn("disabled=admin_button_disabled(not confirmed)", task_management_text)
        self.assertNotIn("disabled=admin_button_disabled(not exec_confirmed)", task_management_text)
        self.assertIn('"Check Fast Snapshot"', dba_control_text)
        self.assertIn("Fast mart snapshot lookup is on demand", dba_control_text)
        self.assertNotIn("load_latest_control_room_mart(company, max_age_hours=6) if snapshot_scope_ok else None", dba_control_text)
        self.assertIn('"Fast Watch"', dba_control_text)
        self.assertIn('"Operations Board"', dba_control_text)
        self.assertNotIn('"App Operations"', dba_control_text)
        self.assertIn('"Load Operations Board"', dba_control_text)
        self.assertIn("Use Operations Board when you need route priority", dba_control_text)
        self.assertIn("Action Brief", dba_control_text)
        self.assertNotIn("All alert history, email-ready messages, suppression windows", dba_control_text)
        self.assertIn("def _render_app_performance_guardrail", dba_control_text)
        self.assertIn("def _running_in_streamlit_in_snowflake", dba_control_text)
        self.assertIn("External release-check files are not available inside Streamlit-in-Snowflake", dba_control_text)
        self.assertIn("_latest_local_snowflake_suite_result", dba_control_text)
        self.assertIn("dba_effective_readiness_score", dba_control_text)
        self.assertIn('"EFFECTIVE_SCORE"', dba_control_text)
        self.assertIn('"DEPLOYMENT_LABEL"', dba_control_text)
        self.assertIn('"GATE_DRIVERS"', dba_control_text)
        self.assertIn('"Severity", "Signal", "Evidence", "Action", "Route", "Workflow"', dba_control_text)
        self.assertNotIn('"SEVERITY", "DOMAIN", "SIGNAL", "ENTITY", "DETAIL"', dba_control_text)
        self.assertIn("_RESULT_SIZE_SAMPLE_ROWS", query_text)
        self.assertIn("OVERWATCH_PERF_RUN_ID", query_text)
        self.assertIn('"perf_run_id": _perf_run_id()', query_text)
        self.assertIn('st.session_state.get("_detailed_query_tags_enabled", False)', query_text)
        self.assertIn('return "OVERWATCH"', query_text)
        self.assertNotIn("OVERWATCH:v3", query_text)
        self.assertIn("PERF_RUN_ID", logging_text)
        self.assertIn('_QUERY_TAG = "OVERWATCH"', session_text)
        self.assertNotIn("OVERWATCH:v3", session_text)
        self.assertNotIn("for stmt in [", session_text)
        self.assertIn("ALTER SESSION SET ", session_text)
        self.assertIn("STATEMENT_TIMEOUT_IN_SECONDS", session_text)
        self.assertIn('st.session_state["_overwatch_active_query_tag"] = _QUERY_TAG', session_text)
        self.assertIn("from utils.cache import clear_all_cache", app_text)
        self.assertNotIn("from utils.display import clear_all_cache", app_text)
        self.assertIn("_overwatch_show_statement_cache", cache_text)
        self.assertIn("_task_management_execution_context_cache", cache_text)
        self.assertIn("from .cache import clear_all_cache", display_text)
        self.assertIn("from .downloads import download_csv, mark_loaded, show_loaded_time", display_text)
        self.assertNotIn("def _csv_download_payload", display_text)
        self.assertIn("def _csv_download_payload", downloads_text)
        self.assertNotIn("import pandas", downloads_text)
        self.assertIn("max_entries=32", downloads_text)
        self.assertIn('st.session_state.get("_query_logging_enabled", False)', query_text)
        self.assertIn("_COMBINED_CSS_CACHE", theme_text)
        self.assertIn("_has_company_scope_columns", data_text)
        self.assertNotIn("render_section_confidence_meter(active_section, st.session_state)", app_text)
        self.assertNotIn("render_section_operating_guide(active_section)", app_text)
        self.assertIn("render_deferred_section_notes(active_section)", app_text)
        self.assertIn('secondary_chrome_ready = bool(st.session_state.get("_overwatch_secondary_chrome_ready"))', app_text)
        self.assertIn("if secondary_chrome_ready:", app_text)
        self.assertIn('st.session_state["_overwatch_secondary_chrome_ready"] = True', app_text)
        self.assertNotIn("render_section_confidence_meter(active_section, dict(st.session_state))", app_text)
        self.assertNotIn("dict(state).items()", (APP_ROOT / "utils" / "section_guidance.py").read_text(encoding="utf-8"))
        executive_landing_import_block = executive_landing_text.split("EXECUTIVE_LANDING_VERSION", 1)[0]
        self.assertNotIn("import pandas as pd", executive_landing_import_block)
        self.assertNotIn("from utils import (", executive_landing_import_block)
        self.assertNotIn("from utils.workflows import render_priority_dataframe", executive_landing_import_block)
        self.assertIn("class _LazyPandas", executive_landing_text)
        self.assertIn('st.button("Load Executive Snapshot"', executive_landing_text)
        self.assertIn("cc_user_profile_requested", cost_center_text)
        self.assertIn('"Cost Explorer"', cost_center_text)
        self.assertIn("COST_EXPLORER_LENSES", cost_center_text)
        self.assertIn("build_mart_cost_explorer_sql", cost_center_text)
        self.assertIn("FACT_CHARGEBACK_DAILY", cost_center_text)
        self.assertIn("Cost attribution gaps", cost_center_text)
        self.assertIn("Save cost explorer outliers to Action Queue", cost_center_text)
        self.assertIn('st.button("Load"', cost_center_text)
        self.assertIn("_build_cost_allocation_trust_board", cost_contract_text)
        self.assertIn("Cost Allocation Trust", cost_contract_text)
        self.assertIn("_build_cost_drilldown_command_map", cost_contract_text)
        self.assertIn("Cost Drilldown Command Map", cost_contract_text)
        self.assertIn('sort_by=["COMMAND_PRIORITY", "DRILLDOWN"]', cost_contract_text)
        self.assertIn("ACCOUNT_HEALTH_PANES", account_health_text)
        self.assertIn('st.selectbox(\n        "Account Health view"', account_health_text)
        self.assertNotIn("st.tabs(", account_health_text)
        self.assertIn('st.button("Load / Refresh Health"', account_health_text)
        self.assertIn("if not refresh_health:", account_health_text)
        self.assertNotIn("or cache_age > 300", account_health_text)
        self.assertIn("def _render_account_health_action_brief", account_health_text)
        self.assertIn("def _render_account_health_operating_snapshot", account_health_text)
        self.assertIn("Operating Snapshot", account_health_text)
        self.assertIn("Secondary metrics and source", account_health_text)
        self.assertIn('st.button("Load Secondary Evidence"', account_health_text)
        self.assertNotIn("Evidence details", account_health_text)
        self.assertNotIn("Current Surfaces", account_health_text)
        self.assertNotIn("Failed Login Users", account_health_text)
        self.assertNotIn("Admin Role Reviews", account_health_text)
        self.assertNotIn("Observed Components", account_health_text)
        self.assertIn('"Account Health detail"', account_health_text)
        self.assertIn('st.selectbox(\n            "Account Health detail"', account_health_text)
        self.assertNotIn('st.radio(\n            "Account Health detail"', account_health_text)
        self.assertIn('("Checklist", "Gates", "Interventions", "Controls", "Operability")', account_health_text)
        self.assertNotIn("k1, k2, k3, k4, k5, k6 = st.columns(6)", account_health_text)
        account_health_import_block = account_health_text.split("CHECKLIST_HISTORY_TABLE", 1)[0]
        self.assertIn("from __future__ import annotations", account_health_import_block)
        self.assertNotIn("import pandas as pd", account_health_import_block)
        self.assertNotIn("from utils import (", account_health_import_block)
        self.assertNotIn("from utils.workflows import", account_health_import_block)
        self.assertIn("class _LazyPandas", account_health_text)
        self.assertIn('render_priority_dataframe = _lazy_util("render_priority_dataframe")', account_health_text)
        self.assertIn("def _account_health_has_source_state", account_health_text)
        self.assertIn("if _account_health_has_source_state(st.session_state):", account_health_text)
        for label, section_text, split_marker in (
            ("Warehouse Health", warehouse_health_text, "WAREHOUSE_HEALTH_VIEWS"),
            ("Change & Drift", change_drift_text, "WORKFLOWS"),
            ("Cost & Contract", cost_contract_text, "WORKFLOWS"),
        ):
            with self.subTest(lazy_pandas_section=label):
                section_import_block = section_text.split(split_marker, 1)[0]
                self.assertNotIn("import pandas as pd", section_import_block)
                self.assertIn("class _LazyPandas", section_text)
        warehouse_health_import_block = warehouse_health_text.split("WAREHOUSE_HEALTH_VIEWS", 1)[0]
        self.assertNotIn("from utils import (", warehouse_health_import_block)
        self.assertNotIn("from utils.workflows import", warehouse_health_import_block)
        self.assertIn("def render_workflow_selector", warehouse_health_text)
        self.assertIn('render_priority_dataframe = _lazy_util("render_priority_dataframe")', warehouse_health_text)
        self.assertIn("def _change_has_source_state", change_drift_text)
        self.assertIn("if _change_has_source_state(st.session_state):", change_drift_text)
        change_drift_import_block = change_drift_text.split("WORKFLOWS", 1)[0]
        self.assertNotIn("from utils import (", change_drift_import_block)
        self.assertNotIn("from utils.workflows import", change_drift_import_block)
        self.assertIn("def render_workflow_selector", change_drift_text)
        self.assertIn("def render_signal_confidence", change_drift_text)
        self.assertIn("def render_workflow_module", change_drift_text)
        self.assertIn('render_priority_dataframe = _lazy_util("render_priority_dataframe")', change_drift_text)
        self.assertIn("return str(st.selectbox(label, list(workflows), key=key))", change_drift_text)
        self.assertNotIn('key=f"{key}_{start}_{workflow}"', change_drift_text)
        self.assertIn("def _change_action_brief", change_drift_text)
        self.assertIn("def _render_change_action_brief", change_drift_text)
        self.assertIn("def _looks_like_frame", cost_contract_text)
        self.assertIn("data_is_frame = _looks_like_frame(data)", cost_contract_text)
        cost_contract_import_block = cost_contract_text.split("WORKFLOWS", 1)[0]
        self.assertNotIn("from utils import (", cost_contract_import_block)
        self.assertNotIn("from utils.workflows import", cost_contract_import_block)
        self.assertIn("def render_workflow_selector", cost_contract_text)
        self.assertIn("def render_signal_confidence", cost_contract_text)
        self.assertIn("def render_workflow_module", cost_contract_text)
        self.assertIn('render_priority_dataframe = _lazy_util("render_priority_dataframe")', cost_contract_text)
        self.assertIn("return str(st.selectbox(label, list(workflows), key=key))", cost_contract_text)
        self.assertNotIn('key=f"{key}_{start}_{workflow}"', cost_contract_text)
        self.assertIn("def _cost_action_brief", cost_contract_text)
        self.assertIn("def _render_cost_action_brief", cost_contract_text)
        self.assertIn("def _render_cost_operating_snapshot", cost_contract_text)
        self.assertIn('st.markdown("**Operating Snapshot**")', cost_contract_text)
        self.assertIn('cols = st.columns(4)', cost_contract_text)
        self.assertIn('key="cost_contract_cockpit_window"', cost_contract_text)
        cost_watch_preload = cost_contract_text.split("def _render_cost_watch_floor", 1)[1].split(
            "if st.button(\"Load Cost Cockpit\"",
            1,
        )[0]
        self.assertNotIn("pd.DataFrame", cost_watch_preload)
        self.assertIn('st.button("Load Operability Mart"', account_health_text)
        self.assertIn("_account_health_operator_next_moves", account_health_text)
        self.assertIn("Account Health operator next-move gates", account_health_text)
        self.assertIn("_account_health_intervention_matrix", account_health_text)
        self.assertIn("Account Health DBA intervention matrix", account_health_text)
        self.assertIn('sort_by=["DBA_PRIORITY", "COUNT", "SURFACE"]', account_health_text)
        account_health_before_secondary = account_health_text.split('if active_view == "Overview":', 1)[1].split(
            'st.button("Load Secondary Evidence"',
            1,
        )[0]
        self.assertNotIn("build_mart_control_room_warehouse_pressure_sql", account_health_before_secondary)
        account_health_render_preload = account_health_text.split("def render():", 1)[1].split(
            "active_view = st.selectbox",
            1,
        )[0]
        self.assertIn('st.selectbox(\n        "Account Health view"', account_health_text)
        self.assertNotIn('st.radio(\n        "Account Health view"', account_health_text)
        self.assertIn("def _account_health_action_session", account_health_text)
        self.assertIn("get_session_for_action", account_health_text)
        self.assertIn("def _account_query_history_capabilities", account_health_text)
        self.assertIn("qh = _query_history_capabilities(action_session)", account_health_text)
        self.assertNotIn("session = get_session()", account_health_render_preload)
        self.assertNotIn("filter_existing_columns(", account_health_render_preload)
        self.assertIn("Cost guardrail", warehouse_health_text)
        self.assertIn("_warehouse_intervention_matrix", warehouse_health_text)
        self.assertIn("Warehouse DBA intervention matrix", warehouse_health_text)
        self.assertIn('sort_by=["DBA_PRIORITY", "METERED_CREDITS"]', warehouse_health_text)
        self.assertIn("return str(st.selectbox(label, list(workflows), key=key))", warehouse_health_text)
        self.assertNotIn('key=f"{key}_{start}_{workflow}"', warehouse_health_text)
        self.assertIn("def _warehouse_action_brief", warehouse_health_text)
        self.assertIn("def _render_warehouse_action_brief", warehouse_health_text)
        self.assertIn("def _render_warehouse_operating_snapshot", warehouse_health_text)
        self.assertIn('st.markdown("**Action Brief**")', warehouse_health_text)
        self.assertIn('st.markdown("**Operating Snapshot**")', warehouse_health_text)
        self.assertIn('cols = st.columns(4)', warehouse_health_text)
        self.assertIn(
            "_render_warehouse_action_brief(_warehouse_action_brief(company, environment, selected_days))",
            warehouse_health_text,
        )
        self.assertIn(
            "_render_warehouse_operating_snapshot(_warehouse_operating_snapshot(company, environment, selected_days))",
            warehouse_health_text,
        )
        warehouse_action_brief = warehouse_health_text.split("def _warehouse_action_brief", 1)[1].split(
            "def _render_warehouse_action_brief",
            1,
        )[0]
        self.assertNotIn("pd.DataFrame", warehouse_action_brief)
        warehouse_render_preload = warehouse_health_text.split("def render():", 1)[1].split(
            "warehouse_view = render_workflow_selector",
            1,
        )[0]
        warehouse_render_start = warehouse_health_text.split("def render():", 1)[1].split(
            "render_operator_briefing",
            1,
        )[0]
        live_monitor_render_preload = live_monitor_text.split("def render():", 1)[1].split(
            'if active_view == "Active Queries":',
            1,
        )[0]
        self.assertIn("RESULT_LIMIT=>100", live_monitor_text)
        self.assertIn("QUERY_HISTORY_BY_WAREHOUSE", live_monitor_text)
        self.assertIn("WAREHOUSE_NAME=>", live_monitor_text)
        self.assertIn("def _query_context_expr", live_monitor_text)
        self.assertIn("def _prioritize_query_context", live_monitor_text)
        self.assertIn("database_name, schema_name, {query_context_expr}", live_monitor_text)
        self.assertIn("df_live = _prioritize_query_context(df_live)", live_monitor_text)
        self.assertIn("df_recent = _prioritize_query_context(df_recent)", live_monitor_text)
        self.assertIn('"QUERY_CONTEXT"', live_monitor_text)
        self.assertIn("df_tq = _prioritize_query_context(df_tq)", dba_tools_text)
        self.assertIn("database_name, schema_name, {_query_context_expr()}", dba_tools_text)
        self.assertIn("admin_button_disabled", live_monitor_text)
        self.assertIn("require_admin_enabled(\"query cancellation\")", live_monitor_text)
        self.assertIn("log_admin_action(", live_monitor_text)
        self.assertNotIn("disabled=admin_button_disabled(not cancel_ready)", live_monitor_text)
        self.assertIn("Type `CANCEL` exactly before cancelling this query.", live_monitor_text)
        self.assertIn("QUERY_HISTORY_OPTIONAL_COLUMNS", live_monitor_text)
        self.assertIn("execution_status = {sql_literal(status_filter, 40)}", live_monitor_text)
        self.assertNotIn("execution_status = '{status_filter}'", live_monitor_text)
        live_panel_body = live_monitor_text.split("def _live_panel():", 1)[1].split(
            "        if refresh_live or auto_refresh:",
            1,
        )[0]
        workload_render_default = workload_operations_text.split("def render() -> None:", 1)[1].split(
            'if active_view == "Workload Brief":',
            1,
        )[0]
        self.assertNotIn("filter_existing_columns(", live_panel_body)
        self.assertNotIn("df_live = run_query_or_raise(f\"\"\"", live_panel_body)
        self.assertIn('ttl_key=f"live_active_fallback_', live_panel_body)
        self.assertIn('tier="live"', live_panel_body)
        architecture_render_preload = architecture_text.split("def render():", 1)[1].split(
            "active_pane = st.selectbox",
            1,
        )[0]
        self.assertNotIn("_architecture_objectives_frame(", architecture_render_preload)
        self.assertNotIn("build_forward_platform_control_register()", architecture_render_preload)
        self.assertNotIn("_architecture_source_health_rows(", architecture_render_preload)
        architecture_top_import_block = architecture_text.split("def build_agentic_ai_surface_scorecard", 1)[0]
        self.assertIn("class _LazyPandas", architecture_top_import_block)
        self.assertNotIn("import pandas as pd", architecture_top_import_block)
        self.assertNotIn("from utils import", architecture_top_import_block)
        self.assertNotIn("from utils.workflows import", architecture_top_import_block)
        self.assertNotIn("from utils.futures_governance import", architecture_top_import_block)
        architecture_platform_futures_preload = architecture_text.split("def _render_platform_futures(company", 1)[1].split(
            'if futures_view == "Overview":',
            1,
        )[0]
        self.assertNotIn("_ensure_architecture_forward_controls_state(", architecture_platform_futures_preload)
        self.assertNotIn("_refresh_architecture_source_health_state(", architecture_platform_futures_preload)
        self.assertNotIn("build_agentic_ai_surface_scorecard(", architecture_platform_futures_preload)
        security_posture_render_preload = security_posture_text.split("def render() -> None:", 1)[1].split(
            'if st.button("Load Security Brief"',
            1,
        )[0]
        security_posture_default_preload = security_posture_text.split("def render() -> None:", 1)[1].split(
            'if active_view == "Evidence Readiness":',
            1,
        )[0]
        security_posture_view_preload = security_posture_text.split("def render() -> None:", 1)[1].split(
            'if active_view == "Access Workflows":',
            1,
        )[0]
        security_access_render_preload = security_access_text.split("def render():", 1)[1].split(
            "def _query_history_columns",
            1,
        )[0]
        change_drift_render_preload = change_drift_text.split("def render() -> None:", 1)[1].split(
            'if st.button("Load Change & Drift Brief"',
            1,
        )[0]
        change_drift_default_preload = change_drift_text.split("def render() -> None:", 1)[1].split(
            'if active_view == "Change Workflows":',
            1,
        )[0]
        object_change_render_preload = object_change_text.split("def render():", 1)[1].split(
            "def _query_history_drift_caps",
            1,
        )[0]
        self.assertIn("def _warehouse_action_session", warehouse_health_text)
        self.assertIn("get_session_for_action", warehouse_health_text)
        self.assertIn("def _warehouse_sql_exprs", warehouse_health_text)
        self.assertIn("exprs = _warehouse_sql_exprs(session)", warehouse_health_text)
        self.assertIn("def _warehouse_support_panels_have_state", warehouse_health_text)
        self.assertIn('st.button("Support Panels"', warehouse_health_text)
        self.assertNotIn("session = get_session()", warehouse_render_start)
        self.assertNotIn("filter_existing_columns(", warehouse_render_preload)
        self.assertNotIn("_render_capacity_brief(", warehouse_render_preload)
        self.assertNotIn("_render_warehouse_ownership_panel(", warehouse_render_preload)
        self.assertNotIn("_render_warehouse_source_health(", warehouse_render_preload)
        self.assertNotIn("get_session()", live_monitor_render_preload)
        self.assertNotIn("render_workflow_module(", workload_render_default)
        self.assertNotIn("get_session()", architecture_render_preload)
        self.assertIn("class _LazyPandas", security_posture_import_block)
        self.assertNotIn("import pandas as pd", security_posture_import_block)
        self.assertNotIn("from utils import", security_posture_import_block)
        self.assertNotIn("from utils.workflows import", security_posture_import_block)
        self.assertNotIn("get_session()", security_posture_render_preload)
        self.assertNotIn("_render_privileged_grant_readiness(", security_posture_default_preload)
        self.assertNotIn("_render_security_source_health(", security_posture_default_preload)
        self.assertNotIn("render_workflow_module(", security_posture_view_preload)
        self.assertIn("def _security_action_brief", security_posture_text)
        self.assertIn('st.markdown("**Action Brief**")', security_posture_text)
        self.assertIn("def _render_security_operating_snapshot", security_posture_text)
        self.assertIn('st.markdown("**Operating Snapshot**")', security_posture_text)
        self.assertIn('cols[2].metric("Grant Chg"', security_posture_text)
        self.assertNotIn("get_session()", security_access_render_preload)
        self.assertNotIn("get_session()", change_drift_render_preload)
        self.assertNotIn("render_workflow_module(", change_drift_default_preload)
        self.assertIn('st.markdown("**Action Brief**")', change_drift_text)
        self.assertNotIn("get_session()", object_change_render_preload)
        self.assertIn("Recovery readiness", change_drift_text)
        self.assertIn("CHANGE_DRIFT_VIEWS", change_drift_text)
        self.assertIn('"Change Brief"', change_drift_text)
        self.assertIn('"Change Workflows"', change_drift_text)
        self.assertIn("_change_intervention_matrix", change_drift_text)
        self.assertIn("Change DBA intervention matrix", change_drift_text)
        self.assertIn('"Terraform evidence"', change_drift_text)
        self.assertIn('"Jira evidence"', change_drift_text)
        self.assertIn('mode="Terraform"', change_drift_text)
        self.assertIn('mode="Jira"', change_drift_text)
        self.assertIn("Terraform Evidence", change_drift_text)
        self.assertIn("Jira Evidence", change_drift_text)
        self.assertIn('"Load Terraform Evidence"', change_drift_text)
        self.assertIn('"Load Jira Evidence"', change_drift_text)
        self.assertNotIn("Jira & Terraform Evidence", change_drift_text)
        self.assertNotIn('st.button("Load Jira / Terraform Evidence"', change_drift_text)
        self.assertIn('sort_by=["DBA_PRIORITY", "SEVERITY", "FINDING_TYPE"]', change_drift_text)
        self.assertIn("ALERT_CENTER_SOURCES_BY_PANE", alert_center_text)
        self.assertIn('"Automation Readiness"', alert_center_text)
        self.assertIn("_alert_center_sources_for_view(active_view)", alert_center_text)
        self.assertIn("ALERT_CENTER_SOURCE_PLAN", alert_center_text)
        self.assertIn("_alert_center_source_summary(required_sources)", alert_center_text)
        self.assertIn("Sources on load", alert_center_text)
        self.assertNotIn("_alert_center_load_plan", alert_center_text)
        self.assertNotIn("with st.expander(\"Source plan\"", alert_center_text)
        self.assertIn('st.selectbox(\n        "Alert Center view"', alert_center_text)
        self.assertNotIn('st.radio(\n        "Alert Center view"', alert_center_text)
        self.assertNotIn("st.tabs(", alert_center_text)
        alert_center_import_block = alert_center_text.split("ALERT_CENTER_PANES", 1)[0]
        self.assertNotIn("build_alert_task_sql", alert_center_import_block)
        self.assertNotIn("load_alert_history", alert_center_import_block)
        self.assertNotIn("from utils.alerts import", alert_center_import_block)
        self.assertNotIn("import pandas as pd", alert_center_import_block)
        self.assertNotIn("from utils.workflows import", alert_center_import_block)
        self.assertIn("def _pd()", alert_center_text)
        self.assertIn("def _render_priority_dataframe", alert_center_text)
        self.assertIn("def _alert_center_action_session", alert_center_text)
        self.assertIn("def _alert_center_pending_brief", alert_center_text)
        self.assertIn("def _render_alert_center_action_brief", alert_center_text)
        self.assertIn('st.markdown("**Operating Snapshot**")', alert_center_text)
        self.assertIn("cols = st.columns(4)", alert_center_text)
        self.assertNotIn("row2 = st.columns(3)", alert_center_text)
        self.assertIn("ALERT_CENTER_HEALTH_DETAIL_OPTIONS", alert_center_text)
        self.assertIn('"Alert health detail"', alert_center_text)
        self.assertIn('st.selectbox(\n            "Alert health detail"', alert_center_text)
        self.assertNotIn('st.radio(\n            "Alert health detail"', alert_center_text)
        self.assertIn("def _alert_integration_readiness_board", alert_center_text)
        self.assertIn("Owner Directory Production Readiness", alert_center_text)
        self.assertIn("Notification & ITSM Readiness", alert_center_text)
        self.assertIn("Alert Automation Readiness", alert_center_text)
        self.assertIn("Ready Controls", alert_center_text)
        self.assertNotIn("m1, m2, m3, m4, m5, m6, m7 = st.columns(7)", alert_center_text)
        self.assertIn("owner_directory_readiness_board", alert_center_text)
        self.assertIn("get_session_for_action", alert_center_text)
        self.assertIn("snowflake_connection_known_unavailable", session_text)
        self.assertIn("Snowflake connection is required to {action}", session_text)
        self.assertIn('session = _alert_center_action_session(f"load {active_view}")', alert_center_text)
        self.assertNotIn("session = _get_session()", alert_center_text.replace("return _get_session()", ""))
        for label, section_text in {
            "Alert Center": alert_center_text,
            "Cost & Contract": cost_contract_text,
            "DBA Control Room": dba_control_text,
        }.items():
            with self.subTest(lazy_session_section=label):
                render_start = section_text.split("def render() -> None:", 1)[1].split("if st.button", 1)[0]
                self.assertNotIn("session = get_session()", render_start)
        self.assertNotIn('"Setup SQL",', alert_center_text.split("ALERT_CENTER_SOURCE_PLAN", 1)[0])
        self.assertNotIn('if active_view == "Setup SQL":', alert_center_text)
        self.assertNotIn("build_alert_task_sql", alert_center_text)
        self.assertIn("snowflake/OVERWATCH_MART_SETUP.sql", alert_center_text)
        self.assertIn('if active_view == "Suppression Windows":', alert_center_text)
        self.assertIn('sources=required_sources', alert_center_text)
        self.assertIn('"_loaded_sources": sorted(sources)', alert_center_text)
        self.assertIn("USAGE_OVERVIEW_PANES", usage_overview_text)
        self.assertIn('st.radio(\n        "Usage detail view"', usage_overview_text)
        self.assertNotIn("st.tabs(", usage_overview_text)
        for name, text in {
            "dba_control_room.py": dba_control_text,
            "security_access.py": security_access_text,
            "recommendations.py": recommendations_text,
            "live_monitor.py": live_monitor_text,
            "query_analysis.py": query_analysis_text,
            "pipeline_health.py": pipeline_health_text,
            "object_change_monitor.py": object_change_text,
            "adoption_analytics.py": adoption_text,
            "platform_topology.py": platform_text,
            "architecture_readiness.py": architecture_text,
            "dba_tools.py": dba_tools_text,
            "optimization_advisor.py": optimization_text,
        }.items():
            with self.subTest(active_view_file=name):
                self.assertNotIn("st.tabs(", text)
        self.assertIn("DBA_CONTROL_ROOM_PANES", dba_control_text)
        self.assertIn('st.selectbox(\n        "DBA Control Room view"', dba_control_text)
        self.assertNotIn('st.radio(\n        "DBA Control Room view"', dba_control_text)
        self.assertIn("DBA_CONTROL_ROOM_DETAIL_PANES", dba_control_text)
        self.assertIn('st.selectbox(\n                "Operations Board detail"', dba_control_text)
        self.assertNotIn('st.radio(\n                "Operations Board detail"', dba_control_text)
        self.assertIn('st.selectbox(\n            "Exception detail sample"', dba_control_text)
        self.assertNotIn('st.radio(\n            "Exception detail sample"', dba_control_text)
        self.assertIn("_dba_control_tower_priority_index", dba_control_text)
        self.assertIn("Operations priority board", dba_control_text)
        self.assertIn("dba_control_tower_priority_index", dba_control_text)
        self.assertIn("_dba_autopilot_flight_plan", dba_control_text)
        self.assertIn("Operator runbook", dba_control_text)
        self.assertIn("dba_autopilot_flight_plan", dba_control_text)
        self.assertIn("SECURITY_ACCESS_PANES", security_access_text)
        self.assertIn("_query_history_columns()", security_access_text)
        self.assertIn("_user_column_exprs()", security_access_text)
        self.assertIn("Program Failure Rate", security_access_text)
        self.assertIn("RECOMMENDATION_PANES", recommendations_text)
        self.assertIn("Proof-Ready", recommendations_text)
        self.assertIn("Automation Readiness", recommendations_text)
        self.assertIn("build_automation_readiness_board", recommendations_text)
        self.assertIn("rec_automation_board", recommendations_text)
        self.assertIn("LIVE_MONITOR_PANES", live_monitor_text)
        self.assertIn("Live query polling is paused", live_monitor_text)
        self.assertIn("QUERY_ANALYSIS_PANES", query_analysis_text)
        self.assertIn('"Root-Cause Brief"', query_analysis_text)
        self.assertIn('"Detailed Diagnosis"', query_analysis_text)
        self.assertIn('importlib.import_module("sections.query_workbench")', query_analysis_text)
        self.assertIn('importlib.import_module("sections.detailed_diagnosis")', query_analysis_text)
        self.assertNotIn("render_workflow_selector(", query_workbench_text)
        self.assertNotIn("from sections import detailed_diagnosis", query_workbench_text)
        self.assertIn("_query_history_exprs()", query_analysis_text)
        self.assertIn("workload_operations_snapshot", workload_operations_text)
        self.assertNotIn("from utils import", workload_operations_import_block)
        self.assertNotIn("from utils.workflows import", workload_operations_import_block)
        self.assertIn("build_mart_control_room_summary_sql", workload_operations_text)
        self.assertIn("WORKLOAD_OPERATIONS_VIEWS", workload_operations_text)
        self.assertIn('"Workload Brief"', workload_operations_text)
        self.assertIn('"Specialist Workflows"', workload_operations_text)
        self.assertIn("def _render_workload_action_brief", workload_operations_text)
        self.assertIn("def _render_workload_metric_rows", workload_operations_text)
        self.assertIn('st.markdown("**Operating Snapshot**")', workload_operations_text)
        self.assertIn('cols = st.columns(4)', workload_operations_text)
        self.assertNotIn('row2 = st.columns(2)', workload_operations_text)
        self.assertNotIn("c1, c2, c3, c4, c5 = st.columns(5)", workload_operations_text)
        self.assertIn("SECURITY_POSTURE_VIEWS", security_posture_text)
        self.assertIn('st.selectbox(\n        "Security posture view"', security_posture_text)
        self.assertNotIn('st.radio(\n        "Security posture view"', security_posture_text)
        self.assertIn('"Security Brief"', security_posture_text)
        self.assertIn('"Evidence Readiness"', security_posture_text)
        self.assertIn('"Access Workflows"', security_posture_text)
        self.assertIn("PIPELINE_HEALTH_PANES", pipeline_health_text)
        self.assertIn('"Snowpipe Usage"', pipeline_health_text)
        self.assertIn('"Dynamic Tables"', pipeline_health_text)
        self.assertIn("ACCOUNT_USAGE.PIPE_USAGE_HISTORY", pipeline_health_text)
        self.assertIn("DYNAMIC_TABLE_REFRESH_HISTORY", pipeline_health_text)
        self.assertIn("_query_search_clause", query_search_text)
        self.assertIn('"Exact query ID"', query_search_text)
        self.assertIn('"Prefix starts with"', query_search_text)
        self.assertIn('"Text contains"', query_search_text)
        self.assertIn("Contains search is capped at 7 days", query_search_text)
        self.assertIn("_search_date_predicate", query_search_text)
        self.assertIn("Snowflake Search Optimization does not accelerate ACCOUNT_USAGE", query_search_text)
        self.assertIn("_load_spcs_usage", spcs_text)
        self.assertIn("spcs_auto_attempted", spcs_text)
        self.assertIn("_load_shared_databases", data_sharing_text)
        self.assertIn("ds_shared_auto_attempted", data_sharing_text)
        self.assertIn("alert_email_targets", app_text)
        self.assertIn("current_alert_recipient", alert_center_text)
        self.assertIn("dba-alerts@yourcompany.com", config_text)
        self.assertNotIn("@yahoo.com", config_text)
        self.assertIn("OBJECT_CHANGE_PANES", object_change_text)
        self.assertIn("_query_history_drift_caps()", object_change_text)
        self.assertIn("ADOPTION_ANALYTICS_PANES", adoption_text)
        self.assertIn("PLATFORM_TOPOLOGY_PANES", platform_text)
        self.assertIn("ARCHITECTURE_READINESS_PANES", architecture_text)
        self.assertIn('st.selectbox(\n        "Architecture readiness view"', architecture_text)
        self.assertNotIn('st.radio(\n        "Architecture readiness view"', architecture_text)
        self.assertIn('st.selectbox(\n        "AI platform futures view"', architecture_text)
        self.assertNotIn('st.radio(\n        "AI platform futures view"', architecture_text)
        self.assertIn("Objectives & Owners", architecture_text)
        self.assertIn("AI & Platform Futures", architecture_text)
        self.assertIn("ARCHITECTURE_OBJECTIVES", architecture_text)
        self.assertIn("build_forward_platform_control_register", architecture_text)
        self.assertIn("build_platform_futures_adoption_gate", architecture_text)
        self.assertIn("build_agentic_ai_surface_scorecard", architecture_text)
        self.assertIn("build_platform_futures_evidence_ddl", architecture_text)
        self.assertIn("build_platform_futures_board", architecture_text)
        self.assertIn("load_adaptive_compute_readiness", architecture_text)
        self.assertIn("load_agent_mcp_inventory", architecture_text)
        self.assertIn("load_ai_usage_guardrails", architecture_text)
        self.assertIn("load_ai_security_guardrails", architecture_text)
        self.assertIn("load_horizon_semantic_readiness", architecture_text)
        self.assertIn("load_openflow_operations", architecture_text)
        self.assertIn("_architecture_source_health_rows", architecture_text)
        self.assertIn("_enrich_architecture_context", architecture_text)
        self.assertIn('st.button("Load Isolation Matrix"', architecture_text)
        self.assertIn('st.button("Load Clustering Candidates"', architecture_text)
        self.assertIn('st.button("Load Cache Evidence"', architecture_text)
        self.assertIn('st.button("Load DR Readiness"', architecture_text)
        self.assertIn('st.button("Load Objective Register"', architecture_text)
        self.assertIn('st.button("Load Architecture Source Health"', architecture_text)
        self.assertIn('st.button("Load Futures Control Board"', architecture_text)
        self.assertIn('st.button("Load Agentic AI Cockpit"', architecture_text)
        self.assertIn('st.button("Load Control Register"', architecture_text)
        self.assertIn('st.button("Load Agents and MCP Inventory"', architecture_text)
        self.assertIn('st.button("Load Adaptive Compute Advisor"', architecture_text)
        self.assertIn('st.button("Load AI Usage Guardrails"', architecture_text)
        self.assertIn('st.button("Load AI Security Guardrails"', architecture_text)
        self.assertIn('st.button("Load Openflow Operations"', architecture_text)
        self.assertIn('st.button("Load Horizon and Semantic Readiness"', architecture_text)
        self.assertIn("Platform futures evidence ledger setup SQL", architecture_text)
        self.assertIn("Expert adoption gate", architecture_text)
        self.assertIn("Agentic AI Cockpit", architecture_text)
        self.assertIn("Agentic AI governance cockpit", architecture_text)
        self.assertIn("Adaptive Compute transition advisor", architecture_text)
        self.assertIn("AI security guardrails to close first", architecture_text)
        self.assertNotIn("_render_platform_futures(get_session()", architecture_text)
        self.assertNotIn('c2.metric("Loaded Surfaces"', architecture_text)
        self.assertNotIn('c2.metric("Evidence Gaps"', architecture_text)
        self.assertNotIn('c5.metric("Control Areas"', architecture_text)
        self.assertIn("Run-Rate and YOY", cost_contract_text)
        self.assertIn("FinOps Control Center", cost_contract_text)
        self.assertIn('"sections.finops_control"', cost_contract_text)
        self.assertIn("build_mart_cost_run_rate_sql", cost_contract_text)
        self.assertIn("YOY_7D_PCT", cost_contract_text)
        self.assertIn("Snowflake Cost Management Parity", cost_contract_text)
        self.assertIn('st.button("Load Snowflake Cost Parity"', cost_contract_text)
        self.assertIn("build_snowflake_cost_management_account_sql", cost_contract_text)
        self.assertIn("build_snowflake_billed_credit_reconciliation_sql", cost_contract_text)
        self.assertIn("build_snowflake_org_currency_cost_sql", cost_contract_text)
        self.assertIn("build_snowflake_rate_sheet_reconciliation_sql", cost_contract_text)
        self.assertIn("build_snowflake_service_cost_lens_sql", cost_contract_text)
        self.assertIn("build_mart_cost_service_lens_sql", cost_contract_text)
        self.assertIn("Cost Source Health", cost_contract_text)
        self.assertIn("Query Attribution Gap", cost_contract_text)
        self.assertIn("Account Service Cost Lens", cost_contract_text)
        self.assertIn("Cortex user cost and recency", cortex_text)
        self.assertIn('"FIRST_USAGE"', cortex_text)
        self.assertIn('"LAST_USAGE"', cortex_text)
        self.assertIn("QUEUE_READINESS", architecture_text)
        self.assertIn("Owner Approval Status", architecture_text)
        self.assertIn("RPO_MINUTES", architecture_text)
        self.assertIn("SYSTEM$CLUSTERING_DEPTH", architecture_text)
        self.assertIn("SHOW FAILOVER GROUPS", architecture_text)
        self.assertIn("SHOW AGENTS IN ACCOUNT", architecture_text)
        self.assertIn("SHOW MCP SERVERS IN ACCOUNT", architecture_text)
        self.assertIn("SHOW GRANTS TO ROLE PUBLIC", architecture_text)
        self.assertIn("Architecture Readiness - Cache", architecture_text)
        self.assertIn("TASK_GRAPH_CONTROL_PANES", dba_tools_text)
        self.assertIn("Schema / Mart Migration Status", dba_tools_text)
        self.assertIn("build_schema_migration_status_sql", dba_tools_text)
        self.assertIn("DBA_TOOL_GROUPS", dba_tools_text)
        self.assertIn("DBA_TOOL_GROUPS", dba_tool_catalog_text)
        self.assertIn("WH_PARAM_HELP", dba_tool_catalog_text)
        self.assertIn("OPTIMIZATION_ADVISOR_PANES", optimization_text)
        self.assertEqual(
            sorted((APP_ROOT).rglob("*.py")),
            sorted(path for path in (APP_ROOT).rglob("*.py") if "st.tabs(" not in path.read_text(encoding="utf-8")),
        )

    def test_utils_re_exports_are_lazy(self):
        utils_text = (APP_ROOT / "utils" / "__init__.py").read_text(encoding="utf-8")

        self.assertIn("def __getattr__", utils_text)
        self.assertIn("_EXPORT_GROUPS", utils_text)
        self.assertIn("_EXPORT_MODULES", utils_text)
        self.assertNotIn("from .alerts import", utils_text)
        self.assertNotIn("from .mart import", utils_text)
        self.assertIn('"environment_label_for_database"', utils_text)
        self.assertIn('"get_environment_filter_or_no_database_clause"', utils_text)
        self.assertIn('"build_platform_futures_adoption_gate"', utils_text)
        self.assertIn('"build_agentic_ai_surface_scorecard"', utils_text)
        self.assertIn('"AGENTIC_AI_CONTROL_AREAS"', utils_text)
        self.assertIn('"load_adaptive_compute_readiness"', utils_text)
        self.assertIn('"load_ai_security_guardrails"', utils_text)
        self.assertIn('"render_workflow_module"', utils_text)
        self.assertIn('"migrate_legacy_workflow_state"', utils_text)
        self.assertIn('"render_ranked_bar_chart"', utils_text)
        self.assertIn('"rank_chart_frame"', utils_text)
        self.assertIn('"build_platform_futures_evidence_ddl"', utils_text)
        self.assertIn('"build_mart_cost_run_rate_sql"', utils_text)
        self.assertIn('"build_mart_cost_explorer_sql"', utils_text)
        self.assertIn('"build_snowflake_cost_management_account_sql"', utils_text)
        self.assertIn('"build_snowflake_billed_credit_reconciliation_sql"', utils_text)
        self.assertIn('"build_snowflake_org_currency_cost_sql"', utils_text)

    def test_dead_ui_helpers_stay_removed(self):
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        helpers_text = (APP_ROOT / "utils" / "helpers.py").read_text(encoding="utf-8")

        self.assertNotIn("CHART_COLORS", display_text)
        self.assertNotIn("data_freshness_badge", helpers_text)

    def test_heavy_chart_dependency_stays_lazy(self):
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        usage_text = (APP_ROOT / "sections" / "usage_overview.py").read_text(encoding="utf-8")
        adoption_text = (APP_ROOT / "sections" / "adoption_analytics.py").read_text(encoding="utf-8")
        topology_text = (APP_ROOT / "sections" / "platform_topology.py").read_text(encoding="utf-8")

        self.assertNotIn("\nimport altair as alt", display_text)
        self.assertIn("def _altair", display_text)
        self.assertIn("alt = _altair()", display_text)
        for section_text in (usage_text, adoption_text, topology_text):
            self.assertNotIn("\nimport altair as alt", section_text)
            self.assertIn("def _altair", section_text)


if __name__ == "__main__":
    unittest.main()
