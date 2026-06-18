"""Refresh and cache signature helpers for the OVERWATCH shell."""
from __future__ import annotations

import streamlit as st

from config import DEFAULTS
from filters import global_filter_signature
from runtime_state import (
    AI_CREDIT_PRICE,
    AI_CREDIT_PRICE_INPUT,
    CREDIT_PRICE,
    CREDIT_PRICE_INPUT,
    EXCEPTIONS_ONLY_MODE,
    STORAGE_COST_PER_TB,
    get_state,
    set_state,
)


def metric_settings_signature() -> tuple:
    """Return settings that change dollarized metrics and derived telemetry."""
    return (
        float(get_state(CREDIT_PRICE, DEFAULTS["credit_price"])),
        float(get_state(
            AI_CREDIT_PRICE_INPUT,
            get_state(AI_CREDIT_PRICE, DEFAULTS["ai_credit_price"]),
        )),
        float(get_state(STORAGE_COST_PER_TB, DEFAULTS["storage_cost_per_tb"])),
    )


def section_render_signature(section: str, company: str, role: str) -> tuple:
    """Return the state tuple that determines whether the main body is stale."""
    from navigation import normalize_nav_section

    return (
        normalize_nav_section(section),
        str(company),
        str(role or ""),
        bool(get_state(EXCEPTIONS_ONLY_MODE)),
        global_filter_signature(),
        metric_settings_signature(),
    )


def current_credit_price() -> float:
    """Read the latest sidebar credit-rate state before the settings widget renders."""
    if CREDIT_PRICE_INPUT in st.session_state:
        set_state(CREDIT_PRICE, get_state(CREDIT_PRICE_INPUT))
    return float(get_state(CREDIT_PRICE, DEFAULTS["credit_price"]))
