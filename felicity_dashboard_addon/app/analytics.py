"""Energy integration and chart downsampling for historical telemetry."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any


POWER_FIELDS = {
    "pv_kwh": ("pv_power_w", "total"),
    "load_kwh": ("load_power_w", "total"),
    "grid_w": ("grid_power_w", "total"),
    "battery_w": ("battery_power_w",),
}

ENERGY_FIELDS = (
    "pv_wh",
    "load_wh",
    "grid_import_wh",
    "grid_export_wh",
    "battery_charge_wh",
    "battery_discharge_wh",
)

DEFAULT_MAX_GAP_SECONDS = 30.0


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _nested(data: dict, path: tuple[str, ...]) -> float:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return 0.0
        value = value.get(key)
    return _number(value)


def _sample_evenly(rows: list[dict], max_points: int) -> list[dict]:
    if len(rows) <= max_points:
        return rows
    if max_points <= 1:
        return [rows[-1]]
    indexes = {
        round(index * (len(rows) - 1) / (max_points - 1))
        for index in range(max_points)
    }
    return [rows[index] for index in sorted(indexes)]


def _chart_point(row: dict) -> dict:
    data = row["parsed"]
    batteries = data.get("batteries") or []
    return {
        "timestamp": row["timestamp"],
        "pv_w": _nested(data, ("pv_power_w", "total")),
        "load_w": _nested(data, ("load_power_w", "total")),
        "grid_w": _nested(data, ("grid_power_w", "total")),
        "battery_w": _nested(data, ("battery_power_w",)),
        "soc_percent": _nested(data, ("soc_percent",)),
        "battery_voltage_v": _nested(data, ("battery_voltage_v",)),
        "battery_current_a": _nested(data, ("battery_current_a",)),
        "bms1_current_a": _nested(batteries[0], ("current_a",)) if batteries else None,
        "bms2_current_a": _nested(batteries[1], ("current_a",)) if len(batteries) > 1 else None,
        "bms1_delta_mv": _nested(batteries[0], ("cell_delta_mv",)) if batteries else None,
        "bms2_delta_mv": _nested(batteries[1], ("cell_delta_mv",)) if len(batteries) > 1 else None,
    }


def telemetry_day(row: dict) -> str:
    """Prefer the inverter's local calendar day over the host timezone."""
    device_timestamp = (
        row.get("parsed", {}).get("device", {}).get("device_timestamp")
    )
    if isinstance(device_timestamp, str) and len(device_timestamp) >= 10:
        return device_timestamp[:10]
    return datetime.fromisoformat(row["timestamp"]).date().isoformat()


def build_gap_statistics(
    rows: list[dict],
    range_start: datetime | None = None,
    range_end: datetime | None = None,
    max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
    now: datetime | None = None,
) -> dict:
    """Describe missing telemetry without treating interpolated values as readings."""
    timestamps = sorted(datetime.fromisoformat(row["timestamp"]) for row in rows)
    start = range_start or (timestamps[0] if timestamps else None)
    end = range_end or (timestamps[-1] if timestamps else None)
    if start is None or end is None:
        return {
            "coverage_percent": 0.0,
            "gap_count": 0,
            "gap_seconds": 0,
            "missing_seconds": 0,
            "longest_gap_seconds": 0,
            "period_seconds": 0,
            "gaps": [],
        }

    if now is None:
        now = datetime.now(end.tzinfo or timezone.utc)
    elif end.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=end.tzinfo)
    if end.tzinfo is not None and now.tzinfo is not None:
        now = now.astimezone(end.tzinfo)
    effective_end = min(end, now)
    period_seconds = max(0.0, (effective_end - start).total_seconds())
    timestamps = [timestamp for timestamp in timestamps if start <= timestamp <= effective_end]

    gaps: list[dict] = []
    observed_seconds = 0.0

    def add_gap(gap_start: datetime, gap_end: datetime) -> None:
        duration = (gap_end - gap_start).total_seconds()
        if duration > max_gap_seconds:
            gaps.append({
                "start": gap_start.isoformat(),
                "end": gap_end.isoformat(),
                "duration_seconds": round(duration),
            })

    if timestamps:
        add_gap(start, timestamps[0])
        for previous, current in zip(timestamps, timestamps[1:]):
            delta_seconds = (current - previous).total_seconds()
            if 0 < delta_seconds <= max_gap_seconds:
                observed_seconds += delta_seconds
            elif delta_seconds > max_gap_seconds:
                add_gap(previous, current)
        add_gap(timestamps[-1], effective_end)
    elif period_seconds > 0:
        add_gap(start, effective_end)

    missing_seconds = max(0.0, period_seconds - observed_seconds)
    gap_seconds = sum(gap["duration_seconds"] for gap in gaps)
    longest_gap = max((gap["duration_seconds"] for gap in gaps), default=0)
    coverage = observed_seconds / period_seconds * 100 if period_seconds else 0.0
    return {
        "coverage_percent": round(min(100.0, coverage), 1),
        "gap_count": len(gaps),
        "gap_seconds": round(gap_seconds),
        "missing_seconds": round(missing_seconds),
        "longest_gap_seconds": round(longest_gap),
        "period_seconds": round(period_seconds),
        "gaps": gaps,
    }


def daily_increment(previous: dict | None, current: dict) -> dict:
    """Build one additive daily aggregate increment for a new snapshot."""
    day = telemetry_day(current)
    current_data = current["parsed"]
    soc = (
        _number(current_data.get("soc_percent"))
        if current_data.get("soc_percent") is not None
        else None
    )
    increment = {
        "day": day,
        **{field: 0.0 for field in ENERGY_FIELDS},
        "integrated_seconds": 0.0,
        "sample_count": 1,
        "soc_start_percent": soc,
        "soc_end_percent": soc,
        "soc_min_percent": soc,
        "soc_max_percent": soc,
        "first_timestamp": current["timestamp"],
        "last_timestamp": current["timestamp"],
    }

    if previous is None or telemetry_day(previous) != day:
        return increment
    previous_time = datetime.fromisoformat(previous["timestamp"])
    current_time = datetime.fromisoformat(current["timestamp"])
    delta_seconds = (current_time - previous_time).total_seconds()
    if delta_seconds <= 0 or delta_seconds > 30:
        return increment

    previous_data = previous["parsed"]
    pv_w = (_nested(previous_data, POWER_FIELDS["pv_kwh"]) + _nested(current_data, POWER_FIELDS["pv_kwh"])) / 2
    load_w = (_nested(previous_data, POWER_FIELDS["load_kwh"]) + _nested(current_data, POWER_FIELDS["load_kwh"])) / 2
    grid_w = (_nested(previous_data, POWER_FIELDS["grid_w"]) + _nested(current_data, POWER_FIELDS["grid_w"])) / 2
    battery_w = (_nested(previous_data, POWER_FIELDS["battery_w"]) + _nested(current_data, POWER_FIELDS["battery_w"])) / 2
    hours = delta_seconds / 3600
    increment.update({
        "pv_wh": max(0.0, pv_w) * hours,
        "load_wh": max(0.0, load_w) * hours,
        "grid_import_wh": max(0.0, grid_w) * hours,
        "grid_export_wh": max(0.0, -grid_w) * hours,
        "battery_charge_wh": max(0.0, battery_w) * hours,
        "battery_discharge_wh": max(0.0, -battery_w) * hours,
        "integrated_seconds": delta_seconds,
    })
    return increment


def build_daily_aggregates(rows: list[dict]) -> list[dict]:
    aggregates: dict[str, dict] = {}
    previous: dict | None = None
    for row in rows:
        increment = daily_increment(previous, row)
        bucket = aggregates.get(increment["day"])
        if bucket is None:
            aggregates[increment["day"]] = increment
        else:
            for field in (*ENERGY_FIELDS, "integrated_seconds", "sample_count"):
                bucket[field] += increment[field]
            bucket["soc_end_percent"] = increment["soc_end_percent"]
            if increment["soc_min_percent"] is not None:
                bucket["soc_min_percent"] = min(
                    value for value in (bucket["soc_min_percent"], increment["soc_min_percent"])
                    if value is not None
                )
                bucket["soc_max_percent"] = max(
                    value for value in (bucket["soc_max_percent"], increment["soc_max_percent"])
                    if value is not None
                )
            bucket["last_timestamp"] = increment["last_timestamp"]
        previous = row
    return [aggregates[day] for day in sorted(aggregates)]


def build_period_analytics(
    rows: list[dict],
    group_by_month: bool = False,
    start_day: date | None = None,
    end_day: date | None = None,
    now: datetime | None = None,
) -> dict:
    """Combine persisted daily aggregates into weekly/monthly/all-time data."""
    now = now or datetime.now().astimezone()
    row_days = [date.fromisoformat(row["day"]) for row in rows]
    start_day = start_day or (min(row_days) if row_days else None)
    end_day = end_day or ((max(row_days) + timedelta(days=1)) if row_days else None)
    groups: dict[str, dict] = {}
    expected_by_day: dict[str, float] = {}

    current_day = start_day
    while current_day is not None and end_day is not None and current_day < end_day:
        key = current_day.strftime("%Y-%m") if group_by_month else current_day.isoformat()
        group = groups.setdefault(
            key,
            {
                "label": key,
                **{field: 0.0 for field in ENERGY_FIELDS},
                "sample_count": 0,
                "integrated_seconds": 0.0,
                "expected_seconds": 0.0,
                "days_with_data": 0,
                "day_count": 0,
            },
        )
        day_start = datetime.combine(current_day, time.min, tzinfo=now.tzinfo)
        day_end = day_start + timedelta(days=1)
        expected_end = min(day_end, now)
        day_expected_seconds = max(0.0, (expected_end - day_start).total_seconds())
        expected_by_day[current_day.isoformat()] = day_expected_seconds
        group["expected_seconds"] += day_expected_seconds
        group["day_count"] += 1
        current_day += timedelta(days=1)

    for row in rows:
        key = row["day"][:7] if group_by_month else row["day"]
        group = groups.setdefault(
            key,
            {
                "label": key,
                **{field: 0.0 for field in ENERGY_FIELDS},
                "sample_count": 0,
                "integrated_seconds": 0.0,
                "expected_seconds": 86400.0,
                "days_with_data": 0,
                "day_count": 1,
            },
        )
        for field in ENERGY_FIELDS:
            group[field] += _number(row.get(field))
        group["sample_count"] += int(row.get("sample_count") or 0)
        group["integrated_seconds"] += _number(row.get("integrated_seconds"))
        group["days_with_data"] += 1

    points = []
    for key in sorted(groups):
        group = groups[key]
        points.append({
            "label": group["label"],
            "pv_kwh": round(group["pv_wh"] / 1000, 3),
            "load_kwh": round(group["load_wh"] / 1000, 3),
            "grid_import_kwh": round(group["grid_import_wh"] / 1000, 3),
            "grid_export_kwh": round(group["grid_export_wh"] / 1000, 3),
            "battery_charge_kwh": round(group["battery_charge_wh"] / 1000, 3),
            "battery_discharge_kwh": round(group["battery_discharge_wh"] / 1000, 3),
            "sample_count": group["sample_count"],
            "has_data": bool(group["sample_count"]),
            "coverage_percent": round(
                min(100.0, group["integrated_seconds"] / group["expected_seconds"] * 100), 1
            ) if group["expected_seconds"] else 0.0,
        })

    totals = {field: sum(_number(row.get(field)) for row in rows) / 1000 for field in ENERGY_FIELDS}
    stats = {
        "pv_kwh": round(totals["pv_wh"], 3),
        "load_kwh": round(totals["load_wh"], 3),
        "grid_import_kwh": round(totals["grid_import_wh"], 3),
        "grid_export_kwh": round(totals["grid_export_wh"], 3),
        "battery_charge_kwh": round(totals["battery_charge_wh"], 3),
        "battery_discharge_kwh": round(totals["battery_discharge_wh"], 3),
    }
    stats["self_consumption_kwh"] = round(max(0.0, stats["pv_kwh"] - stats["grid_export_kwh"]), 3)
    stats["self_consumption_percent"] = round(
        stats["self_consumption_kwh"] / stats["pv_kwh"] * 100, 1
    ) if stats["pv_kwh"] else 0.0
    soc_min = [row["soc_min_percent"] for row in rows if row.get("soc_min_percent") is not None]
    soc_max = [row["soc_max_percent"] for row in rows if row.get("soc_max_percent") is not None]
    stats.update({
        "soc_start_percent": rows[0].get("soc_start_percent") if rows else None,
        "soc_end_percent": rows[-1].get("soc_end_percent") if rows else None,
        "soc_min_percent": min(soc_min) if soc_min else None,
        "soc_max_percent": max(soc_max) if soc_max else None,
    })
    expected_seconds = sum(group["expected_seconds"] for group in groups.values())
    observed_seconds = sum(group["integrated_seconds"] for group in groups.values())
    missing_day_count = sum(
        group["day_count"] - group["days_with_data"] for group in groups.values()
    )
    rows_by_day = {row["day"]: row for row in rows}
    partial_day_count = sum(
        1
        for day_label, expected in expected_by_day.items()
        if expected and day_label in rows_by_day
        and _number(rows_by_day[day_label].get("integrated_seconds")) / expected < 0.99
    )
    return {
        "stats": stats,
        "points": points,
        "day_count": len(rows),
        "gap_statistics": {
            "coverage_percent": round(
                min(100.0, observed_seconds / expected_seconds * 100), 1
            ) if expected_seconds else 0.0,
            "missing_day_count": missing_day_count,
            "partial_day_count": partial_day_count,
            "observed_seconds": round(observed_seconds),
            "period_seconds": round(expected_seconds),
        },
    }


def build_energy_analytics(
    rows: list[dict],
    max_points: int = 720,
    max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
    range_start: datetime | None = None,
    range_end: datetime | None = None,
    now: datetime | None = None,
) -> dict:
    """Integrate power readings and prepare a compact daily chart payload."""
    totals_wh = {
        "pv_kwh": 0.0,
        "load_kwh": 0.0,
        "grid_import_kwh": 0.0,
        "grid_export_kwh": 0.0,
        "battery_charge_kwh": 0.0,
        "battery_discharge_kwh": 0.0,
    }
    integrated_seconds = 0.0

    for previous, current in zip(rows, rows[1:]):
        previous_time = datetime.fromisoformat(previous["timestamp"])
        current_time = datetime.fromisoformat(current["timestamp"])
        delta_seconds = (current_time - previous_time).total_seconds()
        if delta_seconds <= 0 or delta_seconds > max_gap_seconds:
            continue

        previous_data = previous["parsed"]
        current_data = current["parsed"]
        pv_w = (_nested(previous_data, POWER_FIELDS["pv_kwh"]) + _nested(current_data, POWER_FIELDS["pv_kwh"])) / 2
        load_w = (_nested(previous_data, POWER_FIELDS["load_kwh"]) + _nested(current_data, POWER_FIELDS["load_kwh"])) / 2
        grid_w = (_nested(previous_data, POWER_FIELDS["grid_w"]) + _nested(current_data, POWER_FIELDS["grid_w"])) / 2
        battery_w = (_nested(previous_data, POWER_FIELDS["battery_w"]) + _nested(current_data, POWER_FIELDS["battery_w"])) / 2
        hours = delta_seconds / 3600

        totals_wh["pv_kwh"] += max(0.0, pv_w) * hours
        totals_wh["load_kwh"] += max(0.0, load_w) * hours
        totals_wh["grid_import_kwh"] += max(0.0, grid_w) * hours
        totals_wh["grid_export_kwh"] += max(0.0, -grid_w) * hours
        totals_wh["battery_charge_kwh"] += max(0.0, battery_w) * hours
        totals_wh["battery_discharge_kwh"] += max(0.0, -battery_w) * hours
        integrated_seconds += delta_seconds

    stats = {key: round(value / 1000, 3) for key, value in totals_wh.items()}
    stats["self_consumption_kwh"] = round(
        max(0.0, stats["pv_kwh"] - stats["grid_export_kwh"]), 3
    )
    stats["self_consumption_percent"] = round(
        stats["self_consumption_kwh"] / stats["pv_kwh"] * 100, 1
    ) if stats["pv_kwh"] else 0.0

    soc_values = [
        _nested(row["parsed"], ("soc_percent",))
        for row in rows
        if row["parsed"].get("soc_percent") is not None
    ]
    stats.update({
        "soc_start_percent": round(soc_values[0], 1) if soc_values else None,
        "soc_end_percent": round(soc_values[-1], 1) if soc_values else None,
        "soc_min_percent": round(min(soc_values), 1) if soc_values else None,
        "soc_max_percent": round(max(soc_values), 1) if soc_values else None,
    })

    return {
        "stats": stats,
        "points": [_chart_point(row) for row in _sample_evenly(rows, max_points)],
        "sample_count": len(rows),
        "integrated_seconds": round(integrated_seconds),
        "first_timestamp": rows[0]["timestamp"] if rows else None,
        "last_timestamp": rows[-1]["timestamp"] if rows else None,
        "gap_statistics": build_gap_statistics(
            rows,
            range_start=range_start,
            range_end=range_end,
            max_gap_seconds=max_gap_seconds,
            now=now,
        ),
    }
