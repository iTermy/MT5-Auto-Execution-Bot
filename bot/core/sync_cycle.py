import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.config.settings import Settings
from bot.db.sqlite import SQLiteDB
from bot.db.supabase import SupabaseDB
from bot.mt5.client import MT5Client
from bot.trading.fill_detector import FillDetector
from bot.trading.lot_calculator import LotCalculator
from bot.trading.offset_calculator import OffsetCalculator
from bot.trading.order_canceller import OrderCanceller
from bot.trading.order_placer import OrderPlacer
from bot.trading.symbol_mapper import map_symbol, needs_offset
from bot.utils.time_utils import MarketScheduler

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    placed: int = 0
    cancelled: int = 0
    filled: int = 0
    new_trailing: int = 0
    errors: int = 0


class SyncCycle:
    def __init__(self) -> None:
        self._placer = OrderPlacer()
        self._canceller = OrderCanceller()
        self._fill_detector = FillDetector()
        self._offset_calc = OffsetCalculator()

    async def run(
        self,
        supabase: SupabaseDB,
        sqlite: SQLiteDB,
        mt5_client: MT5Client,
        config: Settings,
        scheduler: MarketScheduler,
        placement_active: bool = True,
    ) -> SyncResult:
        result = SyncResult()

        supabase_rows = await supabase.fetch_active_signals()
        sqlite_active = await sqlite.get_all_active()
        sqlite_pending = [r for r in sqlite_active if r["status"] == "pending"]

        supabase_by_limit = {r["limit_id"]: r for r in supabase_rows}
        supabase_limit_ids = set(supabase_by_limit)
        sqlite_limit_ids = {r["limit_id"] for r in sqlite_active}

        # Spread hour gate: cancel all pending orders and skip placement
        if placement_active and scheduler.should_cancel_pending():
            for row in sqlite_pending:
                ok = await self._canceller.cancel_order(
                    row["mt5_ticket"], mt5_client, sqlite, spread=True
                )
                result.cancelled += ok
                result.errors += not ok
            # Fall through to fill detection even during spread hour
            placement_active = False

        if placement_active:
            # Cancel stale pending (limit gone from Supabase)
            for row in sqlite_pending:
                if row["limit_id"] not in supabase_limit_ids:
                    ok = await self._canceller.cancel_order(
                        row["mt5_ticket"], mt5_client, sqlite, spread=False
                    )
                    result.cancelled += ok
                    result.errors += not ok

            # Collect offset instruments needed for new limits + drift checks
            new_limit_ids = supabase_limit_ids - sqlite_limit_ids
            offset_needed: set[str] = set()
            for lid in new_limit_ids:
                if needs_offset(supabase_by_limit[lid]["instrument"], config):
                    offset_needed.add(supabase_by_limit[lid]["instrument"])
            for row in sqlite_pending:
                if row["offset_at_placement"] is not None and row["limit_id"] in supabase_by_limit:
                    offset_needed.add(supabase_by_limit[row["limit_id"]]["instrument"])

            live_prices: dict = {}
            if offset_needed:
                live_prices = await supabase.fetch_live_prices(list(offset_needed))

            # Group all Supabase rows by signal for lot calculation
            by_signal: dict[int, list] = defaultdict(list)
            for row in supabase_rows:
                by_signal[row["signal_id"]].append(row)

            lot_calc = LotCalculator(mt5_client, config)

            for lid in new_limit_ids:
                row = supabase_by_limit[lid]
                instrument = row["instrument"]
                mt5_symbol = map_symbol(instrument, config)
                limit_prices = [float(r["price_level"]) for r in by_signal[row["signal_id"]]]
                lot = lot_calc.calculate(float(row["stop_loss"]), limit_prices, mt5_symbol)

                offset: float | None = None
                if needs_offset(instrument, config):
                    live_row = live_prices.get(instrument)
                    if live_row is None:
                        logger.warning("No live price for %s, skipping limit=%d", instrument, lid)
                        result.errors += 1
                        continue
                    offset = self._offset_calc.get_offset(
                        mt5_symbol, live_row, mt5_client, config.feed_max_staleness_seconds
                    )
                    if offset is None:
                        result.errors += 1
                        continue

                ok = await self._placer.place_order(
                    signal_id=row["signal_id"],
                    limit_id=lid,
                    direction=row["direction"],
                    db_stop_loss=float(row["stop_loss"]),
                    db_price=float(row["price_level"]),
                    is_scalp=int(row["scalp"]),
                    mt5_symbol=mt5_symbol,
                    lot=lot,
                    offset=offset,
                    mt5_client=mt5_client,
                    sqlite=sqlite,
                )
                result.placed += ok
                result.errors += not ok

            # Offset drift check: cancel drifted pending orders so they re-place next cycle
            for row in sqlite_pending:
                if row["offset_at_placement"] is None:
                    continue
                if row["limit_id"] not in supabase_by_limit:
                    continue
                instrument = supabase_by_limit[row["limit_id"]]["instrument"]
                mt5_symbol = map_symbol(instrument, config)
                live_row = live_prices.get(instrument)
                if live_row is None:
                    continue
                current_offset = self._offset_calc.get_offset(
                    mt5_symbol, live_row, mt5_client, config.feed_max_staleness_seconds
                )
                if current_offset is None:
                    continue
                sym = mt5_client.symbol_info(mt5_symbol)
                if sym is None:
                    continue
                pip_sz = sym.point * (10 if sym.digits in (3, 5) else 1)
                threshold = config.offset_drift_threshold_pips * pip_sz
                if self._offset_calc.check_drift(
                    current_offset, float(row["offset_at_placement"]), threshold
                ):
                    logger.info(
                        "Offset drift: %s ticket=%d, cancelling for re-placement",
                        instrument, row["mt5_ticket"],
                    )
                    ok = await self._canceller.cancel_order(
                        row["mt5_ticket"], mt5_client, sqlite, spread=False
                    )
                    result.cancelled += ok
                    result.errors += not ok

        # Always detect fills (runs even when placement_active=False)
        mt5_orders = mt5_client.orders_get()
        mt5_positions = mt5_client.positions_get()

        # Re-fetch pending rows (some may have been cancelled above)
        current_pending = await sqlite.get_pending_orders()
        fills = self._fill_detector.detect_fills(mt5_orders, mt5_positions, current_pending)
        for fill in fills:
            await sqlite.mark_filled(fill.mt5_ticket, fill.filled_at)
            # In hedging mode, position ticket may differ from order ticket
            if fill.position_ticket != fill.mt5_ticket:
                await sqlite.update_ticket(fill.mt5_ticket, fill.position_ticket)
            result.filled += 1
            logger.info("Fill: order=%d pos=%d", fill.mt5_ticket, fill.position_ticket)

        # Detect partial close remainder tickets
        now_iso = datetime.now(timezone.utc).isoformat()
        new_tickets = await self._fill_detector.detect_partial_close_tickets(mt5_client, sqlite)
        for evt in new_tickets:
            await sqlite.insert_order(
                limit_id=-evt.new_ticket,  # synthetic negative ID (no Supabase limit)
                signal_id=evt.signal_id,
                mt5_ticket=evt.new_ticket,
                order_type="remainder",
                lot_size=0.0,
                placed_at=now_iso,
                db_stop_loss=0.0,
                is_scalp=evt.is_scalp,
            )
            await sqlite.mark_filled(evt.new_ticket, now_iso)
            await sqlite.set_trailing(evt.new_ticket)
            result.new_trailing += 1
            logger.info("Partial close remainder: new_ticket=%d signal=%d", evt.new_ticket, evt.signal_id)

        return result
