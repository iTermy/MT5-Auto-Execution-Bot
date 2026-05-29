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


@router.post("/api/engine/shutdown")
async def engine_shutdown(request: Request) -> dict:
    request.app.state.engine.shutdown()
    return {"ok": True}


@router.get("/api/dashboard")
async def get_dashboard(request: Request) -> dict:
    cache = request.app.state.engine.dashboard_cache
    data = cache.data
    return {
        "account": data.account,
        "positions": data.positions,
        "pending_orders": data.pending_orders,
        "summary": data.summary,
        "updated_at": data.updated_at,
    }


@router.get("/api/history")
async def get_history(request: Request, from_date: str = "", to_date: str = "") -> dict:
    if not from_date:
        from_date = "2020-01-01T00:00:00"
    if not to_date:
        to_date = "2099-12-31T23:59:59"

    engine = request.app.state.engine
    rows = await engine._sqlite.get_order_history(from_date, to_date)

    trades = []
    total_pnl = 0.0
    wins = 0
    losses = 0

    for row in rows:
        pnl = row["realized_pnl"] or 0.0
        ch = row["channel_id"]
        trades.append({
            "id": row["id"],
            "signal_id": row["signal_id"],
            "symbol": row["symbol"] or "",
            "direction": row["order_type"],
            "lot_size": row["lot_size"],
            "placed_at": row["placed_at"],
            "filled_at": row["filled_at"] or "",
            "closed_at": row["cancelled_at"] or "",
            "status": row["status"],
            "is_scalp": bool(row["is_scalp"]),
            "realized_pnl": pnl,
            "channel_id": str(ch) if ch is not None else None,
        })
        if row["status"] == "closed" and pnl != 0:
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

    return {
        "trades": trades,
        "stats": {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
        },
    }


@router.get("/api/logs")
async def stream_logs(request: Request):
    gen = request.app.state.log_broadcaster.make_generator("log")
    return EventSourceResponse(gen)


@router.get("/api/status/stream")
async def stream_status(request: Request):
    gen = request.app.state.status_broadcaster.make_generator("status")
    return EventSourceResponse(gen)
