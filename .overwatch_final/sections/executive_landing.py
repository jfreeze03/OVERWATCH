# sections/executive_landing.py - executive landing page
from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape
import zipfile

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT, DEFAULTS, DAY_WINDOW_OPTIONS
from sections.shell_helpers import render_shell_snapshot
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


EXECUTIVE_LANDING_VERSION = "2026-06-05-boardroom-pptx-v1"

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
    render_shell_snapshot(metrics)


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
        "Executive Landing loads only on demand and uses fast summaries, alert/action evidence, and migration status."
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
