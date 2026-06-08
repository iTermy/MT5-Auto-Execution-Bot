import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from bot.config.constants import BOT_VERSION
from bot.config.settings import Settings, load_config
from bot.core.dashboard_cache import DashboardCache
from bot.core.reconciler import Reconciler
from bot.core.sync_cycle import SyncCycle
from bot.db.sqlite import SQLiteDB
from bot.db.supabase import SupabaseDB
from bot.mt5.client import MT5Client
from bot.mt5.connection import MT5Connection
from bot.tp.engine import TPEngine
from bot.utils.time_utils import MarketScheduler

_RETCODE_DONE = 10009  # mt5.TRADE_RETCODE_DONE
_USER_SNAPSHOT_INTERVAL = 300.0  # 5 min between user-table upserts

logger = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        mt5_client: MT5Client,
        mt5_connection: MT5Connection,
        supabase: SupabaseDB,
        sqlite: SQLiteDB,
        config: Settings,
        tp_engine: TPEngine,
        license_validator: Any | None = None,
    ) -> None:
        self._mt5 = mt5_client
        self._mt5_conn = mt5_connection
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
        self._shutdown_callback: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        # FastAPI app; set externally via create_app(engine) in main.py
        self.app: Any | None = None
        self.api_ready = asyncio.Event()
        self.dashboard_cache = DashboardCache()
        # SSE consumers read from this queue
        self.status_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        # License teardown state
        self._license_expired: bool = False
        self.shutdown_reason: str | None = None
        self._last_license_valid: bool = True
        # True after MT5 has been initialized; gates Supabase/sync/tp startup.
        self._engine_started: bool = False
        # monotonic timestamp of last successful user-snapshot upsert
        self._last_user_snapshot: float = 0.0

    def start(self) -> None:
        self._trading_active = True
        logger.info("Trading active")

    def stop(self) -> None:
        self._trading_active = False
        logger.info("Trading paused (position management continues)")

    def set_shutdown_callback(self, callback) -> None:
        self._shutdown_callback = callback

    def shutdown(self) -> None:
        """Signal the engine to stop all tasks and exit. Safe to call from any thread."""
        self._trading_active = False
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._cancel_tasks)
        if self._shutdown_callback is not None:
            self._shutdown_callback()

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
            # Start API server first so the frontend can connect before init logs
            api_task = None
            if self.app is not None:
                api_task = asyncio.create_task(self._serve_api(), name="api_server")
                try:
                    await asyncio.wait_for(self.api_ready.wait(), timeout=15.0)
                except TimeoutError:
                    if api_task.done() and api_task.exception():
                        logger.critical("API server failed to start: %s", api_task.exception())
                    else:
                        logger.critical("API server failed to start within 15s")
                    return

            await self._sqlite.init_schema()

            # Wait until a license key is configured before launching MT5 or
            # opening the Supabase pool. This keeps the UI responsive while the
            # user enters their credentials and prevents signal data from being
            # fetched without an active license.
            await self._wait_for_license_config()

            if not await self._wait_for_mt5_init():
                return

            try:
                await self._supabase.create_pool()
            except Exception:
                logger.critical("Supabase connection failed", exc_info=True)
                return

            await self._reconciler.reconcile(self._mt5, self._sqlite)

            if self._license is not None:
                acct = self._mt5.account_info()
                mt5_account = acct.login if acct else 0
                await self._license.validate(self._config.license_key, mt5_account)
                # Sync _last_license_valid to the real post-validate state so a failed
                # startup validate does not falsely trigger teardown on the first sync cycle.
                self._last_license_valid = self._license.license_valid

            self._engine_started = True

            tasks = [
                asyncio.create_task(self._sync_loop(), name="sync_loop"),
                asyncio.create_task(self._tp_loop(), name="tp_loop"),
                asyncio.create_task(self._reconcile_loop(), name="reconcile_loop"),
            ]
            if self._license is not None:
                tasks.append(
                    asyncio.create_task(
                        self._license.heartbeat_loop(
                            self._config.polling.license_heartbeat_seconds
                        ),
                        name="license_heartbeat",
                    )
                )
            if api_task is not None:
                tasks.append(api_task)
            self._tasks = tasks

            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._running = False
            try:
                await self._supabase.close()
            except Exception:
                pass
            try:
                await self._sqlite.close()
            except Exception:
                pass
            try:
                self._mt5_conn.shutdown()
            except Exception:
                pass

    async def _wait_for_mt5_init(self) -> bool:
        """Initialize MT5 with retry. On failure (e.g. wrong terminal path),
        keep retrying while reloading config so the user can fix the path via
        Settings without restarting the bot. Returns True once initialized,
        False if the engine is shut down before MT5 comes up."""
        logged_failure = False
        while self._running:
            self._mt5_conn.set_terminal_path(self._config.mt5_terminal_path)
            if self._mt5_conn.initialize():
                return True
            if not logged_failure:
                logger.warning(
                    "MT5 initialization failed (path=%r, error=%s) — will retry; "
                    "fix the path in Settings → MT5 terminal path",
                    self._config.mt5_terminal_path or "<auto-detect>",
                    self._mt5_conn.last_error,
                )
                logged_failure = True
            await self._broadcast_status()
            await asyncio.sleep(3.0)
            new_config = load_config()
            if new_config is not None:
                self._config = new_config
                self._scheduler = MarketScheduler(new_config.spread_hour)
        return False

    async def _wait_for_license_config(self) -> None:
        """Poll config.json until license_key is set. Broadcasts status so the UI
        can show the engine is awaiting credentials."""
        if self._config.license_key:
            return
        logger.info("Waiting for license key in config.json — engine paused")
        while not self._config.license_key:
            await self._broadcast_status()
            await asyncio.sleep(2.0)
            new_config = load_config()
            if new_config is not None:
                self._config = new_config
                self._scheduler = MarketScheduler(new_config.spread_hour)
        logger.info("License key configured — proceeding with engine startup")

    async def _sync_loop(self) -> None:
        while True:
            if self._license_expired:
                logger.info("Sync loop halted: license expired")
                return

            # Detect license flip from valid → invalid and run teardown
            if self._license is not None:
                current_valid = self._license.license_valid
                if self._last_license_valid and not current_valid:
                    self._last_license_valid = False
                    await self._license_teardown()
                    return
                self._last_license_valid = current_valid

            try:
                new_config = load_config()
                if new_config:
                    old_license_key = self._config.license_key
                    self._config = new_config
                    self._scheduler = MarketScheduler(new_config.spread_hour)
                    if (
                        self._license is not None
                        and new_config.license_key
                        and new_config.license_key != old_license_key
                    ):
                        acct = self._mt5.account_info()
                        mt5_account = acct.login if acct else 0
                        await self._license.validate(new_config.license_key, mt5_account)
                        self._last_license_valid = self._license.license_valid

                placement_active = self._trading_active and (
                    self._license is None or getattr(self._license, "license_valid", True)
                )

                result = await self._sync_cycle.run(
                    self._supabase,
                    self._sqlite,
                    self._mt5,
                    self._config,
                    self._scheduler,
                    placement_active=placement_active,
                )
                if (
                    result.placed
                    or result.cancelled
                    or result.filled
                    or result.new_trailing
                    or result.errors
                ):
                    logger.info(
                        "Sync: placed=%d cancelled=%d filled=%d trailing=%d errors=%d skipped=%d",
                        result.placed,
                        result.cancelled,
                        result.filled,
                        result.new_trailing,
                        result.errors,
                        result.skipped,
                    )
                await self._broadcast_status()
                await self._update_dashboard()
                await self._maybe_upsert_user_snapshot()
            except Exception:
                logger.error("sync_loop error", exc_info=True)

            await asyncio.sleep(await self._active_interval())

    async def _tp_loop(self) -> None:
        while True:
            try:
                config = self._config
                if not self._scheduler.is_spread_hour():
                    await self._tp.run_cycle(self._mt5, self._sqlite, config)
                else:
                    await self._tp.run_cycle(self._mt5, self._sqlite, config, crypto_only=True)
            except Exception:
                logger.error("tp_loop error", exc_info=True)

            await asyncio.sleep(await self._tp_interval())

    async def _serve_api(self) -> None:
        try:
            import uvicorn

            cfg = uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=8501,
                log_level="error",
                log_config=None,
                loop="none",
            )
            server = uvicorn.Server(cfg)
            await server.serve()
        except Exception:
            logger.error("API server crashed", exc_info=True)

    async def _reconcile_loop(self) -> None:
        """C2: orphan sweep every 60s. M1: full reconcile every 2h."""
        ORPHAN_INTERVAL = 60.0
        FULL_RECONCILE_INTERVAL = 2 * 3600.0
        last_full = time.monotonic()

        while True:
            await asyncio.sleep(ORPHAN_INTERVAL)
            try:
                swept = await self._reconciler.reconcile_orphans(self._mt5, self._sqlite)
                if swept:
                    logger.info("Orphan sweep: %d processed", swept)
            except Exception:
                logger.error("Orphan sweep failed", exc_info=True)

            now = time.monotonic()
            if now - last_full >= FULL_RECONCILE_INTERVAL:
                try:
                    await self._reconciler.reconcile(self._mt5, self._sqlite)
                except Exception:
                    logger.error("Periodic reconcile failed", exc_info=True)
                last_full = now

    async def _license_teardown(self) -> None:
        """Cancel all pending orders and close all positions after license expiry."""
        self._license_expired = True
        self.shutdown_reason = "license_expired"
        logger.error("License expired — cancelling all pending orders and closing all positions")

        try:
            now_iso = datetime.now(UTC).isoformat()

            pending = await self._sqlite.get_pending_orders()
            for row in pending:
                ticket = row["mt5_ticket"]
                res = self._mt5.cancel_pending_order(ticket)
                if res and res.retcode == _RETCODE_DONE:
                    await self._sqlite.mark_cancelled(ticket, now_iso, spread=False)
                    logger.info("License teardown: cancelled pending ticket=%d", ticket)
                else:
                    retcode = res.retcode if res else "None"
                    logger.error(
                        "License teardown: cancel failed ticket=%d retcode=%s", ticket, retcode
                    )

            mt5_positions = {p.ticket: p for p in self._mt5.positions_get()}
            filled = await self._sqlite.get_filled_positions()
            for row in filled:
                ticket = row["mt5_ticket"]
                pos = mt5_positions.get(ticket)
                if pos is None:
                    continue
                res = self._mt5.close_position(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    volume=pos.volume,
                    position_type=pos.type,
                    comment="license_expired",
                )
                if res and res.retcode == _RETCODE_DONE:
                    realized_pnl = self._mt5.get_position_realized_pnl(ticket)
                    if realized_pnl is None:
                        realized_pnl = pos.profit
                    await self._sqlite.mark_closed(ticket, realized_pnl)
                    logger.info("License teardown: closed position ticket=%d", ticket)
                else:
                    retcode = res.retcode if res else "None"
                    logger.error(
                        "License teardown: close failed ticket=%d retcode=%s", ticket, retcode
                    )
        except Exception:
            logger.error("License teardown encountered an error", exc_info=True)

    async def _update_dashboard(self) -> None:
        try:
            acct = self._mt5.account_info()
            positions = self._mt5.positions_get()
            orders = self._mt5.orders_get()
            active = await self._sqlite.get_all_active()
            self.dashboard_cache.update(
                acct,
                positions,
                orders,
                active,
                self._mt5,
                supabase_rows=self._sync_cycle.last_supabase_rows,
                live_prices=self._sync_cycle.last_live_prices,
                pending_limit_ids=self._sync_cycle.last_sqlite_pending_limit_ids,
                config=self._config,
            )
        except Exception:
            logger.error("Dashboard cache update failed", exc_info=True)

    async def _maybe_upsert_user_snapshot(self) -> None:
        """Push a per-user account snapshot to Supabase every 5 min for leaderboard
        and TP-optimization analysis. Non-fatal; logged on failure and skipped if
        prerequisites are missing."""
        if not self._config.license_key:
            return
        if self._supabase._pool is None:
            return
        now = time.monotonic()
        if now - self._last_user_snapshot < _USER_SNAPSHOT_INTERVAL:
            return

        acct = self._mt5.account_info()
        if acct is None:
            return

        stats = await self._sqlite.get_user_stats()
        decided = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / decided * 100.0) if decided else 0.0
        open_positions_count = len(await self._sqlite.get_filled_positions())

        await self._supabase.upsert_user_snapshot(
            license_key=self._config.license_key,
            mt5_account=int(acct.login),
            balance=float(acct.balance),
            equity=float(acct.equity),
            currency=acct.currency,
            leverage=int(acct.leverage),
            open_positions_count=open_positions_count,
            total_realized_pnl=stats["total_pnl"],
            total_trades=int(stats["total_trades"]),
            wins=int(stats["wins"]),
            losses=int(stats["losses"]),
            win_rate=round(win_rate, 2),
            bot_version=BOT_VERSION,
        )
        self._last_user_snapshot = now

    async def _active_interval(self) -> float:
        if self._scheduler.is_spread_hour():
            active = await self._sqlite.get_all_active()
            if active:
                return 30.0
            return 60.0
        active = await self._sqlite.get_all_active()
        if active:
            return float(self._config.polling.tp_active_interval_seconds)
        return float(self._config.polling.supabase_interval_seconds)

    async def _tp_interval(self) -> float:
        if self._scheduler.is_spread_hour():
            active = await self._sqlite.get_all_active()
            if active:
                return 30.0
            return 60.0
        active = await self._sqlite.get_all_active()
        if active:
            return float(self._config.polling.tp_trailing_interval_seconds)
        return float(self._config.polling.supabase_interval_seconds)

    async def _broadcast_status(self) -> None:
        active = await self._sqlite.get_all_active()
        pending_count = sum(1 for r in active if r["status"] == "pending")
        open_count = sum(1 for r in active if r["status"] == "filled")
        trailing_count = sum(1 for r in active if r["status"] == "filled" and r["is_trailing"])
        mt5_connected = self._mt5.ensure_connected()
        status = {
            "engine_running": self._running,
            "trading_active": self._trading_active,
            "license_valid": getattr(self._license, "license_valid", True),
            "license_status": getattr(getattr(self._license, "status", None), "value", "valid"),
            "license_message": getattr(self._license, "message", ""),
            "mt5_connected": mt5_connected,
            "mt5_error": None if mt5_connected else self._mt5_conn.last_error,
            "supabase_connected": self._supabase._pool is not None,
            "pending_count": pending_count,
            "open_count": open_count,
            "trailing_count": trailing_count,
        }
        try:
            self.status_queue.put_nowait(status)
        except asyncio.QueueFull:
            pass
