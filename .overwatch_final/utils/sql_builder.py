"""Small SQL builder primitives for new OVERWATCH query code.

Most legacy SQL in the app still returns Snowflake SQL strings because Snowpark
call sites expect that shape. New code can use SafeQuery to keep SQL text,
parameters, and lineage metadata together before execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class SafeQuery:
    """Immutable SQL container with explicit bind parameters and source labels."""

    sql: str
    params: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    freshness: str = ""

    def with_param(self, name: str, value: Any) -> "SafeQuery":
        params = dict(self.params)
        params[str(name)] = value
        return SafeQuery(self.sql, params=params, source=self.source, freshness=self.freshness)


def bind_identifier(value: object) -> str:
    """Return a conservative Snowflake identifier component."""
    text = str(value or "").strip().upper()
    if text == "ALFA_EDW_PROD":
        text = "ALFA_EDW_PRD"
    elif text.startswith("WH_ALFA_") and text.endswith("_PROD"):
        text = text[:-5] + "_PRD"
    if not text or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,254}", text):
        raise ValueError("Identifier cannot be blank")
    return text


def bind_fqn(database: object, schema: object, name: object) -> str:
    """Return a sanitized three-part Snowflake object name."""
    return ".".join(bind_identifier(part) for part in (database, schema, name))
