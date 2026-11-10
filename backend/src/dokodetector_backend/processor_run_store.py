"""Durable processor-run request and state persistence."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from doko_operations.pipeline_data import (
    PROCESSOR_RUN_STATE_SCHEMA_VERSION,
    ImportProducer,
    ProcessorProducer,
    ProcessorRunRequest,
    ProcessorRunState,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    canonical_processor_run_request_bytes,
    canonical_processor_run_state_bytes,
)

from dokodetector_backend.filesystem import (
    atomic_replace_json,
    commit_staged_directory,
    contained_path,
    staging_directory,
)
from dokodetector_backend.pipeline_revision_store import StoredPipelineRevision
from dokodetector_backend.pipeline_storage import (
    PipelineConflict,
    PipelineNotFound,
    PipelineRuntimeStorage,
    PipelineStateError,
    PipelineStoreError,
    _canonical_timestamp,
    _parse_json_object,
    _process_lock,
    _safe_id,
    _storage,
    _strict_json_file,
    _timestamp_value,
)
from dokodetector_backend.processor_run_catalog import ProcessorRunCatalog
from dokodetector_backend.processor_run_codec import (
    _canonical_split_state_bytes,
    _parse_split_state_bytes,
    read_item_file,
    write_item_file,
)
from dokodetector_backend.processor_run_models import ProcessorRunStatus, StoredProcessorRun
from dokodetector_backend.processor_run_reader import ProcessorRunReader
from dokodetector_backend.recording_catalog_index import RecordingCatalogIndex

LOGGER = logging.getLogger(__name__)


class ProcessorRunStore(ProcessorRunReader, ProcessorRunCatalog):
    """Create and atomically update processor run request and state resources."""

    def __init__(
        self,
        storage: PipelineRuntimeStorage | Path | str,
        *,
        lineage_writer: Any | None = None,
        catalog_index: RecordingCatalogIndex | None = None,
    ) -> None:
        self.storage = _storage(storage)
        self.root = self.storage.runs_root
        self.lineage_writer = lineage_writer
        self.catalog_index = catalog_index
        self._lock = RLock()

    def run_path(self, run_id: str) -> Path:
        return contained_path(self.root, _safe_id(run_id, "run_id"))

    def get(
        self,
        run_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        include_items: bool = True,
        validate_output_revisions: bool = True,
        validate_output_lineage: bool = True,
    ) -> StoredProcessorRun | None:
        try:
            path = self.run_path(run_id)
        except (TypeError, ValueError):
            return None
        try:
            return self._read_path(
                path,
                revision_cache=revision_cache,
                include_items=include_items,
                validate_output_revisions=validate_output_revisions,
                validate_output_lineage=validate_output_lineage,
            )
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if path.exists() or path.is_symlink():
                self._log_invalid(path, error)
            return None

    def require(
        self,
        run_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        include_items: bool = True,
        validate_output_revisions: bool = True,
        validate_output_lineage: bool = True,
    ) -> StoredProcessorRun:
        run = self.get(
            run_id,
            revision_cache=revision_cache,
            include_items=include_items,
            validate_output_revisions=validate_output_revisions,
            validate_output_lineage=validate_output_lineage,
        )
        if run is None:
            raise PipelineNotFound(f"The processor run was not found: {run_id}")
        return run

    def create(
        self,
        request: ProcessorRunRequest | Mapping[str, Any],
        *,
        created_at: datetime | str | None = None,
    ) -> tuple[StoredProcessorRun, bool]:
        parsed_request = (
            ProcessorRunRequest.from_mapping(request.to_mapping())
            if isinstance(request, ProcessorRunRequest)
            else ProcessorRunRequest.from_mapping(request)
        )
        request_bytes = canonical_processor_run_request_bytes(parsed_request)
        timestamp = _canonical_timestamp(created_at)
        state = ProcessorRunState.from_mapping(
            {
                "schema_version": PROCESSOR_RUN_STATE_SCHEMA_VERSION,
                "run_id": parsed_request.run_id,
                "status": "queued",
                "attempt": 1,
                "created_at": timestamp,
                "started_at": None,
                "completed_at": None,
                "updated_at": timestamp,
                "progress": {"completed": 0, "total": 0},
                "items": [],
                "terminal_failure": None,
                "output_revision_ids": [],
                "metrics": {},
            }
        )
        state_bytes = _canonical_split_state_bytes(state, ())
        destination = self.run_path(parsed_request.run_id)
        with _process_lock(self.root / f".{parsed_request.run_id}.lock", self._lock):
            self._recover_run_catalog_intent_locked(parsed_request.run_id)
            if destination.exists() or destination.is_symlink():
                existing = self._existing_or_error(destination)
                if canonical_processor_run_request_bytes(existing.request) == request_bytes:
                    self._publish_run_status(existing.request, existing.state)
                    if self.lineage_writer is not None:
                        self.lineage_writer.accept_processor(existing.request, existing.state)
                    return existing, False
                raise PipelineConflict(
                    "The run ID is already stored with different request content."
                )
            try:
                intent = self._prepare_run_catalog_intent(
                    parsed_request,
                    state,
                    old_state_digest=None,
                    target_state_bytes=state_bytes,
                )
                with staging_directory(self.root, prefix=f".{parsed_request.run_id}-") as staging:
                    (staging / "items").mkdir()
                    atomic_replace_json(
                        staging / "request.json",
                        request_bytes,
                        validate=lambda raw: _strict_json_file(
                            raw, request_bytes, "processor run request"
                        ),
                    )
                    atomic_replace_json(
                        staging / "state.json",
                        state_bytes,
                        validate=lambda raw: self._validate_state_bytes(raw, parsed_request.run_id),
                    )
                    commit_staged_directory(
                        staging,
                        destination,
                        validate=lambda path: self._read_path(path, require_canonical_name=False),
                    )
            except FileExistsError as error:
                self._recover_run_catalog_intent_locked(parsed_request.run_id)
                existing = self._existing_or_error(destination)
                if canonical_processor_run_request_bytes(existing.request) == request_bytes:
                    return existing, False
                raise PipelineConflict(
                    "The run ID is already stored with different request content."
                ) from error
            except (OSError, ValueError) as error:
                raise PipelineStoreError("The processor run could not be created.") from error
            stored = self.get(parsed_request.run_id)
            if stored is None:
                raise PipelineStoreError("The created processor run failed validation.")
            if intent:
                self._finalize_run_catalog_intent(parsed_request.run_id, state_bytes)
            else:
                self._publish_run_status(stored.request, stored.state)
            if self.lineage_writer is not None:
                self.lineage_writer.accept_processor(stored.request, stored.state)
            return stored, True

    def update_state(
        self,
        run_id: str,
        state: ProcessorRunState | Mapping[str, Any],
    ) -> StoredProcessorRun:
        try:
            parsed_state = (
                ProcessorRunState.from_mapping(state.to_mapping())
                if isinstance(state, ProcessorRunState)
                else ProcessorRunState.from_mapping(state)
            )
        except (TypeError, ValueError) as error:
            raise PipelineStateError("processor run state is invalid") from error
        if parsed_state.run_id != run_id:
            raise PipelineStateError("run state ID differs from the requested run")
        with _process_lock(self.root / f".{_safe_id(run_id, 'run_id')}.lock", self._lock):
            self._recover_run_catalog_intent_locked(run_id)
            current = self.require(run_id)
            self._validate_transition(current.state, parsed_state)
            self._validate_output_revisions(current.request, parsed_state)
            self._validate_item_replacement(current.state, parsed_state)
            if parsed_state.created_at != current.state.created_at:
                raise PipelineStateError("run created_at is immutable")
            if _timestamp_value(parsed_state.updated_at) < _timestamp_value(
                current.state.updated_at
            ):
                raise PipelineStateError("run updated_at cannot go backwards")
            old_state_bytes = self.state_path(run_id).read_bytes()
            split_layout = self.items_path(run_id).is_dir()
            if split_layout:
                current_items = {item.item_id: item for item in current.state.items}
                payload = _canonical_split_state_bytes(
                    parsed_state, tuple(item.item_id for item in parsed_state.items)
                )
            else:
                current_items = {}
                payload = canonical_processor_run_state_bytes(parsed_state)
            intent = False
            if current.state.status != parsed_state.status:
                intent = self._prepare_run_catalog_intent(
                    current.request,
                    parsed_state,
                    old_state_digest=hashlib.sha256(old_state_bytes).hexdigest(),
                    target_state_bytes=payload,
                )
            if split_layout:
                self._write_changed_items(run_id, current_items, parsed_state.items)
                atomic_replace_json(
                    self.state_path(run_id),
                    payload,
                    validate=lambda raw: self._validate_state_bytes(raw, run_id),
                )
            else:
                atomic_replace_json(
                    self.state_path(run_id),
                    payload,
                    validate=lambda raw: self._validate_state_bytes(raw, run_id),
                )
            if intent:
                self._finalize_run_catalog_intent(run_id, payload)
            else:
                self._publish_run_status(current.request, parsed_state)
            stored = StoredProcessorRun(request=current.request, state=parsed_state)
            if self.lineage_writer is not None:
                if parsed_state.status in {"complete", "partial", "failed"}:
                    self.lineage_writer.update_processor(current.request, parsed_state)
                elif (
                    parsed_state.status == "running"
                    and parsed_state.attempt > current.state.attempt
                ):
                    self.lineage_writer.accept_processor(current.request, parsed_state)
            return stored

    def start(self, run_id: str, *, started_at: datetime | str | None = None) -> StoredProcessorRun:
        current = self.require(run_id)
        if current.state.status != "queued":
            raise PipelineStateError("only queued runs can start")
        timestamp = _canonical_timestamp(started_at)
        return self.update_state(
            run_id,
            replace(
                current.state,
                status="running",
                started_at=timestamp,
                updated_at=timestamp,
            ),
        )

    def complete(
        self,
        run_id: str,
        output_revision_ids: tuple[str, ...] | list[str],
        *,
        progress: RunProgress | None = None,
        items: tuple[RunItemOutcome, ...] | None = None,
        metrics: Mapping[str, Any] | None = None,
        completed_at: datetime | str | None = None,
    ) -> StoredProcessorRun:
        current = self.require(run_id)
        if current.state.status != "running":
            raise PipelineStateError("only running runs can complete")
        timestamp = _canonical_timestamp(completed_at)
        complete_progress = progress or RunProgress(
            completed=current.state.progress.total,
            total=current.state.progress.total,
        )
        return self.update_state(
            run_id,
            replace(
                current.state,
                status="complete",
                completed_at=timestamp,
                updated_at=timestamp,
                progress=complete_progress,
                items=current.state.items if items is None else items,
                output_revision_ids=tuple(output_revision_ids),
                metrics=current.state.metrics if metrics is None else dict(metrics),
            ),
        )

    def partial(
        self,
        run_id: str,
        *,
        progress: RunProgress,
        items: tuple[RunItemOutcome, ...],
        output_revision_ids: tuple[str, ...] | list[str] = (),
        metrics: Mapping[str, Any] | None = None,
        completed_at: datetime | str | None = None,
    ) -> StoredProcessorRun:
        current = self.require(run_id)
        if current.state.status != "running":
            raise PipelineStateError("only running runs can become partial")
        timestamp = _canonical_timestamp(completed_at)
        return self.update_state(
            run_id,
            replace(
                current.state,
                status="partial",
                completed_at=timestamp,
                updated_at=timestamp,
                progress=progress,
                items=items,
                output_revision_ids=tuple(output_revision_ids),
                metrics=current.state.metrics if metrics is None else dict(metrics),
            ),
        )

    def fail(
        self,
        run_id: str,
        failure: RunFailure | Mapping[str, Any],
        *,
        metrics: Mapping[str, Any] | None = None,
        completed_at: datetime | str | None = None,
    ) -> StoredProcessorRun:
        current = self.require(run_id)
        if current.state.status != "running":
            raise PipelineStateError("only running runs can fail")
        parsed_failure = (
            failure if isinstance(failure, RunFailure) else RunFailure.from_mapping(failure)
        )
        timestamp = _canonical_timestamp(completed_at)
        return self.update_state(
            run_id,
            replace(
                current.state,
                status="failed",
                completed_at=timestamp,
                updated_at=timestamp,
                terminal_failure=parsed_failure,
                metrics=current.state.metrics if metrics is None else dict(metrics),
            ),
        )

    def retry(self, run_id: str, *, started_at: datetime | str | None = None) -> StoredProcessorRun:
        current = self.require(run_id)
        if current.state.status not in {"partial", "failed"}:
            raise PipelineStateError("only partial or failed runs can be retried")
        timestamp = _canonical_timestamp(started_at)
        return self.update_state(
            run_id,
            replace(
                current.state,
                status="running",
                attempt=current.state.attempt + 1,
                started_at=timestamp,
                completed_at=None,
                updated_at=timestamp,
                terminal_failure=None,
                output_revision_ids=(),
                metrics={},
            ),
        )

    def update_progress(
        self,
        run_id: str,
        *,
        progress: RunProgress,
        items: tuple[RunItemOutcome, ...] | None = None,
        metrics: Mapping[str, Any] | None = None,
        updated_at: datetime | str | None = None,
    ) -> StoredProcessorRun:
        current = self.require(run_id)
        if current.state.status != "running":
            raise PipelineStateError("only running runs can receive progress")
        timestamp = _canonical_timestamp(updated_at)
        return self.update_state(
            run_id,
            replace(
                current.state,
                progress=progress,
                items=current.state.items if items is None else items,
                metrics=current.state.metrics if metrics is None else dict(metrics),
                updated_at=timestamp,
            ),
        )

    def record_item_progress(
        self,
        run_id: str,
        *,
        progress: RunProgress,
        item: RunItemOutcome,
        updated_at: datetime | str | None = None,
    ) -> None:
        """Persist one completed item without rewriting the other item outcomes."""

        try:
            parsed_item = RunItemOutcome.from_mapping(item.to_mapping())
        except (TypeError, ValueError) as error:
            raise PipelineStateError("processor run item is invalid") from error
        timestamp = _canonical_timestamp(updated_at)
        safe_run_id = _safe_id(run_id, "run_id")
        with _process_lock(self.root / f".{safe_run_id}.lock", self._lock):
            self._recover_run_catalog_intent_locked(run_id)
            path = self.run_path(run_id)
            if not self.items_path(run_id).is_dir():
                current = self.require(run_id)
                if current.state.status != "running":
                    raise PipelineStateError("only running runs can receive progress")
                next_state = replace(
                    current.state,
                    progress=progress,
                    items=(*current.state.items, parsed_item),
                    updated_at=timestamp,
                )
                self._validate_item_replacement(current.state, next_state)
                atomic_replace_json(
                    self.state_path(run_id),
                    canonical_processor_run_state_bytes(next_state),
                    validate=lambda raw: self._validate_state_bytes(raw, run_id),
                )
                self._publish_run_status(current.request, next_state)
                return

            request, current_state, item_ids = self._read_split_metadata(path)
            if current_state.status != "running":
                raise PipelineStateError("only running runs can receive progress")
            if _timestamp_value(timestamp) < _timestamp_value(current_state.updated_at):
                raise PipelineStateError("run updated_at cannot go backwards")
            existing = None
            if parsed_item.item_id in item_ids:
                existing = read_item_file(
                    self.items_path(run_id) / f"{parsed_item.item_id}.json",
                    parsed_item.item_id,
                )
                if existing.status == "succeeded" and existing != parsed_item:
                    raise PipelineStateError("successful item outcomes cannot be replaced")
            if existing != parsed_item:
                write_item_file(self.root, run_id, parsed_item)
            next_item_ids = (
                item_ids if parsed_item.item_id in item_ids else (*item_ids, parsed_item.item_id)
            )
            next_state = replace(current_state, progress=progress, updated_at=timestamp)
            atomic_replace_json(
                self.state_path(run_id),
                _canonical_split_state_bytes(next_state, next_item_ids),
                validate=lambda raw: self._validate_state_bytes(raw, run_id),
            )
            self._publish_run_status(request, next_state)

    def fail_non_terminal(
        self,
        *,
        failure: RunFailure | Mapping[str, Any],
        updated_at: datetime | str | None = None,
    ) -> int:
        """Fail queued or running runs left behind by a stopped backend."""

        failed = 0
        # Recovery only needs request/state metadata. Loading every terminal run and validating
        # its output revisions makes startup scale with the size of retained processor results.
        for status in self.list_statuses():
            try:
                if status.status == "queued":
                    self.start(status.run_id, started_at=updated_at)
                if status.status not in {"queued", "running"}:
                    continue
                current = self.get(status.run_id)
                if current is None or current.state.status != "running":
                    continue
                self.fail(status.run_id, failure, completed_at=updated_at)
                failed += 1
            except (OSError, TypeError, UnicodeError, ValueError, PipelineStoreError) as error:
                self._log_invalid(self.run_path(status.run_id), error)
        return failed

    def recover_catalog_publications(self) -> int:
        """Reconcile only exact processor runs named by pending catalog intents."""
        if self.catalog_index is None:
            return 0
        intents = self.catalog_index.pending_processor_runs()
        for intent in intents:
            self._recover_run_catalog_intent(intent["run_id"])
        return len(intents)

    def _recover_run_catalog_intent(self, run_id: str) -> None:
        with _process_lock(self.root / f".{_safe_id(run_id, 'run_id')}.lock", self._lock):
            self._recover_run_catalog_intent_locked(run_id)

    def _recover_run_catalog_intent_locked(self, run_id: str) -> None:
        if self.catalog_index is None:
            return
        source_key = f"processor-run:{run_id}"
        pending = self.catalog_index.pending_processor_publication(source_key)
        if pending is None:
            return
        path = self.run_path(run_id)
        expected_source = (
            pending
            if pending["schema_version"] == "recording-catalog-run-intent/v1"
            else pending["source"]["value"]
        )
        if path.exists() and not path.is_symlink() and (path / "state.json").is_file():
            status = self._read_status(path)
            state_digest = hashlib.sha256((path / "state.json").read_bytes()).hexdigest()
            if (
                status.run_id != run_id
                or status.recording_id != expected_source["recording_id"]
                or status.processor_type != expected_source["processor_type"]
            ):
                raise PipelineStoreError("pending processor-run identity does not match its source")
        else:
            status = None
            state_digest = None
        if pending["schema_version"] == "recording-catalog-outbox/v1":
            if status is None or pending["source"]["value"] != self._status_catalog_value(status):
                raise PipelineStoreError(
                    "pending processor-run publication does not match its source state"
                )
            self.catalog_index.recover_processor_run_publication(
                source_key,
                source_value=self._status_catalog_value(status),
            )
        elif state_digest == pending["target_state_digest"]:
            if status is None or status.status != pending["status"]:
                raise PipelineStoreError("pending processor-run target status does not match")
            self.catalog_index.finalize_processor_run(
                source_key, observed_state_digest=state_digest
            )
        elif state_digest == pending["old_state_digest"]:
            self.catalog_index.cancel_processor_run(source_key, observed_state_digest=state_digest)
        else:
            raise PipelineStoreError("pending processor-run state matches neither commit digest")

    def _prepare_run_catalog_intent(
        self,
        request: ProcessorRunRequest,
        state: ProcessorRunState,
        *,
        old_state_digest: str | None,
        target_state_bytes: bytes,
    ) -> bool:
        if self.catalog_index is None:
            return False
        self.catalog_index.prepare_processor_run(
            run_id=request.run_id,
            recording_id=request.source.recording_id,
            processor_type=request.processor_type,
            status=state.status,
            old_state_digest=old_state_digest,
            target_state_digest=hashlib.sha256(target_state_bytes).hexdigest(),
        )
        return True

    def _finalize_run_catalog_intent(self, run_id: str, state_bytes: bytes) -> None:
        if self.catalog_index is not None:
            self.catalog_index.finalize_processor_run(
                f"processor-run:{run_id}",
                observed_state_digest=hashlib.sha256(state_bytes).hexdigest(),
            )

    def _publish_run_status(
        self,
        request: ProcessorRunRequest,
        state: ProcessorRunState,
    ) -> None:
        if self.catalog_index is None:
            return
        self.catalog_index.publish_latest(
            source_key=f"processor-run:{request.run_id}",
            recording_id=request.source.recording_id,
            source_value=self._run_catalog_value(request, state),
            metadata_delta={},
            counter_delta={f"processor_run:{request.processor_type}:{state.status}": 1},
        )

    @staticmethod
    def _run_catalog_value(
        request: ProcessorRunRequest,
        state: ProcessorRunState,
    ) -> dict[str, str]:
        return {
            "run_id": request.run_id,
            "recording_id": request.source.recording_id,
            "processor_type": request.processor_type,
            "status": state.status,
        }

    @staticmethod
    def _status_catalog_value(status: ProcessorRunStatus) -> dict[str, str]:
        return {
            "run_id": status.run_id,
            "recording_id": status.recording_id,
            "processor_type": status.processor_type,
            "status": status.status,
        }

    def state_path(self, run_id: str) -> Path:
        return self.run_path(run_id) / "state.json"

    def items_path(self, run_id: str) -> Path:
        return self.run_path(run_id) / "items"

    def request_path(self, run_id: str) -> Path:
        return self.run_path(run_id) / "request.json"

    def _existing_or_error(self, path: Path) -> StoredProcessorRun:
        try:
            return self._read_path(path)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            raise PipelineStoreError("The existing processor run is invalid.") from error

    @staticmethod
    def _validate_state_bytes(raw: bytes, run_id: str) -> None:
        metadata = _parse_json_object(raw, "processor run state")
        if "item_ids" not in metadata:
            raise ValueError("processor run state uses the legacy single-file format")
        state, _ = _parse_split_state_bytes(raw)
        if state.run_id != run_id:
            raise PipelineStateError("run state ID differs from its directory")

    def _write_changed_items(
        self,
        run_id: str,
        current_items: Mapping[str, RunItemOutcome],
        updated_items: tuple[RunItemOutcome, ...],
    ) -> None:
        for item in updated_items:
            if current_items.get(item.item_id) != item:
                write_item_file(self.root, run_id, item)

    def _validate_transition(self, current: ProcessorRunState, updated: ProcessorRunState) -> None:
        if current.status == updated.status:
            if current.status in {"complete", "partial", "failed"} and current != updated:
                raise PipelineStateError("terminal run state cannot be changed")
            if updated.attempt != current.attempt:
                raise PipelineStateError("run attempt cannot change without an explicit retry")
            return
        allowed = {
            "queued": {"running"},
            "running": {"complete", "partial", "failed"},
            "partial": {"running"},
            "failed": {"running"},
            "complete": set(),
        }
        if updated.status not in allowed[current.status]:
            raise PipelineStateError(
                f"run state cannot change from {current.status} to {updated.status}"
            )
        if current.status in {"queued", "running"} and updated.attempt != current.attempt:
            raise PipelineStateError("run attempt cannot change during normal execution")
        if current.status in {"partial", "failed"} and updated.attempt != current.attempt + 1:
            raise PipelineStateError("retry must increment the run attempt by one")

    def _validate_item_replacement(
        self, current: ProcessorRunState, updated: ProcessorRunState
    ) -> None:
        if current.status not in {"running", "partial", "failed"} or updated.status != "running":
            return
        old = {item.item_id: item for item in current.items}
        new = {item.item_id: item for item in updated.items}
        missing = set(old) - set(new)
        if missing:
            raise PipelineStateError("retry and progress updates must retain prior item outcomes")
        for item_id, old_item in old.items():
            if old_item.status == "succeeded" and new[item_id] != old_item:
                raise PipelineStateError("successful item outcomes cannot be replaced")

    def _validate_output_revisions(
        self,
        request: ProcessorRunRequest,
        state: ProcessorRunState,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        validate_lineage: bool = True,
    ) -> None:
        if not state.output_revision_ids:
            return
        for revision_id in state.output_revision_ids:
            revision = self._get_output_revision(
                revision_id,
                revision_cache=revision_cache,
                validate_lineage=validate_lineage,
            )
            if revision is None:
                raise PipelineStateError(f"run output revision is not published: {revision_id}")
            manifest = revision.manifest
            producer = manifest.producer
            if not isinstance(producer, (ProcessorProducer, ImportProducer)):
                raise PipelineStateError("run output revision has invalid processor lineage")
            if producer.run_id != request.run_id:
                raise PipelineStateError("run output revision has different processor lineage")
            expected_content_type = {
                "event-detection": "events",
                "visible-card-detection": "visible_cards",
                "visual-card-identity": "visual_identities",
                "observation-assembly": "table_observations",
                "visible-card-scene-proposal": "card_scene_proposals",
            }.get(request.processor_type)
            if expected_content_type is not None and manifest.content_type != expected_content_type:
                raise PipelineStateError("run output revision has a different content type")
            if manifest.source != request.source:
                raise PipelineStateError("run output revision has a different source")
            expected_inputs = request.input_revision_ids
            if manifest.input_revision_ids != expected_inputs:
                raise PipelineStateError("run output revision has different input lineage")

    def _get_output_revision(
        self,
        revision_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None,
        validate_lineage: bool,
    ) -> StoredPipelineRevision | None:
        del revision_cache, validate_lineage
        if self.lineage_writer is None:
            raise PipelineStateError("processor output validation needs the lineage writer")
        try:
            return self.lineage_writer.require_revision(revision_id)
        except PipelineNotFound:
            return None

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        if str(error) == "processor run state uses the legacy single-file format":
            LOGGER.debug("processor_run_catalog_skipped path=%s reason=%s", path, error)
            return
        if str(error).startswith("run output revision is present but invalid:"):
            LOGGER.debug("processor_run_catalog_skipped path=%s reason=%s", path, error)
            return
        LOGGER.warning("processor_run_catalog_skipped path=%s reason=%s", path, error)
