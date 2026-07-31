#!/usr/bin/env python3
"""Store Raspberry Pi and database resource usage once per minute."""

import argparse
import logging
import os
import shutil
import signal
import time
from pathlib import Path
from typing import Optional

from config import DB_PATH
from database import initialize_database, save_system_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("felicity.system_monitor")
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def read_cpu_times() -> Optional[tuple[int, int]]:
    line = _read_text(Path("/proc/stat"))
    if not line:
        return None
    first_line = line.splitlines()[0].split()
    if not first_line or first_line[0] != "cpu":
        return None
    values = [int(value) for value in first_line[1:]]
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def read_cpu_percent(sample_seconds: float = 0.2) -> Optional[float]:
    before = read_cpu_times()
    if before is None:
        return None
    time.sleep(sample_seconds)
    after = read_cpu_times()
    if after is None:
        return None
    total_delta = after[0] - before[0]
    idle_delta = after[1] - before[1]
    if total_delta <= 0:
        return None
    return round(100 * (1 - idle_delta / total_delta), 1)


def read_memory() -> dict[str, Optional[float]]:
    text = _read_text(Path("/proc/meminfo"))
    if not text:
        return {"total_bytes": None, "used_bytes": None, "percent": None}
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, raw_value = line.partition(":")
        try:
            values[key] = int(raw_value.strip().split()[0]) * 1024
        except (IndexError, ValueError):
            continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return {"total_bytes": total, "used_bytes": None, "percent": None}
    used = total - available
    return {
        "total_bytes": total,
        "used_bytes": used,
        "percent": round(used / total * 100, 1),
    }


def read_temperature_c() -> Optional[float]:
    candidates = list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
    candidates.extend(Path("/sys/class/hwmon").glob("hwmon*/temp*_input"))
    for path in candidates:
        value = _read_text(path)
        if value is None:
            continue
        try:
            temperature = float(value)
        except ValueError:
            continue
        if temperature > 1000:
            temperature /= 1000
        if 0 < temperature < 120:
            return round(temperature, 1)
    return None


def database_size_bytes(db_path: Path) -> int:
    return sum(
        path.stat().st_size
        for path in (
            db_path,
            Path(f"{db_path}-wal"),
            Path(f"{db_path}-shm"),
        )
        if path.exists()
    )


def collect_system_metrics(db_path: Path = DB_PATH) -> dict:
    disk_path = db_path.parent if db_path.parent.exists() else Path("/")
    disk = shutil.disk_usage(disk_path)
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except (AttributeError, OSError):
        load_1m = load_5m = load_15m = None

    uptime_text = _read_text(Path("/proc/uptime"))
    try:
        uptime_seconds = round(float(uptime_text.split()[0])) if uptime_text else None
    except (IndexError, ValueError):
        uptime_seconds = None

    memory = read_memory()
    return {
        "cpu_percent": read_cpu_percent(),
        "load_average": {
            "1m": round(load_1m, 2) if load_1m is not None else None,
            "5m": round(load_5m, 2) if load_5m is not None else None,
            "15m": round(load_15m, 2) if load_15m is not None else None,
        },
        "memory": memory,
        "cpu_temperature_c": read_temperature_c(),
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "percent": round(disk.used / disk.total * 100, 1),
        },
        "database_size_bytes": database_size_bytes(db_path),
        "uptime_seconds": uptime_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    initialize_database(args.db)
    logger.info("System monitor started: every %.1f seconds", args.interval)

    while running:
        cycle_started = time.monotonic()
        metrics = collect_system_metrics(args.db)
        snapshot_id = save_system_snapshot(metrics, db_path=args.db)
        logger.info(
            "Saved system #%s: CPU=%s%% RAM=%s%% disk=%s%% DB=%s bytes",
            snapshot_id,
            metrics["cpu_percent"],
            metrics["memory"]["percent"],
            metrics["disk"]["percent"],
            metrics["database_size_bytes"],
        )
        if args.once:
            break
        elapsed = time.monotonic() - cycle_started
        time.sleep(max(0, args.interval - elapsed))

    logger.info("System monitor stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
