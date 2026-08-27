"""Versioned table-observation annotations and evidence-package import."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Mapping, Sequence

from .data_contract import canonical_json


class VisionAnnotationError(ValueError):
    """Raised when a table-observation annotation or source manifest is invalid."""


TABLE_OBSERVATION_SCHEMA_VERSION = "table-observation-annotation/v1"
TABLE_OBSERVATION_ANNOTATION_SET_SCHEMA_VERSION = TABLE_OBSERVATION_SCHEMA_VERSION
VISION_ANNOTATION_SCHEMA_VERSION = TABLE_OBSERVATION_SCHEMA_VERSION
VISION_ANNOTATION_SET_SCHEMA_VERSION = TABLE_OBSERVATION_ANNOTATION_SET_SCHEMA_VERSION
VISION_CARD_IDENTITIES = tuple(
    f"{suit}_{rank}"
    for suit in ("CLUBS", "SPADES", "HEARTS", "DIAMONDS")
    for rank in ("NINE", "JACK", "QUEEN", "KING", "TEN", "ACE")
)
VISION_EVENT_REVIEW_STATES = frozenset(
    {
        "unreviewed",
        "confirmed_card_play",
        "false_event_proposal",
        "no_visible_cards",
        "card_not_visible",
        "visible_but_not_identifiable",
        "ambiguous_card",
        "insufficient_visual_evidence",
    }
)
VISION_VISIBILITY_STATES = frozenset(
    {"identifiable", "card_not_visible", "visible_but_not_identifiable", "ambiguous_card"}
)
VISION_REVIEW_STATES = frozenset({"draft", "reviewed"})
ACTIVE_AREA_CLASSES = frozenset({"inside", "outside", "uncertain", "not_applicable"})
MOVEMENT_STATES = frozenset({"stationary", "moving", "reappeared", "unknown"})
OCCLUSION_STATES = frozenset({"none", "short", "complete", "unknown"})
_CARD_IDENTITIES = frozenset(VISION_CARD_IDENTITIES)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise VisionAnnotationError(f"{field} must be a non-empty string.")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if (
        result in {".", ".."}
        or PurePath(result).is_absolute()
        or "/" in result
        or "\\" in result
        or _IDENTIFIER.fullmatch(result) is None
    ):
        raise VisionAnnotationError(f"{field} must be a simple identifier.")
    return result


def _strict_fields(
    data: Mapping[str, Any], expected: set[str], context: str, *, optional: set[str] | None = None
) -> None:
    optional = optional or set()
    missing = expected - set(data)
    unknown = set(data) - expected - optional
    if missing or unknown:
        parts: list[str] = []
        if missing:
            parts.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise VisionAnnotationError(f"{context} has invalid fields ({'; '.join(parts)}).")


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VisionAnnotationError(f"{context} must be an object.")
    return value


def _optional_identifier(value: Any, field: str) -> str | None:
    return None if value is None else _identifier(value, field)


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise VisionAnnotationError(f"{field} must be a list of strings.")
    if any(not item or _TAG.fullmatch(item) is None for item in value):
        raise VisionAnnotationError(f"{field} contains an invalid value.")
    if len(value) != len(set(value)):
        raise VisionAnnotationError(f"{field} must not contain duplicate values.")
    return tuple(value)


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise VisionAnnotationError(f"{field} must be a boolean.")
    return value


@dataclass(frozen=True, slots=True)
class VisionSource:
    """The accepted evidence package or recording that produced an annotation set."""

    package_id: str | None = None
    recording_id: str | None = None
    video_id: str | None = None

    def __post_init__(self) -> None:
        values = {
            "package_id": self.package_id,
            "recording_id": self.recording_id,
            "video_id": self.video_id,
        }
        present = [name for name, value in values.items() if value is not None]
        if len(present) != 1:
            raise VisionAnnotationError("source must identify exactly one package or recording.")
        _identifier(values[present[0]], present[0])

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VisionSource":
        mapping = _mapping(data, "source")
        allowed = {"package_id", "recording_id", "video_id"}
        if not set(mapping) or not set(mapping) <= allowed:
            raise VisionAnnotationError("source must contain one known source identifier.")
        values = {key: _optional_identifier(mapping.get(key), key) for key in allowed}
        return cls(**values)

    def to_mapping(self) -> dict[str, str]:
        values = {
            "package_id": self.package_id,
            "recording_id": self.recording_id,
            "video_id": self.video_id,
        }
        return {key: value for key, value in values.items() if value is not None}

    @property
    def source_id(self) -> str:
        return next(value for value in (self.package_id, self.recording_id, self.video_id) if value)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Pixel coordinates in left, top, right, bottom order."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    def __post_init__(self) -> None:
        values = (self.x_min, self.y_min, self.x_max, self.y_max)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise VisionAnnotationError("bbox coordinates must be integers.")
        if self.x_min < 0 or self.y_min < 0 or self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise VisionAnnotationError("bbox must be a positive rectangle within the frame.")

    @classmethod
    def from_value(cls, value: Any) -> "BoundingBox | None":
        if value is None:
            return None
        if not isinstance(value, list) or len(value) != 4:
            raise VisionAnnotationError("bbox must be null or [x_min, y_min, x_max, y_max].")
        return cls(*(value[index] for index in range(4)))

    def to_value(self) -> list[int]:
        return [self.x_min, self.y_min, self.x_max, self.y_max]


@dataclass(frozen=True, slots=True)
class FrameObservation:
    """One uncertain observation of a visible card in one frame."""

    frame_id: str
    bbox: BoundingBox | None
    usable_for_identity: bool
    tags: tuple[str, ...] = ()
    observation_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.frame_id, "frame_id")
        if self.observation_id is not None:
            _identifier(self.observation_id, "observation_id")
        if not isinstance(self.usable_for_identity, bool):
            raise VisionAnnotationError("usable_for_identity must be a boolean.")
        if self.usable_for_identity and self.bbox is None:
            raise VisionAnnotationError("an identity-usable frame observation needs a bbox.")
        if len(self.tags) != len(set(self.tags)):
            raise VisionAnnotationError("frame observation tags must be unique.")
        for tag in self.tags:
            if not isinstance(tag, str) or not tag or _TAG.fullmatch(tag) is None:
                raise VisionAnnotationError("frame observation tags must be simple strings.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FrameObservation":
        mapping = _mapping(data, "frame observation")
        _strict_fields(
            mapping,
            {"frame_id", "bbox", "usable_for_identity", "tags"},
            "frame observation",
            optional={"observation_id"},
        )
        return cls(
            frame_id=_identifier(mapping["frame_id"], "frame_id"),
            bbox=BoundingBox.from_value(mapping["bbox"]),
            usable_for_identity=_boolean(mapping["usable_for_identity"], "usable_for_identity"),
            tags=_string_list(mapping["tags"], "tags"),
            observation_id=_optional_identifier(mapping.get("observation_id"), "observation_id"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "bbox": self.bbox.to_value() if self.bbox is not None else None,
            "usable_for_identity": self.usable_for_identity,
            "tags": list(self.tags),
            **({"observation_id": self.observation_id} if self.observation_id is not None else {}),
        }


@dataclass(frozen=True, slots=True)
class ObservedCard:
    """One uncertain card instance across selected evidence frames."""

    observed_card_id: str
    visual_card_identity: str | None
    visibility: str
    frame_observations: tuple[FrameObservation, ...]
    became_newly_visible: bool
    active_area_class: str | None
    card_tracklet_id: str | None = None
    movement: str | None = None
    occlusion: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.observed_card_id, "observed_card_id")
        if (
            self.visual_card_identity is not None
            and self.visual_card_identity not in _CARD_IDENTITIES
        ):
            raise VisionAnnotationError(
                f"Unknown visual card identity: {self.visual_card_identity}."
            )
        if self.visibility not in VISION_VISIBILITY_STATES:
            raise VisionAnnotationError(f"Unknown visibility: {self.visibility}.")
        if not self.frame_observations:
            raise VisionAnnotationError("an observed card needs at least one frame observation.")
        frame_ids = [observation.frame_id for observation in self.frame_observations]
        if len(frame_ids) != len(set(frame_ids)):
            raise VisionAnnotationError("frame observations must identify unique frames.")
        observation_ids = [
            observation.observation_id
            for observation in self.frame_observations
            if observation.observation_id
        ]
        if len(observation_ids) != len(set(observation_ids)):
            raise VisionAnnotationError("observation IDs must be unique within an observed card.")
        if not isinstance(self.became_newly_visible, bool):
            raise VisionAnnotationError("became_newly_visible must be a boolean.")
        if self.active_area_class is not None and self.active_area_class not in ACTIVE_AREA_CLASSES:
            raise VisionAnnotationError(f"Unknown active_area_class: {self.active_area_class}.")
        if self.card_tracklet_id is not None:
            _identifier(self.card_tracklet_id, "card_tracklet_id")
        if self.movement is not None and self.movement not in MOVEMENT_STATES:
            raise VisionAnnotationError(f"Unknown movement: {self.movement}.")
        if self.occlusion is not None and self.occlusion not in OCCLUSION_STATES:
            raise VisionAnnotationError(f"Unknown occlusion: {self.occlusion}.")
        if self.visibility == "identifiable":
            if self.visual_card_identity is None:
                raise VisionAnnotationError("an identifiable observed card needs a card identity.")
            if not any(observation.usable_for_identity for observation in self.frame_observations):
                raise VisionAnnotationError(
                    "an identifiable observed card needs an identity-usable frame."
                )
        elif self.visual_card_identity is not None:
            raise VisionAnnotationError(
                "a non-identifiable observed card must not have a card identity."
            )
        if self.visibility != "identifiable" and any(
            observation.usable_for_identity for observation in self.frame_observations
        ):
            raise VisionAnnotationError(
                "a non-identifiable observed card cannot have an identity-usable frame."
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ObservedCard":
        mapping = _mapping(data, "observed card")
        required = {
            "observed_card_id",
            "visual_card_identity",
            "visibility",
            "frame_observations",
            "became_newly_visible",
            "active_area_class",
        }
        optional = {"card_tracklet_id", "movement", "occlusion"}
        _strict_fields(mapping, required | optional, "observed card")
        raw_frames = mapping["frame_observations"]
        if not isinstance(raw_frames, list):
            raise VisionAnnotationError("frame_observations must be a list.")
        identity = mapping["visual_card_identity"]
        if identity is not None:
            identity = _required_string(identity, "visual_card_identity")
        return cls(
            observed_card_id=_identifier(mapping["observed_card_id"], "observed_card_id"),
            visual_card_identity=identity,
            visibility=_required_string(mapping["visibility"], "visibility"),
            frame_observations=tuple(FrameObservation.from_mapping(item) for item in raw_frames),
            became_newly_visible=_boolean(mapping["became_newly_visible"], "became_newly_visible"),
            active_area_class=(
                None
                if mapping["active_area_class"] is None
                else _required_string(mapping["active_area_class"], "active_area_class")
            ),
            card_tracklet_id=_optional_identifier(
                mapping.get("card_tracklet_id"), "card_tracklet_id"
            ),
            movement=(
                None
                if mapping.get("movement") is None
                else _required_string(mapping["movement"], "movement")
            ),
            occlusion=(
                None
                if mapping.get("occlusion") is None
                else _required_string(mapping["occlusion"], "occlusion")
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "observed_card_id": self.observed_card_id,
            "visual_card_identity": self.visual_card_identity,
            "visibility": self.visibility,
            "frame_observations": [
                observation.to_mapping() for observation in self.frame_observations
            ],
            "became_newly_visible": self.became_newly_visible,
            "active_area_class": self.active_area_class,
            "card_tracklet_id": self.card_tracklet_id,
            "movement": self.movement,
            "occlusion": self.occlusion,
        }


@dataclass(frozen=True, slots=True)
class VideoSnippet:
    """Optional bounded snippet associated with the annotation set."""

    video_snippet_id: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        _identifier(self.video_snippet_id, "video_snippet_id")
        if (
            isinstance(self.start_ms, bool)
            or isinstance(self.end_ms, bool)
            or not isinstance(self.start_ms, int)
            or not isinstance(self.end_ms, int)
            or self.start_ms < 0
            or self.end_ms <= self.start_ms
        ):
            raise VisionAnnotationError("video snippet times must be positive ordered integers.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VideoSnippet":
        mapping = _mapping(data, "video snippet")
        _strict_fields(mapping, {"video_snippet_id", "start_ms", "end_ms"}, "video snippet")
        return cls(
            video_snippet_id=_identifier(mapping["video_snippet_id"], "video_snippet_id"),
            start_ms=mapping["start_ms"],
            end_ms=mapping["end_ms"],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "video_snippet_id": self.video_snippet_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
        }


@dataclass(frozen=True, slots=True)
class TableObservationAnnotation:
    """One reviewed table-observation annotation set."""

    annotation_set_id: str
    source: VisionSource
    observed_cards: tuple[ObservedCard, ...]
    event_review: str
    review_state: str
    video_snippet: VideoSnippet | None = None

    def __post_init__(self) -> None:
        _identifier(self.annotation_set_id, "annotation_set_id")
        if self.event_review not in VISION_EVENT_REVIEW_STATES:
            raise VisionAnnotationError(f"Unknown event_review: {self.event_review}.")
        if self.review_state not in VISION_REVIEW_STATES:
            raise VisionAnnotationError(f"Unknown review_state: {self.review_state}.")
        if self.event_review == "confirmed_card_play" and self.review_state != "reviewed":
            raise VisionAnnotationError("a confirmed card play must have review_state reviewed.")
        observed_ids = [card.observed_card_id for card in self.observed_cards]
        if len(observed_ids) != len(set(observed_ids)):
            raise VisionAnnotationError("observed card IDs must be unique.")
        tracklet_ids = [
            card.card_tracklet_id for card in self.observed_cards if card.card_tracklet_id
        ]
        if len(tracklet_ids) != len(set(tracklet_ids)):
            raise VisionAnnotationError(
                "card tracklet IDs must be unique within an annotation set."
            )
        if self.event_review == "no_visible_cards" and self.observed_cards:
            raise VisionAnnotationError("no_visible_cards must not contain observed cards.")
        if self.event_review == "insufficient_visual_evidence" and self.observed_cards:
            raise VisionAnnotationError(
                "insufficient_visual_evidence must not contain observed cards."
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TableObservationAnnotation":
        mapping = _mapping(data, "table-observation annotation")
        expected = {
            "schema_version",
            "annotation_set_id",
            "source",
            "observed_cards",
            "event_review",
            "review_state",
        }
        optional = {"video_snippet"}
        _strict_fields(mapping, expected | optional, "table-observation annotation")
        if mapping["schema_version"] != TABLE_OBSERVATION_SCHEMA_VERSION:
            raise VisionAnnotationError(
                f"schema_version must be {TABLE_OBSERVATION_SCHEMA_VERSION}."
            )
        raw_cards = mapping["observed_cards"]
        if not isinstance(raw_cards, list):
            raise VisionAnnotationError("observed_cards must be a list.")
        return cls(
            annotation_set_id=_identifier(mapping["annotation_set_id"], "annotation_set_id"),
            source=VisionSource.from_mapping(mapping["source"]),
            observed_cards=tuple(ObservedCard.from_mapping(item) for item in raw_cards),
            event_review=_required_string(mapping["event_review"], "event_review"),
            review_state=_required_string(mapping["review_state"], "review_state"),
            video_snippet=(
                None
                if mapping.get("video_snippet") is None
                else VideoSnippet.from_mapping(mapping["video_snippet"])
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": TABLE_OBSERVATION_SCHEMA_VERSION,
            "annotation_set_id": self.annotation_set_id,
            "source": self.source.to_mapping(),
            "observed_cards": [card.to_mapping() for card in self.observed_cards],
            "event_review": self.event_review,
            "review_state": self.review_state,
        }
        if self.video_snippet is not None:
            result["video_snippet"] = self.video_snippet.to_mapping()
        return result


TableObservation = TableObservationAnnotation
VisionAnnotation = TableObservationAnnotation
TableObservationSource = VisionSource
TableObservationAnnotationError = VisionAnnotationError


def annotation_bytes(annotation: TableObservationAnnotation) -> bytes:
    """Return canonical bytes for one table-observation annotation."""

    return canonical_json(annotation.to_mapping()).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise VisionAnnotationError(f"Could not read {path}: {exc}") from exc


def load_vision_annotation(path: str | Path) -> TableObservationAnnotation:
    annotation_path = Path(path)
    try:
        payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisionAnnotationError(
            f"Could not read table-observation annotation {annotation_path}: {exc}"
        ) from exc
    return TableObservationAnnotation.from_mapping(payload)


def save_vision_annotation(
    annotation: TableObservationAnnotation, path: str | Path, *, overwrite: bool = False
) -> None:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise VisionAnnotationError(f"Refusing to overwrite annotation: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(annotation.to_mapping(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def _manifest_path(path: Path) -> Path:
    if path.is_dir():
        path = path / "manifest.json"
    if not path.is_file():
        raise VisionAnnotationError(f"Evidence manifest does not exist: {path}")
    return path


def _evidence_annotation(manifest_path: Path) -> TableObservationAnnotation:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisionAnnotationError(
            f"Could not read evidence manifest {manifest_path}: {exc}"
        ) from exc
    mapping = _mapping(payload, "evidence manifest")
    if mapping.get("schema_version") != "cardevent-evidence/v1":
        raise VisionAnnotationError("Evidence manifest must use cardevent-evidence/v1.")
    package_id = _identifier(mapping.get("package_id"), "package_id")
    event = _mapping(mapping.get("event"), "evidence event")
    event_time_ms = event.get("event_time_ms")
    if isinstance(event_time_ms, bool) or not isinstance(event_time_ms, int) or event_time_ms < 0:
        raise VisionAnnotationError("evidence event_time_ms must be a non-negative integer.")
    raw_frames = mapping.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise VisionAnnotationError("evidence frames must be a non-empty list.")
    observations: list[FrameObservation] = []
    for frame in raw_frames:
        frame_mapping = _mapping(frame, "evidence frame")
        part_name = _identifier(frame_mapping.get("part_name"), "part_name")
        observations.append(
            FrameObservation(
                frame_id=part_name,
                bbox=None,
                usable_for_identity=False,
                tags=(),
            )
        )
    placeholder = ObservedCard(
        observed_card_id=f"observed-card-{package_id}",
        visual_card_identity=None,
        visibility="card_not_visible",
        frame_observations=tuple(observations),
        became_newly_visible=False,
        active_area_class="not_applicable",
    )
    return TableObservationAnnotation(
        annotation_set_id=f"annotation-set-{package_id}",
        source=VisionSource(package_id=package_id),
        observed_cards=(placeholder,),
        event_review="unreviewed",
        review_state="draft",
    )


def import_evidence_packages(
    manifests: Sequence[str | Path],
) -> tuple[TableObservationAnnotation, ...]:
    """Import accepted evidence manifests as draft table-observation annotations."""

    if not manifests:
        raise VisionAnnotationError("At least one evidence manifest is required.")
    paths = sorted({_manifest_path(Path(path)) for path in manifests}, key=lambda path: str(path))
    annotations = tuple(_evidence_annotation(path) for path in paths)
    ids = [annotation.annotation_set_id for annotation in annotations]
    if len(ids) != len(set(ids)):
        raise VisionAnnotationError("Evidence manifests contain duplicate package IDs.")
    return annotations


load_table_observation_annotation = load_vision_annotation
save_table_observation_annotation = save_vision_annotation


__all__ = [
    "ACTIVE_AREA_CLASSES",
    "BoundingBox",
    "FrameObservation",
    "MOVEMENT_STATES",
    "OCCLUSION_STATES",
    "ObservedCard",
    "TABLE_OBSERVATION_ANNOTATION_SET_SCHEMA_VERSION",
    "TABLE_OBSERVATION_SCHEMA_VERSION",
    "TableObservation",
    "TableObservationAnnotation",
    "TableObservationAnnotationError",
    "TableObservationSource",
    "VISION_ANNOTATION_SCHEMA_VERSION",
    "VISION_ANNOTATION_SET_SCHEMA_VERSION",
    "VISION_CARD_IDENTITIES",
    "VISION_EVENT_REVIEW_STATES",
    "VISION_REVIEW_STATES",
    "VISION_VISIBILITY_STATES",
    "VideoSnippet",
    "VisionAnnotationError",
    "VisionAnnotation",
    "VisionSource",
    "annotation_bytes",
    "import_evidence_packages",
    "load_vision_annotation",
    "load_table_observation_annotation",
    "save_vision_annotation",
    "save_table_observation_annotation",
]
