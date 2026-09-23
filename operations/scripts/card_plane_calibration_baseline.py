#!/usr/bin/env python3
"""Run the frozen, read-only calibration baseline on retained and synthetic results."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "operations" / "src"))

from doko_operations.card_plane_calibration import calibrate_recording  # noqa: E402
from doko_operations.card_plane_geometry import (  # noqa: E402
    GEOMETRY_ALGORITHM_VERSION,
    apply_homography,
    card_residual,
    card_vectors,
    polygon_area,
    project_fixed_card,
    quadrilateral_orientations,
)

MANIFEST_SCHEMA = "card-plane-calibration-evaluation/v1"
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
TABLE_TO_IMAGE = np.asarray(
    [[56.0, 9.0, 150.0], [4.0, 52.0, 90.0], [0.001, -0.0005, 1.0]],
    dtype=np.float64,
)
BASE_POSITIONS = [
    (1.4, 1.0),
    (4.2, 1.2),
    (7.0, 1.0),
    (10.0, 1.2),
    (1.2, 3.8),
    (4.0, 3.6),
    (7.2, 3.8),
    (10.2, 3.7),
    (1.5, 6.2),
    (4.4, 6.0),
    (7.4, 6.2),
    (10.4, 6.0),
]
BASE_ANGLES = [0.0, 18.0, 42.0, 74.0, 8.0, 33.0, 62.0, 88.0, 14.0, 48.0, 79.0, 27.0]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON file {path}: {error}") from error


def _visible_result_to_local_result(
    repository_root: Path, revision_id: str, expected_content_sha256: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    revision_root = repository_root / "data/operations/pipeline/revisions" / revision_id
    manifest = _read_json(revision_root / "manifest.json")
    content_path = revision_root / "content.json"
    content = _read_json(content_path)
    actual_content_digest = _sha256(_canonical_bytes(content))
    if actual_content_digest != expected_content_sha256:
        raise ValueError(
            f"{revision_id}: content digest changed; expected {expected_content_sha256}, "
            f"found {actual_content_digest}"
        )
    if manifest.get("revision_id") != revision_id:
        raise ValueError(f"{revision_id}: revision manifest identity changed")
    if manifest.get("content_sha256") != expected_content_sha256:
        raise ValueError(f"{revision_id}: manifest content digest changed")

    frames: list[dict[str, Any]] = []
    for outcome in content.get("outcomes", []):
        identity = outcome.get("frame_identity")
        if not isinstance(identity, dict):
            continue
        width = int(identity["width"])
        height = int(identity["height"])
        predictions: list[dict[str, Any]] = []
        for candidate in outcome.get("candidates", []):
            polygons = candidate.get("geometry", {}).get("visible_region", {}).get("polygons", [])
            if not polygons:
                continue
            score_values = [
                float(score["score"])
                for score in candidate.get("model_scores", [])
                if isinstance(score, dict) and isinstance(score.get("score"), (int, float))
            ]
            predictions.append(
                {
                    "candidate_id": candidate["card_id"],
                    "confidence": max(score_values, default=1.0),
                    "polygons": [
                        [
                            [
                                float(point["x"]) * width / 1000.0,
                                float(point["y"]) * height / 1000.0,
                            ]
                            for point in polygon
                        ]
                        for polygon in polygons
                    ],
                }
            )
        frames.append(
            {
                "frame_id": outcome["event_id"],
                "frame_index": identity["frame_index"],
                "timestamp_us": identity["requested_time_us"],
                "width": width,
                "height": height,
                "source_transform": identity["transform_version"],
                "predictions": predictions,
            }
        )
    return (
        {
            "recording_id": manifest["recording_id"],
            "source_revision": revision_id,
            "frames": frames,
        },
        {
            "recording_id": manifest["recording_id"],
            "model_id": manifest.get("producer", {}).get("model_id"),
            "frame_count": len(frames),
            "source_frame_digest_count": len(
                {
                    str(outcome["frame_identity"]["image_sha256"])
                    for outcome in content.get("outcomes", [])
                    if isinstance(outcome.get("frame_identity"), dict)
                    and outcome["frame_identity"].get("image_sha256")
                }
            ),
            "raw_prediction_count": sum(len(frame["predictions"]) for frame in frames),
        },
    )


def _clip_polygon(points: np.ndarray, width: int, height: int) -> np.ndarray:
    frame = np.asarray([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    area, intersection = cv2.intersectConvexConvex(cv2.convexHull(points.astype(np.float32)), frame)
    if area <= 0 or intersection is None:
        return np.empty((0, 2), dtype=np.float64)
    return intersection.reshape(-1, 2).astype(np.float64)


def _edge_samples(points: np.ndarray, count_per_edge: int = 24) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    return np.concatenate(
        [
            values[index]
            + (values[(index + 1) % len(values)] - values[index])
            * np.arange(count_per_edge, dtype=np.float64)[:, None]
            / count_per_edge
            for index in range(len(values))
        ],
        axis=0,
    )


def _directed_boundary_distances(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source_points = _edge_samples(source)
    target_points = np.asarray(target, dtype=np.float64).reshape(-1, 2)
    target_next = np.roll(target_points, -1, axis=0)
    segment = target_next - target_points
    segment_length_squared = np.sum(segment * segment, axis=1)
    relative = source_points[:, None, :] - target_points[None, :, :]
    fraction = np.sum(relative * segment[None, :, :], axis=2) / np.maximum(
        segment_length_squared[None, :], 1e-12
    )
    projection = (
        target_points[None, :, :] + np.clip(fraction, 0.0, 1.0)[:, :, None] * segment[None, :, :]
    )
    return np.sqrt(np.min(np.sum((source_points[:, None, :] - projection) ** 2, axis=2), axis=1))


def _boundary_metrics(predicted: np.ndarray, expected: np.ndarray) -> dict[str, float]:
    forward = _directed_boundary_distances(predicted, expected)
    reverse = _directed_boundary_distances(expected, predicted)
    distances = np.concatenate([forward, reverse])
    p = np.asarray(predicted, dtype=np.float64).reshape(4, 2)
    e = np.asarray(expected, dtype=np.float64).reshape(4, 2)
    area_bias = polygon_area(p) / max(polygon_area(e), 1e-9) - 1.0
    short_p, long_p = card_vectors(p)
    short_e, long_e = card_vectors(e)
    extent_bias = (
        (float(np.linalg.norm(short_p)) / max(float(np.linalg.norm(short_e)), 1e-9) - 1.0),
        (float(np.linalg.norm(long_p)) / max(float(np.linalg.norm(long_e)), 1e-9) - 1.0),
    )
    return {
        "median_boundary_px": float(np.median(distances)),
        "p90_boundary_px": float(np.percentile(distances, 90)),
        "max_boundary_px": float(np.max(distances)),
        "p90_boundary_over_card_short_side": float(
            np.percentile(distances, 90) / max(float(np.linalg.norm(short_e)), 1e-9)
        ),
        "median_boundary_over_card_short_side": float(
            np.median(distances) / max(float(np.linalg.norm(short_e)), 1e-9)
        ),
        "short_extent_bias": extent_bias[0],
        "long_extent_bias": extent_bias[1],
        "area_bias": float(area_bias),
    }


def _projected_outlines(run: Any) -> dict[str, np.ndarray]:
    calibration = run.calibration or getattr(run, "calibration_fit_candidate", None)
    if calibration is None:
        return {}
    image_to_table = np.asarray(calibration.image_to_table, dtype=np.float64)
    table_to_image = np.asarray(calibration.table_to_image, dtype=np.float64)
    result: dict[str, np.ndarray] = {}
    for receipt in run.candidate_receipts:
        if not receipt.accepted:
            continue
        quad = np.asarray(receipt.quadrilateral, dtype=np.float64)
        possibilities: list[tuple[float, np.ndarray]] = []
        for orientation in quadrilateral_orientations(quad):
            table_quad = apply_homography(image_to_table, orientation)
            angle_error, aspect_error, parallel_error = card_residual(table_quad)
            score = angle_error / 10.0 + aspect_error + parallel_error
            possibilities.append((score, table_quad))
        _score, table_quad = min(possibilities, key=lambda item: item[0])
        short, _long = card_vectors(table_quad)
        center = np.mean(table_quad, axis=0)
        angle = math.degrees(math.atan2(float(short[1]), float(short[0])))
        result[receipt.candidate_id] = project_fixed_card(table_to_image, center, angle, 1.0, 1.5)
    return result


def _synthetic_result(case_id: str) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    references: dict[str, np.ndarray] = {}
    rng = np.random.default_rng(2075)
    table_to_image = TABLE_TO_IMAGE.copy()
    if case_id == "edge-of-view":
        table_to_image[0, 2] = 0.0
    card_specs: list[tuple[str, tuple[float, float], float]] = []
    if case_id == "repeated-stationary":
        for index in range(12):
            card_specs.append((f"moving-{index:02d}", BASE_POSITIONS[index], BASE_ANGLES[index]))
        for index in range(12):
            card_specs.append((f"stationary-{index:02d}", (5.6, 3.2), 31.0))
    else:
        for index, (center, angle) in enumerate(zip(BASE_POSITIONS, BASE_ANGLES, strict=True)):
            card_specs.append((f"card-{index:02d}", center, angle))

    for index, (card_id, center, angle) in enumerate(card_specs):
        expected = project_fixed_card(table_to_image, center, angle, 1.0, 1.5)
        references[card_id] = expected
        prediction = expected.copy()
        confidence = 0.98
        prediction_polygons: list[np.ndarray] = [prediction]
        if case_id == "shrink-10-percent":
            prediction = np.mean(prediction, axis=0) + 0.90 * (
                prediction - np.mean(prediction, axis=0)
            )
            prediction_polygons = [prediction]
        elif case_id == "boundary-noise-2px":
            prediction = prediction + rng.normal(0.0, 2.0, size=prediction.shape)
            prediction_polygons = [prediction]
        elif case_id == "partial-card" and index == 4:
            prediction = np.asarray(
                [
                    prediction[0],
                    prediction[1],
                    (prediction[1] + prediction[2]) / 2.0,
                    (prediction[0] + prediction[3]) / 2.0,
                ]
            )
            prediction_polygons = [prediction]
        elif case_id == "weak-mask" and index == 5:
            confidence = 0.72
        elif case_id == "clipped-card" and index == 0:
            expected = expected.copy()
            expected[:, 0] -= 210.0
            references[card_id] = expected
            clipped = _clip_polygon(expected, FRAME_WIDTH, FRAME_HEIGHT)
            prediction_polygons = [clipped]

        frames.append(
            {
                "frame_id": f"frame-{index:03d}-{card_id}",
                "frame_index": index * 30,
                "timestamp_us": index * 1_000_000,
                "width": FRAME_WIDTH,
                "height": FRAME_HEIGHT,
                "source_transform": "synthetic-known-camera-v1",
                "predictions": [
                    {
                        "candidate_id": card_id,
                        "confidence": confidence,
                        "polygons": [polygon.tolist() for polygon in prediction_polygons],
                    }
                ],
            }
        )

    if case_id == "overlapping-pile":
        overlap = project_fixed_card(table_to_image, BASE_POSITIONS[4], BASE_ANGLES[4], 1.0, 1.5)
        overlap_id = "pile-card-04b"
        references[overlap_id] = overlap
        frames[4]["predictions"].append(
            {
                "candidate_id": overlap_id,
                "confidence": 0.97,
                "polygons": [overlap.tolist()],
            }
        )
    if case_id == "outlier":
        for index, card_id, center in (
            (4, "outlier-card-04", (5.5, 0.6)),
            (9, "outlier-card-09", (9.3, 6.1)),
        ):
            expected = project_fixed_card(
                table_to_image,
                center,
                BASE_ANGLES[index],
                1.0,
                1.5,
            )
            bad = np.mean(expected, axis=0) + 1.7 * (expected - np.mean(expected, axis=0))
            frames[index]["predictions"].append(
                {"candidate_id": card_id, "confidence": 0.99, "polygons": [bad.tolist()]}
            )
    return (
        {
            "recording_id": f"synthetic-{case_id}",
            "source_revision": f"synthetic-{case_id}-v1",
            "frames": frames,
        },
        references,
        {"frame_count": len(frames), "card_count": len(references)},
    )


def _fit_rejected_candidate_ids(run: Any) -> list[str]:
    rejected_indices = run.diagnostics.get("fit", {}).get("rejected_card_indices", [])
    if not rejected_indices:
        return []
    validation = run.diagnostics.get("validation", {})
    fit_ids = validation.get("fit_candidate_ids", [])
    return [
        fit_ids[index]
        for index in sorted(int(value) for value in rejected_indices)
        if 0 <= int(index) < len(fit_ids)
    ]


def _run_case(
    result: dict[str, Any], references: dict[str, np.ndarray] | None = None
) -> dict[str, Any]:
    started = time.perf_counter()
    run = calibrate_recording(
        result,
        size_reference={key: value.tolist() for key, value in references.items()}
        if references
        else None,
        size_reference_revision="synthetic-known-full-card-outlines/v1" if references else None,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    diagnostics = run.diagnostics
    held_out = diagnostics.get("validation", {})
    held_out_rows = held_out.get("held_out_observations", [])
    held_out_ids = [item["candidate_id"] for item in held_out_rows]
    result_summary: dict[str, Any] = {
        "status": run.status,
        "run_digest": run.run_digest,
        "failure_code": None if run.failure is None else run.failure.code,
        "runtime_ms": round(elapsed_ms, 3),
        "candidate_yield": diagnostics.get("candidate_yield", {}),
        "rejection_counts": dict(
            sorted(Counter(diagnostics.get("rejections", {}).values()).items())
        ),
        "diversity": diagnostics.get("diversity"),
        "fit": diagnostics.get("fit"),
        "fit_rejected_count": len(diagnostics.get("fit", {}).get("rejected_card_indices", [])),
        "fit_rejected_candidate_ids": _fit_rejected_candidate_ids(run),
        "gates": diagnostics.get("gates"),
        "held_out": {
            "count": held_out.get("held_out_count", 0),
            "summary": held_out.get("held_out_summary"),
            "regions": held_out.get("regional_metrics"),
        },
        "inspectable_fit_candidate": run.calibration_fit_candidate is not None,
    }
    if references:
        result_summary["candidate_selection"] = {
            "accepted_candidate_ids": sorted(
                item.candidate_id for item in run.candidate_receipts if item.accepted
            ),
            "rejected_candidates": sorted(
                [
                    {"candidate_id": item.candidate_id, "reason": item.rejection_reason}
                    for item in run.candidate_receipts
                    if not item.accepted
                ],
                key=lambda item: item["candidate_id"],
            ),
            "held_out_candidate_ids": sorted(held_out_ids),
        }
        projected = _projected_outlines(run)
        held_out_references = {
            card_id: expected
            for card_id, expected in references.items()
            if card_id in set(held_out_ids)
        }
        candidate_metrics = {
            card_id: _boundary_metrics(projected[card_id], expected)
            for card_id, expected in held_out_references.items()
            if card_id in projected
        }

        def aggregate(metrics: dict[str, dict[str, float]]) -> dict[str, Any]:
            values = list(metrics.values())
            return {
                "projected_outline_count": len(values),
                "median_boundary_px": None
                if not values
                else float(np.median([item["median_boundary_px"] for item in values])),
                "p90_boundary_px": None
                if not values
                else float(np.percentile([item["p90_boundary_px"] for item in values], 90)),
                "p90_boundary_over_short_side": None
                if not values
                else float(
                    np.percentile(
                        [item["p90_boundary_over_card_short_side"] for item in values], 90
                    )
                ),
                "max_boundary_px": None
                if not values
                else float(max(item["max_boundary_px"] for item in values)),
                "median_short_extent_bias": None
                if not values
                else float(np.median([item["short_extent_bias"] for item in values])),
                "median_long_extent_bias": None
                if not values
                else float(np.median([item["long_extent_bias"] for item in values])),
                "median_area_bias": None
                if not values
                else float(np.median([item["area_bias"] for item in values])),
                "worst_abs_short_extent_bias": None
                if not values
                else float(max(abs(item["short_extent_bias"]) for item in values)),
                "worst_abs_area_bias": None
                if not values
                else float(max(abs(item["area_bias"]) for item in values)),
            }

        reference_regions: dict[str, dict[str, dict[str, float]]] = {
            "center": {},
            "view_edges": {},
        }
        first_frame = (result.get("frames") or [{}])[0]
        width = int(first_frame.get("width", FRAME_WIDTH))
        height = int(first_frame.get("height", FRAME_HEIGHT))
        for card_id, metrics in candidate_metrics.items():
            center = np.mean(held_out_references[card_id], axis=0)
            region = (
                "center"
                if 0.25 * width <= center[0] <= 0.75 * width
                and 0.25 * height <= center[1] <= 0.75 * height
                else "view_edges"
            )
            reference_regions[region][card_id] = metrics
        reference_summary = aggregate(candidate_metrics)
        reference_summary.update(
            {
                "reference_outline_count": len(references),
                "independent_holdout_outline_count": len(held_out_references),
                "unprojected_holdout_outline_ids": sorted(
                    set(held_out_references) - set(candidate_metrics)
                ),
                "regions": {
                    region: aggregate(values) for region, values in reference_regions.items()
                },
            }
        )
        result_summary["full_card_reference"] = reference_summary
    return result_summary


def run_baseline(repository_root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError(
            f"unsupported evaluation manifest schema: {manifest.get('schema_version')}"
        )
    results: list[dict[str, Any]] = []
    for item in manifest.get("local_results", []):
        revision_id = item["revision_id"]
        result, source_summary = _visible_result_to_local_result(
            repository_root, revision_id, item["content_sha256"]
        )
        if source_summary["recording_id"] != item["recording_id"]:
            raise ValueError(f"{revision_id}: recording identity changed")
        if source_summary["model_id"] != item["model_id"]:
            raise ValueError(f"{revision_id}: detector variant changed")
        row = {
            "case_id": revision_id,
            "kind": "local-rfdetr-result",
            "source": {
                "revision_id": revision_id,
                "content_sha256": item["content_sha256"],
                "coverage_kind": item["coverage_kind"],
                **source_summary,
            },
            **_run_case(result),
        }
        results.append(row)

    for case in manifest.get("synthetic_cases", []):
        result, references, source_summary = _synthetic_result(case["case_id"])
        row = {
            "case_id": case["case_id"],
            "kind": "synthetic-known-geometry",
            "source": {"recipe": case["recipe"], **source_summary},
            **_run_case(result, references),
        }
        repeat_run = calibrate_recording(
            result,
            size_reference={key: value.tolist() for key, value in references.items()},
            size_reference_revision="synthetic-known-full-card-outlines/v1",
        )
        row["repeatable_run_digest"] = repeat_run.run_digest
        row["repeatable"] = repeat_run.run_digest == row["run_digest"]
        results.append(row)

    local = [item for item in results if item["kind"] == "local-rfdetr-result"]
    published = sum(item["status"] == "published" for item in local)
    failed = len(local) - published
    return {
        "schema_version": "card-plane-calibration-baseline-report/v1",
        "manifest_path": manifest_path.relative_to(repository_root).as_posix(),
        "manifest_sha256": _sha256(_canonical_bytes(manifest)),
        "algorithm": GEOMETRY_ALGORITHM_VERSION,
        "real_outline_reference": manifest["real_outline_reference"],
        "summary": {
            "local_result_count": len(local),
            "published_count": published,
            "failed_count": failed,
            "failed_runs_with_inspectable_fit_candidate": sum(
                item["inspectable_fit_candidate"] for item in local if item["status"] == "failed"
            ),
            "mean_local_runtime_ms": None
            if not local
            else float(np.mean([item["runtime_ms"] for item in local])),
            "maximum_local_runtime_ms": None
            if not local
            else float(max(item["runtime_ms"] for item in local)),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root", type=Path, default=REPOSITORY_ROOT, help="repository checkout root"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPOSITORY_ROOT / "operations/fixtures/card-plane-calibration-v1/manifest.json",
        help="frozen local and synthetic case manifest",
    )
    parser.add_argument("--output", type=Path, help="optional JSON output path; default is stdout")
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    manifest_path = args.manifest.resolve()
    try:
        report = run_baseline(repository_root, manifest_path)
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(payload)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
