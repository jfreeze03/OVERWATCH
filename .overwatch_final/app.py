"""Thin Streamlit entrypoint for OVERWATCH."""
from __future__ import annotations

import time

_APP_STARTED = time.perf_counter()
_ST_STARTED = time.perf_counter()
import streamlit as st
_ST_IMPORTED = time.perf_counter()

_CONFIG_STARTED = time.perf_counter()
st.set_page_config(
    page_title="OVERWATCH - Snowflake DBA Monitor",
    page_icon="O",
    layout="wide",
    initial_sidebar_state="expanded",
)
_CONFIG_DONE = time.perf_counter()
_SHELL_IMPORT_STARTED = time.perf_counter()
from shell import render_app  # noqa: E402
_SHELL_IMPORTED = time.perf_counter()
_TRACE_IMPORT_STARTED = time.perf_counter()
from app_entry_timing import record_app_entry_timings  # noqa: E402
_TRACE_IMPORTED = time.perf_counter()

record_app_entry_timings(
    _APP_STARTED, _ST_STARTED, _ST_IMPORTED, _CONFIG_STARTED, _CONFIG_DONE,
    _SHELL_IMPORT_STARTED, _SHELL_IMPORTED, _TRACE_IMPORT_STARTED, _TRACE_IMPORTED,
)
render_app()
