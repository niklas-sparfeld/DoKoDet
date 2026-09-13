"""Generate and cache one small JPEG frame for each accepted recording."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class RecordingThumbnailError(RuntimeError):
    """A recording thumbnail could not be generated or stored."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
THUMBNAIL_WIDTH = 640
THUMBNAIL_HEIGHT = 360
THUMBNAIL_QUALITY = 6
THUMBNAIL_TIMEOUT_SECONDS = 30.0


class RecordingThumbnailCache:
    """Store disposable JPEG thumbnails keyed by immutable source-video identity."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def path(self, source_sha256: str) -> Path:
        """Return the cache path for one accepted source digest."""

        _validate_digest(source_sha256)
        return self.root / f"{source_sha256}.jpg"

    def read(self, source_sha256: str) -> bytes | None:
        """Read one cached thumbnail without opening its source video."""

        path = self.path(source_sha256)
        try:
            content = path.read_bytes()
        except OSError:
            return None
        return content or None

    def ensure(self, source_sha256: str, video_path: str | Path) -> bytes:
        """Return a cached thumbnail, generating the first source frame on a miss."""

        cached = self.read(source_sha256)
        if cached is not None:
            return cached

        content = _render_first_frame(Path(video_path), timeout_seconds=THUMBNAIL_TIMEOUT_SECONDS)
        self._write(source_sha256, content)
        return content

    def _write(self, source_sha256: str, content: bytes) -> None:
        destination = self.path(source_sha256)
        if not isinstance(content, bytes) or not content:
            raise RecordingThumbnailError("thumbnail content must be non-empty bytes")

        temporary_path: Path | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.root.is_dir():
                raise RecordingThumbnailError(
                    f"thumbnail cache root is not a directory: {self.root}"
                )
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".thumbnail-",
                suffix=".jpg",
                dir=self.root,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
        except (OSError, RecordingThumbnailError) as error:
            raise RecordingThumbnailError("thumbnail cache write failed") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _render_first_frame(video_path: Path, *, timeout_seconds: float) -> bytes:
    if not video_path.is_file():
        raise RecordingThumbnailError("the source recording video is unavailable")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RecordingThumbnailError("ffmpeg is not installed")

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-vf",
        f"scale={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:force_original_aspect_ratio=decrease",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "-q:v",
        str(THUMBNAIL_QUALITY),
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise RecordingThumbnailError("thumbnail generation timed out") from error
    except OSError as error:
        raise RecordingThumbnailError("thumbnail generation could not run") from error
    if result.returncode != 0 or not result.stdout:
        raise RecordingThumbnailError("thumbnail generation failed")
    return result.stdout


def _validate_digest(source_sha256: str) -> None:
    if not isinstance(source_sha256, str) or _SHA256.fullmatch(source_sha256) is None:
        raise RecordingThumbnailError("source_sha256 must be a lower-case SHA-256 digest")


def thumbnail_etag(content: bytes) -> str:
    """Return the immutable entity tag for one cached thumbnail."""

    return hashlib.sha256(content).hexdigest()


__all__ = [
    "RecordingThumbnailCache",
    "RecordingThumbnailError",
    "thumbnail_etag",
]
