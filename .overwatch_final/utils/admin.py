# utils/admin.py - shared guardrails for live DBA actions
import streamlit as st


ADMIN_ACTIONS_KEY = "admin_actions_enabled"


def admin_actions_enabled() -> bool:
    """Return whether live account-changing controls are enabled."""
    return bool(st.session_state.get(ADMIN_ACTIONS_KEY, False))


def admin_disabled_reason() -> str:
    return "Enable Admin actions in Settings before running live Snowflake changes."


def admin_button_disabled(disabled: bool = False) -> bool:
    """Combine a caller-specific disabled flag with the global admin gate."""
    return bool(disabled) or not admin_actions_enabled()


def require_admin_enabled(action: str = "this action") -> bool:
    """Show a consistent warning and return False when admin actions are locked."""
    if admin_actions_enabled():
        return True
    st.warning(f"Admin actions are locked. Enable Admin actions in Settings to run {action}.")
    return False


def render_admin_mode_control() -> None:
    """Render the global live-action toggle."""
    st.toggle(
        "Enable Admin actions",
        key=ADMIN_ACTIONS_KEY,
        help=(
            "Allows live ALTER, EXECUTE, RESUME, SUSPEND, and CANCEL operations. "
            "Keep off for read-only demos and leadership reviews."
        ),
    )
