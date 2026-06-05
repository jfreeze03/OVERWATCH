# sections/executive_landing.py - executive landing page
from __future__ import annotations

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT, DEFAULTS, DAY_WINDOW_OPTIONS
import utils as _utils
from utils.section_guidance import defer_source_note


class _LazyPandas:
    """Load pandas only after an executive snapshot has been requested."""

    _module = None

    def _load(self):
        if self._module is None:
            import pandas as pandas_module

            self._module = pandas_module
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


pd = _LazyPandas()


def _lazy_util(name: str):
    def _call(*args, **kwargs):
        return getattr(_utils, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_schema_migration_status_sql = _lazy_util("build_schema_migration_status_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
load_action_queue = _lazy_util("load_action_queue")
load_alert_history = _lazy_util("load_alert_history")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
run_query = _lazy_util("run_query")


EXECUTIVE_LANDING_VERSION = "2026-06-05-powerpoint-brief"


def _altair():
    """Load Altair only when the slide chart pack is shown."""
    import altair as alt

    return alt


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def _credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def _load_alerts(session, company: str, environment: str, days: int) -> pd.DataFrame:
    return load_alert_history(
        session,
        company=company,
        environment=environment,
        days=int(days),
        limit=100,
        section="Executive Landing",
    )


def _open_action_mask(queue: pd.DataFrame) -> pd.Series:
    if queue is None or queue.empty or "STATUS" not in queue.columns:
        return pd.Series(dtype=bool)
    return ~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored", "Closed"])


def _snapshot_state(cost: pd.DataFrame, alerts: pd.DataFrame, queue: pd.DataFrame, migration: pd.DataFrame) -> dict:
    cost_row = cost.iloc[0] if isinstance(cost, pd.DataFrame) and not cost.empty else pd.Series(dtype=object)
    current_credits = safe_float(cost_row.get("CURRENT_CREDITS"))
    prior_credits = safe_float(cost_row.get("PRIOR_CREDITS"))
    cost_delta = current_credits - prior_credits
    open_alerts = alerts if isinstance(alerts, pd.DataFrame) and not alerts.empty else pd.DataFrame()
    if not open_alerts.empty and "STATUS" in open_alerts.columns:
        open_alerts = open_alerts[~open_alerts["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored", "Closed"])]
    critical_high_alerts = (
        int(open_alerts["SEVERITY"].fillna("").astype(str).str.title().isin(["Critical", "High"]).sum())
        if not open_alerts.empty and "SEVERITY" in open_alerts.columns
        else 0
    )
    action_mask = _open_action_mask(queue)
    high_actions = (
        int(queue.loc[action_mask, "SEVERITY"].fillna("").astype(str).str.title().isin(["Critical", "High"]).sum())
        if isinstance(queue, pd.DataFrame) and not queue.empty and "SEVERITY" in queue.columns and len(action_mask)
        else 0
    )
    migration_blockers = (
        int(migration["MIGRATION_STATE"].fillna("").astype(str).isin(["Blocked", "Version Drift"]).sum())
        if isinstance(migration, pd.DataFrame) and not migration.empty and "MIGRATION_STATE" in migration.columns
        else 0
    )
    score = 100
    score -= min(max(cost_delta, 0) / max(prior_credits, 1) * 25, 25) if prior_credits else 0
    score -= min(critical_high_alerts * 6, 24)
    score -= min(high_actions * 5, 20)
    score -= min(migration_blockers * 10, 20)
    score = max(0, min(100, int(round(score))))
    state = "Ready" if score >= 90 else "Watch" if score >= 80 else "Needs DBA Review" if score >= 70 else "Executive Escalation"
    return {
        "score": score,
        "state": state,
        "current_credits": current_credits,
        "prior_credits": prior_credits,
        "cost_delta": cost_delta,
        "top_increase_credits": safe_float(cost_row.get("TOP_INCREASE_CREDITS")),
        "critical_high_alerts": critical_high_alerts,
        "open_actions": int(action_mask.sum()) if len(action_mask) else 0,
        "high_actions": high_actions,
        "migration_blockers": migration_blockers,
        "top_cost_driver": str(cost_row.get("TOP_INCREASE_WAREHOUSE") or "No loaded driver"),
    }


def _decision_rows(summary: dict) -> pd.DataFrame:
    rows = [
        {
            "PRIORITY": "1",
            "DECISION_AREA": "Operational risk",
            "SIGNAL": f"{summary['critical_high_alerts']:,} Critical/High open alert(s)",
            "NEXT_ACTION": "Open Alert Center automation readiness and confirm owner/escalation proof.",
            "WORKFLOW": "Alert Center",
        },
        {
            "PRIORITY": "2",
            "DECISION_AREA": "Cost movement",
            "SIGNAL": f"{summary['top_cost_driver']} is the top cost mover; delta {summary['cost_delta']:+,.2f} credits",
            "NEXT_ACTION": "Open Cost & Contract FinOps Control Center before changing budgets.",
            "WORKFLOW": "Cost & Contract",
        },
        {
            "PRIORITY": "3",
            "DECISION_AREA": "Owned closure",
            "SIGNAL": f"{summary['open_actions']:,} open action(s), {summary['high_actions']:,} high-priority",
            "NEXT_ACTION": "Work owned queue rows with approval and verification evidence.",
            "WORKFLOW": "DBA Control Room",
        },
        {
            "PRIORITY": "4",
            "DECISION_AREA": "Deployment trust",
            "SIGNAL": f"{summary['migration_blockers']:,} setup/migration blocker(s)",
            "NEXT_ACTION": "Open Setup Status and reconcile the mart migration ledger.",
            "WORKFLOW": "Change & Drift",
        },
    ]
    return pd.DataFrame(rows)


def _executive_action_brief(summary: dict | None) -> dict[str, str]:
    if not summary:
        return {
            "state": "Ready",
            "headline": "Open a board-ready snapshot when leadership evidence is needed.",
            "detail": "Risk, spend movement, closure work, and deployment trust stay behind one explicit load.",
        }
    if summary["critical_high_alerts"] or summary["high_actions"] or summary["migration_blockers"]:
        return {
            "state": str(summary["state"]),
            "headline": "Review the top exception before briefing leaders.",
            "detail": (
                f"{summary['critical_high_alerts']:,} Critical/High alert(s), "
                f"{summary['high_actions']:,} high-priority action(s), "
                f"{summary['migration_blockers']:,} deployment blocker(s)."
            ),
        }
    if summary["cost_delta"] > 0:
        return {
            "state": str(summary["state"]),
            "headline": "Spend increased; validate the top mover before the summary.",
            "detail": f"{summary['top_cost_driver']} moved {summary['cost_delta']:+,.2f} credits in the loaded window.",
        }
    return {
        "state": str(summary["state"]),
        "headline": "No executive blocker is visible in the loaded window.",
        "detail": "Use the decision rows to route any follow-up before sending the leadership brief.",
    }


def _snapshot_matches_scope(snapshot: dict, company: str, environment: str, days: int) -> bool:
    meta = snapshot.get("meta", {}) if isinstance(snapshot, dict) else {}
    try:
        loaded_days = int(meta.get("days") or 0)
    except (TypeError, ValueError):
        loaded_days = 0
    return (
        str(meta.get("company") or "") == str(company or "")
        and str(meta.get("environment") or "") == str(environment or "")
        and loaded_days == int(days or 0)
    )


def _money(value: float, *, signed: bool = False) -> str:
    number = safe_float(value)
    prefix = "+" if signed and number > 0 else ""
    if abs(number) >= 1000:
        return f"{prefix}${number:,.0f}"
    return f"{prefix}${number:,.2f}"


def _powerpoint_kpi_rows(
    summary: dict,
    *,
    company: str,
    environment_label: str,
    days: int,
    credit_price: float,
    source_health: pd.DataFrame | None = None,
) -> pd.DataFrame:
    current_spend = credits_to_dollars(safe_float(summary.get("current_credits")), credit_price)
    prior_spend = credits_to_dollars(safe_float(summary.get("prior_credits")), credit_price)
    spend_delta = current_spend - prior_spend
    source_rows = source_health if isinstance(source_health, pd.DataFrame) else pd.DataFrame()
    loaded_sources = int(source_rows["STATE"].eq("Loaded").sum()) if "STATE" in source_rows.columns else 0
    rows = [
        ("Scope", f"{company} / {environment_label}", "Company and environment currently selected."),
        ("Window", f"{int(days)} days", "Executive snapshot window."),
        ("Executive state", f"{summary.get('state')} ({safe_float(summary.get('score')):.0f}/100)", "Composite operating signal."),
        ("Current spend", _money(current_spend), f"{safe_float(summary.get('current_credits')):,.2f} credits at ${safe_float(credit_price):,.2f}/credit."),
        ("Spend delta", _money(spend_delta, signed=True), f"Prior window: {_money(prior_spend)}."),
        ("Top cost mover", str(summary.get("top_cost_driver") or "No loaded driver"), f"{safe_float(summary.get('top_increase_credits')):+,.2f} credits."),
        ("Critical/High alerts", f"{safe_float(summary.get('critical_high_alerts')):,.0f}", "Open leadership-visible risk."),
        ("Open actions", f"{safe_float(summary.get('open_actions')):,.0f}", f"{safe_float(summary.get('high_actions')):,.0f} high-priority."),
        ("Deployment blockers", f"{safe_float(summary.get('migration_blockers')):,.0f}", "Setup or migration blockers."),
        ("Sources loaded", f"{loaded_sources}/4", "Cost, alerts, action queue, migration ledger."),
    ]
    return pd.DataFrame(rows, columns=["KPI", "VALUE", "SLIDE_NOTE"])


def _powerpoint_chart_rows(summary: dict, *, credit_price: float) -> pd.DataFrame:
    current_spend = credits_to_dollars(safe_float(summary.get("current_credits")), credit_price)
    prior_spend = credits_to_dollars(safe_float(summary.get("prior_credits")), credit_price)
    spend_delta = current_spend - prior_spend
    rows = [
        ("Cost movement", "Current spend", current_spend, _money(current_spend)),
        ("Cost movement", "Prior spend", prior_spend, _money(prior_spend)),
        ("Cost movement", "Spend delta", spend_delta, _money(spend_delta, signed=True)),
        ("Risk and work", "Critical/High alerts", safe_float(summary.get("critical_high_alerts")), f"{safe_float(summary.get('critical_high_alerts')):,.0f}"),
        ("Risk and work", "High-priority actions", safe_float(summary.get("high_actions")), f"{safe_float(summary.get('high_actions')):,.0f}"),
        ("Risk and work", "Deployment blockers", safe_float(summary.get("migration_blockers")), f"{safe_float(summary.get('migration_blockers')):,.0f}"),
        ("Risk and work", "Open actions", safe_float(summary.get("open_actions")), f"{safe_float(summary.get('open_actions')):,.0f}"),
    ]
    return pd.DataFrame(rows, columns=["CHART", "METRIC", "VALUE", "LABEL"])


def _powerpoint_slide_brief(
    summary: dict,
    *,
    company: str,
    environment_label: str,
    days: int,
    credit_price: float,
) -> str:
    current_spend = credits_to_dollars(safe_float(summary.get("current_credits")), credit_price)
    prior_spend = credits_to_dollars(safe_float(summary.get("prior_credits")), credit_price)
    spend_delta = current_spend - prior_spend
    return "\n".join(
        [
            f"OVERWATCH Executive KPI Brief - {company} / {environment_label} / {int(days)} days",
            f"Headline: {summary.get('state')} ({safe_float(summary.get('score')):.0f}/100)",
            "",
            "Slide bullets:",
            f"- Spend: {_money(current_spend)} current window, {_money(spend_delta, signed=True)} versus prior window.",
            f"- Cost driver: {summary.get('top_cost_driver')} ({safe_float(summary.get('top_increase_credits')):+,.2f} credits).",
            f"- Risk: {safe_float(summary.get('critical_high_alerts')):,.0f} Critical/High open alerts.",
            f"- Work queue: {safe_float(summary.get('open_actions')):,.0f} open actions, {safe_float(summary.get('high_actions')):,.0f} high-priority.",
            f"- Deployment trust: {safe_float(summary.get('migration_blockers')):,.0f} setup or migration blockers.",
            "",
            "Next decision:",
            _executive_action_brief(summary)["headline"],
        ]
    )


def _render_slide_bar_chart(chart_rows: pd.DataFrame, chart_name: str) -> None:
    if chart_rows is None or chart_rows.empty:
        st.caption("No chart rows loaded for this slide.")
        return
    data = chart_rows[chart_rows["CHART"].astype(str) == chart_name].copy()
    if data.empty:
        st.caption("No chart rows loaded for this slide.")
        return
    data["VALUE"] = pd.to_numeric(data["VALUE"], errors="coerce").fillna(0)
    max_abs = max(abs(float(data["VALUE"].min())), abs(float(data["VALUE"].max())), 1.0)
    alt = _altair()
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
        .encode(
            x=alt.X("VALUE:Q", title=None, scale=alt.Scale(domain=[min(0, -max_abs if data["VALUE"].min() < 0 else 0), max_abs])),
            y=alt.Y("METRIC:N", sort=None, title=None, axis=alt.Axis(labelLimit=180)),
            color=alt.value("#29B5E8"),
            tooltip=[
                alt.Tooltip("METRIC:N", title="Metric"),
                alt.Tooltip("LABEL:N", title="Value"),
            ],
        )
    )
    labels = (
        alt.Chart(data)
        .mark_text(align="left", dx=5)
        .encode(x="VALUE:Q", y=alt.Y("METRIC:N", sort=None), text="LABEL:N")
    )
    st.altair_chart((bars + labels).properties(height=max(150, 42 * len(data))), width="stretch")


def _render_powerpoint_slide_pack(
    summary: dict,
    source_health: pd.DataFrame,
    *,
    company: str,
    environment: str,
    days: int,
    credit_price: float,
) -> None:
    environment_label = get_environment_label(environment, company)
    kpi_rows = _powerpoint_kpi_rows(
        summary,
        company=company,
        environment_label=environment_label,
        days=days,
        credit_price=credit_price,
        source_health=source_health,
    )
    chart_rows = _powerpoint_chart_rows(summary, credit_price=credit_price)
    slide_brief = _powerpoint_slide_brief(
        summary,
        company=company,
        environment_label=environment_label,
        days=days,
        credit_price=credit_price,
    )
    st.markdown("**PowerPoint Slide Brief**")
    st.text_area("Slide bullets", value=slide_brief, height=230, key="executive_powerpoint_slide_bullets")
    dl_cols = st.columns([1.0, 1.0, 2.0])
    dl_cols[0].download_button(
        "Download bullets",
        slide_brief,
        file_name=f"overwatch_{company.lower()}_{environment.lower()}_{int(days)}d_slide_brief.txt",
        mime="text/plain",
        key="executive_powerpoint_bullets_download",
    )
    dl_cols[1].download_button(
        "Download chart data",
        chart_rows.to_csv(index=False, sep="\t"),
        file_name=f"overwatch_{company.lower()}_{environment.lower()}_{int(days)}d_chart_data.tsv",
        mime="text/tab-separated-values",
        key="executive_powerpoint_chart_data_download",
    )
    st.dataframe(kpi_rows, hide_index=True, width="stretch")
    chart_cols = st.columns(2)
    with chart_cols[0]:
        st.markdown("**Cost Movement**")
        _render_slide_bar_chart(chart_rows, "Cost movement")
    with chart_cols[1]:
        st.markdown("**Risk and Work**")
        _render_slide_bar_chart(chart_rows, "Risk and work")


def _render_executive_action_brief(summary: dict | None, days: int) -> bool:
    brief = _executive_action_brief(summary)
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.1, 3.2, 1.4])
        with label_col:
            st.markdown("**Action Brief**")
            st.caption(str(brief["state"]))
        with detail_col:
            st.markdown(f"**{brief['headline']}**")
            st.caption(str(brief["detail"]))
        with action_col:
            st.caption(f"{int(days)}-day window")
            return bool(st.button("Load Executive Snapshot", key="executive_landing_load", type="primary", width="stretch"))
    return False


def _render_executive_operating_snapshot(
    summary: dict | None,
    *,
    credit_price: float,
    company: str,
    days: int,
) -> None:
    if not summary:
        metrics = (
            ("Scope", company),
            ("Window", f"{int(days)}d"),
            ("Rate", f"${safe_float(credit_price):,.2f}"),
            ("Evidence", "On demand"),
        )
    else:
        metrics = (
            ("State", str(summary["state"])),
            ("Spend", f"${credits_to_dollars(summary['current_credits'], credit_price):,.0f}"),
            ("Alerts", f"{summary['critical_high_alerts']:,}"),
            ("Deploy", f"{summary['migration_blockers']:,}"),
        )
    st.markdown("**Operating Snapshot**")
    cols = st.columns(4)
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.metric(label, value)


def _source_health_rows(snapshot: dict) -> pd.DataFrame:
    errors = [str(err) for err in snapshot.get("errors", [])]

    def _state(key: str, label: str, frame_name: str) -> dict:
        frame = snapshot.get(frame_name, pd.DataFrame())
        matching_error = next((err for err in errors if err.lower().startswith(key.lower())), "")
        if matching_error:
            state = "Limited"
            evidence = matching_error.split(":", 1)[-1].strip() or matching_error
            action = "Open the source section or Setup Status to verify access and deployment."
        elif isinstance(frame, pd.DataFrame) and not frame.empty:
            state = "Loaded"
            evidence = f"{len(frame):,} row(s) loaded."
            action = "Use this evidence for executive triage and drill-through."
        else:
            state = "No Rows"
            evidence = "Source was reachable but returned no rows in scope."
            action = "Confirm the current company, environment, and time window."
        return {
            "SOURCE": label,
            "STATE": state,
            "EVIDENCE": evidence,
            "NEXT_ACTION": action,
        }

    return pd.DataFrame(
        [
            _state("Cost mart unavailable", "Cost cockpit", "cost"),
            _state("Alert evidence unavailable", "Alert evidence", "alerts"),
            _state("Action queue unavailable", "Action queue", "queue"),
            _state("Migration ledger unavailable", "Migration ledger", "migration"),
        ]
    )


def _nav_button(
    label: str,
    section: str,
    *,
    workflow_key: str = "",
    workflow: str = "",
    state_updates: dict[str, str] | None = None,
) -> None:
    if st.button(label, key=f"executive_nav_{section}_{workflow or label}", width="stretch"):
        st.session_state["nav_section"] = section
        if workflow_key and workflow:
            st.session_state[workflow_key] = workflow
        for key, value in (state_updates or {}).items():
            st.session_state[key] = value
        st.rerun()


def render() -> None:
    company = _active_company()
    environment = _active_environment()
    credit_price = _credit_price()
    defer_source_note(
        "Executive Landing loads only on demand and uses OVERWATCH marts, alert/action evidence, and migration status."
    )

    window_col, _window_spacer = st.columns([1.2, 3.0])
    with window_col:
        days = st.selectbox(
            "Executive window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(DEFAULT_DAY_WINDOW),
            format_func=lambda value: f"{value} days",
        )
    snapshot = st.session_state.get("executive_landing_snapshot")
    if isinstance(snapshot, dict) and not _snapshot_matches_scope(snapshot, company, environment, int(days)):
        defer_source_note("Loaded Executive Landing snapshot is for another scope. Reload the snapshot for the selected company, environment, and window.")
        snapshot = None
    summary = None
    if isinstance(snapshot, dict):
        summary = _snapshot_state(
            snapshot.get("cost", pd.DataFrame()),
            snapshot.get("alerts", pd.DataFrame()),
            snapshot.get("queue", pd.DataFrame()),
            snapshot.get("migration", pd.DataFrame()),
        )
    load = _render_executive_action_brief(summary, int(days))
    _render_executive_operating_snapshot(summary, credit_price=credit_price, company=company, days=int(days))

    if load:
        session = get_session_for_action(
            "load Executive Landing snapshot",
            surface="Executive Landing",
            offline_note="Executive Landing shell remains available without Snowflake.",
        )
        if session is None:
            return
        snapshot = {"errors": []}
        try:
            snapshot["cost"] = run_query(
                build_mart_cost_cockpit_sql(company, int(days)),
                ttl_key=f"executive_cost_{company}_{days}",
                tier="historical",
                section="Executive Landing",
            )
        except Exception as exc:
            snapshot["cost"] = pd.DataFrame()
            snapshot["errors"].append(f"Cost mart unavailable: {format_snowflake_error(exc)}")
        try:
            snapshot["alerts"] = _load_alerts(session, company, environment, int(days))
        except Exception as exc:
            snapshot["alerts"] = pd.DataFrame()
            snapshot["errors"].append(f"Alert evidence unavailable: {format_snowflake_error(exc)}")
        try:
            snapshot["queue"] = load_action_queue(session)
        except Exception as exc:
            snapshot["queue"] = pd.DataFrame()
            snapshot["errors"].append(f"Action queue unavailable: {format_snowflake_error(exc)}")
        try:
            snapshot["migration"] = run_query(
                build_schema_migration_status_sql(),
                ttl_key="executive_migration_status",
                tier="recent",
                section="Executive Landing",
            )
        except Exception as exc:
            snapshot["migration"] = pd.DataFrame()
            snapshot["errors"].append(f"Migration ledger unavailable: {format_snowflake_error(exc)}")
        snapshot["meta"] = {"company": company, "environment": environment, "days": int(days)}
        st.session_state["executive_landing_snapshot"] = snapshot
        st.rerun()

    snapshot = st.session_state.get("executive_landing_snapshot")
    if not isinstance(snapshot, dict) or not _snapshot_matches_scope(snapshot, company, environment, int(days)):
        return

    for err in snapshot.get("errors", []):
        defer_source_note(err)

    source_health = _source_health_rows(snapshot)
    loaded_sources = int(source_health["STATE"].eq("Loaded").sum())
    limited_sources = int(source_health["STATE"].eq("Limited").sum())
    no_row_sources = int(source_health["STATE"].eq("No Rows").sum())
    s1, s2, s3 = st.columns(3)
    s1.metric("Sources Loaded", f"{loaded_sources}/4")
    s2.metric("Limited Sources", f"{limited_sources}", delta_color="inverse")
    s3.metric("No-Row Sources", f"{no_row_sources}")
    render_priority_dataframe(
        source_health,
        title="Executive source health",
        priority_columns=["SOURCE", "STATE", "EVIDENCE", "NEXT_ACTION"],
        sort_by=["STATE", "SOURCE"],
        ascending=[True, True],
        raw_label="All executive source health rows",
        height=220,
    )

    _render_powerpoint_slide_pack(
        summary,
        source_health,
        company=company,
        environment=environment,
        days=int(days),
        credit_price=credit_price,
    )

    render_priority_dataframe(
        _decision_rows(summary),
        title="Executive decisions to make first",
        priority_columns=["PRIORITY", "DECISION_AREA", "SIGNAL", "NEXT_ACTION", "WORKFLOW"],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All executive decision rows",
        height=240,
    )

    n1, n2, n3, n4 = st.columns(4)
    with n1:
        _nav_button(
            "Alert Automation",
            "Alert Center",
            state_updates={"alert_center_active_view": "Automation Readiness"},
        )
    with n2:
        _nav_button("FinOps Controls", "Cost & Contract", workflow_key="cost_contract_workflow", workflow="FinOps Control Center")
    with n3:
        _nav_button("DBA Queue", "DBA Control Room")
    with n4:
        _nav_button(
            "Setup Status",
            "Change & Drift",
            workflow_key="change_drift_workflow",
            workflow="Controlled DBA actions",
            state_updates={
                "dba_tools_focus": "Cost",
                "dba_tools_group_selector": "Cost & Setup",
                "dba_tools_tool_selector_Cost & Setup": "Setup Status",
            },
        )

    alerts = snapshot.get("alerts", pd.DataFrame())
    if isinstance(alerts, pd.DataFrame) and not alerts.empty:
        render_priority_dataframe(
            alerts,
            title="Alerts leadership should know about",
            priority_columns=["SEVERITY", "STATUS", "CATEGORY", "ALERT_TYPE", "ENTITY_NAME", "OWNER", "SLA_STATE", "SUGGESTED_ACTION"],
            sort_by=["SEVERITY", "ALERT_TS"],
            ascending=[True, False],
            raw_label="All loaded executive alerts",
            max_rows=8,
            height=280,
        )
