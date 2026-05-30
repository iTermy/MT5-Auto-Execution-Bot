import logging
import math

import MetaTrader5 as mt5

from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client
from bot.mt5.types import PositionInfo
from bot.tp.asset_config import AssetClassConfig
from bot.tp.strategy import TPResult
from bot.tp.trailing import TrailingStopManager

logger = logging.getLogger(__name__)


def _price_movement(position: PositionInfo, bid: float, ask: float) -> float:
    """Price movement in the profit direction (always positive when in profit)."""
    if position.type == 0:  # long
        return bid - position.price_open
    return position.price_open - ask


def _pip_size(point: float, digits: int) -> float:
    return point * (10 if digits in (3, 5) else 1)


class DefaultTPStrategy:
    def __init__(self) -> None:
        self._trailing = TrailingStopManager()

    def should_trigger(
        self,
        positions: list[PositionInfo],
        asset_config: AssetClassConfig,
        mt5_client: MT5Client,
    ) -> bool:
        sorted_pos = sorted(positions, key=lambda p: p.ticket)
        newest = sorted_pos[-1]
        others = sorted_pos[:-1]

        tick = mt5_client.symbol_info_tick(newest.symbol)
        if tick is None:
            return False

        move = _price_movement(newest, tick.bid, tick.ask)

        if asset_config.threshold_unit == "pips":
            sym = mt5_client.symbol_info(newest.symbol)
            if sym is None:
                return False
            pip_sz = _pip_size(sym.point, sym.digits)
            if pip_sz <= 0:
                return False
            move = move / pip_sz

        if move < asset_config.profit_threshold:
            return False

        if others:
            return sum(p.profit for p in others) >= 0
        return True

    async def execute(
        self,
        signal_id: int,
        positions: list[PositionInfo],
        asset_config: AssetClassConfig,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
    ) -> TPResult:
        result = TPResult()
        sorted_pos = sorted(positions, key=lambda p: p.ticket)
        newest = sorted_pos[-1]
        earlier = sorted_pos[:-1]

        for pos in earlier:
            res = mt5_client.close_position(
                ticket=pos.ticket,
                symbol=pos.symbol,
                volume=pos.volume,
                position_type=pos.type,
                comment=f"s{signal_id}",
            )
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                await sqlite.mark_closed(pos.ticket, pos.profit)
                result.closed_tickets.append(pos.ticket)
                logger.info("TP closed ticket=%d signal=%d", pos.ticket, signal_id)
            else:
                retcode = res.retcode if res else "None"
                msg = f"close failed ticket={pos.ticket} retcode={retcode}"
                result.errors.append(msg)
                logger.error("TP: %s signal=%d", msg, signal_id)

        pct = asset_config.partial_close_percent
        if pct <= 0:
            # Trail full position — no close needed
            await sqlite.set_trailing(newest.ticket)
            result.trailed_tickets.append(newest.ticket)
            logger.info("TP trailing full position ticket=%d signal=%d", newest.ticket, signal_id)
        elif pct >= 100:
            res = mt5_client.close_position(
                ticket=newest.ticket,
                symbol=newest.symbol,
                volume=newest.volume,
                position_type=newest.type,
                comment=f"s{signal_id}",
            )
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                await sqlite.mark_closed(newest.ticket, newest.profit)
                result.closed_tickets.append(newest.ticket)
                logger.info("TP fully closed ticket=%d signal=%d", newest.ticket, signal_id)
            else:
                retcode = res.retcode if res else "None"
                msg = f"full close failed ticket={newest.ticket} retcode={retcode}"
                result.errors.append(msg)
                logger.error("TP: %s signal=%d", msg, signal_id)
        else:
            # Partial close — ICMarkets creates a new ticket for the remainder.
            # fill_detector.detect_partial_close_tickets() will pick up the new ticket
            # next cycle and insert it into SQLite with is_trailing=1.
            sym_info = mt5_client.symbol_info(newest.symbol)
            raw_vol = newest.volume * pct / 100
            if sym_info and sym_info.volume_step > 0:
                close_vol = math.floor(raw_vol / sym_info.volume_step) * sym_info.volume_step
                close_vol = round(close_vol, 8)  # float precision cleanup
                close_vol = max(close_vol, sym_info.volume_min)
            else:
                close_vol = round(raw_vol, 2)
            if close_vol <= 0:
                await sqlite.set_trailing(newest.ticket)
                result.trailed_tickets.append(newest.ticket)
                logger.info("TP trailing full position (vol floor=0) ticket=%d signal=%d", newest.ticket, signal_id)
            else:
                res = mt5_client.close_position(
                    ticket=newest.ticket,
                    symbol=newest.symbol,
                    volume=close_vol,
                    position_type=newest.type,
                    comment=f"s{signal_id}",
                )
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    await sqlite.set_trailing(newest.ticket)
                    result.closed_tickets.append(newest.ticket)
                    result.trailed_tickets.append(newest.ticket)
                    logger.info(
                        "TP partial close %d%% ticket=%d signal=%d vol=%.2f",
                        pct, newest.ticket, signal_id, close_vol,
                    )
                else:
                    retcode = res.retcode if res else "None"
                    msg = f"partial close failed ticket={newest.ticket} retcode={retcode}"
                    result.errors.append(msg)
                    logger.error("TP: %s signal=%d", msg, signal_id)

        return result

    async def update_trailing(
        self,
        signal_id: int,
        positions: list[PositionInfo],
        asset_config: AssetClassConfig,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
    ) -> TPResult:
        result = TPResult()
        if not positions:
            return result

        tick = mt5_client.symbol_info_tick(positions[0].symbol)
        if tick is None:
            result.errors.append(f"No tick for {positions[0].symbol}")
            return result

        for pos in positions:
            updated = await self._trailing.update(pos, tick, asset_config, mt5_client, sqlite)
            if updated:
                result.trailed_tickets.append(pos.ticket)

        return result
