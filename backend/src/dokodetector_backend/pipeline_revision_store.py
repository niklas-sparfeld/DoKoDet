"""Immutable pipeline data revision persistence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from doko_operations.pipeline_data import (
    DataRevision,
    EventData,
    EventDataRevision,
    HumanProducer,
    PipelineDataContractError,
    ProcessorProducer,
    RecordingVideoSource,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
    parse_data_revision_bytes,
    parse_data_revision_manifest_bytes,
    parse_event_data_bytes,
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
from dokodetector_backend.pipeline_storage import (
    PipelineConflict,
    PipelineNotFound,
    PipelineRuntimeStorage,
    PipelineStoreError,
    _process_lock,
    _safe_id,
    _storage,
    _strict_json_file,
)

LOGGER = logging.getLogger(__name__)


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
        validate_lineage: bool = True,
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
            revision = self._read_path(
                path,
                revision_cache=revision_cache,
                validate_lineage=validate_lineage,
            )
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
        validate_lineage: bool = True,
    ) -> StoredPipelineRevision:
        revision = self.get(
            revision_id,
            revision_cache=revision_cache,
            validate_lineage=validate_lineage,
        )
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
                    None if revision_cache is None else revision_cache.get(manifest.revision_id)
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

        return self._list_manifests(recording_id=None)

    def list_manifests_for_recording(self, recording_id: str) -> tuple[DataRevision, ...]:
        """Return valid revision manifests for one recording without reading content."""

        _safe_id(recording_id, "recording_id")
        return self._list_manifests(recording_id=recording_id)

    def _list_manifests(self, *, recording_id: str | None) -> tuple[DataRevision, ...]:
        """Read valid manifests, optionally filtering by their canonical recording field."""

        enumeration = enumerate_resource_directories(self.root)
        for diagnostic in enumeration.diagnostics:
            self._log_invalid(diagnostic.path, ValueError(diagnostic.reason))

        manifests: list[DataRevision] = []
        recording_marker = (
            None if recording_id is None else f'"recording_id":"{recording_id}"'.encode("ascii")
        )
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
                if recording_marker is not None and recording_marker not in manifest_bytes:
                    continue
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
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
    ) -> tuple[StoredPipelineRevision, bool]:
        """Publish one complete revision, or replay identical bytes."""

        if revision_cache is None:
            revision_cache = {}
        manifest, pipeline_content = self._coerce_revision(revision, content)
        manifest_bytes = canonical_data_revision_bytes(manifest)
        content_bytes = self._canonical_content_bytes(pipeline_content)
        self._validate_payload(manifest, pipeline_content, manifest_bytes, content_bytes)
        self._validate_lineage(manifest, revision_cache=revision_cache)
        revision_id = manifest.revision_id
        destination = self.revision_path(revision_id)

        with _process_lock(self.root / f".{revision_id}.lock", self._lock):
            if destination.exists() or destination.is_symlink():
                existing = self._existing_or_error(destination, revision_cache=revision_cache)
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
                        validate=lambda path: self._read_path(
                            path, require_canonical_name=False, revision_cache=revision_cache
                        ),
                    )
            except FileExistsError as error:
                existing = self._existing_or_error(destination, revision_cache=revision_cache)
                if self._revision_bytes(existing) == (manifest_bytes, content_bytes):
                    return existing, False
                raise PipelineConflict(
                    "The revision ID is already stored with different content."
                ) from error
            except (OSError, ValueError) as error:
                raise PipelineStoreError("The pipeline revision could not be published.") from error
            stored = self.get(revision_id, revision_cache=revision_cache)
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
        if revision.content_type == "visual_identities" and isinstance(content, VisualIdentityData):
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
            return parse_event_data_bytes(raw, duration_us=duration_us, allow_legacy=allow_legacy)
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
        if manifest.content_type == "visual_identities" and isinstance(content, VisualIdentityData):
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
                raise PipelineDataContractError("table-observation content needs processor lineage")
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
                if self.has_revision(input_revision_id):
                    raise PipelineDataContractError(
                        f"input pipeline revision is present but invalid: {input_revision_id}"
                    )
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

    def _existing_or_error(
        self,
        path: Path,
        *,
        revision_cache: dict[str, StoredPipelineRevision] | None = None,
    ) -> StoredPipelineRevision:
        try:
            return self._read_path(path, revision_cache=revision_cache)
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
        validate_lineage: bool = True,
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
        manifest = parse_data_revision_bytes(manifest_bytes, content_bytes, allow_legacy=True)
        content = self._parse_content_bytes_for_manifest(manifest, content_bytes, allow_legacy=True)
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
        if validate_lineage:
            self._validate_lineage(manifest, revision_cache=revision_cache)
        if require_canonical_name and manifest.revision_id != path.name:
            raise ValueError("revision ID differs from its directory name")
        self._validate_content(manifest, content, allow_legacy=True)
        return StoredPipelineRevision(manifest=manifest, content=content)

    @staticmethod
    def _log_invalid(path: Path, error: BaseException) -> None:
        reason = str(error)
        if reason == "content_type and content_schema do not match" or reason.startswith(
            "input pipeline revision is present but invalid:"
        ):
            LOGGER.debug("pipeline_revision_catalog_skipped path=%s reason=%s", path, error)
            return
        LOGGER.warning("pipeline_revision_catalog_skipped path=%s reason=%s", path, error)
