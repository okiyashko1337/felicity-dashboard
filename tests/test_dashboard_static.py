import unittest
from pathlib import Path
from unittest.mock import patch

from app import APP_VERSION, index, status


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
        self.assertIn('id="stat-coverage-ratio"', html)
        self.assertIn('id="stat-coverage-percent"', html)
        self.assertIn("felicity-hidden-series-v1", html)
        self.assertIn("rememberLegendClick", html)
        self.assertIn('id="detail-gap-status"', html)
        self.assertIn('id="history-gap-status"', html)
        self.assertIn('id="update-esp32"', html)
        self.assertIn('id="update-nextion"', html)
        self.assertIn('id="device-update-status"', html)
        self.assertIn("requestDeviceUpdate", html)
        self.assertIn("gapBefore", html)
        self.assertIn('line("Сумма, Вт"', html)
        self.assertIn("pv_power_w?.pv1) + number(row.parsed.pv_power_w?.pv2)", html)
        self.assertIn("UI __FELICITY_APP_VERSION__", html)
        self.assertNotIn("UI 0.7.0", html)
        self.assertNotIn("progress-bar", html)

    def test_dashboard_html_is_never_cached(self) -> None:
        response = index()

        self.assertEqual(
            response.headers["cache-control"],
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        self.assertEqual(response.headers["x-felicity-ui-version"], APP_VERSION)
        rendered = response.body.decode()
        self.assertIn(f"UI {APP_VERSION}", rendered)
        self.assertNotIn("__FELICITY_APP_VERSION__", rendered)

    def test_status_exposes_the_same_app_version_without_telemetry(self) -> None:
        with patch("app.get_latest_telemetry", return_value=None):
            payload = status()

        self.assertEqual(payload["app_version"], APP_VERSION)


if __name__ == "__main__":
    unittest.main()
