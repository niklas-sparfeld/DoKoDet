"""Structured local logging configuration for the backend process."""

from __future__ import annotations

import logging
import os
import re
import shlex
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

BACKEND_LOGGER_NAME = "dokodetector_backend"
LOG_LEVEL_ENV = "DOKO_LOG_LEVEL"
REQUEST_ID_HEADER = "x-dokodetector-request-id"

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_THIRD_PARTY_LOGGERS = {
    "alembic",
    "fastapi",
    "httpx",
    "multipart",
    "sqlalchemy",
    "uvicorn",
    "zeroconf",
}


class LoggingConfigurationError(ValueError):
    """Raised when the backend logging configuration is invalid."""


class BackendLogFormatter(logging.Formatter):
    """Render one structured backend event on one UTC line."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = (
            datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        event_name = getattr(record, "event_name", None)
        fields = getattr(record, "event_fields", None)
        if event_name is None:
            event_text = _single_line(record.getMessage())
        else:
            event_text = event_name
            if isinstance(fields, Mapping):
                event_text = " ".join(
                    [event_text]
                    + [f"{name}={_format_field(value)}" for name, value in sorted(fields.items())]
                )

        line = f"{timestamp} {record.levelname} {record.name} {event_text}"
        if record.exc_info:
            line += f" exception={_format_exception(record)}"
        if record.stack_info:
            line += f" stack={_quote(record.stack_info)}"
        return _single_line(line)


def parse_log_level(value: str | None = None) -> int:
    """Parse one standard log level, using ``DOKO_LOG_LEVEL`` when omitted."""

    configured = os.environ.get(LOG_LEVEL_ENV, "INFO") if value is None else value
    if not isinstance(configured, str):
        raise LoggingConfigurationError(_invalid_level_message(configured))
    normalized = configured.strip().upper()
    try:
        return _LEVELS[normalized]
    except KeyError as error:
        raise LoggingConfigurationError(_invalid_level_message(configured)) from error


def configure_logging(level: str | None = None) -> int:
    """Configure backend levels without replacing handlers owned by another process."""

    parsed_level = parse_log_level(level)
    root_logger = logging.getLogger()
    root_logger.setLevel(parsed_level)

    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(BackendLogFormatter())
        root_logger.addHandler(handler)

    backend_logger = logging.getLogger(BACKEND_LOGGER_NAME)
    backend_logger.setLevel(parsed_level)
    for logger_name in _THIRD_PARTY_LOGGERS:
        logger = logging.getLogger(logger_name)
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.WARNING)

    access_logger = logging.getLogger("uvicorn.access")
    if access_logger.level == logging.NOTSET:
        access_logger.setLevel(logging.INFO)
    return parsed_level


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    """Write one validated event with bounded structured fields."""

    if not _EVENT_NAME.fullmatch(event):
        raise ValueError("Log event names must use lower-case underscore-separated words.")
    invalid_fields = [name for name in fields if not _FIELD_NAME.fullmatch(name)]
    if invalid_fields:
        raise ValueError(f"Log field names are invalid: {', '.join(sorted(invalid_fields))}.")
    logger.log(
        level,
        event,
        exc_info=exc_info,
        extra={"event_name": event, "event_fields": fields},
        stacklevel=2,
    )


def new_request_id() -> str:
    """Create a compact request identifier for one HTTP request."""

    return uuid4().hex


def get_or_create_request_id(request: Any) -> str:
    """Return the request ID from request state or a safe client header."""

    state = getattr(request, "state", None)
    existing = getattr(state, "request_id", None)
    if isinstance(existing, str) and _REQUEST_ID.fullmatch(existing):
        return existing

    headers = getattr(request, "headers", {})
    request_id = None
    for header in (REQUEST_ID_HEADER, "x-request-id"):
        supplied = headers.get(header)
        if isinstance(supplied, str) and _REQUEST_ID.fullmatch(supplied):
            request_id = supplied
            break
    request_id = request_id or new_request_id()
    if state is not None:
        state.request_id = request_id
    return request_id


def _invalid_level_message(value: object) -> str:
    names = tuple(_LEVELS)
    allowed = ", ".join(names[:-1]) + f", or {names[-1]}"
    return f"{LOG_LEVEL_ENV} must be one of {allowed}; got {value!r}."


def _format_field(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, UUID):
        return str(value)
    return _quote(_single_line(str(value)))


def _quote(value: str) -> str:
    bounded = value if len(value) <= 512 else f"{value[:512]}…<truncated>"
    return shlex.quote(bounded)


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _format_exception(record: logging.LogRecord) -> str:
    formatter = logging.Formatter()
    return _quote(_single_line(formatter.formatException(record.exc_info)))


__all__ = [
    "BACKEND_LOGGER_NAME",
    "BackendLogFormatter",
    "LOG_LEVEL_ENV",
    "LoggingConfigurationError",
    "REQUEST_ID_HEADER",
    "configure_logging",
    "get_or_create_request_id",
    "log_event",
    "new_request_id",
    "parse_log_level",
]
