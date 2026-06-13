# utils/helpers.py - Pagination, freshness tracking, safe conversions
import pandas as pd
import streamlit as st

from .primitives import safe_float, safe_int


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
        if st.button("< Prev", key=f"{key}_prev", disabled=(page == 0)):
            st.session_state[f"_page_{key}"] = page - 1
            st.rerun()
    with c2:
        st.caption(f"Page {page + 1} of {total_pages}  ({total_rows:,} rows total)")
    with c3:
        if st.button("Next >", key=f"{key}_next", disabled=(page >= total_pages - 1)):
            st.session_state[f"_page_{key}"] = page + 1
            st.rerun()

    start = page * page_size
    return df.iloc[start: start + page_size]
