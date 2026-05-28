from dataclasses import dataclass, field
from typing import Protocol

from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client
from bot.mt5.types import PositionInfo
from bot.tp.asset_config import AssetClassConfig


@dataclass
class TPResult:
    closed_tickets: list[int] = field(default_factory=list)
    trailed_tickets: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class TPStrategy(Protocol):
    def should_trigger(
        self,
        positions: list[PositionInfo],
        asset_config: AssetClassConfig,
        mt5_client: MT5Client,
    ) -> bool:
        """Return True if TP trigger conditions are met for this position group."""

    async def execute(
        self,
        signal_id: int,
        positions: list[PositionInfo],
        asset_config: AssetClassConfig,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
    ) -> TPResult:
        """Close earlier positions, partial-close newest, enter trailing phase."""

    async def update_trailing(
        self,
        signal_id: int,
        positions: list[PositionInfo],
        asset_config: AssetClassConfig,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
    ) -> TPResult:
        """Ratchet SL for all trailing positions in this group."""
