#!/usr/bin/env python3
"""Read holding registers 0..100 from a Felicity IVGM inverter."""

import logging
import sys

from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

from modbus_compat import read_holding_registers

SERIAL_PORT = "/dev/ttyUSB0"
BAUDRATE = 9600
SLAVE_ID = 1
START_ADDRESS = 0
REGISTER_COUNT = 101  # Addresses 0 through 100, inclusive.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("felicity.register_scanner")


def main() -> int:
    client = ModbusSerialClient(
        port=SERIAL_PORT,
        baudrate=BAUDRATE,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=2,
        retries=2,
    )

    try:
        logger.info(
            "Connecting to %s: %s baud, 8N1, slave ID %s",
            SERIAL_PORT,
            BAUDRATE,
            SLAVE_ID,
        )
        if not client.connect():
            logger.error(
                "Could not open %s. Check the adapter, port name and dialout permissions.",
                SERIAL_PORT,
            )
            return 1

        response = read_holding_registers(
            client,
            START_ADDRESS,
            REGISTER_COUNT,
            SLAVE_ID,
        )

        if response.isError():
            logger.error("The inverter returned a Modbus error: %s", response)
            return 2

        if len(response.registers) != REGISTER_COUNT:
            logger.error(
                "Incomplete response: expected %s registers, received %s",
                REGISTER_COUNT,
                len(response.registers),
            )
            return 3

        print("Address | Decimal | Hex")
        print("--------+---------+------")
        for offset, value in enumerate(response.registers):
            address = START_ADDRESS + offset
            print(f"{address:7d} | {value:7d} | 0x{value:04X}")

        return 0

    except ModbusException as error:
        logger.error("Modbus communication error: %s", error)
        return 4
    except (OSError, IOError) as error:
        logger.error("Serial port error: %s", error)
        return 5
    except KeyboardInterrupt:
        logger.info("Scan interrupted by user")
        return 130
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
