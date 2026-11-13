import logging as std_logging
import sys

from loguru import logger

from app.config import LoggingSettings


class InterceptHandler(std_logging.Handler):
    """将 Uvicorn 的标准日志转发到相同的 Loguru 输出目标。"""

    def emit(self, record: std_logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info).log(level, record.getMessage())


def configure_logging(settings: LoggingSettings) -> None:
    settings.directory.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(extra={"trace_id": "-"})
    options = {
        "level": settings.level,
        "format": settings.format,
        "backtrace": settings.backtrace,
        "diagnose": settings.diagnose,
        "enqueue": settings.enqueue,
        "colorize": settings.colorize,
        "serialize": settings.serialize,
        "catch": settings.catch,
    }
    logger.add(
        settings.directory / settings.filename,
        rotation=settings.rotation,
        retention=settings.retention,
        compression=settings.compression_format,
        encoding="utf-8",
        **options,
    )
    if settings.console:
        logger.add(sys.stderr, **options)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        standard_logger = std_logging.getLogger(name)
        standard_logger.handlers = [InterceptHandler()]
        standard_logger.setLevel(std_logging.DEBUG)
        standard_logger.propagate = False
