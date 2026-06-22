import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
from bot.trading.symbol_mapper import (
    db_symbol_from_mt5,
    detect_asset_class,
    instrument_under_news,
    map_symbol,
    needs_offset,
    offset_drift_threshold,
    parse_news_symbols,
    proximity_threshold,
)
from bot.utils.time_utils import MarketScheduler

logger = logging.getLogger(__name__)

_UNAVAILABLE_COOLDOWN = 300.0  # seconds before retrying a "not in terminal" symbol


def _within_proximity(
    limit_prices: list[float], mid: float, asset_class: AssetClass, info, prox, db_sym: str = ""
) -> bool:
    threshold = proximity_threshold(asset_class, info, prox, db_sym)
    if threshold is None:
        return True
    return min(abs(p - mid) for p in limit_prices) <= threshold


@dataclass
class SyncResult:
    placed: int = 0
    cancelled: int = 0
    filled: int = 0
    new_trailing: int = 0
    errors: int = 0
    skipped: int = 0  # proximity-filtered limits + past-price placement skips


_FORCE_EXIT_STATUSES = frozenset({"cancelled", "breakeven"})
_SL_FAIL_MAX = 5
_FORCE_EXIT_MAX_ATTEMPTS = 5


def _persist_stock_no_suffix(db_symbol: str, config: Settings) -> None:
    try:
        config_path = Path("config.json")
        data = json.loads(config_path.read_text())
        no_suffix = data.get("stock_no_suffix", [])
        if db_symbol not in no_suffix:
            no_suffix.append(db_symbol)
            data["stock_no_suffix"] = no_suffix
            config_path.write_text(json.dumps(data, indent=2))
            config.stock_no_suffix = no_suffix
            logger.info("Persisted %s to stock_no_suffix in config.json", db_symbol)
    except Exception:
        logger.error("Failed to persist stock_no_suffix", exc_info=True)


def _gate_exempt(instr: str, config: Settings) -> bool:
    """Crypto and 24h stocks (broker -24 suffix) trade around the clock, so they're
    exempt from the spread-hour and news-mode gates."""
    ac = detect_asset_class(instr)
    if ac == AssetClass.CRYPTO:
        return True
    return (
        ac == AssetClass.STOCKS
        and bool(config.stock_suffix)
        and map_symbol(instr, config).endswith(config.stock_suffix)
    )


def _feed_for_symbol(db_sym: str, config: Settings) -> str:
    """Return the TM feed name that serves this symbol."""
    if not needs_offset(db_sym, config):
        return "icmarkets"
    ac = detect_asset_class(db_sym)
    if ac == AssetClass.CRYPTO:
        return "binance"
    return "oanda"


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
        # limit_ids whose exclusion has already been logged (logged once per lifetime)
        self._logged_excluded: set[int] = set()
        # mt5_symbols the broker doesn't offer at all (logged once per lifetime)
        self._logged_unmapped: set[str] = set()
        # signal_ids whose proximity rejection has been logged (logged once per lifetime)
        self._logged_proximity: set[int] = set()
        # C8: SL sync consecutive failure tracking
        self._sl_fail_count: dict[int, int] = {}  # ticket -> consecutive fail count
        self._sl_fail_target: dict[int, float] = {}  # ticket -> last failed target sl
        # M13: force-exit consecutive failure tracking
        self._force_exit_fail_count: dict[int, int] = {}  # mt5_ticket -> consecutive fail count
        # News force-exit consecutive failure tracking (separate from status force-exit)
        self._news_exit_fail_count: dict[int, int] = {}  # mt5_ticket -> consecutive fail count
        # Spread-hour SL strip/restore consecutive failure tracking (log suppression)
        self._sl_strip_fail_count: dict[int, int] = {}  # mt5_ticket -> consecutive fail count
        self._sl_restore_fail_count: dict[int, int] = {}  # mt5_ticket -> consecutive fail count
        self._last_force_exit_status: dict[
            int, str
        ] = {}  # signal_id -> force-exit status at first detection
        self._feed_health_failed: bool = False
        # Snapshots read by DashboardCache to render unplaced "watching" signals.
        # Preserved across Supabase outages so the UI doesn't blank out.
        self.last_supabase_rows: list | None = None
        self.last_live_prices: dict = {}
        self.last_sqlite_pending_limit_ids: set[int] = set()

    def _apply_exclusions(self, rows: list, config: Settings) -> list:
        excluded_syms = {s.upper() for s in config.excluded_symbols}
        disabled_types = set(config.disabled_signal_types)
        disabled_channels = set(config.disabled_channels)

        filtered = []
        for r in rows:
            sym = r["instrument"].upper()
            stype = r["signal_type"]
            chan = None if r["channel_id"] is None else str(r["channel_id"])
            reason = None
            if stype in disabled_types:
                reason = f"signal type '{stype}' disabled"
            elif chan is not None and chan in disabled_channels:
                reason = f"channel {chan} disabled"
            elif sym in excluded_syms:
                reason = "symbol excluded"
            else:
                for rule in config.excluded_trades:
                    if rule.symbol.upper() == sym and rule.signal_type in ("all", stype):
                        reason = f"excluded trade {rule.symbol}/{rule.signal_type}"
                        break

            if reason is None:
                filtered.append(r)
                continue
            lid = r["limit_id"]
            if lid not in self._logged_excluded:
                logger.info(
                    "Excluded: signal_id=%d limit_id=%d symbol=%s — %s",
                    r["signal_id"],
                    lid,
                    r["instrument"],
                    reason,
                )
                self._logged_excluded.add(lid)
        return filtered

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

        try:
            supabase_rows = await supabase.fetch_active_signals()
        except Exception:
            logger.error(
                "Supabase fetch failed — skipping placement phase, running fill detection only",
                exc_info=True,
            )
            supabase_rows = None

        if supabase_rows is not None:
            supabase_rows = self._apply_exclusions(supabase_rows, config)

            sqlite_active = await sqlite.get_all_active()
            sqlite_pending = [r for r in sqlite_active if r["status"] == "pending"]

            supabase_by_limit = {r["limit_id"]: r for r in supabase_rows}
            supabase_limit_ids = set(supabase_by_limit)
            sqlite_limit_ids = {r["limit_id"] for r in sqlite_active}

            # Limits the TM marked 'hit' while their signal is still live. Their
            # local pending order is held by the stale-pending sweep below — the
            # feed reached the level but our broker hasn't filled (sub-pip
            # mismatch). Defaults empty on failure, reverting to plain stale-cancel.
            try:
                hit_limit_ids = await supabase.fetch_hit_limit_ids()
            except Exception:
                logger.error(
                    "Hit-limit fetch failed — stale-pending will not spare hit limits",
                    exc_info=True,
                )
                hit_limit_ids = set()

            # Per-symbol spread-hour / news-mode gate. Crypto and 24h stocks are exempt
            # (24/7 markets). Stocks use an earlier cutoff because they close at 16:00 EST
            # — the cancel must land before then or MT5 rejects it once the session is
            # shut; everything else uses the standard daily_start.
            now = datetime.now(UTC)

            # news_mode is per-symbol: a comma-separated list of currency/asset tokens
            # (or 'ALL'), NULL when there's no news. Fetched regardless of
            # placement_active so news force-exits still fire while placement is paused.
            news_symbols: frozenset[str] = frozenset()
            try:
                news_symbols = parse_news_symbols(await supabase.fetch_news_mode())
            except Exception:
                logger.error("Failed to fetch news_mode", exc_info=True)

            def _instr_of(row) -> str:
                lid = row["limit_id"]
                if lid in supabase_by_limit:
                    return supabase_by_limit[lid]["instrument"]
                return db_symbol_from_mt5(row["symbol"] or "", config)

            def _is_blocked(instr: str) -> bool:
                if _gate_exempt(instr, config):
                    return False
                if instrument_under_news(instr, news_symbols):
                    return True
                is_stock = detect_asset_class(instr) == AssetClass.STOCKS
                return scheduler.should_cancel_pending(now, stock=is_stock)

            if placement_active:
                blocked = 0
                for row in sqlite_pending:
                    if not _is_blocked(_instr_of(row)):
                        continue
                    ok = await self._canceller.cancel_order(
                        row["mt5_ticket"], mt5_client, sqlite, spread=True
                    )
                    result.cancelled += ok
                    result.errors += not ok
                    blocked += 1
                if blocked:
                    logger.info("Spread/news gate cancelled %d pending order(s)", blocked)

                # Drop blocked rows from the pre-gate snapshot so downstream loops
                # (stale-pending, SL change, offset drift) skip the just-cancelled orders.
                # sqlite_limit_ids is intentionally NOT refreshed: the cancelled limits
                # should still be treated as 'known' (not as new placement candidates).
                sqlite_pending = [r for r in sqlite_pending if not _is_blocked(_instr_of(r))]

            # Always fetch live_prices for every offset symbol in the active signal
            # set — used for placement, drift checks, SL sync, and the dashboard's
            # "Closest Signals" view (which needs feed_mid for offset symbols).
            offset_needed: set[str] = {
                r["instrument"] for r in supabase_rows if needs_offset(r["instrument"], config)
            }
            live_prices: dict = {}
            if offset_needed:
                try:
                    live_prices = await supabase.fetch_live_prices(list(offset_needed))
                except Exception:
                    logger.error("Live prices fetch failed", exc_info=True)

            if placement_active:
                # Cancel stale pending (limit gone from Supabase). A limit the TM
                # marked 'hit' on a still-live signal is spared: hold the order so a
                # sub-pip price mismatch still fills. Genuine cancels/closes drop the
                # signal out of hit_limit_ids, so those orders are still cancelled.
                for row in sqlite_pending:
                    lid = row["limit_id"]
                    if lid in supabase_limit_ids or lid in hit_limit_ids:
                        continue
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
                            row["mt5_ticket"],
                            stored_sl,
                            current_sl,
                        )
                        ok = await self._canceller.cancel_order(
                            row["mt5_ticket"], mt5_client, sqlite, spread=False
                        )
                        result.cancelled += ok
                        result.errors += not ok

                new_limit_ids = supabase_limit_ids - sqlite_limit_ids

                # Drop blocked symbols (spread hour / weekend / news mode) from the
                # pre-check phase — otherwise tick/proximity/live-price-staleness checks
                # fire (and spam WARN logs) for symbols the placement loop would skip.
                new_limit_ids = {
                    lid
                    for lid in new_limit_ids
                    if not _is_blocked(supabase_by_limit[lid]["instrument"])
                }

                stale_feeds: set[str] = set()
                if not self._feed_health_failed:
                    try:
                        feed_health = await supabase.fetch_feed_health()
                        stale_feeds = {
                            feed
                            for feed, status in feed_health.items()
                            if status in ("degraded", "down")
                        }
                        if stale_feeds:
                            logger.warning("Stale feeds detected: %s", stale_feeds)
                    except Exception:
                        logger.warning("feed_health unavailable — skipping feed staleness checks")
                        self._feed_health_failed = True

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

                    # Resolve availability against the broker's symbol catalogue, then
                    # fetch the tick. Symbols the broker doesn't carry (e.g. GCQ26) are
                    # skipped cleanly and logged once for their lifetime — no retry churn.
                    # Catalogued-but-hidden symbols are selected into MarketWatch first.
                    # Symbols whose tick failed recently are cooldown-suppressed (no MT5
                    # call, no log); on first failure / after cooldown we warn once.
                    sym_ticks: dict = {}
                    sym_infos: dict = {}
                    newly_unavailable: set[str] = set()
                    broker_symbols = mt5_client.symbols_get()
                    now_mono = time.monotonic()
                    for mt5_sym in list(unique_syms):
                        if now_mono < self._unavailable_until.get(mt5_sym, 0.0):
                            sym_ticks[mt5_sym] = None
                            sym_infos[mt5_sym] = None
                            continue

                        # Catalogue check (skipped if symbols_get is unavailable this cycle).
                        if broker_symbols and mt5_sym not in broker_symbols:
                            base_sym = (
                                mt5_sym[: -len(config.stock_suffix)]
                                if config.stock_suffix and mt5_sym.endswith(config.stock_suffix)
                                else None
                            )
                            if base_sym and base_sym in broker_symbols:
                                # Broker lists the bare stock symbol, not the suffixed one.
                                db_sym = unique_syms[mt5_sym]
                                logger.info(
                                    "Stock suffix fallback: %s not in catalogue, using %s",
                                    mt5_sym,
                                    base_sym,
                                )
                                _persist_stock_no_suffix(db_sym, config)
                                unique_syms[base_sym] = db_sym
                                del unique_syms[mt5_sym]
                                mt5_sym = base_sym
                            else:
                                # Instrument simply isn't offered by this broker — skip.
                                sym_ticks[mt5_sym] = None
                                sym_infos[mt5_sym] = None
                                if mt5_sym not in self._logged_unmapped:
                                    logger.info(
                                        "Symbol %s not offered by this broker — skipping "
                                        "(map it under Settings if it exists by another name)",
                                        mt5_sym,
                                    )
                                    self._logged_unmapped.add(mt5_sym)
                                continue

                        # Catalogued (or catalogue unknown) — ensure it's in MarketWatch.
                        mt5_client.symbol_select(mt5_sym)
                        tick = mt5_client.symbol_info_tick(mt5_sym)

                        sym_ticks[mt5_sym] = tick
                        sym_infos[mt5_sym] = (
                            mt5_client.symbol_info(mt5_sym) if tick is not None else None
                        )
                        if tick is None:
                            self._unavailable_until[mt5_sym] = now_mono + _UNAVAILABLE_COOLDOWN
                            newly_unavailable.add(mt5_sym)
                        else:
                            self._unavailable_until.pop(mt5_sym, None)

                    # Log and count errors only for symbols newly detected as unavailable.
                    # Cooldown-suppressed symbols are skipped silently this cycle.
                    unavailable_mt5: set[str] = set()
                    for mt5_sym in unique_syms:
                        if sym_ticks[mt5_sym] is None:
                            unavailable_mt5.add(mt5_sym)
                            if mt5_sym in newly_unavailable:
                                count = sum(
                                    1
                                    for lid in new_limit_ids
                                    if map_symbol(supabase_by_limit[lid]["instrument"], config)
                                    == mt5_sym
                                )
                                logger.warning(
                                    "Symbol not in terminal: %s — skipping %d limit(s) (retrying in %.0fs)",
                                    mt5_sym,
                                    count,
                                    _UNAVAILABLE_COOLDOWN,
                                )
                                result.errors += count

                    # Pre-check dead feeds per instrument (log once, not once per limit).
                    # An old updated_at is normal for an idle feed; only a feed that
                    # has gone fully dark (beyond the dead-feed bound) is skipped — the
                    # offset itself is anchored to updated_at, not to "now".
                    stale_instruments: set[str] = set()
                    now_utc = datetime.now(UTC)
                    for instrument in offset_needed:
                        live_row = live_prices.get(instrument)
                        if live_row is None:
                            continue
                        age = (now_utc - live_row["updated_at"]).total_seconds()
                        if age > config.feed_max_staleness_seconds:
                            count = sum(
                                1
                                for lid in new_limit_ids
                                if supabase_by_limit[lid]["instrument"] == instrument
                            )
                            if count:
                                logger.warning(
                                    "Live price dark for %s (%.0fs old) — skipping %d limit(s)",
                                    instrument,
                                    age,
                                    count,
                                )
                                result.errors += count
                            stale_instruments.add(instrument)

                    # Group new limits by signal; apply proximity filter per signal
                    new_by_signal: dict[int, list[int]] = defaultdict(list)
                    for lid in new_limit_ids:
                        new_by_signal[supabase_by_limit[lid]["signal_id"]].append(lid)

                    approved_signals: set[int] = set()
                    rejection_reason: dict[int, str] = {}
                    for sig_id, lids in new_by_signal.items():
                        row0 = supabase_by_limit[lids[0]]
                        db_sym = row0["instrument"]
                        mt5_sym = map_symbol(db_sym, config)
                        if mt5_sym in unavailable_mt5:
                            rejection_reason[sig_id] = "symbol not in terminal"
                            continue  # errors already counted by pre-check
                        if needs_offset(db_sym, config) and db_sym in stale_instruments:
                            rejection_reason[sig_id] = "live price stale"
                            continue  # errors already counted by pre-check
                        feed = _feed_for_symbol(db_sym, config)
                        if feed in stale_feeds:
                            rejection_reason[sig_id] = "feed_stale"
                            result.skipped += len(lids)
                            logger.info(
                                "Signal %d (%s): feed=%s is stale — skipping %d limit(s)",
                                sig_id,
                                db_sym,
                                feed,
                                len(lids),
                            )
                            continue
                        tick = sym_ticks.get(mt5_sym)
                        info = sym_infos.get(mt5_sym)
                        if tick is None or info is None:
                            rejection_reason[sig_id] = "symbol not in terminal"
                            result.errors += len(lids)
                            logger.warning(
                                "Signal %d (%s): tick/info unavailable — skipping %d limit(s)",
                                sig_id,
                                db_sym,
                                len(lids),
                            )
                            continue
                        # Proximity is a feed-frame question: the limit prices are feed
                        # prices, so compare against the feed mid for offset symbols. Using
                        # the broker mid here would be off by the whole offset.
                        if needs_offset(db_sym, config):
                            live_row = live_prices.get(db_sym)
                            if live_row is None:
                                rejection_reason[sig_id] = "no live price"
                                result.errors += len(lids)
                                logger.warning(
                                    "Signal %d (%s): no live price for proximity — skipping %d limit(s)",
                                    sig_id,
                                    db_sym,
                                    len(lids),
                                )
                                continue
                            mid = (float(live_row["bid"]) + float(live_row["ask"])) / 2
                        else:
                            mid = (tick.bid + tick.ask) / 2
                        new_prices = [float(supabase_by_limit[lid]["price_level"]) for lid in lids]
                        if _within_proximity(
                            new_prices,
                            mid,
                            detect_asset_class(db_sym),
                            info,
                            config.proximity,
                            db_sym,
                        ):
                            approved_signals.add(sig_id)
                            self._logged_proximity.discard(sig_id)
                        else:
                            rejection_reason[sig_id] = "outside proximity"
                            result.skipped += len(lids)
                            if sig_id not in self._logged_proximity:
                                logger.info(
                                    "Signal %d (%s): all limits outside proximity — skipping %d order(s)",
                                    sig_id,
                                    db_sym,
                                    len(lids),
                                )
                                self._logged_proximity.add(sig_id)

                    # Compute lot once per approved signal (not once per limit)
                    signal_lots: dict[int, float] = {}
                    for sig_id in approved_signals:
                        lids = new_by_signal[sig_id]
                        row0 = supabase_by_limit[lids[0]]
                        all_prices = [float(r["price_level"]) for r in by_signal[sig_id]]
                        mt5_sym = map_symbol(row0["instrument"], config)
                        signal_lots[sig_id] = lot_calc.calculate(
                            float(row0["stop_loss"]),
                            all_prices,
                            mt5_sym,
                            row0["signal_type"] or "standard",
                        )

                    # --- Placement phase: approved signals only ---
                    for lid in new_limit_ids:
                        row = supabase_by_limit[lid]
                        sig_id = row["signal_id"]
                        if sig_id not in approved_signals:
                            continue

                        db_sym = row["instrument"]
                        if _is_blocked(db_sym):
                            continue
                        mt5_sym = map_symbol(db_sym, config)
                        lot = signal_lots[sig_id]

                        offset: float | None = None
                        if needs_offset(db_sym, config):
                            live_row = live_prices.get(db_sym)
                            if live_row is None:
                                logger.warning(
                                    "No live price for %s, skipping limit=%d", db_sym, lid
                                )
                                result.errors += 1
                                continue
                            offset = self._offset_calc.get_offset(
                                mt5_sym,
                                live_row,
                                mt5_client,
                                config.feed_max_staleness_seconds,
                                config.offset_recompute_interval_seconds,
                            )
                            if offset is None:
                                result.errors += 1
                                continue

                        outcome = await self._placer.place_order(
                            signal_id=sig_id,
                            limit_id=lid,
                            direction=row["direction"],
                            db_stop_loss=float(row["stop_loss"]),
                            db_price=float(row["price_level"]),
                            signal_type=row["signal_type"] or "standard",
                            mt5_symbol=mt5_sym,
                            lot=lot,
                            offset=offset,
                            mt5_client=mt5_client,
                            sqlite=sqlite,
                            supabase=supabase,
                            channel_id=row["channel_id"],
                            sequence_number=row["sequence_number"],
                        )
                        if outcome == "placed":
                            result.placed += 1
                        elif outcome == "skipped":
                            result.skipped += 1
                        else:
                            result.errors += 1

                # Offset drift check: cancel drifted pending orders so they re-place next cycle.
                # Skipped entirely for signals whose other limits have already hit — re-placing
                # the survivors at a fresh offset leaves the already-filled (or TM-marked-hit)
                # limits at the old offset, producing inconsistent entries across the same signal.
                # "Hit" here means either: bot has a local fill, OR Supabase signal_status is 'hit'
                # (the TM has marked at least one limit hit, even if MT5 hasn't filled yet).
                now_drift = datetime.now(UTC)
                drift_interval = config.offset_drift_check_interval_seconds
                signals_with_fills = await sqlite.get_signals_with_fills()
                signals_hit_in_db = {
                    r["signal_id"] for r in supabase_rows if r.get("signal_status") == "hit"
                }
                signals_blocked_from_drift = signals_with_fills | signals_hit_in_db
                for row in sqlite_pending:
                    if row["offset_at_placement"] is None:
                        continue
                    if row["limit_id"] not in supabase_by_limit:
                        continue
                    if row["signal_id"] in signals_blocked_from_drift:
                        continue
                    last_check = row["last_offset_check"]
                    if last_check:
                        try:
                            prev = datetime.fromisoformat(last_check)
                            if (now_drift - prev).total_seconds() < drift_interval:
                                continue
                        except ValueError:
                            pass
                    instrument = supabase_by_limit[row["limit_id"]]["instrument"]
                    mt5_symbol = map_symbol(instrument, config)
                    live_row = live_prices.get(instrument)
                    if live_row is None:
                        continue
                    current_offset = self._offset_calc.get_offset(
                        mt5_symbol,
                        live_row,
                        mt5_client,
                        config.feed_max_staleness_seconds,
                        config.offset_recompute_interval_seconds,
                    )
                    if current_offset is None:
                        continue
                    await sqlite.update_last_offset_check(row["mt5_ticket"], now_drift.isoformat())
                    threshold = offset_drift_threshold(
                        detect_asset_class(instrument), config.offset_drift, instrument
                    )
                    if self._offset_calc.check_drift(
                        current_offset, float(row["offset_at_placement"]), threshold
                    ):
                        logger.info(
                            "Offset drift: %s ticket=%d, cancelling for re-placement",
                            instrument,
                            row["mt5_ticket"],
                        )
                        ok = await self._canceller.cancel_order(
                            row["mt5_ticket"], mt5_client, sqlite, spread=False
                        )
                        result.cancelled += ok
                        result.errors += not ok

        # Always detect fills (runs even when placement_active=False or Supabase down)
        mt5_orders = mt5_client.orders_get()
        mt5_positions = mt5_client.positions_get()

        current_pending = await sqlite.get_pending_orders()
        fills = self._fill_detector.detect_fills(mt5_orders, mt5_positions, current_pending)
        for fill in fills:
            await sqlite.mark_filled_and_set_position_ticket(
                fill.mt5_ticket, fill.position_ticket, fill.filled_at
            )
            result.filled += 1
            logger.info("Fill: order=%d pos=%d", fill.mt5_ticket, fill.position_ticket)

        now_iso = datetime.now(UTC).isoformat()
        pos_by_ticket = {p.ticket: p for p in mt5_positions}
        new_tickets = await self._fill_detector.detect_partial_close_tickets(
            mt5_client, sqlite, mt5_positions
        )
        for evt in new_tickets:
            await sqlite.mark_closed(evt.original_ticket)
            remainder_pos = pos_by_ticket.get(evt.new_ticket)
            await sqlite.insert_order(
                limit_id=-evt.new_ticket,
                signal_id=evt.signal_id,
                mt5_ticket=evt.new_ticket,
                order_type="remainder",
                lot_size=0.0,
                placed_at=now_iso,
                db_stop_loss=0.0,
                signal_type=evt.signal_type,
                symbol=remainder_pos.symbol if remainder_pos else None,
            )
            await sqlite.mark_filled(evt.new_ticket, now_iso)
            await sqlite.set_trailing(evt.new_ticket)
            result.new_trailing += 1
            logger.info(
                "Partial close remainder: new_ticket=%d signal=%d (original=%d closed)",
                evt.new_ticket,
                evt.signal_id,
                evt.original_ticket,
            )

        # M2: mark positions closed if they disappeared from MT5 externally
        await self._check_external_closes(sqlite, mt5_client, mt5_positions)

        # Strip/restore SLs around spread hour. Runs unconditionally (even on a
        # Supabase outage) so a stripped position always gets its SL back.
        await self._manage_spread_hour_sls(sqlite, mt5_client, mt5_positions, scheduler, config)

        if supabase_rows is not None:
            # Build signal-level lookup from supabase rows for SL sync and forced exit
            supabase_by_signal: dict[int, dict] = {}
            for row in supabase_rows:
                sid = row["signal_id"]
                if sid not in supabase_by_signal:
                    supabase_by_signal[sid] = row

            await self._sync_filled_sls(
                sqlite, mt5_client, mt5_positions, supabase_by_signal, config, live_prices
            )
            await self._check_forced_exits(
                supabase, sqlite, mt5_client, mt5_positions, scheduler, config
            )
            await self._check_news_exits(news_symbols, sqlite, mt5_client, mt5_positions, config)

            # Snapshot for the dashboard's "Closest Signals" view. Re-query pending
            # so newly-placed orders from this cycle appear as placed=True.
            sqlite_pending_now = await sqlite.get_pending_orders()
            self.last_supabase_rows = list(supabase_rows)
            self.last_live_prices = live_prices
            self.last_sqlite_pending_limit_ids = {r["limit_id"] for r in sqlite_pending_now}

        return result

    async def _sync_filled_sls(
        self,
        sqlite: SQLiteDB,
        mt5_client: MT5Client,
        mt5_positions: list,
        supabase_by_signal: dict[int, dict],
        config: Settings,
        live_prices: dict,
    ) -> None:
        filled = await sqlite.get_filled_positions()
        if not filled:
            return

        pos_by_ticket = {p.ticket: p for p in mt5_positions}

        for row in filled:
            if row["is_trailing"]:
                continue
            # SL deliberately removed for spread-hour protection — don't re-apply it
            # here even if the signal's DB stop-loss changed mid-window.
            if row["sl_stripped"]:
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
                live_row = live_prices.get(instrument)
                if live_row is not None:
                    current_offset = self._offset_calc.get_offset(
                        mt5_sym,
                        live_row,
                        mt5_client,
                        config.feed_max_staleness_seconds,
                        config.offset_recompute_interval_seconds,
                    )
                    offset = (
                        current_offset
                        if current_offset is not None
                        else (row["offset_at_placement"] or 0.0)
                    )
                else:
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
            if res and res.retcode == mt5.TRADE_RETCODE_NO_CHANGES:
                await sqlite.update_db_stop_loss(ticket, current_db_sl, mt5_sl)
                self._sl_fail_count.pop(ticket, None)
                self._sl_fail_target.pop(ticket, None)
                continue
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                await sqlite.update_db_stop_loss(ticket, current_db_sl, mt5_sl)
                self._sl_fail_count.pop(ticket, None)
                self._sl_fail_target.pop(ticket, None)
                logger.info(
                    "SL sync ticket=%d signal=%d: db_sl %.5f -> %.5f, mt5_sl=%.5f",
                    ticket,
                    signal_id,
                    stored_db_sl,
                    current_db_sl,
                    mt5_sl,
                )
            else:
                retcode = res.retcode if res else "None"
                logger.warning("SL sync failed ticket=%d retcode=%s", ticket, retcode)
                if self._sl_fail_target.get(ticket) != mt5_sl:
                    self._sl_fail_count[ticket] = 0
                    self._sl_fail_target[ticket] = mt5_sl
                count = self._sl_fail_count.get(ticket, 0) + 1
                self._sl_fail_count[ticket] = count
                if count == _SL_FAIL_MAX:
                    logger.error(
                        "Persistent SL sync failure: ticket=%d target_sl=%.5f retcode=%s",
                        ticket,
                        mt5_sl,
                        retcode,
                    )

    async def _manage_spread_hour_sls(
        self,
        sqlite: SQLiteDB,
        mt5_client: MT5Client,
        mt5_positions: list,
        scheduler: MarketScheduler,
        config: Settings,
    ) -> None:
        """Strip the stop-loss from every hit position ~5 min before spread hour so a
        spread-driven spike can't stop it out, then restore it once the window ends.
        On restore, if price has genuinely moved past the stop, close at market (a
        bigger but rare loss). Crypto and 24h (-suffix) instruments are exempt — their
        markets stay liquid through these windows. The sl_stripped flag persists in
        SQLite so a restart mid-window never leaves a position unprotected and the TP
        loop / SL-sync both skip a stripped position."""
        filled = await sqlite.get_filled_positions()
        if not filled:
            return

        pos_by_ticket = {p.ticket: p for p in mt5_positions}

        for row in filled:
            ticket = row["mt5_ticket"]
            pos = pos_by_ticket.get(ticket)
            if pos is None:
                continue
            instr = db_symbol_from_mt5(row["symbol"] or pos.symbol, config)
            if _gate_exempt(instr, config):
                continue
            is_stock = detect_asset_class(instr) == AssetClass.STOCKS
            in_window = scheduler.is_sl_strip_window(stock=is_stock)
            stripped = bool(row["sl_stripped"])

            if in_window and not stripped and pos.sl != 0.0:
                await sqlite.update_sl(ticket, pos.sl)  # remember pre-strip SL for restore
                res = mt5_client.modify_position_sl(ticket, pos.symbol, 0.0)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    await sqlite.set_sl_stripped(ticket, 1)
                    self._sl_strip_fail_count.pop(ticket, None)
                    logger.info(
                        "Spread-hour SL strip: ticket=%d signal=%d symbol=%s prev_sl=%.5f",
                        ticket,
                        row["signal_id"],
                        pos.symbol,
                        pos.sl,
                    )
                else:
                    self._log_sl_action_fail("strip", ticket, res, self._sl_strip_fail_count)
            elif not in_window and stripped:
                await self._restore_spread_hour_sl(row, pos, mt5_client, sqlite)

    async def _restore_spread_hour_sl(
        self, row, pos, mt5_client: MT5Client, sqlite: SQLiteDB
    ) -> None:
        ticket = row["mt5_ticket"]
        target = row["last_known_mt5_sl"]
        if target is None or target == 0.0:
            # No stored SL to restore — clear the flag so we stop retrying.
            await sqlite.set_sl_stripped(ticket, 0)
            return

        tick = mt5_client.symbol_info_tick(pos.symbol)
        if tick is None:
            return  # market likely closed (e.g. stock overnight) — retry next cycle

        breached = (pos.type == 0 and tick.bid <= target) or (pos.type != 0 and tick.ask >= target)
        if breached:
            res = mt5_client.close_position(
                ticket=pos.ticket,
                symbol=pos.symbol,
                volume=pos.volume,
                position_type=pos.type,
                comment="spread_sl_restore",
            )
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                realized_pnl = mt5_client.get_position_realized_pnl(ticket)
                if realized_pnl is None:
                    realized_pnl = pos.profit
                await sqlite.mark_closed(ticket, realized_pnl)
                self._sl_restore_fail_count.pop(ticket, None)
                logger.warning(
                    "Spread-hour SL restore: price past stop — closed ticket=%d signal=%d "
                    "sl=%.5f pnl=%s",
                    ticket,
                    row["signal_id"],
                    target,
                    f"{realized_pnl:.2f}" if realized_pnl is not None else "?",
                )
            else:
                self._log_sl_action_fail("restore-close", ticket, res, self._sl_restore_fail_count)
            return

        res = mt5_client.modify_position_sl(ticket, pos.symbol, target)
        if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_NO_CHANGES):
            await sqlite.set_sl_stripped(ticket, 0)
            self._sl_restore_fail_count.pop(ticket, None)
            logger.info(
                "Spread-hour SL restore: ticket=%d signal=%d symbol=%s sl=%.5f",
                ticket,
                row["signal_id"],
                pos.symbol,
                target,
            )
        else:
            self._log_sl_action_fail("restore", ticket, res, self._sl_restore_fail_count)

    def _log_sl_action_fail(self, action: str, ticket: int, res, counter: dict[int, int]) -> None:
        """Log a strip/restore failure once, then again at the cap, then suppress —
        a stock whose market is shut overnight would otherwise spam every cycle."""
        retcode = res.retcode if res else "None"
        count = counter.get(ticket, 0) + 1
        counter[ticket] = count
        if count == 1:
            logger.warning(
                "Spread-hour SL %s failed: ticket=%d retcode=%s", action, ticket, retcode
            )
        elif count == _SL_FAIL_MAX:
            logger.error(
                "Spread-hour SL %s persistently failing: ticket=%d retcode=%s "
                "(suppressing further logs)",
                action,
                ticket,
                retcode,
            )

    async def _check_forced_exits(
        self,
        supabase: SupabaseDB,
        sqlite: SQLiteDB,
        mt5_client: MT5Client,
        mt5_positions: list,
        scheduler: MarketScheduler,
        config: Settings,
    ) -> None:
        filled_sids = await sqlite.get_filled_signal_ids()
        if not filled_sids:
            self._last_signal_status.clear()
            return

        status_map = await supabase.fetch_signal_statuses(list(filled_sids))

        pos_by_ticket = {p.ticket: p for p in mt5_positions}
        all_filled_rows = await sqlite.get_filled_positions()

        for signal_id in filled_sids:
            entry = status_map.get(signal_id)
            if entry is None:
                continue
            current = entry["status"]
            closed_reason = entry.get("closed_reason")

            previous = self._last_signal_status.get(signal_id)

            if current == "profit" and previous != "profit":
                logger.info(
                    "Signal %d profit-marked by TM — keeping positions; TP engine continues",
                    signal_id,
                )

            if current not in _FORCE_EXIT_STATUSES:
                self._last_signal_status[signal_id] = current
                self._last_force_exit_status.pop(signal_id, None)
                continue
            if previous == current:
                continue

            signal_rows = [r for r in all_filled_rows if r["signal_id"] == signal_id]

            # Cancelled status: only force-close if the cancellation is happening within
            # the forex weekend window (Fri >=16:45 EST through Sun <18:00 EST), because
            # weekday cancellations on a hit signal are expected (TM extends expiry to the
            # next day) and positions should stay open. Crypto stays tradable through the
            # weekend, but a 'cancelled' TM status is the only directive we have for it,
            # so crypto positions always close on cancellation regardless of day/time.
            # 'breakeven' status closes unconditionally (unchanged behavior).
            gate_reason = current
            if current == "cancelled":
                is_weekend = scheduler.is_weekend_window()
                if not is_weekend:
                    crypto_rows = [
                        r
                        for r in signal_rows
                        if detect_asset_class(db_symbol_from_mt5(r["symbol"] or "", config))
                        == AssetClass.CRYPTO
                    ]
                    if not crypto_rows:
                        self._last_signal_status[signal_id] = current
                        self._last_force_exit_status.pop(signal_id, None)
                        logger.info(
                            "Signal %d cancelled on weekday — keeping non-crypto positions open",
                            signal_id,
                        )
                        continue
                    signal_rows = crypto_rows
                    gate_reason = "cancelled_crypto"
                else:
                    gate_reason = "cancelled_weekend"

            logger.warning(
                "Forced exit: signal %d status %r -> %r closed_reason=%r reason=%s — closing %d position(s)",
                signal_id,
                previous,
                current,
                closed_reason,
                gate_reason,
                len(signal_rows),
            )

            # Clear per-ticket fail counts on a new or resumed force-exit trigger
            if self._last_force_exit_status.get(signal_id) != current:
                self._last_force_exit_status[signal_id] = current
                for row in signal_rows:
                    self._force_exit_fail_count.pop(row["mt5_ticket"], None)

            # 5.1: Stop trailing before force-exit so the TP loop does not ratchet SL
            for row in signal_rows:
                await sqlite.set_trailing(row["mt5_ticket"], 0)

            all_handled = True
            for row in signal_rows:
                ticket = row["mt5_ticket"]
                pos = pos_by_ticket.get(ticket)
                if pos is None:
                    continue

                fail_count = self._force_exit_fail_count.get(ticket, 0)
                if fail_count >= _FORCE_EXIT_MAX_ATTEMPTS:
                    continue  # given up; treated as handled

                res = mt5_client.close_position(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    volume=pos.volume,
                    position_type=pos.type,
                    comment=f"force_{current}",
                )
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    realized_pnl = mt5_client.get_position_realized_pnl(ticket)
                    if realized_pnl is None:
                        realized_pnl = pos.profit
                    await sqlite.mark_closed(ticket, realized_pnl)
                    self._force_exit_fail_count.pop(ticket, None)
                    logger.info("Forced exit closed ticket=%d signal=%d", ticket, signal_id)
                else:
                    retcode = res.retcode if res else "None"
                    logger.error("Forced exit close failed ticket=%d retcode=%s", ticket, retcode)
                    new_count = self._force_exit_fail_count.get(ticket, 0) + 1
                    self._force_exit_fail_count[ticket] = new_count
                    if new_count == _FORCE_EXIT_MAX_ATTEMPTS:
                        logger.error(
                            "Forced exit abandoned: ticket=%d signal=%d after %d attempts — manual intervention required",
                            ticket,
                            signal_id,
                            new_count,
                        )
                    all_handled = False

            if all_handled:
                self._last_signal_status[signal_id] = current
            # else: leave previous status so next cycle retries

        self._last_signal_status = {
            sid: st for sid, st in self._last_signal_status.items() if sid in filled_sids
        }

    async def _check_news_exits(
        self,
        news_symbols: frozenset[str],
        sqlite: SQLiteDB,
        mt5_client: MT5Client,
        mt5_positions: list,
        config: Settings,
    ) -> None:
        """Force-close filled positions whose instrument is under active news. Mirrors
        the manual-cancel / breakeven force-exit: stop trailing, close, mark closed.
        Crypto and 24h stocks are exempt (same as the placement gate). Idempotent —
        once a position is closed it's gone from MT5 and skipped next cycle."""
        if not news_symbols:
            return
        filled = await sqlite.get_filled_positions()
        if not filled:
            return

        pos_by_ticket = {p.ticket: p for p in mt5_positions}

        for row in filled:
            ticket = row["mt5_ticket"]
            pos = pos_by_ticket.get(ticket)
            if pos is None:
                continue

            instr = db_symbol_from_mt5(row["symbol"] or "", config)
            if _gate_exempt(instr, config) or not instrument_under_news(instr, news_symbols):
                continue

            if self._news_exit_fail_count.get(ticket, 0) >= _FORCE_EXIT_MAX_ATTEMPTS:
                continue

            await sqlite.set_trailing(ticket, 0)
            res = mt5_client.close_position(
                ticket=pos.ticket,
                symbol=pos.symbol,
                volume=pos.volume,
                position_type=pos.type,
                comment="force_news",
            )
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                realized_pnl = mt5_client.get_position_realized_pnl(ticket)
                if realized_pnl is None:
                    realized_pnl = pos.profit
                await sqlite.mark_closed(ticket, realized_pnl)
                self._news_exit_fail_count.pop(ticket, None)
                logger.warning(
                    "News exit closed ticket=%d signal=%d symbol=%s news=%s",
                    ticket,
                    row["signal_id"],
                    instr,
                    ",".join(sorted(news_symbols)),
                )
            else:
                retcode = res.retcode if res else "None"
                logger.error("News exit close failed ticket=%d retcode=%s", ticket, retcode)
                new_count = self._news_exit_fail_count.get(ticket, 0) + 1
                self._news_exit_fail_count[ticket] = new_count
                if new_count == _FORCE_EXIT_MAX_ATTEMPTS:
                    logger.error(
                        "News exit abandoned: ticket=%d signal=%d after %d attempts — "
                        "manual intervention required",
                        ticket,
                        row["signal_id"],
                        new_count,
                    )

    async def _check_external_closes(
        self, sqlite: SQLiteDB, mt5_client: MT5Client, mt5_positions: list
    ) -> None:
        """M2: detect positions no longer in MT5 and mark them closed."""
        filled = await sqlite.get_filled_positions()
        if not filled:
            return

        pos_by_ticket = {p.ticket: p for p in mt5_positions}

        for row in filled:
            ticket = row["mt5_ticket"]
            if ticket not in pos_by_ticket:
                realized_pnl = mt5_client.get_position_realized_pnl(ticket)
                await sqlite.mark_closed(ticket, realized_pnl)
                if row["is_trailing"]:
                    logger.info(
                        "Trailing stop hit: ticket=%d signal=%d symbol=%s pnl=%s",
                        ticket,
                        row["signal_id"],
                        row["symbol"] or "?",
                        f"{realized_pnl:.2f}" if realized_pnl is not None else "?",
                    )
                else:
                    logger.info(
                        "External close: ticket=%d signal=%d pnl=%s",
                        ticket,
                        row["signal_id"],
                        f"{realized_pnl:.2f}" if realized_pnl is not None else "?",
                    )
