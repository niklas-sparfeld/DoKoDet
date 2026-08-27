"""Stable runtime interface for table-evidence analyzers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, model_validator

from .table_observation import ContractModel, TableObservation


class AnalyzerFrame(ContractModel):
    """One read-only frame exposed to an analyzer."""

    part_name: str = Field(min_length=1, max_length=64)
    actual_offset_ms: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    jpeg_bytes: bytes | None = Field(default=None, min_length=1)
    local_reference: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_source(self) -> AnalyzerFrame:
        if (self.jpeg_bytes is None) == (self.local_reference is None):
            raise ValueError("an analyzer frame must contain exactly one read-only source.")
        return self


class AnalyzerEvidence(ContractModel):
    """Visual evidence supplied to one table-evidence analyzer invocation."""

    package_id: UUID
    event_time_ms: int = Field(ge=0)
    frames: list[AnalyzerFrame] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_frame_names(self) -> AnalyzerEvidence:
        names = [frame.part_name for frame in self.frames]
        if len(names) != len(set(names)):
            raise ValueError("analyzer frame part names must be unique.")
        return self


@runtime_checkable
class TableEvidenceAnalyzer(Protocol):
    """Runtime boundary for analyzers that produce canonical table observations."""

    name: str
    version: str

    def analyze(self, evidence: AnalyzerEvidence) -> TableObservation:
        """Return one validated table observation for the supplied evidence."""


__all__ = ["AnalyzerEvidence", "AnalyzerFrame", "TableEvidenceAnalyzer"]
