"""Build the generated OVERWATCH mart setup monolith from active split DDL."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONOLITH_REL = Path("snowflake/OVERWATCH_MART_SETUP.sql")
ACTIVE_SPLIT_RELS = (
    Path("snowflake/mart_setup/01_runtime_objects.sql"),
    Path("snowflake/mart_setup/02_roles_and_grants.sql"),
    Path("snowflake/mart_setup/03_config_and_audit_tables.sql"),
    Path("snowflake/mart_setup/04_mart_tables.sql"),
    Path("snowflake/mart_setup/05_load_procedures.sql"),
    Path("snowflake/mart_setup/06_alert_framework.sql"),
    Path("snowflake/mart_setup/07_tasks.sql"),
)


def build_monolith_text(root: Path = ROOT) -> str:
    """Return the byte-equivalent deployment monolith text."""
    chunks: list[str] = []
    for rel in ACTIVE_SPLIT_RELS:
        path = root / rel
        chunks.append(path.read_text(encoding="utf-8"))
    return "".join(chunks)


def write_monolith(root: Path = ROOT) -> Path:
    """Regenerate snowflake/OVERWATCH_MART_SETUP.sql from active split files."""
    target = root / MONOLITH_REL
    target.write_text(build_monolith_text(root), encoding="utf-8")
    return target


def monolith_is_current(root: Path = ROOT) -> bool:
    target = root / MONOLITH_REL
    return target.exists() and target.read_text(encoding="utf-8") == build_monolith_text(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero if the generated monolith differs from the checked-in artifact.",
    )
    args = parser.parse_args(argv)
    if args.check:
        return 0 if monolith_is_current(ROOT) else 1
    write_monolith(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
