from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from utils.data_state import (  # noqa: E402
    DataState,
    classify_data_state,
    data_state_label,
    detail_available_text,
    final_state_text,
    first_paint_text,
)


FIRST_PAINT_FILES = (
    APP_ROOT / "sections" / "section_command_brief.py",
    APP_ROOT / "sections" / "section_command_rendering.py",
    APP_ROOT / "sections" / "decision_workspace_components.py",
    APP_ROOT / "sections" / "decision_workspace_view_model.py",
    APP_ROOT / "sections" / "summary_mart_loaders.py",
    APP_ROOT / "sections" / "command_center_components.py",
    APP_ROOT / "sections" / "command_center_models.py",
)

RETIRED_PHRASES = tuple(
    "".join(parts)
    for parts in (
        ("Summary", " pending"),
        ("Packet", " pending"),
        ("Evidence loads", " on request"),
        ("Load Cost", " Evidence"),
        ("Load Security", " Evidence"),
        ("Generate Run-Rate", " Projection"),
        ("Load Annual Service", " Projection"),
        ("On", " demand"),
        ("Loading", " summary"),
    )
)


class MartFirstPaintStateTests(unittest.TestCase):
    def test_data_state_maps_generic_placeholders_to_actionable_state(self) -> None:
        self.assertEqual(data_state_label(DataState.REFRESH_REQUIRED), "Refresh required")
        self.assertEqual(data_state_label(DataState.SETUP_REQUIRED), "Setup required")
        self.assertEqual(data_state_label(DataState.CONNECTION_UNAVAILABLE), "Connection unavailable")
        self.assertEqual(data_state_label(DataState.QUERY_FAILED), "Query failed")
        self.assertEqual(first_paint_text("Summary" + " pending"), "Refresh required")
        self.assertEqual(final_state_text("Packet" + " pending"), "Refresh required")
        self.assertEqual(detail_available_text(), "Details available when needed")
        self.assertEqual(classify_data_state("permission denied"), DataState.QUERY_FAILED)

    def test_data_state_labels_are_final_state_copy_not_loading_copy(self) -> None:
        forbidden = ("loading", "pending", "on demand", "on request")
        for state in DataState:
            label = data_state_label(state).lower()
            self.assertFalse(any(token in label for token in forbidden), (state, label))

    def test_first_paint_runtime_sources_do_not_emit_retired_phrases(self) -> None:
        for path in FIRST_PAINT_FILES:
            source = path.read_text(encoding="utf-8")
            for phrase in RETIRED_PHRASES:
                self.assertNotIn(phrase, source, f"{phrase!r} should not appear in {path}")


if __name__ == "__main__":
    unittest.main()
