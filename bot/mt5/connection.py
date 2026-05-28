import logging

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class MT5Connection:
    def initialize(self) -> bool:
        if not mt5.initialize():
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
