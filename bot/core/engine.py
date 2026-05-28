import asyncio
import logging
from typing import Any

from bot.config.settings import Settings, load_config
from bot.core.reconciler import Reconciler
from bot.core.sync_cycle import SyncCycle
from bot.db.sqlite import SQLiteDB
from bot.db.supabase import SupabaseDB
from bot.mt5.client import MT5Client
from bot.tp.engine import TPEngine
from bot.utils.time_utils import MarketScheduler

logger = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        mt5_client: MT5Client,
        supabase: SupabaseDB,
        sqlite: SQLiteDB,
        config: Settings,
        tp_engine: TPEngine,
        license_validator: Any | None = None,
    ) -> None:
        self._mt5 = mt5_client
        self._supabase = supabase
        self._sqlite = sqlite
        self._config = config
        self._tp = tp_engine
        self._license = license_validator
        self._scheduler = MarketScheduler(config.spread_hour)
        self._sync_cycle = SyncCycle()
        self._reconciler = Reconciler()
        self._trading_active = True
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        # FastAPI app; set externally via create_app(engine) in main.py
        self.app: Any | None = None
        # SSE consumers read from this queue
        self.status_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    def start(self) -> None:
        self._trading_active = True
        logger.info("Trading active")

    def stop(self) -> None:
        self._trading_active = False
        logger.info("Trading paused (position management continues)")

    def shutdown(self) -> None:
        """Signal the engine to stop all tasks and exit. Safe to call from any thread."""
        self._trading_active = False
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._cancel_tasks)

    def _cancel_tasks(self) -> None:
        for task in self._tasks:
            task.cancel()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def trading_active(self) -> bool:
        return self._trading_active

    async def run_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._running = True
        try:
            await self._sqlite.init_schema()
            await self._supabase.create_pool()
            await self._reconciler.reconcile(self._mt5, self._sqlite)

            if self._license is not None:
                acct = self._mt5.account_info()
                mt5_account = acct.login if acct else 0
                await self._license.validate(self._config.license_key, mt5_account)

            tasks = [
                asyncio.create_task(self._sync_loop(), name="sync_loop"),
                asyncio.create_task(self._tp_loop(), name="tp_loop"),
            ]
            if self._license is not None:
                tasks.append(asyncio.create_task(
                    self._license.heartbeat_loop(
                        self._config.polling.license_heartbeat_seconds
                    ),
                    name="license_heartbeat",
                ))
            if self.app is not None:
                tasks.append(asyncio.create_task(
                    self._serve_api(), name="api_server"
                ))
            self._tasks = tasks

            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._running = False
            await self._supabase.close()
            await self._sqlite.close()

    async def _sync_loop(self) -> None:
        while True:
            try:
                new_config = load_config()
                if new_config:
                    self._config = new_config
                    self._scheduler = MarketScheduler(new_config.spread_hour)

                placement_active = self._trading_active and (
                    self._license is None
                    or getattr(self._license, "license_valid", True)
                )

                result = await self._sync_cycle.run(
                    self._supabase,
                    self._sqlite,
                    self._mt5,
                    self._config,
                    self._scheduler,
                    placement_active=placement_active,
                )
                if result.placed or result.cancelled or result.filled or result.errors:
                    logger.info(
                        "Sync: placed=%d cancelled=%d filled=%d trailing=%d errors=%d",
                        result.placed, result.cancelled, result.filled,
                        result.new_trailing, result.errors,
                    )
                await self._broadcast_status()
            except Exception:
                logger.error("sync_loop error", exc_info=True)

            await asyncio.sleep(await self._active_interval())

    async def _tp_loop(self) -> None:
        while True:
            try:
                await self._tp.run_cycle(self._mt5, self._sqlite, self._config)
            except Exception:
                logger.error("tp_loop error", exc_info=True)

            await asyncio.sleep(await self._active_interval())

    async def _serve_api(self) -> None:
        import uvicorn
        cfg = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=8501,
            log_level="error",
            loop="none",  # reuse the existing asyncio loop
        )
        server = uvicorn.Server(cfg)
        await server.serve()

    async def _active_interval(self) -> float:
        active = await self._sqlite.get_all_active()
        if active:
            return float(self._config.polling.tp_active_interval_seconds)
        return float(self._config.polling.supabase_interval_seconds)

    async def _broadcast_status(self) -> None:
        active = await self._sqlite.get_all_active()
        pending_count = sum(1 for r in active if r["status"] == "pending")
        open_count = sum(1 for r in active if r["status"] == "filled")
        trailing_count = sum(
            1 for r in active if r["status"] == "filled" and r["is_trailing"]
        )
        status = {
            "engine_running": self._running,
            "trading_active": self._trading_active,
            "license_valid": getattr(self._license, "license_valid", True),
            "mt5_connected": self._mt5.ensure_connected(),
            "supabase_connected": self._supabase._pool is not None,
            "pending_count": pending_count,
            "open_count": open_count,
            "trailing_count": trailing_count,
        }
        try:
            self.status_queue.put_nowait(status)
        except asyncio.QueueFull:
            pass
