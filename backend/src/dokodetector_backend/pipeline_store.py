"""Filesystem stores for recording-pipeline revisions, runs, and selections.

The stores keep no derived index.  A resource is visible only after its complete canonical
directory has been published, and every read validates the files before returning the resource.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Collection, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from doko_operations.pipeline_data import (
    PROCESSOR_RUN_STATE_SCHEMA_VERSION,
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
    canonical_json_bytes,
    canonical_pipeline_selection_bytes,
    canonical_processor_run_request_bytes,
    canonical_processor_run_state_bytes,
    parse_data_revision_bytes,
    parse_data_revision_manifest_bytes,
    parse_event_data_bytes,
    parse_pipeline_selection_bytes,
    parse_processor_run_request_bytes,
    sha256_bytes,
    validate_event_revision_content,
)
from table_evidence_analyzer.pipeline_data import (
    PipelineDataError,
    ProposedCardSceneData,
    TableObservationData,
    VisibleCardData,
    VisualIdentityData,
    canonical_proposed_card_scene_data_bytes,
    canonical_table_observation_data_bytes,
    canonical_visible_card_data_bytes,
    canonical_visual_identity_data_bytes,
    parse_proposed_card_scene_data_bytes,
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
_LEGACY_PROCESSOR_RUN_STATE_SCHEMA_VERSION = "processor-run-state/v1"


class PipelineStoreError(RuntimeError):
    """The canonical pipeline resource could not be read or written."""


class PipelineConflict(PipelineStoreError):
    """A resource ID or optimistic pointer is already used by different content."""


class PipelineNotFound(PipelineStoreError, ValueError):
    """The requested pipeline resource does not exist."""


class PipelineStateError(PipelineStoreError, ValueError):
    """A run state transition or state invariant is invalid."""


class PipelineSelectionConflict(PipelineConflict):
    """A selection update used an old expected revision."""


@dataclass(frozen=True, slots=True)
class PipelineRuntimeStorage:
    """Separate durable pipeline records from rebuildable derived views."""

    runtime_root: Path
    operations_root: Path

    def __init__(self, runtime_root: Path | str, operations_root: Path | str | None = None) -> None:
        object.__setattr__(self, "runtime_root", Path(runtime_root).expanduser().resolve())
        object.__setattr__(
            self,
            "operations_root",
            (
                Path(operations_root).expanduser().resolve()
                if operations_root is not None
                else Path(runtime_root).expanduser().resolve()
            ),
        )

    @property
    def pipeline_root(self) -> Path:
        return self.operations_root / "pipeline"

    @property
    def derived_views_root(self) -> Path:
        return self.runtime_root / "pipeline" / "derived-views"

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
class ProcessorRunStatus:
    """The small mutable state projection needed by recording catalogs."""

    run_id: str
    recording_id: str
    processor_type: str
    status: str


@dataclass(frozen=True, slots=True)
class StoredPipelineRevision:
    """A validated manifest and content payload from the immutable revision store."""

    manifest: DataRevision
    content: (
        EventData
        | VisibleCardData
        | VisualIdentityData
        | TableObservationData
        | ProposedCardSceneData
    )

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
    if value not in {
        "events",
        "visible_cards",
        "visual_identities",
        "table_observations",
        "card_scene_proposals",
    }:
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


def _parse_json_object(raw: bytes, context: str) -> dict[str, Any]:
    """Parse one strict JSON object for the split processor-run storage format."""

    def reject_constant(value: str) -> None:
        raise PipelineDataContractError(f"{context} contains a non-finite JSON number: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PipelineDataContractError(f"{context} contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineDataContractError(f"{context} is not valid JSON") from error
    if not isinstance(value, dict):
        raise PipelineDataContractError(f"{context} must be a JSON object")
    return value


def _canonical_split_state_bytes(
    state: ProcessorRunState, item_ids: tuple[str, ...] | list[str]
) -> bytes:
    """Encode run metadata while keeping item outcomes in separate files."""

    mapping = state.to_mapping()
    mapping.pop("items")
    mapping["item_ids"] = list(item_ids)
    return canonical_json_bytes(mapping)


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


class PipelineRevisionStore:
    """Publish and read immutable pipeline data revisions."""

    def __init__(self, storage: PipelineRuntimeStorage | Path | str) -> None:
        self.storage = _storage(storage)
        self.root = self.storage.revisions_root
        self._lock = RLock()

    def revision_path(self, revision_id: str) -> Path:
        return contained_path(self.root, _safe_id(revision_id, "revision_id"))

    def get(
        self,
        revision_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
    ) -> StoredPipelineRevision | None:
        if revision_cache is not None:
            cached = revision_cache.get(revision_id)
            if cached is not None:
                return cached
        try:
            path = self.revision_path(revision_id)
        except (TypeError, ValueError):
            return None
        try:
            revision = self._read_path(path, revision_cache=revision_cache)
            if revision_cache is not None:
                revision_cache[revision_id] = revision
            return revision
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            if path.exists() or path.is_symlink():
                self._log_invalid(path, error)
            return None

    def require(
        self,
        revision_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
    ) -> StoredPipelineRevision:
        revision = self.get(revision_id, revision_cache=revision_cache)
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

    def list_for_recording(
        self,
        recording_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
    ) -> tuple[StoredPipelineRevision, ...]:
        """Return validated revisions for one recording without parsing other recordings."""

        _safe_id(recording_id, "recording_id")
        enumeration = enumerate_resource_directories(self.root)
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        revisions: list[StoredPipelineRevision] = []
        for path in enumeration.paths:
            try:
                manifest = parse_data_revision_bytes((path / "manifest.json").read_bytes())
                if manifest.recording_id != recording_id:
                    continue
                revision = (
                    None
                    if revision_cache is None
                    else revision_cache.get(manifest.revision_id)
                )
                if revision is None:
                    revision = self._read_path(path, revision_cache=revision_cache)
                if revision_cache is not None:
                    revision_cache[manifest.revision_id] = revision
                revisions.append(revision)
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(sorted(revisions, key=lambda item: item.manifest.revision_id))

    def list_manifests(self) -> tuple[DataRevision, ...]:
        """Return valid revision manifests without reading revision content."""

        enumeration = enumerate_resource_directories(self.root)
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        manifests: list[DataRevision] = []
        for path in enumeration.paths:
            try:
                if path.is_symlink() or not path.is_dir():
                    raise OSError("pipeline revision directory is unavailable")
                children = list(path.iterdir())
                if any(member.is_symlink() or member.is_dir() for member in children):
                    raise ValueError("pipeline revision members must be regular files")
                names = {member.name for member in children if member.is_file()}
                if names != {"manifest.json", "content.json"}:
                    raise ValueError(
                        "pipeline revision must contain only manifest.json and content.json"
                    )
                manifest_bytes = (path / "manifest.json").read_bytes()
                manifest = parse_data_revision_manifest_bytes(manifest_bytes)
                _strict_json_file(
                    manifest_bytes,
                    canonical_data_revision_bytes(manifest),
                    "revision manifest",
                )
                if manifest.revision_id != path.name:
                    raise ValueError("revision ID differs from its directory name")
                manifests.append(manifest)
            except (OSError, TypeError, UnicodeError, ValueError) as error:
                self._log_invalid(path, error)
        return tuple(sorted(manifests, key=lambda item: item.revision_id))

    def has_revision(self, revision_id: str) -> bool:
        """Return whether a revision directory exists without reading content."""

        try:
            path = self.revision_path(revision_id)
        except (TypeError, ValueError):
            return False
        return path.is_dir() and not path.is_symlink() and (path / "manifest.json").is_file()

    def publish(
        self,
        revision: EventDataRevision | DataRevision,
        content: (
            EventData
            | VisibleCardData
            | VisualIdentityData
            | TableObservationData
            | ProposedCardSceneData
            | bytes
            | None
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
            EventData
            | VisibleCardData
            | VisualIdentityData
            | TableObservationData
            | ProposedCardSceneData
            | bytes
            | None
        ),
    ) -> tuple[
        DataRevision,
        EventData
        | VisibleCardData
        | VisualIdentityData
        | TableObservationData
        | ProposedCardSceneData,
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
        if revision.content_type == "card_scene_proposals" and isinstance(
            content, ProposedCardSceneData
        ):
            return revision, content
        raise TypeError("revision content does not match its content type")

    @staticmethod
    def _parse_content_bytes_for_manifest(
        manifest: DataRevision, raw: bytes, *, allow_legacy: bool = False
    ) -> (
        EventData
        | VisibleCardData
        | VisualIdentityData
        | TableObservationData
        | ProposedCardSceneData
    ):
        duration_us = (
            manifest.source.duration_us
            if isinstance(manifest.source, RecordingVideoSource)
            else 2**63 - 1
        )
        if manifest.content_type == "events":
            return parse_event_data_bytes(
                raw, duration_us=duration_us, allow_legacy=allow_legacy
            )
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
        if manifest.content_type == "card_scene_proposals":
            try:
                return parse_proposed_card_scene_data_bytes(raw)
            except PipelineDataError as error:
                raise PipelineDataContractError(str(error)) from error
        raise PipelineDataContractError("unsupported pipeline content type")

    @staticmethod
    def _canonical_content_bytes(
        content: (
            EventData
            | VisibleCardData
            | VisualIdentityData
            | TableObservationData
            | ProposedCardSceneData
        ),
        *,
        allow_legacy: bool = False,
    ) -> bytes:
        if isinstance(content, EventData):
            return canonical_event_data_bytes(content, allow_legacy=allow_legacy)
        if isinstance(content, VisibleCardData):
            return canonical_visible_card_data_bytes(content)
        if isinstance(content, VisualIdentityData):
            return canonical_visual_identity_data_bytes(content)
        if isinstance(content, TableObservationData):
            return canonical_table_observation_data_bytes(content)
        if isinstance(content, ProposedCardSceneData):
            return canonical_proposed_card_scene_data_bytes(content)
        raise TypeError("unsupported pipeline content")

    @staticmethod
    def _validate_content(
        manifest: DataRevision,
        content: (
            EventData
            | VisibleCardData
            | VisualIdentityData
            | TableObservationData
            | ProposedCardSceneData
        ),
        *,
        allow_legacy: bool = False,
    ) -> None:
        if manifest.content_type == "events" and isinstance(content, EventData):
            validate_event_revision_content(manifest, content, allow_legacy=allow_legacy)
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
        if manifest.content_type == "card_scene_proposals" and isinstance(
            content, ProposedCardSceneData
        ):
            if (
                not isinstance(manifest.source, RecordingVideoSource)
                or manifest.recording_id is None
                or manifest.input_revision_ids != (content.detector_revision_id,)
            ):
                raise PipelineDataContractError(
                    "proposed card scene content has invalid detector lineage"
                )
            if (
                sha256_bytes(canonical_proposed_card_scene_data_bytes(content))
                != manifest.content_sha256
            ):
                raise PipelineDataContractError(
                    "content_sha256 does not match proposed card scene content"
                )
            if content.detector_revision_digest != manifest.coverage.get(
                "detector_revision_digest"
            ):
                raise PipelineDataContractError(
                    "proposed card scene detector digest does not match its manifest"
                )
            return
        raise PipelineDataContractError("revision content does not match its manifest")

    @staticmethod
    def _validate_payload(
        manifest: DataRevision,
        content: (
            EventData
            | VisibleCardData
            | VisualIdentityData
            | TableObservationData
            | ProposedCardSceneData
        ),
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

    def _validate_lineage(
        self,
        manifest: DataRevision,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
    ) -> None:
        for input_revision_id in manifest.input_revision_ids:
            if self.get(input_revision_id, revision_cache=revision_cache) is None:
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
        self,
        path: Path,
        *,
        require_canonical_name: bool = True,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
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
        manifest = parse_data_revision_bytes(
            manifest_bytes, content_bytes, allow_legacy=True
        )
        content = self._parse_content_bytes_for_manifest(
            manifest, content_bytes, allow_legacy=True
        )
        _strict_json_file(
            manifest_bytes,
            canonical_data_revision_bytes(manifest),
            "revision manifest",
        )
        _strict_json_file(
            content_bytes,
            self._canonical_content_bytes(content, allow_legacy=True),
            "revision content",
        )
        self._validate_lineage(manifest, revision_cache=revision_cache)
        if require_canonical_name and manifest.revision_id != path.name:
            raise ValueError("revision ID differs from its directory name")
        self._validate_content(manifest, content, allow_legacy=True)
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

    def get(
        self,
        run_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        include_items: bool = True,
        validate_output_revisions: bool = True,
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
    ) -> StoredProcessorRun:
        run = self.get(
            run_id,
            revision_cache=revision_cache,
            include_items=include_items,
            validate_output_revisions=validate_output_revisions,
        )
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

    def list_for_recording(
        self,
        recording_id: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        include_items: bool = True,
        validate_output_revisions: bool = True,
        include_items_for_processor_types: Collection[str] | None = None,
    ) -> tuple[StoredProcessorRun, ...]:
        """Return validated runs for one recording without parsing other recordings."""

        _safe_id(recording_id, "recording_id")
        enumeration = enumerate_resource_directories(self.root)
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        runs: list[StoredProcessorRun] = []
        for path in enumeration.paths:
            try:
                request = parse_processor_run_request_bytes((path / "request.json").read_bytes())
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
        if "item_ids" in metadata:
            state, _ = _parse_split_state_bytes(state_bytes)
        else:
            state = _parse_processor_run_metadata_bytes(state_bytes)
        if state.run_id != request.run_id:
            raise ValueError("processor run request and state IDs differ")
        return ProcessorRunStatus(
            run_id=request.run_id,
            recording_id=request.source.recording_id,
            processor_type=request.processor_type,
            status=state.status,
        )

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
            if destination.exists() or destination.is_symlink():
                existing = self._existing_or_error(destination)
                if canonical_processor_run_request_bytes(existing.request) == request_bytes:
                    return existing, False
                raise PipelineConflict(
                    "The run ID is already stored with different request content."
                )
            try:
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
            if self.items_path(run_id).is_dir():
                current_items = {item.item_id: item for item in current.state.items}
                self._write_changed_items(run_id, current_items, parsed_state.items)
                payload = _canonical_split_state_bytes(
                    parsed_state, tuple(item.item_id for item in parsed_state.items)
                )
                atomic_replace_json(
                    self.state_path(run_id),
                    payload,
                    validate=lambda raw: self._validate_state_bytes(raw, run_id),
                )
            else:
                payload = canonical_processor_run_state_bytes(parsed_state)
                atomic_replace_json(
                    self.state_path(run_id),
                    payload,
                    validate=lambda raw: self._validate_state_bytes(raw, run_id),
                )
            return StoredProcessorRun(request=current.request, state=parsed_state)

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
                return

            _, current_state, item_ids = self._read_split_metadata(path)
            if current_state.status != "running":
                raise PipelineStateError("only running runs can receive progress")
            if _timestamp_value(timestamp) < _timestamp_value(current_state.updated_at):
                raise PipelineStateError("run updated_at cannot go backwards")
            existing = None
            if parsed_item.item_id in item_ids:
                existing = self._read_item_file(
                    self.items_path(run_id) / f"{parsed_item.item_id}.json",
                    parsed_item.item_id,
                )
                if existing.status == "succeeded" and existing != parsed_item:
                    raise PipelineStateError("successful item outcomes cannot be replaced")
            if existing != parsed_item:
                self._write_item_file(run_id, parsed_item)
            next_item_ids = (
                item_ids
                if parsed_item.item_id in item_ids
                else (*item_ids, parsed_item.item_id)
            )
            next_state = replace(current_state, progress=progress, updated_at=timestamp)
            atomic_replace_json(
                self.state_path(run_id),
                _canonical_split_state_bytes(next_state, next_item_ids),
                validate=lambda raw: self._validate_state_bytes(raw, run_id),
            )

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
        if "item_ids" in metadata:
            state, _ = _parse_split_state_bytes(raw)
        else:
            state = _parse_processor_run_state_bytes_compat(raw)
        if state.run_id != run_id:
            raise PipelineStateError("run state ID differs from its directory")

    def _read_path(
        self,
        path: Path,
        *,
        require_canonical_name: bool = True,
        validate_output_revisions: bool = True,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        include_items: bool = True,
    ) -> StoredProcessorRun:
        if path.is_symlink() or not path.is_dir():
            raise OSError("processor run directory is unavailable")
        # Catalog loads (`include_items=False`) must not walk `items/`. Visual-identity
        # runs store hundreds of item files; a recursive scan dominates pipeline workspace
        # latency. Validate only the top-level run layout, then load items by ID when asked.
        top_members = [
            member for member in path.iterdir() if not _is_atomic_json_temp(member)
        ]
        if any(member.is_symlink() for member in top_members):
            raise ValueError("processor run members must not be symlinks")
        top_files = {member.name for member in top_members if member.is_file()}
        top_dirs = {member.name for member in top_members if member.is_dir()}
        legacy_layout = not top_dirs and top_files == {"request.json", "state.json"}
        split_layout = (
            top_dirs == {"items"} and top_files == {"request.json", "state.json"}
        )
        if not legacy_layout and not split_layout:
            raise ValueError("processor run has an unsupported file layout")
        request_bytes = (path / "request.json").read_bytes()
        state_bytes = (path / "state.json").read_bytes()
        request = parse_processor_run_request_bytes(request_bytes)
        _strict_json_file(
            request_bytes,
            canonical_processor_run_request_bytes(request),
            "processor run request",
        )
        if legacy_layout:
            state = (
                _parse_processor_run_state_bytes_compat(state_bytes)
                if include_items
                else _parse_processor_run_metadata_bytes(state_bytes)
            )
        else:
            metadata_state, item_ids = _parse_split_state_bytes(state_bytes)
            if include_items:
                items_dir = path / "items"
                item_members = [
                    member
                    for member in items_dir.iterdir()
                    if not _is_atomic_json_temp(member)
                ]
                if any(member.is_symlink() for member in item_members):
                    raise ValueError("processor run members must not be symlinks")
                if any(member.is_dir() for member in item_members):
                    raise ValueError("processor run has an unsupported file layout")
                item_files = {
                    member.name for member in item_members if member.is_file()
                }
                if not all(name.endswith(".json") for name in item_files):
                    raise ValueError("processor run has an unsupported file layout")
                if not {
                    f"{item_id}.json" for item_id in item_ids
                }.issubset(item_files):
                    raise ValueError("processor run is missing a referenced item file")
                items = tuple(
                    self._read_item_file(items_dir / f"{item_id}.json", item_id)
                    for item_id in item_ids
                )
                state = replace(metadata_state, items=items)
            else:
                state = metadata_state
        if request.run_id != state.run_id:
            raise ValueError("processor run request and state IDs differ")
        if require_canonical_name and request.run_id != path.name:
            raise ValueError("run ID differs from its directory name")
        if validate_output_revisions:
            self._validate_output_revisions(request, state, revision_cache=revision_cache)
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

    def _write_changed_items(
        self,
        run_id: str,
        current_items: Mapping[str, RunItemOutcome],
        updated_items: tuple[RunItemOutcome, ...],
    ) -> None:
        for item in updated_items:
            if current_items.get(item.item_id) != item:
                self._write_item_file(run_id, item)

    def _write_item_file(self, run_id: str, item: RunItemOutcome) -> None:
        item_path = self.items_path(run_id) / f"{_safe_id(item.item_id, 'item_id')}.json"
        payload = canonical_json_bytes(item.to_mapping())
        atomic_replace_json(
            item_path,
            payload,
            validate=lambda raw: self._validate_item_bytes(raw, item.item_id),
        )

    @staticmethod
    def _validate_item_bytes(raw: bytes, item_id: str) -> None:
        item = RunItemOutcome.from_mapping(_parse_json_object(raw, "processor run item"))
        if item.item_id != item_id:
            raise PipelineStateError("processor run item ID differs from its file name")
        _strict_json_file(raw, canonical_json_bytes(item.to_mapping()), "processor run item")

    @staticmethod
    def _read_item_file(path: Path, item_id: str) -> RunItemOutcome:
        raw = path.read_bytes()
        item = RunItemOutcome.from_mapping(_parse_json_object(raw, "processor run item"))
        if item.item_id != item_id:
            raise ValueError("processor run item ID differs from its file name")
        _strict_json_file(raw, canonical_json_bytes(item.to_mapping()), "processor run item")
        return item

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
    ) -> None:
        if not state.output_revision_ids:
            return
        for revision_id in state.output_revision_ids:
            revision = self.revision_store.get(revision_id, revision_cache=revision_cache)
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

    def get(
        self,
        recording_id: str,
        content_type: str,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        revision_manifests: Mapping[str, DataRevision] | None = None,
    ) -> PipelineSelection | None:
        try:
            path = self.selection_path(recording_id, content_type)
        except (TypeError, ValueError):
            return None
        try:
            return self._read_path(
                path,
                recording_id,
                content_type,
                revision_cache=revision_cache,
                revision_manifests=revision_manifests,
            )
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
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        revision_manifests: Mapping[str, DataRevision] | None = None,
    ) -> None:
        if revision_id is None:
            return
        if revision_manifests is None:
            revision = self.revision_store.require(revision_id, revision_cache=revision_cache)
            manifest = revision.manifest
        else:
            manifest = revision_manifests.get(revision_id)
            if manifest is None:
                raise PipelineNotFound(f"The pipeline revision was not found: {revision_id}")
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
            run = self.run_store.get(
                manifest.producer.run_id,
                revision_cache=revision_cache,
                include_items=False,
                validate_output_revisions=False,
            )
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
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
        revision_manifests: Mapping[str, DataRevision] | None = None,
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
            revision_cache=revision_cache,
            revision_manifests=revision_manifests,
        )
        self._validate_pointer(
            selection.selected_completed_reference_revision_id,
            recording_id,
            content_type,
            role="completed reference",
            revision_cache=revision_cache,
            revision_manifests=revision_manifests,
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
    "ProcessorRunStatus",
    "ProcessorRunStore",
    "StoredPipelineRevision",
    "StoredProcessorRun",
]
