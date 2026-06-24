# utils/downloads.py - lightweight CSV export and loaded-time helpers
from datetime import datetime
import re

import streamlit as st


@st.cache_data(ttl=600, max_entries=32, show_spinner=False)
def _csv_download_payload(df) -> str:
    """Cache CSV serialization so download buttons do not tax every rerun."""
    return df.to_csv(index=False)


def _download_key(filename: str, label: str, key: str | None = None) -> str:
    raw = str(key or f"{filename}_{label}").strip() or "download"
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_") or "download"
    return f"dl_{normalized[:160]}"


def _show_download_gate(label: str, key: str) -> bool:
    gate_key = f"{key}_open"
    if st.session_state.get(gate_key):
        return True
    if st.button(f"Show {label}", key=f"{key}_show", width="stretch"):
        st.session_state[gate_key] = True
        return True
    return False


def download_text(
    data: str,
    filename: str,
    *,
    label: str = "Download",
    mime: str = "text/plain",
    key: str | None = None,
    gated: bool = True,
) -> bool:
    """Render a stable, optionally gated download button."""

    if data is None:
        return False
    widget_key = _download_key(filename, label, key)
    if gated and not _show_download_gate(label, widget_key):
        return True
    st.download_button(
        label,
        data,
        file_name=filename,
        mime=mime,
        key=widget_key,
    )
    return True


def download_csv(df, filename: str, label: str = "Export CSV", key: str | None = None, gated: bool = True) -> bool:
    if df is not None and not getattr(df, "empty", True):
        return download_text(
            _csv_download_payload(df),
            filename,
            label=label,
            mime="text/csv",
            key=key,
            gated=gated,
        )
    return False


def mark_loaded(key: str):
    st.session_state[f"_ts_{key}"] = datetime.now().strftime("%H:%M:%S")


def show_loaded_time(key: str):
    ts = st.session_state.get(f"_ts_{key}")
    if ts:
        st.caption(f"Last loaded: {ts}")
