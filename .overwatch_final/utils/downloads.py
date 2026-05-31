# utils/downloads.py - lightweight CSV export and loaded-time helpers
from datetime import datetime

import streamlit as st


@st.cache_data(ttl=600, max_entries=32, show_spinner=False)
def _csv_download_payload(df) -> str:
    """Cache CSV serialization so download buttons do not tax every rerun."""
    return df.to_csv(index=False)


def download_csv(df, filename: str, label: str = "📥 Export CSV"):
    if df is not None and not getattr(df, "empty", True):
        st.download_button(
            label, _csv_download_payload(df),
            file_name=filename, mime="text/csv",
            key=f"dl_{filename}_{id(df)}",
        )


def mark_loaded(key: str):
    st.session_state[f"_ts_{key}"] = datetime.now().strftime("%H:%M:%S")


def show_loaded_time(key: str):
    ts = st.session_state.get(f"_ts_{key}")
    if ts:
        st.caption(f"📅 Last loaded: {ts}")
