import logging
from collections import defaultdict
from datetime import datetime, timezone

import MetaTrader5 as mt5

from bot.config.constants import AssetClass
from bot.config.settings import Settings
from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client
from bot.mt5.types import PositionInfo
from bot.tp.asset_config import get_config
from bot.tp.default_strategy import DefaultTPStrategy
from bot.tp.strategy import TPStrategy
from bot.trading.symbol_mapper import db_symbol_from_mt5, detect_asset_class

logger = logging.getLogger(__name__)


class TPEngine:
    def __init__(self, strategy: TPStrategy | None = None) -> None:
        self._strategy: TPStrategy = strategy or DefaultTPStrategy()

    async def run_cycle(
        self,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
        config: Settings,
        crypto_only: bool = False,
    ) -> None:
        mt5_pos_map = {p.ticket: p for p in mt5_client.positions_get()}
        sqlite_rows = await sqlite.get_filled_positions()

        by_signal: dict[int, list] = defaultdict(list)
        for row in sqlite_rows:
            if row["mt5_ticket"] not in mt5_pos_map:
                continue
            if crypto_only:
                pos = mt5_pos_map[row["mt5_ticket"]]
                db_sym = db_symbol_from_mt5(pos.symbol, config)
                if detect_asset_class(db_sym) != AssetClass.CRYPTO:
                    continue
            by_signal[row["signal_id"]].append(row)

        for signal_id, rows in by_signal.items():
            try:
                await self._process_group(signal_id, rows, mt5_pos_map, mt5_client, sqlite, config)
            except Exception:
                logger.error("TPEngine: unhandled error signal=%d", signal_id, exc_info=True)

    async def _process_group(
        self,
        signal_id: int,
        rows: list,
        mt5_pos_map: dict[int, PositionInfo],
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
        config: Settings,
    ) -> None:
        trailing_rows = [r for r in rows if r["is_trailing"]]
        non_trailing_rows = [r for r in rows if not r["is_trailing"]]

        # Resolve asset class from the first position's MT5 symbol
        first_pos = mt5_pos_map[rows[0]["mt5_ticket"]]
        db_sym = db_symbol_from_mt5(first_pos.symbol, config)
        asset_class = detect_asset_class(db_sym)
        signal_type = rows[0]["signal_type"] or "standard"
        asset_cfg = get_config(asset_class, signal_type, config, instrument=db_sym)

        # 1-1: fixed TP, full close, trailing disabled — never enter the trailing path
        # even if a stray is_trailing=1 row exists.
        if trailing_rows and signal_type != "1-1":
            trailing_positions = [mt5_pos_map[r["mt5_ticket"]] for r in trailing_rows]
            result = await self._strategy.update_trailing(
                signal_id, trailing_positions, asset_cfg, mt5_client, sqlite
            )
            for err in result.errors:
                logger.error("TPEngine trail signal=%d: %s", signal_id, err)

        if non_trailing_rows:
            positions = [mt5_pos_map[r["mt5_ticket"]] for r in non_trailing_rows]
            if self._strategy.should_trigger(positions, asset_cfg, mt5_client):
                result = await self._strategy.execute(
                    signal_id, positions, asset_cfg, mt5_client, sqlite
                )
                for err in result.errors:
                    logger.error("TPEngine execute signal=%d: %s", signal_id, err)
                if result.closed_tickets or result.trailed_tickets:
                    await self._cancel_pending_for_signal(signal_id, mt5_client, sqlite)

    async def _cancel_pending_for_signal(
        self, signal_id: int, mt5_client: MT5Client, sqlite: SQLiteDB
    ) -> None:
        pending = await sqlite.get_pending_by_signal(signal_id)
        if not pending:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        for row in pending:
            ticket = row["mt5_ticket"]
            res = mt5_client.cancel_pending_order(ticket)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                await sqlite.mark_cancelled(ticket, now_iso, spread=False)
                logger.info("TP fired signal=%d — cancelled pending ticket=%d", signal_id, ticket)
            else:
                retcode = res.retcode if res else "None"
                logger.warning("TP cancel pending ticket=%d failed retcode=%s", ticket, retcode)
