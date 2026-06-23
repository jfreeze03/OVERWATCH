"""Cost Center: compatibility facade and renderer dispatch shell."""
from __future__ import annotations

import streamlit as st

import sections.cost_center_action_queue as _action_queue_exports
import sections.cost_center_attribution_view as _attribution_view_exports
import sections.cost_center_burn_view as _burn_view_exports
import sections.cost_center_chargeback_view as _chargeback_view_exports
import sections.cost_center_contracts as _contracts_exports
import sections.cost_center_explain_view as _explain_view_exports
import sections.cost_center_explorer_view as _explorer_view_exports
import sections.cost_center_forecast_view as _forecast_view_exports
import sections.cost_center_models as _models_exports
import sections.cost_center_reconciliation_view as _reconciliation_view_exports
import sections.cost_center_sql as _sql_exports
import sections.cost_center_user_leaderboard_view as _user_leaderboard_view_exports
from sections.cost_center_action_queue import *  # noqa: F403
from sections.cost_center_attribution_view import *  # noqa: F403
from sections.cost_center_burn_view import *  # noqa: F403
from sections.cost_center_chargeback_view import *  # noqa: F403
from sections.cost_center_contracts import *  # noqa: F403
from sections.cost_center_explain_view import *  # noqa: F403
from sections.cost_center_explorer_view import *  # noqa: F403
from sections.cost_center_forecast_view import *  # noqa: F403
from sections.cost_center_models import *  # noqa: F403
from sections.cost_center_reconciliation_view import *  # noqa: F403
from sections.cost_center_sql import *  # noqa: F403
from sections.cost_center_user_leaderboard_view import *  # noqa: F403
from utils import defer_source_note, get_credit_price, get_session
from utils.workflows import render_workflow_selector


COST_CENTER_RENDERERS = {
    "Cost Explorer": render_cost_explorer,
    "Explain This Bill": render_explain_this_bill,
    "User Leaderboard": render_user_leaderboard,
    "Burn Rate": render_burn_rate,
    "Reconciliation": render_cost_reconciliation,
    "Forecast": render_cost_forecast,
    "Attribution": render_cost_attribution,
    "Chargeback": render_chargeback,
}


def render() -> None:
    session = get_session()
    credit_price = get_credit_price()
    company = st.session_state.get("active_company", "ALFA")
    max_wh_size_expr, bytes_scanned_sum_expr, query_tag_dimension_expr = _cost_center_query_history_expressions(session)

    cost_view = render_workflow_selector(
        "Cost allocation workflow",
        "cost_center_view",
        COST_CENTER_VIEWS,
        COST_CENTER_VIEW_DETAILS,
        columns=3,
        labels=COST_CENTER_VIEW_LABELS,
    )
    defer_source_note(
        "Progressive load is enabled: each cost view runs only when its Load or Calculate button is selected."
    )

    renderer = COST_CENTER_RENDERERS.get(cost_view)
    if renderer is None:
        st.warning("Cost Center view is not available. Returning to Cost Explorer.")
        renderer = COST_CENTER_RENDERERS["Cost Explorer"]
    renderer(
        session,
        company,
        credit_price,
        max_wh_size_expr,
        bytes_scanned_sum_expr,
        query_tag_dimension_expr,
    )


__all__ = sorted(set(
    ["COST_CENTER_RENDERERS", "render"]
    + _action_queue_exports.__all__
    + _attribution_view_exports.__all__
    + _burn_view_exports.__all__
    + _chargeback_view_exports.__all__
    + _contracts_exports.__all__
    + _explain_view_exports.__all__
    + _explorer_view_exports.__all__
    + _forecast_view_exports.__all__
    + _models_exports.__all__
    + _reconciliation_view_exports.__all__
    + _sql_exports.__all__
    + _user_leaderboard_view_exports.__all__
))
