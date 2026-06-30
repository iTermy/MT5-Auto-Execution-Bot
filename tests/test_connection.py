from types import SimpleNamespace
from unittest.mock import patch

from bot.mt5.connection import MT5Connection


def _terminal(connected: bool) -> SimpleNamespace:
    return SimpleNamespace(connected=connected)


def test_connected_link_returns_true():
    conn = MT5Connection()
    with patch("bot.mt5.connection.mt5") as mt5:
        mt5.terminal_info.return_value = _terminal(True)
        assert conn.ensure_connected() is True
        mt5.initialize.assert_not_called()
    assert conn.is_initialized


def test_link_down_but_attached_does_not_reinitialize():
    # The "logged in elsewhere" / broker-maintenance case: terminal is attached
    # (IPC alive) but the trade-server link is down. Re-initializing here is what
    # corrupts the pipe, so ensure_connected must wait, not call initialize().
    conn = MT5Connection()
    with patch("bot.mt5.connection.mt5") as mt5:
        mt5.terminal_info.return_value = _terminal(False)
        assert conn.ensure_connected() is False
        mt5.initialize.assert_not_called()
        mt5.shutdown.assert_not_called()


def test_link_recovers_without_restart():
    # Regression: a single failed initialize used to latch _initialized False
    # forever, stranding the bot. The link dropping then returning must recover.
    conn = MT5Connection()
    with patch("bot.mt5.connection.mt5") as mt5:
        mt5.terminal_info.return_value = _terminal(False)
        assert conn.ensure_connected() is False
        mt5.terminal_info.return_value = _terminal(True)
        assert conn.ensure_connected() is True


def test_dead_ipc_reinitializes_then_throttles():
    conn = MT5Connection()
    with patch("bot.mt5.connection.mt5") as mt5:
        mt5.terminal_info.return_value = None
        mt5.initialize.return_value = True
        mt5.account_info.return_value = SimpleNamespace(login=123)
        assert conn.ensure_connected() is True
        mt5.shutdown.assert_called_once()
        mt5.initialize.assert_called_once()

        # A second immediate dead-IPC check is throttled — no re-init storm.
        mt5.terminal_info.return_value = None
        assert conn.ensure_connected() is False
        mt5.initialize.assert_called_once()
