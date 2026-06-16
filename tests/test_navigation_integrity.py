from pathlib import Path
import ast
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import (  # noqa: E402
    ALL_SECTIONS,
    ACCOUNT_WAREHOUSES,
    ALFA_DEV_DATABASES,
    ALFA_PROD_DATABASES,
    ALFA_WAREHOUSES,
    DAY_WINDOW_OPTIONS,
    DEFAULT_DAY_WINDOW,
    NAV_GROUPS,
    PRIMARY_SECTIONS,
    PRIMARY_NAV_HIDDEN_SECTIONS,
    ROLE_SECTIONS,
    SECTION_ALIASES,
    SECTION_BY_TITLE,
    SECTION_DEFINITIONS,
    SECTION_MODULES,
    SECTION_REDIRECTS,
    EXPERIENCE_VIEW_SECTIONS,
    RETIRED_SECTION_REDIRECTS,
    ROLE_EXPERIENCE_VIEWS,
    TREXIS_DATABASES,
    TREXIS_DEV_DATABASES,
    TREXIS_PROD_DATABASES,
    TREXIS_WAREHOUSES,
    default_experience_view_for_role,
    compatibility_state_for_section,
    normalize_section_name,
    resolve_allowed_experience_views,
    resolve_role_profile,
    static_database_options,
    static_warehouse_options,
)
from utils.section_guidance import (  # noqa: E402
    SECTION_EVIDENCE_CONTRACT,
    SECTION_OPERATING_GUIDE,
)
from utils.scorecards import DBA_CONTROL_PLANE_SECTION_BASELINE  # noqa: E402
from sections.shell_helpers import (  # noqa: E402
    action_state_label,
    compact_environment_label,
    evidence_caption,
    evidence_label,
    evidence_loaded,
    freshness_state,
    render_refresh_contract,
    scope_label,
    with_loaded_at,
)


def _chars(*codes: int) -> str:
    return "".join(chr(code) for code in codes)


class NavigationIntegrityTests(unittest.TestCase):
    def test_shell_freshness_state_is_explicit_about_age(self):
        current_meta = with_loaded_at({"source": "Fast summary"}, source="Fast summary")
        stale_meta = {
            "source": "Live fallback",
            "loaded_at": (datetime.now() - timedelta(minutes=95)).isoformat(timespec="seconds"),
        }

        self.assertEqual(freshness_state({}, target_minutes=60), ("", ""))
        self.assertEqual(freshness_state(current_meta, target_minutes=60)[0], "Current")
        stale_state, stale_detail = freshness_state(stale_meta, target_minutes=30)
        self.assertEqual(stale_state, "Stale")
        self.assertIn("Refresh before acting", stale_detail)
        helper_text = (APP_ROOT / "sections" / "shell_helpers.py").read_text(encoding="utf-8")
        self.assertIn("def render_refresh_contract", helper_text)
        self.assertIn("Scheduled Snowflake refresh", helper_text)

    def test_section_registry_matches_navigation(self):
        flattened = [section for sections in NAV_GROUPS.values() for section in sections]
        defined = [section.label for section in SECTION_DEFINITIONS]
        primary_sections = [section for section in ALL_SECTIONS if section not in PRIMARY_NAV_HIDDEN_SECTIONS]
        self.assertEqual(PRIMARY_SECTIONS, primary_sections)
        self.assertEqual(primary_sections, flattened)
        self.assertEqual(ALL_SECTIONS, defined)
        self.assertEqual(len(ALL_SECTIONS), 6)
        self.assertNotIn("Account Health", ALL_SECTIONS)
        self.assertNotIn("Account Health", flattened)
        self.assertFalse(PRIMARY_NAV_HIDDEN_SECTIONS)
        self.assertEqual(
            list(NAV_GROUPS),
            ["COMMAND CENTER", "FINANCIAL CONTROL", "OPERATIONS", "SECURITY"],
        )
        self.assertEqual(set(ALL_SECTIONS), set(SECTION_MODULES))
        self.assertEqual(
            SECTION_MODULES,
            {section.label: section.module for section in SECTION_DEFINITIONS},
        )
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        self.assertEqual(config_text.count("ROLE_SECTIONS = {"), 1)
        self.assertEqual(DAY_WINDOW_OPTIONS, (1, 7, 14, 30, 60, 90))
        self.assertEqual(DEFAULT_DAY_WINDOW, 7)
        self.assertEqual(static_warehouse_options("Trexis"), TREXIS_WAREHOUSES)
        self.assertEqual(static_warehouse_options("ALFA"), ALFA_WAREHOUSES)
        self.assertEqual(static_warehouse_options("ALL"), ACCOUNT_WAREHOUSES)
        self.assertEqual(static_database_options("Trexis", "PROD"), TREXIS_PROD_DATABASES)
        self.assertEqual(static_database_options("Trexis", "DEV_ALL"), TREXIS_DEV_DATABASES)
        self.assertEqual(static_database_options("ALFA", "PROD"), ALFA_PROD_DATABASES)
        self.assertEqual(static_database_options("ALFA", "DEV_ALL"), ALFA_DEV_DATABASES)
        smoke_runner_text = (ROOT / "perf_tests" / "section_smoke_runner.py").read_text(encoding="utf-8")
        self.assertIn('DEFAULT_SECTIONS = [\n    "Executive Landing",', smoke_runner_text)

    def test_calendar_day_windows_use_standard_dropdowns(self):
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        init_text = (APP_ROOT / "utils" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("def day_window_selectbox", display_text)
        self.assertIn("DAY_WINDOW_OPTIONS", display_text)
        self.assertIn('"day_window_selectbox"', init_text)

        offenders = []
        scanned_roots = [APP_ROOT / "sections", APP_ROOT / "utils"]
        for root in scanned_roots:
            for path in root.glob("*.py"):
                if path.name == "display.py":
                    continue
                for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    if "st.slider" in line and "day" in line.lower():
                        offenders.append(f"{path.relative_to(APP_ROOT)}:{line_no}:{line.strip()}")
        self.assertEqual(offenders, [])

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

    def test_workspace_sections_use_shared_base_helpers(self):
        base_text = (APP_ROOT / "sections" / "base.py").read_text(encoding="utf-8")
        primitives_text = (APP_ROOT / "utils" / "primitives.py").read_text(encoding="utf-8")
        self.assertIn("class LazyPandas", base_text)
        self.assertIn("def lazy_util", base_text)
        self.assertIn("def safe_float", primitives_text)
        self.assertIn("def safe_int", primitives_text)

        for path in (APP_ROOT / "sections").glob("*.py"):
            if path.name == "base.py":
                continue
            section_text = path.read_text(encoding="utf-8")
            with self.subTest(section=path.name):
                self.assertNotIn("class _LazyPandas", section_text)
                self.assertNotIn("def _lazy_util", section_text)
                self.assertNotIn("def safe_float", section_text)
                self.assertNotIn("def safe_int", section_text)

    def test_fast_shells_use_data_first_brief_pattern(self):
        shell_modules = {
            section: module_path
            for section, module_path in SECTION_MODULES.items()
            if module_path.endswith("_shell")
        }
        self.assertEqual(set(shell_modules), set(ALL_SECTIONS) - {"Security Monitoring"})
        self.assertEqual(SECTION_MODULES["Security Monitoring"], "sections.security_monitoring")
        helper_text = (APP_ROOT / "sections" / "shell_helpers.py").read_text(encoding="utf-8")
        self.assertIn("def full_workspace_requested", helper_text)
        self.assertIn("def render_signal_lane_board", helper_text)
        self.assertIn("if state.get(brief_key):\n        return False", helper_text)
        self.assertIn("state[workspace_key] = True", helper_text)
        self.assertIn("state[brief_key] = False", helper_text)
        for section, module_path in shell_modules.items():
            with self.subTest(section=section):
                shell_path = APP_ROOT / Path(*module_path.split(".")).with_suffix(".py")
                shell_text = shell_path.read_text(encoding="utf-8")
                self.assertIn("_BRIEF_MODE_KEY", shell_text)
                if section == "Executive Landing":
                    self.assertNotIn("def _return_to_brief", shell_text)
                    self.assertNotIn("def _render_back_to_brief_control", shell_text)
                    self.assertNotIn('st.button("Back to Brief"', shell_text)
                    self.assertNotIn("full_workspace_requested(", shell_text)
                    self.assertNotIn("import full_workspace_requested", shell_text)
                    self.assertIn("render_signal_lane_board", shell_text)
                    self.assertNotIn("render_shell_kpi_row", shell_text)
                    self.assertNotIn("render_shell_status_strip", shell_text)
                    self.assertIn("Executive Glance KPIs", shell_text)
                    continue
                self.assertIn("def _return_to_brief", shell_text)
                self.assertIn("def _render_back_to_brief_control", shell_text)
                self.assertIn('st.button("Back to Brief"', shell_text)
                self.assertIn("full_workspace_requested", shell_text)
                self.assertIn("st.session_state[_BRIEF_MODE_KEY] = False", shell_text)
                self.assertIn("st.session_state[_BRIEF_MODE_KEY] = True", shell_text)
                self.assertIn("_render_back_to_brief_control()", shell_text)
                self.assertIn("from sections.shell_helpers import", shell_text)
                self.assertIn("render_signal_lane_board", shell_text)
                self.assertNotIn("render_shell_status_strip", shell_text)
                self.assertNotIn("st.metric(", shell_text)
                self.assertNotIn('st.markdown("**Action Brief**")', shell_text)
                self.assertNotIn("st.columns([1.0, 3.0, 1.8])", shell_text)
                self.assertNotIn("st.columns([1.1, 3.2, 1.4])", shell_text)
                if section in {"DBA Control Room", "Cost & Contract", "Alert Center", "Workload Operations"}:
                    self.assertIn("st.session_state.setdefault(_BRIEF_MODE_KEY, True)", shell_text)
                    self.assertIn("return False", shell_text)
                else:
                    self.assertIn("return full_workspace_requested(st.session_state, _FULL_WORKSPACE_KEY, _BRIEF_MODE_KEY)", shell_text)
                full_request_block = shell_text.split("def _full_workspace_requested() -> bool:", 1)[1].split(
                    "\ndef _",
                    1,
                )[0]
                self.assertNotIn("return evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)", full_request_block)
                self.assertNotIn("if evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS):\n        return True", full_request_block)
                self.assertNotIn('st.markdown("**Operating Snapshot**")', shell_text)
                self.assertNotIn('("Scope", scope_label(_active_company(), _active_environment()))', shell_text)
                self.assertNotIn('("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))', shell_text)
                self.assertNotIn('("Focus"', shell_text)
                self.assertNotIn('"Focus"', shell_text)
                self.assertNotIn("More ", shell_text)
                self.assertNotIn("Hide ", shell_text)
                self.assertNotIn("action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)", shell_text)
                self.assertNotIn("evidence_caption(", shell_text)
                self.assertNotIn("def _render_status_strip", shell_text)
                self.assertNotIn("def _render_kpi_row", shell_text)
                self.assertNotIn("_render_status_strip()", shell_text)
                self.assertNotIn("def _render_action_brief", shell_text)
                self.assertNotIn('st.caption("Ready")', shell_text)
                render_body = shell_text.split("def render() -> None:", 1)[1]
                first_data_call = (
                    "_render_command_snapshot()"
                    if section == "DBA Control Room"
                    else "_render_metric_board()"
                )
                self.assertIn(first_data_call, render_body)
                if "_render_workflow_launchpad()" in render_body:
                    self.assertLess(render_body.index(first_data_call), render_body.index("_render_workflow_launchpad()"))
                if "render_refresh_contract(" in shell_text and "_render_cost_source_contract()" in render_body:
                    self.assertLess(render_body.index(first_data_call), render_body.index("_render_cost_source_contract()"))
        governance_text = (APP_ROOT / "sections" / "security_monitoring.py").read_text(encoding="utf-8")
        self.assertIn("render_signal_lane_board", governance_text)
        self.assertIn("Security Monitoring Command Board", governance_text)

    def test_shell_evidence_label_reflects_loaded_state(self):
        keys = ("loaded_frame", "loaded_error")
        self.assertFalse(evidence_loaded({}, keys))
        self.assertFalse(evidence_loaded({"loaded_frame": None}, keys))
        self.assertTrue(evidence_loaded({"loaded_error": ""}, keys))
        self.assertTrue(evidence_loaded({"loaded_frame": object()}, keys))
        self.assertEqual(compact_environment_label("ALL"), "All env")
        self.assertEqual(compact_environment_label("PROD"), "Prod")
        self.assertEqual(compact_environment_label("DEV_ALL"), "All dev")
        self.assertEqual(compact_environment_label("ALFA_EDW_DEV"), "ALFA_EDW_DEV")
        self.assertEqual(scope_label("Trexis", "DEV_ALL"), "Trexis / All dev")
        self.assertEqual(evidence_label({}, keys), "On demand")
        self.assertEqual(evidence_label({"loaded_frame": None}, keys), "On demand")
        self.assertEqual(evidence_label({"loaded_error": ""}, keys), "Loaded")
        self.assertEqual(evidence_label({"loaded_frame": object()}, keys), "Loaded")
        self.assertEqual(action_state_label({}, keys), "Ready")
        self.assertEqual(action_state_label({"loaded_frame": object()}, keys), "Loaded")
        self.assertEqual(evidence_caption({}, keys, "Load on demand."), "Load on demand.")
        self.assertIn(
            "continue from the saved status",
            evidence_caption({"loaded_frame": object()}, keys, "Load on demand."),
        )

    def test_sidebar_navigation_requests_section_board(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        navigation_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")
        shell_modules = {
            section: module_path
            for section, module_path in SECTION_MODULES.items()
            if module_path.endswith("_shell")
        }

        self.assertIn("SECTION_WORKSPACE_STATE_KEYS = {", app_text)
        self.assertIn("def _request_section_board_state", app_text)
        self.assertIn("_request_section_board_state(target)", app_text)
        self.assertIn('if target == "Executive Landing":', app_text)
        self.assertIn("st.session_state[workspace_key] = False", app_text)
        self.assertIn("st.session_state[brief_key] = True", app_text)
        self.assertIn('st.session_state.pop("_overwatch_pending_autoload_section", None)', app_text)
        self.assertIn('st.session_state.pop("_overwatch_pending_autoload_started_at", None)', app_text)
        self.assertNotIn('st.session_state["_overwatch_pending_autoload_section"] = target', app_text)
        self.assertLess(
            app_text.index("def _request_section_board_state"),
            app_text.index("def _queue_section_navigation"),
        )
        self.assertIn("def request_section_workspace", navigation_text)
        self.assertIn("request_section_workspace(target)", navigation_text)
        for section, module_path in shell_modules.items():
            with self.subTest(section=section):
                shell_path = APP_ROOT / Path(*module_path.split(".")).with_suffix(".py")
                shell_text = shell_path.read_text(encoding="utf-8")
                workspace_key = shell_text.split('_FULL_WORKSPACE_KEY = "', 1)[1].split('"', 1)[0]
                brief_key = shell_text.split('_BRIEF_MODE_KEY = "', 1)[1].split('"', 1)[0]
                self.assertIn(f'"{section}": ("{workspace_key}", "{brief_key}")', app_text)

    def test_direct_section_navigation_uses_compatibility_helper(self):
        navigation_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")
        self.assertIn("def apply_navigation_state", navigation_text)
        self.assertIn("SECTION_WORKSPACE_STATE_KEYS = {", navigation_text)
        self.assertIn("def request_section_workspace", navigation_text)
        self.assertIn("normalize_section_name(raw_section)", navigation_text)
        self.assertIn("compatibility_state_for_section(raw_section)", navigation_text)
        self.assertIn("request_section_workspace(target)", navigation_text)
        self.assertIn('st.session_state["_overwatch_pending_section"] = target', navigation_text)
        self.assertIn('st.session_state["nav_section"] = target', navigation_text)

        direct_nav_modules = {
            "account_health.py": ("apply_navigation_state(section)", "apply_navigation_state(tgt)"),
            "dba_control_room.py": ("apply_navigation_state(raw_target)",),
            "dba_tools.py": ('apply_navigation_state("Alert Center")',),
            "executive_landing.py": ("apply_navigation_state(section)",),
        }
        for file_name, expected_calls in direct_nav_modules.items():
            module_text = (APP_ROOT / "sections" / file_name).read_text(encoding="utf-8")
            with self.subTest(module=file_name):
                self.assertIn("from sections.navigation import apply_navigation_state", module_text)
                for expected_call in expected_calls:
                    self.assertIn(expected_call, module_text)
                self.assertNotIn('st.session_state["nav_section"] =', module_text)

    def test_executive_landing_uses_fast_shell_module(self):
        self.assertEqual(SECTION_MODULES["Executive Landing"], "sections.executive_landing_shell")
        shell_text = (APP_ROOT / "sections" / "executive_landing_shell.py").read_text(encoding="utf-8")
        full_workspace_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")
        shell_import_block = shell_text.split("def _render_status_strip", 1)[0]

        self.assertNotIn("def _delegate_full_workspace", shell_text)
        self.assertNotIn("from sections import executive_landing", shell_text)
        self.assertIn("_FULL_WORKSPACE_KEY", shell_text)
        self.assertIn("_FULL_WORKSPACE_STATE_KEYS", shell_text)
        self.assertNotIn("import pandas", shell_import_block)
        self.assertIn("from utils.command_board import board_rows, load_or_reuse_command_board", shell_import_block)
        self.assertNotIn("load_setup_readiness", shell_import_block)
        self.assertNotIn("from utils import", shell_import_block)
        self.assertNotIn("import utils", shell_import_block)
        self.assertIn("def _render_kpis", shell_text)
        self.assertIn("render_signal_lane_board(", shell_text)
        self.assertNotIn("def _render_status_strip", shell_text)
        self.assertNotIn("render_shell_status_strip(", shell_text)
        self.assertNotIn("st.caption(\n                evidence_caption", shell_text)
        self.assertIn("_PLATFORM_SUMMARY_KEY", shell_text)
        self.assertIn("def _executive_glance_kpis", shell_text)
        self.assertIn("Total spend vs budget", shell_text)
        self.assertIn("Daily burn rate", shell_text)
        self.assertIn("Open critical/high alerts", shell_text)
        self.assertIn("Pipeline SLA compliance", shell_text)
        self.assertIn("Platform risk signals", shell_text)
        self.assertIn("Active issues in queue", shell_text)
        self.assertIn("Executive Glance KPIs", shell_text)
        self.assertIn("7-Day Spend Trend", shell_text)
        self.assertIn("Observability Summary", shell_text)
        self.assertIn("Snowflake Observability Wall", shell_text)
        self.assertIn("Top 5 Action Items", shell_text)
        self.assertNotIn("Setup Readiness", shell_text)
        self.assertNotIn("MART_EXECUTIVE_OBSERVABILITY", shell_text)
        self.assertIn("load_or_reuse_command_board(", shell_text)
        self.assertIn("Copy Executive Summary", shell_text)
        self.assertNotIn('st.markdown("**Platform Operating Score**")', shell_text)
        self.assertNotIn('("Score", "Load snapshot")', shell_text)
        self.assertNotIn("def _render_operating_snapshot", shell_text)
        self.assertNotIn("def _render_workflow_launchpad", shell_text)
        self.assertNotIn("Executive Briefing Workflows", shell_text)
        self.assertNotIn("Open Executive Snapshot", shell_text)
        self.assertNotIn("Open Snapshot", shell_text)
        self.assertNotIn("Open PowerPoint", shell_text)
        self.assertNotIn("Open Alerts", shell_text)
        self.assertNotIn("Open FinOps", shell_text)
        self.assertNotIn("Open DBA Queue", shell_text)
        self.assertNotIn("Open Setup", shell_text)
        self.assertNotIn("_SECTION_WORKSPACE_KEYS", shell_text)
        self.assertNotIn("def _open_target_workspace", shell_text)
        self.assertNotIn("from sections.navigation import apply_navigation_state", shell_text)
        self.assertNotIn("alert_center_requested_view", shell_text)
        self.assertNotIn("cost_contract_workflow", shell_text)
        self.assertNotIn("_cost_contract_pending_detail_workflow", shell_text)
        self.assertNotIn("dba_control_room_active_view", shell_text)
        self.assertNotIn("change_drift_requested_view", shell_text)
        self.assertNotIn("change_drift_requested_workflow", shell_text)
        self.assertNotIn("change_drift_workflow", shell_text)
        self.assertNotIn("def _build_executive_snapshot_pptx", full_workspace_text)

    def test_dba_control_room_uses_fast_shell_module(self):
        self.assertEqual(SECTION_MODULES["DBA Control Room"], "sections.dba_control_room_shell")
        shell_text = (APP_ROOT / "sections" / "dba_control_room_shell.py").read_text(encoding="utf-8")
        full_workspace_text = (APP_ROOT / "sections" / "dba_control_room.py").read_text(encoding="utf-8")
        shell_import_block = shell_text.split("def _delegate_full_workspace", 1)[0]

        self.assertIn("def _delegate_full_workspace", shell_text)
        self.assertIn("from sections import dba_control_room", shell_text)
        self.assertIn("_FULL_WORKSPACE_KEY", shell_text)
        self.assertNotIn("import pandas", shell_import_block)
        self.assertIn("from utils.command_board import load_or_reuse_command_board", shell_import_block)
        self.assertNotIn("from utils import", shell_import_block)
        self.assertNotIn("import utils", shell_import_block)
        self.assertNotIn("st.number_input", shell_text)
        self.assertNotIn("def _render_status_strip", shell_text)
        self.assertNotIn("def _render_kpi_row", shell_text)
        self.assertNotIn("render_shell_status_strip(", shell_text)
        self.assertIn("def _render_command_snapshot", shell_text)
        self.assertIn("def _apply_fast_entry_default", shell_text)
        self.assertIn("_FAST_ENTRY_VERSION = 2", shell_text)
        self.assertIn("st.session_state[_FULL_WORKSPACE_KEY] = False", shell_text)
        self.assertNotIn("render_refresh_contract(", shell_text)
        self.assertIn("DBA Command Snapshot", shell_text)
        self.assertIn("Morning Route Board", shell_text)
        self.assertNotIn("DBA Mart Contract", shell_text)
        self.assertNotIn("MART_DBA_CONTROL_ROOM", shell_text)
        self.assertNotIn("MART_EXECUTIVE_OBSERVABILITY", shell_text)
        self.assertIn("def _load_command_board", shell_text)
        self.assertIn("load_or_reuse_command_board(", shell_text)
        self.assertIn("open the heavy workspace only from a selected DBA route", shell_text)
        self.assertIn("st.session_state.setdefault(_BRIEF_MODE_KEY, True)", shell_text)
        self.assertNotIn("def _render_operating_snapshot", shell_text)
        self.assertIn("def _render_workflow_launchpad", shell_text)
        self.assertIn("_WORKFLOWS", shell_text)
        self.assertNotIn('st.markdown("**Operating Snapshot**")', shell_text)
        self.assertIn("DBA Control Workflows", shell_text)
        self.assertIn("Open Fast Watch", shell_text)
        self.assertIn("Open Morning Brief", shell_text)
        self.assertIn("Open Ops Board", shell_text)
        self.assertIn("Open Triage", shell_text)
        self.assertNotIn("Open Release Gate", shell_text)
        self.assertNotIn("Open Compare", shell_text)
        self.assertNotIn("Open Telemetry Inputs", shell_text)
        self.assertIn("Open Service Posture", shell_text)
        self.assertIn("Open Brief Export", shell_text)
        self.assertIn("render_shell_workflows(", shell_text)
        self.assertNotIn("More DBA Workflows", shell_text)
        self.assertIn("dba_control_room_active_view", shell_text)
        self.assertNotIn("render_shell_snapshot(metrics)", shell_text)
        self.assertNotIn("cols = st.columns(4)", shell_text)
        self.assertNotIn('("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS))', shell_text)
        self.assertNotIn('("Rate", f"${_credit_price():.2f}")', shell_text)
        self.assertNotIn('("Budget"', shell_text)
        self.assertIn("with_loaded_at(", full_workspace_text)
        self.assertIn("source=getattr(snapshot_result, \"source\", \"Fast summary snapshot\")", full_workspace_text)
        self.assertIn("DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS = 24", full_workspace_text)
        self.assertIn("DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS", full_workspace_text)
        self.assertIn('"Morning Brief"', full_workspace_text)
        self.assertIn('"Morning Brief": "Morning"', full_workspace_text)
        self.assertIn('elif active_view in {"Operations Board", "Morning Brief"}:', full_workspace_text)
        self.assertIn('load_label = "Refresh DBA Morning Brief"', full_workspace_text)
        self.assertIn('st.session_state["dba_operations_board_detail"] = ops_detail', full_workspace_text)
        self.assertIn('"Service Posture"', full_workspace_text)
        self.assertIn('from sections import service_health', full_workspace_text)
        self.assertIn("service_health.render()", full_workspace_text)
        self.assertIn('st.session_state.get("dba_control_room_active_view") == "Service Posture"', full_workspace_text)
        service_posture_block = full_workspace_text.split('st.session_state.get("dba_control_room_active_view") == "Service Posture"', 1)[1].split(
            'if not data:',
            1,
        )[0]
        self.assertIn("_render_consolidated_service_posture()", service_posture_block)
        self.assertIn("guarded live checks are reserved for explicit detail loads", full_workspace_text)
        self.assertNotIn("Allow live ACCOUNT_USAGE fallback queries", full_workspace_text)

    def test_alert_center_uses_fast_shell_module(self):
        self.assertEqual(SECTION_MODULES["Alert Center"], "sections.alert_center_shell")
        shell_text = (APP_ROOT / "sections" / "alert_center_shell.py").read_text(encoding="utf-8")
        full_workspace_text = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        shell_import_block = shell_text.split("def _delegate_full_workspace", 1)[0]

        self.assertIn("def _delegate_full_workspace", shell_text)
        self.assertIn("from sections import alert_center", shell_text)
        self.assertIn("_FULL_WORKSPACE_KEY", shell_text)
        self.assertIn("_FULL_WORKSPACE_STATE_KEYS", shell_text)
        self.assertIn("def _apply_fast_entry_default", shell_text)
        self.assertIn("_FAST_ENTRY_VERSION = 1", shell_text)
        self.assertIn("st.session_state[_FULL_WORKSPACE_KEY] = False", shell_text)
        self.assertIn("st.session_state.setdefault(_BRIEF_MODE_KEY, True)", shell_text)
        render_preload = shell_text.split("def render() -> None:", 1)[1].split("if _full_workspace_requested():", 1)[0]
        self.assertIn("_apply_fast_entry_default()", render_preload)
        self.assertNotIn("import pandas", shell_import_block)
        self.assertIn("from utils.command_board import load_or_reuse_command_board", shell_import_block)
        self.assertNotIn("from utils import", shell_import_block)
        self.assertNotIn("import utils", shell_import_block)
        self.assertNotIn("def _render_status_strip", shell_text)
        self.assertNotIn("def _render_kpi_row", shell_text)
        self.assertNotIn("render_shell_status_strip(", shell_text)
        self.assertIn("def _render_metric_board", shell_text)
        self.assertIn("Alert Command Board", shell_text)
        self.assertIn("Alert Lifecycle Board", shell_text)
        self.assertNotIn("Alert Object Contract", shell_text)
        self.assertNotIn("render_refresh_contract(", shell_text)
        self.assertNotIn("ALERT_EVENTS / ALERT_ACTION_QUEUE", shell_text)
        self.assertNotIn("MART_EXECUTIVE_OBSERVABILITY", shell_text)
        self.assertIn("critical_high_alerts", shell_text)
        self.assertIn("current_cost_usd", shell_text)
        self.assertIn("cortex_cost_usd", shell_text)
        self.assertIn("_load_command_board()", shell_text)
        self.assertIn("load_or_reuse_command_board(", shell_text)
        self.assertNotIn("def _render_operating_snapshot", shell_text)
        self.assertIn("def _render_workflow_launchpad", shell_text)
        self.assertIn("Alert Command Workflows", shell_text)
        self.assertIn("Open Command Center", shell_text)
        self.assertIn("Open Morning Brief", shell_text)
        self.assertIn("Open Detection Catalog", shell_text)
        self.assertIn("Open Issue Inbox", shell_text)
        self.assertIn("Open Triage Digest", shell_text)
        self.assertIn("Open Delivery", shell_text)
        self.assertIn("Open Queue Routing", shell_text)
        self.assertNotIn("Open Automation", shell_text)
        self.assertIn("Open Remediation", shell_text)
        self.assertNotIn("Open Setup", shell_text)
        self.assertIn("alert_center_requested_view", shell_text)
        self.assertIn("ALERT_CENTER_PANES", full_workspace_text)

    def test_security_monitoring_keeps_security_surface_narrow(self):
        self.assertEqual(SECTION_MODULES["Security Monitoring"], "sections.security_monitoring")
        wrapper_text = (APP_ROOT / "sections" / "security_monitoring.py").read_text(encoding="utf-8")
        security_text = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")

        self.assertIn('VIEWS = ("Security Posture",)', wrapper_text)
        self.assertIn('importlib.import_module("sections.security_posture")', wrapper_text)
        self.assertIn("security_monitoring_view", wrapper_text)
        self.assertIn("def _apply_fast_entry_default", wrapper_text)
        self.assertIn("_FAST_ENTRY_VERSION = 1", wrapper_text)
        self.assertNotIn("def _render_status_strip", wrapper_text)
        self.assertNotIn("def _render_kpi_row", wrapper_text)
        self.assertNotIn("render_shell_status_strip(", wrapper_text)
        self.assertIn("def _render_metric_board", wrapper_text)
        self.assertIn("Security Monitoring Command Board", wrapper_text)
        self.assertIn("Security Monitoring Detail", wrapper_text)
        self.assertNotIn("sections.change_drift", wrapper_text)
        self.assertNotIn("Change & Drift", wrapper_text)
        self.assertNotIn("Privilege & Setup Readiness", wrapper_text)
        self.assertNotIn("Snowflake Role Contract", wrapper_text)
        self.assertNotIn("load_setup_readiness", wrapper_text)
        self.assertNotIn("OVERWATCH_MONITOR", wrapper_text)
        self.assertNotIn("OVERWATCH_OPERATOR", wrapper_text)
        self.assertNotIn("render_refresh_contract(", wrapper_text)
        self.assertIn("Security Monitoring Detail", wrapper_text)
        self.assertIn("Open Security Detail", wrapper_text)
        self.assertIn("st.session_state.setdefault(_BRIEF_MODE_KEY, True)", wrapper_text)
        self.assertIn("render_shell_workflows(", wrapper_text)
        self.assertIn("_security_posture_full_workspace_requested", wrapper_text)
        self.assertIn("SECURITY_POSTURE_VIEWS", security_text)

    def test_workload_operations_uses_fast_shell_module(self):
        self.assertEqual(SECTION_MODULES["Workload Operations"], "sections.workload_operations_shell")
        shell_text = (APP_ROOT / "sections" / "workload_operations_shell.py").read_text(encoding="utf-8")
        full_workspace_text = (APP_ROOT / "sections" / "workload_operations.py").read_text(encoding="utf-8")
        shell_import_block = shell_text.split("def _delegate_full_workspace", 1)[0]

        self.assertIn("def _delegate_full_workspace", shell_text)
        self.assertIn("from sections import workload_operations", shell_text)
        self.assertIn("_FULL_WORKSPACE_KEY", shell_text)
        self.assertIn("_FULL_WORKSPACE_STATE_KEYS", shell_text)
        self.assertNotIn("import pandas", shell_import_block)
        self.assertIn("from utils.command_board import load_or_reuse_command_board", shell_import_block)
        self.assertNotIn("from utils import", shell_import_block)
        self.assertNotIn("import utils", shell_import_block)
        self.assertNotIn("def _render_status_strip", shell_text)
        self.assertNotIn("def _render_kpi_row", shell_text)
        self.assertNotIn("render_shell_status_strip(", shell_text)
        self.assertIn("def _render_metric_board", shell_text)
        self.assertIn("Workload Command Board", shell_text)
        self.assertIn("Contention Solution Board", shell_text)
        self.assertIn("Contention Answer Model", shell_text)
        self.assertIn("Safe Fix Status", shell_text)
        self.assertNotIn("render_refresh_contract(", shell_text)
        self.assertNotIn("MART_EXECUTIVE_OBSERVABILITY", shell_text)
        self.assertIn("_load_command_board()", shell_text)
        self.assertIn("load_or_reuse_command_board(", shell_text)
        self.assertIn('st.session_state.setdefault(_BRIEF_MODE_KEY, True)', shell_text)
        self.assertNotIn("def _render_operating_snapshot", shell_text)
        self.assertIn("Workload Investigation Workflows", shell_text)
        self.assertNotIn("Open Workload Workspace", shell_text)
        self.assertIn("Open Task Graphs", shell_text)
        self.assertIn("Open Contention", shell_text)
        self.assertIn("Open Query Diagnosis", shell_text)
        self.assertIn("Open Live Triage", shell_text)
        self.assertIn("_EXPLICIT_WORKFLOW_KEY", shell_text)
        self.assertIn("st.session_state[_EXPLICIT_WORKFLOW_KEY] = True", shell_text)
        self.assertIn("WORKLOAD_OPERATIONS_VIEWS", full_workspace_text)
        self.assertIn("WORKLOAD_OPERATIONS_EXPLICIT_WORKFLOW_KEY", full_workspace_text)
        self.assertIn(
            'st.session_state.get("workload_operations_view") == "Specialist Workflows" and not explicit_workflow_request',
            full_workspace_text,
        )

    def test_cost_contract_uses_fast_shell_module(self):
        self.assertEqual(SECTION_MODULES["Cost & Contract"], "sections.cost_contract_shell")
        shell_text = (APP_ROOT / "sections" / "cost_contract_shell.py").read_text(encoding="utf-8")
        full_workspace_text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        shell_import_block = shell_text.split("def _delegate_full_workspace", 1)[0]

        self.assertIn("def _delegate_full_workspace", shell_text)
        self.assertIn("from sections import cost_contract", shell_text)
        self.assertIn("_FULL_WORKSPACE_KEY", shell_text)
        self.assertIn("_FULL_WORKSPACE_STATE_KEYS", shell_text)
        self.assertIn("def _apply_fast_entry_default", shell_text)
        self.assertIn("_FAST_ENTRY_VERSION = 1", shell_text)
        self.assertIn("st.session_state[_FULL_WORKSPACE_KEY] = False", shell_text)
        self.assertIn("st.session_state.setdefault(_BRIEF_MODE_KEY, True)", shell_text)
        render_preload = shell_text.split("def render() -> None:", 1)[1].split("if _full_workspace_requested():", 1)[0]
        self.assertIn("_apply_fast_entry_default()", render_preload)
        self.assertNotIn("_DETAIL_WORKFLOW_KEY", shell_text)
        self.assertNotIn("_PENDING_DETAIL_WORKFLOW_KEY", shell_text)
        self.assertNotIn("import pandas", shell_import_block)
        self.assertIn("from utils.command_board import load_or_reuse_command_board", shell_import_block)
        self.assertNotIn("from utils import", shell_import_block)
        self.assertNotIn("import utils", shell_import_block)
        self.assertNotIn("def _render_status_strip", shell_text)
        self.assertNotIn("def _render_kpi_row", shell_text)
        self.assertNotIn("render_shell_status_strip(", shell_text)
        self.assertIn("def _render_metric_board", shell_text)
        self.assertIn("Cost Command Board", shell_text)
        self.assertIn("Cost Signals", shell_text)
        self.assertIn("Cost Executive Flow", shell_text)
        self.assertNotIn("Cost Mart Contract", shell_text)
        self.assertNotIn("render_refresh_contract(", shell_text)
        self.assertNotIn("FACT_COST_DAILY / FACT_CORTEX_DAILY", shell_text)
        self.assertNotIn("MART_EXECUTIVE_OBSERVABILITY", shell_text)
        self.assertIn("load_or_reuse_command_board(", shell_text)
        self.assertIn('("Current Spend", "Awaiting data")', shell_text)
        self.assertIn('("30d Forecast", "Awaiting data")', shell_text)
        self.assertIn('("Open Est. Savings", _money(board.get("est_savings")) if board["loaded"] else "Awaiting data")', shell_text)
        self.assertNotIn("def _render_operating_snapshot", shell_text)
        self.assertIn("Cost Investigation Workflows", shell_text)
        self.assertIn("Open Cost Overview", shell_text)
        self.assertIn("render_shell_workflows(", shell_text)
        self.assertNotIn("visible = _WORKFLOWS[1:4]", shell_text)
        self.assertNotIn("extra_cols", shell_text)
        self.assertIn("Open FinOps", shell_text)
        self.assertIn("Open Cortex Spend", shell_text)
        self.assertIn("Open Budgets", shell_text)
        self.assertIn("Open Storage Cost", shell_text)
        self.assertIn("cost_contract_workflow", shell_text)
        self.assertNotIn("open_detail", shell_text)
        self.assertIn("WORKFLOWS", full_workspace_text)
        self.assertIn('"Storage cost and retention"', full_workspace_text)
        self.assertIn('"Storage cost and retention": "sections.storage_monitor"', full_workspace_text)
        self.assertIn("_PENDING_DETAIL_WORKFLOW_KEY", full_workspace_text)
        self.assertNotIn("_AUTO_OPEN_DETAIL_WORKFLOWS", full_workspace_text)
        self.assertIn("routed_workflow = st.session_state.pop(_PENDING_DETAIL_WORKFLOW_KEY, None)", full_workspace_text)
        self.assertIn("legacy_detail_workflow = st.session_state.pop(_DETAIL_WORKFLOW_KEY, None)", full_workspace_text)
        self.assertNotIn('st.button("Open detail"', full_workspace_text)
        self.assertIn("render_workflow_module(workflow, WORKFLOW_MODULES)", full_workspace_text)

    def test_roles_and_aliases_resolve_to_visible_sections(self):
        primary_sections = [section for section in ALL_SECTIONS if section not in PRIMARY_NAV_HIDDEN_SECTIONS]
        for role, sections in ROLE_SECTIONS.items():
            with self.subTest(role=role):
                self.assertTrue(sections)
                self.assertLessEqual(set(sections), set(ALL_SECTIONS))
                self.assertNotIn("Account Health", sections)
        self.assertIn("Workload Operations", ROLE_SECTIONS["ANALYST"])
        self.assertIn("Workload Operations", ROLE_SECTIONS["MANAGER"])
        self.assertIn("Security Monitoring", ROLE_SECTIONS["ANALYST"])
        self.assertNotIn("Security Posture", ROLE_SECTIONS["ANALYST"])
        self.assertNotIn("Change & Drift", ROLE_SECTIONS["ANALYST"])
        self.assertEqual(ROLE_SECTIONS["MANAGER"], primary_sections)
        self.assertEqual(ROLE_SECTIONS["DBA"], primary_sections)

        role_profile_cases = {
            "SNOW_PRI_GFR_PRD_ALFA_PDMWMGMT": "EXECUTIVE",
            "SNOW_PRI_GFR_PRD_ALFA_DSA": "MANAGER",
            "SNOW_PRI_GFR_PRD_ALFA_DTI": "ANALYST",
            "SNOW_PRI_GFR_NONPRD_ALFA_PDMWMGMT": "EXECUTIVE",
            "SNOW_PRI_GFR_NONPRD_ALFA_DSA": "MANAGER",
            "SNOW_PRI_GFR_NONPRD_ALFA_DTI": "ANALYST",
            "SNOW_ACCOUNTADMINS": "DBA",
            "SNOW_SYSADMINS": "DBA",
            "ACCOUNTADMIN": "DBA",
        }
        for role, expected_profile in role_profile_cases.items():
            with self.subTest(role_profile=role):
                self.assertEqual(resolve_role_profile(role), expected_profile)
        self.assertEqual(resolve_role_profile("SNOW_PRI_UNKNOWN_VIEWER"), "REPORT")
        self.assertEqual(resolve_role_profile(""), "REPORT")
        self.assertIn("Workload Operations", ROLE_SECTIONS[resolve_role_profile("SNOW_PRI_GFR_PRD_ALFA_DTI")])
        self.assertEqual(ROLE_SECTIONS[resolve_role_profile("SNOW_PRI_GFR_PRD_ALFA_DSA")], primary_sections)
        self.assertEqual(resolve_allowed_experience_views("SNOW_PRI_GFR_PRD_ALFA_PDMWMGMT"), ("Executive",))
        self.assertEqual(
            resolve_allowed_experience_views("SNOW_PRI_GFR_PRD_ALFA_DSA"),
            ("Executive", "FinOps", "Security", "Platform"),
        )
        self.assertEqual(resolve_allowed_experience_views("SNOW_PRI_GFR_PRD_ALFA_DTI"), ("Platform",))
        self.assertEqual(resolve_allowed_experience_views("SNOW_ACCOUNTADMINS"), tuple(EXPERIENCE_VIEW_SECTIONS.keys()))
        self.assertEqual(resolve_allowed_experience_views("SNOW_SYSADMINS"), tuple(EXPERIENCE_VIEW_SECTIONS.keys()))
        self.assertEqual(resolve_allowed_experience_views("ACCOUNTADMIN"), tuple(EXPERIENCE_VIEW_SECTIONS.keys()))
        self.assertEqual(default_experience_view_for_role("SNOW_PRI_GFR_PRD_ALFA_DSA"), "Executive")
        self.assertEqual(default_experience_view_for_role("SNOW_PRI_GFR_PRD_ALFA_DTI"), "Platform")
        self.assertEqual(default_experience_view_for_role("SNOW_ACCOUNTADMINS"), "DBA")
        self.assertIn("Workload Operations", EXPERIENCE_VIEW_SECTIONS["Platform"])

        self.assertEqual(set(SECTION_BY_TITLE), set(ALL_SECTIONS))
        self.assertLessEqual(set(SECTION_ALIASES.values()), set(ALL_SECTIONS))
        self.assertLessEqual(set(SECTION_REDIRECTS.values()), set(ALL_SECTIONS))
        for alias, target in SECTION_REDIRECTS.items():
            with self.subTest(alias=alias):
                self.assertEqual(SECTION_ALIASES[alias], target)
                self.assertEqual(normalize_section_name(alias), target)
                self.assertNotIn(alias, SECTION_BY_TITLE)
        self.assertEqual(RETIRED_SECTION_REDIRECTS["Account Health"], SECTION_BY_TITLE["DBA Control Room"])
        self.assertEqual(SECTION_ALIASES["Account Health"], SECTION_BY_TITLE["DBA Control Room"])
        self.assertEqual(normalize_section_name("Account Health"), SECTION_BY_TITLE["DBA Control Room"])
        self.assertEqual(
            compatibility_state_for_section("Account Health"),
            {
                "dba_control_room_active_view": "Morning Brief",
                "_dba_control_room_full_workspace_requested": True,
                "_dba_control_room_brief_mode": False,
            },
        )
        self.assertEqual(SECTION_ALIASES["Credit Contract"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Cost Center"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Security & Access"], SECTION_BY_TITLE["Security Monitoring"])
        self.assertEqual(SECTION_ALIASES["DBA Tools"], SECTION_BY_TITLE["Workload Operations"])
        self.assertEqual(SECTION_ALIASES["Optimization"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Warehouse Health"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertNotIn("Architecture", SECTION_ALIASES)
        self.assertNotIn("Architecture Readiness", SECTION_ALIASES)
        self.assertNotIn("Disaster Recovery", SECTION_ALIASES)
        self.assertEqual(SECTION_ALIASES["Executive Briefing"], SECTION_BY_TITLE["Executive Landing"])
        self.assertNotIn("LEGACY_SECTION_ALIASES", (APP_ROOT / "config.py").read_text(encoding="utf-8"))

    def test_experience_views_are_registered(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")

        self.assertIn("Executive Landing", ALL_SECTIONS)
        self.assertEqual(SECTION_MODULES["Executive Landing"], "sections.executive_landing_shell")
        self.assertIn("EXPERIENCE_VIEW_SECTIONS", config_text)
        self.assertIn("ROLE_EXPERIENCE_VIEWS", config_text)
        self.assertIn("resolve_allowed_experience_views", config_text)
        self.assertIn("default_experience_view_for_role", config_text)
        self.assertIn("Navigation View", app_text)
        self.assertIn("def _apply_role_based_defaults", app_text)
        self.assertIn("exceptions_only_mode", app_text)
        self.assertIn("def _allowed_experience_options", app_text)
        self.assertIn("def _current_experience_view", app_text)
        self.assertIn("_sync_experience_navigation", app_text)
        self.assertIn("on_change=_sync_experience_navigation", app_text)
        for profile, sections in EXPERIENCE_VIEW_SECTIONS.items():
            with self.subTest(profile=profile):
                self.assertTrue(sections)
                self.assertLessEqual(set(sections), set(ALL_SECTIONS))
        self.assertIn("Executive Landing", EXPERIENCE_VIEW_SECTIONS["Executive"])
        self.assertIn("Cost & Contract", EXPERIENCE_VIEW_SECTIONS["FinOps"])
        self.assertIn("Security Monitoring", EXPERIENCE_VIEW_SECTIONS["Security"])
        for profile, sections in EXPERIENCE_VIEW_SECTIONS.items():
            with self.subTest(hidden_section_experience=profile):
                self.assertNotIn("Account Health", sections)
                self.assertNotIn("Warehouse Health", sections)
                self.assertNotIn("Architecture Readiness", sections)
        for profile, views in ROLE_EXPERIENCE_VIEWS.items():
            with self.subTest(role_experience=profile):
                self.assertTrue(views)
                self.assertLessEqual(set(views), set(EXPERIENCE_VIEW_SECTIONS))

    def test_executive_landing_routes_to_workflow_panes(self):
        executive_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")

        self.assertIn("_source_health_rows", executive_text)
        self.assertIn("Executive Data Health", executive_text)
        self.assertIn('"alert_center_active_view": "Automation Health"', executive_text)
        self.assertIn('workflow_key="cost_contract_workflow"', executive_text)
        self.assertIn('workflow="FinOps Control Center"', executive_text)
        self.assertIn('workflow_key="change_drift_workflow"', executive_text)
        self.assertIn('workflow="Controlled DBA actions"', executive_text)
        self.assertIn('"dba_tools_group_selector": "Cost & Health"', executive_text)
        self.assertIn('"dba_tools_tool_selector_Cost & Health": "Data Health"', executive_text)

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
        ask_text = (APP_ROOT / "utils" / "ask_overwatch.py").read_text(encoding="utf-8")
        self.assertNotIn("Top Priority Brief", app_text)
        self.assertNotIn("Open Executive Landing for the ranked platform brief.", app_text)
        self.assertNotIn("ow-priority-empty", app_text)
        self.assertNotIn("load or refresh a section to populate priority evidence", app_text)
        self.assertNotIn('"top_priority_brief_domain"', app_text)
        self.assertNotIn("build_top_priority_brief_cards(", app_text)
        self.assertNotIn("_render_top_priority_brief", app_text)
        self.assertIn("build_top_priority_brief_cards(", ask_text)
        self.assertIn('"rec_automation_board"', ask_text)
        self.assertNotIn('"arch_futures_board"', ask_text)
        self.assertNotIn('"account_health_morning_exceptions"', app_text)
        self.assertIn('"account_health_morning_exceptions"', ask_text)
        self.assertNotIn('"account_health_operator_gates"', app_text)
        self.assertIn('"account_health_operator_gates"', ask_text)
        self.assertNotIn('"security_posture_summary"', app_text)
        self.assertIn('"security_posture_summary"', ask_text)
        self.assertNotIn('"security_posture_exceptions"', app_text)
        self.assertIn('"security_posture_exceptions"', ask_text)
        self.assertNotIn('"ask_overwatch_panel_toggle"', app_text)
        self.assertNotIn('st.expander("Ask OVERWATCH", expanded=True)', app_text)
        self.assertNotIn('"Ask a specific DBA operating question..."', app_text)
        self.assertNotIn("SNOWFLAKE.CORTEX.COMPLETE", app_text)

    def test_workflow_hubs_replace_scattered_operational_pages(self):
        visible_titles = {section.title for section in SECTION_DEFINITIONS}
        self.assertIn("Alert Center", visible_titles)
        self.assertIn("Workload Operations", visible_titles)
        self.assertIn("Cost & Contract", visible_titles)
        self.assertIn("Security Monitoring", visible_titles)
        for retired_title in (
            "Account Health",
            "Warehouse Health",
            "Architecture Readiness",
            "Security Posture",
            "Change & Drift",
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

    def test_workflow_hubs_expose_expected_subworkflows(self):
        from sections import change_drift, cost_contract, dba_control_room, query_analysis, security_posture, task_management, workload_operations

        self.assertIn("Query diagnosis", workload_operations.WORKFLOWS)
        self.assertIn("Contention Center", workload_operations.WORKFLOWS)
        self.assertIn("Task graphs", workload_operations.WORKFLOWS)
        self.assertIn("Stored procedures", workload_operations.WORKFLOWS)
        self.assertNotIn("History search", workload_operations.WORKFLOWS)
        self.assertIn("History Search", query_analysis.QUERY_ANALYSIS_PANES)
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Contention Center"], "sections.contention_center")
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Query diagnosis"], "sections.query_analysis")
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Task graphs"], "sections.task_management")
        self.assertEqual(task_management.TASK_CONTROL_VIEWS[0], "Job Status Brief")
        self.assertIn("Snowflake task handoff", task_management.TASK_CONTROL_DETAILS["Job Status Brief"])
        task_management_text = (APP_ROOT / "sections" / "task_management.py").read_text(encoding="utf-8")
        self.assertIn('allow_live_fallback=False', task_management_text)
        self.assertIn('"Loading latest task summary snapshot..."', task_management_text)
        self.assertIn('refresh_mode="summary snapshot"', task_management_text)
        self.assertNotIn("OVERWATCH_EXTERNAL_CONTROL_FEED", task_management_text)
        self.assertNotIn("Imported Snowflake task evidence", task_management_text)
        self.assertNotIn("Snowflake task feed setup", task_management_text)
        self.assertNotIn("Download Snowflake task Feed SQL", task_management_text)
        self.assertNotIn("OVERWATCH_TASK_STATUS_FEED_STAGE", task_management_text)
        self.assertIn('"Performance Indicators"', task_management_text)
        self.assertNotIn('"Perf Indicators"', task_management_text)
        self.assertIn("from sections.shell_helpers import render_shell_snapshot", task_management_text)
        self.assertIn('("Handoff State", task_status_state)', task_management_text)
        self.assertIn('"Performance Indicators"', task_management_text)
        self.assertIn('"SLA / Cost Drift"', task_management_text)
        self.assertIn('("Query Detail"', task_management_text)
        self.assertNotIn(".metric(", task_management_text)
        self.assertIn("Service Posture", dba_control_room.DBA_CONTROL_ROOM_PANES)
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Service Posture"], "Service")
        self.assertIn("Morning Brief", dba_control_room.DBA_CONTROL_ROOM_PANES)
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Morning Brief"], "Morning")
        self.assertEqual(
            cost_contract.WORKFLOWS[:5],
            (
                "Explain bill / attribution / contract",
                "Storage cost and retention",
                "Budget Monitoring",
                "Recommendations and action queue",
                "FinOps Control Center",
            ),
        )
        self.assertIn("Recommendations and action queue", cost_contract.WORKFLOWS)
        self.assertIn("Storage cost and retention", cost_contract.WORKFLOWS)
        self.assertEqual(cost_contract.WORKFLOW_MODULES["Storage cost and retention"], "sections.storage_monitor")
        self.assertIn("Budget Monitoring", cost_contract.WORKFLOWS)
        self.assertEqual(cost_contract.WORKFLOW_MODULES["Budget Monitoring"], "sections.budget_monitoring")
        self.assertEqual(cost_contract.WORKFLOW_MODULES["AI and Cortex spend"], "sections.cortex_monitor")
        budget_monitoring_text = (APP_ROOT / "sections" / "budget_monitoring.py").read_text(encoding="utf-8")
        self.assertIn("display_inventory = apply_operator_status_labels", budget_monitoring_text)
        self.assertIn("add_cost_companion_columns(prioritize_context_columns(inventory))", budget_monitoring_text)
        self.assertIn("from sections.shell_helpers import render_shell_snapshot", budget_monitoring_text)
        self.assertIn('"Tracked Signals"', budget_monitoring_text)
        self.assertNotIn("_build_native_budget_sql", budget_monitoring_text)
        self.assertNotIn("_build_per_user_quota_sql", budget_monitoring_text)
        self.assertNotIn("_build_budget_custom_action_sql", budget_monitoring_text)
        self.assertNotIn(".metric(", budget_monitoring_text)
        self.assertEqual(SECTION_ALIASES["Alerts"], SECTION_BY_TITLE["Alert Center"])
        self.assertIn("Access posture", security_posture.WORKFLOWS)
        self.assertIn("Privilege sprawl", security_posture.WORKFLOWS)
        self.assertEqual(security_posture.WORKFLOW_MODULES["Access posture"], "sections.security_access")
        self.assertNotIn("Release evidence", change_drift.WORKFLOWS)
        self.assertNotIn("Owner approval evidence", change_drift.WORKFLOWS)
        self.assertIn("Schema and object drift", change_drift.WORKFLOWS)
        self.assertIn("Data movement and replication", change_drift.WORKFLOWS)
        self.assertIn("Controlled DBA actions", change_drift.WORKFLOWS)
        self.assertEqual(change_drift.WORKFLOW_MODULES["Controlled DBA actions"], "sections.dba_tools")
        change_drift_text = (APP_ROOT / "sections" / "change_drift.py").read_text(encoding="utf-8")
        dba_tools_text = (APP_ROOT / "sections" / "dba_tools.py").read_text(encoding="utf-8")
        object_change_text = (APP_ROOT / "sections" / "object_change_monitor.py").read_text(encoding="utf-8")
        self.assertIn('st.session_state["dba_tools_focus_tool"] = "Schema Compare"', change_drift_text)
        self.assertIn('focus_tool = str(st.session_state.get("dba_tools_focus_tool") or "")', dba_tools_text)
        self.assertIn("focus_tool_active = (", dba_tools_text)
        self.assertIn("selected_tool = focus_tool", dba_tools_text)
        self.assertIn("if not focus_tool_active:", dba_tools_text)
        self.assertNotIn('st.header("Who Changed What?")', object_change_text)
        self.assertEqual(
            change_drift.WORKFLOWS[:5],
            (
                "Object and access changes",
                "Schema and object drift",
                "Data movement and replication",
                "Stored procedure lineage",
                "Controlled DBA actions",
            ),
        )

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

    def test_cost_contract_workflow_detail_renders_on_selection(self):
        text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")

        self.assertIn('_DETAIL_WORKFLOW_KEY = "_cost_contract_detail_workflow"', text)
        self.assertNotIn('st.button("Open detail"', text)
        self.assertNotIn("if open_workflow == workflow:", text)
        self.assertIn("routed_workflow = st.session_state.pop(_PENDING_DETAIL_WORKFLOW_KEY, None)", text)
        self.assertIn("legacy_detail_workflow = st.session_state.pop(_DETAIL_WORKFLOW_KEY, None)", text)
        self.assertNotIn('st.button("Open full cockpit boards"', text)
        self.assertNotIn("_FULL_COCKPIT_BOARDS_KEY", text)
        self.assertIn("render_workflow_module(workflow, WORKFLOW_MODULES)", text)

    def test_navigation_labels_are_plain_titles(self):
        for section in ALL_SECTIONS:
            with self.subTest(section=section):
                self.assertEqual(section, section.strip())
                self.assertTrue(all(ord(ch) < 128 for ch in section))

    def test_specialist_pages_use_compact_headings(self):
        compact_files = [
            "cost_center.py",
            "data_sharing.py",
            "detailed_diagnosis.py",
            "query_search.py",
            "service_health.py",
            "snowflake_value.py",
            "spcs_tracker.py",
            "storage_monitor.py",
            "stored_proc_tracker.py",
        ]
        for filename in compact_files:
            with self.subTest(filename=filename):
                section_text = (APP_ROOT / "sections" / filename).read_text(encoding="utf-8")
                self.assertNotIn("st.header(", section_text)
                self.assertIn("st.subheader(", section_text)

    def test_consolidated_shells_use_shared_workflow_selector(self):
        consolidated_files = [
            "change_drift.py",
            "cost_contract.py",
            "security_posture.py",
            "warehouse_health.py",
            "workload_operations.py",
        ]
        for filename in consolidated_files:
            with self.subTest(filename=filename):
                section_text = (APP_ROOT / "sections" / filename).read_text(encoding="utf-8")
                self.assertNotIn("def render_workflow_selector", section_text)
                self.assertIn('render_workflow_selector = _lazy_util("render_workflow_selector")', section_text)
                self.assertNotIn("return str(st.selectbox(label, list(workflows), key=key))", section_text)

    def test_global_filter_and_metric_changes_clear_loaded_state(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        cache_text = (APP_ROOT / "utils" / "cache.py").read_text(encoding="utf-8")
        company_filter_text = (APP_ROOT / "utils" / "company_filter.py").read_text(encoding="utf-8")
        query_text = (APP_ROOT / "utils" / "query.py").read_text(encoding="utf-8")
        state_keys_text = (APP_ROOT / "utils" / "state_keys.py").read_text(encoding="utf-8")
        self.assertIn("def _global_filter_signature", app_text)
        self.assertIn("def _metric_settings_signature", app_text)
        self.assertIn('str(st.session_state.get("global_schema", ""))', app_text)
        self.assertNotIn("load_schema_options", app_text)
        self.assertIn("_global_schema_choice_scope", app_text)
        self.assertIn("Schema contains", app_text)
        self.assertIn("def _render_topbar_filter_strip", app_text)
        self.assertIn("def _maybe_clear_scope_cache_on_filter_change", app_text)
        self.assertIn("_maybe_clear_scope_cache_on_filter_change()", app_text)
        self.assertIn("global_filters_clear_topbar", app_text)
        self.assertIn("Optional role, database, and schema narrowing.", app_text)
        self.assertIn("get_global_schema_filter_clause", company_filter_text)
        self.assertIn("schema_col", company_filter_text)
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
        self.assertIn("resolve_role_profile(_get_current_role())", app_text)
        self.assertIn("resolve_allowed_experience_views(_get_current_role())", app_text)
        self.assertIn("matched_profile  = resolve_role_profile(current_role)", app_text)
        self.assertIn("compatibility_state_for_section", app_text)
        self.assertIn("_apply_section_compatibility_state(raw_section)", app_text)

    def test_saved_state_architecture_is_removed(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        utils_init_text = (APP_ROOT / "utils" / "__init__.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        dba_tools_text = (APP_ROOT / "sections" / "dba_tools.py").read_text(encoding="utf-8")
        setup_text = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")

        self.assertFalse((APP_ROOT / "utils" / "bookmarks.py").exists())
        for text in (app_text, utils_init_text, theme_text, dba_tools_text, setup_text):
            self.assertNotIn("OVERWATCH_BOOKMARKS", text)
            self.assertNotIn("Saved Views", text)
        self.assertNotIn("_overwatch_saved_views_loaded", app_text)
        self.assertNotIn("_overwatch_saved_views_cache", app_text)
        self.assertNotIn("def _load_bookmark_helpers", app_text)
        self.assertNotIn("from utils.bookmarks", app_text)
        self.assertNotIn("restore_theme_preference", theme_text)

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
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        evidence_mode_text = (APP_ROOT / "utils" / "evidence_mode.py").read_text(encoding="utf-8")

        header_index = app_text.index("_render_app_header(active_section, active_company, credit_price, current_role)")
        topbar_index = app_text.index("active_company = _render_topbar_filter_strip(active_company)")
        sidebar_index = app_text.index("with st.sidebar:")
        self.assertLess(header_index, sidebar_index)
        self.assertLess(header_index, topbar_index)
        self.assertLess(topbar_index, sidebar_index)
        self.assertIn("def _current_active_section", app_text)
        self.assertIn("def _current_credit_price", app_text)
        self.assertIn("def _sidebar_panel_toggle", app_text)
        self.assertIn("ow-filter-strip-kicker", app_text)
        self.assertNotIn("def _render_priority_brief_empty_state", app_text)
        self.assertNotIn("Open Executive Landing for the ranked platform brief.", app_text)
        self.assertNotIn(".ow-priority-empty", theme_text)
        self.assertNotIn("load or refresh a section to populate priority evidence", app_text)
        self.assertIn('"Date range"', app_text)
        self.assertIn('"Warehouse"', app_text)
        self.assertIn('"User contains"', app_text)
        self.assertIn('if _sidebar_panel_toggle("Advanced Scope", "advanced_scope")', app_text)
        self.assertIn('if _sidebar_panel_toggle("Settings", "settings")', app_text)
        self.assertEqual(app_text.count('if _sidebar_panel_toggle("Advanced Scope", "advanced_scope")'), 1)
        self.assertNotIn('if _sidebar_panel_toggle("Saved Views", "saved_views")', app_text)
        self.assertNotIn('if _sidebar_panel_toggle("Global Filters", "global_filters")', app_text)
        self.assertIn("Optional role, database, and schema narrowing.", app_text)
        self.assertNotIn("TRIAGE_MODE_OPTIONS", app_text)
        self.assertNotIn('"Evidence Mode"', app_text)
        self.assertIn("triage_view_mode", app_text)
        self.assertIn("_sync_exceptions_only_mode", app_text)
        self.assertIn("TRIAGE_MODE_TRIAGE", app_text)
        self.assertNotIn("TRIAGE_MODE_INVESTIGATE", app_text)
        self.assertNotIn("TRIAGE_MODE_ALL_EVIDENCE", app_text)
        self.assertIn("TRIAGE_MODE_LEGACY_ALIASES", evidence_mode_text)
        self.assertNotIn('"Exceptions-only mode"', app_text)
        for path in APP_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            self.assertNotIn("Exceptions-only mode", path.read_text(encoding="utf-8"), str(path))
        self.assertNotIn("st.toggle(", app_text)
        self.assertNotIn("Command Palette", app_text)
        self.assertNotIn("command_palette", app_text)
        self.assertNotIn('with st.expander("Saved Views", expanded=False)', app_text)
        self.assertNotIn('with st.expander("Global Filters", expanded=False)', app_text)
        self.assertNotIn('with st.expander("Settings", expanded=False)', app_text)
        self.assertLess(app_text.index("def _render_topbar_filter_strip"), app_text.index('if _sidebar_panel_toggle("Advanced Scope", "advanced_scope")'))
        self.assertLess(app_text.index('if _sidebar_panel_toggle("Advanced Scope", "advanced_scope")'), app_text.index('if _sidebar_panel_toggle("Settings", "settings")'))

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
        self.assertIn(
            '[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarContent"] > *:not([data-testid="stSidebarHeader"])',
            theme_text,
        )
        self.assertIn('[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarUserContent"]', theme_text)
        self.assertIn("pointer-events: none !important;", theme_text)
        self.assertIn("display: none !important;", theme_text)

    def test_current_sections_have_operating_guides(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        guidance_text = (APP_ROOT / "utils" / "section_guidance.py").read_text(encoding="utf-8")

        self.assertNotIn("render_section_operating_guide(active_section)", app_text)
        self.assertNotIn("clear_deferred_section_notes(active_section)", app_text)
        self.assertNotIn("render_deferred_section_notes(active_section)", app_text)
        self.assertNotIn("render_section_reference(active_section)", app_text)
        self.assertIn("Compatibility no-op", guidance_text)
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
        self.assertIn("Do not change access from summary rows", SECTION_OPERATING_GUIDE["Security Monitoring"]["guardrail"])
        self.assertIn(".ow-section-guide", theme_text)
        self.assertIn(".ow-workload-lane-card", theme_text)
        self.assertIn(".ow-workload-lane-state", theme_text)

    def test_current_sections_have_evidence_contracts(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        guidance_text = (APP_ROOT / "utils" / "section_guidance.py").read_text(encoding="utf-8")
        shell_helpers_text = (APP_ROOT / "sections" / "shell_helpers.py").read_text(encoding="utf-8")
        workflow_text = (APP_ROOT / "utils" / "workflows.py").read_text(encoding="utf-8")
        workload_text = (APP_ROOT / "sections" / "workload_operations.py").read_text(encoding="utf-8")

        self.assertNotIn("render_section_confidence_meter(active_section", app_text)
        self.assertNotIn("render_section_operating_guide(active_section)", app_text)
        self.assertNotIn("render_deferred_section_notes(active_section)", app_text)
        self.assertNotIn("render_section_reference(active_section)", app_text)
        self.assertNotIn("render_section_evidence_contract(active_section)", app_text)
        self.assertNotIn('st.expander("Notes / Evidence", expanded=False)', guidance_text)
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
        self.assertTrue(
            any("Allocated/Estimated" in row["confidence"] for row in SECTION_EVIDENCE_CONTRACT["Cost & Contract"])
        )
        self.assertIn("Email-first", SECTION_EVIDENCE_CONTRACT["Alert Center"][1]["confidence"])
        self.assertIn("Do not split exact spend by database", SECTION_EVIDENCE_CONTRACT["Cost & Contract"][0]["invalid_use"])
        security_invalid_uses = " ".join(
            row["invalid_use"] for row in SECTION_EVIDENCE_CONTRACT["Security Monitoring"]
        )
        self.assertIn("Do not revoke access", security_invalid_uses)
        self.assertIn("Do not treat delayed account metadata as real-time enforcement", security_invalid_uses)
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
        self.assertNotIn("_SNAPSHOT_GRID_STYLE", shell_helpers_text)
        self.assertNotIn("_LANE_CARD_STYLE", shell_helpers_text)
        self.assertNotIn("_STATUS_STRIP_STYLE", shell_helpers_text)
        self.assertNotIn("unsafe_allow_html=True", shell_helpers_text)
        self.assertNotIn("html.escape", shell_helpers_text)
        self.assertIn("def _badge", shell_helpers_text)
        self.assertIn("st.container(border=True)", shell_helpers_text)
        self.assertIn("st.columns", shell_helpers_text)
        self.assertIn("st.caption(detail)", shell_helpers_text)
        self.assertIn("_GUIDE_LABEL_STYLE", guidance_text)
        self.assertIn("_GUIDE_DETAIL_STYLE", guidance_text)
        self.assertIn("_EVIDENCE_LABEL_STYLE", guidance_text)
        self.assertIn("ow-section-guide-label", guidance_text)
        self.assertIn("ow-evidence-contract-source", guidance_text)
        self.assertNotIn("_LANE_LABEL_STYLE", workload_text)
        self.assertNotIn("_LANE_DETAIL_STYLE", workload_text)
        self.assertNotIn("ow-workload-lane-label", workload_text)
        self.assertNotIn("unsafe_allow_html=True", workload_text)
        self.assertIn("st.caption(str(lane.get(\"label\")", workload_text)
        self.assertIn('help=str(lane.get("detail")', workload_text)
        self.assertNotIn("ow-workload-lane-detail", workload_text)
        self.assertNotIn("_TABLE_HEADING_STYLE", workflow_text)
        self.assertNotIn("_TABLE_COUNT_STYLE", workflow_text)
        self.assertIn("st.caption(f\"Showing {visible_rows:,} of {len(df):,}\")", workflow_text)
        self.assertIn("overflow-wrap: anywhere", theme_text)

    def test_priority_tables_defer_full_raw_detail_rendering(self):
        workflows_text = (APP_ROOT / "utils" / "workflows.py").read_text(encoding="utf-8")
        display_text = (APP_ROOT / "utils" / "display.py").read_text(encoding="utf-8")
        stored_proc_text = (APP_ROOT / "sections" / "stored_proc_tracker.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        self.assertIn("Full detail is loaded only when requested", workflows_text)
        self.assertIn('st.button("Show full detail"', workflows_text)
        self.assertIn('CONTEXT_PRIORITY_COLUMNS = ("ENVIRONMENT", "DATABASE_NAME", "SCHEMA_NAME")', workflows_text)
        self.assertIn("def prioritize_context_columns", workflows_text)
        self.assertIn("prioritize_context_columns(view)", workflows_text)
        self.assertIn("from .workflows import add_cost_companion_columns, prioritize_context_columns", display_text)
        self.assertIn("from .workflows import apply_operator_status_labels", display_text)
        self.assertIn("grid_df = add_cost_companion_columns", display_text)
        self.assertIn("grid_df = apply_operator_status_labels(grid_df)", display_text)
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
        self.assertIn('st.button("Back to chart"', display_text)
        self.assertIn("requested_key", display_text)
        self.assertIn("if requested != selected:", display_text)
        self.assertIn("chart_df = add_cost_companion_columns(rank_chart_frame", display_text)
        self.assertIn('title="Cost USD"', display_text)
        self.assertIn("def render_chart_with_data_toggle(", display_text)
        self.assertIn("render_mode_selector(", display_text)
        self.assertIn('requested_key = f"{key}_chart_data_requested"', display_text)
        self.assertIn("st.session_state[requested_key] = \"Chart\"", display_text)
        self.assertIn('st.button("Back to chart"', display_text)
        self.assertIn("def add_cost_companion_columns", workflows_text)
        self.assertIn("view = add_cost_companion_columns(view)", workflows_text)
        self.assertIn(
            "display_view = clean_operator_display_text(apply_operator_status_labels(view))",
            workflows_text,
        )

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
        shell_helpers_text = (APP_ROOT / "sections" / "shell_helpers.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        workflows_text = (APP_ROOT / "utils" / "workflows.py").read_text(encoding="utf-8")

        self.assertIn("WORKFLOWS_VERSION", workflows_text)
        self.assertIn("WORKFLOWS_VERSION", app_text)
        self.assertIn("reload_loaded_sections()", app_text)
        self.assertIn("def reload_loaded_sections()", sections_text)
        self.assertIn("help=details.get(workflow) or None", workflows_text)
        self.assertIn("help=details.get(mode) or None", workflows_text)
        self.assertNotIn("st.caption(details[workflow])", workflows_text)
        self.assertNotIn("st.caption(details[mode])", workflows_text)
        self.assertIn("help=caption or None", shell_helpers_text)
        self.assertNotIn("st.caption(caption)", shell_helpers_text)
        self.assertNotIn("ow-workload-lane-detail", theme_text)
        self.assertIn("from .section_guidance import defer_section_note", workflows_text)
        self.assertIn("defer_source_note", workflows_text)
        self.assertIn("defer_section_note(summary)", workflows_text)
        self.assertIn("defer_source_note(*parts)", workflows_text)
        self.assertIn("def render_load_status", workflows_text)
        self.assertIn("st.status(label", workflows_text)
        self.assertIn("status.update(label=complete", workflows_text)
        self.assertIn("def render_mode_selector", workflows_text)
        self.assertIn('getattr(st, "segmented_control", None)', workflows_text)
        self.assertIn("st.selectbox(", workflows_text)
        self.assertNotIn("help=_section_subtitle(section_name)", app_text)
        self.assertNotIn('<div class="ow-section-subtitle">{safe_subtitle}</div>', app_text)
        self.assertNotIn('st.caption("NAVIGATE")', app_text)

        section_texts = {
            path.name: path.read_text(encoding="utf-8")
            for path in (APP_ROOT / "sections").glob("*.py")
        }
        forbidden_visible_launcher_copy = (
            'st.caption(row["DBA_MOVE"])',
            'st.caption(row["WHEN"])',
            "st.caption(detail[:220])",
            'st.write(str(item.get("NEXT_ACTION", "")))',
            "ow-workload-lane-detail",
        )
        offenders = [
            f"{name}: {pattern}"
            for name, text in section_texts.items()
            for pattern in forbidden_visible_launcher_copy
            if pattern in text
        ]
        self.assertEqual(offenders, [])
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
            ("account_health.py", 'st.header("Account Health - Command Center")'),
        ]
        for filename, marker in duplicate_headers:
            with self.subTest(filename=filename):
                section_text = (APP_ROOT / "sections" / filename).read_text(encoding="utf-8")
                self.assertNotIn(marker, section_text)

    def test_utils_re_exports_are_lazy(self):
        utils_text = (APP_ROOT / "utils" / "__init__.py").read_text(encoding="utf-8")

        self.assertIn("def __getattr__", utils_text)
        self.assertIn("_EXPORT_GROUPS", utils_text)
        self.assertIn("_EXPORT_MODULES", utils_text)
        self.assertNotIn("from .alerts import", utils_text)
        self.assertNotIn("from .mart import", utils_text)
        self.assertIn('"environment_label_for_database"', utils_text)
        self.assertIn('"get_environment_filter_or_no_database_clause"', utils_text)
        self.assertNotIn('"build_platform_futures_adoption_gate"', utils_text)
        self.assertIn('"render_load_status"', utils_text)
        self.assertNotIn('"build_agentic_ai_surface_scorecard"', utils_text)
        self.assertNotIn('"AGENTIC_AI_CONTROL_AREAS"', utils_text)
        self.assertNotIn('"load_adaptive_compute_readiness"', utils_text)
        self.assertNotIn('"load_ai_security_guardrails"', utils_text)
        self.assertIn('"render_workflow_module"', utils_text)
        self.assertIn('"migrate_legacy_workflow_state"', utils_text)
        self.assertIn('"render_ranked_bar_chart"', utils_text)
        self.assertIn('"render_chart_with_data_toggle"', utils_text)
        self.assertIn('"rank_chart_frame"', utils_text)
        self.assertNotIn('"build_platform_futures_evidence_ddl"', utils_text)
        self.assertIn('"build_mart_cost_run_rate_sql"', utils_text)
        self.assertIn('"build_mart_cost_explorer_sql"', utils_text)
        self.assertIn('"load_database_options"', utils_text)
        self.assertIn('"load_schema_options"', utils_text)
        self.assertIn('"load_warehouse_options"', utils_text)
        self.assertIn('"add_cost_companion_columns"', utils_text)

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
