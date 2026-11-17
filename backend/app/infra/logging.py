import logging as std_logging
import sys

from loguru import logger

from app.config import settings


class InterceptHandler(std_logging.Handler):
    """将 Uvicorn 的标准日志转发到相同的 Loguru 输出目标。"""

    def emit(self, record: std_logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info).log(level, record.getMessage())


def configure_logging() -> None:
    logging_settings = settings.logging
    logging_settings.directory.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(extra={"trace_id": "-"})
    options = {
        "level": logging_settings.level,
        "format": logging_settings.format,
        "backtrace": logging_settings.backtrace,
        "diagnose": logging_settings.diagnose,
        "enqueue": logging_settings.enqueue,
        "colorize": logging_settings.colorize,
        "serialize": logging_settings.serialize,
        "catch": logging_settings.catch,
    }
    logger.add(
        logging_settings.directory / logging_settings.filename,
        rotation=logging_settings.rotation,
        retention=logging_settings.retention,
        compression=logging_settings.compression_format,
        encoding="utf-8",
        **options,
    )
    if logging_settings.console:
        logger.add(sys.stderr, **options)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        standard_logger = std_logging.getLogger(name)
        standard_logger.handlers = [InterceptHandler()]
        standard_logger.setLevel(std_logging.DEBUG)
        standard_logger.propagate = False
