import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
ADDON_APP_DIR = PROJECT_DIR / "felicity_dashboard_addon" / "app"
BUNDLED_FILES = (
    "analytics.py",
    "app.py",
    "collector.py",
    "config.py",
    "database.py",
    "device_update.py",
    "felicity_local.py",
    "main.py",
    "nextion_bridge.py",
    "storage_migration.py",
    "system_monitor.py",
    "static/index.html",
)
FIRMWARE_FILES = (
    "felicity-esp32.bin",
    "felicity-nextion.tft",
)


class AddonBundleTests(unittest.TestCase):
    def test_bundled_application_matches_project(self) -> None:
        for relative_path in BUNDLED_FILES:
            with self.subTest(path=relative_path):
                source = (PROJECT_DIR / relative_path).read_bytes()
                bundled = (ADDON_APP_DIR / relative_path).read_bytes()
                self.assertEqual(source, bundled)

    def test_bundled_firmware_matches_release_artifacts(self) -> None:
        for filename in FIRMWARE_FILES:
            with self.subTest(path=filename):
                source = (PROJECT_DIR / "firmware" / filename).read_bytes()
                bundled = (ADDON_APP_DIR / "firmware" / filename).read_bytes()
                self.assertGreater(len(source), 0)
                self.assertEqual(source, bundled)


if __name__ == "__main__":
    unittest.main()
