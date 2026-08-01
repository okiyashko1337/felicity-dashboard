#!/usr/bin/env python3
"""Generate realistic Felicity IVGM register snapshots for UI development."""

import argparse
import json
import math
import random
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import DB_PATH
from database import initialize_database, save_telemetry_snapshot

POLL_INTERVAL_SECONDS = 2.0
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


class InverterSimulator:
    def __init__(self, pv_test_watts: Optional[float] = None) -> None:
        self.pv_test_watts = pv_test_watts
        self.soc = random.uniform(55.0, 75.0)
        self.cloud_factor = random.uniform(0.85, 1.0)
        self.grid_voltage = [230.0, 230.0, 230.0]
        self.load_power = [
            random.uniform(500.0, 1200.0),
            random.uniform(500.0, 1200.0),
            random.uniform(500.0, 1200.0),
        ]

    @staticmethod
    def daylight_factor(now: datetime) -> float:
        """Return a smooth 0..1 solar curve between 06:00 and 20:00."""
        local_now = now.astimezone()
        hour = (
            local_now.hour
            + local_now.minute / 60
            + local_now.second / 3600
        )
        sunrise = 6.0
        sunset = 20.0
        if hour <= sunrise or hour >= sunset:
            return 0.0
        phase = (hour - sunrise) / (sunset - sunrise)
        return math.sin(math.pi * phase)

    def generate(self, now: datetime) -> tuple[dict[int, int], dict]:
        daylight = self.daylight_factor(now)

        # Clouds change gradually rather than making PV power jump abruptly.
        self.cloud_factor += random.uniform(-0.025, 0.025)
        self.cloud_factor = min(1.0, max(0.55, self.cloud_factor))
        pv_total = 5000.0 * daylight * self.cloud_factor
        if daylight == 0:
            pv_total = 0.0
        if self.pv_test_watts is not None:
            pv_total = max(0.0, self.pv_test_watts + random.uniform(-60, 60))
            daylight = min(1.0, pv_total / 5000.0)

        pv1 = max(0, round(pv_total * 0.52 + random.uniform(-30, 30)))
        pv2 = max(0, round(pv_total - pv1))
        if pv_total == 0:
            pv1 = pv2 = 0

        for index in range(3):
            self.grid_voltage[index] += random.uniform(-0.35, 0.35)
            self.grid_voltage[index] += (230.0 - self.grid_voltage[index]) * 0.08
            self.grid_voltage[index] = min(235.0, max(225.0, self.grid_voltage[index]))

            self.load_power[index] += random.uniform(-65, 65)
            self.load_power[index] = min(2000.0, max(300.0, self.load_power[index]))

        total_load = sum(self.load_power)
        net_power = pv_total - total_load
        self.soc += net_power / 3_600_000
        self.soc += random.uniform(-0.015, 0.015)
        self.soc = min(95.0, max(40.0, self.soc))

        battery_voltage = 51.2 + (self.soc - 67.5) * 0.018
        battery_voltage += random.uniform(-0.08, 0.08)
        battery_power = round(net_power)
        battery_current = round(net_power / max(battery_voltage, 1), 1)
        pv_voltage = [
            round(390 + 35 * daylight + random.uniform(-2, 2), 1) if pv1 else 0,
            round(360 + 30 * daylight + random.uniform(-2, 2), 1) if pv2 else 0,
        ]
        pv_current = [
            round(pv1 / pv_voltage[0], 1) if pv_voltage[0] else 0,
            round(pv2 / pv_voltage[1], 1) if pv_voltage[1] else 0,
        ]
        temperatures = {
            "inverter": round(38 + pv_total / 1300 + random.uniform(-0.2, 0.2), 1),
            "dc": round(39 + pv_total / 1250 + random.uniform(-0.2, 0.2), 1),
            "transformer": round(42 + total_load / 1000 + random.uniform(-0.2, 0.2), 1),
        }
        pack_current = battery_current / 2
        batteries = []
        for address, offset in ((1, -0.03), (2, 0.03)):
            pack_voltage = round(battery_voltage + offset, 3)
            cell_min = round(pack_voltage / 16 - 0.002, 3)
            cell_max = round(cell_min + random.uniform(0.003, 0.007), 3)
            batteries.append(
                {
                    "serial": f"SIM-BMS-{address}",
                    "mod_address": address,
                    "voltage_v": pack_voltage,
                    "current_a": round(pack_current + random.uniform(-0.8, 0.8), 1),
                    "power_w": round(pack_voltage * pack_current),
                    "soc_percent": round(self.soc, 1),
                    "soh_percent": 100.0,
                    "capacity_ah": 350.0,
                    "temperature_c": {
                        "max": round(31 + abs(pack_current) / 30 + random.uniform(-0.2, 0.2), 1),
                        "min": round(30 + abs(pack_current) / 35 + random.uniform(-0.2, 0.2), 1),
                    },
                    "cell_voltage_v": {
                        "max": cell_max,
                        "min": cell_min,
                        "max_cell": 8,
                        "min_cell": 1,
                    },
                    "cell_delta_mv": round((cell_max - cell_min) * 1000, 1),
                    "fault": 0,
                    "warning": 0,
                    "state": 9152,
                }
            )

        raw_registers = {
            101: round(self.soc),
            102: round(battery_voltage * 10),
            110: pv1,
            111: pv2,
            120: round(self.grid_voltage[0] * 10),
            121: round(self.grid_voltage[1] * 10),
            122: round(self.grid_voltage[2] * 10),
            135: round(self.load_power[0]),
            136: round(self.load_power[1]),
            137: round(self.load_power[2]),
        }

        parsed_data = {
            "source": "simulator",
            "healthy": True,
            "warning": 0,
            "faults": [],
            "soc_percent": raw_registers[101],
            "soh_percent": 100,
            "battery_voltage_v": raw_registers[102] / 10,
            "battery_current_a": battery_current,
            "battery_power_w": battery_power,
            "battery_state": (
                "charging" if net_power > 0 else "discharging" if net_power < 0 else "idle"
            ),
            "pv_power_w": {
                "pv1": raw_registers[110],
                "pv2": raw_registers[111],
                "channels": [raw_registers[110], raw_registers[111], 0, 0],
                "total": raw_registers[110] + raw_registers[111],
            },
            "pv_voltage_v": {
                "mppt1": pv_voltage[0],
                "mppt2": pv_voltage[1],
                "channels": [pv_voltage[0], pv_voltage[1], 0, 0],
            },
            "pv_current_a": {
                "mppt1": pv_current[0],
                "mppt2": pv_current[1],
                "channels": [pv_current[0], pv_current[1], 0, 0],
            },
            "grid_voltage_v": {
                "l1": raw_registers[120] / 10,
                "l2": raw_registers[121] / 10,
                "l3": raw_registers[122] / 10,
            },
            "grid_current_a": {
                "l1": round(self.load_power[0] / self.grid_voltage[0], 1),
                "l2": round(self.load_power[1] / self.grid_voltage[1], 1),
                "l3": round(self.load_power[2] / self.grid_voltage[2], 1),
            },
            "load_power_w": {
                "l1": raw_registers[135],
                "l2": raw_registers[136],
                "l3": raw_registers[137],
                "total": (
                    raw_registers[135]
                    + raw_registers[136]
                    + raw_registers[137]
                ),
            },
            "grid_power_w": {"l1": 0, "l2": 0, "l3": 0, "total": 0},
            "grid_frequency_hz": 50.0,
            "grid_frequency_by_phase_hz": {"l1": 50.0, "l2": 50.0, "l3": 50.0},
            "inverter_voltage_v": {
                "l1": raw_registers[120] / 10,
                "l2": raw_registers[121] / 10,
                "l3": raw_registers[122] / 10,
            },
            "inverter_current_a": {
                "l1": round(self.load_power[0] / self.grid_voltage[0], 1),
                "l2": round(self.load_power[1] / self.grid_voltage[1], 1),
                "l3": round(self.load_power[2] / self.grid_voltage[2], 1),
            },
            "inverter_power_w": {
                "l1": round(self.load_power[0]),
                "l2": round(self.load_power[1]),
                "l3": round(self.load_power[2]),
                "total": round(total_load),
            },
            "backup_power_w": {"l1": 0, "l2": 0, "l3": 0, "total": 0},
            "backup_voltage_v": {
                "l1": raw_registers[120] / 10,
                "l2": raw_registers[121] / 10,
                "l3": raw_registers[122] / 10,
            },
            "backup_current_a": {"l1": 0, "l2": 0, "l3": 0},
            "dc_bus_voltage_v": {"total": 780.0, "positive": 390.0, "negative": 390.0},
            "temperature_c": temperatures,
            "batteries": batteries,
        }
        return raw_registers, parsed_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite database path")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Generate one snapshot and exit",
    )
    parser.add_argument(
        "--pv-test-watts",
        type=float,
        help="Override the solar curve with a visible test power level",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    initialize_database(args.db)
    simulator = InverterSimulator(pv_test_watts=args.pv_test_watts)

    while running:
        cycle_started = time.monotonic()
        timestamp = datetime.now(timezone.utc)
        raw_registers, parsed_data = simulator.generate(timestamp)
        save_telemetry_snapshot(
            raw_data=raw_registers,
            parsed_data=parsed_data,
            source="simulator",
            db_path=args.db,
            timestamp=timestamp,
        )

        print(
            json.dumps(
                {
                    "timestamp": timestamp.isoformat(),
                    "registers": raw_registers,
                    "parsed": parsed_data,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        if args.once:
            break
        elapsed = time.monotonic() - cycle_started
        time.sleep(max(0, POLL_INTERVAL_SECONDS - elapsed))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
