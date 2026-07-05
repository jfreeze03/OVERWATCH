from __future__ import annotations

import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class WorkloadOperationsButtonRoutingTests(unittest.TestCase):
    def test_workload_route_labels_set_canonical_pipeline_focus(self) -> None:
        import sections.navigation as navigation

        cases = {
            "Pipeline & Tasks": "Failed Tasks",
            "Pipeline & Task Health": "Failed Tasks",
            "Failed Tasks": "Failed Tasks",
            "Failed Procedures": "Failed Procedures",
            "Load Issues & SLA": "Load Issues & SLA",
            "SLA Risk": "SLA Risk",
            "Suspended Tasks": "Suspended Tasks",
        }
        for workflow, expected_focus in cases.items():
            with self.subTest(workflow=workflow):
                updates: list[tuple[str, object]] = []
                with (
                    patch.object(navigation, "query_budget_context", lambda *args, **kwargs: nullcontext()),
                    patch.object(navigation, "apply_navigation_state", return_value="Workload Operations"),
                    patch.object(navigation, "set_state", side_effect=lambda key, value: updates.append((key, value))),
                ):
                    navigation.apply_section_workflow_navigation("Workload Operations", workflow=workflow)
                self.assertIn(("workload_operations_workflow", "Pipeline & Task Health"), updates)
                self.assertIn(("workload_operations_pipeline_focus", expected_focus), updates)

    def test_pipeline_task_lenses_reset_underlying_module_state(self) -> None:
        import sections.workload_operations as workload

        cases = {
            "Failed Tasks": [("task_management_view", "Job Status Brief")],
            "SLA Risk": [
                ("task_management_view", "SLA & Cost Drift"),
                ("task_management_embedded_lens", "SLA Risk"),
            ],
            "Suspended Tasks": [
                ("task_management_view", "Job Status Brief"),
                ("task_management_embedded_lens", "Suspended Tasks"),
                ("task_management_status_filter", "Suspended"),
            ],
            "Load Issues & SLA": [("pipeline_health_active_view", "Load Failures")],
        }
        for focus, expected_updates in cases.items():
            with self.subTest(focus=focus):
                updates: list[tuple[str, object]] = []
                rendered: list[str] = []
                with (
                    patch.object(workload, "_render_workload_lens_selector", return_value=focus),
                    patch.object(workload, "render_workflow_module", side_effect=lambda workflow, modules: rendered.append(workflow)),
                    patch.object(workload, "set_state", side_effect=lambda key, value: updates.append((key, value))),
                ):
                    workload._render_pipeline_task_health_surface()
                for update in expected_updates:
                    self.assertIn(update, updates)
                self.assertTrue(rendered)

    def test_pipeline_health_defers_session_until_explicit_session_action(self) -> None:
        source = (APP_ROOT / "sections" / "pipeline_health.py").read_text(encoding="utf-8")
        self.assertNotIn("def render():\n    session = get_session()", source)
        self.assertIn("_get_session_for_pipeline_action", source)

    def test_workload_embedded_lenses_use_decoupled_route_state(self) -> None:
        source = (APP_ROOT / "sections" / "workload_operations.py").read_text(encoding="utf-8")
        self.assertIn("def _render_workload_lens_selector", source)
        self.assertIn('widget_key = f"{key}__selector"', source)
        self.assertIn("st.rerun()", source)

    def test_canonical_pipeline_workflow_does_not_force_load_focus(self) -> None:
        import sections.workload_operations as workload

        self.assertNotIn(workload.PIPELINE_TASK_HEALTH_WORKFLOW, workload.PIPELINE_FOCUS_ALIASES)


if __name__ == "__main__":
    unittest.main()
