import logging

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class MT5Connection:
    def __init__(self, terminal_path: str = "") -> None:
        self._terminal_path = terminal_path
        self._initialized = False
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
        if not self._initialized:
            return False
        info = mt5.terminal_info()
        if info is not None and info.connected:
            return True
        logger.warning(
            "MT5 connection lost — terminal closed, crashed, or unreachable; reconnecting"
        )
        self._initialized = False
        if self.initialize():
            logger.info("MT5 reconnected")
            return True
        return False
