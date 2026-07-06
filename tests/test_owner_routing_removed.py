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


RETIRED_SIGNAL_FIELDS = {
    "owner_route",
    "owner_gap",
    "owner_id",
    "owner_name",
}

RETIRED_ACTION_QUEUE_COLUMNS = {
    "OWNER_APPROVAL_STATUS",
    "OWNER_APPROVAL_BY",
    "OWNER_APPROVAL_AT",
    "OWNER_APPROVAL_NOTE",
    "OWNER_EMAIL",
    "ONCALL_PRIMARY",
    "ONCALL_SECONDARY",
    "APPROVAL_GROUP",
    "ESCALATION_TARGET",
    "OWNER_SOURCE",
    "OWNER_EVIDENCE",
}

FORBIDDEN_DAILY_TEXT = (
    "owner unavailable",
    "owner route",
    "owner approval",
    "approval group",
    "escalation target",
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

    def test_owner_routing_migration_and_validation_exist(self) -> None:
        migration = ROOT / "snowflake" / "migrations" / "2026_07_remove_owner_routing.sql"
        validation = ROOT / "snowflake" / "validation" / "validate_owner_routing_removed.sql"
        audit = ROOT / "docs" / "OWNER_ROUTING_REMOVAL_AUDIT.md"
        self.assertTrue(migration.exists())
        self.assertTrue(validation.exists())
        self.assertTrue(audit.exists())
        self.assertIn("DROP COLUMN IF EXISTS OWNER_APPROVAL_STATUS", migration.read_text(encoding="utf-8"))
        self.assertIn("INFORMATION_SCHEMA.COLUMNS", validation.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
