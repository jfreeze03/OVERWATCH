"""Decision Workspace sidecar contract registries.

The active runtime imports the allowlists lazily from this package when
performance tracing needs to decide whether an admin/setup action may open a
session or issue direct SQL. Keeping the package surface explicit prevents this
directory from drifting back into inert stubs.
"""

__all__ = [
    "direct_sql_allowlist",
    "session_open_allowlist",
]
