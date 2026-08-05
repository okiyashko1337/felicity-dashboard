#!/usr/bin/env python3
"""Forward ESP32 QEMU ``NX>`` log commands to a physical Nextion UART."""

from __future__ import annotations

import argparse
import os
import sys
import termios
import time


TERMINATOR = b"\xff\xff\xff"


def configure_uart(fd: int, baud: int) -> None:
    speed = getattr(termios, f"B{baud}", None)
    if speed is None:
        raise ValueError(f"unsupported baud rate: {baud}")
    attributes = termios.tcgetattr(fd)
    attributes[0] = termios.IGNPAR
    attributes[1] = 0
    attributes[2] = termios.CS8 | termios.CLOCAL | termios.CREAD
    attributes[3] = 0
    attributes[4] = speed
    attributes[5] = speed
    attributes[6][termios.VMIN] = 0
    attributes[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attributes)
    termios.tcflush(fd, termios.TCIOFLUSH)


def command_from_log(line: bytes) -> bytes | None:
    marker = b"NX> "
    position = line.find(marker)
    if position < 0:
        return None
    command = line[position + len(marker) :].strip(b"\r\n")
    return command or None


def relay(port: str, baud: int) -> int:
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    forwarded = 0
    try:
        configure_uart(fd, baud)
        print(f"Nextion relay: {port} at {baud} baud", file=sys.stderr, flush=True)
        for line in sys.stdin.buffer:
            command = command_from_log(line)
            if command is None:
                continue
            payload = command + TERMINATOR
            os.write(fd, payload)
            # Pace QEMU at the physical UART wire rate (8-N-1 = 10 bits per
            # byte).  tcdrain() cannot be used here: some macOS FTDI drivers
            # wait indefinitely even though the bytes have already left.
            time.sleep(len(payload) * 10 / baud)
            forwarded += 1
            if forwarded % 250 == 0:
                print(f"Nextion relay: {forwarded} commands forwarded", file=sys.stderr,
                      flush=True)
    finally:
        os.close(fd)
        print(f"Nextion relay stopped: {forwarded} commands", file=sys.stderr, flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="macOS /dev/cu.* USB-UART device")
    parser.add_argument("--baud", type=int, default=115200)
    arguments = parser.parse_args()
    return relay(arguments.port, arguments.baud)


if __name__ == "__main__":
    raise SystemExit(main())
