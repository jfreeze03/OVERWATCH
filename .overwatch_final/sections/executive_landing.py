# sections/executive_landing.py - executive landing page
from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape
import zipfile

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
from sections.navigation import apply_navigation_state
from sections.shell_helpers import render_refresh_contract, render_setup_health_board, render_shell_kpi_row, render_shell_snapshot, render_shell_status_strip
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
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")


EXECUTIVE_LANDING_VERSION = "2026-06-05-boardroom-pptx-v1"
PLATFORM_SUMMARY_STATE_KEY = "executive_landing_platform_summary"
OBSERVABILITY_STATE_KEY = "executive_landing_observability_board"

_PPTX_EMU_PER_INCH = 914400
_PPTX_SLIDE_WIDTH = 12192000
_PPTX_SLIDE_HEIGHT = 6858000
_PPTX_BG = "07111A"
_PPTX_PANEL = "0D2233"
_PPTX_CARD = "132D40"
_PPTX_GRID = "1D3346"
_PPTX_TEXT = "E8F3FF"
_PPTX_MUTED = "A9BED0"
_PPTX_ACCENT = "29B5E8"
_PPTX_RISK = "F97316"


def _altair():
    """Load Altair only when the slide chart pack is shown."""
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
    """Strict executive score with visible drivers and hard evidence caps."""
    prior_credits = safe_float(summary.get("prior_credits"))
    cost_delta = safe_float(summary.get("cost_delta"))
    critical_high = safe_int(summary.get("critical_high_alerts"))
    open_actions = safe_int(summary.get("open_actions"))
    high_actions = safe_int(summary.get("high_actions"))
    migration_blockers = safe_int(summary.get("migration_blockers"))
    source_rows = source_health if isinstance(source_health, pd.DataFrame) else pd.DataFrame()
    loaded_sources = int(source_rows["STATE"].eq("Loaded").sum()) if "STATE" in source_rows.columns else 0
    limited_sources = int(source_rows["STATE"].eq("Limited").sum()) if "STATE" in source_rows.columns else 0

    cost_delta_pct = cost_delta / max(prior_credits, 1.0) if cost_delta > 0 and prior_credits else 0.0
    cost_penalty = min(20.0, max(0.0, cost_delta_pct) * 35.0)
    alert_penalty = min(24.0, critical_high * 8.0)
    action_penalty = min(18.0, high_actions * 5.0 + max(0, open_actions - high_actions) * 0.5)
    deployment_penalty = min(24.0, migration_blockers * 12.0)
    evidence_penalty = min(18.0, limited_sources * 8.0)

    caps: list[tuple[int, str]] = []
    if limited_sources:
        caps.append((82, f"{limited_sources} executive evidence source(s) are limited."))
    if migration_blockers:
        caps.append((74, f"{migration_blockers} setup or migration blocker(s) cap the executive score."))
    if critical_high:
        caps.append((85, f"{critical_high} Critical/High open alert(s) cap the executive score."))
    if high_actions:
        caps.append((88, f"{high_actions} high-priority open action(s) cap the executive score."))
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
            next_action="Open Cost & Contract and validate the top cost mover before budget action.",
            cap=90 if cost_delta_pct >= 0.20 else None,
        ),
        _score_driver(
            "Reliability / Alerts",
            penalty=alert_penalty,
            evidence=f"{critical_high:,} Critical/High open alert(s).",
            next_action="Open Alert Center and confirm owner, SLA state, and escalation proof.",
            cap=85 if critical_high else None,
        ),
        _score_driver(
            "Owned Closure",
            penalty=action_penalty,
            evidence=f"{open_actions:,} open action(s), {high_actions:,} high-priority.",
            next_action="Open DBA Control Room and work owner-ready queue rows with verification evidence.",
            cap=88 if high_actions else None,
        ),
        _score_driver(
            "Deployment Trust",
            penalty=deployment_penalty,
            evidence=f"{migration_blockers:,} setup or migration blocker(s).",
            next_action="Open Setup Status and reconcile the migration ledger before leadership sign-off.",
            cap=74 if migration_blockers else None,
        ),
        _score_driver(
            "Evidence Coverage",
            penalty=evidence_penalty,
            evidence=f"{loaded_sources}/4 executive source(s) loaded; {limited_sources} limited.",
            next_action="Reload or route to the source section when evidence is limited.",
            cap=82 if limited_sources else None,
        ),
    ])
    if not drivers.empty:
        drivers = drivers.sort_values(["SCORE_IMPACT", "DRIVER"], ascending=[True, True]).reset_index(drop=True)

    raw_score = max(
        0.0,
        min(100.0, 100.0 - cost_penalty - alert_penalty - action_penalty - deployment_penalty - evidence_penalty),
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
    }


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
    return _with_platform_operating_score({
        "current_credits": current_credits,
        "prior_credits": prior_credits,
        "cost_delta": cost_delta,
        "top_increase_credits": safe_float(cost_row.get("TOP_INCREASE_CREDITS")),
        "critical_high_alerts": critical_high_alerts,
        "open_actions": int(action_mask.sum()) if len(action_mask) else 0,
        "high_actions": high_actions,
        "migration_blockers": migration_blockers,
        "top_cost_driver": str(cost_row.get("TOP_INCREASE_WAREHOUSE") or "No loaded driver"),
    })


def _default_platform_summary() -> dict:
    """Render an honest score frame before the executive mart or snapshot is loaded."""
    source_health = pd.DataFrame([
        {
            "SOURCE": "Executive observability mart",
            "STATE": "Limited",
            "EVIDENCE": "Precomputed board rows are not loaded for this scope.",
            "NEXT_ACTION": "Refresh the executive board after the OVERWATCH mart refresh completes.",
        },
        {
            "SOURCE": "Cost summary",
            "STATE": "Limited",
            "EVIDENCE": "Cost facts are not loaded in this executive session yet.",
            "NEXT_ACTION": "Open Cost & Contract or refresh the executive board for spend proof.",
        },
        {
            "SOURCE": "Alert and action queue",
            "STATE": "Limited",
            "EVIDENCE": "Open alert and owner-action counts are not loaded yet.",
            "NEXT_ACTION": "Open Alert Center or DBA Control Room for owner-ready triage.",
        },
        {
            "SOURCE": "Setup and migration trust",
            "STATE": "Limited",
            "EVIDENCE": "Setup status is not loaded in this executive session yet.",
            "NEXT_ACTION": "Open Governance & Security when setup proof is needed.",
        },
    ])
    return _with_platform_operating_score({
        "current_credits": 0.0,
        "prior_credits": 0.0,
        "cost_delta": 0.0,
        "top_increase_credits": 0.0,
        "critical_high_alerts": 0,
        "open_actions": 0,
        "high_actions": 0,
        "migration_blockers": 0,
        "top_cost_driver": "Not loaded",
    }, source_health)


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
        cap_reason = str(summary.get("cap_reason") or "")
        cap_detail = f" Score cap: {cap_reason}" if cap_reason and cap_reason != "No hard cap applied." else ""
        return {
            "state": str(summary["state"]),
            "headline": "Review the top exception before briefing leaders.",
            "detail": (
                f"{summary['critical_high_alerts']:,} Critical/High alert(s), "
                f"{summary['high_actions']:,} high-priority action(s), "
                f"{summary['migration_blockers']:,} deployment blocker(s).{cap_detail}"
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
                    f"{len(normalised):,} board row(s) loaded."
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
        source="Executive fact marts",
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
                f"{len(normalised):,} board row(s) loaded from the executive observability mart."
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
        return f"{safe_int(value)}/100"
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
        return "Not loaded"
    return _money(_obs_value(board, metric, column=column), signed=signed)


def _obs_count_label(board: pd.DataFrame, metric: str) -> str:
    if not _obs_metric_loaded(board, metric):
        return "Not loaded"
    return f"{safe_int(_obs_value(board, metric)):,}"


def _render_observability_source_status(board: pd.DataFrame) -> None:
    statuses = _obs_rows(board, "SOURCE_STATUS")
    if not isinstance(statuses, pd.DataFrame) or statuses.empty:
        return
    rows = statuses[["DIMENSION", "METRIC", "UNIT"]].copy()
    rows = rows.rename(columns={"DIMENSION": "SOURCE", "METRIC": "STATE", "UNIT": "DETAIL"})
    loaded = int(rows["STATE"].astype(str).eq("Loaded").sum()) if "STATE" in rows.columns else 0
    unavailable = int(rows["STATE"].astype(str).eq("Unavailable").sum()) if "STATE" in rows.columns else 0
    no_rows = int(rows["STATE"].astype(str).eq("No Rows").sum()) if "STATE" in rows.columns else 0
    with st.expander(
        f"Executive board source status: {loaded} loaded, {unavailable} unavailable, {no_rows} no rows",
        expanded=unavailable > 0 and loaded == 0,
    ):
        render_priority_dataframe(
            rows,
            title="Executive board source status",
            priority_columns=["SOURCE", "STATE", "DETAIL"],
            sort_by=["STATE", "SOURCE"],
            ascending=[True, True],
            raw_label="All executive board source rows",
            height=260,
            max_rows=12,
        )


def _summary_from_observability(board: pd.DataFrame, *, credit_price: float) -> dict | None:
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
    scored = _with_platform_operating_score(summary, pd.DataFrame([
        {"SOURCE": "Executive observability marts", "STATE": "Loaded", "EVIDENCE": "Precomputed board rows loaded."}
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


def _executive_priority_rows(board: pd.DataFrame, *, days: int) -> pd.DataFrame:
    """Convert the loaded KPI board into the first decisions leadership cares about."""
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
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
            "NEXT_ACTION": "Open Alert Center and work owner, SLA, and remediation proof.",
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
    return out.sort_values(["PRIORITY", "LANE"]).reset_index(drop=True)


def _render_executive_priority_board(board: pd.DataFrame, *, days: int) -> None:
    rows = _executive_priority_rows(board, days=int(days))
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


def _executive_pressure_rows(board: pd.DataFrame) -> pd.DataFrame:
    """Return one-page pressure lanes from the compact executive mart."""
    columns = [
        "LANE", "STATE", "VALUE", "PRESSURE_SCORE", "WHY_IT_MATTERS",
        "OWNER_ROUTE", "NEXT_ACTION",
    ]
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
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
            "STATE": _platform_score_state(platform_health) if _obs_metric_loaded(board, "Platform Health") else "Not loaded",
            "VALUE": f"{safe_int(platform_health)}/100" if _obs_metric_loaded(board, "Platform Health") else "Not loaded",
            "PRESSURE_SCORE": max(0.0, 100.0 - safe_float(platform_health)) if _obs_metric_loaded(board, "Platform Health") else 0.0,
            "WHY_IT_MATTERS": "Rolls cost, risk, workload, setup, and evidence caps into one board-level pressure signal.",
            "OWNER_ROUTE": "Executive Landing",
            "NEXT_ACTION": "Open the highest pressure lane below before specialist drilldown.",
        },
        {
            "LANE": "Cost movement",
            "STATE": "Rising" if spend_delta > 0 else "Flat / down",
            "VALUE": _money(spend_delta, signed=True) if _obs_metric_loaded(board, "Spend Delta") else "Not loaded",
            "PRESSURE_SCORE": capped(max(spend_delta, 0.0), max(current_spend * 0.20, 500.0)),
            "WHY_IT_MATTERS": "Leadership asks first why the bill moved and whether the increase has an owner.",
            "OWNER_ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Open Cost & Contract when this lane is above 40.",
        },
        {
            "LANE": "Cortex spend",
            "STATE": "Spend active" if cortex_spend > 0 else "No spend",
            "VALUE": _money(cortex_spend) if _obs_metric_loaded(board, "Cortex Spend") else "Not loaded",
            "PRESSURE_SCORE": capped(cortex_spend, 500.0),
            "WHY_IT_MATTERS": "AI spend can grow without warehouse-style owner habits or quota guardrails.",
            "OWNER_ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Review top AI user/source and quota posture.",
        },
        {
            "LANE": "Queue pressure",
            "STATE": "Queued" if queue_seconds > 0 else "Clear",
            "VALUE": _format_seconds(queue_seconds) if _obs_metric_loaded(board, "Queue Time") else "Not loaded",
            "PRESSURE_SCORE": capped(queue_seconds, 3600.0),
            "WHY_IT_MATTERS": "Queue time turns into missed SLAs, frustrated users, and sometimes wasteful resize decisions.",
            "OWNER_ROUTE": "DBA Control Room",
            "NEXT_ACTION": "Check warehouse pressure and contention before resizing.",
        },
        {
            "LANE": "Spillage",
            "STATE": "Spilling" if spill_gb > 0 else "Clear",
            "VALUE": _format_gb(spill_gb) if _obs_metric_loaded(board, "Remote Spill") else "Not loaded",
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
            "VALUE": f"{safe_float(storage_tb):,.2f} TB" if _obs_metric_loaded(board, "Storage") else "Not loaded",
            "PRESSURE_SCORE": capped(storage_tb, 50.0),
            "WHY_IT_MATTERS": "Storage, failsafe, and stages become contract noise when growth lacks lifecycle controls.",
            "OWNER_ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Review storage growth and cleanup candidates when this lane climbs.",
        },
    ]
    out = pd.DataFrame(rows, columns=columns)
    return out.sort_values(["PRESSURE_SCORE", "LANE"], ascending=[False, True]).reset_index(drop=True)


def _render_executive_pressure_board(board: pd.DataFrame) -> None:
    rows = _executive_pressure_rows(board)
    if rows.empty:
        return
    st.markdown("**Executive Pressure Index**")
    render_shell_kpi_row((
        ("Highest Pressure", str(rows.iloc[0].get("LANE") or "Loaded")),
        ("Score", f"{safe_float(rows.iloc[0].get('PRESSURE_SCORE')):,.0f}/100"),
        ("Owner Route", str(rows.iloc[0].get("OWNER_ROUTE") or "Executive Landing")),
        ("State", str(rows.iloc[0].get("STATE") or "Review")),
    ))
    chart_rows = rows.copy()
    chart_rows["PRESSURE_SCORE"] = pd.to_numeric(chart_rows["PRESSURE_SCORE"], errors="coerce").fillna(0.0)
    alt = _altair()
    chart = (
        alt.Chart(chart_rows)
        .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3, color="#29B5E8")
        .encode(
            x=alt.X("PRESSURE_SCORE:Q", title="Pressure Score", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y(
                "LANE:N",
                sort=alt.SortField(field="PRESSURE_SCORE", order="descending"),
                title=None,
                axis=alt.Axis(labelLimit=180),
            ),
            tooltip=[
                alt.Tooltip("LANE:N", title="Lane"),
                alt.Tooltip("STATE:N", title="State"),
                alt.Tooltip("VALUE:N", title="Value"),
                alt.Tooltip("PRESSURE_SCORE:Q", title="Pressure", format=",.0f"),
                alt.Tooltip("OWNER_ROUTE:N", title="Owner route"),
                alt.Tooltip("NEXT_ACTION:N", title="Next action"),
            ],
        )
        .properties(height=250)
    )
    st.altair_chart(chart, width="stretch")
    render_priority_dataframe(
        rows,
        title="Executive pressure details",
        priority_columns=[
            "LANE", "STATE", "VALUE", "PRESSURE_SCORE",
            "OWNER_ROUTE", "WHY_IT_MATTERS", "NEXT_ACTION",
        ],
        sort_by=["PRESSURE_SCORE", "LANE"],
        ascending=[False, True],
        raw_label="All executive pressure rows",
        height=250,
        max_rows=8,
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
    st.markdown(f"**{title}**")
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
    st.markdown(f"**{title}**")
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
    def _render_mart_health_contract() -> None:
        render_setup_health_board(
            "Executive Mart Health",
            (
                ("Executive mart", "MART_EXECUTIVE_OBSERVABILITY"),
                ("Cost/Cortex", "FACT_COST_DAILY / FACT_CORTEX_DAILY"),
                ("Workload", "QUERY / TASK facts"),
                ("Alerts", "ALERT_EVENTS / action queue"),
            ),
            cadence="60 min scheduled refresh",
            fallback="No live ACCOUNT_USAGE scan on first paint",
            owner="DBA / FinOps / Security",
        )

    error = str((payload or {}).get("error") or "").strip()
    if not isinstance(board, pd.DataFrame) or board.empty or not _has_observability_kpis(board):
        render_shell_status_strip(
            state="Setup Needed" if error else "Waiting",
            headline="Executive observability board is ready for precomputed Snowflake facts.",
            detail=(
                error
                if error
                else "Run the OVERWATCH mart refresh to populate cost, query, task, storage, alert, and Cortex facts."
            ),
        )
        render_shell_kpi_row((
            ("Scope", f"{company} / {get_environment_label(environment, company)}"),
            ("Window", f"{int(days)}d"),
            ("Source", "Precomputed marts"),
            ("Status", "No rows"),
        ))
        render_refresh_contract(
            payload,
            source="MART_EXECUTIVE_OBSERVABILITY",
            target_minutes=60,
            refresh_method="Scheduled OVERWATCH mart refresh",
            live_fallback="No",
        )
        _render_mart_health_contract()
        st.markdown("**Executive Metric Board**")
        st.markdown("**Executive Command Wall**")
        render_shell_kpi_row((
            ("Spend", "Not loaded"),
            ("Delta", "Not loaded"),
            ("Cortex", "Not loaded"),
            ("30d Forecast", "Not loaded"),
        ))
        render_shell_kpi_row((
            ("Queries", "Not loaded"),
            ("Avg Runtime", "Not loaded"),
            ("P95 Runtime", "Not loaded"),
            ("Remote Spill", "Not loaded"),
        ))
        render_shell_kpi_row((
            ("Critical / High", "Not loaded"),
            ("Failed Queries", "Not loaded"),
            ("Failed Tasks", "Not loaded"),
            ("Open Actions", "Not loaded"),
        ))
        render_shell_kpi_row((
            ("Queue Time", "Not loaded"),
            ("Avg/day", "Not loaded"),
            ("Storage", "Not loaded"),
            ("Freshness", "Not loaded"),
        ))
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
        "Executive board schema loaded, but the mart has no recent fact rows for this scope."
        if not has_fact_trends
        else "Snowflake observability summary loaded from precomputed OVERWATCH facts."
    )
    status_detail = (
        "Run or verify the OVERWATCH mart refresh before using this view for leadership numbers."
        if not has_fact_trends
        else (
            f"{int(days)}-day view: cost, Cortex, query runtime, queue pressure, spill, task health, and storage. "
            "Alerts and action-queue counts remain Not loaded unless their secure app tables are available to this role. "
            "Detailed proof stays in the specialist sections."
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
        source="MART_EXECUTIVE_OBSERVABILITY",
        target_minutes=60,
        refresh_method="Scheduled OVERWATCH mart refresh",
        live_fallback="No",
    )
    _render_mart_health_contract()
    st.markdown("**Executive Command Wall**")
    render_shell_kpi_row((
        ("Platform", f"{safe_int(health)}/100" if health else "Loaded"),
        ("Spend", _obs_money_label(board, "Credits Used")),
        ("Delta", _obs_money_label(board, "Spend Delta", signed=True)),
        ("Cortex", _obs_money_label(board, "Cortex Spend")),
    ))
    render_shell_kpi_row((
        ("Queries", _obs_count_label(board, "Total Queries")),
        ("Avg Runtime", _format_seconds(avg_runtime) if _obs_metric_loaded(board, "Avg Runtime") else "Not loaded"),
        ("P95 Runtime", _format_seconds(p95_runtime) if _obs_metric_loaded(board, "P95 Runtime") else "Not loaded"),
        ("Remote Spill", _format_gb(spill_gb) if _obs_metric_loaded(board, "Remote Spill") else "Not loaded"),
    ))
    render_shell_kpi_row((
        ("Critical / High", _obs_count_label(board, "Critical High Alerts")),
        ("Failed Queries", _obs_count_label(board, "Failed Queries")),
        ("Failed Tasks", _obs_count_label(board, "Failed Tasks")),
        ("Open Actions", _obs_count_label(board, "Open Actions")),
    ))
    render_shell_kpi_row((
        ("Queue Time", _format_seconds(queue_seconds) if _obs_metric_loaded(board, "Queue Time") else "Not loaded"),
        ("30d Forecast", _money(month_end_forecast) if _obs_metric_loaded(board, "Credits Used") else "Not loaded"),
        ("Avg/day", _money(avg_daily_spend) if _obs_metric_loaded(board, "Credits Used") else "Not loaded"),
        ("Storage", f"{safe_float(storage_tb):,.2f} TB / {_money(storage_cost)}" if _obs_metric_loaded(board, "Storage") else "Not loaded"),
    ))
    _render_executive_pressure_board(board)
    _render_executive_priority_board(board, days=int(days))

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
        pressure["PRESSURE_SCORE"] = pd.to_numeric(pressure["VALUE"], errors="coerce").fillna(0)
        pressure = pressure.groupby("DIMENSION", as_index=False, sort=False)["PRESSURE_SCORE"].sum()
    _render_bar_chart(
        pressure,
        title="Warehouse Pressure: Queue + Spill",
        x_column="DIMENSION",
        y_column="PRESSURE_SCORE",
        x_title="Pressure Score",
        color="#F97316",
        height=260,
    )

    freshness = _obs_rows(board, "FRESHNESS")
    if isinstance(freshness, pd.DataFrame) and not freshness.empty:
        with st.expander("Board data freshness", expanded=False):
            rows = freshness[["DIMENSION", "PERIOD_START", "UNIT"]].copy()
            rows = rows.rename(columns={"DIMENSION": "SOURCE", "PERIOD_START": "LATEST_LOAD", "UNIT": "TYPE"})
            render_priority_dataframe(
                rows,
                title="Precomputed source freshness",
                priority_columns=["SOURCE", "LATEST_LOAD", "TYPE"],
                raw_label="All executive board freshness rows",
                height=180,
                max_rows=8,
            )
    _render_observability_source_status(board)


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
        ("Executive state", f"{summary.get('state')} ({safe_float(summary.get('score')):.0f}/100)", "Platform Operating Score with hard evidence caps."),
        ("Score cap", "None" if safe_int(summary.get("score_cap"), 100) >= 100 else f"{safe_int(summary.get('score_cap'))}/100", str(summary.get("cap_reason") or "No hard cap applied.")),
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
            f"Score cap: {summary.get('cap_reason') or 'No hard cap applied.'}",
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


def _safe_filename_piece(value: object) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    text = "_".join(part for part in text.split("_") if part)
    return text[:80] or "scope"


def _pptx_emu(inches: float) -> int:
    return int(float(inches) * _PPTX_EMU_PER_INCH)


def _pptx_color(value: str | None, fallback: str = _PPTX_TEXT) -> str:
    text = str(value or fallback).strip().lstrip("#")
    return text.upper()[:6] if len(text) >= 6 else fallback


def _pptx_escape(value: object) -> str:
    return xml_escape(str(value or ""), {'"': "&quot;", "'": "&apos;"})


def _pptx_text_lines(value: object, *, max_lines: int | None = None) -> list[str]:
    lines = [line.strip() for line in str(value or "").replace("\r\n", "\n").split("\n") if line.strip()]
    return lines[:max_lines] if max_lines is not None else lines


def _pptx_paragraphs(lines: list[str], *, font_size: int, color: str, bold: bool = False) -> str:
    size = max(800, int(font_size * 100))
    bold_attr = ' b="1"' if bold else ""
    color = _pptx_color(color)
    if not lines:
        lines = [""]
    return "".join(
        f'<a:p><a:r><a:rPr lang="en-US" sz="{size}"{bold_attr}>'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:rPr>'
        f"<a:t>{_pptx_escape(line)}</a:t></a:r>"
        f'<a:endParaRPr lang="en-US" sz="{size}"/></a:p>'
        for line in lines
    )


def _pptx_shape(
    shape_id: int,
    name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    lines: list[str] | str,
    *,
    font_size: int = 16,
    color: str = _PPTX_TEXT,
    bold: bool = False,
    fill: str | None = None,
    line: str | None = None,
    radius: bool = False,
    margin: int = 91440,
) -> str:
    if isinstance(lines, str):
        lines = _pptx_text_lines(lines)
    fill_xml = (
        f'<a:solidFill><a:srgbClr val="{_pptx_color(fill)}"/></a:solidFill>'
        if fill
        else "<a:noFill/>"
    )
    line_xml = (
        f'<a:ln><a:solidFill><a:srgbClr val="{_pptx_color(line)}"/></a:solidFill></a:ln>'
        if line
        else "<a:ln><a:noFill/></a:ln>"
    )
    geometry = "roundRect" if radius else "rect"
    return (
        "<p:sp><p:nvSpPr>"
        f'<p:cNvPr id="{shape_id}" name="{_pptx_escape(name)}"/>'
        '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>'
        f'<a:xfrm><a:off x="{_pptx_emu(x)}" y="{_pptx_emu(y)}"/>'
        f'<a:ext cx="{_pptx_emu(width)}" cy="{_pptx_emu(height)}"/></a:xfrm>'
        f'<a:prstGeom prst="{geometry}"><a:avLst/></a:prstGeom>'
        f"{fill_xml}{line_xml}</p:spPr>"
        f'<p:txBody><a:bodyPr wrap="square" anchor="t" lIns="{margin}" tIns="{margin}" rIns="{margin}" bIns="{margin}"/>'
        f"<a:lstStyle/>{_pptx_paragraphs(lines, font_size=font_size, color=color, bold=bold)}</p:txBody></p:sp>"
    )


def _pptx_slide_xml(shapes: list[str], *, background: str = _PPTX_BG) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld>'
        f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{_pptx_color(background)}"/></a:solidFill></p:bgPr></p:bg>'
        '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"{''.join(shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )


def _pptx_slide_brief_parts(slide_brief: str) -> tuple[str, list[str]]:
    lines = _pptx_text_lines(slide_brief)
    headline = next((line.replace("Headline:", "").strip() for line in lines if line.startswith("Headline:")), "")
    bullets = [line[2:].strip() for line in lines if line.startswith("- ")]
    return headline or "Executive KPI brief loaded.", bullets[:6]


def _pptx_kpi_lookup(kpi_rows: pd.DataFrame) -> dict[str, tuple[str, str]]:
    if not isinstance(kpi_rows, pd.DataFrame) or kpi_rows.empty:
        return {}
    lookup: dict[str, tuple[str, str]] = {}
    for _, row in kpi_rows.iterrows():
        key = str(row.get("KPI") or "").strip()
        if key:
            lookup[key] = (str(row.get("VALUE") or ""), str(row.get("SLIDE_NOTE") or ""))
    return lookup


def _pptx_bar_panel(
    chart_rows: pd.DataFrame,
    chart_name: str,
    *,
    start_id: int,
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[str]:
    if not isinstance(chart_rows, pd.DataFrame) or chart_rows.empty:
        data = pd.DataFrame()
    else:
        data = chart_rows[chart_rows["CHART"].astype(str) == chart_name].copy()
    shapes = [
        _pptx_shape(start_id, f"{chart_name} panel", x, y, width, height, "", fill=_PPTX_PANEL, radius=True),
        _pptx_shape(start_id + 1, f"{chart_name} title", x + 0.18, y + 0.12, width - 0.35, 0.28, chart_name, font_size=15, color="FFFFFF", bold=True),
    ]
    if data.empty:
        shapes.append(_pptx_shape(start_id + 2, f"{chart_name} empty", x + 0.2, y + 0.62, width - 0.4, 0.35, "No chart rows loaded.", font_size=11, color=_PPTX_MUTED))
        return shapes
    data["VALUE"] = pd.to_numeric(data["VALUE"], errors="coerce").fillna(0)
    max_abs = max(abs(float(data["VALUE"].min())), abs(float(data["VALUE"].max())), 1.0)
    has_negative = bool((data["VALUE"] < 0).any())
    label_width = min(2.0, width * 0.34)
    track_x = x + label_width + 0.45
    track_width = max(0.8, width - label_width - 1.15)
    row_height = max(0.36, min(0.58, (height - 0.72) / max(1, len(data.head(6)))))
    for row_idx, (_, row) in enumerate(data.head(6).iterrows()):
        value = safe_float(row.get("VALUE"))
        label = str(row.get("METRIC") or "")
        display = str(row.get("LABEL") or f"{value:,.0f}")
        row_y = y + 0.58 + row_idx * row_height
        shapes.append(_pptx_shape(start_id + 10 + row_idx * 5, f"{chart_name} label {row_idx}", x + 0.18, row_y, label_width, row_height * 0.75, label, font_size=9, color=_PPTX_MUTED, margin=45720))
        shapes.append(_pptx_shape(start_id + 11 + row_idx * 5, f"{chart_name} track {row_idx}", track_x, row_y + 0.08, track_width, row_height * 0.42, "", fill=_PPTX_GRID))
        if has_negative:
            half = track_width / 2
            bar_width = max(0.05, half * min(1.0, abs(value) / max_abs))
            bar_x = track_x + half - bar_width if value < 0 else track_x + half
        else:
            bar_width = max(0.05, track_width * min(1.0, abs(value) / max_abs))
            bar_x = track_x
        shapes.append(_pptx_shape(start_id + 12 + row_idx * 5, f"{chart_name} bar {row_idx}", bar_x, row_y + 0.08, bar_width, row_height * 0.42, "", fill=_PPTX_RISK if value < 0 else _PPTX_ACCENT))
        shapes.append(_pptx_shape(start_id + 13 + row_idx * 5, f"{chart_name} value {row_idx}", track_x + track_width + 0.08, row_y, 0.8, row_height * 0.75, display, font_size=9, color=_PPTX_TEXT, bold=True, margin=45720))
    return shapes


def _build_executive_snapshot_title_slide(
    slide_brief: str,
    kpi_rows: pd.DataFrame,
    *,
    company: str,
    environment_label: str,
    days: int,
) -> str:
    headline, bullets = _pptx_slide_brief_parts(slide_brief)
    kpis = _pptx_kpi_lookup(kpi_rows)
    cards = [
        ("Current spend", *kpis.get("Current spend", ("$0", ""))),
        ("Spend delta", *kpis.get("Spend delta", ("$0", ""))),
        ("Critical/High alerts", *kpis.get("Critical/High alerts", ("0", ""))),
        ("Open actions", *kpis.get("Open actions", ("0", ""))),
    ]
    shapes = [
        _pptx_shape(2, "Title", 0.55, 0.34, 8.4, 0.55, "OVERWATCH Executive Snapshot", font_size=28, bold=True),
        _pptx_shape(3, "Scope", 0.58, 0.9, 7.9, 0.3, f"{company} / {environment_label} / {int(days)} days", font_size=12, color=_PPTX_MUTED),
        _pptx_shape(4, "Headline", 0.58, 1.35, 7.35, 0.72, headline, font_size=18, color="FFFFFF", bold=True),
        _pptx_shape(5, "Bullets", 0.58, 2.18, 7.2, 3.72, [f"- {line}" for line in bullets], font_size=15, color=_PPTX_TEXT),
    ]
    for idx, (label, value, note) in enumerate(cards):
        y = 1.12 + idx * 1.24
        shapes.append(_pptx_shape(10 + idx, f"Card {label}", 8.35, y, 4.25, 0.95, "", fill=_PPTX_CARD, radius=True))
        shapes.append(_pptx_shape(20 + idx, f"Card label {label}", 8.52, y + 0.08, 3.8, 0.2, label, font_size=9, color=_PPTX_MUTED, bold=True))
        shapes.append(_pptx_shape(30 + idx, f"Card value {label}", 8.52, y + 0.31, 3.8, 0.34, value, font_size=20, color="FFFFFF", bold=True))
        shapes.append(_pptx_shape(40 + idx, f"Card note {label}", 8.52, y + 0.67, 3.85, 0.2, note, font_size=8, color=_PPTX_MUTED))
    return _pptx_slide_xml(shapes)


def _build_executive_snapshot_chart_slide(chart_rows: pd.DataFrame, kpi_rows: pd.DataFrame, *, company: str, environment_label: str) -> str:
    kpis = _pptx_kpi_lookup(kpi_rows)
    score = kpis.get("Executive state", ("Not loaded", ""))[0]
    sources = kpis.get("Sources loaded", ("0/4", ""))[0]
    shapes = [
        _pptx_shape(2, "Title", 0.55, 0.34, 8.0, 0.55, "Boardroom KPI Drivers", font_size=27, bold=True),
        _pptx_shape(3, "Scope", 0.58, 0.92, 7.5, 0.3, f"{company} / {environment_label}", font_size=12, color=_PPTX_MUTED),
        _pptx_shape(4, "Score", 8.25, 0.42, 2.0, 0.62, [score, "Executive state"], font_size=14, color="FFFFFF", bold=True, fill=_PPTX_CARD, radius=True),
        _pptx_shape(5, "Sources", 10.45, 0.42, 2.0, 0.62, [sources, "Sources loaded"], font_size=14, color="FFFFFF", bold=True, fill=_PPTX_CARD, radius=True),
    ]
    shapes.extend(_pptx_bar_panel(chart_rows, "Cost movement", start_id=20, x=0.65, y=1.45, width=5.95, height=4.65))
    shapes.extend(_pptx_bar_panel(chart_rows, "Risk and work", start_id=90, x=6.85, y=1.45, width=5.85, height=4.65))
    return _pptx_slide_xml(shapes)


def _pptx_rels(entries: list[tuple[str, str, str]]) -> str:
    relationships = "".join(
        f'<Relationship Id="{rel_id}" Type="{rel_type}" Target="{_pptx_escape(target)}"/>'
        for rel_id, rel_type, target in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{relationships}</Relationships>"
    )


def _pptx_content_types(slide_count: int) -> str:
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{idx}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for idx in range(1, slide_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        f"{slide_overrides}</Types>"
    )


def _pptx_presentation_xml(slide_count: int) -> str:
    slide_ids = "".join(f'<p:sldId id="{255 + idx}" r:id="rId{idx + 1}"/>' for idx in range(1, slide_count + 1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
        f'<p:sldSz cx="{_PPTX_SLIDE_WIDTH}" cy="{_PPTX_SLIDE_HEIGHT}" type="wide"/>'
        '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    )


def _pptx_slide_master_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
        '<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>'
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
        'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        '<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>'
    )


def _pptx_slide_layout_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">'
        '<p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
        '<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>'
        '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
    )


def _pptx_theme_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="OVERWATCH">'
        '<a:themeElements><a:clrScheme name="OVERWATCH">'
        '<a:dk1><a:srgbClr val="07111A"/></a:dk1><a:lt1><a:srgbClr val="F8FAFC"/></a:lt1>'
        '<a:dk2><a:srgbClr val="13283A"/></a:dk2><a:lt2><a:srgbClr val="B8C7D8"/></a:lt2>'
        '<a:accent1><a:srgbClr val="29B5E8"/></a:accent1><a:accent2><a:srgbClr val="71D3DC"/></a:accent2>'
        '<a:accent3><a:srgbClr val="F97316"/></a:accent3><a:accent4><a:srgbClr val="10B981"/></a:accent4>'
        '<a:accent5><a:srgbClr val="EAB308"/></a:accent5><a:accent6><a:srgbClr val="8B5CF6"/></a:accent6>'
        '<a:hlink><a:srgbClr val="29B5E8"/></a:hlink><a:folHlink><a:srgbClr val="71D3DC"/></a:folHlink>'
        '</a:clrScheme><a:fontScheme name="OVERWATCH"><a:majorFont><a:latin typeface="Aptos Display"/>'
        '<a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/>'
        '<a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="OVERWATCH">'
        '<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/></a:schemeClr></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:shade val="85000"/></a:schemeClr></a:solidFill></a:fillStyleLst>'
        '<a:lnStyleLst><a:ln w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/>'
        '</a:solidFill><a:prstDash val="solid"/></a:ln><a:ln w="12700" cap="flat" cmpd="sng" algn="ctr">'
        '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
        '<a:ln w="19050" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/>'
        '</a:solidFill><a:prstDash val="solid"/></a:ln></a:lnStyleLst>'
        '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/>'
        '</a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
        '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/></a:schemeClr></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:shade val="85000"/></a:schemeClr></a:solidFill></a:bgFillStyleLst>'
        "</a:fmtScheme></a:themeElements></a:theme>"
    )


def _pptx_doc_props(slide_count: int) -> tuple[str, str]:
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>OVERWATCH Executive Snapshot</dc:title><dc:creator>OVERWATCH</dc:creator>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>OVERWATCH</Application><PresentationFormat>On-screen Show (16:9)</PresentationFormat>'
        f"<Slides>{int(slide_count)}</Slides></Properties>"
    )
    return core, app


def _build_executive_snapshot_pptx(
    slide_brief: str,
    kpi_rows: pd.DataFrame,
    chart_rows: pd.DataFrame,
    *,
    company: str,
    environment_label: str,
    days: int,
) -> bytes:
    slides = [
        _build_executive_snapshot_title_slide(slide_brief, kpi_rows, company=company, environment_label=environment_label, days=days),
        _build_executive_snapshot_chart_slide(chart_rows, kpi_rows, company=company, environment_label=environment_label),
    ]
    core_props, app_props = _pptx_doc_props(len(slides))
    presentation_rels = [(
        "rId1",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
        "slideMasters/slideMaster1.xml",
    )]
    presentation_rels.extend(
        (
            f"rId{idx + 1}",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
            f"slides/slide{idx}.xml",
        )
        for idx in range(1, len(slides) + 1)
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _pptx_content_types(len(slides)))
        archive.writestr("_rels/.rels", _pptx_rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "ppt/presentation.xml"),
            ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
            ("rId3", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties", "docProps/app.xml"),
        ]))
        archive.writestr("docProps/core.xml", core_props)
        archive.writestr("docProps/app.xml", app_props)
        archive.writestr("ppt/presentation.xml", _pptx_presentation_xml(len(slides)))
        archive.writestr("ppt/_rels/presentation.xml.rels", _pptx_rels(presentation_rels))
        archive.writestr("ppt/slideMasters/slideMaster1.xml", _pptx_slide_master_xml())
        archive.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _pptx_rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme", "../theme/theme1.xml"),
        ]))
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", _pptx_slide_layout_xml())
        archive.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _pptx_rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster", "../slideMasters/slideMaster1.xml"),
        ]))
        archive.writestr("ppt/theme/theme1.xml", _pptx_theme_xml())
        for idx, slide_xml in enumerate(slides, start=1):
            archive.writestr(f"ppt/slides/slide{idx}.xml", slide_xml)
            archive.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", _pptx_rels([
                ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "../slideLayouts/slideLayout1.xml"),
            ]))
    return buffer.getvalue()


def _render_powerpoint_kpi_strip(kpi_rows: pd.DataFrame) -> None:
    lookup = _pptx_kpi_lookup(kpi_rows)
    cards = [
        ("Current Spend", lookup.get("Current spend", ("$0", ""))[0]),
        ("Spend Delta", lookup.get("Spend delta", ("$0", ""))[0]),
        ("Critical / High", lookup.get("Critical/High alerts", ("0", ""))[0]),
        ("Open Actions", lookup.get("Open actions", ("0", ""))[0]),
    ]
    render_shell_snapshot(tuple(cards))


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
    file_scope = f"{_safe_filename_piece(company)}_{_safe_filename_piece(environment_label)}_{int(days)}d"
    deck_bytes = _build_executive_snapshot_pptx(
        slide_brief,
        kpi_rows,
        chart_rows,
        company=company,
        environment_label=environment_label,
        days=days,
    )
    st.markdown("**PowerPoint Executive Snapshot**")
    st.text_area("Slide bullets", value=slide_brief, height=230, key="executive_powerpoint_slide_bullets")
    _render_powerpoint_kpi_strip(kpi_rows)
    dl_cols = st.columns([1.0, 1.0, 1.0, 1.0])
    dl_cols[0].download_button(
        "Download bullets",
        slide_brief,
        file_name=f"overwatch_executive_snapshot_{file_scope}.txt",
        mime="text/plain",
        key="executive_powerpoint_bullets_download",
    )
    dl_cols[1].download_button(
        "Download chart data",
        chart_rows.to_csv(index=False, sep="\t"),
        file_name=f"overwatch_executive_snapshot_{file_scope}_chart_data.tsv",
        mime="text/tab-separated-values",
        key="executive_powerpoint_chart_data_download",
    )
    dl_cols[2].download_button(
        "Download PowerPoint",
        deck_bytes,
        file_name=f"overwatch_executive_snapshot_{file_scope}.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        key="executive_powerpoint_deck_download",
    )
    chart_cols = st.columns(2)
    with chart_cols[0]:
        st.markdown("**Cost Movement**")
        _render_slide_bar_chart(chart_rows, "Cost movement")
    with chart_cols[1]:
        st.markdown("**Risk and Work**")
        _render_slide_bar_chart(chart_rows, "Risk and work")
    with st.expander("PowerPoint support data", expanded=False):
        render_priority_dataframe(
            kpi_rows,
            title="Slide KPI rows",
            priority_columns=["KPI", "VALUE", "SLIDE_NOTE"],
            raw_label="All executive slide KPI rows",
            height=250,
            max_rows=10,
        )
        render_priority_dataframe(
            chart_rows,
            title="Slide chart rows",
            priority_columns=["CHART", "METRIC", "VALUE", "LABEL"],
            raw_label="All executive slide chart rows",
            height=240,
            max_rows=12,
        )


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


def _render_platform_operating_score(summary: dict | None) -> None:
    if not summary:
        return
    drivers = summary.get("platform_score_drivers")
    if not isinstance(drivers, pd.DataFrame):
        drivers = pd.DataFrame()
    cap_value = safe_int(summary.get("score_cap"), 100)
    cap_label = "None" if cap_value >= 100 else f"{cap_value}/100"
    st.markdown("**Platform Operating Score**")
    render_shell_kpi_row((
        ("Score", f"{safe_int(summary.get('score'))}/100"),
        ("State", str(summary.get("state") or "Review")),
        ("Raw", f"{safe_float(summary.get('raw_score')):,.1f}/100"),
        ("Cap", cap_label),
    ))
    if not drivers.empty:
        render_priority_dataframe(
            drivers,
            title="Platform score drivers",
            priority_columns=["DRIVER", "STATE", "SCORE_IMPACT", "EVIDENCE", "SCORE_CAP", "NEXT_ACTION"],
            sort_by=["SCORE_IMPACT", "DRIVER"],
            ascending=[True, True],
            raw_label="All platform operating score drivers",
            height=260,
            max_rows=5,
        )


def _render_command_intelligence_maturity() -> None:
    from utils.operational_intelligence import build_god_tier_capability_rows

    rows = pd.DataFrame(build_god_tier_capability_rows())
    if rows.empty:
        return
    render_priority_dataframe(
        rows.head(6),
        title="Command center maturity priorities",
        priority_columns=[
            "RANK", "CAPABILITY", "STATUS", "WHERE_IT_LANDS",
            "WHY_IT_MATTERS", "NEXT_ACTION",
        ],
        sort_by=["RANK"],
        ascending=True,
        raw_label="All command center maturity priorities",
        height=240,
        max_rows=6,
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
            ("Evidence", "On demand"),
        )
    else:
        metrics = (
            ("Score", f"{safe_int(summary['score'])}/100"),
            ("Spend", f"${credits_to_dollars(summary['current_credits'], credit_price):,.0f}"),
            ("Alerts", f"{summary['critical_high_alerts']:,}"),
            ("Deploy", f"{summary['migration_blockers']:,}"),
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
            _state("Cost summary unavailable", "Cost cockpit", "cost"),
            _state("Alert evidence unavailable", "Alert evidence", "alerts"),
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
            "Refresh Board",
            key="executive_landing_observability_refresh",
            type="primary",
            width="stretch",
        )
    expected_scope = _executive_snapshot_scope(company, environment, int(days))
    board, board_payload = _current_observability_board(company, environment, int(days))
    if refresh_board:
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
    summary = _summary_from_observability(board, credit_price=credit_price)
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

    if load:
        if _load_executive_snapshot(company, environment, int(days)):
            st.rerun()

    snapshot = st.session_state.get("executive_landing_snapshot")
    if not isinstance(snapshot, dict) or not _snapshot_matches_scope(snapshot, company, environment, int(days)):
        _render_platform_operating_score(summary)
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
        ("Sources Loaded", f"{loaded_sources}/4"),
        ("Limited Sources", f"{limited_sources}"),
        ("No-Row Sources", f"{no_row_sources}"),
    ))
    with st.expander("Executive source health", expanded=False):
        render_priority_dataframe(
            source_health,
            title="Executive source health",
            priority_columns=["SOURCE", "STATE", "EVIDENCE", "NEXT_ACTION"],
            sort_by=["STATE", "SOURCE"],
            ascending=[True, True],
            raw_label="All executive source health rows",
            height=220,
        )

    _render_platform_operating_score(summary)
    _render_command_intelligence_maturity()

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
