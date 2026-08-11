#!/usr/bin/env python3
"""Poll the Felicity local Wi-Fi protocol and persist normalized telemetry."""

import argparse
import json
import logging
import signal
import sqlite3
import time
from pathlib import Path

from config import (
    DB_PATH,
    FELICITY_HOST,
    FELICITY_MAX_RETRY_DELAY_SECONDS,
    FELICITY_PORT,
    POLL_INTERVAL_SECONDS,
)
from database import initialize_database, save_telemetry_anomaly, save_telemetry_snapshot
from felicity_local import (
    FelicityLocalClient,
    FelicityProtocolError,
    TelemetryAnomaly,
    parse_realtime_packets,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("felicity.local_collector")
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def retry_delay(interval: float, consecutive_failures: int) -> float:
    """Return a bounded exponential delay after a communication failure."""
    exponent = max(0, consecutive_failures - 1)
    return min(FELICITY_MAX_RETRY_DELAY_SECONDS, interval * (2**exponent))


def wait_until_next_cycle(seconds: float) -> None:
    """Sleep in short pieces so SIGTERM still stops the add-on promptly."""
    deadline = time.monotonic() + max(0.0, seconds)
    while running:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=FELICITY_HOST)
    parser.add_argument("--port", type=int, default=FELICITY_PORT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL_SECONDS)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read and save one snapshot, then exit",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    initialize_database(args.db)
    client = FelicityLocalClient(host=args.host, port=args.port)
    interval = args.interval

    logger.info(
        "Local collector started: %s:%s every %.1f seconds",
        args.host,
        args.port,
        interval,
    )
    next_status_log = 0.0
    consecutive_failures = 0
    exit_code = 0

    while running:
        cycle_started = time.monotonic()
        cycle_delay = interval
        packets: list[dict[str, object]] = []
        try:
            packets = client.request()
            parsed = parse_realtime_packets(packets)
            snapshot_id = save_telemetry_snapshot(
                raw_data=packets,
                parsed_data=parsed,
                source="felicity_local_wifi",
                db_path=args.db,
            )
            if args.once or cycle_started >= next_status_log:
                logger.info(
                    "Saved #%s: PV=%s W, home=%s W, battery=%s W, SOC=%s%%, grid=%s W",
                    snapshot_id,
                    parsed["pv_power_w"]["total"],
                    parsed["load_power_w"]["total"],
                    parsed["battery_power_w"],
                    parsed["soc_percent"],
                    parsed["grid_power_w"]["total"],
                )
                next_status_log = cycle_started + 60
            if consecutive_failures:
                logger.info(
                    "Felicity Wi-Fi communication recovered after %s failed poll(s)",
                    consecutive_failures,
                )
            consecutive_failures = 0
            if args.once:
                break
        except TelemetryAnomaly as error:
            consecutive_failures = 0
            anomaly_id = save_telemetry_anomaly(
                raw_data=packets,
                reason=error.reason,
                details=error.details,
                db_path=args.db,
            )
            logger.warning(
                "Rejected anomaly #%s: %s %s",
                anomaly_id,
                error.reason,
                error.details,
            )
            if args.once:
                exit_code = 2
                break
        except (
            ConnectionError,
            OSError,
            FelicityProtocolError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            consecutive_failures += 1
            cycle_delay = retry_delay(interval, consecutive_failures)
            logger.error(
                "Felicity Wi-Fi poll failed (%s consecutive); retry in %.1fs: %s",
                consecutive_failures,
                cycle_delay,
                error,
            )
            if args.once:
                exit_code = 1
                break
        except sqlite3.Error as error:
            logger.error("Telemetry database temporarily unavailable: %s", error)
            if args.once:
                exit_code = 3
                break

        elapsed = time.monotonic() - cycle_started
        wait_until_next_cycle(cycle_delay - elapsed)

    logger.info("Local collector stopped")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
