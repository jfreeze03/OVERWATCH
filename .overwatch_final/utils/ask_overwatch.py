# utils/ask_overwatch.py - deterministic, evidence-grounded Ask OVERWATCH answers
from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from .helpers import safe_float, safe_int
from .recommendation_intelligence import harden_recommendation


SEVERITY_RANK = {
    "CRITICAL": 0,
    "HIGH": 1,
    "P1": 1,
    "MEDIUM": 2,
    "WATCH": 3,
    "LOW": 4,
    "INFO": 5,
}

ASK_OVERWATCH_STATE_KEYS = (
    "rec_recommendations",
    "rec_automation_board",
    "rec_action_queue",
    "cost_contract_queue",
    "alert_center_data",
    "dba_control_room_data",
    "dba_control_room_incident_board",
    "dba_control_room_handoff",
    "arch_futures_board",
)


def snapshot_ask_overwatch_state(state: Mapping) -> dict:
    """Return only the loaded evidence surfaces Ask OVERWATCH reads."""
    snapshot: dict = {}
    for key in ASK_OVERWATCH_STATE_KEYS:
        try:
            if key in state:
                snapshot[key] = state.get(key)
        except Exception:
            continue
    return snapshot


def _is_df(value: object) -> bool:
    return isinstance(value, pd.DataFrame) and not value.empty


def _value(row: Mapping | pd.Series | dict, *keys: str, default: object = "") -> object:
    if row is None:
        return default
    for key in keys:
        try:
            if isinstance(row, pd.Series):
                if key in row.index:
                    return row.get(key, default)
                upper = key.upper()
                if upper in row.index:
                    return row.get(upper, default)
                title = key.title()
                if title in row.index:
                    return row.get(title, default)
            elif isinstance(row, Mapping):
                if key in row:
                    return row.get(key, default)
                upper = key.upper()
                if upper in row:
                    return row.get(upper, default)
                title = key.title()
                if title in row:
                    return row.get(title, default)
        except Exception:
            continue
    return default


def _text(row: Mapping | pd.Series | dict, *keys: str, default: str = "") -> str:
    value = _value(row, *keys, default=default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return str(value).strip()


def _rank(severity: object) -> int:
    return SEVERITY_RANK.get(str(severity or "").upper(), 9)


def _append_card(cards: list[dict], card: dict) -> None:
    clean = {key: ("" if value is None else str(value)) for key, value in card.items()}
    clean.setdefault("severity", "Medium")
    clean.setdefault("surface", "OVERWATCH")
    clean.setdefault("entity", clean.get("signal", "Snowflake"))
    clean.setdefault("evidence", "")
    clean.setdefault("next_action", "Open the owning OVERWATCH workflow and validate evidence.")
    clean.setdefault("proof", "Attach proof before closure.")
    clean.setdefault("do_not", "Do not act without source evidence.")
    clean.setdefault("route", clean.get("surface", "OVERWATCH"))
    cards.append(clean)


def _cards_from_recommendations(state: Mapping, cards: list[dict]) -> None:
    recs = state.get("rec_recommendations") or []
    if not isinstance(recs, list):
        return
    for rec in recs[:25]:
        hardened = harden_recommendation(rec)
        _append_card(cards, {
            "surface": "Recommendations",
            "severity": hardened.get("Severity", "Medium"),
            "signal": hardened.get("Decision", "Recommendation"),
            "entity": hardened.get("Entity", ""),
            "evidence": hardened.get("Evidence Packet", hardened.get("Finding", "")),
            "next_action": hardened.get("Safe Next Action", hardened.get("Action", "")),
            "proof": hardened.get("Proof Required", ""),
            "do_not": hardened.get("Do Not Do", ""),
            "route": "Cost & Contract > Recommendations and action queue",
            "category": hardened.get("Category", ""),
            "value": hardened.get("Estimated Monthly Savings", 0),
        })


def _cards_from_automation_board(state: Mapping, cards: list[dict]) -> None:
    frame = state.get("rec_automation_board")
    if not _is_df(frame):
        return
    view = frame.copy()
    view.columns = [str(col).upper() for col in view.columns]
    lane_rank = {
        "READY FOR GUIDED EXECUTION": 0,
        "APPROVAL REQUIRED": 1,
        "EVIDENCE REQUIRED": 2,
        "AUTO-CLOSE CANDIDATE": 3,
        "MANUAL ONLY": 4,
        "OBSERVE ONLY": 5,
    }
    view["_LANE_RANK"] = view.get("AUTOMATION_LANE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper().map(lane_rank).fillna(9)
    view = view.sort_values(["_LANE_RANK", "AUTOMATION_SCORE"], ascending=[True, False]).drop(columns=["_LANE_RANK"])
    for _, row in view.head(10).iterrows():
        lane = _text(row, "AUTOMATION_LANE", default="Automation review")
        blockers = _text(row, "BLOCKERS", default="none")
        _append_card(cards, {
            "surface": "Automation Readiness",
            "severity": _text(row, "SEVERITY", default="Medium"),
            "signal": lane,
            "entity": _text(row, "ENTITY", default="automation candidate"),
            "evidence": (
                f"lane={lane}; score={_text(row, 'AUTOMATION_SCORE', default='0')}; "
                f"blockers={blockers}; decision={_text(row, 'DECISION')}"
            ),
            "next_action": _text(row, "SAFE_AUTOMATION_STEP", default="Open Automation Readiness and resolve blockers."),
            "proof": _text(row, "PROOF_REQUIRED", "VERIFICATION_QUERY", default="Attach verification evidence before closure."),
            "do_not": _text(row, "DO_NOT_DO", default="Do not automate without source evidence and approval."),
            "route": "Cost & Contract > Automation Readiness",
            "category": _text(row, "CATEGORY", default="Automation"),
            "value": _text(row, "AUTOMATION_SCORE", default="0"),
        })


def _cards_from_platform_futures(state: Mapping, cards: list[dict]) -> None:
    frame = state.get("arch_futures_board")
    if not _is_df(frame):
        return
    view = frame.copy()
    view.columns = [str(col).upper() for col in view.columns]
    if "SEVERITY" in view.columns:
        view["_RANK"] = view["SEVERITY"].apply(_rank)
        view = view.sort_values(["_RANK", "CONTROL_AREA"], ascending=[True, True]).drop(columns=["_RANK"])
    for _, row in view.head(10).iterrows():
        control_area = _text(row, "CONTROL_AREA", default="AI & Platform Futures")
        _append_card(cards, {
            "surface": "Architecture Readiness - AI & Platform Futures",
            "severity": _text(row, "SEVERITY", default="Medium"),
            "signal": control_area,
            "entity": _text(row, "ENTITY_NAME", default="platform future control"),
            "evidence": _text(row, "FINDING", default="Open platform futures finding."),
            "next_action": _text(row, "DBA_ACTION", default="Assign owner, approval, proof SQL, and verification."),
            "proof": _text(row, "PROOF_SQL", "VERIFICATION_QUERY", default="Attach source metadata and approval evidence."),
            "do_not": "Do not auto-change agents, MCP servers, Openflow runtimes, semantic models, or DR controls from dashboard findings.",
            "route": "Architecture Readiness > AI & Platform Futures",
            "category": control_area,
            "owner": _text(row, "OWNER", "OWNER_EMAIL", "APPROVAL_GROUP"),
        })


def _cards_from_queue(df: pd.DataFrame, cards: list[dict], *, surface: str) -> None:
    if not _is_df(df):
        return
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    if "STATUS" in frame.columns:
        frame = frame[~frame["STATUS"].fillna("").astype(str).str.upper().isin(["FIXED", "IGNORED"])]
    if frame.empty:
        return
    if "SEVERITY" in frame.columns:
        frame["_RANK"] = frame["SEVERITY"].apply(_rank)
        frame = frame.sort_values(["_RANK"], ascending=True).drop(columns=["_RANK"])
    for _, row in frame.head(8).iterrows():
        entity = _text(row, "ENTITY_NAME", "ENTITY", "CATEGORY", default="queued action")
        finding = _text(row, "FINDING", "RECOMMENDED_ACTION", default="Open action queue item")
        proof = _text(row, "COMMAND_EVIDENCE_REQUIRED", "EVIDENCE_GAP", "PROOF_QUERY", "VERIFICATION_QUERY")
        _append_card(cards, {
            "surface": surface,
            "severity": _text(row, "SEVERITY", default="Medium"),
            "signal": _text(row, "CATEGORY", "COMMAND_STATE", default="Open queue item"),
            "entity": entity,
            "evidence": finding,
            "next_action": _text(row, "NEXT_ACTION", "RECOMMENDED_ACTION", default="Assign owner, due date, and verification evidence."),
            "proof": proof or "Attach verification evidence before closure.",
            "do_not": "Do not mark Fixed until the verification status is proved.",
            "route": _text(row, "ROUTE", default="Action Queue"),
            "owner": _text(row, "OWNER", "OWNER_EMAIL", "APPROVAL_GROUP"),
        })


def _cards_from_alert_center(state: Mapping, cards: list[dict]) -> None:
    data = state.get("alert_center_data")
    if not isinstance(data, Mapping):
        return
    issues = data.get("issues")
    if _is_df(issues):
        frame = issues.copy()
        frame.columns = [str(col).upper() for col in frame.columns]
        if "SEVERITY" in frame.columns:
            frame["_RANK"] = frame["SEVERITY"].apply(_rank)
            frame = frame.sort_values(["_RANK"], ascending=True).drop(columns=["_RANK"])
        for _, row in frame.head(8).iterrows():
            _append_card(cards, {
                "surface": "Alert Center",
                "severity": _text(row, "SEVERITY", default="Medium"),
                "signal": _text(row, "CATEGORY", "ALERT_TYPE", "SOURCE_TYPE", default="Open alert issue"),
                "entity": _text(row, "ENTITY_NAME", "ENTITY", "OBJECT_NAME", default="alert issue"),
                "evidence": _text(row, "MESSAGE", "DETAIL", "ALERT_MESSAGE", default="Open Alert Center issue"),
                "next_action": _text(row, "SUGGESTED_ACTION", "NEXT_ACTION", default="Route the alert to owner and record email delivery if action is required."),
                "proof": _text(row, "PROOF_QUERY", "EVIDENCE", default="Use Alert Center proof query or action queue evidence."),
                "do_not": "Do not send or suppress alerts without status reason and owner context.",
                "route": "Alert Center",
            })
    queue = data.get("action_queue")
    if _is_df(queue):
        _cards_from_queue(queue, cards, surface="Alert Center action queue")


def _cards_from_dba_control_room(state: Mapping, cards: list[dict]) -> None:
    data = state.get("dba_control_room_data")
    if isinstance(data, Mapping):
        summary = data.get("summary")
        credits = data.get("credits")
        if _is_df(summary):
            row = summary.iloc[0]
            failed = safe_int(_value(row, "FAILED_QUERIES", default=0))
            queued = safe_int(_value(row, "QUEUED_QUERIES", default=0))
            spill = safe_int(_value(row, "REMOTE_SPILL_QUERIES", default=0))
            p95 = safe_float(_value(row, "P95_ELAPSED_SEC", default=0))
            if failed or queued or spill or p95 >= 120:
                _append_card(cards, {
                    "surface": "DBA Control Room",
                    "severity": "High" if failed >= 10 or queued >= 20 else "Medium",
                    "signal": "Control-room workload risk",
                    "entity": "Account workload",
                    "evidence": (
                        f"{failed:,} failed queries, {queued:,} queued queries, "
                        f"{spill:,} remote-spill queries, p95 {p95:,.0f}s."
                    ),
                    "next_action": "Use DBA Control Room drill routes, then open Workload Operations or Warehouse Health for the top signal.",
                    "proof": "Attach the source query, top entity, and before/after metric to the action queue.",
                    "do_not": "Do not change global warehouse settings from aggregate metrics alone.",
                    "route": "DBA Control Room",
                })
        if _is_df(credits):
            row = credits.iloc[0]
            period = safe_float(_value(row, "PERIOD_CREDITS", default=0))
            prior = safe_float(_value(row, "PRIOR_CREDITS", default=0))
            delta = ((period - prior) / prior * 100) if prior > 0 else 0
            if delta >= 25:
                _append_card(cards, {
                    "surface": "DBA Control Room",
                    "severity": "High" if delta >= 60 else "Medium",
                    "signal": "Credit spike",
                    "entity": "Account cost",
                    "evidence": f"{period:,.2f} credits in window, {delta:+.1f}% versus prior window.",
                    "next_action": "Open Cost & Contract attribution and isolate top warehouse, user, task, or database driver.",
                    "proof": "Attach the attributed top driver and prior/current credit comparison.",
                    "do_not": "Do not call this savings until the driver is assigned and verified.",
                    "route": "Cost & Contract",
                })
        queue = data.get("action_queue")
        if _is_df(queue):
            _cards_from_queue(queue, cards, surface="DBA Control Room action queue")

    for key, surface in [
        ("dba_control_room_incident_board", "DBA incident board"),
        ("dba_control_room_handoff", "DBA shift handoff"),
    ]:
        frame = state.get(key)
        if _is_df(frame):
            local = frame.copy()
            local.columns = [str(col).upper() for col in local.columns]
            for _, row in local.head(6).iterrows():
                _append_card(cards, {
                    "surface": surface,
                    "severity": _text(row, "SEVERITY", "STATE", default="Medium"),
                    "signal": _text(row, "INCIDENT_TYPE", "LANE", "SIGNALS", default=surface),
                    "entity": _text(row, "ENTITY", "OWNER_OR_ROUTE", "ROUTE", default=surface),
                    "evidence": _text(row, "EVIDENCE", "SIGNALS", default="Loaded DBA operating evidence"),
                    "next_action": _text(row, "NEXT_ACTION", "CONTAINMENT_ACTION", default="Work the incident lane first."),
                    "proof": _text(row, "PROOF_REQUIRED", default="Attach source evidence before closure."),
                    "do_not": "Do not close or hand off without proof requirements.",
                    "route": _text(row, "ROUTE", "OWNER_OR_ROUTE", default="DBA Control Room"),
                })


def build_ask_overwatch_context(state: Mapping, *, max_cards: int = 30) -> list[dict]:
    """Collect loaded app evidence into cards that can safely answer operator questions."""
    cards: list[dict] = []
    _cards_from_recommendations(state, cards)
    _cards_from_automation_board(state, cards)
    _cards_from_platform_futures(state, cards)
    _cards_from_queue(state.get("rec_action_queue"), cards, surface="Recommendations action queue")
    _cards_from_queue(state.get("cost_contract_queue"), cards, surface="Cost & Contract action queue")
    _cards_from_alert_center(state, cards)
    _cards_from_dba_control_room(state, cards)

    if not cards:
        return []
    cards.sort(
        key=lambda card: (
            _rank(card.get("severity")),
            -safe_float(card.get("value", 0)),
            str(card.get("surface", "")),
        )
    )
    return cards[:max_cards]


def _domain_filter(question: str, cards: list[dict]) -> list[dict]:
    q = question.lower()
    domain_terms = {
        "cost": ("cost", "credit", "spend", "budget", "savings", "contract", "idle", "cortex"),
        "warehouse": ("warehouse", "queue", "spill", "capacity", "sizing", "suspend", "auto_suspend"),
        "reliability": ("task", "procedure", "failure", "failed", "runtime", "sla", "graph"),
        "alert": ("alert", "incident", "email", "overdue", "issue"),
        "security": ("security", "grant", "role", "login", "mfa", "access"),
        "change": ("change", "drift", "ddl", "owner", "approval"),
        "automation": ("automation", "automate", "auto", "guided", "approval", "manual only", "blocker"),
        "ai_platform": ("agent", "mcp", "intelligence", "openflow", "horizon", "semantic", "aisql", "cortex code", "ai"),
    }
    matched_domains = [
        domain for domain, terms in domain_terms.items()
        if any(term in q for term in terms)
    ]
    if not matched_domains:
        return cards
    filtered = []
    for card in cards:
        blob = " ".join(str(card.get(key, "")) for key in ["surface", "signal", "entity", "evidence", "next_action", "route", "category"]).lower()
        if any(any(term in blob for term in domain_terms[domain]) for domain in matched_domains):
            filtered.append(card)
    return filtered or cards


def answer_ask_overwatch(
    question: str,
    state: Mapping,
    *,
    active_section: str = "",
    company: str = "",
    environment: str = "",
    role: str = "",
) -> dict:
    """Answer from loaded OVERWATCH evidence only; refuse generic speculation."""
    clean_question = str(question or "").strip()
    if not clean_question:
        return {
            "answer": "Ask a specific DBA operating question after loading evidence.",
            "cards": [],
            "confidence": "No question",
        }

    cards = build_ask_overwatch_context(state)
    if not cards:
        return {
            "answer": (
                "**Answer:** I do not have enough loaded OVERWATCH evidence to give a specific recommendation.\n\n"
                "**Load first:** DBA Control Room for top incidents, Alert Center for active issues, or Cost & Contract > "
                "Recommendations for owned cost/reliability actions.\n\n"
                "**Why:** Ask OVERWATCH is evidence-grounded now. It will not invent best-practice advice without loaded facts."
            ),
            "cards": [],
            "confidence": "No loaded evidence",
        }

    selected = _domain_filter(clean_question, cards)
    top = selected[0]
    scope = " / ".join(part for part in [company, environment, active_section] if part)
    scope_text = f" for {scope}" if scope else ""
    owner = top.get("owner") or top.get("route") or top.get("surface")

    answer = (
        f"**Answer:** Work **{top.get('entity', 'the top finding')}** first{scope_text}.\n\n"
        f"**Decision:** {top.get('signal', 'Triage the loaded finding')}.\n\n"
        f"**Evidence:** {top.get('evidence', '')}\n\n"
        f"**Next move:** {top.get('next_action', '')}\n\n"
        f"**Where to go:** {top.get('route', top.get('surface', 'OVERWATCH'))}. Owner/route: {owner}.\n\n"
        f"**Proof before closure:** {top.get('proof', 'Attach verification evidence before closure.')}\n\n"
        f"**Do not do:** {top.get('do_not', 'Do not act without source evidence.')}"
    )
    if role:
        answer += f"\n\n**Context:** Role `{role}`; answer used {len(selected):,} relevant loaded evidence card(s)."
    else:
        answer += f"\n\n**Context:** Answer used {len(selected):,} relevant loaded evidence card(s)."
    return {
        "answer": answer,
        "cards": selected[:8],
        "confidence": "Evidence-grounded",
    }


def build_grounded_cortex_prompt(question: str, cards: list[dict], *, max_cards: int = 8) -> str:
    """Prompt template for any future Cortex wording pass; intentionally strict."""
    evidence_lines = []
    for idx, card in enumerate(cards[:max_cards], start=1):
        evidence_lines.append(
            f"{idx}. surface={card.get('surface')}; severity={card.get('severity')}; "
            f"entity={card.get('entity')}; evidence={card.get('evidence')}; "
            f"next_action={card.get('next_action')}; proof={card.get('proof')}; do_not={card.get('do_not')}"
        )
    evidence = "\n".join(evidence_lines) or "NO_EVIDENCE_LOADED"
    return (
        "You are OVERWATCH, a Snowflake DBA control assistant. Answer only from the evidence below. "
        "If the evidence does not answer the question, say exactly that and tell the user what OVERWATCH section to load. "
        "Do not give generic Snowflake best practices. Include Decision, Evidence, Next move, Proof before closure, and Do not do.\n\n"
        f"Question: {question}\n\nEvidence:\n{evidence}"
    )
