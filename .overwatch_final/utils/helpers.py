# utils/helpers.py — Pagination, freshness tracking, safe conversions
import pandas as pd
import streamlit as st
from datetime import datetime


def paginate_df(
    df: pd.DataFrame,
    page_size: int = 100,
    key: str = "page",
) -> pd.DataFrame:
    """Render a paginated DataFrame. Returns the current page slice.
    Renders pagination controls inline via st.columns.
    """
    if df is None or df.empty:
        return df

    total_rows = len(df)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)

    if total_pages == 1:
        return df

    if f"_page_{key}" not in st.session_state:
        st.session_state[f"_page_{key}"] = 0

    page = st.session_state[f"_page_{key}"]
    page = max(0, min(page, total_pages - 1))

    c1, c2, c3 = st.columns([1, 3, 1])
    with c1:
        if st.button("◀ Prev", key=f"{key}_prev", disabled=(page == 0)):
            st.session_state[f"_page_{key}"] = page - 1
            st.rerun()
    with c2:
        st.caption(f"Page {page + 1} of {total_pages}  ({total_rows:,} rows total)")
    with c3:
        if st.button("Next ▶", key=f"{key}_next", disabled=(page >= total_pages - 1)):
            st.session_state[f"_page_{key}"] = page + 1
            st.rerun()

    start = page * page_size
    return df.iloc[start: start + page_size]


def safe_float(value, default: float = 0.0) -> float:
    """Convert a value to float safely, returning default on failure."""
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    """Convert a value to int safely."""
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def data_freshness_badge(ts_key: str) -> str:
    """Return an HTML badge showing data freshness for a given section key."""
    ts_str = st.session_state.get(f"_ts_{ts_key}")
    if not ts_str:
        return '<span class="status-badge badge-warning">Not loaded</span>'
    try:
        loaded_at = datetime.strptime(ts_str, '%H:%M:%S').replace(
            year=datetime.now().year,
            month=datetime.now().month,
            day=datetime.now().day,
        )
        age_sec = (datetime.now() - loaded_at).total_seconds()
        if age_sec < 300:
            return f'<span class="status-badge badge-healthy">Fresh ({int(age_sec)}s ago)</span>'
        elif age_sec < 3600:
            return f'<span class="status-badge badge-warning">{int(age_sec/60)}m ago</span>'
        else:
            return f'<span class="status-badge badge-critical">{int(age_sec/3600)}h ago</span>'
    except Exception:
        return f'<span class="status-badge badge-warning">Loaded at {ts_str}</span>'
