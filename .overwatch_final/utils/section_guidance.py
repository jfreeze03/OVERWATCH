# utils/section_guidance.py - low-cost DBA operating guidance for each section
from __future__ import annotations

import html
import re
from functools import lru_cache

import streamlit as st


SECTION_GUIDANCE_VERSION = "2026-06-03-bottom-notes-v1"
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

SECTION_OPERATING_GUIDE = {
    "Executive Landing": {
        "first_move": "Review executive state, critical actions, cost movement, and migration blockers before drilling into owner workflows.",
        "evidence": "Roll-up of cost cockpit, alert/action queue, source health, and schema migration status evidence.",
        "closure": "Use linked operational sections for closure; this page should route decisions, not certify remediation by itself.",
        "guardrail": "Treat Executive Landing as a decision summary; do not override source-section evidence or close findings from roll-up metrics alone.",
    },
    "DBA Control Room": {
        "first_move": "Work Critical/High incidents first, then stale evidence and unowned action routes.",
        "evidence": "Incident board, source health, command queue, and loaded action-closure evidence.",
        "closure": "Close only with owner, ticket, verification SQL/result, and recovery state attached.",
        "guardrail": "Do not treat a green summary as clean if any source-health row is stale or unavailable.",
    },
    "Alert Center": {
        "first_move": "Review unacknowledged Critical/High alerts and delivery readiness before rule tuning.",
        "evidence": "Alert rule, source query, severity, delivery target, annotation, and delivery log.",
        "closure": "Acknowledge or resolve with reason, owner route, and email delivery proof.",
        "guardrail": "Email is the active channel; do not imply Teams delivery until the webhook exists.",
    },
    "Account Health": {
        "first_move": "Clear checklist failures, source gaps, and access-hygiene blockers before lower-priority hygiene.",
        "evidence": "Checklist row, ACCOUNT_USAGE/IAM context, owner route, and proof query.",
        "closure": "Queue or close with verification result, approval context, and recovery SLA status.",
        "guardrail": "Login-only findings have no database context, so environment filters must not be implied.",
    },
    "Workload Operations": {
        "first_move": "Start with running, queued, failed, or late tasks/procedures and their linked query IDs.",
        "evidence": "Task graph, task history, CALL/query history, SLA baseline, and root-cause category.",
        "closure": "Document recovery within SLA, failed dependency, rerun/cancel decision, and owner handoff.",
        "guardrail": "Do not execute, retry, suspend, or cancel without the exact task/query identity and rollback path.",
    },
    "Warehouse Health": {
        "first_move": "Separate queue pressure, spill, latency, and cost drift before proposing setting changes.",
        "evidence": "WAREHOUSE_METERING_HISTORY, QUERY_HISTORY, owner readiness, and before/after baseline.",
        "closure": "Approve only with ticket, rollback SQL, baseline pressure, and post-change verification.",
        "guardrail": "Warehouse cost is exact at warehouse grain; database split is allocated when warehouses are shared.",
    },
    "Architecture Readiness": {
        "first_move": "Review isolation, clustering, cache, DR, Adaptive Compute, AI/MCP, AI security, Openflow, and governance-readiness gaps before approving new platform patterns.",
        "evidence": "QUERY_HISTORY, TABLES, WAREHOUSE_METERING_HISTORY, SHOW warehouse/replication/agent/MCP/grant metadata, AI settings, AI/Openflow usage views, owner route, and proof SQL.",
        "closure": "Queue findings with proof SQL, owner approval, RPO/RTO or performance baseline, and verification plan.",
        "guardrail": "Do not run clustering-depth, failover, adaptive warehouse conversion, AI security grant/parameter changes, agent/MCP, Openflow, semantic, or architecture-changing DDL without explicit DBA review.",
    },
    "Cost & Contract": {
        "first_move": "Work contract burn risk and verified savings actions before cosmetic spend breakdowns.",
        "evidence": "Metering history, query/database attribution, contract target, owner approval, and savings baseline.",
        "closure": "Close savings only after current spend beats baseline and owner approval is recorded.",
        "guardrail": "Database-attributed cost is Allocated/Estimated unless exact warehouse metering supports it.",
    },
    "Security Posture": {
        "first_move": "Review privileged grants, dormant access, MFA/login risk, and data-sharing exposure.",
        "evidence": "Grant row, login/share evidence, owner route, approval ticket, and blast-radius note.",
        "closure": "Mark complete only after access review approval and verification proof are attached.",
        "guardrail": "Do not revoke or narrow access without inheritance, role-chain, and workload impact review.",
    },
    "Change & Drift": {
        "first_move": "Find drift without ticket approval, recent access changes, and deployment-risk exceptions.",
        "evidence": "Object/access change row, deployment or ITSM ticket, owner route, and rollback proof.",
        "closure": "Close only when approval, implementation evidence, and post-change verification line up.",
        "guardrail": "Treat unmatched drift as a control issue until source-control or ITSM evidence explains it.",
    },
}


SECTION_EVIDENCE_CONTRACT = {
    "Executive Landing": [
        {
            "source": "Cost cockpit, alert center, action queue, and migration status roll-ups",
            "confidence": "Derived from source-section evidence",
            "decision_use": "Prioritize executive attention, route work, and decide which operational section needs review.",
            "invalid_use": "Do not close, suppress, or approve remediation from summary cards alone.",
            "proof": "Source-section evidence row, owner route, ticket or approval, and verification result.",
        },
        {
            "source": "Schema migration and deployment readiness contract",
            "confidence": "Exact when setup ledger is deployed",
            "decision_use": "Identify whether the app schema/mart contract is ready for operating workflows.",
            "invalid_use": "Do not treat a missing migration row as Snowflake health failure without checking setup deployment.",
            "proof": "OVERWATCH_SCHEMA_MIGRATION row, expected version, applied timestamp, and setup SQL source.",
        },
    ],
    "DBA Control Room": [
        {
            "source": "Incident board and action queue",
            "confidence": "Loaded session evidence",
            "decision_use": "Triage Critical/High work and route ownership gaps.",
            "invalid_use": "Do not close incidents without source proof and recovery evidence.",
            "proof": "Ticket, owner, verification SQL/result, and recovery state.",
        },
        {
            "source": "Source-health rows",
            "confidence": "Freshness state",
            "decision_use": "Decide whether the control room is safe to trust.",
            "invalid_use": "Do not treat stale or unavailable sources as healthy.",
            "proof": "Loaded source timestamp and state for each surface.",
        },
    ],
    "Alert Center": [
        {
            "source": "OVERWATCH alert tables and rules",
            "confidence": "Exact when deployed",
            "decision_use": "Review severity, ownership, acknowledgement, and rule coverage.",
            "invalid_use": "Do not assume missing configured rules mean no operational risk.",
            "proof": "Rule row, alert ID, annotation, and delivery record.",
        },
        {
            "source": "Email delivery configuration",
            "confidence": "Email-first",
            "decision_use": "Confirm outbound alert path and escalation target.",
            "invalid_use": "Do not claim Teams/webhook delivery until that integration exists.",
            "proof": "Delivery target, digest or alert delivery log, and owner route.",
        },
    ],
    "Account Health": [
        {
            "source": "Login/authentication evidence",
            "confidence": "Account-level exact",
            "decision_use": "Investigate failed logins, MFA gaps, and dormant-user risk.",
            "invalid_use": "Do not apply environment filters to login-only findings.",
            "proof": "User, event time, login status, and IAM or owner approval evidence.",
        },
        {
            "source": "Checklist and access-hygiene rows",
            "confidence": "Scoped when database context exists",
            "decision_use": "Queue account hygiene and access cleanup actions.",
            "invalid_use": "Do not close hygiene items without verification result.",
            "proof": "Checklist row, owner route, proof query, and recovery SLA state.",
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
    "Warehouse Health": [
        {
            "source": "WAREHOUSE_METERING_HISTORY",
            "confidence": "Exact warehouse cost",
            "decision_use": "Measure warehouse spend, idle waste, and before/after changes.",
            "invalid_use": "Do not split exact spend by database from shared warehouse metering.",
            "proof": "Warehouse, metered credits, baseline window, and post-change window.",
        },
        {
            "source": "QUERY_HISTORY pressure signals",
            "confidence": "Operationally exact at query grain",
            "decision_use": "Separate queue pressure, spill, latency, and workload shape.",
            "invalid_use": "Do not resize solely from one pressure signal.",
            "proof": "Queue/spill/runtime trend, owner approval, rollback SQL, and verification.",
        },
    ],
    "Architecture Readiness": [
        {
            "source": "Architecture objective register",
            "confidence": "Manual owner and RPO/RTO objective",
            "decision_use": "Confirm intended workload class, owner route, isolation policy, and recovery target.",
            "invalid_use": "Do not treat unregistered workloads as approved architecture patterns.",
            "proof": "Objective row, owner route, approval group, RPO/RTO, and verification query.",
        },
        {
            "source": "QUERY_HISTORY workload, cache, and routing evidence",
            "confidence": "Delayed Snowflake metadata",
            "decision_use": "Decide whether to isolate workloads, tune cache behavior, or leave shared routing alone.",
            "invalid_use": "Do not move database workloads from aggregate rows without owner and app impact review.",
            "proof": "Database, warehouse, users/roles, queue/spill/cache evidence, and owner approval.",
        },
        {
            "source": "TABLES and replication/failover metadata",
            "confidence": "Manual validation required",
            "decision_use": "Rank clustering and DR readiness gaps for DBA review.",
            "invalid_use": "Do not run clustering-depth, failover, or DDL automatically from dashboard findings.",
            "proof": "Selected-table clustering proof SQL, failover/replication inventory, RPO/RTO, and drill evidence.",
        },
        {
            "source": "Adaptive Compute, CoWork Artifact, Cortex Sense, Agent, MCP, Snowflake Intelligence, Openflow, Horizon, semantic, and AI-change readiness evidence",
            "confidence": "Delayed metadata plus capability visibility",
            "decision_use": "Decide whether emerging Snowflake capabilities are owner-approved, budgeted, and auditable.",
            "invalid_use": "Do not auto-change agents, MCP servers, Openflow runtimes, semantic models, DR controls, or AI-generated SQL. Do not auto-convert warehouses.",
            "proof": "SHOW inventory, ACCOUNT_USAGE rows, owner route, budget/approval note, and verification query.",
        },
    ],
    "Cost & Contract": [
        {
            "source": "Warehouse metering and contract settings",
            "confidence": "Exact metering plus manual contract input",
            "decision_use": "Track burn rate, renewal pressure, and verified savings.",
            "invalid_use": "Do not treat contract targets as Snowflake-derived facts.",
            "proof": "Configured credit price/contract target and metering window.",
        },
        {
            "source": "Query, user, role, and database attribution",
            "confidence": "Allocated/Estimated",
            "decision_use": "Route chargeback and owner conversations.",
            "invalid_use": "Do not present shared-warehouse database cost as exact.",
            "proof": "Attribution rule, query/database evidence, owner approval, and savings result.",
        },
    ],
    "Security Posture": [
        {
            "source": "ACCOUNT_USAGE grants, roles, shares, and login history",
            "confidence": "Delayed account metadata",
            "decision_use": "Review privileged grants, dormant access, MFA risk, and sharing exposure.",
            "invalid_use": "Do not revoke access without role-chain and workload impact review.",
            "proof": "Grant/share row, owner approval, ticket, and verification query.",
        },
        {
            "source": "Owner route and approval evidence",
            "confidence": "Manual or directory-derived",
            "decision_use": "Decide whether access review is ready for action queue.",
            "invalid_use": "Do not mark reviewed when owner or approval evidence is missing.",
            "proof": "Owner route, approver, approval note, and post-change validation.",
        },
    ],
    "Change & Drift": [
        {
            "source": "Object, grant, and deployment change evidence",
            "confidence": "Delayed account metadata",
            "decision_use": "Find drift, unauthorized changes, and deployment-risk exceptions.",
            "invalid_use": "Do not assume unmatched drift is approved.",
            "proof": "Change row, owner route, ticket/source-control reference, and rollback context.",
        },
        {
            "source": "ITSM/source-control linkage",
            "confidence": "Manual until integrated",
            "decision_use": "Separate explainable change from control failure.",
            "invalid_use": "Do not auto-close drift without external approval proof.",
            "proof": "Approval, implementation evidence, verification result, and closure note.",
        },
    ],
}


def _guide_value(section: str, key: str) -> str:
    guide = SECTION_OPERATING_GUIDE.get(str(section), {})
    return str(guide.get(key, "")).strip()


@lru_cache(maxsize=16)
def _section_guide_markup(section: str) -> str:
    """Return the compact SOP markup for the active DBA section."""
    guide = SECTION_OPERATING_GUIDE.get(str(section))
    if not guide:
        return ""

    items = [
        ("First DBA move", _guide_value(section, "first_move")),
        ("Evidence standard", _guide_value(section, "evidence")),
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
    markup = _section_guide_markup(section)
    if not markup:
        return
    with st.expander("DBA Playbook", expanded=False):
        st.markdown(markup, unsafe_allow_html=True)


def render_section_evidence_contract(section: str) -> None:
    """Render the trust boundary for the active DBA section."""
    markup = _section_evidence_contract_markup(section)
    if not markup:
        return
    with st.expander("Evidence Contract", expanded=False):
        st.markdown(markup, unsafe_allow_html=True)


def _notes_key(section: str) -> str:
    safe_section = str(section or "section").strip() or "section"
    return f"{_DEFERRED_NOTES_PREFIX}:{safe_section}"


def clear_deferred_section_notes(section: str) -> None:
    """Clear transient notes for the section before a fresh render."""
    st.session_state[_notes_key(section)] = []


def defer_section_note(note: str, *, section: str | None = None) -> None:
    """Collect non-critical explanatory text for a bottom Notes / Evidence area."""
    clean_note = " ".join(str(note or "").split())
    if not clean_note:
        return
    active_section = section or st.session_state.get("_overwatch_active_section", "")
    key = _notes_key(active_section)
    notes = list(st.session_state.get(key, []))
    if clean_note not in notes:
        notes.append(clean_note)
    st.session_state[key] = notes


def defer_source_note(*parts: object, section: str | None = None) -> None:
    """Collect source/freshness text without adding visual noise near metrics."""
    clean_parts = [
        _humanize_source_note(" ".join(str(part or "").split()))
        for part in parts
        if str(part or "").strip()
    ]
    if clean_parts:
        defer_section_note(" | ".join(clean_parts), section=section)


def _humanize_source_note(note: str) -> str:
    """Keep source notes operator-facing instead of exposing internal table names."""
    text = str(note or "")
    if not text:
        return ""
    text = re.sub(r"OVERWATCH\s+mart\s+snapshot", "Fast summary snapshot", text, flags=re.IGNORECASE)
    text = re.sub(r"OVERWATCH\s+mart\s*:\s*(FACT|DIM)_[A-Z0-9_]+", "Fast summary", text, flags=re.IGNORECASE)
    text = re.sub(r"Workflow\s+mart\s*:\s*[A-Z0-9_]+", "Workflow evidence", text, flags=re.IGNORECASE)
    text = re.sub(r"OVERWATCH\s+mart", "Fast summary", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmart\s+refresh\b", "summary refresh", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmart\s+unavailable\b", "fast summary unavailable", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmart\s+schema\b", "summary schema", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmart\s+facts\b", "summary rows", text, flags=re.IGNORECASE)
    return text


def render_deferred_section_notes(section: str) -> None:
    """Render deferred explanations and source contracts in one quiet bottom expander."""
    guide_markup = _section_guide_markup(section)
    contract_markup = _section_evidence_contract_markup(section)
    notes = list(st.session_state.get(_notes_key(section), []))
    if not notes and not guide_markup and not contract_markup:
        return

    note_items = "".join(f"<li>{html.escape(note)}</li>" for note in notes)
    notes_markup = (
        f"""
        <div class="ow-section-notes">
            <div class="ow-section-notes-title">Source Notes</div>
            <ul>{note_items}</ul>
        </div>
        """
        if notes
        else ""
    )
    with st.expander("Notes / Evidence", expanded=False):
        st.markdown(f"{notes_markup}{guide_markup}{contract_markup}", unsafe_allow_html=True)


@lru_cache(maxsize=16)
def _section_evidence_contract_markup(section: str) -> str:
    """Return the evidence contract markup for the active DBA section."""
    rows = SECTION_EVIDENCE_CONTRACT.get(str(section))
    if not rows:
        return ""
    contract_cards = []
    for row in rows:
        contract_cards.append(
            f"<div class=\"ow-evidence-contract-card\" style=\"{_EVIDENCE_CARD_STYLE}\">"
            f"<div class=\"ow-evidence-contract-source\" style=\"{_EVIDENCE_SOURCE_STYLE}\">{html.escape(row['source'])}</div>"
            f"<div style=\"{_EVIDENCE_ROW_STYLE}\"><span style=\"{_EVIDENCE_LABEL_STYLE}\">Source basis:</span>{html.escape(row['confidence'])}</div>"
            f"<div style=\"{_EVIDENCE_ROW_STYLE}\"><span style=\"{_EVIDENCE_LABEL_STYLE}\">Decision use:</span>{html.escape(row['decision_use'])}</div>"
            f"<div style=\"{_EVIDENCE_ROW_STYLE}\"><span style=\"{_EVIDENCE_LABEL_STYLE}\">Invalid use:</span>{html.escape(row['invalid_use'])}</div>"
            f"<div style=\"{_EVIDENCE_ROW_STYLE}\"><span style=\"{_EVIDENCE_LABEL_STYLE}\">Closure proof:</span>{html.escape(row['proof'])}</div>"
            "</div>"
        )
    return f"""
    <div class="ow-evidence-contract" style="{_EVIDENCE_GRID_STYLE}" aria-label="{html.escape(str(section))} evidence contract">
        {''.join(contract_cards)}
    </div>
    """


def render_section_reference(section: str) -> None:
    """Render the hidden section reference material without adding default page noise."""
    guide_markup = _section_guide_markup(section)
    contract_markup = _section_evidence_contract_markup(section)
    if not guide_markup and not contract_markup:
        return
    with st.expander("Details", expanded=False):
        st.markdown(f"{guide_markup}{contract_markup}", unsafe_allow_html=True)
