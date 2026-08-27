"""Shared source, lineage, eligibility, and dataset-version contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Mapping, Sequence

from .manifest import CONTENT_TYPES, SOURCE_PERMISSIONS, DatasetRecord


class ContractError(ValueError):
    """Raised when a data-contract record is invalid."""


DATA_CONTRACT_SCHEMA_VERSION = "data-contract/v1"
SOURCE_RECORD_SCHEMA_VERSION = "source-record/v1"
LINEAGE_SCHEMA_VERSION = "lineage/v1"
ELIGIBILITY_SCHEMA_VERSION = "eligibility/v1"
DATASET_VERSION_SCHEMA_VERSION = "dataset-version/v1"

ENTITY_KINDS = frozenset(
    {
        "source_asset",
        "session",
        "recording",
        "game",
        "round",
        "evidence_package",
        "frame",
        "annotation_set",
        "review",
        "crop",
    }
)
LINEAGE_RELATIONS = frozenset(
    {
        "recording_in_session",
        "source_contains_recording",
        "evidence_package_from_recording",
        "frame_from_evidence_package",
        "annotation_for_evidence_package",
        "crop_from_frame",
        "crop_target_from_annotation",
    }
)
LINEAGE_RELATION_KINDS = {
    "recording_in_session": ("session", "recording"),
    "source_contains_recording": ("source_asset", "recording"),
    "evidence_package_from_recording": ("recording", "evidence_package"),
    "frame_from_evidence_package": ("evidence_package", "frame"),
    "annotation_for_evidence_package": ("evidence_package", "annotation_set"),
    "crop_from_frame": ("frame", "crop"),
    "crop_target_from_annotation": ("annotation_set", "crop"),
}
ELIGIBILITY_STATES = frozenset(
    {"intake", "annotating", "review_required", "reviewed", "eligible", "excluded", "retired"}
)
REVIEW_STATES = frozenset({"not_started", "draft", "in_review", "reviewed", "rejected"})
INTENDED_USES = frozenset({"train", "validation", "test", "evaluation"})
RETENTION_STATES = frozenset({"active", "deletion_requested", "deleted", "retired"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field} must be a non-empty string.")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field)


def _identifier(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if result in {".", ".."} or PurePath(result).is_absolute() or "/" in result or "\\" in result:
        raise ContractError(f"{field} must be an identifier, not a local path.")
    return result


def _sha256(value: Any, field: str = "sha256") -> str:
    result = _required_string(value, field)
    if _SHA256.fullmatch(result) is None:
        raise ContractError(f"{field} must be a lower-case SHA-256 digest.")
    return result


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{field} must be a positive integer.")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ContractError(f"{field} must be a list of non-empty strings.")
    if len(value) != len(set(value)):
        raise ContractError(f"{field} must not contain duplicate values.")
    return tuple(value)


def _check_schema(data: Mapping[str, Any], expected: set[str], version: str, context: str) -> None:
    unknown = set(data) - expected
    missing = expected - set(data)
    if unknown or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise ContractError(f"{context} has invalid fields ({'; '.join(parts)}).")
    if data["schema_version"] != version:
        raise ContractError(f"Unsupported {context} schema: {data['schema_version']}.")


def _as_json_value(value: Any) -> Any:
    if hasattr(value, "to_mapping"):
        return _as_json_value(value.to_mapping())
    if isinstance(value, Mapping):
        return {str(key): _as_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_as_json_value(item) for item in value]
    if isinstance(value, list):
        return [_as_json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Return stable JSON bytes for a contract value."""

    return json.dumps(
        _as_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str) -> str:
    with open(path, "rb") as source:
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Immutable source bytes and the operator-owned facts about them."""

    source_asset_id: str
    sha256: str
    byte_length: int
    media_type: str
    original_filename: str
    acquisition_method: str
    source_permission: str
    allowed_uses: tuple[str, ...]
    session_id: str | None = None
    recording_id: str | None = None
    video_id: str | None = None
    game_id: str | None = None
    round_id: str | None = None
    table_setup: str | None = None
    content_type: str | None = None
    retention_state: str = "active"
    notes: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.source_asset_id, "source_asset_id")
        _sha256(self.sha256)
        _positive_integer(self.byte_length, "byte_length")
        _required_string(self.media_type, "media_type")
        filename = _required_string(self.original_filename, "original_filename")
        if PurePath(filename).is_absolute() or "/" in filename or "\\" in filename:
            raise ContractError("original_filename must be a filename, not a local path.")
        _required_string(self.acquisition_method, "acquisition_method")
        if self.source_permission not in SOURCE_PERMISSIONS:
            raise ContractError(f"Unknown source_permission: {self.source_permission}.")
        if not self.allowed_uses or any(use not in INTENDED_USES for use in self.allowed_uses):
            raise ContractError("allowed_uses must contain only known intended uses.")
        if len(self.allowed_uses) != len(set(self.allowed_uses)):
            raise ContractError("allowed_uses must not contain duplicate values.")
        for field in (
            "session_id",
            "recording_id",
            "video_id",
            "game_id",
            "round_id",
            "table_setup",
        ):
            value = getattr(self, field)
            if value is not None:
                _identifier(value, field)
        if self.retention_state not in RETENTION_STATES:
            raise ContractError(f"Unknown retention_state: {self.retention_state}.")
        if self.content_type is not None and self.content_type not in CONTENT_TYPES:
            raise ContractError(f"Unknown content_type: {self.content_type}.")
        if self.content_type in {"staged_scenario", "staged_trick_sequence"} and (
            self.game_id is not None or self.round_id is not None
        ):
            raise ContractError("Staged activity must not have a game_id or round_id.")

    def verify_bytes(self, value: bytes) -> None:
        """Verify that bytes still match this immutable source record."""

        if not isinstance(value, bytes):
            raise ContractError("Source bytes must be bytes.")
        if len(value) != self.byte_length or sha256_bytes(value) != self.sha256:
            raise ContractError(f"Source bytes do not match {self.source_asset_id}.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SourceRecord":
        fields = {
            "schema_version",
            "source_asset_id",
            "sha256",
            "byte_length",
            "media_type",
            "original_filename",
            "acquisition_method",
            "source_permission",
            "allowed_uses",
            "session_id",
            "recording_id",
            "video_id",
            "game_id",
            "round_id",
            "table_setup",
            "content_type",
            "retention_state",
            "notes",
        }
        if not isinstance(data, Mapping):
            raise ContractError("source record must be a mapping.")
        _check_schema(data, fields, SOURCE_RECORD_SCHEMA_VERSION, "source record")
        return cls(
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            sha256=_sha256(data["sha256"]),
            byte_length=_positive_integer(data["byte_length"], "byte_length"),
            media_type=_required_string(data["media_type"], "media_type"),
            original_filename=_required_string(data["original_filename"], "original_filename"),
            acquisition_method=_required_string(data["acquisition_method"], "acquisition_method"),
            source_permission=_required_string(data["source_permission"], "source_permission"),
            allowed_uses=_string_tuple(data["allowed_uses"], "allowed_uses"),
            session_id=_optional_string(data["session_id"], "session_id"),
            recording_id=_optional_string(data["recording_id"], "recording_id"),
            video_id=_optional_string(data["video_id"], "video_id"),
            game_id=_optional_string(data["game_id"], "game_id"),
            round_id=_optional_string(data["round_id"], "round_id"),
            table_setup=_optional_string(data["table_setup"], "table_setup"),
            content_type=_optional_string(data["content_type"], "content_type"),
            retention_state=_required_string(data["retention_state"], "retention_state"),
            notes=_optional_string(data["notes"], "notes"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": SOURCE_RECORD_SCHEMA_VERSION,
            "source_asset_id": self.source_asset_id,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "media_type": self.media_type,
            "original_filename": self.original_filename,
            "acquisition_method": self.acquisition_method,
            "source_permission": self.source_permission,
            "allowed_uses": list(self.allowed_uses),
            "session_id": self.session_id,
            "recording_id": self.recording_id,
            "video_id": self.video_id,
            "game_id": self.game_id,
            "round_id": self.round_id,
            "table_setup": self.table_setup,
            "content_type": self.content_type,
            "retention_state": self.retention_state,
            "notes": self.notes,
        }

    @classmethod
    def from_cardevent_record(
        cls,
        record: DatasetRecord,
        *,
        source_asset_id: str,
        sha256: str,
        byte_length: int,
        allowed_uses: Sequence[str],
        acquisition_method: str = "cardevent-v1-manifest",
        recording_id: str | None = None,
    ) -> "SourceRecord":
        """Adapt one complete CardEventNet V1 metadata record."""

        if record.file_name is None or record.source_permission is None:
            raise ContractError("A complete CardEventNet V1 record is required for adaptation.")
        suffix = PurePath(record.file_name).suffix.lower()
        media_type = {
            ".mov": "video/quicktime",
            ".m4v": "video/x-m4v",
        }.get(suffix, "application/octet-stream")
        return cls(
            source_asset_id=source_asset_id,
            sha256=sha256,
            byte_length=byte_length,
            media_type=media_type,
            original_filename=record.file_name,
            acquisition_method=acquisition_method,
            source_permission=record.source_permission,
            allowed_uses=tuple(allowed_uses),
            session_id=record.session_id,
            recording_id=recording_id,
            video_id=record.video_id,
            game_id=record.game_id,
            table_setup=record.table_setup,
            content_type=record.content_type,
            notes=record.notes,
        )


@dataclass(frozen=True, slots=True)
class EntityRef:
    kind: str
    id: str

    def __post_init__(self) -> None:
        if self.kind not in ENTITY_KINDS:
            raise ContractError(f"Unknown lineage entity kind: {self.kind}.")
        _identifier(self.id, "lineage entity id")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EntityRef":
        if not isinstance(data, Mapping) or set(data) != {"kind", "id"}:
            raise ContractError("lineage entity must contain kind and id.")
        return cls(
            kind=_required_string(data["kind"], "lineage entity kind"),
            id=_identifier(data["id"], "lineage entity id"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id}


@dataclass(frozen=True, slots=True)
class LineageEdge:
    parent: EntityRef
    child: EntityRef
    relation: str
    source_frame_id: str | None = None
    transform: str | None = None

    def __post_init__(self) -> None:
        if self.parent == self.child:
            raise ContractError("A lineage edge must not point to itself.")
        if self.relation not in LINEAGE_RELATIONS:
            raise ContractError(f"Unknown lineage relation: {self.relation}.")
        expected_parent, expected_child = LINEAGE_RELATION_KINDS[self.relation]
        if (self.parent.kind, self.child.kind) != (expected_parent, expected_child):
            raise ContractError(
                f"Lineage relation {self.relation} requires {expected_parent} -> {expected_child}."
            )
        if self.source_frame_id is not None:
            _identifier(self.source_frame_id, "source_frame_id")
        if self.transform is not None:
            _required_string(self.transform, "transform")
        if self.relation == "crop_from_frame" and (
            self.source_frame_id != self.parent.id or self.transform is None
        ):
            raise ContractError(
                "A crop_from_frame edge must record its source frame and transform."
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LineageEdge":
        fields = {"schema_version", "parent", "child", "relation", "source_frame_id", "transform"}
        if not isinstance(data, Mapping):
            raise ContractError("lineage edge must be a mapping.")
        _check_schema(data, fields, LINEAGE_SCHEMA_VERSION, "lineage edge")
        return cls(
            parent=EntityRef.from_mapping(data["parent"]),
            child=EntityRef.from_mapping(data["child"]),
            relation=_required_string(data["relation"], "relation"),
            source_frame_id=_optional_string(data["source_frame_id"], "source_frame_id"),
            transform=_optional_string(data["transform"], "transform"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": LINEAGE_SCHEMA_VERSION,
            "parent": self.parent.to_mapping(),
            "child": self.child.to_mapping(),
            "relation": self.relation,
            "source_frame_id": self.source_frame_id,
            "transform": self.transform,
        }


@dataclass(frozen=True, slots=True)
class LineageGraph:
    edges: tuple[LineageEdge, ...]

    def __post_init__(self) -> None:
        if len(set(self.edges)) != len(self.edges):
            raise ContractError("Lineage edges must be unique.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LineageGraph":
        fields = {"schema_version", "edges"}
        if not isinstance(data, Mapping):
            raise ContractError("lineage graph must be a mapping.")
        _check_schema(data, fields, LINEAGE_SCHEMA_VERSION, "lineage graph")
        if not isinstance(data["edges"], list):
            raise ContractError("lineage graph edges must be a list.")
        return cls(tuple(LineageEdge.from_mapping(edge) for edge in data["edges"]))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": LINEAGE_SCHEMA_VERSION,
            "edges": [edge.to_mapping() for edge in self.edges],
        }

    def validate(self) -> None:
        """Validate graph-wide invariants before a dataset consumes the graph."""

        parents: dict[EntityRef, list[EntityRef]] = {}
        children: dict[EntityRef, list[EntityRef]] = {}
        for edge in self.edges:
            parents.setdefault(edge.child, []).append(edge.parent)
            children.setdefault(edge.parent, []).append(edge.child)

        # These relationships have one owning parent.  A package or recording with
        # multiple parents would make its source lineage ambiguous.
        for relation, child_kind in (
            ("recording_in_session", "recording"),
            ("source_contains_recording", "recording"),
            ("evidence_package_from_recording", "evidence_package"),
        ):
            for child, child_parents in parents.items():
                if child.kind != child_kind:
                    continue
                matching = [
                    edge_parent
                    for edge_parent in child_parents
                    if any(
                        edge.parent == edge_parent
                        and edge.child == child
                        and edge.relation == relation
                        for edge in self.edges
                    )
                ]
                if len(matching) > 1:
                    raise ContractError(f"{child.kind}:{child.id} has multiple {relation} parents.")

        # Validate every connected component, not only entities queried by a caller.
        # This catches a stale cycle in an otherwise unused branch of the graph.
        all_entities = set(parents) | set(children)
        state: dict[EntityRef, int] = {}

        def visit(entity: EntityRef) -> None:
            current_state = state.get(entity, 0)
            if current_state == 1:
                raise ContractError("Lineage graph contains a cycle.")
            if current_state == 2:
                return
            state[entity] = 1
            for child in children.get(entity, ()):
                visit(child)
            state[entity] = 2

        for entity in sorted(all_entities, key=lambda item: (item.kind, item.id)):
            visit(entity)

    def source_assets_for(self, entity: EntityRef) -> tuple[EntityRef, ...]:
        """Return immutable source assets reachable from an entity."""

        parents: dict[EntityRef, list[EntityRef]] = {}
        for edge in self.edges:
            parents.setdefault(edge.child, []).append(edge.parent)
        found: set[EntityRef] = set()
        visiting: set[EntityRef] = set()

        def visit(current: EntityRef) -> None:
            if current.kind == "source_asset":
                found.add(current)
                return
            if current in visiting:
                raise ContractError("Lineage graph contains a cycle.")
            visiting.add(current)
            for parent in sorted(parents.get(current, ()), key=lambda item: (item.kind, item.id)):
                visit(parent)
            visiting.remove(current)

        visit(entity)
        return tuple(sorted(found, key=lambda item: item.id))

    def single_source_asset_for(self, entity: EntityRef) -> EntityRef:
        sources = self.source_assets_for(entity)
        if len(sources) != 1:
            raise ContractError(
                f"Expected one immutable source asset for {entity.kind}:{entity.id}; "
                f"found {len(sources)}."
            )
        return sources[0]


@dataclass(frozen=True, slots=True)
class Eligibility:
    source_asset_id: str
    state: str
    source_permission: str
    allowed_uses: tuple[str, ...]
    review_state: str
    annotation_set_id: str | None = None
    review_id: str | None = None
    intended_use: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.source_asset_id, "source_asset_id")
        if self.state not in ELIGIBILITY_STATES:
            raise ContractError(f"Unknown eligibility state: {self.state}.")
        if self.source_permission not in SOURCE_PERMISSIONS:
            raise ContractError(f"Unknown source_permission: {self.source_permission}.")
        if not self.allowed_uses or any(use not in INTENDED_USES for use in self.allowed_uses):
            raise ContractError("allowed_uses must contain only known intended uses.")
        if len(self.allowed_uses) != len(set(self.allowed_uses)):
            raise ContractError("allowed_uses must not contain duplicate values.")
        if self.review_state not in REVIEW_STATES:
            raise ContractError(f"Unknown review_state: {self.review_state}.")
        for field in ("annotation_set_id", "review_id"):
            value = getattr(self, field)
            if value is not None:
                _identifier(value, field)
        if self.intended_use is not None and self.intended_use not in INTENDED_USES:
            raise ContractError(f"Unknown intended_use: {self.intended_use}.")
        if self.state == "eligible":
            if self.review_state != "reviewed":
                raise ContractError("Eligible data must have review_state reviewed.")
            if self.annotation_set_id is None or self.review_id is None:
                raise ContractError("Eligible data must name its annotation set and review.")
            if self.intended_use is None or self.intended_use not in self.allowed_uses:
                raise ContractError("Eligible data must have an allowed intended_use.")
        if self.state == "excluded" and not self.reason:
            raise ContractError("Excluded data must record a reason.")

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
            raise ContractError("eligibility must be a mapping.")
        _check_schema(data, fields, ELIGIBILITY_SCHEMA_VERSION, "eligibility")
        return cls(
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            state=_required_string(data["state"], "state"),
            source_permission=_required_string(data["source_permission"], "source_permission"),
            allowed_uses=_string_tuple(data["allowed_uses"], "allowed_uses"),
            review_state=_required_string(data["review_state"], "review_state"),
            annotation_set_id=_optional_string(data["annotation_set_id"], "annotation_set_id"),
            review_id=_optional_string(data["review_id"], "review_id"),
            intended_use=_optional_string(data["intended_use"], "intended_use"),
            reason=_optional_string(data["reason"], "reason"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": ELIGIBILITY_SCHEMA_VERSION,
            "source_asset_id": self.source_asset_id,
            "state": self.state,
            "source_permission": self.source_permission,
            "allowed_uses": list(self.allowed_uses),
            "review_state": self.review_state,
            "annotation_set_id": self.annotation_set_id,
            "review_id": self.review_id,
            "intended_use": self.intended_use,
            "reason": self.reason,
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
    source_frame_id: str | None = None
    observed_card_id: str | None = None
    bbox: tuple[int, int, int, int] | None = None
    visual_card_identity: str | None = None
    quality_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.dataset_item_id, "dataset_item_id")
        _identifier(self.source_asset_id, "source_asset_id")
        _sha256(self.source_sha256, "source_sha256")
        _identifier(self.annotation_set_id, "annotation_set_id")
        _identifier(self.review_id, "review_id")
        _required_string(self.target_schema, "target_schema")
        _required_string(self.inclusion_reason, "inclusion_reason")
        _required_string(self.transform_version, "transform_version")
        if self.eligibility.state != "eligible":
            raise ContractError("Dataset entries must be eligible.")
        if self.eligibility.source_asset_id != self.source_asset_id:
            raise ContractError("Dataset entry and eligibility source_asset_id must match.")
        if self.eligibility.annotation_set_id != self.annotation_set_id:
            raise ContractError("Dataset entry and eligibility annotation_set_id must match.")
        if self.eligibility.review_id != self.review_id:
            raise ContractError("Dataset entry and eligibility review_id must match.")
        if not self.group_keys:
            raise ContractError("Dataset entries must record at least one leakage group key.")
        keys = [key for key, _ in self.group_keys]
        if len(keys) != len(set(keys)):
            raise ContractError("Dataset entry group keys must be unique.")
        for key, value in self.group_keys:
            _required_string(key, "group key name")
            _identifier(value, "group key value")
        for field in ("source_frame_id", "observed_card_id"):
            value = getattr(self, field)
            if value is not None:
                _identifier(value, field)
        if self.bbox is not None and (
            len(self.bbox) != 4
            or any(isinstance(value, bool) or not isinstance(value, int) for value in self.bbox)
            or self.bbox[0] < 0
            or self.bbox[1] < 0
            or self.bbox[2] <= self.bbox[0]
            or self.bbox[3] <= self.bbox[1]
        ):
            raise ContractError("bbox must be a positive integer rectangle.")
        if self.visual_card_identity is not None:
            _identifier(self.visual_card_identity, "visual_card_identity")
        if len(self.quality_tags) != len(set(self.quality_tags)) or any(
            not isinstance(tag, str) or not tag for tag in self.quality_tags
        ):
            raise ContractError("quality_tags must contain unique non-empty strings.")
        sample_fields = (
            self.source_frame_id,
            self.observed_card_id,
            self.bbox,
            self.visual_card_identity,
        )
        if any(value is not None for value in sample_fields) and not all(
            value is not None for value in sample_fields
        ):
            raise ContractError(
                "A dataset sample reference needs source frame, observed card, bbox, and identity."
            )
        if self.quality_tags and self.source_frame_id is None:
            raise ContractError("quality_tags require an explicit dataset sample reference.")

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
        }
        optional_fields = {
            "source_frame_id",
            "observed_card_id",
            "bbox",
            "visual_card_identity",
            "quality_tags",
        }
        if not isinstance(data, Mapping) or not set(data) <= fields | optional_fields:
            raise ContractError("dataset entry has invalid fields.")
        if not fields <= set(data):
            raise ContractError("dataset entry has invalid fields.")
        raw_group_keys = data["group_keys"]
        if not isinstance(raw_group_keys, list):
            raise ContractError("group_keys must be a list of [name, value] pairs.")
        group_keys: list[tuple[str, str]] = []
        for pair in raw_group_keys:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ContractError("Each group key must be a [name, value] pair.")
            group_keys.append(
                (
                    _required_string(pair[0], "group key name"),
                    _identifier(pair[1], "group key value"),
                )
            )
        raw_bbox = data.get("bbox")
        bbox: tuple[int, int, int, int] | None
        if raw_bbox is None:
            bbox = None
        elif isinstance(raw_bbox, list) and len(raw_bbox) == 4:
            bbox = tuple(raw_bbox)  # type: ignore[assignment]
        else:
            raise ContractError("bbox must be null or a four-item list.")
        raw_quality_tags = data.get("quality_tags", [])
        quality_tags = _string_tuple(raw_quality_tags, "quality_tags")
        return cls(
            dataset_item_id=_identifier(data["dataset_item_id"], "dataset_item_id"),
            source_asset_id=_identifier(data["source_asset_id"], "source_asset_id"),
            source_sha256=_sha256(data["source_sha256"], "source_sha256"),
            annotation_set_id=_identifier(data["annotation_set_id"], "annotation_set_id"),
            review_id=_identifier(data["review_id"], "review_id"),
            eligibility=Eligibility.from_mapping(data["eligibility"]),
            target_schema=_required_string(data["target_schema"], "target_schema"),
            group_keys=tuple(group_keys),
            inclusion_reason=_required_string(data["inclusion_reason"], "inclusion_reason"),
            transform_version=_required_string(data["transform_version"], "transform_version"),
            source_frame_id=_optional_string(data.get("source_frame_id"), "source_frame_id"),
            observed_card_id=_optional_string(data.get("observed_card_id"), "observed_card_id"),
            bbox=bbox,
            visual_card_identity=_optional_string(
                data.get("visual_card_identity"), "visual_card_identity"
            ),
            quality_tags=quality_tags,
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
class DatasetVersion:
    dataset_version_id: str
    task: str
    target_schema: str
    entries: tuple[DatasetEntry, ...]
    allowed_use_filter: tuple[str, ...]
    group_key_names: tuple[str, ...]
    derived_artifact_transform_version: str
    creation_code_revision: str
    dirty_state: bool
    deck_design_version: str | None = None
    card_set_version: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.dataset_version_id, "dataset_version_id")
        _required_string(self.task, "task")
        _required_string(self.target_schema, "target_schema")
        if not self.entries:
            raise ContractError("A dataset version must contain at least one entry.")
        if not self.allowed_use_filter or any(
            use not in INTENDED_USES for use in self.allowed_use_filter
        ):
            raise ContractError("allowed_use_filter must contain only known intended uses.")
        if len(self.allowed_use_filter) != len(set(self.allowed_use_filter)):
            raise ContractError("allowed_use_filter must not contain duplicate values.")
        if not self.group_key_names or len(self.group_key_names) != len(set(self.group_key_names)):
            raise ContractError("group_key_names must contain unique names.")
        for name in self.group_key_names:
            _required_string(name, "group key name")
        _required_string(
            self.derived_artifact_transform_version, "derived_artifact_transform_version"
        )
        _required_string(self.creation_code_revision, "creation_code_revision")
        if not isinstance(self.dirty_state, bool):
            raise ContractError("dirty_state must be a boolean.")
        for field in ("deck_design_version", "card_set_version", "created_at"):
            value = getattr(self, field)
            if value is not None:
                _required_string(value, field)
        item_ids = [entry.dataset_item_id for entry in self.entries]
        if len(item_ids) != len(set(item_ids)):
            raise ContractError("Dataset entry IDs must be unique within a dataset version.")
        for entry in self.entries:
            if not set(entry.eligibility.allowed_uses).intersection(self.allowed_use_filter):
                raise ContractError(
                    f"Dataset entry {entry.dataset_item_id} does not match the allowed-use filter."
                )
            if entry.target_schema != self.target_schema:
                raise ContractError(
                    f"Dataset entry {entry.dataset_item_id} has a different target schema."
                )
            entry_group_names = {key for key, _ in entry.group_keys}
            if not entry_group_names <= set(self.group_key_names):
                raise ContractError(
                    f"Dataset entry {entry.dataset_item_id} does not contain the "
                    "declared group key names."
                )
        used_group_names = {key for entry in self.entries for key, _ in entry.group_keys}
        if used_group_names != set(self.group_key_names):
            raise ContractError("group_key_names must declare the group keys used by entries.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DatasetVersion":
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
            raise ContractError("dataset version must be a mapping.")
        _check_schema(data, fields, DATASET_VERSION_SCHEMA_VERSION, "dataset version")
        if not isinstance(data["entries"], list):
            raise ContractError("dataset version entries must be a list.")
        version = cls(
            dataset_version_id=_identifier(data["dataset_version_id"], "dataset_version_id"),
            task=_required_string(data["task"], "task"),
            target_schema=_required_string(data["target_schema"], "target_schema"),
            entries=tuple(DatasetEntry.from_mapping(entry) for entry in data["entries"]),
            allowed_use_filter=_string_tuple(data["allowed_use_filter"], "allowed_use_filter"),
            group_key_names=_string_tuple(data["group_key_names"], "group_key_names"),
            derived_artifact_transform_version=_required_string(
                data["derived_artifact_transform_version"], "derived_artifact_transform_version"
            ),
            creation_code_revision=_required_string(
                data["creation_code_revision"], "creation_code_revision"
            ),
            dirty_state=data["dirty_state"],
            deck_design_version=_optional_string(
                data["deck_design_version"], "deck_design_version"
            ),
            card_set_version=_optional_string(data["card_set_version"], "card_set_version"),
            created_at=_optional_string(data["created_at"], "created_at"),
        )
        expected_digest = _sha256(data["dataset_version_digest"], "dataset_version_digest")
        if version.digest != expected_digest:
            raise ContractError("dataset_version_digest does not match the dataset contents.")
        return version

    def _digest_mapping(self) -> dict[str, Any]:
        def entry_mapping(entry: DatasetEntry) -> dict[str, Any]:
            mapping = entry.to_mapping()
            mapping["group_keys"] = sorted(mapping["group_keys"])
            mapping["eligibility"]["allowed_uses"] = sorted(mapping["eligibility"]["allowed_uses"])
            return mapping

        return {
            "schema_version": DATASET_VERSION_SCHEMA_VERSION,
            "task": self.task,
            "target_schema": self.target_schema,
            "entries": [
                entry_mapping(entry)
                for entry in sorted(self.entries, key=lambda item: item.dataset_item_id)
            ],
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
        return sha256_bytes(canonical_json(self._digest_mapping()).encode("utf-8"))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": DATASET_VERSION_SCHEMA_VERSION,
            "dataset_version_id": self.dataset_version_id,
            "task": self.task,
            "target_schema": self.target_schema,
            "entries": [entry.to_mapping() for entry in self.entries],
            "allowed_use_filter": list(self.allowed_use_filter),
            "group_key_names": list(self.group_key_names),
            "derived_artifact_transform_version": self.derived_artifact_transform_version,
            "creation_code_revision": self.creation_code_revision,
            "dirty_state": self.dirty_state,
            "deck_design_version": self.deck_design_version,
            "card_set_version": self.card_set_version,
            "created_at": self.created_at,
            "dataset_version_digest": self.digest,
        }


def adapt_cardevent_manifest(
    records: Sequence[DatasetRecord],
    source_metadata: Mapping[str, Mapping[str, Any]],
) -> tuple[SourceRecord, ...]:
    """Adapt complete CardEventNet V1 records with measured source metadata."""

    adapted: list[SourceRecord] = []
    seen_video_ids: set[str] = set()
    for record in records:
        if record.video_id in seen_video_ids:
            raise ContractError(f"Duplicate CardEventNet video ID: {record.video_id}.")
        seen_video_ids.add(record.video_id)
        try:
            metadata = source_metadata[record.video_id]
        except KeyError as exc:
            raise ContractError(
                f"Missing source metadata for CardEventNet video {record.video_id}."
            ) from exc
        required = {"source_asset_id", "sha256", "byte_length", "allowed_uses"}
        missing = required - set(metadata)
        if missing:
            raise ContractError(
                f"Source metadata for {record.video_id} is missing: {', '.join(sorted(missing))}."
            )
        adapted.append(
            SourceRecord.from_cardevent_record(
                record,
                source_asset_id=_required_string(metadata["source_asset_id"], "source_asset_id"),
                sha256=_sha256(metadata["sha256"]),
                byte_length=_positive_integer(metadata["byte_length"], "byte_length"),
                allowed_uses=_string_tuple(metadata["allowed_uses"], "allowed_uses"),
                acquisition_method=metadata.get("acquisition_method", "cardevent-v1-manifest"),
                recording_id=metadata.get("recording_id"),
            )
        )
    return tuple(sorted(adapted, key=lambda item: item.source_asset_id))
