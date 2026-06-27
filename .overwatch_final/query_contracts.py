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
        if contract.ttl_key_pattern and _matches(contract.ttl_key_pattern, ttl_key):
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
        add("SELECT_STAR", "error", "SELECT * is forbidden for daily app-facing query loaders.")
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
        if where_pos < 0:
            add("MISSING_TARGET_PREDICATE", "error", "Targeted evidence query has no predicate before LIMIT.")
        elif limit_pos >= 0 and where_pos > limit_pos:
            add("PREDICATE_AFTER_LIMIT", "error", "Target predicate must appear before LIMIT.")
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
        tier="recent",
        max_rows=500,
        requires_target_predicate=True,
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
