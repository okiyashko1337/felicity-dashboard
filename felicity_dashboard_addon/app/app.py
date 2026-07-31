"""FastAPI server for live and simulated Felicity telemetry."""

import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from config import DB_PATH
from database import (
    get_latest_telemetry,
    get_latest_system_snapshot,
    get_system_history,
    get_telemetry_history,
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
