"""Leadership monitoring panels for stakeholder-run manual query themes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from html import escape as _escape
import math
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st

from queries import leadership_watchlist as leadership_queries
from utils.display_safety import clean_display_text
from utils.primitives import safe_float, safe_int


@dataclass(frozen=True)
class AlertCandidate:
    category: str
    threshold: str
    severity: str
    route: str
    owner: str
    source_panel: str
    suppression: str


def _html(value: object) -> str:
    return _escape(clean_display_text(value))


def _today() -> date:
    return date.today()


def _window(days: int) -> tuple[date, date]:
    end = _today()
    return end - timedelta(days=max(1, int(days)) - 1), end


def _clean_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        safe = frame.copy()
        forbidden = {"USER_ID", "RAW_USER_ID", "CREDENTIAL_ID", "QUERY_TEXT", "SOURCE_OBJECT"}
        return safe[[column for column in safe.columns if str(column).upper() not in forbidden]]
    return pd.DataFrame()


def _series(frame: pd.DataFrame, column: str) -> list[float]:
    if column not in frame.columns:
        return []
    values = pd.to_numeric(frame[column], errors="coerce").dropna().tail(24).tolist()
    return [safe_float(value) for value in values]


def _sparkline(values: Sequence[float], *, tone: str = "info") -> str:
    finite = [float(value) for value in values if math.isfinite(safe_float(value, default=float("nan")))]
    if len(finite) < 2:
        return (
            '<svg class="ow-lw-chart ow-lw-chart-empty" viewBox="0 0 320 92" role="img" '
            'aria-label="Trend unavailable"><path d="M12 70h296"/></svg>'
        )
    low = min(finite)
    high = max(finite)
    span = high - low or 1.0
    step = 296 / max(len(finite) - 1, 1)
    coords = []
    for index, value in enumerate(finite):
        x = 12 + index * step
        y = 76 - ((value - low) / span * 58)
        coords.append(f"{x:.2f},{y:.2f}")
    return (
        f'<svg class="ow-lw-chart" data-tone="{_html(tone)}" viewBox="0 0 320 92" role="img" aria-label="Trend">'
        '<path class="ow-lw-fill" d="M12 84 '
        + " ".join(f"L{point}" for point in coords)
        + ' L308 84 Z"></path>'
        f'<polyline points="{" ".join(coords)}"></polyline>'
        "</svg>"
    )


def _bar_chart(labels: Sequence[object], values: Sequence[object], *, tone: str = "info") -> str:
    pairs = [
        (_html(label), max(0.0, safe_float(value)))
        for label, value in zip(labels, values, strict=False)
    ][:8]
    if not pairs:
        return (
            '<svg class="ow-lw-chart ow-lw-chart-empty" viewBox="0 0 320 92" role="img" '
            'aria-label="No rows"><path d="M12 70h296"/></svg>'
        )
    high = max(value for _, value in pairs) or 1.0
    rows = []
    for index, (label, value) in enumerate(pairs):
        y = 12 + index * 10
        width = 210 * value / high
        rows.append(
            f'<text x="12" y="{y + 6}" class="ow-lw-bar-label">{label[:20]}</text>'
            f'<rect x="112" y="{y}" width="{width:.1f}" height="6" rx="3"></rect>'
            f'<text x="{118 + width:.1f}" y="{y + 6}" class="ow-lw-bar-value">{value:,.0f}</text>'
        )
    return (
        f'<svg class="ow-lw-chart ow-lw-bars" data-tone="{_html(tone)}" viewBox="0 0 320 92" '
        'role="img" aria-label="Ranked bar chart">'
        + "".join(rows)
        + "</svg>"
    )


def _format_table(frame: pd.DataFrame, columns: Sequence[str], *, max_rows: int = 8) -> pd.DataFrame:
    safe = _clean_frame(frame)
    if safe.empty:
        return pd.DataFrame([{"Status": "Source unavailable", "Next step": "Use the owning section drill-through."}])
    selected = [column for column in columns if column in safe.columns]
    if not selected:
        selected = list(safe.columns[: min(6, len(safe.columns))])
    compact = safe[selected].head(max_rows).copy()
    for column in compact.columns:
        if "BYTES" in str(column).upper():
            compact[column] = pd.to_numeric(compact[column], errors="coerce").map(
                lambda value: "" if pd.isna(value) else f"{value / (1024 ** 4):,.2f} TB"
            )
        elif str(column).upper().endswith("_TB"):
            compact[column] = pd.to_numeric(compact[column], errors="coerce").map(
                lambda value: "" if pd.isna(value) else f"{value:,.2f}"
            )
        elif any(token in str(column).upper() for token in ("COST", "USD")):
            compact[column] = pd.to_numeric(compact[column], errors="coerce").map(
                lambda value: "" if pd.isna(value) else f"${value:,.2f}"
            )
        elif any(token in str(column).upper() for token in ("CREDITS", "TOKEN", "COUNT")):
            compact[column] = pd.to_numeric(compact[column], errors="coerce").map(
                lambda value: "" if pd.isna(value) else f"{value:,.0f}"
            )
    return compact


def _freshness(frame: pd.DataFrame) -> str:
    for column in ("UPDATED_AT", "LAST_SEEN", "LATEST_OCCURRENCE"):
        if column in frame.columns and not frame.empty:
            value = str(frame[column].dropna().astype(str).head(1).squeeze() or "").strip()
            if value:
                return value[:19]
    return "Source unavailable"


def _status_from_total(total: float, *, unit: str, empty: str = "Source unavailable") -> str:
    if not math.isfinite(total):
        return empty
    if total <= 0:
        return f"No {unit} in scope"
    return f"{total:,.0f} {unit} in scope"


def render_chart_table_panel(
    *,
    title: str,
    description: str,
    frame: pd.DataFrame | None,
    chart_html: str,
    table_columns: Sequence[str],
    callout: str,
    context_label: str,
    source_label: str = "App-facing summary view",
    max_rows: int = 8,
) -> None:
    safe = _clean_frame(frame)
    st.html(
        '<section class="ow-lw-panel">'
        '<header>'
        f'<div><h3>{_html(title)}</h3><p>{_html(description)}</p></div>'
        f'<span>{_html(source_label)} - {_html(_freshness(safe))}</span>'
        '</header>'
        f'<div class="ow-lw-callout">{_html(callout)}</div>'
        f'{chart_html}'
        f'<div class="ow-lw-context" data-interactive="false" data-action-like="false">{_html(context_label)}</div>'
        '</section>'
    )
    st.dataframe(_format_table(safe, table_columns, max_rows=max_rows), hide_index=True, width="stretch")


def _credit_daily_panels(company: str, environment: str, start_date: object, end_date: object, warehouse: str | None) -> None:
    credit = leadership_queries.get_credit_daily(company, environment, start_date, end_date, warehouse=warehouse)
    total = safe_float(pd.to_numeric(credit.get("CREDITS_USED", pd.Series(dtype=float)), errors="coerce").sum(), default=float("nan"))
    render_chart_table_panel(
        title="Credit Burn Rate",
        description="Daily credit consumption by compute and cloud-service split.",
        frame=credit,
        chart_html=_sparkline(_series(credit, "CREDITS_USED"), tone="warning"),
        table_columns=("USAGE_DATE", "SERVICE_TYPE", "WAREHOUSE_NAME", "CREDITS_USED", "ESTIMATED_COST_USD"),
        callout=_status_from_total(total, unit="credits"),
        context_label="Cost drivers available in Cost Intelligence",
    )

    ytd_start = date(_today().year, 1, 1)
    ytd = leadership_queries.get_credit_daily(company, environment, ytd_start, end_date, warehouse=warehouse)
    monthly = pd.DataFrame()
    if not ytd.empty and "USAGE_DATE" in ytd.columns:
        ytd_copy = ytd.copy()
        ytd_copy["MONTH"] = pd.to_datetime(ytd_copy["USAGE_DATE"], errors="coerce").dt.to_period("M").astype(str)
        monthly = (
            ytd_copy.groupby("MONTH", dropna=False)[["CREDITS_USED", "ESTIMATED_COST_USD"]]
            .sum(numeric_only=True)
            .reset_index()
        )
        monthly["BUDGET_STATUS"] = "Track in Cost Intelligence"
    render_chart_table_panel(
        title="YTD Credit Trend",
        description="Cumulative year-to-date credit posture for leadership review.",
        frame=monthly,
        chart_html=_sparkline(_series(monthly, "CREDITS_USED"), tone="info"),
        table_columns=("MONTH", "CREDITS_USED", "ESTIMATED_COST_USD", "BUDGET_STATUS"),
        callout=_status_from_total(
            safe_float(pd.to_numeric(monthly.get("CREDITS_USED", pd.Series(dtype=float)), errors="coerce").sum(), default=float("nan")),
            unit="YTD credits",
        ),
        context_label="Cost Intelligence workflow available",
    )


def render_cost_leadership_panels(
    company: str,
    environment: str,
    *,
    start_date: object,
    end_date: object,
    warehouse: str | None = None,
) -> None:
    st.markdown("### Cost Intelligence leadership monitors")
    _credit_daily_panels(company, environment, start_date, end_date, warehouse)

    comparison = leadership_queries.get_credit_comparison_24h(company, environment, warehouse=warehouse)
    delta = safe_float(pd.to_numeric(comparison.get("CREDIT_DELTA", pd.Series(dtype=float)), errors="coerce").sum(), default=float("nan"))
    render_chart_table_panel(
        title="24h Credit Comparison",
        description="Current 24-hour credit use compared to the prior 24-hour window.",
        frame=comparison,
        chart_html=_bar_chart(comparison.get("CONTRIBUTOR_NAME", []), comparison.get("CREDIT_DELTA", []), tone="warning"),
        table_columns=("CONTRIBUTOR_TYPE", "CONTRIBUTOR_NAME", "CURRENT_24H_CREDITS", "PRIOR_24H_CREDITS", "CREDIT_DELTA", "PCT_DELTA"),
        callout="Flat versus prior 24h" if math.isfinite(delta) and abs(delta) < 0.01 else f"{delta:+,.1f} credit delta versus prior 24h",
        context_label="Contributor detail available in Cost Intelligence",
    )

    storage = leadership_queries.get_storage_daily(company, environment, start_date, end_date)
    growth = safe_float(pd.to_numeric(storage.get("DAILY_GROWTH_BYTES", pd.Series(dtype=float)), errors="coerce").sum(), default=float("nan"))
    render_chart_table_panel(
        title="Storage Growth",
        description="Database, failsafe, and total storage movement over the selected window.",
        frame=storage,
        chart_html=_bar_chart(storage.get("DATABASE_NAME", []), storage.get("TOTAL_TB", []), tone="info"),
        table_columns=("USAGE_DATE", "DATABASE_NAME", "DATABASE_TB", "FAILSAFE_TB", "TOTAL_TB", "DAILY_GROWTH_BYTES", "DAILY_GROWTH_PCT"),
        callout="Storage source unavailable" if not math.isfinite(growth) else f"{growth / (1024 ** 4):+,.2f} TB net daily growth",
        context_label="Storage driver detail available in Cost Intelligence",
    )

    cortex_start, cortex_end = _window(30)
    cortex = leadership_queries.get_cortex_code_usage(company, environment, cortex_start, cortex_end)
    tokens = safe_float(pd.to_numeric(cortex.get("TOKEN_COUNT", pd.Series(dtype=float)), errors="coerce").sum(), default=float("nan"))
    render_chart_table_panel(
        title="Cortex Code Usage",
        description="Snowsight and IDE Cortex Code adoption, token volume, and AI-credit use.",
        frame=cortex,
        chart_html=_bar_chart(cortex.get("USER_CHART_LABEL", []), cortex.get("TOKEN_COUNT", []), tone="healthy"),
        table_columns=("USAGE_DATE", "USER_CHART_LABEL", "CLIENT_SOURCE", "SERVICE_TYPE", "TOKEN_COUNT", "CREDITS_USED", "ESTIMATED_COST_USD"),
        callout=_status_from_total(tokens, unit="tokens"),
        context_label="Cortex drivers available in Cost Intelligence",
    )


def render_cost_leadership_panels_for_current_scope(company: str, environment: str, days: int) -> None:
    from runtime_state import GLOBAL_WAREHOUSE, get_state

    start_date, end_date = _window(days or 7)
    render_cost_leadership_panels(
        company,
        environment,
        start_date=start_date,
        end_date=end_date,
        warehouse=str(get_state(GLOBAL_WAREHOUSE, "") or "").strip() or None,
    )


def render_security_leadership_panels(company: str, environment: str, *, days: int = 7) -> None:
    start_date, end_date = _window(max(7, int(days or 7)))
    st.markdown("### Security leadership monitors")

    failed_last_hour = leadership_queries.get_failed_logins_last_hour(company, environment)
    failed_total = safe_float(pd.to_numeric(failed_last_hour.get("FAILED_COUNT", pd.Series(dtype=float)), errors="coerce").sum(), default=float("nan"))
    render_chart_table_panel(
        title="Failed Logins - Last Hour",
        description="Recent failed-login pressure from compact login telemetry.",
        frame=failed_last_hour,
        chart_html=_bar_chart(failed_last_hour.get("USER_NAME", []), failed_last_hour.get("FAILED_COUNT", []), tone="critical"),
        table_columns=("USER_NAME", "CLIENT_IP", "REPORTED_CLIENT_TYPE", "ERROR_CODE", "ERROR_MESSAGE", "FIRST_SEEN", "LAST_SEEN", "FAILED_COUNT"),
        callout=_status_from_total(failed_total, unit="failed logins"),
        context_label="Security detail available in Security Monitoring",
    )

    login = leadership_queries.get_login_security(company, environment, start_date, end_date)
    render_chart_table_panel(
        title="Login Success/Failure - 7 Days",
        description="Success and failure trend by day, including affected users and IPs.",
        frame=login,
        chart_html=_sparkline(_series(login, "FAILED_COUNT"), tone="warning"),
        table_columns=("EVENT_DATE", "LOGIN_COUNT", "FAILED_COUNT", "USER_NAME", "CLIENT_IP", "RISK_REASON"),
        callout=f"{safe_int(pd.to_numeric(login.get('FAILED_COUNT', pd.Series(dtype=float)), errors='coerce').sum()):,} failed login(s) in 7 days",
        context_label="Failed-login detail available in Security Monitoring",
    )

    suspicious = leadership_queries.get_suspicious_logins(company, environment, start_date, end_date)
    render_chart_table_panel(
        title="Suspicious Login Attempts",
        description="Repeated failures by user, IP, or client pattern.",
        frame=suspicious,
        chart_html=_bar_chart(suspicious.get("CLIENT_IP", []), suspicious.get("RISK_SCORE", []), tone="critical"),
        table_columns=("USER_NAME", "CLIENT_IP", "REPORTED_CLIENT_TYPE", "FAILED_COUNT", "ERROR_MESSAGE", "FIRST_SEEN", "LAST_SEEN", "RISK_REASON"),
        callout=f"{len(suspicious):,} suspicious login pattern(s)" if not suspicious.empty else "No suspicious login patterns in scope",
        context_label="Access signal detail available in Security Monitoring",
    )

    grants = leadership_queries.get_role_grant_audit(company, environment)
    render_chart_table_panel(
        title="Role / Grant Audit",
        description="TF_O_DEV_* grant posture for ALFA_EDW_SAN plus recent change visibility.",
        frame=grants,
        chart_html=_bar_chart(grants.get("ROLE_NAME", []), [1] * len(grants), tone="warning"),
        table_columns=("ROLE_NAME", "PRIVILEGE", "GRANTED_ON", "OBJECT_DATABASE", "OBJECT_NAME", "GRANTEE_NAME", "GRANTED_BY", "CREATED_ON", "DELETED_ON"),
        callout=f"{len(grants):,} grant row(s) in audit scope" if not grants.empty else "No grant changes in audit scope",
        context_label="Risky grant detail available in Security Monitoring",
    )


def render_workload_query_error_panels(company: str, environment: str) -> None:
    start_date = _today() - timedelta(days=1)
    end_date = _today()
    errors = leadership_queries.get_query_errors(company, environment, start_date, end_date)
    st.markdown("### Workload leadership monitors")
    render_chart_table_panel(
        title="Query Error Frequency - Last 24h",
        description="Error-code frequency and latest safe query identifiers for failed statements.",
        frame=errors,
        chart_html=_bar_chart(errors.get("ERROR_CODE", []), errors.get("FAILED_QUERY_COUNT", []), tone="critical"),
        table_columns=("ERROR_CODE", "ERROR_MESSAGE", "FAILED_QUERY_COUNT", "USER_NAME", "WAREHOUSE_NAME", "DATABASE_NAME", "LATEST_OCCURRENCE", "LATEST_QUERY_ID"),
        callout=f"{safe_int(pd.to_numeric(errors.get('FAILED_QUERY_COUNT', pd.Series(dtype=float)), errors='coerce').sum()):,} failed query row(s) in 24h",
        context_label="Query Investigation workflow available",
    )
    render_chart_table_panel(
        title="Failed Query Trend",
        description="Hourly failed-query count and failure rate for workload triage.",
        frame=errors,
        chart_html=_sparkline(_series(errors, "FAILED_QUERY_COUNT"), tone="warning"),
        table_columns=("EVENT_HOUR", "TOTAL_QUERY_COUNT", "FAILED_QUERY_COUNT", "FAILURE_RATE", "ERROR_CODE", "WAREHOUSE_NAME"),
        callout="Failure trend unavailable" if errors.empty else "Review top error code before tuning warehouse capacity",
        context_label="Specialist workflow available",
    )


def leadership_alert_candidates() -> list[AlertCandidate]:
    return [
        AlertCandidate("Credit Burn Spike", "+25% current 24h credits vs prior 24h", "High", "Cost Intelligence", "Cost attribution", "24h Credit Comparison", "Suppress repeat contributor for one review window"),
        AlertCandidate("Failed Login Spike", "10 failures in last hour or 3x baseline", "High", "Security Monitoring", "IAM / Security", "Failed Logins - Last Hour", "Group by user and IP"),
        AlertCandidate("Suspicious Login Activity", "Repeated failures across users or failure followed by success", "Critical", "Security Monitoring", "IAM / Security", "Suspicious Login Attempts", "Deduplicate by IP/user pair"),
        AlertCandidate("Query Error Spike", ">5% failure rate or 2x same-hour baseline", "High", "Workload Operations", "DBA / Workload", "Query Error Frequency", "Suppress same error code after route"),
        AlertCandidate("Storage Growth Spike", "+10% day over day or +1 TB", "Medium", "Cost Intelligence", "Data reviewer", "Storage Growth", "Deduplicate by database"),
        AlertCandidate("Cortex Code Spend Spike", "Credits or tokens above prior 7-day average", "Medium", "Cost Intelligence", "AI cost attribution", "Cortex Code Usage", "Suppress known rollout windows"),
        AlertCandidate("High-Risk Role Grant Change", "Elevated TF_O_DEV_* grant or unexpected grantee", "Critical", "Security Monitoring", "IAM / Security", "Role / Grant Audit", "Require owner acknowledgement"),
    ]


def render_alert_candidate_panel() -> None:
    candidates = leadership_alert_candidates()
    frame = pd.DataFrame([candidate.__dict__ for candidate in candidates])
    render_chart_table_panel(
        title="Leadership Alert Candidates",
        description="Noise-controlled alert candidates mapped to the leadership monitoring panels.",
        frame=frame,
        chart_html=_bar_chart(frame["category"], [idx + 1 for idx in range(len(frame))], tone="info"),
        table_columns=("category", "threshold", "severity", "route", "owner", "source_panel", "suppression"),
        callout=f"{len(candidates):,} monitored candidate categories",
        context_label="Detection catalog available in Alert Center",
        source_label="Alert rule catalog",
        max_rows=10,
    )


def render_leadership_watchlist_strip(items: Iterable[dict[str, object]] | None = None) -> None:
    rows = list(items or [])
    if not rows:
        rows = [
            {"label": "Credit burn", "value": "Cost Intelligence", "detail": "Open cost trend", "tone": "warning", "trend": (2, 3, 4, 5)},
            {"label": "Failed logins", "value": "Security", "detail": "Last-hour monitor", "tone": "critical", "trend": (1, 0, 2, 1)},
            {"label": "Query errors", "value": "Workload", "detail": "24h error trend", "tone": "warning", "trend": (3, 4, 3, 5)},
            {"label": "Storage growth", "value": "Cost Intelligence", "detail": "Database growth", "tone": "info", "trend": (1, 1, 2, 2)},
            {"label": "Cortex Code", "value": "Cost Intelligence", "detail": "Token adoption", "tone": "healthy", "trend": (1, 2, 3, 4)},
            {"label": "Role grants", "value": "Security", "detail": "TF_O_DEV audit", "tone": "warning", "trend": (2, 2, 3, 2)},
        ]
    cards = []
    for row in rows[:6]:
        cards.append(
            '<article class="ow-lw-watch-card" data-tone="{tone}">'
            '<span>{label}</span><strong>{value}</strong><small>{detail}</small>{chart}'
            "</article>".format(
                tone=_html(row.get("tone") or "info"),
                label=_html(row.get("label")),
                value=_html(row.get("value")),
                detail=_html(row.get("detail")),
                chart=_sparkline(tuple(row.get("trend") or ()), tone=str(row.get("tone") or "info")),
            )
        )
    st.html(
        '<section class="ow-lw-watchlist" aria-label="Leadership Watchlist">'
        '<header><h3>Leadership Watchlist</h3><span>Manual monitoring coverage</span></header>'
        '<div class="ow-lw-watch-grid">'
        + "".join(cards)
        + "</div></section>"
    )


__all__ = [
    "AlertCandidate",
    "leadership_alert_candidates",
    "render_alert_candidate_panel",
    "render_chart_table_panel",
    "render_cost_leadership_panels",
    "render_cost_leadership_panels_for_current_scope",
    "render_leadership_watchlist_strip",
    "render_security_leadership_panels",
    "render_workload_query_error_panels",
]
