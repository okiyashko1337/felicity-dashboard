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
    FELICITY_EXPECTED_BMS_PACKETS,
    FELICITY_HOST,
    FELICITY_MAX_RESPONSE_BYTES,
    FELICITY_PORT,
    FELICITY_READ_TIMEOUT_SECONDS,
)


FELICITY_RESPONSE_ACK = b"."
FELICITY_CLOSE_TIMEOUT_SECONDS = 0.25


INVERTER_WARNING_MESSAGES = {
    2: "низкое напряжение батареи",
    3: "низкий SOC батареи",
    15: "ограничение мощности: перегрев радиатора",
    16: "ограничение мощности: внутренний перегрев",
    17: "ошибка связи AFCI",
    18: "неисправность внешнего вентилятора",
    22: "неисправность внутреннего вентилятора",
    23: "ошибка связи счётчика",
    24: "обратное направление внешнего датчика CT",
    26: "несовпадение версий ПО и оборудования",
}


class FelicityProtocolError(RuntimeError):
    """Raised when the local module returns an incomplete or unexpected reply."""


class TelemetryAnomaly(FelicityProtocolError):
    """Raised when a reply is valid JSON but not a trustworthy telemetry frame."""

    def __init__(self, reason: str, details: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details


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
    expected_bms_packets: int = FELICITY_EXPECTED_BMS_PACKETS
    max_response_bytes: int = FELICITY_MAX_RESPONSE_BYTES

    def request(self, command: str = FELICITY_COMMAND) -> list[dict[str, Any]]:
        """Send one read-only local-monitor request and return all JSON packets."""
        response = bytearray()
        complete_packets: list[dict[str, Any]] | None = None
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
                response.extend(chunk)
                if len(response) > self.max_response_bytes:
                    raise FelicityProtocolError(
                        "Felicity response exceeded the safe size limit"
                    )

                if command == FELICITY_COMMAND:
                    complete_packets = _try_complete_realtime_response(
                        response,
                        self.expected_bms_packets,
                    )
                    if complete_packets is not None:
                        break

            if not response:
                raise FelicityProtocolError("Felicity module returned an empty response")

            if complete_packets is None:
                try:
                    packets = decode_json_stream(response.decode("utf-8"))
                except UnicodeDecodeError as error:
                    raise FelicityProtocolError(
                        "Felicity module returned invalid UTF-8"
                    ) from error
                if command == FELICITY_COMMAND:
                    _validate_complete_realtime_response(
                        packets,
                        self.expected_bms_packets,
                    )
            else:
                packets = complete_packets

            # Only a decoded inverter+BMS response is acknowledged as complete.
            # An empty, truncated or partial response is closed without an ACK.
            if command == FELICITY_COMMAND:
                self._finish_complete_session(connection)

        return packets

    @staticmethod
    def _finish_complete_session(connection: socket.socket) -> None:
        """Acknowledge one complete reply, half-close, then drain peer shutdown."""
        try:
            connection.sendall(FELICITY_RESPONSE_ACK)
        except OSError:
            return

        try:
            connection.shutdown(socket.SHUT_WR)
        except OSError:
            return

        try:
            connection.settimeout(FELICITY_CLOSE_TIMEOUT_SECONDS)
            while connection.recv(4096):
                pass
        except (OSError, socket.timeout):
            pass


def _validate_complete_realtime_response(
    packets: list[dict[str, Any]],
    expected_bms_packets: int,
) -> None:
    inverter_count = sum(packet.get("Type") == 84 for packet in packets)
    bms_addresses = {
        packet.get("ModAddr")
        for packet in packets
        if packet.get("Type") == 112 and packet.get("ModAddr") is not None
    }
    if inverter_count < 1 or len(bms_addresses) < expected_bms_packets:
        raise FelicityProtocolError(
            "Incomplete realtime response: "
            f"inverter packets={inverter_count}, "
            f"BMS packets={len(bms_addresses)}/{expected_bms_packets}"
        )


def _try_complete_realtime_response(
    response: bytes | bytearray,
    expected_bms_packets: int,
) -> list[dict[str, Any]] | None:
    try:
        packets = decode_json_stream(bytes(response).decode("utf-8"))
        _validate_complete_realtime_response(packets, expected_bms_packets)
    except (UnicodeDecodeError, FelicityProtocolError):
        return None
    return packets


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


def _has_shape(value: Any, rows: dict[int, int]) -> bool:
    if not isinstance(value, list):
        return False
    for row, minimum_length in rows.items():
        if row >= len(value) or not isinstance(value[row], list):
            return False
        if len(value[row]) < minimum_length:
            return False
        if any(not isinstance(item, (int, float)) for item in value[row][:minimum_length]):
            return False
    return True


def validate_realtime_packet(inverter: dict[str, Any]) -> None:
    """Reject incomplete frames before missing values can become plausible zeroes."""
    required = {
        "Home": {0: 1, 1: 3},
        "GrCTPP": {0: 3, 2: 1},
        "ACin": {0: 3},
        "Batt2": {0: 1, 1: 1, 2: 1},
        "Batsoc2": {0: 1},
        "PV": {0: 2, 1: 2, 2: 2},
    }
    invalid = [name for name, shape in required.items() if not _has_shape(inverter.get(name), shape)]
    if invalid:
        raise TelemetryAnomaly(
            "incomplete_packet",
            {"invalid_sections": invalid, "device_timestamp": inverter.get("date")},
        )


def _has_nonzero(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_has_nonzero(item) for item in value)
    if isinstance(value, dict):
        return any(_has_nonzero(item) for item in value.values())
    return bool(value)


def _decode_warning_codes(value: Any) -> list[int]:
    """Decode the inverter warning bitmask into the Wxx codes from its manual."""
    try:
        mask = int(value or 0)
    except (TypeError, ValueError):
        return []
    return [code for code in range(1, 33) if mask & (1 << (code - 1))]


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
    validate_realtime_packet(inverter)

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
    warning_codes = _decode_warning_codes(inverter.get("warn", 0))

    if all(value == 0 for value in grid_voltage.values()) and any(
        abs(value) > 100 for value in grid_phases.values()
    ):
        raise TelemetryAnomaly(
            "inconsistent_grid_telemetry",
            {"grid_voltage_v": grid_voltage, "grid_power_w": grid_phases},
        )

    consistency_issues: list[str] = []
    for name, total, phases in (
        ("Home", home_total, home_phases),
        ("GrCTPP", grid_total, grid_phases),
    ):
        phase_sum = sum(phases.values())
        tolerance = max(300, abs(phase_sum) * 0.2)
        if abs(total - phase_sum) > tolerance:
            consistency_issues.append(name)
    if consistency_issues:
        raise TelemetryAnomaly(
            "inconsistent_phase_total",
            {"sections": consistency_issues},
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
        "warning_codes": warning_codes,
        "warning_messages": [
            INVERTER_WARNING_MESSAGES.get(code, f"предупреждение W{code:02d}")
            for code in warning_codes
        ],
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
