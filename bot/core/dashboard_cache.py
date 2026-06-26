import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bot.config.constants import AssetClass
from bot.config.settings import Settings
from bot.trading.symbol_mapper import (
    detect_asset_class,
    map_symbol,
    needs_offset,
    proximity_threshold,
)

logger = logging.getLogger(__name__)

_MARGIN_MODE_HEDGING = 2  # mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
_PIP_CLASSES = (AssetClass.FOREX, AssetClass.FOREX_JPY)


def _proximity_pct(distance: float, closest_price: float, threshold: float | None) -> int:
    """0–100 fill heuristic. Scaled to 3× the instrument's placement-proximity threshold
    when one is configured (100% = at the limit, ~66% = at the placement threshold, 0% =
    at/beyond 3× the threshold the bot uses to decide a limit is worth placing). Falls back
    to distance-as-fraction-of-price (1% → 0%) for asset classes with no configured threshold."""
    if threshold and threshold > 0:
        closeness = 1.0 - min(abs(distance) / (3 * threshold), 1.0)
    elif closest_price:
        closeness = 1.0 - min(abs(distance) / abs(closest_price) / 0.01, 1.0)
    else:
        return 0
    return round(closeness * 100)


@dataclass
class DashboardData:
    account: dict | None = None
    positions: list[dict] = field(default_factory=list)
    pending_orders: list[dict] = field(default_factory=list)
    nearby_signals: list[dict] = field(default_factory=list)
    summary: dict = field(
        default_factory=lambda: {
            "total_profit": 0.0,
            "open_count": 0,
            "pending_count": 0,
            "trailing_count": 0,
        }
    )
    updated_at: str = ""


class DashboardCache:
    def __init__(self) -> None:
        self._data = DashboardData()

    @property
    def data(self) -> DashboardData:
        return self._data

    def update(
        self,
        account_info,
        mt5_positions,
        mt5_orders,
        sqlite_active,
        mt5_client,
        supabase_rows: list | None = None,
        live_prices: dict | None = None,
        pending_limit_ids: set[int] | None = None,
        config: Settings | None = None,
        broker_symbols: frozenset[str] | None = None,
        signal_actions: dict[int, str] | None = None,
    ) -> None:
        now_iso = datetime.now(UTC).isoformat()

        sqlite_by_ticket = {r["mt5_ticket"]: r for r in sqlite_active}

        acct: dict | None = None
        if account_info:
            acct = {
                "login": account_info.login,
                "balance": account_info.balance,
                "equity": account_info.equity,
                "margin": account_info.margin,
                "margin_free": account_info.margin_free,
                "leverage": account_info.leverage,
                "currency": account_info.currency,
                "server": account_info.server,
                "company": account_info.company,
                "hedging": account_info.margin_mode == _MARGIN_MODE_HEDGING,
            }

        all_symbols = {p.symbol for p in mt5_positions} | {o.symbol for o in mt5_orders}
        # Also fetch ticks for non-offset symbols that only appear in supabase_rows,
        # so we can compute distance for unplaced "watching" signals. Skip symbols the
        # broker doesn't carry — otherwise symbol_info_tick spams "Not found" every cycle
        # for instruments this broker simply doesn't offer.
        if supabase_rows and config is not None:
            for r in supabase_rows:
                if needs_offset(r["instrument"], config):
                    continue
                sym = map_symbol(r["instrument"], config)
                if broker_symbols is None or sym in broker_symbols:
                    all_symbols.add(sym)
        tick_cache = {}
        for sym in all_symbols:
            tick = mt5_client.symbol_info_tick(sym)
            if tick:
                tick_cache[sym] = tick

        positions = []
        for pos in mt5_positions:
            row = sqlite_by_ticket.get(pos.ticket)
            current_price = pos.price_open
            tick = tick_cache.get(pos.symbol)
            if tick:
                current_price = tick.bid if pos.type == 0 else tick.ask
            ch = row["channel_id"] if row else None
            positions.append(
                {
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "direction": "long" if pos.type == 0 else "short",
                    "volume": pos.volume,
                    "price_open": pos.price_open,
                    "current_price": current_price,
                    "sl": pos.sl,
                    "profit": pos.profit,
                    "is_trailing": bool(row["is_trailing"]) if row else False,
                    "signal_id": row["signal_id"] if row else 0,
                    "channel_id": str(ch) if ch is not None else None,
                    "signal_type": (row["signal_type"] if row else None) or "standard",
                }
            )

        pending = []
        for order in mt5_orders:
            row = sqlite_by_ticket.get(order.ticket)
            current_price = 0.0
            distance = 0.0
            tick = tick_cache.get(order.symbol)
            if tick:
                mid = (tick.bid + tick.ask) / 2
                current_price = mid
                distance = abs(order.price_open - mid)
            ch = row["channel_id"] if row else None
            pending.append(
                {
                    "ticket": order.ticket,
                    "symbol": order.symbol,
                    "direction": "long" if order.type in (2, 4) else "short",
                    "volume": order.volume_current,
                    "price_level": order.price_open,
                    "current_price": current_price,
                    "sl": order.sl,
                    "distance": round(distance, 5),
                    "signal_id": row["signal_id"] if row else 0,
                    "channel_id": str(ch) if ch is not None else None,
                    "signal_type": (row["signal_type"] if row else None) or "standard",
                }
            )

        nearby = _build_nearby_signals(
            supabase_rows or [],
            live_prices or {},
            pending_limit_ids or set(),
            tick_cache,
            config,
            mt5_client,
            signal_actions or {},
        )

        total_profit = sum(p["profit"] for p in positions)
        trailing_count = sum(1 for p in positions if p["is_trailing"])

        self._data = DashboardData(
            account=acct,
            positions=positions,
            pending_orders=pending,
            nearby_signals=nearby,
            summary={
                "total_profit": round(total_profit, 2),
                "open_count": len(positions),
                "pending_count": len(pending),
                "trailing_count": trailing_count,
            },
            updated_at=now_iso,
        )


def _build_nearby_signals(
    supabase_rows: list,
    live_prices: dict,
    pending_limit_ids: set[int],
    tick_cache: dict,
    config: Settings | None,
    mt5_client,
    signal_actions: dict[int, str],
) -> list[dict]:
    if not supabase_rows or config is None:
        return []

    by_signal: dict[int, list] = defaultdict(list)
    for r in supabase_rows:
        by_signal[r["signal_id"]].append(r)

    result: list[dict] = []
    for sig_id, rows in by_signal.items():
        first = rows[0]
        db_sym = first["instrument"]
        mt5_sym = map_symbol(db_sym, config)

        if needs_offset(db_sym, config):
            lp = live_prices.get(db_sym)
            if lp is None:
                continue  # can't compute distance without feed price
            current_price = (float(lp["bid"]) + float(lp["ask"])) / 2
        else:
            tick = tick_cache.get(mt5_sym)
            if tick is None:
                continue
            current_price = (tick.bid + tick.ask) / 2

        prices = [float(r["price_level"]) for r in rows]
        closest_price = min(prices, key=lambda p: abs(p - current_price))
        distance = current_price - closest_price
        placed = any(r["limit_id"] in pending_limit_ids for r in rows)
        ch = first["channel_id"]
        asset_class = detect_asset_class(db_sym)
        distance_magnitude = _distance_magnitude(distance, asset_class)
        distance_display = _format_distance(distance, asset_class)
        price_display = _format_price(closest_price, asset_class)

        info = mt5_client.symbol_info(mt5_sym) if asset_class in _PIP_CLASSES else None
        threshold = (
            None
            if asset_class in _PIP_CLASSES and info is None
            else proximity_threshold(asset_class, info, config.proximity, db_sym)
        )
        proximity_pct = _proximity_pct(distance, closest_price, threshold)

        result.append(
            {
                "signal_id": sig_id,
                "distance_display": distance_display,
                "closest_price_display": price_display,
                "proximity_pct": proximity_pct,
                "symbol": db_sym,
                "mt5_symbol": mt5_sym,
                "direction": first["direction"],
                "channel_id": str(ch) if ch is not None else None,
                "signal_type": first["signal_type"] or "standard",
                "limit_count": len(rows),
                "closest_price": closest_price,
                "current_price": round(current_price, 5),
                "distance": round(distance, 5),
                "distance_magnitude": distance_magnitude,
                "placed": placed,
                "action": signal_actions.get(sig_id),
            }
        )

    # Sort by the proximity bar fill (closeness relative to each instrument's own
    # threshold), so the fullest bars — the signals nearest to triggering — come first.
    # distance_magnitude breaks ties between equal (rounded) fills.
    result.sort(key=lambda x: (-x["proximity_pct"], x["distance_magnitude"]))
    return result


def _distance_magnitude(distance: float, asset_class: AssetClass) -> float:
    """The displayed proximity number (pips for forex, dollars otherwise). Used for the
    distance label and as a tie-break when two signals share the same bar fill."""
    abs_d = abs(distance)
    if asset_class == AssetClass.FOREX:
        return abs_d * 10000
    if asset_class == AssetClass.FOREX_JPY:
        return abs_d * 100
    return abs_d


def _format_distance(distance: float, asset_class: AssetClass) -> str:
    mag = _distance_magnitude(distance, asset_class)
    if asset_class in (AssetClass.FOREX, AssetClass.FOREX_JPY):
        return f"{mag:.1f} pips"
    # metals/indices/stocks/crypto/oil — quoted in dollars per unit price
    if mag >= 100:
        return f"${mag:,.2f}"
    return f"${mag:.2f}"


def _format_price(price: float, asset_class: AssetClass) -> str:
    abs_p = abs(price)
    if asset_class == AssetClass.FOREX_JPY:
        return f"{price:.3f}"
    if asset_class == AssetClass.FOREX:
        return f"{price:.5f}"
    if abs_p >= 1000:
        return f"{price:,.2f}"
    if abs_p >= 10:
        return f"{price:.2f}"
    return f"{price:.4f}"
