from __future__ import annotations

import dataclasses
from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from sections.section_command_brief import SectionCommandSignal
from utils import action_queue


def _retired_column(*parts: str) -> str:
    return "_".join(parts)


_RETIRED_ENTITY = "owner"

RETIRED_SIGNAL_FIELDS = {
    "workflow_route",
    "workflow_gap",
    "owner_id",
    "owner_name",
}

RETIRED_ACTION_QUEUE_COLUMNS = {
    _retired_column("OWNER"),
    _retired_column("OWNER", "APPROVAL", "STATUS"),
    _retired_column("OWNER", "APPROVAL", "BY"),
    _retired_column("OWNER", "APPROVAL", "AT"),
    _retired_column("OWNER", "APPROVAL", "NOTE"),
    _retired_column("OWNER", "EMAIL"),
    _retired_column("ROUTE", "EMAIL"),
    _retired_column("REVIEW", "PRIMARY"),
    _retired_column("REVIEW", "SECONDARY"),
    _retired_column("REVIEW", "GROUP"),
    _retired_column("REVIEW", "TARGET"),
    _retired_column("ROUTE", "SOURCE"),
    _retired_column("ROUTE", "EVIDENCE"),
    _retired_column("APPROVAL", "ROUTE", "READY"),
    _retired_column("ON" + "CALL", "PRIMARY"),
    _retired_column("ON" + "CALL", "SECONDARY"),
    _retired_column("APPROVAL", "GROUP"),
    _retired_column("ESCALATION", "TARGET"),
    _retired_column("OWNER", "SOURCE"),
    _retired_column("OWNER", "EVIDENCE"),
}

FORBIDDEN_DAILY_TEXT = (
    f"{_RETIRED_ENTITY} unavailable",
    f"{_RETIRED_ENTITY} route",
    f"{_RETIRED_ENTITY} routing",
    f"{_RETIRED_ENTITY} approval",
    "approval " + "group",
    "escalation " + "target",
    "on-call",
    "oncall",
)


class OwnerRoutingRemovedTests(unittest.TestCase):
    def test_section_command_signal_has_no_owner_routing_fields(self) -> None:
        fields = {field.name for field in dataclasses.fields(SectionCommandSignal)}
        self.assertFalse(RETIRED_SIGNAL_FIELDS & fields)
        self.assertIn("route_section", fields)
        self.assertIn("route_workflow", fields)
        self.assertIn("route_key", fields)

    def test_action_queue_optional_schema_has_no_owner_routing_columns(self) -> None:
        columns = set(action_queue.ACTION_QUEUE_OPTIONAL_COLUMN_TYPES)
        self.assertFalse(RETIRED_ACTION_QUEUE_COLUMNS & columns)

    def test_action_queue_enrichment_text_is_workflow_based(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "STATUS": "New",
                    "CATEGORY": "Cost",
                    "SEVERITY": "High",
                    "ENTITY_NAME": "WAREHOUSE_A",
                    "TICKET_ID": "",
                    "APPROVER": "",
                    "VERIFICATION_QUERY": "",
                    "BASELINE_VALUE": "",
                    "CURRENT_VALUE": "",
                }
            ]
        )
        enriched = action_queue.enrich_action_queue_view(rows, today="2026-07-06")
        text = " ".join(str(value) for value in enriched.to_numpy().ravel()).lower()
        for forbidden in FORBIDDEN_DAILY_TEXT:
            self.assertNotIn(forbidden, text)
        self.assertIn("missing ticket/change id", text)

    def test_core_first_paint_renderers_do_not_emit_owner_columns(self) -> None:
        files = [
            ROOT / ".overwatch_final" / "sections" / "decision_workspace_components.py",
            ROOT / ".overwatch_final" / "sections" / "command_center_components.py",
            ROOT / ".overwatch_final" / "sections" / "command_center_models.py",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in files).lower()
        for forbidden in FORBIDDEN_DAILY_TEXT:
            self.assertNotIn(forbidden, text)
        self.assertNotIn(">owner<", text)

    def test_action_queue_ddl_builder_has_no_retired_owner_columns(self) -> None:
        ddl = action_queue.build_action_queue_ddl().upper()
        self.assertNotIn(" OWNER ", ddl)
        for column in RETIRED_ACTION_QUEUE_COLUMNS:
            self.assertNotIn(column, ddl)

    def test_active_setup_sql_does_not_create_retired_owner_routing(self) -> None:
        active_sql_paths = [
            ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql",
            ROOT / "snowflake" / "mart_setup" / "03_config_and_audit_tables.sql",
            ROOT / "snowflake" / "mart_setup" / "04_mart_tables.sql",
            ROOT / "snowflake" / "mart_setup" / "05_load_procedures.sql",
            ROOT / "snowflake" / "mart_setup" / "06_alert_framework.sql",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in active_sql_paths).upper()
        allowed_snowflake_syntax = "EXECUTE AS OWNER"
        scrubbed = text.replace(allowed_snowflake_syntax, "")
        forbidden = {
            _retired_column("OVERWATCH", "OPERATIONAL", "OWNER", "MAP"),
            _retired_column("MART", "OPERATIONAL", "OWNER", "COVERAGE"),
            _retired_column("OVERWATCH", "OWNER", "TAG", "NAMES"),
            _retired_column("DIM", "COST", "OWNER", "TAG"),
            _retired_column("ALERT", "OWNER", "ROUTING"),
            _retired_column("OWNER", "EMAIL"),
            "OWNER_ID",
            "OWNER_NAME",
            "OWNER_ASSIGNED",
            "OWNER_APPROVAL",
            "ONCALL",
            "APPROVAL_GROUP",
            "ESCALATION_TARGET",
            _retired_column("OWNER", "SOURCE"),
            _retired_column("OWNER", "EVIDENCE"),
            _retired_column("ROUTE", "EMAIL"),
            _retired_column("REVIEW", "PRIMARY"),
            _retired_column("REVIEW", "SECONDARY"),
            _retired_column("REVIEW", "GROUP"),
            _retired_column("REVIEW", "TARGET"),
            _retired_column("ROUTE", "SOURCE"),
            _retired_column("ROUTE", "EVIDENCE"),
            _retired_column("APPROVAL", "ROUTE", "READY"),
            _retired_column("OWNER", "ROUTE"),
            _retired_column("OWNER", "GAP"),
            "COST_OWNER",
            "DATA_OWNER",
            "APP_OWNER",
            "BUSINESS_OWNER",
            "SERVICE_OWNER",
        }
        for token in sorted(forbidden):
            self.assertNotIn(token, scrubbed)
        self.assertIn("MART_OPERATIONAL_ROUTE_COVERAGE", scrubbed)
        self.assertIn("OVERWATCH_OPERATIONAL_ROUTE_MAP", scrubbed)
        self.assertNotIn(" OWNER ", scrubbed)

    def test_owner_routing_migration_and_validation_exist(self) -> None:
        migration = ROOT / "snowflake" / "migrations" / "2026_07_remove_owner_routing.sql"
        validation = ROOT / "snowflake" / "validation" / "validate_owner_routing_removed.sql"
        audit = ROOT / "docs" / "OWNER_ROUTING_REMOVAL_AUDIT.md"
        self.assertTrue(migration.exists())
        self.assertTrue(validation.exists())
        self.assertTrue(audit.exists())
        self.assertIn(
            "DROP COLUMN IF EXISTS " + _retired_column("OWNER", "APPROVAL", "STATUS"),
            migration.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "DROP COLUMN IF EXISTS " + _retired_column("ROUTE", "EMAIL"),
            migration.read_text(encoding="utf-8"),
        )
        self.assertIn(_retired_column("REVIEW", "PRIMARY"), validation.read_text(encoding="utf-8"))
        self.assertIn("INFORMATION_SCHEMA.COLUMNS", validation.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
