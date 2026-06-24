from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

import perf_trace  # noqa: E402


class PerfTraceContractTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(st.session_state)
        st.session_state.clear()

    def tearDown(self):
        st.session_state.clear()
        st.session_state.update(self.previous)

    def test_trace_is_inert_without_perf_run_context(self):
        with patch.object(perf_trace, "_query_value", return_value=""):
            perf_trace.record_phase("shell:inject_theme", 12.3)

        self.assertEqual(perf_trace.trace_samples(), [])
        self.assertNotIn(perf_trace.PERF_TRACE_KEY, st.session_state)

    def test_query_params_seed_bounded_trace_samples(self):
        def fake_query_value(key: str) -> str:
            return {
                perf_trace.PERF_RUN_QUERY_PARAM: "RUN_TRACE",
                perf_trace.PERF_USER_QUERY_PARAM: "4",
                perf_trace.PERF_ITERATION_QUERY_PARAM: "2",
            }.get(key, "")

        with patch.object(perf_trace, "_query_value", side_effect=fake_query_value):
            for idx in range(perf_trace.MAX_TRACE_SAMPLES + 3):
                perf_trace.record_phase(f"phase:{idx}", idx, active_section="Executive Landing")

        samples = perf_trace.trace_samples()
        self.assertEqual(len(samples), perf_trace.MAX_TRACE_SAMPLES)
        self.assertEqual(samples[0]["phase"], "phase:3")
        self.assertEqual(samples[-1]["run_id"], "RUN_TRACE")
        self.assertEqual(samples[-1]["user"], "4")
        self.assertEqual(samples[-1]["iteration"], "2")
        self.assertEqual(samples[-1]["active_section"], "Executive Landing")
        self.assertIn("runtime", samples[-1])
        self.assertIn("python_version", samples[-1]["runtime"])
        self.assertIn("process_id", samples[-1]["runtime"])
        self.assertIn("thread_name", samples[-1]["runtime"])

    def test_render_trace_marker_is_hidden_and_perf_only(self):
        with patch.object(perf_trace, "_query_value", return_value=""):
            with patch.object(perf_trace.st, "markdown") as markdown:
                perf_trace.render_trace_marker()
        markdown.assert_not_called()

        with patch.object(perf_trace, "_query_value", side_effect=lambda key: "RUN_TRACE" if key == perf_trace.PERF_RUN_QUERY_PARAM else ""):
            perf_trace.record_phase("shell:total_render_app", 10.0)
            with patch.object(perf_trace.st, "markdown") as markdown:
                perf_trace.render_trace_marker()

        html = markdown.call_args.args[0]
        self.assertIn('id="overwatch-perf-trace"', html)
        self.assertIn("display:none", html)
        self.assertIn("shell:total_render_app", html)

    def test_app_entry_import_timing_can_be_recorded_after_the_fact(self):
        with patch.object(perf_trace, "_query_value", side_effect=lambda key: "RUN_TRACE" if key == perf_trace.PERF_RUN_QUERY_PARAM else ""):
            perf_trace.record_phase("app_entry:import_shell", 123.45)
            perf_trace.record_phase("app_entry:pre_render_total", 150.0)

        samples = perf_trace.trace_samples()
        self.assertEqual(samples[0]["phase"], "app_entry:import_shell")
        self.assertEqual(samples[0]["elapsed_ms"], 123.45)
        self.assertEqual(samples[1]["phase"], "app_entry:pre_render_total")
        self.assertEqual(samples[1]["elapsed_ms"], 150.0)

    def test_app_entry_source_records_import_phase_names(self):
        app_source = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        helper_source = (APP_ROOT / "app_entry_timing.py").read_text(encoding="utf-8")
        combined_source = f"{app_source}\n{helper_source}"

        for phase in (
            "app_entry:import_streamlit",
            "app_entry:set_page_config",
            "app_entry:import_shell",
            "app_entry:import_perf_trace",
            "app_entry:pre_render_total",
        ):
            with self.subTest(phase=phase):
                self.assertIn(phase, combined_source)


if __name__ == "__main__":
    unittest.main()
