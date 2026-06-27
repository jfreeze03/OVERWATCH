# sections/task_management.py - Task Management compatibility facade/route
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
from utils import get_session
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


def render():
    # SESSION_OPEN_ADMIN_OK boundary=admin reason=legacy_session budget=advanced_diagnostics owner=platform
    session = get_session()

    if st.session_state.get("exceptions_only_mode"):
        render_task_job_status_brief(session)
        st.stop()

    task_view = render_workflow_selector(
        "Task management workflow",
        "task_management_view",
        TASK_CONTROL_VIEWS,
        TASK_CONTROL_DETAILS,
        columns=3,
    )
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
    + ["TASK_MANAGEMENT_RENDERERS", "render"]
))
