from fastapi import APIRouter

from app.routers import health, hello
from app.schemas.common import ErrorResponse

router = APIRouter(
    prefix="/api",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
router.include_router(health.router)
router.include_router(hello.router)
