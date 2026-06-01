from pathlib import Path
import ast
import importlib.util
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import (  # noqa: E402
    ALL_SECTIONS,
    NAV_GROUPS,
    ROLE_SECTIONS,
    SECTION_ALIASES,
    SECTION_BY_TITLE,
    SECTION_DEFINITIONS,
    SECTION_MODULES,
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

    def test_roles_and_aliases_resolve_to_visible_sections(self):
        for role, sections in ROLE_SECTIONS.items():
            with self.subTest(role=role):
                self.assertTrue(sections)
                self.assertLessEqual(set(sections), set(ALL_SECTIONS))

        self.assertLessEqual(set(SECTION_ALIASES.values()), set(ALL_SECTIONS))
        self.assertEqual(SECTION_ALIASES["Credit Contract"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Cost Center"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Security & Access"], SECTION_BY_TITLE["Security Posture"])
        self.assertEqual(SECTION_ALIASES["DBA Tools"], SECTION_BY_TITLE["Change & Drift"])
        self.assertEqual(SECTION_ALIASES["Optimization"], SECTION_BY_TITLE["Warehouse Health"])

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
        self.assertIn("Ask OVERWATCH (Evidence Mode)", app_text)
        self.assertIn("answer_ask_overwatch(", app_text)
        self.assertNotIn("SNOWFLAKE.CORTEX.COMPLETE", app_text)

    def test_workflow_hubs_replace_scattered_operational_pages(self):
        visible_titles = {section.title for section in SECTION_DEFINITIONS}
        self.assertIn("Alert Center", visible_titles)
        self.assertIn("Workload Operations", visible_titles)
        self.assertIn("Cost & Contract", visible_titles)
        self.assertIn("Security Posture", visible_titles)
        self.assertIn("Change & Drift", visible_titles)
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

    def test_workflow_hubs_expose_expected_subworkflows(self):
        from sections import change_drift, cost_contract, security_posture, workload_operations

        self.assertIn("Query diagnosis", workload_operations.WORKFLOWS)
        self.assertIn("Task graphs", workload_operations.WORKFLOWS)
        self.assertIn("Stored procedures", workload_operations.WORKFLOWS)
        self.assertIn("Recommendations and action queue", cost_contract.WORKFLOWS)
        self.assertEqual(SECTION_ALIASES["Alerts"], SECTION_BY_TITLE["Alert Center"])
        self.assertIn("Access posture", security_posture.WORKFLOWS)
        self.assertIn("Schema and object drift", change_drift.WORKFLOWS)
        self.assertIn("Data movement and replication", change_drift.WORKFLOWS)
        self.assertIn("Controlled DBA actions", change_drift.WORKFLOWS)
        self.assertEqual(change_drift.WORKFLOWS[-1], "Controlled DBA actions")

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
        self.assertIn('st.session_state.get("global_environment"', query_text)
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
            '"change_drift_summary"',
            '"security_posture_summary"',
        ):
            with self.subTest(prefix=prefix):
                self.assertIn(prefix, cache_text)
        self.assertIn('"_prev_global_filter_signature"', state_keys_text)
        self.assertIn('"_prev_metric_settings_signature"', state_keys_text)

    def test_sidebar_saved_views_are_explicit_load_only(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("_overwatch_saved_views_loaded", app_text)
        self.assertIn("_overwatch_saved_views_cache", app_text)
        self.assertIn("Saved views are skipped during normal reruns", app_text)
        self.assertNotIn("bookmarks = load_bookmarks(_session) if _session else []", app_text)

    def test_section_switches_clear_stale_body_during_render(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")

        self.assertIn("def _queue_section_navigation", app_text)
        self.assertIn("_overwatch_pending_section", app_text)
        self.assertIn("def _section_render_signature", app_text)
        self.assertIn("_overwatch_last_section_render_signature", app_text)
        self.assertIn("transition_slot = st.empty()", app_text)
        self.assertIn("section_slot = st.empty()", app_text)
        self.assertIn("_render_section_transition_state(active_section)", app_text)
        self.assertIn("with section_slot.container():", app_text)
        self.assertIn("sections.dispatch(active_section)", app_text)
        self.assertIn("transition_slot.empty()", app_text)
        self.assertIn(".ow-section-transition", theme_text)
        self.assertIn("position: fixed", theme_text)

    def test_priority_tables_defer_full_raw_detail_rendering(self):
        workflows_text = (APP_ROOT / "utils" / "workflows.py").read_text(encoding="utf-8")
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        self.assertIn("Full detail rendering is deferred", workflows_text)
        self.assertIn('st.button("Render full detail"', workflows_text)
        self.assertIn("grid_df = df.head(1000)", display_text)

    def test_app_performance_hot_paths_are_deferred_or_cached(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        query_text = (APP_ROOT / "utils" / "query.py").read_text(encoding="utf-8")
        session_text = (APP_ROOT / "utils" / "session.py").read_text(encoding="utf-8")
        logging_text = (APP_ROOT / "utils" / "logging.py").read_text(encoding="utf-8")
        metadata_text = (APP_ROOT / "utils" / "metadata.py").read_text(encoding="utf-8")
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        cache_text = (APP_ROOT / "utils" / "cache.py").read_text(encoding="utf-8")
        downloads_text = (APP_ROOT / "utils" / "downloads.py").read_text(encoding="utf-8")
        dba_tools_text = (APP_ROOT / "sections" / "dba_tools.py").read_text(encoding="utf-8")
        task_management_text = (APP_ROOT / "sections" / "task_management.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        data_text = (APP_ROOT / "utils" / "data.py").read_text(encoding="utf-8")

        self.assertIn("Telemetry summaries are rendered on demand", app_text)
        self.assertIn('st.button("Render telemetry summary"', app_text)
        self.assertIn('st.session_state["_logging_enabled"] = False', app_text)
        self.assertIn('st.session_state["_detailed_query_tags_enabled"] = False', app_text)
        self.assertIn('"Detailed Snowflake query tags"', app_text)
        self.assertIn("st.session_state.get(_ENABLED_KEY, False)", logging_text)
        self.assertIn("if not is_query_logging_enabled():", logging_text)
        self.assertNotIn("not is_logging_enabled() or not is_query_logging_enabled()", logging_text)
        self.assertIn("_overwatch_show_statement_cache", metadata_text)
        self.assertIn("_SHOW_CACHE_TTL_SECONDS = 300", metadata_text)
        self.assertIn("force_refresh: bool = False", metadata_text)
        self.assertIn("return frame.copy()", metadata_text)
        self.assertIn("force_refresh=bool(refresh_wh)", dba_tools_text)
        self.assertIn("force_inventory_refresh=True", task_management_text)
        self.assertIn("_task_management_execution_context_cache", task_management_text)
        self.assertIn("_EXECUTION_CONTEXT_CACHE_TTL_SECONDS = 300", task_management_text)
        self.assertIn("_RESULT_SIZE_SAMPLE_ROWS", query_text)
        self.assertIn('st.session_state.get("_detailed_query_tags_enabled", False)', query_text)
        self.assertIn('return "OVERWATCH"', query_text)
        self.assertNotIn("OVERWATCH:v3", query_text)
        self.assertIn('_QUERY_TAG = "OVERWATCH"', session_text)
        self.assertNotIn("OVERWATCH:v3", session_text)
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

    def test_utils_re_exports_are_lazy(self):
        utils_text = (APP_ROOT / "utils" / "__init__.py").read_text(encoding="utf-8")

        self.assertIn("def __getattr__", utils_text)
        self.assertIn("_EXPORT_GROUPS", utils_text)
        self.assertIn("_EXPORT_MODULES", utils_text)
        self.assertNotIn("from .alerts import", utils_text)
        self.assertNotIn("from .mart import", utils_text)
        self.assertIn('"environment_label_for_database"', utils_text)
        self.assertIn('"get_environment_filter_or_no_database_clause"', utils_text)

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
