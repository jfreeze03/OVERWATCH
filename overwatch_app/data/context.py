"""Shared v2 query scope."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryScope:
    company: str = "ALL"
    environment: str = "ALL"
    window: int = 30
    warehouse: str = "ALL"
    workflow: str = "Overview"
    role: str = ""
    source_version: str = "current"

    def cache_parts(self) -> tuple[str, str, int, str, str, str, str]:
        return (
            str(self.company or "ALL").upper(),
            str(self.environment or "ALL").upper(),
            int(self.window or 30),
            str(self.warehouse or "ALL").upper(),
            str(self.workflow or "Overview"),
            str(self.role or "").upper(),
            str(self.source_version or "current"),
        )

    def cache_key(self, namespace: str) -> str:
        return "|".join((namespace, *map(str, self.cache_parts())))


def build_scope(
    *,
    company: str = "ALL",
    environment: str = "ALL",
    window: int = 30,
    warehouse: str = "ALL",
    workflow: str = "Overview",
    role: str = "",
    source_version: str = "current",
) -> QueryScope:
    return QueryScope(
        company=company,
        environment=environment,
        window=int(window or 30),
        warehouse=warehouse,
        workflow=workflow,
        role=role,
        source_version=source_version,
    )
