from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class LeadershipWatchlistRemovalTests(unittest.TestCase):
    def test_standalone_watchlist_panel_module_is_removed(self) -> None:
        retired_path = APP_ROOT / "sections" / "leadership_watchlist_panels.py"
        self.assertFalse(retired_path.exists(), "standalone leadership watchlist panel must stay removed")

    def test_active_runtime_does_not_reference_removed_watchlist_panel(self) -> None:
        forbidden = (
            "leadership_watchlist_panels",
            "render_leadership_watchlist_strip",
            "render_cost_leadership_panels",
            "render_security_leadership_panels",
            "leadership_alert_candidates",
        )
        hits: list[str] = []
        for root in (APP_ROOT, ROOT / "tools"):
            for path in root.rglob("*.py"):
                if path == Path(__file__):
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for token in forbidden:
                    if token in text:
                        hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
