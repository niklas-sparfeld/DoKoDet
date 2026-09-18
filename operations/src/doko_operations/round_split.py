"""Review a long game video and publish one intake bundle per round."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
PERMISSIONS = {"training_only", "training_and_evaluation", "project_use", "unrestricted"}
USES = {"train", "validation", "test", "evaluation"}
DEFAULT_SOURCE_PERMISSION = "unrestricted"
DEFAULT_ALLOWED_USES = ("train", "validation", "test", "evaluation")
TASKS = ("cardevent_event_detection", "table_evidence_analysis")
EPSILON = 1e-6


class RoundSplitError(ValueError):
    """Raised when a round split cannot be selected or published safely."""


@dataclass(frozen=True, slots=True)
class VideoPart:
    """One input video and its position in the combined timeline."""

    path: Path
    start_seconds: float
    duration_seconds: float
    fps: float
    width: int
    height: int

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds


@dataclass(frozen=True, slots=True)
class RoundBoundary:
    """One half-open interval in the combined input timeline."""

    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise RoundSplitError("round end must be after round start")


@dataclass(frozen=True, slots=True)
class RoundSplitMetadata:
    """Operator metadata shared by all rounds in one game."""

    operator: str
    session_id: str
    game_id: str
    source_permission: str = DEFAULT_SOURCE_PERMISSION
    allowed_uses: tuple[str, ...] = DEFAULT_ALLOWED_USES
    recording_prefix: str | None = None
    round_id_prefix: str = "round"
    table_setup: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operator, str) or not self.operator.strip():
            raise RoundSplitError("operator must be non-empty text")
        for field in ("session_id", "game_id", "round_id_prefix"):
            _identifier(getattr(self, field), field)
        if self.recording_prefix is not None:
            _identifier(self.recording_prefix, "recording_prefix")
        if self.source_permission not in PERMISSIONS:
            raise RoundSplitError("source_permission is invalid")
        if (
            not self.allowed_uses
            or len(set(self.allowed_uses)) != len(self.allowed_uses)
            or any(use not in USES for use in self.allowed_uses)
        ):
            raise RoundSplitError("allowed_uses must contain unique supported values")
        if self.table_setup is not None:
            _identifier(self.table_setup, "table_setup")
        if self.notes is not None and not self.notes:
            raise RoundSplitError("notes must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class RoundSplitResult:
    """One published recording bundle."""

    recording_id: str
    round_id: str
    bundle_path: Path
    start_seconds: float
    end_seconds: float
    source_sha256: str

    def to_mapping(self, repository_root: str | Path) -> dict[str, Any]:
        root = Path(repository_root).expanduser().resolve()
        try:
            bundle = self.bundle_path.resolve().relative_to(root)
            bundle_path = bundle.as_posix()
        except ValueError:
            bundle_path = str(self.bundle_path.resolve())
        return {
            "recording_id": self.recording_id,
            "round_id": self.round_id,
            "bundle_path": bundle_path,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class RoundPiece:
    """The part of an input video that belongs to one round."""

    video: VideoPart
    offset_seconds: float
    duration_seconds: float


def probe_videos(video_paths: Sequence[str | Path]) -> tuple[VideoPart, ...]:
    """Read the input timeline metadata with OpenCV."""

    if not video_paths:
        raise RoundSplitError("at least one video is required")
    try:
        import cv2
    except ImportError as error:  # pragma: no cover - dependency is declared by operations
        raise RoundSplitError("OpenCV is required for round selection") from error

    result: list[VideoPart] = []
    timeline_start = 0.0
    for raw_path in video_paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise RoundSplitError(f"input video was not found: {path}")
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise RoundSplitError(f"OpenCV could not open input video: {path}")
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            capture.release()
        if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
            raise RoundSplitError(f"input video has no usable frame metadata: {path}")
        duration = frame_count / fps
        result.append(VideoPart(path, timeline_start, duration, fps, width, height))
        timeline_start += duration
    return tuple(result)


def suggest_identifiers(
    video_paths: Sequence[str | Path],
    *,
    ffprobe_binary: str = "ffprobe",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, str]:
    """Suggest a session ID and game ID from the first input video's date metadata."""

    if not video_paths:
        raise RoundSplitError("at least one video is required")
    path = Path(video_paths[0]).expanduser().resolve()
    if not path.is_file():
        raise RoundSplitError(f"input video was not found: {path}")
    recorded_at = _embedded_creation_time(path, ffprobe_binary, command_runner)
    if recorded_at is None:
        recorded_at = _file_metadata_time(path)
    date = recorded_at.date().isoformat()
    return f"session-{date}", f"game-{date}-01"


def round_pieces(videos: Sequence[VideoPart], boundary: RoundBoundary) -> tuple[RoundPiece, ...]:
    """Map one combined-timeline round to source-video pieces."""

    pieces: list[RoundPiece] = []
    for video in videos:
        start = max(boundary.start_seconds, video.start_seconds)
        end = min(boundary.end_seconds, video.end_seconds)
        if end - start <= EPSILON:
            continue
        pieces.append(
            RoundPiece(
                video=video,
                offset_seconds=start - video.start_seconds,
                duration_seconds=end - start,
            )
        )
    if not pieces:
        raise RoundSplitError("round is outside the input video timeline")
    return tuple(pieces)


def select_rounds(
    videos: Sequence[VideoPart],
    *,
    window_name: str = "DokoDetector round splitter",
) -> tuple[RoundBoundary, ...]:
    """Open an OpenCV review window and collect S/E round boundaries."""

    if not videos:
        raise RoundSplitError("at least one video is required")
    try:
        import cv2
    except ImportError as error:  # pragma: no cover - dependency is declared by operations
        raise RoundSplitError("OpenCV is required for round selection") from error

    total_duration = videos[-1].end_seconds
    last_readable_time = _last_readable_time(videos)
    current = 0.0
    start: float | None = None
    boundaries: list[RoundBoundary] = []
    paused = True
    status = "S=start E=end Space=play/pause Q=finish"
    reader = _TimelineReader(videos, cv2)
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, min(1280, videos[0].width), min(720, videos[0].height))
    try:
        while True:
            frame = reader.read_at(current)
            if frame is None:
                raise RoundSplitError(f"could not read the input video at {current:.3f}s")
            display = _fit_frame(frame, 1280, 720, cv2)
            _draw_overlay(display, current, total_duration, start, boundaries, status, cv2)
            cv2.imshow(window_name, display)
            delay = 0 if paused else max(1, round(1000 / reader.fps_at(current)))
            key = cv2.waitKeyEx(delay)
            if key < 0:
                current = min(last_readable_time, current + 1 / reader.fps_at(current))
                if current >= last_readable_time - EPSILON:
                    paused = True
                continue

            if key == 27:
                raise RoundSplitError("round selection cancelled")
            if key in {ord("q"), ord("Q"), 13}:
                if start is not None:
                    raise RoundSplitError("round start is open; press E before finishing")
                if not boundaries:
                    raise RoundSplitError("no rounds were selected")
                return tuple(boundaries)
            if key == ord(" "):
                paused = not paused
                continue

            lower = key & 0xFF
            if lower == ord("s"):
                if start is not None:
                    status = "A round start is already set. Press E first."
                elif boundaries and current < boundaries[-1].end_seconds - EPSILON:
                    status = "The next start must be after the previous end."
                else:
                    start = current
                    paused = True
                    status = f"Round {len(boundaries) + 1} start: {_format_time(current)}"
                continue
            if lower == ord("e"):
                if start is None:
                    status = "Press S before E."
                elif current <= start + EPSILON:
                    status = "The round end must be after the start."
                else:
                    boundaries.append(RoundBoundary(start, current))
                    status = (
                        f"Saved round {len(boundaries)}: "
                        f"{_format_time(start)} - {_format_time(current)}"
                    )
                    start = None
                    paused = True
                continue

            seek = _seek_seconds(key)
            if seek is not None:
                current = min(last_readable_time, max(0.0, current + seek))
                paused = True
                continue
    finally:
        reader.close()
        cv2.destroyWindow(window_name)


def materialize_rounds(
    repository_root: str | Path,
    videos: Sequence[VideoPart],
    boundaries: Sequence[RoundBoundary],
    metadata: RoundSplitMetadata,
    *,
    intake_root: str | Path | None = None,
    ffmpeg_binary: str = "ffmpeg",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now: datetime | None = None,
) -> tuple[RoundSplitResult, ...]:
    """Encode and publish one canonical recording bundle for each selected round."""

    if not videos:
        raise RoundSplitError("at least one video is required")
    if not boundaries:
        raise RoundSplitError("at least one round is required")
    root = Path(repository_root).expanduser().resolve()
    output_root = Path(intake_root or root / "data" / "intake" / "recordings").expanduser()
    if not output_root.is_absolute():
        output_root = root / output_root
    output_root = output_root.resolve()
    ffmpeg = _resolve_ffmpeg(ffmpeg_binary)
    prefix = metadata.recording_prefix or metadata.game_id
    recording_ids = tuple(f"{prefix}-{index:03d}" for index in range(1, len(boundaries) + 1))
    if len(set(recording_ids)) != len(recording_ids):
        raise RoundSplitError("generated recording IDs are not unique")
    existing = [
        output_root / recording_id
        for recording_id in recording_ids
        if (output_root / recording_id).exists()
    ]
    if existing:
        raise RoundSplitError(f"recording bundle already exists: {existing[0]}")

    output_root.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".round-split-", dir=output_root))
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    results: list[RoundSplitResult] = []
    try:
        for index, boundary in enumerate(boundaries, start=1):
            if boundary.end_seconds > videos[-1].end_seconds + EPSILON:
                raise RoundSplitError("round end is outside the input video timeline")
            recording_id = f"{prefix}-{index:03d}"
            round_id = f"{metadata.round_id_prefix}-{index:03d}"
            source_asset_id = f"{recording_id}-source"
            video_id = f"{recording_id}-video"
            bundle = staging_root / recording_id
            video_dir = bundle / "videos"
            video_dir.mkdir(parents=True)
            output_video = video_dir / f"{video_id}.mov"
            _encode_round(
                round_pieces(videos, boundary),
                output_video,
                ffmpeg,
                command_runner,
                staging_root / f"pieces-{index:03d}",
                target_fps=videos[0].fps,
            )
            digest = _sha256_file(output_video)
            source_record = _source_record(
                metadata,
                source_asset_id=source_asset_id,
                recording_id=recording_id,
                video_id=video_id,
                round_id=round_id,
                video_path=output_video,
                digest=digest,
                boundary=boundary,
                videos=videos,
            )
            enrollment = _task_enrollment(source_asset_id, metadata.operator, timestamp)
            source_bytes = _json_bytes(source_record)
            enrollment_bytes = _json_bytes(enrollment)
            (bundle / "source-record.json").write_bytes(source_bytes)
            (bundle / "initial-task-enrollment.json").write_bytes(enrollment_bytes)
            manifest = _repository_manifest(
                source_asset_id,
                recording_id,
                video_id,
                metadata.session_id,
                output_video,
                digest,
                source_bytes,
                enrollment_bytes,
            )
            (bundle / "manifest.json").write_bytes(_json_bytes(manifest))
            _validate_bundle(root, bundle, staging_root)
            results.append(
                RoundSplitResult(
                    recording_id,
                    round_id,
                    output_root / recording_id,
                    boundary.start_seconds,
                    boundary.end_seconds,
                    digest,
                )
            )
        for result in results:
            (staging_root / result.recording_id).rename(output_root / result.recording_id)
    except BaseException:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    shutil.rmtree(staging_root, ignore_errors=True)
    return tuple(results)


class _TimelineReader:
    def __init__(self, videos: Sequence[VideoPart], cv2_module: Any) -> None:
        self.videos = videos
        self.cv2 = cv2_module
        self.capture: Any = None
        self.capture_index: int | None = None
        self.last_seconds: float | None = None

    def read_at(self, seconds: float) -> Any:
        index = min(
            len(self.videos) - 1,
            next(
                (i for i, video in enumerate(self.videos) if seconds < video.end_seconds),
                len(self.videos) - 1,
            ),
        )
        video = self.videos[index]
        if self.capture_index != index:
            self.close_capture()
            self.capture = self.cv2.VideoCapture(str(video.path))
            self.capture_index = index
        if self.capture is None or not self.capture.isOpened():
            return None
        sequential = (
            self.last_seconds is not None
            and abs(seconds - (self.last_seconds + 1 / video.fps)) <= 0.25 / video.fps
        )
        if sequential:
            ok, frame = self.capture.read()
        else:
            local_seconds = min(
                max(0.0, seconds - video.start_seconds),
                max(0.0, video.duration_seconds - 1 / video.fps),
            )
            self.capture.set(
                self.cv2.CAP_PROP_POS_MSEC,
                local_seconds * 1000,
            )
            ok, frame = self.capture.read()
        self.last_seconds = seconds if ok else None
        return frame if ok else None

    def fps_at(self, seconds: float) -> float:
        return next(
            (video.fps for video in self.videos if seconds < video.end_seconds), self.videos[-1].fps
        )

    def close_capture(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.capture_index = None
        self.last_seconds = None

    def close(self) -> None:
        self.close_capture()


def _last_readable_time(videos: Sequence[VideoPart]) -> float:
    return max(0.0, videos[-1].end_seconds - 1 / videos[-1].fps)


def _fit_frame(frame: Any, max_width: int, max_height: int, cv2_module: Any) -> Any:
    height, width = frame.shape[:2]
    scale = min(max_width / width, max_height / height, 1.0)
    if scale == 1.0:
        return frame
    return cv2_module.resize(frame, (round(width * scale), round(height * scale)))


def _draw_overlay(
    frame: Any,
    current: float,
    total: float,
    start: float | None,
    boundaries: Sequence[RoundBoundary],
    status: str,
    cv2_module: Any,
) -> None:
    lines = [
        f"{_format_time(current)} / {_format_time(total)}  rounds: {len(boundaries)}",
        f"S start: {_format_time(start) if start is not None else '-'}  {status}",
        "H/L +/-1s  J/K +/-10s  Space play/pause  Q finish  Esc cancel",
    ]
    for index, line in enumerate(lines):
        cv2_module.putText(
            frame,
            line,
            (16, 30 + index * 28),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
            cv2_module.LINE_AA,
        )


def _seek_seconds(key: int) -> float | None:
    if key in {2424832, ord("h")}:
        return -1.0
    if key in {2555904, ord("l")}:
        return 1.0
    if key in {2490368, ord("j")}:
        return -10.0
    if key in {2621440, ord("k")}:
        return 10.0
    return None


def _encode_round(
    pieces: Sequence[RoundPiece],
    output: Path,
    ffmpeg: str,
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
    temporary_root: Path,
    *,
    target_fps: float,
) -> None:
    temporary_root.mkdir(parents=True)
    rendered: list[Path] = []
    try:
        for index, piece in enumerate(pieces):
            rendered_path = temporary_root / f"piece-{index:03d}.mov"
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{piece.offset_seconds:.6f}",
                "-i",
                str(piece.video.path),
                "-t",
                f"{piece.duration_seconds:.6f}",
                "-vf",
                "scale=-2:1080:flags=lanczos",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                f"{target_fps:.6f}",
                "-movflags",
                "+faststart",
                str(rendered_path),
            ]
            _run_ffmpeg(command_runner, command)
            if not rendered_path.is_file() or rendered_path.stat().st_size == 0:
                raise RoundSplitError(f"ffmpeg did not create {rendered_path.name}")
            rendered.append(rendered_path)
        if len(rendered) == 1:
            shutil.copyfile(rendered[0], output)
            return
        list_path = temporary_root / "concat.txt"
        list_path.write_text(
            "".join(
                f"file '{path.as_posix().replace(chr(39), chr(39) + chr(39))}'\n"
                for path in rendered
            ),
            encoding="utf-8",
        )
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(output),
        ]
        _run_ffmpeg(command_runner, command)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _run_ffmpeg(
    command_runner: Callable[..., subprocess.CompletedProcess[str]], command: Sequence[str]
) -> None:
    try:
        completed = command_runner(command, capture_output=True, text=True)
    except OSError as error:
        raise RoundSplitError(f"could not run ffmpeg: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
        raise RoundSplitError(f"ffmpeg failed: {detail}")


def _validate_bundle(repository_root: Path, bundle: Path, staging_root: Path) -> None:
    from .intake import inspect_repository

    inspection = inspect_repository(
        repository_root,
        bundle_root=bundle,
        pending_video_root=staging_root / ".pending",
        evidence_package_root=staging_root / ".evidence",
        artifacts_root=staging_root / ".artifacts",
    )
    if not inspection.valid or not inspection.bundles or inspection.bundles[0].state != "complete":
        messages = [failure.message for failure in inspection.failures]
        raise RoundSplitError(
            "generated recording bundle failed validation"
            + (f": {'; '.join(messages)}" if messages else "")
        )


def _source_record(
    metadata: RoundSplitMetadata,
    *,
    source_asset_id: str,
    recording_id: str,
    video_id: str,
    round_id: str,
    video_path: Path,
    digest: str,
    boundary: RoundBoundary,
    videos: Sequence[VideoPart],
) -> dict[str, Any]:
    source_names = ", ".join(video.path.name for video in videos)
    split_note = (
        f"Manual round split from {source_names}; timeline "
        f"{_format_time(boundary.start_seconds)}-{_format_time(boundary.end_seconds)}."
    )
    notes = f"{metadata.notes} {split_note}" if metadata.notes else split_note
    return {
        "schema_version": "source-record/v1",
        "source_asset_id": source_asset_id,
        "sha256": digest,
        "byte_length": video_path.stat().st_size,
        "media_type": "video/quicktime",
        "original_filename": video_path.name,
        "acquisition_method": "manual_round_split",
        "source_permission": metadata.source_permission,
        "allowed_uses": list(metadata.allowed_uses),
        "session_id": metadata.session_id,
        "recording_id": recording_id,
        "video_id": video_id,
        "game_id": metadata.game_id,
        "round_id": round_id,
        "table_setup": metadata.table_setup,
        "content_type": "real_game",
        "retention_state": "active",
        "notes": notes,
    }


def _task_enrollment(source_asset_id: str, operator: str, created_at: datetime) -> dict[str, Any]:
    timestamp = created_at.isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "task-enrollment/v1",
        "source_asset_id": source_asset_id,
        "enrollments": [
            {
                "task_enrollment_id": f"{source_asset_id}-{task}",
                "task": task,
                "disposition": "selected",
                "lifecycle_state": "intake",
                "operator": operator,
                "created_at_utc": timestamp,
                "reason": None,
            }
            for task in TASKS
        ],
    }


def _repository_manifest(
    source_asset_id: str,
    recording_id: str,
    video_id: str,
    session_id: str,
    video_path: Path,
    digest: str,
    source_bytes: bytes,
    enrollment_bytes: bytes,
) -> dict[str, Any]:
    return {
        "schema_version": "repository-bundle/v1",
        "source_asset_id": source_asset_id,
        "recording_id": recording_id,
        "video_id": video_id,
        "session_id": session_id,
        "state": "complete",
        "source_sha256": digest,
        "files": {
            "video": {
                "relative_path": f"videos/{video_path.name}",
                "type": "video/quicktime",
                "byte_length": video_path.stat().st_size,
                "sha256": digest,
            },
            "source_record": {
                "relative_path": "source-record.json",
                "type": "application/json",
                "byte_length": len(source_bytes),
                "sha256": _sha256_bytes(source_bytes),
            },
            "task_enrollment": {
                "relative_path": "initial-task-enrollment.json",
                "type": "application/json",
                "byte_length": len(enrollment_bytes),
                "sha256": _sha256_bytes(enrollment_bytes),
            },
            "proposal_generator_runs": [],
        },
    }


def _resolve_ffmpeg(binary: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise RoundSplitError(f"ffmpeg was not found: {binary}")
    return resolved


def _embedded_creation_time(
    path: Path,
    ffprobe_binary: str,
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> datetime | None:
    command = [
        ffprobe_binary,
        "-v",
        "error",
        "-show_entries",
        "format_tags=creation_time,com.apple.quicktime.creationdate:stream_tags=creation_time,com.apple.quicktime.creationdate",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = command_runner(command, capture_output=True, text=True)
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None
    tags: list[dict[str, Any]] = []
    format_tags = payload.get("format", {}).get("tags", {})
    if isinstance(format_tags, dict):
        tags.append(format_tags)
    for stream in payload.get("streams", []):
        stream_tags = stream.get("tags", {}) if isinstance(stream, dict) else {}
        if isinstance(stream_tags, dict):
            tags.append(stream_tags)
    for tag_set in tags:
        for key, value in tag_set.items():
            if key.lower() in {"creation_time", "com.apple.quicktime.creationdate"}:
                parsed = _parse_metadata_time(value)
                if parsed is not None:
                    return parsed
    return None


def _file_metadata_time(path: Path) -> datetime:
    stat = path.stat()
    timestamp = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return datetime.fromtimestamp(timestamp, timezone.utc)


def _parse_metadata_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise RoundSplitError(f"{field} must be a safe identifier")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: Any) -> bytes:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (serialized + "\n").encode("utf-8")


def _format_time(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


__all__ = [
    "RoundBoundary",
    "RoundPiece",
    "RoundSplitError",
    "RoundSplitMetadata",
    "RoundSplitResult",
    "VideoPart",
    "DEFAULT_ALLOWED_USES",
    "DEFAULT_SOURCE_PERMISSION",
    "materialize_rounds",
    "probe_videos",
    "round_pieces",
    "select_rounds",
    "suggest_identifiers",
]
