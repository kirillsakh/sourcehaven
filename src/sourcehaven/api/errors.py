from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """An error the API reports as a top-level JSON body `{"code": ..., "message": ...}`.

    Args:
        status_code: HTTP status of the response.
        code: Stable machine-readable error code that clients branch on.
        message: Optional human-readable detail; it must never echo request content.
        details: Further top-level fields, such as the id of a conflicting resource.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str | None = None,
        *,
        details: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code: int = status_code
        self.code: str = code
        self.message: str | None = message
        self.details: dict[str, str] = dict(details or {})


def _body(code: str, message: str | None) -> dict[str, str]:
    return {"code": code} if message is None else {"code": code, "message": message}


async def _handle_api_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ApiError)
    body: dict[str, str] = {**error.details, **_body(error.code, error.message)}
    return JSONResponse(body, status_code=error.status_code)


async def _handle_validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    # Only the location and the validator's message are reported; `input` would echo the request.
    problems: list[str] = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    ]
    return JSONResponse(_body("invalid_request", "; ".join(problems)), status_code=422)


def install_error_handlers(app: FastAPI) -> None:
    """Make every API error use the top-level `{"code": ...}` body."""
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
