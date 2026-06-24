"""App-entry perf tracing helpers kept out of the Streamlit entrypoint."""
from __future__ import annotations

from perf_trace import record_phase


def _ms(started: float, finished: float) -> float:
    return (finished - started) * 1000


def record_app_entry_timings(
    app_started: float,
    streamlit_started: float,
    streamlit_imported: float,
    page_config_started: float,
    page_config_done: float,
    shell_import_started: float,
    shell_imported: float,
    perf_trace_import_started: float,
    perf_trace_imported: float,
) -> None:
    record_phase("app_entry:import_streamlit", _ms(streamlit_started, streamlit_imported))
    record_phase("app_entry:set_page_config", _ms(page_config_started, page_config_done))
    record_phase("app_entry:import_shell", _ms(shell_import_started, shell_imported))
    record_phase("app_entry:import_perf_trace", _ms(perf_trace_import_started, perf_trace_imported))
    record_phase("app_entry:pre_render_total", _ms(app_started, perf_trace_imported))
    record_phase("app_entry_import_done")
