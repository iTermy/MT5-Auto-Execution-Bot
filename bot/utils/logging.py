import asyncio
import logging
from datetime import UTC, datetime

_LOG_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=1000)


class SSELogHandler(logging.Handler):
    def __init__(self, queue: asyncio.Queue) -> None:
        super().__init__()
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(
                {
                    "level": record.levelname,
                    "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                    "message": record.getMessage(),
                }
            )
        except asyncio.QueueFull:
            pass


def get_log_queue() -> asyncio.Queue:
    return _LOG_QUEUE


def setup_logging(level: int = logging.INFO, log_file: str = "bot.log") -> None:
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8"),
        SSELogHandler(_LOG_QUEUE),
    ]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=level, handlers=handlers, force=True)
