"""Stable errors for the HTTP boundary."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import ClientDisconnect

from dokodetector_backend.logging_config import get_or_create_request_id, log_event

LOGGER = logging.getLogger(__name__)


class APIErrorDetail(BaseModel):
    """One safe, field-level validation detail."""

    model_config = ConfigDict(extra="forbid")

    field: str
    message: str


class APIError(BaseModel):
    """The stable error body used by the API."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: list[APIErrorDetail] = Field(default_factory=list)


class APIErrorResponse(BaseModel):
    """The stable top-level API error response."""

    model_config = ConfigDict(extra="forbid")

    error: APIError


class ContractError(ValueError):
    """A safe contract error that can be returned to an API client."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: Sequence[APIErrorDetail] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = list(details)


def validation_details(error: ValidationError | RequestValidationError) -> list[APIErrorDetail]:
    """Convert Pydantic errors without exposing invalid input values."""

    details: list[APIErrorDetail] = []
    for item in error.errors():
        location = [str(part) for part in item["loc"] if part not in {"body", "query", "path"}]
        details.append(
            APIErrorDetail(
                field=".".join(location) or "$",
                message=str(item["msg"]),
            )
        )
    return details


def error_response(
    code: str,
    message: str,
    *,
    status_code: int,
    details: Sequence[APIErrorDetail] = (),
) -> JSONResponse:
    """Build a stable JSON error response."""

    body = APIErrorResponse(error=APIError(code=code, message=message, details=list(details)))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_error_handlers(app: FastAPI) -> None:
    """Register safe handlers for expected HTTP boundary errors."""

    @app.exception_handler(ClientDisconnect)
    async def handle_client_disconnect(request: Request, __: ClientDisconnect) -> Response:
        """Treat an aborted request body as an expected client-side event."""

        _log_rejection(
            request,
            code="client_disconnect",
            message="The client disconnected before the request completed.",
            status_code=499,
        )
        return Response(status_code=499)

    @app.exception_handler(ContractError)
    async def handle_contract_error(request: Request, error: ContractError) -> JSONResponse:
        _log_rejection(request, error)
        return error_response(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = validation_details(error)
        _log_rejection(
            request,
            code="invalid_request",
            message="The request failed validation.",
            status_code=422,
            details=details,
        )
        return error_response(
            "invalid_request",
            "The request failed validation.",
            status_code=422,
            details=details,
        )

    @app.exception_handler(ValidationError)
    async def handle_validation_error(request: Request, error: ValidationError) -> JSONResponse:
        details = validation_details(error)
        _log_rejection(
            request,
            code="invalid_request",
            message="The request failed validation.",
            status_code=422,
            details=details,
        )
        return error_response(
            "invalid_request",
            "The request failed validation.",
            status_code=422,
            details=details,
        )


def _log_rejection(
    request: Request,
    error: ContractError | None = None,
    *,
    code: str | None = None,
    message: str | None = None,
    status_code: int | None = None,
    details: Sequence[APIErrorDetail] = (),
) -> None:
    """Log the safe, actionable fields for a rejected HTTP request."""

    if error is not None:
        code = error.code
        message = error.message
        status_code = error.status_code
        details = error.details

    assert code is not None
    assert message is not None
    assert status_code is not None
    package_id = request.path_params.get("package_id", "-")
    upload_id = (
        request.headers.get("x-dokodetector-upload-id")
        or request.path_params.get("upload_id")
        or "-"
    )
    cause = error.__cause__ if error is not None else None
    detail_text = "; ".join(f"{item.field}: {item.message}" for item in details) or "-"
    level = logging.ERROR if status_code >= 500 else logging.WARNING
    event_name = "http_request_failed" if level >= logging.ERROR else "http_request_rejected"
    log_event(
        LOGGER,
        level,
        event_name,
        exc_info=_exception_info(cause) if level >= logging.ERROR else None,
        request_id=get_or_create_request_id(request),
        method=request.method,
        path=request.url.path,
        package_id=package_id,
        recording_id=request.path_params.get("recording_id", "-"),
        analysis_id=request.path_params.get("analysis_id", "-"),
        upload_id=upload_id,
        status_code=status_code,
        code=code,
        message=message,
        details=detail_text,
        cause=_safe_cause_text(cause),
    )


def _safe_cause_text(cause: BaseException | None) -> str:
    """Return a single-line cause without logging rejected input values."""

    if cause is None:
        return "-"
    if isinstance(cause, (ValidationError, RequestValidationError)):
        return f"{type(cause).__name__}: validation details are listed above"
    message = " ".join(str(cause).split())
    if len(message) > 512:
        message = f"{message[:512]}…<truncated>"
    return f"{type(cause).__name__}: {message or '<no message>'}"


def _exception_info(
    cause: BaseException | None,
) -> tuple[type[BaseException], BaseException, object] | None:
    """Return traceback information only for a backend operation failure."""

    if cause is None or cause.__traceback__ is None:
        return None
    return type(cause), cause, cause.__traceback__


__all__ = [
    "APIError",
    "APIErrorDetail",
    "APIErrorResponse",
    "ContractError",
    "error_response",
    "register_error_handlers",
    "validation_details",
]
