"""Errors shared by visual identity pipeline owners."""


class VisualIdentityPipelineError(RuntimeError):
    """The visual identity pipeline could not accept or execute a request."""


class VisualIdentityPipelineInputError(VisualIdentityPipelineError, ValueError):
    """The visual identity pipeline request is invalid."""
