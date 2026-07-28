import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import DB_PATH


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def initialize_database(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS register_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                start_address INTEGER NOT NULL,
                registers_json TEXT NOT NULL
            )
            """
        )


def save_snapshot(
    registers: list[int],
    start_address: int,
    db_path: Path = DB_PATH,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO register_snapshots
                (timestamp, start_address, registers_json)
            VALUES (?, ?, ?)
            """,
            (timestamp, start_address, json.dumps(registers)),
        )


def get_latest_snapshot(db_path: Path = DB_PATH) -> Optional[dict]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, timestamp, start_address, registers_json
            FROM register_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    registers = json.loads(row["registers_json"])
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "start_address": row["start_address"],
        "registers": registers,
    }
