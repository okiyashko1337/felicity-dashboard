import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import sqlite3

from database import (
    get_latest_telemetry,
    get_parsed_telemetry_range_sampled,
    get_system_range,
    get_telemetry_range_sampled,
    initialize_database,
    save_system_snapshot,
    save_telemetry_snapshot,
)


class DetailRangeTests(unittest.TestCase):
    def test_database_context_closes_every_connection(self) -> None:
        real_connect = sqlite3.connect
        opened = []

        def tracked_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            opened.append(connection)
            return connection

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            with patch("database.sqlite3.connect", side_effect=tracked_connect):
                initialize_database(db_path)

        self.assertTrue(opened)
        for connection in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

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
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["timestamp"], start.isoformat())
        self.assertEqual(rows[-1]["timestamp"], (start + timedelta(seconds=120)).isoformat())

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

    def test_compact_sampled_range_never_loads_raw_packets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            start = datetime(2026, 7, 31, tzinfo=timezone.utc)
            for index in range(20):
                save_telemetry_snapshot(
                    [{"large": "raw" * 100}],
                    {"soc_percent": index},
                    "test",
                    db_path,
                    start + timedelta(seconds=index * 10),
                )

            rows = get_parsed_telemetry_range_sampled(
                start, start + timedelta(minutes=5), 5, db_path
            )
            latest = get_latest_telemetry(db_path)

        self.assertLessEqual(len(rows), 5)
        self.assertEqual(rows[0]["parsed"], {"soc_percent": 0})
        self.assertEqual(rows[-1]["parsed"], {"soc_percent": 12})
        self.assertEqual(latest["parsed"], {"soc_percent": 19})
        self.assertNotIn("raw", rows[0])


if __name__ == "__main__":
    unittest.main()
