#!/usr/bin/env python3
"""Bridge a physical ESP32 Nextion TCP stream to a macOS USB-UART."""

from __future__ import annotations

import argparse
import os
import select
import socket
import sys
import termios
import time


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
    attributes[6][termios.VMIN] = 1
    attributes[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attributes)
    termios.tcflush(fd, termios.TCIOFLUSH)


def connect(host: str, port: int, timeout: float) -> socket.socket:
    deadline = time.monotonic() + timeout
    while True:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(min(1.0, max(0.1, deadline - time.monotonic())))
        try:
            client.connect((host, port))
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client.setblocking(False)
            return client
        except (ConnectionError, TimeoutError, OSError):
            client.close()
            if time.monotonic() >= deadline:
                raise TimeoutError(f"ESP32 bridge {host}:{port} did not answer")
            time.sleep(0.2)


def bridge(host: str, tcp_port: int, serial_port: str, baud: int) -> None:
    max_pending_display = 16 * 1024
    physical = os.open(serial_port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    client: socket.socket | None = None
    display_bytes = 0
    touch_bytes = 0
    try:
        configure_uart(physical, baud)
        client = connect(host, tcp_port, timeout=15)
        print(
            f"Nextion bridge: ESP32 {host}:{tcp_port} <-> {serial_port} at {baud}",
            file=sys.stderr,
            flush=True,
        )
        pending_display = bytearray()
        while True:
            writable = [physical] if pending_display else []
            readable = [physical]
            # Apply real UART backpressure to TCP instead of buffering an
            # entire graph in RAM. This mirrors a direct ESP32 UART link.
            if len(pending_display) < max_pending_display:
                readable.append(client)
            readable, writable, _ = select.select(
                readable, writable, [], 0.2
            )
            if client in readable:
                payload = client.recv(4096)
                if not payload:
                    raise ConnectionError("ESP32 closed the bridge")
                pending_display.extend(payload)
                display_bytes += len(payload)
            if physical in writable:
                try:
                    written = os.write(physical, pending_display[:4096])
                    del pending_display[:written]
                except BlockingIOError:
                    pass
            if physical in readable:
                payload = os.read(physical, 4096)
                if payload:
                    client.sendall(payload)
                    touch_bytes += len(payload)
                    print(f"Touch UART: {payload.hex(' ')}", file=sys.stderr,
                          flush=True)
    finally:
        if client is not None:
            client.close()
        os.close(physical)
        print(
            f"Bridge stopped: display={display_bytes} bytes, touch={touch_bytes} bytes",
            file=sys.stderr,
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="ESP32 Wi-Fi address")
    parser.add_argument("--tcp-port", type=int, default=2323)
    parser.add_argument("--serial", required=True, help="macOS /dev/cu.* FTDI port")
    parser.add_argument("--baud", type=int, default=115200)
    arguments = parser.parse_args()
    bridge(arguments.host, arguments.tcp_port, arguments.serial, arguments.baud)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
