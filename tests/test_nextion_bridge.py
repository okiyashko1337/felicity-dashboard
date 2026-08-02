from __future__ import annotations

import unittest
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from threading import Event

from nextion_bridge import (
    FelicityApi,
    NextionDashboard,
    NextionFrameParser,
    NextionTransport,
    coverage_bins,
    format_duration,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.text: dict[tuple[str, str], str] = {}
        self.colors: dict[tuple[str, str], int] = {}
        self.waveform: list[tuple[int, int]] = []
        self.waveform_batches: list[tuple[int, list[int]]] = []
        self.cleared = 0
        self.commands: list[str] = []
        self.touch_enables = 0

    def command(self, value: str) -> None:
        self.commands.append(value)

    def enable_touch_coordinates(self) -> None:
        self.touch_enables += 1

    def set_text(self, page: str, component: str, value: object) -> None:
        self.text[(page, component)] = str(value)

    def set_text_at(self, page: str, component: str, value: object, layout) -> None:
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


class RecordingConnection:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, value: bytes) -> None:
        self.writes.append(value)


class UnusedApi:
    pass


class CapturingApi(FelicityApi):
    def __init__(self) -> None:
        super().__init__("http://dashboard", timeout=2.0)
        self.requests: list[tuple[str, float | None]] = []

    def get(self, path: str, timeout: float | None = None) -> dict:
        self.requests.append((path, timeout))
        return {}


class BlockingApi:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def current(self) -> dict:
        self.started.set()
        self.release.wait(timeout=1)
        return {}


class NextionBridgeTests(unittest.TestCase):
    def test_today_uses_fast_daily_summary_and_gaps_keep_long_timeout(self) -> None:
        now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
        api = CapturingApi()

        api.today(now)
        api.today_gaps(now)

        self.assertEqual(
            api.requests[0],
            ("/api/analytics/day-summary?day=2026-08-02", None),
        )
        self.assertIn("/api/analytics?", api.requests[1][0])
        self.assertEqual(api.requests[1][1], 15.0)

    def test_device_chart_uses_compact_esp32_endpoint(self) -> None:
        api = CapturingApi()

        api.device_chart("load")

        self.assertEqual(
            api.requests[0],
            ("/api/device/chart?metric=load", 5.0),
        )

    def test_frame_parser_handles_fragmented_page_event(self) -> None:
        parser = NextionFrameParser()

        self.assertEqual(parser.feed(b"\x66\x03\xff"), [])
        self.assertEqual(parser.feed(b"\xff\xff\x88\xff\xff\xff"), [b"\x66\x03", b"\x88"])

    def test_frame_parser_discards_unbounded_unterminated_noise(self) -> None:
        parser = NextionFrameParser(max_buffer_bytes=32)

        self.assertEqual(parser.feed(b"x" * 128), [])

        self.assertLessEqual(len(parser.buffer), 2)
        self.assertEqual(parser.feed(b"\x67\x00\xc8\x00\x64\x01\xff\xff\xff"), [b"\x67\x00\xc8\x00\x64\x01"])

    def test_frame_parser_recovers_touch_after_noise_in_same_frame(self) -> None:
        parser = NextionFrameParser(max_buffer_bytes=32)

        frames = parser.feed(b"x" * 128 + b"\x67\x00\xc8\x00\x64\x01\xff\xff\xff")

        self.assertEqual(frames, [b"\x67\x00\xc8\x00\x64\x01"])

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
        self.assertEqual(transport.text[("home", "tSysTitle")], "SYSTEM")
        self.assertEqual(transport.colors[("home", "tSysTitle")], 2047)
        self.assertEqual(transport.colors[("home", "tPvTitle")], 2047)
        self.assertEqual(transport.text[("home", "tPvTitle")], "SOLAR")
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

    def test_touch_press_is_accepted_when_release_event_is_missing(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())

        try:
            self.assertTrue(dashboard.handle_frame(b"\x67\x00\xc8\x00\x64\x01"))
            self.assertEqual(dashboard.page, "load")
            self.assertGreaterEqual(transport.touch_enables, 1)
        finally:
            dashboard.close()

    def test_slow_api_poll_does_not_block_touch_handling(self) -> None:
        transport = RecordingTransport()
        api = BlockingApi()
        dashboard = NextionDashboard(transport, api)

        try:
            dashboard.schedule_api_poll("live", api.current)
            self.assertTrue(api.started.wait(timeout=0.5))
            self.assertTrue(dashboard.handle_frame(b"\x67\x00\xc8\x00\x64\x01"))
            self.assertEqual(dashboard.page, "load")
        finally:
            api.release.set()
            dashboard.close()

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
            [command for command in transport.commands if command.startswith("line ")],
            [
                "line 60,235,60,235,65519",
                "line 60,231,60,231,64495",
                "line 60,226,60,226,2047",
                "line 60,235,68,235,65519",
                "line 60,231,68,230,64495",
                "line 60,226,68,225,2047",
            ],
        )
        self.assertEqual(transport.waveform, [])
        self.assertEqual(transport.waveform_batches, [])

    def test_fixed_day_replay_uses_full_width_and_keeps_data_gaps(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())
        dashboard.page = "load"
        dashboard.device_charts["load"] = {
            "metric": "load",
            "start": "2026-08-02T00:00:00+00:00",
            "end": "2026-08-03T00:00:00+00:00",
            "samples": [
                [0, 0, 0, 0],
                [7500, 2500, 2500, 2500],
                None,
                [15000, 5000, 5000, 5000],
            ],
        }

        dashboard.replay_waveform()

        lines = [command for command in transport.commands if command.startswith("line ")]
        self.assertTrue(any(command.startswith("line 60,") for command in lines))
        self.assertTrue(any(",180," in command for command in lines))
        self.assertTrue(any(command.startswith("line 420,") for command in lines))
        self.assertFalse(any(command.startswith("line 180,") and ",420," in command for command in lines))
        self.assertEqual(transport.text[("load", "tXLeft")], "00:00")
        self.assertEqual(transport.text[("load", "tXMid")], "12:00")
        self.assertEqual(transport.text[("load", "tXRight")], "24:00")

    def test_fixed_time_axis_is_not_repainted_when_chart_refreshes(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())
        dashboard.page = "load"

        dashboard.render_fixed_time_axis("load")
        first_commands = list(transport.commands)
        dashboard.render_fixed_time_axis("load")

        self.assertEqual(transport.commands, first_commands)

    def test_unchanged_detail_values_send_no_uart_commands(self) -> None:
        connection = RecordingConnection()
        transport = NextionTransport("unused", 115200)
        transport.connection = connection
        dashboard = NextionDashboard(transport, UnusedApi())
        dashboard.page = "load"
        dashboard.live = {
            "parsed": {"load_power_w": {"total": 600, "l1": 100, "l2": 200, "l3": 300}}
        }
        dashboard.device_charts["load"] = {
            "metric": "load",
            "start": "2026-08-02T00:00:00+00:00",
            "end": "2026-08-03T00:00:00+00:00",
            "samples": [],
        }

        dashboard.render_detail()
        connection.writes.clear()
        dashboard.render_detail()

        self.assertEqual(connection.writes, [])

    def test_clock_tick_updates_only_the_time_text(self) -> None:
        moments = [datetime(2026, 8, 2, 18, 30, 0, tzinfo=timezone.utc)]
        connection = RecordingConnection()
        transport = NextionTransport("unused", 115200)
        transport.connection = connection
        dashboard = NextionDashboard(
            transport, UnusedApi(), clock=lambda: moments[0]
        )
        dashboard.page = "load"

        dashboard.update_clock()
        dashboard.update_freshness()
        connection.writes.clear()
        moments[0] += timedelta(seconds=1)
        dashboard.update_clock()
        dashboard.update_freshness()

        self.assertEqual(len(connection.writes), 1)
        command = connection.writes[0].decode("ascii", errors="replace")
        self.assertTrue(command.startswith("xstr 375,3,98,26,"))
        self.assertIn('"18:30:01"', command)
        self.assertNotIn("fill ", command)
        self.assertNotIn("line ", command)

    def test_chart_refresh_only_touches_plot_rectangle(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())
        dashboard.page = "load"
        dashboard.chart_axis_signature["load"] = ("00:00", "12:00", "24:00")
        result = Future()
        result.set_result({
            "metric": "load",
            "start": "2026-08-02T00:00:00+00:00",
            "end": "2026-08-03T00:00:00+00:00",
            "samples": [[600, 100, 200, 300]],
        })
        dashboard.api_polls["chart:load"] = result

        needs_full_repaint = dashboard.collect_api_results()

        self.assertFalse(needs_full_repaint)
        self.assertTrue(transport.commands)
        self.assertTrue(all(command.startswith(("fill 60,120,", "line ")) for command in transport.commands))
        self.assertFalse(any(command.startswith("xstr ") for command in transport.commands))

    def test_identical_chart_payload_sends_no_uart_commands(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())
        dashboard.page = "load"
        payload = {
            "metric": "load",
            "start": "2026-08-02T00:00:00+00:00",
            "end": "2026-08-03T00:00:00+00:00",
            "samples": [[600, 100, 200, 300]],
        }
        dashboard.device_charts["load"] = payload
        result = Future()
        result.set_result(dict(payload))
        dashboard.api_polls["chart:load"] = result

        needs_full_repaint = dashboard.collect_api_results()

        self.assertFalse(needs_full_repaint)
        self.assertEqual(transport.commands, [])

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
        self.assertEqual(transport.text[("pv", "tYTop")], "15kW")
        self.assertEqual(transport.text[("pv", "tXLeft")], "00:00")
        self.assertEqual(transport.text[("pv", "tXMid")], "12:00")
        self.assertEqual(transport.text[("pv", "tXRight")], "24:00")
        self.assertFalse(any(command.startswith("line ") for command in transport.commands))
        self.assertEqual(len(dashboard.chart_replays["pv"]), 2)

        dashboard.advance_waveform_replay()

        self.assertTrue(any(command.startswith("line ") for command in transport.commands))

    def test_long_history_is_thinned_before_replay(self) -> None:
        dashboard = NextionDashboard(RecordingTransport(), UnusedApi())
        dashboard.page = "pv"
        dashboard.histories["pv"].extend((value, value, value) for value in range(90))

        dashboard.begin_waveform_replay()

        self.assertLessEqual(len(dashboard.chart_replays["pv"]), 30)
        self.assertEqual(dashboard.chart_replays["pv"][-1], (89, 89, 89))
        self.assertEqual(dashboard.chart_replays["pv"][0], (60, 60, 60))

    def test_detail_fallback_keeps_fixed_day_axis_while_chart_loads(self) -> None:
        now = datetime(2026, 8, 2, 7, 32, 14, tzinfo=timezone.utc)
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi(), clock=lambda: now)
        dashboard.page = "pv"
        dashboard.histories["pv"].extend((value, value, value) for value in range(90))

        dashboard.begin_waveform_replay()

        self.assertIn("fill 58,245,364,18,2307", transport.commands)
        self.assertEqual(transport.text[("pv", "tXLeft")], "00:00")
        self.assertEqual(transport.text[("pv", "tXMid")], "12:00")
        self.assertEqual(transport.text[("pv", "tXRight")], "24:00")

    def test_gap_page_uses_incremental_lines_and_day_timescale(self) -> None:
        now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi(), clock=lambda: now)
        dashboard.page = "gaps"
        dashboard.gap_data = {
            "gap_statistics": {
                "coverage_percent": 99.0,
                "gap_count": 1,
                "longest_gap_seconds": 60,
                "gaps": [{
                    "start": (now - timedelta(hours=1)).isoformat(),
                    "end": (now - timedelta(minutes=59)).isoformat(),
                }],
            }
        }

        dashboard.render_page(replay=True)

        self.assertEqual(transport.text[("gaps", "tXLeft")], "00:00")
        self.assertEqual(transport.text[("gaps", "tXMid")], "11:59")
        self.assertEqual(transport.text[("gaps", "tXRight")], "23:59")
        self.assertEqual(len(dashboard.chart_replays["gaps"]), 24)
        self.assertEqual(transport.cleared, 0)
        self.assertEqual(transport.waveform_batches, [])

        dashboard.advance_waveform_replay()

        self.assertTrue(any(command.startswith("line ") for command in transport.commands))

    def test_system_history_contains_disk_channel(self) -> None:
        dashboard = NextionDashboard(RecordingTransport(), UnusedApi())
        dashboard.live = {"parsed": {}}
        dashboard.system_data = {
            "data": {
                "cpu_percent": 10,
                "memory": {"percent": 20},
                "cpu_temperature_c": 50,
                "disk": {"percent": 30},
            }
        }

        dashboard.remember_live()

        self.assertEqual(len(dashboard.histories["system"][-1]), 4)

    def test_system_page_replaces_legacy_background_and_colors_metrics(self) -> None:
        now = datetime(2026, 8, 2, 8, 24, tzinfo=timezone.utc)
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi(), clock=lambda: now)
        dashboard.page = "system"
        dashboard.live = {"timestamp": now.isoformat(), "parsed": {}}
        dashboard.system_data = {
            "data": {
                "cpu_percent": 55.4,
                "memory": {"percent": 38.2},
                "cpu_temperature_c": 66.1,
                "disk": {"percent": 17.1},
            }
        }

        dashboard.render_page(replay=True)

        self.assertIn("fill 0,0,480,272,162", transport.commands)
        self.assertEqual(transport.text[("system", "tBack")], "BACK")
        self.assertEqual(transport.text[("system", "tTitle")], "SYSTEM")
        self.assertEqual(transport.colors[("system", "tMain")], 2016)
        self.assertEqual(transport.colors[("system", "tC")], 64495)

    def test_battery_page_uses_dark_canvas_and_colored_metrics(self) -> None:
        now = datetime(2026, 8, 2, 8, 47, tzinfo=timezone.utc)
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi(), clock=lambda: now)
        dashboard.page = "battery"
        dashboard.live = {
            "timestamp": now.isoformat(),
            "parsed": {
                "soc_percent": 74,
                "battery_voltage_v": 51.4,
                "battery_current_a": -38.2,
                "battery_power_w": -1963,
            },
        }

        dashboard.render_page(replay=True)

        self.assertIn("fill 0,0,480,272,162", transport.commands)
        self.assertEqual(transport.colors[("battery", "tMain")], 65519)
        self.assertEqual(transport.colors[("battery", "tB")], 64495)

    def test_detail_header_draws_clipped_safe_yin_yang_and_back_label(self) -> None:
        now = datetime(2026, 8, 2, 8, 47, tzinfo=timezone.utc)
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi(), clock=lambda: now)
        dashboard.page = "pv"
        dashboard.live = {"timestamp": now.isoformat(), "parsed": {}}

        dashboard.render_page(replay=True)

        self.assertIn("fill 0,0,178,32,162", transport.commands)
        self.assertIn("cir 15,16,9,2047", transport.commands)
        self.assertEqual(transport.text[("pv", "tBack")], "BACK")

    def test_light_detail_pages_open_on_dark_template_without_losing_logical_page(self) -> None:
        transport = RecordingTransport()
        dashboard = NextionDashboard(transport, UnusedApi())

        self.assertTrue(dashboard.navigate("battery"))
        self.assertEqual(transport.commands[-1], "page pv")
        self.assertEqual(dashboard.page, "battery")
        self.assertFalse(dashboard.handle_frame(b"\x66\x01"))
        self.assertEqual(dashboard.page, "battery")

    def test_duration_is_compact_for_small_display(self) -> None:
        self.assertEqual(format_duration(42), "42s")
        self.assertEqual(format_duration(125), "2m")
        self.assertEqual(format_duration(7380), "2h 03m")


if __name__ == "__main__":
    unittest.main()
