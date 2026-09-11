"""Read-only inventory and preflight audit for the legacy CardEventNet corpus.

The audit is deliberately independent from migration.  It reads legacy files and current
operations artifacts, then returns a deterministic report that a later migration can consume.
It does not create directories, change active pointers, or modify source bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .holdout import validate_system_holdout_registry
from .intake import discover_bundle_paths, inspect_repository

CARD_EVENTNET_INVENTORY_SCHEMA_VERSION = "cardeventnet-inventory/v1"
CARD_EVENTNET_TASK = "cardevent_event_detection"
VIDEO_EXTENSIONS = frozenset({".mov", ".m4v", ".mp4"})
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
LFS_OID = re.compile(rb"^oid sha256:([0-9a-f]{64})$", re.MULTILINE)
LFS_SIZE = re.compile(rb"^size ([0-9]+)$", re.MULTILINE)
LEGACY_PATH_TOKENS = (
    "card_event_net/data",
    "data/raw/",
    "data/annotations/",
    "data/splits/",
    "data/cache",
    "data/outputs/",
)


class CardEventNetInventoryError(ValueError):
    """Raised for an invalid audit configuration, not for a source-data discrepancy."""


@dataclass(frozen=True, slots=True)
class LegacyArtifact:
    """One legacy file and its planned migration disposition."""

    path: str
    kind: str
    byte_length: int | None
    sha256: str | None
    source_sha256: str | None
    source_byte_length: int | None
    content_state: str
    video_id: str | None
    annotation_present: bool | None
    human_review_complete: bool | None
    split_memberships: tuple[str, ...]
    disposition: str
    destination: str | None
    reason: str
    errors: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "source_sha256": self.source_sha256,
            "source_byte_length": self.source_byte_length,
            "content_state": self.content_state,
            "video_id": self.video_id,
            "annotation_present": self.annotation_present,
            "human_review_complete": self.human_review_complete,
            "split_memberships": list(self.split_memberships),
            "disposition": self.disposition,
            "destination": self.destination,
            "reason": self.reason,
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """One deterministic item-level audit finding."""

    kind: str
    message: str
    video_id: str | None = None
    path: str | None = None
    severity: str = "warning"

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "video_id": self.video_id,
            "path": self.path,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class RecordingAudit:
    """Legacy and shared state for one source recording identity."""

    video_id: str
    source_video: str | None
    raw_path: str | None
    raw_content_state: str | None
    source_sha256: str | None
    source_byte_length: int | None
    metadata_present: bool
    source_permission: str | None
    annotation_path: str | None
    annotation_present: bool
    annotation_valid: bool | None
    annotation_sha256: str | None
    annotation_schema: str | None
    annotation_event_count: int | None
    legacy_review_artifact_paths: tuple[str, ...]
    human_review_complete: bool
    human_review_basis: str | None
    shared_recording_id: str | None
    shared_bundle_state: str | None
    shared_source_sha256: str | None
    source_digest_match: bool | None
    event_revision_ids: tuple[str, ...]
    maintained_reference_state: str | None
    maintained_reference_revision_id: str | None
    development_partitions: tuple[str, ...]
    holdout_groups: tuple[str, ...]
    migration_state: str
    blockers: tuple[str, ...]
    next_action: str

    @property
    def annotation_review_complete(self) -> bool:
        """Return durable maintained-reference completion, never annotation-file presence."""

        return self.human_review_complete

    def to_mapping(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "source_video": self.source_video,
            "raw_path": self.raw_path,
            "raw_content_state": self.raw_content_state,
            "source_sha256": self.source_sha256,
            "source_byte_length": self.source_byte_length,
            "metadata_present": self.metadata_present,
            "source_permission": self.source_permission,
            "annotation_path": self.annotation_path,
            "annotation_present": self.annotation_present,
            "annotation_valid": self.annotation_valid,
            "annotation_sha256": self.annotation_sha256,
            "annotation_schema": self.annotation_schema,
            "annotation_event_count": self.annotation_event_count,
            "legacy_review_artifact_paths": list(self.legacy_review_artifact_paths),
            "human_review_complete": self.human_review_complete,
            "human_review_basis": self.human_review_basis,
            "shared_recording_id": self.shared_recording_id,
            "shared_bundle_state": self.shared_bundle_state,
            "shared_source_sha256": self.shared_source_sha256,
            "source_digest_match": self.source_digest_match,
            "event_revision_ids": list(self.event_revision_ids),
            "maintained_reference_state": self.maintained_reference_state,
            "maintained_reference_revision_id": self.maintained_reference_revision_id,
            "development_partitions": list(self.development_partitions),
            "holdout_groups": list(self.holdout_groups),
            "migration_state": self.migration_state,
            "blockers": list(self.blockers),
            "next_action": self.next_action,
        }


@dataclass(frozen=True, slots=True)
class CardEventNetInventory:
    """Complete deterministic M0 inventory report."""

    legacy_root: str
    shared_intake_root: str
    operations_root: str
    campaign_root: str
    legacy_root_exists: bool
    shared_intake_exists: bool
    operations_root_exists: bool
    campaign_root_exists: bool
    artifacts: tuple[LegacyArtifact, ...]
    recordings: tuple[RecordingAudit, ...]
    shared_recordings: tuple[dict[str, Any], ...]
    event_revisions: tuple[dict[str, Any], ...]
    maintained_references: tuple[dict[str, Any], ...]
    development_split: dict[str, Any]
    holdout_registry: dict[str, Any]
    campaign_artifacts: tuple[dict[str, Any], ...]
    discrepancies: tuple[Discrepancy, ...]

    def to_mapping(self) -> dict[str, Any]:
        counts = _counts(self)
        core: dict[str, Any] = {
            "schema_version": CARD_EVENTNET_INVENTORY_SCHEMA_VERSION,
            "read_only": True,
            "legacy_root": self.legacy_root,
            "shared_intake_root": self.shared_intake_root,
            "operations_root": self.operations_root,
            "campaign_root": self.campaign_root,
            "roots": {
                "legacy_exists": self.legacy_root_exists,
                "shared_intake_exists": self.shared_intake_exists,
                "operations_exists": self.operations_root_exists,
                "campaigns_exists": self.campaign_root_exists,
            },
            "counts": counts,
            "remaining_imports": [
                item.video_id
                for item in self.recordings
                if item.migration_state != "already_migrated"
            ],
            "recordings": [item.to_mapping() for item in self.recordings],
            "legacy_artifacts": [item.to_mapping() for item in self.artifacts],
            "shared_recordings": list(self.shared_recordings),
            "event_revisions": list(self.event_revisions),
            "maintained_references": list(self.maintained_references),
            "development_split": self.development_split,
            "holdout_registry": self.holdout_registry,
            "campaign_artifacts": list(self.campaign_artifacts),
            "discrepancies": [item.to_mapping() for item in self.discrepancies],
        }
        core["audit_digest"] = _sha256_json(core)
        return core


def audit_cardeventnet(
    repository_root: str | Path,
    *,
    legacy_root: str | Path | None = None,
    intake_root: str | Path | None = None,
    operations_root: str | Path | None = None,
    campaign_root: str | Path | None = None,
    holdout_registry: str | Path | None = None,
) -> CardEventNetInventory:
    """Build a read-only, deterministic CardEventNet legacy inventory."""

    repository = Path(repository_root).expanduser().resolve()
    if not repository.is_dir():
        raise CardEventNetInventoryError(f"repository root is not a directory: {repository}")
    legacy = _resolve(repository, legacy_root or Path("card_event_net/data"))
    intake = _resolve(repository, intake_root or Path("data/intake/recordings"))
    operations = _resolve(repository, operations_root or Path("data/operations"))
    campaigns = _resolve(repository, campaign_root or Path("data/model-campaigns"))
    holdout = _resolve(
        repository,
        holdout_registry or operations / "system-holdout-registry.json",
    )

    metadata, manifest_errors = _read_metadata(repository, legacy)
    artifacts, raw_by_id, annotation_by_id, review_by_id, split_memberships, discrepancies = (
        _inventory_legacy_files(
            repository,
            legacy,
            metadata=metadata,
        )
    )
    discrepancies.extend(manifest_errors)
    discrepancies.extend(
        _split_discrepancies(
            split_memberships,
            metadata_ids=set(metadata),
            artifact_by_path={item.path: item for item in artifacts},
        )
    )

    shared, shared_by_id, shared_discrepancies = _read_shared_recordings(
        repository, intake, operations
    )
    discrepancies.extend(shared_discrepancies)
    revisions, revisions_by_recording, revision_discrepancies = _read_event_revisions(
        repository, operations
    )
    discrepancies.extend(revision_discrepancies)
    references, references_by_recording, reference_discrepancies = _read_references(
        repository, operations
    )
    discrepancies.extend(reference_discrepancies)
    development_split, development_discrepancies = _read_development_split(repository, operations)
    discrepancies.extend(development_discrepancies)
    holdout_data, holdout_discrepancies = _read_holdout(repository, holdout)
    discrepancies.extend(holdout_discrepancies)
    campaign_artifacts, campaign_discrepancies = _read_campaign_artifacts(repository, campaigns)
    discrepancies.extend(campaign_discrepancies)

    video_ids = set(metadata) | set(raw_by_id) | set(annotation_by_id) | set(review_by_id)
    video_ids.update(split_memberships)
    video_ids.update(shared_by_id)
    recordings = tuple(
        _recording_audit(
            repository,
            video_id,
            metadata=metadata,
            raw=raw_by_id.get(video_id, ()),
            annotation=annotation_by_id.get(video_id),
            reviews=review_by_id.get(video_id, ()),
            split_memberships=split_memberships.get(video_id, ()),
            shared=shared_by_id.get(video_id, ()),
            revisions_by_recording=revisions_by_recording,
            references_by_recording=references_by_recording,
            development_split=development_split,
            holdout_data=holdout_data,
            discrepancies=discrepancies,
        )
        for video_id in sorted(video_ids)
    )
    discrepancies.extend(_recording_discrepancies(recordings))
    discrepancies = tuple(sorted(set(discrepancies), key=_discrepancy_key))
    return CardEventNetInventory(
        legacy_root=_relative(legacy, repository),
        shared_intake_root=_relative(intake, repository),
        operations_root=_relative(operations, repository),
        campaign_root=_relative(campaigns, repository),
        legacy_root_exists=legacy.exists(),
        shared_intake_exists=intake.exists(),
        operations_root_exists=operations.exists(),
        campaign_root_exists=campaigns.exists(),
        artifacts=tuple(sorted(artifacts, key=lambda item: item.path)),
        recordings=recordings,
        shared_recordings=tuple(sorted(shared, key=lambda item: str(item.get("path", "")))),
        event_revisions=tuple(sorted(revisions, key=lambda item: str(item.get("path", "")))),
        maintained_references=tuple(sorted(references, key=lambda item: str(item.get("path", "")))),
        development_split=development_split,
        holdout_registry=holdout_data,
        campaign_artifacts=tuple(
            sorted(campaign_artifacts, key=lambda item: str(item.get("path", "")))
        ),
        discrepancies=discrepancies,
    )


def build_cardevent_inventory(*args: Any, **kwargs: Any) -> CardEventNetInventory:
    """Compatibility-friendly name for callers that use the plan's inventory terminology."""

    return audit_cardeventnet(*args, **kwargs)


def render_cardevent_inventory_json(report: CardEventNetInventory) -> str:
    """Render canonical human-independent JSON."""

    return json.dumps(report.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_cardevent_inventory_human(report: CardEventNetInventory) -> str:
    """Render a concise operator report with actionable discrepancies."""

    data = report.to_mapping()
    counts = data["counts"]
    legacy_state = "present" if report.legacy_root_exists else "missing"
    lines = [
        "CardEventNet legacy inventory",
        f"legacy root: {report.legacy_root} ({legacy_state})",
        f"shared intake: {report.shared_intake_root} ({counts['shared_recordings']} recordings)",
        f"legacy source videos: {counts['raw_video_files']} "
        f"({counts['hydrated_source_videos']} hydrated, "
        f"{counts['lfs_pointer_videos']} LFS pointers)",
        f"annotations: {counts['annotation_files']} "
        f"({counts['annotation_valid']} valid, {counts['annotation_missing']} missing)",
        f"human review complete: {counts['human_review_complete']} / {counts['recordings']}",
        f"remaining imports: {len(data['remaining_imports'])}",
        f"legacy artifacts: {counts['legacy_artifacts']} across "
        f"{len(counts['legacy_by_kind'])} kinds",
        f"discrepancies: {len(report.discrepancies)}",
    ]
    if report.discrepancies:
        lines.append("discrepancy details:")
        for item in report.discrepancies:
            subject = item.video_id or item.path or "repository"
            lines.append(f"  - {item.kind}: {subject}: {item.message}")
    return "\n".join(lines) + "\n"


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (repository / path if not path.is_absolute() else path).resolve()


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.relative_to(repository).as_posix() or "."
    except ValueError:
        return path.as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, str(error)
    if not isinstance(value, dict):
        return None, "JSON document must contain an object"
    return value, None


def _normalise_video_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).stem


def _lfs_metadata(path: Path) -> tuple[str, int] | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw.startswith(LFS_POINTER_PREFIX):
        return None
    oid = LFS_OID.search(raw)
    size = LFS_SIZE.search(raw)
    if oid is None or size is None:
        return None
    return oid.group(1).decode("ascii"), int(size.group(1))


def _file_facts(
    path: Path,
) -> tuple[int | None, str | None, str | None, int | None, str, tuple[str, ...]]:
    errors: list[str] = []
    try:
        byte_length = path.stat().st_size
        digest = _sha256_file(path)
    except OSError as error:
        return None, None, None, None, "unreadable", (str(error),)
    lfs = _lfs_metadata(path)
    if lfs is not None:
        source_sha256, source_byte_length = lfs
        return byte_length, digest, source_sha256, source_byte_length, "lfs_pointer", ()
    return byte_length, digest, digest, byte_length, "materialized", tuple(errors)


def _read_metadata(
    repository: Path, legacy: Path
) -> tuple[dict[str, dict[str, Any]], list[Discrepancy]]:
    path = legacy / "dataset-manifest.v1.yaml"
    relative = _relative(path, repository)
    if not path.is_file():
        return {}, [
            Discrepancy(
                "legacy_manifest_missing",
                "dataset-manifest.v1.yaml is missing",
                path=relative,
                severity="error",
            )
        ]
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        return {}, [
            Discrepancy("legacy_manifest_invalid", str(error), path=relative, severity="error")
        ]
    if not isinstance(value, Mapping) or not isinstance(value.get("videos"), list):
        return {}, [
            Discrepancy(
                "legacy_manifest_invalid",
                "manifest must contain a videos list",
                path=relative,
                severity="error",
            )
        ]
    findings: list[Discrepancy] = []
    if value.get("schema_version") != "cardevent-video-metadata/v1":
        findings.append(
            Discrepancy(
                "legacy_manifest_schema_unsupported",
                "manifest schema_version is not cardevent-video-metadata/v1",
                path=relative,
                severity="error",
            )
        )
    metadata: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value["videos"]):
        if not isinstance(item, Mapping):
            findings.append(
                Discrepancy(
                    "legacy_manifest_item_invalid",
                    f"video entry {index} is not an object",
                    path=relative,
                    severity="error",
                )
            )
            continue
        video_id = item.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            findings.append(
                Discrepancy(
                    "legacy_manifest_item_invalid",
                    f"video entry {index} has no video_id",
                    path=relative,
                    severity="error",
                )
            )
            continue
        if video_id in metadata:
            findings.append(
                Discrepancy(
                    "duplicate_legacy_video_id",
                    f"video_id {video_id} occurs more than once",
                    video_id=video_id,
                    path=relative,
                    severity="error",
                )
            )
            continue
        metadata[video_id] = dict(item)
    return metadata, findings


def _inventory_legacy_files(
    repository: Path,
    legacy: Path,
    *,
    metadata: Mapping[str, Mapping[str, Any]],
) -> tuple[
    list[LegacyArtifact],
    dict[str, list[LegacyArtifact]],
    dict[str, LegacyArtifact],
    dict[str, list[str]],
    dict[str, list[str]],
    list[Discrepancy],
]:
    if not legacy.exists():
        return (
            [],
            {},
            {},
            {},
            {},
            [
                Discrepancy(
                    "legacy_root_missing",
                    "legacy root does not exist",
                    path=_relative(legacy, repository),
                    severity="error",
                )
            ],
        )
    files = sorted(
        (item for item in legacy.rglob("*") if item.is_file() or item.is_symlink()),
        key=lambda item: item.relative_to(legacy).as_posix(),
    )
    review_refs, review_discrepancies = _read_review_refs(repository, legacy, files)
    split_memberships, split_discrepancies = _read_split_memberships(repository, legacy, files)
    raw_by_id: dict[str, list[LegacyArtifact]] = defaultdict(list)
    annotation_by_id: dict[str, LegacyArtifact] = {}
    artifacts: list[LegacyArtifact] = []
    discrepancies = [*review_discrepancies, *split_discrepancies]
    for path in files:
        relative = path.relative_to(legacy).as_posix()
        kind, video_id = _kind_and_video_id(relative, metadata)
        byte_length, digest, source_digest, source_length, state, errors = _file_facts(path)
        membership = tuple(sorted(split_memberships.get(video_id or "", ())))
        destination, disposition, reason = _disposition(
            relative,
            kind=kind,
            video_id=video_id,
            metadata=metadata,
            path=path,
        )
        annotation_present = kind == "annotation"
        human_review_complete = False if annotation_present or kind == "review_artifact" else None
        artifact = LegacyArtifact(
            path=_relative(path, repository),
            kind=kind,
            byte_length=byte_length,
            sha256=digest,
            source_sha256=source_digest,
            source_byte_length=source_length,
            content_state=state,
            video_id=video_id,
            annotation_present=annotation_present if kind in {"raw_video", "annotation"} else None,
            human_review_complete=human_review_complete,
            split_memberships=membership,
            disposition=disposition,
            destination=destination,
            reason=reason,
            errors=errors,
        )
        artifacts.append(artifact)
        if kind == "raw_video" and video_id is not None:
            raw_by_id[video_id].append(artifact)
        if kind == "annotation" and video_id is not None:
            if video_id in annotation_by_id:
                discrepancies.append(
                    Discrepancy(
                        "duplicate_annotation",
                        "more than one annotation file maps to this video",
                        video_id=video_id,
                        path=artifact.path,
                        severity="error",
                    )
                )
            else:
                annotation_by_id[video_id] = artifact
        if kind == "other" and disposition == "manual_review_required":
            discrepancies.append(
                Discrepancy(
                    "unclassified_legacy_artifact",
                    "legacy path has no safe automatic disposition",
                    path=artifact.path,
                    severity="error",
                )
            )
    for video_id, raw_items in sorted(raw_by_id.items()):
        if len(raw_items) > 1:
            discrepancies.append(
                Discrepancy(
                    "duplicate_raw_video",
                    "more than one raw video maps to this video",
                    video_id=video_id,
                    severity="error",
                )
            )
    for video_id, annotation in sorted(annotation_by_id.items()):
        errors = _annotation_errors(
            _path_from_relative(repository, annotation.path), metadata.get(video_id)
        )
        if errors:
            discrepancies.extend(
                Discrepancy(
                    "annotation_invalid",
                    message,
                    video_id=video_id,
                    path=annotation.path,
                    severity="error",
                )
                for message in errors
            )
    return (
        artifacts,
        dict(raw_by_id),
        annotation_by_id,
        review_refs,
        split_memberships,
        discrepancies,
    )


def _path_from_relative(repository: Path, relative: str) -> Path:
    return repository / PurePosixPath(relative)


def _kind_and_video_id(
    relative: str, metadata: Mapping[str, Mapping[str, Any]]
) -> tuple[str, str | None]:
    del metadata
    path = PurePosixPath(relative)
    parts = path.parts
    name = path.name
    if parts and parts[0] == "raw" and path.suffix.lower() in VIDEO_EXTENSIONS:
        return "raw_video", _normalise_video_id(path.stem)
    if parts and parts[0] == "annotations" and path.suffix.lower() == ".json":
        return "annotation", _normalise_video_id(path.stem)
    if parts and parts[0] == "reviews":
        return "review_artifact", None
    if parts and parts[0] == "splits":
        return "split", None
    if name.startswith("dataset-manifest"):
        return "manifest", None
    if "cache" in parts:
        return "cache", None
    if "outputs" in parts:
        return "output", None
    return "other", None


def _disposition(
    relative: str,
    *,
    kind: str,
    video_id: str | None,
    metadata: Mapping[str, Mapping[str, Any]],
    path: Path,
) -> tuple[str | None, str, str]:
    recording = f"cardeventnet-{video_id}" if video_id else "<recording-id>"
    if kind == "raw_video":
        return (
            f"data/intake/recordings/{recording}/videos/video-{recording}{path.suffix.lower()}",
            "canonical_source",
            "import immutable source bytes into the shared recording bundle",
        )
    if kind == "manifest":
        if relative.endswith(".example.yaml") or relative.endswith(".example.yml"):
            return (
                None,
                "obsolete",
                "example metadata is not source evidence or an active authority",
            )
        return (
            "data/intake/recordings/<recording-id>/source-record.json",
            "canonical_metadata",
            "adapt source metadata into the shared source-record contract",
        )
    if kind == "annotation":
        return (
            f"data/operations/cardeventnet-imports/{recording}/annotation.json",
            "human_review_evidence",
            "preserve original annotation bytes and digest; do not certify review",
        )
    if kind == "review_artifact":
        return (
            f"data/operations/cardeventnet-imports/legacy/{relative}",
            "historical_evidence",
            "preserve legacy review evidence with its digest and provenance",
        )
    if kind == "split":
        return (
            f"data/operations/cardeventnet-imports/legacy/{relative}",
            "historical_evidence",
            "preserve legacy split membership as historical evidence; do not "
            "use as the active split",
        )
    if kind == "cache":
        return (
            f".runtime/cardevent/cache/{relative}",
            "derived_cache",
            "rebuild this derived cache from canonical inputs",
        )
    if kind == "output":
        return (
            f"data/operations/cardeventnet-imports/legacy/{relative}",
            "derived_output",
            "retain historical output for lineage; it is not a current campaign input",
        )
    if relative.endswith(".gitkeep"):
        return None, "obsolete", "repository placeholder has no data value"
    del metadata
    return None, "manual_review_required", "classify this legacy path before migration"


def _read_review_refs(
    repository: Path, legacy: Path, files: Sequence[Path]
) -> tuple[dict[str, list[str]], list[Discrepancy]]:
    refs: dict[str, list[str]] = defaultdict(list)
    discrepancies: list[Discrepancy] = []
    for path in files:
        relative = path.relative_to(legacy).as_posix()
        if not relative.startswith("reviews/") or path.suffix.lower() != ".json":
            continue
        payload, error = _safe_read_json(path)
        if error is not None:
            discrepancies.append(
                Discrepancy(
                    "review_artifact_invalid",
                    error,
                    path=_relative(path, repository),
                    severity="error",
                )
            )
            continue
        found = sorted(_video_values(payload))
        paths_for_video = _relative(path, repository)
        for video_id in found:
            refs[video_id].append(paths_for_video)
    return (
        {key: sorted(set(value)) for key, value in refs.items()},
        discrepancies,
    )


def _video_values(value: Any, key: str | None = None) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if child_key in {"video", "source_video", "video_id"}:
                normalised = _normalise_video_id(child)
                if normalised is not None:
                    result.add(normalised)
            result.update(_video_values(child, child_key))
    elif isinstance(value, list):
        for child in value:
            result.update(_video_values(child, key))
    return result


def _read_split_memberships(
    repository: Path, legacy: Path, files: Sequence[Path]
) -> tuple[dict[str, list[str]], list[Discrepancy]]:
    memberships: dict[str, list[str]] = defaultdict(list)
    discrepancies: list[Discrepancy] = []
    for path in files:
        relative = path.relative_to(legacy).as_posix()
        if not relative.startswith("splits/") or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            discrepancies.append(
                Discrepancy(
                    "split_invalid", str(error), path=_relative(path, repository), severity="error"
                )
            )
            continue
        if not isinstance(value, Mapping):
            discrepancies.append(
                Discrepancy(
                    "split_invalid",
                    "split must contain a mapping",
                    path=_relative(path, repository),
                    severity="error",
                )
            )
            continue
        for partition, raw_ids in value.items():
            if not isinstance(partition, str) or not isinstance(raw_ids, list):
                discrepancies.append(
                    Discrepancy(
                        "split_invalid",
                        "partition values must be lists",
                        path=_relative(path, repository),
                        severity="error",
                    )
                )
                continue
            for raw_id in raw_ids:
                video_id = _normalise_video_id(raw_id)
                if video_id is None:
                    discrepancies.append(
                        Discrepancy(
                            "split_item_invalid",
                            "split item is not a video identifier",
                            path=_relative(path, repository),
                            severity="error",
                        )
                    )
                    continue
                membership = f"{_relative(path, repository)}:{partition}"
                memberships[video_id].append(membership)
    return {key: sorted(set(value)) for key, value in memberships.items()}, discrepancies


def _split_discrepancies(
    memberships: Mapping[str, Sequence[str]],
    *,
    metadata_ids: set[str],
    artifact_by_path: Mapping[str, LegacyArtifact],
) -> list[Discrepancy]:
    del artifact_by_path
    return [
        Discrepancy(
            "split_references_unknown_video",
            "split references a video absent from the manifest",
            video_id=video_id,
            severity="error",
        )
        for video_id in sorted(set(memberships) - metadata_ids)
    ]


def _annotation_errors(path: Path, metadata: Mapping[str, Any] | None) -> list[str]:
    payload, error = _safe_read_json(path)
    if error is not None:
        return [error]
    assert payload is not None
    errors: list[str] = []
    if not isinstance(payload.get("schema_version"), str) and _normalise_video_id(
        payload.get("video")
    ) not in {"IMG_2780", "IMG_2781"}:
        errors.append("annotation schema_version is missing")
    if not isinstance(payload.get("events"), list):
        errors.append("annotation events must be a list")
    expected_video = metadata.get("file_name") if metadata else None
    actual_video = payload.get("video")
    if (
        expected_video is not None
        and Path(str(actual_video)).name != Path(str(expected_video)).name
    ):
        errors.append("annotation video does not match manifest file_name")
    if not errors:
        for index, event in enumerate(payload["events"]):
            if (
                not isinstance(event, Mapping)
                or not isinstance(event.get("time_s"), (int, float))
                or isinstance(event.get("time_s"), bool)
            ):
                errors.append(f"annotation event {index} has no numeric time_s")
                break
            if event.get("type") != "card_state_changed":
                errors.append("annotation contains a retired or unsupported event type")
                break
            duration_s = metadata.get("duration_s") if metadata else None
            if (
                isinstance(duration_s, (int, float))
                and not isinstance(duration_s, bool)
                and (event["time_s"] < 0 or event["time_s"] > duration_s)
            ):
                errors.append("annotation event time is outside the manifest duration")
                break
    return errors


def _read_shared_recordings(
    repository: Path, intake: Path, operations: Path
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[Discrepancy]]:
    if not intake.exists():
        return [], {}, []
    try:
        inspection = inspect_repository(
            repository,
            bundle_root=intake,
            evidence_package_root=operations / ".m0-no-evidence",
            pending_video_root=operations / ".m0-no-pending",
            artifacts_root=operations,
        )
    except (OSError, ValueError) as error:
        return (
            [],
            {},
            [
                Discrepancy(
                    "shared_intake_unreadable",
                    str(error),
                    path=_relative(intake, repository),
                    severity="error",
                )
            ],
        )
    by_path = {item.path: item for item in inspection.bundles}
    records: list[dict[str, Any]] = []
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    findings: list[Discrepancy] = []
    for path in discover_bundle_paths(intake):
        relative = _relative(path, repository)
        bundle = by_path.get(relative)
        source, source_error = _safe_read_json(path / "source-record.json")
        manifest, manifest_error = _safe_read_json(path / "manifest.json")
        source_id = source.get("source_asset_id") if source else None
        recording_id = source.get("recording_id") if source else None
        video_id = _shared_video_id(source, manifest)
        source_digest = _first_string(source, "sha256") or _first_string(manifest, "source_sha256")
        original_filename = _first_string(source, "original_filename")
        errors = list(bundle.errors if bundle is not None else ())
        if source_error is not None:
            errors.append(f"source-record.json: {source_error}")
        if manifest_error is not None:
            errors.append(f"manifest.json: {manifest_error}")
        state = bundle.state if bundle is not None else "invalid"
        record = {
            "path": relative,
            "state": state,
            "recording_id": recording_id,
            "source_asset_id": source_id,
            "video_id": video_id,
            "original_filename": original_filename,
            "source_sha256": source_digest,
            "source_permission": _first_string(source, "source_permission"),
            "session_id": _first_string(source, "session_id"),
            "game_id": _first_string(source, "game_id"),
            "source_lineage": _first_string(source, "source_lineage"),
            "table_setup": _first_string(source, "table_setup"),
            "errors": sorted(set(errors)),
        }
        records.append(record)
        if video_id is not None:
            by_id[video_id].append(record)
        if state != "complete":
            findings.append(
                Discrepancy(
                    "shared_bundle_invalid",
                    "shared recording bundle is not valid",
                    video_id=video_id,
                    path=relative,
                    severity="error",
                )
            )
    return records, dict(by_id), findings


def _shared_video_id(
    source: Mapping[str, Any] | None, manifest: Mapping[str, Any] | None
) -> str | None:
    candidates = (
        source.get("video_id") if source else None,
        source.get("original_filename") if source else None,
        manifest.get("video_id") if manifest else None,
        source.get("recording_id") if source else None,
    )
    for candidate in candidates:
        value = _normalise_video_id(candidate)
        if value is None:
            continue
        if value.startswith("video-"):
            value = value.removeprefix("video-")
        if value.startswith("cardeventnet-"):
            value = value.removeprefix("cardeventnet-")
        if value.startswith("source-"):
            value = value.removeprefix("source-")
        return value
    return None


def _first_string(value: Mapping[str, Any] | None, key: str) -> str | None:
    item = value.get(key) if value else None
    return item if isinstance(item, str) else None


def _read_event_revisions(
    repository: Path, operations: Path
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[Discrepancy]]:
    root = operations / "pipeline" / "revisions"
    revisions: list[dict[str, Any]] = []
    by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    findings: list[Discrepancy] = []
    if not root.exists():
        return revisions, {}, findings
    for manifest_path in sorted(root.rglob("manifest.json"), key=lambda item: item.as_posix()):
        payload, error = _safe_read_json(manifest_path)
        relative = _relative(manifest_path, repository)
        if error is not None:
            item = {"path": relative, "state": "invalid", "errors": [error]}
            revisions.append(item)
            findings.append(
                Discrepancy("event_revision_invalid", error, path=relative, severity="error")
            )
            continue
        assert payload is not None
        content_type = payload.get("content_type")
        recording_id = payload.get("recording_id")
        content_path = manifest_path.parent / "content.json"
        content_present = content_path.is_file()
        errors: list[str] = []
        if content_type == "events" and not content_present:
            errors.append("content.json is missing")
        item = {
            "path": relative,
            "state": ("valid" if not errors else "invalid")
            if content_type == "events"
            else "other",
            "revision_id": payload.get("revision_id"),
            "recording_id": recording_id,
            "content_type": content_type,
            "content_sha256": payload.get("content_sha256"),
            "origin": payload.get("origin"),
            "errors": sorted(set(errors)),
        }
        revisions.append(item)
        if content_type == "events" and isinstance(recording_id, str) and not errors:
            by_recording[recording_id].append(item)
        if errors:
            findings.append(
                Discrepancy(
                    "event_revision_invalid",
                    "; ".join(errors),
                    path=relative,
                    severity="error",
                )
            )
    return revisions, dict(by_recording), findings


def _read_references(
    repository: Path, operations: Path
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[Discrepancy]]:
    root = operations / "pipeline-references"
    references: list[dict[str, Any]] = []
    by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    findings: list[Discrepancy] = []
    if not root.exists():
        return references, {}, findings
    for state_path in sorted(root.rglob("state.json"), key=lambda item: item.as_posix()):
        payload, error = _safe_read_json(state_path)
        relative = _relative(state_path, repository)
        if error is not None:
            item = {"path": relative, "state": "invalid", "errors": [error]}
            references.append(item)
            findings.append(
                Discrepancy("maintained_reference_invalid", error, path=relative, severity="error")
            )
            continue
        assert payload is not None
        draft_path = state_path.parent / "draft.json"
        draft, draft_error = _safe_read_json(draft_path)
        recording_id = payload.get("recording_id")
        content_type = payload.get("content_type")
        errors: list[str] = []
        if draft_error is not None:
            errors.append(f"draft.json: {draft_error}")
        if draft is not None and (
            draft.get("recording_id") != recording_id
            or draft.get("content_type") != content_type
            or draft.get("revision") != payload.get("draft_revision")
        ):
            errors.append("state.json and draft.json disagree")
        completed = (
            not errors
            and payload.get("draft_state") == "completed"
            and isinstance(payload.get("selected_completed_revision_id"), str)
        )
        item = {
            "path": relative,
            "state": "completed" if completed else str(payload.get("draft_state", "invalid")),
            "recording_id": recording_id,
            "content_type": content_type,
            "draft_revision": payload.get("draft_revision"),
            "selected_completed_revision_id": payload.get("selected_completed_revision_id"),
            "errors": sorted(set(errors)),
        }
        references.append(item)
        if isinstance(recording_id, str):
            by_recording[recording_id].append(item)
        if content_type == "events" and not completed:
            findings.append(
                Discrepancy(
                    "maintained_event_reference_incomplete",
                    "event reference is not completed",
                    path=relative,
                    severity="warning",
                )
            )
    return references, dict(by_recording), findings


def _read_development_split(
    repository: Path, operations: Path
) -> tuple[dict[str, Any], list[Discrepancy]]:
    root = operations / "cardevent-development-split"
    active_path = root / "active.json"
    if not active_path.is_file():
        return {
            "state": "missing",
            "path": _relative(active_path, repository),
            "partitions": {},
        }, []
    active, error = _safe_read_json(active_path)
    if error is not None:
        return {
            "state": "invalid",
            "path": _relative(active_path, repository),
            "partitions": {},
            "errors": [error],
        }, [
            Discrepancy(
                "development_split_invalid",
                error,
                path=_relative(active_path, repository),
                severity="error",
            )
        ]
    assert active is not None
    version_id = active.get("split_version_id")
    version_path = root / "versions" / f"{version_id}.json" if isinstance(version_id, str) else None
    version, version_error = (
        _safe_read_json(version_path)
        if version_path is not None
        else (None, "active split has no split_version_id")
    )
    if version_error is not None:
        return {
            "state": "invalid",
            "path": _relative(active_path, repository),
            "version_id": version_id,
            "partitions": {},
            "errors": [version_error],
        }, [
            Discrepancy(
                "development_split_invalid",
                version_error,
                path=_relative(active_path, repository),
                severity="error",
            )
        ]
    assert version is not None
    partitions = {
        key: sorted(value)
        for key, value in version.items()
        if key in {"train", "validation", "test", "unassigned"}
        and isinstance(value, list)
        and all(isinstance(item, str) for item in value)
    }
    result = {
        "state": "valid",
        "path": _relative(active_path, repository),
        "version_path": _relative(version_path, repository),
        "split_version_id": version_id,
        "split_version_digest": active.get("split_version_digest"),
        "partitions": partitions,
    }
    return result, []


def _read_holdout(repository: Path, path: Path) -> tuple[dict[str, Any], list[Discrepancy]]:
    if not path.is_file():
        return {"state": "missing", "path": _relative(path, repository), "seals": []}, []
    payload, error = _safe_read_json(path)
    if error is not None:
        return {
            "state": "invalid",
            "path": _relative(path, repository),
            "seals": [],
            "errors": [error],
        }, [
            Discrepancy(
                "holdout_registry_invalid",
                error,
                path=_relative(path, repository),
                severity="error",
            )
        ]
    assert payload is not None
    try:
        validate_system_holdout_registry(payload)
    except ValueError as validation_error:
        message = str(validation_error)
        return {
            "state": "invalid",
            "path": _relative(path, repository),
            "seals": [],
            "errors": [message],
        }, [
            Discrepancy(
                "holdout_registry_invalid",
                message,
                path=_relative(path, repository),
                severity="error",
            )
        ]
    return {
        "state": "valid",
        "path": _relative(path, repository),
        "registry_version": payload.get("registry_version"),
        "registry_digest": payload.get("registry_digest"),
        "seals": [
            {
                "seal_id": item.get("seal_id"),
                "group_key": item.get("group_key"),
                "review_state": item.get("review_state"),
            }
            for item in payload.get("seals", [])
        ],
    }, []


def _read_campaign_artifacts(
    repository: Path, campaigns: Path
) -> tuple[list[dict[str, Any]], list[Discrepancy]]:
    if not campaigns.exists():
        return [], []
    artifacts: list[dict[str, Any]] = []
    findings: list[Discrepancy] = []
    for path in sorted(
        (item for item in campaigns.rglob("*") if item.is_file()), key=lambda item: item.as_posix()
    ):
        relative = _relative(path, repository)
        references = _legacy_references(path)
        item = {
            "path": relative,
            "campaign_id": path.parent.name if path.name != "campaign.json" else path.parent.name,
            "kind": path.name,
            "legacy_references": references,
        }
        artifacts.append(item)
        if references:
            findings.append(
                Discrepancy(
                    "campaign_legacy_path_reference",
                    ", ".join(references),
                    path=relative,
                    severity="warning",
                )
            )
    return artifacts, findings


def _legacy_references(path: Path) -> list[str]:
    if path.suffix.lower() in {".pt", ".mov", ".m4v", ".mp4", ".mlmodelc", ".mlpackage"}:
        return []
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if len(raw) > 4 * 1024 * 1024:
        return []
    text = raw.decode("utf-8", errors="ignore")
    return sorted(token for token in LEGACY_PATH_TOKENS if token in text)


def _recording_audit(
    repository: Path,
    video_id: str,
    *,
    metadata: Mapping[str, Mapping[str, Any]],
    raw: Sequence[LegacyArtifact],
    annotation: LegacyArtifact | None,
    reviews: Sequence[str],
    split_memberships: Sequence[str],
    shared: Sequence[Mapping[str, Any]],
    revisions_by_recording: Mapping[str, Sequence[Mapping[str, Any]]],
    references_by_recording: Mapping[str, Sequence[Mapping[str, Any]]],
    development_split: Mapping[str, Any],
    holdout_data: Mapping[str, Any],
    discrepancies: list[Discrepancy],
) -> RecordingAudit:
    manifest = metadata.get(video_id)
    raw_item = raw[0] if raw else None
    source_video = (
        str(manifest.get("file_name"))
        if manifest and isinstance(manifest.get("file_name"), str)
        else None
    )
    if source_video is None and raw_item is not None:
        source_video = Path(raw_item.path).name
    if annotation is not None:
        annotation_path = annotation.path
        annotation_sha256 = annotation.sha256
        annotation_payload, annotation_error = _safe_read_json(
            _path_from_relative(repository, annotation.path)
        )
        annotation_schema = annotation_payload.get("schema_version") if annotation_payload else None
        if annotation_payload and annotation_schema is None:
            annotation_schema = "cardevent-annotation/legacy-v1"
        annotation_event_count = (
            len(annotation_payload.get("events", []))
            if annotation_payload and isinstance(annotation_payload.get("events"), list)
            else None
        )
        annotation_valid = annotation_error is None and not _annotation_errors(
            _path_from_relative(repository, annotation.path), manifest
        )
    else:
        annotation_path = None
        annotation_sha256 = None
        annotation_schema = None
        annotation_event_count = None
        annotation_valid = None
    expected_source_digest = raw_item.source_sha256 if raw_item else None
    expected_recording_id = f"cardeventnet-{video_id}"
    matching_shared = (
        [
            item
            for item in shared
            if item.get("source_sha256") == expected_source_digest
            and item.get("state") == "complete"
        ]
        if expected_source_digest
        else []
    )
    selected_shared = matching_shared[0] if matching_shared else (shared[0] if shared else None)
    source_digest_match = (
        True if matching_shared else (False if shared and expected_source_digest else None)
    )
    recording_id = (
        selected_shared.get("recording_id")
        if selected_shared
        else (expected_recording_id if references_by_recording.get(expected_recording_id) else None)
    )
    event_revisions = tuple(
        sorted(
            str(item.get("revision_id"))
            for item in revisions_by_recording.get(recording_id or "", ())
            if isinstance(item.get("revision_id"), str) and item.get("content_type") == "events"
        )
    )
    references = [
        item
        for item in references_by_recording.get(recording_id or "", ())
        if item.get("content_type") == "events"
    ]
    completed_reference = next(
        (item for item in references if item.get("state") == "completed"), None
    )
    human_complete = completed_reference is not None and bool(event_revisions)
    partition_keys = {video_id}
    if recording_id is not None:
        partition_keys.add(recording_id)
    partitions = tuple(
        sorted(
            partition
            for partition, values in development_split.get("partitions", {}).items()
            if any(key in values for key in partition_keys)
        )
    )
    holdout_groups = tuple(sorted(_holdout_groups_for(selected_shared, holdout_data)))
    blockers: list[str] = []
    if raw_item is None:
        blockers.append("source recording is missing")
    elif raw_item.content_state == "lfs_pointer" and source_digest_match is not True:
        blockers.append("source file is an unhydrated Git LFS pointer")
    if manifest is None:
        blockers.append("source metadata is missing from dataset-manifest.v1.yaml")
    else:
        missing_metadata = [
            field
            for field in ("file_name", "duration_s", "session_id", "table_setup")
            if not manifest.get(field)
        ]
        if missing_metadata:
            blockers.append("source metadata is incomplete: " + ", ".join(missing_metadata))
        if manifest.get("source_permission") not in {
            "training_only",
            "training_and_evaluation",
            "project_use",
            "unrestricted",
        }:
            blockers.append("source permission is missing or invalid")
    if annotation is None:
        blockers.append("human event annotation is missing")
    elif annotation_valid is False:
        blockers.append("human event annotation is invalid")
    if shared and source_digest_match is False:
        blockers.append("shared recording has a conflicting source digest")
    if selected_shared and selected_shared.get("state") != "complete":
        blockers.append("shared recording bundle is invalid")
    if selected_shared and not event_revisions:
        blockers.append("shared recording has no events revision")
    if selected_shared and references and not human_complete:
        blockers.append("maintained event reference is not complete")
    split_files: dict[str, set[str]] = defaultdict(set)
    for membership in split_memberships:
        split_path, partition = membership.rsplit(":", 1)
        split_files[split_path].add(partition)
    if any(len(partitions) > 1 for partitions in split_files.values()):
        blockers.append("legacy split membership assigns the recording to multiple partitions")
    if human_complete:
        migration_state = "already_migrated"
        next_action = "no M0 action; retain the completed maintained event reference"
    elif source_digest_match is True:
        migration_state = "already_migrated_review_required"
        next_action = (
            f"complete full-recording event review for {video_id} in the recording workspace"
        )
    elif raw_item is None:
        migration_state = "source_missing"
        next_action = f"restore or collect the source recording for {video_id}"
    elif annotation is None:
        migration_state = "annotation_missing"
        next_action = f"review the complete recording {video_id} and create its event reference"
    elif annotation_valid is False:
        migration_state = "annotation_invalid"
        next_action = (
            f"inspect the preserved annotation for {video_id}, then complete full-recording review"
        )
    elif source_digest_match is False:
        migration_state = "source_digest_conflict"
        next_action = f"resolve the source-digest conflict for {video_id} before migration"
    else:
        migration_state = "ready_to_migrate"
        next_action = f"migrate {video_id} with its preserved annotation evidence"
    del discrepancies
    return RecordingAudit(
        video_id=video_id,
        source_video=source_video,
        raw_path=raw_item.path if raw_item else None,
        raw_content_state=raw_item.content_state if raw_item else None,
        source_sha256=expected_source_digest,
        source_byte_length=raw_item.source_byte_length if raw_item else None,
        metadata_present=manifest is not None,
        source_permission=str(manifest.get("source_permission"))
        if manifest and manifest.get("source_permission") is not None
        else None,
        annotation_path=annotation_path,
        annotation_present=annotation is not None,
        annotation_valid=annotation_valid,
        annotation_sha256=annotation_sha256,
        annotation_schema=annotation_schema if isinstance(annotation_schema, str) else None,
        annotation_event_count=annotation_event_count,
        legacy_review_artifact_paths=tuple(sorted(set(reviews))),
        human_review_complete=human_complete,
        human_review_basis=("maintained_reference" if human_complete else None),
        shared_recording_id=recording_id,
        shared_bundle_state=selected_shared.get("state") if selected_shared else None,
        shared_source_sha256=selected_shared.get("source_sha256") if selected_shared else None,
        source_digest_match=source_digest_match,
        event_revision_ids=event_revisions,
        maintained_reference_state=completed_reference.get("state")
        if completed_reference
        else (references[0].get("state") if references else None),
        maintained_reference_revision_id=completed_reference.get("selected_completed_revision_id")
        if completed_reference
        else None,
        development_partitions=partitions,
        holdout_groups=holdout_groups,
        migration_state=migration_state,
        blockers=tuple(sorted(set(blockers))),
        next_action=next_action,
    )


def _holdout_groups_for(shared: Mapping[str, Any] | None, holdout: Mapping[str, Any]) -> set[str]:
    if not shared or not isinstance(holdout.get("seals"), list):
        return set()
    result: set[str] = set()
    for seal in holdout["seals"]:
        if not isinstance(seal, Mapping) or not isinstance(seal.get("group_key"), Mapping):
            continue
        group = seal["group_key"]
        name, value = group.get("name"), group.get("value")
        if isinstance(name, str) and isinstance(value, str) and shared.get(name) == value:
            result.add(f"{name}:{value}")
    return result


def _recording_discrepancies(recordings: Sequence[RecordingAudit]) -> list[Discrepancy]:
    findings: list[Discrepancy] = []
    for item in recordings:
        if item.shared_recording_id is None:
            findings.append(
                Discrepancy(
                    "shared_recording_missing",
                    "no shared recording bundle matches this legacy source",
                    video_id=item.video_id,
                    severity="warning",
                )
            )
        if not item.event_revision_ids and item.shared_recording_id is not None:
            findings.append(
                Discrepancy(
                    "event_revision_missing",
                    "shared recording has no CardEventNet events revision",
                    video_id=item.video_id,
                    severity="warning",
                )
            )
    return findings


def _counts(report: CardEventNetInventory) -> dict[str, Any]:
    by_kind = Counter(item.kind for item in report.artifacts)
    raw = [item for item in report.artifacts if item.kind == "raw_video"]
    annotations = [item for item in report.artifacts if item.kind == "annotation"]
    valid_annotation_ids = {
        record.video_id for record in report.recordings if record.annotation_valid is True
    }
    return {
        "recordings": len(report.recordings),
        "legacy_artifacts": len(report.artifacts),
        "legacy_by_kind": dict(sorted(by_kind.items())),
        "raw_video_files": len(raw),
        "hydrated_source_videos": sum(item.content_state == "materialized" for item in raw),
        "lfs_pointer_videos": sum(item.content_state == "lfs_pointer" for item in raw),
        "annotation_files": len(annotations),
        "annotation_valid": sum(item.video_id in valid_annotation_ids for item in annotations),
        "annotation_missing": sum(not record.annotation_present for record in report.recordings),
        "human_review_complete": sum(record.human_review_complete for record in report.recordings),
        "shared_recordings": len(report.shared_recordings),
        "event_revisions": len(
            [item for item in report.event_revisions if item.get("content_type") == "events"]
        ),
        "maintained_references": len(
            [item for item in report.maintained_references if item.get("content_type") == "events"]
        ),
        "campaign_artifacts": len(report.campaign_artifacts),
        "discrepancies": len(report.discrepancies),
    }


def _discrepancy_key(item: Discrepancy) -> tuple[str, str, str, str, str]:
    return (item.kind, item.video_id or "", item.path or "", item.severity, item.message)


__all__ = [
    "CARD_EVENTNET_INVENTORY_SCHEMA_VERSION",
    "CardEventNetInventory",
    "CardEventNetInventoryError",
    "Discrepancy",
    "LegacyArtifact",
    "RecordingAudit",
    "audit_cardeventnet",
    "build_cardevent_inventory",
    "render_cardevent_inventory_human",
    "render_cardevent_inventory_json",
]
