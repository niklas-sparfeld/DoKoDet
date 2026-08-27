from pathlib import Path

import pytest

from dokodetector_backend.video_probe import VideoProbeError, probe_video_bytes

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "evidence" / "v2" / "example-complete" / "snippet.mp4"
)


def test_probe_counts_the_canonical_video_fixture() -> None:
    probe = probe_video_bytes(FIXTURE.read_bytes())

    assert probe.container == "mp4"
    assert probe.video_codec == "h264"
    assert (probe.width, probe.height) == (640, 360)
    assert probe.nominal_frame_rate == 15.0
    assert probe.duration_ms == 2133
    assert probe.frame_count == 32


def test_probe_rejects_truncated_video() -> None:
    with pytest.raises(VideoProbeError):
        probe_video_bytes(FIXTURE.read_bytes()[:-100])
