from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


PACKAGE_THRESHOLD_LINES = 800


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


class SectionArchitectureTests(unittest.TestCase):
    def test_section_architecture_convention_is_documented(self):
        doc = (ROOT / "docs" / "SECTION_ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("Package-style sections", doc)
        self.assertIn("dba_control_room", doc)
        self.assertIn("cost_contract", doc)
        self.assertIn("alert_center", doc)
        self.assertIn("query_investigation_root_cause.py", doc)

    def test_primary_section_inventory_marks_large_single_file_candidates(self):
        from config import SECTION_MODULES

        dba_path = APP_ROOT / "sections" / "dba_control_room"
        self.assertTrue(dba_path.is_dir())
        self.assertTrue((dba_path / "__init__.py").exists())

        candidates: dict[str, int] = {}
        for section, module in SECTION_MODULES.items():
            module_path = APP_ROOT / Path(*module.split(".")).with_suffix(".py")
            package_path = APP_ROOT / Path(*module.split("."))
            if package_path.is_dir():
                continue
            if module_path.exists() and _line_count(module_path) > PACKAGE_THRESHOLD_LINES:
                candidates[section] = _line_count(module_path)

        self.assertIn("Alert Center", candidates)
        self.assertGreater(candidates["Alert Center"], PACKAGE_THRESHOLD_LINES)

        cost_module = APP_ROOT / "sections" / "cost_contract.py"
        self.assertTrue(cost_module.exists())
        self.assertLessEqual(_line_count(cost_module), PACKAGE_THRESHOLD_LINES)

    def test_retired_query_workbench_module_is_absent(self):
        self.assertFalse((APP_ROOT / "sections" / "query_workbench.py").exists())


if __name__ == "__main__":
    unittest.main()
