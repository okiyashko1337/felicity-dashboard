#!/usr/bin/env python3
"""Run ESP32-C3 QEMU and bridge its UART1 to a physical Nextion on macOS."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import termios
import time


def prepare_flash_image(build: Path) -> None:
    flash = build / "qemu_flash.bin"
    inputs = (
        build / "bootloader/bootloader.bin",
        build / "partition_table/partition-table.bin",
        build / "felicity_esp32_client.bin",
    )
    for image in inputs:
        if not image.exists():
            raise FileNotFoundError(f"missing build image: {image}")
    if flash.exists() and flash.stat().st_mtime >= max(p.stat().st_mtime for p in inputs):
        return
    esptool = shutil.which("esptool")
    if not esptool:
        raise FileNotFoundError("esptool is not in PATH")
    subprocess.run(
        [
            esptool, "--chip=esp32c3", "merge-bin",
            f"--output={flash}", "--pad-to-size=4MB",
            "--flash-mode", "dio", "--flash-freq", "80m", "--flash-size", "4MB",
            "0x0", str(inputs[0]), "0x8000", str(inputs[1]),
            "0x10000", str(inputs[2]),
        ],
        check=True,
    )


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


def qemu_command(build: Path, socket_path: Path) -> list[str]:
    executable = shutil.which("qemu-system-riscv32")
    if not executable:
        raise FileNotFoundError("qemu-system-riscv32 is not in PATH")
    flash = build / "qemu_flash.bin"
    efuse = build / "qemu_efuse.bin"
    for image in (flash, efuse):
        if not image.exists():
            raise FileNotFoundError(f"missing QEMU image: {image}")
    return [
        executable,
        "-M", "esp32c3",
        "-drive", f"file={flash},if=mtd,format=raw",
        "-drive", f"file={efuse},if=none,format=raw,id=efuse",
        "-global", "driver=nvram.esp32c3.efuse,property=drive,value=efuse",
        "-global", "driver=timer.esp32c3.timg,property=wdt_disable,value=true",
        "-nic", "user,model=open_eth",
        "-nographic",
        "-serial", "mon:stdio",
        "-serial", f"unix:{socket_path},server=on,wait=off",
    ]


def connect_uart_socket(path: Path, process: subprocess.Popen[bytes]) -> socket.socket:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"QEMU exited with code {process.returncode}")
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(str(path))
            client.setblocking(False)
            return client
        except (FileNotFoundError, ConnectionRefusedError):
            client.close()
            time.sleep(0.05)
    raise TimeoutError("QEMU UART1 socket did not appear")


def bridge(port: str, baud: int, build: Path) -> int:
    prepare_flash_image(build)
    with tempfile.TemporaryDirectory(prefix="felicity-qemu-") as temporary:
        socket_path = Path(temporary) / "uart1.sock"
        physical = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        configure_uart(physical, baud)
        process = subprocess.Popen(qemu_command(build, socket_path))
        virtual: socket.socket | None = None
        display_bytes = touch_bytes = 0
        try:
            virtual = connect_uart_socket(socket_path, process)
            print(
                f"Bidirectional Nextion bridge: {port} <-> QEMU UART1 at {baud}",
                file=sys.stderr,
                flush=True,
            )
            while process.poll() is None:
                readable, _, _ = select.select([physical, virtual], [], [], 0.1)
                if virtual in readable:
                    payload = virtual.recv(4096)
                    if not payload:
                        break
                    os.write(physical, payload)
                    time.sleep(len(payload) * 10 / baud)
                    display_bytes += len(payload)
                if physical in readable:
                    payload = os.read(physical, 4096)
                    if payload:
                        virtual.sendall(payload)
                        touch_bytes += len(payload)
                        print(
                            f"Touch UART: {payload.hex(' ')}",
                            file=sys.stderr,
                            flush=True,
                        )
        finally:
            if virtual is not None:
                virtual.close()
            os.close(physical)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            print(
                f"Bridge stopped: display={display_bytes} bytes, touch={touch_bytes} bytes",
                file=sys.stderr,
                flush=True,
            )
        return process.returncode or 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="macOS /dev/cu.* USB-UART device")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--build", type=Path, default=Path("build-qemu-live"))
    arguments = parser.parse_args()
    return bridge(arguments.port, arguments.baud, arguments.build.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
