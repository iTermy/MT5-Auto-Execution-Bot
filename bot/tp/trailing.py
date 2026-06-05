import logging

import MetaTrader5 as mt5

from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client
from bot.mt5.types import PositionInfo, TickInfo
from bot.tp.asset_config import AssetClassConfig

logger = logging.getLogger(__name__)


class TrailingStopManager:
    async def update(
        self,
        position: PositionInfo,
        tick: TickInfo,
        asset_config: AssetClassConfig,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
    ) -> bool:
        sym = mt5_client.symbol_info(position.symbol)
        if sym is None:
            return False

        if asset_config.threshold_unit == "pips":
            pip_sz = sym.point * (10 if sym.digits in (3, 5) else 1)
            trail_dist = asset_config.trailing_distance * pip_sz
        else:
            trail_dist = asset_config.trailing_distance

        trail_dist = round(trail_dist, sym.digits)

        if position.type == 0:  # long — SL ratchets up
            new_sl = round(tick.bid - trail_dist, sym.digits)
            # Only move SL up (favorable); allow initial set when sl==0
            if position.sl > 0 and new_sl <= position.sl:
                return False
        else:  # short — SL ratchets down
            new_sl = round(tick.ask + trail_dist, sym.digits)
            # Only move SL down (favorable); allow initial set when sl==0
            if position.sl > 0 and new_sl >= position.sl:
                return False

        res = mt5_client.modify_position_sl(position.ticket, position.symbol, new_sl)
        if res is not None and res.retcode == mt5.TRADE_RETCODE_NO_CHANGES:
            return False
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = res.retcode if res else "None"
            logger.error("Trail SL failed ticket=%d retcode=%s", position.ticket, retcode)
            return False

        await sqlite.update_sl(position.ticket, new_sl)
        logger.debug("Trail SL ticket=%d new_sl=%.5f", position.ticket, new_sl)
        return True
