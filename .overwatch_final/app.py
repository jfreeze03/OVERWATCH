"""Thin lazy Streamlit entrypoint for OVERWATCH."""
from __future__ import annotations

import time

_APP_STARTED = time.perf_counter()


def main() -> None:
    st_started = time.perf_counter()
    import streamlit as st
    st_imported = config_started = time.perf_counter()
    st.set_page_config(page_title="OVERWATCH - Snowflake DBA Monitor", page_icon="O", layout="wide",
                       initial_sidebar_state="expanded")
    config_done = time.perf_counter()
    shell_import_started = time.perf_counter()
    from shell import render_app
    shell_imported = time.perf_counter()
    trace_import_started = time.perf_counter()
    from app_entry_timing import record_app_entry_timings
    trace_imported = time.perf_counter()
    record_app_entry_timings(_APP_STARTED, st_started, st_imported, config_started, config_done,
                             shell_import_started, shell_imported, trace_import_started, trace_imported)
    render_app()


if __name__ == "__main__":
    main()
