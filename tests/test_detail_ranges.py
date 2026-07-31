import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import (
    get_system_range,
    get_telemetry_range_sampled,
    initialize_database,
    save_system_snapshot,
    save_telemetry_snapshot,
)


class DetailRangeTests(unittest.TestCase):
    def test_telemetry_range_is_evenly_sampled_and_keeps_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            start = datetime(2026, 7, 31, tzinfo=timezone.utc)
            for index in range(100):
                save_telemetry_snapshot(
                    {},
                    {"soc_percent": 40 + index / 10},
                    "test",
                    db_path,
                    start + timedelta(seconds=index * 2),
                )

            rows = get_telemetry_range_sampled(
                start,
                start + timedelta(minutes=5),
                10,
                db_path,
            )

        self.assertLessEqual(len(rows), 10)
        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[-1]["id"], 100)

    def test_system_range_is_evenly_sampled_and_keeps_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            start = datetime(2026, 7, 31, tzinfo=timezone.utc)
            for index in range(30):
                save_system_snapshot(
                    {"cpu_percent": index},
                    db_path,
                    start + timedelta(minutes=index),
                )

            rows = get_system_range(
                start,
                start + timedelta(hours=1),
                8,
                db_path,
            )

        self.assertLessEqual(len(rows), 8)
        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[-1]["id"], 30)


if __name__ == "__main__":
    unittest.main()
