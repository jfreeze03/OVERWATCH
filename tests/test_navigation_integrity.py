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
    normalize_section_name,
)
from utils.section_guidance import (  # noqa: E402
    CONFIDENCE_BANDS,
    SECTION_EVIDENCE_CONTRACT,
    SECTION_OPERATING_GUIDE,
    SECTION_SOURCE_HEALTH_STATE_KEYS,
    build_section_confidence_meter,
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
        self.assertNotIn("LEGACY_SECTION_ALIASES", (APP_ROOT / "config.py").read_text(encoding="utf-8"))

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
        self.assertIn('st.expander("Ask OVERWATCH", expanded=False)', app_text)
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

    def test_architecture_objectives_cover_alfa_prod_dev_and_execution_warehouse(self):
        objectives = {
            (row["ENTITY_TYPE"], row["ENTITY_PATTERN"]): row
            for row in ARCHITECTURE_OBJECTIVES
        }
        self.assertEqual(objectives[("DATABASE", "ALFA_EDW_PROD")]["EXPECTED_ENVIRONMENT"], "PROD")
        self.assertEqual(objectives[("DATABASE", "ALFA_EDW_DEV")]["EXPECTED_ENVIRONMENT"], "DEV_ALL")
        self.assertEqual(objectives[("WAREHOUSE", "COMPUTE_WH")]["WORKLOAD_CLASS"], "OVERWATCH execution and utility compute")
        self.assertIn("monitor cost separately", objectives[("WAREHOUSE", "COMPUTE_WH")]["ISOLATION_POLICY"])

    def test_workflow_hubs_expose_expected_subworkflows(self):
        from sections import change_drift, cost_contract, security_posture, workload_operations

        self.assertIn("Query diagnosis", workload_operations.WORKFLOWS)
        self.assertIn("Task graphs", workload_operations.WORKFLOWS)
        self.assertIn("Stored procedures", workload_operations.WORKFLOWS)
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Task graphs"], "sections.task_management")
        self.assertIn("Recommendations and action queue", cost_contract.WORKFLOWS)
        self.assertEqual(cost_contract.WORKFLOW_MODULES["AI and Cortex spend"], "sections.cortex_monitor")
        self.assertEqual(SECTION_ALIASES["Alerts"], SECTION_BY_TITLE["Alert Center"])
        self.assertIn("Access posture", security_posture.WORKFLOWS)
        self.assertEqual(security_posture.WORKFLOW_MODULES["Access posture"], "sections.security_access")
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
            '"arch_"',
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
        self.assertIn('CONNECTION_OPTIONAL_SECTIONS = {"Alert Center"}', app_text)
        self.assertIn("def _section_requires_connection", app_text)
        self.assertIn("_overwatch_pending_section", app_text)
        self.assertIn("def _section_render_signature", app_text)
        self.assertIn("_overwatch_last_section_render_signature", app_text)
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

    def test_current_sections_have_operating_guides(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")

        self.assertIn("render_section_reference(active_section)", app_text)
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

        self.assertIn("render_section_confidence_meter(active_section", app_text)
        self.assertIn("render_section_reference(active_section)", app_text)
        self.assertNotIn("render_section_operating_guide(active_section)", app_text)
        self.assertNotIn("render_section_evidence_contract(active_section)", app_text)
        self.assertIn('st.expander("Details", expanded=False)', guidance_text)
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
        self.assertIn(".ow-confidence-gauge-track", theme_text)
        self.assertIn(".ow-confidence-gauge-marker", theme_text)
        self.assertIn(".ow-confidence-mix-item", theme_text)
        self.assertIn("SECTION_SOURCE_HEALTH_STATE_KEYS", guidance_text)
        self.assertIn("_SOURCE_HEALTH_FALLBACK_SCAN_LIMIT", guidance_text)
        self.assertIn("lru_cache", guidance_text)
        self.assertIn("@lru_cache(maxsize=16)", guidance_text)
        self.assertIn('"arch_source_health"', guidance_text)
        self.assertNotIn("ow-confidence-chip", theme_text)
        self.assertNotIn("ow-confidence-chip", guidance_text)
        self.assertNotIn("ow-confidence-card-detail", theme_text)
        self.assertNotIn("ow-confidence-card-detail", guidance_text)
        self.assertNotIn("The OVERWATCH shell is loaded", app_text)

    def test_confidence_meter_classifies_contract_and_loaded_source_health(self):
        band_keys = [key for key, _, _ in CONFIDENCE_BANDS]
        self.assertEqual(band_keys, ["exact", "allocated", "delayed", "manual", "unavailable"])

        meter = build_section_confidence_meter("Cost & Contract")
        by_label = {row["label"]: row for row in meter["rows"]}
        self.assertGreater(by_label["Exact"]["count"], 0)
        self.assertGreater(by_label["Allocated"]["count"], 0)
        self.assertEqual(meter["source_health_rows"], 0)
        self.assertEqual(meter["state"], "Mixed Confidence")

        with_loaded_health = build_section_confidence_meter(
            "Warehouse Health",
            {
                "wh_source_health": pd.DataFrame([
                    {
                        "SURFACE": "Overview",
                        "STATE": "Stale",
                        "SOURCE": "ACCOUNT_USAGE",
                        "CONFIDENCE": "Pre-aggregated",
                        "ROWS": 2,
                    },
                    {
                        "SURFACE": "Capacity brief",
                        "STATE": "Loaded",
                        "SOURCE": "WAREHOUSE_METERING_HISTORY",
                        "CONFIDENCE": "Exact",
                        "ROWS": 1,
                    },
                ])
            },
        )
        loaded_by_label = {row["label"]: row for row in with_loaded_health["rows"]}
        self.assertGreaterEqual(loaded_by_label["Unavailable"]["count"], 1)
        self.assertEqual(with_loaded_health["source_health_rows"], 2)
        self.assertIn(with_loaded_health["state"], {"Use With Caution", "Evidence Gaps"})

        self.assertEqual(SECTION_SOURCE_HEALTH_STATE_KEYS["Architecture Readiness"], ("arch_source_health",))
        ignored_noise = build_section_confidence_meter(
            "Cost & Contract",
            {
                f"random_frame_{idx}": pd.DataFrame([{
                    "SURFACE": "Noise",
                    "STATE": "Stale",
                    "SOURCE": "Not a source health key",
                    "CONFIDENCE": "Unavailable",
                }])
                for idx in range(100)
            },
        )
        self.assertEqual(ignored_noise["source_health_rows"], 0)

    def test_priority_tables_defer_full_raw_detail_rendering(self):
        workflows_text = (APP_ROOT / "utils" / "workflows.py").read_text(encoding="utf-8")
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        self.assertIn("Full detail rendering is deferred", workflows_text)
        self.assertIn('st.button("Render full detail"', workflows_text)
        self.assertIn("grid_df = df.head(1000)", display_text)
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
        self.assertIn("with st.expander(str(title), expanded=False)", workflows_text)
        self.assertIn("ow-brief-strip-collapsed", workflows_text)
        self.assertNotIn("ow-brief-title", workflows_text)
        self.assertNotIn("ow-brief-title", theme_text)
        duplicate_headers = {
            "dba_control_room.py": 'st.header("DBA Control Room")',
            "alert_center.py": 'st.header("Alert Center")',
            "cost_contract.py": 'st.header("Cost & Contract")',
            "workload_operations.py": 'st.header("Workload Operations")',
            "security_posture.py": 'st.header("Security Posture")',
            "change_drift.py": 'st.header("Change & Drift")',
            "architecture_readiness.py": 'st.header("Architecture Readiness")',
            "account_health.py": 'st.header("Account Health - Command Center")',
        }
        for filename, marker in duplicate_headers.items():
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
        cortex_text = (APP_ROOT / "sections" / "cortex_monitor.py").read_text(encoding="utf-8")
        account_health_text = (APP_ROOT / "sections" / "account_health.py").read_text(encoding="utf-8")
        alert_center_text = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        dba_control_text = (APP_ROOT / "sections" / "dba_control_room.py").read_text(encoding="utf-8")
        security_access_text = (APP_ROOT / "sections" / "security_access.py").read_text(encoding="utf-8")
        recommendations_text = (APP_ROOT / "sections" / "recommendations.py").read_text(encoding="utf-8")
        live_monitor_text = (APP_ROOT / "sections" / "live_monitor.py").read_text(encoding="utf-8")
        query_analysis_text = (APP_ROOT / "sections" / "query_analysis.py").read_text(encoding="utf-8")
        pipeline_health_text = (APP_ROOT / "sections" / "pipeline_health.py").read_text(encoding="utf-8")
        object_change_text = (APP_ROOT / "sections" / "object_change_monitor.py").read_text(encoding="utf-8")
        adoption_text = (APP_ROOT / "sections" / "adoption_analytics.py").read_text(encoding="utf-8")
        platform_text = (APP_ROOT / "sections" / "platform_topology.py").read_text(encoding="utf-8")
        architecture_text = (APP_ROOT / "sections" / "architecture_readiness.py").read_text(encoding="utf-8")
        usage_overview_text = (APP_ROOT / "sections" / "usage_overview.py").read_text(encoding="utf-8")
        optimization_text = (APP_ROOT / "utils" / "optimization_advisor.py").read_text(encoding="utf-8")
        downloads_text = (APP_ROOT / "utils" / "downloads.py").read_text(encoding="utf-8")
        dba_tools_text = (APP_ROOT / "sections" / "dba_tools.py").read_text(encoding="utf-8")
        task_management_text = (APP_ROOT / "sections" / "task_management.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        data_text = (APP_ROOT / "utils" / "data.py").read_text(encoding="utf-8")
        top_import_block = app_text.split("def _snapshot_ask_overwatch_state", 1)[0]

        self.assertIn("Telemetry summaries are rendered on demand", app_text)
        self.assertIn('st.button("Render telemetry summary"', app_text)
        self.assertNotIn("from utils.ask_overwatch import answer_ask_overwatch", top_import_block)
        self.assertIn("from utils.ask_overwatch import answer_ask_overwatch", app_text)
        self.assertNotIn("from utils.bookmarks import (", top_import_block)
        self.assertIn("def _load_bookmark_helpers", app_text)
        self.assertNotIn("import utils.display as display_module", top_import_block)
        self.assertNotIn("import utils.workflows as workflows_module", top_import_block)
        self.assertIn("def _maybe_reload_dev_helpers", app_text)
        self.assertIn('st.session_state.get("_overwatch_dev_reload_helpers", False)', app_text)
        self.assertIn('st.session_state["_logging_enabled"] = False', app_text)
        self.assertIn('"Persist section timing"', app_text)
        self.assertIn("section_render_started = time.perf_counter()", app_text)
        self.assertIn("log_section_load(active_section, duration_ms)", app_text)
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
        self.assertIn('"Check Fast Snapshot"', dba_control_text)
        self.assertIn("Fast mart snapshot lookup is on demand", dba_control_text)
        self.assertNotIn("load_latest_control_room_mart(company, max_age_hours=6) if snapshot_scope_ok else None", dba_control_text)
        self.assertIn('"Fast Watch"', dba_control_text)
        self.assertIn('"Operations Tower"', dba_control_text)
        self.assertIn('"App Performance"', dba_control_text)
        self.assertIn('"Build Operations Tower"', dba_control_text)
        self.assertIn("Control Tower, Autopilot, Incident Board, and Shift Handoff are deferred", dba_control_text)
        self.assertIn("def _render_app_performance_guardrail", dba_control_text)
        self.assertIn("_latest_local_snowflake_suite_result", dba_control_text)
        self.assertIn("_RESULT_SIZE_SAMPLE_ROWS", query_text)
        self.assertIn("OVERWATCH_PERF_RUN_ID", query_text)
        self.assertIn('"perf_run_id": _perf_run_id()', query_text)
        self.assertIn('st.session_state.get("_detailed_query_tags_enabled", False)', query_text)
        self.assertIn('return "OVERWATCH"', query_text)
        self.assertNotIn("OVERWATCH:v3", query_text)
        self.assertIn("PERF_RUN_ID", logging_text)
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
        self.assertIn("render_section_confidence_meter(active_section, st.session_state)", app_text)
        self.assertNotIn("render_section_confidence_meter(active_section, dict(st.session_state))", app_text)
        self.assertNotIn("dict(state).items()", (APP_ROOT / "utils" / "section_guidance.py").read_text(encoding="utf-8"))
        self.assertIn("cc_user_profile_requested", cost_center_text)
        self.assertIn('"Cost Explorer"', cost_center_text)
        self.assertIn("COST_EXPLORER_LENSES", cost_center_text)
        self.assertIn("build_mart_cost_explorer_sql", cost_center_text)
        self.assertIn("FACT_CHARGEBACK_DAILY", cost_center_text)
        self.assertIn("Cost attribution gaps", cost_center_text)
        self.assertIn("Save cost explorer outliers to Action Queue", cost_center_text)
        self.assertIn('st.button("Load"', cost_center_text)
        self.assertIn("ACCOUNT_HEALTH_PANES", account_health_text)
        self.assertIn('st.radio(\n        "Account Health view"', account_health_text)
        self.assertNotIn("st.tabs(", account_health_text)
        self.assertIn('st.button("Load / Refresh Health"', account_health_text)
        self.assertNotIn("or cache_age > 300", account_health_text)
        self.assertIn('st.button("Load Operability Mart"', account_health_text)
        self.assertIn("ALERT_CENTER_SOURCES_BY_PANE", alert_center_text)
        self.assertIn("_alert_center_sources_for_view(active_view)", alert_center_text)
        self.assertIn("ALERT_CENTER_SOURCE_PLAN", alert_center_text)
        self.assertIn("_alert_center_source_summary(required_sources)", alert_center_text)
        self.assertIn("Sources on load", alert_center_text)
        self.assertNotIn("_alert_center_load_plan", alert_center_text)
        self.assertNotIn("with st.expander(\"Source plan\"", alert_center_text)
        self.assertIn('st.radio(\n        "Alert Center view"', alert_center_text)
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
        self.assertIn('st.session_state.get("_overwatch_connection_unavailable")', alert_center_text)
        self.assertIn("Snowflake connection is required to {action}", alert_center_text)
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
        self.assertIn('if active_view == "Setup SQL":', alert_center_text)
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
        self.assertIn("DBA_CONTROL_ROOM_DETAIL_PANES", dba_control_text)
        self.assertIn("_dba_control_tower_priority_index", dba_control_text)
        self.assertIn("DBA Control Tower priority index", dba_control_text)
        self.assertIn("dba_control_tower_priority_index", dba_control_text)
        self.assertIn("_dba_autopilot_flight_plan", dba_control_text)
        self.assertIn("DBA Autopilot flight plan", dba_control_text)
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
        self.assertIn("_query_history_exprs()", query_analysis_text)
        self.assertIn("PIPELINE_HEALTH_PANES", pipeline_health_text)
        self.assertIn("OBJECT_CHANGE_PANES", object_change_text)
        self.assertIn("_query_history_drift_caps()", object_change_text)
        self.assertIn("ADOPTION_ANALYTICS_PANES", adoption_text)
        self.assertIn("PLATFORM_TOPOLOGY_PANES", platform_text)
        self.assertIn("ARCHITECTURE_READINESS_PANES", architecture_text)
        self.assertIn("Objectives & Owners", architecture_text)
        self.assertIn("AI & Platform Futures", architecture_text)
        self.assertIn("ARCHITECTURE_OBJECTIVES", architecture_text)
        self.assertIn("build_forward_platform_control_register", architecture_text)
        self.assertIn("build_platform_futures_adoption_gate", architecture_text)
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
        self.assertIn('st.button("Load Agents and MCP Inventory"', architecture_text)
        self.assertIn('st.button("Load Adaptive Compute Advisor"', architecture_text)
        self.assertIn('st.button("Load AI Usage Guardrails"', architecture_text)
        self.assertIn('st.button("Load AI Security Guardrails"', architecture_text)
        self.assertIn('st.button("Load Openflow Operations"', architecture_text)
        self.assertIn('st.button("Load Horizon and Semantic Readiness"', architecture_text)
        self.assertIn("Platform futures evidence ledger setup SQL", architecture_text)
        self.assertIn("Expert adoption gate", architecture_text)
        self.assertIn("Adaptive Compute transition advisor", architecture_text)
        self.assertIn("AI security guardrails to close first", architecture_text)
        self.assertIn("Run-Rate and YOY", cost_contract_text)
        self.assertIn("build_mart_cost_run_rate_sql", cost_contract_text)
        self.assertIn("YOY_7D_PCT", cost_contract_text)
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
        self.assertIn('"load_adaptive_compute_readiness"', utils_text)
        self.assertIn('"load_ai_security_guardrails"', utils_text)
        self.assertIn('"render_workflow_module"', utils_text)
        self.assertIn('"migrate_legacy_workflow_state"', utils_text)
        self.assertIn('"render_ranked_bar_chart"', utils_text)
        self.assertIn('"rank_chart_frame"', utils_text)
        self.assertIn('"build_platform_futures_evidence_ddl"', utils_text)
        self.assertIn('"build_mart_cost_run_rate_sql"', utils_text)
        self.assertIn('"build_mart_cost_explorer_sql"', utils_text)

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
