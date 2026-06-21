from pathlib import Path


def read_mart_setup_sql(root: Path) -> str:
    """Return the deployable mart setup SQL in numeric execution order."""
    setup_dir = root / "snowflake" / "mart_setup"
    if setup_dir.exists():
        return "\n\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(setup_dir.glob("[0-9][0-9]_*.sql"))
        )
    return (root / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
