import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from database import (
    get_latest_system_snapshot,
    get_system_history,
    initialize_database,
    save_system_snapshot,
)
from system_monitor import collect_system_metrics, database_size_bytes


class SystemMonitorTests(unittest.TestCase):
    def test_collects_storage_and_database_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            metrics = collect_system_metrics(db_path)

        self.assertGreater(metrics["disk"]["total_bytes"], 0)
        self.assertGreater(metrics["database_size_bytes"], 0)
        self.assertIn("percent", metrics["memory"])
        self.assertIn("1m", metrics["load_average"])

    def test_system_database_round_trip(self) -> None:
        data = {
            "cpu_percent": 12.5,
            "memory": {"percent": 31.2},
            "disk": {"percent": 20.0},
            "database_size_bytes": 4096,
        }
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            row_id = save_system_snapshot(
                data,
                db_path=db_path,
                timestamp=datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc),
            )
            latest = get_latest_system_snapshot(db_path)
            history = get_system_history(10, db_path)

        self.assertEqual(row_id, 1)
        self.assertEqual(latest["data"], data)
        self.assertEqual(history, [latest])

    def test_database_size_includes_wal_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            db_path.write_bytes(b"db")
            Path(f"{db_path}-wal").write_bytes(b"wal")
            Path(f"{db_path}-shm").write_bytes(b"shm!")
            self.assertEqual(database_size_bytes(db_path), 9)


if __name__ == "__main__":
    unittest.main()
