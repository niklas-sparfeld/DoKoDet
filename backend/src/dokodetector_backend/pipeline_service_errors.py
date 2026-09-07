"""Shared errors for pipeline service boundaries."""

from __future__ import annotations


class PipelineServiceError(RuntimeError):
    """A pipeline operation could not be completed."""


class PipelineInputError(PipelineServiceError, ValueError):
    """A pipeline request or source artifact is invalid."""


class PipelineProviderError(PipelineServiceError):
    """An event provider failed without exposing provider internals to the API."""


__all__ = ["PipelineInputError", "PipelineProviderError", "PipelineServiceError"]
