from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from config import DB_PATH, HISTORY_INTERVAL_SECONDS
from analytics import build_daily_aggregates, daily_increment


HISTORY_FIELDS = (
    "pv_power_w",
    "load_power_w",
    "grid_power_w",
    "grid_voltage_v",
    "battery_power_w",
    "soc_percent",
    "battery_voltage_v",
    "battery_current_a",
)
COVERAGE_RETENTION_DAYS = 3
SYSTEM_RETENTION_HOURS = 48


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def compact_telemetry(data: dict) -> dict:
    """Keep only fields used by history charts and energy analytics."""
    compact = {key: data[key] for key in HISTORY_FIELDS if key in data}
    batteries = data.get("batteries")
    if isinstance(batteries, list):
        compact["batteries"] = [
            {
                key: battery.get(key)
                for key in ("soc_percent", "current_a", "cell_delta_mv")
                if isinstance(battery, dict) and key in battery
            }
            for battery in batteries
            if isinstance(battery, dict)
        ]
    return compact


@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a transactional SQLite connection and always close it afterward."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=15)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                parsed_data_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_current (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                sequence INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
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
            CREATE TABLE IF NOT EXISTS telemetry_coverage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_coverage_timestamp
            ON telemetry_coverage(timestamp)
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


def migrate_compact_storage(db_path: Path = DB_PATH) -> dict:
    """Replace legacy two-second raw history with compact two-minute points."""
    initialize_database(db_path)
    with connect(db_path) as connection:
        legacy_raw = "raw_data_json" in {
            row["name"]
            for row in connection.execute("PRAGMA table_info(telemetry_snapshots)")
        }
    if legacy_raw:
        # Preserve exact historical energy totals while the dense legacy rows
        # are still available; compact history is intentionally chart-oriented.
        ensure_energy_daily(db_path)
    migrated = False
    before_rows = after_rows = 0
    system_rows_removed = 0
    with connect(db_path) as connection:
        latest_system = connection.execute(
            "SELECT timestamp FROM system_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if latest_system is not None:
            system_cutoff = datetime.fromisoformat(
                latest_system["timestamp"]
            ) - timedelta(hours=SYSTEM_RETENTION_HOURS)
            cursor = connection.execute(
                "DELETE FROM system_snapshots WHERE timestamp < ?",
                (system_cutoff.isoformat(),),
            )
            system_rows_removed = max(0, cursor.rowcount)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(telemetry_snapshots)")
        }
        latest = connection.execute(
            """
            SELECT id, timestamp, source, parsed_data_json
            FROM telemetry_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        current = connection.execute(
            "SELECT 1 FROM telemetry_current WHERE singleton = 1"
        ).fetchone()
        if current is None and latest is not None:
            connection.execute(
                """
                INSERT INTO telemetry_current
                    (singleton, sequence, timestamp, source, parsed_data_json)
                VALUES (1, ?, ?, ?, ?)
                """,
                (
                    latest["id"], latest["timestamp"], latest["source"],
                    latest["parsed_data_json"],
                ),
            )

        if "raw_data_json" in columns:
            before_rows = int(
                connection.execute("SELECT COUNT(*) FROM telemetry_snapshots").fetchone()[0]
            )
            if latest is not None:
                latest_timestamp = datetime.fromisoformat(latest["timestamp"])
                cutoff = latest_timestamp - timedelta(days=COVERAGE_RETENTION_DAYS)
                connection.execute("DELETE FROM telemetry_coverage")
                connection.execute(
                    """
                    INSERT INTO telemetry_coverage (timestamp)
                    SELECT timestamp
                    FROM telemetry_snapshots
                    WHERE timestamp >= ?
                    ORDER BY timestamp ASC, id ASC
                    """,
                    (cutoff.isoformat(),),
                )
            connection.execute("DROP TABLE IF EXISTS telemetry_snapshots_compact")
            connection.execute(
                """
                CREATE TABLE telemetry_snapshots_compact (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    parsed_data_json TEXT NOT NULL
                )
                """
            )
            rows = connection.execute(
                """
                SELECT id, timestamp, source, parsed_data_json
                FROM telemetry_snapshots
                ORDER BY timestamp ASC, id ASC
                """
            )
            last_kept: datetime | None = None
            for row in rows:
                timestamp = datetime.fromisoformat(row["timestamp"])
                if last_kept is not None and (
                    timestamp.astimezone(timezone.utc)
                    - last_kept.astimezone(timezone.utc)
                ).total_seconds() < HISTORY_INTERVAL_SECONDS:
                    continue
                parsed = json.loads(row["parsed_data_json"])
                connection.execute(
                    """
                    INSERT INTO telemetry_snapshots_compact
                        (id, timestamp, source, parsed_data_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        row["id"], row["timestamp"], row["source"],
                        _json_dump(compact_telemetry(parsed)),
                    ),
                )
                last_kept = timestamp
                after_rows += 1
            connection.execute("DROP TABLE telemetry_snapshots")
            connection.execute(
                "ALTER TABLE telemetry_snapshots_compact RENAME TO telemetry_snapshots"
            )
            connection.execute(
                """
                CREATE INDEX idx_telemetry_timestamp
                ON telemetry_snapshots(timestamp)
                """
            )
            connection.execute(
                """
                INSERT INTO dashboard_meta (key, value)
                VALUES ('compact_storage_v1', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (datetime.now(timezone.utc).isoformat(),),
            )
            migrated = True

    vacuumed = False
    if migrated or system_rows_removed:
        connection = sqlite3.connect(db_path, timeout=30)
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("VACUUM")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            vacuumed = True
        finally:
            connection.close()
    return {
        "migrated": migrated,
        "before_rows": before_rows,
        "after_rows": after_rows,
        "system_rows_removed": system_rows_removed,
        "vacuumed": vacuumed,
    }


def save_telemetry_snapshot(
    raw_data: object,
    parsed_data: dict,
    source: str,
    db_path: Path = DB_PATH,
    timestamp: Optional[datetime] = None,
) -> int:
    timestamp = timestamp or datetime.now(timezone.utc)
    with connect(db_path) as connection:
        current_row = connection.execute(
            """
            SELECT sequence, timestamp, parsed_data_json
            FROM telemetry_current
            WHERE singleton = 1
            """
        ).fetchone()
        if current_row is None:
            current_row = connection.execute(
                """
                SELECT id AS sequence, timestamp, parsed_data_json
                FROM telemetry_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        sequence = 1 if current_row is None else int(current_row["sequence"]) + 1
        previous = None if current_row is None else {
            "timestamp": current_row["timestamp"],
            "parsed": json.loads(current_row["parsed_data_json"]),
        }
        connection.execute(
            """
            INSERT INTO telemetry_current
                (singleton, sequence, timestamp, source, parsed_data_json)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                sequence = excluded.sequence,
                timestamp = excluded.timestamp,
                source = excluded.source,
                parsed_data_json = excluded.parsed_data_json
            """,
            (
                sequence,
                timestamp.isoformat(),
                source,
                _json_dump(parsed_data),
            ),
        )
        current = {"timestamp": timestamp.isoformat(), "parsed": parsed_data}
        _upsert_energy_daily(connection, daily_increment(previous, current))
        connection.execute(
            "INSERT INTO telemetry_coverage (timestamp) VALUES (?)",
            (timestamp.isoformat(),),
        )
        if sequence % 1800 == 0:
            cutoff = timestamp.astimezone(timezone.utc) - timedelta(
                days=COVERAGE_RETENTION_DAYS
            )
            connection.execute(
                "DELETE FROM telemetry_coverage WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )
        last_history = connection.execute(
            "SELECT timestamp FROM telemetry_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        should_store_history = last_history is None
        if last_history is not None:
            last_timestamp = datetime.fromisoformat(last_history["timestamp"])
            should_store_history = (
                timestamp.astimezone(timezone.utc)
                - last_timestamp.astimezone(timezone.utc)
            ).total_seconds() >= HISTORY_INTERVAL_SECONDS
        if should_store_history:
            connection.execute(
                """
                INSERT INTO telemetry_snapshots (timestamp, source, parsed_data_json)
                VALUES (?, ?, ?)
                """,
                (timestamp.isoformat(), source, _json_dump(compact_telemetry(parsed_data))),
            )
        return sequence


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
        existing = int(connection.execute("SELECT COUNT(*) FROM energy_daily").fetchone()[0])
        if existing:
            connection.execute(
                "INSERT INTO dashboard_meta (key, value) VALUES (?, ?)",
                ("energy_daily_backfill_v1", datetime.now(timezone.utc).isoformat()),
            )
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
        "parsed": json.loads(row["parsed_data_json"]),
    }


def get_latest_telemetry(db_path: Path = DB_PATH) -> Optional[dict]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT sequence AS id, timestamp, source, parsed_data_json
            FROM telemetry_current
            WHERE singleton = 1
            """
        ).fetchone()
        if row is None:
            row = connection.execute(
                """
                SELECT id, timestamp, source, parsed_data_json
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
            SELECT id, timestamp, source, parsed_data_json
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
            FROM telemetry_coverage
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
                    id, timestamp, source, parsed_data_json,
                    ROW_NUMBER() OVER (ORDER BY timestamp ASC, id ASC) AS row_number,
                    COUNT(*) OVER () AS total_count
                FROM telemetry_snapshots
                WHERE timestamp >= ? AND timestamp < ?
            )
            SELECT id, timestamp, source, parsed_data_json
            FROM ranked
            WHERE (row_number - 1) % ? = 0 OR row_number = total_count
            ORDER BY timestamp ASC, id ASC
            """,
            (start_utc, end_utc, stride),
        ).fetchall()
    return [serialize_telemetry_row(row) for row in rows]


def get_parsed_telemetry_range_sampled(
    start: datetime,
    end: datetime,
    max_points: int,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Evenly sample a range without reading large raw Modbus packets."""
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
                    id, timestamp, parsed_data_json,
                    ROW_NUMBER() OVER (ORDER BY timestamp ASC, id ASC) AS row_number,
                    COUNT(*) OVER () AS total_count
                FROM telemetry_snapshots
                WHERE timestamp >= ? AND timestamp < ?
            )
            SELECT timestamp, parsed_data_json
            FROM ranked
            WHERE (row_number - 1) % ? = 0 OR row_number = total_count
            ORDER BY timestamp ASC, id ASC
            """,
            (start_utc, end_utc, stride),
        ).fetchall()
    return [
        {"timestamp": row["timestamp"], "parsed": json.loads(row["parsed_data_json"])}
        for row in rows
    ]


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
            (timestamp.isoformat(), _json_dump(data)),
        )
        if int(cursor.lastrowid) % 360 == 0:
            cutoff = timestamp.astimezone(timezone.utc) - timedelta(
                hours=SYSTEM_RETENTION_HOURS
            )
            connection.execute(
                "DELETE FROM system_snapshots WHERE timestamp < ?",
                (cutoff.isoformat(),),
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
