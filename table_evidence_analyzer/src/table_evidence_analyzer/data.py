"""Offline dataset, frame-artifact, and deterministic crop contracts.

The dataset and split JSON consumed here are the ``dataset-version/v1`` and
``table-dataset-split/v1`` artifacts produced by plan 0020.  This module does
not assemble datasets or choose split members.  It verifies those frozen
artifacts and adds the analyzer-specific mapping from a source frame ID to
immutable bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .cards import CARD_IDENTITIES, CARD_SET_ID

DATASET_VERSION_SCHEMA = "dataset-version/v1"
SPLIT_VERSION_SCHEMA = "table-dataset-split/v1"
ARTIFACT_INDEX_SCHEMA = "sample-artifact-index/v1"
CROP_CACHE_SCHEMA = "crop-cache/v1"
TARGET_SCHEMA = "table-observation-annotation/v1"
DEFAULT_TRANSFORM_VERSION = "identity-crop-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class DataContractError(ValueError):
    """Raised when a frozen dataset or derived artifact is unsafe to use."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise DataContractError(f"{field} must be a non-empty identifier.")
    if "/" in value or "\\" in value:
        raise DataContractError(f"{field} must not be a local path.")
    return value


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DataContractError(f"{field} must be a lower-case SHA-256 digest.")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DataContractError(f"{field} must be a non-empty string.")
    return value


def _required_fields(data: Mapping[str, Any], fields: set[str], context: str) -> None:
    unknown = set(data) - fields
    missing = fields - set(data)
    if unknown or missing:
        detail: list[str] = []
        if missing:
            detail.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            detail.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise DataContractError(f"{context} has invalid fields ({'; '.join(detail)}).")


def _sorted_unique_strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise DataContractError(f"{field} must be a list of non-empty strings.")
    if len(value) != len(set(value)):
        raise DataContractError(f"{field} must not contain duplicate values.")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class Eligibility:
    source_asset_id: str
    state: str
    source_permission: str
    allowed_uses: tuple[str, ...]
    review_state: str
    annotation_set_id: str | None
    review_id: str | None
    intended_use: str | None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Eligibility":
        fields = {
            "schema_version",
            "source_asset_id",
            "state",
            "source_permission",
            "allowed_uses",
            "review_state",
            "annotation_set_id",
            "review_id",
            "intended_use",
            "reason",
        }
        if not isinstance(data, Mapping):
            raise DataContractError("eligibility must be a mapping.")
        _required_fields(data, fields, "eligibility")
        if data["schema_version"] != "eligibility/v1":
            raise DataContractError(f"Unsupported eligibility schema: {data['schema_version']}.")
        allowed = _sorted_unique_strings(data["allowed_uses"], "allowed_uses")
        if any(use not in {"train", "validation", "test", "evaluation"} for use in allowed):
            raise DataContractError("allowed_uses contains an unknown intended use.")
        source_asset_id = _require_id(data["source_asset_id"], "source_asset_id")
        annotation_id = data["annotation_set_id"]
        review_id = data["review_id"]
        if annotation_id is not None:
            annotation_id = _require_id(annotation_id, "annotation_set_id")
        if review_id is not None:
            review_id = _require_id(review_id, "review_id")
        if data["state"] == "eligible" and (
            data["review_state"] != "reviewed"
            or annotation_id is None
            or review_id is None
            or data["intended_use"] not in allowed
        ):
            raise DataContractError("eligible data must be reviewed with an allowed intended_use.")
        if data["intended_use"] is not None and data["intended_use"] not in {
            "train",
            "validation",
            "test",
            "evaluation",
        }:
            raise DataContractError("eligibility intended_use is unknown.")
        return cls(
            source_asset_id=source_asset_id,
            state=_require_text(data["state"], "state"),
            source_permission=_require_text(data["source_permission"], "source_permission"),
            allowed_uses=allowed,
            review_state=_require_text(data["review_state"], "review_state"),
            annotation_set_id=annotation_id,
            review_id=review_id,
            intended_use=data["intended_use"],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": "eligibility/v1",
            "source_asset_id": self.source_asset_id,
            "state": self.state,
            "source_permission": self.source_permission,
            "allowed_uses": list(self.allowed_uses),
            "review_state": self.review_state,
            "annotation_set_id": self.annotation_set_id,
            "review_id": self.review_id,
            "intended_use": self.intended_use,
            "reason": None,
        }


@dataclass(frozen=True, slots=True)
class DatasetEntry:
    dataset_item_id: str
    source_asset_id: str
    source_sha256: str
    annotation_set_id: str
    review_id: str
    eligibility: Eligibility
    target_schema: str
    group_keys: tuple[tuple[str, str], ...]
    inclusion_reason: str
    transform_version: str
    source_frame_id: str | None
    observed_card_id: str | None
    bbox: tuple[int, int, int, int] | None
    visual_card_identity: str | None
    quality_tags: tuple[str, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DatasetEntry":
        fields = {
            "dataset_item_id",
            "source_asset_id",
            "source_sha256",
            "annotation_set_id",
            "review_id",
            "eligibility",
            "target_schema",
            "group_keys",
            "inclusion_reason",
            "transform_version",
            "source_frame_id",
            "observed_card_id",
            "bbox",
            "visual_card_identity",
            "quality_tags",
        }
        if not isinstance(data, Mapping):
            raise DataContractError("dataset entry must be a mapping.")
        if not set(data) <= fields or not {
            "dataset_item_id",
            "source_asset_id",
            "source_sha256",
            "annotation_set_id",
            "review_id",
            "eligibility",
            "target_schema",
            "group_keys",
            "inclusion_reason",
            "transform_version",
        } <= set(data):
            raise DataContractError("dataset entry has invalid fields.")
        raw_groups = data["group_keys"]
        if not isinstance(raw_groups, list):
            raise DataContractError("group_keys must be a list of [name, value] pairs.")
        groups: list[tuple[str, str]] = []
        for pair in raw_groups:
            if not isinstance(pair, list) or len(pair) != 2:
                raise DataContractError("each group key must be a [name, value] pair.")
            groups.append((_require_id(pair[0], "group key name"), _require_id(pair[1], "group key value")))
        if len({name for name, _ in groups}) != len(groups):
            raise DataContractError("dataset entry group keys must be unique.")
        raw_bbox = data.get("bbox")
        bbox: tuple[int, int, int, int] | None = None
        if raw_bbox is not None:
            if (
                not isinstance(raw_bbox, list)
                or len(raw_bbox) != 4
                or any(isinstance(item, bool) or not isinstance(item, int) for item in raw_bbox)
            ):
                raise DataContractError("bbox must be null or a four-item integer list.")
            bbox = tuple(raw_bbox)  # type: ignore[assignment]
        quality = _sorted_unique_strings(data.get("quality_tags", []), "quality_tags")
        source_frame_id = data.get("source_frame_id")
        observed_card_id = data.get("observed_card_id")
        identity = data.get("visual_card_identity")
        for value, field in (
            (source_frame_id, "source_frame_id"),
            (observed_card_id, "observed_card_id"),
            (identity, "visual_card_identity"),
        ):
            if value is not None:
                _require_id(value, field)
        if any(value is not None for value in (source_frame_id, observed_card_id, bbox, identity)) and not all(
            value is not None for value in (source_frame_id, observed_card_id, bbox, identity)
        ):
            raise DataContractError("a dataset sample reference needs frame, card, bbox, and identity.")
        if bbox is not None and (bbox[0] < 0 or bbox[1] < 0 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]):
            raise DataContractError("bbox must be a positive rectangle.")
        return cls(
            dataset_item_id=_require_id(data["dataset_item_id"], "dataset_item_id"),
            source_asset_id=_require_id(data["source_asset_id"], "source_asset_id"),
            source_sha256=_require_digest(data["source_sha256"], "source_sha256"),
            annotation_set_id=_require_id(data["annotation_set_id"], "annotation_set_id"),
            review_id=_require_id(data["review_id"], "review_id"),
            eligibility=Eligibility.from_mapping(data["eligibility"]),
            target_schema=_require_text(data["target_schema"], "target_schema"),
            group_keys=tuple(groups),
            inclusion_reason=_require_text(data["inclusion_reason"], "inclusion_reason"),
            transform_version=_require_text(data["transform_version"], "transform_version"),
            source_frame_id=source_frame_id,
            observed_card_id=observed_card_id,
            bbox=bbox,
            visual_card_identity=identity,
            quality_tags=quality,
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "dataset_item_id": self.dataset_item_id,
            "source_asset_id": self.source_asset_id,
            "source_sha256": self.source_sha256,
            "annotation_set_id": self.annotation_set_id,
            "review_id": self.review_id,
            "eligibility": self.eligibility.to_mapping(),
            "target_schema": self.target_schema,
            "group_keys": [list(pair) for pair in self.group_keys],
            "inclusion_reason": self.inclusion_reason,
            "transform_version": self.transform_version,
        }
        if self.source_frame_id is not None:
            result.update(
                {
                    "source_frame_id": self.source_frame_id,
                    "observed_card_id": self.observed_card_id,
                    "bbox": list(self.bbox) if self.bbox is not None else None,
                    "visual_card_identity": self.visual_card_identity,
                    "quality_tags": list(self.quality_tags),
                }
            )
        return result


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_version_id: str
    task: str
    target_schema: str
    entries: tuple[DatasetEntry, ...]
    allowed_use_filter: tuple[str, ...]
    group_key_names: tuple[str, ...]
    derived_artifact_transform_version: str
    creation_code_revision: str
    dirty_state: bool
    deck_design_version: str | None
    card_set_version: str | None
    created_at: str | None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DatasetManifest":
        fields = {
            "schema_version",
            "dataset_version_id",
            "task",
            "target_schema",
            "entries",
            "allowed_use_filter",
            "group_key_names",
            "derived_artifact_transform_version",
            "creation_code_revision",
            "dirty_state",
            "deck_design_version",
            "card_set_version",
            "created_at",
            "dataset_version_digest",
        }
        if not isinstance(data, Mapping):
            raise DataContractError("dataset version must be a mapping.")
        _required_fields(data, fields, "dataset version")
        if data["schema_version"] != DATASET_VERSION_SCHEMA:
            raise DataContractError(f"Unsupported dataset schema: {data['schema_version']}.")
        if not isinstance(data["entries"], list) or not data["entries"]:
            raise DataContractError("dataset version entries must be a non-empty list.")
        entries = tuple(DatasetEntry.from_mapping(entry) for entry in data["entries"])
        item_ids = [entry.dataset_item_id for entry in entries]
        if len(item_ids) != len(set(item_ids)):
            raise DataContractError("dataset entry IDs must be unique.")
        group_names = _sorted_unique_strings(data["group_key_names"], "group_key_names")
        allowed = _sorted_unique_strings(data["allowed_use_filter"], "allowed_use_filter")
        if any(use not in {"train", "validation", "test", "evaluation"} for use in allowed):
            raise DataContractError("allowed_use_filter contains an unknown intended use.")
        if set(name for entry in entries for name, _ in entry.group_keys) != set(group_names):
            raise DataContractError("group_key_names must declare the group keys used by entries.")
        version = cls(
            dataset_version_id=_require_id(data["dataset_version_id"], "dataset_version_id"),
            task=_require_text(data["task"], "task"),
            target_schema=_require_text(data["target_schema"], "target_schema"),
            entries=entries,
            allowed_use_filter=allowed,
            group_key_names=group_names,
            derived_artifact_transform_version=_require_text(
                data["derived_artifact_transform_version"], "derived_artifact_transform_version"
            ),
            creation_code_revision=_require_text(data["creation_code_revision"], "creation_code_revision"),
            dirty_state=data["dirty_state"],
            deck_design_version=data["deck_design_version"],
            card_set_version=data["card_set_version"],
            created_at=data["created_at"],
        )
        if not isinstance(version.dirty_state, bool):
            raise DataContractError("dirty_state must be a boolean.")
        if version.digest != _require_digest(data["dataset_version_digest"], "dataset_version_digest"):
            raise DataContractError("dataset_version_digest does not match the dataset contents.")
        return version

    def _digest_mapping(self) -> dict[str, Any]:
        entries = []
        for entry in sorted(self.entries, key=lambda item: item.dataset_item_id):
            mapping = entry.to_mapping()
            mapping["group_keys"] = sorted(mapping["group_keys"])
            mapping["eligibility"]["allowed_uses"] = sorted(mapping["eligibility"]["allowed_uses"])
            entries.append(mapping)
        return {
            "schema_version": DATASET_VERSION_SCHEMA,
            "task": self.task,
            "target_schema": self.target_schema,
            "entries": entries,
            "allowed_use_filter": sorted(self.allowed_use_filter),
            "group_key_names": sorted(self.group_key_names),
            "derived_artifact_transform_version": self.derived_artifact_transform_version,
            "creation_code_revision": self.creation_code_revision,
            "dirty_state": self.dirty_state,
            "deck_design_version": self.deck_design_version,
            "card_set_version": self.card_set_version,
        }

    @property
    def digest(self) -> str:
        return _sha256(_canonical(self._digest_mapping()).encode())


@dataclass(frozen=True, slots=True)
class SplitManifest:
    split_version_id: str
    dataset_version_id: str
    dataset_version_digest: str
    group_key_names: tuple[str, ...]
    seed: int
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]
    unassigned: tuple[str, ...]

    @property
    def partitions(self) -> dict[str, tuple[str, ...]]:
        return {
            "train": self.train,
            "validation": self.validation,
            "test": self.test,
            "unassigned": self.unassigned,
        }

    @property
    def digest(self) -> str:
        payload = {
            "schema_version": SPLIT_VERSION_SCHEMA,
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "group_key_names": sorted(self.group_key_names),
            "seed": self.seed,
            "train": sorted(self.train),
            "validation": sorted(self.validation),
            "test": sorted(self.test),
            "unassigned": sorted(self.unassigned),
        }
        return _sha256(_canonical(payload).encode())

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SplitManifest":
        fields = {
            "schema_version",
            "split_version_id",
            "dataset_version_id",
            "dataset_version_digest",
            "group_key_names",
            "seed",
            "train",
            "validation",
            "test",
            "unassigned",
            "split_version_digest",
        }
        if not isinstance(data, Mapping):
            raise DataContractError("dataset split must be a mapping.")
        _required_fields(data, fields, "dataset split")
        if data["schema_version"] != SPLIT_VERSION_SCHEMA:
            raise DataContractError(f"Unsupported dataset split schema: {data['schema_version']}.")
        partitions: dict[str, tuple[str, ...]] = {}
        for name in ("train", "validation", "test", "unassigned"):
            partitions[name] = _sorted_unique_strings(data[name], name)
        all_ids = sum((list(values) for values in partitions.values()), [])
        if len(all_ids) != len(set(all_ids)):
            raise DataContractError("dataset split item IDs must be unique across partitions.")
        seed = data["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise DataContractError("dataset split seed must be an integer.")
        manifest = cls(
            split_version_id=_require_id(data["split_version_id"], "split_version_id"),
            dataset_version_id=_require_id(data["dataset_version_id"], "dataset_version_id"),
            dataset_version_digest=_require_digest(data["dataset_version_digest"], "dataset_version_digest"),
            group_key_names=_sorted_unique_strings(data["group_key_names"], "group_key_names"),
            seed=seed,
            **partitions,
        )
        if manifest.digest != _require_digest(data["split_version_digest"], "split_version_digest"):
            raise DataContractError("split_version_digest does not match the split contents.")
        return manifest

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": SPLIT_VERSION_SCHEMA,
            "split_version_id": self.split_version_id,
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "group_key_names": list(self.group_key_names),
            "seed": self.seed,
            "train": list(self.train),
            "validation": list(self.validation),
            "test": list(self.test),
            "unassigned": list(self.unassigned),
            "split_version_digest": self.digest,
        }

    def validate_against(self, dataset: DatasetManifest) -> None:
        if self.dataset_version_id != dataset.dataset_version_id:
            raise DataContractError("dataset split references a different dataset version ID.")
        if self.dataset_version_digest != dataset.digest:
            raise DataContractError("dataset split references a different dataset digest.")
        if set(self.group_key_names) != set(dataset.group_key_names):
            raise DataContractError("dataset split group keys do not match the dataset version.")
        expected = {entry.dataset_item_id for entry in dataset.entries}
        actual = {item for values in self.partitions.values() for item in values}
        if expected != actual:
            raise DataContractError("dataset split item mismatch.")
        item_partition = {
            item: partition for partition, items in self.partitions.items() for item in items
        }
        group_partitions: dict[tuple[str, str], str] = {}
        for entry in dataset.entries:
            partition = item_partition[entry.dataset_item_id]
            for group in entry.group_keys:
                previous = group_partitions.get(group)
                if previous is not None and previous != partition:
                    raise DataContractError(
                        "a session, game, table setup, or source lineage group crosses dataset partitions."
                    )
                group_partitions[group] = partition


@dataclass(frozen=True, slots=True)
class ResolvedFrame:
    source_asset_id: str
    source_frame_id: str
    bytes: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    source_asset_id: str
    source_frame_id: str
    relative_path: str
    media_type: str
    byte_length: int
    sha256: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ArtifactRecord":
        fields = {
            "source_asset_id",
            "source_frame_id",
            "relative_path",
            "media_type",
            "byte_length",
            "sha256",
        }
        if not isinstance(data, Mapping):
            raise DataContractError("artifact entry must be a mapping.")
        _required_fields(data, fields, "artifact entry")
        relative = data["relative_path"]
        if not isinstance(relative, str) or not relative or PurePosixPath(relative).is_absolute():
            raise DataContractError("artifact relative_path must be a relative path.")
        if any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts):
            raise DataContractError("artifact relative_path must not escape the artifact root.")
        length = data["byte_length"]
        if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
            raise DataContractError("artifact byte_length must be a positive integer.")
        return cls(
            source_asset_id=_require_id(data["source_asset_id"], "source_asset_id"),
            source_frame_id=_require_id(data["source_frame_id"], "source_frame_id"),
            relative_path=relative,
            media_type=_require_text(data["media_type"], "media_type"),
            byte_length=length,
            sha256=_require_digest(data["sha256"], "artifact sha256"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactIndex:
    artifact_index_id: str
    dataset_version_id: str
    dataset_version_digest: str
    artifacts: tuple[ArtifactRecord, ...]
    root: Path | None = None

    @property
    def digest(self) -> str:
        payload = {
            "schema_version": ARTIFACT_INDEX_SCHEMA,
            "artifact_index_id": self.artifact_index_id,
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "artifacts": [
                {
                    "source_asset_id": artifact.source_asset_id,
                    "source_frame_id": artifact.source_frame_id,
                    "relative_path": artifact.relative_path,
                    "media_type": artifact.media_type,
                    "byte_length": artifact.byte_length,
                    "sha256": artifact.sha256,
                }
                for artifact in sorted(self.artifacts, key=lambda item: item.source_frame_id)
            ],
        }
        return _sha256(_canonical(payload).encode())

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, root: Path | None = None) -> "ArtifactIndex":
        fields = {
            "schema_version",
            "artifact_index_id",
            "dataset_version_id",
            "dataset_version_digest",
            "artifacts",
            "artifact_index_digest",
        }
        if not isinstance(data, Mapping):
            raise DataContractError("artifact index must be a mapping.")
        _required_fields(data, fields, "artifact index")
        if data["schema_version"] != ARTIFACT_INDEX_SCHEMA:
            raise DataContractError(f"Unsupported artifact index schema: {data['schema_version']}.")
        raw = data["artifacts"]
        if not isinstance(raw, list) or not raw:
            raise DataContractError("artifact index artifacts must be a non-empty list.")
        artifacts = tuple(ArtifactRecord.from_mapping(item) for item in raw)
        frame_ids = [item.source_frame_id for item in artifacts]
        if len(frame_ids) != len(set(frame_ids)):
            raise DataContractError("artifact index source_frame_id values must be unique.")
        index = cls(
            artifact_index_id=_require_id(data["artifact_index_id"], "artifact_index_id"),
            dataset_version_id=_require_id(data["dataset_version_id"], "dataset_version_id"),
            dataset_version_digest=_require_digest(data["dataset_version_digest"], "dataset_version_digest"),
            artifacts=artifacts,
            root=root,
        )
        if index.digest != _require_digest(data["artifact_index_digest"], "artifact_index_digest"):
            raise DataContractError("artifact_index_digest does not match the index contents.")
        return index

    def resolve(
        self,
        source_frame_id: str,
        *,
        source_asset_id: str | None = None,
        root: Path | None = None,
    ) -> ResolvedFrame:
        matches = [item for item in self.artifacts if item.source_frame_id == source_frame_id]
        if not matches:
            raise DataContractError(f"No artifact index entry for source frame {source_frame_id}.")
        artifact = matches[0]
        if source_asset_id is not None and artifact.source_asset_id != source_asset_id:
            raise DataContractError(f"Source frame {source_frame_id} has a different source asset.")
        artifact_root = root or self.root
        if artifact_root is None:
            raise DataContractError("An artifact root is required to resolve frame bytes.")
        path = (artifact_root / artifact.relative_path).resolve()
        resolved_root = artifact_root.resolve()
        if resolved_root not in path.parents:
            raise DataContractError(f"Artifact path escapes the artifact root: {artifact.relative_path}")
        try:
            value = path.read_bytes()
        except OSError as exc:
            raise DataContractError(f"Could not read source frame artifact {source_frame_id}.") from exc
        if len(value) != artifact.byte_length or _sha256(value) != artifact.sha256:
            raise DataContractError(f"Source frame {source_frame_id} does not match its digest.")
        return ResolvedFrame(artifact.source_asset_id, source_frame_id, value, artifact.sha256)


@dataclass(frozen=True, slots=True)
class CropArtifact:
    dataset_item_id: str
    source_asset_id: str
    source_frame_id: str
    source_frame_sha256: str
    annotation_set_id: str
    review_id: str
    observed_card_id: str
    visual_card_identity: str
    bbox: tuple[int, int, int, int]
    transform_version: str
    relative_path: str
    byte_length: int
    sha256: str
    partition: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "dataset_item_id": self.dataset_item_id,
            "source_asset_id": self.source_asset_id,
            "source_frame_id": self.source_frame_id,
            "source_frame_sha256": self.source_frame_sha256,
            "annotation_set_id": self.annotation_set_id,
            "review_id": self.review_id,
            "observed_card_id": self.observed_card_id,
            "visual_card_identity": self.visual_card_identity,
            "bbox": list(self.bbox),
            "transform_version": self.transform_version,
            "relative_path": self.relative_path,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "partition": self.partition,
            "lineage": {
                "source_asset_id": self.source_asset_id,
                "source_frame_id": self.source_frame_id,
                "annotation_set_id": self.annotation_set_id,
                "review_id": self.review_id,
                "transform_version": self.transform_version,
            },
        }


@dataclass(frozen=True, slots=True)
class CropCache:
    dataset_version_id: str
    dataset_version_digest: str
    split_version_id: str
    split_version_digest: str
    transform_version: str
    crops: tuple[CropArtifact, ...]
    root: Path | None = None

    @property
    def digest(self) -> str:
        payload = {
            "schema_version": CROP_CACHE_SCHEMA,
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "split_version_id": self.split_version_id,
            "split_version_digest": self.split_version_digest,
            "transform_version": self.transform_version,
            "crops": [crop.to_mapping() for crop in sorted(self.crops, key=lambda item: item.dataset_item_id)],
        }
        return _sha256(_canonical(payload).encode())

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, root: Path | None = None) -> "CropCache":
        fields = {
            "schema_version",
            "dataset_version_id",
            "dataset_version_digest",
            "split_version_id",
            "split_version_digest",
            "transform_version",
            "crops",
            "cache_digest",
        }
        if not isinstance(data, Mapping):
            raise DataContractError("crop cache must be a mapping.")
        _required_fields(data, fields, "crop cache")
        if data["schema_version"] != CROP_CACHE_SCHEMA:
            raise DataContractError(f"Unsupported crop cache schema: {data['schema_version']}.")
        if not isinstance(data["crops"], list) or not data["crops"]:
            raise DataContractError("crop cache crops must be a non-empty list.")
        crops: list[CropArtifact] = []
        for raw in data["crops"]:
            if not isinstance(raw, Mapping):
                raise DataContractError("crop cache entries must be mappings.")
            _required_fields(
                raw,
                {
                    "dataset_item_id",
                    "source_asset_id",
                    "source_frame_id",
                    "source_frame_sha256",
                    "annotation_set_id",
                    "review_id",
                    "observed_card_id",
                    "visual_card_identity",
                    "bbox",
                    "transform_version",
                    "relative_path",
                    "byte_length",
                    "sha256",
                    "partition",
                    "lineage",
                },
                "crop cache entry",
            )
            lineage = raw.get("lineage")
            if not isinstance(lineage, Mapping):
                raise DataContractError("crop cache entries must contain complete lineage.")
            expected_lineage = {
                "source_asset_id": raw.get("source_asset_id"),
                "source_frame_id": raw.get("source_frame_id"),
                "annotation_set_id": raw.get("annotation_set_id"),
                "review_id": raw.get("review_id"),
                "transform_version": raw.get("transform_version"),
            }
            if dict(lineage) != expected_lineage:
                raise DataContractError("crop cache entry has incomplete or changed lineage.")
            bbox = raw.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4 or any(not isinstance(item, int) for item in bbox):
                raise DataContractError("crop cache bbox is invalid.")
            relative = raw.get("relative_path")
            if (
                not isinstance(relative, str)
                or "\\" in relative
                or PurePosixPath(relative).is_absolute()
                or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
            ):
                raise DataContractError("crop cache relative_path is invalid.")
            byte_length = raw.get("byte_length")
            if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length <= 0:
                raise DataContractError("crop cache byte_length must be a positive integer.")
            partition = raw.get("partition")
            if partition not in {"train", "validation", "test", "unassigned"}:
                raise DataContractError("crop cache partition is invalid.")
            crops.append(
                CropArtifact(
                    dataset_item_id=_require_id(raw.get("dataset_item_id"), "dataset_item_id"),
                    source_asset_id=_require_id(raw.get("source_asset_id"), "source_asset_id"),
                    source_frame_id=_require_id(raw.get("source_frame_id"), "source_frame_id"),
                    source_frame_sha256=_require_digest(raw.get("source_frame_sha256"), "source_frame_sha256"),
                    annotation_set_id=_require_id(raw.get("annotation_set_id"), "annotation_set_id"),
                    review_id=_require_id(raw.get("review_id"), "review_id"),
                    observed_card_id=_require_id(raw.get("observed_card_id"), "observed_card_id"),
                    visual_card_identity=_require_id(raw.get("visual_card_identity"), "visual_card_identity"),
                    bbox=tuple(bbox),
                    transform_version=_require_text(raw.get("transform_version"), "transform_version"),
                    relative_path=relative,
                    byte_length=byte_length,
                    sha256=_require_digest(raw.get("sha256"), "crop sha256"),
                    partition=partition,
                )
            )
        cache = cls(
            dataset_version_id=_require_id(data["dataset_version_id"], "dataset_version_id"),
            dataset_version_digest=_require_digest(data["dataset_version_digest"], "dataset_version_digest"),
            split_version_id=_require_id(data["split_version_id"], "split_version_id"),
            split_version_digest=_require_digest(data["split_version_digest"], "split_version_digest"),
            transform_version=_require_text(data["transform_version"], "transform_version"),
            crops=tuple(crops),
            root=root,
        )
        if cache.digest != _require_digest(data["cache_digest"], "cache_digest"):
            raise DataContractError("stale crop cache: cache_digest does not match its contents.")
        return cache

    def read(self, crop: CropArtifact) -> bytes:
        if self.root is None:
            raise DataContractError("A crop cache root is required to read crop bytes.")
        path = (self.root / crop.relative_path).resolve()
        root = self.root.resolve()
        if root not in path.parents:
            raise DataContractError("crop cache path escapes its root.")
        try:
            value = path.read_bytes()
        except OSError as exc:
            raise DataContractError(f"Crop artifact is missing: {crop.dataset_item_id}.") from exc
        if len(value) != crop.byte_length or _sha256(value) != crop.sha256:
            raise DataContractError(f"stale crop cache: crop {crop.dataset_item_id} does not match its digest.")
        return value


@dataclass(frozen=True, slots=True)
class LoadedCrop:
    dataset_item_id: str
    crop_bytes: bytes
    target: str
    partition: str
    source_frame_sha256: str


class MaterializedCropDataset(Sequence[LoadedCrop]):
    """Small deterministic loader over verified materialized crops."""

    def __init__(self, cache: CropCache, *, partition: str | None = None) -> None:
        if partition is not None and partition not in {"train", "validation", "test", "unassigned"}:
            raise DataContractError(f"Unknown dataset partition: {partition}.")
        self.cache = cache
        self.crops = tuple(crop for crop in cache.crops if partition is None or crop.partition == partition)

    def __len__(self) -> int:
        return len(self.crops)

    def __getitem__(self, index: int) -> LoadedCrop:
        crop = self.crops[index]
        return LoadedCrop(
            dataset_item_id=crop.dataset_item_id,
            crop_bytes=self.cache.read(crop),
            target=crop.visual_card_identity,
            partition=crop.partition,
            source_frame_sha256=crop.source_frame_sha256,
        )

    def __iter__(self) -> Iterator[LoadedCrop]:
        for index in range(len(self)):
            yield self[index]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    dataset_version_id: str
    dataset_version_digest: str
    checked_entry_count: int
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": "table-analyzer-dataset-validation/v1",
            "dataset_version_id": self.dataset_version_id,
            "dataset_version_digest": self.dataset_version_digest,
            "checked_entry_count": self.checked_entry_count,
            "valid": self.valid,
            "errors": list(self.errors),
        }


def load_dataset_manifest(path: str | Path) -> DatasetManifest:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return DatasetManifest.from_mapping(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise DataContractError(f"Could not read dataset manifest {path}: {exc}") from exc


def load_split_manifest(path: str | Path) -> SplitManifest:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return SplitManifest.from_mapping(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise DataContractError(f"Could not read dataset split {path}: {exc}") from exc


def load_artifact_index(path: str | Path) -> ArtifactIndex:
    index_path = Path(path)
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return ArtifactIndex.from_mapping(data, root=index_path.parent)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise DataContractError(f"Could not read artifact index {path}: {exc}") from exc


def validate_dataset(
    dataset: DatasetManifest,
    *,
    split: SplitManifest | None = None,
    artifacts: ArtifactIndex | None = None,
    card_set: Sequence[str] = CARD_IDENTITIES,
) -> ValidationReport:
    errors: list[str] = []
    try:
        if split is not None:
            split.validate_against(dataset)
    except DataContractError as exc:
        errors.append(str(exc))
    if artifacts is not None:
        if artifacts.dataset_version_id != dataset.dataset_version_id:
            errors.append("artifact index references a different dataset version ID.")
        if artifacts.dataset_version_digest != dataset.digest:
            errors.append("artifact index references a different dataset digest.")
    entry_by_frame = {}
    for entry in dataset.entries:
        if entry.target_schema != dataset.target_schema or entry.target_schema != TARGET_SCHEMA:
            errors.append(f"Entry {entry.dataset_item_id} has an unknown target schema.")
        if entry.transform_version != dataset.derived_artifact_transform_version:
            errors.append(f"Entry {entry.dataset_item_id} has a changed transform version.")
        eligibility = entry.eligibility
        if eligibility.state != "eligible" or eligibility.review_state != "reviewed":
            errors.append(f"Entry {entry.dataset_item_id} is not reviewed and eligible.")
        if (
            eligibility.source_asset_id != entry.source_asset_id
            or eligibility.annotation_set_id != entry.annotation_set_id
            or eligibility.review_id != entry.review_id
        ):
            errors.append(f"Entry {entry.dataset_item_id} has invalid eligibility lineage.")
        if not set(eligibility.allowed_uses).intersection(dataset.allowed_use_filter):
            errors.append(f"Entry {entry.dataset_item_id} does not pass the allowed-use filter.")
        if entry.visual_card_identity not in set(card_set):
            errors.append(f"Entry {entry.dataset_item_id} has an unknown card identity.")
        if entry.source_frame_id is None or entry.bbox is None:
            errors.append(f"Entry {entry.dataset_item_id} has no materializable sample reference.")
            continue
        if artifacts is not None:
            matching = [item for item in artifacts.artifacts if item.source_frame_id == entry.source_frame_id]
            if not matching:
                errors.append(f"Entry {entry.dataset_item_id} has no sample-artifact index entry.")
            elif matching[0].source_asset_id != entry.source_asset_id:
                errors.append(f"Entry {entry.dataset_item_id} has a mismatched source artifact.")
            else:
                try:
                    frame = artifacts.resolve(entry.source_frame_id, source_asset_id=entry.source_asset_id)
                    entry_by_frame[entry.source_frame_id] = frame.sha256
                except DataContractError as exc:
                    errors.append(str(exc))
    return ValidationReport(
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        checked_entry_count=len(dataset.entries),
        errors=tuple(sorted(set(errors))),
    )


def assert_valid_dataset(*args: Any, **kwargs: Any) -> ValidationReport:
    report = validate_dataset(*args, **kwargs)
    if not report.valid:
        raise DataContractError("Dataset validation failed: " + "; ".join(report.errors))
    return report


def _ppm_tokens(value: bytes) -> tuple[int, int, int, int]:
    """Read the P6 header and return width, height, max value, and pixel offset."""

    if not value.startswith(b"P6"):
        raise DataContractError("source frame is not a supported deterministic P6 image.")
    tokens: list[bytes] = []
    index = 2
    while len(tokens) < 3:
        while index < len(value) and value[index] in b" \t\r\n":
            index += 1
        if index < len(value) and value[index] == ord("#"):
            newline = value.find(b"\n", index)
            if newline < 0:
                raise DataContractError("source frame has an invalid PPM comment.")
            index = newline + 1
            continue
        start = index
        while index < len(value) and value[index] not in b" \t\r\n":
            index += 1
        if start == index:
            raise DataContractError("source frame has an incomplete PPM header.")
        tokens.append(value[start:index])
    try:
        width, height, max_value = (int(token) for token in tokens)
    except ValueError as exc:
        raise DataContractError("source frame has an invalid PPM header.") from exc
    if width <= 0 or height <= 0 or max_value != 255:
        raise DataContractError("source frame must be a positive 8-bit PPM image.")
    while index < len(value) and value[index] in b" \t\r\n":
        index += 1
    expected = width * height * 3
    if len(value) - index != expected:
        raise DataContractError("source frame PPM pixel bytes do not match its dimensions.")
    return width, height, max_value, index


def _crop_ppm(value: bytes, bbox: tuple[int, int, int, int]) -> bytes:
    width, height, _max_value, offset = _ppm_tokens(value)
    x_min, y_min, x_max, y_max = bbox
    if x_min < 0 or y_min < 0 or x_max > width or y_max > height or x_max <= x_min or y_max <= y_min:
        raise DataContractError("crop bbox is outside the source frame.")
    source = memoryview(value)[offset:]
    row_width = width * 3
    rows = b"".join(
        source[(y_min + row) * row_width + x_min * 3 : (y_min + row) * row_width + x_max * 3].tobytes()
        for row in range(y_max - y_min)
    )
    return f"P6\n{x_max - x_min} {y_max - y_min}\n255\n".encode() + rows


def materialize_crops(
    dataset: DatasetManifest,
    split: SplitManifest,
    artifacts: ArtifactIndex,
    cache_dir: str | Path,
    *,
    rebuild: bool = False,
) -> CropCache:
    """Resolve every sample and write a deterministic crop cache.

    A present cache is accepted only when its complete lineage, metadata, and
    content digests match the supplied dataset, split, and source artifacts.
    Pass ``rebuild=True`` to remove only the stale cache files listed by its
    manifest and regenerate them.
    """

    assert_valid_dataset(dataset, split=split, artifacts=artifacts)
    cache_root = Path(cache_dir)
    manifest_path = cache_root / "crop-manifest.json"
    if manifest_path.exists():
        try:
            existing = CropCache.from_mapping(
                json.loads(manifest_path.read_text(encoding="utf-8")), root=cache_root
            )
            if (
                existing.dataset_version_id != dataset.dataset_version_id
                or existing.dataset_version_digest != dataset.digest
                or existing.split_version_id != split.split_version_id
                or existing.split_version_digest != split.digest
                or existing.transform_version != dataset.derived_artifact_transform_version
            ):
                raise DataContractError("stale crop cache: cache lineage does not match inputs.")
            for crop in existing.crops:
                existing.read(crop)
            return existing
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, DataContractError) as exc:
            if not rebuild:
                if isinstance(exc, DataContractError) and str(exc).startswith("stale crop cache"):
                    raise
                raise DataContractError(f"stale crop cache: {exc}") from exc
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                for crop in raw.get("crops", []):
                    relative = crop.get("relative_path") if isinstance(crop, Mapping) else None
                    if isinstance(relative, str) and ".." not in PurePosixPath(relative).parts:
                        candidate = (cache_root / relative).resolve()
                        if cache_root.resolve() in candidate.parents and candidate.is_file():
                            candidate.unlink()
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
            manifest_path.unlink(missing_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    crops_dir = cache_root / "crops"
    crops_dir.mkdir(exist_ok=True)
    partition_by_item = {
        item: partition for partition, items in split.partitions.items() for item in items
    }
    crops: list[CropArtifact] = []
    for entry in dataset.entries:
        assert entry.source_frame_id is not None and entry.bbox is not None
        frame = artifacts.resolve(entry.source_frame_id, source_asset_id=entry.source_asset_id)
        crop_bytes = _crop_ppm(frame.bytes, entry.bbox)
        filename = f"{_sha256(entry.dataset_item_id.encode())}.ppm"
        relative_path = f"crops/{filename}"
        (cache_root / relative_path).write_bytes(crop_bytes)
        crops.append(
            CropArtifact(
                dataset_item_id=entry.dataset_item_id,
                source_asset_id=entry.source_asset_id,
                source_frame_id=entry.source_frame_id,
                source_frame_sha256=frame.sha256,
                annotation_set_id=entry.annotation_set_id,
                review_id=entry.review_id,
                observed_card_id=entry.observed_card_id or "",
                visual_card_identity=entry.visual_card_identity or "",
                bbox=entry.bbox,
                transform_version=entry.transform_version,
                relative_path=relative_path,
                byte_length=len(crop_bytes),
                sha256=_sha256(crop_bytes),
                partition=partition_by_item[entry.dataset_item_id],
            )
        )
    cache = CropCache(
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        split_version_id=split.split_version_id,
        split_version_digest=split.digest,
        transform_version=dataset.derived_artifact_transform_version,
        crops=tuple(crops),
        root=cache_root,
    )
    payload = {
        "schema_version": CROP_CACHE_SCHEMA,
        "dataset_version_id": cache.dataset_version_id,
        "dataset_version_digest": cache.dataset_version_digest,
        "split_version_id": cache.split_version_id,
        "split_version_digest": cache.split_version_digest,
        "transform_version": cache.transform_version,
        "crops": [crop.to_mapping() for crop in cache.crops],
        "cache_digest": cache.digest,
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return cache


@dataclass(frozen=True, slots=True)
class SmokeFixture:
    root: Path
    dataset_path: Path
    split_path: Path
    artifact_index_path: Path
    crop_dir: Path
    frame_paths: tuple[Path, ...]
    frame_ids: tuple[str, ...]


def _ppm(width: int, height: int, color: tuple[int, int, int], marker: int) -> bytes:
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels.extend(((color[0] + x + marker) % 256, (color[1] + y) % 256, color[2]))
    return f"P6\n{width} {height}\n255\n".encode() + bytes(pixels)


def build_smoke_fixture(root: str | Path) -> SmokeFixture:
    """Create three reviewed, generated image samples in independent groups."""

    fixture_root = Path(root)
    artifact_root = fixture_root / "artifacts"
    frames_root = artifact_root / "frames"
    frames_root.mkdir(parents=True, exist_ok=True)
    identities = ("CLUBS_NINE", "SPADES_JACK", "HEARTS_QUEEN")
    colors = ((30, 80, 120), (90, 40, 150), (140, 60, 30))
    entries: list[dict[str, Any]] = []
    artifact_rows: list[dict[str, Any]] = []
    frame_paths: list[Path] = []
    frame_ids: list[str] = []
    for index, (identity, color) in enumerate(zip(identities, colors, strict=True)):
        suffix = chr(ord("a") + index)
        source_asset_id = f"smoke-source-{suffix}"
        frame_id = f"smoke-frame-{suffix}"
        source_bytes = f"smoke-source-bytes-{suffix}".encode()
        frame_bytes = _ppm(16, 16, color, index)
        frame_path = frames_root / f"{frame_id}.ppm"
        frame_path.write_bytes(frame_bytes)
        frame_paths.append(frame_path)
        frame_ids.append(frame_id)
        artifact_rows.append(
            {
                "source_asset_id": source_asset_id,
                "source_frame_id": frame_id,
                "relative_path": f"frames/{frame_id}.ppm",
                "media_type": "image/x-portable-pixmap",
                "byte_length": len(frame_bytes),
                "sha256": _sha256(frame_bytes),
            }
        )
        entries.append(
            {
                "dataset_item_id": f"smoke-item-{suffix}",
                "source_asset_id": source_asset_id,
                "source_sha256": _sha256(source_bytes),
                "annotation_set_id": f"smoke-annotation-{suffix}",
                "review_id": f"smoke-review-{suffix}",
                "eligibility": {
                    "schema_version": "eligibility/v1",
                    "source_asset_id": source_asset_id,
                    "state": "eligible",
                    "source_permission": "training_and_evaluation",
                    "allowed_uses": ["train", "validation", "test"],
                    "review_state": "reviewed",
                    "annotation_set_id": f"smoke-annotation-{suffix}",
                    "review_id": f"smoke-review-{suffix}",
                    "intended_use": "train" if index == 0 else "validation" if index == 1 else "test",
                    "reason": None,
                },
                "target_schema": TARGET_SCHEMA,
                "group_keys": [
                    ["session_id", f"smoke-session-{suffix}"],
                    ["game_id", f"smoke-game-{suffix}"],
                    ["table_setup", f"smoke-setup-{suffix}"],
                    ["source_lineage", source_asset_id],
                ],
                "inclusion_reason": "Generated reviewed identity crop for loader smoke coverage.",
                "transform_version": DEFAULT_TRANSFORM_VERSION,
                "source_frame_id": frame_id,
                "observed_card_id": f"smoke-card-{suffix}",
                "bbox": [2, 2, 14, 14],
                "visual_card_identity": identity,
                "quality_tags": [],
            }
        )
    dataset = DatasetManifest(
        dataset_version_id="table-analyzer-smoke-dataset-v1",
        task="table_evidence_analyzer_identity_crop",
        target_schema=TARGET_SCHEMA,
        entries=tuple(DatasetEntry.from_mapping(entry) for entry in entries),
        allowed_use_filter=("train", "validation", "test"),
        group_key_names=("session_id", "game_id", "table_setup", "source_lineage"),
        derived_artifact_transform_version=DEFAULT_TRANSFORM_VERSION,
        creation_code_revision="smoke-fixture",
        dirty_state=False,
        deck_design_version="smoke-deck-design-v1",
        card_set_version=CARD_SET_ID,
        created_at="2026-08-28T00:00:00Z",
    )
    split = SplitManifest(
        split_version_id="table-analyzer-smoke-split-v1",
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        group_key_names=dataset.group_key_names,
        seed=17,
        train=("smoke-item-a",),
        validation=("smoke-item-b",),
        test=("smoke-item-c",),
        unassigned=(),
    )
    index = ArtifactIndex(
        artifact_index_id="table-analyzer-smoke-artifacts-v1",
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        artifacts=tuple(ArtifactRecord.from_mapping(row) for row in artifact_rows),
        root=artifact_root,
    )
    fixture_root.mkdir(parents=True, exist_ok=True)
    dataset_path = fixture_root / "dataset.json"
    dataset_payload = {
        "schema_version": DATASET_VERSION_SCHEMA,
        "dataset_version_id": dataset.dataset_version_id,
        "task": dataset.task,
        "target_schema": dataset.target_schema,
        "entries": [entry.to_mapping() for entry in dataset.entries],
        "allowed_use_filter": list(dataset.allowed_use_filter),
        "group_key_names": list(dataset.group_key_names),
        "derived_artifact_transform_version": dataset.derived_artifact_transform_version,
        "creation_code_revision": dataset.creation_code_revision,
        "dirty_state": dataset.dirty_state,
        "deck_design_version": dataset.deck_design_version,
        "card_set_version": dataset.card_set_version,
        "created_at": dataset.created_at,
        "dataset_version_digest": dataset.digest,
    }
    dataset_path.write_text(json.dumps(dataset_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    split_path = fixture_root / "split.json"
    split_path.write_text(json.dumps(split.to_mapping(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    artifact_index_path = artifact_root / "index.json"
    index_payload = {
        "schema_version": ARTIFACT_INDEX_SCHEMA,
        "artifact_index_id": index.artifact_index_id,
        "dataset_version_id": index.dataset_version_id,
        "dataset_version_digest": index.dataset_version_digest,
        "artifacts": [
            {
                "source_asset_id": row.source_asset_id,
                "source_frame_id": row.source_frame_id,
                "relative_path": row.relative_path,
                "media_type": row.media_type,
                "byte_length": row.byte_length,
                "sha256": row.sha256,
            }
            for row in index.artifacts
        ],
        "artifact_index_digest": index.digest,
    }
    artifact_index_path.write_text(json.dumps(index_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return SmokeFixture(
        root=fixture_root,
        dataset_path=dataset_path,
        split_path=split_path,
        artifact_index_path=artifact_index_path,
        crop_dir=fixture_root / "crop-cache",
        frame_paths=tuple(frame_paths),
        frame_ids=tuple(frame_ids),
    )


__all__ = [
    "ARTIFACT_INDEX_SCHEMA",
    "CROP_CACHE_SCHEMA",
    "DATASET_VERSION_SCHEMA",
    "DEFAULT_TRANSFORM_VERSION",
    "DataContractError",
    "ArtifactIndex",
    "ArtifactRecord",
    "CropArtifact",
    "CropCache",
    "DatasetEntry",
    "DatasetManifest",
    "Eligibility",
    "LoadedCrop",
    "MaterializedCropDataset",
    "ResolvedFrame",
    "SmokeFixture",
    "SplitManifest",
    "ValidationReport",
    "assert_valid_dataset",
    "build_smoke_fixture",
    "load_artifact_index",
    "load_dataset_manifest",
    "load_split_manifest",
    "materialize_crops",
    "validate_dataset",
]
