"""Processor-run reader isolated for lineage migration inventory."""

from __future__ import annotations

from pathlib import Path

from doko_operations.pipeline_data import PipelineDataContractError, ProcessorRunState

from dokodetector_backend.legacy_processor_run_codec import (
    _parse_processor_run_metadata_bytes,
    _parse_processor_run_state_bytes_compat,
)
from dokodetector_backend.pipeline_revision_store import (
    PipelineRevisionStore,
    StoredPipelineRevision,
)
from dokodetector_backend.pipeline_storage import PipelineRuntimeStorage, _parse_json_object
from dokodetector_backend.processor_run_codec import _parse_split_state_bytes
from dokodetector_backend.processor_run_store import ProcessorRunStore


class LegacyProcessorRunStore(ProcessorRunStore):
    """Read pre-lineage processor runs for the migration inventory only."""

    def __init__(
        self,
        storage: PipelineRuntimeStorage | Path | str,
        *,
        revision_store: PipelineRevisionStore,
    ) -> None:
        super().__init__(storage)
        self.legacy_revision_store = revision_store

    def _parse_legacy_state(self, raw: bytes, *, include_items: bool) -> ProcessorRunState:
        metadata = _parse_json_object(raw, "processor run state")
        if "item_ids" in metadata:
            state, item_ids = _parse_split_state_bytes(raw)
            if item_ids:
                raise ValueError("processor run is missing its items directory")
            return state
        return (
            _parse_processor_run_state_bytes_compat(raw)
            if include_items
            else _parse_processor_run_metadata_bytes(raw)
        )

    def _get_output_revision(
        self,
        revision_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None,
        validate_lineage: bool,
    ) -> StoredPipelineRevision | None:
        revision = self.legacy_revision_store.get(
            revision_id,
            revision_cache=revision_cache,
            validate_lineage=validate_lineage,
        )
        if revision is None and self.legacy_revision_store.has_revision(revision_id):
            raise PipelineDataContractError(
                f"run output revision is present but invalid: {revision_id}"
            )
        return revision
