"""Shared section infrastructure for OVERWATCH workspace modules."""

from __future__ import annotations

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, ENVIRONMENT_CONFIG
from utils.primitives import safe_float


class LazyPandas:
    """Proxy that imports pandas only when dataframe work is actually needed."""

    _module = None

    def _load(self):
        if self._module is None:
            import pandas as pandas_module

            self._module = pandas_module
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


def lazy_pandas() -> LazyPandas:
    """Return a lazy pandas proxy for section-level ``pd`` assignments."""
    return LazyPandas()


def lazy_util(name: str):
    """Create a lazy reference to a function exported from ``utils``."""
    def _call(*args, **kwargs):
        import utils as _utils

        return getattr(_utils, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


def lazy_util_attr(name: str):
    """Create a lazy reference to a non-callable value exported from ``utils``."""
    def _get():
        import utils as _utils

        return getattr(_utils, name)

    _get.__name__ = name
    return _get


def get_active_company() -> str:
    """Return the active company filter from session state."""
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    """Return the active environment filter from session state."""
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def get_credit_price() -> float:
    """Return the current compute credit price."""
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def get_ai_credit_price() -> float:
    """Return the current Cortex/AI credit price."""
    return safe_float(st.session_state.get("ai_credit_price", DEFAULTS.get("ai_credit_price", 2.20)), 2.20)
