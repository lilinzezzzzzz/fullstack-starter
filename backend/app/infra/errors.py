import sqlite3
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException

from app.schemas.common import ErrorDetail, ErrorResponse


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def error_response(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    details: list[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "unavailable")
    traceparent = getattr(request.state, "traceparent", None)
    body = ErrorResponse(code=code, message=message, details=details or [], trace_id=trace_id)
    response_headers = {
        **(headers if headers is not None else {}),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if traceparent is not None:
        response_headers["traceparent"] = traceparent
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
        headers=response_headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.code, exc.message, exc.status_code)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else f"HTTP_{exc.status_code}"
        headers = {
            key: value
            for key, value in (exc.headers.items() if exc.headers is not None else ())
            if key.lower() in {"allow", "www-authenticate", "retry-after"}
        }
        return error_response(request, code, str(exc.detail), exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 仅返回字段错误信息，不返回被拒绝的请求体或任意异常上下文。
        details = [
            ErrorDetail(field=".".join(str(part) for part in item["loc"]), message=item["msg"])
            for item in exc.errors()
        ]
        return error_response(request, "VALIDATION_ERROR", "请求参数无效", 422, details)

    @app.exception_handler(OperationalError)
    async def database_error(request: Request, exc: OperationalError) -> JSONResponse:
        sqlite_code = getattr(exc.orig, "sqlite_errorcode", 0)
        if sqlite_code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return error_response(request, "DATABASE_BUSY", "数据库正忙，请稍后重试", 503)
        return await unexpected_error(request, exc)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unavailable")
        # 异常到达 ServerErrorMiddleware 时，Exception 处理器在 RequestMiddleware 外运行，
        # 因此仅为本条日志恢复请求上下文。
        with logger.contextualize(trace_id=trace_id):
            logger.opt(exception=exc).error("Unhandled request error")
        return error_response(request, "INTERNAL_ERROR", "服务暂时不可用，请稍后重试", 500)
