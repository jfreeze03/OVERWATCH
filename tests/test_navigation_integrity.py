from pathlib import Path
import ast
import contextlib
import importlib.util
import json
import re
import subprocess
import sys
import unittest
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


def _section_source(path: Path) -> str:
    """Read a section's source, transparently handling subpackages.

    Some sections (e.g. ``dba_control_room``) are subpackages rather than a
    single module file; in that case concatenate every module so text-based
    assertions continue to work after the refactor.
    """
    if path.suffix == ".py" and not path.exists():
        pkg = path.with_suffix("")
        if pkg.is_dir():
            return "\n".join(
                p.read_text(encoding="utf-8") for p in sorted(pkg.rglob("*.py"))
            )
    return path.read_text(encoding="utf-8")

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
    ADMIN_ACCESS_ROLES,
    SECTION_ALIASES,
    SECTION_BY_TITLE,
    SECTION_DEFINITIONS,
    SECTION_MODULES,
    SECTION_REDIRECTS,
    RETIRED_SECTION_REDIRECTS,
    TREXIS_DATABASES,
    TREXIS_DEV_DATABASES,
    TREXIS_PROD_DATABASES,
    TREXIS_WAREHOUSES,
    compatibility_state_for_section,
    normalize_section_name,
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
from workflow_contracts import (  # noqa: E402
    ABANDONED_PRIMARY_SECTION_TITLES,
    LEGACY_ROUTE_CONTRACT,
    PRIMARY_SECTION_TITLES,
    SECTION_WORKFLOW_CONTRACT,
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
            ["MONITORING CORE", "FINANCIAL CONTROL", "OPERATIONS", "SECURITY"],
        )
        self.assertEqual(set(ALL_SECTIONS), set(SECTION_MODULES))
        self.assertEqual(
            SECTION_MODULES,
            {section.label: section.module for section in SECTION_DEFINITIONS},
        )
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        access_text = (APP_ROOT / "access_control.py").read_text(encoding="utf-8")
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")
        self.assertEqual(ADMIN_ACCESS_ROLES, ("SNOW_ACCOUNTADMINS", "SNOW_SYSADMINS"))
        self.assertNotIn("ROLE_SECTIONS = {", config_text)
        self.assertIn("from shell import render_app", app_text)
        self.assertLessEqual(len(app_text.splitlines()), 30)
        self.assertIn("ADMIN_ACCESS_ROLES", access_text)
        self.assertIn("def current_role_allows_app_access", access_text)
        self.assertIn("def admin_access_is_allowed", access_text)
        self.assertIn("_SNOWFLAKE_AVAILABLE_PROCESS_CACHE", access_text)
        self.assertIn("_SNOWFLAKE_AVAILABLE_LOCK = threading.Lock()", access_text)
        self.assertIn("if not force and _SNOWFLAKE_AVAILABLE_PROCESS_CACHE is not None", access_text)
        self.assertIn("_SNOWFLAKE_AVAILABLE_LOCK.acquire(blocking=False)", access_text)
        self.assertIn('set_state(CURRENT_ROLE_SOURCE, "secrets")', access_text)
        self.assertIn('get_state(CURRENT_ROLE_SOURCE) == "session"', access_text)
        self.assertIn("SNOW_ACCOUNTADMINS or SNOW_SYSADMINS", layout_text)
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

    def test_session_cache_decorator_supports_snowflake_streamlit_runtime(self):
        session_text = (APP_ROOT / "utils" / "session.py").read_text(encoding="utf-8")
        self.assertIn("@st.cache_resource(show_spinner=False)", session_text)
        self.assertNotIn("on_release=", session_text)

    def test_fast_shells_use_data_first_brief_pattern(self):
        shell_modules = {
            section: module_path
            for section, module_path in SECTION_MODULES.items()
            if module_path.endswith("_shell")
        }
        self.assertEqual(shell_modules, {"Executive Landing": "sections.executive_landing_shell"})
        self.assertEqual(SECTION_MODULES["Executive Landing"], "sections.executive_landing_shell")
        self.assertEqual(SECTION_MODULES["DBA Control Room"], "sections.dba_control_room")
        self.assertEqual(SECTION_MODULES["Alert Center"], "sections.alert_center")
        self.assertEqual(SECTION_MODULES["Cost & Contract"], "sections.cost_contract")
        self.assertEqual(SECTION_MODULES["Workload Operations"], "sections.workload_operations")
        self.assertEqual(SECTION_MODULES["Security Monitoring"], "sections.security_posture")
        self.assertFalse((APP_ROOT / "sections" / "dba_control_room_shell.py").exists())
        self.assertFalse((APP_ROOT / "sections" / "alert_center_shell.py").exists())
        self.assertFalse((APP_ROOT / "sections" / "cost_contract_shell.py").exists())
        self.assertFalse((APP_ROOT / "sections" / "workload_operations_shell.py").exists())
        self.assertFalse((APP_ROOT / "sections" / "security_monitoring.py").exists())
        self.assertTrue((APP_ROOT / "sections" / "executive_landing_shell.py").exists())

        helper_text = (APP_ROOT / "sections" / "shell_helpers.py").read_text(encoding="utf-8")
        self.assertIn("def full_workspace_requested", helper_text)
        self.assertIn("def render_signal_lane_board", helper_text)
        self.assertIn("if state.get(brief_key):\n        return False", helper_text)
        self.assertIn("state[workspace_key] = True", helper_text)
        self.assertIn("state[brief_key] = False", helper_text)

        executive_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")
        executive_shell = (APP_ROOT / "sections" / "executive_landing_shell.py").read_text(encoding="utf-8")
        executive_overview = (APP_ROOT / "sections" / "executive_landing_overview_view.py").read_text(encoding="utf-8")
        executive_security = (APP_ROOT / "sections" / "executive_landing_security_view.py").read_text(encoding="utf-8")
        self.assertIn("Snowflake Observability Wall", executive_overview)
        self.assertNotIn("Executive Summary Signals", executive_text)
        self.assertIn("Refresh Summary", executive_shell)

    def test_app_shell_first_paint_stays_lazy_and_query_builder_clean(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        shell_text = (APP_ROOT / "shell.py").read_text(encoding="utf-8")
        navigation_text = (APP_ROOT / "navigation.py").read_text(encoding="utf-8")
        dispatch_text = (APP_ROOT / "section_dispatch.py").read_text(encoding="utf-8")
        route_registry_text = (APP_ROOT / "route_registry.py").read_text(encoding="utf-8")
        executive_shell_text = (APP_ROOT / "sections" / "executive_landing_shell.py").read_text(encoding="utf-8")
        first_paint_text = "\n".join([
            app_text,
            shell_text,
            navigation_text,
            dispatch_text,
            route_registry_text,
            executive_shell_text,
        ])

        self.assertNotRegex(first_paint_text, r"\brun_query(?:_or_raise)?\s*\(")
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", first_paint_text)
        self.assertNotIn("utils.mart", first_paint_text)
        self.assertNotIn("from sections.", shell_text)
        self.assertNotIn("from sections import", shell_text)
        self.assertIn("importlib.import_module(module_path)", dispatch_text)
        self.assertNotIn("from sections.executive_landing_overview_view import", executive_shell_text)
        self.assertNotIn("from sections.executive_landing_admin_view import", executive_shell_text)
        self.assertIn("importlib.import_module(module_path)", executive_shell_text)

    def test_importing_shell_does_not_load_executive_workflow_modules(self):
        code = (
            "import json, pathlib, sys\n"
            f"sys.path.insert(0, {str(APP_ROOT)!r})\n"
            "import shell\n"
            "broad = sorted(name for name in sys.modules if name.startswith('sections.executive_landing_') "
            "and name.rsplit('.', 1)[-1] not in {'executive_landing_common', 'executive_landing_contracts', "
            "'executive_landing_data', 'executive_landing_models', 'executive_landing_shell'})\n"
            "print(json.dumps(broad))\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), [])

    def test_executive_landing_route_module_is_lightweight(self):
        code = (
            "import importlib, json, pathlib, sys\n"
            f"sys.path.insert(0, {str(APP_ROOT)!r})\n"
            "importlib.import_module('sections.executive_landing_shell')\n"
            "broad = sorted(name for name in sys.modules if name.startswith('sections.executive_landing_') "
            "and name.rsplit('.', 1)[-1] not in {'executive_landing_common', 'executive_landing_contracts', "
            "'executive_landing_data', 'executive_landing_models', 'executive_landing_shell'})\n"
            "print(json.dumps(broad))\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), [])

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

    def test_sidebar_navigation_requests_section_detail_state(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        top_navigation_text = (APP_ROOT / "navigation.py").read_text(encoding="utf-8")
        navigation_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")

        self.assertNotIn("SECTION_WORKSPACE_STATE_KEYS = {", app_text)
        self.assertIn("from shell import render_app", app_text)
        self.assertIn("def queue_section_navigation", top_navigation_text)
        self.assertIn("request_section_workspace(target)", top_navigation_text)
        self.assertIn("request_executive_landing_hydration()", top_navigation_text)
        self.assertIn('target == "Executive Landing"', top_navigation_text)
        self.assertIn('if target == "Executive Landing":', top_navigation_text)
        self.assertIn('pop_state(PENDING_AUTOLOAD_SECTION, None)', top_navigation_text)
        self.assertIn('pop_state(PENDING_AUTOLOAD_STARTED_AT, None)', top_navigation_text)
        self.assertNotIn('st.session_state["_overwatch_pending_autoload_section"] = target', top_navigation_text)
        self.assertLess(
            top_navigation_text.index("request_section_workspace(target)"),
            top_navigation_text.index("set_state(NAV_SECTION, target)"),
        )
        self.assertIn("def request_section_workspace", navigation_text)
        self.assertIn("request_section_workspace(target)", navigation_text)
        self.assertIn("set_state(EXECUTIVE_LANDING_WORKSPACE_REQUESTED, True)", navigation_text)
        self.assertIn("set_state(EXECUTIVE_LANDING_BRIEF_MODE, False)", navigation_text)
        self.assertIn('set_state(EXECUTIVE_LANDING_WORKFLOW, "Executive Overview")', navigation_text)
        self.assertIn('set_state(ALERT_CENTER_ACTIVE_VIEW, "Active Alerts")', navigation_text)
        self.assertIn('set_state(COST_CONTRACT_WORKFLOW, "Cost Overview")', navigation_text)
        self.assertIn('set_state(WORKLOAD_OPERATIONS_WORKFLOW, "Workload Overview")', navigation_text)
        self.assertIn('set_state(SECURITY_POSTURE_WORKFLOW, "Security Overview")', navigation_text)

    def test_direct_section_navigation_uses_compatibility_helper(self):
        navigation_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")
        self.assertIn("def apply_navigation_state", navigation_text)
        self.assertNotIn("SECTION_WORKSPACE_STATE_KEYS = {", navigation_text)
        self.assertIn("EXECUTIVE_LANDING_BOARD_STATE_KEYS = (", navigation_text)
        self.assertIn("def request_executive_landing_hydration", navigation_text)
        self.assertIn("def request_section_workspace", navigation_text)
        self.assertIn("normalize_section_name(raw_section)", navigation_text)
        self.assertIn("compatibility_state_for_section(raw_section)", navigation_text)
        self.assertIn("request_section_workspace(target)", navigation_text)
        self.assertIn("request_executive_landing_hydration()", navigation_text)
        self.assertIn('set_state(EXECUTIVE_LANDING_WORKFLOW, "Executive Overview")', navigation_text)
        self.assertIn('set_state(DBA_CONTROL_ROOM_ACTIVE_VIEW, "Morning Cockpit")', navigation_text)
        self.assertIn('set_state(ALERT_CENTER_ACTIVE_VIEW, "Active Alerts")', navigation_text)
        self.assertIn('set_state(COST_CONTRACT_WORKFLOW, "Cost Overview")', navigation_text)
        self.assertIn('set_state(WORKLOAD_OPERATIONS_WORKFLOW, "Workload Overview")', navigation_text)
        self.assertIn('set_state("workload_operations_pipeline_focus", "Failed Procedures")', navigation_text)
        self.assertIn('set_state(SECURITY_POSTURE_VIEW, "Security Overview")', navigation_text)
        self.assertIn('set_state(SECURITY_POSTURE_WORKFLOW, "Security Overview")', navigation_text)
        self.assertIn('target != current or target == "Executive Landing"', navigation_text)
        self.assertIn("set_state(PENDING_SECTION, target)", navigation_text)
        self.assertIn("set_state(NAV_SECTION, target)", navigation_text)

        direct_nav_modules = {
            "account_health_overview_view.py": ("apply_navigation_state(section)", "apply_navigation_state(tgt)"),
            "dba_control_room.py": ("apply_navigation_state(raw_target)",),
            "dba_tools.py": ('apply_navigation_state("Alert Center")',),
            "executive_landing_common.py": ("apply_navigation_state(section)",),
        }
        for file_name, expected_calls in direct_nav_modules.items():
            module_text = _section_source(APP_ROOT / "sections" / file_name)
            with self.subTest(module=file_name):
                self.assertIn("from sections.navigation import apply_navigation_state", module_text)
                for expected_call in expected_calls:
                    self.assertIn(expected_call, module_text)
                self.assertNotIn('st.session_state["nav_section"] =', module_text)

    def test_navigation_fallback_and_retired_redirects_are_safe(self):
        from navigation import current_active_section
        from runtime_state import (
            DBA_CONTROL_ROOM_ACTIVE_VIEW,
            EXECUTIVE_LANDING_WORKFLOW,
            NAV_SECTION,
            PENDING_SECTION,
            SECURITY_POSTURE_VIEW,
            SECURITY_POSTURE_WORKFLOW,
        )
        from sections.navigation import apply_navigation_state

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            self.assertEqual(current_active_section([]), "Executive Landing")

            st.session_state[NAV_SECTION] = "Missing Section"
            self.assertEqual(current_active_section(["Alert Center", "Cost & Contract"]), "Alert Center")
            self.assertEqual(st.session_state[NAV_SECTION], "Alert Center")

            target = apply_navigation_state("Executive Briefing")
            self.assertEqual(target, "Executive Landing")
            self.assertEqual(st.session_state[EXECUTIVE_LANDING_WORKFLOW], "Executive Overview")

            target = apply_navigation_state("Adoption Analytics")
            self.assertEqual(target, "Executive Landing")
            self.assertEqual(st.session_state[EXECUTIVE_LANDING_WORKFLOW], "Executive Admin / Advanced")

            target = apply_navigation_state("Account Health")
            self.assertEqual(target, "DBA Control Room")
            self.assertEqual(st.session_state[NAV_SECTION], "DBA Control Room")
            self.assertEqual(st.session_state[PENDING_SECTION], "DBA Control Room")
            self.assertEqual(st.session_state[DBA_CONTROL_ROOM_ACTIVE_VIEW], "Morning Cockpit")

            target = apply_navigation_state("Security & Access")
            self.assertEqual(target, "Security Monitoring")
            self.assertEqual(st.session_state[SECURITY_POSTURE_VIEW], "Risky Grants")
            self.assertEqual(st.session_state[SECURITY_POSTURE_WORKFLOW], "Risky Grants")

            target = apply_navigation_state("Data Sharing")
            self.assertEqual(target, "Security Monitoring")
            self.assertEqual(st.session_state[SECURITY_POSTURE_VIEW], "Data Sharing Exposure")

            target = apply_navigation_state("Access posture")
            self.assertEqual(target, "Security Monitoring")
            self.assertEqual(st.session_state[SECURITY_POSTURE_VIEW], "Security Overview")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_legacy_route_matrix_lands_on_current_workflows(self):
        from runtime_state import NAV_SECTION
        from sections.navigation import apply_navigation_state

        previous = dict(st.session_state)
        try:
            for route, expected_section, expected_state in LEGACY_ROUTE_CONTRACT:
                with self.subTest(route=route):
                    st.session_state.clear()
                    target = apply_navigation_state(route)
                    self.assertEqual(target, expected_section)
                    self.assertEqual(st.session_state[NAV_SECTION], expected_section)
                    for key, value in expected_state.items():
                        self.assertEqual(st.session_state.get(key), value)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_primary_workflow_text_does_not_use_abandoned_four_section_nav(self):
        primary_text_files = [
            APP_ROOT / "layout.py",
            APP_ROOT / "sections" / "executive_landing.py",
            APP_ROOT / "sections" / "dba_control_room" / "render.py",
            APP_ROOT / "sections" / "alert_center.py",
            APP_ROOT / "sections" / "cost_contract.py",
            APP_ROOT / "sections" / "workload_operations.py",
            APP_ROOT / "sections" / "security_posture.py",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in primary_text_files)
        self.assertNotIn('"Incidents"', combined)
        self.assertNotIn('"Optimization"', combined)
        self.assertNotIn("Command Center / Incidents / Optimization / Settings", combined)
        self.assertNotRegex(combined, r"see chart [A-D]|chart [A-D]|Chart [A-D]")

    def test_executive_landing_uses_direct_observability_module(self):
        self.assertEqual(SECTION_MODULES["Executive Landing"], "sections.executive_landing_shell")
        self.assertTrue((APP_ROOT / "sections" / "executive_landing_shell.py").exists())
        full_workspace_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")
        route_shell_text = (APP_ROOT / "sections" / "executive_landing_shell.py").read_text(encoding="utf-8")
        observability_text = (APP_ROOT / "sections" / "executive_landing_data.py").read_text(encoding="utf-8")
        overview_text = (APP_ROOT / "sections" / "executive_landing_overview_view.py").read_text(encoding="utf-8")

        self.assertIn("def _load_executive_observability", observability_text)
        self.assertIn("_executive_landing_observability_autoload_scope", route_shell_text)
        self.assertIn("def _executive_observability_autoload_allowed", observability_text)
        self.assertIn("Executive first paint must not query Snowflake automatically.", observability_text)
        self.assertIn("def _executive_observability_connection_unavailable", observability_text)
        self.assertIn('st.session_state.get("_overwatch_connection_available") is not True', observability_text)
        self.assertIn("or snowflake_connection_known_unavailable()", observability_text)
        self.assertIn("Use Refresh Summary to read the compact observability mart.", route_shell_text)
        self.assertIn("_store_connection_unavailable_observability(company, environment, int(days))", route_shell_text)
        self.assertIn("refresh_session = get_session_for_action", route_shell_text)
        first_load_block = route_shell_text.split("if needs_first_load:", 1)[1].split("if refresh_board:", 1)[0]
        self.assertNotIn("_load_executive_observability(", first_load_block)
        self.assertNotIn("st.session_state.get(autoload_scope_key) != expected_scope", full_workspace_text + observability_text)
        self.assertIn("Snowflake Observability Wall", overview_text)
        self.assertNotIn("Executive Summary Signals", full_workspace_text)
        self.assertIn("Refresh Summary", route_shell_text)
        self.assertNotIn("Refresh Board", full_workspace_text)
        self.assertNotIn("Executive Command Wall", full_workspace_text)
        self.assertNotIn("Setup Readiness", full_workspace_text)
        self.assertNotIn("render_native_readiness_board", full_workspace_text)
        self.assertNotIn('st.markdown("**Platform Operating Score**")', full_workspace_text)
        self.assertNotIn("def _render_operating_snapshot", full_workspace_text)
        self.assertNotIn("def _render_workflow_launchpad", full_workspace_text)
        self.assertNotIn("Executive Briefing Workflows", full_workspace_text)
        self.assertNotIn("Open Executive Snapshot", full_workspace_text)
        self.assertNotIn("Open Snapshot", full_workspace_text)
        self.assertNotIn("Open PowerPoint", full_workspace_text)
        self.assertNotIn("Open Alerts", full_workspace_text)
        self.assertNotIn("Open FinOps", full_workspace_text)
        self.assertNotIn("Open DBA Queue", full_workspace_text)
        self.assertNotIn("Open Setup", full_workspace_text)
        self.assertNotIn("_SECTION_WORKSPACE_KEYS", full_workspace_text)
        self.assertNotIn("def _open_target_workspace", full_workspace_text)
        self.assertNotIn("def _build_executive_snapshot_pptx", full_workspace_text)

    def test_section_landing_default_messages_are_removed(self):
        offenders = []
        for path in APP_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "Landing default" in text:
                offenders.append(str(path.relative_to(APP_ROOT)))
        self.assertEqual(offenders, [])

    def test_dba_control_room_uses_morning_cockpit_workflows(self):
        self.assertEqual(SECTION_MODULES["DBA Control Room"], "sections.dba_control_room")
        self.assertFalse((APP_ROOT / "sections" / "dba_control_room_shell.py").exists())
        full_workspace_text = _section_source(APP_ROOT / "sections" / "dba_control_room.py")
        nav_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")
        self.assertIn('"Morning Cockpit"', full_workspace_text)
        self.assertIn('set_state(DBA_CONTROL_ROOM_ACTIVE_VIEW, "Morning Cockpit")', nav_text)
        self.assertIn("with_loaded_at(", full_workspace_text)
        self.assertIn("source=getattr(snapshot_result, \"source\", \"Fast summary snapshot\")", full_workspace_text)
        auto_snapshot_block = full_workspace_text.split(
            'if snapshot_scope_ok and auto_load_fast_snapshot and snapshot_result is None:',
            1,
        )[1].split("if snapshot_scope_ok:", 1)[0]
        self.assertNotIn("load_latest_control_room_mart", auto_snapshot_block)
        self.assertIn("DBA Control Room opened with a lightweight Morning Cockpit shell.", auto_snapshot_block)
        self.assertIn(
            "Fast snapshot checks are explicit so navigation stays responsive under concurrent DBA traffic.",
            full_workspace_text,
        )
        self.assertNotIn("Fast snapshot loads automatically on section navigation", full_workspace_text)
        self.assertIn("DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS = 24", full_workspace_text)
        self.assertIn("DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS", full_workspace_text)
        for workflow in (
            "Morning Cockpit",
            "Failure Triage",
            "Cost Watch",
            "Performance Watch",
            "Change Watch",
            "Action Queue",
            "Control Room Admin / Advanced",
        ):
            with self.subTest(workflow=workflow):
                self.assertIn(f'"{workflow}"', full_workspace_text)
        self.assertIn('MORNING_COCKPIT_WORKFLOW: "Morning"', full_workspace_text)
        self.assertIn('FAILURE_TRIAGE_WORKFLOW: "Failures"', full_workspace_text)
        self.assertIn('CONTROL_ROOM_ADMIN_WORKFLOW: "Advanced"', full_workspace_text)
        self.assertIn('elif active_view == ACTION_QUEUE_WORKFLOW:', full_workspace_text)
        self.assertIn('load_label = "Load Action Queue"', full_workspace_text)
        self.assertIn('ops_detail_options = ("Queue", "Daily Brief", "Priority"', full_workspace_text)
        self.assertIn('"Incident Board"', full_workspace_text)
        self.assertIn('st.session_state["dba_operations_board_detail"] = "Queue"', full_workspace_text)
        self.assertIn('key="dba_operations_board_detail"', full_workspace_text)
        self.assertIn('"Service Posture": CONTROL_ROOM_ADMIN_WORKFLOW', full_workspace_text)
        self.assertIn('"Admin Tools": CONTROL_ROOM_ADMIN_WORKFLOW', full_workspace_text)
        self.assertIn('from sections import service_health', full_workspace_text)
        self.assertIn("service_health.render()", full_workspace_text)
        self.assertIn('from sections import dba_tools', full_workspace_text)
        self.assertIn("dba_tools.render()", full_workspace_text)
        self.assertIn('"Warehouse Settings"', full_workspace_text)
        self.assertIn('"Cortex AI Limits"', full_workspace_text)
        self.assertIn('st.session_state.get("dba_control_room_active_view") == CONTROL_ROOM_ADMIN_WORKFLOW', full_workspace_text)
        service_posture_block = full_workspace_text.split('st.session_state.get("dba_control_room_active_view") == CONTROL_ROOM_ADMIN_WORKFLOW', 1)[1].split(
            'if not data:',
            1,
        )[0]
        self.assertIn("_render_control_room_admin_advanced(company, environment)", service_posture_block)
        self.assertIn("guarded live checks are reserved for explicit detail loads", full_workspace_text)
        self.assertNotIn("Allow live ACCOUNT_USAGE fallback queries", full_workspace_text)

    def test_alert_center_uses_fast_shell_module(self):
        self.assertEqual(SECTION_MODULES["Alert Center"], "sections.alert_center")
        self.assertFalse((APP_ROOT / "sections" / "alert_center_shell.py").exists())
        full_workspace_text = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        active_view_text = (APP_ROOT / "sections" / "alert_center_active_view.py").read_text(encoding="utf-8")
        contract_text = (APP_ROOT / "sections" / "alert_center_contracts.py").read_text(encoding="utf-8")
        nav_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")
        self.assertIn("ALERT_CENTER_DEFAULT_VIEW", full_workspace_text)
        self.assertIn('ALERT_CENTER_DEFAULT_VIEW = "Active Alerts"', contract_text)
        self.assertIn('set_state(ALERT_CENTER_ACTIVE_VIEW, "Active Alerts")', nav_text)
        self.assertNotIn("Alert Signal Summary", full_workspace_text)
        self.assertNotIn("Alert Command Board", full_workspace_text)
        self.assertIn("ALERT_CENTER_PANES", full_workspace_text)
        self.assertIn('"Alert History"', full_workspace_text)
        self.assertIn('"Alert Settings / Admin"', full_workspace_text)
        self.assertIn('"View Details"', active_view_text)

    def test_security_monitoring_keeps_security_surface_narrow(self):
        self.assertEqual(SECTION_MODULES["Security Monitoring"], "sections.security_posture")
        self.assertFalse((APP_ROOT / "sections" / "security_monitoring.py").exists())
        security_text = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
        nav_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")
        self.assertIn("SECURITY_POSTURE_VIEWS", security_text)
        self.assertNotIn("Security Signal Summary", security_text)
        self.assertNotIn("Security Monitoring Command Board", security_text)
        self.assertIn('set_state(SECURITY_POSTURE_VIEW, "Security Overview")', nav_text)

    def test_workload_operations_uses_fast_shell_module(self):
        self.assertEqual(SECTION_MODULES["Workload Operations"], "sections.workload_operations")
        self.assertFalse((APP_ROOT / "sections" / "workload_operations_shell.py").exists())
        full_workspace_text = (APP_ROOT / "sections" / "workload_operations.py").read_text(encoding="utf-8")
        nav_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")
        self.assertIn('WORKLOAD_OVERVIEW_WORKFLOW = "Workload Overview"', full_workspace_text)
        self.assertIn('QUERY_INVESTIGATION_WORKFLOW = "Query Investigation"', full_workspace_text)
        self.assertIn('PIPELINE_TASK_HEALTH_WORKFLOW = "Pipeline & Task Health"', full_workspace_text)
        self.assertIn('CONTENTION_PERFORMANCE_WORKFLOW = "Performance & Contention"', full_workspace_text)
        self.assertIn('CHANGE_DRIFT_WORKFLOW = "Change Analysis"', full_workspace_text)
        self.assertIn('ADVANCED_DBA_TOOLS_WORKFLOW = "Advanced DBA Tools"', full_workspace_text)
        self.assertIn('set_state(WORKLOAD_OPERATIONS_WORKFLOW, "Workload Overview")', nav_text)
        self.assertNotIn("Workload Brief", full_workspace_text)
        self.assertIn("WORKLOAD_OPERATIONS_EXPLICIT_WORKFLOW_KEY", full_workspace_text)
        self.assertNotIn("WORKLOAD_OPERATIONS_VIEWS", full_workspace_text)
        self.assertNotIn("Workload Brief", full_workspace_text)
        self.assertNotIn("workload_operations_view", full_workspace_text)
        self.assertNotIn("Refresh Workload Snapshot", full_workspace_text)
        self.assertNotIn("Download DBA runbook", full_workspace_text)

    def test_cost_contract_uses_fast_shell_module(self):
        from sections import cost_contract_contracts

        self.assertEqual(SECTION_MODULES["Cost & Contract"], "sections.cost_contract")
        self.assertFalse((APP_ROOT / "sections" / "cost_contract_shell.py").exists())
        full_workspace_text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        contract_text = (APP_ROOT / "sections" / "cost_contract_contracts.py").read_text(encoding="utf-8")
        panel_text = (APP_ROOT / "sections" / "cost_contract_panels.py").read_text(encoding="utf-8")
        intelligence_text = (APP_ROOT / "sections" / "cost_contract_intelligence.py").read_text(encoding="utf-8")
        workflow_text = (APP_ROOT / "sections" / "cost_contract_workflow.py").read_text(encoding="utf-8")
        overview_floor_text = (APP_ROOT / "sections" / "cost_contract_overview_floor.py").read_text(encoding="utf-8")
        cost_contract_surface = full_workspace_text + contract_text + panel_text + intelligence_text + workflow_text + overview_floor_text
        nav_text = (APP_ROOT / "sections" / "navigation.py").read_text(encoding="utf-8")
        self.assertIn('"Cost Overview"', cost_contract_surface)
        self.assertIn('"Cost by Warehouse"', cost_contract_surface)
        self.assertIn('set_state(COST_CONTRACT_WORKFLOW, "Cost Overview")', nav_text)
        self.assertNotIn("Cost Signal Summary", cost_contract_surface)
        self.assertNotIn("Cost Command Board", cost_contract_surface)
        cost_center_text = (APP_ROOT / "sections" / "cost_center.py").read_text(encoding="utf-8")
        self.assertNotIn("Contract Utilization", cost_center_text)
        self.assertNotIn("Annual committed credits", cost_center_text)
        self.assertNotIn("Calculate Utilization", cost_center_text)
        self.assertIn("WORKFLOWS", cost_contract_surface)
        self.assertIn("Advanced cost tools and evidence", full_workspace_text)
        self.assertIn("Open Advanced Cost Tools", full_workspace_text)
        self.assertEqual(cost_contract_contracts.ADVANCED_COST_TOOL_MODULES["Storage & Retention"], "sections.storage_monitor")
        self.assertIn('"Storage & Retention": "sections.storage_monitor"', contract_text)
        self.assertIn('"Refresh Cost"', cost_contract_surface)
        self.assertNotIn('"Refresh Overview"', full_workspace_text)
        self.assertNotIn('"Refresh Cost Details"', full_workspace_text)
        self.assertNotIn("Cost Detail Refresh", full_workspace_text)
        self.assertNotIn("Cost Drilldown Readiness", full_workspace_text)
        self.assertIn("Cost Drilldown Status", cost_contract_surface)
        self.assertNotIn("def _cost_action_brief", full_workspace_text)
        self.assertNotIn("def _cost_operating_snapshot", full_workspace_text)
        self.assertIn("_PENDING_DETAIL_WORKFLOW_KEY", full_workspace_text)
        self.assertNotIn("_AUTO_OPEN_DETAIL_WORKFLOWS", full_workspace_text)
        self.assertIn("routed_workflow = st.session_state.pop(_PENDING_DETAIL_WORKFLOW_KEY, None)", full_workspace_text)
        self.assertIn("legacy_detail_workflow = st.session_state.pop(_DETAIL_WORKFLOW_KEY, None)", full_workspace_text)
        self.assertNotIn('st.button("Open detail"', full_workspace_text)
        self.assertIn("render_workflow_module(workflow, WORKFLOW_MODULES)", workflow_text)

    def test_roles_and_aliases_resolve_to_visible_sections(self):
        primary_sections = [section for section in ALL_SECTIONS if section not in PRIMARY_NAV_HIDDEN_SECTIONS]
        self.assertEqual(primary_sections, list(PRIMARY_SECTIONS))
        self.assertEqual(ADMIN_ACCESS_ROLES, ("SNOW_ACCOUNTADMINS", "SNOW_SYSADMINS"))
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        shell_text = (APP_ROOT / "shell.py").read_text(encoding="utf-8")
        access_text = (APP_ROOT / "access_control.py").read_text(encoding="utf-8")
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")
        self.assertNotIn("ROLE_SECTIONS", config_text)
        self.assertNotIn("ROLE_PROFILE_OVERRIDES", config_text)
        self.assertNotIn("resolve_role_profile", config_text)
        self.assertNotIn("EXPERIENCE_VIEW_SECTIONS", config_text)
        self.assertNotIn("ROLE_EXPERIENCE_VIEWS", config_text)
        self.assertNotIn("resolve_allowed_experience_views", config_text)
        self.assertNotIn("default_experience_view_for_role", config_text)
        self.assertNotIn("Navigation View", app_text)
        self.assertNotIn("overwatch_experience_view", app_text)
        self.assertIn("admin_access_is_allowed(current_role, connection_available)", shell_text)
        self.assertIn("render_admin_access_required(current_role)", shell_text)
        self.assertIn("def admin_access_is_allowed", access_text)
        self.assertIn("def render_admin_access_required", layout_text)

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
                "dba_control_room_active_view": "Morning Cockpit",
                "_dba_control_room_full_workspace_requested": True,
                "_dba_control_room_brief_mode": False,
            },
        )
        self.assertEqual(SECTION_ALIASES["Command Center"], SECTION_BY_TITLE["DBA Control Room"])
        self.assertEqual(SECTION_ALIASES["Usage Overview"], SECTION_BY_TITLE["DBA Control Room"])
        self.assertEqual(SECTION_ALIASES["Service Health"], SECTION_BY_TITLE["DBA Control Room"])
        self.assertEqual(SECTION_ALIASES["Fast Watch"], SECTION_BY_TITLE["DBA Control Room"])
        self.assertEqual(SECTION_ALIASES["Morning Brief"], SECTION_BY_TITLE["DBA Control Room"])
        self.assertEqual(compatibility_state_for_section("Command Center")["dba_control_room_active_view"], "Morning Cockpit")
        self.assertEqual(compatibility_state_for_section("Usage Overview")["dba_control_room_active_view"], "Cost Watch")
        self.assertEqual(
            compatibility_state_for_section("Service Health")["dba_control_room_active_view"],
            "Control Room Admin / Advanced",
        )
        self.assertEqual(compatibility_state_for_section("Fast Watch")["dba_control_room_active_view"], "Morning Cockpit")
        self.assertEqual(compatibility_state_for_section("Morning Brief")["dba_control_room_active_view"], "Morning Cockpit")
        self.assertEqual(SECTION_ALIASES["Credit Contract"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Cost Center"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Recommendations"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Cortex Monitor"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Security & Access"], SECTION_BY_TITLE["Security Monitoring"])
        self.assertEqual(SECTION_ALIASES["Security Posture"], SECTION_BY_TITLE["Security Monitoring"])
        self.assertEqual(SECTION_ALIASES["Data Sharing"], SECTION_BY_TITLE["Security Monitoring"])
        self.assertEqual(SECTION_ALIASES["Failed Logins"], SECTION_BY_TITLE["Security Monitoring"])
        self.assertEqual(SECTION_ALIASES["Access posture"], SECTION_BY_TITLE["Security Monitoring"])
        self.assertNotIn("DBA Tools", SECTION_ALIASES)
        self.assertNotIn("Change & Drift", SECTION_ALIASES)
        self.assertNotIn("Who Changed What?", SECTION_ALIASES)
        self.assertEqual(SECTION_ALIASES["Optimization"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(SECTION_ALIASES["Warehouse Health"], SECTION_BY_TITLE["Cost & Contract"])
        self.assertEqual(compatibility_state_for_section("Cost Center")["cost_contract_workflow"], "Cost by Warehouse")
        self.assertEqual(compatibility_state_for_section("Credit Contract")["cost_contract_workflow"], "Budget vs Actual")
        self.assertEqual(
            compatibility_state_for_section("Recommendations & Anomalies")["cost_contract_workflow"],
            "Cost Recommendations",
        )
        self.assertEqual(compatibility_state_for_section("Recommendations")["cost_contract_workflow"], "Cost Recommendations")
        self.assertEqual(compatibility_state_for_section("Cortex Monitor")["cost_contract_advanced_tool"], "Cortex Spend")
        self.assertEqual(compatibility_state_for_section("Warehouse Health")["cost_contract_workflow"], "Waste Detection")
        self.assertEqual(compatibility_state_for_section("Storage Monitor")["cost_contract_workflow"], "Cost Overview")
        self.assertEqual(compatibility_state_for_section("Storage Monitor")["cost_contract_advanced_tool"], "Storage & Retention")
        self.assertEqual(compatibility_state_for_section("AI & Cortex Monitor")["cost_contract_advanced_tool"], "Cortex Spend")
        self.assertEqual(compatibility_state_for_section("SPCS Tracker")["cost_contract_advanced_tool"], "SPCS Spend")
        self.assertNotIn("Architecture", SECTION_ALIASES)
        self.assertNotIn("Architecture Readiness", SECTION_ALIASES)
        self.assertNotIn("Disaster Recovery", SECTION_ALIASES)
        self.assertEqual(SECTION_ALIASES["Executive Briefing"], SECTION_BY_TITLE["Executive Landing"])
        self.assertNotIn("LEGACY_SECTION_ALIASES = {", (APP_ROOT / "config.py").read_text(encoding="utf-8"))

    def test_experience_views_are_removed_for_admin_only_app(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        access_text = (APP_ROOT / "access_control.py").read_text(encoding="utf-8")
        runtime_text = (APP_ROOT / "runtime_state.py").read_text(encoding="utf-8")
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")

        self.assertIn("Executive Landing", ALL_SECTIONS)
        self.assertEqual(SECTION_MODULES["Executive Landing"], "sections.executive_landing_shell")
        self.assertIn("ADMIN_ACCESS_ROLES", config_text)
        self.assertIn("def current_role_allows_app_access", access_text)
        self.assertIn("def render_admin_access_required", layout_text)
        self.assertNotIn("EXPERIENCE_VIEW_SECTIONS", config_text)
        self.assertNotIn("ROLE_EXPERIENCE_VIEWS", config_text)
        self.assertNotIn("resolve_allowed_experience_views", config_text)
        self.assertNotIn("default_experience_view_for_role", config_text)
        self.assertNotIn("Navigation View", app_text)
        self.assertNotIn("overwatch_experience_view", app_text)
        self.assertIn("def apply_admin_defaults", runtime_text)
        self.assertIn("exceptions_only_mode", runtime_text)
        self.assertNotIn("def _allowed_experience_options", app_text)
        self.assertNotIn("def _current_experience_view", app_text)
        self.assertNotIn("_sync_experience_navigation", app_text)

    def test_executive_landing_routes_to_workflow_panes(self):
        executive_text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")
        executive_shell = (APP_ROOT / "sections" / "executive_landing_shell.py").read_text(encoding="utf-8")
        executive_contracts = (APP_ROOT / "sections" / "executive_landing_contracts.py").read_text(encoding="utf-8")
        executive_common = (APP_ROOT / "sections" / "executive_landing_common.py").read_text(encoding="utf-8")
        executive_data_health = (APP_ROOT / "sections" / "executive_landing_data_health_view.py").read_text(encoding="utf-8")
        executive_overview = (APP_ROOT / "sections" / "executive_landing_overview_view.py").read_text(encoding="utf-8")
        executive_cost = (APP_ROOT / "sections" / "executive_landing_cost_view.py").read_text(encoding="utf-8")
        executive_security = (APP_ROOT / "sections" / "executive_landing_security_view.py").read_text(encoding="utf-8")
        executive_change = (APP_ROOT / "sections" / "executive_landing_change_view.py").read_text(encoding="utf-8")
        executive_admin = (APP_ROOT / "sections" / "executive_landing_admin_view.py").read_text(encoding="utf-8")
        route_registry_text = (APP_ROOT / "route_registry.py").read_text(encoding="utf-8")

        self.assertIn("_source_health_rows", executive_shell)
        self.assertIn("Executive Data Health", executive_data_health)
        self.assertIn("EXECUTIVE_LANDING_WORKFLOWS = (", executive_contracts)
        for workflow in (
            "Executive Overview",
            "Cost Movement",
            "Operational Risk",
            "Security Risk",
            "Change Summary",
            "Executive Actions",
            "Executive Admin / Advanced",
        ):
            self.assertIn(workflow, executive_contracts)
        self.assertIn("normalize_executive_landing_workflow", executive_shell)
        self.assertIn('WORKFLOW_ALIASES_BY_SECTION["Executive Landing"]', executive_contracts)
        self.assertIn('"Executive Briefing": "Executive Overview"', route_registry_text)
        self.assertIn('"Adoption Analytics": "Executive Admin / Advanced"', route_registry_text)
        self.assertIn('"alert_center_active_view": "Active Alerts"', executive_overview + executive_data_health)
        self.assertIn('workflow_key="cost_contract_workflow"', executive_common + executive_cost)
        self.assertIn('workflow="Cost by Warehouse"', executive_cost)
        self.assertIn('workflow_key="workload_operations_workflow"', executive_common + executive_change)
        self.assertIn('workflow="Change Analysis"', executive_change)
        self.assertIn('workflow_key="security_posture_workflow"', executive_overview + executive_security)
        self.assertIn('state_updates={"dba_control_room_active_view": "Change Watch"}', executive_change)
        self.assertIn("Scorecard formulas, value ledger, telemetry trust detail, production readiness", executive_admin)
        self.assertIn('with st.expander("Advanced observability charts and source grids", expanded=False):', executive_admin)

    def test_section_alias_literal_has_no_duplicate_keys(self):
        registry_tree = ast.parse((APP_ROOT / "route_registry.py").read_text(encoding="utf-8"))
        for dict_name in ("LEGACY_SECTION_ALIASES", "RETIRED_SECTION_ALIASES"):
            alias_dict = None
            for node in registry_tree.body:
                if (
                    isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == dict_name for target in node.targets)
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
            "Change Analysis",
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
        dba_control_text = _section_source(APP_ROOT / "sections" / "dba_control_room.py")

        self.assertNotIn("_render_admin_readiness_panel", dba_control_text)
        self.assertNotIn("Admin Readiness to 95", dba_control_text)
        self.assertNotIn("Average Readiness", dba_control_text)
        self.assertNotIn("Sections At 95", dba_control_text)
        self.assertNotIn("dba_control_plane_component_rows", dba_control_text)

    def test_dba_control_room_uses_shared_company_scope_and_cached_release_inventory(self):
        dba_control_text = _section_source(APP_ROOT / "sections" / "dba_control_room.py")

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

    def test_streamlit_manifest_uses_current_app_warehouse(self):
        manifest = (APP_ROOT / "snowflake.yml").read_text(encoding="utf-8")
        self.assertIn("query_warehouse: COMPUTE_WH", manifest)
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
        from sections import (
            alert_center,
            change_drift,
            cost_contract,
            dba_control_room,
            pipeline_health,
            query_analysis,
            security_posture,
            task_management,
            workload_operations,
        )

        self.assertEqual(
            workload_operations.WORKFLOWS,
            (
                "Workload Overview",
                "Query Investigation",
                "Pipeline & Task Health",
                "Performance & Contention",
                "Change Analysis",
                "Advanced DBA Tools",
            ),
        )
        self.assertEqual(len(workload_operations.WORKFLOWS), len(set(workload_operations.WORKFLOWS)))
        self.assertNotIn("Query & contention", workload_operations.WORKFLOWS)
        self.assertNotIn("AI query diagnosis", workload_operations.WORKFLOWS)
        self.assertNotIn("Live triage", workload_operations.WORKFLOWS)
        self.assertNotIn("Task graphs", workload_operations.WORKFLOWS)
        self.assertNotIn("History search", workload_operations.WORKFLOWS)
        self.assertNotIn("Task & procedure health", workload_operations.WORKFLOWS)
        self.assertNotIn("Stored procedures", workload_operations.WORKFLOWS)
        self.assertNotIn("Pipeline / SLA risk", workload_operations.WORKFLOWS)
        self.assertNotIn("Schema & data compare", workload_operations.WORKFLOWS)
        self.assertIn("History Search", query_analysis.QUERY_ANALYSIS_PANES)
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Query Investigation"], "sections.query_analysis")
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Performance & Contention"], "sections.contention_center")
        self.assertEqual(workload_operations.WORKFLOW_MODULES["Advanced DBA Tools"], "sections.dba_tools")
        self.assertIn("Failed Tasks", workload_operations.PIPELINE_FOCUS_DETAILS)
        self.assertIn("Failed Procedures", workload_operations.PIPELINE_FOCUS_DETAILS)
        self.assertIn("Load Issues & SLA", workload_operations.PIPELINE_FOCUS_DETAILS)
        self.assertEqual(workload_operations.CONSOLIDATED_WORKFLOW_ALIASES["Task graphs"], "Pipeline & Task Health")
        self.assertEqual(workload_operations.CONSOLIDATED_WORKFLOW_ALIASES["Stored procedures"], "Pipeline & Task Health")
        self.assertEqual(workload_operations.CONSOLIDATED_WORKFLOW_ALIASES["Pipeline health"], "Pipeline & Task Health")
        self.assertEqual(workload_operations.CONSOLIDATED_WORKFLOW_ALIASES["Contention Center"], "Performance & Contention")
        self.assertEqual(workload_operations.CONSOLIDATED_WORKFLOW_ALIASES["Schema Compare"], "Advanced DBA Tools")
        pipeline_health_text = (APP_ROOT / "sections" / "pipeline_health.py").read_text(encoding="utf-8")
        self.assertIn('key="pipe_load_failures_button"', pipeline_health_text)
        self.assertIn('st.session_state["pipe_load_failures"] = _annotate_pipeline_routes', pipeline_health_text)
        self.assertNotIn('st.button("Load Copy History Failures", key="pipe_load_failures")', pipeline_health_text)
        self.assertEqual(task_management.TASK_CONTROL_VIEWS[0], "Job Status Brief")
        self.assertIn("Snowflake task handoff", task_management.TASK_CONTROL_DETAILS["Job Status Brief"])
        task_management_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                APP_ROOT / "sections" / "task_management.py",
                APP_ROOT / "sections" / "task_management_job_status_view.py",
                APP_ROOT / "sections" / "task_management_sla_cost_view.py",
            ]
        )
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
        self.assertIn("render_shell_snapshot", task_management_text)
        self.assertIn('("Handoff State", task_status_state)', task_management_text)
        self.assertIn('"Performance Indicators"', task_management_text)
        self.assertIn('"SLA / Cost Drift"', task_management_text)
        self.assertIn('("Query Detail"', task_management_text)
        self.assertNotIn(".metric(", task_management_text)
        self.assertEqual(
            dba_control_room.DBA_CONTROL_ROOM_PANES,
            (
                "Morning Cockpit",
                "Failure Triage",
                "Cost Watch",
                "Performance Watch",
                "Change Watch",
                "Action Queue",
                "Control Room Admin / Advanced",
            ),
        )
        self.assertEqual(len(dba_control_room.DBA_CONTROL_ROOM_PANES), len(set(dba_control_room.DBA_CONTROL_ROOM_PANES)))
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Morning Cockpit"], "Morning")
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Failure Triage"], "Failures")
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Cost Watch"], "Cost")
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Performance Watch"], "Performance")
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Change Watch"], "Changes")
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Action Queue"], "Actions")
        self.assertEqual(dba_control_room.DBA_CONTROL_ROOM_PANE_LABELS["Control Room Admin / Advanced"], "Advanced")
        self.assertEqual(dba_control_room.normalize_dba_control_room_pane("Fast Watch"), "Morning Cockpit")
        self.assertEqual(dba_control_room.normalize_dba_control_room_pane("Morning Brief"), "Morning Cockpit")
        self.assertEqual(dba_control_room.normalize_dba_control_room_pane("Operations Detail"), "Action Queue")
        self.assertEqual(dba_control_room.normalize_dba_control_room_pane("Triage"), "Failure Triage")
        self.assertEqual(dba_control_room.normalize_dba_control_room_pane("Service Posture"), "Control Room Admin / Advanced")
        self.assertEqual(dba_control_room.normalize_dba_control_room_pane("Admin Tools"), "Control Room Admin / Advanced")
        self.assertNotIn("Service Posture", dba_control_room.DBA_CONTROL_ROOM_PANES)
        self.assertNotIn("Admin Tools", dba_control_room.DBA_CONTROL_ROOM_PANES)
        self.assertNotIn("Operations Detail", dba_control_room.DBA_CONTROL_ROOM_PANES)
        self.assertEqual(
            cost_contract.WORKFLOWS,
            (
                "Cost Overview",
                "Cost by Warehouse",
                "Cost by User / Role",
                "Burn Rate & Forecast",
                "Budget vs Actual",
                "Waste Detection",
                "Chargeback / Company Split",
                "Cost Recommendations",
            ),
        )
        self.assertIn("Cost Recommendations", cost_contract.WORKFLOWS)
        self.assertNotIn("Cortex Spend", cost_contract.WORKFLOWS)
        self.assertNotIn("Advanced Cost Tools", cost_contract.WORKFLOWS)
        self.assertEqual(cost_contract.LEGACY_COST_WORKFLOW_ALIASES["Forecast"], "Burn Rate & Forecast")
        self.assertEqual(cost_contract.LEGACY_COST_WORKFLOW_ALIASES["Chargeback"], "Chargeback / Company Split")
        self.assertEqual(cost_contract.LEGACY_COST_WORKFLOW_ALIASES["Recommendations"], "Cost Recommendations")
        self.assertEqual(cost_contract.LEGACY_COST_WORKFLOW_ALIASES["Cortex Spend"], "Cost Overview")
        self.assertEqual(cost_contract.LEGACY_COST_INNER_VIEW_ALIASES["Forecast"]["cost_center_view"], "Forecast")
        self.assertEqual(cost_contract.LEGACY_COST_INNER_VIEW_ALIASES["Attribution"]["cost_center_view"], "Attribution")
        cost_contract_text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        self.assertIn("_PRESERVE_COST_CENTER_VIEW_KEY", cost_contract_text)
        self.assertIn("_LAST_COST_WORKFLOW_KEY", cost_contract_text)
        self.assertEqual(cost_contract.ADVANCED_COST_TOOL_MODULES["Storage & Retention"], "sections.storage_monitor")
        self.assertEqual(cost_contract.ADVANCED_COST_TOOL_MODULES["Cortex Spend"], "sections.cortex_monitor")
        self.assertEqual(cost_contract.WORKFLOW_MODULES["Cost by User / Role"], "sections.cost_center")
        self.assertFalse((APP_ROOT / "sections" / "budget_monitoring.py").exists())
        self.assertFalse((APP_ROOT / "sections" / "finops_control.py").exists())
        self.assertEqual(
            tuple(alert_center.ALERT_CENTER_PANES),
            (
                "Active Alerts",
                "Cost Alerts",
                "Reliability Alerts",
                "Security Alerts",
                "Alert History",
                "Alert Settings / Admin",
            ),
        )
        self.assertEqual(alert_center.ALERT_CENTER_DEFAULT_VIEW, "Active Alerts")
        self.assertEqual(alert_center._normalize_alert_center_view("Alert Configuration"), "Alert Settings / Admin")
        self.assertEqual(alert_center._normalize_alert_center_view("Advanced Alert Admin"), "Alert Settings / Admin")
        self.assertEqual(alert_center._normalize_alert_center_view("Alert History"), "Alert History")
        self.assertEqual(alert_center._alert_admin_view_for_route("Alert Configuration"), "Delivery & Automation")
        self.assertEqual(alert_center.ALERT_CENTER_SOURCES_BY_PANE["Alert History"], {"alerts", "action_queue", "delivery_log"})
        self.assertEqual(SECTION_ALIASES["Alerts"], SECTION_BY_TITLE["Alert Center"])
        self.assertEqual(compatibility_state_for_section("Alerts")["alert_center_active_view"], "Active Alerts")
        self.assertEqual(compatibility_state_for_section("Alert History")["alert_center_active_view"], "Alert History")
        self.assertEqual(compatibility_state_for_section("Alert Configuration")["alert_center_active_view"], "Alert Settings / Admin")
        self.assertEqual(compatibility_state_for_section("Alert Configuration")["alert_center_admin_view"], "Delivery & Automation")
        self.assertEqual(
            tuple(security_posture.WORKFLOWS),
            (
                "Security Overview",
                "Failed Logins",
                "Risky Grants",
                "Privilege Sprawl",
                "Access Changes",
                "Data Sharing Exposure",
                "Security Alerts",
                "Security Admin / Advanced",
            ),
        )
        self.assertEqual(len(security_posture.WORKFLOWS), len(set(security_posture.WORKFLOWS)))
        self.assertEqual(security_posture.WORKFLOW_MODULES["Failed Logins"], "sections.security_access")
        self.assertEqual(security_posture.WORKFLOW_MODULES["Risky Grants"], "sections.security_access")
        self.assertEqual(security_posture.WORKFLOW_MODULES["Data Sharing Exposure"], "sections.data_sharing")
        self.assertEqual(compatibility_state_for_section("Security Posture")["security_posture_view"], "Security Overview")
        self.assertEqual(compatibility_state_for_section("Security & Access")["security_posture_view"], "Risky Grants")
        self.assertEqual(compatibility_state_for_section("Data Sharing")["security_posture_view"], "Data Sharing Exposure")
        self.assertEqual(compatibility_state_for_section("Failed Logins")["security_posture_view"], "Failed Logins")
        self.assertEqual(compatibility_state_for_section("Access posture")["security_posture_view"], "Security Overview")
        self.assertNotIn("Release evidence", change_drift.WORKFLOWS)
        self.assertNotIn("Owner approval evidence", change_drift.WORKFLOWS)
        self.assertIn("Schema and object drift", change_drift.WORKFLOWS)
        self.assertIn("Data movement and replication", change_drift.WORKFLOWS)
        self.assertIn("Controlled DBA actions", change_drift.WORKFLOWS)
        self.assertEqual(change_drift.WORKFLOW_MODULES["Controlled DBA actions"], "sections.dba_tools")
        change_drift_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                APP_ROOT / "sections" / "change_drift.py",
                APP_ROOT / "sections" / "change_drift_workflows_view.py",
            ]
        )
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
            "cost_contract_workflow.py": [
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
            if file_name == "change_drift.py":
                text = "\n".join(
                    path.read_text(encoding="utf-8")
                    for path in [
                        APP_ROOT / "sections" / "change_drift.py",
                        APP_ROOT / "sections" / "change_drift_contracts.py",
                        APP_ROOT / "sections" / "change_drift_workflows_view.py",
                    ]
                )
            else:
                text = (APP_ROOT / "sections" / file_name).read_text(encoding="utf-8")
            with self.subTest(file_name=file_name):
                self.assertIn("WORKFLOW_MODULES", text)
                self.assertIn("render_workflow_module(", text)
                for pattern in removed_patterns:
                    self.assertNotIn(pattern, text)

    def test_primary_navigation_stays_six_section_model(self):
        self.assertEqual(
            PRIMARY_SECTIONS,
            [
                "Executive Landing",
                "DBA Control Room",
                "Alert Center",
                "Cost & Contract",
                "Workload Operations",
                "Security Monitoring",
            ],
        )
        self.assertNotIn("Command Center", PRIMARY_SECTIONS)
        self.assertNotIn("Incidents", PRIMARY_SECTIONS)
        self.assertNotIn("Optimization", PRIMARY_SECTIONS)
        self.assertNotIn("Settings", PRIMARY_SECTIONS)

    def test_workflow_contract_matches_primary_navigation(self):
        self.assertEqual(tuple(PRIMARY_SECTIONS), PRIMARY_SECTION_TITLES)
        self.assertEqual(set(SECTION_WORKFLOW_CONTRACT), set(PRIMARY_SECTIONS))
        self.assertFalse(set(ABANDONED_PRIMARY_SECTION_TITLES) & set(PRIMARY_SECTIONS))
        self.assertGreaterEqual(len(LEGACY_ROUTE_CONTRACT), 30)

    def test_cost_contract_workflow_detail_renders_on_selection(self):
        from sections import cost_contract, cost_contract_contracts

        text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        workflow_text = (APP_ROOT / "sections" / "cost_contract_workflow.py").read_text(encoding="utf-8")

        self.assertEqual(cost_contract._DETAIL_WORKFLOW_KEY, "_cost_contract_detail_workflow")
        self.assertEqual(cost_contract._PENDING_DETAIL_WORKFLOW_KEY, "_cost_contract_pending_detail_workflow")
        self.assertIs(cost_contract.WORKFLOWS, cost_contract_contracts.WORKFLOWS)
        self.assertNotIn('st.button("Open detail"', text)
        self.assertNotIn("if open_workflow == workflow:", text)
        self.assertIn("routed_workflow = st.session_state.pop(_PENDING_DETAIL_WORKFLOW_KEY, None)", text)
        self.assertIn("legacy_detail_workflow = st.session_state.pop(_DETAIL_WORKFLOW_KEY, None)", text)
        self.assertNotIn('st.button("Open full cockpit boards"', text)
        self.assertNotIn("_FULL_COCKPIT_BOARDS_KEY", text)
        self.assertIn("render_workflow_module(workflow, WORKFLOW_MODULES)", workflow_text)

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
            "spcs_tracker.py",
            "storage_monitor.py",
            "stored_proc_tracker.py",
        ]
        for filename in compact_files:
            with self.subTest(filename=filename):
                if filename == "cost_center.py":
                    section_text = "\n".join(
                        path.read_text(encoding="utf-8")
                        for path in sorted((APP_ROOT / "sections").glob("cost_center*_view.py"))
                    )
                else:
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
                if filename == "change_drift.py":
                    section_text = "\n".join(
                        path.read_text(encoding="utf-8")
                        for path in [
                            APP_ROOT / "sections" / "change_drift.py",
                            APP_ROOT / "sections" / "change_drift_workflows_view.py",
                        ]
                    )
                else:
                    section_text = (APP_ROOT / "sections" / filename).read_text(encoding="utf-8")
                self.assertNotIn("def render_workflow_selector", section_text)
                self.assertIn('render_workflow_selector = _lazy_util("render_workflow_selector")', section_text)
                self.assertNotIn("return str(st.selectbox(label, list(workflows), key=key))", section_text)

    def test_global_filter_and_metric_changes_clear_loaded_state(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        filters_text = (APP_ROOT / "filters.py").read_text(encoding="utf-8")
        refresh_text = (APP_ROOT / "refresh.py").read_text(encoding="utf-8")
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")
        shell_text = (APP_ROOT / "shell.py").read_text(encoding="utf-8")
        runtime_text = (APP_ROOT / "runtime_state.py").read_text(encoding="utf-8")
        cache_text = (APP_ROOT / "utils" / "cache.py").read_text(encoding="utf-8")
        company_filter_text = (APP_ROOT / "utils" / "company_filter.py").read_text(encoding="utf-8")
        query_text = (APP_ROOT / "utils" / "query.py").read_text(encoding="utf-8")
        state_keys_text = (APP_ROOT / "utils" / "state_keys.py").read_text(encoding="utf-8")
        self.assertIn("from shell import render_app", app_text)
        self.assertIn("def global_filter_signature", filters_text)
        self.assertIn("def metric_settings_signature", refresh_text)
        self.assertIn("str(get_state(GLOBAL_SCHEMA, \"\"))", filters_text)
        self.assertNotIn("load_schema_options", filters_text)
        self.assertIn("GLOBAL_SCHEMA_CHOICE_SCOPE", filters_text)
        self.assertIn('GLOBAL_SCHEMA_CHOICE_SCOPE = "_global_schema_choice_scope"', runtime_text)
        self.assertIn("Schema contains", filters_text)
        self.assertIn("def render_topbar_filter_strip", filters_text)
        self.assertIn("def maybe_clear_scope_cache_on_filter_change", filters_text)
        self.assertIn("maybe_clear_scope_cache_on_filter_change()", shell_text)
        self.assertIn("WIDGET_GLOBAL_FILTERS_CLEAR_TOPBAR", filters_text)
        self.assertIn('WIDGET_GLOBAL_FILTERS_CLEAR_TOPBAR = "global_filters_clear_topbar"', runtime_text)
        self.assertIn("Optional role, database, and schema narrowing.", filters_text)
        self.assertIn("get_global_schema_filter_clause", company_filter_text)
        self.assertIn("schema_col", company_filter_text)
        self.assertIn("previous_filter_signature != current_filter_signature", filters_text)
        self.assertIn("previous_metric_signature != current_metric_signature", layout_text)
        self.assertIn("clear_all_cache()", layout_text)
        self.assertIn("clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)", filters_text)
        self.assertIn("clear_all_cache(clear_streamlit_cache=False, clear_metadata=False)", layout_text)
        self.assertIn("bump_global_cache_salt", cache_text)
        self.assertIn("set_state(REFRESH_SALT_GLOBAL, salt)", cache_text)
        self.assertNotIn("st.cache_data.clear()", cache_text)
        self.assertIn("get_state(REFRESH_SALT_GLOBAL", query_text)
        self.assertIn("get_state(GLOBAL_ENVIRONMENT", query_text)
        self.assertNotIn('st.session_state.get("exceptions_only_mode"', query_text)
        self.assertIn("get_state(CURRENT_ROLE", query_text)
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
        access_text = (APP_ROOT / "access_control.py").read_text(encoding="utf-8")
        runtime_text = (APP_ROOT / "runtime_state.py").read_text(encoding="utf-8")
        shell_text = (APP_ROOT / "shell.py").read_text(encoding="utf-8")
        navigation_text = (APP_ROOT / "navigation.py").read_text(encoding="utf-8")

        self.assertIn("from shell import render_app", app_text)
        self.assertIn("def seed_current_role_from_secrets", access_text)
        self.assertIn('snowflake_cfg.get("role")', access_text)
        self.assertIn("seed_current_role_from_secrets()", shell_text)
        self.assertIn("def apply_admin_defaults", runtime_text)
        self.assertIn("apply_admin_defaults()", shell_text)
        for text in (app_text, access_text, runtime_text, shell_text):
            self.assertNotIn("resolve_role_profile(get_current_role())", text)
            self.assertNotIn("resolve_allowed_experience_views(get_current_role())", text)
            self.assertNotIn("matched_profile", text)
        self.assertIn("compatibility_state_for_section", navigation_text)
        self.assertIn("apply_section_compatibility_state(raw_section)", navigation_text)

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
        navigation_text = (APP_ROOT / "navigation.py").read_text(encoding="utf-8")
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")
        shell_text = (APP_ROOT / "shell.py").read_text(encoding="utf-8")
        dispatch_text = (APP_ROOT / "section_dispatch.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")

        self.assertIn("from shell import render_app", app_text)
        self.assertIn("def queue_section_navigation", navigation_text)
        self.assertIn("CONNECTION_OPTIONAL_SECTIONS = set(ALL_SECTIONS)", navigation_text)
        self.assertIn("def section_requires_connection", navigation_text)
        self.assertIn("PENDING_SECTION", navigation_text)
        self.assertIn("def section_render_signature", (APP_ROOT / "refresh.py").read_text(encoding="utf-8"))
        self.assertIn("LAST_SECTION_RENDER_SIGNATURE", navigation_text)
        self.assertIn("def should_show_section_transition", navigation_text)
        self.assertIn("has_pending_navigation = PENDING_SECTION in st.session_state", navigation_text)
        self.assertIn("section_changed = bool(", navigation_text)
        self.assertIn("section_slot = st.empty()", shell_text)
        self.assertIn("def fresh_section_container", layout_text)
        self.assertIn("slot.empty()", layout_text)
        self.assertIn("render_section_transition_state(active_section)", shell_text)
        self.assertIn("with fresh_section_container(section_slot):", shell_text)
        self.assertIn("dispatch_section(active_section)", shell_text)
        self.assertIn("def dispatch_section", dispatch_text)
        self.assertIn("needs_connection = section_requires_connection(active_section)", shell_text)
        self.assertIn("elif needs_connection and (", shell_text)
        self.assertNotIn("transition_slot = st.empty()", app_text)
        self.assertNotIn("transition_slot.empty()", app_text)
        self.assertIn(".ow-section-transition", theme_text)
        self.assertIn("position: fixed", theme_text)

    def test_app_shell_header_renders_before_sidebar_hydration(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        shell_text = (APP_ROOT / "shell.py").read_text(encoding="utf-8")
        layout_text = (APP_ROOT / "layout.py").read_text(encoding="utf-8")
        filters_text = (APP_ROOT / "filters.py").read_text(encoding="utf-8")
        runtime_text = (APP_ROOT / "runtime_state.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        evidence_mode_text = (APP_ROOT / "utils" / "evidence_mode.py").read_text(encoding="utf-8")

        header_index = shell_text.index("render_app_header(active_section, active_company, credit_price, current_role)")
        topbar_index = shell_text.index("active_company = render_topbar_filter_strip(active_company)")
        sidebar_index = shell_text.index("render_sidebar(")
        self.assertLess(header_index, sidebar_index)
        self.assertLess(header_index, topbar_index)
        self.assertLess(topbar_index, sidebar_index)
        self.assertIn("def current_active_section", (APP_ROOT / "navigation.py").read_text(encoding="utf-8"))
        self.assertIn("def current_credit_price", (APP_ROOT / "refresh.py").read_text(encoding="utf-8"))
        self.assertIn("@dataclass(frozen=True)", layout_text)
        self.assertIn("class SidebarState", layout_text)
        from layout import SidebarState

        self.assertTrue(is_dataclass(SidebarState))
        self.assertEqual(
            [field.name for field in fields(SidebarState)],
            [
                "active_company",
                "active_section",
                "current_role",
                "admin_access_allowed",
                "connection_available",
                "idle_query_paused",
                "credit_price",
                "visible_sections",
            ],
        )
        self.assertIn("sidebar_state = render_sidebar(", shell_text)
        self.assertIn("active_company = sidebar_state.active_company", shell_text)
        self.assertIn("active_section = sidebar_state.active_section", shell_text)
        self.assertIn("connection_available = sidebar_state.connection_available", shell_text)
        self.assertIn("idle_query_paused = sidebar_state.idle_query_paused", shell_text)
        self.assertNotIn(
            "active_section, admin_allowed, visible_sections, credit_price, current_role = render_sidebar",
            shell_text,
        )
        self.assertIn("cached_snowflake_available(default=False)", shell_text)
        self.assertIn("def sidebar_panel_toggle", layout_text)
        sidebar_toggle_block = layout_text[
            layout_text.index("def sidebar_panel_toggle"):
            layout_text.index("def format_idle_duration")
        ]
        self.assertIn('type="secondary"', sidebar_toggle_block)
        self.assertNotIn('type="primary" if is_active else "secondary"', sidebar_toggle_block)
        self.assertIn("ow-filter-strip-kicker", filters_text)
        self.assertNotIn("def _render_priority_brief_empty_state", app_text + shell_text + layout_text)
        self.assertNotIn("Open Executive Landing for the ranked platform brief.", app_text + shell_text + layout_text)
        self.assertNotIn(".ow-priority-empty", theme_text)
        self.assertNotIn("load or refresh a section to populate priority evidence", app_text + shell_text + layout_text)
        self.assertIn('"Date range"', filters_text)
        self.assertIn('"Warehouse"', filters_text)
        self.assertIn('"User contains"', filters_text)
        self.assertIn('if sidebar_panel_toggle("Advanced Scope", "advanced_scope")', layout_text)
        self.assertIn('if sidebar_panel_toggle("Settings", "settings")', layout_text)
        self.assertEqual(layout_text.count('if sidebar_panel_toggle("Advanced Scope", "advanced_scope")'), 1)
        self.assertNotIn('if sidebar_panel_toggle("Saved Views", "saved_views")', layout_text)
        self.assertNotIn('if sidebar_panel_toggle("Global Filters", "global_filters")', layout_text)
        self.assertIn("Optional role, database, and schema narrowing.", filters_text)
        self.assertNotIn("TRIAGE_MODE_OPTIONS", runtime_text)
        self.assertNotIn('"Evidence Mode"', layout_text)
        self.assertIn("triage_view_mode", runtime_text)
        self.assertIn("sync_exceptions_only_mode", runtime_text)
        self.assertIn("TRIAGE_MODE_TRIAGE", runtime_text)
        self.assertNotIn("TRIAGE_MODE_INVESTIGATE", runtime_text)
        self.assertNotIn("TRIAGE_MODE_ALL_EVIDENCE", runtime_text)
        self.assertIn("TRIAGE_MODE_LEGACY_ALIASES", evidence_mode_text)
        self.assertNotIn('"Exceptions-only mode"', app_text + shell_text + layout_text)
        for path in APP_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            self.assertNotIn("Exceptions-only mode", path.read_text(encoding="utf-8"), str(path))
        self.assertNotIn("st.toggle(", app_text + shell_text + layout_text)
        self.assertNotIn("Command Palette", app_text + shell_text + layout_text)
        self.assertNotIn("command_palette", app_text + shell_text + layout_text)
        self.assertNotIn('with st.expander("Saved Views", expanded=False)', app_text + shell_text + layout_text)
        self.assertNotIn('with st.expander("Global Filters", expanded=False)', app_text + shell_text + layout_text)
        self.assertNotIn('with st.expander("Settings", expanded=False)', app_text + shell_text + layout_text)
        self.assertLess(shell_text.index("render_topbar_filter_strip"), shell_text.index("render_sidebar("))
        self.assertLess(layout_text.index('if sidebar_panel_toggle("Advanced Scope", "advanced_scope")'), layout_text.index('if sidebar_panel_toggle("Settings", "settings")'))

    def test_idle_shell_render_does_not_probe_snowflake(self):
        import shell
        from layout import SidebarState
        from runtime_state import ACTIVE_COMPANY, CURRENT_ROLE

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state[ACTIVE_COMPANY] = "ALFA"
            st.session_state[CURRENT_ROLE] = "SNOW_ACCOUNTADMINS"

            with contextlib.ExitStack() as stack:
                for name in (
                    "inject_theme",
                    "ensure_startup_state",
                    "seed_current_role_from_secrets",
                    "apply_admin_defaults",
                    "ensure_idle_state",
                    "set_active_section",
                    "render_app_header",
                    "maybe_clear_scope_cache_on_filter_change",
                    "mark_section_rendered",
                    "log_section_load",
                ):
                    stack.enter_context(patch.object(shell, name))
                stack.enter_context(patch.object(shell, "queries_paused", return_value=True))
                stack.enter_context(
                    patch.object(shell, "mark_operator_activity", side_effect=AssertionError("activity marked while idle"))
                )
                stack.enter_context(
                    patch.object(
                        shell,
                        "probe_snowflake_available",
                        side_effect=AssertionError("Snowflake probe during idle"),
                    )
                )
                stack.enter_context(
                    patch.object(
                        shell,
                        "refresh_current_role_for_access",
                        side_effect=AssertionError("role refresh during idle"),
                    )
                )
                mock_cached = stack.enter_context(
                    patch.object(shell, "cached_snowflake_available", return_value=True)
                )
                stack.enter_context(patch.object(shell, "current_visible_sections", return_value=["Executive Landing"]))
                stack.enter_context(patch.object(shell, "current_active_section", return_value="Executive Landing"))
                stack.enter_context(patch.object(shell, "current_credit_price", return_value=3.0))
                stack.enter_context(patch.object(shell, "render_topbar_filter_strip", return_value="ALFA"))
                stack.enter_context(
                    patch.object(
                        shell,
                        "render_sidebar",
                        return_value=SidebarState(
                            active_company="ALFA",
                            active_section="Executive Landing",
                            current_role="SNOW_ACCOUNTADMINS",
                            admin_access_allowed=True,
                            connection_available=True,
                            idle_query_paused=True,
                            credit_price=3.0,
                            visible_sections=["Executive Landing"],
                        ),
                    )
                )
                stack.enter_context(
                    patch.object(shell, "section_render_signature", return_value=("Executive Landing", "ALFA"))
                )
                stack.enter_context(patch.object(shell, "should_show_section_transition", return_value=False))
                stack.enter_context(patch.object(shell, "section_requires_connection", return_value=True))
                stack.enter_context(patch.object(shell.st, "empty", return_value=object()))
                stack.enter_context(
                    patch.object(shell, "fresh_section_container", return_value=contextlib.nullcontext())
                )
                mock_pause = stack.enter_context(patch.object(shell, "render_query_pause_state"))
                shell.render_app()

            mock_cached.assert_called_once_with(default=False)
            mock_pause.assert_called_once()
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_connection_optional_first_paint_does_not_probe_snowflake(self):
        import shell
        from layout import SidebarState
        from runtime_state import ACTIVE_COMPANY, CURRENT_ROLE

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state[ACTIVE_COMPANY] = "ALFA"
            st.session_state[CURRENT_ROLE] = "SNOW_ACCOUNTADMINS"

            with contextlib.ExitStack() as stack:
                for name in (
                    "inject_theme",
                    "ensure_startup_state",
                    "seed_current_role_from_secrets",
                    "apply_admin_defaults",
                    "ensure_idle_state",
                    "set_active_section",
                    "render_app_header",
                    "maybe_clear_scope_cache_on_filter_change",
                    "mark_section_rendered",
                    "log_section_load",
                    "render_trace_marker",
                ):
                    stack.enter_context(patch.object(shell, name))
                stack.enter_context(patch.object(shell, "queries_paused", return_value=False))
                stack.enter_context(patch.object(shell, "mark_operator_activity"))
                stack.enter_context(
                    patch.object(
                        shell,
                        "probe_snowflake_available",
                        side_effect=AssertionError("optional first paint should not probe Snowflake"),
                    )
                )
                mock_cached = stack.enter_context(
                    patch.object(shell, "cached_snowflake_available", return_value=False)
                )
                stack.enter_context(
                    patch.object(shell, "refresh_current_role_for_access", return_value="SNOW_ACCOUNTADMINS")
                )
                stack.enter_context(patch.object(shell, "current_visible_sections", return_value=["Executive Landing"]))
                stack.enter_context(patch.object(shell, "current_active_section", return_value="Executive Landing"))
                stack.enter_context(patch.object(shell, "section_requires_connection", return_value=False))
                stack.enter_context(patch.object(shell, "current_credit_price", return_value=3.0))
                stack.enter_context(patch.object(shell, "render_topbar_filter_strip", return_value="ALFA"))
                stack.enter_context(
                    patch.object(
                        shell,
                        "render_sidebar",
                        return_value=SidebarState(
                            active_company="ALFA",
                            active_section="Executive Landing",
                            current_role="SNOW_ACCOUNTADMINS",
                            admin_access_allowed=True,
                            connection_available=False,
                            idle_query_paused=False,
                            credit_price=3.0,
                            visible_sections=["Executive Landing"],
                        ),
                    )
                )
                stack.enter_context(
                    patch.object(shell, "section_render_signature", return_value=("Executive Landing", "ALFA"))
                )
                stack.enter_context(patch.object(shell, "should_show_section_transition", return_value=False))
                stack.enter_context(patch.object(shell.st, "empty", return_value=object()))
                stack.enter_context(
                    patch.object(shell, "fresh_section_container", return_value=contextlib.nullcontext())
                )
                mock_dispatch = stack.enter_context(patch.object(shell, "dispatch_section"))
                shell.render_app()

            mock_cached.assert_called_once_with(default=False)
            mock_dispatch.assert_called_once_with("Executive Landing")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_shell_session_state_access_is_centralized(self):
        runtime_text = (APP_ROOT / "runtime_state.py").read_text(encoding="utf-8")
        self.assertIn("def get_state", runtime_text)
        self.assertIn("def set_state", runtime_text)
        self.assertIn("def pop_state", runtime_text)
        self.assertIn("def ensure_default_state", runtime_text)
        self.assertIn("def clear_scoped_state", runtime_text)

        forbidden = re.compile(r"st\.session_state(?:\[(?:'|\")|\.get\(|\.pop\(|\.setdefault\()")
        shell_modules = [
            APP_ROOT / "shell.py",
            APP_ROOT / "layout.py",
            APP_ROOT / "filters.py",
            APP_ROOT / "navigation.py",
            APP_ROOT / "access_control.py",
            APP_ROOT / "refresh.py",
            APP_ROOT / "sections" / "navigation.py",
            APP_ROOT / "utils" / "action_queue.py",
            APP_ROOT / "utils" / "session.py",
            APP_ROOT / "utils" / "query.py",
            APP_ROOT / "utils" / "cache.py",
            APP_ROOT / "utils" / "command_board.py",
            APP_ROOT / "utils" / "company_filter.py",
            APP_ROOT / "utils" / "compatibility.py",
            APP_ROOT / "utils" / "idle.py",
            APP_ROOT / "utils" / "mart.py",
            APP_ROOT / "utils" / "metadata.py",
            APP_ROOT / "utils" / "optimization_advisor.py",
            APP_ROOT / "utils" / "shared_metrics.py",
        ]
        offenders = []
        for path in shell_modules:
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if forbidden.search(line):
                    offenders.append(f"{path.relative_to(APP_ROOT)}:{line_no}:{line.strip()}")
        self.assertEqual(offenders, [])

        contract_text = (ROOT / "docs" / "SESSION_STATE_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("Known Exceptions", contract_text)
        self.assertIn("Streamlit widget keys", contract_text)

    def test_access_empty_states_render_safely(self):
        import layout

        with patch.object(layout.st, "markdown") as mock_markdown:
            layout.render_admin_access_required("APP_READONLY")
        self.assertTrue(mock_markdown.called)

        with (
            patch.object(layout.st, "markdown") as mock_markdown,
            patch.object(layout.st, "button", return_value=False) as mock_button,
        ):
            layout.render_connection_empty_state("DBA Control Room")
        self.assertTrue(mock_markdown.called)
        mock_button.assert_called_once()

    def test_cached_admin_role_suppresses_scope_switch_access_flicker(self):
        import access_control
        import navigation
        from runtime_state import LAST_ALLOWED_ROLE, LAST_SECTION_RENDER_SIGNATURE, PENDING_SECTION

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state[LAST_ALLOWED_ROLE] = "SNOW_SYSADMINS"

            with patch.object(access_control, "get_session", side_effect=AssertionError("role refresh should not block scope switch")):
                self.assertEqual(access_control.refresh_current_role_for_access(True), "SNOW_SYSADMINS")
            self.assertTrue(access_control.admin_access_is_allowed("", True))

            st.session_state.clear()
            st.session_state[LAST_SECTION_RENDER_SIGNATURE] = ("Executive Landing", "ALFA")
            self.assertFalse(navigation.should_show_section_transition(("Executive Landing", "Trexis")))
            st.session_state[PENDING_SECTION] = "Cost & Contract"
            self.assertTrue(navigation.should_show_section_transition(("Cost & Contract", "Trexis")))
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

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
        self.assertIn("WORKLOAD_OVERVIEW_WORKFLOW", workload_text)
        self.assertIn("QUERY_INVESTIGATION_WORKFLOW", workload_text)
        self.assertIn("PIPELINE_TASK_HEALTH_WORKFLOW", workload_text)
        self.assertIn("CONTENTION_PERFORMANCE_WORKFLOW", workload_text)
        self.assertIn("CHANGE_DRIFT_WORKFLOW", workload_text)
        self.assertIn("ADVANCED_DBA_TOOLS_WORKFLOW", workload_text)
        self.assertIn("AI_QUERY_DIAGNOSIS_WORKFLOW", workload_text)
        self.assertNotIn("TRIAGE_FOCI", workload_text)
        self.assertNotIn("PIPELINE_FOCI", workload_text)
        self.assertNotIn("Workload Brief", workload_text)
        self.assertNotIn("workload_operations_view", workload_text)
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
        self.assertIn('or "PROOF" in upper', workflows_text)
        self.assertIn('or "EVIDENCE" in upper', workflows_text)
        self.assertIn('or "VERIFY" in upper', workflows_text)
        self.assertIn('or "VERIFICATION" in upper', workflows_text)
        self.assertIn('or "MANUAL" in upper', workflows_text)
        self.assertIn('or "OWNER" in upper', workflows_text)
        self.assertIn('or "INTERNAL" in upper', workflows_text)
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
        shell_helpers_text = (APP_ROOT / "sections" / "shell_helpers.py").read_text(encoding="utf-8")
        theme_text = (APP_ROOT / "theme.py").read_text(encoding="utf-8")
        workflows_text = (APP_ROOT / "utils" / "workflows.py").read_text(encoding="utf-8")

        self.assertIn("WORKFLOWS_VERSION", workflows_text)
        self.assertNotIn("WORKFLOWS_VERSION", app_text)
        self.assertNotIn("reload_loaded_sections()", app_text)
        self.assertNotIn("_maybe_reload_dev_helpers", app_text)
        self.assertNotIn("_overwatch_dev_reload_helpers", app_text)
        self.assertNotIn("CONFIG_VERSION", app_text)
        self.assertNotIn("UTILS_EXPORT_VERSION", app_text)
        self.assertNotIn("SECTION_GUIDANCE_VERSION", app_text)
        self.assertNotIn("THEME_VERSION", app_text)
        self.assertNotIn("help=details.get(workflow) or None", workflows_text)
        self.assertNotIn("help=details.get(mode) or None", workflows_text)
        self.assertNotIn("st.caption(details[workflow])", workflows_text)
        self.assertNotIn("st.caption(details[mode])", workflows_text)
        self.assertNotIn("help=caption or None", shell_helpers_text)
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
                section_text = _section_source(APP_ROOT / "sections" / filename)
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
