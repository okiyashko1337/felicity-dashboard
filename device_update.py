"""Persistent update coordination for the ESP32-C3 Nextion controller."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


TARGETS = {
    "esp32": ("felicity-esp32.bin", "/api/device/firmware/esp32.bin"),
    "nextion": ("felicity-nextion.tft", "/api/device/firmware/nextion.tft"),
}
FINAL_STATES = {"complete", "error"}
REPORT_STATES = {"downloading", "installing", "restarting", *FINAL_STATES}
_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


@lru_cache(maxsize=8)
def _sha256(path: str, size: int, modified_ns: int) -> str:
    del size, modified_ns
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DeviceUpdateStore:
    def __init__(self, firmware_dir: Path, state_path: Path, version: str) -> None:
        self.firmware_dir = firmware_dir
        self.state_path = state_path
        self.version = version

    def firmware_path(self, target: str) -> Path:
        if target not in TARGETS:
            raise ValueError(f"Unknown firmware target: {target}")
        return self.firmware_dir / TARGETS[target][0]

    def firmware(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for target, (filename, download_url) in TARGETS.items():
            path = self.firmware_dir / filename
            if not path.is_file():
                result[target] = {"available": False}
                continue
            stat = path.stat()
            result[target] = {
                "available": True,
                "version": self.version,
                "size": stat.st_size,
                "sha256": _sha256(str(path.resolve()), stat.st_size, stat.st_mtime_ns),
                "download_url": download_url,
            }
        return result

    def snapshot(self) -> dict[str, Any]:
        with _lock:
            state = _read(self.state_path)
        return {
            "firmware": self.firmware(),
            "request": state.get("request"),
            "status": state.get("status", {"state": "idle", "progress_percent": 0}),
        }

    def request(self, target: str) -> dict[str, Any]:
        firmware = self.firmware()
        if target not in firmware:
            raise ValueError(f"Unknown firmware target: {target}")
        if not firmware[target].get("available"):
            raise FileNotFoundError(f"Firmware for {target} is not bundled")
        with _lock:
            state = _read(self.state_path)
            active = state.get("request")
            if isinstance(active, dict):
                raise RuntimeError("Another device update is already active")
            request = {
                "id": uuid.uuid4().hex,
                "target": target,
                "version": firmware[target]["version"],
                "requested_at": _utc_now(),
            }
            state = {
                "request": request,
                "status": {
                    "state": "queued",
                    "progress_percent": 0,
                    "target": target,
                    "request_id": request["id"],
                    "updated_at": _utc_now(),
                },
            }
            _atomic_write(self.state_path, state)
        return self.snapshot()

    def report(self, report: dict[str, Any]) -> dict[str, Any]:
        request_id = str(report.get("request_id", ""))
        target = str(report.get("target", ""))
        state_name = str(report.get("state", ""))
        if target not in TARGETS or not request_id or state_name not in REPORT_STATES:
            raise ValueError("Invalid device update report")
        progress = max(0, min(100, int(report.get("progress_percent", 0))))
        with _lock:
            state = _read(self.state_path)
            active = state.get("request")
            if not isinstance(active, dict) or active.get("id") != request_id:
                raise RuntimeError("Device update request is no longer active")
            if active.get("target") != target:
                raise RuntimeError("Device update target does not match the request")
            status = {
                "state": state_name,
                "progress_percent": progress,
                "target": target,
                "request_id": request_id,
                "device_version": str(report.get("device_version", "")),
                "message": str(report.get("message", ""))[:240],
                "updated_at": _utc_now(),
            }
            state["status"] = status
            if state_name in FINAL_STATES:
                state["request"] = None
            _atomic_write(self.state_path, state)
        return self.snapshot()

    def cancel(self) -> dict[str, Any]:
        """Cancel a queued or failed-to-start request without deleting artifacts."""
        with _lock:
            state = _read(self.state_path)
            active = state.get("request")
            if not isinstance(active, dict):
                return {
                    "firmware": self.firmware(),
                    "request": None,
                    "status": state.get("status", {"state": "idle", "progress_percent": 0}),
                }
            if state.get("status", {}).get("state") != "queued":
                raise RuntimeError("An update already in progress cannot be cancelled")
            state = {
                "request": None,
                "status": {
                    "state": "cancelled",
                    "progress_percent": 0,
                    "target": active.get("target"),
                    "request_id": active.get("id"),
                    "message": "Update request cancelled",
                    "updated_at": _utc_now(),
                },
            }
            _atomic_write(self.state_path, state)
        return self.snapshot()

    def confirm_running(self, device_version: str) -> dict[str, Any]:
        """Complete an ESP32 request after the newly booted image calls home."""
        with _lock:
            state = _read(self.state_path)
            active = state.get("request")
            if not isinstance(active, dict) or active.get("target") != "esp32":
                return {
                    "firmware": self.firmware(),
                    "request": state.get("request"),
                    "status": state.get("status", {"state": "idle", "progress_percent": 0}),
                }
            if str(active.get("version", "")) != device_version:
                raise RuntimeError("Running ESP32 version does not match the request")
            state = {
                "request": None,
                "status": {
                    "state": "complete",
                    "progress_percent": 100,
                    "target": "esp32",
                    "request_id": active["id"],
                    "device_version": device_version,
                    "message": "ESP32 rebooted into the verified image",
                    "updated_at": _utc_now(),
                },
            }
            _atomic_write(self.state_path, state)
        return self.snapshot()
