from __future__ import annotations

from pathlib import Path
import re
import unittest

from tools.build_mart_setup_monolith import ACTIVE_SPLIT_RELS, build_monolith_text, monolith_is_current


ROOT = Path(__file__).resolve().parents[1]
MART_SETUP_DIR = ROOT / "snowflake" / "mart_setup"
MANIFEST = ROOT / "snowflake" / "ACTIVE_MART_DDL_MANIFEST.yml"
REVIEW_DOC = ROOT / "docs" / "DDL_ACTIVE_MART_REVIEW.md"
VALIDATION_SQL = ROOT / "snowflake" / "validation" / "validate_overwatch_mart_setup.sql"
DROP_SQL = ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql"
MONOLITH = ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql"

ACTIVE_SETUP_FILES = tuple(path.as_posix() for path in ACTIVE_SPLIT_RELS)

RETIRED_ACTIVE_OBJECTS = (
    "FACT_MONITORING_COST_DAILY",
    "OVERWATCH_AUTOMATION_RUN",
    "OVERWATCH_AUTOMATION_HEALTH_V",
    "SP_OVERWATCH_REFRESH_AUTOMATION",
    "OVERWATCH_AUTOMATION_REFRESH",
    "OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY",
    "OVERWATCH_REFRESH_POLICY",
    "OVERWATCH_COMPANY_SCOPE",
    "OVERWATCH_COMPLIANCE_READINESS_V",
)


def _active_setup_text() -> str:
    return "".join((ROOT / rel).read_text(encoding="utf-8") for rel in ACTIVE_SETUP_FILES)


def _created_objects(sql: str) -> set[tuple[str, str]]:
    objects: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"(?im)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:TRANSIENT|SECURE)\s+)?"
        r"(TABLE|VIEW|PROCEDURE|TASK)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Z0-9_\.\"]+)"
    )
    for match in pattern.finditer(sql):
        object_type = match.group(1).upper()
        object_name = match.group(2).strip('"').split(".")[-1].upper()
        if object_name.startswith(("TMP_", "TEMP_")):
            continue
        objects.add((object_type, object_name))
    return objects


class ActiveMartDdlManifestTests(unittest.TestCase):
    def test_active_mart_setup_path_is_exactly_seven_files(self) -> None:
        actual = tuple(f"snowflake/mart_setup/{path.name}" for path in sorted(MART_SETUP_DIR.glob("[0-9][0-9]_*.sql")))
        self.assertEqual(actual, ACTIVE_SETUP_FILES)
        self.assertNotIn("snowflake/mart_setup/08_validation.sql", actual)
        self.assertNotIn("snowflake/mart_setup/09_summary_marts.sql", actual)

    def test_validation_and_summary_paths_are_separated_correctly(self) -> None:
        self.assertTrue(VALIDATION_SQL.is_file())
        self.assertFalse((MART_SETUP_DIR / "08_validation.sql").exists())
        self.assertFalse((MART_SETUP_DIR / "09_summary_marts.sql").exists())
        mart_sql = (MART_SETUP_DIR / "04_mart_tables.sql").read_text(encoding="utf-8").upper()
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_QUERY_DAILY_SUMMARY", mart_sql)
        self.assertIn("CREATE OR REPLACE SECURE VIEW V_EXECUTIVE_PACKET_CURRENT", mart_sql)
        self.assertIn("CREATE OR REPLACE SECURE VIEW V_LEADERSHIP_CREDIT_DAILY", mart_sql)

    def test_generated_monolith_matches_active_split_only(self) -> None:
        self.assertTrue(monolith_is_current(ROOT))
        self.assertEqual(MONOLITH.read_text(encoding="utf-8"), build_monolith_text(ROOT))
        self.assertNotIn("SECTION_COMMAND_SOURCE_ENVIRONMENT_METADATA", MONOLITH.read_text(encoding="utf-8"))
        self.assertIn("SECTION_COMMAND_SOURCE_ENVIRONMENT_METADATA", VALIDATION_SQL.read_text(encoding="utf-8"))

    def test_manifest_and_review_cover_every_sql_file(self) -> None:
        self.assertTrue(MANIFEST.is_file())
        self.assertTrue(REVIEW_DOC.is_file())
        manifest = MANIFEST.read_text(encoding="utf-8")
        review = REVIEW_DOC.read_text(encoding="utf-8")
        for rel in ACTIVE_SETUP_FILES:
            self.assertIn(rel, manifest)
            self.assertIn(rel, review)
        for rel in sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*.sql")
            if ".git/" not in path.as_posix()
        ):
            with self.subTest(sql=rel):
                self.assertIn(rel, review)
        self.assertIn("monolith_builder: tools/build_mart_setup_monolith.py", manifest)

    def test_active_objects_are_resettable(self) -> None:
        drop_sql = DROP_SQL.read_text(encoding="utf-8").upper()
        missing: list[str] = []
        for object_type, object_name in sorted(_created_objects(_active_setup_text())):
            expected = f"DROP {object_type} IF EXISTS {object_name}"
            if expected not in drop_sql:
                missing.append(f"{object_type} {object_name}")
        self.assertFalse(missing, "active created objects missing reset coverage: " + ", ".join(missing[:20]))

    def test_retired_objects_are_not_recreated_by_active_setup(self) -> None:
        sql = _active_setup_text().upper()
        for object_name in RETIRED_ACTIVE_OBJECTS:
            with self.subTest(object_name=object_name):
                self.assertIsNone(
                    re.search(rf"(?im)^\s*CREATE\b[\s\S]{{0,120}}\b{re.escape(object_name)}\b", sql),
                    f"{object_name} must stay out of active mart setup",
                )


if __name__ == "__main__":
    unittest.main()
