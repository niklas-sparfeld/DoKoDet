from __future__ import annotations

import pytest

from cardevent.sampling import (
    LABEL_CONFIRMED_HARD_NEGATIVE,
    LABEL_IGNORE,
    build_training_times,
    is_clean_negative_time,
    is_positive_time,
    label_state_for_time,
    select_frame_indices,
    select_frame_timestamps,
)


def test_causal_sampler_never_selects_a_future_frame() -> None:
    timestamps = (0.0, 0.1, 0.2, 0.3)

    indices = select_frame_indices(
        timestamps,
        0.15,
        offsets_s=(-0.2, -0.1, 0.0),
    )

    assert indices == (0, 0, 1)
    assert all(timestamps[index] <= 0.15 for index in indices)


def test_sampler_uses_nearest_cached_frame() -> None:
    timestamps = (0.0, 0.1, 0.2, 0.3)

    selected = select_frame_timestamps(timestamps, 0.25, offsets_s=(-0.1, 0.0))

    assert selected == (0.1, 0.2)


def test_sampler_repeats_the_first_frame_near_video_start() -> None:
    selected = select_frame_timestamps(
        (0.0, 0.1, 0.2),
        0.0,
        offsets_s=(-1.4, -0.2, 0.0),
    )

    assert selected == (0.0, 0.0, 0.0)


def test_positive_and_negative_windows_use_only_the_defined_intervals() -> None:
    events = (10.0,)

    assert is_positive_time(10.4, events, positive_window_s=0.45)
    assert not is_positive_time(10.5, events, positive_window_s=0.45)
    assert not is_clean_negative_time(11.0, events, past_exclusion_s=1.8, future_exclusion_s=0.8)
    assert is_clean_negative_time(12.0, events, past_exclusion_s=1.8, future_exclusion_s=0.8)


def test_training_times_are_approximately_one_to_three() -> None:
    samples = build_training_times(
        tuple(index / 10.0 for index in range(100)),
        (5.0, 8.0),
        negative_to_positive_ratio=3,
    )

    positives = [sample for sample in samples if sample.label == 1.0]
    negatives = [sample for sample in samples if sample.label == 0.0]
    assert positives
    assert len(negatives) == len(positives) * 3
    assert all(not (4.55 <= sample.time_s <= 5.8) for sample in negatives)


def test_sampler_rejects_future_offsets() -> None:
    with pytest.raises(ValueError, match="future frames"):
        select_frame_indices((0.0, 0.1), 0.1, offsets_s=(0.0, 0.1))


def test_three_way_labels_ignore_transitions_and_hard_negatives_override_them() -> None:
    assert label_state_for_time(10.6, (10.0,)) == LABEL_IGNORE
    assert (
        label_state_for_time(10.6, (10.0,), confirmed_hard_negative_times_s=(10.6,))
        == LABEL_CONFIRMED_HARD_NEGATIVE
    )


def test_training_sampler_warns_when_clean_negative_ratio_is_unattainable() -> None:
    with pytest.warns(UserWarning, match="ratio cannot be reached"):
        samples = build_training_times(
            (0.0, 0.1, 0.2, 0.3, 0.4),
            (0.2,),
            negative_to_positive_ratio=3,
        )
    assert samples
