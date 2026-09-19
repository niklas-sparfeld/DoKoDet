"""Calibrate one stable table plane and render review-scale synthetic cards.

The renderer uses only an explicit reviewed empty table frame as its background.  It extracts a
per-table paper colour from several reviewed cards in the same recording.  It then applies that
one colour response, a soft rounded alpha edge, and card-scale blur to upright scanned deck cards.
It does not add shadows, glare, or random per-card lighting changes.

The calibration treats each complete reviewed card as a 1 by 1.5 rectangle on one flat table
plane.  One rectangle gives an initial projective rectification.  All available rectangles then
fit a common metric upgrade, reject outliers, and provide the median card size in table coordinates.
The inverse homography projects synthetic card layouts, including overlap, back into the empty
source frame.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .card_plane_geometry import (
    CARD_ASPECT_RATIO,
    CardPlaneGeometryError,
)
from .card_plane_geometry import (
    apply_homography as _apply_homography,
)
from .card_plane_geometry import (
    card_vectors as _card_vectors,
)
from .card_plane_geometry import (
    cyclic_quad as _cyclic_quad,
)
from .card_plane_geometry import (
    fit_table_plane as _shared_fit_table_plane,
)
from .card_plane_geometry import (
    mask_bbox as _mask_bbox,
)
from .card_plane_geometry import (
    mask_to_polygons as _mask_polygons,
)
from .card_plane_geometry import (
    polygon_area as _polygon_area,
)
from .card_plane_geometry import (
    remove_small_components as _remove_small_components,
)
from .derived_view import DerivedViewCache, FFmpegFrameResolver, resolve_exact_event
from .pipeline_data import RecordingVideoSource
from .reviewed_rfdetr_detector_campaign import canonical_json_bytes
from .rfdetr_segmentation_materialization import validate_rfdetr_coco_annotations
from .synthetic_visible_region_materialization import (
    validate_synthetic_visible_region_inputs,
)
from .synthetic_visible_region_recording_synthesis import (
    MAX_CARD_COUNT_DEFAULT,
    SOURCE_MANIFEST_DEFAULT,
    _quad_array,
    build_synthetic_visible_region_recording_discovery,
)
from .synthetic_visible_region_rendering import (
    CANONICAL_HEIGHT,
    CANONICAL_WIDTH,
    MIN_VISIBLE_PIXELS,
    _alpha_composite,
    _derive_visible_masks,
    _occlusion_ratio,
    _quad_to_records,
    _read_cutout,
)

SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION = (
    "synthetic-visible-region-planar-geometry-samples/v1"
)
SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CAMPAIGN_ID = (
    "0070-m5-synthetic-visible-region-planar-geometry-samples"
)
M1_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m1-inputs.json"
OUTPUT_DIRECTORY_DEFAULT = ".runtime/synthetic-visible-region-0070-planar-geometry-samples"
MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-planar-geometry-samples.json"
SCANNED_DECK_SOURCE_DEFAULT = "data/decks/ass-altenburger-romme-french/source"
SAMPLE_COUNT_DEFAULT = 3
MAX_REVIEW_SCENE_COUNT = 2_000
PRODUCTION_CARD_COUNT_PATTERN = (2, 3, 3, 4, 4, 4, 3, 4, 3, 4)
BACKGROUND_STRATEGY = "explicit-reviewed-empty-table-only-v1"
REFERENCE_CARD_LIMIT = 8
REFERENCE_FRAME_LIMIT = 4
SCAN_ALPHA_INSET_FRACTION = 0.01
SCAN_CORNER_RADIUS_FRACTION = 0.075
SCAN_ALPHA_FEATHER_PIXELS = 1.2
MIN_MASK_ALPHA = 128
CARD_SATURATION_FACTOR = 0.78
CARD_BLUR_REDUCTION_FACTOR = 0.42
CARD_RENDER_SUPERSAMPLE = 2
CARD_SHADOW_OPACITY = 0.12
CARD_SHADOW_BLUR_SIGMA = 0.75
CARD_SHADOW_OFFSET_PIXELS = (1.5, 1.5)
CARD_SHADOW_Z_ORDER_LENGTH_STEP = 0.15
SCENE_CARD_SATURATION_MULTIPLIER_RANGE = (0.94, 1.06)
SCENE_CARD_BLUR_MULTIPLIER_RANGE = (0.88, 1.12)
SCENE_CARD_SHADOW_OPACITY_MULTIPLIER_RANGE = (0.90, 1.10)
SCENE_BRIGHTNESS_DELTA_RANGE = (-0.025, 0.025)
SCENE_CONTRAST_RANGE = (0.97, 1.03)
SCENE_SATURATION_MULTIPLIER_RANGE = (0.96, 1.04)
SCENE_JPEG_QUALITY_RANGE = (92, 96)
_SHA256_LENGTH = 64
_REVIEW_CARD_STEMS = (
    "SPADES_ten",
    "DIAMONDS_queen",
    "HEARTS_jack",
    "CLUBS_king",
    "DIAMONDS_ace",
    "HEARTS_ten",
)


class SyntheticVisibleRegionPlanarGeometryError(ValueError):
    """The reviewed table-plane geometry cannot safely produce a sample."""


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"could not read {field} {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionPlanarGeometryError(f"{field} must be a JSON object")
    return dict(value)


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else repository / path


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _write_bytes(path: Path, value: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return _sha256_bytes(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    return _write_bytes(path, canonical_json_bytes(value) + b"\n")


def _rounded_scan_alpha(width: int, height: int) -> np.ndarray:
    """Return a feathered matte that removes the scan bed and its dark perimeter."""

    inset_x = max(1, int(round(width * SCAN_ALPHA_INSET_FRACTION)))
    inset_y = max(1, int(round(height * SCAN_ALPHA_INSET_FRACTION)))
    radius = max(2, int(round(min(width, height) * SCAN_CORNER_RADIUS_FRACTION)))
    radius = min(radius, (width - 2 * inset_x) // 2, (height - 2 * inset_y) // 2)
    mask = np.zeros((height, width), dtype=np.uint8)
    right, bottom = width - inset_x - 1, height - inset_y - 1
    cv2.rectangle(mask, (inset_x + radius, inset_y), (right - radius, bottom), 255, -1)
    cv2.rectangle(mask, (inset_x, inset_y + radius), (right, bottom - radius), 255, -1)
    for center in (
        (inset_x + radius, inset_y + radius),
        (right - radius, inset_y + radius),
        (inset_x + radius, bottom - radius),
        (right - radius, bottom - radius),
    ):
        cv2.circle(mask, center, radius, 255, thickness=cv2.FILLED, lineType=cv2.LINE_AA)
    return cv2.GaussianBlur(mask, (0, 0), SCAN_ALPHA_FEATHER_PIXELS)


def _scanned_deck_assets(repository: Path, source_directory: str | Path) -> list[dict[str, Any]]:
    """Load upright canonical cards directly from the supplied deck scans."""

    directory = _resolve(repository, source_directory)
    if not directory.is_dir():
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"scanned card source directory is missing: {directory}"
        )
    source_paths = {
        path.stem: path
        for path in sorted(directory.glob("*.webp"))
        if not path.stem.startswith(("BACK_", "JOKER_"))
    }
    missing = [stem for stem in _REVIEW_CARD_STEMS if stem not in source_paths]
    if missing:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"scanned card source is missing review cards: {', '.join(missing)}"
        )
    source_digest = _sha256_bytes(
        canonical_json_bytes(
            {
                stem: _sha256_file(path)
                for stem, path in sorted(source_paths.items())
            }
        )
    )
    source_group = {
        "id": "0070-ass-altenburger-romme-french-scans",
        "key": source_digest,
        "permission": "training_only",
        "split": "train",
        "table_setup": "canonical-scanned-deck",
    }
    assets: list[dict[str, Any]] = []
    for stem in _REVIEW_CARD_STEMS:
        path = source_paths[stem]
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"could not decode scanned card {path}"
            )
        source_height, source_width = image.shape[:2]
        canonical = cv2.resize(
            image,
            (CANONICAL_WIDTH, CANONICAL_HEIGHT),
            interpolation=cv2.INTER_CUBIC,
        )
        alpha = _rounded_scan_alpha(CANONICAL_WIDTH, CANONICAL_HEIGHT)
        rgba = np.dstack((canonical, alpha))
        source_sha256 = _sha256_file(path)
        record = {
            "cutout_id": f"scanned-ass-altenburger-romme-french-{stem.lower()}",
            "source_asset_id": f"ass-altenburger-romme-french-{stem.lower()}",
            "deck_card_name": stem,
            "reviewed_decision": {"card_side": "face_up"},
            "source_group": source_group,
            "source_frame": {
                "path": _relative(path, repository),
                "width": source_width,
                "height": source_height,
                "source_file_sha256": source_sha256,
            },
            "source_quadrilateral": [
                {"x": 0.0, "y": 0.0},
                {"x": float(source_width - 1), "y": 0.0},
                {"x": float(source_width - 1), "y": float(source_height - 1)},
                {"x": 0.0, "y": float(source_height - 1)},
            ],
        }
        assets.append({"record": record, "rgba": rgba, "alpha": alpha})
    return assets


def _read_card_asset(asset: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if "rgba" in asset and "alpha" in asset:
        return np.asarray(asset["rgba"]), np.asarray(asset["alpha"])
    return _read_cutout(asset)


def _selected_scan_assets(
    assets: Sequence[Mapping[str, Any]], card_count: int, scene_index: int
) -> list[Mapping[str, Any]]:
    start = sum(range(scene_index + 1))
    return [assets[(start + offset) % len(assets)] for offset in range(card_count)]


def _round(value: float) -> float:
    return round(float(value), 6)


def _scene_variation(scene_id: str) -> dict[str, float | int | str]:
    """Return one reproducible appearance recipe shared by a complete synthetic scene."""

    seed = int.from_bytes(hashlib.sha256(scene_id.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    return {
        "method": "scene-shared-deterministic-appearance-v1",
        "seed": str(seed),
        "card_saturation_multiplier": _round(
            rng.uniform(*SCENE_CARD_SATURATION_MULTIPLIER_RANGE)
        ),
        "card_blur_multiplier": _round(rng.uniform(*SCENE_CARD_BLUR_MULTIPLIER_RANGE)),
        "card_shadow_opacity_multiplier": _round(
            rng.uniform(*SCENE_CARD_SHADOW_OPACITY_MULTIPLIER_RANGE)
        ),
        "brightness_delta": _round(rng.uniform(*SCENE_BRIGHTNESS_DELTA_RANGE)),
        "contrast": _round(rng.uniform(*SCENE_CONTRAST_RANGE)),
        "saturation_multiplier": _round(rng.uniform(*SCENE_SATURATION_MULTIPLIER_RANGE)),
        "jpeg_quality": int(rng.integers(*SCENE_JPEG_QUALITY_RANGE)),
    }


def _apply_scene_variation(scene: np.ndarray, variation: Mapping[str, float | int | str]) -> None:
    """Apply the scene-shared appearance recipe after all card compositing is complete."""

    adjusted = scene.astype(np.float32) * float(variation["contrast"])
    adjusted += float(variation["brightness_delta"]) * 255.0
    hsv = cv2.cvtColor(np.clip(adjusted, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(
        np.float32
    )
    hsv[:, :, 1] *= float(variation["saturation_multiplier"])
    scene[:] = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)


def fit_table_plane(card_quads: Sequence[np.ndarray]) -> dict[str, Any]:
    """Use the shared table-plane fit while retaining the 0070 error boundary."""

    try:
        return _shared_fit_table_plane(card_quads)
    except CardPlaneGeometryError as error:
        raise SyntheticVisibleRegionPlanarGeometryError(str(error)) from error


def _empty_backgrounds(
    repository: Path, m1: Mapping[str, Any], recording_ids: set[str] | None
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in m1.get("backgrounds", []):
        if not isinstance(item, Mapping):
            continue
        source_group = item.get("source_group")
        decision = item.get("reviewed_decision")
        files = item.get("files")
        image = files.get("image") if isinstance(files, Mapping) else None
        if (
            not isinstance(source_group, Mapping)
            or not isinstance(decision, Mapping)
            or not isinstance(image, Mapping)
            or source_group.get("split") != "train"
            or decision.get("status") != "accepted"
            or decision.get("contains_visible_card") is not False
            or decision.get("full_frame_review_coverage") is not True
        ):
            continue
        recording_id = str(source_group.get("id", ""))
        if recording_ids is not None and recording_id not in recording_ids:
            continue
        path = _resolve(repository, str(image.get("path", "")))
        if not path.is_file() or _sha256_file(path) != image.get("sha256"):
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"reviewed empty background is missing or changed: {item.get('background_id')}"
            )
        result.append({"record": dict(item), "path": path, "sha256": str(image["sha256"])})
    return sorted(result, key=lambda item: str(item["record"]["background_id"]))


def _recording_geometry(
    discovery: Mapping[str, Any], background: Mapping[str, Any]
) -> tuple[list[np.ndarray], list[dict[str, Any]]]:
    source_group = background["source_group"]
    recording_id = str(source_group["id"])
    width = int(background["frame_identity"]["width"])
    height = int(background["frame_identity"]["height"])
    dimensions = np.asarray([width, height], dtype=np.float64)
    quads: list[np.ndarray] = []
    provenance: list[dict[str, Any]] = []
    for candidate in discovery["candidates"]:
        if (
            not isinstance(candidate, Mapping)
            or candidate.get("source_split") != "train"
            or candidate.get("recording_id") != recording_id
            or candidate.get("table_setup") != source_group.get("table_setup")
        ):
            continue
        frame = candidate.get("frame_identity", {})
        if frame.get("width") != width or frame.get("height") != height:
            continue
        for card_index, normalized_quad in enumerate(candidate["normalized_quadrilaterals"]):
            quads.append(_quad_array(normalized_quad) * dimensions)
            provenance.append(
                {
                    "candidate_id": str(candidate["candidate_id"]),
                    "event_id": str(candidate["event_id"]),
                    "card_index": card_index,
                    "selection_score": _round(float(candidate["selection_score"])),
                }
            )
    if len(quads) < 3:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"recording {recording_id} has fewer than three complete reviewed card quadrilaterals"
        )
    return quads, provenance


def _paper_bgr(image: np.ndarray, support: np.ndarray | None = None) -> np.ndarray:
    """Estimate paper colour from bright, low-saturation pixels inside one card."""

    if image.ndim != 3 or image.shape[2] != 3:
        raise SyntheticVisibleRegionPlanarGeometryError("paper sample is not a BGR image")
    if support is None:
        support = np.full(image.shape[:2], 255, dtype=np.uint8)
    if support.shape != image.shape[:2]:
        raise SyntheticVisibleRegionPlanarGeometryError("paper sample support has wrong dimensions")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    values = hsv[:, :, 2][support >= MIN_MASK_ALPHA]
    if values.size < 64:
        raise SyntheticVisibleRegionPlanarGeometryError("paper sample has too few supported pixels")
    value_floor = float(np.percentile(values, 60))
    selected = (support >= MIN_MASK_ALPHA) & (hsv[:, :, 2] >= value_floor) & (hsv[:, :, 1] <= 96)
    pixels = image[selected]
    if len(pixels) < 64:
        selected = (support >= MIN_MASK_ALPHA) & (hsv[:, :, 2] >= value_floor)
        pixels = image[selected]
    if len(pixels) < 64:
        raise SyntheticVisibleRegionPlanarGeometryError("paper sample has too few white pixels")
    return np.median(pixels.astype(np.float32), axis=0)


def _reference_card_sources(
    discovery: Mapping[str, Any], background: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Select unoccluded face-up reviewed cards from this exact table recording."""

    source_group = background["source_group"]
    recording_id = str(source_group["id"])
    width = int(background["frame_identity"]["width"])
    height = int(background["frame_identity"]["height"])
    dimensions = np.asarray([width, height], dtype=np.float64)
    candidates = []
    for candidate in discovery["candidates"]:
        if (
            not isinstance(candidate, Mapping)
            or candidate.get("source_split") != "train"
            or candidate.get("recording_id") != recording_id
            or candidate.get("table_setup") != source_group.get("table_setup")
            or float(candidate.get("metrics", {}).get("maximum_pairwise_overlap_ratio", 1.0)) > 0.02
        ):
            continue
        candidates.append(candidate)
    def select(side: str, side_policy: str) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        used_events: set[str] = set()
        for candidate in sorted(
            candidates, key=lambda item: float(item["selection_score"]), reverse=True
        ):
            event_id = str(candidate["event_id"])
            if len(used_events) >= REFERENCE_FRAME_LIMIT and event_id not in used_events:
                continue
            for card_index, (candidate_side, normalized_quad) in enumerate(
                zip(candidate["card_sides"], candidate["normalized_quadrilaterals"], strict=True)
            ):
                if candidate_side != side:
                    continue
                cards.append(
                    {
                        "candidate_id": str(candidate["candidate_id"]),
                        "event_id": event_id,
                        "frame_identity": dict(candidate["frame_identity"]),
                        "card_index": card_index,
                        "card_side_policy": side_policy,
                        "image_quad": _quad_array(normalized_quad) * dimensions,
                    }
                )
                used_events.add(event_id)
                if len(cards) >= REFERENCE_CARD_LIMIT:
                    return cards
        return cards

    face_up_cards = select("face_up", "face_up_preferred")
    if face_up_cards:
        return face_up_cards
    unknown_cards = select("unknown", "unknown_visible_card_fallback")
    if unknown_cards:
        return unknown_cards
    raise SyntheticVisibleRegionPlanarGeometryError(
        f"recording {recording_id} has no usable face-up or unknown cards for "
        "appearance calibration"
    )


def _recording_video_source(
    repository: Path,
    source_manifest_path: str | Path,
    recording_id: str,
    requested_time_us: int,
) -> tuple[Path, RecordingVideoSource]:
    source_manifest = _read_json(
        _resolve(repository, source_manifest_path), "recording source manifest"
    )
    record = next(
        (
            item
            for item in source_manifest.get("recordings", [])
            if isinstance(item, Mapping) and item.get("recording_id") == recording_id
        ),
        None,
    )
    if not isinstance(record, Mapping):
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"recording {recording_id} is absent from the source manifest"
        )
    video_path = _resolve(repository, str(record["source_video_path"]))
    source = RecordingVideoSource(
        recording_id=recording_id,
        relative_path=str(record["source_video_path"]),
        video_sha256=str(record["source_sha256"]),
        byte_length=int(record["source_byte_length"]),
        duration_us=requested_time_us + 1,
    )
    return video_path, source


def _rectified_card_paper(frame: np.ndarray, image_quad: np.ndarray) -> np.ndarray:
    """Rectify a reviewed card so its paper can be sampled without table pixels."""

    source = _cyclic_quad(image_quad).astype(np.float32)
    destination = np.asarray(
        [[0, 0], [159, 0], [159, 239], [0, 239]], dtype=np.float32
    )
    rectified = cv2.warpPerspective(
        frame, cv2.getPerspectiveTransform(source, destination), (160, 240)
    )
    support = np.zeros((240, 160), dtype=np.uint8)
    cv2.rectangle(support, (12, 16), (147, 223), 255, thickness=cv2.FILLED)
    return _paper_bgr(rectified, support)


def _reference_card_short_side(image_quad: np.ndarray) -> float:
    cyclic = _cyclic_quad(image_quad)
    lengths = [
        float(np.linalg.norm(cyclic[(index + 1) % 4] - cyclic[index]))
        for index in range(4)
    ]
    return min(lengths)


def _table_card_appearance(
    repository: Path,
    output_root: Path,
    discovery: Mapping[str, Any],
    background: Mapping[str, Any],
    source_manifest_path: str | Path,
) -> dict[str, Any]:
    """Measure the table's real card paper response from exact reviewed event frames."""

    references = _reference_card_sources(discovery, background)
    recording_id = str(background["source_group"]["id"])
    last_time = max(int(item["frame_identity"]["requested_time_us"]) for item in references)
    video_path, source = _recording_video_source(
        repository, source_manifest_path, recording_id, last_time
    )
    cache = DerivedViewCache(output_root / "appearance-reference-frame-cache")
    resolver = FFmpegFrameResolver()
    frames: dict[str, np.ndarray] = {}
    frame_identities: dict[str, Mapping[str, Any]] = {}
    for index, reference in enumerate(references):
        event_id = str(reference["event_id"])
        if event_id in frames:
            continue
        resolved = resolve_exact_event(
            video_path,
            source=source,
            requested_time_us=int(reference["frame_identity"]["requested_time_us"]),
            cache=cache,
            resolver=resolver,
            validate_source=index == 0,
        )
        expected = reference["frame_identity"]
        if resolved.identity_mapping() != expected:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"appearance reference frame changed for {event_id}"
            )
        frame = cv2.imdecode(np.frombuffer(resolved.image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"could not decode appearance reference frame {event_id}"
            )
        frames[event_id] = frame
        frame_identities[event_id] = resolved.identity_mapping()
    samples = [
        _rectified_card_paper(frames[str(item["event_id"])], item["image_quad"])
        for item in references
    ]
    paper_bgr = np.median(np.asarray(samples, dtype=np.float32), axis=0)
    short_sides = [_reference_card_short_side(item["image_quad"]) for item in references]
    return {
        "method": "reviewed-face-up-card-paper-median-v1",
        "paper_bgr": [_round(value) for value in paper_bgr],
        "reference_card_count": len(references),
        "reference_frame_count": len(frames),
        "reference_card_side_policy": references[0]["card_side_policy"],
        "median_short_side_pixels": _round(float(np.median(short_sides))),
        "references": [
            {
                "candidate_id": item["candidate_id"],
                "event_id": item["event_id"],
                "card_index": item["card_index"],
                "card_side_policy": item["card_side_policy"],
                "frame_identity": frame_identities[str(item["event_id"])],
                "paper_bgr": [_round(value) for value in sample],
            }
            for item, sample in zip(references, samples, strict=True)
        ],
    }


def _white_balanced_scan(
    rgba: np.ndarray, alpha: np.ndarray, target_paper_bgr: Sequence[float]
) -> tuple[np.ndarray, list[float]]:
    source_paper_bgr = _paper_bgr(rgba[:, :, :3], alpha)
    gain = np.clip(
        np.asarray(target_paper_bgr, dtype=np.float32) / np.maximum(source_paper_bgr, 1.0),
        0.55,
        1.20,
    )
    adjusted = np.clip(rgba[:, :, :3].astype(np.float32) * gain, 0, 255).astype(np.uint8)
    return np.dstack((adjusted, alpha)), [_round(value) for value in gain]


def _reduce_scan_saturation(
    rgba: np.ndarray, alpha: np.ndarray, saturation_factor: float = CARD_SATURATION_FACTOR
) -> np.ndarray:
    """Reduce scan pigment saturation to the softer response of the recorded cards."""

    hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= saturation_factor
    adjusted = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
    return np.dstack((adjusted, alpha))


def _card_blur_sigma(image_quad: np.ndarray, appearance: Mapping[str, Any]) -> float:
    short_side = max(_reference_card_short_side(image_quad), 1.0)
    reference_short_side = max(float(appearance["median_short_side_pixels"]), 1.0)
    baseline = np.clip(160.0 / reference_short_side, 0.65, 1.15)
    return float(
        np.clip(
            baseline * np.sqrt(reference_short_side / short_side) * CARD_BLUR_REDUCTION_FACTOR,
            0.22,
            0.58,
        )
    )


def _warp_soft_card(
    rgba: np.ndarray,
    alpha: np.ndarray,
    destination_quad: np.ndarray,
    output_width: int,
    output_height: int,
    blur_sigma: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Supersample a premultiplied card so transparent pixels and diagonal ink stay smooth."""

    source_quad = np.asarray(
        [
            [0, 0],
            [CANONICAL_WIDTH - 1, 0],
            [CANONICAL_WIDTH - 1, CANONICAL_HEIGHT - 1],
            [0, CANONICAL_HEIGHT - 1],
        ],
        dtype=np.float32,
    )
    padding = max(2, int(np.ceil(blur_sigma * 4.0)) + 2)
    left = max(0, int(np.floor(np.min(destination_quad[:, 0]))) - padding)
    top = max(0, int(np.floor(np.min(destination_quad[:, 1]))) - padding)
    right = min(output_width, int(np.ceil(np.max(destination_quad[:, 0]))) + padding + 1)
    bottom = min(output_height, int(np.ceil(np.max(destination_quad[:, 1]))) + padding + 1)
    if right <= left or bottom <= top:
        empty = np.zeros((output_height, output_width, 4), dtype=np.uint8)
        return empty, empty[:, :, 3]
    patch_width, patch_height = right - left, bottom - top
    local_quad = (
        destination_quad - np.asarray([left, top], dtype=np.float64)
    ) * CARD_RENDER_SUPERSAMPLE
    transform = cv2.getPerspectiveTransform(source_quad, local_quad.astype(np.float32))
    alpha_float = alpha.astype(np.float32) / 255.0
    premultiplied = rgba[:, :, :3].astype(np.float32) * alpha_float[:, :, None]
    supersampled_size = (
        patch_width * CARD_RENDER_SUPERSAMPLE,
        patch_height * CARD_RENDER_SUPERSAMPLE,
    )
    warped_alpha = cv2.warpPerspective(
        alpha_float, transform, supersampled_size, flags=cv2.INTER_CUBIC
    )
    warped_premultiplied = cv2.warpPerspective(
        premultiplied, transform, supersampled_size, flags=cv2.INTER_CUBIC
    )
    if blur_sigma > 0:
        warped_alpha = cv2.GaussianBlur(
            warped_alpha, (0, 0), blur_sigma * CARD_RENDER_SUPERSAMPLE
        )
        warped_premultiplied = cv2.GaussianBlur(
            warped_premultiplied, (0, 0), blur_sigma * CARD_RENDER_SUPERSAMPLE
        )
    warped_alpha = cv2.resize(
        warped_alpha, (patch_width, patch_height), interpolation=cv2.INTER_AREA
    )
    warped_premultiplied = cv2.resize(
        warped_premultiplied, (patch_width, patch_height), interpolation=cv2.INTER_AREA
    )
    result = np.zeros((output_height, output_width, 4), dtype=np.uint8)
    supported = warped_alpha > 1e-5
    patch = result[top:bottom, left:right]
    patch[:, :, :3][supported] = np.clip(
        warped_premultiplied[supported] / warped_alpha[supported][:, None], 0, 255
    ).astype(np.uint8)
    patch[:, :, 3] = np.clip(warped_alpha * 255.0, 0, 255).astype(np.uint8)
    return result, result[:, :, 3]


def _shadow_length_scale(z_order: int) -> float:
    return 1.0 + max(0, z_order - 1) * CARD_SHADOW_Z_ORDER_LENGTH_STEP


def _apply_subtle_card_shadow(
    scene: np.ndarray, alpha: np.ndarray, z_order: int, opacity: float
) -> float:
    """Put a short table shadow below a card without changing its target mask."""

    length_scale = _shadow_length_scale(z_order)
    shadow = cv2.GaussianBlur(alpha, (0, 0), CARD_SHADOW_BLUR_SIGMA * length_scale)
    translation = np.float32(
        [
            [1, 0, CARD_SHADOW_OFFSET_PIXELS[0] * length_scale],
            [0, 1, CARD_SHADOW_OFFSET_PIXELS[1] * length_scale],
        ]
    )
    shadow = cv2.warpAffine(shadow, translation, (scene.shape[1], scene.shape[0]))
    weight = shadow.astype(np.float32) / 255.0 * opacity
    scene[:] = np.clip(scene.astype(np.float32) * (1.0 - weight[:, :, None]), 0, 255).astype(
        np.uint8
    )
    return length_scale


def _pose_from_quad(quad: np.ndarray) -> dict[str, np.ndarray | float]:
    short, long = _card_vectors(quad)
    short_length = float(np.linalg.norm(short))
    long_length = float(np.linalg.norm(long))
    if short_length < 1e-8 or long_length < 1e-8:
        raise SyntheticVisibleRegionPlanarGeometryError("card pose has a zero-length edge")
    return {
        "center": np.mean(quad, axis=0),
        "short_axis": short / short_length,
        "long_axis": long / long_length,
        "short_size": short_length,
        "long_size": long_length,
    }


def _rotate(vector: np.ndarray, degrees: float) -> np.ndarray:
    radians = np.deg2rad(degrees)
    matrix = np.asarray(
        [[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]],
        dtype=np.float64,
    )
    return matrix @ vector


def _quad_from_pose(
    center: np.ndarray,
    short_axis: np.ndarray,
    long_axis: np.ndarray,
    short_size: float,
    long_size: float,
) -> np.ndarray:
    short = short_axis * short_size / 2.0
    long = long_axis * long_size / 2.0
    return np.asarray(
        [
            center - short - long,
            center + short - long,
            center + short + long,
            center - short + long,
        ],
        dtype=np.float64,
    )


def _anchor_pose(
    calibration: Mapping[str, Any], width: int, height: int
) -> dict[str, np.ndarray | float]:
    target = np.asarray([width * 0.56, height * 0.55], dtype=np.float64)
    inverse = np.asarray(calibration["table_to_image"], dtype=np.float64)
    candidates = []
    for index in calibration["inlier_indices"]:
        table_quad = calibration["table_quads"][index]
        image_center = np.mean(_apply_homography(inverse, table_quad), axis=0)
        candidates.append((float(np.linalg.norm(image_center - target)), table_quad))
    if not candidates:
        raise SyntheticVisibleRegionPlanarGeometryError("table calibration has no anchor card")
    return _pose_from_quad(min(candidates, key=lambda item: item[0])[1])


def _sample_layouts(anchor: Mapping[str, np.ndarray | float]) -> list[tuple[str, list[np.ndarray]]]:
    center = np.asarray(anchor["center"], dtype=np.float64)
    short_axis = np.asarray(anchor["short_axis"], dtype=np.float64)
    long_axis = np.asarray(anchor["long_axis"], dtype=np.float64)
    short_size = float(anchor["short_size"])
    long_size = float(anchor["long_size"])

    def pose(offset_short: float, offset_long: float, rotation: float) -> np.ndarray:
        return _quad_from_pose(
            center + short_axis * offset_short + long_axis * offset_long,
            _rotate(short_axis, rotation),
            _rotate(long_axis, rotation),
            short_size,
            long_size,
        )

    return [
        ("observed_single_card_pose", [pose(0.0, 0.0, 0.0)]),
        (
            "two_card_overlap",
            [
                pose(-0.14 * short_size, -0.18 * long_size, -7.0),
                pose(0.24 * short_size, 0.17 * long_size, 10.0),
            ],
        ),
        (
            "three_card_overlap",
            [
                pose(-0.28 * short_size, -0.20 * long_size, -12.0),
                pose(0.02 * short_size, 0.08 * long_size, 1.0),
                pose(0.30 * short_size, 0.36 * long_size, 14.0),
            ],
        ),
    ]


def _production_layouts(
    anchor: Mapping[str, np.ndarray | float],
    *,
    count: int,
    seed: int,
) -> list[tuple[str, list[np.ndarray]]]:
    """Create bounded, deterministic 1--4-card layouts around the measured anchor."""

    if count < 1:
        return []
    center = np.asarray(anchor["center"], dtype=np.float64)
    short_axis = np.asarray(anchor["short_axis"], dtype=np.float64)
    long_axis = np.asarray(anchor["long_axis"], dtype=np.float64)
    short_size = float(anchor["short_size"])
    long_size = float(anchor["long_size"])
    rng = np.random.default_rng(seed)
    layouts: list[tuple[str, list[np.ndarray]]] = []
    for index in range(count):
        card_count = PRODUCTION_CARD_COUNT_PATTERN[index % len(PRODUCTION_CARD_COUNT_PATTERN)]
        base = (
            center
            + short_axis * rng.uniform(-0.24, 0.24) * short_size
            + long_axis * rng.uniform(-0.34, 0.34) * long_size
        )
        table_quads = []
        for _card_index in range(card_count):
            local_center = (
                base
                + short_axis * rng.uniform(-0.46, 0.46) * short_size
                + long_axis * rng.uniform(-0.58, 0.58) * long_size
            )
            local_rotation = float(rng.uniform(-32.0, 32.0))
            table_quads.append(
                _quad_from_pose(
                    local_center,
                    _rotate(short_axis, local_rotation),
                    _rotate(long_axis, local_rotation),
                    short_size,
                    long_size,
                )
            )
        layouts.append((f"production_{index:04d}_{card_count}card_messy", table_quads))
    return layouts


def _render_scene(
    repository: Path,
    output_root: Path,
    *,
    scene_id: str,
    image_id: int,
    background: Mapping[str, Any],
    background_path: Path,
    background_sha256: str,
    layout_name: str,
    table_quads: Sequence[np.ndarray],
    table_to_image: np.ndarray,
    assets: Sequence[Mapping[str, Any]],
    calibration: Mapping[str, Any],
    appearance: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    scene = cv2.imread(str(background_path), cv2.IMREAD_COLOR)
    if scene is None:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"could not decode empty background {background_path}"
        )
    height, width = scene.shape[:2]
    variation = _scene_variation(scene_id)
    card_saturation_factor = CARD_SATURATION_FACTOR * float(
        variation["card_saturation_multiplier"]
    )
    card_shadow_opacity = CARD_SHADOW_OPACITY * float(
        variation["card_shadow_opacity_multiplier"]
    )
    placements: list[dict[str, Any]] = []
    for index, (table_quad, asset) in enumerate(zip(table_quads, assets, strict=True), start=1):
        record = asset["record"]
        rgba, alpha = _read_card_asset(asset)
        image_quad = _apply_homography(table_to_image, table_quad)
        balanced_rgba, white_balance_gain = _white_balanced_scan(
            rgba, alpha, appearance["paper_bgr"]
        )
        adjusted_rgba = _reduce_scan_saturation(
            balanced_rgba, alpha, card_saturation_factor
        )
        blur_sigma = _card_blur_sigma(image_quad, appearance) * float(
            variation["card_blur_multiplier"]
        )
        warped, warped_alpha = _warp_soft_card(
            adjusted_rgba, alpha, image_quad, width, height, blur_sigma
        )
        full_mask = np.where(warped_alpha >= MIN_MASK_ALPHA, 255, 0).astype(np.uint8)
        full_mask = _remove_small_components(full_mask, MIN_VISIBLE_PIXELS)
        placements.append(
            {
                "instance_index": index,
                "z_order": index,
                "table_quad": table_quad,
                "image_quad": image_quad,
                "cutout_id": str(record["cutout_id"]),
                "source_asset_id": str(record["source_asset_id"]),
                "side": str(record["reviewed_decision"]["card_side"]),
                "source_group": dict(record["source_group"]),
                "full_mask": full_mask,
                "warped_rgba": warped,
                "alpha": warped_alpha,
                "white_balance_gain_bgr": white_balance_gain,
                "saturation_factor": _round(card_saturation_factor),
                "blur_sigma": _round(blur_sigma),
                "deck_card_name": record.get("deck_card_name"),
                "source_frame": record.get("source_frame"),
                "source_quadrilateral": record["source_quadrilateral"],
            }
        )
    full_masks = [item["full_mask"] for item in placements]
    visible_masks = [
        _remove_small_components(mask, MIN_VISIBLE_PIXELS)
        for mask in _derive_visible_masks(full_masks, list(reversed(range(len(full_masks)))))
    ]
    for placement in placements:
        placement["shadow_length_scale"] = _apply_subtle_card_shadow(
            scene, placement["alpha"], int(placement["z_order"]), card_shadow_opacity
        )
        _alpha_composite(scene, placement["warped_rgba"], placement["alpha"])
    _apply_scene_variation(scene, variation)
    ok, encoded = cv2.imencode(
        ".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, int(variation["jpeg_quality"])]
    )
    if not ok:
        raise SyntheticVisibleRegionPlanarGeometryError(f"could not encode scene {scene_id}")
    image_path = output_root / "images" / f"{scene_id}.jpg"
    image_digest = _write_bytes(image_path, encoded.tobytes())

    instances: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for placement, visible_mask in zip(placements, visible_masks, strict=True):
        visible_pixels = int(np.count_nonzero(visible_mask))
        if visible_pixels < MIN_VISIBLE_PIXELS:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"{scene_id} creates a card below the visible-pixel threshold"
            )
        polygons = _mask_polygons(visible_mask)
        if not polygons:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"{scene_id} creates a card with no visible polygon"
            )
        mask_path = (
            output_root / "masks" / f"{scene_id}-instance-{placement['instance_index']:02d}.png"
        )
        ok, encoded_mask = cv2.imencode(".png", visible_mask)
        if not ok:
            raise SyntheticVisibleRegionPlanarGeometryError(f"could not encode {scene_id} mask")
        mask_digest = _write_bytes(mask_path, encoded_mask.tobytes())
        bbox = _mask_bbox(visible_mask)
        area = sum(
            _polygon_area(list(zip(polygon[::2], polygon[1::2], strict=True)))
            for polygon in polygons
        ) / 2.0
        instance = {
            "instance_index": placement["instance_index"],
            "cutout_id": placement["cutout_id"],
            "source_asset_id": placement["source_asset_id"],
            "deck_card_name": placement["deck_card_name"],
            "side": placement["side"],
            "z_order": placement["z_order"],
            "source_group": placement["source_group"],
            "source_frame": placement["source_frame"],
            "source_quadrilateral": placement["source_quadrilateral"],
            "table_quadrilateral": _quad_to_records(placement["table_quad"]),
            "target_quadrilateral": _quad_to_records(placement["image_quad"]),
            "scale": _round(
                float(np.sqrt(abs(cv2.contourArea(placement["image_quad"].astype(np.float32)))))
                / max(width, height)
            ),
            "center_normalized": [
                _round(float(np.mean(placement["image_quad"][:, 0])) / width),
                _round(float(np.mean(placement["image_quad"][:, 1])) / height),
            ],
            "clipped": bool(
                np.any(placement["image_quad"][:, 0] < 0)
                or np.any(placement["image_quad"][:, 0] >= width)
                or np.any(placement["image_quad"][:, 1] < 0)
                or np.any(placement["image_quad"][:, 1] >= height)
            ),
            "full_mask_pixels": int(np.count_nonzero(placement["full_mask"])),
            "visible_mask_pixels": visible_pixels,
            "occlusion_ratio": _occlusion_ratio(placement["full_mask"], visible_mask),
            "appearance": {
                "white_balance_gain_bgr": placement["white_balance_gain_bgr"],
                "saturation_factor": placement["saturation_factor"],
                "blur_sigma": placement["blur_sigma"],
                "shadow_length_scale": _round(placement["shadow_length_scale"]),
                "mask_alpha_threshold": MIN_MASK_ALPHA,
            },
            "mask": {
                "path": _relative(mask_path, repository),
                "sha256": mask_digest,
                "bbox": bbox,
                "polygons": polygons,
            },
        }
        instances.append(instance)
        annotation_id = int(
            hashlib.sha256(f"{scene_id}:{placement['instance_index']}".encode()).hexdigest()[:12],
            16,
        )
        annotations.append(
            {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": 1,
                "bbox": bbox,
                "area": _round(area),
                "segmentation": polygons,
                "iscrowd": 0,
                "target_state": "synthetic_visible_region",
                "recording_id": scene_id,
                "event_id": scene_id,
                "item_id": placement["cutout_id"],
                "reference_revision_id": "synthetic-visible-region-planar-geometry-v1",
                "card_id": placement["cutout_id"],
                "source_video_sha256": str(background["source_group"]["source_sha256"]),
                "source_frame_sha256": image_digest,
                "target_geometry_sha256": _sha256_bytes(
                    canonical_json_bytes(placement["image_quad"].tolist())
                ),
                "split": "train",
                "card_side": placement["side"],
                "session_id": f"synthetic-planar-{background['background_id']}",
                "source_asset_id": placement["source_asset_id"],
                "video_id": scene_id,
                "table_setup": str(background["source_group"]["table_setup"]),
                "source_group_key": str(background["source_group"]["key"]),
            }
        )
    receipt_core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CAMPAIGN_ID,
        "milestone": "M5-geometry-revision",
        "scene_id": scene_id,
        "layout": layout_name,
        "background": {
            "strategy": BACKGROUND_STRATEGY,
            "background_id": background["background_id"],
            "reviewed_decision": background["reviewed_decision"],
            "source_group": background["source_group"],
            "frame_identity": background["frame_identity"],
            "path": _relative(background_path, repository),
            "sha256": background_sha256,
        },
        "table_calibration": {
            key: value
            for key, value in calibration.items()
            if key
            not in {
                "image_to_table",
                "table_to_image",
                "oriented_image_quads",
                "table_quads",
                "inlier_indices",
            }
        },
        "placements": instances,
        "card_appearance": dict(appearance),
        "scene_variation": variation,
        "output": {
            "image": {
                "path": _relative(image_path, repository),
                "sha256": image_digest,
                "width": width,
                "height": height,
            }
        },
        "source_lineage": {
            "permission": "training_only",
            "split": "train",
            "source_group_keys": sorted(
                {str(background["source_group"]["key"])}
                | {str(item["source_group"]["key"]) for item in instances}
            ),
        },
        "renderer": {
            "opencv_version": cv2.__version__,
            "numpy_version": np.__version__,
            "python_version": platform.python_version(),
            "mask_policy": "rounded-alpha-card-z-order-and-frame-clipping-v1",
            "photometric_policy": (
                "scene-shared-white-balance-desaturation-reduced-blur-contact-shadow-"
                "global-finish-and-supersampled-card-warp-v1"
            ),
        },
    }
    receipt = {
        **receipt_core,
        "receipt_digest": _sha256_bytes(canonical_json_bytes(receipt_core)),
    }
    receipt_path = output_root / "receipts" / f"{scene_id}.json"
    _write_json(receipt_path, receipt)
    summary = {
        "scene_id": scene_id,
        "layout": layout_name,
        "card_count": len(instances),
        "bucket": {
            1: "fully_visible_card",
            2: "overlapping_cards_shallow",
            3: "overlapping_cards_medium",
            4: "overlapping_cards_heavy",
        }[len(instances)],
        "background": {
            "background_id": background["background_id"],
            "strategy": BACKGROUND_STRATEGY,
            "reviewed_decision": background["reviewed_decision"],
        },
        "table_calibration_digest": calibration["calibration_digest"],
        "photometric_effects": {
            "table_paper_bgr": appearance["paper_bgr"],
            "reference_card_count": appearance["reference_card_count"],
            "card_saturation_factor": _round(card_saturation_factor),
            "card_shadow_opacity": _round(card_shadow_opacity),
            "card_shadow_blur_sigma": CARD_SHADOW_BLUR_SIGMA,
            "card_shadow_z_order_length_step": CARD_SHADOW_Z_ORDER_LENGTH_STEP,
            "card_render_supersample": CARD_RENDER_SUPERSAMPLE,
            "scene_variation": variation,
        },
        "image_path": _relative(image_path, repository),
        "image_sha256": image_digest,
        "receipt_path": _relative(receipt_path, repository),
        "receipt_digest": receipt["receipt_digest"],
        "instance_count": len(instances),
    }
    image = {
        "id": image_id,
        "file_name": _relative(image_path, output_root),
        "width": width,
        "height": height,
        "sha256": image_digest,
        "recording_id": scene_id,
        "event_id": scene_id,
        "item_id": background["background_id"],
        "reference_revision_id": "synthetic-visible-region-planar-geometry-v1",
        "source_video_sha256": str(background["source_group"]["source_sha256"]),
        "source_frame_sha256": image_digest,
        "split": "train",
        "trainer_partition": "train",
        "session_id": f"synthetic-planar-{background['background_id']}",
        "source_asset_id": background["background_id"],
        "video_id": scene_id,
        "table_setup": str(background["source_group"]["table_setup"]),
        "source_group_key": str(background["source_group"]["key"]),
        "dataset_origin": "synthetic",
        "background_strategy": BACKGROUND_STRATEGY,
    }
    return summary, image, annotations


def build_synthetic_visible_region_planar_geometry_samples(
    repository_root: str | Path,
    *,
    source_manifest_path: str | Path = SOURCE_MANIFEST_DEFAULT,
    m1_manifest_path: str | Path = M1_MANIFEST_DEFAULT,
    card_source_directory: str | Path = SCANNED_DECK_SOURCE_DEFAULT,
    output_directory: str | Path = OUTPUT_DIRECTORY_DEFAULT,
    sample_count: int = SAMPLE_COUNT_DEFAULT,
    recording_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Create a bounded, deterministic appearance-review set from selected stable recordings."""

    if not 1 <= sample_count <= MAX_REVIEW_SCENE_COUNT:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"sample_count must be between one and {MAX_REVIEW_SCENE_COUNT}"
        )
    repository = Path(repository_root).expanduser().resolve()
    requested_recordings = set(recording_ids) if recording_ids is not None else None
    discovery = build_synthetic_visible_region_recording_discovery(
        repository, source_manifest_path=source_manifest_path, max_card_count=MAX_CARD_COUNT_DEFAULT
    )
    m1_path = _resolve(repository, m1_manifest_path)
    m1 = _read_json(m1_path, "M1 input manifest")
    try:
        validate_synthetic_visible_region_inputs(m1)
    except ValueError as error:
        raise SyntheticVisibleRegionPlanarGeometryError(
            f"M1 input manifest is invalid: {error}"
        ) from error
    backgrounds = _empty_backgrounds(repository, m1, requested_recordings)
    if not backgrounds:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "no accepted reviewed empty training table matches the selected recordings"
        )
    output_root = _resolve(repository, output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    scanned_assets = _scanned_deck_assets(repository, card_source_directory)

    calibrations: list[dict[str, Any]] = []
    appearances: dict[str, dict[str, Any]] = {}
    layout_plans: list[list[tuple[Mapping[str, Any], dict[str, Any], str, list[np.ndarray]]]] = []
    review_layouts = sample_count <= 36
    layout_count = max(3, int(np.ceil(sample_count / len(backgrounds))))
    for background_item in backgrounds:
        background = background_item["record"]
        background_image = cv2.imread(str(background_item["path"]), cv2.IMREAD_COLOR)
        if background_image is None:
            raise SyntheticVisibleRegionPlanarGeometryError(
                f"could not decode empty background {background_item['path']}"
            )
        quads, provenance = _recording_geometry(discovery, background)
        calibration = fit_table_plane(quads)
        calibration_summary = {
            key: value
            for key, value in calibration.items()
            if key
            not in {
                "image_to_table",
                "table_to_image",
                "oriented_image_quads",
                "table_quads",
                "inlier_indices",
            }
        }
        calibration_summary.update(
            {
                "recording_id": str(background["source_group"]["id"]),
                "table_setup": str(background["source_group"]["table_setup"]),
                "background_id": str(background["background_id"]),
                "background_strategy": BACKGROUND_STRATEGY,
                "accepted_geometry_sources": [
                    provenance[index] for index in calibration["inlier_indices"]
                ],
            }
        )
        calibrations.append(calibration_summary)
        appearances[str(background["background_id"])] = _table_card_appearance(
            repository,
            output_root,
            discovery,
            background,
            source_manifest_path,
        )
        anchor = _anchor_pose(calibration, background_image.shape[1], background_image.shape[0])
        layout_plans.append(
            [
                (background_item, calibration, layout_name, layout_quads)
                for layout_name, layout_quads in (
                    _sample_layouts(anchor)
                    if review_layouts
                    else _production_layouts(
                        anchor,
                        count=layout_count,
                        seed=int.from_bytes(
                            hashlib.sha256(str(background["background_id"]).encode()).digest()[:8],
                            "big",
                        ),
                    )
                )
            ]
        )
    plans = [
        plan
        for layout_index in range(3)
        for layouts in layout_plans
        for plan in [layouts[layout_index]]
    ]
    plans.extend(
        plan
        for layout_index in range(3, layout_count)
        for layouts in layout_plans
        for plan in [layouts[layout_index]]
    )
    plans = plans[:sample_count]
    if len(plans) < sample_count:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "selected recordings do not provide enough geometry sample layouts"
        )

    summaries: list[dict[str, Any]] = []
    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    for index, (background_item, calibration, layout_name, table_quads) in enumerate(plans):
        background = background_item["record"]
        recording_id = str(background["source_group"]["id"])
        assets = _selected_scan_assets(scanned_assets, len(table_quads), index)
        scene_id = f"scene-{index:02d}-{recording_id}-{layout_name}"
        summary, image, annotations = _render_scene(
            repository,
            output_root,
            scene_id=scene_id,
            image_id=index + 1,
            background=background,
            background_path=background_item["path"],
            background_sha256=background_item["sha256"],
            layout_name=layout_name,
            table_quads=table_quads,
            table_to_image=np.asarray(calibration["table_to_image"], dtype=np.float64),
            assets=assets,
            calibration=calibration,
            appearance=appearances[str(background["background_id"])],
        )
        summaries.append(summary)
        coco_images.append(image)
        coco_annotations.extend(annotations)
    coco = {
        "info": {
            "description": "Geometry-only synthetic visible-card samples on reviewed empty tables",
            "version": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION,
            "coco_version": "coco-2017",
            "campaign_id": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CAMPAIGN_ID,
            "trainer_partition": "train",
        },
        "licenses": [],
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": [{"id": 1, "name": "visible_card", "supercategory": "card"}],
    }
    validate_rfdetr_coco_annotations(coco)
    coco_path = output_root / "_annotations.coco.json"
    coco_digest = _write_json(coco_path, coco)
    core = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_CAMPAIGN_ID,
        "milestone": "M5-geometry-revision",
        "freeze_state": "geometry_samples_ready_for_operator_review",
        "source_manifest": {
            "path": _relative(_resolve(repository, source_manifest_path), repository),
            "sha256": _sha256_file(_resolve(repository, source_manifest_path)),
            "manifest_digest": discovery["source_manifest"]["manifest_digest"],
        },
        "m1_manifest": {
            "path": _relative(m1_path, repository),
            "sha256": _sha256_file(m1_path),
            "manifest_digest": m1["manifest_digest"],
        },
        "policy": {
            "background_strategy": BACKGROUND_STRATEGY,
            "table_geometry_method": "multi-card-planar-metric-rectification-v1",
            "card_aspect_ratio": CARD_ASPECT_RATIO,
            "card_source_directory": _relative(
                _resolve(repository, card_source_directory), repository
            ),
            "card_source": "upright-ass-altenburger-romme-french-scans-v1",
            "geometry_sources": "complete-reviewed-four-point-cards-from-the-same-recording",
            "photometric_effects": (
                "same-table reviewed-card paper white balance, scan desaturation, rounded alpha, "
                "reduced card-scale blur, and a subtle shadow"
            ),
            "sample_count": sample_count,
            "recording_ids": sorted(requested_recordings) if requested_recordings else None,
        },
        "inventory": {
            "empty_background_count": len(backgrounds),
            "calibrated_recording_count": len(calibrations),
            "sample_scene_count": len(summaries),
            "sample_annotation_count": len(coco_annotations),
            "sample_scene_counts_by_card_count": dict(
                sorted(Counter(str(item["card_count"]) for item in summaries).items())
            ),
        },
        "calibrations": calibrations,
        "outputs": {
            "directory": _relative(output_root, repository),
            "coco": {"path": _relative(coco_path, repository), "sha256": coco_digest},
            "scene_count": len(summaries),
            "image_count": len(coco_images),
            "annotation_count": len(coco_annotations),
        },
        "scenes": summaries,
        "coverage_gaps": [
            "only recordings with an accepted full-frame-reviewed empty training table can render",
            "camera height, distance, and intrinsics are not identified; the calibrated "
            "table-plane homography is sufficient for planar card placement",
            "shadow, glare, random scene lighting, and compression changes are intentionally "
            "absent from this appearance review",
        ],
    }
    return {**core, "manifest_digest": _sha256_bytes(canonical_json_bytes(core))}


def write_synthetic_visible_region_planar_geometry_manifest(
    path: str | Path, manifest: Mapping[str, Any]
) -> Path:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return destination


def validate_synthetic_visible_region_planar_geometry_manifest(raw: Mapping[str, Any]) -> None:
    """Validate a completed planar-geometry scene manifest before training-view merge."""

    required = {
        "schema_version",
        "campaign_id",
        "milestone",
        "freeze_state",
        "source_manifest",
        "m1_manifest",
        "policy",
        "inventory",
        "calibrations",
        "outputs",
        "scenes",
        "coverage_gaps",
        "manifest_digest",
    }
    if set(raw) != required:
        raise SyntheticVisibleRegionPlanarGeometryError(
            "planar-geometry manifest has invalid fields"
        )
    if raw["schema_version"] != SYNTHETIC_VISIBLE_REGION_PLANAR_GEOMETRY_SCHEMA_VERSION:
        raise SyntheticVisibleRegionPlanarGeometryError("planar-geometry schema is unsupported")
    if raw["milestone"] != "M5-geometry-revision":
        raise SyntheticVisibleRegionPlanarGeometryError("planar-geometry milestone is invalid")
    if raw["freeze_state"] != "geometry_samples_ready_for_operator_review":
        raise SyntheticVisibleRegionPlanarGeometryError("planar-geometry state is invalid")
    if not isinstance(raw["scenes"], list) or not raw["scenes"]:
        raise SyntheticVisibleRegionPlanarGeometryError("planar-geometry manifest has no scenes")
    if not isinstance(raw["coverage_gaps"], list):
        raise SyntheticVisibleRegionPlanarGeometryError("planar-geometry coverage gaps are invalid")
    outputs = raw["outputs"]
    if not isinstance(outputs, Mapping) or not isinstance(outputs.get("coco"), Mapping):
        raise SyntheticVisibleRegionPlanarGeometryError("planar-geometry COCO output is missing")
    core = {key: raw[key] for key in required if key != "manifest_digest"}
    if raw["manifest_digest"] != _sha256_bytes(canonical_json_bytes(core)):
        raise SyntheticVisibleRegionPlanarGeometryError("planar-geometry manifest digest is stale")


def render_synthetic_visible_region_planar_geometry_human(manifest: Mapping[str, Any]) -> str:
    inventory = manifest["inventory"]
    return "\n".join(
        [
            "Epic 0070 planar table-geometry review samples",
            f"state: {manifest['freeze_state']}",
            f"reviewed empty tables: {inventory['empty_background_count']}",
            f"calibrated recordings: {inventory['calibrated_recording_count']}",
            f"geometry-only samples: {inventory['sample_scene_count']}",
            f"COCO: {manifest['outputs']['coco']['path']}",
        ]
    ) + "\n"


__all__ = [
    "MANIFEST_DEFAULT",
    "M1_MANIFEST_DEFAULT",
    "OUTPUT_DIRECTORY_DEFAULT",
    "SAMPLE_COUNT_DEFAULT",
    "SyntheticVisibleRegionPlanarGeometryError",
    "_apply_homography",
    "build_synthetic_visible_region_planar_geometry_samples",
    "fit_table_plane",
    "render_synthetic_visible_region_planar_geometry_human",
    "validate_synthetic_visible_region_planar_geometry_manifest",
    "write_synthetic_visible_region_planar_geometry_manifest",
]
