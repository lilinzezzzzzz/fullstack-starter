from functools import cache


class HelloService:
    """Business behavior for the Hello example."""

    def greet(self) -> str:
        return "Hello World"


@cache
def new_hello_service() -> HelloService:
    return HelloService()
