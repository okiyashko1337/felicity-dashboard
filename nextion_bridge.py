#!/usr/bin/env python3
"""Send Felicity dashboard data to a Nextion NX4827P043 display over UART."""

from __future__ import annotations

import argparse
import json
import logging
import math
import signal
import time
from collections import deque
from datetime import datetime, time as datetime_time, timedelta
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen

import serial


TERMINATOR = b"\xff\xff\xff"
PAGE_NAMES = {
    0: "home",
    1: "pv",
    2: "load",
    3: "battery",
    4: "grid",
    5: "system",
    6: "today",
    7: "gaps",
}
DETAIL_PAGES = {"pv", "load", "battery", "grid", "system", "today"}
CHART_PAGES = DETAIL_PAGES | {"gaps"}
WAVEFORM_COMPONENT_ID = 2
HISTORY_LENGTH = 90
GAP_CHART_POINTS = 46
CHART_LEFT = 60
CHART_TOP = 120
CHART_RIGHT = 420
CHART_BOTTOM = 240
CHART_STEP = 4
CHART_REPLAY_STEP = 8
CHART_HISTORY_MAX_POINTS = 30
CHART_REPLAY_SAMPLES_PER_TICK = 3
CHART_COLORS = {
    "pv": (65519, 64495, 2047),
    "load": (65535, 2016, 65519, 2047),
    "battery": (65519, 64495),
    "grid": (65535, 2016, 65519, 64495),
    "system": (2016, 2047, 65519, 64495),
    "today": (65519, 2047),
    "gaps": (2016,),
}
CHART_AXIS_LABELS = {
    "pv": ("15kW", "7.5k", "0"),
    "load": ("15kW", "7.5k", "0"),
    "battery": ("100%", "50%", "0%"),
    "grid": ("260V", "220V", "180V"),
    "system": ("100", "50", "0"),
    "today": ("15kW", "7.5k", "0"),
    "gaps": ("100%", "50%", "0%"),
}
CHART_RIGHT_AXIS_LABELS = {
    "battery": ("+15k", "0", "-15k"),
    "grid": ("+15k", "0", "-15k"),
}
TRANSPARENT_TEXT_COMPONENTS = {
    "tYTop", "tYMid", "tYBottom", "tY2Top", "tY2Mid", "tY2Bottom",
    "tXLeft", "tXMid", "tXRight",
}

# The HMI contains only bitmap backgrounds and waveforms.  Text is drawn with
# xstr so values can change without maintaining dozens of Nextion components.
TEXT_LAYOUTS = {
    "header": {
        "tFresh": (180, 3, 70, 26),
        "tDate": (255, 3, 115, 26),
        "tTime": (375, 3, 98, 26),
    },
    "home": {
        "tSysTitle": (175, 164, 132, 20),
        "tPvV": (18, 80, 132, 28),
        "tPvS": (18, 116, 134, 26),
        "tLoadV": (175, 80, 132, 28),
        "tLoadS": (175, 116, 134, 26),
        "tBatV": (332, 80, 132, 28),
        "tBatS": (332, 116, 134, 26),
        "tGridV": (18, 190, 132, 28),
        "tGridS": (18, 226, 134, 26),
        "tSysV": (175, 190, 132, 28),
        "tSysS": (175, 226, 134, 26),
        "tDayV": (332, 190, 132, 28),
        "tDayS": (332, 226, 134, 26),
    },
    "detail": {
        "tBack": (4, 3, 22, 26),
        "tBrand": (28, 3, 82, 26),
        "tTitle": (112, 3, 64, 26),
        "tMain": (18, 52, 145, 26),
        "tA": (172, 50, 292, 18),
        "tB": (172, 69, 292, 18),
        "tC": (18, 85, 446, 16),
        "tYTop": (15, 111, 42, 14),
        "tYMid": (15, 179, 42, 14),
        "tYBottom": (15, 245, 42, 14),
        "tY2Top": (424, 111, 42, 14),
        "tY2Mid": (424, 179, 42, 14),
        "tY2Bottom": (424, 245, 42, 14),
        "tXLeft": (60, 247, 52, 14),
        "tXMid": (214, 247, 52, 14),
        "tXRight": (368, 247, 52, 14),
    },
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("felicity.nextion")
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def nested(data: dict, *path: str, default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def text_number(value: Any, digits: int = 0) -> str:
    if value is None:
        return "--"
    return f"{number(value):.{digits}f}"


def format_duration(seconds: Any) -> str:
    total = max(0, round(number(seconds)))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes:02d}m" if minutes else f"{hours}h"


def scale(value: Any, minimum: float, maximum: float) -> int:
    if maximum <= minimum:
        return 0
    ratio = (number(value) - minimum) / (maximum - minimum)
    return max(0, min(255, round(ratio * 255)))


def average(values: list[Any]) -> float:
    usable = [number(value) for value in values if value is not None]
    return sum(usable) / len(usable) if usable else 0.0


def coverage_bins(
    gaps: list[dict],
    start: datetime,
    end: datetime,
    count: int = 96,
) -> list[int]:
    """Return 0..255 coverage for equal intervals, using gap overlap as missing time."""
    if count <= 0 or end <= start:
        return []
    duration = (end - start).total_seconds()
    bin_seconds = duration / count
    result: list[int] = []
    parsed_gaps = [
        (datetime.fromisoformat(gap["start"]), datetime.fromisoformat(gap["end"]))
        for gap in gaps
        if gap.get("start") and gap.get("end")
    ]
    for index in range(count):
        bin_start = start + timedelta(seconds=index * bin_seconds)
        bin_end = start + timedelta(seconds=(index + 1) * bin_seconds)
        missing = 0.0
        for gap_start, gap_end in parsed_gaps:
            overlap_start = max(bin_start, gap_start.astimezone(bin_start.tzinfo))
            overlap_end = min(bin_end, gap_end.astimezone(bin_end.tzinfo))
            missing += max(0.0, (overlap_end - overlap_start).total_seconds())
        covered = max(0.0, bin_seconds - min(bin_seconds, missing))
        result.append(round(covered / bin_seconds * 255))
    return result


class NextionFrameParser:
    """Split the Nextion byte stream into frames terminated by three 0xFF bytes."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer.extend(chunk)
        frames: list[bytes] = []
        while True:
            position = self.buffer.find(TERMINATOR)
            if position < 0:
                break
            frames.append(bytes(self.buffer[:position]))
            del self.buffer[:position + len(TERMINATOR)]
        return frames


class NextionTransport:
    def __init__(self, port: str, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate
        self.connection: serial.SerialBase | None = None
        self.parser = NextionFrameParser()
        self.text_cache: dict[tuple[str, str], str] = {}
        self.color_cache: dict[tuple[str, str], int] = {}

    def open(self) -> None:
        self.connection = serial.serial_for_url(
            self.port,
            baudrate=self.baudrate,
            timeout=0.05,
            write_timeout=1,
        )
        self.connection.reset_input_buffer()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def command(self, command: str) -> None:
        if self.connection is None:
            raise serial.SerialException("Nextion serial port is closed")
        self.connection.write(command.encode("ascii", errors="replace") + TERMINATOR)

    def set_text(self, page: str, component: str, value: Any) -> None:
        key = (page, component)
        rendered = str(value)
        if self.text_cache.get(key) == rendered:
            return
        self.text_cache[key] = rendered
        layout = TEXT_LAYOUTS["header"].get(component)
        if layout is None:
            layout = TEXT_LAYOUTS["home" if page == "home" else "detail"].get(component)
        if layout is None:
            return
        x, y, width, height = layout
        color = self.color_cache.get(key, 65535)
        background = 162 if component in TEXT_LAYOUTS["header"] or page != "home" else 2307
        if page != "home" and component in {"tMain", "tA", "tB", "tC"}:
            background = 2307
        safe = rendered.replace("\\", "/").replace('"', "'")
        style = 3 if component in TRANSPARENT_TEXT_COMPONENTS else 1
        self.command(
            f'xstr {x},{y},{width},{height},0,{color},{background},0,1,{style},"{safe}"'
        )

    def set_text_at(
        self,
        page: str,
        component: str,
        value: Any,
        layout: tuple[int, int, int, int],
    ) -> None:
        """Draw movable chart labels without reusing a stale cached position."""
        rendered = str(value)
        self.text_cache[(page, component)] = rendered
        x, y, width, height = layout
        color = self.color_cache.get((page, component), 65535)
        safe = rendered.replace("\\", "/").replace('"', "'")
        self.command(
            f'xstr {x},{y},{width},{height},0,{color},2307,0,1,3,"{safe}"'
        )

    def set_color(self, page: str, component: str, rgb565: int) -> None:
        key = (page, component)
        if self.color_cache.get(key) == rgb565:
            return
        self.color_cache[key] = rgb565
        if key in self.text_cache:
            # Force a repaint because set_text normally suppresses unchanged text.
            value = self.text_cache.pop(key)
            self.set_text(page, component, value)

    def invalidate_page(self, page: str | None = None) -> None:
        """Forget painted text after a Nextion page load or reconnect."""
        if page is None:
            self.text_cache.clear()
            return
        self.text_cache = {
            key: value for key, value in self.text_cache.items() if key[0] != page
        }

    def clear_waveform(self) -> None:
        self.command(f"cle {WAVEFORM_COMPONENT_ID},255")

    def add_waveform(self, channel: int, value: int) -> None:
        self.command(f"add {WAVEFORM_COMPONENT_ID},{channel},{max(0, min(255, value))}")

    def add_waveform_batch(self, channel: int, values: list[int]) -> None:
        if self.connection is None or not values:
            return
        payload = bytes(max(0, min(255, value)) for value in values)
        self.command(f"addt {WAVEFORM_COMPONENT_ID},{channel},{len(payload)}")
        if not self.wait_for_frame(b"\xfe", timeout=1.0):
            raise serial.SerialException("Nextion did not enter waveform transfer mode")
        self.connection.write(payload)
        self.connection.flush()
        if not self.wait_for_frame(b"\xfd", timeout=1.0):
            raise serial.SerialException("Nextion did not finish waveform transfer")

    def wait_for_frame(self, expected: bytes, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for frame in self.read_frames():
                if frame == expected:
                    return True
            time.sleep(0.002)
        return False

    def read_frames(self) -> list[bytes]:
        if self.connection is None:
            return []
        waiting = self.connection.in_waiting
        return self.parser.feed(self.connection.read(waiting or 1))


class FelicityApi:
    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str) -> dict:
        with urlopen(f"{self.base_url}{path}", timeout=self.timeout) as response:
            return json.load(response)

    def current(self) -> dict:
        return self.get("/api/current")

    def system(self) -> dict:
        return self.get("/api/system/current")

    def today(self, now: datetime | None = None) -> dict:
        now = now or datetime.now().astimezone()
        start = datetime.combine(now.date(), datetime_time.min, tzinfo=now.tzinfo)
        end = start + timedelta(days=1)
        query = urlencode({"start": start.isoformat(), "end": end.isoformat(), "max_points": 480})
        return self.get(f"/api/analytics?{query}")


class NextionDashboard:
    def __init__(
        self,
        transport: NextionTransport,
        api: FelicityApi,
        live_interval: float = 2.0,
        system_interval: float = 60.0,
        analytics_interval: float = 60.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.transport = transport
        self.api = api
        self.live_interval = live_interval
        self.system_interval = system_interval
        self.analytics_interval = analytics_interval
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.page = "home"
        self.live: dict | None = None
        self.system_data: dict | None = None
        self.today_data: dict | None = None
        self.histories: dict[str, deque[tuple[int, ...]]] = {
            page: deque(maxlen=HISTORY_LENGTH) for page in DETAIL_PAGES
        }
        self.chart_x: dict[str, int] = {}
        self.chart_previous: dict[str, tuple[int, ...]] = {}
        self.chart_replays: dict[str, deque[tuple[int, ...]]] = {}
        self.chart_start_time: dict[str, datetime] = {}
        self.chart_end_time: dict[str, datetime] = {}
        self.chart_axis_bucket: dict[str, int] = {}

    def navigate(self, page: str) -> bool:
        if page == self.page:
            return False
        self.transport.command(f"page {page}")
        self.page = page
        self.transport.invalidate_page(page)
        # Let the display finish painting the new bitmap before drawing dynamic
        # xstr text over it. Otherwise the page paint can erase the first frame.
        time.sleep(0.08)
        logger.info("Nextion page: %s", page)
        return True

    def handle_touch(self, x: int, y: int) -> bool:
        if self.page == "home":
            if y < 44 and 260 <= x <= 400:
                return self.navigate("gaps")
            if 50 <= y <= 153:
                index = 0 if x < 161 else 1 if x < 318 else 2
                return self.navigate(("pv", "load", "battery")[index])
            if 160 <= y <= 271:
                index = 0 if x < 161 else 1 if x < 318 else 2
                return self.navigate(("grid", "system", "today")[index])
        elif x <= 70 and y < 44:
            return self.navigate("home")
        return False

    def handle_frame(self, frame: bytes) -> bool:
        if len(frame) >= 2 and frame[0] == 0x66:
            page = PAGE_NAMES.get(frame[1])
            if page:
                changed = page != self.page
                self.page = page
                if changed:
                    logger.info("Nextion page: %s", page)
                return changed
        if len(frame) >= 6 and frame[0] in {0x67, 0x68} and frame[5] == 0:
            x = frame[1] << 8 | frame[2]
            y = frame[3] << 8 | frame[4]
            return self.handle_touch(x, y)
        return frame == b"\x88"

    def update_clock(self) -> None:
        now = self.clock()
        self.transport.set_text(self.page, "tTime", now.strftime("%H:%M:%S"))
        self.transport.set_text(self.page, "tDate", now.strftime("%d.%m.%Y"))

    def update_freshness(self) -> None:
        fresh = False
        if self.live and self.live.get("timestamp"):
            timestamp = datetime.fromisoformat(self.live["timestamp"])
            age = (self.clock().astimezone(timestamp.tzinfo) - timestamp).total_seconds()
            fresh = 0 <= age <= 10
        self.transport.set_text(self.page, "tFresh", "LIVE" if fresh else "NO DATA")
        self.transport.set_color(self.page, "tFresh", 2016 if fresh else 63488)

    def remember_live(self) -> None:
        if not self.live:
            return
        data = self.live.get("parsed", {})
        pv = data.get("pv_power_w", {})
        load = data.get("load_power_w", {})
        grid_v = data.get("grid_voltage_v", {})
        grid_w = data.get("grid_power_w", {})
        system = (self.system_data or {}).get("data", {})
        self.histories["pv"].append((
            scale(pv.get("total"), 0, 15000),
            scale(pv.get("pv1"), 0, 15000),
            scale(pv.get("pv2"), 0, 15000),
        ))
        self.histories["load"].append((
            scale(load.get("total"), 0, 15000),
            scale(load.get("l1"), 0, 15000),
            scale(load.get("l2"), 0, 15000),
            scale(load.get("l3"), 0, 15000),
        ))
        self.histories["battery"].append((
            scale(data.get("soc_percent"), 0, 100),
            scale(data.get("battery_power_w"), -15000, 15000),
        ))
        self.histories["grid"].append((
            scale(grid_v.get("l1"), 180, 260),
            scale(grid_v.get("l2"), 180, 260),
            scale(grid_v.get("l3"), 180, 260),
            scale(grid_w.get("total"), -15000, 15000),
        ))
        self.histories["system"].append((
            scale(system.get("cpu_percent"), 0, 100),
            scale(nested(system, "memory", "percent"), 0, 100),
            scale(system.get("cpu_temperature_c"), 0, 100),
            scale(nested(system, "disk", "percent"), 0, 100),
        ))
        self.histories["today"].append((
            scale(pv.get("total"), 0, 15000),
            scale(load.get("total"), 0, 15000),
        ))

    @staticmethod
    def sparse_history(samples: list[tuple[int, ...]]) -> list[tuple[int, ...]]:
        """Replay recent real samples so pixel distance still represents time."""
        return samples[-CHART_HISTORY_MAX_POINTS:]

    def begin_waveform_replay(self) -> None:
        """Prepare a chart replay without blocking current-value rendering."""
        if self.page == "gaps":
            now = self.clock()
            start = datetime.combine(now.date(), datetime_time.min, tzinfo=now.tzinfo)
            gaps = (self.today_data or {}).get("gap_statistics", {}).get("gaps", [])
            elapsed = max(0.0, min(86400.0, (now - start).total_seconds()))
            point_count = max(
                2,
                min(GAP_CHART_POINTS, math.ceil(elapsed / 86400 * (GAP_CHART_POINTS - 1)) + 1),
            )
            values = coverage_bins(gaps, start, now, count=point_count)
            samples = [(value,) for value in values]
        elif self.page in DETAIL_PAGES:
            samples = self.sparse_history(list(self.histories[self.page]))
            now = self.clock()
            start = now - timedelta(seconds=max(0, len(samples) - 1) * self.live_interval)
        else:
            return
        self.chart_replays.clear()
        self.chart_replays[self.page] = deque(samples)
        self.chart_x[self.page] = CHART_LEFT
        self.chart_previous.pop(self.page, None)
        self.chart_start_time[self.page] = start
        self.chart_end_time[self.page] = now
        projected_x = min(
            CHART_RIGHT,
            CHART_LEFT + max(0, len(samples) - 1) * CHART_REPLAY_STEP,
        )
        if self.page == "gaps":
            day_end = start + timedelta(days=1) - timedelta(minutes=1)
            self.render_time_axis(self.page, CHART_RIGHT, start, day_end)
        else:
            self.render_time_axis(self.page, projected_x, start, now)

    def advance_waveform_replay(self, max_samples: int = CHART_REPLAY_SAMPLES_PER_TICK) -> bool:
        """Draw only a small chart chunk so UART never starves live values."""
        if self.page not in CHART_PAGES:
            return False
        pending = self.chart_replays.get(self.page)
        if not pending:
            self.chart_replays.pop(self.page, None)
            return False

        for _ in range(max_samples):
            if not pending:
                break
            sample = pending.popleft()
            previous = self.chart_previous.get(self.page)
            x = self.chart_x.get(self.page, CHART_LEFT)
            if previous is None:
                self.draw_chart_segment(self.page, x, sample, x, sample)
            elif x < CHART_RIGHT:
                step = CHART_REPLAY_STEP
                next_x = min(CHART_RIGHT, x + step)
                self.draw_chart_segment(self.page, x, previous, next_x, sample)
                x = next_x
            self.chart_x[self.page] = x
            self.chart_previous[self.page] = sample

        if not pending:
            self.chart_replays.pop(self.page, None)
            self.render_time_axis(
                self.page,
                self.chart_x.get(self.page, CHART_LEFT),
                self.chart_start_time.get(self.page),
                self.chart_end_time.get(self.page),
            )
        return True

    def replay_waveform(self) -> None:
        """Synchronous helper retained for diagnostics and unit tests."""
        self.begin_waveform_replay()
        while self.advance_waveform_replay(CHART_HISTORY_MAX_POINTS):
            pass

    @staticmethod
    def chart_y(value: int) -> int:
        bounded = max(0, min(255, value))
        height = CHART_BOTTOM - CHART_TOP
        return CHART_BOTTOM - round(bounded * height / 255)

    def draw_chart_segment(
        self,
        page: str,
        x1: int,
        first: tuple[int, ...],
        x2: int,
        second: tuple[int, ...],
    ) -> None:
        colors = CHART_COLORS.get(page, ())
        for channel, (start, end) in enumerate(zip(first, second)):
            if channel >= len(colors):
                break
            if page == "gaps" and x1 != x2:
                self.transport.command(
                    f"line {x1},{self.chart_y(start)},{x2},{self.chart_y(start)},{colors[channel]}"
                )
                if start != end:
                    self.transport.command(
                        f"line {x2},{self.chart_y(start)},{x2},{self.chart_y(end)},{colors[channel]}"
                    )
            else:
                self.transport.command(
                    f"line {x1},{self.chart_y(start)},{x2},{self.chart_y(end)},{colors[channel]}"
                )

    def append_active_waveform(self) -> None:
        if self.page not in DETAIL_PAGES or not self.histories[self.page]:
            return
        if self.chart_replays.get(self.page):
            return
        sample = self.histories[self.page][-1]
        previous = self.chart_previous.get(self.page)
        x = self.chart_x.get(self.page, CHART_LEFT)
        if previous is None:
            self.draw_chart_segment(self.page, x, sample, x, sample)
            self.chart_previous[self.page] = sample
            return
        if x >= CHART_RIGHT:
            self.reset_chart_sweep(self.page)
            x = CHART_LEFT
            previous = None
        if previous is None:
            self.draw_chart_segment(self.page, x, sample, x, sample)
            self.chart_previous[self.page] = sample
            self.chart_start_time[self.page] = self.clock()
            self.chart_end_time[self.page] = self.clock()
            self.render_time_axis(self.page, x)
            return
        next_x = min(CHART_RIGHT, x + CHART_STEP)
        self.draw_chart_segment(self.page, x, previous, next_x, sample)
        self.chart_x[self.page] = next_x
        self.chart_previous[self.page] = sample
        self.chart_end_time[self.page] = self.clock()
        bucket = int(self.clock().timestamp() // 10)
        if self.chart_axis_bucket.get(self.page) != bucket:
            self.chart_axis_bucket[self.page] = bucket
            self.render_time_axis(self.page, next_x)

    def reset_chart_sweep(self, page: str) -> None:
        """Clear only the plot, preserving the header and live value cards."""
        self.transport.command(
            f"fill {CHART_LEFT},{CHART_TOP},{CHART_RIGHT - CHART_LEFT + 1},"
            f"{CHART_BOTTOM - CHART_TOP + 1},2307"
        )
        for x in range(CHART_LEFT, CHART_RIGHT + 1, 72):
            self.transport.command(f"line {x},{CHART_TOP},{x},{CHART_BOTTOM},2016")
        for y in range(CHART_TOP, CHART_BOTTOM + 1, 30):
            self.transport.command(f"line {CHART_LEFT},{y},{CHART_RIGHT},{y},2016")
        self.chart_x[page] = CHART_LEFT
        self.chart_previous.pop(page, None)
        now = self.clock()
        self.chart_start_time[page] = now
        self.chart_end_time[page] = now

    def render_home(self) -> None:
        if not self.live:
            return
        data = self.live.get("parsed", {})
        pv = data.get("pv_power_w", {})
        load = data.get("load_power_w", {})
        grid_v = data.get("grid_voltage_v", {})
        grid_w = data.get("grid_power_w", {})
        battery_power = number(data.get("battery_power_w"))
        battery_mode = "CHG" if battery_power > 0 else "DIS" if battery_power < 0 else "IDLE"
        self.transport.set_text("home", "tPvV", f"{text_number(pv.get('total'))}W")
        self.transport.set_text("home", "tPvS", f"{text_number(pv.get('pv1'))}+{text_number(pv.get('pv2'))}")
        self.transport.set_text("home", "tLoadV", f"{text_number(load.get('total'))}W")
        self.transport.set_text("home", "tLoadS", f"{text_number(load.get('l1'))}/{text_number(load.get('l2'))}/{text_number(load.get('l3'))}")
        self.transport.set_text("home", "tBatV", f"{text_number(data.get('soc_percent'))}%")
        self.transport.set_text("home", "tBatS", f"{text_number(data.get('battery_voltage_v'), 1)}V {battery_mode[:1]}{text_number(abs(battery_power))}W")
        self.transport.set_text("home", "tGridV", f"{text_number(average([grid_v.get('l1'), grid_v.get('l2'), grid_v.get('l3')]), 1)}V")
        self.transport.set_text("home", "tGridS", f"{text_number(grid_w.get('total'))}W {text_number(data.get('grid_frequency_hz'), 0)}Hz")
        system = (self.system_data or {}).get("data", {})
        # Keep this label dynamic so older HMI backgrounds saying
        # "RASPBERRY PI" are corrected without requiring another asset flash.
        self.transport.set_color("home", "tSysTitle", 44373)
        self.transport.set_text("home", "tSysTitle", "SYSTEM")
        self.transport.set_text("home", "tSysV", f"{text_number(system.get('cpu_percent'), 0)}%")
        self.transport.set_text("home", "tSysS", f"R{text_number(nested(system, 'memory', 'percent'), 0)} T{text_number(system.get('cpu_temperature_c'), 0)} D{text_number(nested(system, 'disk', 'percent'), 0)}")
        stats = (self.today_data or {}).get("stats", {})
        pv_kwh = number(stats.get("pv_kwh"))
        load_kwh = number(stats.get("load_kwh"))
        coverage = pv_kwh / load_kwh * 100 if load_kwh else 0
        self.transport.set_text("home", "tDayV", f"{pv_kwh:.1f}kWh")
        self.transport.set_text("home", "tDayS", f"L{load_kwh:.1f} C{coverage:.0f}%")

    def render_detail(self) -> None:
        if not self.live:
            return
        data = self.live.get("parsed", {})
        page = self.page
        if page == "pv":
            pv = data.get("pv_power_w", {})
            voltage = data.get("pv_voltage_v", {})
            values = (f"{text_number(pv.get('total'))} W", f"PV1  {text_number(pv.get('pv1'))} W", f"PV2  {text_number(pv.get('pv2'))} W", f"MPPT  {text_number(voltage.get('mppt1'), 1)} / {text_number(voltage.get('mppt2'), 1)} V")
        elif page == "load":
            load = data.get("load_power_w", {})
            values = (f"{text_number(load.get('total'))} W", f"L1  {text_number(load.get('l1'))} W", f"L2  {text_number(load.get('l2'))} W", f"L3  {text_number(load.get('l3'))} W")
        elif page == "battery":
            power = number(data.get("battery_power_w"))
            state = "CHARGE" if power > 0 else "DISCHARGE" if power < 0 else "IDLE"
            batteries = data.get("batteries", [])
            module_soc = " / ".join(
                f"{text_number(item.get('soc_percent'), 0)}%" for item in batteries[:2]
            ) or "--"
            values = (
                f"{text_number(data.get('soc_percent'))}%",
                f"VOLTAGE  {text_number(data.get('battery_voltage_v'), 1)} V  /  {text_number(data.get('battery_current_a'), 1)} A",
                f"POWER  {text_number(power)} W  /  {state}",
                f"BMS SOC  {module_soc}",
            )
        elif page == "grid":
            voltage = data.get("grid_voltage_v", {})
            power = data.get("grid_power_w", {})
            values = (f"{text_number(average([voltage.get('l1'), voltage.get('l2'), voltage.get('l3')]), 1)} V", f"L1/L2/L3  {text_number(voltage.get('l1'), 1)} / {text_number(voltage.get('l2'), 1)} / {text_number(voltage.get('l3'), 1)} V", f"EXCHANGE  {text_number(power.get('total'))} W", f"FREQUENCY  {text_number(data.get('grid_frequency_hz'), 2)} Hz")
        elif page == "system":
            system = (self.system_data or {}).get("data", {})
            values = (f"{text_number(system.get('cpu_percent'), 1)}% CPU", f"RAM  {text_number(nested(system, 'memory', 'percent'), 1)}%", f"TEMP  {text_number(system.get('cpu_temperature_c'), 1)} C", f"DISK  {text_number(nested(system, 'disk', 'percent'), 1)}%")
        elif page == "today":
            stats = (self.today_data or {}).get("stats", {})
            pv_kwh = number(stats.get("pv_kwh"))
            load_kwh = number(stats.get("load_kwh"))
            coverage = pv_kwh / load_kwh * 100 if load_kwh else 0
            values = (f"PV  {pv_kwh:.2f} kWh", f"LOAD  {load_kwh:.2f} kWh", f"COVERAGE  {coverage:.0f}%", f"GRID  +{number(stats.get('grid_import_kwh')):.2f} / -{number(stats.get('grid_export_kwh')):.2f} kWh")
        else:
            return

        self.transport.set_color(page, "tBack", 65519)
        self.transport.set_color(page, "tBrand", 2047)
        self.transport.set_text(page, "tBack", "<")
        self.transport.set_text(page, "tBrand", "FELICITY")
        self.transport.set_text(page, "tTitle", page.upper()[:6])
        if page == "system":
            for component, color in zip(
                ("tMain", "tA", "tB", "tC"), CHART_COLORS["system"]
            ):
                self.transport.set_color(page, component, color)
        for component, value in zip(("tMain", "tA", "tB", "tC"), values):
            self.transport.set_text(page, component, value)
        self.render_chart_axes(page)

    def render_system_canvas(self) -> None:
        """Replace the legacy light System bitmap with the standard dark UI."""
        self.transport.command("fill 0,0,480,272,162")
        self.transport.command("line 8,32,472,32,2047")
        self.transport.command("fill 10,42,460,64,2307")
        self.transport.command("draw 10,42,469,105,8775")
        self.transport.command(
            f"fill {CHART_LEFT},{CHART_TOP},{CHART_RIGHT - CHART_LEFT + 1},"
            f"{CHART_BOTTOM - CHART_TOP + 1},2307"
        )
        self.transport.command(
            f"draw {CHART_LEFT},{CHART_TOP},{CHART_RIGHT},{CHART_BOTTOM},8775"
        )
        for x in range(CHART_LEFT, CHART_RIGHT + 1, 72):
            self.transport.command(f"line {x},{CHART_TOP},{x},{CHART_BOTTOM},6597")
        for y in range(CHART_TOP, CHART_BOTTOM + 1, 30):
            self.transport.command(f"line {CHART_LEFT},{y},{CHART_RIGHT},{y},6597")

    def render_chart_axes(self, page: str) -> None:
        labels = CHART_AXIS_LABELS.get(page)
        if not labels:
            return
        for component in (
            "tYTop", "tYMid", "tYBottom", "tXLeft", "tXMid", "tXRight",
        ):
            self.transport.set_color(page, component, 31727)
        for component, value in zip(("tYTop", "tYMid", "tYBottom"), labels):
            self.transport.set_text(page, component, value)
        right_labels = CHART_RIGHT_AXIS_LABELS.get(page)
        if right_labels:
            for component, value in zip(("tY2Top", "tY2Mid", "tY2Bottom"), right_labels):
                self.transport.set_color(page, component, 31727)
                self.transport.set_text(page, component, value)
        now = self.clock()
        if page == "gaps":
            start = datetime.combine(now.date(), datetime_time.min, tzinfo=now.tzinfo)
            now = start + timedelta(days=1) - timedelta(minutes=1)
            end_x = CHART_RIGHT
        else:
            sample_count = min(len(self.histories.get(page, ())), CHART_HISTORY_MAX_POINTS)
            history_seconds = max(0.0, (sample_count - 1) * self.live_interval)
            start = now - timedelta(seconds=history_seconds)
            end_x = min(CHART_RIGHT, CHART_LEFT + max(0, sample_count - 1) * CHART_REPLAY_STEP)
        self.chart_start_time[page] = start
        self.chart_end_time[page] = now
        self.render_time_axis(page, end_x, start, now)

    def render_time_axis(
        self,
        page: str,
        end_x: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        """Keep time labels clean and aligned with the actual line endpoint."""
        start = start or self.chart_start_time.get(page) or self.clock()
        end = end or self.chart_end_time.get(page) or self.clock()
        end_x = max(CHART_LEFT, min(CHART_RIGHT, end_x))
        self.transport.command("fill 58,245,364,18,2307")

        label_width = 52
        left_x = CHART_LEFT
        right_x = max(left_x, min(CHART_RIGHT - label_width, end_x - label_width // 2))
        midpoint_x = round((CHART_LEFT + end_x) / 2 - label_width / 2)
        midpoint = start + (end - start) / 2
        labels: list[tuple[str, datetime, int]] = []
        if right_x - left_x >= label_width + 8:
            labels.append(("tXLeft", start, left_x))
        if right_x - left_x >= label_width * 2 + 24:
            labels.append(("tXMid", midpoint, midpoint_x))
        labels.append(("tXRight", end, right_x))
        for component, moment, x in labels:
            self.transport.set_text_at(
                page, component, moment.strftime("%H:%M"), (x, 247, label_width, 14)
            )

    def render_gaps(self) -> None:
        gaps = (self.today_data or {}).get("gap_statistics", {})
        gap_list = gaps.get("gaps", [])
        latest = gap_list[-1] if gap_list else None
        self.transport.set_color("gaps", "tBack", 65519)
        self.transport.set_color("gaps", "tBrand", 2047)
        self.transport.set_text("gaps", "tBack", "<")
        self.transport.set_text("gaps", "tBrand", "FELICITY")
        self.transport.set_text("gaps", "tTitle", "GAPS")
        self.transport.set_text("gaps", "tMain", f"{number(gaps.get('coverage_percent')):.1f}%")
        self.transport.set_text("gaps", "tA", f"GAPS  {round(number(gaps.get('gap_count')))}")
        self.transport.set_text("gaps", "tB", f"LONGEST  {format_duration(gaps.get('longest_gap_seconds'))}")
        latest_text = "NO GAPS" if not latest else f"LAST  {datetime.fromisoformat(latest['start']).astimezone().strftime('%H:%M')} - {datetime.fromisoformat(latest['end']).astimezone().strftime('%H:%M')}"
        self.transport.set_text("gaps", "tC", latest_text)
        self.render_chart_axes("gaps")

    def render_gap_waveform(self) -> None:
        now = self.clock()
        start = datetime.combine(now.date(), datetime_time.min, tzinfo=now.tzinfo)
        end = min(start + timedelta(days=1), now)
        gaps = (self.today_data or {}).get("gap_statistics", {}).get("gaps", [])
        self.transport.clear_waveform()
        self.transport.add_waveform_batch(0, coverage_bins(gaps, start, end))

    def render_page(self, replay: bool = False) -> None:
        # Paint the current values first. History is replayed later in small
        # chunks so even a large chart cannot hold the live UI hostage.
        if replay:
            time.sleep(0.15)
            self.transport.invalidate_page(self.page)
            if self.page == "system":
                self.render_system_canvas()
        if self.page == "home":
            self.render_home()
        elif self.page == "gaps":
            self.render_gaps()
        else:
            self.render_detail()
        self.update_clock()
        self.update_freshness()
        if replay:
            self.begin_waveform_replay()

    def run_connected(self) -> None:
        self.transport.invalidate_page()
        self.transport.command("bkcmd=0")
        self.transport.command("sendxy=1")
        self.transport.command("page home")
        self.page = "home"
        next_clock = next_live = next_system = next_today = 0.0
        force_render = True
        while running:
            cycle = time.monotonic()
            for frame in self.transport.read_frames():
                force_render = self.handle_frame(frame) or force_render

            if cycle >= next_live:
                try:
                    self.live = self.api.current()
                    self.remember_live()
                except Exception as error:  # keep the screen alive across API restarts
                    logger.warning("Current data unavailable: %s", error)
                next_live = cycle + self.live_interval
                if self.page in DETAIL_PAGES:
                    self.append_active_waveform()
                    self.render_detail()
                elif self.page == "home":
                    self.render_home()

            if cycle >= next_system:
                try:
                    self.system_data = self.api.system()
                except Exception as error:
                    logger.warning("System data unavailable: %s", error)
                next_system = cycle + self.system_interval

            if cycle >= next_today or (force_render and self.page in {"today", "gaps"}):
                try:
                    self.today_data = self.api.today(self.clock())
                except Exception as error:
                    logger.warning("Today's analytics unavailable: %s", error)
                next_today = cycle + self.analytics_interval

            if force_render:
                self.render_page(replay=True)
                force_render = False
            elif cycle >= next_clock:
                self.update_clock()
                self.update_freshness()
            self.advance_waveform_replay()
            if cycle >= next_clock:
                next_clock = cycle + 1.0
            time.sleep(0.05)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Serial port or pyserial URL")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    transport = NextionTransport(args.port, args.baudrate)
    dashboard = NextionDashboard(transport, FelicityApi(args.api), live_interval=args.interval)

    while running:
        try:
            logger.info("Connecting Nextion on %s at %s baud", args.port, args.baudrate)
            transport.open()
            dashboard.run_connected()
        except (OSError, serial.SerialException) as error:
            logger.error("Nextion connection lost: %s", error)
            transport.close()
            if running:
                time.sleep(5)
        finally:
            transport.close()
    logger.info("Nextion bridge stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
