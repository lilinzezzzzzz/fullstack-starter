"""仅保存插桩元数据的 OpenTelemetry API 适配器，不持有真实 SDK 资源。"""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass

from opentelemetry.context import Context
from opentelemetry.trace import Link, Span, SpanKind, Tracer, TracerProvider
from opentelemetry.util.types import Attributes

from app.telemetry.provider import get_tracer_provider


@dataclass(frozen=True)
class _TracerAdapter(Tracer):
    name: str
    version: str | None
    schema_url: str | None
    attributes: Attributes

    def _current_tracer(self) -> Tracer:
        # FastAPI 可以缓存本适配器，每次 span 操作都重新取得活跃作用域的 tracer。
        return get_tracer_provider().get_tracer(
            self.name,
            self.version,
            schema_url=self.schema_url,
            attributes=self.attributes,
        )

    def start_span(
        self,
        name: str,
        context: Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ) -> Span:
        return self._current_tracer().start_span(
            name,
            context=context,
            kind=kind,
            attributes=attributes,
            links=links,
            start_time=start_time,
            record_exception=record_exception,
            set_status_on_exception=set_status_on_exception,
        )

    def start_as_current_span(
        self,
        name: str,
        context: Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
        end_on_exit: bool = True,
    ) -> AbstractContextManager[Span]:
        # 返回 SDK 自身的上下文管理器，保留其异常处理和上下文恢复行为。
        return self._current_tracer().start_as_current_span(
            name,
            context=context,
            kind=kind,
            attributes=attributes,
            links=links,
            start_time=start_time,
            record_exception=record_exception,
            set_status_on_exception=set_status_on_exception,
            end_on_exit=end_on_exit,
        )


class TracerProviderAdapter(TracerProvider):
    """供 FastAPI 构建时注入的稳定入口；真实 provider 由 lifespan 管理。"""

    def get_tracer(
        self,
        instrumenting_module_name: str,
        instrumenting_library_version: str | None = None,
        schema_url: str | None = None,
        attributes: Attributes = None,
    ) -> Tracer:
        return _TracerAdapter(
            instrumenting_module_name,
            instrumenting_library_version,
            schema_url,
            attributes,
        )
