from functools import cache


class HelloService:
    """Hello 示例的业务行为。"""

    def greet(self) -> str:
        return "Hello World"


@cache
def new_hello_service() -> HelloService:
    return HelloService()
