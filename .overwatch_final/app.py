"""Thin Streamlit entrypoint for OVERWATCH.

Production shell responsibilities live in `shell.py`; this file stays small so
Streamlit-in-Snowflake and local wrapper deployments have one stable entrypoint.
"""
from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="OVERWATCH - Snowflake DBA Monitor",
    page_icon="O",
    layout="wide",
    initial_sidebar_state="expanded",
)

from shell import render_app  # noqa: E402
from perf_trace import record_phase  # noqa: E402


record_phase("app_entry_import_done")
render_app()
