import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

if sys.platform == "win32":
    import winreg
else:
    winreg = None  # type: ignore[assignment]

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
    found: set[Path] = set()
    _scan_origin_files(found)
    _scan_uninstall_registry(found)
    _scan_install_roots(found)
    return {"paths": sorted(str(p) for p in found)}


def _add_install_dir(install_dir: Path, found: set[Path]) -> None:
    candidate = install_dir / "terminal64.exe"
    try:
        if candidate.is_file():
            found.add(candidate.resolve())
    except OSError:
        pass


# ---- Source 1: %APPDATA%\MetaQuotes\Terminal\<hash>\origin.txt ----
# MT5 writes the absolute install path here for every terminal it has
# launched. Authoritative regardless of where the broker installed to.


def _scan_origin_files(found: set[Path]) -> None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return
    meta_root = Path(appdata) / "MetaQuotes" / "Terminal"
    try:
        entries = list(meta_root.iterdir())
    except OSError:
        return
    for sub in entries:
        try:
            if not sub.is_dir():
                continue
        except OSError:
            continue
        if sub.name.lower() in {"common", "community"}:
            continue
        origin = sub / "origin.txt"
        try:
            raw = origin.read_bytes()
        except OSError:
            continue
        text = _decode_origin(raw).strip().strip('"')
        if text:
            _add_install_dir(Path(text), found)


def _decode_origin(raw: bytes) -> str:
    for enc in ("utf-16", "utf-8-sig", "utf-8", "mbcs", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


# ---- Source 2: Windows Uninstall registry ----
# Every MetaTrader installer (broker-branded or plain) writes a
# DisplayName + InstallLocation here. Covers terminals that exist but
# have never been launched, so origin.txt doesn't exist yet.

_REG_NAME_HINTS = ("metatrader", "mt5", "metaquotes")


def _scan_uninstall_registry(found: set[Path]) -> None:
    if winreg is None:
        return
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    bases = (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
    )
    for hive, access in bases:
        try:
            base = winreg.OpenKey(hive, sub, 0, access)
        except OSError:
            continue
        try:
            _walk_uninstall_key(base, found)
        finally:
            base.Close()


def _walk_uninstall_key(base, found: set[Path]) -> None:
    i = 0
    while True:
        try:
            name = winreg.EnumKey(base, i)
        except OSError:
            return
        i += 1
        try:
            with winreg.OpenKey(base, name) as key:
                display = _read_reg_str(key, "DisplayName").lower()
                if not any(h in display for h in _REG_NAME_HINTS):
                    continue
                loc = _read_reg_str(key, "InstallLocation")
                if loc:
                    _add_install_dir(Path(loc), found)
                    continue
                uninstall = _read_reg_str(key, "UninstallString")
                parent = _parent_from_uninstall(uninstall)
                if parent is not None:
                    _add_install_dir(parent, found)
        except OSError:
            continue


def _read_reg_str(key, name: str) -> str:
    try:
        val, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(val).strip().strip('"') if val else ""


def _parent_from_uninstall(uninstall: str) -> Path | None:
    s = uninstall.strip().strip('"')
    if not s:
        return None
    if s.lower().endswith(".exe"):
        try:
            return Path(s).parent
        except (OSError, ValueError):
            return None
    return None


# ---- Source 3: filesystem scan ----
# Fallback for portable installs that aren't in the registry and have
# never been launched. Walks to depth 3 under the standard install roots.

_SCAN_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "windowsapps",
        "modifiablewindowsapps",
        "windowsappsdeleted",
        "packages",
        "common files",
        "windows defender",
        "windows nt",
        "windows mail",
        "windows photo viewer",
        "windows portable devices",
        "windows security",
        "windows sidebar",
        "internet explorer",
    }
)

_SCAN_MAX_DEPTH = 3


def _scan_install_roots(found: set[Path]) -> None:
    roots: list[Path] = []
    seen: set[Path] = set()
    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        val = os.environ.get(env_var)
        if not val:
            continue
        root = Path(val)
        if root in seen:
            continue
        seen.add(root)
        if root.exists():
            roots.append(root)
    for root in roots:
        _scan_for_terminal(root, found, _SCAN_MAX_DEPTH)


def _scan_for_terminal(folder: Path, found: set[Path], depth: int) -> None:
    _add_install_dir(folder, found)
    if depth <= 0:
        return
    for sub in _safe_subdirs(folder):
        _scan_for_terminal(sub, found, depth - 1)


def _safe_subdirs(path: Path) -> list[Path]:
    out: list[Path] = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.name.lower() in _SCAN_SKIP_DIRS:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        out.append(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        return out
    return out


@router.get("/api/logs")
async def stream_logs(request: Request):
    gen = request.app.state.log_broadcaster.make_generator("log")
    return EventSourceResponse(gen)


@router.get("/api/status/stream")
async def stream_status(request: Request):
    gen = request.app.state.status_broadcaster.make_generator("status")
    return EventSourceResponse(gen)
