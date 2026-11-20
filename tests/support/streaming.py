"""In-process streaming HTTP and server-sent-event helpers for tests.

`httpx.ASGITransport` collects the whole response body before returning, so it can neither show
that an event arrives before generation finishes nor simulate a client that disconnects mid-stream.
`StreamingASGITransport` runs the app in its own task, hands body chunks over as they are sent,
and reports `http.disconnect` to the app once the client closes the response.
"""

import asyncio
import json
from collections.abc import AsyncIterator, MutableMapping
from dataclasses import dataclass
from typing import Any, Final

import httpx
from starlette.types import ASGIApp, Message

EVENT_TIMEOUT_SECONDS: Final[float] = 10.0
APP_SHUTDOWN_TIMEOUT_SECONDS: Final[float] = 10.0


@dataclass(frozen=True)
class SseEvent:
    """One server-sent event; `data` is its decoded JSON payload."""

    name: str
    # The payload is untyped JSON; tests index into it freely.
    data: dict[str, Any]


def _parse_block(lines: list[str]) -> SseEvent | None:
    name: str | None = None
    data_lines: list[str] = []
    for line in lines:
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            name = value
        elif field == "data":
            data_lines.append(value)
    if name is None and not data_lines:
        return None
    data: dict[str, Any] = json.loads("\n".join(data_lines)) if data_lines else {}
    return SseEvent(name=name or "message", data=data)


def parse_sse(body: str) -> list[SseEvent]:
    """Parse a complete `text/event-stream` body, skipping keep-alive comments."""
    events: list[SseEvent] = []
    block: list[str] = []
    for line in [*body.replace("\r\n", "\n").split("\n"), ""]:
        if line:
            block.append(line)
            continue
        event: SseEvent | None = _parse_block(block)
        if event is not None:
            events.append(event)
        block = []
    return events


class SseStream:
    """Reads events from a streaming response one at a time."""

    def __init__(self, response: httpx.Response) -> None:
        self.response: httpx.Response = response
        self._lines: AsyncIterator[str] = response.aiter_lines()

    async def next_event(self) -> SseEvent:
        """Return the next event.

        Raises:
            EOFError: If the stream ends first.
            TimeoutError: If no event arrives within `EVENT_TIMEOUT_SECONDS`.
        """
        block: list[str] = []
        async with asyncio.timeout(EVENT_TIMEOUT_SECONDS):
            async for line in self._lines:
                if line:
                    block.append(line)
                    continue
                event: SseEvent | None = _parse_block(block)
                block = []
                if event is not None:
                    return event
        raise EOFError("The event stream ended")

    async def next_event_name(self) -> str:
        return (await self.next_event()).name

    async def read_until(self, name: str) -> list[SseEvent]:
        """Read events up to and including the first one called `name`."""
        events: list[SseEvent] = []
        while not events or events[-1].name != name:
            events.append(await self.next_event())
        return events

    async def collect_rest(self) -> list[SseEvent]:
        """Read every remaining event until the stream ends."""
        events: list[SseEvent] = []
        while True:
            try:
                events.append(await self.next_event())
            except EOFError:
                return events


class _StreamedBody(httpx.AsyncByteStream):
    def __init__(
        self,
        chunks: asyncio.Queue[bytes | None],
        disconnected: asyncio.Event,
        app_task: asyncio.Task[None],
    ) -> None:
        self._chunks: asyncio.Queue[bytes | None] = chunks
        self._disconnected: asyncio.Event = disconnected
        self._app_task: asyncio.Task[None] = app_task

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while (chunk := await self._chunks.get()) is not None:
            yield chunk

    async def aclose(self) -> None:
        # Closing the response is the client going away; wait until the app has handled it, so
        # its clean-up has run and any error it raised surfaces in the test.
        self._disconnected.set()
        async with asyncio.timeout(APP_SHUTDOWN_TIMEOUT_SECONDS):
            await self._app_task


class StreamingASGITransport(httpx.AsyncBaseTransport):
    """An httpx transport that streams an in-process ASGI app's response as it is produced.

    The scope declares no ASGI `spec_version`, so Starlette (as with uvicorn's HTTP/1.1
    protocols, which declare 2.3) detects a disconnect by receiving `http.disconnect`.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app: ASGIApp = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body: bytes = await request.aread()
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(key.lower(), value) for key, value in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port),
            "client": ("127.0.0.1", 123),
            "root_path": "",
        }
        started: asyncio.Future[tuple[int, list[tuple[bytes, bytes]]]] = (
            asyncio.get_running_loop().create_future()
        )
        chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        disconnected: asyncio.Event = asyncio.Event()
        request_delivered: bool = False

        async def receive() -> Message:
            nonlocal request_delivered
            if not request_delivered:
                request_delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                started.set_result((message["status"], list(message.get("headers", []))))
            elif message["type"] == "http.response.body":
                if message.get("body"):
                    await chunks.put(message["body"])
                if not message.get("more_body", False):
                    await chunks.put(None)

        async def run_app() -> None:
            await self._app(scope, receive, send)

        app_task: asyncio.Task[None] = asyncio.create_task(run_app())
        first_of: set[asyncio.Future[Any]] = {started, app_task}
        await asyncio.wait(first_of, return_when=asyncio.FIRST_COMPLETED)
        if not started.done():
            app_task.result()
            raise RuntimeError("The app finished without starting a response")
        status, headers = started.result()
        return httpx.Response(
            status,
            headers=headers,
            stream=_StreamedBody(chunks, disconnected, app_task),
            request=request,
        )
