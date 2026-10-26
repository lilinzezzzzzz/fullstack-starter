from typing import Annotated

from fastapi import APIRouter, Depends

from app.schemas.hello import HelloResponse
from app.services.hello import HelloService, new_hello_service

router = APIRouter(prefix="/v1", tags=["hello"])


@router.get("/hello", response_model=HelloResponse, operation_id="get_hello")
def get_hello(service: Annotated[HelloService, Depends(new_hello_service)]) -> HelloResponse:
    return HelloResponse(message=service.greet())
