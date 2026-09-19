"""Materialize operator-reviewed card cutouts for epic 0070 M1.

The source photos are training-only inputs.  This module does not infer card identity and does
not create table backgrounds.  It uses a fixed OpenCV extraction recipe so a cold and warm run
produce the same cutout files and receipt.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .derived_view import FFmpegFrameResolver, resolve_exact_event
from .pipeline_data import RecordingVideoSource
from .reviewed_rfdetr_detector_campaign import canonical_json_bytes

SYNTHETIC_VISIBLE_REGION_INPUTS_SCHEMA_VERSION = "synthetic-visible-region-inputs/v1"
SYNTHETIC_VISIBLE_REGION_INPUTS_CAMPAIGN_ID = "0070-m1-synthetic-visible-region-inputs"
SOURCE_DIRECTORY_DEFAULT = "data/decks/old"
OUTPUT_DIRECTORY_DEFAULT = ".runtime/synthetic-visible-region-0070-m1"
MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m1-inputs.json"
M0_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m0-manifest.json"
MATERIALIZATION_DIRECTORY_DEFAULT = ".runtime/rfdetr-segmentation-0068"
TABLE_INPUT_SPEC_DEFAULT = ".runtime/synthetic-visible-region-0070-m1-table-inputs.json"
CANONICAL_WIDTH = 640
CANONICAL_HEIGHT = 960
CANONICAL_CORNER_RADIUS = 28
GRID_ROWS = 4
GRID_COLUMNS = 5
GRID_COLUMN_CENTERS = (0.18, 0.34, 0.50, 0.67, 0.84)
GRID_ROW_CENTERS = (0.12, 0.35, 0.60, 0.85)
GRID_CELL_HALF_WIDTH = 0.11
# The first and last grid rows sit close to the photo edges.  A taller cell keeps the full
# rounded card in the working crop; component selection still prefers the central card when
# neighboring rows enter the expanded crop.
GRID_CELL_HALF_HEIGHT = 0.17
SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".heic", ".heif", ".png"})
FACE_UP = "face_up"
SOURCE_PERMISSION = "training_only"
SOURCE_GROUP_ID = "0070-user-supplied-decks-old"
SOURCE_GROUP_KEY = hashlib.sha256(SOURCE_GROUP_ID.encode("utf-8")).hexdigest()
_SHA256_LENGTH = 64


class SyntheticVisibleRegionMaterializationError(ValueError):
    """Raised when M1 input materialization cannot produce a safe receipt."""


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


def _round(value: float) -> float:
    return round(float(value), 6)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionMaterializationError(f"JSON object required: {path}")
    return dict(value)


def _sips_version() -> str | None:
    executable = shutil.which("sips")
    if executable is None:
        return None
    result = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, check=False
    )
    output = (result.stdout or result.stderr).strip()
    return output or None


def _decode_source(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".heic", ".heif"}:
        executable = shutil.which("sips")
        if executable is None:
            raise SyntheticVisibleRegionMaterializationError(
                f"HEIC source requires the macOS sips decoder: {path}"
            )
        with tempfile.TemporaryDirectory(prefix="doko-deck-decode-") as temporary:
            decoded = Path(temporary) / "decoded.png"
            result = subprocess.run(
                [executable, "-s", "format", "png", str(path), "--out", str(decoded)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 or not decoded.is_file():
                detail = (result.stderr or result.stdout).strip()
                raise SyntheticVisibleRegionMaterializationError(
                    f"could not decode HEIC source {path}: {detail}"
                )
            image = cv2.imread(str(decoded), cv2.IMREAD_COLOR)
        decoder = {"name": "sips", "version": _sips_version(), "output": "png"}
    else:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        decoder = {"name": "opencv", "version": cv2.__version__, "output": "source"}
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise SyntheticVisibleRegionMaterializationError(f"could not decode image source: {path}")
    return image, decoder


def _order_quad(points: np.ndarray) -> np.ndarray:
    """Return four points in a stable clockwise order starting near the top left."""

    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    start = int(np.argmin(ordered[:, 0] + ordered[:, 1]))
    ordered = np.roll(ordered, -start, axis=0)
    # Image coordinates use a positive y axis downwards.  Keep the same winding as the
    # destination rectangle so the perspective transform cannot silently mirror a cutout.
    first_edge = ordered[1] - ordered[0]
    second_edge = ordered[2] - ordered[1]
    cross = float(first_edge[0] * second_edge[1] - first_edge[1] * second_edge[0])
    if cross < 0:
        ordered = np.concatenate((ordered[:1], ordered[:0:-1]))
    return ordered


def _canonical_quad(points: np.ndarray) -> np.ndarray:
    ordered = _order_quad(points)
    first = float(np.linalg.norm(ordered[1] - ordered[0]))
    second = float(np.linalg.norm(ordered[2] - ordered[1]))
    # The card's short edge is the canonical top edge.  This normalizes cards photographed
    # in landscape without making any identity or orientation claim.
    if first > second:
        ordered = np.roll(ordered, -1, axis=0)
    return ordered


def _quad_from_contour(contour: np.ndarray) -> np.ndarray:
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    for epsilon in (0.02, 0.03, 0.04, 0.05, 0.07, 0.10):
        approximation = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approximation) == 4:
            return _canonical_quad(approximation.reshape(4, 2))
    rectangle = cv2.boxPoints(cv2.minAreaRect(hull))
    return _canonical_quad(rectangle)


def _select_card_component(binary: np.ndarray) -> np.ndarray:
    """Return the largest plausible card component, preferring a central component."""

    components, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
    if components <= 1:
        raise SyntheticVisibleRegionMaterializationError("OpenCV did not find a card component")
    height, width = binary.shape[:2]
    candidates: list[tuple[float, int]] = []
    image_area = float(width * height)
    for component_index in range(1, components):
        x, y, component_width, component_height, area = stats[component_index]
        area_ratio = float(area) / image_area
        if not 0.08 <= area_ratio <= 0.90:
            continue
        if (
            x <= 0
            or y <= 0
            or x + component_width >= width - 1
            or y + component_height >= height - 1
        ):
            continue
        center_x, center_y = centroids[component_index]
        distance = float(
            np.hypot((center_x - width / 2) / width, (center_y - height / 2) / height)
        )
        # A card is the large, central bright object on the dark surface.  The small centrality
        # bonus avoids selecting a bright table reflection without overriding a clearly larger
        # card component.
        candidates.append((float(area) * (1.0 - min(0.25, distance)), component_index))
    if not candidates:
        raise SyntheticVisibleRegionMaterializationError(
            "OpenCV did not find a bounded card component on the dark surface"
        )
    component_index = max(candidates)[1]
    return np.where(labels == component_index, 255, 0).astype(np.uint8)


def _edge_card_component(image: np.ndarray) -> np.ndarray:
    """Extract a rounded card silhouette from a dark surface with Canny-supported edges.

    The luminance mask supplies the card interior.  Canny edges supply the outer boundary, which
    keeps rounded corners and excludes the dark surface.  The two signals are deliberately
    combined: card artwork creates many internal edges, while the bright connected component
    identifies which closed outer contour belongs to the card.
    """

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    threshold, bright = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    # The table wood in the individual HEIC photos has bright reflections.  A threshold close
    # to Otsu therefore joins the table to the card.  Keep a high white-card threshold while
    # allowing a small amount of variation between photos.
    threshold = max(185.0, min(float(threshold) + 70.0, 205.0))
    bright = np.where(blurred >= threshold, 255, 0).astype(np.uint8)
    bright = cv2.morphologyEx(
        bright, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    )
    bright = cv2.morphologyEx(
        bright, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )
    bright_component = _select_card_component(bright)
    bright_contours, _ = cv2.findContours(
        bright_component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    if not bright_contours:
        raise SyntheticVisibleRegionMaterializationError(
            "OpenCV card component has no external contour"
        )
    bright_outer = np.zeros_like(bright_component)
    cv2.drawContours(
        bright_outer, [max(bright_contours, key=cv2.contourArea)], -1, 255, cv2.FILLED
    )

    # The thresholded card can lose the dark rounded border.  Close the Canny edge ring, fill
    # external contours, and use the bright component to choose the card-owned ring.
    lower = max(12, int(threshold * 0.16))
    upper = max(lower + 20, int(threshold * 0.48))
    edges = cv2.Canny(blurred, lower, upper, L2gradient=True)
    edges = cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
        iterations=2,
    )
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    bright_area = float(np.count_nonzero(bright_component))
    best: tuple[float, np.ndarray] | None = None
    height, width = gray.shape[:2]
    for contour in contours:
        area = float(cv2.contourArea(contour))
        area_ratio = area / float(width * height)
        if not 0.08 <= area_ratio <= 0.90:
            continue
        x, y, component_width, component_height = cv2.boundingRect(contour)
        if (
            x <= 0
            or y <= 0
            or x + component_width >= width - 1
            or y + component_height >= height - 1
        ):
            continue
        candidate = np.zeros_like(bright_component)
        cv2.drawContours(candidate, [contour], -1, 255, cv2.FILLED)
        intersection = float(np.count_nonzero(cv2.bitwise_and(candidate, bright_component)))
        union = float(np.count_nonzero(cv2.bitwise_or(candidate, bright_component)))
        if union <= 0.0:
            continue
        iou = intersection / union
        center_x, center_y = np.mean(contour.reshape(-1, 2), axis=0)
        centrality = 1.0 - min(
            0.25, float(np.hypot((center_x - width / 2) / width, (center_y - height / 2) / height))
        )
        score = iou * centrality * min(1.0, area / max(1.0, bright_area))
        if best is None or score > best[0]:
            best = (score, candidate)

    # Use the Canny-filled outer contour when it is available.  It fills every dark artwork pixel
    # while following the edge ring.  The thresholded outer contour is the safe fallback for
    # photos where glare breaks the card's outer edge.
    if best is None or best[0] < 0.25:
        return bright_outer
    return best[1]


def _extract_mask(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Extract one card mask and its source quadrilateral from the dark surface."""

    original_height, original_width = image.shape[:2]
    scale = min(1.0, 900.0 / max(original_height, original_width))
    if scale < 1.0:
        working = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        working = image
    component = _edge_card_component(working)
    contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise SyntheticVisibleRegionMaterializationError("OpenCV card component has no contour")
    contour = max(contours, key=cv2.contourArea)
    quad = _quad_from_contour(contour)
    if scale < 1.0:
        quad = quad / scale
        source_mask = cv2.resize(
            component, (original_width, original_height), interpolation=cv2.INTER_NEAREST
        )
    else:
        source_mask = component
    return source_mask, quad


def _grid_cell(image: np.ndarray, row: int, column: int) -> tuple[np.ndarray, int, int]:
    height, width = image.shape[:2]
    x0 = max(0, round((GRID_COLUMN_CENTERS[column] - GRID_CELL_HALF_WIDTH) * width))
    x1 = min(width, round((GRID_COLUMN_CENTERS[column] + GRID_CELL_HALF_WIDTH) * width))
    y0 = max(0, round((GRID_ROW_CENTERS[row] - GRID_CELL_HALF_HEIGHT) * height))
    y1 = min(height, round((GRID_ROW_CENTERS[row] + GRID_CELL_HALF_HEIGHT) * height))
    return image[y0:y1, x0:x1], x0, y0


def _extract_source_card(
    image: np.ndarray, *, mode: str, row: int | None = None, column: int | None = None
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    if mode == "grid":
        if row is None or column is None:
            raise SyntheticVisibleRegionMaterializationError("grid card is missing its cell")
        cell, offset_x, offset_y = _grid_cell(image, row, column)
        cell_mask, quad = _extract_mask(cell)
        quad = quad + np.array([offset_x, offset_y], dtype=np.float32)
        full_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        height, width = cell.shape[:2]
        full_mask[offset_y : offset_y + height, offset_x : offset_x + width] = cell_mask
        source_mask = full_mask
        grid = {"row": row, "column": column}
    else:
        source_mask, quad = _extract_mask(image)
        grid = {}
    return source_mask, quad, grid


def _rectify(
    image: np.ndarray, source_mask: np.ndarray, source_quad: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    destination_quad = np.array(
        [
            [0, 0],
            [CANONICAL_WIDTH - 1, 0],
            [CANONICAL_WIDTH - 1, CANONICAL_HEIGHT - 1],
            [0, CANONICAL_HEIGHT - 1],
        ],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(source_quad.astype(np.float32), destination_quad)
    inverse = cv2.getPerspectiveTransform(destination_quad, source_quad.astype(np.float32))
    roundtrip = cv2.perspectiveTransform(destination_quad[None, :, :], inverse)[0]
    roundtrip_error = float(np.max(np.linalg.norm(roundtrip - source_quad, axis=1)))
    color = cv2.warpPerspective(
        image, transform, (CANONICAL_WIDTH, CANONICAL_HEIGHT), flags=cv2.INTER_CUBIC
    )
    alpha = cv2.warpPerspective(
        source_mask, transform, (CANONICAL_WIDTH, CANONICAL_HEIGHT), flags=cv2.INTER_NEAREST
    )
    alpha = np.where(alpha >= 128, 255, 0).astype(np.uint8)
    # The projective quad describes the card's straight edges.  Its four virtual intersections
    # sit outside the rounded physical corners, so retain the observed contour and apply the
    # measured canonical corner radius after the warp.
    rounded = np.zeros_like(alpha)
    radius = CANONICAL_CORNER_RADIUS
    cv2.rectangle(
        rounded, (radius, 0), (CANONICAL_WIDTH - radius - 1, CANONICAL_HEIGHT - 1), 255, -1
    )
    cv2.rectangle(
        rounded, (0, radius), (CANONICAL_WIDTH - 1, CANONICAL_HEIGHT - radius - 1), 255, -1
    )
    for center in (
        (radius, radius),
        (CANONICAL_WIDTH - radius - 1, radius),
        (radius, CANONICAL_HEIGHT - radius - 1),
        (CANONICAL_WIDTH - radius - 1, CANONICAL_HEIGHT - radius - 1),
    ):
        cv2.circle(rounded, center, radius, 255, -1)
    alpha = cv2.bitwise_and(alpha, rounded)
    rgba = cv2.cvtColor(color, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = alpha
    return rgba, alpha, roundtrip_error


def _source_id(path: Path) -> str:
    stem = path.stem.lower().replace(" ", "-")
    return f"deck-old-{stem}"


def _write_file(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha256_bytes(data)


def _materialize_cutout(
    repository: Path,
    output_root: Path,
    image: np.ndarray,
    source_mask: np.ndarray,
    source_quad: np.ndarray,
    source: Mapping[str, Any],
    index: int,
    grid: Mapping[str, int],
) -> dict[str, Any]:
    rgba, alpha, roundtrip_error = _rectify(image, source_mask, source_quad)
    cutout_id = f"{source['source_asset_id']}-{index:02d}"
    image_path = output_root / "cutouts" / f"{cutout_id}.png"
    alpha_path = output_root / "cutouts" / f"{cutout_id}.alpha.png"
    ok, encoded_image = cv2.imencode(".png", rgba)
    if not ok:
        raise SyntheticVisibleRegionMaterializationError(f"could not encode cutout {cutout_id}")
    ok, encoded_alpha = cv2.imencode(".png", alpha)
    if not ok:
        raise SyntheticVisibleRegionMaterializationError(f"could not encode alpha {cutout_id}")
    image_digest = _write_file(image_path, encoded_image.tobytes())
    alpha_digest = _write_file(alpha_path, encoded_alpha.tobytes())
    points = [
        {"x": _round(point[0]), "y": _round(point[1])}
        for point in source_quad.astype(np.float64)
    ]
    source_height, source_width = image.shape[:2]
    alpha_pixels = int(np.count_nonzero(alpha))
    record: dict[str, Any] = {
        "cutout_id": cutout_id,
        "source_asset_id": source["source_asset_id"],
        "source_frame": {
            "path": source["path"],
            "source_file_sha256": source["source_file_sha256"],
            "decoded_pixel_sha256": source["decoded_pixel_sha256"],
            "width": source_width,
            "height": source_height,
        },
        "source_group": dict(source["source_group"]),
        "reviewed_decision": dict(source["reviewed_decision"]),
        "source_quadrilateral": points,
        "grid_cell": dict(grid),
        "canonical": {"width": CANONICAL_WIDTH, "height": CANONICAL_HEIGHT},
        "alpha_pixels": alpha_pixels,
        "alpha_fraction": _round(alpha_pixels / (CANONICAL_WIDTH * CANONICAL_HEIGHT)),
        "roundtrip_max_pixel_error": _round(roundtrip_error),
        "files": {
            "rgba": {"path": _relative(image_path, repository), "sha256": image_digest},
            "alpha": {"path": _relative(alpha_path, repository), "sha256": alpha_digest},
        },
    }
    if source.get("event_id") is not None:
        record["source_frame"]["event_id"] = source["event_id"]
    if source.get("item_id") is not None:
        record["source_frame"]["item_id"] = source["item_id"]
    if source.get("frame_identity") is not None:
        record["source_frame"]["identity"] = source["frame_identity"]
    record["cutout_digest"] = _sha256_bytes(canonical_json_bytes(record))
    return record


def _source_record(
    repository: Path, path: Path, image: np.ndarray, decoder: Mapping[str, Any]
) -> dict[str, Any]:
    height, width = image.shape[:2]
    return {
        "source_asset_id": _source_id(path),
        "path": _relative(path, repository),
        "source_file_sha256": _sha256_file(path),
        "decoded_pixel_sha256": _sha256_bytes(image.tobytes()),
        "format": path.suffix.lower().lstrip("."),
        "width": width,
        "height": height,
        "decoder": dict(decoder),
        "source_group_id": SOURCE_GROUP_ID,
        "source_group_key": SOURCE_GROUP_KEY,
        "source_permission": SOURCE_PERMISSION,
        "source_split": "train",
        "source_group": {
            "id": SOURCE_GROUP_ID,
            "key": SOURCE_GROUP_KEY,
            "permission": SOURCE_PERMISSION,
            "split": "train",
            "table_setup": "user-supplied-deck-photo-surface",
        },
        "reviewed_decision": {
            "status": "accepted",
            "reviewer": "user-supplied-source-review",
            "description": "Clear top-down high-resolution card photo on a dark surface.",
            "card_side": FACE_UP,
            "complete_four_corner_region": True,
            "occluded": False,
            "clipped": False,
        },
    }


def _filled_quad_mask(shape: tuple[int, int], quad: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.round(quad).astype(np.int32), 255)
    return mask


def _reviewed_frame_source(
    repository: Path,
    image_path: Path,
    cutout: Mapping[str, Any],
    source_group: Mapping[str, Any],
) -> dict[str, Any]:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise SyntheticVisibleRegionMaterializationError(
            f"could not read reviewed training frame: {image_path}"
        )
    height, width = image.shape[:2]
    frame_identity = dict(cutout["frame_identity"])
    if (width, height) != (int(frame_identity["width"]), int(frame_identity["height"])):
        raise SyntheticVisibleRegionMaterializationError(
            f"reviewed frame dimensions differ for {cutout['event_id']}"
        )
    source_file_sha256 = _sha256_file(image_path)
    if cutout.get("materialized_frame_sha256") != source_file_sha256:
        raise SyntheticVisibleRegionMaterializationError(
            f"reviewed frame digest differs for {cutout['event_id']}"
        )
    return {
        "source_asset_id": f"source-0068-{cutout['event_id']}",
        "path": _relative(image_path, repository),
        "source_file_sha256": source_file_sha256,
        "decoded_pixel_sha256": _sha256_bytes(image.tobytes()),
        "source_group": dict(source_group),
        "reviewed_decision": {
            "status": "accepted",
            "reviewer": "0068-reviewed-visible-region",
            "card_side": cutout["side"],
            "complete_four_corner_region": True,
            "occluded": False,
            "clipped": False,
            "reference_revision_id": cutout["reference_revision_id"],
        },
        "frame_identity": frame_identity,
        "event_id": cutout["event_id"],
        "item_id": cutout["item_id"],
        "image": image,
    }


def _m0_cutouts(
    repository: Path, m0_manifest: Mapping[str, Any], materialization_root: Path
) -> list[dict[str, Any]]:
    materialization = _read_json(materialization_root / "materialization.json")
    if materialization is None:
        raise SyntheticVisibleRegionMaterializationError(
            f"0068 materialization manifest is missing: {materialization_root}"
        )
    event_paths = {
        str(item["event_id"]): materialization_root / str(item["path"])
        for item in materialization.get("generated_files", [])
        if isinstance(item, Mapping)
        and item.get("kind") == "extracted_frame"
        and isinstance(item.get("event_id"), str)
    }
    result: list[dict[str, Any]] = []
    for cutout in m0_manifest.get("eligibility", {}).get("card_cutouts", []):
        event_id = str(cutout["event_id"])
        image_path = event_paths.get(event_id)
        if image_path is None:
            raise SyntheticVisibleRegionMaterializationError(
                f"0068 materialized frame is missing for {event_id}"
            )
        source_group = {
            "id": str(cutout["recording_id"]),
            "key": str(cutout["source_group_key"]),
            "permission": str(cutout["source_permission"]),
            "split": str(cutout["source_split"]),
            "table_setup": str(cutout["table_setup"]),
            "source_sha256": str(cutout["source_sha256"]),
        }
        source = _reviewed_frame_source(repository, image_path, cutout, source_group)
        image = source.pop("image")
        width = int(source["frame_identity"]["width"])
        height = int(source["frame_identity"]["height"])
        quad = np.array(
            [
                [float(point["x"]) * width, float(point["y"]) * height]
                for point in cutout["quadrilateral"]
            ],
            dtype=np.float32,
        )
        result.append(
            {
                "source": source,
                "image": image,
                "mask": _filled_quad_mask((height, width), quad),
                "quad": quad,
                "grid": {},
                "index": 1,
            }
        )
    return result


def _calibration_quad(target: Mapping[str, Any]) -> list[dict[str, float]] | None:
    geometry = target.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    region = geometry.get("visible_region")
    if not isinstance(region, Mapping):
        return None
    polygons = region.get("polygons")
    if not isinstance(polygons, list) or len(polygons) != 1:
        return None
    points = polygons[0]
    if not isinstance(points, list) or len(points) != 4:
        return None
    result: list[dict[str, float]] = []
    for point in points:
        if not isinstance(point, Mapping):
            return None
        x = point.get("x")
        y = point.get("y")
        if isinstance(x, bool) or not isinstance(x, int) or not 0 < x < 1000:
            return None
        if isinstance(y, bool) or not isinstance(y, int) or not 0 < y < 1000:
            return None
        result.append({"x": _round(x / 1000), "y": _round(y / 1000)})
    crosses = [
        (result[(index + 1) % 4]["x"] - result[index]["x"])
        * (result[(index + 2) % 4]["y"] - result[(index + 1) % 4]["y"])
        - (result[(index + 1) % 4]["y"] - result[index]["y"])
        * (
            result[(index + 2) % 4]["x"]
            - result[(index + 1) % 4]["x"]
        )
        for index in range(4)
    ]
    if not (all(value > 0 for value in crosses) or all(value < 0 for value in crosses)):
        return None
    return result


def _geometry_calibration_examples(
    source_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Select exact four-corner one- and two-card training frames for placement calibration."""

    examples: list[dict[str, Any]] = []
    for sample in source_manifest.get("samples", []):
        if not isinstance(sample, Mapping) or sample.get("split") != "train":
            continue
        targets = sample.get("targets")
        if not isinstance(targets, list) or len(targets) not in {1, 2}:
            continue
        if sample.get("ignored_regions"):
            continue
        quads: list[list[dict[str, float]]] = []
        kinds: list[str] = []
        sides: list[str] = []
        for target in targets:
            if not isinstance(target, Mapping):
                quads = []
                break
            quad = _calibration_quad(target)
            if quad is None:
                quads = []
                break
            geometry = target.get("geometry", {})
            kinds.append(str(geometry.get("kind", "unknown")))
            sides.append(str(target.get("side", "unknown")))
            quads.append(quad)
        if not quads:
            continue
        frame_identity = sample.get("frame_identity", {})
        if not isinstance(frame_identity, Mapping):
            continue
        examples.append(
            {
                "example_id": f"{sample['event_id']}-table-geometry",
                "recording_id": str(sample["recording_id"]),
                "event_id": str(sample["event_id"]),
                "item_id": str(sample.get("item_id", sample["event_id"])),
                "source_group_key": str(sample.get("source_group_key", "")),
                "source_sha256": str(sample.get("source_sha256", "")),
                "source_split": "train",
                "table_setup": str(sample.get("table_setup", "unknown")),
                "source_dimensions": {
                    "width": int(frame_identity.get("width", 0)),
                    "height": int(frame_identity.get("height", 0)),
                },
                "card_count": len(quads),
                "card_sides": sides,
                "annotation_kinds": kinds,
                "normalized_quadrilaterals": quads,
                "selection": "exact-four-corner-one-two-card-training-frame-v1",
            }
        )
    examples.sort(key=lambda item: (item["recording_id"], item["event_id"]))
    return examples


def _load_table_spec(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"schema_version": "synthetic-visible-region-table-inputs/v1", "inputs": []}
    value = _read_json(path)
    if value is None or value.get("schema_version") != "synthetic-visible-region-table-inputs/v1":
        raise SyntheticVisibleRegionMaterializationError("table input spec schema is unsupported")
    if not isinstance(value.get("inputs"), list):
        raise SyntheticVisibleRegionMaterializationError("table input spec inputs must be a list")
    return value


def _record_reviewed_background(
    repository: Path,
    output_root: Path,
    spec: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    recording_id = str(spec["recording_id"])
    recordings = {
        str(item["recording_id"]): item
        for item in source_manifest.get("recordings", [])
        if isinstance(item, Mapping) and isinstance(item.get("recording_id"), str)
    }
    recording = recordings.get(recording_id)
    if recording is None:
        raise SyntheticVisibleRegionMaterializationError(
            f"table input recording is not in the frozen 0068 manifest: {recording_id}"
        )
    split = str(recording.get("split"))
    if split != "train":
        return None, {
            "input_id": spec["input_id"],
            "url": spec["url"],
            "role": spec["role"],
            "recording_id": recording_id,
            "source_split": split,
            "excluded_reason": "validation_or_sealed_test_source_group_not_allowed",
        }
    requested_time_us = int(spec["requested_time_us"])
    video_path = repository / str(recording["source_video_path"])
    source = RecordingVideoSource(
        recording_id=recording_id,
        relative_path=str(recording["source_video_path"]),
        video_sha256=str(recording["source_sha256"]),
        byte_length=int(recording["source_byte_length"]),
        duration_us=requested_time_us + 1,
    )
    resolved = resolve_exact_event(
        video_path,
        source=source,
        requested_time_us=requested_time_us,
        resolver=FFmpegFrameResolver(),
        validate_source=True,
    )
    background_id = f"background-{recording_id}-{requested_time_us}"
    background_path = output_root / "backgrounds" / f"{background_id}.jpg"
    digest = _write_file(background_path, resolved.image_bytes)
    return {
        "background_id": background_id,
        "input_id": spec["input_id"],
        "url": spec["url"],
        "source_group": {
            "id": recording_id,
            "key": str(spec["source_group_key"]),
            "permission": str(recording["source_permission"]),
            "split": split,
            "table_setup": str(recording["table_setup"]),
            "source_sha256": str(recording["source_sha256"]),
        },
        "reviewed_decision": {
            "status": "accepted",
            "reviewer": "user-supplied-source-review",
            "full_frame_review_coverage": True,
            "contains_visible_card": False,
        },
        "frame_identity": resolved.identity_mapping(),
        "files": {"image": {"path": _relative(background_path, repository), "sha256": digest}},
    }, None


def _materializer_facts() -> dict[str, Any]:
    return {
        "opencv_version": cv2.__version__,
        "numpy_version": np.__version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "sips_version": _sips_version(),
        "mask_recipe": "opencv-dark-surface-canny-rounded-v2",
        "canonical_size": {"width": CANONICAL_WIDTH, "height": CANONICAL_HEIGHT},
        "canonical_corner_radius": CANONICAL_CORNER_RADIUS,
    }


def _source_files(source_root: Path) -> list[Path]:
    if not source_root.is_dir():
        raise SyntheticVisibleRegionMaterializationError(
            f"source directory does not exist: {source_root}"
        )
    files = sorted(
        path
        for path in source_root.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not files:
        raise SyntheticVisibleRegionMaterializationError(
            f"source directory has no supported card photos: {source_root}"
        )
    return files


def build_synthetic_visible_region_inputs(
    repository_root: str | Path,
    *,
    source_directory: str | Path = SOURCE_DIRECTORY_DEFAULT,
    output_directory: str | Path = OUTPUT_DIRECTORY_DEFAULT,
    m0_manifest_path: str | Path = M0_MANIFEST_DEFAULT,
    materialization_directory: str | Path = MATERIALIZATION_DIRECTORY_DEFAULT,
    table_input_spec: str | Path | None = TABLE_INPUT_SPEC_DEFAULT,
) -> dict[str, Any]:
    """Materialize the training-only M1 card, background, and geometry inputs."""

    repository = Path(repository_root).expanduser().resolve()
    source_root = Path(source_directory).expanduser()
    if not source_root.is_absolute():
        source_root = repository / source_root
    output_root = Path(output_directory).expanduser()
    if not output_root.is_absolute():
        output_root = repository / output_root
    m0_path = Path(m0_manifest_path).expanduser()
    if not m0_path.is_absolute():
        m0_path = repository / m0_path
    m0_manifest = _read_json(m0_path)
    materialization_root = Path(materialization_directory).expanduser()
    if not materialization_root.is_absolute():
        materialization_root = repository / materialization_root
    table_spec_path = None if table_input_spec is None else Path(table_input_spec).expanduser()
    if table_spec_path is not None and not table_spec_path.is_absolute():
        table_spec_path = repository / table_spec_path
    source_files = _source_files(source_root)
    sources: list[dict[str, Any]] = []
    cutouts: list[dict[str, Any]] = []
    for path in source_files:
        image, decoder = _decode_source(path)
        source = _source_record(repository, path, image, decoder)
        sources.append(source)
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            mode = "grid"
            locations: Sequence[tuple[int | None, int | None]] = [
                (row, column)
                for row in range(GRID_ROWS)
                for column in range(GRID_COLUMNS)
            ]
        else:
            mode = "single"
            locations = [(None, None)]
        for index, (row, column) in enumerate(locations, start=1):
            source_mask, source_quad, grid = _extract_source_card(
                image, mode=mode, row=row, column=column
            )
            cutouts.append(
                _materialize_cutout(
                    repository,
                    output_root,
                    image,
                    source_mask,
                    source_quad,
                    source,
                    index,
                    grid,
                )
            )
    m0_assets: list[dict[str, Any]] = []
    if m0_manifest is not None and (materialization_root / "materialization.json").is_file():
        m0_assets = _m0_cutouts(repository, m0_manifest, materialization_root)
        for asset in m0_assets:
            source = asset["source"]
            sources.append(source)
            cutouts.append(
                _materialize_cutout(
                    repository,
                    output_root,
                    asset["image"],
                    asset["mask"],
                    asset["quad"],
                    source,
                    asset["index"],
                    asset["grid"],
                )
            )
    cutouts.sort(key=lambda item: str(item["cutout_id"]))
    table_spec = _load_table_spec(table_spec_path)
    source_manifest = _read_json(
        repository / "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"
    ) or {}
    backgrounds: list[dict[str, Any]] = []
    excluded_review_inputs: list[dict[str, Any]] = []
    operator_review_links: list[dict[str, Any]] = []
    cutouts_by_event = {
        item["source_frame"].get("event_id"): item
        for item in cutouts
        if item["source_frame"].get("event_id") is not None
    }
    for table_input in table_spec["inputs"]:
        if not isinstance(table_input, Mapping):
            raise SyntheticVisibleRegionMaterializationError("table input must be an object")
        if table_input.get("role") == "card":
            event_id = str(table_input.get("event_id"))
            source_recording = next(
                (
                    item
                    for item in source_manifest.get("recordings", [])
                    if isinstance(item, Mapping)
                    and item.get("recording_id") == table_input.get("recording_id")
                ),
                None,
            )
            source_split = None if source_recording is None else source_recording.get("split")
            linked_cutout = cutouts_by_event.get(event_id)
            if source_split != "train":
                excluded_review_inputs.append(
                    {
                        "input_id": table_input["input_id"],
                        "url": table_input["url"],
                        "role": table_input["role"],
                        "event_id": event_id,
                        "recording_id": table_input["recording_id"],
                        "source_split": source_split,
                        "excluded_reason": (
                            "validation_or_sealed_test_source_group_not_allowed"
                        ),
                    }
                )
            elif linked_cutout is None:
                excluded_review_inputs.append(
                    {
                        "input_id": table_input["input_id"],
                        "url": table_input["url"],
                        "role": table_input["role"],
                        "event_id": event_id,
                        "excluded_reason": "no_eligible_training_cutout_for_reviewed_card",
                    }
                )
            else:
                operator_review_links.append(
                    {
                        "input_id": table_input["input_id"],
                        "url": table_input["url"],
                        "role": table_input["role"],
                        "event_id": event_id,
                        "cutout_id": linked_cutout["cutout_id"],
                    }
                )
        elif table_input.get("role") == "empty_background":
            background, excluded = _record_reviewed_background(
                repository, output_root, table_input, source_manifest
            )
            if background is not None:
                backgrounds.append(background)
                operator_review_links.append(
                    {
                        "input_id": table_input["input_id"],
                        "url": table_input["url"],
                        "role": table_input["role"],
                        "background_id": background["background_id"],
                    }
                )
            if excluded is not None:
                excluded_review_inputs.append(excluded)
        else:
            raise SyntheticVisibleRegionMaterializationError(
                f"unsupported table input role: {table_input.get('role')}"
            )
    occluders: list[dict[str, Any]] = []
    coverage_gaps = []
    if not backgrounds:
        coverage_gaps.append("no full-frame empty background has explicit operator review coverage")
    side_counts = {
        side: sum(item["reviewed_decision"]["card_side"] == side for item in cutouts)
        for side in (FACE_UP, "face_down", "unknown")
    }
    if not side_counts["face_down"]:
        coverage_gaps.append("no face_down card cutout is present in the supplied photos")
    perspective_examples = [
        {
            "cutout_id": item["cutout_id"],
            "table_setup": item["source_group"].get("table_setup"),
            "source_quadrilateral": item["source_quadrilateral"],
            "source_width": item["source_frame"]["width"],
            "source_height": item["source_frame"]["height"],
        }
        for item in cutouts
    ]
    calibration_examples = _geometry_calibration_examples(source_manifest)
    core: dict[str, Any] = {
        "schema_version": SYNTHETIC_VISIBLE_REGION_INPUTS_SCHEMA_VERSION,
        "campaign_id": SYNTHETIC_VISIBLE_REGION_INPUTS_CAMPAIGN_ID,
        "milestone": "M1",
        "freeze_state": "blocked",
        "source_boundary": {
            "source_group_id": SOURCE_GROUP_ID,
            "source_group_key": SOURCE_GROUP_KEY,
            "permission": SOURCE_PERMISSION,
            "split": "train",
            "additional_source_policy": (
                "0068-frozen-train-plus-explicitly-reviewed-train-only-inputs/v1"
            ),
            "validation_and_sealed_test_contributors": False,
            "base_m0_manifest_digest": m0_manifest.get("manifest_digest") if m0_manifest else None,
        },
        "source_directory": _relative(source_root, repository),
        "sources": sources,
        "cutouts": cutouts,
        "backgrounds": backgrounds,
        "occluders": occluders,
        "operator_review_links": operator_review_links,
        "excluded_review_inputs": excluded_review_inputs,
        "perspective_library": {
            "source": "complete-reviewed-training-quadrilaterals",
            "example_count": len(perspective_examples),
            "examples": perspective_examples,
            "calibration_source": "exact-four-corner-one-two-card-training-frames-v1",
            "calibration_example_count": len(calibration_examples),
            "calibration_examples": calibration_examples,
        },
        "inventory": {
            "source_count": len(sources),
            "cutout_count": len(cutouts),
            "side_counts": side_counts,
            "background_count": len(backgrounds),
            "occluder_count": 0,
            "m0_cutout_count": len(m0_assets),
            "grid_source_count": sum(
                path.suffix.lower() in {".jpg", ".jpeg"} for path in source_files
            ),
            "individual_source_count": sum(
                path.suffix.lower() in {".heic", ".heif", ".png"} for path in source_files
            ),
        },
        "materializer": _materializer_facts(),
        "table_input_spec": (
            _relative(table_spec_path, repository) if table_spec_path is not None else None
        ),
        "coverage_gaps": coverage_gaps,
    }
    manifest = {
        **core,
        "manifest_digest": _sha256_bytes(canonical_json_bytes(core)),
    }
    return manifest


def validate_synthetic_visible_region_inputs(raw: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "campaign_id",
        "milestone",
        "freeze_state",
        "source_boundary",
        "source_directory",
        "sources",
        "cutouts",
        "backgrounds",
        "occluders",
        "operator_review_links",
        "excluded_review_inputs",
        "perspective_library",
        "inventory",
        "materializer",
        "table_input_spec",
        "coverage_gaps",
        "manifest_digest",
    }
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise SyntheticVisibleRegionMaterializationError("M1 input manifest has invalid fields")
    if raw["schema_version"] != SYNTHETIC_VISIBLE_REGION_INPUTS_SCHEMA_VERSION:
        raise SyntheticVisibleRegionMaterializationError("M1 input manifest schema is unsupported")
    if raw["campaign_id"] != SYNTHETIC_VISIBLE_REGION_INPUTS_CAMPAIGN_ID:
        raise SyntheticVisibleRegionMaterializationError("M1 input manifest identity is invalid")
    if raw["milestone"] != "M1" or raw["freeze_state"] not in {"blocked", "ready"}:
        raise SyntheticVisibleRegionMaterializationError("M1 input manifest state is invalid")
    if not isinstance(raw["coverage_gaps"], list) or any(
        not isinstance(item, str) for item in raw["coverage_gaps"]
    ):
        raise SyntheticVisibleRegionMaterializationError("coverage_gaps must be a list of strings")
    inventory = raw["inventory"]
    if inventory.get("source_count") != len(raw["sources"]):
        raise SyntheticVisibleRegionMaterializationError("source inventory is stale")
    if inventory.get("cutout_count") != len(raw["cutouts"]):
        raise SyntheticVisibleRegionMaterializationError("cutout inventory is stale")
    if inventory.get("background_count") != len(raw["backgrounds"]):
        raise SyntheticVisibleRegionMaterializationError("background inventory is stale")
    for cutout in raw["cutouts"]:
        if cutout["source_group"]["split"] != "train":
            raise SyntheticVisibleRegionMaterializationError("cutout is not training-only")
        if cutout["reviewed_decision"]["card_side"] not in {FACE_UP, "face_down", "unknown"}:
            raise SyntheticVisibleRegionMaterializationError("cutout has an invalid card side")
        if cutout["reviewed_decision"]["clipped"] or cutout["reviewed_decision"]["occluded"]:
            raise SyntheticVisibleRegionMaterializationError(
                "clipped or occluded cutout was accepted"
            )
        if float(cutout["roundtrip_max_pixel_error"]) > 0.01:
            raise SyntheticVisibleRegionMaterializationError(
                "cutout roundtrip error exceeds tolerance"
            )
    core = {key: raw[key] for key in expected if key != "manifest_digest"}
    if raw["manifest_digest"] != _sha256_bytes(canonical_json_bytes(core)):
        raise SyntheticVisibleRegionMaterializationError("M1 input manifest digest is stale")


def write_synthetic_visible_region_inputs(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    validate_synthetic_visible_region_inputs(manifest)
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(manifest) + b"\n"
    if destination.exists() and destination.read_bytes() != payload:
        raise SyntheticVisibleRegionMaterializationError(
            f"M1 input manifest already exists and differs: {destination}"
        )
    if not destination.exists():
        destination.write_bytes(payload)
    return destination


def render_synthetic_visible_region_inputs_human(manifest: Mapping[str, Any]) -> str:
    inventory = manifest["inventory"]
    lines = [
        "Synthetic visible-region training data M1",
        f"status: {manifest['freeze_state']}",
        f"source photos: {inventory['source_count']}",
        f"materialized card cutouts: {inventory['cutout_count']}",
        f"face-up cutouts: {inventory['side_counts']['face_up']}",
        f"face-down cutouts: {inventory['side_counts']['face_down']}",
        f"empty backgrounds: {inventory['background_count']}",
        f"manifest digest: {manifest['manifest_digest']}",
    ]
    if manifest["coverage_gaps"]:
        lines.append("coverage gaps:")
        lines.extend(f"- {gap}" for gap in manifest["coverage_gaps"])
    return "\n".join(lines) + "\n"


__all__ = [
    "MANIFEST_DEFAULT",
    "M0_MANIFEST_DEFAULT",
    "OUTPUT_DIRECTORY_DEFAULT",
    "SOURCE_DIRECTORY_DEFAULT",
    "SYNTHETIC_VISIBLE_REGION_INPUTS_CAMPAIGN_ID",
    "SYNTHETIC_VISIBLE_REGION_INPUTS_SCHEMA_VERSION",
    "SyntheticVisibleRegionMaterializationError",
    "build_synthetic_visible_region_inputs",
    "render_synthetic_visible_region_inputs_human",
    "validate_synthetic_visible_region_inputs",
    "write_synthetic_visible_region_inputs",
]
