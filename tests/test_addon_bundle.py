import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
ADDON_APP_DIR = PROJECT_DIR / "felicity_dashboard_addon" / "app"
BUNDLED_FILES = (
    "app.py",
    "collector.py",
    "config.py",
    "database.py",
    "felicity_local.py",
    "main.py",
    "system_monitor.py",
    "static/index.html",
)


class AddonBundleTests(unittest.TestCase):
    def test_bundled_application_matches_project(self) -> None:
        for relative_path in BUNDLED_FILES:
            with self.subTest(path=relative_path):
                source = (PROJECT_DIR / relative_path).read_bytes()
                bundled = (ADDON_APP_DIR / relative_path).read_bytes()
                self.assertEqual(source, bundled)


if __name__ == "__main__":
    unittest.main()
