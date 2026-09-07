"""Errors shared by the maintained-reference lifecycle and its handlers."""

from __future__ import annotations

import re
from typing import Any

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def identifier(value: Any, field: str) -> str:
    """Validate an identifier shared by lifecycle and content commands."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or _SAFE_ID.fullmatch(value) is None
    ):
        raise PipelineReferenceInputError(f"{field} must be a safe identifier")
    return value


class PipelineReferenceError(RuntimeError):
    """The maintained-reference service could not complete an operation."""


class PipelineReferenceInputError(PipelineReferenceError, ValueError):
    """A maintained-reference request is invalid."""


class PipelineReferenceCoverageError(PipelineReferenceInputError):
    """A maintained-reference draft does not cover its declared scope."""

    def __init__(self, message: str, details: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.details = details


class PipelineReferenceConflict(PipelineReferenceError):
    """A maintained-reference request used an old draft revision."""

    def __init__(self, message: str, current: Any) -> None:
        super().__init__(message)
        self.current = current
