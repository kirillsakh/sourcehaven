from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Multipart framing (boundaries, part headers) around the file within the request body.
MULTIPART_ALLOWANCE_BYTES: int = 16 * 1024


class UploadSizeLimitMiddleware:
    """Cap the request body of one endpoint before FastAPI parses and spools it.

    FastAPI parses a multipart body (spooling it to disk) before dependencies such as session
    authentication or the route itself run, so the limit has to apply at the ASGI layer. A
    declared `Content-Length` over the limit is answered with 413 without reading anything; a
    body without one, or one that lies, is counted as it streams. Once the count passes the limit
    the app is shown a disconnect, so it stops reading, and whatever it answers is replaced by 413.

    Args:
        app: The wrapped application.
        method: The only HTTP method that is limited.
        path: The only path that is limited.
        max_body_bytes: Largest accepted request body, multipart framing included.
    """

    def __init__(self, app: ASGIApp, *, method: str, path: str, max_body_bytes: int) -> None:
        self._app: ASGIApp = app
        self._method: str = method
        self._path: str = path
        self._max_body_bytes: int = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != self._method
            or scope["path"] != self._path
        ):
            await self._app(scope, receive, send)
            return
        declared: str | None = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdecimal() and int(declared) > self._max_body_bytes:
            await self._reject(scope, receive, send)
            return

        received_bytes: int = 0
        exceeded: bool = False
        response_started: bool = False

        async def counting_receive() -> Message:
            nonlocal received_bytes, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message: Message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self._max_body_bytes:
                    # Raising here would be turned into a 400 by FastAPI's body parsing, so the
                    # app is told the client went away and its answer is replaced below.
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if exceeded and not response_started:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, counting_receive, tracking_send)
        except Exception:
            if not exceeded or response_started:
                raise
        if exceeded and not response_started:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response: JSONResponse = JSONResponse({"code": "too_large"}, status_code=413)
        await response(scope, receive, send)
