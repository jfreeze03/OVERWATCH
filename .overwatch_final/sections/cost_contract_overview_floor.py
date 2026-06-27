# sections/cost_contract_overview_floor.py - Cost Overview floor orchestration.
from __future__ import annotations

import streamlit as st

from config import DAY_WINDOW_OPTIONS, DEFAULTS, DEFAULT_DAY_WINDOW
from performance import EVIDENCE_CLICK_QUERY_BUDGET, query_budget_context
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.cost_contract_advisor_panels import (
    _render_account_service_cost_lens,
    _render_cost_advisor_board,
    _render_cost_efficiency_rca,
    _render_savings_closure_control,
)
from sections.cost_contract_contracts import (
    _ADVANCED_COST_DETAIL_VISIBLE_KEY,
    _COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY,
    _COST_SPLASH_KEY,
)
from sections.cost_contract_dataframes import _looks_like_frame
from sections.cost_contract_evidence_panels import (
    _render_change_cost_correlation_board,
    _render_cost_spike_root_cause_board,
)
from sections.cost_contract_intelligence import _loaded_cortex_state
from sections.cost_contract_loader import _refresh_cost_detail_state
from sections.cost_contract_monitoring import _render_cost_monitoring_mart_and_incident_timeline
from sections.cost_contract_overview_panels import (
    _render_cost_period_explanation,
    _render_cost_run_rate_lens,
    _render_metric_items,
)
from sections.cost_contract_panels import (
    _render_cost_allocation_trust_board,
    _render_cost_control_coverage_board,
    _render_cost_decomposition_board,
    _render_cost_drilldown_command_map,
    _render_cost_source_health,
    _render_query_attribution_gap,
)
from sections.cost_contract_splash import (
    _cost_splash_summary,
)
from sections.cost_contract_evidence import load_cost_evidence
from sections.cortex_signals import build_cortex_signal, render_cortex_signal_panel
from sections.decision_workspace_target_filters import get_decision_evidence_target
from sections.operator_case import make_case_evidence, render_add_to_case_button
from sections.shell_helpers import (
    _clean_display_text,
    build_first_paint_summary_spec,
    render_decision_evidence_panel,
    render_data_freshness,
    render_escaped_bold_text,
    render_section_first_paint_shell,
)
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note


pd = lazy_pandas()

credits_to_dollars = _lazy_util("credits_to_dollars")
get_active_environment = _lazy_util("get_active_environment")
get_session_for_action = _lazy_util("get_session_for_action")


def _render_cost_first_paint_shell(company: str, days: int, splash: dict, credit_price: float) -> None:
    loaded = bool(splash.get("loaded"))
    environment = str(get_active_environment() or DEFAULTS.get("default_environment") or "ALL")
    cost_summary = _cost_splash_summary(splash, credit_price, days)
    render_section_first_paint_shell(build_first_paint_summary_spec(
        section="Cost & Contract",
        state="Loaded context" if loaded else "Ready",
        headline="Cost Overview starts with spend triage, then loads proof on request.",
        detail="Use Refresh Cost for the current cost story; forecasts, reconciliation, and driver rows stay behind explicit actions.",
        metrics=(
            ("Window", f"{int(days)} days"),
            ("Spend story", "Loaded" if loaded else "Summary unavailable"),
            ("Top driver", "Loaded" if loaded else "On demand"),
            ("Forecast/chart", "Loaded" if loaded else "On demand"),
        ),
        snapshot=(
            ("Scope", f"{company} / {environment}"),
            ("Decision path", "Spend movement -> top driver -> savings queue"),
        ),
    ))
    render_cortex_signal_panel(
        build_cortex_signal(
            cost_summary,
            days=int(days),
            total_spend_usd=cost_summary.get("spend"),
        ),
        title="Cortex AI cost lane",
        cta_label="Open Cortex Cost Drivers",
        cta_key="cost_contract_next_move_cortex_cost_drivers",
    )


def _render_cost_watch_floor(company: str, credit_price: float) -> None:
    selected_days = safe_int(
        st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW),
        DEFAULT_DAY_WINDOW,
    )
    if selected_days not in DAY_WINDOW_OPTIONS:
        selected_days = DEFAULT_DAY_WINDOW
    days = selected_days
    refresh_cost = bool(st.session_state.pop("cost_contract_command_brief_load_evidence", False))
    advanced_requested = bool(st.session_state.get(_ADVANCED_COST_DETAIL_VISIBLE_KEY))

    if not refresh_cost and not advanced_requested and not st.session_state.get("cost_contract_evidence_result"):
        return

    controls = st.columns([1.0, 3.6])
    with controls[0]:
        days = st.selectbox(
            "Cost window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(selected_days),
            format_func=lambda d: f"{d} days",
            key="cost_contract_cockpit_window",
        )

    if refresh_cost:
        st.session_state.pop(_COST_SPLASH_KEY, None)
        st.session_state.pop(_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY, None)
        target = get_decision_evidence_target("Cost & Contract")
        with query_budget_context(
            "evidence_click",
            section="Cost & Contract",
            workflow="Cost Overview",
            budget=EVIDENCE_CLICK_QUERY_BUDGET,
        ):
            evidence = load_cost_evidence(
                company,
                str(get_active_environment() or DEFAULTS.get("default_environment") or "ALL"),
                int(days),
                target,
            )
        st.session_state["cost_contract_evidence_result"] = evidence

    evidence = st.session_state.get("cost_contract_evidence_result")
    if isinstance(evidence, dict):
        target_label = str(evidence.get("target_label") or "")
        target_copy = f" for {target_label}" if target_label else ""
        source_note = str(evidence.get("source") or "Cost evidence")
        environment_scope_note = str(evidence.get("environment_scope_note") or "").strip()
        if environment_scope_note:
            source_note = f"{source_note} - {environment_scope_note}"
        render_decision_evidence_panel(
            f"Cost Evidence{target_copy}",
            source_note,
            str(evidence.get("summary") or "Cost evidence loaded."),
            tuple(evidence.get("metrics") or (("Rows", str(evidence.get("row_count", 0))),)),
            rows=evidence.get("rows"),
            source_note=source_note,
        )
        if evidence.get("error"):
            st.warning(f"Cost evidence unavailable: {evidence.get('error')}")
        if not advanced_requested:
            if st.button("Open Advanced Cost Details", key="cost_contract_open_advanced_details", width="stretch"):
                st.session_state[_ADVANCED_COST_DETAIL_VISIBLE_KEY] = True
                st.rerun()
            return

    proof_data = st.session_state.get("cost_contract_cockpit")
    proof_meta = st.session_state.get("cost_contract_cockpit_meta", {})
    proof_current = (
        _looks_like_frame(proof_data)
        and not proof_data.empty
        and proof_meta.get("company") == company
        and proof_meta.get("days") == int(days)
    )
    render_data_freshness(
        proof_meta if proof_current else {},
        source=st.session_state.get("cost_contract_cockpit_source", "Cost detail workspace"),
        target_minutes=60,
        delayed_note="Cost detail uses fast summaries first; full account-history refresh is explicit.",
    )

    if advanced_requested and not proof_current:
        session = get_session_for_action(
            "load the Cost Control Cockpit",
            surface="Cost & Contract",
            offline_note="Cost workflow navigation remains available without a live Snowflake connection.",
        )
        if session is None:
            return
        _refresh_cost_detail_state(st.session_state, session, company, int(days), credit_price)
    defer_section_note(
        "Cost detail telemetry is optional; refresh only when you need account-history rows behind the fast cost summary."
    )

    data = st.session_state.get("cost_contract_cockpit")
    meta = st.session_state.get("cost_contract_cockpit_meta", {})
    err = st.session_state.get("cost_contract_cockpit_error", "")
    if err:
        st.warning(f"Cost cockpit unavailable: {err}")
    loaded_days = meta.get("days")
    data_is_frame = _looks_like_frame(data)
    if (
        data_is_frame
        and not data.empty
        and meta.get("company") == company
        and loaded_days is not None
        and int(loaded_days) != int(days)
    ):
        st.info(
            f"Loaded cockpit data is for {int(loaded_days)} days; selected window is {int(days)} days. "
            "Refresh cost details before acting on detailed telemetry."
        )
    if (
        not data_is_frame
        or data.empty
        or meta.get("company") != company
        or meta.get("days") != int(days)
    ):
        defer_section_note("Specialist cost pages load their own detailed data after the cockpit first move.")
        return

    defer_source_note(st.session_state.get("cost_contract_cockpit_source", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"))
    if not st.session_state.get(_ADVANCED_COST_DETAIL_VISIBLE_KEY):
        st.caption("Advanced cost detail boards are hidden by default. Open them only when you need reconciliation, source health, or proof detail.")
        if st.button("View Advanced Cost Details", key="cost_contract_view_advanced_details", width="stretch"):
            st.session_state[_ADVANCED_COST_DETAIL_VISIBLE_KEY] = True
            st.rerun()
        return

    row = data.iloc[0]
    queue = st.session_state.get("cost_contract_queue", pd.DataFrame())
    queue_err = st.session_state.get("cost_contract_queue_error", "")
    if queue_err:
        st.caption(f"Action queue unavailable for this role/context: {queue_err}")
    open_actions = high_actions = 0
    total_savings = 0.0
    if isinstance(queue, pd.DataFrame) and not queue.empty and "STATUS" in queue.columns:
        open_mask = ~queue["STATUS"].isin(["Fixed", "Ignored"])
        open_actions = int(open_mask.sum())
        high_actions = int((queue.get("SEVERITY", pd.Series(dtype=str)).isin(["Critical", "High"]) & open_mask).sum())
        if "EST_MONTHLY_SAVINGS" in queue.columns:
            total_savings = safe_float(pd.to_numeric(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"], errors="coerce").fillna(0).sum())
    current_credits = safe_float(row.get("CURRENT_CREDITS", 0))
    prior_credits = safe_float(row.get("PRIOR_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    top_wh = str(row.get("TOP_INCREASE_WAREHOUSE") or "No increase")
    top_delta = safe_float(row.get("TOP_INCREASE_CREDITS", 0))
    top_delta_usd = credits_to_dollars(top_delta, credit_price)
    top_delta_usd_label = f"{'+' if top_delta_usd >= 0 else '-'}${abs(top_delta_usd):,.0f}"
    render_add_to_case_button(
        make_case_evidence(
            section="Cost & Contract",
            workflow="Cost Overview",
            scope=f"{company} / {int(days)} days",
            freshness=str(proof_meta.get("loaded_at") or "Loaded cost cockpit"),
            source=str(st.session_state.get("cost_contract_cockpit_source") or "Cost detail workspace"),
            summary=(
                f"{current_credits:,.2f} current credits vs {prior_credits:,.2f} prior "
                f"({delta_pct:+.1f}%); top increase {top_wh} at {top_delta:,.2f} credits."
            ),
            next_action="Review the top warehouse driver and open advanced cost details only if reconciliation is needed.",
            evidence_rows_preview=data,
        ),
        key="cost_contract_add_to_case",
    )
    cortex_projected, cortex_exception_count = _loaded_cortex_state()
    secondary_metrics = []
    if total_savings > 0:
        secondary_metrics.append({"label": "Savings Queue", "value": f"${total_savings:,.0f}/mo"})
    if cortex_projected > 0 or cortex_exception_count > 0:
        secondary_metrics.append({
            "label": "Cortex Projection",
            "value": f"${cortex_projected:,.0f}/30d",
            "delta": f"{cortex_exception_count:,} exceptions",
            "delta_color": "inverse",
        })
    if secondary_metrics:
        with st.expander("Secondary cockpit metrics", expanded=False):
            _render_metric_items(secondary_metrics)
            if open_actions or high_actions:
                st.caption(f"{open_actions:,} open cost action(s), {high_actions:,} high priority.")
            st.caption(f"Top warehouse increase: {top_wh} ({top_delta:+,.2f} credits / {top_delta_usd_label}).")

    run_rate_source = st.session_state.get("cost_contract_run_rate_source", "")
    if run_rate_source:
        defer_source_note(run_rate_source)
    _render_cost_run_rate_lens(
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_run_rate_error", ""),
    )
    _render_cost_period_explanation(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        credit_price,
    )
    _render_cost_source_health(
        cockpit=data,
        run_rate=st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue=queue,
        attribution=st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        service_lens=st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
    )
    _render_query_attribution_gap(
        st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_attribution_error", ""),
    )
    _render_account_service_cost_lens(
        st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_service_lens_error", ""),
    )
    _render_cost_advisor_board(
        efficiency_summary=st.session_state.get("cost_contract_efficiency_summary", pd.DataFrame()),
        warehouse_efficiency=st.session_state.get("cost_contract_warehouse_efficiency", pd.DataFrame()),
        clustering_cost=st.session_state.get("cost_contract_clustering_cost", pd.DataFrame()),
        reconciliation=st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        service_lens=st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
        credit_price=credit_price,
        days=int(days),
        storage_table_metrics=st.session_state.get("stor_df_table_metrics", pd.DataFrame()),
        storage_db_detail=st.session_state.get("stor_df_db_detail", pd.DataFrame()),
        storage_cost_per_tb=st.session_state.get("storage_cost_per_tb", DEFAULTS.get("storage_cost_per_tb", 23.0)),
    )
    _render_cost_efficiency_rca(
        st.session_state.get("cost_contract_efficiency_summary", pd.DataFrame()),
        st.session_state.get("cost_contract_warehouse_efficiency", pd.DataFrame()),
        st.session_state.get("cost_contract_clustering_cost", pd.DataFrame()),
        credit_price,
        errors={
            "Efficiency summary": st.session_state.get("cost_contract_efficiency_summary_error", ""),
            "Warehouse efficiency": st.session_state.get("cost_contract_warehouse_efficiency_error", ""),
            "Clustering cost": st.session_state.get("cost_contract_clustering_cost_error", ""),
        },
    )
    _render_cost_spike_root_cause_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        credit_price,
    )
    _render_change_cost_correlation_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
    )
    _render_cost_monitoring_mart_and_incident_timeline(
        company=company,
        cockpit=data,
        run_rate=st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue=queue,
    )
    _render_savings_closure_control(queue, credit_price)
    _render_cost_control_coverage_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_allocation_trust_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_drilldown_command_map(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_decomposition_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )

    moves = []
    if delta_pct >= 20 or safe_float(row.get("TOP_INCREASE_CREDITS", 0)) > 0:
        moves.append((
            "Explain the usage movement",
            f"Top increase: {row.get('TOP_INCREASE_WAREHOUSE', 'unknown')} "
            f"({safe_float(row.get('TOP_INCREASE_CREDITS', 0)):,.2f} credits).",
            "Cost Explorer",
        ))
    if high_actions > 0 or total_savings > 0:
        moves.append((
            "Work the action queue",
            f"{high_actions:,} high-priority action(s), ${total_savings:,.0f}/month potential savings.",
            "Cost Recommendations",
        ))
    if cortex_exception_count > 0 or cortex_projected > 0:
        moves.append((
            "Inspect AI / Cortex spend",
            f"Projected Cortex spend ${cortex_projected:,.0f}/30d with {cortex_exception_count:,} exception(s).",
            "Cortex AI",
        ))
    if not moves:
        moves.append((
            "Review attribution and queue",
            "No dominant cost incident in this cockpit window. Review attribution or open recommendations.",
            "Cost Recommendations",
        ))

    st.markdown("**Next Cost Moves**")
    cols = st.columns(min(len(moves), 3))
    for idx, (title, evidence, workflow) in enumerate(moves[:3]):
        with cols[idx]:
            render_escaped_bold_text(title)
            st.caption(_clean_display_text(evidence))
            if st.button(f"Open {workflow}", key=f"cost_contract_next_{idx}_{workflow}", width="stretch"):
                st.session_state["cost_contract_workflow"] = workflow
                if workflow == "Cost Explorer":
                    st.session_state["cost_center_view"] = "Cost Explorer"
                    st.session_state["cc_explorer_lens"] = "Warehouse"
                st.rerun()
