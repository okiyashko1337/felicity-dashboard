import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import (
    get_latest_telemetry,
    get_parsed_telemetry_history,
    get_telemetry_timestamps,
    initialize_database,
    migrate_compact_storage,
    save_system_snapshot,
    save_telemetry_snapshot,
)


def telemetry(index: int) -> dict:
    return {
        "pv_power_w": {"total": index, "pv1": index, "pv2": 0},
        "load_power_w": {"total": index, "l1": index, "l2": 0, "l3": 0},
        "grid_power_w": {"total": 0},
        "grid_voltage_v": {"l1": 230, "l2": 230, "l3": 230},
        "battery_power_w": 0,
        "soc_percent": 50,
        "battery_voltage_v": 52,
        "battery_current_a": 0,
        "batteries": [{"soc_percent": 50, "current_a": 0, "cell_delta_mv": 3}],
        "diagnostic_only": "x" * 500,
    }


class StorageMigrationTests(unittest.TestCase):
    def test_legacy_raw_history_is_compacted_and_migration_is_idempotent(self) -> None:
        start = datetime(2026, 8, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE telemetry_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    raw_data_json TEXT NOT NULL,
                    parsed_data_json TEXT NOT NULL
                )
                """
            )
            for index in range(181):
                connection.execute(
                    """
                    INSERT INTO telemetry_snapshots
                        (timestamp, source, raw_data_json, parsed_data_json)
                    VALUES (?, 'legacy', ?, ?)
                    """,
                    (
                        (start + timedelta(seconds=index * 2)).isoformat(),
                        json.dumps({"raw": "y" * 1000}),
                        json.dumps(telemetry(index)),
                    ),
                )
            connection.commit()
            connection.close()
            before_size = db_path.stat().st_size

            result = migrate_compact_storage(db_path)
            second = migrate_compact_storage(db_path)
            latest = get_latest_telemetry(db_path)
            history = get_parsed_telemetry_history(100, db_path)
            coverage = get_telemetry_timestamps(
                start, start + timedelta(hours=1), db_path
            )
            with sqlite3.connect(db_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(telemetry_snapshots)")
                }

            self.assertEqual(result["before_rows"], 181)
            self.assertEqual(result["after_rows"], 4)
            self.assertTrue(result["vacuumed"])
            self.assertFalse(second["migrated"])
            self.assertNotIn("raw_data_json", columns)
            self.assertEqual(len(history), 4)
            self.assertNotIn("diagnostic_only", history[0]["parsed"])
            self.assertEqual(latest["id"], 181)
            self.assertEqual(latest["parsed"]["diagnostic_only"], "x" * 500)
            self.assertEqual(len(coverage), 181)
            self.assertLess(db_path.stat().st_size, before_size)

    def test_live_polling_keeps_full_current_and_two_minute_compact_history(self) -> None:
        start = datetime(2026, 8, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            for index in range(121):
                save_telemetry_snapshot(
                    raw_data={"never": "stored"},
                    parsed_data=telemetry(index),
                    source="test",
                    db_path=db_path,
                    timestamp=start + timedelta(seconds=index * 2),
                )

            latest = get_latest_telemetry(db_path)
            history = get_parsed_telemetry_history(100, db_path)
            coverage = get_telemetry_timestamps(
                start, start + timedelta(hours=1), db_path
            )

        self.assertEqual(latest["id"], 121)
        self.assertIn("diagnostic_only", latest["parsed"])
        self.assertEqual(len(history), 3)
        self.assertNotIn("diagnostic_only", history[0]["parsed"])
        self.assertEqual(len(coverage), 121)

    def test_migration_prunes_system_metrics_older_than_48_hours(self) -> None:
        start = datetime(2026, 7, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            for hours in (0, 24, 48, 49, 72):
                save_system_snapshot(
                    {"hours": hours},
                    db_path=db_path,
                    timestamp=start + timedelta(hours=hours),
                )

            result = migrate_compact_storage(db_path)
            with sqlite3.connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT data_json FROM system_snapshots ORDER BY timestamp"
                ).fetchall()

        self.assertEqual(result["system_rows_removed"], 1)
        self.assertTrue(result["vacuumed"])
        self.assertEqual([json.loads(row[0])["hours"] for row in rows], [24, 48, 49, 72])


if __name__ == "__main__":
    unittest.main()
