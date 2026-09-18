from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from doko_operations.intake import inspect_repository
from doko_operations.round_split import (
    RoundBoundary,
    RoundSplitMetadata,
    VideoPart,
    _TimelineReader,
    materialize_rounds,
    round_pieces,
    suggest_identifiers,
)

ROOT = Path(__file__).parents[2]
VIDEO = ROOT / "fixtures" / "evidence" / "v2" / "example-complete" / "snippet.mp4"


def test_round_pieces_span_input_videos() -> None:
    videos = (
        VideoPart(Path("first.mov"), 0.0, 10.0, 30.0, 3840, 2160),
        VideoPart(Path("second.mov"), 10.0, 5.0, 30.0, 3840, 2160),
    )

    pieces = round_pieces(videos, RoundBoundary(8.0, 12.0))

    assert [
        (piece.video.path.name, piece.offset_seconds, piece.duration_seconds) for piece in pieces
    ] == [
        ("first.mov", 8.0, 2.0),
        ("second.mov", 0.0, 2.0),
    ]


def test_timeline_reader_clamps_seek_to_the_last_readable_frame() -> None:
    class Capture:
        def __init__(self) -> None:
            self.positions: list[float] = []

        def isOpened(self) -> bool:
            return True

        def set(self, _property: int, position: float) -> None:
            self.positions.append(position)

        def read(self) -> tuple[bool, object]:
            return True, object()

        def release(self) -> None:
            return None

    class Cv2:
        CAP_PROP_POS_MSEC = 0

        def __init__(self) -> None:
            self.capture = Capture()

        def VideoCapture(self, _path: str) -> Capture:
            return self.capture

    video = VideoPart(Path("capture.mov"), 0.0, 10.0, 30.0, 3840, 2160)
    cv2 = Cv2()
    reader = _TimelineReader((video,), cv2)
    try:
        assert reader.read_at(video.end_seconds) is not None
        assert cv2.capture.positions == [(10.0 - 1 / 30.0) * 1000]
    finally:
        reader.close()


def test_suggest_identifiers_uses_video_creation_metadata(tmp_path: Path) -> None:
    video = tmp_path / "capture.mov"
    video.write_bytes(b"video")

    def fake_ffprobe(command, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {"format": {"tags": {"com.apple.quicktime.creationdate": "2024-03-02T18:45:00Z"}}}
            ),
            stderr="",
        )

    assert suggest_identifiers((video,), command_runner=fake_ffprobe) == (
        "session-2024-03-02",
        "game-2024-03-02-01",
    )


def test_materialize_rounds_publishes_valid_silent_1080p_bundle(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for round-split encoding")

    video = VideoPart(VIDEO, 0.0, 2.2, 15.0, 640, 360)
    metadata = RoundSplitMetadata(
        operator="Fixture Operator",
        session_id="session-round-split",
        game_id="game-round-split",
    )

    results = materialize_rounds(
        tmp_path,
        (video,),
        (RoundBoundary(0.1, 0.8),),
        metadata,
        ffmpeg_binary=ffmpeg,
    )

    assert len(results) == 1
    bundle = tmp_path / "data" / "intake" / "recordings" / "game-round-split-001"
    inspection = inspect_repository(
        tmp_path,
        bundle_root=bundle,
        pending_video_root=tmp_path / "empty-pending",
        evidence_package_root=tmp_path / "empty-evidence",
        artifacts_root=tmp_path / "empty-artifacts",
    )
    assert inspection.valid
    assert inspection.bundles[0].state == "complete"

    source = json.loads((bundle / "source-record.json").read_text())
    assert source["round_id"] == "round-001"
    assert source["game_id"] == "game-round-split"
    assert source["media_type"] == "video/quicktime"
    assert source["source_permission"] == "unrestricted"
    assert source["allowed_uses"] == ["train", "validation", "test", "evaluation"]
    enrollment = json.loads((bundle / "initial-task-enrollment.json").read_text())
    assert {item["operator"] for item in enrollment["enrollments"]} == {"Fixture Operator"}

    probe = shutil.which("ffprobe")
    assert probe is not None
    import subprocess

    result = subprocess.run(
        [
            probe,
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(bundle / "videos" / "game-round-split-001-video.mov"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = json.loads(result.stdout)["streams"]
    assert [stream["codec_type"] for stream in streams] == ["video"]
    assert streams[0]["height"] == 1080
