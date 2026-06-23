"""Account Health: daily checklist, source readiness, and DBA morning brief."""
from __future__ import annotations

import streamlit as st

import sections.account_health_access_hygiene as _access_hygiene_exports
import sections.account_health_access_hygiene_view as _access_hygiene_view_exports
import sections.account_health_action_queue as _action_queue_exports
import sections.account_health_checklist as _checklist_exports
import sections.account_health_common as _common_exports
import sections.account_health_contracts as _contracts_exports
import sections.account_health_data as _data_exports
import sections.account_health_history as _history_exports
import sections.account_health_models as _models_exports
import sections.account_health_morning_view as _morning_view_exports
import sections.account_health_overview_models as _overview_models_exports
import sections.account_health_overview_view as _overview_view_exports
import sections.account_health_source_health_view as _source_health_view_exports
import sections.account_health_sql as _sql_exports
from sections.account_health_access_hygiene import *  # noqa: F403
from sections.account_health_access_hygiene_view import *  # noqa: F403
from sections.account_health_action_queue import *  # noqa: F403
from sections.account_health_checklist import *  # noqa: F403
from sections.account_health_common import *  # noqa: F403
from sections.account_health_contracts import *  # noqa: F403
from sections.account_health_data import *  # noqa: F403
from sections.account_health_history import *  # noqa: F403
from sections.account_health_models import *  # noqa: F403
from sections.account_health_morning_view import *  # noqa: F403
from sections.account_health_overview_models import *  # noqa: F403
from sections.account_health_overview_view import *  # noqa: F403
from sections.account_health_source_health_view import *  # noqa: F403
from sections.account_health_sql import *  # noqa: F403
from sections.base import lazy_util as _lazy_util


get_active_environment = _lazy_util("get_active_environment")
render_mode_selector = _lazy_util("render_mode_selector")


ACCOUNT_HEALTH_RENDERERS = {
    "Overview": render_account_health_overview,
    "Morning Report": render_account_health_morning_report,
}


def render() -> None:
    credit_price = get_credit_price()
    company = st.session_state.get("active_company", "ALFA")
    environment = get_active_environment()
    active_view = render_mode_selector(
        "Account Health view",
        "account_health_active_view",
        ACCOUNT_HEALTH_PANES,
        default=ACCOUNT_HEALTH_PANES[0],
        details=ACCOUNT_HEALTH_PANE_DETAILS,
        labels=ACCOUNT_HEALTH_PANE_LABELS,
        columns=2,
    )
    renderer = ACCOUNT_HEALTH_RENDERERS.get(active_view)
    if renderer is None:
        st.warning("Account Health view is not available. Returning to Overview.")
        renderer = ACCOUNT_HEALTH_RENDERERS["Overview"]
    renderer(company, environment, credit_price)


__all__ = sorted(set(
    ["ACCOUNT_HEALTH_RENDERERS", "render"]
    + _access_hygiene_exports.__all__
    + _access_hygiene_view_exports.__all__
    + _action_queue_exports.__all__
    + _checklist_exports.__all__
    + _common_exports.__all__
    + _contracts_exports.__all__
    + _data_exports.__all__
    + _history_exports.__all__
    + _models_exports.__all__
    + _morning_view_exports.__all__
    + _overview_models_exports.__all__
    + _overview_view_exports.__all__
    + _source_health_view_exports.__all__
    + _sql_exports.__all__
))
