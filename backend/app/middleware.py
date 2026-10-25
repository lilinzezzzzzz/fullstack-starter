from time import perf_counter
from uuid import uuid4

from loguru import logger
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.errors import error_response


class RequestMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        status_code = 500

        async def send_response(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                if scope["path"].startswith("/api"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        with logger.contextualize(request_id=request_id):
            try:
                try:
                    hostname = request.url.hostname
                except ValueError:
                    hostname = None
                if hostname not in self.settings.allowed_hosts:
                    response = error_response(request, "INVALID_HOST", "Host 不在允许列表中", 400)
                    await response(scope, receive, send_response)
                    return

                origin = request.headers.get("origin")
                current_origin = str(request.base_url).rstrip("/")
                if (
                    origin is not None
                    and origin != current_origin
                    and origin not in self.settings.allowed_origins
                ) or request.headers.get("sec-fetch-site") == "cross-site":
                    response = error_response(request, "INVALID_ORIGIN", "不允许此来源访问", 403)
                    await response(scope, receive, send_response)
                    return

                await self.app(scope, receive, send_response)
            finally:
                if self.settings.logging.request_logging:
                    logger.info(
                        "{} {} {} {:.1f}ms",
                        scope["method"],
                        scope["path"],
                        status_code,
                        (perf_counter() - started) * 1000,
                    )
