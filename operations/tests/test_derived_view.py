from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from doko_operations.derived_view import (
    DEFAULT_DECODER_VERSION,
    DEFAULT_TRANSFORM_VERSION,
    SAMPLED_FRAME_INTERVAL_US,
    DerivedViewCache,
    DerivedViewError,
    DerivedViewMissingFrameError,
    DerivedViewSourceError,
    DetectorBoxGeometry,
    ExactEventRequest,
    FFmpegFrameResolver,
    PredictedVisibleRegionGeometry,
    ResolvedFrame,
    ReviewedVisibleRegionGeometry,
    SampledFrameResolver,
    VisibleRegionCropRequest,
    VisibleRegionExclusionInput,
    crop_cache_key,
    crop_jpeg_preview_cache_key,
    crop_jpeg_preview_cache_key_for_source_digest,
    frame_cache_key,
    generate_visible_region_corruption,
    parse_geometry,
    resolve_crop_jpeg_preview,
    resolve_crop_jpeg_preview_from_cache,
    resolve_exact_event,
    resolve_visible_region_crop,
)
from doko_operations.pipeline_data import RecordingVideoSource


def _make_cfr_video(path: Path, *, duration_s: float = 0.5) -> None:
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
            str(duration_s),
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


def test_ffmpeg_probe_reads_packet_timestamps_without_frame_side_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "streams": [{"width": 1920, "height": 1080}],
        "packets": [{"pts_time": "0.033333"}, {"pts_time": "0.000000"}],
    }
    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload).encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", run)

    frames = FFmpegFrameResolver()._probe_frames(tmp_path / "source.mov")

    assert frames == [(0, 1920, 1080), (33_333, 1920, 1080)]
    assert len(calls) == 1
    assert "-show_packets" in calls[0]
    assert "-show_frames" not in calls[0]


def test_ffmpeg_decoder_seeks_to_the_requested_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"jpeg", stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)

    image_bytes = FFmpegFrameResolver()._decode_frame(
        tmp_path / "source.mov", 12, 5_000_000, "jpeg"
    )

    assert image_bytes == b"jpeg"
    assert len(calls) == 1
    assert "-copyts" in calls[0]
    assert calls[0][calls[0].index("-ss") + 1] == "4.999999500"
    assert calls[0][calls[0].index("-vf") + 1] == r"select=gte(t\,4.999999500)"
    assert "eq(n" not in " ".join(calls[0])


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


def test_sampled_frame_resolver_extracts_one_250_ms_cache_for_many_requests(
    tmp_path: Path,
) -> None:
    video = tmp_path / "cfr.mp4"
    _make_cfr_video(video, duration_s=1.0)
    source = _source(video, duration_us=1_000_000)
    resolver = SampledFrameResolver(tmp_path / "sampled-frames")

    with patch("doko_operations.derived_view.subprocess.run", wraps=subprocess.run) as run:
        first = resolve_exact_event(
            video,
            source=source,
            requested_time_us=100_000,
            resolver=resolver,
        )
        second = resolve_exact_event(
            video,
            source=source,
            requested_time_us=300_000,
            resolver=resolver,
        )

    assert run.call_count == 1
    assert first.presentation_timestamp_us == SAMPLED_FRAME_INTERVAL_US
    assert second.presentation_timestamp_us == SAMPLED_FRAME_INTERVAL_US * 2
    assert first.width == second.width == 64
    assert first.height == second.height == 48
    cache_directories = list((tmp_path / "sampled-frames").rglob("manifest.json"))
    assert len(cache_directories) == 1


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
    reviewed_raw_crop = resolve_visible_region_crop(
        frame,
        reviewed,
        crop_policy="raw_rectangular",
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
    assert reviewed_raw_crop.status == "usable"
    assert reviewed_raw_crop.pixel_bounds == detector_crop.pixel_bounds
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
    oracle_geometry = ReviewedVisibleRegionGeometry(
        (((100, 100), (500, 100), (500, 500), (100, 500)),)
    )
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
                geometry=oracle_geometry,
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


def _colour_frame() -> ResolvedFrame:
    image = Image.new("RGB", (100, 100), (10, 10, 10))
    pixels = image.load()
    for y in range(30, 70):
        for x in range(30, 70):
            pixels[x, y] = (220, 20, 20)
    for y in range(32, 68):
        for x in range(21, 30):
            pixels[x, y] = (20, 80, 220)
    for y in range(32, 68):
        for x in range(70, 79):
            pixels[x, y] = (20, 220, 80)
    for y in range(70, 79):
        for x in range(38, 62):
            pixels[x, y] = (220, 180, 20)
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    return ResolvedFrame(
        requested_time_us=0,
        frame_index=0,
        presentation_timestamp_us=0,
        source_video_sha256="a" * 64,
        width=100,
        height=100,
        decoder_version=DEFAULT_DECODER_VERSION,
        transform_version="fixture-frame-v1",
        output_encoding="png",
        image_bytes=encoded.getvalue(),
    )


def test_crop_jpeg_preview_uses_a_verified_warm_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crop = resolve_visible_region_crop(
        _colour_frame(),
        DetectorBoxGeometry(200, 200, 800, 800),
        crop_policy="raw_rectangular",
    )
    cache = DerivedViewCache(tmp_path / "derived-views")

    cold = resolve_crop_jpeg_preview(crop, cache=cache)

    assert cold.content_type == "image/jpeg"
    with Image.open(BytesIO(cold.image_bytes)) as image:
        assert image.format == "JPEG"
    preview_key = crop_jpeg_preview_cache_key(crop)
    cached = cache.read(preview_key)
    assert cached is not None
    assert cached.manifest["view_kind"] == "visible-region-crop-jpeg-preview/v1"

    def fail_if_decoded(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("warm JPEG preview should not decode the canonical crop")

    monkeypatch.setattr(Image, "open", fail_if_decoded)
    warm = resolve_crop_jpeg_preview(crop, cache=cache)

    assert warm.image_bytes == cold.image_bytes
    assert warm.image_sha256 == cold.image_sha256


def test_crop_jpeg_preview_digest_lookup_validates_source_and_content(
    tmp_path: Path,
) -> None:
    crop = resolve_visible_region_crop(
        _colour_frame(),
        DetectorBoxGeometry(200, 200, 800, 800),
        crop_policy="raw_rectangular",
    )
    assert crop.image_sha256 is not None
    cache = DerivedViewCache(tmp_path / "derived-views")
    preview = resolve_crop_jpeg_preview(crop, cache=cache)

    hit = resolve_crop_jpeg_preview_from_cache(crop.image_sha256, cache=cache)
    assert hit is not None
    assert hit.image_bytes == preview.image_bytes

    missing = resolve_crop_jpeg_preview_from_cache("d" * 64, cache=cache)
    assert missing is None

    key = crop_jpeg_preview_cache_key_for_source_digest(crop.image_sha256)
    cached = cache.read(key)
    assert cached is not None
    identity = dict(cached.manifest["identity"])
    identity["source_crop_sha256"] = "e" * 64
    manifest = {
        key: value
        for key, value in cached.manifest.items()
        if key not in {"content_sha256", "byte_length"}
    }
    cache.write(
        key,
        {**manifest, "identity": identity},
        cached.content,
    )
    assert resolve_crop_jpeg_preview_from_cache(crop.image_sha256, cache=cache) is None


def _predicted_region(x_min: int, y_min: int, x_max: int, y_max: int):
    return PredictedVisibleRegionGeometry(
        (((x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)),)
    )


def test_resilience_crop_conditions_preserve_geometry_and_exclude_eroded_neighbors() -> None:
    frame = _colour_frame()
    target_box = DetectorBoxGeometry(200, 200, 800, 800)
    target_region = PredictedVisibleRegionGeometry(
        (((300, 500), (500, 300), (700, 500), (500, 700)),)
    )
    neighbors = (
        VisibleRegionExclusionInput("left", _predicted_region(210, 320, 300, 680), "generated"),
        VisibleRegionExclusionInput("right", _predicted_region(700, 320, 790, 680), "generated"),
        VisibleRegionExclusionInput("bottom", _predicted_region(380, 700, 620, 790), "generated"),
    )

    raw = resolve_visible_region_crop(frame, target_box, crop_policy="raw_rectangular")
    predicted = resolve_visible_region_crop(
        frame, target_region, crop_policy="predicted_visible_region"
    )
    excluded = resolve_visible_region_crop(
        frame,
        target_box,
        crop_policy="generated_other_region_exclusion",
        exclusion_inputs=neighbors,
    )
    predicted_with_exclusion = resolve_visible_region_crop(
        frame,
        target_region,
        crop_policy="predicted_region_with_other_exclusion",
        exclusion_inputs=neighbors,
    )
    reviewed_exclusion = resolve_visible_region_crop(
        frame,
        target_box,
        crop_policy="reviewed_other_region_exclusion",
        exclusion_inputs=tuple(
            VisibleRegionExclusionInput(
                item.proposal_id,
                ReviewedVisibleRegionGeometry(item.geometry.polygons),
                "reviewed",
            )
            for item in neighbors
        ),
    )

    assert raw.geometry == target_box
    assert excluded.geometry == target_box
    assert predicted_with_exclusion.geometry == target_region
    assert reviewed_exclusion.geometry == target_box
    assert excluded.exclusion_inputs == neighbors
    assert {item["decision"] for item in excluded.exclusion_decisions} == {"excluded"}
    with (
        Image.open(BytesIO(raw.image_bytes or b"")) as raw_image,
        Image.open(BytesIO(predicted.image_bytes or b"")) as predicted_image,
        Image.open(BytesIO(excluded.image_bytes or b"")) as excluded_image,
    ):
        assert raw_image.getpixel((5, 30)) == (20, 80, 220)
        assert predicted_image.getpixel((5, 5)) == (128, 128, 128)
        assert excluded_image.getpixel((5, 30)) == (128, 128, 128)
        assert excluded_image.getpixel((30, 30)) == (220, 20, 20)


def test_exclusion_deduplicates_disputes_and_records_no_eligible_inputs() -> None:
    frame = _colour_frame()
    target_box = DetectorBoxGeometry(200, 200, 800, 800)
    left = _predicted_region(210, 320, 400, 680)
    duplicate = VisibleRegionExclusionInput("left-duplicate", left, "generated")
    first = VisibleRegionExclusionInput("left", left, "generated")
    duplicated = resolve_visible_region_crop(
        frame,
        target_box,
        crop_policy="generated_other_region_exclusion",
        exclusion_inputs=(first, duplicate),
    )
    assert [item["decision"] for item in duplicated.exclusion_decisions] == [
        "excluded",
        "duplicate_geometry",
    ]

    overlap_left = VisibleRegionExclusionInput(
        "overlap-left", _predicted_region(210, 320, 400, 680), "generated"
    )
    overlap_right = VisibleRegionExclusionInput(
        "overlap-right", _predicted_region(300, 320, 490, 680), "generated"
    )
    disputed = resolve_visible_region_crop(
        frame,
        target_box,
        crop_policy="generated_other_region_exclusion",
        exclusion_inputs=(overlap_left, overlap_right),
    )
    assert [item["decision"] for item in disputed.exclusion_decisions] == [
        "disputed_overlap",
        "disputed_overlap",
        "no_eligible_exclusion_region",
    ]

    ineligible = VisibleRegionExclusionInput(
        "unknown-confidence",
        left,
        "generated",
        eligible=False,
        eligibility_reason="provider_confidence_unavailable; deterministic fallback",
    )
    no_eligible = resolve_visible_region_crop(
        frame,
        target_box,
        crop_policy="generated_other_region_exclusion",
        exclusion_inputs=(ineligible,),
    )
    raw = resolve_visible_region_crop(frame, target_box, crop_policy="raw_rectangular")
    assert no_eligible.image_bytes == raw.image_bytes
    assert no_eligible.exclusion_decisions[-1]["decision"] == "no_eligible_exclusion_region"


def test_exclusion_crop_cache_reproduces_bytes_and_lineage(tmp_path: Path) -> None:
    frame = _colour_frame()
    target = DetectorBoxGeometry(200, 200, 800, 800)
    input_region = VisibleRegionExclusionInput(
        "left", _predicted_region(210, 320, 300, 680), "generated"
    )
    cache = DerivedViewCache(tmp_path / "derived-views")
    cold = resolve_visible_region_crop(
        frame,
        target,
        crop_policy="generated_other_region_exclusion",
        exclusion_inputs=(input_region,),
        cache=cache,
    )
    warm = resolve_visible_region_crop(
        frame,
        target,
        crop_policy="generated_other_region_exclusion",
        exclusion_inputs=(input_region,),
        cache=cache,
    )
    assert cold.image_bytes == warm.image_bytes
    assert cold.identity_mapping() == warm.identity_mapping()
    assert cold.identity_mapping()["geometry"] == target.to_mapping()
    assert cold.identity_mapping()["exclusion_inputs"] == [input_region.to_mapping()]


def test_visible_region_corruptions_are_deterministic_and_lineage_linked() -> None:
    source = ReviewedVisibleRegionGeometry(
        (
            ((200, 200), (400, 200), (400, 500), (200, 500)),
            ((600, 600), (800, 600), (800, 800), (600, 800)),
        )
    )
    donor = ReviewedVisibleRegionGeometry((((50, 50), (150, 50), (150, 150), (50, 150)),))
    families = (
        "erosion_missing_boundary_pixels",
        "dilation_into_background_or_neighbor",
        "position_shift",
        "holes_missing_connected_components",
        "false_disconnected_components",
        "pixels_from_another_visible_card",
        "complete_derived_box_fallback",
    )
    for family in families:
        first = generate_visible_region_corruption(
            source,
            family,
            0.10 if family != "false_disconnected_components" else 1,
            seed=5101,
            donor_geometry=donor,
        )
        second = generate_visible_region_corruption(
            source,
            family,
            0.10 if family != "false_disconnected_components" else 1,
            seed=5101,
            donor_geometry=donor,
        )
        assert first.to_mapping() == second.to_mapping()
        assert first.source_geometry == source
        assert first.source_geometry_sha256 != first.output_geometry_sha256
        assert first.to_mapping()["transform_version"] == "visible-region-corruption/v1"
    fallback = generate_visible_region_corruption(
        source, "complete_derived_box_fallback", 1, seed=5107
    )
    assert isinstance(fallback.output_geometry, DetectorBoxGeometry)
    over_segmented = generate_visible_region_corruption(
        source, "false_disconnected_components", 1, seed=5105
    )
    under_segmented = generate_visible_region_corruption(
        source, "holes_missing_connected_components", 0.20, seed=5104
    )
    assert isinstance(over_segmented.output_geometry, PredictedVisibleRegionGeometry)
    assert len(over_segmented.output_geometry.polygons) == 3
    assert isinstance(under_segmented.output_geometry, PredictedVisibleRegionGeometry)
    assert len(under_segmented.output_geometry.polygons) == 1


def test_resilience_inputs_reject_malformed_or_mismatched_geometry() -> None:
    detector = DetectorBoxGeometry(100, 100, 900, 900)
    predicted = _predicted_region(200, 200, 800, 800)
    with pytest.raises(DerivedViewError, match="oracle_visible_region needs"):
        VisibleRegionCropRequest(
            frame_identity={},
            geometry=detector,
            width=100,
            height=100,
            crop_policy="oracle_visible_region",
        )
    with pytest.raises(DerivedViewError, match="source does not match"):
        VisibleRegionExclusionInput("wrong-source", predicted, "reviewed")
    with pytest.raises(DerivedViewError, match="unsupported visible-region corruption"):
        generate_visible_region_corruption(
            ReviewedVisibleRegionGeometry((((100, 100), (900, 100), (900, 900), (100, 900)),)),
            "not-a-frozen-family",
            0.1,
            seed=1,
        )
