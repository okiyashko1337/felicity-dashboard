import unittest
from datetime import datetime, timedelta, timezone

from nextion_bridge import NextionDashboard, NextionFrameParser, coverage_bins, format_duration


class RecordingTransport:
    def __init__(self) -> None:
        self.text: dict[tuple[str, str], str] = {}
        self.colors: dict[tuple[str, str], int] = {}
        self.waveform: list[tuple[int, int]] = []
        self.waveform_batches: list[tuple[int, list[int]]] = []
        self.cleared = 0
        self.commands: list[str] = []

    def command(self, value: str) -> None:
        self.commands.append(value)

    def set_text(self, page: str, component: str, value: object) -> None:
        self.text[(page, component)] = str(value)

    def set_color(self, page: str, component: str, value: int) -> None:
        self.colors[(page, component)] = value

    def clear_waveform(self) -> None:
        self.cleared += 1

    def add_waveform(self, channel: int, value: int) -> None:
        self.waveform.append((channel, value))

    def add_waveform_batch(self, channel: int, values: list[int]) -> None:
        self.waveform_batches.append((channel, values))

    def invalidate_page(self, page=None) -> None:
        pass


class UnusedApi:
    pass


class NextionBridgeTests(unittest.TestCase):
    def test_frame_parser_handles_fragmented_page_event(self) -> None:
        parser = NextionFrameParser()

        self.assertEqual(parser.feed(b"\x66\x03\xff"), [])
        self.assertEqual(parser.feed(b"\xff\xff\x88\xff\xff\xff"), [b"\x66\x03", b"\x88"])

    def test_gap_coverage_is_binned_without_interpolation(self) -> None:
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        gaps = [{
            "start": (start + timedelta(minutes=15)).isoformat(),
            "end": (start + timedelta(minutes=30)).isoformat(),
        }]

        result = coverage_bins(gaps, start, start + timedelta(hours=1), count=4)

        self.assertEqual(result, [255, 0, 255, 255])

    def test_home_page_contains_six_tiles_and_freshness(self) -> None:
        now = datetime(2026, 8, 1, 15, 9, 13, tzinfo=timezone.utc)
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi(), clock=lambda: now)
        dashboard.live = {
            "timestamp": (now - timedelta(seconds=2)).isoformat(),
            "parsed": {
                "pv_power_w": {"total": 3100, "pv1": 1860, "pv2": 1240},
                "load_power_w": {"total": 1700, "l1": 510, "l2": 510, "l3": 680},
                "soc_percent": 50,
                "battery_voltage_v": 52.4,
                "battery_power_w": 1400,
                "grid_voltage_v": {"l1": 230, "l2": 231, "l3": 229},
                "grid_power_w": {"total": 0},
                "grid_frequency_hz": 50,
            },
        }
        dashboard.system_data = {
            "data": {"cpu_percent": 9, "memory": {"percent": 30}, "cpu_temperature_c": 55}
        }
        dashboard.today_data = {"stats": {"pv_kwh": 12.4, "load_kwh": 8.0}}

        dashboard.render_page()

        self.assertEqual(transport.text[("home", "tPvV")], "3100W")
        self.assertEqual(transport.text[("home", "tDayV")], "12.4kWh")
        self.assertEqual(transport.text[("home", "tDayS")], "L8.0 C155%")
        self.assertEqual(transport.text[("home", "tFresh")], "LIVE")
        self.assertEqual(transport.text[("home", "tTime")], "15:09:13")

    def test_date_page_id_selects_gap_statistics(self) -> None:
        dashboard = NextionDashboard(RecordingTransport(), UnusedApi())

        self.assertTrue(dashboard.handle_frame(b"\x66\x07"))
        self.assertEqual(dashboard.page, "gaps")

    def test_raw_touch_opens_tile_and_back_area(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())

        self.assertTrue(dashboard.handle_frame(b"\x67\x00\xc8\x00\x64\x00"))
        self.assertEqual(dashboard.page, "load")
        self.assertEqual(transport.commands[-1], "page load")

        self.assertTrue(dashboard.handle_frame(b"\x67\x00\x20\x00\x10\x00"))
        self.assertEqual(dashboard.page, "home")
        self.assertEqual(transport.commands[-1], "page home")

    def test_raw_touch_on_home_date_opens_gap_statistics(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())

        self.assertTrue(dashboard.handle_frame(b"\x67\x01\x2c\x00\x14\x00"))
        self.assertEqual(dashboard.page, "gaps")

    def test_replay_draws_manual_lines_without_waveform_refresh(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())
        dashboard.page = "pv"
        dashboard.histories["pv"].extend(((10, 20, 30), (11, 21, 31)))

        dashboard.replay_waveform()

        self.assertEqual(transport.cleared, 0)
        self.assertEqual(
            transport.commands,
            [
                "line 14,256,14,256,65519",
                "line 14,250,14,250,64495",
                "line 14,244,14,244,2047",
                "line 14,256,18,255,65519",
                "line 14,250,18,249,64495",
                "line 14,244,18,243,2047",
            ],
        )
        self.assertEqual(transport.waveform, [])
        self.assertEqual(transport.waveform_batches, [])

    def test_detail_values_render_before_incremental_chart_replay(self) -> None:
        now = datetime(2026, 8, 1, 15, 9, 13, tzinfo=timezone.utc)
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi(), clock=lambda: now)
        dashboard.page = "pv"
        dashboard.live = {
            "timestamp": now.isoformat(),
            "parsed": {
                "pv_power_w": {"total": 210, "pv1": 120, "pv2": 90},
                "pv_voltage_v": {"mppt1": 380, "mppt2": 375},
            },
        }
        dashboard.histories["pv"].extend(((10, 20, 30), (11, 21, 31)))

        dashboard.render_page(replay=True)

        self.assertEqual(transport.text[("pv", "tMain")], "210 W")
        self.assertFalse(any(command.startswith("line ") for command in transport.commands))
        self.assertEqual(len(dashboard.chart_replays["pv"]), 2)

        dashboard.advance_waveform_replay()

        self.assertTrue(any(command.startswith("line ") for command in transport.commands))

    def test_long_history_is_thinned_before_replay(self) -> None:
        dashboard = NextionDashboard(RecordingTransport(), UnusedApi())
        dashboard.page = "pv"
        dashboard.histories["pv"].extend((value, value, value) for value in range(90))

        dashboard.begin_waveform_replay()

        self.assertLessEqual(len(dashboard.chart_replays["pv"]), 45)
        self.assertEqual(dashboard.chart_replays["pv"][-1], (89, 89, 89))

    def test_duration_is_compact_for_small_display(self) -> None:
        self.assertEqual(format_duration(42), "42s")
        self.assertEqual(format_duration(125), "2m")
        self.assertEqual(format_duration(7380), "2h 03m")


if __name__ == "__main__":
    unittest.main()
