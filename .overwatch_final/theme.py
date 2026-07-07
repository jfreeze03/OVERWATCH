# theme.py - OVERWATCH production theme system.
#
# CSS lives in theme_assets/ so the Python module stays maintainable while
# preserving the same injected selectors and Streamlit override behavior.
from pathlib import Path

import streamlit as st

THEME_VERSION = "2026-07-05-command-center-v3"

_DEFAULT_THEME = "carbon"
_ACTIVE_THEME_KEY = "_overwatch_active_theme"
_THEME_QUERY_PARAM = "overwatch_theme"
_THEME_ALIASES = {
    "aurora": "carbon",
    "black_ice": "carbon",
    "midnight": "carbon",
    "corporate": "carbon",
    "henson": "carbon",
}

THEMES = {
    "carbon": {
        "label": "Snowflake Dark",
        "swatch": "#29B5E8",
        "bg": "#0B1117",
    },
}

_THEME_ASSET_DIR = Path(__file__).with_name("theme_assets")


def _read_theme_asset(filename: str) -> str:
    return (_THEME_ASSET_DIR / filename).read_text(encoding="utf-8")


_VARS = {
    "carbon": _read_theme_asset("carbon.vars.css"),
}

_STRUCTURAL_CSS = _read_theme_asset("structural.css")
_COMMAND_CENTER_CSS = _read_theme_asset("command_center.css")
_STREAMLIT_ICON_FIX = _read_theme_asset("streamlit_icon_fix.css")
_THEME_EXTRAS = {
    "carbon": _read_theme_asset("carbon.extra.css"),
}

def _normalize_theme_key(theme_key: str | None) -> str:
    theme_key = str(theme_key or _DEFAULT_THEME)
    theme_key = _THEME_ALIASES.get(theme_key, theme_key)
    return theme_key if theme_key in THEMES else _DEFAULT_THEME


def _query_param_theme() -> str | None:
    try:
        query_params = st.query_params
        raw_theme = query_params.get(_THEME_QUERY_PARAM)
    except Exception:
        try:
            query_params = st.experimental_get_query_params()
            raw_theme = query_params.get(_THEME_QUERY_PARAM)
        except Exception:
            return None
    if isinstance(raw_theme, list):
        raw_theme = raw_theme[-1] if raw_theme else None
    if not raw_theme:
        return None
    return _normalize_theme_key(str(raw_theme))


def _set_query_param_theme(theme_key: str) -> None:
    theme_key = _normalize_theme_key(theme_key)
    try:
        st.query_params[_THEME_QUERY_PARAM] = theme_key
    except Exception:
        try:
            query_params = st.experimental_get_query_params()
            query_params[_THEME_QUERY_PARAM] = theme_key
            st.experimental_set_query_params(**query_params)
        except Exception:
            pass


def _get_theme() -> str:
    query_theme = _query_param_theme()
    persistent_theme = st.session_state.get(_ACTIVE_THEME_KEY)
    existing_theme = st.session_state.get("active_theme")
    theme_key = _normalize_theme_key(query_theme or persistent_theme or existing_theme or _DEFAULT_THEME)
    if st.session_state.get("_active_theme_version") != THEME_VERSION:
        st.session_state["_active_theme_version"] = THEME_VERSION
    if st.session_state.get("active_theme") != theme_key:
        st.session_state["active_theme"] = theme_key
    if st.session_state.get(_ACTIVE_THEME_KEY) != theme_key:
        st.session_state[_ACTIVE_THEME_KEY] = theme_key
    return theme_key


_COMBINED_CSS_CACHE: dict[str, str] = {}


def _combined_theme_css(theme_key: str) -> str:
    cached = _COMBINED_CSS_CACHE.get(theme_key)
    if cached:
        return cached
    vars_block = _VARS.get(theme_key, _VARS[_DEFAULT_THEME])
    combined = (
        _STRUCTURAL_CSS.replace("{vars}", vars_block)
        + _COMMAND_CENTER_CSS
        + _STREAMLIT_ICON_FIX
        + _THEME_EXTRAS.get(theme_key, "")
    )
    _COMBINED_CSS_CACHE[theme_key] = combined
    return combined


def inject_theme() -> None:
    """
    Inject CSS variables + structural styles for the current theme.
    Call once at the top of app.py before any other st.* calls.
    Also applies theme-specific body class for extra overrides.
    """
    theme_key = _get_theme()
    st.markdown(_combined_theme_css(theme_key), unsafe_allow_html=True)
