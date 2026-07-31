"""Energy integration and chart downsampling for historical telemetry."""

from __future__ import annotations

from datetime import datetime
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


def build_period_analytics(rows: list[dict], group_by_month: bool = False) -> dict:
    """Combine persisted daily aggregates into weekly/monthly/all-time data."""
    groups: dict[str, dict] = {}
    for row in rows:
        key = row["day"][:7] if group_by_month else row["day"]
        group = groups.setdefault(
            key,
            {"label": key, **{field: 0.0 for field in ENERGY_FIELDS}, "sample_count": 0},
        )
        for field in ENERGY_FIELDS:
            group[field] += _number(row.get(field))
        group["sample_count"] += int(row.get("sample_count") or 0)

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
    return {"stats": stats, "points": points, "day_count": len(rows)}


def build_energy_analytics(
    rows: list[dict],
    max_points: int = 720,
    max_gap_seconds: float = 30.0,
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
    }
