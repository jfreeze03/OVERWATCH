"""Central v2 query facade."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pandas as pd


def _legacy_app_root() -> Path:
    return Path(__file__).resolve().parents[2] / ".overwatch_final"


def run_query(sql: str, **kwargs: Any) -> pd.DataFrame:
    """Run SQL through the existing guarded query runner when available."""
    app_root = _legacy_app_root()
    if app_root.exists() and str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    try:
        from utils import run_query as legacy_run_query  # type: ignore
    except Exception:
        return pd.DataFrame()
    try:
        return legacy_run_query(sql, **kwargs)
    except Exception:
        return pd.DataFrame()


def execute_sql(session: Any, sql: str) -> bool:
    """Execute a write safely for helpers that receive a Snowpark-like session."""
    if session is None or not callable(getattr(session, "sql", None)):
        return False
    session.sql(sql).collect()
    return True
