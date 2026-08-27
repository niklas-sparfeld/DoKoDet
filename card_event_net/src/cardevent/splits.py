from __future__ import annotations

import random
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class SplitError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VideoSplit:
    train: tuple[str, ...]
    val: tuple[str, ...]
    test: tuple[str, ...]
    unassigned: tuple[str, ...] = ()

    _PARTITIONS = ("train", "val", "test", "unassigned")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VideoSplit":
        if not isinstance(data, Mapping):
            raise SplitError("Split file must contain a YAML mapping.")

        unknown = set(data) - set(cls._PARTITIONS)
        if unknown:
            raise SplitError(f"Unknown split fields: {', '.join(sorted(unknown))}.")

        partitions: dict[str, tuple[str, ...]] = {}
        for partition in cls._PARTITIONS:
            values = data.get(partition, [])
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise SplitError(f"Split partition {partition} must be a list of names.")
            if len(set(values)) != len(values):
                raise SplitError(f"Split partition {partition} contains duplicate names.")
            partitions[partition] = tuple(values)

        seen: set[str] = set()
        for partition in cls._PARTITIONS:
            overlap = seen.intersection(partitions[partition])
            if overlap:
                names = ", ".join(sorted(overlap))
                raise SplitError(f"Source videos occur in more than one partition: {names}")
            seen.update(partitions[partition])

        return cls(**partitions)

    def to_mapping(self) -> dict[str, list[str]]:
        result = {
            "train": list(self.train),
            "val": list(self.val),
            "test": list(self.test),
        }
        if self.unassigned:
            result["unassigned"] = list(self.unassigned)
        return result

    def names(self, partition: str) -> tuple[str, ...]:
        try:
            return getattr(self, partition)
        except AttributeError as exc:
            raise SplitError(f"Unknown split partition: {partition}") from exc


def video_id(video_path: str | Path) -> str:
    path = Path(video_path)
    if not path.stem:
        raise SplitError(f"Video has no usable name: {video_path}")
    return path.stem


def make_video_split(
    videos: Sequence[str | Path],
    *,
    seed: int = 42,
) -> VideoSplit:
    names = sorted(video_id(video) for video in videos)
    if len(set(names)) != len(names):
        raise SplitError("Video stems must be unique to build a split.")
    if len(names) < 3:
        warnings.warn(
            "Fewer than three source videos are available. "
            "The generated split cannot provide an independent test set.",
            UserWarning,
            stacklevel=2,
        )

    rng = random.Random(seed)
    rng.shuffle(names)
    video_count = len(names)
    if video_count == 0:
        return VideoSplit(train=(), val=(), test=(), unassigned=())

    train_count = max(1, round(video_count * 0.70))
    val_count = max(1, round(video_count * 0.15)) if video_count >= 2 else 0
    test_count = video_count - train_count - val_count
    while test_count < 1 and train_count > 1:
        train_count -= 1
        test_count = video_count - train_count - val_count
    if test_count < 0:
        val_count = max(0, val_count + test_count)
        test_count = 0

    train_end = train_count
    val_end = train_end + val_count
    return VideoSplit(
        train=tuple(names[:train_end]),
        val=tuple(names[train_end:val_end]),
        test=tuple(names[val_end : val_end + test_count]),
    )


def load_split(path: str | Path) -> VideoSplit:
    split_path = Path(path)
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is not available. Run `uv sync` to install the project dependencies."
        ) from exc

    try:
        data = yaml.safe_load(split_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SplitError(f"Could not read split file: {split_path}") from exc
    return VideoSplit.from_mapping(data)


def save_split(split: VideoSplit, path: str | Path) -> Path:
    split_path = Path(path)
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is not available. Run `uv sync` to install the project dependencies."
        ) from exc

    split_path.parent.mkdir(parents=True, exist_ok=True)
    split_path.write_text(
        yaml.safe_dump(split.to_mapping(), sort_keys=False),
        encoding="utf-8",
    )
    return split_path
