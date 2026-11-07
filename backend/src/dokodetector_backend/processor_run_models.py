"""Validated processor-run persistence records."""

from __future__ import annotations

from dataclasses import dataclass

from doko_operations.pipeline_data import ProcessorRunRequest, ProcessorRunState


@dataclass(frozen=True, slots=True)
class StoredProcessorRun:
    """The validated immutable request and mutable state for one processor run."""

    request: ProcessorRunRequest
    state: ProcessorRunState

    @property
    def run_id(self) -> str:
        return self.request.run_id


@dataclass(frozen=True, slots=True)
class ProcessorRunStatus:
    """The small mutable state projection needed by recording catalogs."""

    run_id: str
    recording_id: str
    processor_type: str
    status: str
