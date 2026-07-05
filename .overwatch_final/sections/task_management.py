# sections/task_management.py - Task Management compatibility facade/route
import html

import streamlit as st

from sections.task_management_action_queue import *
from sections.task_management_action_queue import __all__ as _action_queue_all
from sections.task_management_common import *
from sections.task_management_common import __all__ as _common_all
from sections.task_management_contracts import *
from sections.task_management_contracts import __all__ as _contracts_all
from sections.task_management_control_view import *
from sections.task_management_control_view import __all__ as _control_view_all
from sections.task_management_etl_audit_view import *
from sections.task_management_etl_audit_view import __all__ as _etl_audit_view_all
from sections.task_management_execute_view import *
from sections.task_management_execute_view import __all__ as _execute_view_all
from sections.task_management_failure_console_view import *
from sections.task_management_failure_console_view import __all__ as _failure_console_view_all
from sections.task_management_history_view import *
from sections.task_management_history_view import __all__ as _history_view_all
from sections.task_management_job_status_view import *
from sections.task_management_job_status_view import __all__ as _job_status_view_all
from sections.task_management_models import *
from sections.task_management_models import __all__ as _models_all
from sections.task_management_sla_cost_view import *
from sections.task_management_sla_cost_view import __all__ as _sla_cost_view_all
from sections.task_management_sql import *
from sections.task_management_sql import __all__ as _sql_all
from utils import get_session_for_action
from utils.workflows import render_workflow_selector


TASK_MANAGEMENT_RENDERERS = {
    "Job Status Brief": render_task_job_status_brief,
    "Failure Console": render_task_failure_console,
    "SLA & Cost Drift": render_task_sla_cost_drift,
    "Task History": render_task_history,
    "ETL Audit": render_task_etl_audit,
    "Control Center": render_task_control_center,
    "Execute Task": render_task_execute_task,
}


def _render_task_management_active_marker(task_view: str) -> None:
    """Expose active task-management subsection for browser/runtime checks."""
    safe_view = html.escape(str(task_view or "Job Status Brief"), quote=True)
    st.html(
        '<div class="ow-workflow-selector ow-task-management-selector" '
        f'data-active="{safe_view}" data-active-label="{safe_view}">'
        '<span class="ow-sr-only">Task management workflow</span>'
        '</div>'
    )


def render():
    task_view = render_workflow_selector(
        "Task management workflow",
        "task_management_view",
        TASK_CONTROL_VIEWS,
        TASK_CONTROL_DETAILS,
        columns=3,
    )
    _render_task_management_active_marker(task_view)
    session = get_session_for_action(
        "load task management evidence",
        surface="Task Management",
        offline_note="Task workflow controls remain available; data loads after the connection is available.",
    )
    if session is None:
        return

    if st.session_state.get("exceptions_only_mode"):
        render_task_job_status_brief(session)
        st.stop()

    TASK_MANAGEMENT_RENDERERS.get(task_view, render_task_job_status_brief)(session)


__all__ = sorted(set(
    list(_contracts_all)
    + list(_common_all)
    + list(_models_all)
    + list(_sql_all)
    + list(_action_queue_all)
    + list(_job_status_view_all)
    + list(_failure_console_view_all)
    + list(_sla_cost_view_all)
    + list(_history_view_all)
    + list(_etl_audit_view_all)
    + list(_control_view_all)
    + list(_execute_view_all)
    + ["TASK_MANAGEMENT_RENDERERS", "_render_task_management_active_marker", "render"]
))
