from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .splits import SplitError, VideoSplit, make_video_split


class ManifestError(ValueError):
    pass


MANIFEST_SCHEMA_VERSION = "cardevent-video-metadata/v1"
CONTENT_TYPES = frozenset(
    {"real_game", "staged_trick_sequence", "staged_scenario", "synthetic_render", "other"}
)
CAMERA_VIEWS = frozenset({"overhead", "high_oblique", "low_oblique", "side_oblique", "other"})
CAMERA_MOTIONS = frozenset({"fixed", "handheld_static", "handheld_moving", "other"})
CAMERA_FRAMINGS = frozenset({"table_fills_frame", "table_with_context", "wide_context", "other"})
ORIENTATIONS = frozenset({"portrait", "landscape", "square", "other"})
LIGHTING_TAGS = frozenset(
    {"daylight", "room_light", "mixed", "low_light", "changing", "strong_shadow", "glare"}
)
SCENARIO_TAGS = frozenset(
    {
        "normal_card_play",
        "rapid_consecutive_plays",
        "long_pause",
        "overlapping_card_plays",
        "trick_collected_during_play",
        "face_down_card_played",
        "face_down_card_turned",
        "collected_tricks_visible",
        "score_card_set_aside",
        "card_withdrawn",
        "card_repositioned",
        "multiple_cards_dropped",
        "old_card_returned",
        "other_anomaly",
    }
)
KNOWN_LIMITATIONS = frozenset(
    {
        "regular_play_cadence",
        "short_inter_trick_pauses",
        "no_overlapping_card_plays",
        "few_mistakes",
        "no_game_decisions",
        "single_actor",
    }
)
SOURCES = frozenset({"self_recorded", "contributed", "licensed", "synthetic", "other"})
SOURCE_PERMISSIONS = frozenset(
    {"training_only", "training_and_evaluation", "project_use", "unrestricted"}
)

MANIFEST_FIELDS = (
    "video_id",
    "file_name",
    "content_type",
    "session_id",
    "game_id",
    "recording_date",
    "device",
    "camera",
    "resolution",
    "frame_rate",
    "duration_s",
    "orientation",
    "camera_view",
    "camera_motion",
    "camera_framing",
    "table_setup",
    "lighting",
    "background",
    "card_deck",
    "scenario_tags",
    "known_limitations",
    "source",
    "annotation_version",
    "source_permission",
    "notes",
)

VERSIONED_REQUIRED_FIELDS = frozenset(MANIFEST_FIELDS) - {"notes"}
VERSIONED_NON_NULL_FIELDS = frozenset(
    {
        "file_name",
        "content_type",
        "orientation",
        "camera_view",
        "camera_motion",
        "camera_framing",
        "table_setup",
        "source",
        "source_permission",
    }
)


def _optional_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and (not isinstance(value, str) or not value):
        raise ManifestError(f"manifest.{key} must be a non-empty string or null.")
    return value


def _tag_tuple(data: Mapping[str, Any], key: str, allowed: frozenset[str]) -> tuple[str, ...]:
    value = data.get(key, ())
    if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
        raise ManifestError(f"manifest.{key} must be a list of strings.")
    unknown = set(value) - allowed
    if unknown:
        raise ManifestError(f"Unknown manifest.{key} values: {', '.join(sorted(unknown))}.")
    if len(value) != len(set(value)):
        raise ManifestError(f"manifest.{key} values must be unique.")
    return tuple(value)


def _validate_recording_date(value: str | None) -> None:
    if value is None:
        return
    try:
        if "T" in value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        else:
            date.fromisoformat(value)
    except ValueError as exc:
        raise ManifestError(
            "manifest.recording_date must be an ISO date or a timestamp with a UTC offset."
        ) from exc


def _validate_choice(value: str | None, key: str, allowed: frozenset[str]) -> None:
    if value is not None and value not in allowed:
        raise ManifestError(f"Unknown manifest.{key} value: {value}.")


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    video_id: str
    session_id: str
    file_name: str | None = None
    content_type: str | None = None
    game_id: str | None = None
    recording_date: str | None = None
    device: str | None = None
    camera: str | None = None
    resolution: str | None = None
    frame_rate: float | None = None
    duration_s: float | None = None
    orientation: str | None = None
    camera_view: str | None = None
    camera_motion: str | None = None
    camera_framing: str | None = None
    table_setup: str | None = None
    lighting: tuple[str, ...] = ()
    background: str | None = None
    card_deck: str | None = None
    scenario_tags: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()
    source: str | None = None
    annotation_version: str | None = None
    source_permission: str | None = None
    notes: str | None = None

    @classmethod
    def from_mapping(
        cls, data: Mapping[str, Any], *, require_complete: bool = False
    ) -> "DatasetRecord":
        unknown = set(data) - set(MANIFEST_FIELDS)
        if unknown:
            raise ManifestError(f"Unknown manifest fields: {', '.join(sorted(unknown))}.")
        if require_complete:
            missing = VERSIONED_REQUIRED_FIELDS - set(data)
            if missing:
                raise ManifestError(
                    f"Versioned manifest record is missing fields: {', '.join(sorted(missing))}."
                )
            null_fields = {key for key in VERSIONED_NON_NULL_FIELDS if data.get(key) is None}
            if null_fields:
                raise ManifestError(
                    "Versioned manifest record has null required fields: "
                    f"{', '.join(sorted(null_fields))}."
                )
        for key in ("video_id", "session_id"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ManifestError(f"manifest.{key} must be a non-empty string.")

        strings = {
            key: _optional_string(data, key)
            for key in MANIFEST_FIELDS
            if key
            not in {
                "video_id",
                "session_id",
                "frame_rate",
                "duration_s",
                "lighting",
                "scenario_tags",
                "known_limitations",
            }
        }
        for key in ("frame_rate", "duration_s"):
            value = data.get(key)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ManifestError(f"manifest.{key} must be a number or null.")
                value = float(value)
                if not math.isfinite(value) or value <= 0.0:
                    raise ManifestError(f"manifest.{key} must be positive and finite.")
            strings[key] = value

        resolution = strings["resolution"]
        if resolution is not None and re.fullmatch(r"[1-9]\d*x[1-9]\d*", resolution) is None:
            raise ManifestError("manifest.resolution must use WIDTHxHEIGHT, for example 1920x1080.")
        _validate_recording_date(strings["recording_date"])
        _validate_choice(strings["content_type"], "content_type", CONTENT_TYPES)
        _validate_choice(strings["orientation"], "orientation", ORIENTATIONS)
        _validate_choice(strings["camera_view"], "camera_view", CAMERA_VIEWS)
        _validate_choice(strings["camera_motion"], "camera_motion", CAMERA_MOTIONS)
        _validate_choice(strings["camera_framing"], "camera_framing", CAMERA_FRAMINGS)
        _validate_choice(strings["source"], "source", SOURCES)
        _validate_choice(strings["source_permission"], "source_permission", SOURCE_PERMISSIONS)
        if strings["content_type"] == "real_game" and strings["game_id"] is None:
            raise ManifestError("A real_game record must have a game_id.")

        return cls(
            video_id=data["video_id"],
            session_id=data["session_id"],
            **strings,
            lighting=_tag_tuple(data, "lighting", LIGHTING_TAGS),
            scenario_tags=_tag_tuple(data, "scenario_tags", SCENARIO_TAGS),
            known_limitations=_tag_tuple(data, "known_limitations", KNOWN_LIMITATIONS),
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in MANIFEST_FIELDS:
            value = getattr(self, key)
            result[key] = list(value) if isinstance(value, tuple) else value
        return result


def load_dataset_manifest(path: str | Path) -> tuple[DatasetRecord, ...]:
    try:
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, ModuleNotFoundError) as exc:
        raise ManifestError(f"Could not read dataset manifest: {exc}") from exc
    require_complete = False
    if isinstance(data, Mapping):
        unknown_top_level = set(data) - {"schema_version", "videos"}
        if unknown_top_level:
            raise ManifestError(
                f"Unknown dataset manifest fields: {', '.join(sorted(unknown_top_level))}."
            )
        schema_version = data.get("schema_version")
        if schema_version is not None and schema_version != MANIFEST_SCHEMA_VERSION:
            raise ManifestError(f"Unsupported dataset manifest schema: {schema_version}.")
        require_complete = schema_version == MANIFEST_SCHEMA_VERSION
        rows = data.get("videos")
    else:
        rows = data
    if not isinstance(rows, list):
        raise ManifestError("Dataset manifest must contain a videos list.")
    records = tuple(
        DatasetRecord.from_mapping(row, require_complete=require_complete)
        for row in rows
        if isinstance(row, Mapping)
    )
    if len(records) != len(rows) or len({record.video_id for record in records}) != len(records):
        raise ManifestError("Dataset manifest video_id values must be unique mappings.")
    return records


def validate_session_isolation(split: VideoSplit, records: Sequence[DatasetRecord]) -> None:
    sessions = {record.video_id: record.session_id for record in records}
    missing = set(split.train + split.val + split.test) - set(sessions)
    if missing:
        raise ManifestError(f"Split videos missing from manifest: {', '.join(sorted(missing))}.")
    seen: dict[str, str] = {}
    for partition in ("train", "val", "test"):
        for video in split.names(partition):
            session = sessions[video]
            if session in seen and seen[session] != partition:
                raise SplitError(f"Session {session} occurs in more than one partition.")
            seen[session] = partition


def make_group_split(records: Sequence[DatasetRecord], *, seed: int = 42) -> VideoSplit:
    groups: dict[str, list[str]] = {}
    for record in records:
        groups.setdefault(record.session_id, []).append(record.video_id)
    group_split = make_video_split(tuple(groups), seed=seed)
    split = VideoSplit(
        train=tuple(sorted(video for group in group_split.train for video in groups[group])),
        val=tuple(sorted(video for group in group_split.val for video in groups[group])),
        test=tuple(sorted(video for group in group_split.test for video in groups[group])),
    )
    validate_session_isolation(split, records)
    return split
