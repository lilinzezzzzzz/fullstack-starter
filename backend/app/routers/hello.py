from fastapi import APIRouter, Request

from app.schemas.hello import HelloResponse
from app.services import hello

router = APIRouter(prefix="/v1", tags=["hello"])


@router.get("/hello", response_model=HelloResponse, operation_id="get_hello")
def get_hello(request: Request) -> HelloResponse:
    return hello.say_hello(request.app.state.settings.application.title)
