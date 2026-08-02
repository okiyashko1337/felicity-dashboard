"""FastAPI server for live and simulated Felicity telemetry."""

from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from config import DB_PATH
from analytics import build_energy_analytics, build_gap_statistics, build_period_analytics
from database import (
    get_latest_telemetry,
    get_latest_system_snapshot,
    get_system_range,
    get_system_history,
    get_parsed_telemetry_history,
    get_telemetry_timestamps,
    get_telemetry_history,
    get_telemetry_range,
    get_telemetry_range_sampled,
    get_energy_daily,
    ensure_energy_daily,
    initialize_database,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
APP_VERSION = os.environ.get("FELICITY_APP_VERSION", "dev")
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Felicity-UI-Version": APP_VERSION,
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database(DB_PATH)
    ensure_energy_daily(DB_PATH)
    yield


app = FastAPI(title="Felicity Energy Dashboard API", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(
        html.replace("__FELICITY_APP_VERSION__", APP_VERSION),
        headers=NO_CACHE_HEADERS,
    )


@app.get("/api/current")
def current() -> dict:
    try:
        snapshot = get_latest_telemetry(DB_PATH)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No telemetry yet. Start collector.py or simulator.py.",
        )
    return snapshot


@app.get("/api/device/current")
def device_current() -> dict:
    """Return the latest snapshot without raw packets for constrained clients."""
    snapshot = get_latest_telemetry(DB_PATH)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No telemetry yet")
    return {
        "id": snapshot["id"],
        "timestamp": snapshot["timestamp"],
        "source": snapshot["source"],
        "parsed": snapshot["parsed"],
    }


def _value(data: dict, *path: str) -> float:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return 0.0
        current = current.get(key)
    try:
        return float(current or 0)
    except (TypeError, ValueError):
        return 0.0


def _device_chart_sample(metric: str, data: dict) -> list[float]:
    if metric == "pv":
        return [_value(data, "pv_power_w", key) for key in ("total", "pv1", "pv2")]
    if metric == "load":
        return [_value(data, "load_power_w", key) for key in ("total", "l1", "l2", "l3")]
    if metric == "battery":
        return [_value(data, "soc_percent"), _value(data, "battery_power_w")]
    if metric == "grid":
        return [
            *[_value(data, "grid_voltage_v", key) for key in ("l1", "l2", "l3")],
            _value(data, "grid_power_w", "total"),
        ]
    if metric == "today":
        return [_value(data, "pv_power_w", "total"), _value(data, "load_power_w", "total")]
    raise HTTPException(status_code=422, detail=f"Unsupported chart metric: {metric}")


@app.get("/api/device/chart")
def device_chart(
    metric: Literal["pv", "load", "battery", "grid", "system", "today"],
    limit: int = Query(default=90, ge=2, le=180),
) -> dict:
    """Return compact chart samples tailored to the Nextion client."""
    if metric == "system":
        rows = get_system_history(limit, DB_PATH)
        samples = [
            [
                _value(row["data"], "cpu_percent"),
                _value(row["data"], "memory", "percent"),
                _value(row["data"], "cpu_temperature_c"),
                _value(row["data"], "disk", "percent"),
            ]
            for row in rows
        ]
    else:
        rows = get_parsed_telemetry_history(limit, DB_PATH)
        samples = [_device_chart_sample(metric, row["parsed"]) for row in rows]
    return {
        "metric": metric,
        "start": rows[0]["timestamp"] if rows else None,
        "end": rows[-1]["timestamp"] if rows else None,
        "samples": samples,
    }


def _gap_coverage_samples(
    gaps: list[dict], start: datetime, end: datetime, count: int
) -> list[list[float]]:
    if count <= 0 or end <= start:
        return []
    bin_seconds = (end - start).total_seconds() / count
    intervals = [
        (datetime.fromisoformat(gap["start"]), datetime.fromisoformat(gap["end"]))
        for gap in gaps
        if gap.get("start") and gap.get("end")
    ]
    samples: list[list[float]] = []
    for index in range(count):
        bin_start = start + timedelta(seconds=index * bin_seconds)
        bin_end = start + timedelta(seconds=(index + 1) * bin_seconds)
        missing = 0.0
        for gap_start, gap_end in intervals:
            overlap_start = max(bin_start, gap_start.astimezone(bin_start.tzinfo))
            overlap_end = min(bin_end, gap_end.astimezone(bin_end.tzinfo))
            missing += max(0.0, (overlap_end - overlap_start).total_seconds())
        covered = max(0.0, bin_seconds - min(bin_seconds, missing))
        samples.append([round(covered / bin_seconds * 100, 1)])
    return samples


@app.get("/api/device/gaps")
def device_gaps(bins: int = Query(default=30, ge=2, le=60)) -> dict:
    """Return today's compact telemetry-coverage summary for the Nextion."""
    now = datetime.now().astimezone()
    start = datetime.combine(now.date(), datetime.min.time(), tzinfo=now.tzinfo)
    try:
        rows = get_telemetry_timestamps(start, now, DB_PATH)
        stats = build_gap_statistics(rows, range_start=start, range_end=now, now=now)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error
    latest = stats["gaps"][-1] if stats["gaps"] else None
    return {
        "start": start.isoformat(),
        "end": now.isoformat(),
        "coverage_percent": stats["coverage_percent"],
        "gap_count": stats["gap_count"],
        "longest_gap_seconds": stats["longest_gap_seconds"],
        "latest_start": latest["start"] if latest else None,
        "latest_end": latest["end"] if latest else None,
        "samples": _gap_coverage_samples(stats["gaps"], start, now, bins),
    }


@app.get("/api/history")
def history(limit: int = Query(default=180, ge=2, le=3600)) -> list[dict]:
    try:
        return get_telemetry_history(limit, DB_PATH)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error


@app.get("/api/detail/history")
def detail_history(
    start: datetime,
    end: datetime,
    max_points: int = Query(default=900, ge=60, le=1440),
) -> list[dict]:
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="start and end must include timezone")
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    if (end - start).total_seconds() > 36 * 3600:
        raise HTTPException(status_code=422, detail="range cannot exceed 36 hours")
    try:
        return get_telemetry_range_sampled(start, end, max_points, DB_PATH)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error


@app.get("/api/analytics")
def analytics(
    start: datetime,
    end: datetime,
    max_points: int = Query(default=720, ge=60, le=1440),
) -> dict:
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="start and end must include timezone")
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    if (end - start).total_seconds() > 36 * 3600:
        raise HTTPException(status_code=422, detail="range cannot exceed 36 hours")
    try:
        rows = get_telemetry_range(start, end, DB_PATH)
        result = build_energy_analytics(
            rows,
            max_points=max_points,
            range_start=start,
            range_end=end,
        )
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        **result,
    }


@app.get("/api/analytics/period")
def analytics_period(
    period: Literal["week", "month", "all"],
    anchor: Optional[date] = None,
) -> dict:
    anchor = anchor or date.today()
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=7)
    elif period == "month":
        start = anchor.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        start = end = None

    try:
        rows = get_energy_daily(
            start.isoformat() if start else None,
            end.isoformat() if end else None,
            DB_PATH,
        )
        result = build_period_analytics(
            rows,
            group_by_month=period == "all",
            start_day=start if start else (date.fromisoformat(rows[0]["day"]) if rows else None),
            end_day=end if end else (date.fromisoformat(rows[-1]["day"]) + timedelta(days=1) if rows else None),
        )
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error
    return {
        "period": period,
        "anchor": anchor.isoformat(),
        "start": start.isoformat() if start else (rows[0]["day"] if rows else None),
        "end": end.isoformat() if end else (rows[-1]["day"] if rows else None),
        **result,
    }


@app.get("/api/analytics/day-summary")
def analytics_day_summary(day: date) -> dict:
    """Return one persisted daily aggregate without scanning raw telemetry."""
    end = day + timedelta(days=1)
    try:
        rows = get_energy_daily(day.isoformat(), end.isoformat(), DB_PATH)
        result = build_period_analytics(rows, start_day=day, end_day=end)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error
    return {"day": day.isoformat(), **result}


@app.get("/api/status")
def status() -> dict:
    snapshot = get_latest_telemetry(DB_PATH)
    if snapshot is None:
        return {
            "online": False,
            "source": None,
            "age_seconds": None,
            "app_version": APP_VERSION,
        }

    timestamp = datetime.fromisoformat(snapshot["timestamp"])
    age_seconds = max(
        0.0,
        (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds(),
    )
    return {
        "online": age_seconds <= 10,
        "source": snapshot["source"],
        "age_seconds": round(age_seconds, 1),
        "app_version": APP_VERSION,
    }


@app.get("/api/system/current")
def system_current() -> dict:
    try:
        snapshot = get_latest_system_snapshot(DB_PATH)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No system telemetry yet. Start system_monitor.py.",
        )
    return snapshot


@app.get("/api/system/history")
def system_history(limit: int = Query(default=1440, ge=2, le=10080)) -> list[dict]:
    try:
        return get_system_history(limit, DB_PATH)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error


@app.get("/api/system/range")
def system_range(
    start: datetime,
    end: datetime,
    max_points: int = Query(default=900, ge=2, le=1440),
) -> list[dict]:
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="start and end must include timezone")
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    if (end - start).total_seconds() > 36 * 3600:
        raise HTTPException(status_code=422, detail="range cannot exceed 36 hours")
    try:
        return get_system_range(start, end, max_points, DB_PATH)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error
