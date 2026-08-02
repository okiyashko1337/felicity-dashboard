#!/usr/bin/env python3
"""Run exclusive storage migrations before dashboard services start."""

import logging
import sqlite3

from config import DB_PATH
from database import migrate_compact_storage


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("felicity.storage_migration")


def main() -> int:
    try:
        result = migrate_compact_storage(DB_PATH)
    except sqlite3.Error as error:
        logger.exception("Storage migration failed: %s", error)
        return 1
    if result["migrated"] or result["system_rows_removed"]:
        logger.info(
            "Compacted telemetry history: %s -> %s rows; removed system=%s; vacuum=%s",
            result["before_rows"],
            result["after_rows"],
            result["system_rows_removed"],
            result["vacuumed"],
        )
    else:
        logger.info("Compact telemetry storage is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
