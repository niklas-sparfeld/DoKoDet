from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .annotation import VideoAnnotation
from .cache import CacheError, CacheMetadata, load_cache_metadata
from .sampling import (
    DEFAULT_CLIP_OFFSETS_S,
    LabeledTime,
    build_inference_times,
    build_training_times,
    is_positive_time,
    select_frame_indices,
)


@dataclass(frozen=True, slots=True)
class DatasetSample:
    source_video: str
    cache_dir: Path
    decision_time_s: float
    label: float


class CachedFrameStore:
    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.metadata = load_cache_metadata(self.cache_dir)
        self.frames_dir = self.cache_dir / "frames"
        if not self.frames_dir.is_dir():
            raise CacheError(f"Cached frames directory does not exist: {self.frames_dir}")
        missing = [
            self.frame_path(index)
            for index in range(len(self.metadata.frame_timestamps_s))
            if not self.frame_path(index).is_file()
        ]
        if missing:
            raise CacheError(
                f"Cache is missing {len(missing)} frame files, starting with {missing[0]}"
            )

    def frame_path(self, index: int) -> Path:
        if index < 0 or index >= len(self.metadata.frame_timestamps_s):
            raise IndexError(f"Cached frame index out of range: {index}")
        return self.frames_dir / f"{index:06d}.jpg"

    def read_frame(self, index: int) -> Any:
        try:
            import cv2
            import torch
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "OpenCV and PyTorch are required to load the dataset. "
                "Run `uv sync` to install the project dependencies."
            ) from exc

        image = cv2.imread(str(self.frame_path(index)), cv2.IMREAD_COLOR)
        if image is None:
            raise CacheError(
                "OpenCV could not read cached frame. "
                "Check the cache files and OpenCV image support: "
                f"{self.frame_path(index)}"
            )
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        if image.shape[:2] != (self.metadata.frame_size, self.metadata.frame_size):
            raise CacheError(
                f"Cached frame has unexpected shape {image.shape[:2]}: {self.frame_path(index)}"
            )
        return torch.from_numpy(image).permute(2, 0, 1)


def samples_for_cache(
    cache_dir: str | Path,
    event_times_s: Sequence[float],
    *,
    positive_window_s: float = 0.45,
    past_exclusion_s: float = 1.8,
    future_exclusion_s: float = 0.8,
    negative_to_positive_ratio: int = 3,
    seed: int = 42,
) -> list[DatasetSample]:
    cache_path = Path(cache_dir)
    metadata = load_cache_metadata(cache_path)
    times = build_training_times(
        metadata.frame_timestamps_s,
        event_times_s,
        positive_window_s=positive_window_s,
        past_exclusion_s=past_exclusion_s,
        future_exclusion_s=future_exclusion_s,
        negative_to_positive_ratio=negative_to_positive_ratio,
        seed=seed,
    )
    return _dataset_samples(cache_path, metadata, times)


def inference_samples_for_cache(
    cache_dir: str | Path,
    *,
    stride_s: float = 0.125,
    event_times_s: Sequence[float] | None = None,
    positive_window_s: float = 0.45,
) -> list[DatasetSample]:
    cache_path = Path(cache_dir)
    metadata = load_cache_metadata(cache_path)
    times = (
        LabeledTime(
            time_s=time_s,
            label=(
                1.0
                if event_times_s is not None
                and is_positive_time(
                    time_s,
                    event_times_s,
                    positive_window_s=positive_window_s,
                )
                else 0.0
            ),
        )
        for time_s in build_inference_times(metadata.duration_s, stride_s=stride_s)
    )
    return _dataset_samples(cache_path, metadata, times)


def _dataset_samples(
    cache_dir: Path,
    metadata: CacheMetadata,
    times: Sequence[LabeledTime] | Any,
) -> list[DatasetSample]:
    return [
        DatasetSample(
            source_video=metadata.source_video,
            cache_dir=cache_dir,
            decision_time_s=sample.time_s,
            label=sample.label,
        )
        for sample in times
    ]


def samples_for_annotation(
    cache_dir: str | Path,
    annotation: VideoAnnotation,
    **sampling_options: Any,
) -> list[DatasetSample]:
    return samples_for_cache(
        cache_dir,
        [event.time_s for event in annotation.events],
        **sampling_options,
    )


class CausalClipDataset:
    """A PyTorch dataset that returns causal clips with shape [8, 3, 224, 224]."""

    def __init__(
        self,
        samples: Sequence[DatasetSample],
        *,
        offsets_s: Sequence[float] = DEFAULT_CLIP_OFFSETS_S,
    ) -> None:
        try:
            import torch
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "PyTorch is required to create the dataset. "
                "Run `uv sync` to install the project dependencies."
            ) from exc

        self.samples = tuple(samples)
        self.offsets_s = tuple(offsets_s)
        self._stores: dict[Path, CachedFrameStore] = {}
        self._torch = torch

    def __len__(self) -> int:
        return len(self.samples)

    def _store_for(self, cache_dir: Path) -> CachedFrameStore:
        key = cache_dir.resolve()
        if key not in self._stores:
            self._stores[key] = CachedFrameStore(key)
        return self._stores[key]

    def __getitem__(self, index: int) -> tuple[Any, Any]:
        sample = self.samples[index]
        store = self._store_for(sample.cache_dir)
        frame_indices = select_frame_indices(
            store.metadata.frame_timestamps_s,
            sample.decision_time_s,
            offsets_s=self.offsets_s,
        )
        clip = self._torch.stack([store.read_frame(frame_index) for frame_index in frame_indices])
        label = self._torch.tensor(sample.label, dtype=self._torch.float32)
        return clip, label


VideoDataset = CausalClipDataset
