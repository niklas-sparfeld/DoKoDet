from __future__ import annotations

import random
import warnings
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from math import isfinite
from typing import Sequence

DEFAULT_CLIP_OFFSETS_S: tuple[float, ...] = (
    -1.4,
    -1.2,
    -1.0,
    -0.8,
    -0.6,
    -0.4,
    -0.2,
    0.0,
)


class SamplingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LabeledTime:
    time_s: float
    label: float
    label_state: str = "negative"


LABEL_POSITIVE = "positive"
LABEL_NEGATIVE = "negative"
LABEL_IGNORE = "ignore"
LABEL_CONFIRMED_HARD_NEGATIVE = "confirmed_hard_negative"


def label_state_for_time(
    decision_time_s: float,
    event_times_s: Sequence[float],
    *,
    positive_window_s: float = 0.45,
    past_exclusion_s: float = 1.8,
    future_exclusion_s: float = 0.8,
    confirmed_hard_negative_times_s: Sequence[float] = (),
    hard_negative_tolerance_s: float = 1e-6,
) -> str:
    """Classify one decision time with shared train and validation semantics."""
    if any(
        abs(decision_time_s - time_s) <= hard_negative_tolerance_s
        for time_s in confirmed_hard_negative_times_s
    ):
        if is_positive_time(decision_time_s, event_times_s, positive_window_s=positive_window_s):
            raise SamplingError("Confirmed hard negatives cannot overlap positive windows.")
        return LABEL_CONFIRMED_HARD_NEGATIVE
    if is_positive_time(decision_time_s, event_times_s, positive_window_s=positive_window_s):
        return LABEL_POSITIVE
    if is_clean_negative_time(
        decision_time_s,
        event_times_s,
        past_exclusion_s=past_exclusion_s,
        future_exclusion_s=future_exclusion_s,
    ):
        return LABEL_NEGATIVE
    return LABEL_IGNORE


def label_for_state(label_state: str) -> float:
    if label_state == LABEL_POSITIVE:
        return 1.0
    if label_state in {LABEL_NEGATIVE, LABEL_CONFIRMED_HARD_NEGATIVE}:
        return 0.0
    if label_state == LABEL_IGNORE:
        return -1.0
    raise SamplingError(f"Unknown label state: {label_state}")


def _validate_timestamps(frame_timestamps_s: Sequence[float]) -> None:
    if not frame_timestamps_s:
        raise SamplingError("At least one cached frame timestamp is required.")
    if any(not isfinite(value) or value < 0.0 for value in frame_timestamps_s):
        raise SamplingError("Cached frame timestamps must be finite and non-negative.")
    if any(
        current < previous
        for previous, current in zip(frame_timestamps_s, frame_timestamps_s[1:], strict=False)
    ):
        raise SamplingError("Cached frame timestamps must be sorted.")


def _validate_offsets(offsets_s: Sequence[float]) -> None:
    if not offsets_s:
        raise SamplingError("At least one clip offset is required.")
    if any(not isfinite(offset) or offset > 0.0 for offset in offsets_s):
        raise SamplingError("Clip offsets must be finite and must not use future frames.")
    if any(
        current < previous for previous, current in zip(offsets_s, offsets_s[1:], strict=False)
    ):
        raise SamplingError("Clip offsets must be sorted from low to high.")


def select_frame_indices(
    frame_timestamps_s: Sequence[float],
    decision_time_s: float,
    *,
    offsets_s: Sequence[float] = DEFAULT_CLIP_OFFSETS_S,
) -> tuple[int, ...]:
    """Select nearest cached frames without using a frame after the decision time."""
    _validate_timestamps(frame_timestamps_s)
    _validate_offsets(offsets_s)
    if not isfinite(decision_time_s) or decision_time_s < 0.0:
        raise SamplingError("Decision time must be finite and non-negative.")

    eligible_count = bisect_right(frame_timestamps_s, decision_time_s + 1e-9)
    if eligible_count == 0:
        raise SamplingError("No cached frame is available at or before the decision time.")

    selected: list[int] = []
    eligible_timestamps = frame_timestamps_s[:eligible_count]
    for offset_s in offsets_s:
        target_time_s = decision_time_s + offset_s
        right_index = bisect_left(eligible_timestamps, target_time_s)
        if right_index == 0:
            selected.append(0)
        elif right_index == eligible_count:
            selected.append(eligible_count - 1)
        else:
            left_index = right_index - 1
            left_distance = abs(eligible_timestamps[left_index] - target_time_s)
            right_distance = abs(eligible_timestamps[right_index] - target_time_s)
            selected.append(left_index if left_distance <= right_distance else right_index)

    return tuple(selected)


def select_frame_timestamps(
    frame_timestamps_s: Sequence[float],
    decision_time_s: float,
    *,
    offsets_s: Sequence[float] = DEFAULT_CLIP_OFFSETS_S,
) -> tuple[float, ...]:
    indices = select_frame_indices(
        frame_timestamps_s,
        decision_time_s,
        offsets_s=offsets_s,
    )
    return tuple(frame_timestamps_s[index] for index in indices)


def event_in_window(
    decision_time_s: float,
    event_times_s: Sequence[float],
    *,
    start_offset_s: float,
    end_offset_s: float,
) -> bool:
    if start_offset_s > end_offset_s:
        raise SamplingError("Window start must not be after its end.")
    start_s = decision_time_s + start_offset_s
    end_s = decision_time_s + end_offset_s
    return any(start_s <= event_time_s <= end_s for event_time_s in event_times_s)


def is_positive_time(
    decision_time_s: float,
    event_times_s: Sequence[float],
    *,
    positive_window_s: float = 0.45,
) -> bool:
    if positive_window_s < 0.0 or not isfinite(positive_window_s):
        raise SamplingError("positive_window_s must be finite and non-negative.")
    return event_in_window(
        decision_time_s,
        event_times_s,
        start_offset_s=-positive_window_s,
        end_offset_s=0.0,
    )


def is_clean_negative_time(
    decision_time_s: float,
    event_times_s: Sequence[float],
    *,
    past_exclusion_s: float = 1.8,
    future_exclusion_s: float = 0.8,
) -> bool:
    if (
        past_exclusion_s < 0.0
        or future_exclusion_s < 0.0
        or not isfinite(past_exclusion_s)
        or not isfinite(future_exclusion_s)
    ):
        raise SamplingError("Negative exclusion windows must be finite and non-negative.")
    return not event_in_window(
        decision_time_s,
        event_times_s,
        start_offset_s=-past_exclusion_s,
        end_offset_s=future_exclusion_s,
    )


def build_training_times(
    frame_timestamps_s: Sequence[float],
    event_times_s: Sequence[float],
    *,
    positive_window_s: float = 0.45,
    past_exclusion_s: float = 1.8,
    future_exclusion_s: float = 0.8,
    negative_to_positive_ratio: int = 3,
    seed: int = 42,
    confirmed_hard_negative_times_s: Sequence[float] = (),
) -> tuple[LabeledTime, ...]:
    """Build deterministic, approximately 1:3 positive/clean-negative samples."""
    _validate_timestamps(frame_timestamps_s)
    if negative_to_positive_ratio < 1:
        raise SamplingError("negative_to_positive_ratio must be at least 1.")

    labeled = [
        LabeledTime(
            time_s=time_s,
            label=label_for_state(
                label_state_for_time(
                    time_s,
                    event_times_s,
                    positive_window_s=positive_window_s,
                    past_exclusion_s=past_exclusion_s,
                    future_exclusion_s=future_exclusion_s,
                    confirmed_hard_negative_times_s=confirmed_hard_negative_times_s,
                )
            ),
            label_state=label_state_for_time(
                time_s,
                event_times_s,
                positive_window_s=positive_window_s,
                past_exclusion_s=past_exclusion_s,
                future_exclusion_s=future_exclusion_s,
                confirmed_hard_negative_times_s=confirmed_hard_negative_times_s,
            ),
        )
        for time_s in frame_timestamps_s
    ]
    positive_times = [sample for sample in labeled if sample.label_state == LABEL_POSITIVE]
    negative_times = [sample for sample in labeled if sample.label_state == LABEL_NEGATIVE]
    hard_negative_times = [
        sample for sample in labeled if sample.label_state == LABEL_CONFIRMED_HARD_NEGATIVE
    ]

    rng = random.Random(seed)
    rng.shuffle(negative_times)
    requested_negatives = len(positive_times) * negative_to_positive_ratio
    selected_negative_times = negative_times[:requested_negatives]
    if len(selected_negative_times) < requested_negatives:
        warnings.warn(
            "Requested positive-to-negative ratio cannot be reached with clean negatives.",
            UserWarning,
            stacklevel=2,
        )

    samples = [
        *positive_times,
        *selected_negative_times,
        *hard_negative_times,
    ]
    return tuple(sorted(samples, key=lambda sample: sample.time_s))


def build_labeled_times(
    frame_timestamps_s: Sequence[float],
    event_times_s: Sequence[float],
    *,
    positive_window_s: float = 0.45,
    past_exclusion_s: float = 1.8,
    future_exclusion_s: float = 0.8,
    confirmed_hard_negative_times_s: Sequence[float] = (),
) -> tuple[LabeledTime, ...]:
    """Return every decision time, including ignored transition samples."""
    _validate_timestamps(frame_timestamps_s)
    result = []
    for time_s in frame_timestamps_s:
        state = label_state_for_time(
            time_s,
            event_times_s,
            positive_window_s=positive_window_s,
            past_exclusion_s=past_exclusion_s,
            future_exclusion_s=future_exclusion_s,
            confirmed_hard_negative_times_s=confirmed_hard_negative_times_s,
        )
        result.append(LabeledTime(time_s=time_s, label=label_for_state(state), label_state=state))
    return tuple(result)


def build_inference_times(duration_s: float, *, stride_s: float = 0.125) -> tuple[float, ...]:
    if duration_s < 0.0 or not isfinite(duration_s):
        raise SamplingError("duration_s must be finite and non-negative.")
    if stride_s <= 0.0 or not isfinite(stride_s):
        raise SamplingError("stride_s must be finite and positive.")

    times: list[float] = []
    index = 0
    while True:
        time_s = index * stride_s
        if time_s > duration_s + 1e-9:
            break
        times.append(min(time_s, duration_s))
        index += 1
    return tuple(times)
