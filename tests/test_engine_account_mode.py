from unittest.mock import MagicMock

from bot.core.engine import Engine
from tests.conftest import make_account_info, make_settings


def _engine(mt5: MagicMock) -> Engine:
    return Engine(mt5, MagicMock(), MagicMock(), MagicMock(), make_settings(), MagicMock())


def test_check_account_mode_blocks_netting() -> None:
    mt5 = MagicMock()
    mt5.account_info.return_value = make_account_info(margin_mode=0)
    assert _engine(mt5)._check_account_mode() is False


def test_check_account_mode_allows_hedging() -> None:
    mt5 = MagicMock()
    mt5.account_info.return_value = make_account_info(margin_mode=2)
    assert _engine(mt5)._check_account_mode() is True


def test_check_account_mode_allows_when_account_unreadable() -> None:
    # A transient account_info() failure must not block trading.
    mt5 = MagicMock()
    mt5.account_info.return_value = None
    assert _engine(mt5)._check_account_mode() is True
