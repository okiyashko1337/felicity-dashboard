"""Client and parser for the Felicity Wi-Fi module local TCP protocol."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from config import (
    FELICITY_COMMAND,
    FELICITY_CONNECT_TIMEOUT_SECONDS,
    FELICITY_HOST,
    FELICITY_PORT,
    FELICITY_READ_TIMEOUT_SECONDS,
)


class FelicityProtocolError(RuntimeError):
    """Raised when the local module returns an incomplete or unexpected reply."""


def decode_json_stream(payload: str) -> list[dict[str, Any]]:
    """Decode concatenated JSON objects returned without separators."""
    decoder = json.JSONDecoder()
    documents: list[dict[str, Any]] = []
    position = 0

    while position < len(payload):
        while position < len(payload) and payload[position].isspace():
            position += 1
        if position >= len(payload):
            break

        try:
            document, position = decoder.raw_decode(payload, position)
        except json.JSONDecodeError as error:
            remainder = payload[position : position + 120]
            raise FelicityProtocolError(
                f"Incomplete JSON response near {remainder!r}"
            ) from error

        if not isinstance(document, dict):
            raise FelicityProtocolError("Expected JSON objects from Felicity module")
        documents.append(document)

    if not documents:
        raise FelicityProtocolError("Felicity module returned no JSON objects")
    return documents


@dataclass(frozen=True)
class FelicityLocalClient:
    host: str = FELICITY_HOST
    port: int = FELICITY_PORT
    connect_timeout: float = FELICITY_CONNECT_TIMEOUT_SECONDS
    read_timeout: float = FELICITY_READ_TIMEOUT_SECONDS

    def request(self, command: str = FELICITY_COMMAND) -> list[dict[str, Any]]:
        """Send one read-only local-monitor request and return all JSON packets."""
        chunks: list[bytes] = []
        with socket.create_connection(
            (self.host, self.port), timeout=self.connect_timeout
        ) as connection:
            connection.settimeout(self.read_timeout)
            connection.sendall(command.encode("ascii"))

            while True:
                try:
                    chunk = connection.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                chunks.append(chunk)

        if not chunks:
            raise FelicityProtocolError("Felicity module returned an empty response")
        return decode_json_stream(b"".join(chunks).decode("utf-8"))


def _number(value: Any, default: float = 0.0) -> float:
    return default if value is None else float(value)


def _array_value(data: Any, *indexes: int, default: Any = 0) -> Any:
    current = data
    try:
        for index in indexes:
            current = current[index]
    except (IndexError, KeyError, TypeError):
        return default
    return default if current is None else current


def _scaled_phase_values(data: Any, scale: float) -> dict[str, float]:
    return {
        "l1": round(_number(_array_value(data, 0)) / scale, 3),
        "l2": round(_number(_array_value(data, 1)) / scale, 3),
        "l3": round(_number(_array_value(data, 2)) / scale, 3),
    }


def _has_nonzero(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_has_nonzero(item) for item in value)
    if isinstance(value, dict):
        return any(_has_nonzero(item) for item in value.values())
    return bool(value)


def _parse_device_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return value


def _parse_bms(packet: dict[str, Any]) -> dict[str, Any]:
    voltage_v = _number(_array_value(packet.get("BattList"), 0, 0)) / 1000
    current_a = _number(_array_value(packet.get("BattList"), 1, 0)) / 10
    soc_percent = _number(_array_value(packet.get("BatsocList"), 0, 0)) / 100
    soh_percent = _number(_array_value(packet.get("BatsocList"), 0, 1)) / 10
    capacity_ah = _number(_array_value(packet.get("BatsocList"), 0, 2)) / 1000
    max_cell_voltage_v = _number(_array_value(packet.get("BMaxMin"), 0, 0)) / 1000
    min_cell_voltage_v = _number(_array_value(packet.get("BMaxMin"), 0, 1)) / 1000

    return {
        "serial": packet.get("DevSN"),
        "mod_address": packet.get("ModAddr"),
        "voltage_v": round(voltage_v, 3),
        "current_a": round(current_a, 1),
        "power_w": round(voltage_v * current_a),
        "soc_percent": round(soc_percent, 2),
        "soh_percent": round(soh_percent, 1),
        "capacity_ah": round(capacity_ah, 1),
        "temperature_c": {
            "max": round(
                _number(_array_value(packet.get("Templist"), 0, 0)) / 10, 1
            ),
            "min": round(
                _number(_array_value(packet.get("Templist"), 0, 1)) / 10, 1
            ),
        },
        "cell_voltage_v": {
            "max": round(max_cell_voltage_v, 3),
            "min": round(min_cell_voltage_v, 3),
            "max_cell": _array_value(packet.get("BMaxMin"), 1, 0, default=None),
            "min_cell": _array_value(packet.get("BMaxMin"), 1, 1, default=None),
        },
        "cell_delta_mv": round(
            (max_cell_voltage_v - min_cell_voltage_v) * 1000, 1
        ),
        "fault": packet.get("BBfault", 0),
        "warning": packet.get("BBwarn", 0),
        "state": packet.get("Bstate"),
    }


def parse_realtime_packets(packets: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize one inverter packet and its optional BMS packets for the API."""
    inverter = next((packet for packet in packets if packet.get("Type") == 84), None)
    if inverter is None:
        raise FelicityProtocolError("Realtime response does not contain an inverter packet")

    bms_packets = sorted(
        (packet for packet in packets if packet.get("Type") == 112),
        key=lambda packet: packet.get("ModAddr", 0),
    )

    pv = inverter.get("PV", [])
    pv_channels = [
        round(_number(_array_value(pv, 2, index))) for index in range(4)
    ]
    pv1 = pv_channels[0]
    pv2 = pv_channels[1]
    pv_voltage_channels = [
        round(_number(_array_value(pv, 0, index)) / 10, 1) for index in range(4)
    ]
    pv_current_channels = [
        round(_number(_array_value(pv, 1, index)) / 10, 1) for index in range(4)
    ]

    home = inverter.get("Home", [])
    home_phases = {
        "l1": round(_number(_array_value(home, 1, 0)) * 10),
        "l2": round(_number(_array_value(home, 1, 1)) * 10),
        "l3": round(_number(_array_value(home, 1, 2)) * 10),
    }
    home_total = round(_number(_array_value(home, 0, 0)) * 10)
    if not home_total:
        home_total = sum(home_phases.values())

    grid_ct = inverter.get("GrCTPP", [])
    grid_phases = {
        "l1": round(_number(_array_value(grid_ct, 0, 0)) * 10),
        "l2": round(_number(_array_value(grid_ct, 0, 1)) * 10),
        "l3": round(_number(_array_value(grid_ct, 0, 2)) * 10),
    }
    grid_total = round(_number(_array_value(grid_ct, 2, 0)) * 10)
    if not grid_total:
        grid_total = sum(grid_phases.values())
    # CT measurements commonly wander a few watts around zero. Treat that as
    # no grid exchange so the UI does not alternate between import and export.
    if abs(grid_total) < 50:
        grid_total = 0

    battery_voltage_v = _number(
        _array_value(inverter.get("Batt2"), 0, 0)
    ) / 1000
    battery_current_a = _number(
        _array_value(inverter.get("Batt2"), 1, 0)
    ) / 10
    battery_power_w = round(_number(_array_value(inverter.get("Batt2"), 2, 0)))
    soc_percent = _number(
        _array_value(inverter.get("Batsoc2"), 0, 0)
    ) / 100
    soh_percent = _number(
        _array_value(inverter.get("Batsoc2"), 0, 1)
    ) / 10

    grid_voltage = _scaled_phase_values(
        _array_value(inverter.get("ACin"), 0, default=[]), 10
    )
    grid_current = _scaled_phase_values(
        _array_value(inverter.get("ACin"), 1, default=[]), 10
    )
    grid_frequency = _scaled_phase_values(
        _array_value(inverter.get("ACin"), 2, default=[]), 100
    )

    inverter_voltage = _scaled_phase_values(
        _array_value(inverter.get("INV"), 0, default=[]), 10
    )
    inverter_current = _scaled_phase_values(
        _array_value(inverter.get("INV"), 1, default=[]), 10
    )
    inverter_phase_power = _scaled_phase_values(
        _array_value(inverter.get("INV"), 4, default=[]), 1
    )
    backup_voltage = _scaled_phase_values(
        _array_value(inverter.get("ACout"), 0, default=[]), 10
    )
    backup_current = _scaled_phase_values(
        _array_value(inverter.get("ACout"), 1, default=[]), 10
    )
    backup_phase_power = _scaled_phase_values(
        _array_value(inverter.get("ACout"), 4, default=[]), 1
    )

    return {
        "source": "felicity_local_wifi",
        "device": {
            "serial": inverter.get("DevSN"),
            "type": inverter.get("Type"),
            "subtype": inverter.get("SubType"),
            "work_mode": inverter.get("workM"),
            "device_timestamp": _parse_device_timestamp(inverter.get("date")),
        },
        "healthy": not _has_nonzero(
            [inverter.get("warn", 0), inverter.get("faulS", [])]
        ),
        "warning": inverter.get("warn", 0),
        "faults": inverter.get("faulS", []),
        "pv_power_w": {
            "pv1": pv1,
            "pv2": pv2,
            "channels": pv_channels,
            "total": sum(pv_channels),
        },
        "pv_voltage_v": {
            "mppt1": pv_voltage_channels[0],
            "mppt2": pv_voltage_channels[1],
            "channels": pv_voltage_channels,
        },
        "pv_current_a": {
            "mppt1": pv_current_channels[0],
            "mppt2": pv_current_channels[1],
            "channels": pv_current_channels,
        },
        "load_power_w": {**home_phases, "total": home_total},
        "grid_power_w": {**grid_phases, "total": grid_total},
        "grid_voltage_v": grid_voltage,
        "grid_current_a": grid_current,
        "grid_frequency_by_phase_hz": grid_frequency,
        "grid_frequency_hz": round(
            sum(grid_frequency.values()) / max(1, len(grid_frequency)), 2
        ),
        "inverter_voltage_v": inverter_voltage,
        "inverter_current_a": inverter_current,
        "inverter_power_w": {
            **inverter_phase_power,
            "total": round(_number(_array_value(inverter.get("INV"), 3, 0))),
        },
        "backup_voltage_v": backup_voltage,
        "backup_current_a": backup_current,
        "backup_power_w": {
            **backup_phase_power,
            "total": round(_number(_array_value(inverter.get("ACout"), 3, 0))),
        },
        "dc_bus_voltage_v": {
            "total": round(_number(inverter.get("busV")) / 10, 1),
            "positive": round(_number(inverter.get("busVp")) / 10, 1),
            "negative": round(_number(inverter.get("busVn")) / 10, 1),
        },
        "soc_percent": round(soc_percent, 2),
        "soh_percent": round(soh_percent, 1),
        "battery_voltage_v": round(battery_voltage_v, 3),
        "battery_current_a": round(battery_current_a, 1),
        "battery_power_w": battery_power_w,
        "battery_state": (
            "charging"
            if battery_power_w > 0
            else "discharging"
            if battery_power_w < 0
            else "idle"
        ),
        "temperature_c": {
            "inverter": round(
                _number(_array_value(inverter.get("Temp"), 0, 0)) / 10, 1
            ),
            "dc": round(
                _number(_array_value(inverter.get("Temp"), 0, 1)) / 10, 1
            ),
            "transformer": round(
                _number(_array_value(inverter.get("Temp"), 0, 2)) / 10, 1
            ),
        },
        "batteries": [_parse_bms(packet) for packet in bms_packets],
    }
