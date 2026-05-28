import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

import MetaTrader5 as mt5

from bot.config.constants import AssetClass
from bot.config.settings import Settings
from bot.db.sqlite import SQLiteDB
from bot.db.supabase import SupabaseDB
from bot.mt5.client import MT5Client
from bot.trading.fill_detector import FillDetector
from bot.trading.lot_calculator import LotCalculator
from bot.trading.offset_calculator import OffsetCalculator
from bot.trading.order_canceller import OrderCanceller
from bot.trading.order_placer import OrderPlacer
from bot.trading.symbol_mapper import detect_asset_class, map_symbol, needs_offset
from bot.utils.time_utils import MarketScheduler

logger = logging.getLogger(__name__)

_UNAVAILABLE_COOLDOWN = 300.0  # seconds before retrying a "not in terminal" symbol

# Asset-class proximity thresholds. (threshold, unit): unit is "pips" or "price" (USD distance).
_PROXIMITY: dict[AssetClass, tuple] = {
    AssetClass.FOREX:     (10,     "pips"),
    AssetClass.FOREX_JPY: (10,     "pips"),
    AssetClass.METALS:    (20.0,   "price"),
    AssetClass.CRYPTO:    (1000.0, "price"),
    AssetClass.STOCKS:    (5.0,    "price"),
    # INDICES: handled per-instrument below. OIL: not present → always allowed.
}

# Per-index proximity thresholds (USD distance from current price).
# Matched by substring against the DB instrument name — add new rows as needed.
_INDEX_PROXIMITY_USD: dict[str, float] = {
    "SPX":   20.0,   # S&P 500
    "US500": 20.0,   # S&P 500 alternate name
    "NAS":   50.0,   # Nasdaq 100
    "USTEC": 50.0,   # Nasdaq 100 alternate name
    "DAX":   50.0,   # DAX (DB side)
    "DE30":  50.0,   # DAX (ICMarkets MT5 side, in case DB uses it)
    "JP225": 100.0,  # Nikkei 225
    # "UK100": ...,  # FTSE 100 — add threshold when needed
}


def _within_proximity(
    limit_prices: list[float], mid: float, asset_class: AssetClass, info, db_sym: str = ""
) -> bool:
    min_dist = min(abs(p - mid) for p in limit_prices)

    if asset_class == AssetClass.INDICES:
        s = db_sym.upper()
        for keyword, threshold in _INDEX_PROXIMITY_USD.items():
            if keyword in s:
                return min_dist <= threshold
        return True  # unrecognized index → no filter

    if asset_class not in _PROXIMITY:
        return True  # OIL and any other unhandled classes

    threshold, unit = _PROXIMITY[asset_class]
    if unit == "pips":
        pip_sz = info.point * (10 if info.digits in (3, 5) else 1)
        return (min_dist / pip_sz) <= threshold if pip_sz > 0 else True
    return min_dist <= threshold


@dataclass
class SyncResult:
    placed: int = 0
    cancelled: int = 0
    filled: int = 0
    new_trailing: int = 0
    errors: int = 0
    skipped: int = 0  # proximity-filtered limits


_FORCE_EXIT_STATUSES = frozenset({"cancelled", "breakeven"})


class SyncCycle:
    def __init__(self) -> None:
        self._placer = OrderPlacer()
        self._canceller = OrderCanceller()
        self._fill_detector = FillDetector()
        self._offset_calc = OffsetCalculator()
        # mt5_symbol -> monotonic timestamp after which we retry the tick lookup
        self._unavailable_until: dict[str, float] = {}
        # signal_id -> last known status (for forced exit transition detection)
        self._last_signal_status: dict[int, str] = {}

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

            # Cancel pending orders whose signal SL changed (re-places next cycle)
            for row in sqlite_pending:
                lid = row["limit_id"]
                if lid not in supabase_by_limit:
                    continue
                stored_sl = row["db_stop_loss"]
                if stored_sl is None:
                    continue
                current_sl = float(supabase_by_limit[lid]["stop_loss"])
                mt5_sym = map_symbol(supabase_by_limit[lid]["instrument"], config)
                sym = mt5_client.symbol_info(mt5_sym)
                if sym is None:
                    continue
                pip_sz = sym.point * (10 if sym.digits in (3, 5) else 1)
                if pip_sz > 0 and abs(current_sl - stored_sl) >= pip_sz:
                    logger.info(
                        "SL change on pending: ticket=%d sl %.5f -> %.5f — cancelling for re-placement",
                        row["mt5_ticket"], stored_sl, current_sl,
                    )
                    ok = await self._canceller.cancel_order(
                        row["mt5_ticket"], mt5_client, sqlite, spread=False
                    )
                    result.cancelled += ok
                    result.errors += not ok

            new_limit_ids = supabase_limit_ids - sqlite_limit_ids

            # Collect offset instruments needed for new limits + drift checks
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

            if new_limit_ids:
                # --- Pre-check phase ---

                # Build unique mt5_symbol -> db_symbol map
                unique_syms: dict[str, str] = {}
                for lid in new_limit_ids:
                    db_sym = supabase_by_limit[lid]["instrument"]
                    unique_syms[map_symbol(db_sym, config)] = db_sym

                # Fetch tick once per symbol with cooldown for unavailable symbols.
                # Symbols that failed recently are skipped entirely (no MT5 call, no log).
                # On first detection or after cooldown expires, mt5_client logs one ERROR
                # and we log one WARNING — then silence for _UNAVAILABLE_COOLDOWN seconds.
                sym_ticks: dict = {}
                sym_infos: dict = {}
                newly_unavailable: set[str] = set()
                now_mono = time.monotonic()
                for mt5_sym in unique_syms:
                    if now_mono < self._unavailable_until.get(mt5_sym, 0.0):
                        # Known unavailable and cooldown not expired — skip silently
                        sym_ticks[mt5_sym] = None
                        sym_infos[mt5_sym] = None
                        continue
                    tick = mt5_client.symbol_info_tick(mt5_sym)
                    sym_ticks[mt5_sym] = tick
                    sym_infos[mt5_sym] = mt5_client.symbol_info(mt5_sym) if tick is not None else None
                    if tick is None:
                        self._unavailable_until[mt5_sym] = now_mono + _UNAVAILABLE_COOLDOWN
                        newly_unavailable.add(mt5_sym)
                    else:
                        self._unavailable_until.pop(mt5_sym, None)

                # Log and count errors only for symbols newly detected as unavailable.
                # Cooldown-suppressed symbols are skipped silently this cycle.
                unavailable_mt5: set[str] = set()
                for mt5_sym, db_sym in unique_syms.items():
                    if sym_ticks[mt5_sym] is None:
                        unavailable_mt5.add(mt5_sym)
                        if mt5_sym in newly_unavailable:
                            count = sum(
                                1 for lid in new_limit_ids
                                if map_symbol(supabase_by_limit[lid]["instrument"], config) == mt5_sym
                            )
                            logger.warning(
                                "Symbol not in terminal: %s — skipping %d limit(s) (retrying in %.0fs)",
                                mt5_sym, count, _UNAVAILABLE_COOLDOWN,
                            )
                            result.errors += count

                # Pre-check offset staleness per instrument (log once, not once per limit)
                stale_instruments: set[str] = set()
                now_utc = datetime.now(timezone.utc)
                for instrument in offset_needed:
                    live_row = live_prices.get(instrument)
                    if live_row is None:
                        continue
                    age = (now_utc - live_row["updated_at"]).total_seconds()
                    if age > config.feed_max_staleness_seconds:
                        count = sum(
                            1 for lid in new_limit_ids
                            if supabase_by_limit[lid]["instrument"] == instrument
                        )
                        if count:
                            logger.warning(
                                "Live price stale for %s (%.0fs) — skipping %d limit(s)",
                                instrument, age, count,
                            )
                            result.errors += count
                        stale_instruments.add(instrument)

                # Group new limits by signal; apply proximity filter per signal
                new_by_signal: dict[int, list[int]] = defaultdict(list)
                for lid in new_limit_ids:
                    new_by_signal[supabase_by_limit[lid]["signal_id"]].append(lid)

                approved_signals: set[int] = set()
                for sig_id, lids in new_by_signal.items():
                    row0 = supabase_by_limit[lids[0]]
                    db_sym = row0["instrument"]
                    mt5_sym = map_symbol(db_sym, config)
                    if mt5_sym in unavailable_mt5:
                        continue  # errors already counted
                    if needs_offset(db_sym, config) and db_sym in stale_instruments:
                        continue  # errors already counted
                    tick = sym_ticks.get(mt5_sym)
                    info = sym_infos.get(mt5_sym)
                    if tick is None or info is None:
                        result.errors += len(lids)
                        continue
                    mid = (tick.bid + tick.ask) / 2
                    new_prices = [float(supabase_by_limit[lid]["price_level"]) for lid in lids]
                    if _within_proximity(new_prices, mid, detect_asset_class(db_sym), info, db_sym):
                        approved_signals.add(sig_id)
                    else:
                        result.skipped += len(lids)
                        logger.debug(
                            "Signal %d (%s): no limit within proximity threshold, skipping %d order(s)",
                            sig_id, db_sym, len(lids),
                        )

                # Compute lot once per approved signal (not once per limit)
                signal_lots: dict[int, float] = {}
                for sig_id in approved_signals:
                    lids = new_by_signal[sig_id]
                    row0 = supabase_by_limit[lids[0]]
                    all_prices = [float(r["price_level"]) for r in by_signal[sig_id]]
                    mt5_sym = map_symbol(row0["instrument"], config)
                    signal_lots[sig_id] = lot_calc.calculate(
                        float(row0["stop_loss"]), all_prices, mt5_sym
                    )

                # --- Placement phase: approved signals only ---
                for lid in new_limit_ids:
                    row = supabase_by_limit[lid]
                    sig_id = row["signal_id"]
                    if sig_id not in approved_signals:
                        continue

                    db_sym = row["instrument"]
                    mt5_sym = map_symbol(db_sym, config)
                    lot = signal_lots[sig_id]

                    offset: float | None = None
                    if needs_offset(db_sym, config):
                        live_row = live_prices.get(db_sym)
                        if live_row is None:
                            logger.warning("No live price for %s, skipping limit=%d", db_sym, lid)
                            result.errors += 1
                            continue
                        offset = self._offset_calc.get_offset(
                            mt5_sym, live_row, mt5_client, config.feed_max_staleness_seconds
                        )
                        if offset is None:
                            result.errors += 1
                            continue

                    ok = await self._placer.place_order(
                        signal_id=sig_id,
                        limit_id=lid,
                        direction=row["direction"],
                        db_stop_loss=float(row["stop_loss"]),
                        db_price=float(row["price_level"]),
                        is_scalp=int(row["scalp"]),
                        mt5_symbol=mt5_sym,
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

        current_pending = await sqlite.get_pending_orders()
        fills = self._fill_detector.detect_fills(mt5_orders, mt5_positions, current_pending)
        for fill in fills:
            await sqlite.mark_filled(fill.mt5_ticket, fill.filled_at)
            if fill.position_ticket != fill.mt5_ticket:
                await sqlite.update_ticket(fill.mt5_ticket, fill.position_ticket)
            result.filled += 1
            logger.info("Fill: order=%d pos=%d", fill.mt5_ticket, fill.position_ticket)

        now_iso = datetime.now(timezone.utc).isoformat()
        new_tickets = await self._fill_detector.detect_partial_close_tickets(mt5_client, sqlite)
        for evt in new_tickets:
            await sqlite.mark_closed(evt.original_ticket)
            await sqlite.insert_order(
                limit_id=-evt.new_ticket,
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
            logger.info("Partial close remainder: new_ticket=%d signal=%d (original=%d closed)", evt.new_ticket, evt.signal_id, evt.original_ticket)

        # Build signal-level lookup from supabase rows for SL sync and forced exit
        supabase_by_signal: dict[int, dict] = {}
        for row in supabase_rows:
            sid = row["signal_id"]
            if sid not in supabase_by_signal:
                supabase_by_signal[sid] = row

        await self._sync_filled_sls(
            sqlite, mt5_client, mt5_positions, supabase_by_signal, config
        )
        await self._check_forced_exits(
            supabase, sqlite, mt5_client, mt5_positions
        )

        return result

    async def _sync_filled_sls(
        self,
        sqlite: SQLiteDB,
        mt5_client: MT5Client,
        mt5_positions: list,
        supabase_by_signal: dict[int, dict],
        config: Settings,
    ) -> None:
        filled = await sqlite.get_filled_positions()
        if not filled:
            return

        pos_by_ticket = {p.ticket: p for p in mt5_positions}

        for row in filled:
            if row["is_trailing"]:
                continue

            ticket = row["mt5_ticket"]
            if ticket not in pos_by_ticket:
                continue

            signal_id = row["signal_id"]
            sig = supabase_by_signal.get(signal_id)
            if sig is None:
                continue

            stored_db_sl = row["db_stop_loss"]
            if stored_db_sl is None:
                continue

            current_db_sl = float(sig["stop_loss"])
            instrument = sig["instrument"]
            mt5_sym = map_symbol(instrument, config)

            sym = mt5_client.symbol_info(mt5_sym)
            if sym is None:
                continue
            pip_sz = sym.point * (10 if sym.digits in (3, 5) else 1)
            if pip_sz <= 0:
                continue

            if abs(current_db_sl - stored_db_sl) < pip_sz:
                continue

            offset = 0.0
            if needs_offset(instrument, config):
                tick = mt5_client.symbol_info_tick(mt5_sym)
                if tick is None:
                    continue
                offset = row["offset_at_placement"] or 0.0

            tick = mt5_client.symbol_info_tick(mt5_sym)
            if tick is None:
                continue
            spread = tick.ask - tick.bid
            direction = sig["direction"]
            if direction == "long":
                mt5_sl = round(current_db_sl + offset - spread, sym.digits)
            else:
                mt5_sl = round(current_db_sl + offset + spread, sym.digits)

            pos = pos_by_ticket[ticket]
            res = mt5_client.modify_position_sl(ticket, pos.symbol, mt5_sl)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                await sqlite.update_db_stop_loss(ticket, current_db_sl, mt5_sl)
                logger.info(
                    "SL sync ticket=%d signal=%d: db_sl %.5f -> %.5f, mt5_sl=%.5f",
                    ticket, signal_id, stored_db_sl, current_db_sl, mt5_sl,
                )
            else:
                retcode = res.retcode if res else "None"
                logger.warning("SL sync failed ticket=%d retcode=%s", ticket, retcode)

    async def _check_forced_exits(
        self,
        supabase: SupabaseDB,
        sqlite: SQLiteDB,
        mt5_client: MT5Client,
        mt5_positions: list,
    ) -> None:
        filled_sids = await sqlite.get_filled_signal_ids()
        if not filled_sids:
            self._last_signal_status.clear()
            return

        status_map = await supabase.fetch_signal_statuses(list(filled_sids))

        pos_by_ticket = {p.ticket: p for p in mt5_positions}

        for signal_id in filled_sids:
            current = status_map.get(signal_id)
            if current is None:
                continue

            previous = self._last_signal_status.get(signal_id)
            self._last_signal_status[signal_id] = current

            if current not in _FORCE_EXIT_STATUSES:
                continue
            if previous == current:
                continue
            if previous != "hit":
                continue

            logger.warning(
                "Forced exit: signal %d status %r -> %r — closing all positions",
                signal_id, previous, current,
            )

            filled_rows = await sqlite.get_filled_positions()
            for row in filled_rows:
                if row["signal_id"] != signal_id:
                    continue
                ticket = row["mt5_ticket"]
                pos = pos_by_ticket.get(ticket)
                if pos is None:
                    continue
                res = mt5_client.close_position(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    volume=pos.volume,
                    position_type=pos.type,
                    comment=f"force_{current}",
                )
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    await sqlite.mark_closed(ticket)
                    logger.info("Forced exit closed ticket=%d signal=%d", ticket, signal_id)
                else:
                    retcode = res.retcode if res else "None"
                    logger.error("Forced exit close failed ticket=%d retcode=%s", ticket, retcode)

        self._last_signal_status = {
            sid: st for sid, st in self._last_signal_status.items()
            if sid in filled_sids
        }
