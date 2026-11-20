from collections.abc import AsyncIterator

import httpx
import pytest
from starlette.types import Receive, Scope, Send

from sourcehaven.api.upload_limit import UploadSizeLimitMiddleware

LIMIT: int = 100


class RecordingApp:
    """Reads the whole request body, like a form parser, and records that it ran."""

    def __init__(self) -> None:
        self.calls: int = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.calls += 1
        more: bool = True
        while more:
            message = await receive()
            more = bool(message.get("more_body", False))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def _client(inner: RecordingApp) -> httpx.AsyncClient:
    guarded: UploadSizeLimitMiddleware = UploadSizeLimitMiddleware(
        inner, method="POST", path="/up", max_body_bytes=LIMIT
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded), base_url="http://t")


async def test_declared_oversize_never_reaches_the_app() -> None:
    inner: RecordingApp = RecordingApp()
    async with _client(inner) as client:
        response: httpx.Response = await client.post("/up", content=b"x" * (LIMIT + 1))
    assert (response.status_code, response.json()) == (413, {"code": "too_large"})
    assert inner.calls == 0


async def test_chunked_oversize_is_aborted_while_streaming() -> None:
    inner: RecordingApp = RecordingApp()

    async def body() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 30

    async with _client(inner) as client:
        response: httpx.Response = await client.post("/up", content=body())
    assert (response.status_code, response.json()) == (413, {"code": "too_large"})


@pytest.mark.parametrize(("method", "path"), [("POST", "/other"), ("GET", "/up")])
async def test_other_requests_are_not_limited(method: str, path: str) -> None:
    inner: RecordingApp = RecordingApp()
    async with _client(inner) as client:
        response: httpx.Response = await client.request(method, path, content=b"x" * 500)
    assert response.status_code == 204 and inner.calls == 1


async def test_body_within_the_limit_passes() -> None:
    inner: RecordingApp = RecordingApp()
    async with _client(inner) as client:
        response: httpx.Response = await client.post("/up", content=b"x" * LIMIT)
    assert response.status_code == 204 and inner.calls == 1
