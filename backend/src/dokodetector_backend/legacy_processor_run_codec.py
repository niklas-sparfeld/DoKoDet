"""Legacy processor-run state parser used only by lineage migration inventory."""

from __future__ import annotations

from doko_operations.pipeline_data import (
    PROCESSOR_RUN_STATE_SCHEMA_VERSION,
    ProcessorRunState,
    canonical_json_bytes,
)

from dokodetector_backend.pipeline_storage import (
    PipelineDataContractError,
    _parse_json_object,
    _strict_json_file,
)

_LEGACY_PROCESSOR_RUN_STATE_SCHEMA_VERSION = "processor-run-state/v1"


def _parse_processor_run_state_bytes_compat(raw: bytes) -> ProcessorRunState:
    """Read current state and the older processor-run state form."""

    data = _parse_json_object(raw, "processor run state")
    raw_schema_version = data.get("schema_version")
    missing_metrics = "metrics" not in data
    legacy_schema = (
        raw_schema_version == _LEGACY_PROCESSOR_RUN_STATE_SCHEMA_VERSION and missing_metrics
    )
    if legacy_schema:
        data["schema_version"] = PROCESSOR_RUN_STATE_SCHEMA_VERSION
    if missing_metrics:
        data["metrics"] = {}
    state = ProcessorRunState.from_mapping(data)
    expected_mapping = state.to_mapping()
    if missing_metrics:
        expected_mapping.pop("metrics")
    if legacy_schema:
        expected_mapping["schema_version"] = _LEGACY_PROCESSOR_RUN_STATE_SCHEMA_VERSION
    expected = canonical_json_bytes(expected_mapping)
    _strict_json_file(raw, expected, "processor run state")
    return state


def _parse_processor_run_metadata_bytes(raw: bytes) -> ProcessorRunState:
    """Read legacy run metadata without constructing every stored item outcome."""

    data = _parse_json_object(raw, "processor run state")
    raw_schema_version = data.get("schema_version")
    missing_metrics = "metrics" not in data
    legacy_schema = (
        raw_schema_version == _LEGACY_PROCESSOR_RUN_STATE_SCHEMA_VERSION and missing_metrics
    )
    if missing_metrics:
        data["metrics"] = {}
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise PipelineDataContractError("processor run state items must be a list")
    state_data = dict(data)
    state_data["items"] = []
    if legacy_schema:
        state_data["schema_version"] = PROCESSOR_RUN_STATE_SCHEMA_VERSION
    state = ProcessorRunState.from_mapping(state_data)
    canonical_data = dict(data)
    if missing_metrics:
        canonical_data.pop("metrics")
    _strict_json_file(
        raw,
        canonical_json_bytes(canonical_data),
        "processor run state",
    )
    return state
