"""Stable errors for the HTTP boundary."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import ClientDisconnect


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
    async def handle_client_disconnect(_: Request, __: ClientDisconnect) -> Response:
        """Treat an aborted request body as an expected client-side event."""

        return Response(status_code=499)

    @app.exception_handler(ContractError)
    async def handle_contract_error(_: Request, error: ContractError) -> JSONResponse:
        return error_response(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            "invalid_request",
            "The request failed validation.",
            status_code=422,
            details=validation_details(error),
        )

    @app.exception_handler(ValidationError)
    async def handle_validation_error(_: Request, error: ValidationError) -> JSONResponse:
        return error_response(
            "invalid_request",
            "The request failed validation.",
            status_code=422,
            details=validation_details(error),
        )


__all__ = [
    "APIError",
    "APIErrorDetail",
    "APIErrorResponse",
    "ContractError",
    "error_response",
    "register_error_handlers",
    "validation_details",
]
