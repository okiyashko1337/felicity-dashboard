import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from database import (
    get_latest_telemetry,
    initialize_database,
    save_telemetry_snapshot,
)
from felicity_local import TelemetryAnomaly, decode_json_stream, parse_realtime_packets


INVERTER_PACKET = {
    "CommVer": 1,
    "date": "20260731152155",
    "DevSN": "120415004826050141",
    "Type": 84,
    "SubType": 1052,
    "workM": 5,
    "busV": 7800,
    "busVp": 3900,
    "busVn": 3899,
    "warn": 0,
    "faulS": [[0, 0, 0, 0, 0, 0, 0, 0, 0]],
    "GrCTPP": [[0, 0, 0], [24, 19, 21], [0]],
    "INV": [[2303, 2338, 2259], [46, 35, 33], [4999, 4999, 4999], [2600], [1050, 820, 730]],
    "ACin": [[2304, 2339, 2263], [-44, -35, -32], [4999, 4999, 4999], [-2510, 0], [-1010, -800, -700]],
    "ACout": [[2304, 2346, 2260], [4, 3, 4], [4999, 4999, 4999], [90, 290, 0], [40, 20, 30]],
    "PV": [[4189, 3484, 0, 0], [112, 120, 119, 117], [4700, 4190, 0, 0], [0]],
    "Temp": [[426, 429, 478, 0]],
    "Batt2": [[53600, 0], [1127, 0], [6050, 0], [0]],
    "Batsoc2": [[4200, 1000, 500], [0, 0, 7789]],
    "Home": [[251, None], [101, 80, 70]],
}

BMS_PACKET_1 = {
    "DevSN": "074504831426140623",
    "Type": 112,
    "ModAddr": 1,
    "BBfault": 0,
    "BBwarn": 0,
    "Templist": [[330, 320], [0, 1], [None], [None]],
    "BattList": [[53400, None], [518, None]],
    "BatsocList": [[4200, 1000, 350000]],
    "BMaxMin": [[3340, 3336], [8, 1]],
    "Bstate": 9152,
}

BMS_PACKET_2 = {
    **BMS_PACKET_1,
    "DevSN": "074504831426140938",
    "ModAddr": 2,
    "BattList": [[53340, None], [587, None]],
    "BMaxMin": [[3341, 3336], [8, 1]],
}


class FelicityLocalTests(unittest.TestCase):
    def test_decodes_concatenated_json_objects(self) -> None:
        payload = "".join(
            json.dumps(packet) for packet in [INVERTER_PACKET, BMS_PACKET_1, BMS_PACKET_2]
        )
        packets = decode_json_stream(payload)
        self.assertEqual([packet["Type"] for packet in packets], [84, 112, 112])

    def test_parses_users_live_snapshot(self) -> None:
        parsed = parse_realtime_packets(
            [INVERTER_PACKET, BMS_PACKET_1, BMS_PACKET_2]
        )

        self.assertEqual(parsed["pv_power_w"]["total"], 8890)
        self.assertEqual(parsed["load_power_w"], {"l1": 1010, "l2": 800, "l3": 700, "total": 2510})
        self.assertEqual(parsed["grid_power_w"]["total"], 0)
        self.assertEqual(parsed["battery_power_w"], 6050)
        self.assertEqual(parsed["battery_state"], "charging")
        self.assertEqual(parsed["soc_percent"], 42)
        self.assertEqual(parsed["inverter_power_w"]["total"], 2600)
        self.assertEqual(parsed["backup_power_w"]["total"], 90)
        self.assertEqual(parsed["grid_voltage_v"], {"l1": 230.4, "l2": 233.9, "l3": 226.3})
        self.assertEqual(parsed["pv_voltage_v"]["mppt1"], 418.9)
        self.assertEqual(parsed["pv_current_a"]["mppt2"], 12.0)
        self.assertEqual(parsed["grid_frequency_hz"], 49.99)
        self.assertEqual(parsed["inverter_current_a"], {"l1": 4.6, "l2": 3.5, "l3": 3.3})
        self.assertEqual(parsed["dc_bus_voltage_v"]["total"], 780.0)
        self.assertTrue(parsed["healthy"])
        self.assertEqual(len(parsed["batteries"]), 2)
        self.assertEqual(parsed["batteries"][0]["voltage_v"], 53.4)
        self.assertEqual(parsed["batteries"][0]["cell_delta_mv"], 4.0)
        self.assertEqual(parsed["batteries"][1]["current_a"], 58.7)

    def test_decodes_low_soc_warning_bitmask(self) -> None:
        inverter = {**INVERTER_PACKET, "warn": 4}

        parsed = parse_realtime_packets([inverter])

        self.assertFalse(parsed["healthy"])
        self.assertEqual(parsed["warning_codes"], [3])
        self.assertEqual(parsed["warning_messages"], ["низкий SOC батареи"])

    def test_rejects_partial_inverter_packet_instead_of_filling_zeroes(self) -> None:
        partial = {**INVERTER_PACKET}
        partial.pop("Home")
        partial.pop("ACin")
        partial.pop("Batt2")

        with self.assertRaises(TelemetryAnomaly) as raised:
            parse_realtime_packets([partial])

        self.assertEqual(raised.exception.reason, "incomplete_packet")
        self.assertEqual(
            raised.exception.details["invalid_sections"],
            ["Home", "ACin", "Batt2"],
        )

    def test_rejects_grid_power_with_zero_grid_voltage(self) -> None:
        inconsistent = {**INVERTER_PACKET, "ACin": [[0, 0, 0]], "GrCTPP": [[120, 0, 0], [], [120]]}

        with self.assertRaises(TelemetryAnomaly) as raised:
            parse_realtime_packets([inconsistent])

        self.assertEqual(raised.exception.reason, "inconsistent_grid_telemetry")

    def test_database_round_trip(self) -> None:
        parsed = parse_realtime_packets([INVERTER_PACKET])
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            row_id = save_telemetry_snapshot(
                raw_data=[INVERTER_PACKET],
                parsed_data=parsed,
                source="felicity_local_wifi",
                db_path=db_path,
                timestamp=datetime(2026, 7, 31, 13, 21, 55, tzinfo=timezone.utc),
            )
            latest = get_latest_telemetry(db_path)

        self.assertEqual(row_id, 1)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["source"], "felicity_local_wifi")
        self.assertEqual(latest["parsed"]["load_power_w"]["total"], 2510)


if __name__ == "__main__":
    unittest.main()
