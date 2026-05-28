import logging
from collections import defaultdict

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
    ) -> None:
        mt5_pos_map = {p.ticket: p for p in mt5_client.positions_get()}
        sqlite_rows = await sqlite.get_filled_positions()

        # Group rows by signal_id, keeping only those with a live MT5 position
        by_signal: dict[int, list] = defaultdict(list)
        for row in sqlite_rows:
            if row["mt5_ticket"] in mt5_pos_map:
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
        is_scalp = bool(rows[0]["is_scalp"])
        asset_cfg = get_config(asset_class, is_scalp, config, instrument=db_sym)

        if trailing_rows:
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
