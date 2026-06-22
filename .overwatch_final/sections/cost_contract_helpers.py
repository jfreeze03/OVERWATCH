"""Non-render Cost & Contract helpers.

The helpers here may read Streamlit session state for operator-configured
prices, but they do not render UI or own workflow routing.
"""

from __future__ import annotations

import streamlit as st

from config import DEFAULTS
from sections.base import lazy_util as _lazy_util
from utils.primitives import safe_float


get_ai_credit_price = _lazy_util("get_ai_credit_price")


def get_credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def get_current_ai_credit_price() -> float:
    try:
        return safe_float(get_ai_credit_price(), 2.20)
    except Exception:
        return safe_float(st.session_state.get("ai_credit_price", DEFAULTS.get("ai_credit_price", 2.20)), 2.20)
