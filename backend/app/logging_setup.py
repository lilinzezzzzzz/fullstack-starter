import logging
import sys

from loguru import logger

from app.config import LoggingSettings


class InterceptHandler(logging.Handler):
    """Forward Uvicorn's standard logging to the same Loguru sinks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info).log(level, record.getMessage())


def configure_logging(settings: LoggingSettings) -> None:
    settings.directory.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(extra={"request_id": "-"})
    options = {
        "level": settings.level,
        "format": settings.format,
        "backtrace": False,
        "diagnose": False,
        "enqueue": False,
        "colorize": False,
        "serialize": settings.serialize,
        "catch": True,
    }
    logger.add(
        settings.directory / settings.filename,
        rotation=settings.rotation,
        retention=settings.retention,
        compression=None if settings.compression == "none" else settings.compression,
        encoding="utf-8",
        **options,
    )
    if settings.console:
        logger.add(sys.stderr, **options)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        standard_logger = logging.getLogger(name)
        standard_logger.handlers = [InterceptHandler()]
        standard_logger.setLevel(logging.DEBUG)
        standard_logger.propagate = False
