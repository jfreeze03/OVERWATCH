# utils/section_guidance.py - low-cost DBA operating guidance for each section
from __future__ import annotations

import html

import streamlit as st


SECTION_OPERATING_GUIDE = {
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
            "confidence": "Freshness confidence",
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


def render_section_operating_guide(section: str) -> None:
    """Render a compact SOP strip for the active DBA section."""
    guide = SECTION_OPERATING_GUIDE.get(str(section))
    if not guide:
        return

    items = [
        ("First DBA move", _guide_value(section, "first_move")),
        ("Evidence standard", _guide_value(section, "evidence")),
        ("Closure rule", _guide_value(section, "closure")),
        ("Safety boundary", _guide_value(section, "guardrail")),
    ]
    cards = []
    for label, detail in items:
        cards.append(
            "<div class=\"ow-section-guide-card\">"
            f"<div class=\"ow-section-guide-label\">{html.escape(label)}</div>"
            f"<div class=\"ow-section-guide-detail\">{html.escape(detail)}</div>"
            "</div>"
        )
    st.markdown(
        f"""
        <div class="ow-section-guide" aria-label="{html.escape(str(section))} operating guide">
            {''.join(cards)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_evidence_contract(section: str) -> None:
    """Render the trust boundary for the active DBA section."""
    rows = SECTION_EVIDENCE_CONTRACT.get(str(section))
    if not rows:
        return
    with st.expander("Evidence Contract", expanded=False):
        st.caption("Decision confidence, invalid use, and closure proof for this section.")
        contract_cards = []
        for row in rows:
            contract_cards.append(
                "<div class=\"ow-evidence-contract-card\">"
                f"<div class=\"ow-evidence-contract-source\">{html.escape(row['source'])}</div>"
                f"<div><span>Confidence:</span>{html.escape(row['confidence'])}</div>"
                f"<div><span>Decision use:</span>{html.escape(row['decision_use'])}</div>"
                f"<div><span>Invalid use:</span>{html.escape(row['invalid_use'])}</div>"
                f"<div><span>Closure proof:</span>{html.escape(row['proof'])}</div>"
                "</div>"
            )
        st.markdown(
            f"""
            <div class="ow-evidence-contract" aria-label="{html.escape(str(section))} evidence contract">
                {''.join(contract_cards)}
            </div>
            """,
            unsafe_allow_html=True,
        )
