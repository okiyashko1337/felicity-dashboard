#!/usr/bin/env python3
"""Poll the Felicity local Wi-Fi protocol and persist normalized telemetry."""

import argparse
import json
import logging
import signal
import sqlite3
import time
from pathlib import Path

from config import DB_PATH, FELICITY_HOST, FELICITY_PORT, POLL_INTERVAL_SECONDS
from database import initialize_database, save_telemetry_snapshot
from felicity_local import (
    FelicityLocalClient,
    FelicityProtocolError,
    parse_realtime_packets,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("felicity.local_collector")
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


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

    logger.info(
        "Local collector started: %s:%s every %.1f seconds",
        args.host,
        args.port,
        args.interval,
    )
    next_status_log = 0.0

    while running:
        cycle_started = time.monotonic()
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
            if args.once:
                break
        except (ConnectionError, OSError, FelicityProtocolError) as error:
            logger.error("Polling failed: %s", error)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            logger.exception("Cannot parse Felicity response: %s", error)
        except sqlite3.Error as error:
            logger.error("Telemetry database temporarily unavailable: %s", error)

        elapsed = time.monotonic() - cycle_started
        time.sleep(max(0, args.interval - elapsed))

    logger.info("Local collector stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
