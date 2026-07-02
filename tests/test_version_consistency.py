from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class VersionConsistencyTests(unittest.TestCase):
    def test_version_module_is_single_source_for_app_build_and_config_labels(self):
        import config
        import version
        from utils import logging as usage_logging

        self.assertEqual(version.__version__, version.APP_VERSION)
        self.assertEqual(config.CONFIG_VERSION, version.CONFIG_VERSION)
        self.assertEqual(usage_logging.APP_VERSION, version.APP_VERSION)
        self.assertTrue(version.BUILD_LABEL)
        self.assertTrue(version.RELEASE_CHANNEL)

        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        self.assertIn("from version import CONFIG_VERSION", config_text)
        self.assertNotIn('CONFIG_VERSION = "', config_text)


if __name__ == "__main__":
    unittest.main()
