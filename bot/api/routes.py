import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse

from bot.config.settings import Settings

router = APIRouter()

_CONFIG_PATH = Path("config.json")

_STATUS_DEFAULTS: dict = {
    "engine_running": False,
    "trading_active": False,
    "license_valid": False,
    "mt5_connected": False,
    "supabase_connected": False,
    "pending_count": 0,
    "open_count": 0,
    "trailing_count": 0,
}


@router.get("/api/status")
async def get_status(request: Request) -> dict:
    last = request.app.state.status_broadcaster.last_msg
    return last if last is not None else _STATUS_DEFAULTS


@router.get("/api/config")
async def get_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except FileNotFoundError:
        raise HTTPException(404, "config.json not found")


@router.put("/api/config")
async def update_config(config: Settings) -> dict:
    _CONFIG_PATH.write_text(config.model_dump_json(indent=2))
    return {"ok": True}


@router.post("/api/engine/start")
async def engine_start(request: Request) -> dict:
    request.app.state.engine.start()
    return {"ok": True}


@router.post("/api/engine/stop")
async def engine_stop(request: Request) -> dict:
    request.app.state.engine.stop()
    return {"ok": True}


@router.get("/api/logs")
async def stream_logs(request: Request):
    gen = request.app.state.log_broadcaster.make_generator("log")
    return EventSourceResponse(gen)


@router.get("/api/status/stream")
async def stream_status(request: Request):
    gen = request.app.state.status_broadcaster.make_generator("status")
    return EventSourceResponse(gen)
