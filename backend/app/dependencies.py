from fastapi import Request

from app.services.hello import HelloService


def new_hello_service(request: Request) -> HelloService:
    return HelloService(
        application_title=request.app.state.settings.application.title,
    )
