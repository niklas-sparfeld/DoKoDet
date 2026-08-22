from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .splits import SplitError, VideoSplit, make_video_split


class ManifestError(ValueError):
    pass


MANIFEST_FIELDS = (
    "video_id",
    "session_id",
    "recording_date",
    "device",
    "camera",
    "resolution",
    "frame_rate",
    "table_setup",
    "card_deck",
    "annotation_version",
    "source_permission",
)


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    video_id: str
    session_id: str
    recording_date: str | None = None
    device: str | None = None
    camera: str | None = None
    resolution: str | None = None
    frame_rate: float | None = None
    table_setup: str | None = None
    card_deck: str | None = None
    annotation_version: str | None = None
    source_permission: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DatasetRecord":
        unknown = set(data) - set(MANIFEST_FIELDS)
        if unknown:
            raise ManifestError(f"Unknown manifest fields: {', '.join(sorted(unknown))}.")
        for key in ("video_id", "session_id"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ManifestError(f"manifest.{key} must be a non-empty string.")
        values = {key: data.get(key) for key in MANIFEST_FIELDS}
        if values["frame_rate"] is not None:
            if isinstance(values["frame_rate"], bool) or not isinstance(
                values["frame_rate"], (int, float)
            ):
                raise ManifestError("manifest.frame_rate must be a number or null.")
            values["frame_rate"] = float(values["frame_rate"])
        return cls(**values)

    def to_mapping(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in MANIFEST_FIELDS}


def load_dataset_manifest(path: str | Path) -> tuple[DatasetRecord, ...]:
    try:
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, ModuleNotFoundError) as exc:
        raise ManifestError(f"Could not read dataset manifest: {exc}") from exc
    rows = data.get("videos") if isinstance(data, Mapping) else data
    if not isinstance(rows, list):
        raise ManifestError("Dataset manifest must contain a videos list.")
    records = tuple(DatasetRecord.from_mapping(row) for row in rows if isinstance(row, Mapping))
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
