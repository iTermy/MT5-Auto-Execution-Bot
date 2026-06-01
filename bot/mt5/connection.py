import logging

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class MT5Connection:
    def __init__(self, terminal_path: str = "") -> None:
        self._terminal_path = terminal_path

    def initialize(self) -> bool:
        kwargs = {}
        if self._terminal_path:
            kwargs["path"] = self._terminal_path
        if not mt5.initialize(**kwargs):
            logger.error("MT5 initialize failed: %s", mt5.last_error())
            return False
        info = mt5.account_info()
        logger.info("MT5 initialized: account %s", info.login if info else "unknown")
        return True

    def shutdown(self) -> None:
        mt5.shutdown()
        logger.info("MT5 shutdown")

    def ensure_connected(self) -> bool:
        if mt5.terminal_info() is not None:
            return True
        logger.warning("MT5 connection lost, reconnecting")
        return self.initialize()
