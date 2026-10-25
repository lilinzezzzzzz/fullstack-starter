from app.schemas.hello import HelloResponse


def say_hello(application_title: str) -> HelloResponse:
    return HelloResponse(message=f"Hello, {application_title}!")
