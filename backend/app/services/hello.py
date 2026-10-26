from fastapi import Request


class HelloService:
    """Business behavior for the Hello example."""

    def __init__(self, application_title: str) -> None:
        self._application_title = application_title

    def greet(self) -> str:
        return f"Hello, {self._application_title}!"


def new_hello_service(request: Request) -> HelloService:
    return HelloService(
        application_title=request.app.state.settings.application.title,
    )
