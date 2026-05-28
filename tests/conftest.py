import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock

import MetaTrader5 as mt5

from bot.config.settings import (
    Settings, LotSizingConfig, PollingConfig, SpreadHourConfig,
    TPConfig, AssetTPConfig,
)
from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client
from bot.mt5.types import AccountInfo, OrderInfo, OrderResult, PositionInfo, SymbolInfo, TickInfo


# ---------------------------------------------------------------------------
# Factory helpers — used by multiple test modules
# ---------------------------------------------------------------------------

def make_settings(**overrides) -> Settings:
    base = dict(
        license_key="test-key",
        lot_sizing=LotSizingConfig(mode="risk_percent", risk_percent=1.0, fixed_lot=0.01, max_lot_per_order=5.0),
        polling=PollingConfig(),
        tp_config=TPConfig(
            partial_close_percent=50,
            forex=AssetTPConfig(profit_threshold=7, threshold_unit="pips", trailing_distance=3),
            forex_jpy=AssetTPConfig(profit_threshold=7, threshold_unit="pips", trailing_distance=3),
            metals=AssetTPConfig(profit_threshold=4.0, threshold_unit="dollars", trailing_distance=2.0),
            indices=AssetTPConfig(profit_threshold=20.0, threshold_unit="dollars", trailing_distance=5.0),
            stocks=AssetTPConfig(profit_threshold=1.0, threshold_unit="dollars", trailing_distance=0.5),
            crypto=AssetTPConfig(profit_threshold=300.0, threshold_unit="dollars", trailing_distance=50.0),
            oil=AssetTPConfig(profit_threshold=0.5, threshold_unit="dollars", trailing_distance=0.2),
        ),
    )
    base.update(overrides)
    return Settings(**base)


def make_symbol_info(**overrides) -> SymbolInfo:
    defaults = dict(
        name="EURUSD",
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_tick_value=1.0,
        trade_tick_size=0.00001,
        trade_contract_size=100000.0,
    )
    defaults.update(overrides)
    return SymbolInfo(**defaults)


def make_tick(**overrides) -> TickInfo:
    defaults = dict(symbol="EURUSD", bid=1.10000, ask=1.10002, time=0)
    defaults.update(overrides)
    return TickInfo(**defaults)


def make_position(**overrides) -> PositionInfo:
    defaults = dict(
        ticket=1001,
        symbol="EURUSD",
        volume=0.1,
        type=0,
        price_open=1.09000,
        sl=1.08500,
        tp=0.0,
        profit=0.0,
        magic=20250001,
        comment="s1",
        time=0,
        identifier=1001,
    )
    defaults.update(overrides)
    return PositionInfo(**defaults)


def make_order_info(**overrides) -> OrderInfo:
    defaults = dict(
        ticket=1001,
        symbol="EURUSD",
        volume_current=0.1,
        type=2,
        price_open=1.09000,
        sl=1.08500,
        tp=0.0,
        magic=20250001,
        comment="s1",
        time_setup=0,
    )
    defaults.update(overrides)
    return OrderInfo(**defaults)


def make_order_result(retcode=None, ticket=1001) -> OrderResult:
    return OrderResult(
        retcode=retcode if retcode is not None else mt5.TRADE_RETCODE_DONE,
        ticket=ticket,
        volume=0.1,
        price=1.09000,
        comment="done",
    )


def make_account_info(**overrides) -> AccountInfo:
    defaults = dict(
        login=123456, balance=10000.0, equity=10000.0,
        margin=0.0, margin_free=10000.0, leverage=100, currency="USD",
    )
    defaults.update(overrides)
    return AccountInfo(**defaults)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def sqlite_db():
    db = SQLiteDB(":memory:")
    await db.init_schema()
    yield db
    await db.close()


@pytest.fixture
def mock_mt5() -> MagicMock:
    client = MagicMock(spec=MT5Client)
    client.orders_get.return_value = []
    client.positions_get.return_value = []
    client.ensure_connected.return_value = True
    client.symbol_info.return_value = make_symbol_info()
    client.symbol_info_tick.return_value = make_tick()
    return client


@pytest.fixture
def sample_config() -> Settings:
    return make_settings()
