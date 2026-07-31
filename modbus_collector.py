"""Legacy Modbus RTU collector kept for future hardware diagnostics."""

import logging
import signal
import time

from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

from config import (
    BAUDRATE,
    POLL_INTERVAL_SECONDS,
    REGISTER_ADDRESS,
    REGISTER_COUNT,
    SERIAL_PORT,
    SLAVE_ID,
)
from database import initialize_database, save_snapshot
from modbus_compat import read_holding_registers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("felicity.modbus_collector")
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    initialize_database()

    client = ModbusSerialClient(
        port=SERIAL_PORT,
        baudrate=BAUDRATE,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=1,
        retries=2,
    )

    logger.info(
        "Modbus collector started: %s, %s baud, slave %s",
        SERIAL_PORT,
        BAUDRATE,
        SLAVE_ID,
    )
    try:
        while running:
            cycle_started = time.monotonic()
            try:
                if not client.connected and not client.connect():
                    raise ConnectionError(f"Cannot open {SERIAL_PORT}")

                response = read_holding_registers(
                    client,
                    REGISTER_ADDRESS,
                    REGISTER_COUNT,
                    SLAVE_ID,
                )
                if response.isError():
                    raise ModbusException(f"Modbus error: {response}")

                save_snapshot(response.registers, REGISTER_ADDRESS)
                logger.info("Saved registers: %s", response.registers)
            except (ModbusException, ConnectionError, OSError) as error:
                logger.error("Polling failed: %s", error)
                client.close()

            elapsed = time.monotonic() - cycle_started
            time.sleep(max(0, POLL_INTERVAL_SECONDS - elapsed))
    finally:
        client.close()
        logger.info("Modbus collector stopped")


if __name__ == "__main__":
    main()
