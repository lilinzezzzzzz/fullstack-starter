from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.schemas.hello import HelloResponse
from app.services.hello import HelloService, new_hello_service

router = APIRouter(prefix="/v1", tags=["hello"])


def get_hello_service(request: Request) -> HelloService:
    return new_hello_service(request.app.state.settings.application.title)


@router.get("/hello", response_model=HelloResponse, operation_id="get_hello")
def get_hello(service: Annotated[HelloService, Depends(get_hello_service)]) -> HelloResponse:
    return HelloResponse(message=service.greet())
