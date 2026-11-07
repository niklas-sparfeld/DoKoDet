"""Canonical codecs for split processor-run metadata and item files."""

from __future__ import annotations

from pathlib import Path

from doko_operations.pipeline_data import (
    PipelineDataContractError,
    ProcessorRunState,
    RunItemOutcome,
    canonical_json_bytes,
)

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.pipeline_storage import (
    PipelineStateError,
    _parse_json_object,
    _safe_id,
    _strict_json_file,
)


def _canonical_split_state_bytes(
    state: ProcessorRunState, item_ids: tuple[str, ...] | list[str]
) -> bytes:
    """Encode run metadata while keeping item outcomes in separate files."""

    mapping = state.to_mapping()
    mapping.pop("items")
    mapping["item_ids"] = list(item_ids)
    return canonical_json_bytes(mapping)


def _parse_split_state_bytes(raw: bytes) -> tuple[ProcessorRunState, tuple[str, ...]]:
    data = _parse_json_object(raw, "processor run metadata")
    expected = {
        "schema_version",
        "run_id",
        "status",
        "attempt",
        "created_at",
        "started_at",
        "completed_at",
        "updated_at",
        "progress",
        "item_ids",
        "terminal_failure",
        "output_revision_ids",
        "metrics",
    }
    legacy_expected = expected - {"metrics"}
    missing_metrics = set(data) == legacy_expected
    if set(data) not in (expected, legacy_expected):
        raise PipelineDataContractError("processor run metadata has unexpected fields")
    raw_item_ids = data["item_ids"]
    if not isinstance(raw_item_ids, list):
        raise PipelineDataContractError("processor run metadata item_ids must be a list")
    item_ids = tuple(_safe_id(item_id, "item_id") for item_id in raw_item_ids)
    if len(set(item_ids)) != len(item_ids):
        raise PipelineDataContractError("processor run metadata item_ids must be unique")
    state_data = dict(data)
    state_data.pop("item_ids")
    state_data["items"] = []
    if missing_metrics:
        state_data["metrics"] = {}
    state = ProcessorRunState.from_mapping(state_data)
    expected_bytes = _canonical_split_state_bytes(state, item_ids)
    if missing_metrics:
        legacy_state = state.to_mapping()
        legacy_state.pop("items")
        legacy_state.pop("metrics")
        legacy_state["item_ids"] = list(item_ids)
        expected_bytes = canonical_json_bytes(legacy_state)
    _strict_json_file(raw, expected_bytes, "processor run metadata")
    return state, item_ids


def _is_atomic_json_temp(path: Path) -> bool:
    """Identify store-owned JSON replacement files without a second filesystem lookup."""

    return path.name.endswith(".tmp") and ".json." in path.name


def write_item_file(items_root: Path, run_id: str, item: RunItemOutcome) -> None:
    item_path = items_root / run_id / "items" / f"{_safe_id(item.item_id, 'item_id')}.json"
    payload = canonical_json_bytes(item.to_mapping())
    atomic_replace_json(
        item_path,
        payload,
        validate=lambda raw: validate_item_bytes(raw, item.item_id),
    )


def validate_item_bytes(raw: bytes, item_id: str) -> None:
    item = RunItemOutcome.from_mapping(_parse_json_object(raw, "processor run item"))
    if item.item_id != item_id:
        raise PipelineStateError("processor run item ID differs from its file name")
    _strict_json_file(raw, canonical_json_bytes(item.to_mapping()), "processor run item")


def read_item_file(path: Path, item_id: str) -> RunItemOutcome:
    raw = path.read_bytes()
    item = RunItemOutcome.from_mapping(_parse_json_object(raw, "processor run item"))
    if item.item_id != item_id:
        raise ValueError("processor run item ID differs from its file name")
    _strict_json_file(raw, canonical_json_bytes(item.to_mapping()), "processor run item")
    return item
