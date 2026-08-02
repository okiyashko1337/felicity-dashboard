from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from config import DB_PATH
from analytics import build_daily_aggregates, daily_increment


@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a transactional SQLite connection and always close it afterward."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                raw_data_json TEXT NOT NULL,
                parsed_data_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS energy_daily (
                day TEXT PRIMARY KEY,
                pv_wh REAL NOT NULL DEFAULT 0,
                load_wh REAL NOT NULL DEFAULT 0,
                grid_import_wh REAL NOT NULL DEFAULT 0,
                grid_export_wh REAL NOT NULL DEFAULT 0,
                battery_charge_wh REAL NOT NULL DEFAULT 0,
                battery_discharge_wh REAL NOT NULL DEFAULT 0,
                integrated_seconds REAL NOT NULL DEFAULT 0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                soc_start_percent REAL,
                soc_end_percent REAL,
                soc_min_percent REAL,
                soc_max_percent REAL,
                first_timestamp TEXT,
                last_timestamp TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp
            ON telemetry_snapshots(timestamp)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS system_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                data_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_system_timestamp
            ON system_snapshots(timestamp)
            """
        )
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


def save_telemetry_snapshot(
    raw_data: object,
    parsed_data: dict,
    source: str,
    db_path: Path = DB_PATH,
    timestamp: Optional[datetime] = None,
) -> int:
    timestamp = timestamp or datetime.now(timezone.utc)
    with connect(db_path) as connection:
        previous_row = connection.execute(
            """
            SELECT timestamp, parsed_data_json
            FROM telemetry_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        cursor = connection.execute(
            """
            INSERT INTO telemetry_snapshots
                (timestamp, source, raw_data_json, parsed_data_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                timestamp.isoformat(),
                source,
                json.dumps(raw_data, ensure_ascii=False),
                json.dumps(parsed_data, ensure_ascii=False),
            ),
        )
        previous = None if previous_row is None else {
            "timestamp": previous_row["timestamp"],
            "parsed": json.loads(previous_row["parsed_data_json"]),
        }
        current = {"timestamp": timestamp.isoformat(), "parsed": parsed_data}
        _upsert_energy_daily(connection, daily_increment(previous, current))
        return int(cursor.lastrowid)


def _upsert_energy_daily(connection: sqlite3.Connection, data: dict) -> None:
    connection.execute(
        """
        INSERT INTO energy_daily (
            day, pv_wh, load_wh, grid_import_wh, grid_export_wh,
            battery_charge_wh, battery_discharge_wh, integrated_seconds,
            sample_count, soc_start_percent, soc_end_percent,
            soc_min_percent, soc_max_percent, first_timestamp, last_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(day) DO UPDATE SET
            pv_wh = energy_daily.pv_wh + excluded.pv_wh,
            load_wh = energy_daily.load_wh + excluded.load_wh,
            grid_import_wh = energy_daily.grid_import_wh + excluded.grid_import_wh,
            grid_export_wh = energy_daily.grid_export_wh + excluded.grid_export_wh,
            battery_charge_wh = energy_daily.battery_charge_wh + excluded.battery_charge_wh,
            battery_discharge_wh = energy_daily.battery_discharge_wh + excluded.battery_discharge_wh,
            integrated_seconds = energy_daily.integrated_seconds + excluded.integrated_seconds,
            sample_count = energy_daily.sample_count + excluded.sample_count,
            soc_start_percent = COALESCE(energy_daily.soc_start_percent, excluded.soc_start_percent),
            soc_end_percent = excluded.soc_end_percent,
            soc_min_percent = CASE
                WHEN energy_daily.soc_min_percent IS NULL THEN excluded.soc_min_percent
                WHEN excluded.soc_min_percent IS NULL THEN energy_daily.soc_min_percent
                ELSE MIN(energy_daily.soc_min_percent, excluded.soc_min_percent)
            END,
            soc_max_percent = CASE
                WHEN energy_daily.soc_max_percent IS NULL THEN excluded.soc_max_percent
                WHEN excluded.soc_max_percent IS NULL THEN energy_daily.soc_max_percent
                ELSE MAX(energy_daily.soc_max_percent, excluded.soc_max_percent)
            END,
            first_timestamp = COALESCE(energy_daily.first_timestamp, excluded.first_timestamp),
            last_timestamp = excluded.last_timestamp
        """,
        (
            data["day"], data["pv_wh"], data["load_wh"],
            data["grid_import_wh"], data["grid_export_wh"],
            data["battery_charge_wh"], data["battery_discharge_wh"],
            data["integrated_seconds"], data["sample_count"],
            data["soc_start_percent"], data["soc_end_percent"],
            data["soc_min_percent"], data["soc_max_percent"],
            data["first_timestamp"], data["last_timestamp"],
        ),
    )


def ensure_energy_daily(db_path: Path = DB_PATH) -> None:
    """Backfill daily aggregates once for databases created before v0.4."""
    with connect(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        migration = connection.execute(
            "SELECT value FROM dashboard_meta WHERE key = ?",
            ("energy_daily_backfill_v1",),
        ).fetchone()
        if migration is not None:
            return
        connection.execute("DELETE FROM energy_daily")
        rows = connection.execute(
            """
            SELECT timestamp, parsed_data_json
            FROM telemetry_snapshots
            ORDER BY timestamp ASC, id ASC
            """
        ).fetchall()
        telemetry = [
            {"timestamp": row["timestamp"], "parsed": json.loads(row["parsed_data_json"])}
            for row in rows
        ]
        for aggregate in build_daily_aggregates(telemetry):
            _upsert_energy_daily(connection, aggregate)
        connection.execute(
            "INSERT INTO dashboard_meta (key, value) VALUES (?, ?)",
            ("energy_daily_backfill_v1", datetime.now(timezone.utc).isoformat()),
        )


def get_energy_daily(
    start_day: str | None = None,
    end_day: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    clauses = []
    parameters: list[str] = []
    if start_day is not None:
        clauses.append("day >= ?")
        parameters.append(start_day)
    if end_day is not None:
        clauses.append("day < ?")
        parameters.append(end_day)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM energy_daily {where} ORDER BY day ASC",
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def serialize_telemetry_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "source": row["source"],
        "raw": json.loads(row["raw_data_json"]),
        "parsed": json.loads(row["parsed_data_json"]),
    }


def get_latest_telemetry(db_path: Path = DB_PATH) -> Optional[dict]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, timestamp, source, raw_data_json, parsed_data_json
            FROM telemetry_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return serialize_telemetry_row(row) if row is not None else None


def get_telemetry_history(
    limit: int,
    db_path: Path = DB_PATH,
) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, timestamp, source, raw_data_json, parsed_data_json
            FROM telemetry_snapshots
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [serialize_telemetry_row(row) for row in reversed(rows)]


def get_parsed_telemetry_history(
    limit: int,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Return recent telemetry without the large raw inverter packets."""
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT timestamp, parsed_data_json
            FROM telemetry_snapshots
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "timestamp": row["timestamp"],
            "parsed": json.loads(row["parsed_data_json"]),
        }
        for row in reversed(rows)
    ]


def get_telemetry_timestamps(
    start: datetime,
    end: datetime,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Return only timestamps for inexpensive coverage-gap analysis."""
    start_utc = start.astimezone(timezone.utc).isoformat()
    end_utc = end.astimezone(timezone.utc).isoformat()
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT timestamp
            FROM telemetry_snapshots
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC, id ASC
            """,
            (start_utc, end_utc),
        ).fetchall()
    return [{"timestamp": row["timestamp"]} for row in rows]


def get_telemetry_range(
    start: datetime,
    end: datetime,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Return parsed telemetry in a half-open UTC time range."""
    start_utc = start.astimezone(timezone.utc).isoformat()
    end_utc = end.astimezone(timezone.utc).isoformat()
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, timestamp, source, parsed_data_json
            FROM telemetry_snapshots
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC, id ASC
            """,
            (start_utc, end_utc),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "source": row["source"],
            "parsed": json.loads(row["parsed_data_json"]),
        }
        for row in rows
    ]


def get_telemetry_range_sampled(
    start: datetime,
    end: datetime,
    max_points: int,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Return an evenly sampled telemetry range without loading every row."""
    start_utc = start.astimezone(timezone.utc).isoformat()
    end_utc = end.astimezone(timezone.utc).isoformat()
    with connect(db_path) as connection:
        total = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM telemetry_snapshots
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (start_utc, end_utc),
            ).fetchone()[0]
        )
        if total == 0:
            return []
        stride = max(1, math.ceil((total - 1) / max(1, max_points - 1)))
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT
                    id, timestamp, source, raw_data_json, parsed_data_json,
                    ROW_NUMBER() OVER (ORDER BY timestamp ASC, id ASC) AS row_number,
                    COUNT(*) OVER () AS total_count
                FROM telemetry_snapshots
                WHERE timestamp >= ? AND timestamp < ?
            )
            SELECT id, timestamp, source, raw_data_json, parsed_data_json
            FROM ranked
            WHERE (row_number - 1) % ? = 0 OR row_number = total_count
            ORDER BY timestamp ASC, id ASC
            """,
            (start_utc, end_utc, stride),
        ).fetchall()
    return [serialize_telemetry_row(row) for row in rows]


def save_system_snapshot(
    data: dict,
    db_path: Path = DB_PATH,
    timestamp: Optional[datetime] = None,
) -> int:
    timestamp = timestamp or datetime.now(timezone.utc)
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO system_snapshots (timestamp, data_json)
            VALUES (?, ?)
            """,
            (timestamp.isoformat(), json.dumps(data, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)


def _serialize_system_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "data": json.loads(row["data_json"]),
    }


def get_latest_system_snapshot(db_path: Path = DB_PATH) -> Optional[dict]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, timestamp, data_json
            FROM system_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return _serialize_system_row(row) if row is not None else None


def get_system_history(limit: int, db_path: Path = DB_PATH) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, timestamp, data_json
            FROM system_snapshots
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_serialize_system_row(row) for row in reversed(rows)]


def get_system_range(
    start: datetime,
    end: datetime,
    max_points: int,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Return evenly sampled Raspberry Pi metrics for a time range."""
    start_utc = start.astimezone(timezone.utc).isoformat()
    end_utc = end.astimezone(timezone.utc).isoformat()
    with connect(db_path) as connection:
        total = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM system_snapshots
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (start_utc, end_utc),
            ).fetchone()[0]
        )
        if total == 0:
            return []
        stride = max(1, math.ceil((total - 1) / max(1, max_points - 1)))
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT
                    id, timestamp, data_json,
                    ROW_NUMBER() OVER (ORDER BY timestamp ASC, id ASC) AS row_number,
                    COUNT(*) OVER () AS total_count
                FROM system_snapshots
                WHERE timestamp >= ? AND timestamp < ?
            )
            SELECT id, timestamp, data_json
            FROM ranked
            WHERE (row_number - 1) % ? = 0 OR row_number = total_count
            ORDER BY timestamp ASC, id ASC
            """,
            (start_utc, end_utc, stride),
        ).fetchall()
    return [_serialize_system_row(row) for row in rows]


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
