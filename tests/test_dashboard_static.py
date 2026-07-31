import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class DashboardStaticTests(unittest.TestCase):
    def test_dashboard_contains_all_panels_periods_and_refresh_state(self) -> None:
        html = (PROJECT_DIR / "static" / "index.html").read_text()

        for panel in ("solar", "home", "battery", "grid", "system"):
            self.assertIn(f'data-panel="{panel}"', html)
        for period in ("day", "week", "month", "all"):
            self.assertIn(f'data-period="{period}"', html)
        self.assertIn('id="frame-meta"', html)
        self.assertIn('id="current-clock"', html)
        self.assertNotIn("progress-bar", html)


if __name__ == "__main__":
    unittest.main()
