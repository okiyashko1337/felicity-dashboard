from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from database import get_latest_snapshot, initialize_database

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Felicity Inverter Dashboard", lifespan=lifespan)


@app.get("/api/current")
def current() -> dict:
    snapshot = get_latest_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No inverter data yet")
    return snapshot


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

