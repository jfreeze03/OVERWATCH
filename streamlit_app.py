"""Streamlit Community Cloud entrypoint for OVERWATCH.

The Snowflake Streamlit-in-Snowflake runtime uses `.overwatch_final/app.py`
directly. Community Cloud should use this wrapper from the repository root so
it installs dependencies from the root `requirements.txt` instead of the
Snowflake-specific `.overwatch_final/environment.yml`.
"""

from pathlib import Path
import runpy
import sys


APP_DIR = Path(__file__).resolve().parent / ".overwatch_final"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

runpy.run_path(str(APP_DIR / "app.py"), run_name="__main__")
