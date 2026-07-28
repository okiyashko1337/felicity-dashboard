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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("felicity.collector")
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

    logger.info("Collector started: %s, %s baud, slave %s", SERIAL_PORT, BAUDRATE, SLAVE_ID)
    try:
        while running:
            cycle_started = time.monotonic()
            try:
                if not client.connected and not client.connect():
                    raise ConnectionError(f"Cannot open {SERIAL_PORT}")

                response = client.read_holding_registers(
                    REGISTER_ADDRESS,
                    count=REGISTER_COUNT,
                    device_id=SLAVE_ID,
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
        logger.info("Collector stopped")


if __name__ == "__main__":
    main()

