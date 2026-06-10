import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from bot.config.constants import BOT_VERSION
from bot.config.settings import Settings

router = APIRouter()

_CONFIG_PATH = Path("config.json")

_STATUS_DEFAULTS: dict = {
    "engine_running": False,
    "trading_active": False,
    "license_valid": False,
    "license_status": "error",
    "license_message": "",
    "mt5_connected": False,
    "supabase_connected": False,
    "pending_count": 0,
    "open_count": 0,
    "trailing_count": 0,
    "bot_version": BOT_VERSION,
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
        raise HTTPException(404, "config.json not found") from None


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
        "nearby_signals": data.nearby_signals,
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
        signal_id = row["signal_id"]
        signal_pnl = row["total_pnl"] or 0.0
        closed_count = row["closed_count"] or 0
        cancelled_count = row["cancelled_count"] or 0
        ch = row["channel_id"]
        # Signal status: "closed" if any limit was filled-then-closed; otherwise
        # "cancelled" (the whole signal was rejected/expired before any fill).
        status = "closed" if closed_count > 0 else "cancelled"
        trades.append(
            {
                "signal_id": signal_id,
                "symbol": row["symbol"] or "",
                "direction": row["direction"],
                "total_lots": row["total_lots"] or 0.0,
                "placed_at": row["placed_at"],
                "filled_at": row["first_filled_at"] or "",
                "closed_at": row["last_closed_at"] or "",
                "status": status,
                "signal_type": row["signal_type"],
                "total_pnl": signal_pnl,
                "fills_count": closed_count,
                "cancelled_count": cancelled_count,
                "channel_id": str(ch) if ch is not None else None,
            }
        )
        if status == "closed":
            total_pnl += signal_pnl
            if signal_pnl > 0:
                wins += 1
            elif signal_pnl < 0:
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


@router.get("/api/mt5/terminals")
async def list_mt5_terminals() -> dict:
    roots: list[Path] = []
    seen_roots: set[Path] = set()
    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        val = os.environ.get(env_var)
        if not val:
            continue
        root = Path(val)
        if root in seen_roots:
            continue
        seen_roots.add(root)
        roots.append(root)

    found: set[Path] = set()
    for root in roots:
        if root.exists():
            _scan_for_terminal(root, max_depth=3, found=found)

    return {"paths": sorted(str(p) for p in found)}


def _scan_for_terminal(start: Path, max_depth: int, found: set[Path]) -> None:
    """Walk *start* up to *max_depth* directory levels deep, collecting any
    `terminal64.exe` files. Uses os.scandir so a PermissionError on one
    subdirectory (e.g. C:\\Program Files\\WindowsApps) does not abort the
    whole scan — only that subtree is skipped."""
    stack: list[tuple[Path, int]] = [(start, 0)]
    target = "terminal64.exe"
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False) and entry.name.lower() == target:
                            found.add(Path(entry.path))
                        elif depth < max_depth and entry.is_dir(follow_symlinks=False):
                            stack.append((Path(entry.path), depth + 1))
                    except OSError:
                        continue
        except OSError:
            continue


@router.get("/api/logs")
async def stream_logs(request: Request):
    gen = request.app.state.log_broadcaster.make_generator("log")
    return EventSourceResponse(gen)


@router.get("/api/status/stream")
async def stream_status(request: Request):
    gen = request.app.state.status_broadcaster.make_generator("status")
    return EventSourceResponse(gen)
