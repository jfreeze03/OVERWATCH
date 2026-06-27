"""SQL-free query contracts and lightweight performance linting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha1
import re
from typing import Any


@dataclass(frozen=True)
class QueryContract:
    boundary: str
    section: str = ""
    ttl_key_pattern: str = ""
    tier: str = "standard"
    max_rows: int | None = None
    allow_account_usage: bool = False
    allow_metadata: bool = False
    allow_select_star: bool = False
    allow_contains_search: bool = False
    requires_target_predicate: bool = False
    target_predicate_markers: tuple[str, ...] = ()
    first_paint_allowed: bool = False
    expected_table_family: str = ""

    def to_artifact(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueryLintFinding:
    code: str
    severity: str
    message: str
    boundary: str
    section: str = ""

    def to_artifact(self) -> dict[str, Any]:
        return asdict(self)


_QUERY_CONTRACTS: list[QueryContract] = []


def register_query_contract(contract: QueryContract) -> QueryContract:
    _QUERY_CONTRACTS.append(contract)
    return contract


def iter_query_contracts() -> tuple[QueryContract, ...]:
    return tuple(_QUERY_CONTRACTS)


def _matches(pattern: str, value: str) -> bool:
    return bool(pattern and re.search(pattern, str(value or ""), flags=re.IGNORECASE))


def resolve_query_contract(
    *,
    boundary: str = "",
    section: str = "",
    ttl_key: str = "",
    tier: str = "",
) -> QueryContract:
    boundary = str(boundary or "other")
    section = str(section or "")
    ttl_key = str(ttl_key or "")
    tier = str(tier or "")
    for contract in _QUERY_CONTRACTS:
        if (
            contract.ttl_key_pattern
            and _matches(contract.ttl_key_pattern, ttl_key)
            and (not contract.boundary or contract.boundary == boundary)
        ):
            return contract
    for contract in _QUERY_CONTRACTS:
        if contract.boundary != boundary:
            continue
        if contract.section and contract.section != section:
            continue
        if contract.tier and tier and contract.tier != tier:
            continue
        return contract
    return QueryContract(boundary=boundary, section=section, tier=tier or "standard")


def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:''|[^'])*'", "''", str(sql or ""), flags=re.DOTALL)


def _limit_position(sql: str) -> int:
    match = re.search(r"\bLIMIT\s+\d+\b", _strip_literals(sql), flags=re.IGNORECASE)
    return match.start() if match else -1


def _where_position(sql: str) -> int:
    match = re.search(r"\bWHERE\b", _strip_literals(sql), flags=re.IGNORECASE)
    return match.start() if match else -1


def lint_query_text(sql: str, contract: QueryContract) -> list[QueryLintFinding]:
    """Return sanitized findings for app-facing query performance contracts."""
    text = str(sql or "")
    masked = _strip_literals(text)
    upper = masked.upper()
    findings: list[QueryLintFinding] = []

    def add(code: str, severity: str, message: str) -> None:
        findings.append(QueryLintFinding(code, severity, message, contract.boundary, contract.section))

    if contract.first_paint_allowed and contract.boundary != "decision_packet":
        add("FIRST_PAINT_BOUNDARY", "error", "First-paint queries must use the decision_packet boundary.")
    if "SNOWFLAKE.ACCOUNT_USAGE" in upper and not contract.allow_account_usage:
        add("ACCOUNT_USAGE_FORBIDDEN", "error", "Account Usage is allowed only by explicit fallback/admin contract.")
    leading = upper.lstrip()
    if (
        (leading.startswith("SHOW ") or leading.startswith("DESC ") or leading.startswith("DESCRIBE "))
        and not contract.allow_metadata
    ):
        add("METADATA_FORBIDDEN", "error", "Metadata probes are not allowed for this query contract.")
    if re.search(r"\bSELECT\s+\*", upper) and not contract.allow_select_star:
        add("STAR_PROJECTION", "error", "Wildcard projection is forbidden for daily app-facing query loaders.")
    if re.search(r"\b(SELECT|WITH)\b", upper) and not re.search(r"\bLIMIT\s+\d+\b", upper):
        add("MISSING_LIMIT", "error", "App-facing read queries must be bounded with LIMIT.")
    if (
        re.search(r"ILIKE\s+('%\s*\|\||''%|'%[^']*%')", upper)
        and not contract.allow_contains_search
    ):
        add("CONTAINS_SEARCH", "warning", "Leading-wildcard contains search is not allowed for this route context.")
    if contract.requires_target_predicate:
        limit_pos = _limit_position(masked)
        where_pos = _where_position(masked)
        predicate_region = masked[where_pos:limit_pos] if limit_pos >= 0 and where_pos >= 0 else masked[where_pos:]
        markers = contract.target_predicate_markers or (
            "QUERY_ID", "QUERY_HASH", "QUERY_SIGNATURE",
            "ALERT_ID", "ALERT_KEY", "EVENT_ID",
            "WAREHOUSE_NAME", "USER_NAME", "LOGIN_NAME", "ROLE_NAME",
            "DATABASE_NAME", "GRANT_ID", "SHARE_NAME",
            "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME",
        )
        if where_pos < 0:
            add("MISSING_TARGET_PREDICATE", "error", "Targeted evidence query has no predicate before LIMIT.")
        elif limit_pos >= 0 and where_pos > limit_pos:
            add("PREDICATE_AFTER_LIMIT", "error", "Target predicate must appear before LIMIT.")
        elif not any(marker.upper() in predicate_region.upper() for marker in markers):
            add("TARGET_MARKER_MISSING", "error", "Targeted evidence query lacks an allowlisted target marker before LIMIT.")
    if contract.expected_table_family and contract.expected_table_family.upper() not in upper:
        add("UNEXPECTED_TABLE_FAMILY", "warning", "Query does not reference the expected table family.")
    return findings


def query_fingerprint(sql: str) -> str:
    """Return a stable fingerprint without exposing raw SQL text."""
    normalized = re.sub(r"\s+", " ", _strip_literals(str(sql or "")).strip().upper())
    return sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]


register_query_contract(
    QueryContract(
        boundary="decision_packet",
        ttl_key_pattern=r"^section_command_packet_",
        tier="command_summary",
        max_rows=1,
        first_paint_allowed=True,
        expected_table_family="MART_SECTION_DECISION_CURRENT_FLAT",
    )
)
register_query_contract(
    QueryContract(
        boundary="evidence",
        tier="",
        max_rows=500,
    )
)
for _ttl_pattern, _section, _markers in (
    (r"alert_.*evidence|alert_.*history|alert_.*delivery|alert_.*action", "Alert Center", ("ALERT_ID", "ALERT_KEY", "EVENT_ID", "ACTION_ID")),
    (r"cost_targeted_evidence|cc_targeted_evidence", "Cost & Contract", ("WAREHOUSE_NAME", "USER_NAME", "ROLE_NAME", "DATABASE_NAME", "DEPARTMENT", "SERVICE_CATEGORY", "SERVICE_TYPE")),
    (r"dba_control_room_.*evidence|dba_.*proof|dba_.*failed", "DBA Control Room", ("QUERY_ID", "QUERY_HASH", "QUERY_SIGNATURE", "WAREHOUSE_NAME", "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME")),
    (r"query_search_recent_detail|workload_.*evidence|workload_.*pipeline", "Workload Operations", ("QUERY_ID", "QUERY_HASH", "QUERY_SIGNATURE", "WAREHOUSE_NAME", "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME")),
    (r"security_.*evidence|security_.*proof", "Security Monitoring", ("USER_NAME", "LOGIN_NAME", "ROLE_NAME", "GRANTEE_NAME", "GRANT_ID", "SHARE_NAME", "DATABASE_NAME", "OBJECT_NAME")),
):
    register_query_contract(
        QueryContract(
            boundary="evidence",
            section=_section,
            ttl_key_pattern=_ttl_pattern,
            tier="",
            max_rows=500,
            requires_target_predicate=True,
            target_predicate_markers=_markers,
        )
    )
register_query_contract(
    QueryContract(
        boundary="query_search",
        ttl_key_pattern=r"^query_search_recent_detail_",
        tier="recent",
        max_rows=500,
        expected_table_family="FACT_QUERY_DETAIL_RECENT",
    )
)
register_query_contract(
    QueryContract(
        boundary="query_preview",
        ttl_key_pattern=r"^query_text_preview_",
        tier="recent",
        max_rows=1,
        expected_table_family="FACT_QUERY_DETAIL_RECENT",
    )
)
register_query_contract(
    QueryContract(
        boundary="account_usage",
        tier="historical",
        max_rows=200,
        allow_account_usage=True,
        allow_metadata=True,
        first_paint_allowed=False,
    )
)
register_query_contract(QueryContract(boundary="metadata", tier="metadata", allow_metadata=True))
register_query_contract(QueryContract(boundary="setup_health", tier="metadata", allow_metadata=True))
register_query_contract(QueryContract(boundary="other", tier="standard", max_rows=5000))


__all__ = [
    "QueryContract",
    "QueryLintFinding",
    "iter_query_contracts",
    "lint_query_text",
    "query_fingerprint",
    "register_query_contract",
    "resolve_query_contract",
]
