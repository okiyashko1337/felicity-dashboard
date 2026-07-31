"""FastAPI server for live and simulated Felicity telemetry."""

import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from config import DB_PATH
from analytics import build_energy_analytics
from database import (
    get_latest_telemetry,
    get_latest_system_snapshot,
    get_system_history,
    get_telemetry_history,
    get_telemetry_range,
    initialize_database,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database(DB_PATH)
    yield


app = FastAPI(title="Felicity Energy Dashboard API", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


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


@app.get("/api/history")
def history(limit: int = Query(default=180, ge=2, le=3600)) -> list[dict]:
    try:
        return get_telemetry_history(limit, DB_PATH)
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
        result = build_energy_analytics(rows, max_points=max_points)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Database error: {error}") from error
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        **result,
    }


@app.get("/api/status")
def status() -> dict:
    snapshot = get_latest_telemetry(DB_PATH)
    if snapshot is None:
        return {"online": False, "source": None, "age_seconds": None}

    timestamp = datetime.fromisoformat(snapshot["timestamp"])
    age_seconds = max(
        0.0,
        (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds(),
    )
    return {
        "online": age_seconds <= 10,
        "source": snapshot["source"],
        "age_seconds": round(age_seconds, 1),
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
