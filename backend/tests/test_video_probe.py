import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dokodetector_backend.video_probe import (
    VideoProbeError,
    probe_video_bytes,
    probe_video_path,
    probe_video_path_metadata,
)

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


def test_path_probe_counts_packets_without_decoding_every_frame() -> None:
    payload = {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "270.05"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "161640/5401",
                "nb_frames": "8082",
                "nb_read_packets": "8082",
                "duration": "270.05",
            }
        ],
    }

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        assert "-count_packets" in command
        assert "-count_frames" not in command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload).encode(),
            stderr=b"",
        )

    with patch("dokodetector_backend.video_probe.subprocess.run", side_effect=run):
        probe = probe_video_path(FIXTURE)

    assert probe.frame_count == 8082


def test_metadata_probe_reads_declared_frame_count_without_decoding_all_frames() -> None:
    payload = {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "270.05"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "161640/5401",
                "nb_frames": "8082",
                "duration": "270.05",
            }
        ],
    }

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        assert "-count_frames" not in command
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload).encode())

    with patch("dokodetector_backend.video_probe.subprocess.run", side_effect=run):
        probe = probe_video_path_metadata(FIXTURE)

    assert probe.nominal_frame_rate == pytest.approx(29.93, abs=0.01)
    assert probe.frame_count == 8082


def test_metadata_probe_accepts_hevc_quicktime_source() -> None:
    payload = {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "90.72"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "3262800/54433",
                "nb_frames": "5438",
                "duration": "90.72",
            }
        ],
    }

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        assert "-count_frames" not in command
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload).encode())

    with patch("dokodetector_backend.video_probe.subprocess.run", side_effect=run):
        probe = probe_video_path_metadata(FIXTURE)

    assert probe.video_codec == "hevc"
    assert probe.width == 1920
    assert probe.height == 1080
    assert probe.duration_ms == 90720
    assert probe.frame_count == 5438
