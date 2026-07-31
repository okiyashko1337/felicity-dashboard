import unittest
from pathlib import Path

from app import index


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
        for scale in ("15m", "1h", "6h", "day"):
            self.assertIn(f'data-detail-scale="{scale}"', html)
        for card in ("bms1-soc", "bms2-soc", "temperature-main", "dc-bus", "backup-power"):
            self.assertIn(f'id="{card}"', html)
        self.assertIn("Текущий день", html)
        self.assertIn("00:00–23:59", html)
        self.assertIn("UI 0.6.0", html)
        self.assertNotIn("progress-bar", html)

    def test_dashboard_html_is_never_cached(self) -> None:
        response = index()

        self.assertEqual(
            response.headers["cache-control"],
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        self.assertEqual(response.headers["x-felicity-ui-version"], "0.6.0")


if __name__ == "__main__":
    unittest.main()
