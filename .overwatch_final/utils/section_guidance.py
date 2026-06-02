# utils/section_guidance.py - low-cost DBA operating guidance for each section
from __future__ import annotations

import html
from functools import lru_cache

import streamlit as st


SECTION_GUIDANCE_VERSION = "2026-06-01-platform-futures-v1"

CONFIDENCE_BANDS = (
    ("exact", "Exact", "Source-of-truth or direct operational evidence."),
    ("allocated", "Allocated", "Useful for routing and chargeback, not exact ownership cost."),
    ("delayed", "Delayed", "Snowflake metadata or source-health evidence with latency."),
    ("manual", "Manual", "Configured, email, owner, approval, ITSM, or directory evidence."),
    ("unavailable", "Unavailable", "Expected evidence is stale, missing, or not loaded."),
)


SECTION_SOURCE_HEALTH_STATE_KEYS = {
    "Architecture Readiness": ("arch_source_health",),
}

_SOURCE_HEALTH_FALLBACK_SCAN_LIMIT = 40


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


def _confidence_band(confidence: object) -> str:
    text = str(confidence or "").lower()
    if any(token in text for token in ("unavailable", "not loaded", "missing", "stale")):
        return "unavailable"
    if any(token in text for token in ("allocated", "estimated", "estimate", "derived", "forecast", "projection")):
        return "allocated"
    if any(token in text for token in ("delayed", "freshness", "metadata", "account_usage", "lag")):
        return "delayed"
    if "exact" in text or "source-of-truth" in text:
        return "exact"
    if any(token in text for token in ("manual", "email", "configured", "directory", "itsm", "approval", "owner")):
        return "manual"
    return "manual"


def _state_band(state: object) -> str:
    text = str(state or "").strip().lower()
    if text in {"loaded", "ready", "verified", "no rows"}:
        return "exact"
    if text in {"stale", "scope stale", "deferred", "not loaded", "unavailable"}:
        return "unavailable"
    if "blocked" in text or "gap" in text or "failed" in text:
        return "unavailable"
    return ""


def _looks_like_source_health_frame(value: object) -> bool:
    columns = getattr(value, "columns", None)
    if columns is None:
        return False
    colset = {str(column).upper() for column in columns}
    return {"STATE", "CONFIDENCE"}.issubset(colset) and bool({"SURFACE", "SOURCE"} & colset)


def _source_health_frame_rows(key: str, value: object) -> list[dict]:
    rows: list[dict] = []
    if not _looks_like_source_health_frame(value):
        return rows
    try:
        for row in value.to_dict("records"):
            rows.append({
                "key": str(key),
                "surface": str(row.get("SURFACE") or row.get("SOURCE") or key),
                "state": str(row.get("STATE") or ""),
                "confidence": str(row.get("CONFIDENCE") or ""),
                "rows": row.get("ROWS", ""),
            })
    except Exception:
        return []
    return rows


def _source_health_rows(section: str, state: dict | None) -> list[dict]:
    rows: list[dict] = []
    if not state:
        return rows

    checked_keys: set[str] = set()
    for key in SECTION_SOURCE_HEALTH_STATE_KEYS.get(str(section), ()):
        checked_keys.add(str(key))
        try:
            rows.extend(_source_health_frame_rows(str(key), state.get(key)))
        except Exception:
            continue

    if rows:
        return rows

    # Compatibility path for tests and older sections that may add source-health
    # frames before they are registered above. Keep the scan bounded so the
    # confidence meter cannot become slower as Streamlit session_state grows.
    try:
        state_items = list(state.items())
    except Exception:
        state_items = []
    scanned = 0
    for key, value in state_items:
        if str(key) in checked_keys:
            continue
        if "source_health" not in str(key).lower():
            continue
        scanned += 1
        rows.extend(_source_health_frame_rows(str(key), value))
        if scanned >= _SOURCE_HEALTH_FALLBACK_SCAN_LIMIT:
            break
    return rows


def build_section_confidence_meter(section: str, state: dict | None = None) -> dict:
    """Return a compact confidence meter model for the active section."""
    contract = SECTION_EVIDENCE_CONTRACT.get(str(section), [])
    band_counts = {key: 0 for key, _, _ in CONFIDENCE_BANDS}
    details = {key: [] for key, _, _ in CONFIDENCE_BANDS}
    for row in contract:
        band = _confidence_band(row.get("confidence"))
        band_counts[band] += 1
        details[band].append(str(row.get("source") or "").strip())

    loaded_sources = _source_health_rows(str(section), state)
    for row in loaded_sources:
        band = _state_band(row.get("state")) or _confidence_band(row.get("confidence"))
        band_counts[band] += 1
        details[band].append(str(row.get("surface") or row.get("key") or "").strip())

    total = sum(band_counts.values()) or 1
    penalty = (
        band_counts["allocated"] * 6
        + band_counts["delayed"] * 8
        + band_counts["manual"] * 10
        + band_counts["unavailable"] * 18
    )
    score = max(0, min(100, round(100 - (penalty / total), 1)))
    if band_counts["unavailable"] >= 2:
        state_label = "Evidence Gaps"
    elif band_counts["unavailable"] == 1 or band_counts["delayed"] >= 2:
        state_label = "Use With Caution"
    elif band_counts["allocated"] or band_counts["manual"]:
        state_label = "Mixed Confidence"
    else:
        state_label = "High Confidence"

    rows = []
    for key, label, description in CONFIDENCE_BANDS:
        count = int(band_counts[key])
        rows.append({
            "key": key,
            "label": label,
            "count": count,
            "pct": round((count / total) * 100, 1),
            "description": description,
            "examples": ", ".join(item for item in details[key] if item) or "None in current section contract",
        })
    return {
        "section": str(section),
        "score": score,
        "state": state_label,
        "total": total,
        "source_health_rows": len(loaded_sources),
        "rows": rows,
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
            "<div class=\"ow-section-guide-card\">"
            f"<div class=\"ow-section-guide-label\">{html.escape(label)}</div>"
            f"<div class=\"ow-section-guide-detail\">{html.escape(detail)}</div>"
            "</div>"
        )
    return f"""
    <div class="ow-section-guide" aria-label="{html.escape(str(section))} operating guide">
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


def render_section_confidence_meter(section: str, state: dict | None = None) -> None:
    """Render the section-level trust/confidence meter."""
    meter = build_section_confidence_meter(section, state)
    score = meter["score"]
    state_label = meter["state"]
    display_state = {
        "Evidence Gaps": "Gaps",
        "Use With Caution": "Caution",
        "Mixed Confidence": "Mixed",
        "High Confidence": "High",
    }.get(str(state_label), str(state_label))
    rows = meter["rows"]
    total = max(1, int(meter["total"]))
    mix = []
    for row in rows:
        key = row["key"]
        count = int(row["count"])
        label = {"allocated": "Alloc", "delayed": "Delay", "unavailable": "Gaps"}.get(key, row["label"])
        mix.append(
            f"<span class=\"ow-confidence-mix-item ow-confidence-mix-{html.escape(key)}\">"
            f"<span class=\"ow-confidence-dot ow-confidence-{html.escape(key)}\"></span>"
            f"{html.escape(str(label))} {count}"
            "</span>"
        )
    marker_left = max(0.0, min(100.0, float(score)))
    loaded_note = (
        f"{meter['source_health_rows']} live source row(s)"
        if meter["source_health_rows"]
        else "baseline"
    )
    st.markdown(
        f"""
        <div class="ow-confidence-meter" aria-label="{html.escape(str(section))} confidence meter">
            <div class="ow-confidence-meter-head">
                <div>
                    <span class="ow-confidence-meter-kicker">Confidence:</span>
                    <span class="ow-confidence-meter-title">{html.escape(display_state)}</span>
                </div>
                <div class="ow-confidence-score">{score:.1f}<span>/100</span></div>
            </div>
            <div class="ow-confidence-gauge" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{score:.1f}">
                <div class="ow-confidence-gauge-track"></div>
                <span class="ow-confidence-gauge-marker" style="left:{marker_left:.1f}%"></span>
            </div>
            <div class="ow-confidence-foot">
                <div class="ow-confidence-mix">{' '.join(mix)}</div>
                <div class="ow-confidence-meta">{total:,} signals | {html.escape(loaded_note)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_evidence_contract(section: str) -> None:
    """Render the trust boundary for the active DBA section."""
    markup = _section_evidence_contract_markup(section)
    if not markup:
        return
    with st.expander("Evidence Contract", expanded=False):
        st.markdown(markup, unsafe_allow_html=True)


@lru_cache(maxsize=16)
def _section_evidence_contract_markup(section: str) -> str:
    """Return the evidence contract markup for the active DBA section."""
    rows = SECTION_EVIDENCE_CONTRACT.get(str(section))
    if not rows:
        return ""
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
    return f"""
    <div class="ow-evidence-contract" aria-label="{html.escape(str(section))} evidence contract">
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
