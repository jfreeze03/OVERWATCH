"""Streamlit Community Cloud entrypoint for OVERWATCH."""

from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parent
V2_DIR = ROOT / "overwatch_app"
LEGACY_DIR = ROOT / ".overwatch_final"

if V2_DIR.exists():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    runpy.run_module("overwatch_app.app", run_name="__main__")
else:
    if str(LEGACY_DIR) not in sys.path:
        sys.path.insert(0, str(LEGACY_DIR))

    runpy.run_path(str(LEGACY_DIR / "app.py"), run_name="__main__")
