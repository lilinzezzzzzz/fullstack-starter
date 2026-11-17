"""只转发属性读取的延迟代理；目标缓存和生命周期由 getter 管理。

创建代理和 repr() 不调用 getter。赋值、删除、调用、迭代等协议不转发，
布尔判断和真实类型检查也不代表目标状态；需要真实对象时应直接调用 getter。
"""

from collections.abc import Callable
from typing import Any, cast


def lazy_proxy[T](getter: Callable[[], T]) -> T:
    """创建属性读取代理，返回类型仅用于目标属性的静态提示。"""
    return cast(T, _LazyProxy(getter))


class _LazyProxy[T]:
    __slots__ = ("_getter",)

    def __init__(self, getter: Callable[[], T]) -> None:
        object.__setattr__(self, "_getter", getter)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._getter(), name)

    def __repr__(self) -> str:
        return "<_LazyProxy>"
