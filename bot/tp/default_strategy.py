import logging
import math

import MetaTrader5 as mt5

from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client
from bot.mt5.types import PositionInfo
from bot.tp.asset_config import AssetClassConfig
from bot.tp.outcome import TriggerSnapshot
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


async def _record_exit_slippage(res, pos: PositionInfo, mt5_client: MT5Client, sqlite: SQLiteDB) -> None:
    """Persist adverse-positive close slippage in broker points. Best-effort analytics."""
    try:
        sym = mt5_client.symbol_info(pos.symbol)
        if sym is None or sym.point <= 0 or not res.requested_price or not res.price:
            return
        diff = res.price - res.requested_price
        # Closing a long sells: filling below the requested price is adverse. Short mirrored.
        slip = (-diff if pos.type == 0 else diff) / sym.point
        await sqlite.set_exit_slippage(pos.ticket, slip)
    except Exception:
        logger.debug("exit slippage record failed ticket=%d", pos.ticket, exc_info=True)


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

        others_profit = sum(p.profit for p in others) if others else 0.0
        if others and others_profit < 0:
            return False

        side = "long" if newest.type == 0 else "short"
        ref_price = tick.bid if newest.type == 0 else tick.ask
        logger.info(
            "TP triggered: ticket=%d %s entry=%.5f price=%.5f move=%.5f threshold=%.5f unit=%s others_pnl=%.2f",
            newest.ticket,
            side,
            newest.price_open,
            ref_price,
            move,
            asset_config.profit_threshold,
            asset_config.threshold_unit,
            others_profit,
        )
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

        # Capture pre-close state for the TPOutcome snapshot. realized_pnl below is
        # the cumulative profit across positions about to be closed (matches what
        # gets logged per mark_closed); we use it for analytics, not for execution.
        tick_pre = mt5_client.symbol_info_tick(newest.symbol)
        tp_trigger_price = 0.0
        move_at_trigger = 0.0
        if tick_pre is not None:
            tp_trigger_price = tick_pre.bid if newest.type == 0 else tick_pre.ask
            move = _price_movement(newest, tick_pre.bid, tick_pre.ask)
            if asset_config.threshold_unit == "pips":
                sym_pre = mt5_client.symbol_info(newest.symbol)
                if sym_pre is not None:
                    pip_sz_pre = _pip_size(sym_pre.point, sym_pre.digits)
                    if pip_sz_pre > 0:
                        move = move / pip_sz_pre
            move_at_trigger = move
        others_pnl_pre = sum(p.profit for p in earlier) if earlier else 0.0
        all_pos = earlier + [newest]
        total_volume = sum(p.volume for p in all_pos)
        avg_entry = (
            sum(p.price_open * p.volume for p in all_pos) / total_volume
            if total_volume > 0
            else newest.price_open
        )

        for pos in earlier:
            res = mt5_client.close_position(
                ticket=pos.ticket,
                symbol=pos.symbol,
                volume=pos.volume,
                position_type=pos.type,
                comment=f"s{signal_id}",
            )
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                realized_pnl = mt5_client.get_position_realized_pnl(pos.ticket)
                if realized_pnl is None:
                    realized_pnl = pos.profit
                await sqlite.mark_closed(pos.ticket, realized_pnl)
                await _record_exit_slippage(res, pos, mt5_client, sqlite)
                result.closed_tickets.append(pos.ticket)
                logger.info(
                    "TP closed ticket=%d signal=%d vol=%.2f pnl=%.2f",
                    pos.ticket,
                    signal_id,
                    pos.volume,
                    realized_pnl,
                )
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
                realized_pnl = mt5_client.get_position_realized_pnl(newest.ticket)
                if realized_pnl is None:
                    realized_pnl = newest.profit
                await sqlite.mark_closed(newest.ticket, realized_pnl)
                await _record_exit_slippage(res, newest, mt5_client, sqlite)
                result.closed_tickets.append(newest.ticket)
                logger.info(
                    "TP fully closed ticket=%d signal=%d vol=%.2f pnl=%.2f",
                    newest.ticket,
                    signal_id,
                    newest.volume,
                    realized_pnl,
                )
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
                if raw_vol < sym_info.volume_step:
                    close_vol = max(sym_info.volume_step, sym_info.volume_min)
                else:
                    close_vol = math.floor(raw_vol / sym_info.volume_step) * sym_info.volume_step
                    close_vol = round(close_vol, 8)
                    close_vol = max(close_vol, sym_info.volume_min)
            else:
                close_vol = round(raw_vol, 2)
            if close_vol <= 0:
                await sqlite.set_trailing(newest.ticket)
                result.trailed_tickets.append(newest.ticket)
                logger.info(
                    "TP trailing full position (vol floor=0) ticket=%d signal=%d",
                    newest.ticket,
                    signal_id,
                )
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
                    await _record_exit_slippage(res, newest, mt5_client, sqlite)
                    result.closed_tickets.append(newest.ticket)
                    result.trailed_tickets.append(newest.ticket)
                    logger.info(
                        "TP partial close %d%% ticket=%d signal=%d vol=%.2f",
                        pct,
                        newest.ticket,
                        signal_id,
                        close_vol,
                    )
                else:
                    retcode = res.retcode if res else "None"
                    msg = f"partial close failed ticket={newest.ticket} retcode={retcode}"
                    result.errors.append(msg)
                    logger.error("TP: %s signal=%d", msg, signal_id)

        realized_pnl_total = sum(
            p.profit for p in all_pos if p.ticket in set(result.closed_tickets)
        )
        result.snapshot = TriggerSnapshot(
            tp_trigger_price=tp_trigger_price,
            move_at_trigger=move_at_trigger,
            realized_pnl=realized_pnl_total,
            others_pnl=others_pnl_pre,
            total_volume=total_volume,
            avg_entry_price=avg_entry,
            partial_close_pct=pct,
            trailing_started=newest.ticket in result.trailed_tickets,
        )
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
