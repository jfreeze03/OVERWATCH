# sections/executive_landing.py - executive landing page
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from config import (
    ACTION_QUEUE_TABLE,
    ALERT_DB,
    ALERT_SCHEMA,
    DEFAULT_COMPANY,
    DEFAULT_DAY_WINDOW,
    DEFAULT_ENVIRONMENT,
    DEFAULTS,
    DAY_WINDOW_OPTIONS,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_navigation_state, apply_section_workflow_navigation
from sections.shell_helpers import (
    render_escaped_bold_text,
    render_refresh_contract,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
)
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_schema_migration_status_sql = _lazy_util("build_schema_migration_status_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
load_action_queue = _lazy_util("load_action_queue")
load_alert_history = _lazy_util("load_alert_history")
mart_object_name = _lazy_util("mart_object_name")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")
load_enterprise_operating_rollups = _lazy_util("load_enterprise_operating_rollups")
load_change_intelligence_summary = _lazy_util("load_change_intelligence_summary")
load_closed_loop_summary = _lazy_util("load_closed_loop_summary")
load_command_center_summary = _lazy_util("load_command_center_summary")
load_executive_scorecard_summary = _lazy_util("load_executive_scorecard_summary")
load_executive_forecast_summary = _lazy_util("load_executive_forecast_summary")
load_production_readiness_summary = _lazy_util("load_production_readiness_summary")
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
snowflake_connection_known_unavailable = _lazy_util("snowflake_connection_known_unavailable")
sql_literal = _lazy_util("sql_literal")


EXECUTIVE_LANDING_VERSION = "2026-06-14-boardroom-glance-v2"
PLATFORM_SUMMARY_STATE_KEY = "executive_landing_platform_summary"
OBSERVABILITY_STATE_KEY = "executive_landing_observability_board"
OBSERVABILITY_OFFLINE_SOURCE = "Snowflake connection unavailable"



def _altair():
    """Load Altair only when charts are shown."""
    import altair as alt

    return alt


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


def _platform_score_state(score: float) -> str:
    score = safe_float(score)
    if score >= 90:
        return "Ready"
    if score >= 80:
        return "Watch"
    if score >= 70:
        return "Needs DBA Review"
    return "Executive Escalation"


def _pressure_level(score: float) -> str:
    score = safe_float(score)
    if score >= 75:
        return "Critical"
    if score >= 40:
        return "Review"
    if score > 0:
        return "Watch"
    return "Clear"


def _score_driver(
    driver: str,
    *,
    penalty: float,
    evidence: str,
    next_action: str,
    cap: int | None = None,
) -> dict:
    penalty = max(0.0, safe_float(penalty))
    return {
        "DRIVER": driver,
        "STATE": "Review" if penalty > 0 else "Ready",
        "SCORE_IMPACT": round(-penalty, 1),
        "EVIDENCE": evidence,
        "SCORE_CAP": "" if cap is None else int(cap),
        "NEXT_ACTION": next_action,
    }


def _build_platform_operating_score(summary: dict, source_health: pd.DataFrame | None = None) -> dict:
    """Strict executive health index with visible drivers and telemetry limits."""
    prior_credits = safe_float(summary.get("prior_credits"))
    cost_delta = safe_float(summary.get("cost_delta"))
    critical_high = safe_int(summary.get("critical_high_alerts"))
    open_actions = safe_int(summary.get("open_actions"))
    high_actions = safe_int(summary.get("high_actions"))
    migration_blockers = safe_int(summary.get("migration_blockers"))
    advisor_findings = safe_int(summary.get("advisor_findings"))
    advisor_high = safe_int(summary.get("advisor_high_findings"))
    advisor_value_at_risk = safe_float(summary.get("advisor_value_at_risk_usd"))
    source_rows = source_health if isinstance(source_health, pd.DataFrame) else pd.DataFrame()
    loaded_sources = int(source_rows["STATE"].eq("Loaded").sum()) if "STATE" in source_rows.columns else 0
    limited_sources = int(source_rows["STATE"].eq("Limited").sum()) if "STATE" in source_rows.columns else 0

    cost_delta_pct = cost_delta / max(prior_credits, 1.0) if cost_delta > 0 and prior_credits else 0.0
    cost_penalty = min(20.0, max(0.0, cost_delta_pct) * 35.0)
    alert_penalty = min(24.0, critical_high * 8.0)
    action_penalty = min(18.0, high_actions * 5.0 + max(0, open_actions - high_actions) * 0.5)
    deployment_penalty = min(24.0, migration_blockers * 12.0)
    telemetry_penalty = min(18.0, limited_sources * 8.0)
    advisor_penalty = min(
        12.0,
        advisor_high * 4.0 + max(0, advisor_findings - advisor_high) * 0.25 + min(advisor_value_at_risk / 2500.0, 4.0),
    )

    caps: list[tuple[int, str]] = []
    if limited_sources:
        caps.append((82, f"{limited_sources} executive telemetry input(s) are limited."))
    if migration_blockers:
        caps.append((74, f"{migration_blockers} monitoring coverage blocker(s) cap the executive operating state."))
    if critical_high:
        caps.append((85, f"{critical_high} Critical/High open alert(s) limit the executive health index."))
    if high_actions:
        caps.append((88, f"{high_actions} high-priority open action(s) limit the executive health index."))
    if advisor_high:
        caps.append((89, f"{advisor_high} high-priority loaded advisor finding(s) need DBA review."))
    if cost_delta_pct >= 0.20:
        caps.append((90, f"Spend increased {cost_delta_pct:.0%} versus the prior window."))

    drivers = pd.DataFrame([
        _score_driver(
            "Cost & Contract",
            penalty=cost_penalty,
            evidence=(
                f"Spend delta {cost_delta:+,.2f} credits"
                if cost_delta > 0
                else "No positive spend movement in loaded cost summary."
            ),
            next_action="Open Cost & Contract and validate the top cost mover before changing warehouse settings.",
            cap=90 if cost_delta_pct >= 0.20 else None,
        ),
        _score_driver(
            "Reliability / Alerts",
            penalty=alert_penalty,
            evidence=f"{critical_high:,} Critical/High open alert(s).",
            next_action="Open Alert Center and confirm route, SLA state, and escalation status.",
            cap=85 if critical_high else None,
        ),
        _score_driver(
            "Owned Closure",
            penalty=action_penalty,
            evidence=f"{open_actions:,} open action(s), {high_actions:,} high-priority.",
            next_action="Open DBA Control Room and work routed queue rows with telemetry status.",
            cap=88 if high_actions else None,
        ),
        _score_driver(
            "Monitoring Coverage",
            penalty=deployment_penalty,
            evidence=f"{migration_blockers:,} monitoring coverage blocker(s).",
            next_action="Open Data Health and reconcile source status before using the executive wall.",
            cap=74 if migration_blockers else None,
        ),
        _score_driver(
            "Telemetry Coverage",
            penalty=telemetry_penalty,
            evidence=f"{loaded_sources}/4 executive signal group(s) ready; {limited_sources} limited.",
            next_action="Reload or route to the owning monitoring view when telemetry is limited.",
            cap=82 if limited_sources else None,
        ),
        _score_driver(
            "Advisor Backlog",
            penalty=advisor_penalty,
            evidence=(
                f"{advisor_findings:,} loaded advisor finding(s), {advisor_high:,} high-priority, "
                f"{_money(advisor_value_at_risk)} value at risk."
            ),
            next_action="Open the loaded advisor row's owning section before tuning or assigning work.",
            cap=89 if advisor_high else None,
        ),
    ])
    if not drivers.empty:
        drivers = drivers.sort_values(["SCORE_IMPACT", "DRIVER"], ascending=[True, True]).reset_index(drop=True)

    raw_score = max(
        0.0,
        min(
            100.0,
            100.0
            - cost_penalty
            - alert_penalty
            - action_penalty
            - deployment_penalty
            - telemetry_penalty
            - advisor_penalty,
        ),
    )
    cap_value = min((cap for cap, _reason in caps), default=100)
    cap_reason = next((reason for cap, reason in sorted(caps, key=lambda item: item[0]) if cap == cap_value), "")
    final_score = max(0, min(100, int(round(min(raw_score, cap_value)))))
    return {
        "score": final_score,
        "raw_score": round(raw_score, 1),
        "state": _platform_score_state(final_score),
        "score_cap": cap_value,
        "cap_reason": cap_reason or "No hard cap applied.",
        "platform_score_drivers": drivers,
    }


def _with_platform_operating_score(summary: dict, source_health: pd.DataFrame | None = None) -> dict:
    enriched = dict(summary or {})
    enriched.update(_build_platform_operating_score(enriched, source_health))
    return enriched


def _persist_platform_summary(summary: dict | None) -> None:
    if not summary:
        return
    st.session_state[PLATFORM_SUMMARY_STATE_KEY] = {
        "score": safe_int(summary.get("score")),
        "raw_score": safe_float(summary.get("raw_score")),
        "state": str(summary.get("state") or "Review"),
        "score_cap": safe_int(summary.get("score_cap"), 100),
        "cap_reason": str(summary.get("cap_reason") or "No hard cap applied."),
        "advisor_lanes": safe_int(summary.get("advisor_lanes")),
        "advisor_findings": safe_int(summary.get("advisor_findings")),
        "advisor_high_findings": safe_int(summary.get("advisor_high_findings")),
        "advisor_estimated_monthly_savings_usd": safe_float(summary.get("advisor_estimated_monthly_savings_usd")),
        "advisor_value_at_risk_usd": safe_float(summary.get("advisor_value_at_risk_usd")),
    }


def _snapshot_state(
    cost: pd.DataFrame,
    alerts: pd.DataFrame,
    queue: pd.DataFrame,
    migration: pd.DataFrame,
    state: dict | None = None,
) -> dict:
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
    advisor_rows = _executive_loaded_advisor_rows(state)
    advisor_totals = _advisor_overlay_totals(advisor_rows)
    summary = {
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
    summary.update(advisor_totals)
    return _with_platform_operating_score(summary)


def _default_platform_summary() -> dict:
    """Render an honest state frame before the executive summary is refreshed."""
    source_health = pd.DataFrame([
        {
            "SOURCE": "Executive observability summary",
            "STATE": "Limited",
            "EVIDENCE": "Executive summary rows are available after refresh for this scope.",
            "NEXT_ACTION": "Refresh the executive summary when current leadership context is needed.",
        },
        {
            "SOURCE": "Cost summary",
            "STATE": "Limited",
            "EVIDENCE": "Cost facts are available after executive refresh.",
            "NEXT_ACTION": "Open Cost & Contract or refresh the executive summary for spend context.",
        },
        {
            "SOURCE": "Alert and action queue",
            "STATE": "Limited",
            "EVIDENCE": "Open alert and owner-action counts are available after refresh.",
            "NEXT_ACTION": "Open Alert Center or DBA Control Room for owner-ready triage.",
        },
        {
            "SOURCE": "Monitoring coverage",
            "STATE": "Limited",
            "EVIDENCE": "Monitoring source status is available after refresh.",
            "NEXT_ACTION": "Open the source section when coverage detail is needed.",
        },
    ])
    summary = {
        "current_credits": 0.0,
        "prior_credits": 0.0,
        "cost_delta": 0.0,
        "top_increase_credits": 0.0,
        "critical_high_alerts": 0,
        "open_actions": 0,
        "high_actions": 0,
        "migration_blockers": 0,
        "top_cost_driver": "On demand",
    }
    summary.update(_advisor_overlay_totals(pd.DataFrame()))
    return _with_platform_operating_score(summary, source_health)


def _decision_rows(summary: dict) -> pd.DataFrame:
    rows = [
        {
            "PRIORITY": "1",
            "DECISION_AREA": "Operational risk",
            "SIGNAL": f"{summary['critical_high_alerts']:,} Critical/High open alert(s)",
            "NEXT_ACTION": "Open Alert Center automation readiness and confirm route/escalation status.",
            "WORKFLOW": "Alert Center",
        },
        {
            "PRIORITY": "2",
            "DECISION_AREA": "Cost movement",
            "SIGNAL": f"{summary['top_cost_driver']} is the top cost mover; delta {summary['cost_delta']:+,.2f} credits",
            "NEXT_ACTION": "Open Cost & Contract and explain the top cost mover before changing warehouse settings.",
            "WORKFLOW": "Cost & Contract",
        },
        {
            "PRIORITY": "3",
            "DECISION_AREA": "Loaded advisors",
            "SIGNAL": (
                f"{safe_int(summary.get('advisor_findings')):,} finding(s), "
                f"{safe_int(summary.get('advisor_high_findings')):,} high-priority, "
                f"{_money(safe_float(summary.get('advisor_estimated_monthly_savings_usd')))}/mo estimated savings"
            ),
            "NEXT_ACTION": "Open Cost & Contract, Warehouse Health, or Workload Operations for the top loaded advisor row.",
            "WORKFLOW": "Cost & Contract",
        },
        {
            "PRIORITY": "4",
            "DECISION_AREA": "Measured closure",
            "SIGNAL": f"{summary['open_actions']:,} open action(s), {summary['high_actions']:,} high-priority",
            "NEXT_ACTION": "Work routed queue rows with telemetry status.",
            "WORKFLOW": "DBA Control Room",
        },
        {
            "PRIORITY": "5",
            "DECISION_AREA": "Deployment trust",
            "SIGNAL": f"{summary['migration_blockers']:,} monitoring coverage blocker(s)",
            "NEXT_ACTION": "Open Security Monitoring and reconcile readiness telemetry.",
            "WORKFLOW": "Change & Drift",
        },
    ]
    return pd.DataFrame(rows)


def _executive_action_brief(summary: dict | None) -> dict[str, str]:
    if not summary:
        return {
            "state": "Ready",
            "headline": "Open an executive snapshot when leadership telemetry is needed.",
            "detail": "Risk, spend movement, closure work, and deployment trust stay behind one explicit load.",
        }
    advisor_high = safe_int(summary.get("advisor_high_findings"))
    advisor_findings = safe_int(summary.get("advisor_findings"))
    advisor_savings = safe_float(summary.get("advisor_estimated_monthly_savings_usd"))
    if summary["critical_high_alerts"] or summary["high_actions"] or summary["migration_blockers"] or advisor_high:
        cap_reason = str(summary.get("cap_reason") or "")
        cap_detail = f" Limiter: {cap_reason}" if cap_reason and cap_reason != "No hard cap applied." else ""
        return {
            "state": str(summary["state"]),
            "headline": "Review the top exception before briefing leaders.",
            "detail": (
                f"{summary['critical_high_alerts']:,} Critical/High alert(s), "
                f"{summary['high_actions']:,} high-priority action(s), "
                f"{summary['migration_blockers']:,} deployment blocker(s), "
                f"{advisor_high:,} high-priority advisor finding(s).{cap_detail}"
            ),
        }
    if summary["cost_delta"] > 0:
        return {
            "state": str(summary["state"]),
            "headline": "Spend increased; validate the top mover before the summary.",
            "detail": f"{summary['top_cost_driver']} moved {summary['cost_delta']:+,.2f} credits in the loaded window.",
        }
    if advisor_findings:
        return {
            "state": str(summary["state"]),
            "headline": "Loaded advisor work is ready for executive triage.",
            "detail": (
                f"{advisor_findings:,} advisor finding(s) loaded; "
                f"{_money(advisor_savings)}/mo estimated savings where quantified."
            ),
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


def _company_filter_sql(alias: str = "") -> str:
    company = _active_company()
    if str(company or "").upper() == "ALL":
        return ""
    prefix = f"{alias}." if alias else ""
    return f"AND {prefix}COMPANY = {sql_literal(company, 100)}"


def _environment_filter_sql(alias: str = "") -> str:
    environment = _active_environment()
    if str(environment or "").upper() == "ALL":
        return ""
    prefix = f"{alias}." if alias else ""
    return f"AND UPPER(COALESCE({prefix}ENVIRONMENT, 'ALL')) = {sql_literal(environment.upper(), 100)}"


def _build_executive_observability_sql(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
    ai_credit_price: float,
) -> str:
    """Return the tiny first-paint executive board query."""
    days = max(1, int(days or DEFAULT_DAY_WINDOW))
    _ = (credit_price, ai_credit_price)
    company_value = "ALL" if str(company or "").upper() == "ALL" else str(company or DEFAULT_COMPANY)
    environment_value = "ALL" if str(environment or "").upper() == "ALL" else str(environment or DEFAULT_ENVIRONMENT)
    company_lit = sql_literal(company_value.upper(), 100)
    environment_lit = sql_literal(environment_value.upper(), 100)
    board_table = mart_object_name("MART_EXECUTIVE_OBSERVABILITY")
    return f"""
WITH candidate AS (
    SELECT
        PANEL,
        METRIC,
        DIMENSION,
        PERIOD_START,
        VALUE,
        VALUE_USD,
        UNIT,
        SORT_ORDER,
        COMPANY,
        ENVIRONMENT,
        SNAPSHOT_TS
    FROM {board_table}
    WHERE WINDOW_DAYS = {days}
      AND UPPER(COMPANY) IN ({company_lit}, 'ALL')
      AND (
        UPPER(COALESCE(ENVIRONMENT, 'ALL')) = 'ALL'
        OR UPPER(COALESCE(ENVIRONMENT, 'ALL')) = {environment_lit}
      )
      AND SNAPSHOT_TS >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
),
ranked AS (
    SELECT
        PANEL,
        METRIC,
        DIMENSION,
        PERIOD_START,
        VALUE,
        VALUE_USD,
        UNIT,
        SORT_ORDER,
        ROW_NUMBER() OVER (
            PARTITION BY PANEL, METRIC, DIMENSION, PERIOD_START, SORT_ORDER
            ORDER BY
                IFF(UPPER(COMPANY) = {company_lit}, 0, 1),
                IFF(UPPER(COALESCE(ENVIRONMENT, 'ALL')) = {environment_lit}, 0, 1),
                SNAPSHOT_TS DESC
        ) AS RN
    FROM candidate
)
SELECT PANEL, METRIC, DIMENSION, PERIOD_START, VALUE, VALUE_USD, UNIT, SORT_ORDER
FROM ranked
WHERE RN = 1
ORDER BY PANEL, SORT_ORDER, PERIOD_START, VALUE DESC
"""


def _observability_scope(company: str, environment: str, days: int) -> tuple[str, str, int]:
    return str(company), str(environment), int(days)


_OBS_COLUMNS = ["PANEL", "METRIC", "DIMENSION", "PERIOD_START", "VALUE", "VALUE_USD", "UNIT", "SORT_ORDER"]


def _normalise_observability_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=_OBS_COLUMNS)
    rows = frame.copy()
    for column in _OBS_COLUMNS:
        if column not in rows.columns:
            rows[column] = None
    return rows[_OBS_COLUMNS]


def _sort_observability_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    rows = _normalise_observability_frame(frame)
    if rows.empty:
        return rows
    rows["SORT_ORDER"] = pd.to_numeric(rows["SORT_ORDER"], errors="coerce").fillna(9999)
    return rows.sort_values(
        ["PANEL", "SORT_ORDER", "DIMENSION"],
        na_position="last",
    ).reset_index(drop=True)


def _observability_status_frame(statuses: list[dict]) -> pd.DataFrame:
    rows = []
    for idx, status in enumerate(statuses, start=1):
        rows.append({
            "PANEL": "SOURCE_STATUS",
            "METRIC": str(status.get("state") or "Unknown"),
            "DIMENSION": str(status.get("source") or "Unknown source"),
            "PERIOD_START": None,
            "VALUE": None,
            "VALUE_USD": None,
            "UNIT": str(status.get("detail") or ""),
            "SORT_ORDER": 990 + idx,
        })
    return pd.DataFrame(rows, columns=_OBS_COLUMNS)


def _store_observability_payload(
    board: pd.DataFrame | None,
    *,
    company: str,
    environment: str,
    days: int,
    source: str,
    error: str = "",
) -> bool:
    normalised = _sort_observability_frame(board)
    st.session_state[OBSERVABILITY_STATE_KEY] = {
        "data": normalised,
        "scope": _observability_scope(company, environment, int(days)),
        "source": source,
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
        "error": error,
    }
    return not _obs_rows(normalised, "KPI").empty


def _store_connection_unavailable_observability(company: str, environment: str, days: int) -> bool:
    return _store_observability_payload(
        _observability_status_frame([{
            "source": "Connection",
            "state": "Unavailable",
            "detail": (
                "Snowflake connection is not available yet. Executive Landing is showing local shell "
                "state until the app has a live Snowflake session or Refresh Summary is used after configuration."
            ),
        }]),
        company=company,
        environment=environment,
        days=int(days),
        source=OBSERVABILITY_OFFLINE_SOURCE,
        error="Snowflake connection is not available yet; showing local Executive Landing shell state.",
    )


def _build_executive_observability_query_parts(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
    ai_credit_price: float,
) -> list[tuple[str, str, str]]:
    """Build independent fast queries so one missing source cannot blank the board."""
    days = max(1, int(days or DEFAULT_DAY_WINDOW))
    company_clause = "" if str(company or "").upper() == "ALL" else f"AND COMPANY = {sql_literal(company, 100)}"
    env_clause = "" if str(environment or "").upper() == "ALL" else f"AND UPPER(COALESCE(ENVIRONMENT, 'ALL')) = {sql_literal(str(environment).upper(), 100)}"
    cost_table = mart_object_name("FACT_COST_DAILY")
    cortex_table = mart_object_name("FACT_CORTEX_DAILY")
    query_table = mart_object_name("FACT_QUERY_HOURLY")
    query_detail_table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    task_table = mart_object_name("FACT_TASK_RUN")
    storage_table = mart_object_name("FACT_STORAGE_DAILY")
    control_table = mart_object_name("MART_DBA_CONTROL_ROOM")
    alert_table = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier('ALERT_EVENTS')}"
    queue_table = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"

    cost_sql = f"""
WITH cost_daily AS (
    SELECT
        USAGE_DATE,
        COALESCE(SERVICE_CATEGORY, 'Unknown') AS SERVICE_CATEGORY,
        COALESCE(SERVICE_TYPE, 'Unknown') AS SERVICE_TYPE,
        SUM(COALESCE(CREDITS_BILLED, CREDITS_USED_COMPUTE, 0)) AS CREDITS,
        SUM(COALESCE(
            EST_COST_USD,
            COALESCE(CREDITS_BILLED, CREDITS_USED_COMPUTE, 0) * {float(credit_price):.4f}
        )) AS COST_USD,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {cost_table}
    WHERE USAGE_DATE >= DATEADD('MONTH', -6, CURRENT_DATE())
      AND USAGE_DATE < CURRENT_DATE()
      {company_clause}
    GROUP BY USAGE_DATE, COALESCE(SERVICE_CATEGORY, 'Unknown'), COALESCE(SERVICE_TYPE, 'Unknown')
),
cost_current AS (
    SELECT
        SUM(IFF(USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE()), CREDITS, 0)) AS CURRENT_CREDITS,
        SUM(IFF(USAGE_DATE >= DATEADD('DAY', -{days * 2}, CURRENT_DATE()) AND USAGE_DATE < DATEADD('DAY', -{days}, CURRENT_DATE()), CREDITS, 0)) AS PRIOR_CREDITS,
        SUM(IFF(USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE()), COST_USD, 0)) AS CURRENT_COST_USD,
        SUM(IFF(USAGE_DATE >= DATEADD('DAY', -{days * 2}, CURRENT_DATE()) AND USAGE_DATE < DATEADD('DAY', -{days}, CURRENT_DATE()), COST_USD, 0)) AS PRIOR_COST_USD,
        MAX(LOAD_TS) AS LOAD_TS
    FROM cost_daily
),
monthly_cost AS (
    SELECT
        DATE_TRUNC('MONTH', USAGE_DATE) AS PERIOD_START,
        SUM(CREDITS) AS CREDITS,
        SUM(COST_USD) AS COST_USD
    FROM cost_daily
    GROUP BY DATE_TRUNC('MONTH', USAGE_DATE)
),
cost_driver_ranked AS (
    SELECT
        SERVICE_CATEGORY || ' / ' || SERVICE_TYPE AS DRIVER,
        SUM(CREDITS) AS CREDITS,
        SUM(COST_USD) AS COST_USD,
        ROW_NUMBER() OVER (
            ORDER BY SUM(COST_USD) DESC, SERVICE_CATEGORY || ' / ' || SERVICE_TYPE
        ) AS RN
    FROM cost_daily
    WHERE USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE())
    GROUP BY SERVICE_CATEGORY, SERVICE_TYPE
)
SELECT 'KPI' AS PANEL, 'Credits Used' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(CURRENT_CREDITS, 0)::FLOAT AS VALUE, COALESCE(CURRENT_COST_USD, 0)::FLOAT AS VALUE_USD, 'credits_usd' AS UNIT, 1 AS SORT_ORDER
FROM cost_current
UNION ALL
SELECT 'KPI', 'Spend Delta', 'Current vs prior', NULL::TIMESTAMP_NTZ,
       COALESCE(CURRENT_CREDITS, 0) - COALESCE(PRIOR_CREDITS, 0),
       COALESCE(CURRENT_COST_USD, 0) - COALESCE(PRIOR_COST_USD, 0), 'credits_usd', 2
FROM cost_current
UNION ALL
SELECT 'DAILY_COST', 'Daily Spend', TO_VARCHAR(USAGE_DATE), TO_TIMESTAMP_NTZ(USAGE_DATE),
       SUM(CREDITS), SUM(COST_USD), 'credits_usd', 101
FROM cost_daily
WHERE USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE())
GROUP BY USAGE_DATE
UNION ALL
SELECT 'MONTHLY_COST', 'Monthly Spend', TO_VARCHAR(PERIOD_START, 'YYYY-MM'), TO_TIMESTAMP_NTZ(PERIOD_START),
       CREDITS, COST_USD, 'credits_usd', 201
FROM monthly_cost
UNION ALL
SELECT 'COST_DRIVER', 'Cost Drivers', DRIVER, NULL::TIMESTAMP_NTZ,
       CREDITS, COST_USD, 'credits_usd', 251
FROM cost_driver_ranked
WHERE RN <= 8
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Cost facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 901
FROM cost_daily
"""

    cortex_sql = f"""
WITH cortex_daily AS (
    SELECT
        USAGE_DATE,
        SUM(COALESCE(CREDITS_USED, 0)) AS CREDITS,
        SUM(COALESCE(EST_COST_USD, COALESCE(CREDITS_USED, 0) * {float(ai_credit_price):.4f})) AS COST_USD,
        SUM(COALESCE(REQUEST_COUNT, 0)) AS REQUESTS,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {cortex_table}
    WHERE USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE())
      AND USAGE_DATE < CURRENT_DATE()
      {company_clause}
    GROUP BY USAGE_DATE
)
SELECT 'KPI' AS PANEL, 'Cortex Spend' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(SUM(CREDITS), 0)::FLOAT AS VALUE, COALESCE(SUM(COST_USD), 0)::FLOAT AS VALUE_USD, 'credits_usd' AS UNIT, 3 AS SORT_ORDER
FROM cortex_daily
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Cortex facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 904
FROM cortex_daily
"""

    query_sql = f"""
WITH query_daily AS (
    SELECT
        TO_DATE(HOUR_START) AS USAGE_DATE,
        SUM(COALESCE(QUERY_COUNT, 0)) AS QUERIES,
        SUM(COALESCE(FAILED_COUNT, 0)) AS FAILED_QUERIES,
        SUM(COALESCE(TOTAL_ELAPSED_MS, 0)) AS ELAPSED_MS,
        SUM(COALESCE(TOTAL_QUEUED_MS, 0)) AS QUEUED_MS,
        SUM(COALESCE(TOTAL_SPILL_BYTES, 0)) AS SPILL_BYTES,
        SUM(COALESCE(TOTAL_BYTES_SCANNED, 0)) AS BYTES_SCANNED,
        MAX(COALESCE(P95_EXECUTION_MS, 0)) AS P95_EXECUTION_MS,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {query_table}
    WHERE HOUR_START >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY TO_DATE(HOUR_START)
),
query_type AS (
    SELECT
        COALESCE(QUERY_TYPE, 'Unknown') AS QUERY_TYPE,
        SUM(COALESCE(QUERY_COUNT, 0)) AS QUERIES
    FROM {query_table}
    WHERE HOUR_START >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY COALESCE(QUERY_TYPE, 'Unknown')
),
query_type_ranked AS (
    SELECT QUERY_TYPE, QUERIES,
           ROW_NUMBER() OVER (ORDER BY QUERIES DESC, QUERY_TYPE) AS RN
    FROM query_type
),
query_database AS (
    SELECT
        COALESCE(DATABASE_NAME, 'Unknown') AS DATABASE_NAME,
        SUM(COALESCE(QUERY_COUNT, 0)) AS QUERIES
    FROM {query_table}
    WHERE HOUR_START >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY COALESCE(DATABASE_NAME, 'Unknown')
),
query_database_ranked AS (
    SELECT DATABASE_NAME, QUERIES,
           ROW_NUMBER() OVER (ORDER BY QUERIES DESC, DATABASE_NAME) AS RN
    FROM query_database
),
warehouse_pressure AS (
    SELECT
        COALESCE(WAREHOUSE_NAME, 'Unknown') AS WAREHOUSE_NAME,
        SUM(COALESCE(QUERY_COUNT, 0)) AS QUERIES,
        SUM(COALESCE(TOTAL_QUEUED_MS, 0)) AS QUEUED_MS,
        SUM(COALESCE(TOTAL_SPILL_BYTES, 0)) AS SPILL_BYTES,
        MAX(COALESCE(P95_EXECUTION_MS, 0)) AS P95_EXECUTION_MS
    FROM {query_table}
    WHERE HOUR_START >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY COALESCE(WAREHOUSE_NAME, 'Unknown')
),
warehouse_pressure_ranked AS (
    SELECT WAREHOUSE_NAME, QUERIES, QUEUED_MS, SPILL_BYTES, P95_EXECUTION_MS,
           ROW_NUMBER() OVER (
               ORDER BY QUEUED_MS DESC, SPILL_BYTES DESC, P95_EXECUTION_MS DESC, WAREHOUSE_NAME
           ) AS RN
    FROM warehouse_pressure
)
SELECT 'KPI' AS PANEL, 'Total Queries' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(SUM(QUERIES), 0)::FLOAT AS VALUE, NULL::FLOAT AS VALUE_USD, 'queries' AS UNIT, 4 AS SORT_ORDER
FROM query_daily
UNION ALL
SELECT 'KPI', 'Avg Runtime', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(SUM(ELAPSED_MS) / NULLIF(SUM(QUERIES), 0) / 1000, 0), NULL::FLOAT, 'seconds', 5
FROM query_daily
UNION ALL
SELECT 'KPI', 'P95 Runtime', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(MAX(P95_EXECUTION_MS) / 1000, 0), NULL::FLOAT, 'seconds', 6
FROM query_daily
UNION ALL
SELECT 'KPI', 'Queue Time', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(SUM(QUEUED_MS) / 1000, 0), NULL::FLOAT, 'seconds', 7
FROM query_daily
UNION ALL
SELECT 'KPI', 'Remote Spill', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(SUM(SPILL_BYTES) / POWER(1024, 3), 0), NULL::FLOAT, 'gb', 8
FROM query_daily
UNION ALL
SELECT 'KPI', 'Failed Queries', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(SUM(FAILED_QUERIES), 0), NULL::FLOAT, 'queries', 9
FROM query_daily
UNION ALL
SELECT 'DAILY_WORKLOAD', 'Avg Runtime', TO_VARCHAR(USAGE_DATE), TO_TIMESTAMP_NTZ(USAGE_DATE),
       COALESCE(ELAPSED_MS / NULLIF(QUERIES, 0) / 1000, 0), NULL::FLOAT, 'seconds', 301
FROM query_daily
UNION ALL
SELECT 'DAILY_WORKLOAD', 'P95 Runtime', TO_VARCHAR(USAGE_DATE), TO_TIMESTAMP_NTZ(USAGE_DATE),
       COALESCE(P95_EXECUTION_MS / 1000, 0), NULL::FLOAT, 'seconds', 302
FROM query_daily
UNION ALL
SELECT 'DAILY_WORKLOAD', 'Queue Seconds', TO_VARCHAR(USAGE_DATE), TO_TIMESTAMP_NTZ(USAGE_DATE),
       COALESCE(QUEUED_MS / 1000, 0), NULL::FLOAT, 'seconds', 303
FROM query_daily
UNION ALL
SELECT 'QUERY_TYPE', 'Queries by Type', QUERY_TYPE, NULL::TIMESTAMP_NTZ,
       QUERIES, NULL::FLOAT, 'queries', 401
FROM query_type_ranked
WHERE RN <= 8
UNION ALL
SELECT 'QUERY_DATABASE', 'Queries by Database', DATABASE_NAME, NULL::TIMESTAMP_NTZ,
       QUERIES, NULL::FLOAT, 'queries', 451
FROM query_database_ranked
WHERE RN <= 8
UNION ALL
SELECT 'WAREHOUSE_PRESSURE', 'Queue Seconds', WAREHOUSE_NAME, NULL::TIMESTAMP_NTZ,
       COALESCE(QUEUED_MS / 1000, 0), NULL::FLOAT, 'seconds', 501
FROM warehouse_pressure_ranked
WHERE RN <= 8
UNION ALL
SELECT 'WAREHOUSE_PRESSURE', 'Remote Spill GB', WAREHOUSE_NAME, NULL::TIMESTAMP_NTZ,
       COALESCE(SPILL_BYTES / POWER(1024, 3), 0), NULL::FLOAT, 'gb', 502
FROM warehouse_pressure_ranked
WHERE RN <= 8
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Query facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 902
FROM query_daily
"""

    execution_status_sql = f"""
WITH status_ranked AS (
    SELECT
        COALESCE(EXECUTION_STATUS, 'Unknown') AS EXECUTION_STATUS,
        COUNT(*) AS QUERIES,
        MAX(LOAD_TS) AS LOAD_TS,
        ROW_NUMBER() OVER (
            ORDER BY COUNT(*) DESC, COALESCE(EXECUTION_STATUS, 'Unknown')
        ) AS RN
    FROM {query_detail_table}
    WHERE START_TIME >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY COALESCE(EXECUTION_STATUS, 'Unknown')
)
SELECT 'EXEC_STATUS' AS PANEL, 'Execution Status' AS METRIC, EXECUTION_STATUS AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       QUERIES::FLOAT AS VALUE, NULL::FLOAT AS VALUE_USD, 'queries' AS UNIT, 461 AS SORT_ORDER
FROM status_ranked
WHERE RN <= 8
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Query detail facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 908
FROM status_ranked
"""

    task_sql = f"""
WITH task_rollup AS (
    SELECT
        COUNT(*) AS TASK_RUNS,
        COUNT_IF(UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR')) AS FAILED_TASKS,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {task_table}
    WHERE SCHEDULED_TIME >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
)
SELECT 'KPI' AS PANEL, 'Failed Tasks' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(MAX(FAILED_TASKS), 0)::FLOAT AS VALUE, NULL::FLOAT AS VALUE_USD, 'tasks' AS UNIT, 10 AS SORT_ORDER
FROM task_rollup
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Task facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 903
FROM task_rollup
"""

    storage_sql = f"""
WITH storage_rollup AS (
    SELECT
        SUM(COALESCE(EST_STORAGE_TB, 0)) AS STORAGE_TB,
        SUM(COALESCE(EST_COST_USD, 0)) AS STORAGE_COST_USD,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {storage_table}
    WHERE SNAPSHOT_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE())
      {company_clause}
      {env_clause}
)
SELECT 'KPI' AS PANEL, 'Storage' AS METRIC, 'Current snapshot' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(MAX(STORAGE_TB), 0)::FLOAT AS VALUE, COALESCE(MAX(STORAGE_COST_USD), 0)::FLOAT AS VALUE_USD, 'tb_usd' AS UNIT, 13 AS SORT_ORDER
FROM storage_rollup
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Storage facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 905
FROM storage_rollup
"""

    control_sql = f"""
WITH control_latest AS (
    SELECT *
    FROM {control_table}
    WHERE SNAPSHOT_TS >= DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
      {company_clause}
    QUALIFY ROW_NUMBER() OVER (PARTITION BY COMPANY ORDER BY SNAPSHOT_TS DESC) = 1
)
SELECT 'KPI' AS PANEL, 'Platform Health' AS METRIC, 'Latest control room' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(MAX(HEALTH_SCORE), 0)::FLOAT AS VALUE, NULL::FLOAT AS VALUE_USD, 'score' AS UNIT, 14 AS SORT_ORDER
FROM control_latest
"""

    alert_sql = f"""
SELECT 'KPI' AS PANEL, 'Critical High Alerts' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(COUNT_IF(UPPER(COALESCE(SEVERITY, '')) IN ('CRITICAL', 'HIGH')
           AND UPPER(COALESCE(STATUS, 'NEW')) NOT IN ('RESOLVED', 'FIXED', 'IGNORED', 'CLOSED')), 0)::FLOAT AS VALUE,
       NULL::FLOAT AS VALUE_USD, 'alerts' AS UNIT, 11 AS SORT_ORDER
FROM {alert_table}
WHERE EVENT_TS >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
"""

    queue_sql = f"""
SELECT 'KPI' AS PANEL, 'Open Actions' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(COUNT_IF(UPPER(COALESCE(STATUS, 'NEW')) NOT IN ('FIXED', 'IGNORED', 'CLOSED', 'RESOLVED')), 0)::FLOAT AS VALUE,
       NULL::FLOAT AS VALUE_USD, 'actions' AS UNIT, 12 AS SORT_ORDER
FROM {queue_table}
WHERE CREATED_AT >= DATEADD('DAY', -{days * 2}, CURRENT_TIMESTAMP())
  {company_clause}
"""

    return [
        ("cost", "Cost facts", cost_sql),
        ("cortex", "Cortex facts", cortex_sql),
        ("query", "Query performance facts", query_sql),
        ("query_detail", "Query detail facts", execution_status_sql),
        ("task", "Task facts", task_sql),
        ("storage", "Storage facts", storage_sql),
        ("control", "Platform health facts", control_sql),
        ("alert", "Alert events", alert_sql),
        ("queue", "Action queue", queue_sql),
    ]


def _load_executive_observability_from_parts(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
    ai_credit_price: float,
    initial_statuses: list[dict] | None = None,
) -> bool:
    frames: list[pd.DataFrame] = []
    statuses = list(initial_statuses or [])
    for key, label, sql in _build_executive_observability_query_parts(
        company,
        environment,
        int(days),
        credit_price=credit_price,
        ai_credit_price=ai_credit_price,
    ):
        try:
            frame = run_query(
                sql,
                ttl_key=f"executive_observability_part_{key}_{company}_{environment}_{int(days)}",
                tier="recent",
                section="Executive Landing",
            )
            normalised = _normalise_observability_frame(frame)
            frames.append(normalised)
            statuses.append({
                "source": label,
                "state": "Loaded" if not normalised.empty else "No Rows",
                "detail": (
                    f"{len(normalised):,} summary row(s) loaded."
                    if not normalised.empty else "No rows for this scope."
                ),
            })
        except Exception as exc:
            statuses.append({
                "source": label,
                "state": "Unavailable",
                "detail": format_snowflake_error(exc),
            })
    frames.append(_observability_status_frame(statuses))
    board = pd.concat(frames, ignore_index=True) if frames else _observability_status_frame(statuses)
    return _store_observability_payload(
        board,
        company=company,
        environment=environment,
        days=int(days),
        source="Executive monitoring facts",
        error="" if any(status.get("state") == "Loaded" for status in statuses) else "No executive fact sources loaded.",
    )


def _load_executive_observability(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
) -> bool:
    ai_credit_price = safe_float(st.session_state.get("ai_credit_price", DEFAULTS.get("ai_credit_price", 2.20)), 2.20)
    try:
        board = run_query(
            _build_executive_observability_sql(
                company,
                environment,
                int(days),
                credit_price=credit_price,
                ai_credit_price=ai_credit_price,
            ),
            ttl_key=f"executive_observability_{company}_{environment}_{int(days)}",
            tier="recent",
            section="Executive Landing",
        )
        normalised = _normalise_observability_frame(board)
        mart_status = {
            "source": "MART_EXECUTIVE_OBSERVABILITY",
            "state": "Loaded" if not normalised.empty else "No Rows",
            "detail": (
                f"{len(normalised):,} summary row(s) loaded from the executive observability mart."
                if not normalised.empty
                else "The executive observability mart returned no rows for this scope."
            ),
        }
        if not _obs_rows(normalised, "KPI").empty:
            return _store_observability_payload(
                pd.concat([normalised, _observability_status_frame([mart_status])], ignore_index=True),
                company=company,
                environment=environment,
                days=int(days),
                source="MART_EXECUTIVE_OBSERVABILITY",
                error="",
            )
        return _load_executive_observability_from_parts(
            company,
            environment,
            int(days),
            credit_price=credit_price,
            ai_credit_price=ai_credit_price,
            initial_statuses=[mart_status],
        )
    except Exception as exc:
        detail = format_snowflake_error(exc)
        return _load_executive_observability_from_parts(
            company,
            environment,
            int(days),
            credit_price=credit_price,
            ai_credit_price=ai_credit_price,
            initial_statuses=[{
                "source": "MART_EXECUTIVE_OBSERVABILITY",
                "state": "Unavailable",
                "detail": detail,
            }],
        )


def _current_observability_board(company: str, environment: str, days: int) -> tuple[pd.DataFrame, dict]:
    payload = st.session_state.get(OBSERVABILITY_STATE_KEY)
    if not isinstance(payload, dict):
        return pd.DataFrame(), {}
    if payload.get("scope") != _observability_scope(company, environment, int(days)):
        return pd.DataFrame(), {}
    data = payload.get("data")
    return (data if isinstance(data, pd.DataFrame) else pd.DataFrame()), payload


def _observability_payload_is_offline(payload: dict) -> bool:
    return isinstance(payload, dict) and payload.get("source") == OBSERVABILITY_OFFLINE_SOURCE


def _executive_observability_autoload_allowed() -> bool:
    return (
        st.session_state.get("_overwatch_connection_available") is True
        and not snowflake_connection_known_unavailable()
    )


def _obs_rows(board: pd.DataFrame, panel: str, metric: str | None = None) -> pd.DataFrame:
    if not isinstance(board, pd.DataFrame) or board.empty or "PANEL" not in board.columns:
        return pd.DataFrame()
    rows = board[board["PANEL"].astype(str).eq(panel)].copy()
    if metric and "METRIC" in rows.columns:
        rows = rows[rows["METRIC"].astype(str).eq(metric)].copy()
    return rows


def _obs_value(board: pd.DataFrame, metric: str, *, column: str = "VALUE", default: float = 0.0) -> float:
    rows = _obs_rows(board, "KPI", metric)
    if rows.empty or column not in rows.columns:
        return default
    return safe_float(rows.iloc[0].get(column), default)


def _format_seconds(value: float) -> str:
    seconds = safe_float(value)
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


def _format_gb(value: float) -> str:
    gb = safe_float(value)
    if gb >= 1024:
        return f"{gb / 1024:.1f} TB"
    return f"{gb:.1f} GB"


def _format_metric_value(value: float, unit: str) -> str:
    unit_key = str(unit or "").lower()
    if "usd" in unit_key:
        return _money(safe_float(value))
    if unit_key == "seconds":
        return _format_seconds(value)
    if unit_key == "gb":
        return _format_gb(value)
    if unit_key == "score":
        return _platform_score_state(value)
    if unit_key in {"queries", "tasks", "alerts", "actions"}:
        return f"{safe_int(value):,}"
    if unit_key == "tb_usd":
        return f"{safe_float(value):,.2f} TB"
    return f"{safe_float(value):,.2f}"


def _has_observability_kpis(board: pd.DataFrame) -> bool:
    return not _obs_rows(board, "KPI").empty


def _obs_metric_loaded(board: pd.DataFrame, metric: str) -> bool:
    return not _obs_rows(board, "KPI", metric).empty


def _obs_money_label(board: pd.DataFrame, metric: str, *, column: str = "VALUE_USD", signed: bool = False) -> str:
    if not _obs_metric_loaded(board, metric):
        return "On demand"
    return _money(_obs_value(board, metric, column=column), signed=signed)


def _obs_count_label(board: pd.DataFrame, metric: str) -> str:
    if not _obs_metric_loaded(board, metric):
        return "On demand"
    return f"{safe_int(_obs_value(board, metric)):,}"


def _state_payload(state: dict | None = None):
    return st.session_state if state is None else state


def _state_frame(state: dict | None, key: str) -> pd.DataFrame:
    value = _state_payload(state).get(key)
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, list):
        return pd.DataFrame(value)
    if isinstance(value, dict):
        return pd.DataFrame([value])
    return pd.DataFrame()


def _sum_first_numeric(frame: pd.DataFrame, columns: list[str]) -> float:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return 0.0
    upper_lookup = {str(column).upper(): column for column in frame.columns}
    for column in columns:
        actual = upper_lookup.get(str(column).upper())
        if actual:
            return safe_float(pd.to_numeric(frame[actual], errors="coerce").fillna(0).sum())
    return 0.0


def _count_high_priority(frame: pd.DataFrame) -> int:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return 0
    for column in ("SEVERITY", "PRIORITY", "OPTIMIZATION_SEVERITY", "STATE"):
        if column in frame.columns:
            values = frame[column].fillna("").astype(str).str.upper()
            return int(values.isin(["CRITICAL", "HIGH", "ESCALATE", "INCIDENT", "BLOCKED"]).sum())
    return 0


def _advisor_state_label(high_count: int, finding_count: int, *, default: str = "Loaded") -> str:
    if safe_int(high_count) > 0:
        return "Review"
    if safe_int(finding_count) > 0:
        return default
    return "No rows"


def _append_advisor_row(
    rows: list[dict],
    *,
    lane: str,
    findings: int,
    high_findings: int = 0,
    estimated_savings: float = 0.0,
    value_at_risk: float = 0.0,
    signal: str,
    next_action: str,
    route: str,
    priority: int = 8,
    state: str | None = None,
) -> None:
    findings = safe_int(findings)
    if findings <= 0:
        return
    high_findings = safe_int(high_findings)
    estimated_savings = safe_float(estimated_savings)
    value_at_risk = safe_float(value_at_risk)
    rows.append({
        "PRIORITY": safe_int(priority, 8),
        "LANE": lane,
        "STATE": state or _advisor_state_label(high_findings, findings),
        "VALUE": (
            f"{findings:,} finding(s); {_money(estimated_savings)}/mo est. savings"
            if estimated_savings > 0
            else f"{findings:,} finding(s)"
        ),
        "FINDINGS": findings,
        "HIGH_FINDINGS": high_findings,
        "EST_MONTHLY_SAVINGS_USD": round(estimated_savings, 2),
        "VALUE_AT_RISK_USD": round(value_at_risk, 2),
        "ADVISOR_SIGNAL": signal,
        "NEXT_ACTION": next_action,
        "ROUTE": route,
    })


def _executive_loaded_advisor_rows(state: dict | None = None) -> pd.DataFrame:
    """Summarize already-loaded advisor/recommendation frames without querying Snowflake."""
    rows: list[dict] = []

    cost_board = _state_frame(state, "cost_contract_cost_advisor_board")
    if not cost_board.empty:
        findings = len(cost_board)
        high = _count_high_priority(cost_board)
        savings = _sum_first_numeric(cost_board, ["EST_MONTHLY_SAVINGS_USD", "Estimated Monthly Savings"])
        value_at_risk = _sum_first_numeric(cost_board, ["EST_MONTHLY_IMPACT_USD", "VALUE_AT_RISK_USD"])
        category = str(cost_board.iloc[0].get("CATEGORY") or "loaded cost advisor finding")
        entity = str(cost_board.iloc[0].get("ENTITY") or "loaded entity")
        _append_advisor_row(
            rows,
            lane="Cost Advisor",
            findings=findings,
            high_findings=high,
            estimated_savings=savings,
            value_at_risk=value_at_risk,
            signal=f"{high:,} high-priority; {_money(value_at_risk)} value at risk; top row: {category} / {entity}.",
            next_action="Open Cost & Contract recommendations and work the highest telemetry-backed cost row first.",
            route="Cost & Contract",
            priority=3 if high else 6,
        )

    recs = _state_frame(state, "rec_recommendations")
    if not recs.empty:
        high = _count_high_priority(recs)
        savings = _sum_first_numeric(
            recs,
            ["Estimated Monthly Savings", "EST_MONTHLY_SAVINGS_USD", "MONTHLY_SAVINGS_USD"],
        )
        categories = (
            ", ".join(sorted({str(value) for value in recs.get("Category", pd.Series(dtype=str)).dropna()})[:4])
            if "Category" in recs.columns
            else "recommendations"
        )
        _append_advisor_row(
            rows,
            lane="Recommendation Feed",
            findings=len(recs),
            high_findings=high,
            estimated_savings=savings,
            signal=f"{len(recs):,} generated recommendation(s) across {categories}.",
            next_action="Open Cost & Contract recommendations and confirm owner, validation, and safe next action before assignment.",
            route="Cost & Contract",
            priority=4 if high else 7,
        )

    idle = _state_frame(state, "opt_df_idle")
    duplicate = _state_frame(state, "opt_df_dup")
    sizing = _state_frame(state, "opt_df_sz")
    capacity_exceptions = _state_frame(state, "wh_capacity_exceptions")
    settings_inventory = _state_frame(state, "wh_settings_inventory")
    rec_setting_plan = _state_frame(state, "rec_warehouse_control_plan")
    warehouse_advisor = _state_frame(state, "rec_warehouse_advisor_recommendations")
    warehouse_findings = (
        len(idle)
        + len(duplicate)
        + len(sizing)
        + len(capacity_exceptions)
        + len(rec_setting_plan)
        + len(warehouse_advisor)
    )
    if warehouse_findings:
        idle_credits = _sum_first_numeric(idle, ["IDLE_CREDITS"])
        total_credits = _sum_first_numeric(sizing, ["TOTAL_CREDITS"])
        advisor_savings = _sum_first_numeric(warehouse_advisor, ["EST_MONTHLY_SAVINGS_USD", "Estimated Monthly Savings"])
        savings = (
            advisor_savings
            if advisor_savings
            else credits_to_dollars((idle_credits / 7.0 * 30.0), _credit_price()) if idle_credits else 0.0
        )
        spill = _sum_first_numeric(sizing, ["REMOTE_SPILL_GB"]) + _sum_first_numeric(capacity_exceptions, ["REMOTE_SPILL_GB"])
        queue = _sum_first_numeric(sizing, ["AVG_QUEUE_SEC", "QUEUE_SECONDS"]) + _sum_first_numeric(capacity_exceptions, ["QUEUE_SECONDS"])
        pressure_count = 0
        if not sizing.empty:
            spill_series = pd.to_numeric(sizing.get("REMOTE_SPILL_GB", pd.Series([0] * len(sizing))), errors="coerce").fillna(0)
            queue_series = pd.to_numeric(sizing.get("AVG_QUEUE_SEC", pd.Series([0] * len(sizing))), errors="coerce").fillna(0)
            pressure_count += int(((spill_series >= 10) | (queue_series >= 600)).sum())
        high = max(_count_high_priority(capacity_exceptions), _count_high_priority(warehouse_advisor), pressure_count)
        inventory_note = f"; {len(settings_inventory):,} warehouse setting row(s) loaded" if not settings_inventory.empty else ""
        advisor_note = f"; {len(warehouse_advisor):,} advisor recommendation(s)" if not warehouse_advisor.empty else ""
        control_note = f"; {len(rec_setting_plan):,} guardrail finding(s)" if not rec_setting_plan.empty else ""
        _append_advisor_row(
            rows,
            lane="Warehouse Optimization",
            findings=warehouse_findings,
            high_findings=high,
            estimated_savings=savings,
            value_at_risk=credits_to_dollars(total_credits, _credit_price()) if total_credits else 0.0,
            signal=(
                f"{len(idle):,} idle, {len(duplicate):,} repeated-query, {len(sizing):,} sizing, "
                f"{len(capacity_exceptions):,} capacity exception row(s); {_format_gb(spill)} spill, "
                f"{_format_seconds(queue)} queue{inventory_note}{advisor_note}{control_note}."
            ),
            next_action="Open Cost & Contract warehouse advisor, then execute any approved change through DBA Control Room Admin.",
            route="Cost & Contract",
            priority=3 if high else 6,
        )

    procedure_exceptions = pd.concat(
        [
            _state_frame(state, "sp_sla_exceptions"),
            _state_frame(state, "sp_ops_exceptions"),
        ],
        ignore_index=True,
        sort=False,
    )
    procedure_latest = _state_frame(state, "sp_sla_latest")
    procedure_cost = _state_frame(state, "spt_df_sp_tracker")
    procedure_analysis = _state_frame(state, "sp_analysis_board")
    procedure_optimization = 0
    if not procedure_cost.empty and "OPTIMIZATION_SCORE" in procedure_cost.columns:
        scores = pd.to_numeric(procedure_cost["OPTIMIZATION_SCORE"], errors="coerce").fillna(0)
        procedure_optimization = int((scores > 0).sum())
    procedure_analysis_findings = len(procedure_analysis)
    procedure_findings = len(procedure_exceptions) + procedure_optimization + procedure_analysis_findings
    if procedure_findings:
        high = max(_count_high_priority(procedure_exceptions), _count_high_priority(procedure_analysis))
        cost_estimate = _sum_first_numeric(procedure_cost, ["EST_COST", "ESTIMATED_COST_USD", "EST_COST_USD"])
        runtime = _sum_first_numeric(procedure_cost, ["TOTAL_ELAPSED_SEC", "TOTAL_ELAPSED_SECONDS"])
        _append_advisor_row(
            rows,
            lane="Stored Procedure Advisor",
            findings=procedure_findings,
            high_findings=high,
            value_at_risk=cost_estimate,
            signal=(
                f"{len(procedure_exceptions):,} SLA/cost exception row(s), "
                f"{procedure_analysis_findings:,} analysis signal(s), "
                f"{procedure_optimization:,} optimization candidate(s), {len(procedure_latest):,} latest run row(s), "
                f"{_format_seconds(runtime)} tracked runtime."
            ),
            next_action="Open Workload Operations > Stored procedures and review procedure SLA/cost exceptions before reruns or tuning.",
            route="Workload Operations",
            priority=2 if high else 5,
        )

    storage_tables = _state_frame(state, "stor_df_table_metrics")
    storage_db = _state_frame(state, "stor_df_db_detail")
    if not storage_tables.empty or not storage_db.empty:
        time_travel_gb = _sum_first_numeric(storage_tables, ["TIME_TRAVEL_GB"])
        failsafe_gb = _sum_first_numeric(storage_tables, ["FAILSAFE_GB"]) + _sum_first_numeric(storage_db, ["FAILSAFE_GB"])
        storage_cost = _sum_first_numeric(storage_db, ["EST_COST_USD", "EST_MONTHLY_COST", "MONTHLY_COST_USD"])
        findings = len(storage_tables) + len(storage_db)
        _append_advisor_row(
            rows,
            lane="Storage Retention",
            findings=findings,
            estimated_savings=0.0,
            value_at_risk=storage_cost,
            signal=(
                f"{len(storage_tables):,} table storage row(s), {len(storage_db):,} database row(s), "
                f"{time_travel_gb:,.1f} GB time-travel, {failsafe_gb:,.1f} GB failsafe."
            ),
            next_action="Open Storage cost and retention, then confirm recovery and compliance windows before retention changes.",
            route="Cost & Contract",
            priority=7,
            state="Track",
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(
            columns=[
                "PRIORITY", "LANE", "STATE", "VALUE", "FINDINGS", "HIGH_FINDINGS",
                "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD", "ADVISOR_SIGNAL", "NEXT_ACTION", "ROUTE",
            ]
        )
    return out.sort_values(
        ["PRIORITY", "HIGH_FINDINGS", "EST_MONTHLY_SAVINGS_USD", "FINDINGS"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def _advisor_overlay_totals(rows: pd.DataFrame | None) -> dict:
    if not isinstance(rows, pd.DataFrame) or rows.empty:
        return {
            "advisor_lanes": 0,
            "advisor_findings": 0,
            "advisor_high_findings": 0,
            "advisor_estimated_monthly_savings_usd": 0.0,
            "advisor_value_at_risk_usd": 0.0,
        }
    return {
        "advisor_lanes": int(len(rows)),
        "advisor_findings": safe_int(pd.to_numeric(rows.get("FINDINGS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "advisor_high_findings": safe_int(pd.to_numeric(rows.get("HIGH_FINDINGS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "advisor_estimated_monthly_savings_usd": safe_float(
            pd.to_numeric(rows.get("EST_MONTHLY_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
        ),
        "advisor_value_at_risk_usd": safe_float(
            pd.to_numeric(rows.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
        ),
    }


def _render_observability_source_status(board: pd.DataFrame) -> None:
    statuses = _obs_rows(board, "SOURCE_STATUS")
    if not isinstance(statuses, pd.DataFrame) or statuses.empty:
        return
    rows = statuses[["DIMENSION", "METRIC", "UNIT"]].copy()
    rows = rows.rename(columns={"DIMENSION": "INPUT", "METRIC": "STATE", "UNIT": "DETAIL"})
    loaded = int(rows["STATE"].astype(str).eq("Loaded").sum()) if "STATE" in rows.columns else 0
    unavailable = int(rows["STATE"].astype(str).eq("Unavailable").sum()) if "STATE" in rows.columns else 0
    no_rows = int(rows["STATE"].astype(str).eq("No Rows").sum()) if "STATE" in rows.columns else 0
    with st.expander(
        f"Executive summary input status: {loaded} loaded, {unavailable} unavailable, {no_rows} no rows",
        expanded=unavailable > 0 and loaded == 0,
    ):
        render_priority_dataframe(
            rows,
            title="Executive summary input status",
            priority_columns=["INPUT", "STATE", "DETAIL"],
            sort_by=["STATE", "INPUT"],
            ascending=[True, True],
            raw_label="All executive summary input rows",
            height=260,
            max_rows=12,
        )


def _summary_from_observability(board: pd.DataFrame, *, credit_price: float, state: dict | None = None) -> dict | None:
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
        return None
    current_credits = _obs_value(board, "Credits Used")
    cost_delta = _obs_value(board, "Spend Delta")
    critical_high = safe_int(_obs_value(board, "Critical High Alerts"))
    open_actions = safe_int(_obs_value(board, "Open Actions"))
    failed_tasks = safe_int(_obs_value(board, "Failed Tasks"))
    failed_queries = safe_int(_obs_value(board, "Failed Queries"))
    score = _obs_value(board, "Platform Health", default=0)
    prior_credits = max(0.0, current_credits - cost_delta)
    advisor_rows = _executive_loaded_advisor_rows(state)
    advisor_totals = _advisor_overlay_totals(advisor_rows)
    summary = {
        "current_credits": current_credits,
        "prior_credits": prior_credits,
        "cost_delta": cost_delta,
        "top_increase_credits": max(cost_delta, 0.0),
        "critical_high_alerts": critical_high,
        "open_actions": open_actions,
        "high_actions": critical_high,
        "migration_blockers": 0,
        "top_cost_driver": "Account spend",
    }
    summary.update(advisor_totals)
    scored = _with_platform_operating_score(summary, pd.DataFrame([
        {"SOURCE": "Executive observability facts", "STATE": "Loaded", "EVIDENCE": "Monitoring summary rows loaded."}
    ]))
    if score > 0:
        scored["score"] = safe_int(score)
        scored["raw_score"] = safe_float(score)
        scored["state"] = _platform_score_state(score)
    scored["failed_tasks"] = failed_tasks
    scored["failed_queries"] = failed_queries
    scored["current_spend_usd"] = _obs_value(board, "Credits Used", column="VALUE_USD", default=credits_to_dollars(current_credits, credit_price))
    scored["cortex_spend_usd"] = _obs_value(board, "Cortex Spend", column="VALUE_USD")
    scored["spill_gb"] = _obs_value(board, "Remote Spill")
    scored["avg_runtime_sec"] = _obs_value(board, "Avg Runtime")
    scored["p95_runtime_sec"] = _obs_value(board, "P95 Runtime")
    return scored


def _executive_priority_rows(
    board: pd.DataFrame,
    *,
    days: int,
    advisor_rows: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Convert the loaded KPI board into the first decisions leadership cares about."""
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
        if isinstance(advisor_rows, pd.DataFrame) and not advisor_rows.empty:
            rows = []
            for _, row in advisor_rows.head(6).iterrows():
                rows.append({
                    "PRIORITY": safe_int(row.get("PRIORITY"), 5),
                    "LANE": str(row.get("LANE") or "Loaded advisor"),
                    "STATE": str(row.get("STATE") or "Review"),
                    "SIGNAL": str(row.get("ADVISOR_SIGNAL") or row.get("VALUE") or "Loaded advisor finding."),
                    "BUSINESS_IMPACT": (
                        f"{safe_int(row.get('FINDINGS')):,} finding(s); "
                        f"{_money(safe_float(row.get('EST_MONTHLY_SAVINGS_USD')))}/mo estimated savings where quantified."
                    ),
                    "NEXT_ACTION": str(row.get("NEXT_ACTION") or "Open the owning monitoring section."),
                    "ROUTE": str(row.get("ROUTE") or "Cost & Contract"),
                })
            return pd.DataFrame(rows).sort_values(["PRIORITY", "LANE"]).reset_index(drop=True)
        return pd.DataFrame(
            columns=["PRIORITY", "LANE", "STATE", "SIGNAL", "BUSINESS_IMPACT", "NEXT_ACTION", "ROUTE"]
        )

    current_spend = _obs_value(board, "Credits Used", column="VALUE_USD")
    spend_delta = _obs_value(board, "Spend Delta", column="VALUE_USD")
    cortex_spend = _obs_value(board, "Cortex Spend", column="VALUE_USD")
    queries = safe_int(_obs_value(board, "Total Queries"))
    p95_runtime = _obs_value(board, "P95 Runtime")
    queue_seconds = _obs_value(board, "Queue Time")
    spill_gb = _obs_value(board, "Remote Spill")
    failed_queries = safe_int(_obs_value(board, "Failed Queries"))
    failed_tasks = safe_int(_obs_value(board, "Failed Tasks"))
    critical_high = safe_int(_obs_value(board, "Critical High Alerts"))
    open_actions = safe_int(_obs_value(board, "Open Actions"))
    storage_tb = _obs_value(board, "Storage")
    month_end = current_spend / max(int(days), 1) * 30.0

    rows = [
        {
            "PRIORITY": 1 if critical_high else 6,
            "LANE": "Open risk",
            "STATE": "Escalate" if critical_high else "Clear",
            "SIGNAL": f"{critical_high:,} Critical/High alert(s), {open_actions:,} open owner action(s).",
            "BUSINESS_IMPACT": "Security, reliability, or cost issue may already be visible to leadership.",
            "NEXT_ACTION": "Open Alert Center and work route, SLA, and remediation status.",
            "ROUTE": "Alert Center",
        },
        {
            "PRIORITY": 2 if spend_delta > 0 else 7,
            "LANE": "Cost movement",
            "STATE": "Review" if spend_delta > 0 else "Stable",
            "SIGNAL": f"{_money(current_spend)} spend, {_money(spend_delta, signed=True)} vs prior, {_money(month_end)} 30d pace.",
            "BUSINESS_IMPACT": "Finance will ask why the bill moved and whether contract burn is changing.",
            "NEXT_ACTION": "Open Cost & Contract and explain the top service or warehouse driver first.",
            "ROUTE": "Cost & Contract",
        },
        {
            "PRIORITY": 3 if failed_tasks else 8,
            "LANE": "Pipeline reliability",
            "STATE": "Recover" if failed_tasks else "Clear",
            "SIGNAL": f"{failed_tasks:,} failed task(s) in the selected window.",
            "BUSINESS_IMPACT": "Late or failed task graphs can break reporting and downstream data freshness.",
            "NEXT_ACTION": "Open Workload Operations and inspect task graph, error, owner, and next run.",
            "ROUTE": "Workload Operations",
        },
        {
            "PRIORITY": 4 if failed_queries or queue_seconds or spill_gb else 9,
            "LANE": "Performance pressure",
            "STATE": "Tune" if failed_queries or queue_seconds or spill_gb else "Normal",
            "SIGNAL": (
                f"{failed_queries:,} failed query(s), {_format_seconds(queue_seconds)} queued, "
                f"{_format_gb(spill_gb)} remote spill, p95 {_format_seconds(p95_runtime)}."
            ),
            "BUSINESS_IMPACT": "Slow or failing workloads burn credits and delay business reporting.",
            "NEXT_ACTION": "Open DBA Control Room or Workload Operations before resizing warehouses.",
            "ROUTE": "DBA Control Room",
        },
        {
            "PRIORITY": 5 if cortex_spend else 10,
            "LANE": "AI / Cortex spend",
            "STATE": "Watch" if cortex_spend else "No spend",
            "SIGNAL": f"{_money(cortex_spend)} Cortex spend across {queries:,} total query events.",
            "BUSINESS_IMPACT": "AI usage can grow quickly without owner, quota, and access guardrails.",
            "NEXT_ACTION": "Open Cost & Contract AI spend and validate top user/source before controls.",
            "ROUTE": "Cost & Contract",
        },
        {
            "PRIORITY": 11,
            "LANE": "Storage footprint",
            "STATE": "Track" if storage_tb else "No data",
            "SIGNAL": f"{safe_float(storage_tb):,.2f} TB currently represented in the summary.",
            "BUSINESS_IMPACT": "Storage/failsafe/stage growth becomes a contract and cleanup problem if ignored.",
            "NEXT_ACTION": "Open Cost & Contract storage when growth or retention is questioned.",
            "ROUTE": "Cost & Contract",
        },
    ]
    out = pd.DataFrame(rows)
    if isinstance(advisor_rows, pd.DataFrame) and not advisor_rows.empty:
        advisor_view = advisor_rows.copy()
        for _, row in advisor_view.head(6).iterrows():
            out = pd.concat(
                [
                    out,
                    pd.DataFrame([{
                        "PRIORITY": min(5, safe_int(row.get("PRIORITY"), 5)),
                        "LANE": str(row.get("LANE") or "Loaded advisor"),
                        "STATE": str(row.get("STATE") or "Review"),
                        "SIGNAL": str(row.get("ADVISOR_SIGNAL") or row.get("VALUE") or "Loaded advisor finding."),
                        "BUSINESS_IMPACT": (
                            f"{safe_int(row.get('FINDINGS')):,} finding(s); "
                            f"{_money(safe_float(row.get('EST_MONTHLY_SAVINGS_USD')))}/mo estimated savings where quantified."
                        ),
                        "NEXT_ACTION": str(row.get("NEXT_ACTION") or "Open the owning monitoring section."),
                        "ROUTE": str(row.get("ROUTE") or "Cost & Contract"),
                    }])
                ],
                ignore_index=True,
                sort=False,
            )
    return out.sort_values(["PRIORITY", "LANE"]).reset_index(drop=True)


def _render_executive_priority_board(board: pd.DataFrame, *, days: int, advisor_rows: pd.DataFrame | None = None) -> None:
    rows = _executive_priority_rows(board, days=int(days), advisor_rows=advisor_rows)
    if rows.empty:
        return
    render_priority_dataframe(
        rows,
        title="Executive signals to work first",
        priority_columns=[
            "PRIORITY", "LANE", "STATE", "SIGNAL",
            "BUSINESS_IMPACT", "NEXT_ACTION", "ROUTE",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All executive priority rows",
        height=300,
        max_rows=12,
    )


def _executive_pressure_rows(board: pd.DataFrame, advisor_rows: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return one-page pressure lanes from the compact executive mart."""
    columns = [
        "LANE", "STATE", "VALUE", "PRESSURE_SCORE", "WHY_IT_MATTERS",
        "OWNER_ROUTE", "NEXT_ACTION",
    ]
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
        if isinstance(advisor_rows, pd.DataFrame) and not advisor_rows.empty:
            totals = _advisor_overlay_totals(advisor_rows)
            return pd.DataFrame([{
                "LANE": "Advisor backlog",
                "STATE": "Review" if totals["advisor_high_findings"] else "Loaded",
                "VALUE": (
                    f"{totals['advisor_findings']:,} finding(s); "
                    f"{_money(totals['advisor_estimated_monthly_savings_usd'])}/mo savings"
                ),
                "PRESSURE_SCORE": min(
                    totals["advisor_high_findings"] * 15.0
                    + totals["advisor_findings"] * 2.0
                    + totals["advisor_value_at_risk_usd"] / 2500.0,
                    100.0,
                ),
                "WHY_IT_MATTERS": "Loaded advisors identify avoidable cost, warehouse pressure, storage retention, and procedure work.",
                "OWNER_ROUTE": "Cost & Contract",
                "NEXT_ACTION": "Open the highest-priority advisor row before assigning or tuning work.",
            }], columns=columns)
        return pd.DataFrame(columns=columns)

    current_spend = _obs_value(board, "Credits Used", column="VALUE_USD")
    spend_delta = _obs_value(board, "Spend Delta", column="VALUE_USD")
    cortex_spend = _obs_value(board, "Cortex Spend", column="VALUE_USD")
    queue_seconds = _obs_value(board, "Queue Time")
    spill_gb = _obs_value(board, "Remote Spill")
    failed_queries = _obs_value(board, "Failed Queries")
    failed_tasks = _obs_value(board, "Failed Tasks")
    critical_high = _obs_value(board, "Critical High Alerts")
    open_actions = _obs_value(board, "Open Actions")
    storage_tb = _obs_value(board, "Storage")
    platform_health = _obs_value(board, "Platform Health")

    def capped(value: float, threshold: float) -> float:
        if threshold <= 0:
            return 0.0
        return min(max(safe_float(value) / threshold * 100.0, 0.0), 100.0)

    rows = [
        {
            "LANE": "Platform health",
            "STATE": _platform_score_state(platform_health) if _obs_metric_loaded(board, "Platform Health") else "On demand",
            "VALUE": _platform_score_state(platform_health) if _obs_metric_loaded(board, "Platform Health") else "On demand",
            "PRESSURE_SCORE": max(0.0, 100.0 - safe_float(platform_health)) if _obs_metric_loaded(board, "Platform Health") else 0.0,
            "WHY_IT_MATTERS": "Rolls cost, risk, workload, and telemetry quality into one summary-level pressure signal.",
            "OWNER_ROUTE": "Executive Landing",
            "NEXT_ACTION": "Open the highest pressure lane below before specialist drilldown.",
        },
        {
            "LANE": "Cost movement",
            "STATE": "Rising" if spend_delta > 0 else "Flat / down",
            "VALUE": _money(spend_delta, signed=True) if _obs_metric_loaded(board, "Spend Delta") else "On demand",
            "PRESSURE_SCORE": capped(max(spend_delta, 0.0), max(current_spend * 0.20, 500.0)),
            "WHY_IT_MATTERS": "Leadership asks first why the bill moved and whether the increase has an owner.",
            "OWNER_ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Open Cost & Contract when this lane is above 40.",
        },
        {
            "LANE": "Cortex spend",
            "STATE": "Spend active" if cortex_spend > 0 else "No spend",
            "VALUE": _money(cortex_spend) if _obs_metric_loaded(board, "Cortex Spend") else "On demand",
            "PRESSURE_SCORE": capped(cortex_spend, 500.0),
            "WHY_IT_MATTERS": "AI spend can grow without warehouse-style owner habits or quota guardrails.",
            "OWNER_ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Review top AI user/source and quota posture.",
        },
        {
            "LANE": "Queue pressure",
            "STATE": "Queued" if queue_seconds > 0 else "Clear",
            "VALUE": _format_seconds(queue_seconds) if _obs_metric_loaded(board, "Queue Time") else "On demand",
            "PRESSURE_SCORE": capped(queue_seconds, 3600.0),
            "WHY_IT_MATTERS": "Queue time turns into missed SLAs, frustrated users, and sometimes wasteful resize decisions.",
            "OWNER_ROUTE": "DBA Control Room",
            "NEXT_ACTION": "Check warehouse pressure and contention before resizing.",
        },
        {
            "LANE": "Spillage",
            "STATE": "Spilling" if spill_gb > 0 else "Clear",
            "VALUE": _format_gb(spill_gb) if _obs_metric_loaded(board, "Remote Spill") else "On demand",
            "PRESSURE_SCORE": capped(spill_gb, 100.0),
            "WHY_IT_MATTERS": "Remote spill is a strong signal for poor pruning, oversized joins, and warehouse pressure.",
            "OWNER_ROUTE": "Workload Operations",
            "NEXT_ACTION": "Open Query Diagnosis for the top spilling SQL patterns.",
        },
        {
            "LANE": "Reliability",
            "STATE": "Failures" if failed_queries or failed_tasks else "Clear",
            "VALUE": f"{safe_int(failed_queries):,} query / {safe_int(failed_tasks):,} task",
            "PRESSURE_SCORE": capped(safe_float(failed_queries) + safe_float(failed_tasks) * 5.0, 25.0),
            "WHY_IT_MATTERS": "Failed query and task volume predicts missed reporting, reruns, and support tickets.",
            "OWNER_ROUTE": "DBA Control Room",
            "NEXT_ACTION": "Work failed production tasks and repeat query failures first.",
        },
        {
            "LANE": "Alerts and actions",
            "STATE": "Open risk" if critical_high or open_actions else "Clear",
            "VALUE": f"{safe_int(critical_high):,} critical/high; {safe_int(open_actions):,} actions",
            "PRESSURE_SCORE": min(safe_float(critical_high) * 12.0 + safe_float(open_actions) * 3.0, 100.0),
            "WHY_IT_MATTERS": "Unowned alert/action backlog is where small warnings become incidents.",
            "OWNER_ROUTE": "Alert Center",
            "NEXT_ACTION": "Acknowledge, assign, suppress, or resolve the oldest high-impact rows.",
        },
        {
            "LANE": "Storage footprint",
            "STATE": "Track" if storage_tb > 0 else "No data",
            "VALUE": f"{safe_float(storage_tb):,.2f} TB" if _obs_metric_loaded(board, "Storage") else "On demand",
            "PRESSURE_SCORE": capped(storage_tb, 50.0),
            "WHY_IT_MATTERS": "Storage, failsafe, and stages become contract noise when growth lacks lifecycle controls.",
            "OWNER_ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Review storage growth and cleanup candidates when this lane climbs.",
        },
    ]
    if isinstance(advisor_rows, pd.DataFrame) and not advisor_rows.empty:
        totals = _advisor_overlay_totals(advisor_rows)
        rows.append({
            "LANE": "Advisor backlog",
            "STATE": "Review" if totals["advisor_high_findings"] else "Loaded",
            "VALUE": (
                f"{totals['advisor_findings']:,} finding(s); "
                f"{_money(totals['advisor_estimated_monthly_savings_usd'])}/mo savings"
            ),
            "PRESSURE_SCORE": min(
                totals["advisor_high_findings"] * 15.0
                + totals["advisor_findings"] * 2.0
                + totals["advisor_value_at_risk_usd"] / 2500.0,
                100.0,
            ),
            "WHY_IT_MATTERS": "Loaded advisors identify avoidable cost, warehouse pressure, storage retention, and procedure work.",
            "OWNER_ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Open the highest-priority advisor row before assigning or tuning work.",
        })
    out = pd.DataFrame(rows, columns=columns)
    return out.sort_values(["PRESSURE_SCORE", "LANE"], ascending=[False, True]).reset_index(drop=True)


def _executive_pressure_placeholder_rows() -> pd.DataFrame:
    """Return the executive pressure frame when the mart has not loaded yet."""
    return pd.DataFrame(
        [
            {
                "LANE": "Platform health",
                "STATE": "On demand",
                "VALUE": "On demand",
                "PRESSURE_SCORE": 0.0,
                "WHY_IT_MATTERS": "Platform health needs cost, workload, alert, and telemetry facts before it is decision-grade.",
                "OWNER_ROUTE": "Executive Landing",
                "NEXT_ACTION": "Refresh the executive summary facts.",
            },
            {
                "LANE": "Cost movement",
                "STATE": "On demand",
                "VALUE": "On demand",
                "PRESSURE_SCORE": 0.0,
                "WHY_IT_MATTERS": "Spend movement is the first leadership question and must come from metering facts.",
                "OWNER_ROUTE": "Cost & Contract",
                "NEXT_ACTION": "Refresh the cost summary facts.",
            },
            {
                "LANE": "Cortex spend",
                "STATE": "On demand",
                "VALUE": "On demand",
                "PRESSURE_SCORE": 0.0,
                "WHY_IT_MATTERS": "AI spend needs explicit owner and quota visibility.",
                "OWNER_ROUTE": "Cost & Contract",
                "NEXT_ACTION": "Refresh AI spend or mark Cortex unavailable for this account.",
            },
            {
                "LANE": "Runtime and queue",
                "STATE": "On demand",
                "VALUE": "On demand",
                "PRESSURE_SCORE": 0.0,
                "WHY_IT_MATTERS": "Runtime, queue, and spill show whether the platform is hurting users.",
                "OWNER_ROUTE": "Workload Operations",
                "NEXT_ACTION": "Refresh QUERY_HISTORY rollups for the active scope.",
            },
            {
                "LANE": "Reliability",
                "STATE": "On demand",
                "VALUE": "On demand",
                "PRESSURE_SCORE": 0.0,
                "WHY_IT_MATTERS": "Failed queries, failed tasks, and missed runs are the fastest path to incident risk.",
                "OWNER_ROUTE": "DBA Control Room",
                "NEXT_ACTION": "Refresh task, procedure, and alert facts.",
            },
            {
                "LANE": "Alerts and actions",
                "STATE": "On demand",
                "VALUE": "On demand",
                "PRESSURE_SCORE": 0.0,
                "WHY_IT_MATTERS": "Open critical/high alerts and unowned action queue rows drive the morning command queue.",
                "OWNER_ROUTE": "Alert Center",
                "NEXT_ACTION": "Refresh alert and action summaries.",
            },
        ]
    )


def _executive_summary_lanes(board: pd.DataFrame, *, days: int, credit_price: float) -> list[dict[str, str]]:
    """Return the dense boss-page metric lanes without running a live query."""
    _ = credit_price
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
        return [
            {
                "label": "Credits used / dollars",
                "value": "On demand",
                "state": "Mart",
                "detail": "Load MART_EXECUTIVE_OBSERVABILITY for official/metered spend.",
            },
            {
                "label": "Cortex dollars",
                "value": "On demand",
                "state": "AI",
                "detail": "Uses Cortex fact rows where account telemetry is available.",
            },
            {
                "label": "Monthly run rate",
                "value": "On demand",
                "state": "Forecast",
                "detail": "Projected from the selected summary window after facts load.",
            },
            {
                "label": "Queries / avg runtime",
                "value": "On demand",
                "state": "Workload",
                "detail": "Query count and runtime rollups come from hourly facts.",
            },
            {
                "label": "P95 runtime / queue",
                "value": "On demand",
                "state": "SLA",
                "detail": "Queue and p95 runtime tell leadership whether users feel pain.",
            },
            {
                "label": "Remote spillage",
                "value": "On demand",
                "state": "SQL shape",
                "detail": "Highlights memory pressure, join shape, and pruning problems.",
            },
            {
                "label": "Alerts / failed tasks",
                "value": "On demand",
                "state": "Reliability",
                "detail": "Critical/high alerts and failed task facts drive the DBA queue.",
            },
            {
                "label": "Warehouse pressure",
                "value": "On demand",
                "state": "Capacity",
                "detail": "Summarizes queue plus spill before anyone resizes compute.",
            },
        ]

    current_spend = _obs_value(board, "Credits Used", column="VALUE_USD")
    cortex_spend = _obs_value(board, "Cortex Spend", column="VALUE_USD")
    queries = _obs_value(board, "Total Queries")
    avg_runtime = _obs_value(board, "Avg Runtime")
    p95_runtime = _obs_value(board, "P95 Runtime")
    queue_seconds = _obs_value(board, "Queue Time")
    spill_gb = _obs_value(board, "Remote Spill")
    critical_high = _obs_value(board, "Critical High Alerts")
    failed_tasks = _obs_value(board, "Failed Tasks")
    failed_queries = _obs_value(board, "Failed Queries")
    storage_tb = _obs_value(board, "Storage")
    month_end_forecast = current_spend / max(int(days), 1) * 30.0
    pressure = _obs_rows(board, "WAREHOUSE_PRESSURE")
    warehouse_pressure = 0.0
    if isinstance(pressure, pd.DataFrame) and not pressure.empty and "VALUE" in pressure.columns:
        warehouse_pressure = safe_float(pd.to_numeric(pressure["VALUE"], errors="coerce").fillna(0).sum())

    return [
        {
            "label": "Credits used / dollars",
            "value": _obs_money_label(board, "Credits Used"),
            "state": "Cost",
            "detail": "Current selected-window spend from the executive mart.",
        },
        {
            "label": "Cortex dollars",
            "value": _obs_money_label(board, "Cortex Spend"),
            "state": "AI",
            "detail": "AI usage cost at the configured Cortex credit rate.",
        },
        {
            "label": "Monthly run rate",
            "value": _money(month_end_forecast) if _obs_metric_loaded(board, "Credits Used") else "On demand",
            "state": "Forecast",
            "detail": f"Projected from {int(days)} day(s); confirm against complete-day metering.",
        },
        {
            "label": "Queries / avg runtime",
            "value": f"{safe_int(queries):,} / {_format_seconds(avg_runtime)}",
            "state": "Workload",
            "detail": f"{safe_int(failed_queries):,} failed query row(s) in the loaded scope.",
        },
        {
            "label": "P95 runtime / queue",
            "value": f"{_format_seconds(p95_runtime)} / {_format_seconds(queue_seconds)}",
            "state": "SLA",
            "detail": "Use Workload Operations before capacity changes.",
        },
        {
            "label": "Remote spillage",
            "value": _format_gb(spill_gb),
            "state": "SQL shape",
            "detail": "High spill means tune query shape or warehouse pressure telemetry.",
        },
        {
            "label": "Alerts / failed tasks",
            "value": f"{safe_int(critical_high):,} / {safe_int(failed_tasks):,}",
            "state": "Reliability",
            "detail": "Critical/high alert count and failed task count.",
        },
        {
            "label": "Warehouse pressure",
            "value": f"{warehouse_pressure:,.0f}",
            "state": "Capacity",
            "detail": f"Storage footprint: {safe_float(storage_tb):,.2f} TB.",
        },
    ]


def _render_executive_pressure_board(board: pd.DataFrame, advisor_rows: pd.DataFrame | None = None) -> None:
    rows = _executive_pressure_rows(board, advisor_rows=advisor_rows)
    if rows.empty and isinstance(board, pd.DataFrame) and {"LANE", "STATE", "VALUE", "PRESSURE_SCORE"}.issubset(set(board.columns)):
        rows = board.copy()
    if rows.empty:
        return
    st.markdown("**Executive Pressure Lanes**")
    top_pressure = safe_float(rows.iloc[0].get("PRESSURE_SCORE"))
    render_shell_kpi_row((
        ("Highest Pressure", str(rows.iloc[0].get("LANE") or "Loaded")),
        ("Pressure", _pressure_level(top_pressure)),
        ("Escalation", str(rows.iloc[0].get("OWNER_ROUTE") or "Executive Landing")),
        ("State", str(rows.iloc[0].get("STATE") or "Review")),
    ))
    display_rows = rows.copy()
    display_rows["PRESSURE_LEVEL"] = display_rows["PRESSURE_SCORE"].map(_pressure_level)
    display_rows = display_rows.drop(columns=["PRESSURE_SCORE"], errors="ignore")
    render_priority_dataframe(
        display_rows,
        title="Executive pressure details",
        priority_columns=[
            "LANE", "STATE", "VALUE", "PRESSURE_LEVEL",
            "OWNER_ROUTE", "WHY_IT_MATTERS", "NEXT_ACTION",
        ],
        sort_by=["LANE"],
        ascending=[True],
        raw_label="All executive pressure lanes",
        height=250,
        max_rows=8,
    )


def _render_loaded_advisor_overlay(advisor_rows: pd.DataFrame | None) -> None:
    if not isinstance(advisor_rows, pd.DataFrame) or advisor_rows.empty:
        return
    totals = _advisor_overlay_totals(advisor_rows)
    st.markdown("**Loaded Advisor Signals**")
    render_shell_kpi_row((
        ("Advisor Lanes", f"{totals['advisor_lanes']:,}"),
        ("Findings", f"{totals['advisor_findings']:,}"),
        ("High Priority", f"{totals['advisor_high_findings']:,}"),
        ("Est. Savings / Mo", _money(totals["advisor_estimated_monthly_savings_usd"])),
    ))
    render_priority_dataframe(
        advisor_rows,
        title="Advisor signals included in executive summary",
        priority_columns=[
            "PRIORITY", "LANE", "STATE", "VALUE", "ADVISOR_SIGNAL", "NEXT_ACTION", "ROUTE",
        ],
        sort_by=["PRIORITY", "HIGH_FINDINGS", "EST_MONTHLY_SAVINGS_USD"],
        ascending=[True, False, False],
        raw_label="All loaded advisor summary rows",
        height=260,
        max_rows=8,
    )


def _advisor_lane(advisor_rows: pd.DataFrame | None, lane_text: str) -> pd.Series | None:
    if not isinstance(advisor_rows, pd.DataFrame) or advisor_rows.empty or "LANE" not in advisor_rows.columns:
        return None
    matches = advisor_rows[advisor_rows["LANE"].fillna("").astype(str).str.contains(lane_text, case=False, na=False)]
    if matches.empty:
        return None
    return matches.iloc[0]


def _executive_command_summary_rows(board: pd.DataFrame, advisor_rows: pd.DataFrame | None, *, days: int) -> pd.DataFrame:
    """Return one compact operating summary across current loaded executive inputs."""
    rows: list[dict[str, object]] = []
    has_board = isinstance(board, pd.DataFrame) and not board.empty and _has_observability_kpis(board)
    spend_delta = _obs_value(board, "Spend Delta", column="VALUE_USD") if has_board else 0.0
    cost_driver = _obs_rows(board, "COST_DRIVER") if has_board else pd.DataFrame()
    top_cost_driver = "No loaded cost driver"
    top_cost_value = 0.0
    if isinstance(cost_driver, pd.DataFrame) and not cost_driver.empty and "VALUE_USD" in cost_driver.columns:
        ranked = cost_driver.copy()
        ranked["VALUE_USD"] = pd.to_numeric(ranked["VALUE_USD"], errors="coerce").fillna(0)
        ranked = ranked.sort_values("VALUE_USD", ascending=False)
        top_cost_driver = str(ranked.iloc[0].get("DIMENSION") or "Cost driver")
        top_cost_value = safe_float(ranked.iloc[0].get("VALUE_USD"))
    elif has_board and _obs_metric_loaded(board, "Spend Delta"):
        top_cost_driver = "Account spend"
        top_cost_value = spend_delta

    rows.append({
        "PRIORITY": 1 if spend_delta > 0 else 5,
        "AREA": "Cost movement",
        "STATE": "Review" if spend_delta > 0 else "Stable",
        "CURRENT_SIGNAL": f"{top_cost_driver}: {_money(top_cost_value)}; delta {_money(spend_delta, signed=True)}.",
        "NEXT_ACTION": "Open Cost & Contract and explain the top driver before setting changes.",
        "ROUTE": "Cost & Contract",
    })

    failed_tasks = safe_int(_obs_value(board, "Failed Tasks")) if has_board else 0
    failed_queries = safe_int(_obs_value(board, "Failed Queries")) if has_board else 0
    queue_seconds = _obs_value(board, "Queue Time") if has_board else 0.0
    spill_gb = _obs_value(board, "Remote Spill") if has_board else 0.0
    workload_pressure = failed_tasks + failed_queries + (1 if queue_seconds else 0) + (1 if spill_gb else 0)
    rows.append({
        "PRIORITY": 2 if workload_pressure else 6,
        "AREA": "Workload health",
        "STATE": "Investigate" if workload_pressure else "Clear",
        "CURRENT_SIGNAL": (
            f"{failed_tasks:,} failed task(s), {failed_queries:,} failed query(s), "
            f"{_format_seconds(queue_seconds)} queue, {_format_gb(spill_gb)} spill."
        ),
        "NEXT_ACTION": "Open Workload Operations for task/procedure and query pressure detail.",
        "ROUTE": "Workload Operations",
    })

    procedure_row = _advisor_lane(advisor_rows, "Procedure")
    rows.append({
        "PRIORITY": safe_int(procedure_row.get("PRIORITY"), 3) if procedure_row is not None else 7,
        "AREA": "Stored procedure advisor",
        "STATE": str(procedure_row.get("STATE") or "Review") if procedure_row is not None else "On demand",
        "CURRENT_SIGNAL": (
            str(procedure_row.get("ADVISOR_SIGNAL") or procedure_row.get("VALUE") or "Procedure analysis loaded.")
            if procedure_row is not None
            else "Load Task & procedure health to include stored-procedure SLA, cost, and optimization signals."
        ),
        "NEXT_ACTION": (
            str(procedure_row.get("NEXT_ACTION") or "Open Workload Operations procedure health.")
            if procedure_row is not None
            else "Open Workload Operations > Stored procedures."
        ),
        "ROUTE": "Workload Operations",
    })

    warehouse_row = _advisor_lane(advisor_rows, "Warehouse")
    rows.append({
        "PRIORITY": safe_int(warehouse_row.get("PRIORITY"), 4) if warehouse_row is not None else 8,
        "AREA": "Warehouse advisor",
        "STATE": str(warehouse_row.get("STATE") or "Review") if warehouse_row is not None else "On demand",
        "CURRENT_SIGNAL": (
            str(warehouse_row.get("ADVISOR_SIGNAL") or warehouse_row.get("VALUE") or "Warehouse advisor loaded.")
            if warehouse_row is not None
            else "Load Cost & Contract > Warehouse Advisor to include warehouse recommendations and savings."
        ),
        "NEXT_ACTION": (
            str(warehouse_row.get("NEXT_ACTION") or "Open Cost & Contract warehouse advisor.")
            if warehouse_row is not None
            else "Open Cost & Contract > Recommendations and action queue > Warehouse Advisor."
        ),
        "ROUTE": "Cost & Contract",
    })

    critical_high = safe_int(_obs_value(board, "Critical High Alerts")) if has_board else 0
    open_actions = safe_int(_obs_value(board, "Open Actions")) if has_board else 0
    rows.append({
        "PRIORITY": 1 if critical_high else 9,
        "AREA": "Open risk",
        "STATE": "Escalate" if critical_high else "Track",
        "CURRENT_SIGNAL": f"{critical_high:,} Critical/High alert(s), {open_actions:,} open action(s).",
        "NEXT_ACTION": "Open Alert Center and DBA Control Room for route, owner, and telemetry status.",
        "ROUTE": "Alert Center",
    })

    return pd.DataFrame(rows).sort_values(["PRIORITY", "AREA"]).reset_index(drop=True)


def _render_executive_command_summary(board: pd.DataFrame, advisor_rows: pd.DataFrame | None, *, days: int) -> None:
    rows = _executive_command_summary_rows(board, advisor_rows, days=int(days))
    if rows.empty:
        return
    st.markdown("**Executive Command Summary**")
    render_priority_dataframe(
        rows,
        title="Current top operating calls",
        priority_columns=["AREA", "STATE", "CURRENT_SIGNAL", "NEXT_ACTION", "ROUTE"],
        sort_by=["PRIORITY", "AREA"],
        ascending=[True, True],
        raw_label="All executive command summary rows",
        height=260,
        max_rows=5,
    )


def _render_line_chart(
    rows: pd.DataFrame,
    *,
    title: str,
    y_column: str,
    y_title: str,
    color_column: str | None = None,
    height: int = 210,
) -> None:
    render_escaped_bold_text(title)
    if rows is None or rows.empty or y_column not in rows.columns or "PERIOD_START" not in rows.columns:
        st.caption("No precomputed rows loaded for this chart.")
        return
    chart_rows = rows.copy()
    chart_rows["PERIOD_START"] = pd.to_datetime(chart_rows["PERIOD_START"], errors="coerce")
    chart_rows[y_column] = pd.to_numeric(chart_rows[y_column], errors="coerce").fillna(0)
    chart_rows = chart_rows.dropna(subset=["PERIOD_START"])
    if chart_rows.empty:
        st.caption("No precomputed rows loaded for this chart.")
        return
    alt = _altair()
    color = alt.Color(f"{color_column}:N", title=None) if color_column and color_column in chart_rows.columns else alt.value("#29B5E8")
    chart = (
        alt.Chart(chart_rows)
        .mark_line(point=True)
        .encode(
            x=alt.X("PERIOD_START:T", title=None),
            y=alt.Y(f"{y_column}:Q", title=y_title),
            color=color,
            tooltip=[
                alt.Tooltip("PERIOD_START:T", title="Period"),
                alt.Tooltip(f"{y_column}:Q", title=y_title, format=",.2f"),
                *([alt.Tooltip(f"{color_column}:N", title="Metric")] if color_column and color_column in chart_rows.columns else []),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")


def _render_bar_chart(
    rows: pd.DataFrame,
    *,
    title: str,
    x_column: str,
    y_column: str,
    x_title: str,
    color: str = "#29B5E8",
    height: int = 220,
) -> None:
    render_escaped_bold_text(title)
    if rows is None or rows.empty or x_column not in rows.columns or y_column not in rows.columns:
        st.caption("No precomputed rows loaded for this chart.")
        return
    chart_rows = rows.copy()
    chart_rows[y_column] = pd.to_numeric(chart_rows[y_column], errors="coerce").fillna(0)
    chart_rows[x_column] = chart_rows[x_column].astype(str)
    chart_rows = chart_rows.sort_values(y_column, ascending=False).head(10)
    if chart_rows.empty:
        st.caption("No precomputed rows loaded for this chart.")
        return
    alt = _altair()
    chart = (
        alt.Chart(chart_rows)
        .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3, color=color)
        .encode(
            x=alt.X(f"{y_column}:Q", title=x_title),
            y=alt.Y(
                f"{x_column}:N",
                sort=alt.SortField(field=y_column, order="descending"),
                title=None,
                axis=alt.Axis(labelLimit=220),
            ),
            tooltip=[
                alt.Tooltip(f"{x_column}:N", title="Group"),
                alt.Tooltip(f"{y_column}:Q", title=x_title, format=",.2f"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")


def _render_executive_observability_board(
    board: pd.DataFrame,
    payload: dict,
    *,
    company: str,
    environment: str,
    days: int,
    credit_price: float,
) -> None:
    error = str((payload or {}).get("error") or "").strip()
    advisor_rows = _executive_loaded_advisor_rows()
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
        render_shell_status_strip(
            state="Refresh Needed" if error else "Waiting",
            headline="Executive observability summary is ready for precomputed Snowflake facts.",
            detail=(
                error
                if error
                else "Refresh executive summaries to populate cost, query, task, storage, alert, and Cortex facts."
            ),
        )
        render_shell_kpi_row((
            ("Scope", f"{company} / {get_environment_label(environment, company)}"),
            ("Window", f"{int(days)}d"),
            ("Source", "Data summaries"),
            ("Status", "No rows"),
        ))
        render_refresh_contract(
            payload,
            source="Executive summary facts",
            target_minutes=60,
            refresh_method="Scheduled data refresh",
            live_fallback="On demand",
        )
        st.markdown("**Snowflake Observability Wall**")
        render_shell_kpi_row((
            ("Spend", "On demand"),
            ("Delta", "On demand"),
            ("Cortex", "On demand"),
            ("30d Forecast", "On demand"),
        ))
        render_shell_kpi_row((
            ("Queries", "On demand"),
            ("Avg Runtime", "On demand"),
            ("P95 Runtime", "On demand"),
            ("Remote Spill", "On demand"),
        ))
        render_shell_kpi_row((
            ("Critical / High", "On demand"),
            ("Failed Queries", "On demand"),
            ("Failed Tasks", "On demand"),
            ("Open Actions", "On demand"),
        ))
        render_shell_kpi_row((
            ("Queue Time", "On demand"),
            ("Avg/day", "On demand"),
            ("Storage", "On demand"),
            ("Freshness", "On demand"),
        ))
        _render_executive_command_summary(pd.DataFrame(), advisor_rows, days=int(days))
        _render_executive_pressure_board(_executive_pressure_placeholder_rows(), advisor_rows=advisor_rows)
        _render_executive_priority_board(pd.DataFrame(), days=int(days), advisor_rows=advisor_rows)
        _render_loaded_advisor_overlay(advisor_rows)
        _render_observability_source_status(board)
        return

    current_spend = _obs_value(board, "Credits Used", column="VALUE_USD")
    spend_delta = _obs_value(board, "Spend Delta", column="VALUE_USD")
    cortex_spend = _obs_value(board, "Cortex Spend", column="VALUE_USD")
    queries = _obs_value(board, "Total Queries")
    avg_runtime = _obs_value(board, "Avg Runtime")
    p95_runtime = _obs_value(board, "P95 Runtime")
    queue_seconds = _obs_value(board, "Queue Time")
    spill_gb = _obs_value(board, "Remote Spill")
    failed_queries = _obs_value(board, "Failed Queries")
    failed_tasks = _obs_value(board, "Failed Tasks")
    critical_high = _obs_value(board, "Critical High Alerts")
    open_actions = _obs_value(board, "Open Actions")
    storage_tb = _obs_value(board, "Storage")
    storage_cost = _obs_value(board, "Storage", column="VALUE_USD")
    health = _obs_value(board, "Platform Health")
    month_end_forecast = current_spend / max(int(days), 1) * 30.0
    avg_daily_spend = current_spend / max(int(days), 1)
    source_status = _obs_rows(board, "SOURCE_STATUS")
    unavailable_sources = (
        int(source_status["METRIC"].astype(str).eq("Unavailable").sum())
        if isinstance(source_status, pd.DataFrame) and not source_status.empty and "METRIC" in source_status.columns
        else 0
    )
    has_fact_trends = any(
        not _obs_rows(board, panel).empty
        for panel in (
            "DAILY_COST",
            "MONTHLY_COST",
            "DAILY_WORKLOAD",
            "COST_DRIVER",
            "QUERY_TYPE",
            "QUERY_DATABASE",
            "EXEC_STATUS",
            "WAREHOUSE_PRESSURE",
        )
    )
    status_state = "No Rows" if not has_fact_trends else (_platform_score_state(health) if health else "Loaded")
    status_headline = (
        "Executive summary schema loaded, but the mart has no recent fact rows for this scope."
        if not has_fact_trends
        else "Snowflake observability summary loaded from precomputed OVERWATCH facts."
    )
    loaded_advisor_count = safe_int(len(advisor_rows)) if isinstance(advisor_rows, pd.DataFrame) and not advisor_rows.empty else 0
    status_detail = (
        "Run or check the OVERWATCH mart refresh before using this view for leadership numbers."
        if not has_fact_trends
        else (
            f"{int(days)}-day view: cost, Cortex, query runtime, queue pressure, spill, task health, and storage. "
            f"{loaded_advisor_count:,} loaded advisor lane(s) are included from current session state. "
            "Alerts and action-queue counts remain On demand unless their secure app tables are available to this role. "
            "Detailed telemetry stays in the specialist sections."
        )
    )
    if unavailable_sources and has_fact_trends:
        status_detail = f"{status_detail} {unavailable_sources} optional source(s) are unavailable."

    render_shell_status_strip(
        state=status_state,
        headline=status_headline,
        detail=status_detail,
    )
    render_refresh_contract(
        payload,
        source="Executive summary facts",
        target_minutes=60,
        refresh_method="Scheduled data refresh",
        live_fallback="On demand",
    )
    st.markdown("**Snowflake Observability Wall**")
    render_shell_kpi_row((
        ("Platform", _platform_score_state(health) if health else "Loaded"),
        ("Spend", _obs_money_label(board, "Credits Used")),
        ("Delta", _obs_money_label(board, "Spend Delta", signed=True)),
        ("Cortex", _obs_money_label(board, "Cortex Spend")),
    ))
    render_shell_kpi_row((
        ("Queries", _obs_count_label(board, "Total Queries")),
        ("Avg Runtime", _format_seconds(avg_runtime) if _obs_metric_loaded(board, "Avg Runtime") else "On demand"),
        ("P95 Runtime", _format_seconds(p95_runtime) if _obs_metric_loaded(board, "P95 Runtime") else "On demand"),
        ("Remote Spill", _format_gb(spill_gb) if _obs_metric_loaded(board, "Remote Spill") else "On demand"),
    ))
    render_shell_kpi_row((
        ("Critical / High", _obs_count_label(board, "Critical High Alerts")),
        ("Failed Queries", _obs_count_label(board, "Failed Queries")),
        ("Failed Tasks", _obs_count_label(board, "Failed Tasks")),
        ("Open Actions", _obs_count_label(board, "Open Actions")),
    ))
    render_shell_kpi_row((
        ("Queue Time", _format_seconds(queue_seconds) if _obs_metric_loaded(board, "Queue Time") else "On demand"),
        ("30d Forecast", _money(month_end_forecast) if _obs_metric_loaded(board, "Credits Used") else "On demand"),
        ("Avg/day", _money(avg_daily_spend) if _obs_metric_loaded(board, "Credits Used") else "On demand"),
        ("Storage", f"{safe_float(storage_tb):,.2f} TB / {_money(storage_cost)}" if _obs_metric_loaded(board, "Storage") else "On demand"),
    ))
    _render_executive_command_summary(board, advisor_rows, days=int(days))
    _render_executive_pressure_board(board, advisor_rows=advisor_rows)
    _render_executive_priority_board(board, days=int(days), advisor_rows=advisor_rows)
    _render_loaded_advisor_overlay(advisor_rows)

    daily_cost = _obs_rows(board, "DAILY_COST").copy()
    monthly_cost = _obs_rows(board, "MONTHLY_COST").copy()
    daily_workload = _obs_rows(board, "DAILY_WORKLOAD").copy()
    cost_driver = _obs_rows(board, "COST_DRIVER").copy()
    query_mix = _obs_rows(board, "QUERY_TYPE").copy()
    query_database = _obs_rows(board, "QUERY_DATABASE").copy()
    exec_status = _obs_rows(board, "EXEC_STATUS").copy()
    warehouse_pressure = _obs_rows(board, "WAREHOUSE_PRESSURE").copy()

    chart_cols = st.columns(2)
    with chart_cols[0]:
        _render_line_chart(
            daily_cost,
            title="Daily Spend",
            y_column="VALUE_USD",
            y_title="Estimated Cost USD",
            height=210,
        )
    with chart_cols[1]:
        _render_bar_chart(
            monthly_cost,
            title="Monthly Spend Summary",
            x_column="DIMENSION",
            y_column="VALUE_USD",
            x_title="Estimated Cost USD",
            color="#71D3DC",
            height=210,
        )

    trend_cols = st.columns(2)
    with trend_cols[0]:
        _render_line_chart(
            daily_workload,
            title="Runtime and Queue Trend",
            y_column="VALUE",
            y_title="Seconds",
            color_column="METRIC",
            height=230,
        )
    with trend_cols[1]:
        _render_bar_chart(
            query_mix,
            title="Queries by Type",
            x_column="DIMENSION",
            y_column="VALUE",
            x_title="Queries",
            color="#10B981",
            height=230,
        )

    driver_cols = st.columns(3)
    with driver_cols[0]:
        _render_bar_chart(
            cost_driver,
            title="Top Cost Drivers",
            x_column="DIMENSION",
            y_column="VALUE_USD",
            x_title="Estimated Cost USD",
            color="#F59E0B",
            height=230,
        )
    with driver_cols[1]:
        _render_bar_chart(
            query_database,
            title="Queries by Database",
            x_column="DIMENSION",
            y_column="VALUE",
            x_title="Queries",
            color="#8B5CF6",
            height=230,
        )
    with driver_cols[2]:
        _render_bar_chart(
            exec_status,
            title="Execution Status",
            x_column="DIMENSION",
            y_column="VALUE",
            x_title="Queries",
            color="#EF4444",
            height=230,
        )

    pressure = warehouse_pressure.copy()
    if not pressure.empty:
        pressure["PRESSURE_VALUE"] = pd.to_numeric(pressure["VALUE"], errors="coerce").fillna(0)
        pressure = pressure.groupby("DIMENSION", as_index=False, sort=False)["PRESSURE_VALUE"].sum()
    _render_bar_chart(
        pressure,
        title="Warehouse Pressure: Queue + Spill",
        x_column="DIMENSION",
        y_column="PRESSURE_VALUE",
        x_title="Pressure",
        color="#F97316",
        height=260,
    )

    freshness = _obs_rows(board, "FRESHNESS")
    if isinstance(freshness, pd.DataFrame) and not freshness.empty:
        with st.expander("Summary data freshness", expanded=False):
            rows = freshness[["DIMENSION", "PERIOD_START", "UNIT"]].copy()
            rows = rows.rename(columns={"DIMENSION": "INPUT", "PERIOD_START": "LATEST_LOAD", "UNIT": "TYPE"})
            render_priority_dataframe(
                rows,
                title="Summary data freshness",
                priority_columns=["INPUT", "LATEST_LOAD", "TYPE"],
                raw_label="All executive summary freshness rows",
                height=180,
                max_rows=8,
            )
    _render_observability_source_status(board)


def _render_executive_action_brief(summary: dict | None, days: int, *, show_strip: bool = True) -> bool:
    brief = _executive_action_brief(summary)
    button_help = " ".join(
        part for part in (str(brief.get("headline") or ""), str(brief.get("detail") or "")) if part
    )
    if show_strip:
        render_shell_status_strip(
            state=brief["state"],
            headline=brief["headline"],
            detail=brief.get("detail") or f"{int(days)}-day window",
        )
    load_col, _ = st.columns([1.1, 4.0])
    with load_col:
        return bool(
            st.button(
                "Load Snapshot",
                key="executive_landing_load",
                help=button_help or None,
                type="primary",
                width="stretch",
            )
        )


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
            ("Telemetry", "On demand"),
        )
    else:
        metrics = (
            ("State", str(summary.get("state") or _platform_score_state(summary["score"]))),
            ("Spend", f"${credits_to_dollars(summary['current_credits'], credit_price):,.0f}"),
            ("Alerts", f"{summary['critical_high_alerts']:,}"),
            ("Data Gaps", f"{summary['migration_blockers']:,}"),
        )
    render_shell_kpi_row(metrics)


def _source_health_rows(snapshot: dict) -> pd.DataFrame:
    errors = [str(err) for err in snapshot.get("errors", [])]

    def _state(key: str, label: str, frame_name: str) -> dict:
        frame = snapshot.get(frame_name, pd.DataFrame())
        matching_error = next((err for err in errors if err.lower().startswith(key.lower())), "")
        if matching_error:
            state = "Limited"
            evidence = matching_error.split(":", 1)[-1].strip() or matching_error
            action = "Open the source section or Data Health to check access and status."
        elif isinstance(frame, pd.DataFrame) and not frame.empty:
            state = "Loaded"
            evidence = f"{len(frame):,} row(s) loaded."
            action = "Use this telemetry for executive triage and drill-through."
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
            _state("Cost summary unavailable", "Cost cockpit", "cost"),
            _state("Alert telemetry unavailable", "Alert telemetry", "alerts"),
            _state("Action queue unavailable", "Action queue", "queue"),
            _state("Migration ledger unavailable", "Migration ledger", "migration"),
        ]
    )


def _executive_snapshot_scope(company: str, environment: str, days: int) -> tuple[str, str, int]:
    return str(company), str(environment), int(days)


def _load_executive_snapshot(company: str, environment: str, days: int) -> bool:
    session = get_session_for_action(
        "load Executive Landing snapshot",
        surface="Executive Landing",
        offline_note="Executive Landing shell remains available without Snowflake.",
    )
    if session is None:
        return False
    st.session_state.pop(PLATFORM_SUMMARY_STATE_KEY, None)
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
        snapshot["errors"].append(f"Cost summary unavailable: {format_snowflake_error(exc)}")
    try:
        snapshot["alerts"] = _load_alerts(session, company, environment, int(days))
    except Exception as exc:
        snapshot["alerts"] = pd.DataFrame()
        snapshot["errors"].append(f"Alert telemetry unavailable: {format_snowflake_error(exc)}")
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
    st.session_state["_executive_landing_auto_load_scope"] = _executive_snapshot_scope(company, environment, days)
    return True


def _nav_button(
    label: str,
    section: str,
    *,
    workflow_key: str = "",
    workflow: str = "",
    state_updates: dict[str, str] | None = None,
) -> None:
    if st.button(label, key=f"executive_nav_{section}_{workflow or label}", width="stretch"):
        apply_navigation_state(section)
        if workflow_key and workflow:
            st.session_state[workflow_key] = workflow
        for key, value in (state_updates or {}).items():
            st.session_state[key] = value
        st.rerun()


def _render_loaded_executive_alert_context() -> None:
    board = build_loaded_section_alert_signal_board(st.session_state, section="Executive Landing", limit=8)
    if board.empty:
        return
    render_priority_dataframe(
        board,
        title="Loaded alert signals affecting the executive summary",
        priority_columns=[
            "SECTION_FOCUS", "SEVERITY", "SLA_STATE", "CATEGORY", "SIGNAL",
            "ENTITY", "OWNER", "ROUTE", "FIRST_RESPONSE", "RECOMMENDED_ACTION",
            "OPEN_PATH", "AUTOMATION_READINESS",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All loaded executive alert context rows",
        height=260,
        max_rows=6,
    )
    top = board.iloc[0]
    cols = st.columns(2)
    with cols[0]:
        if st.button("Open Alert Command", key="executive_alert_open_command", width="stretch"):
            apply_section_workflow_navigation(
                "Alert Center",
                alert_center_view=str(top.get("ALERT_CENTER_VIEW") or "Command Center"),
            )
            st.rerun()
    with cols[1]:
        if st.button("Open Impacted Section", key="executive_alert_open_impacted_section", width="stretch"):
            apply_section_workflow_navigation(
                str(top.get("DESTINATION_SECTION") or "Alert Center"),
                workflow=str(top.get("DESTINATION_WORKFLOW") or "Command Center"),
                alert_center_view=str(top.get("ALERT_CENTER_VIEW") or "Command Center"),
            )
            st.rerun()


def _render_enterprise_operating_model_summary(rollups: dict[str, pd.DataFrame]) -> None:
    """Render first-paint-safe leadership trust/value rollups."""
    trust = rollups.get("trust", pd.DataFrame())
    ownership = rollups.get("ownership", pd.DataFrame())
    value = rollups.get("value", pd.DataFrame())
    app = rollups.get("app", pd.DataFrame())

    trust_issues = 0
    trust_confidence = "fallback"
    if isinstance(trust, pd.DataFrame) and not trust.empty:
        status = trust.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        trust_issues = int((~status.eq("Ready")).sum())
        confidence = trust.get("CONFIDENCE", pd.Series(dtype=str)).dropna().astype(str).str.lower()
        trust_confidence = confidence.iloc[0] if not confidence.empty else "fallback"

    owner_gaps = 0
    if isinstance(ownership, pd.DataFrame) and not ownership.empty and "GAP_ITEMS" in ownership.columns:
        owner_gaps = safe_int(pd.to_numeric(ownership["GAP_ITEMS"], errors="coerce").fillna(0).sum())

    verified_savings = 0.0
    unverified_estimate = 0.0
    if isinstance(value, pd.DataFrame) and not value.empty:
        verified_savings = safe_float(pd.to_numeric(value.get("VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        unverified_estimate = safe_float(pd.to_numeric(value.get("UNVERIFIED_ESTIMATE_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())

    app_review = 0
    if isinstance(app, pd.DataFrame) and not app.empty:
        app_review = safe_int((~app.get("HEALTH_STATE", pd.Series(dtype=str)).fillna("").astype(str).eq("Ready")).sum())

    if all(
        not isinstance(frame, pd.DataFrame) or frame.empty
        for frame in (trust, ownership, value, app)
    ):
        st.caption("Enterprise operating model rollups are pending. Run the mart refresh to populate trust, ownership, value, and app health summaries.")
        return

    st.markdown("**Enterprise Operating Model**")
    render_shell_snapshot((
        ("Trust Issues", f"{trust_issues:,}"),
        ("Ownership Gaps", f"{owner_gaps:,}"),
        ("Verified Value", f"${verified_savings:,.0f}"),
        ("App Review", f"{app_review:,}"),
    ))
    st.caption(
        "Operating path: Finding -> Owner -> Trust Level -> Business Impact -> Action -> Value Verified. "
        f"Trust confidence: {trust_confidence}; unverified savings stay separate (${unverified_estimate:,.0f})."
    )
    with st.expander("Enterprise operating model rollups", expanded=trust_issues > 0 or owner_gaps > 0 or app_review > 0):
        if isinstance(trust, pd.DataFrame) and not trust.empty:
            trust_view = trust[[
                column for column in [
                    "SOURCE_NAME", "STATUS", "CONFIDENCE", "FRESHNESS_MINUTES",
                    "SOURCE_OBJECT", "OWNER_ROUTE", "BUSINESS_IMPACT", "NEXT_ACTION",
                ]
                if column in trust.columns
            ]].head(12)
            st.dataframe(trust_view, width="stretch", hide_index=True)
        if isinstance(ownership, pd.DataFrame) and not ownership.empty:
            ownership_view = ownership[[
                column for column in [
                    "SURFACE", "ENTITY_TYPE", "TOTAL_ITEMS", "ROUTED_ITEMS",
                    "GAP_ITEMS", "COVERAGE_PCT", "TRUST_LEVEL", "CONFIDENCE",
                    "OWNER_ROUTE", "NEXT_ACTION",
                ]
                if column in ownership.columns
            ]].head(12)
            st.dataframe(ownership_view, width="stretch", hide_index=True)
        if isinstance(value, pd.DataFrame) and not value.empty:
            value_view = value[[
                column for column in [
                    "STATUS", "OWNER_ROUTE", "EXPECTED_SAVINGS_USD",
                    "VERIFIED_SAVINGS_USD", "UNVERIFIED_ESTIMATE_USD",
                    "CONFIDENCE", "VALUE_STATE", "NEXT_ACTION",
                ]
                if column in value.columns
            ]].head(12)
            st.dataframe(value_view, width="stretch", hide_index=True)
        if isinstance(app, pd.DataFrame) and not app.empty:
            app_view = app[[
                column for column in [
                    "SECTION_NAME", "HEALTH_STATE", "P95_RENDER_MS",
                    "SLOW_SECTION_COUNT", "QUERY_FAILURE_COUNT",
                    "OVERWATCH_COST_USD", "VALIDATION_STATUS", "CONFIDENCE",
                    "NEXT_ACTION",
                ]
                if column in app.columns
            ]].head(12)
            st.dataframe(app_view, width="stretch", hide_index=True)


def _render_production_readiness_dashboard(readiness: pd.DataFrame) -> None:
    """Render Phase 2A compact production readiness from the summary mart."""
    if not isinstance(readiness, pd.DataFrame) or readiness.empty:
        st.caption("Production readiness summary is pending. Run the mart refresh to populate deployment, validation, privilege, refresh, config, and environment checks.")
        return

    row = readiness.iloc[0]
    status = str(row.get("VALIDATION_STATUS") or "Unknown")
    readiness_score = safe_int(row.get("READINESS_SCORE"), 0)
    missing_privileges = safe_int(row.get("MISSING_PRIVILEGES"), 0)
    failed_refreshes = safe_int(row.get("FAILED_MART_REFRESHES"), 0)
    missing_marts = safe_int(row.get("MISSING_SUMMARY_MARTS"), 0)
    stale_sources = safe_int(row.get("STALE_SOURCE_COUNT"), 0)
    config_drift = safe_int(row.get("CONFIG_DRIFT_COUNT"), 0)

    st.markdown("**Production Readiness**")
    render_shell_snapshot((
        ("Status", status),
        ("Score", f"{readiness_score}/100"),
        ("Missing Privileges", f"{missing_privileges:,}"),
        ("Failed Refreshes", f"{failed_refreshes:,}"),
        ("Missing Marts", f"{missing_marts:,}"),
    ))
    st.caption(
        f"Deployment {row.get('DEPLOYMENT_VERSION') or 'unknown'}; "
        f"last validation {row.get('LAST_VALIDATION_TS') or 'not recorded'}; "
        f"confidence {row.get('CONFIDENCE') or 'fallback'}."
    )
    with st.expander("Production readiness signals", expanded=status in {"Blocked", "Review"}):
        signal_rows = pd.DataFrame([
            {"SIGNAL": "Data freshness", "VALUE": stale_sources, "STATE": "Review" if stale_sources else "Ready"},
            {"SIGNAL": "Configuration drift", "VALUE": config_drift, "STATE": "Review" if config_drift else "Ready"},
            {"SIGNAL": "Environment readiness", "VALUE": row.get("ENVIRONMENT_READINESS") or "Unknown", "STATE": row.get("ENVIRONMENT_READINESS") or "Unknown"},
            {"SIGNAL": "Top risk", "VALUE": row.get("TOP_RISK") or "Production readiness checks are green.", "STATE": status},
            {"SIGNAL": "Next action", "VALUE": row.get("NEXT_ACTION") or "Keep validation current.", "STATE": status},
        ])
        st.dataframe(signal_rows, width="stretch", hide_index=True)


def _render_executive_scorecard_summary(scorecard: pd.DataFrame) -> None:
    """Render Phase 2B leadership scoring from the compact scorecard mart."""
    if not isinstance(scorecard, pd.DataFrame) or scorecard.empty:
        st.caption("Executive Scorecard is pending. Run the executive mart refresh to populate leadership health scores.")
        return

    work = scorecard.copy()
    status = work.get("STATUS", pd.Series(dtype=str)).fillna("Unknown").astype(str)
    trend = work.get("TREND", pd.Series(dtype=str)).fillna("Stable").astype(str)
    scores = pd.to_numeric(work.get("CURRENT_SCORE", pd.Series(dtype=float)), errors="coerce").fillna(0)
    risk_values = pd.to_numeric(work.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    value_at_risk = safe_float(risk_values.sum())
    lowest_score = safe_float(scores.min()) if not scores.empty else 0.0
    red = safe_int(status.eq("Red").sum())
    yellow = safe_int(status.eq("Yellow").sum())
    worsening = safe_int(trend.str.contains("worsening", case=False, na=False).sum())
    work["_CURRENT_SCORE_SORT"] = scores
    work["_VALUE_RISK_SORT"] = risk_values
    top_row = work.sort_values(
        by=["_CURRENT_SCORE_SORT", "_VALUE_RISK_SORT"],
        ascending=[True, False],
        na_position="last",
    ).iloc[0]

    st.markdown("**Executive Scorecard**")
    render_shell_snapshot((
        ("Lowest Score", f"{lowest_score:.0f}/100"),
        ("Red", f"{red:,}"),
        ("Yellow", f"{yellow:,}"),
        ("Worsening", f"{worsening:,}"),
        ("Value/Risk", f"${value_at_risk:,.0f}"),
    ))
    st.caption(
        f"Top concern: {top_row.get('SCORE_NAME') or 'Executive score'} is "
        f"{top_row.get('STATUS') or 'Unknown'}; owner route "
        f"{top_row.get('OWNER_ROUTE') or 'Owner gap'}. "
        f"Action: {top_row.get('RECOMMENDED_ACTION') or 'Review score drivers'}."
    )
    view = work[[
        column for column in [
            "SCORE_NAME", "CURRENT_SCORE", "STATUS", "TREND", "TOP_DRIVER",
            "RECOMMENDED_ACTION", "OWNER_ROUTE", "OWNER_GAP", "VALUE_AT_RISK_USD",
            "CONFIDENCE", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)


def _format_forecast_value(value: object, unit: object) -> str:
    numeric = safe_float(value, 0.0)
    unit_label = str(unit or "").lower()
    if unit_label == "usd":
        return f"${numeric:,.0f}"
    if unit_label == "percent":
        return f"{numeric:,.1f}%"
    if unit_label == "tb":
        return f"{numeric:,.2f} TB"
    if unit_label == "seconds":
        return f"{numeric:,.0f}s"
    if unit_label == "count":
        return f"{numeric:,.0f}"
    return f"{numeric:,.2f}"


def _render_executive_forecast_summary(forecasts: pd.DataFrame) -> None:
    """Render Phase 2C compact forecasting from the summary mart."""
    if not isinstance(forecasts, pd.DataFrame) or forecasts.empty:
        st.caption("Executive Forecasting is pending. Run the executive mart refresh to populate leadership forecast rows.")
        return

    work = forecasts.copy()
    trend = work.get("TREND_DIRECTION", pd.Series(dtype=str)).fillna("Unknown").astype(str)
    confidence = work.get("CONFIDENCE", pd.Series(dtype=str)).fillna("Low").astype(str)
    risk_values = pd.to_numeric(work.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    upward = safe_int(trend.eq("Up").sum())
    low_confidence = safe_int(confidence.eq("Low").sum())
    value_risk = safe_float(risk_values.sum())
    work["_RISK_SORT"] = risk_values
    work["_LOW_CONF_SORT"] = confidence.eq("Low").astype(int)
    top_row = work.sort_values(
        by=["_RISK_SORT", "_LOW_CONF_SORT"],
        ascending=[False, False],
        na_position="last",
    ).iloc[0]

    st.markdown("**Executive Forecasting**")
    render_shell_snapshot((
        ("Forecasts", f"{len(work):,}"),
        ("Trending Up", f"{upward:,}"),
        ("Low Confidence", f"{low_confidence:,}"),
        ("Value/Risk", f"${value_risk:,.0f}"),
    ))
    st.caption(
        f"Top forecast: {top_row.get('FORECAST_NAME') or 'Forecast'} "
        f"{_format_forecast_value(top_row.get('FORECAST_VALUE'), top_row.get('VALUE_UNIT'))}; "
        f"confidence {top_row.get('CONFIDENCE') or 'Low'}. "
        "Forecasts are heuristic estimates and are not counted as verified savings."
    )
    view = work[[
        column for column in [
            "FORECAST_NAME", "FORECAST_DOMAIN", "FORECAST_VALUE", "VALUE_UNIT",
            "CURRENT_ACTUAL", "PRIOR_PERIOD_VALUE", "TREND_DIRECTION",
            "CONFIDENCE", "MAIN_DRIVER", "RECOMMENDED_ACTION", "OWNER_ROUTE",
            "VALUE_AT_RISK_USD", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]].copy()
    if "FORECAST_VALUE" in view.columns and "VALUE_UNIT" in view.columns:
        view["FORECAST_DISPLAY"] = [
            _format_forecast_value(value, unit)
            for value, unit in zip(view["FORECAST_VALUE"], view["VALUE_UNIT"], strict=False)
        ]
    st.dataframe(view, width="stretch", hide_index=True)


def _render_change_intelligence_summary(changes: pd.DataFrame) -> None:
    """Render Phase 2D compact change-risk summary from the summary mart."""
    if not isinstance(changes, pd.DataFrame) or changes.empty:
        st.caption("Change Intelligence is pending. Run the executive mart refresh to populate recent change-risk rows.")
        return

    work = changes.copy()
    change_count = pd.to_numeric(work.get("CHANGE_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    high_risk = pd.to_numeric(work.get("HIGH_RISK_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    owner_gaps = pd.to_numeric(work.get("OWNER_GAP_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    correlations = pd.to_numeric(work.get("CORRELATION_CANDIDATE_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    work["_HIGH_RISK_SORT"] = high_risk
    work["_CHANGE_SORT"] = change_count
    top_row = work.sort_values(
        by=["_HIGH_RISK_SORT", "_CHANGE_SORT"],
        ascending=[False, False],
        na_position="last",
    ).iloc[0]

    st.markdown("**Change Intelligence**")
    render_shell_snapshot((
        ("Changes", f"{safe_int(change_count.sum()):,}"),
        ("High Risk", f"{safe_int(high_risk.sum()):,}"),
        ("Owner Gaps", f"{safe_int(owner_gaps.sum()):,}"),
        ("Possible Links", f"{safe_int(correlations.sum()):,}"),
    ))
    st.caption(
        f"Top change area: {top_row.get('CHANGE_CATEGORY') or top_row.get('CHANGE_TYPE') or 'Change'}; "
        f"latest object {top_row.get('TOP_OBJECT_NAME') or 'No recent changes'}. "
        "Related alerts are shown as possible correlations, not root-cause claims."
    )
    view = work[[
        column for column in [
            "CHANGE_CATEGORY", "CHANGE_TYPE", "CHANGE_COUNT", "HIGH_RISK_COUNT",
            "RELATED_ALERT_COUNT", "CORRELATION_CANDIDATE_COUNT", "LATEST_CHANGE_TS",
            "TOP_OBJECT_NAME", "TOP_CHANGED_BY", "RISK_LEVEL", "BUSINESS_IMPACT",
            "OWNER_ROUTE", "CONFIDENCE", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)


def _render_closed_loop_summary(actions: pd.DataFrame) -> None:
    """Render Phase 2E compact closed-loop action/value summary."""
    if not isinstance(actions, pd.DataFrame) or actions.empty:
        st.caption("Closed Loop Operations is pending. Run the executive mart refresh to populate action lifecycle rows.")
        return

    work = actions.copy()
    open_count = pd.to_numeric(work.get("OPEN_ACTION_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    approvals = pd.to_numeric(work.get("APPROVAL_REQUIRED_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    pending_verify = pd.to_numeric(work.get("VERIFICATION_PENDING_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    verified_value = pd.to_numeric(work.get("ACTUAL_VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    expected_value = pd.to_numeric(work.get("EXPECTED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    work["_ACTION_SORT"] = open_count + approvals + pending_verify
    work["_VALUE_SORT"] = expected_value
    top_row = work.sort_values(
        by=["_ACTION_SORT", "_VALUE_SORT"],
        ascending=[False, False],
        na_position="last",
    ).iloc[0]

    st.markdown("**Closed Loop Operations**")
    render_shell_snapshot((
        ("Open Actions", f"{safe_int(open_count.sum()):,}"),
        ("Need Approval", f"{safe_int(approvals.sum()):,}"),
        ("Verify", f"{safe_int(pending_verify.sum()):,}"),
        ("Verified Value", f"${safe_float(verified_value.sum()):,.0f}"),
    ))
    st.caption(
        f"Top action area: {top_row.get('ACTION_DOMAIN') or 'Actions'}; "
        f"{top_row.get('NEXT_ACTION') or 'Work actions through approval and verification.'} "
        "Expected savings stay separate from actual verified savings."
    )
    view = work[[
        column for column in [
            "ACTION_DOMAIN", "OPEN_ACTION_COUNT", "APPROVAL_REQUIRED_COUNT",
            "APPROVED_COUNT", "VERIFICATION_PENDING_COUNT", "VERIFIED_COUNT",
            "CLOSED_COUNT", "HIGH_RISK_COUNT", "OWNER_GAP_COUNT",
            "EXPECTED_SAVINGS_USD", "ACTUAL_VERIFIED_SAVINGS_USD",
            "UNVERIFIED_EXPECTED_USD", "TOP_FINDING", "NEXT_ACTION",
            "CONFIDENCE", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)


def _render_command_center_summary(findings: pd.DataFrame) -> None:
    """Render Phase 2F compact Command Center summary from the summary mart."""
    if not isinstance(findings, pd.DataFrame) or findings.empty:
        st.caption("Command Center is pending. Run the executive mart refresh to populate correlated findings.")
        return

    work = findings.copy()
    finding_count = pd.to_numeric(work.get("FINDING_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0).astype("float64")
    high_risk = pd.to_numeric(work.get("HIGH_RISK_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0).astype("float64")
    owner_gap = pd.to_numeric(work.get("OWNER_GAP_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0).astype("float64")
    expected_value = pd.to_numeric(work.get("EXPECTED_VALUE_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).astype("float64")
    work["_SORT_VALUE"] = high_risk.mul(1_000_000.0).add(owner_gap.mul(10_000.0)).add(expected_value)
    top_row = work.sort_values("_SORT_VALUE", ascending=False, na_position="last").iloc[0]

    st.markdown("**Command Center**")
    render_shell_snapshot((
        ("Findings", f"{safe_int(finding_count.sum()):,}"),
        ("High Risk", f"{safe_int(high_risk.sum()):,}"),
        ("Owner Gaps", f"{safe_int(owner_gap.sum()):,}"),
        ("Value/Risk", f"${safe_float(expected_value.sum()):,.0f}"),
    ))
    st.caption(
        f"Top investigation: {top_row.get('INVESTIGATION_TYPE') or 'Command Center'}; "
        f"{top_row.get('TOP_RECOMMENDED_ACTION') or 'Load the DBA Command Center workspace for evidence.'} "
        "Findings are deterministic root-cause candidates, not unverified causality claims."
    )
    view = work[[
        column for column in [
            "INVESTIGATION_TYPE", "QUESTION_TEXT", "FINDING_COUNT",
            "HIGH_RISK_COUNT", "OWNER_GAP_COUNT", "RELATED_CHANGE_COUNT",
            "RELATED_ALERT_COUNT", "RELATED_SCORECARD_COUNT",
            "RELATED_FORECAST_COUNT", "REVIEW_PLAN_COUNT",
            "EXPECTED_VALUE_USD", "TOP_ROOT_CAUSE_CANDIDATE",
            "TOP_EVIDENCE_SUMMARY", "TOP_RECOMMENDED_ACTION",
            "CONFIDENCE", "RISK_LEVEL", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)


def _render_advanced_executive_rollups(company: str, environment: str, days: int) -> None:
    """Render enterprise rollups after the executive decision surface."""
    st.divider()
    with st.expander("Advanced executive rollups", expanded=False):
        _render_enterprise_operating_model_summary(
            load_enterprise_operating_rollups(company, environment, days=int(days))
        )
        _render_production_readiness_dashboard(
            load_production_readiness_summary(company, environment, days=int(days))
        )
        _render_executive_scorecard_summary(
            load_executive_scorecard_summary(company, environment, days=int(days))
        )
        _render_executive_forecast_summary(
            load_executive_forecast_summary(company, environment, days=int(days))
        )
        _render_change_intelligence_summary(
            load_change_intelligence_summary(company, environment, days=int(days))
        )
        _render_closed_loop_summary(
            load_closed_loop_summary(company, environment, days=int(days))
        )
        _render_command_center_summary(
            load_command_center_summary(company, environment, days=int(days))
        )


def render() -> None:
    company = _active_company()
    environment = _active_environment()
    credit_price = _credit_price()
    defer_source_note(
        "Executive Landing opens with precomputed observability facts; full snapshot/export detail stays action-gated."
    )

    window_col, refresh_col, _window_spacer = st.columns([1.2, 1.0, 2.2])
    with window_col:
        days = st.selectbox(
            "Executive window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(DEFAULT_DAY_WINDOW),
            format_func=lambda value: f"{value} days",
        )
    with refresh_col:
        refresh_board = st.button(
            "Refresh Summary",
            key="executive_landing_observability_refresh",
            type="primary",
            width="stretch",
        )
    expected_scope = _executive_snapshot_scope(company, environment, int(days))
    board, board_payload = _current_observability_board(company, environment, int(days))
    autoload_scope_key = "_executive_landing_observability_autoload_scope"
    needs_first_load = (
        not isinstance(board, pd.DataFrame)
        or board.empty
        or _observability_payload_is_offline(board_payload)
    )
    if needs_first_load:
        if _executive_observability_autoload_allowed():
            _load_executive_observability(
                company,
                environment,
                int(days),
                credit_price=credit_price,
            )
        elif not isinstance(board, pd.DataFrame) or board.empty:
            _store_connection_unavailable_observability(company, environment, int(days))
        st.session_state[autoload_scope_key] = expected_scope
        board, board_payload = _current_observability_board(company, environment, int(days))
    if refresh_board:
        refresh_session = get_session_for_action(
            "refresh executive summaries",
            surface="Executive Landing",
            offline_note="Executive Landing will keep showing the local shell state until Snowflake is configured.",
        )
        if refresh_session is None:
            _store_connection_unavailable_observability(company, environment, int(days))
        else:
            _load_executive_observability(
                company,
                environment,
                int(days),
                credit_price=credit_price,
            )
        st.session_state["_executive_landing_observability_scope"] = expected_scope
        board, board_payload = _current_observability_board(company, environment, int(days))

    snapshot = st.session_state.get("executive_landing_snapshot")
    if isinstance(snapshot, dict) and not _snapshot_matches_scope(snapshot, company, environment, int(days)):
        defer_source_note("Loaded Executive Landing snapshot is for another scope. Reload the snapshot for the selected company, environment, and window.")
        st.session_state.pop(PLATFORM_SUMMARY_STATE_KEY, None)
        snapshot = None
    summary = _summary_from_observability(board, credit_price=credit_price, state=st.session_state)
    source_health = pd.DataFrame()
    if isinstance(snapshot, dict):
        source_health = _source_health_rows(snapshot)
        summary = _snapshot_state(
            snapshot.get("cost", pd.DataFrame()),
            snapshot.get("alerts", pd.DataFrame()),
            snapshot.get("queue", pd.DataFrame()),
            snapshot.get("migration", pd.DataFrame()),
        )
        summary = _with_platform_operating_score(summary, source_health)
        _persist_platform_summary(summary)
    elif summary:
        _persist_platform_summary(summary)
    else:
        summary = _default_platform_summary()
        _persist_platform_summary(summary)

    _render_executive_observability_board(
        board,
        board_payload,
        company=company,
        environment=environment,
        days=int(days),
        credit_price=credit_price,
    )
    load = _render_executive_action_brief(summary, int(days), show_strip=False)
    _render_loaded_executive_alert_context()

    if load:
        if _load_executive_snapshot(company, environment, int(days)):
            st.rerun()

    snapshot = st.session_state.get("executive_landing_snapshot")
    if not isinstance(snapshot, dict) or not _snapshot_matches_scope(snapshot, company, environment, int(days)):
        _render_advanced_executive_rollups(company, environment, int(days))
        return

    for err in snapshot.get("errors", []):
        defer_source_note(err)

    if not isinstance(source_health, pd.DataFrame) or source_health.empty:
        source_health = _source_health_rows(snapshot)
        summary = _with_platform_operating_score(summary, source_health)
        _persist_platform_summary(summary)
    loaded_sources = int(source_health["STATE"].eq("Loaded").sum())
    limited_sources = int(source_health["STATE"].eq("Limited").sum())
    no_row_sources = int(source_health["STATE"].eq("No Rows").sum())
    render_shell_snapshot((
        ("Inputs Ready", f"{loaded_sources}/4"),
        ("Limited Inputs", f"{limited_sources}"),
        ("No-Row Inputs", f"{no_row_sources}"),
    ))
    with st.expander("Executive Data Health", expanded=False):
        render_priority_dataframe(
            source_health,
            title="Executive data health",
            priority_columns=["SOURCE", "STATE", "EVIDENCE", "NEXT_ACTION"],
            sort_by=["STATE", "SOURCE"],
            ascending=[True, True],
            raw_label="All executive data-health rows",
            height=220,
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
            "Alert Command",
            "Alert Center",
            state_updates={"alert_center_active_view": "Command Center"},
        )
    with n2:
        _nav_button("Cost Drivers", "Cost & Contract", workflow_key="cost_contract_workflow", workflow="Usage attribution and run-rate")
    with n3:
        _nav_button("DBA Queue", "DBA Control Room")
    with n4:
        _nav_button(
            "Data Health",
            "Change & Drift",
            workflow_key="change_drift_workflow",
            workflow="Controlled DBA actions",
            state_updates={
                "dba_tools_focus": "Cost",
                "dba_tools_group_selector": "Cost & Health",
                "dba_tools_tool_selector_Cost & Health": "Data Health",
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

    _render_advanced_executive_rollups(company, environment, int(days))
