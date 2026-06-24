import asyncio
import logging
import logging.handlers
import sys
import threading
from datetime import UTC, datetime

_LOG_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=1000)

logger = logging.getLogger(__name__)


class SSELogHandler(logging.Handler):
    def __init__(self, queue: asyncio.Queue) -> None:
        super().__init__()
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        # The file log carries the full traceback; the UI gets a one-line summary
        # (ExcType: message) so users can deduce the cause without the noise.
        message = record.getMessage()
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value = record.exc_info[0], record.exc_info[1]
            message = f"{message} ({exc_type.__name__}: {exc_value})"
        try:
            self._queue.put_nowait(
                {
                    "level": record.levelname,
                    "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                    "message": message,
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
    # Rotate so a long-running VPS bot doesn't grow an unbounded log; keep enough
    # history that a crash the user reports hours later is still on disk.
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        file_handler,
        SSELogHandler(_LOG_QUEUE),
    ]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=level, handlers=handlers, force=True)
    _install_excepthooks()


def _install_excepthooks() -> None:
    """Route otherwise-silent crashes to the log so a bot that 'just disappeared'
    still leaves a diagnosable record. Covers the main thread (tray) and worker
    threads (the engine runs in one) — a crash there would otherwise kill the loop
    while the tray icon keeps the app looking alive."""

    def _main_hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread else "?"
        logger.critical(
            "Uncaught exception in thread %s",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook
