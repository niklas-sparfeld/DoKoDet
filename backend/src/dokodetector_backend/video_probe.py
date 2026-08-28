"""Probe accepted evidence video bytes with the local FFmpeg toolchain."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any


class VideoProbeError(ValueError):
    """The bytes are not a readable supported video."""


class UnsupportedVideoError(VideoProbeError):
    """The video is readable but uses unsupported media properties."""


class VideoProbeUnavailable(RuntimeError):
    """The local video probe tool is not available."""


@dataclass(frozen=True, slots=True)
class VideoProbe:
    """Technical values read from one video stream."""

    container: str
    video_codec: str
    width: int
    height: int
    nominal_frame_rate: float
    duration_ms: int
    frame_count: int


def probe_video_bytes(source: bytes, *, timeout_seconds: float = 5.0) -> VideoProbe:
    """Probe and count decoded frames in one bounded video byte sequence."""

    if not isinstance(source, bytes):
        raise TypeError("Video sources must be bytes.")

    return _probe_video("pipe:0", source, timeout_seconds=timeout_seconds)


def probe_video_path(path: str | Path, *, timeout_seconds: float = 5.0) -> VideoProbe:
    """Probe and count decoded frames from a local file without loading it into memory."""

    video_path = Path(path)
    if not video_path.is_file():
        raise VideoProbeError("The video file does not exist.")
    return _probe_video(str(video_path), None, timeout_seconds=timeout_seconds)


def _probe_video(input_path: str, source: bytes | None, *, timeout_seconds: float) -> VideoProbe:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise VideoProbeUnavailable("The local video probe tool is not installed.")

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_entries",
                "format=format_name,duration:stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,nb_read_frames,duration",
                "-show_format",
                "-show_streams",
                "-count_frames",
                "-i",
                input_path,
            ],
            input=source,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise VideoProbeError("The video probe timed out.") from error
    except OSError as error:
        raise VideoProbeUnavailable("The local video probe could not run.") from error

    if result.returncode != 0:
        raise VideoProbeError("The video bytes could not be decoded.")

    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise VideoProbeError("The video probe returned invalid data.") from error
    if not isinstance(payload, dict):
        raise VideoProbeError("The video probe returned invalid data.")

    format_payload = payload.get("format")
    streams = payload.get("streams")
    if not isinstance(format_payload, dict) or not isinstance(streams, list):
        raise VideoProbeError("The video probe did not return stream data.")

    format_names = {
        name.strip().lower() for name in str(format_payload.get("format_name", "")).split(",")
    }
    if "mp4" not in format_names:
        raise UnsupportedVideoError("The video container is not supported.")

    video_streams = [stream for stream in streams if _stream_type(stream) == "video"]
    if len(video_streams) != 1:
        raise UnsupportedVideoError("The video must contain exactly one video stream.")
    stream = video_streams[0]
    if str(stream.get("codec_name", "")).lower() != "h264":
        raise UnsupportedVideoError("The video codec is not supported.")

    width = _positive_int(stream.get("width"), "video width")
    height = _positive_int(stream.get("height"), "video height")
    frame_rate = _frame_rate(stream.get("avg_frame_rate"))
    duration_ms = _duration_ms(stream.get("duration") or format_payload.get("duration"))
    frame_count = _positive_int(stream.get("nb_read_frames"), "decoded video frames")
    declared_frame_count = _optional_positive_int(stream.get("nb_frames"))
    if declared_frame_count is not None and frame_count != declared_frame_count:
        raise VideoProbeError("The video does not contain all declared frames.")
    return VideoProbe(
        container="mp4",
        video_codec="h264",
        width=width,
        height=height,
        nominal_frame_rate=frame_rate,
        duration_ms=duration_ms,
        frame_count=frame_count,
    )


def _stream_type(stream: object) -> str:
    return str(stream.get("codec_type", "")).lower() if isinstance(stream, dict) else ""


def _positive_int(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise VideoProbeError(f"The probe did not return {label}.") from error
    if parsed <= 0:
        raise VideoProbeError(f"The probe did not return {label}.")
    return parsed


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise VideoProbeError("The probe returned an invalid frame count.") from error
    if parsed <= 0:
        raise VideoProbeError("The probe returned an invalid frame count.")
    return parsed


def _frame_rate(value: Any) -> float:
    try:
        parsed = float(Fraction(str(value)))
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise VideoProbeError("The probe did not return a valid frame rate.") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise VideoProbeError("The probe did not return a valid frame rate.")
    return parsed


def _duration_ms(value: Any) -> int:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as error:
        raise VideoProbeError("The probe did not return a valid duration.") from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise VideoProbeError("The probe did not return a valid duration.")
    return round(seconds * 1000)


__all__ = [
    "UnsupportedVideoError",
    "VideoProbe",
    "VideoProbeError",
    "VideoProbeUnavailable",
    "probe_video_bytes",
    "probe_video_path",
]
