# utils/section_guidance.py - low-cost DBA operating guidance for each section
from __future__ import annotations

import html
import re
from functools import lru_cache

import streamlit as st


SECTION_GUIDANCE_VERSION = "2026-06-13-no-bottom-notes-v1"
_DEFERRED_NOTES_PREFIX = "_overwatch_deferred_section_notes"
_GUIDE_GRID_STYLE = (
    "display:grid;"
    "grid-template-columns:repeat(4,minmax(0,1fr));"
    "gap:0.65rem;"
    "margin:0.2rem 0 0.85rem;"
)
_GUIDE_CARD_STYLE = (
    "min-width:0;"
    "border-top:1px solid var(--border-subtle, rgba(41,181,232,0.18));"
    "padding:0.55rem 0.05rem 0;"
)
_GUIDE_LABEL_STYLE = (
    "display:block;"
    "color:var(--text-muted, #7b9cab);"
    "font-size:0.64rem;"
    "font-weight:850;"
    "letter-spacing:0.06em;"
    "line-height:1.2;"
    "text-transform:uppercase;"
    "overflow-wrap:anywhere;"
)
_GUIDE_DETAIL_STYLE = (
    "display:block;"
    "color:var(--text-secondary, #b9d7e2);"
    "font-size:0.8rem;"
    "line-height:1.35;"
    "margin-top:0.18rem;"
    "overflow-wrap:anywhere;"
)
_EVIDENCE_GRID_STYLE = (
    "display:grid;"
    "grid-template-columns:repeat(2,minmax(0,1fr));"
    "gap:0.7rem;"
    "margin:0.15rem 0 0.35rem;"
)
_EVIDENCE_CARD_STYLE = (
    "min-width:0;"
    "border:1px solid var(--border-subtle, rgba(41,181,232,0.18));"
    "border-radius:8px;"
    "padding:0.75rem 0.8rem;"
    "background:var(--bg-expander, rgba(10,27,35,0.68));"
    "color:var(--text-secondary, #b9d7e2);"
    "font-size:0.78rem;"
    "line-height:1.35;"
    "overflow-wrap:anywhere;"
)
_EVIDENCE_SOURCE_STYLE = (
    "display:block;"
    "color:var(--text-primary, #eef8fb);"
    "font-weight:850;"
    "font-size:0.82rem;"
    "line-height:1.25;"
    "overflow-wrap:anywhere;"
)
_EVIDENCE_ROW_STYLE = "display:block;margin-top:0.38rem;overflow-wrap:anywhere;"
_EVIDENCE_LABEL_STYLE = (
    "display:block;"
    "color:var(--text-muted, #7b9cab);"
    "font-size:0.62rem;"
    "font-weight:850;"
    "letter-spacing:0.06em;"
    "line-height:1.2;"
    "text-transform:uppercase;"
    "margin-bottom:0.08rem;"
    "overflow-wrap:anywhere;"
)


def _clean_guidance_text(value: object) -> str:
    text = str(value or "")
    replacements = (
        (r"\bevidence\b", "telemetry"),
        (r"\bEvidence\b", "Telemetry"),
        (r"\bproof\b", "status"),
        (r"\bProof\b", "Status"),
        (r"\bverification\b", "status"),
        (r"\bVerification\b", "Status"),
        (r"\bapproval\b", "review"),
        (r"\bApproval\b", "Review"),
        (r"\bowner\b", "route"),
        (r"\bOwner\b", "Route"),
        (r"\bsource[- ]health\b", "data health"),
        (r"\bSource[- ]Health\b", "Data Health"),
        (r"\bschema migration status\b", "persistent object status"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text

SECTION_OPERATING_GUIDE = {
    "Executive Landing": {
        "first_move": "Review executive state, critical actions, cost movement, and data-health blockers before drilling into operational sections.",
        "evidence": "Roll-up of cost cockpit, alert/action queue, data health, and persistent object status telemetry.",
        "closure": "Use linked operational sections for closure; this page should route decisions, not certify remediation by itself.",
        "guardrail": "Treat Executive Landing as a decision summary; do not override source-section telemetry or close findings from roll-up metrics alone.",
    },
    "DBA Control Room": {
        "first_move": "Work Critical/High incidents first, then stale telemetry and unassigned action routes.",
        "evidence": "Incident board, data health, command queue, and loaded action-closure telemetry.",
        "closure": "Close when the route has a ticket/reference and the recovery state clears in telemetry.",
        "guardrail": "Do not treat a green summary as clean if any source-health row is stale or unavailable.",
    },
    "Alert Center": {
        "first_move": "Review unacknowledged Critical/High alerts and delivery health before rule tuning.",
        "evidence": "Alert rule, source query, severity, delivery target, annotation, and delivery log.",
        "closure": "Acknowledge or resolve with reason, assignment, and email delivery status.",
        "guardrail": "Email is the active channel; do not imply Teams delivery until the webhook exists.",
    },
    "Workload Operations": {
        "first_move": "Start with running, queued, failed, or late tasks/procedures and their linked query IDs.",
        "evidence": "Task graph, task history, CALL/query history, SLA baseline, and root-cause category.",
        "closure": "Track recovery within SLA, failed dependency, and rerun/cancel decision.",
        "guardrail": "Do not execute, retry, suspend, or cancel without the exact task/query identity and rollback path.",
    },
    "Cost & Contract": {
        "first_move": "Work contract burn risk and verified savings actions before cosmetic spend breakdowns.",
        "evidence": "Metering history, query/database attribution, contract target, and savings baseline.",
        "closure": "Close savings only after current spend beats baseline and telemetry status is recorded.",
        "guardrail": "Database-attributed cost is Allocated/Estimated unless exact warehouse metering supports it.",
    },
    "Security Monitoring": {
        "first_move": "Review privileged access, login risk, public grants, data sharing, and security alerts.",
        "evidence": "ACCOUNT_USAGE grants, login history, share metadata, access history, and alert rows.",
        "closure": "Close when the finding clears and the investigation note or delivery/action status is current.",
        "guardrail": "Do not change access from summary rows; use this section to monitor and investigate.",
    },
}


SECTION_EVIDENCE_CONTRACT = {
    "Executive Landing": [
        {
            "source": "Cost cockpit, alert center, action queue, and migration status roll-ups",
            "confidence": "Derived from source-section telemetry",
            "decision_use": "Prioritize executive attention, route work, and decide which operational section needs review.",
            "invalid_use": "Do not close, suppress, or approve remediation from summary cards alone.",
            "proof": "Source-section telemetry row and ticket/reference.",
        },
        {
            "source": "Schema migration and data-health contract",
            "confidence": "Exact when status ledger is available",
            "decision_use": "Identify whether the app schema and summaries are current for operating workflows.",
            "invalid_use": "Do not treat a missing migration row as Snowflake health failure without checking data-health status.",
            "proof": "Status ledger row, expected version, applied timestamp, and status note.",
        },
    ],
    "DBA Control Room": [
        {
            "source": "Incident board and action queue",
            "confidence": "Loaded session telemetry",
            "decision_use": "Triage Critical/High work and route assignment gaps.",
            "invalid_use": "Do not close incidents without input telemetry and recovery status.",
            "proof": "Ticket/reference and recovery state.",
        },
        {
            "source": "Source-health rows",
            "confidence": "Freshness state",
            "decision_use": "Decide whether the control room is safe to trust.",
            "invalid_use": "Do not treat stale or unavailable sources as healthy.",
            "proof": "Loaded input timestamp and state for each surface.",
        },
    ],
    "Alert Center": [
        {
            "source": "OVERWATCH alert tables and rules",
            "confidence": "Exact when deployed",
            "decision_use": "Review severity, assignment, acknowledgement, and rule coverage.",
            "invalid_use": "Do not assume missing configured rules mean no operational risk.",
            "proof": "Rule row, alert ID, annotation, and delivery record.",
        },
        {
            "source": "Email delivery configuration",
            "confidence": "Email-first",
            "decision_use": "Confirm outbound alert path and escalation target.",
            "invalid_use": "Do not claim external delivery until a Snowflake notification integration exists.",
            "proof": "Delivery target, digest or alert delivery log, and routing note.",
        },
    ],
    "Workload Operations": [
        {
            "source": "TASK_HISTORY and query/CALL history",
            "confidence": "Delayed Snowflake metadata",
            "decision_use": "Diagnose failed, late, queued, or high-cost task/procedure runs.",
            "invalid_use": "Do not retry or cancel from aggregate rows alone.",
            "proof": "Task FQN, graph run, query ID, dependency, and recovery timing.",
        },
        {
            "source": "SLA baselines and failure category",
            "confidence": "Derived from loaded run history",
            "decision_use": "Prioritize recovery and identify regressions.",
            "invalid_use": "Do not label a fix recovered without a successful follow-up run.",
            "proof": "Before/after runtime, status, failed dependency, and SLA result.",
        },
    ],
    "Cost & Contract": [
        {
            "source": "WAREHOUSE_METERING_HISTORY",
            "confidence": "Exact warehouse cost",
            "decision_use": "Measure spend, contract burn, idle waste, and before/after warehouse changes.",
            "invalid_use": "Do not split exact spend by database from shared warehouse metering.",
            "proof": "Warehouse, metered credits, baseline window, and post-change window.",
        },
        {
            "source": "Warehouse metering and contract settings",
            "confidence": "Exact metering plus configured contract input",
            "decision_use": "Track burn rate, renewal pressure, and verified savings.",
            "invalid_use": "Do not treat contract targets as Snowflake-derived facts.",
            "proof": "Configured credit price/contract target and metering window.",
        },
        {
            "source": "Query, user, role, and database attribution",
            "confidence": "Allocated/Estimated",
            "decision_use": "Route chargeback and escalation conversations.",
            "invalid_use": "Do not present shared-warehouse database cost as exact.",
            "proof": "Attribution rule, query/database telemetry, and savings result.",
        },
    ],
    "Security Monitoring": [
        {
            "source": "ACCOUNT_USAGE grants, roles, shares, and login history",
            "confidence": "Delayed account metadata",
            "decision_use": "Review privileged grants, dormant access, MFA risk, and sharing exposure.",
            "invalid_use": "Do not revoke access without role-chain and workload impact review.",
            "proof": "Grant/share row, investigation note, ticket/reference, and telemetry query.",
        },
        {
            "source": "Object and grant telemetry",
            "confidence": "Delayed account metadata",
            "decision_use": "Find risky object, grant, and sharing changes that need review.",
            "invalid_use": "Do not treat delayed account metadata as real-time enforcement.",
            "proof": "Change row, query/user telemetry, and ticket/reference.",
        },
    ],
}


def _guide_value(section: str, key: str) -> str:
    guide = SECTION_OPERATING_GUIDE.get(str(section), {})
    return _clean_guidance_text(guide.get(key, "")).strip()


@lru_cache(maxsize=16)
def _section_guide_markup(section: str) -> str:
    """Return the compact SOP markup for the active DBA section."""
    guide = SECTION_OPERATING_GUIDE.get(str(section))
    if not guide:
        return ""

    items = [
        ("First DBA move", _guide_value(section, "first_move")),
        ("Telemetry standard", _guide_value(section, "evidence")),
        ("Closure rule", _guide_value(section, "closure")),
        ("Safety boundary", _guide_value(section, "guardrail")),
    ]
    cards = []
    for label, detail in items:
        cards.append(
            f"<div class=\"ow-section-guide-card\" style=\"{_GUIDE_CARD_STYLE}\">"
            f"<div class=\"ow-section-guide-label\" style=\"{_GUIDE_LABEL_STYLE}\">{html.escape(label)}</div>"
            f"<div class=\"ow-section-guide-detail\" style=\"{_GUIDE_DETAIL_STYLE}\">{html.escape(detail)}</div>"
            "</div>"
        )
    return f"""
    <div class="ow-section-guide" style="{_GUIDE_GRID_STYLE}" aria-label="{html.escape(str(section))} operating guide">
        {''.join(cards)}
    </div>
    """


def render_section_operating_guide(section: str) -> None:
    """Render a collapsed SOP strip for the active DBA section."""
    guide = SECTION_OPERATING_GUIDE.get(str(section))
    if not guide:
        return
    with st.expander("DBA Playbook", expanded=False):
        items = (
            ("First DBA move", _guide_value(section, "first_move")),
            ("Telemetry standard", _guide_value(section, "evidence")),
            ("Closure rule", _guide_value(section, "closure")),
            ("Safety boundary", _guide_value(section, "guardrail")),
        )
        cols = st.columns(2)
        for idx, (label, detail) in enumerate(items):
            with cols[idx % 2]:
                with st.container(border=True):
                    st.caption(label)
                    st.markdown(f"**{detail}**")


def render_section_evidence_contract(section: str) -> None:
    """Render the trust boundary for the active DBA section."""
    rows = SECTION_EVIDENCE_CONTRACT.get(str(section))
    if not rows:
        return
    with st.expander("Operating Context", expanded=False):
        for row in rows:
            with st.container(border=True):
                st.markdown(f"**{_clean_guidance_text(row['source'])}**")
                st.caption(f"Measurement: {_clean_guidance_text(row['confidence'])}")
                st.caption(f"Decision use: {_clean_guidance_text(row['decision_use'])}")
                st.caption(f"Invalid use: {_clean_guidance_text(row['invalid_use'])}")
                st.caption(f"Closure status: {_clean_guidance_text(row['proof'])}")


def _notes_key(section: str) -> str:
    safe_section = str(section or "section").strip() or "section"
    return f"{_DEFERRED_NOTES_PREFIX}:{safe_section}"


def clear_deferred_section_notes(section: str) -> None:
    """Retained for compatibility; bottom section notes are no longer rendered."""
    st.session_state.pop(_notes_key(section), None)


def defer_section_note(note: str, *, section: str | None = None) -> None:
    """Compatibility no-op; generic section notes were removed from the app UI."""
    return


def defer_source_note(*parts: object, section: str | None = None) -> None:
    """Compatibility no-op; input details now live in local telemetry/KPI surfaces."""
    return


def _humanize_source_note(note: str) -> str:
    """Keep source notes operator-facing instead of exposing internal table names."""
    text = str(note or "")
    if not text:
        return ""
    text = re.sub(r"OVERWATCH\s+mart\s+snapshot", "Fast summary snapshot", text, flags=re.IGNORECASE)
    text = re.sub(r"OVERWATCH\s+mart\s*:\s*(FACT|DIM)_[A-Z0-9_]+", "Fast summary", text, flags=re.IGNORECASE)
    text = re.sub(r"Workflow\s+mart\s*:\s*[A-Z0-9_]+", "Workflow telemetry", text, flags=re.IGNORECASE)
    text = re.sub(r"OVERWATCH\s+mart", "Fast summary", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmart\s+refresh\b", "summary refresh", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmart\s+unavailable\b", "fast summary unavailable", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmart\s+schema\b", "summary schema", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmart\s+facts\b", "summary rows", text, flags=re.IGNORECASE)
    return text


def render_deferred_section_notes(section: str) -> None:
    """Retained for compatibility; the app no longer renders bottom notes/detail drawers."""
    clear_deferred_section_notes(section)


@lru_cache(maxsize=16)
def _section_evidence_contract_markup(section: str) -> str:
    """Return the telemetry contract markup for the active DBA section."""
    rows = SECTION_EVIDENCE_CONTRACT.get(str(section))
    if not rows:
        return ""
    contract_cards = []
    for row in rows:
        contract_cards.append(
            f"<div class=\"ow-evidence-contract-card\" style=\"{_EVIDENCE_CARD_STYLE}\">"
            f"<div class=\"ow-evidence-contract-source\" style=\"{_EVIDENCE_SOURCE_STYLE}\">{html.escape(_clean_guidance_text(row['source']))}</div>"
            f"<div style=\"{_EVIDENCE_ROW_STYLE}\"><span style=\"{_EVIDENCE_LABEL_STYLE}\">Measurement:</span>{html.escape(_clean_guidance_text(row['confidence']))}</div>"
            f"<div style=\"{_EVIDENCE_ROW_STYLE}\"><span style=\"{_EVIDENCE_LABEL_STYLE}\">Decision use:</span>{html.escape(_clean_guidance_text(row['decision_use']))}</div>"
            f"<div style=\"{_EVIDENCE_ROW_STYLE}\"><span style=\"{_EVIDENCE_LABEL_STYLE}\">Invalid use:</span>{html.escape(_clean_guidance_text(row['invalid_use']))}</div>"
            f"<div style=\"{_EVIDENCE_ROW_STYLE}\"><span style=\"{_EVIDENCE_LABEL_STYLE}\">Closure status:</span>{html.escape(_clean_guidance_text(row['proof']))}</div>"
            "</div>"
        )
    return f"""
    <div class="ow-evidence-contract" style="{_EVIDENCE_GRID_STYLE}" aria-label="{html.escape(str(section))} telemetry contract">
        {''.join(contract_cards)}
    </div>
    """


def render_section_reference(section: str) -> None:
    """Render the hidden section reference material without adding default page noise."""
    guide = SECTION_OPERATING_GUIDE.get(str(section))
    contract = SECTION_EVIDENCE_CONTRACT.get(str(section))
    if not guide and not contract:
        return
    with st.expander("Details", expanded=False):
        if guide:
            st.markdown("**DBA Playbook**")
            for label, detail in (
                ("First DBA move", _guide_value(section, "first_move")),
                ("Telemetry standard", _guide_value(section, "evidence")),
                ("Closure rule", _guide_value(section, "closure")),
                ("Safety boundary", _guide_value(section, "guardrail")),
            ):
                st.caption(label)
                st.markdown(f"**{detail}**")
        if contract:
            st.markdown("**Operating Context**")
            for row in contract:
                with st.container(border=True):
                    st.markdown(f"**{_clean_guidance_text(row['source'])}**")
                    st.caption(f"Measurement: {_clean_guidance_text(row['confidence'])}")
                    st.caption(f"Decision use: {_clean_guidance_text(row['decision_use'])}")
                    st.caption(f"Invalid use: {_clean_guidance_text(row['invalid_use'])}")
                    st.caption(f"Closure status: {_clean_guidance_text(row['proof'])}")
