import time
from unittest.mock import MagicMock

import MetaTrader5 as mt5

from bot.mt5.client import MT5Client
from tests.conftest import make_symbol_info

# symbol_info.filling_mode bits (MT5 spec): FOK=1, IOC=2.
_FOK = 1
_IOC = 2

# resolve_filling reads symbol_info; pre-populating the client's cache avoids any
# real MT5 call (symbol_info returns the cached value).


def _client_with_filling(mode: int) -> MT5Client:
    client = MT5Client(MagicMock())
    client._symbol_info_cache["X"] = (
        time.monotonic(),
        make_symbol_info(name="X", filling_mode=mode),
    )
    return client


def test_resolve_filling_prefers_ioc() -> None:
    client = _client_with_filling(_IOC | _FOK)
    assert client.resolve_filling("X") == mt5.ORDER_FILLING_IOC


def test_resolve_filling_fok_only() -> None:
    client = _client_with_filling(_FOK)
    assert client.resolve_filling("X") == mt5.ORDER_FILLING_FOK


def test_resolve_filling_falls_back_to_return() -> None:
    client = _client_with_filling(0)
    assert client.resolve_filling("X") == mt5.ORDER_FILLING_RETURN
