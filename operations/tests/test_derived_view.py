from __future__ import annotations

import hashlib
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from doko_operations.derived_view import (
    DEFAULT_DECODER_VERSION,
    DEFAULT_TRANSFORM_VERSION,
    DerivedViewCache,
    DerivedViewMissingFrameError,
    DerivedViewSourceError,
    DetectorBoxGeometry,
    ExactEventRequest,
    ResolvedFrame,
    ReviewedVisibleRegionGeometry,
    VisibleRegionCropRequest,
    crop_cache_key,
    frame_cache_key,
    parse_geometry,
    resolve_exact_event,
    resolve_visible_region_crop,
)
from doko_operations.pipeline_data import RecordingVideoSource


def _make_cfr_video(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for derived-view fixtures")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:rate=10",
            "-t",
            "0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def _make_vfr_video(path: Path, root: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for derived-view fixtures")
    frame_paths: list[Path] = []
    for index, colour in enumerate(((220, 30, 30), (30, 220, 30), (30, 30, 220), (220, 220, 30))):
        frame_path = root / f"frame-{index}.png"
        Image.new("RGB", (64, 48), colour).save(frame_path)
        frame_paths.append(frame_path)
    concat = root / "vfr.ffconcat"
    concat.write_text(
        "\n".join(
            [
                "ffconcat version 1.0",
                f"file '{frame_paths[0]}'",
                "duration 0.08",
                f"file '{frame_paths[1]}'",
                "duration 0.20",
                f"file '{frame_paths[2]}'",
                "duration 0.40",
                f"file '{frame_paths[3]}'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def _source(path: Path, *, duration_us: int) -> RecordingVideoSource:
    content = path.read_bytes()
    return RecordingVideoSource(
        recording_id="recording-derived-view",
        relative_path="videos/source.mp4",
        video_sha256=hashlib.sha256(content).hexdigest(),
        byte_length=len(content),
        duration_us=duration_us,
    )


def test_exact_event_uses_presentation_timestamps_and_warm_cache(tmp_path: Path) -> None:
    video = tmp_path / "cfr.mp4"
    _make_cfr_video(video)
    source = _source(video, duration_us=500_000)
    cache = DerivedViewCache(tmp_path / "derived-views")

    cold = resolve_exact_event(
        video,
        source=source,
        requested_time_us=150_000,
        cache=cache,
    )
    warm = resolve_exact_event(
        video,
        source=source,
        requested_time_us=150_000,
        cache=cache,
    )

    assert cold.frame_index == 2
    assert cold.presentation_timestamp_us == 200_000
    assert cold.identity_mapping() == warm.identity_mapping()
    assert cold.image_bytes == warm.image_bytes
    assert cold.image_sha256 == warm.image_sha256


def test_exact_event_vfr_does_not_use_nominal_frame_rate(tmp_path: Path) -> None:
    video = tmp_path / "vfr.mp4"
    _make_vfr_video(video, tmp_path)
    source = _source(video, duration_us=900_000)

    frame = resolve_exact_event(
        video,
        source=source,
        requested_time_us=90_000,
    )

    assert frame.frame_index == 2
    assert frame.presentation_timestamp_us == 280_000


def test_exact_event_missing_frame_and_corrupt_cache_regenerate(tmp_path: Path) -> None:
    video = tmp_path / "cfr.mp4"
    _make_cfr_video(video)
    source = _source(video, duration_us=500_000)
    cache = DerivedViewCache(tmp_path / "derived-views")
    first = resolve_exact_event(video, source=source, requested_time_us=0, cache=cache)
    request = ExactEventRequest(source=source, requested_time_us=0)
    key = frame_cache_key(request, decoder_version=DEFAULT_DECODER_VERSION)
    (cache.path(key) / "content.bin").write_bytes(b"corrupt")

    regenerated = resolve_exact_event(video, source=source, requested_time_us=0, cache=cache)

    assert regenerated.image_bytes == first.image_bytes
    with pytest.raises(DerivedViewMissingFrameError):
        resolve_exact_event(video, source=source, requested_time_us=500_000)
    with pytest.raises(DerivedViewSourceError, match="does not exist"):
        resolve_exact_event(tmp_path / "missing.mp4", source=source, requested_time_us=0)


def test_geometry_tags_keep_detector_boxes_separate_from_disconnected_reviewed_regions(
    tmp_path: Path,
) -> None:
    image = BytesIO()
    Image.new("RGB", (20, 20), (20, 40, 60)).save(image, format="PNG")
    frame = ResolvedFrame(
        requested_time_us=0,
        frame_index=0,
        presentation_timestamp_us=0,
        source_video_sha256="a" * 64,
        width=20,
        height=20,
        decoder_version=DEFAULT_DECODER_VERSION,
        transform_version="fixture-frame-v1",
        output_encoding="png",
        image_bytes=image.getvalue(),
    )
    detector = DetectorBoxGeometry(100, 100, 900, 900)
    reviewed = ReviewedVisibleRegionGeometry(
        (
            ((100, 100), (400, 100), (400, 900), (100, 900)),
            ((600, 100), (900, 100), (900, 900), (600, 900)),
        )
    )
    cache = DerivedViewCache(tmp_path / "derived-views")

    detector_crop = resolve_visible_region_crop(
        frame,
        detector,
        crop_policy="raw_rectangular",
        cache=cache,
    )
    reviewed_crop = resolve_visible_region_crop(
        frame,
        reviewed,
        crop_policy="oracle_visible_region",
        cache=cache,
    )

    assert detector_crop.status == "usable"
    assert detector_crop.pixel_bounds is not None
    assert detector_crop.pixel_bounds.to_mapping() == {
        "x_min": 2,
        "y_min": 2,
        "x_max": 18,
        "y_max": 18,
    }
    detector_key = crop_cache_key(
        VisibleRegionCropRequest(
            frame_identity=frame.identity_mapping(),
            geometry=detector,
            width=frame.width,
            height=frame.height,
            crop_policy="raw_rectangular",
            output_encoding="ppm",
            decoder_version=frame.decoder_version,
            transform_version=DEFAULT_TRANSFORM_VERSION,
        )
    )
    (cache.path(detector_key) / "content.bin").write_bytes(b"corrupt")
    regenerated = resolve_visible_region_crop(
        frame,
        detector,
        crop_policy="raw_rectangular",
        cache=cache,
    )
    assert regenerated.image_bytes == detector_crop.image_bytes
    assert reviewed_crop.status == "usable"
    assert reviewed_crop.pixel_bounds == detector_crop.pixel_bounds
    assert parse_geometry(detector.to_mapping()) == detector
    assert parse_geometry(reviewed.to_mapping()) == reviewed
    with Image.open(BytesIO(reviewed_crop.image_bytes or b"")) as crop:
        assert crop.getpixel((8, 8)) == (128, 128, 128)


def test_crop_cache_key_includes_geometry_policy_versions_and_encoding(tmp_path: Path) -> None:
    frame_identity = {
        "schema_version": "exact-event/v1",
        "source_video_sha256": "a" * 64,
        "frame_index": 2,
        "presentation_timestamp_us": 200_000,
        "image_sha256": "b" * 64,
    }
    geometry = DetectorBoxGeometry(100, 100, 500, 500)
    request = VisibleRegionCropRequest(
        frame_identity=frame_identity,
        geometry=geometry,
        width=64,
        height=48,
        crop_policy="raw_rectangular",
    )

    variants = {
        crop_cache_key(request),
        crop_cache_key(
            VisibleRegionCropRequest(
                frame_identity=frame_identity,
                geometry=DetectorBoxGeometry(101, 100, 500, 500),
                width=64,
                height=48,
                crop_policy="raw_rectangular",
            )
        ),
        crop_cache_key(
            VisibleRegionCropRequest(
                frame_identity=frame_identity,
                geometry=geometry,
                width=64,
                height=48,
                crop_policy="oracle_visible_region",
            )
        ),
        crop_cache_key(
            VisibleRegionCropRequest(
                frame_identity=frame_identity,
                geometry=geometry,
                width=64,
                height=48,
                crop_policy="raw_rectangular",
                output_encoding="png",
            )
        ),
        crop_cache_key(
            VisibleRegionCropRequest(
                frame_identity=frame_identity,
                geometry=geometry,
                width=64,
                height=48,
                crop_policy="raw_rectangular",
                decoder_version="ffmpeg/other",
                transform_version=DEFAULT_TRANSFORM_VERSION,
            )
        ),
    }
    assert len(variants) == 5
