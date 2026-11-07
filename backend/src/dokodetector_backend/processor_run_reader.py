"""Strict processor-run resource reader."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from doko_operations.pipeline_data import (
    ProcessorRunRequest,
    ProcessorRunState,
    canonical_processor_run_request_bytes,
    parse_processor_run_request_bytes,
)

from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_storage import _strict_json_file
from dokodetector_backend.processor_run_codec import (
    _is_atomic_json_temp,
    _parse_split_state_bytes,
    read_item_file,
)
from dokodetector_backend.processor_run_models import StoredProcessorRun


class ProcessorRunReader:
    def _parse_legacy_state(self, raw: bytes, *, include_items: bool) -> ProcessorRunState:
        del raw, include_items
        raise ValueError("processor run state uses the legacy single-file format")

    def _parse_legacy_state(self, raw: bytes, *, include_items: bool) -> ProcessorRunState:
        del raw, include_items
        raise ValueError("processor run state uses the legacy single-file format")

    def _read_path(
        self,
        path: Path,
        *,
        require_canonical_name: bool = True,
        validate_output_revisions: bool = True,
        validate_output_lineage: bool = True,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        include_items: bool = True,
        parsed_request: ProcessorRunRequest | None = None,
        request_bytes: bytes | None = None,
    ) -> StoredProcessorRun:
        if path.is_symlink() or not path.is_dir():
            raise OSError("processor run directory is unavailable")
        # Catalog loads (`include_items=False`) must not walk `items/`. Visual-identity
        # runs store hundreds of item files; a recursive scan dominates pipeline workspace
        # latency. Validate only the top-level run layout, then load items by ID when asked.
        top_members = [member for member in path.iterdir() if not _is_atomic_json_temp(member)]
        if any(member.is_symlink() for member in top_members):
            raise ValueError("processor run members must not be symlinks")
        top_files = {member.name for member in top_members if member.is_file()}
        top_dirs = {member.name for member in top_members if member.is_dir()}
        legacy_layout = not top_dirs and top_files == {"request.json", "state.json"}
        split_layout = top_dirs == {"items"} and top_files == {"request.json", "state.json"}
        if not legacy_layout and not split_layout:
            raise ValueError("processor run has an unsupported file layout")
        if request_bytes is None:
            request_bytes = (path / "request.json").read_bytes()
        state_bytes = (path / "state.json").read_bytes()
        request = parsed_request or parse_processor_run_request_bytes(request_bytes)
        # Parsing the request has already validated every nested JSON value. Avoid
        # walking large crop-input arrays a second time just to verify canonical bytes.
        canonical_request_bytes = json.dumps(
            request.to_mapping(),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        _strict_json_file(
            request_bytes,
            canonical_request_bytes,
            "processor run request",
        )
        if legacy_layout:
            state = self._parse_legacy_state(state_bytes, include_items=include_items)
        else:
            metadata_state, item_ids = _parse_split_state_bytes(state_bytes)
            if include_items:
                items_dir = path / "items"
                item_members = [
                    member for member in items_dir.iterdir() if not _is_atomic_json_temp(member)
                ]
                if any(member.is_symlink() for member in item_members):
                    raise ValueError("processor run members must not be symlinks")
                if any(member.is_dir() for member in item_members):
                    raise ValueError("processor run has an unsupported file layout")
                item_files = {member.name for member in item_members if member.is_file()}
                if not all(name.endswith(".json") for name in item_files):
                    raise ValueError("processor run has an unsupported file layout")
                if not {f"{item_id}.json" for item_id in item_ids}.issubset(item_files):
                    raise ValueError("processor run is missing a referenced item file")
                items = tuple(
                    read_item_file(items_dir / f"{item_id}.json", item_id) for item_id in item_ids
                )
                state = replace(metadata_state, items=items)
            else:
                state = metadata_state
        if request.run_id != state.run_id:
            raise ValueError("processor run request and state IDs differ")
        if require_canonical_name and request.run_id != path.name:
            raise ValueError("run ID differs from its directory name")
        if validate_output_revisions:
            self._validate_output_revisions(
                request,
                state,
                revision_cache=revision_cache,
                validate_lineage=validate_output_lineage,
            )
        return StoredProcessorRun(request=request, state=state)

    def _read_split_metadata(
        self, path: Path
    ) -> tuple[ProcessorRunRequest, ProcessorRunState, tuple[str, ...]]:
        request_bytes = (path / "request.json").read_bytes()
        state_bytes = (path / "state.json").read_bytes()
        request = parse_processor_run_request_bytes(request_bytes)
        _strict_json_file(
            request_bytes,
            canonical_processor_run_request_bytes(request),
            "processor run request",
        )
        state, item_ids = _parse_split_state_bytes(state_bytes)
        if request.run_id != state.run_id or request.run_id != path.name:
            raise ValueError("processor run IDs differ")
        return request, state, item_ids
