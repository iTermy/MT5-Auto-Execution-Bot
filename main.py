import asyncio
import logging
import sys
import threading
import time
import urllib.request
import webbrowser

import pystray
from PIL import Image

from bot.api.app import create_app
from bot.config.settings import load_config, load_dsn, load_license_url
from bot.core.engine import Engine
from bot.db.sqlite import SQLiteDB
from bot.db.supabase import SupabaseDB
from bot.license.validator import LicenseValidator
from bot.mt5.client import MT5Client
from bot.mt5.connection import MT5Connection
from bot.tp.engine import TPEngine
from bot.utils.logging import setup_logging

logger = logging.getLogger(__name__)

_API_URL = "http://localhost:8501"


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


def _run_engine(conn: MT5Connection, engine: Engine) -> None:
    if not conn.initialize():
        logger.critical("MT5 initialization failed — engine thread exiting")
        return
    try:
        asyncio.run(engine.run_forever())
    finally:
        conn.shutdown()


def main() -> None:
    setup_logging()

    config = load_config()
    if config is None:
        logger.critical("Failed to load config.json — copy config.example.json to config.json")
        sys.exit(1)

    dsn = load_dsn()
    license_url = load_license_url()

    conn = MT5Connection()
    mt5_client = MT5Client(conn)
    supabase = SupabaseDB(dsn)
    sqlite = SQLiteDB()
    tp_engine = TPEngine()
    license_validator = LicenseValidator(license_url)

    engine = Engine(
        mt5_client=mt5_client,
        supabase=supabase,
        sqlite=sqlite,
        config=config,
        tp_engine=tp_engine,
        license_validator=license_validator,
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
        args=(conn, engine),
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
