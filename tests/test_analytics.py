import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analytics import build_energy_analytics
from database import get_telemetry_range, initialize_database, save_telemetry_snapshot


def telemetry(pv: float, load: float, grid: float, battery: float, soc: float) -> dict:
    return {
        "pv_power_w": {"total": pv},
        "load_power_w": {"total": load},
        "grid_power_w": {"total": grid},
        "battery_power_w": battery,
        "battery_voltage_v": 53.2,
        "battery_current_a": battery / 53.2,
        "soc_percent": soc,
        "batteries": [
            {"current_a": battery / 106.4, "cell_delta_mv": 4},
            {"current_a": battery / 106.4, "cell_delta_mv": 5},
        ],
    }


class AnalyticsTests(unittest.TestCase):
    def test_integrates_energy_and_battery_directions(self) -> None:
        start = datetime(2026, 7, 31, tzinfo=timezone.utc)
        rows = [
            {"timestamp": start.isoformat(), "parsed": telemetry(4000, 2000, -500, 1500, 40)},
            {"timestamp": (start + timedelta(hours=1)).isoformat(), "parsed": telemetry(4000, 2000, -500, 1500, 60)},
        ]
        result = build_energy_analytics(rows, max_points=60, max_gap_seconds=7200)

        self.assertEqual(result["stats"]["pv_kwh"], 4.0)
        self.assertEqual(result["stats"]["load_kwh"], 2.0)
        self.assertEqual(result["stats"]["grid_export_kwh"], 0.5)
        self.assertEqual(result["stats"]["battery_charge_kwh"], 1.5)
        self.assertEqual(result["stats"]["self_consumption_kwh"], 3.5)
        self.assertEqual(result["stats"]["soc_min_percent"], 40)
        self.assertEqual(result["stats"]["soc_max_percent"], 60)

    def test_does_not_integrate_long_data_gaps(self) -> None:
        start = datetime(2026, 7, 31, tzinfo=timezone.utc)
        rows = [
            {"timestamp": start.isoformat(), "parsed": telemetry(5000, 1000, 0, 4000, 40)},
            {"timestamp": (start + timedelta(minutes=10)).isoformat(), "parsed": telemetry(5000, 1000, 0, 4000, 41)},
        ]
        result = build_energy_analytics(rows)
        self.assertEqual(result["stats"]["pv_kwh"], 0)
        self.assertEqual(result["integrated_seconds"], 0)

    def test_range_query_is_half_open(self) -> None:
        start = datetime(2026, 7, 31, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            for hour in (0, 12, 24):
                save_telemetry_snapshot(
                    raw_data={},
                    parsed_data=telemetry(1, 1, 0, 0, 50),
                    source="test",
                    db_path=db_path,
                    timestamp=start + timedelta(hours=hour),
                )
            rows = get_telemetry_range(start, start + timedelta(days=1), db_path)
        self.assertEqual([row["id"] for row in rows], [1, 2])


if __name__ == "__main__":
    unittest.main()
