from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.utils.lazy_proxy import lazy_proxy


def test_proxy_defers_reads_and_leaves_target_caching_to_getter() -> None:
    first = SimpleNamespace(value=0)
    getter = Mock(return_value=first)
    proxy = lazy_proxy(getter)
    assert repr(proxy) == "<_LazyProxy>"
    assert bool(proxy) is True
    getter.assert_not_called()
    assert proxy.value == 0
    getter.return_value = SimpleNamespace(value=False)
    assert proxy.value is False
    assert getter.call_count == 2


def test_proxy_preserves_getter_error_and_does_not_forward_assignment() -> None:
    target = SimpleNamespace(value="unchanged")
    getter = Mock(return_value=target)
    proxy = lazy_proxy(getter)
    with pytest.raises(AttributeError):
        proxy.value = "replacement"
    with pytest.raises(AttributeError):
        del proxy.value
    assert target.value == "unchanged"
    error = ValueError("configuration unavailable")
    getter.side_effect = error
    with pytest.raises(ValueError) as raised:
        _ = proxy.value
    assert raised.value is error
