import logging
import time

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

# When the IPC pipe is dead (terminal closed/crashed), throttle full re-init
# attempts so a down terminal doesn't spin initialize() every sync tick.
_REINIT_BACKOFF = 5.0  # seconds


class MT5Connection:
    def __init__(self, terminal_path: str = "") -> None:
        self._terminal_path = terminal_path
        self._initialized = False
        self._next_reinit_at = 0.0
        self._link_down_logged = False
        self.last_error: str | None = None

    def set_terminal_path(self, path: str) -> None:
        self._terminal_path = path

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def initialize(self) -> bool:
        kwargs = {}
        if self._terminal_path:
            kwargs["path"] = self._terminal_path
        if not mt5.initialize(**kwargs):
            err = mt5.last_error()
            self.last_error = (
                f"{err[0]}: {err[1]}" if isinstance(err, tuple) and len(err) >= 2 else str(err)
            )
            logger.error("MT5 initialize failed: %s", err)
            self._initialized = False
            return False
        self.last_error = None
        info = mt5.account_info()
        logger.info("MT5 initialized: account %s", info.login if info else "unknown")
        self._initialized = True
        return True

    def shutdown(self) -> None:
        mt5.shutdown()
        self._initialized = False
        logger.info("MT5 shutdown")

    def ensure_connected(self) -> bool:
        """Returns whether the terminal is currently connected to the broker's
        trade server. terminal_info() is the source of truth — never the cached
        _initialized flag, which a single failed initialize() would otherwise
        latch False forever (stranding the bot until restart).

        - IPC pipe alive (terminal_info() is not None): the terminal is attached.
          A False .connected means the broker link dropped — server maintenance,
          or another login holding the account's single session (e.g. the user
          opens the terminal on their laptop while the VPS runs the bot). The
          terminal re-establishes the link on its own once the slot frees, so we
          must NOT re-initialize here: re-initializing a live-but-disconnected
          terminal is what corrupts the IPC pipe and triggers the auth-fail
          cascade (-6 → endless -10004). Just wait and re-check next cycle.
        - IPC pipe dead (terminal_info() is None): the terminal closed, crashed,
          or was never attached — the only case a full re-initialize fixes.
          Throttled so a down terminal doesn't spin initialize() every tick.
        """
        info = mt5.terminal_info()
        if info is not None:
            self._initialized = True
            if info.connected:
                if self._link_down_logged:
                    logger.info("MT5 trade-server link restored")
                    self._link_down_logged = False
                return True
            if not self._link_down_logged:
                logger.warning(
                    "MT5 trade-server link down — terminal still attached, waiting for it "
                    "to reconnect (broker maintenance or account logged in elsewhere)"
                )
                self._link_down_logged = True
            return False

        self._initialized = False
        now = time.monotonic()
        if now < self._next_reinit_at:
            return False
        self._next_reinit_at = now + _REINIT_BACKOFF
        logger.warning("MT5 IPC connection lost — terminal closed or crashed; reconnecting")
        mt5.shutdown()
        if self.initialize():
            logger.info("MT5 reconnected")
            return True
        return False
