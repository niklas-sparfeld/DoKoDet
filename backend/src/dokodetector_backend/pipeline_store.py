"""Filesystem stores for recording-pipeline revisions, runs, and selections.

The stores keep no derived index.  A resource is visible only after its complete canonical
directory has been published, and every read validates the files before returning the resource.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    EventDataRevision,
    HumanProducer,
    ImportProducer,
    PipelineDataContractError,
    PipelineSelection,
    PipelineSelectionUpdate,
    ProcessorProducer,
    ProcessorRunRequest,
    ProcessorRunState,
    RecordingVideoSource,
    RunFailure,
    RunItemOutcome,
    RunProgress,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
    canonical_pipeline_selection_bytes,
    canonical_processor_run_request_bytes,
    canonical_processor_run_state_bytes,
    parse_data_revision_bytes,
    parse_event_data_bytes,
    parse_pipeline_selection_bytes,
    parse_processor_run_request_bytes,
    parse_processor_run_state_bytes,
    sha256_bytes,
    validate_event_revision_content,
)
from table_evidence_analyzer.pipeline_data import (
    PipelineDataError,
    TableObservationData,
    VisibleCardData,
    VisualIdentityData,
    canonical_table_observation_data_bytes,
    canonical_visible_card_data_bytes,
    canonical_visual_identity_data_bytes,
    parse_table_observation_data_bytes,
    parse_visible_card_data_bytes,
    parse_visual_identity_data_bytes,
)

from dokodetector_backend.filesystem import (
    atomic_replace_json,
    commit_staged_directory,
    contained_path,
    enumerate_resource_directories,
    staging_directory,
)

try:
    from fcntl import LOCK_EX, LOCK_UN, flock
except ImportError:  # pragma: no cover - the supported backend runs on macOS and Linux.
    LOCK_EX = LOCK_UN = 0

    def flock(_descriptor: int, _operation: int) -> None:
        return None


LOGGER = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_UTC_ZERO = timezone.utc


class PipelineStoreError(RuntimeError):
    """The canonical pipeline resource could not be read or written."""


class PipelineConflict(PipelineStoreError):
    """A resource ID or optimistic pointer is already used by different content."""


class PipelineNotFound(PipelineStoreError):
    """The requested pipeline resource does not exist."""


class PipelineStateError(PipelineStoreError, ValueError):
    """A run state transition or state invariant is invalid."""


class PipelineSelectionConflict(PipelineConflict):
    """A selection update used an old expected revision."""


@dataclass(frozen=True, slots=True)
class PipelineRuntimeStorage:
    """Canonical roots shared by the three pipeline stores."""

    runtime_root: Path

    def __init__(self, runtime_root: Path | str) -> None:
        object.__setattr__(self, "runtime_root", Path(runtime_root).expanduser().resolve())

    @property
    def pipeline_root(self) -> Path:
        return self.runtime_root / "pipeline"

    @property
    def revisions_root(self) -> Path:
        return self.pipeline_root / "revisions"

    @property
    def runs_root(self) -> Path:
        return self.pipeline_root / "runs"

    @property
    def selections_root(self) -> Path:
        return self.pipeline_root / "selections"


@dataclass(frozen=True, slots=True)
class StoredProcessorRun:
    """The validated immutable request and mutable state for one processor run."""

    request: ProcessorRunRequest
    state: ProcessorRunState

    @property
    def run_id(self) -> str:
        return self.request.run_id


@dataclass(frozen=True, slots=True)
class StoredPipelineRevision:
    """A validated manifest and content payload from the immutable revision store."""

    manifest: DataRevision
    content: EventData | VisibleCardData | VisualIdentityData | TableObservationData

    def to_mapping(self) -> dict[str, Any]:
        return {"manifest": self.manifest.to_mapping(), "content": self.content.to_mapping()}


def _storage(value: PipelineRuntimeStorage | Path | str) -> PipelineRuntimeStorage:
    return value if isinstance(value, PipelineRuntimeStorage) else PipelineRuntimeStorage(value)


def _safe_id(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or _SAFE_ID.fullmatch(value) is None
    ):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _safe_content_type(value: str) -> str:
    if value not in {"events", "visible_cards", "visual_identities", "table_observations"}:
        raise ValueError("content_type is unsupported")
    return value


def _canonical_timestamp(value: datetime | str | None) -> str:
    if value is None:
        parsed = datetime.now(_UTC_ZERO)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError as error:
            raise ValueError("timestamp must be ISO-8601") from error
    else:
        raise TypeError("timestamp must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp must use UTC")
    return parsed.astimezone(_UTC_ZERO).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp_value(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


@contextmanager
def _process_lock(path: Path, thread_lock: RLock) -> Iterator[None]:
    """Hold one in-process and one local-process lock for a resource."""

    with thread_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            flock(handle.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(handle.fileno(), LOCK_UN)


def _strict_json_file(raw: bytes, expected: bytes, context: str) -> None:
    if raw != expected:
        raise PipelineDataContractError(f"{context} is not canonical JSON")


class PipelineRevisionStore:
    """Publish and read immutable pipeline data revisions."""

    def __init__(self, storage: PipelineRuntimeStorage | Path | str) -> None:
        self.storage = _storage(storage)
        self.root = self.storage.revisions_root
        self._lock = RLock()

    def revision_path(self, revision_id: str) -> Path:
        return contained_path(self.root, _safe_id(revision_id, "revision_id"))

    def get(self, revision_id: str) -> StoredPipelineRevision | None:
        try:
            path = self.revision_path(revision_id)
        except (TypeError, ValueError):
            return None
        try:
            return self._read_path(path)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if path.exists() or path.is_symlink():
                self._log_invalid(path, error)
            return None

    def require(self, revision_id: str) -> StoredPipelineRevision:
        revision = self.get(revision_id)
        if revision is None:
            raise PipelineNotFound(f"The pipeline revision was not found: {revision_id}")
        return revision

    def list(self) -> tuple[StoredPipelineRevision, ...]:
        enumeration = enumerate_resource_directories(
            self.root,
            validate=self._read_path,
        )
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))
        revisions: list[StoredPipelineRevision] = []
        for path in enumeration.paths:
            try:
                revisions.append(self._read_path(path))
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(sorted(revisions, key=lambda item: item.manifest.revision_id))

    def publish(
        self,
        revision: EventDataRevision | DataRevision,
        content: (
            EventData | VisibleCardData | VisualIdentityData | TableObservationData | bytes | None
        ) = None,
    ) -> tuple[StoredPipelineRevision, bool]:
        """Publish one complete revision, or replay identical bytes."""

        manifest, pipeline_content = self._coerce_revision(revision, content)
        manifest_bytes = canonical_data_revision_bytes(manifest)
        content_bytes = self._canonical_content_bytes(pipeline_content)
        self._validate_payload(manifest, pipeline_content, manifest_bytes, content_bytes)
        self._validate_lineage(manifest)
        revision_id = manifest.revision_id
        destination = self.revision_path(revision_id)

        with _process_lock(self.root / f".{revision_id}.lock", self._lock):
            if destination.exists() or destination.is_symlink():
                existing = self._existing_or_error(destination)
                if self._revision_bytes(existing) == (manifest_bytes, content_bytes):
                    return existing, False
                raise PipelineConflict("The revision ID is already stored with different content.")
            try:
                with staging_directory(self.root, prefix=f".{revision_id}-") as staging:
                    # Write content first.  The manifest is the final file in the staged revision.
                    atomic_replace_json(
                        staging / "content.json",
                        content_bytes,
                        validate=lambda raw: self._validate_payload_bytes(
                            manifest, raw, manifest_bytes
                        ),
                    )
                    atomic_replace_json(
                        staging / "manifest.json",
                        manifest_bytes,
                        validate=lambda raw: _strict_json_file(
                            raw, manifest_bytes, "revision manifest"
                        ),
                    )
                    commit_staged_directory(
                        staging,
                        destination,
                        validate=lambda path: self._read_path(path, require_canonical_name=False),
                    )
            except FileExistsError as error:
                existing = self._existing_or_error(destination)
                if self._revision_bytes(existing) == (manifest_bytes, content_bytes):
                    return existing, False
                raise PipelineConflict(
                    "The revision ID is already stored with different content."
                ) from error
            except (OSError, ValueError) as error:
                raise PipelineStoreError("The pipeline revision could not be published.") from error
            stored = self.get(revision_id)
            if stored is None:
                raise PipelineStoreError("The published pipeline revision failed validation.")
            return stored, True

    def _coerce_revision(
        self,
        revision: EventDataRevision | DataRevision,
        content: (
            EventData | VisibleCardData | VisualIdentityData | TableObservationData | bytes | None
        ),
    ) -> tuple[
        DataRevision, EventData | VisibleCardData | VisualIdentityData | TableObservationData
    ]:
        if isinstance(revision, EventDataRevision):
            if content is not None:
                raise TypeError("content must not be supplied with EventDataRevision")
            return revision.manifest, revision.content
        if not isinstance(revision, DataRevision) or content is None:
            raise TypeError("publish requires an EventDataRevision or manifest and content")
        if isinstance(content, bytes):
            return revision, self._parse_content_bytes_for_manifest(revision, content)
        if revision.content_type == "events" and isinstance(content, EventData):
            return revision, content
        if revision.content_type == "visible_cards" and isinstance(content, VisibleCardData):
            return revision, content
        if revision.content_type == "visual_identities" and isinstance(
            content, VisualIdentityData
        ):
            return revision, content
        if revision.content_type == "table_observations" and isinstance(
            content, TableObservationData
        ):
            return revision, content
        raise TypeError("revision content does not match its content type")

    @staticmethod
    def _parse_content_bytes_for_manifest(
        manifest: DataRevision, raw: bytes
    ) -> EventData | VisibleCardData | VisualIdentityData | TableObservationData:
        duration_us = (
            manifest.source.duration_us
            if isinstance(manifest.source, RecordingVideoSource)
            else 2**63 - 1
        )
        if manifest.content_type == "events":
            return parse_event_data_bytes(raw, duration_us=duration_us)
        if manifest.content_type == "visible_cards":
            try:
                return parse_visible_card_data_bytes(raw)
            except PipelineDataError as error:
                raise PipelineDataContractError(str(error)) from error
        if manifest.content_type == "visual_identities":
            try:
                return parse_visual_identity_data_bytes(raw)
            except PipelineDataError as error:
                raise PipelineDataContractError(str(error)) from error
        if manifest.content_type == "table_observations":
            try:
                return parse_table_observation_data_bytes(raw)
            except PipelineDataError as error:
                raise PipelineDataContractError(str(error)) from error
        raise PipelineDataContractError("unsupported pipeline content type")

    @staticmethod
    def _canonical_content_bytes(
        content: EventData | VisibleCardData | VisualIdentityData | TableObservationData,
    ) -> bytes:
        if isinstance(content, EventData):
            return canonical_event_data_bytes(content)
        if isinstance(content, VisibleCardData):
            return canonical_visible_card_data_bytes(content)
        if isinstance(content, VisualIdentityData):
            return canonical_visual_identity_data_bytes(content)
        if isinstance(content, TableObservationData):
            return canonical_table_observation_data_bytes(content)
        raise TypeError("unsupported pipeline content")

    @staticmethod
    def _validate_content(
        manifest: DataRevision,
        content: EventData | VisibleCardData | VisualIdentityData | TableObservationData,
    ) -> None:
        if manifest.content_type == "events" and isinstance(content, EventData):
            validate_event_revision_content(manifest, content)
            return
        if manifest.content_type == "visible_cards" and isinstance(content, VisibleCardData):
            if sha256_bytes(canonical_visible_card_data_bytes(content)) != manifest.content_sha256:
                raise PipelineDataContractError(
                    "content_sha256 does not match canonical visible-card content"
                )
            return
        if manifest.content_type == "visual_identities" and isinstance(
            content, VisualIdentityData
        ):
            if (
                sha256_bytes(canonical_visual_identity_data_bytes(content))
                != manifest.content_sha256
            ):
                raise PipelineDataContractError(
                    "content_sha256 does not match canonical visual-identity content"
                )
            return
        if manifest.content_type == "table_observations" and isinstance(
            content, TableObservationData
        ):
            if (
                not isinstance(manifest.source, RecordingVideoSource)
                or manifest.recording_id is None
            ):
                raise PipelineDataContractError(
                    "table-observation content needs a recording video source"
                )
            producer = manifest.producer
            if not isinstance(producer, ProcessorProducer):
                raise PipelineDataContractError(
                    "table-observation content needs processor lineage"
                )
            for observation in content.observations:
                source = observation.source
                if (
                    source.package_id is not None
                    or source.recording_id != manifest.recording_id
                    or source.video_sha256 != manifest.source.video_sha256
                    or source.assembly_run_id != producer.run_id
                    or tuple(source.input_revision_ids or ()) != manifest.input_revision_ids
                ):
                    raise PipelineDataContractError(
                        "table-observation source lineage does not match its revision"
                    )
            if (
                sha256_bytes(canonical_table_observation_data_bytes(content))
                != manifest.content_sha256
            ):
                raise PipelineDataContractError(
                    "content_sha256 does not match table-observation content"
                )
            return
        raise PipelineDataContractError("revision content does not match its manifest")

    @staticmethod
    def _validate_payload(
        manifest: DataRevision,
        content: EventData | VisibleCardData | VisualIdentityData | TableObservationData,
        manifest_bytes: bytes,
        content_bytes: bytes,
    ) -> None:
        _strict_json_file(
            manifest_bytes,
            canonical_data_revision_bytes(manifest),
            "revision manifest",
        )
        _strict_json_file(
            content_bytes,
            PipelineRevisionStore._canonical_content_bytes(content),
            "revision content",
        )
        parse_data_revision_bytes(manifest_bytes, content_bytes)
        PipelineRevisionStore._validate_content(manifest, content)

    @staticmethod
    def _validate_payload_bytes(manifest: DataRevision, raw: bytes, manifest_bytes: bytes) -> None:
        content = PipelineRevisionStore._parse_content_bytes_for_manifest(manifest, raw)
        expected = PipelineRevisionStore._canonical_content_bytes(content)
        _strict_json_file(raw, expected, "revision content")
        parse_data_revision_bytes(manifest_bytes, raw)

    def _validate_lineage(self, manifest: DataRevision) -> None:
        for input_revision_id in manifest.input_revision_ids:
            if self.get(input_revision_id) is None:
                raise PipelineNotFound(
                    f"The input pipeline revision was not found: {input_revision_id}"
                )
        if (
            manifest.origin == "corrected"
            and isinstance(manifest.producer, HumanProducer)
            and manifest.producer.base_revision_id not in manifest.input_revision_ids
        ):
            raise PipelineDataContractError(
                "corrected revision base_revision_id must be an input revision"
            )

    def _existing_or_error(self, path: Path) -> StoredPipelineRevision:
        try:
            return self._read_path(path)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            raise PipelineStoreError("The existing pipeline revision is invalid.") from error

    @staticmethod
    def _revision_bytes(revision: StoredPipelineRevision) -> tuple[bytes, bytes]:
        return (
            canonical_data_revision_bytes(revision.manifest),
            PipelineRevisionStore._canonical_content_bytes(revision.content),
        )

    def _read_path(
        self, path: Path, *, require_canonical_name: bool = True
    ) -> StoredPipelineRevision:
        if path.is_symlink() or not path.is_dir():
            raise OSError("pipeline revision directory is unavailable")
        members = list(path.rglob("*"))
        if any(member.is_symlink() for member in members) or any(
            member.is_dir() for member in members
        ):
            raise ValueError("pipeline revision members must be regular files")
        if {member.relative_to(path).as_posix() for member in members} != {
            "manifest.json",
            "content.json",
        }:
            raise ValueError("pipeline revision must contain only manifest.json and content.json")
        manifest_bytes = (path / "manifest.json").read_bytes()
        content_bytes = (path / "content.json").read_bytes()
        manifest = parse_data_revision_bytes(manifest_bytes, content_bytes)
        content = self._parse_content_bytes_for_manifest(manifest, content_bytes)
        _strict_json_file(
            manifest_bytes,
            canonical_data_revision_bytes(manifest),
            "revision manifest",
        )
        _strict_json_file(content_bytes, self._canonical_content_bytes(content), "revision content")
        self._validate_lineage(manifest)
        if require_canonical_name and manifest.revision_id != path.name:
            raise ValueError("revision ID differs from its directory name")
        self._validate_content(manifest, content)
        return StoredPipelineRevision(manifest=manifest, content=content)

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        LOGGER.warning("pipeline_revision_catalog_skipped path=%s reason=%s", path, error)


class ProcessorRunStore:
    """Create and atomically update processor run request and state resources."""

    def __init__(
        self,
        storage: PipelineRuntimeStorage | Path | str,
        *,
        revision_store: PipelineRevisionStore | None = None,
    ) -> None:
        self.storage = _storage(storage)
        self.root = self.storage.runs_root
        self.revision_store = revision_store or PipelineRevisionStore(self.storage)
        self._lock = RLock()

    def run_path(self, run_id: str) -> Path:
        return contained_path(self.root, _safe_id(run_id, "run_id"))

    def get(self, run_id: str) -> StoredProcessorRun | None:
        try:
            path = self.run_path(run_id)
        except (TypeError, ValueError):
            return None
        try:
            return self._read_path(path)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if path.exists() or path.is_symlink():
                self._log_invalid(path, error)
            return None

    def require(self, run_id: str) -> StoredProcessorRun:
        run = self.get(run_id)
        if run is None:
            raise PipelineNotFound(f"The processor run was not found: {run_id}")
        return run

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
                "schema_version": "processor-run-state/v1",
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
            }
        )
        state_bytes = canonical_processor_run_state_bytes(state)
        destination = self.run_path(parsed_request.run_id)
        with _process_lock(self.root / f".{parsed_request.run_id}.lock", self._lock):
            if destination.exists() or destination.is_symlink():
                existing = self._existing_or_error(destination)
                if canonical_processor_run_request_bytes(existing.request) == request_bytes:
                    return existing, False
                raise PipelineConflict(
                    "The run ID is already stored with different request content."
                )
            try:
                with staging_directory(self.root, prefix=f".{parsed_request.run_id}-") as staging:
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
            payload = canonical_processor_run_state_bytes(parsed_state)
            atomic_replace_json(
                self.state_path(run_id),
                payload,
                validate=lambda raw: self._validate_state_bytes(raw, run_id),
            )
            stored = self.get(run_id)
            if stored is None:
                raise PipelineStoreError("The updated processor run failed validation.")
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
            ),
        )

    def partial(
        self,
        run_id: str,
        *,
        progress: RunProgress,
        items: tuple[RunItemOutcome, ...],
        output_revision_ids: tuple[str, ...] | list[str] = (),
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
            ),
        )

    def fail(
        self,
        run_id: str,
        failure: RunFailure | Mapping[str, Any],
        *,
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
            ),
        )

    def update_progress(
        self,
        run_id: str,
        *,
        progress: RunProgress,
        items: tuple[RunItemOutcome, ...] | None = None,
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
                updated_at=timestamp,
            ),
        )

    def fail_non_terminal(
        self,
        *,
        failure: RunFailure | Mapping[str, Any],
        updated_at: datetime | str | None = None,
    ) -> int:
        """Fail queued or running runs left behind by a stopped backend."""

        failed = 0
        for item in self.list():
            if item.state.status == "queued":
                self.start(item.run_id, started_at=updated_at)
            current = self.get(item.run_id)
            if current is None or current.state.status != "running":
                continue
            self.fail(item.run_id, failure, completed_at=updated_at)
            failed += 1
        return failed

    def state_path(self, run_id: str) -> Path:
        return self.run_path(run_id) / "state.json"

    def request_path(self, run_id: str) -> Path:
        return self.run_path(run_id) / "request.json"

    def _existing_or_error(self, path: Path) -> StoredProcessorRun:
        try:
            return self._read_path(path)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            raise PipelineStoreError("The existing processor run is invalid.") from error

    @staticmethod
    def _validate_state_bytes(raw: bytes, run_id: str) -> None:
        state = parse_processor_run_state_bytes(raw)
        if state.run_id != run_id:
            raise PipelineStateError("run state ID differs from its directory")
        _strict_json_file(raw, canonical_processor_run_state_bytes(state), "processor run state")

    def _read_path(self, path: Path, *, require_canonical_name: bool = True) -> StoredProcessorRun:
        if path.is_symlink() or not path.is_dir():
            raise OSError("processor run directory is unavailable")
        members = [
            member
            for member in path.rglob("*")
            if not (
                member.is_file()
                and member.name.endswith(".tmp")
                and (
                    member.name.startswith(".request.json.")
                    or member.name.startswith(".state.json.")
                )
            )
        ]
        if any(member.is_symlink() for member in members) or any(
            member.is_dir() for member in members
        ):
            raise ValueError("processor run members must be regular files")
        if {member.relative_to(path).as_posix() for member in members} != {
            "request.json",
            "state.json",
        }:
            raise ValueError("processor run must contain only request.json and state.json")
        request_bytes = (path / "request.json").read_bytes()
        state_bytes = (path / "state.json").read_bytes()
        request = parse_processor_run_request_bytes(request_bytes)
        state = parse_processor_run_state_bytes(state_bytes)
        _strict_json_file(
            request_bytes,
            canonical_processor_run_request_bytes(request),
            "processor run request",
        )
        _strict_json_file(state_bytes, canonical_processor_run_state_bytes(state), "run state")
        if request.run_id != state.run_id:
            raise ValueError("processor run request and state IDs differ")
        if require_canonical_name and request.run_id != path.name:
            raise ValueError("run ID differs from its directory name")
        self._validate_output_revisions(request, state)
        return StoredProcessorRun(request=request, state=state)

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
        self, request: ProcessorRunRequest, state: ProcessorRunState
    ) -> None:
        if not state.output_revision_ids:
            return
        for revision_id in state.output_revision_ids:
            revision = self.revision_store.get(revision_id)
            if revision is None:
                raise PipelineStoreError(f"run output revision is not published: {revision_id}")
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
            }.get(request.processor_type)
            if expected_content_type is not None and manifest.content_type != expected_content_type:
                raise PipelineStateError("run output revision has a different content type")
            if manifest.source != request.source:
                raise PipelineStateError("run output revision has a different source")
            if manifest.input_revision_ids != request.input_revision_ids:
                raise PipelineStateError("run output revision has different input lineage")

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        LOGGER.warning("processor_run_catalog_skipped path=%s reason=%s", path, error)


class PipelineSelectionStore:
    """Read and optimistically update current generated/reference selection pointers."""

    def __init__(
        self,
        storage: PipelineRuntimeStorage | Path | str,
        *,
        revision_store: PipelineRevisionStore | None = None,
        run_store: ProcessorRunStore | None = None,
    ) -> None:
        self.storage = _storage(storage)
        self.root = self.storage.selections_root
        self.revision_store = revision_store or PipelineRevisionStore(self.storage)
        self.run_store = run_store or ProcessorRunStore(
            self.storage,
            revision_store=self.revision_store,
        )
        self._lock = RLock()

    def selection_path(self, recording_id: str, content_type: str) -> Path:
        _safe_id(recording_id, "recording_id")
        _safe_content_type(content_type)
        return contained_path(
            self.root / recording_id,
            f"{content_type}.json",
        )

    def get(self, recording_id: str, content_type: str) -> PipelineSelection | None:
        try:
            path = self.selection_path(recording_id, content_type)
        except (TypeError, ValueError):
            return None
        try:
            return self._read_path(path, recording_id, content_type)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if path.exists() or path.is_symlink():
                self._log_invalid(path, error)
            return None

    def list(self) -> tuple[PipelineSelection, ...]:
        if self.root.is_symlink() or not self.root.is_dir():
            return ()
        selections: list[PipelineSelection] = []
        for recording_directory in sorted(self.root.iterdir(), key=lambda path: path.name):
            if recording_directory.name.startswith("."):
                self._log_invalid(recording_directory, ValueError("staging directory ignored"))
                continue
            if recording_directory.is_symlink() or not recording_directory.is_dir():
                continue
            for path in sorted(recording_directory.glob("*.json"), key=lambda item: item.name):
                content_type = path.stem
                try:
                    selections.append(self._read_path(path, recording_directory.name, content_type))
                except (OSError, TypeError, UnicodeError, ValueError) as error:
                    self._log_invalid(path, error)
        return tuple(sorted(selections, key=lambda item: (item.recording_id, item.content_type)))

    def list_for_recording(self, recording_id: str) -> tuple[PipelineSelection, ...]:
        return tuple(item for item in self.list() if item.recording_id == recording_id)

    def update(
        self,
        recording_id: str,
        content_type: str,
        update: PipelineSelectionUpdate | Mapping[str, Any],
        *,
        updated_at: datetime | str | None = None,
    ) -> PipelineSelection:
        parsed_update = (
            PipelineSelectionUpdate.from_mapping(update.to_mapping())
            if isinstance(update, PipelineSelectionUpdate)
            else PipelineSelectionUpdate.from_mapping(update)
        )
        path = self.selection_path(recording_id, content_type)
        with _process_lock(
            path.parent / f".{path.stem}.lock",
            self._lock,
        ):
            current = self.get(recording_id, content_type)
            current_revision = 0 if current is None else current.revision
            if parsed_update.expected_revision != current_revision:
                raise PipelineSelectionConflict(
                    f"selection revision mismatch: expected {parsed_update.expected_revision}, "
                    f"actual {current_revision}"
                )
            self._validate_pointer(
                parsed_update.selected_generated_revision_id,
                recording_id,
                content_type,
                role="generated",
            )
            self._validate_pointer(
                parsed_update.selected_completed_reference_revision_id,
                recording_id,
                content_type,
                role="completed reference",
            )
            selection = PipelineSelection(
                revision=current_revision + 1,
                recording_id=recording_id,
                content_type=content_type,
                selected_generated_revision_id=parsed_update.selected_generated_revision_id,
                selected_completed_reference_revision_id=(
                    parsed_update.selected_completed_reference_revision_id
                ),
                updated_at=_canonical_timestamp(updated_at),
            )
            payload = canonical_pipeline_selection_bytes(selection)
            atomic_replace_json(
                path,
                payload,
                validate=lambda raw: _strict_json_file(raw, payload, "pipeline selection"),
            )
            stored = self.get(recording_id, content_type)
            if stored is None:
                raise PipelineStoreError("The updated pipeline selection failed validation.")
            return stored

    def update_pointers(
        self,
        recording_id: str,
        content_type: str,
        *,
        expected_revision: int,
        selected_generated_revision_id: str | None,
        selected_completed_reference_revision_id: str | None,
        updated_at: datetime | str | None = None,
    ) -> PipelineSelection:
        return self.update(
            recording_id,
            content_type,
            PipelineSelectionUpdate(
                expected_revision=expected_revision,
                selected_generated_revision_id=selected_generated_revision_id,
                selected_completed_reference_revision_id=selected_completed_reference_revision_id,
            ),
            updated_at=updated_at,
        )

    def _validate_pointer(
        self,
        revision_id: str | None,
        recording_id: str,
        content_type: str,
        *,
        role: str,
    ) -> None:
        if revision_id is None:
            return
        revision = self.revision_store.require(revision_id)
        manifest = revision.manifest
        if (
            manifest.recording_id != recording_id
            or manifest.content_type != content_type
            or not isinstance(manifest.source, RecordingVideoSource)
        ):
            raise PipelineStateError(
                f"{role} selection points to a different recording or content type"
            )
        if role == "generated":
            if manifest.origin != "processor" or not isinstance(
                manifest.producer, (ProcessorProducer, ImportProducer)
            ):
                raise PipelineStateError("generated selection must point to processor output")
            run = self.run_store.get(manifest.producer.run_id)
            if run is None or run.state.status != "complete":
                raise PipelineStateError(
                    "generated selection cannot point to a partial or failed run"
                )
            if revision_id not in run.state.output_revision_ids:
                raise PipelineStateError("generated selection is not an output of its run")
        elif manifest.origin not in {"manual", "corrected"} or not isinstance(
            manifest.producer, HumanProducer
        ):
            raise PipelineStateError("completed reference selection must point to human output")

    def _read_path(
        self,
        path: Path,
        recording_id: str,
        content_type: str,
    ) -> PipelineSelection:
        if path.is_symlink() or not path.is_file():
            raise OSError("pipeline selection is unavailable")
        raw = path.read_bytes()
        selection = parse_pipeline_selection_bytes(raw)
        _strict_json_file(raw, canonical_pipeline_selection_bytes(selection), "pipeline selection")
        if selection.recording_id != recording_id or selection.content_type != content_type:
            raise ValueError("selection identity differs from its path")
        if path.name != f"{content_type}.json":
            raise ValueError("selection content type differs from its path")
        self._validate_pointer(
            selection.selected_generated_revision_id,
            recording_id,
            content_type,
            role="generated",
        )
        self._validate_pointer(
            selection.selected_completed_reference_revision_id,
            recording_id,
            content_type,
            role="completed reference",
        )
        return selection

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        LOGGER.warning("pipeline_selection_catalog_skipped path=%s reason=%s", path, error)


__all__ = [
    "PipelineConflict",
    "PipelineNotFound",
    "PipelineRevisionStore",
    "PipelineRuntimeStorage",
    "PipelineSelectionConflict",
    "PipelineSelectionStore",
    "PipelineStateError",
    "PipelineStoreError",
    "ProcessorRunStore",
    "StoredPipelineRevision",
    "StoredProcessorRun",
]
