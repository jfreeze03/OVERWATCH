from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RenderProvenanceReconciliationTests(unittest.TestCase):
    def _commit(self) -> str:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

    def _payloads(self, *, synthetic: bool = False, text_mismatch: bool = False):
        from tools.contracts.render_provenance_reconciliation import ADDITIONAL_SURFACES, PRIMARY_SURFACES

        commit = self._commit()
        surfaces = [*PRIMARY_SURFACES, *ADDITIONAL_SURFACES]
        deterministic_rows = []
        runtime_fragments = []
        browser_rows = []
        provenance_rows = []
        leak_rows = []
        action_rows = []
        for index, (section, workflow) in enumerate(surfaces):
            text = f"{section} {workflow} rendered from runtime"
            deterministic_text = "synthetic placeholder" if synthetic and index == 0 else text
            browser_text = f"{text} mismatch" if text_mismatch and index == 0 else deterministic_text
            source = "synthetic_safe_fallback" if synthetic and index == 0 else "deterministic_streamlit_rendered"
            runtime_fragments.append(
                {
                    "producer": "full_app_runtime_validation",
                    "source": "rendered_app",
                    "provenance_origin": "producer",
                    "commit_sha": commit,
                    "section": section,
                    "workflow": workflow,
                    "runtime_source": "actual_section_render",
                    "render_call_path": f"runtime.sections.{index}.render",
                    "text": text,
                    "action_like_elements": [
                        {"label": "Action A", "stable_key": f"{section}-{workflow}-a", "action_area": "route_action"},
                        {"label": "Action B", "stable_key": f"{section}-{workflow}-b", "action_area": "evidence_action"},
                    ],
                    "raw_sql_included": False,
                }
            )
            deterministic_rows.append(
                {
                    "producer": "deterministic_streamlit_render",
                    "source": source,
                    "provenance_origin": "producer",
                    "commit_sha": commit,
                    "section": section,
                    "workflow": workflow,
                    "runtime_source": "actual_section_render",
                    "render_call_path": f"sections.{index}.render",
                    "first_viewport_text": deterministic_text,
                    "action_like_element_count": 2,
                    "rendered": source != "synthetic_safe_fallback",
                    "passed": source != "synthetic_safe_fallback",
                    "raw_sql_included": False,
                }
            )
            browser_rows.append(
                {
                    "producer": "browser_render_gauntlet",
                    "source": "deterministic_streamlit_rendered",
                    "provenance_origin": "producer",
                    "commit_sha": commit,
                    "section": section,
                    "workflow": workflow,
                    "first_viewport_text": browser_text,
                    "action_like_element_count": 2,
                    "rendered": True,
                    "passed": True,
                    "raw_sql_included": False,
                }
            )
            provenance_rows.append(
                {
                    "artifact": "artifacts/full_app_validation/deterministic_streamlit_render_results.json",
                    "row_index": index,
                    "producer": "deterministic_streamlit_render",
                    "source": "deterministic_streamlit_rendered",
                    "provenance_origin": "producer",
                    "commit_sha": commit,
                    "section": section,
                    "workflow": workflow,
                    "passed": True,
                    "raw_sql_included": False,
                }
            )
            leak_rows.append(
                {
                    "surface": section,
                    "item": "deterministic_render",
                    "finding_count": 0,
                    "passed": True,
                    "raw_sql_included": False,
                }
            )
            action_rows.extend(
                [
                    {
                        "section": section,
                        "workflow": workflow,
                        "stable_key": f"{section}-{workflow}-a",
                        "action_area": "route_action",
                        "clicked": True,
                        "passed": True,
                    },
                    {
                        "section": section,
                        "workflow": workflow,
                        "stable_key": f"{section}-{workflow}-b",
                        "action_area": "evidence_action",
                        "clicked": True,
                        "passed": True,
                    },
                ]
            )
        return {
            "artifacts/full_app_validation/view_results.json": [],
            "artifacts/full_app_validation/rendered_fragments.json": runtime_fragments,
            "artifacts/full_app_validation/deterministic_streamlit_render_results.json": {"rows": deterministic_rows},
            "artifacts/full_app_validation/browser_render_results.json": {"rows": browser_rows},
            "artifacts/full_app_validation/runtime_artifact_provenance_results.json": {"rows": provenance_rows},
            "artifacts/full_app_validation/rendered_ui_leak_scan_results.json": {"rows": leak_rows},
            "artifacts/full_app_validation/action_click_results.json": {"rows": action_rows},
        }

    def test_matching_runtime_deterministic_browser_and_provenance_pass(self):
        from tools.contracts.render_provenance_reconciliation import (
            build_render_provenance_reconciliation,
            evaluate_render_provenance_reconciliation_gate,
        )

        results = build_render_provenance_reconciliation(ROOT, self._payloads())
        gate = evaluate_render_provenance_reconciliation_gate(results)

        self.assertTrue(results["passed"], results)
        self.assertTrue(gate["passed"], gate)
        self.assertEqual(results["failure_count"], 0)

    def test_synthetic_deterministic_render_fails(self):
        from tools.contracts.render_provenance_reconciliation import build_render_provenance_reconciliation

        results = build_render_provenance_reconciliation(ROOT, self._payloads(synthetic=True))

        self.assertFalse(results["passed"])
        self.assertIn("synthetic_deterministic_render", results["failures"][0]["failure_reason"])

    def test_rendered_text_hash_mismatch_fails(self):
        from tools.contracts.render_provenance_reconciliation import build_render_provenance_reconciliation

        results = build_render_provenance_reconciliation(ROOT, self._payloads(text_mismatch=True))

        self.assertFalse(results["passed"])
        self.assertIn("rendered_text_hash_mismatch", results["failures"][0]["failure_reason"])

    def test_deterministic_without_runtime_render_fails(self):
        from tools.contracts.render_provenance_reconciliation import build_render_provenance_reconciliation

        payloads = self._payloads()
        payloads["artifacts/full_app_validation/rendered_fragments.json"] = []
        results = build_render_provenance_reconciliation(ROOT, payloads)

        self.assertFalse(results["passed"])
        self.assertIn("runtime_render_row_missing", results["failures"][0]["failure_reason"])

    def test_rendered_actions_without_click_rows_fail(self):
        from tools.contracts.render_provenance_reconciliation import build_render_provenance_reconciliation

        payloads = self._payloads()
        payloads["artifacts/full_app_validation/action_click_results.json"] = {"rows": []}
        results = build_render_provenance_reconciliation(ROOT, payloads)

        self.assertFalse(results["passed"])
        self.assertIn("visible_action_click_rows_missing", results["failures"][0]["failure_reason"])


if __name__ == "__main__":
    unittest.main()
