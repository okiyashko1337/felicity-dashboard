import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import _device_chart_sample
from database import (
    get_parsed_telemetry_history,
    initialize_database,
    save_telemetry_snapshot,
)


class DeviceApiTests(unittest.TestCase):
    def test_compact_history_omits_raw_packets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            save_telemetry_snapshot(
                raw_data=[{"large": "raw packet"}],
                parsed_data={"soc_percent": 42},
                source="test",
                db_path=db_path,
                timestamp=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )

            rows = get_parsed_telemetry_history(10, db_path)

        self.assertEqual(rows[0]["parsed"], {"soc_percent": 42})
        self.assertNotIn("raw", rows[0])

    def test_chart_samples_match_nextion_series_order(self) -> None:
        parsed = {
            "pv_power_w": {"total": 3000, "pv1": 1800, "pv2": 1200},
            "load_power_w": {"total": 1500, "l1": 500, "l2": 450, "l3": 550},
            "soc_percent": 74,
            "battery_power_w": -900,
            "grid_voltage_v": {"l1": 230.1, "l2": 231.2, "l3": 229.8},
            "grid_power_w": {"total": 125},
        }

        self.assertEqual(_device_chart_sample("pv", parsed), [3000, 1800, 1200])
        self.assertEqual(_device_chart_sample("load", parsed), [1500, 500, 450, 550])
        self.assertEqual(_device_chart_sample("battery", parsed), [74, -900])
        self.assertEqual(
            _device_chart_sample("grid", parsed),
            [230.1, 231.2, 229.8, 125],
        )


if __name__ == "__main__":
    unittest.main()
