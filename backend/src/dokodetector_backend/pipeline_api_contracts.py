"""Shared helpers for pipeline HTTP contract translation."""

from __future__ import annotations

import re
from typing import Any

from dokodetector_backend.errors import ContractError

RECORDING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def validate_recording_id(recording_id: str) -> None:
    """Validate the recording identifier shared by all pipeline routes."""

    if RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ContractError("invalid_recording_id", "The recording ID is invalid.")


def run_response(run: Any) -> dict[str, Any]:
    """Translate a stored processor run to its public response shape."""

    request = run.request.to_mapping()
    state = run.state.to_mapping()
    return {
        "run_id": run.run_id,
        "recording_id": run.request.source.recording_id,
        "processor_type": run.request.processor_type,
        "status": run.state.status,
        "attempt": run.state.attempt,
        "request": request,
        "state": state,
    }


__all__ = ["run_response", "validate_recording_id"]
