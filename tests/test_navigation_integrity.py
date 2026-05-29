from pathlib import Path
import importlib.util
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from config import (  # noqa: E402
    ALL_SECTIONS,
    NAV_GROUPS,
    ROLE_SECTIONS,
    SECTION_ALIASES,
    SECTION_BY_TITLE,
    SECTION_DEFINITIONS,
    SECTION_MODULES,
)


class NavigationIntegrityTests(unittest.TestCase):
    def test_section_registry_matches_navigation(self):
        flattened = [section for sections in NAV_GROUPS.values() for section in sections]
        defined = [section.label for section in SECTION_DEFINITIONS]
        self.assertEqual(ALL_SECTIONS, flattened)
        self.assertEqual(ALL_SECTIONS, defined)
        self.assertEqual(set(ALL_SECTIONS), set(SECTION_MODULES))
        self.assertEqual(
            SECTION_MODULES,
            {section.label: section.module for section in SECTION_DEFINITIONS},
        )

    def test_section_definitions_are_complete(self):
        for section in SECTION_DEFINITIONS:
            with self.subTest(section=section.title):
                self.assertTrue(section.group)
                self.assertTrue(section.icon)
                self.assertTrue(section.title)
                self.assertTrue(section.module)
                self.assertEqual(section.label, f"{section.icon} {section.title}")

    def test_registered_modules_exist(self):
        missing = [
            module_path
            for module_path in SECTION_MODULES.values()
            if importlib.util.find_spec(module_path) is None
        ]
        self.assertEqual(missing, [])

    def test_roles_and_aliases_resolve_to_visible_sections(self):
        for role, sections in ROLE_SECTIONS.items():
            with self.subTest(role=role):
                self.assertTrue(sections)
                self.assertLessEqual(set(sections), set(ALL_SECTIONS))

        self.assertLessEqual(set(SECTION_ALIASES.values()), set(ALL_SECTIONS))
        self.assertEqual(SECTION_ALIASES["Credit Contract"], SECTION_BY_TITLE["Cost Center"])
        self.assertEqual(SECTION_ALIASES["Optimization"], SECTION_BY_TITLE["Warehouse Health"])

    def test_every_navigation_label_has_an_icon_prefix(self):
        for section in ALL_SECTIONS:
            with self.subTest(section=section):
                icon, _, title = section.partition(" ")
                self.assertTrue(icon)
                self.assertTrue(title)
                self.assertFalse(icon[0].isalnum())


if __name__ == "__main__":
    unittest.main()
