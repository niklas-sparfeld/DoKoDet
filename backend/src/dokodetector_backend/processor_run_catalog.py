"""Compact processor-run catalog reads."""

from __future__ import annotations

import logging
from collections.abc import Collection
from pathlib import Path

from doko_operations.pipeline_data import parse_processor_run_request_bytes

from dokodetector_backend.filesystem import enumerate_resource_directories
from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_storage import _parse_json_object, _safe_id
from dokodetector_backend.processor_run_codec import _parse_split_state_bytes
from dokodetector_backend.processor_run_models import ProcessorRunStatus, StoredProcessorRun

LOGGER = logging.getLogger(__name__)


class ProcessorRunCatalog:
    root: Path

    def list(self) -> tuple[StoredProcessorRun, ...]:
        enumeration = enumerate_resource_directories(self.root, validate=self._read_path)
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))
        runs: list[StoredProcessorRun] = []
        for path in enumeration.paths:
            try:
                runs.append(self._read_path(path))
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(sorted(runs, key=lambda item: item.run_id))

    def list_for_recording(
        self,
        recording_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        include_items: bool = True,
        validate_output_revisions: bool = True,
        include_items_for_processor_types: Collection[str] | None = None,
        processor_types: Collection[str] | None = None,
    ) -> tuple[StoredProcessorRun, ...]:
        """Return validated runs for one recording and optional processor types."""

        _safe_id(recording_id, "recording_id")
        enumeration = enumerate_resource_directories(self.root)
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        runs: list[StoredProcessorRun] = []
        # Run requests are canonical JSON and the recording identity must appear as
        # a literal recording_id value. Most requests belong to other recordings;
        # skip their expensive recursive contract validation unless this marker is
        # present. A false positive is harmless because the parsed request below is
        # still checked against the requested recording.
        recording_marker = f'"recording_id":"{recording_id}"'.encode("ascii")
        processor_markers = (
            None
            if processor_types is None
            else tuple(
                f'"processor_type":"{processor_type}"'.encode("ascii")
                for processor_type in processor_types
            )
        )
        for path in enumeration.paths:
            try:
                request_bytes = (path / "request.json").read_bytes()
                if recording_marker not in request_bytes:
                    continue
                if processor_markers is not None and not any(
                    marker in request_bytes for marker in processor_markers
                ):
                    continue
                request = parse_processor_run_request_bytes(request_bytes)
                if request.source.recording_id != recording_id:
                    continue
                runs.append(
                    self._read_path(
                        path,
                        revision_cache=revision_cache,
                        include_items=include_items
                        and (
                            include_items_for_processor_types is None
                            or request.processor_type in include_items_for_processor_types
                        ),
                        validate_output_revisions=validate_output_revisions,
                        parsed_request=request,
                        request_bytes=request_bytes,
                    )
                )
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(sorted(runs, key=lambda item: item.run_id))

    def list_statuses(self) -> tuple[ProcessorRunStatus, ...]:
        """Return run identity and state without validating output revisions."""

        enumeration = enumerate_resource_directories(self.root)
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        statuses: list[ProcessorRunStatus] = []
        for path in enumeration.paths:
            try:
                statuses.append(self._read_status(path))
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(sorted(statuses, key=lambda item: item.run_id))

    def _read_status(self, path: Path) -> ProcessorRunStatus:
        """Read only the fields needed for compact catalog status summaries."""

        if path.is_symlink() or not path.is_dir():
            raise OSError("processor run directory is unavailable")
        request_path = path / "request.json"
        state_path = path / "state.json"
        if (
            request_path.is_symlink()
            or state_path.is_symlink()
            or not request_path.is_file()
            or not state_path.is_file()
        ):
            raise ValueError("processor run is missing request.json or state.json")
        request = parse_processor_run_request_bytes(request_path.read_bytes())
        if request.run_id != path.name:
            raise ValueError("run ID differs from its directory name")
        state_bytes = state_path.read_bytes()
        metadata = _parse_json_object(state_bytes, "processor run state")
        if "item_ids" not in metadata:
            raise ValueError("processor run state uses the legacy single-file format")
        state, _ = _parse_split_state_bytes(state_bytes)
        if state.run_id != request.run_id:
            raise ValueError("processor run request and state IDs differ")
        return ProcessorRunStatus(
            run_id=request.run_id,
            recording_id=request.source.recording_id,
            processor_type=request.processor_type,
            status=state.status,
        )
