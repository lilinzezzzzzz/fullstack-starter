from time import perf_counter

from loguru import logger
from opentelemetry.propagate import inject
from opentelemetry.trace import format_trace_id, get_current_span
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.infra.errors import error_response


class RequestMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        span_context = get_current_span().get_span_context()
        if not span_context.is_valid:
            raise RuntimeError("FastAPI native telemetry did not create a valid request context")
        trace_id = format_trace_id(span_context.trace_id)
        carrier: dict[str, str] = {}
        inject(carrier)
        traceparent = carrier["traceparent"]
        request.state.trace_id = trace_id
        # 保留当前服务端上下文，供中间件退出后的 500 响应共用。
        request.state.traceparent = traceparent
        started = perf_counter()
        status_code = 500

        async def send_response(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["traceparent"] = traceparent
                headers["X-Content-Type-Options"] = "nosniff"
                if scope["path"].startswith("/api"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        with logger.contextualize(trace_id=trace_id):
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
