import asyncio
import json

import httpx2
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from loguru import logger
from opentelemetry import trace

from app.config import Settings
from app.main import create_app
from tests.helpers import response_trace_context, response_trace_id

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_ID = "00f067aa0ba902b7"
TRACEPARENT = f"00-{TRACE_ID}-{PARENT_ID}-01"


@pytest.mark.parametrize(
    "traceparent",
    [
        TRACEPARENT,
        f" {TRACEPARENT}",
        f"{TRACEPARENT} ",
        f"00-{TRACE_ID}-{PARENT_ID}-00",
        f"00-{TRACE_ID}-{PARENT_ID}-ff",
        f"01-{TRACE_ID}-{PARENT_ID}-01",
        f"01-{TRACE_ID}-{PARENT_ID}-01-opaque-extension",
    ],
)
@pytest.mark.parametrize("path", ["/api/v1/hello", "/api/not-found"])
def test_valid_traceparent_correlates_success_and_errors(
    client: TestClient, traceparent: str, path: str
) -> None:
    response = client.get(path, headers={"TraceParent": traceparent, "X-Trace-ID": "ignored"})
    assert response.status_code == (200 if path.endswith("hello") else 404)
    assert response_trace_id(response.headers) == TRACE_ID
    assert "x-request-id" not in response.headers
    if response.is_error:
        assert response.json()["trace_id"] == TRACE_ID


@pytest.mark.parametrize(
    "traceparent",
    [
        "",
        "invalid",
        f"00-{'0' * 32}-{PARENT_ID}-01",
        f"00-{TRACE_ID}-{'0' * 16}-01",
        f"ff-{TRACE_ID}-{PARENT_ID}-01",
        f"00-{TRACE_ID.upper()}-{PARENT_ID}-01",
        f"00-{TRACE_ID}-{PARENT_ID.upper()}-01",
        f"00-{'g' * 32}-{PARENT_ID}-01",
        f"00-{TRACE_ID[:-1]}-{PARENT_ID}-01",
        f"00-{TRACE_ID}-{PARENT_ID[:-1]}-01",
        f"00-{TRACE_ID}-{PARENT_ID}-1",
        f"00-{TRACE_ID}-{PARENT_ID}-gg",
        f"00-{TRACE_ID}-{PARENT_ID}-01-extra",
        f"01-{TRACE_ID}-{PARENT_ID}-01extra",
        f"{TRACEPARENT},{TRACEPARENT}",
    ],
)
def test_invalid_traceparent_creates_sdk_context(client: TestClient, traceparent: str) -> None:
    response = client.get("/api/not-found", headers={"traceparent": traceparent})
    assert response.status_code == 404
    identifier = response_trace_id(response.headers)
    assert len(identifier) == 32
    assert identifier == identifier.lower()
    assert int(identifier, 16) != 0
    assert identifier != TRACE_ID
    assert response.json()["trace_id"] == identifier


@pytest.mark.parametrize("first", [TRACEPARENT, "invalid"])
def test_duplicate_traceparent_headers_follow_sdk_first_value(
    client: TestClient, first: str
) -> None:
    response = client.get(
        "/api/not-found",
        headers=[("traceparent", first), ("traceparent", TRACEPARENT)],
    )
    identifier = response_trace_id(response.headers)
    assert len(identifier) == 32 and int(identifier, 16) != 0
    assert (identifier == TRACE_ID) == (first == TRACEPARENT)
    assert response.json()["trace_id"] == identifier


def test_related_requests_share_the_inbound_trace_id(client: TestClient) -> None:
    first = client.get("/api/v1/hello", headers={"traceparent": TRACEPARENT})
    second = client.get(
        "/api/v1/hello", headers={"traceparent": f"00-{TRACE_ID}-0123456789abcdef-01"}
    )
    assert response_trace_id(first.headers) == response_trace_id(second.headers) == TRACE_ID


def test_response_traceparent_uses_server_context_instead_of_echoing_parent(
    settings: Settings,
) -> None:
    app = create_app(settings)

    @app.get("/api/response-context")
    def observe() -> dict[str, str | int]:
        context = trace.get_current_span().get_span_context()
        return {
            "trace_id": trace.format_trace_id(context.trace_id),
            "span_id": trace.format_span_id(context.span_id),
            "trace_flags": int(context.trace_flags),
        }

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            "/api/response-context",
            headers={"traceparent": TRACEPARENT, "tracestate": "vendor=opaque"},
        )
    assert response.status_code == 200
    context = response_trace_context(response.headers)
    assert trace.format_trace_id(context.trace_id) == response.json()["trace_id"] == TRACE_ID
    assert trace.format_span_id(context.span_id) == response.json()["span_id"]
    assert trace.format_span_id(context.span_id) != PARENT_ID
    assert int(context.trace_flags) == response.json()["trace_flags"]
    assert response.headers["traceparent"] != TRACEPARENT
    assert "tracestate" not in response.headers


@pytest.mark.anyio
async def test_overlapping_requests_isolate_trace_context_and_restore_logs(
    settings: Settings,
) -> None:
    logging = settings.logging.model_copy(update={"serialize": True})
    app = create_app(settings.model_copy(update={"logging": logging}))
    both_arrived = asyncio.Event()
    arrivals = 0

    @app.get("/api/trace-context")
    async def observe_context(request: Request) -> dict[str, str]:
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            both_arrived.set()
        await both_arrived.wait()
        logger.info("trace-context-probe")
        return {"trace_id": request.state.trace_id}

    identifiers = [TRACE_ID, "0123456789abcdef0123456789abcdef"]
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client,
    ):
        responses = await asyncio.wait_for(
            asyncio.gather(
                *(
                    client.get(
                        "/api/trace-context",
                        headers={"traceparent": f"00-{identifier}-{PARENT_ID}-01"},
                    )
                    for identifier in identifiers
                )
            ),
            timeout=5,
        )
        logger.info("outside-trace-probe")

    for response, identifier in zip(responses, identifiers, strict=True):
        assert response.status_code == 200
        assert response.json() == {"trace_id": identifier}
        assert response_trace_id(response.headers) == identifier

    records = [
        json.loads(line)["record"]
        for line in (logging.directory / logging.filename).read_text().splitlines()
    ]
    contexts = [record["extra"] for record in records if record["message"] == "trace-context-probe"]
    assert sorted(context["trace_id"] for context in contexts) == sorted(identifiers)
    assert all(set(context) == {"trace_id"} for context in contexts)
    outside = next(record for record in records if record["message"] == "outside-trace-probe")
    assert outside["extra"] == {"trace_id": "-"}


@pytest.mark.anyio
async def test_cancelled_request_releases_native_trace_context(settings: Settings) -> None:
    app = create_app(settings)
    entered = asyncio.Event()
    waiting = asyncio.Event()

    @app.get("/api/cancel-context")
    async def wait_until_cancelled() -> None:
        entered.set()
        await waiting.wait()

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client,
    ):
        task = asyncio.create_task(
            client.get("/api/cancel-context", headers={"traceparent": TRACEPARENT})
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not trace.get_current_span().get_span_context().is_valid
        response = await client.get("/api/v1/hello")
        assert response.status_code == 200
        assert response_trace_id(response.headers) != TRACE_ID
