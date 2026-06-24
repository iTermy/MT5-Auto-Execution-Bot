import asyncio
import atexit
import ctypes
import logging
import platform
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import pystray
from PIL import Image

from bot.api.app import create_app
from bot.config.constants import BOT_VERSION
from bot.config.settings import (
    load_config,
    load_dsn,
    load_license_url,
    load_update_manifest_url,
    migrate_config,
)
from bot.core.engine import Engine
from bot.db.sqlite import SQLiteDB
from bot.db.supabase import SupabaseDB
from bot.db.tp_outcomes_writer import TPOutcomesWriter
from bot.license.validator import LicenseValidator
from bot.mt5.client import MT5Client
from bot.mt5.connection import MT5Connection
from bot.tp.engine import TPEngine
from bot.tp.finalizer import TPFinalizer
from bot.update.checker import UpdateChecker
from bot.utils.logging import setup_logging

logger = logging.getLogger(__name__)

_API_URL = "http://localhost:8501"
_LOCK_PATH = Path(tempfile.gettempdir()) / "mt5bot.lock"


def _acquire_single_instance_lock() -> int | None:
    """Take an exclusive lock on a temp file to prevent a second MT5Bot.exe
    from running concurrently. Returns the file descriptor on success or None
    if another instance already holds the lock."""
    import msvcrt

    fd = None
    try:
        fd = _LOCK_PATH.open("w+")
        msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        if fd is not None:
            fd.close()
        return None

    def _release() -> None:
        try:
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        try:
            fd.close()
        except Exception:
            pass

    atexit.register(_release)
    return fd


def _make_tray_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (18, 28, 50, 255))
    return img


def _wait_for_api(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{_API_URL}/api/status", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def _run_engine(engine: Engine) -> None:
    try:
        asyncio.run(engine.run_forever())
    except Exception:
        # The tray (main thread) stays alive, so without this the engine would die
        # silently and the bot would just look idle. Make the crash diagnosable.
        logger.critical("Engine thread crashed", exc_info=True)


def _ensure_config_exists() -> None:
    target = Path("config.json")
    if target.exists():
        return
    bundle_dir = Path(getattr(sys, "_MEIPASS", "."))
    template = bundle_dir / "config.example.json"
    if not template.exists():
        return
    shutil.copyfile(template, target)
    logger.info("Created config.json from bundled template at %s", target.resolve())


def main() -> None:
    setup_logging()
    logger.info(
        "MT5Bot %s starting | Python %s | %s | cwd=%s",
        BOT_VERSION,
        platform.python_version(),
        platform.platform(),
        Path.cwd(),
    )

    if _acquire_single_instance_lock() is None:
        ctypes.windll.user32.MessageBoxW(
            0,
            "MT5 Auto Execution Bot is already running. Check your system tray.",
            "MT5Bot",
            0x40,  # MB_ICONINFORMATION
        )
        sys.exit(0)

    _ensure_config_exists()
    migrate_config()

    config = load_config()
    if config is None:
        logger.critical("Failed to load config.json — copy config.example.json to config.json")
        sys.exit(1)

    dsn = load_dsn()
    license_url = load_license_url()
    update_manifest_url = load_update_manifest_url()

    conn = MT5Connection(config.mt5_terminal_path)
    mt5_client = MT5Client(conn)
    supabase = SupabaseDB(dsn)
    sqlite = SQLiteDB()
    tp_outcomes_writer = TPOutcomesWriter(supabase)
    tp_engine = TPEngine(outcomes_writer=tp_outcomes_writer)
    tp_finalizer = TPFinalizer(tp_outcomes_writer)
    license_validator = LicenseValidator(license_url)
    update_checker = UpdateChecker(update_manifest_url)

    engine = Engine(
        mt5_client=mt5_client,
        mt5_connection=conn,
        supabase=supabase,
        sqlite=sqlite,
        config=config,
        tp_engine=tp_engine,
        tp_finalizer=tp_finalizer,
        license_validator=license_validator,
        update_checker=update_checker,
    )
    engine.app = create_app(engine)

    def on_open(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(_API_URL)

    def on_exit(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        engine.shutdown()

    tray = pystray.Icon(
        name="mt5_bot",
        icon=_make_tray_icon(),
        title="MT5 Auto Execution Bot",
        menu=pystray.Menu(
            pystray.MenuItem("Open UI", on_open),
            pystray.MenuItem("Exit", on_exit),
        ),
    )
    engine.set_shutdown_callback(tray.stop)

    engine_thread = threading.Thread(
        target=_run_engine,
        args=(engine,),
        name="engine",
        daemon=False,
    )
    engine_thread.start()

    if _wait_for_api():
        webbrowser.open(_API_URL)
    else:
        logger.warning("FastAPI did not become ready within 30s — open %s manually", _API_URL)

    tray.run()

    # Reached after on_exit calls icon.stop()
    engine_thread.join(timeout=10)
    sys.exit(0)


if __name__ == "__main__":
    main()
