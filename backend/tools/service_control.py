"""读取显式 TOML 配置，并在前台运行单 worker Uvicorn。"""

import argparse
from pathlib import Path

import uvicorn
from loguru import logger

from app.config import CONFIG_FILE, load_settings
from app.logging_setup import configure_logging
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local service in the foreground")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        configure_logging(settings.logging)
        uvicorn.run(
            create_app(settings),
            host=settings.server.host,
            port=settings.server.port,
            workers=settings.server.workers,
            timeout_graceful_shutdown=settings.server.graceful_shutdown_seconds,
            timeout_keep_alive=settings.server.keep_alive_seconds,
            backlog=settings.server.backlog,
            limit_concurrency=(
                None
                if settings.server.concurrency_limit == 0
                else settings.server.concurrency_limit
            ),
            log_config=None,
            access_log=False,
            proxy_headers=False,
            forwarded_allow_ips=[],
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    finally:
        logger.complete()


if __name__ == "__main__":
    main()
