"""Materialize and execute the frozen epic 0051 M3 work matrix.

The M0 manifest is the only annotation authority used here.  The materializer stores one
receipt per crop, and the executor stores one receipt per classifier request.  Both receipts
include the complete frozen request identity before reuse is allowed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from pathlib import Path
from typing import Any

from .derived_view import (
    CropGeometry,
    DetectorBoxGeometry,
    FFmpegFrameResolver,
    PredictedVisibleRegionGeometry,
    ResolvedFrame,
    ReviewedVisibleRegionGeometry,
    VisibleRegionExclusionInput,
    generate_visible_region_corruption,
    parse_geometry,
    resolve_exact_event,
    resolve_visible_region_crop,
)
from .pipeline_data import RecordingVideoSource
from .resilience_baseline import (
    CONDITION_IDS,
    canonical_json_bytes,
    sha256_json,
    validate_resilience_baseline_manifest,
)
from .resilience_comparison import (
    RESILIENCE_COMPARISON_ROW_SCHEMA_VERSION,
    run_resilience_comparison,
    write_resilience_comparison,
)

RESILIENCE_WORK_PLAN_SCHEMA_VERSION = "visible-region-identity-resilience-work-plan/v1"
RESILIENCE_MATERIALIZATION_SCHEMA_VERSION = "visible-region-identity-resilience-materialization/v1"
RESILIENCE_EXECUTION_SCHEMA_VERSION = "visible-region-identity-resilience-execution/v1"
RESILIENCE_RECEIPT_SCHEMA_VERSION = "visible-region-identity-resilience-receipt/v1"

_REVIEWED_CONDITIONS = {"reviewed_other_region_exclusion", "oracle_visible_region"}
_GENERATED_EXCLUSION_CONDITIONS = {
    "generated_other_region_exclusion",
    "predicted_region_with_other_exclusion",
}
_REQUIRED_CROP_FIELDS = {
    "schema_version",
    "work_id",
    "request_digest",
    "matrix_entry",
    "input_family",
    "deployable",
    "crop_status",
    "crop_path",
    "crop_sha256",
    "crop_identity",
    "frame_identity_sha256",
    "reviewed_geometry_sha256",
    "reviewed_target_identity",
    "source_lineage_group",
    "partition",
    "dimensions",
    "diagnostics",
}
FrameResolver = Callable[[Path, RecordingVideoSource, Mapping[str, Any]], ResolvedFrame]


class ResilienceExecutionError(ValueError):
    """The frozen M3 work cannot be materialized or executed safely."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ResilienceExecutionError(f"{field} must be an object")
    return value


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ResilienceExecutionError(f"could not read {field}: {error}") from error
    return dict(_mapping(value, field))


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        fd, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(canonical_json_bytes(value).decode("utf-8"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        Path(temporary_path).replace(path)
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        fd, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(fd, "wb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        Path(temporary_path).replace(path)
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ResilienceExecutionError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _validate_gate(manifest: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(_mapping(manifest, "resilience baseline manifest"))
    try:
        validate_resilience_baseline_manifest(data)
    except (TypeError, ValueError) as error:
        raise ResilienceExecutionError(f"M0 manifest is invalid: {error}") from error
    if data["validation_classification_allowed"] is not True:
        gaps = "; ".join(str(gap) for gap in data.get("coverage_gaps", []))
        raise ResilienceExecutionError(
            "M3 execution is blocked by M0 coverage" + (f": {gaps}" if gaps else "")
        )
    return data


def _as_reviewed(value: Mapping[str, Any] | CropGeometry) -> ReviewedVisibleRegionGeometry:
    geometry = value if not isinstance(value, Mapping) else parse_geometry(value)
    if isinstance(geometry, ReviewedVisibleRegionGeometry):
        return geometry
    if isinstance(geometry, PredictedVisibleRegionGeometry):
        return ReviewedVisibleRegionGeometry(polygons=geometry.polygons)
    raise ResilienceExecutionError("reviewed visible-region input cannot be a detector box")


def _as_predicted(value: Mapping[str, Any] | CropGeometry) -> PredictedVisibleRegionGeometry:
    geometry = value if not isinstance(value, Mapping) else parse_geometry(value)
    if isinstance(geometry, PredictedVisibleRegionGeometry):
        return geometry
    if isinstance(geometry, ReviewedVisibleRegionGeometry):
        return PredictedVisibleRegionGeometry(polygons=geometry.polygons)
    raise ResilienceExecutionError("predicted visible-region input cannot be a detector box")


def _as_detector(value: Mapping[str, Any] | CropGeometry) -> DetectorBoxGeometry:
    geometry = value if not isinstance(value, Mapping) else parse_geometry(value)
    if isinstance(geometry, DetectorBoxGeometry):
        return geometry
    points = [point for polygon in geometry.polygons for point in polygon]
    return DetectorBoxGeometry(
        x_min=min(point[0] for point in points),
        y_min=min(point[1] for point in points),
        x_max=max(point[0] for point in points),
        y_max=max(point[1] for point in points),
    )


def _area(geometry: CropGeometry) -> float:
    if isinstance(geometry, DetectorBoxGeometry):
        box = geometry.to_mapping()["box_2d"]
        return float((box["x_max"] - box["x_min"]) * (box["y_max"] - box["y_min"]))
    return sum(
        abs(
            sum(
                polygon[index][0] * polygon[(index + 1) % len(polygon)][1]
                - polygon[(index + 1) % len(polygon)][0] * polygon[index][1]
                for index in range(len(polygon))
            )
        )
        / 2.0
        for polygon in geometry.polygons
    )


def _bounds(geometry: CropGeometry) -> tuple[int, int, int, int]:
    if isinstance(geometry, DetectorBoxGeometry):
        box = geometry.to_mapping()["box_2d"]
        return box["x_min"], box["y_min"], box["x_max"], box["y_max"]
    points = [point for polygon in geometry.polygons for point in polygon]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _overlap_fraction(
    target: CropGeometry, neighbors: tuple[VisibleRegionExclusionInput, ...]
) -> float:
    target_bounds = _bounds(target)
    target_area = max(
        1.0,
        float((target_bounds[2] - target_bounds[0]) * (target_bounds[3] - target_bounds[1])),
    )
    maximum = 0.0
    for neighbor in neighbors:
        bounds = _bounds(neighbor.geometry)
        intersection = max(
            0, min(target_bounds[2], bounds[2]) - max(target_bounds[0], bounds[0])
        ) * max(0, min(target_bounds[3], bounds[3]) - max(target_bounds[1], bounds[1]))
        maximum = max(maximum, intersection / target_area)
    return min(1.0, maximum)


def _neighbor_inputs(values: Any, *, source: str) -> tuple[VisibleRegionExclusionInput, ...]:
    if not isinstance(values, list):
        raise ResilienceExecutionError("frozen neighboring geometries must be a list")
    result: list[VisibleRegionExclusionInput] = []
    for index, value in enumerate(values):
        item = _mapping(value, f"neighboring geometry {index}")
        proposal_id = item.get("proposal_id")
        geometry = item.get("geometry")
        if not isinstance(proposal_id, str) or not proposal_id:
            raise ResilienceExecutionError(f"neighboring geometry {index} has no proposal_id")
        if not isinstance(geometry, Mapping):
            raise ResilienceExecutionError(f"neighboring geometry {index} has no geometry")
        parsed = _as_predicted(geometry) if source == "generated" else _as_reviewed(geometry)
        result.append(
            VisibleRegionExclusionInput(
                proposal_id=proposal_id,
                geometry=parsed,
                source=source,
            )
        )
    return tuple(result)


def _condition_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    contract = _mapping(manifest["measurement_contract"], "measurement_contract")
    conditions = contract.get("conditions")
    if not isinstance(conditions, list):
        raise ResilienceExecutionError("measurement contract conditions are missing")
    result = {
        str(condition["condition_id"]): condition
        for condition in conditions
        if isinstance(condition, Mapping)
    }
    if set(result) != set(CONDITION_IDS):
        raise ResilienceExecutionError("measurement contract conditions are incomplete")
    return result


def _corruption(
    sample: Mapping[str, Any], value: Mapping[str, Any] | None
) -> tuple[CropGeometry | None, dict[str, Any] | None]:
    if value is None:
        return None, None
    family = value.get("family")
    severity = value.get("severity")
    seed = value.get("seed")
    reviewed = _as_reviewed(sample["reviewed_visible_geometry"])
    neighbors = _neighbor_inputs(sample["reviewed_neighbor_geometries"], source="reviewed")
    donor = neighbors[0].geometry if neighbors else None
    result = generate_visible_region_corruption(
        reviewed,
        str(family),
        severity,
        seed=seed,
        donor_geometry=donor,
    )
    detail = {
        "family": result.family,
        "severity": result.severity,
        "seed": result.seed,
        "source_geometry_sha256": str(sample["reviewed_visible_geometry_digest"]),
        "output_geometry_sha256": sha256_json(result.output_geometry.to_mapping()),
    }
    return result.output_geometry, detail


def _context(
    manifest: Mapping[str, Any], sample: Mapping[str, Any], matrix_entry: Mapping[str, Any]
) -> dict[str, Any]:
    condition_id = str(matrix_entry["condition_id"])
    corruption_value = matrix_entry.get("corruption")
    if corruption_value is not None and not isinstance(corruption_value, Mapping):
        raise ResilienceExecutionError("matrix corruption must be an object or null")
    corruption_geometry, corruption_detail = _corruption(sample, corruption_value)
    synthetic = corruption_value is not None
    upper_bound = not synthetic and condition_id in _REVIEWED_CONDITIONS
    if synthetic:
        input_family = "synthetic_corruption"
        base_geometry: CropGeometry = corruption_geometry  # type: ignore[assignment]
    elif upper_bound:
        input_family = "reviewed_upper_bound"
        base_geometry = _as_reviewed(sample["reviewed_visible_geometry"])
    else:
        input_family = "actual_gemini"
        base_geometry = parse_geometry(sample["generated_visible_geometry"])

    if condition_id in {
        "raw_rectangular",
        *_GENERATED_EXCLUSION_CONDITIONS,
        "reviewed_other_region_exclusion",
    }:
        target = _as_detector(base_geometry)
    elif condition_id == "predicted_visible_region":
        target = _as_predicted(base_geometry)
    elif condition_id == "oracle_visible_region":
        target = _as_reviewed(base_geometry)
    else:
        raise ResilienceExecutionError(f"unsupported frozen condition: {condition_id}")

    if condition_id in _GENERATED_EXCLUSION_CONDITIONS:
        exclusions = _neighbor_inputs(sample["generated_neighbor_geometries"], source="generated")
    elif condition_id == "reviewed_other_region_exclusion":
        exclusions = _neighbor_inputs(sample["reviewed_neighbor_geometries"], source="reviewed")
    else:
        exclusions = ()
    source_neighbors = (
        sample["reviewed_neighbor_geometries"]
        if upper_bound or synthetic
        else sample["generated_neighbor_geometries"]
    )
    visible_card_count = 1 + len(source_neighbors)
    return {
        "input_family": input_family,
        "target_geometry": target.to_mapping(),
        "exclusion_inputs": [item.to_mapping() for item in exclusions],
        "corruption": corruption_detail,
        "dimensions": {
            "visible_card_count": visible_card_count,
            "visible_area_fraction": min(1.0, _area(target) / 1_000_000.0),
            "neighboring_overlap_fraction": _overlap_fraction(target, exclusions),
        },
        "diagnostics": {
            "target_geometry_sha256": sha256_json(target.to_mapping()),
            "exclusion_count": len(exclusions),
            "corruption_transform": (
                "visible-region-corruption/v1" if corruption_detail is not None else None
            ),
        },
    }


def _corruption_key(value: Mapping[str, Any] | None) -> str:
    if value is None:
        return "none"
    return f"{value['family']}-{value['severity']}-{value['seed']}".replace("/", "-")


def _work_items(manifest: Mapping[str, Any], output_root: Path) -> list[dict[str, Any]]:
    samples = {str(sample["sample_id"]): sample for sample in manifest["paired_samples"]}
    conditions = _condition_map(manifest)
    m0_digest = sha256_json(manifest)
    result: list[dict[str, Any]] = []
    for matrix_entry in manifest["experiment_plan"]["matrix"]:
        entry = _mapping(matrix_entry, "experiment_plan.matrix entry")
        sample = samples.get(str(entry["sample_id"]))
        if sample is None:
            raise ResilienceExecutionError(f"matrix sample is missing: {entry['sample_id']}")
        try:
            context = _context(manifest, sample, entry)
            preflight_status = "ready"
            preflight_error = None
        except (TypeError, ValueError, KeyError) as error:
            fallback_corruption = None
            if isinstance(entry.get("corruption"), Mapping):
                corruption_value = entry["corruption"]
                try:
                    _, fallback_corruption = _corruption(sample, corruption_value)
                except (TypeError, ValueError, KeyError):
                    fallback_corruption = {
                        "family": corruption_value.get("family"),
                        "severity": corruption_value.get("severity"),
                        "seed": corruption_value.get("seed"),
                        "source_geometry_sha256": sample["reviewed_visible_geometry_digest"],
                        "output_geometry_sha256": sha256_json(
                            {"work_id": sha256_json(dict(entry)), "geometry": "invalid"}
                        ),
                    }
            context = {
                "input_family": (
                    "synthetic_corruption"
                    if entry.get("corruption") is not None
                    else "actual_gemini"
                ),
                "target_geometry": None,
                "exclusion_inputs": [],
                "corruption": fallback_corruption,
                "dimensions": {
                    "visible_card_count": 0,
                    "visible_area_fraction": 0.0,
                    "neighboring_overlap_fraction": 0.0,
                },
                "diagnostics": {},
            }
            preflight_status = "failed"
            preflight_error = str(error)
        condition = conditions[str(entry["condition_id"])]
        work_id = sha256_json({"m0_manifest_sha256": m0_digest, "matrix_entry": dict(entry)})
        request_digest = sha256_json(
            {
                "work_id": work_id,
                "m0_manifest_sha256": m0_digest,
                "matrix_entry": dict(entry),
                "context": context,
            }
        )
        crop_path = (
            Path("crops")
            / str(entry["sample_id"])
            / str(entry["condition_id"])
            / f"{_corruption_key(entry.get('corruption'))}.ppm"
        )
        result.append(
            {
                "schema_version": RESILIENCE_RECEIPT_SCHEMA_VERSION,
                "work_id": work_id,
                "request_digest": request_digest,
                "matrix_entry": dict(entry),
                "input_family": context["input_family"],
                "deployable": bool(condition.get("deployable")),
                "crop_policy": str(entry["condition_id"]),
                "crop_path": crop_path.as_posix(),
                "target_geometry": context["target_geometry"],
                "exclusion_inputs": context["exclusion_inputs"],
                "corruption": context["corruption"],
                "dimensions": context["dimensions"],
                "preflight_status": preflight_status,
                "preflight_error": preflight_error,
                "context_diagnostics": context["diagnostics"],
                "frame_identity_sha256": str(sample["frame_identity_digest"]),
                "reviewed_geometry_sha256": str(sample["reviewed_visible_geometry_digest"]),
                "reviewed_target_identity": str(sample["reviewed_target_identity"]),
                "source_lineage_group": str(sample["source_lineage_group"]),
                "partition": str(sample["partition"]),
                "recording_id": str(sample["recording_id"]),
                "source_video_path": str(sample["source_video_path"]),
            }
        )
    return result


def build_resilience_work_plan(
    manifest: Mapping[str, Any], *, output_root: str | Path | None = None
) -> dict[str, Any]:
    """Build the complete M3 work matrix without reading or classifying a frame."""

    data = _validate_gate(manifest)
    destination = None if output_root is None else Path(output_root).expanduser().resolve()
    items = _work_items(data, destination or Path("."))
    reusable = 0
    if destination is not None:
        for item in items:
            receipt = destination / "receipts" / f"{item['work_id']}.json"
            crop = destination / item["crop_path"]
            if receipt.is_file() and crop.is_file():
                try:
                    cached = _read_json(receipt, "crop receipt")
                    if (
                        cached.get("request_digest") == item["request_digest"]
                        and cached.get("crop_status") == "usable"
                        and cached.get("crop_sha256") == _sha256_bytes(crop.read_bytes())
                    ):
                        reusable += 1
                except (OSError, ResilienceExecutionError):
                    pass
    plan_core = {
        "schema_version": RESILIENCE_WORK_PLAN_SCHEMA_VERSION,
        "m0_manifest_sha256": sha256_json(data),
        "measurement_contract_sha256": data["measurement_contract_sha256"],
        "matrix_sha256": data["experiment_plan"]["matrix_sha256"],
        "planned_classifier_request_count": len(items),
        "estimated_cost_usd": data["experiment_plan"]["estimated_cost_usd"],
        "cache_reusable_crop_count": reusable,
        "items": items,
    }
    result = json.loads(canonical_json_bytes(plan_core).decode("utf-8"))
    result["plan_sha256"] = sha256_json(result)
    return result


def _source_for_sample(sample: Mapping[str, Any]) -> RecordingVideoSource:
    frame = _mapping(sample["frame_identity"], "sample.frame_identity")
    requested = frame.get("requested_time_us")
    presentation = frame.get("presentation_timestamp_us", requested)
    if not isinstance(requested, int) or not isinstance(presentation, int):
        raise ResilienceExecutionError("frozen frame identity has no valid timestamp")
    return RecordingVideoSource(
        recording_id=str(sample["recording_id"]),
        relative_path=str(sample["source_video_path"]),
        video_sha256=str(sample["source_video_sha256"]),
        byte_length=int(sample["source_video_byte_length"]),
        duration_us=max(1, requested + 1, presentation + 1),
    )


def _default_frame_resolver(
    video_path: Path,
    source: RecordingVideoSource,
    frame_identity: Mapping[str, Any],
    *,
    cache_root: Path,
    validate_source: bool,
) -> ResolvedFrame:
    resolver = FFmpegFrameResolver()
    return resolve_exact_event(
        video_path,
        source=source,
        requested_time_us=int(frame_identity["requested_time_us"]),
        cache=cache_root,
        resolver=resolver,
        validate_source=validate_source,
    )


def _empty_crop_sha(item: Mapping[str, Any], status: str, reason: str | None) -> str:
    return sha256_json({"work_id": item["work_id"], "status": status, "reason": reason})


def _receipt_matches(item: Mapping[str, Any], receipt: Mapping[str, Any], crop_path: Path) -> bool:
    if receipt.get("request_digest") != item["request_digest"]:
        return False
    if receipt.get("crop_status") != "usable" or not crop_path.is_file():
        return False
    try:
        return receipt.get("crop_sha256") == _sha256_bytes(crop_path.read_bytes())
    except OSError:
        return False


def _resolve_crop(frame: ResolvedFrame, item: Mapping[str, Any]) -> Any:
    geometry = parse_geometry(item["target_geometry"])
    return resolve_visible_region_crop(
        frame,
        geometry,
        crop_policy=str(item["crop_policy"]),
        output_encoding="ppm",
        exclusion_inputs=item["exclusion_inputs"],
    )


def materialize_resilience_work(
    manifest: Mapping[str, Any],
    *,
    repository_root: str | Path,
    output_root: str | Path,
    frame_resolver: FrameResolver | None = None,
) -> dict[str, Any]:
    """Extract and retain every frozen M3 crop, reusing verified crop receipts."""

    data = _validate_gate(manifest)
    repository = Path(repository_root).expanduser().resolve()
    destination = Path(output_root).expanduser()
    if not destination.is_absolute():
        destination = repository / destination
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    plan = build_resilience_work_plan(data, output_root=destination)
    resolver = frame_resolver
    frame_cache: dict[str, ResolvedFrame] = {}
    validated_recordings: set[str] = set()
    receipts: list[dict[str, Any]] = []
    reused = 0
    materialized = 0
    unusable = 0
    failed = 0
    samples = {str(sample["sample_id"]): sample for sample in data["paired_samples"]}
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as workers:
        for _sample_id, group in groupby(
            plan["items"], key=lambda item: item["matrix_entry"]["sample_id"]
        ):
            group_items = [dict(item) for item in group]
            ready_items: list[dict[str, Any]] = []
            for item in group_items:
                crop_path = destination / item["crop_path"]
                receipt_path = destination / "receipts" / f"{item['work_id']}.json"
                if receipt_path.is_file() and crop_path.is_file():
                    try:
                        cached = _read_json(receipt_path, "crop receipt")
                    except ResilienceExecutionError:
                        cached = {}
                    if _receipt_matches(item, cached, crop_path):
                        receipts.append(cached)
                        reused += 1
                        continue
                if item["preflight_status"] != "ready":
                    status = "failed"
                    reason = str(item["preflight_error"] or "crop preflight failed")
                    failed += 1
                    receipt = _crop_receipt(
                        item, status, None, _empty_crop_sha(item, status, reason), reason
                    )
                    _write_json_atomic(receipt_path, receipt)
                    receipts.append(receipt)
                    continue
                ready_items.append(item)

            if not ready_items:
                continue
            sample = samples[str(ready_items[0]["matrix_entry"]["sample_id"])]
            try:
                frame_key = str(sample["frame_identity_digest"])
                if frame_key not in frame_cache:
                    source = _source_for_sample(sample)
                    video_path = repository / source.relative_path
                    frame = (
                        resolver(video_path, source, sample["frame_identity"])
                        if resolver is not None
                        else _default_frame_resolver(
                            video_path,
                            source,
                            sample["frame_identity"],
                            cache_root=destination / "frame-cache",
                            validate_source=source.recording_id not in validated_recordings,
                        )
                    )
                    if resolver is None:
                        validated_recordings.add(source.recording_id)
                    if frame.identity_mapping() != dict(sample["frame_identity"]):
                        raise ResilienceExecutionError(
                            f"resolved frame identity differs for {sample['sample_id']}"
                        )
                    frame_cache[frame_key] = frame
                frame = frame_cache[frame_key]
            except (OSError, TypeError, ValueError, KeyError) as error:
                for item in ready_items:
                    status = "failed"
                    reason = str(error)
                    crop_path = destination / item["crop_path"]
                    receipt_path = destination / "receipts" / f"{item['work_id']}.json"
                    failed += 1
                    receipt = _crop_receipt(
                        item, status, None, _empty_crop_sha(item, status, reason), reason
                    )
                    _write_json_atomic(receipt_path, receipt)
                    receipts.append(receipt)
                continue

            futures = [(item, workers.submit(_resolve_crop, frame, item)) for item in ready_items]
            for item, future in futures:
                crop_path = destination / item["crop_path"]
                receipt_path = destination / "receipts" / f"{item['work_id']}.json"
                try:
                    crop = future.result()
                    crop_identity = crop.identity_mapping()
                    if (
                        crop.status == "usable"
                        and crop.image_bytes is not None
                        and crop.image_sha256
                    ):
                        _write_bytes_atomic(crop_path, crop.image_bytes)
                        status = "usable"
                        reason = None
                        crop_sha = crop.image_sha256
                        materialized += 1
                    else:
                        status = "unusable"
                        reason = crop.unusable_reason or "crop is unusable"
                        crop_sha = _empty_crop_sha(item, status, reason)
                        unusable += 1
                except (OSError, TypeError, ValueError, KeyError) as error:
                    status = "failed"
                    reason = str(error)
                    crop_sha = _empty_crop_sha(item, status, reason)
                    failed += 1
                    crop_identity = None
                receipt = _crop_receipt(item, status, crop_identity, crop_sha, reason)
                _write_json_atomic(receipt_path, receipt)
                receipts.append(receipt)
    receipts.sort(key=lambda item: str(item["work_id"]))
    core = {
        "schema_version": RESILIENCE_MATERIALIZATION_SCHEMA_VERSION,
        "m0_manifest_sha256": plan["m0_manifest_sha256"],
        "measurement_contract": data["measurement_contract"],
        "measurement_contract_sha256": plan["measurement_contract_sha256"],
        "matrix_sha256": plan["matrix_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "partitions": data["partitions"],
        "output_root": str(destination),
        "counts": {
            "planned_work_count": len(plan["items"]),
            "materialized_crop_count": materialized,
            "reused_crop_count": reused,
            "unusable_crop_count": unusable,
            "failed_crop_count": failed,
        },
        "items": receipts,
    }
    result = json.loads(canonical_json_bytes(core).decode("utf-8"))
    result["materialization_sha256"] = sha256_json(result)
    _write_json_atomic(destination / "work.json", result)
    return result


def _crop_receipt(
    item: Mapping[str, Any],
    status: str,
    crop_identity: Mapping[str, Any] | None,
    crop_sha256: str,
    reason: str | None,
) -> dict[str, Any]:
    result = dict(item)
    result.update(
        {
            "schema_version": RESILIENCE_RECEIPT_SCHEMA_VERSION,
            "crop_status": status,
            "crop_sha256": crop_sha256,
            "crop_identity": None if crop_identity is None else dict(crop_identity),
            "crop_error": reason,
            "diagnostics": {
                **dict(item.get("context_diagnostics", {})),
                "crop_error": reason,
            },
        }
    )
    result.pop("context_diagnostics", None)
    return result


def _classifier_identity(classifier: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(classifier, "name", "unknown")),
        "version": str(getattr(classifier, "version", "unknown")),
        "calibration": str(getattr(classifier, "calibration", "unknown")),
        "model": getattr(classifier, "model", None),
    }


def _classifier_outcome(result: Any) -> dict[str, Any]:
    status = getattr(result, "status", None)
    classification = getattr(result, "classification", None)
    candidates = tuple(getattr(result, "candidates", ()))
    if status == "unavailable":
        outcome_status = "failed"
    elif classification == "identity" and candidates:
        outcome_status = "classified"
    else:
        outcome_status = "unusable"
    candidate = candidates[0] if candidates else None
    top1 = None if candidate is None else str(candidate.card)
    score = None if candidate is None else float(candidate.probability)
    usage = getattr(result, "usage", None)
    token_count = int(getattr(usage, "total_tokens", 0))
    return {
        "status": outcome_status,
        "top1_identity": top1,
        "candidate_count": len(candidates),
        "score": score,
        "score_calibrated": False,
        "high_confidence": None,
        "retry_count": int(getattr(result, "retry_count", 0)),
        "latency_ms": float(getattr(result, "latency_ms", 0.0)),
        "token_count": token_count,
        "estimated_cost_usd": float(getattr(result, "estimated_cost_usd", 0.0)),
        "error": getattr(result, "error", None)
        or ("classifier abstained" if outcome_status == "unusable" else None),
    }


def _failure_outcome(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "top1_identity": None,
        "candidate_count": 0,
        "score": None,
        "score_calibrated": False,
        "high_confidence": None,
        "retry_count": 0,
        "latency_ms": 0.0,
        "token_count": 0,
        "estimated_cost_usd": 0.0,
        "error": reason,
    }


def execute_resilience_work(
    materialization: Mapping[str, Any] | str | Path,
    *,
    classifier: Any,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run the pinned classifier over retained crops and calculate the M3 comparison."""

    if isinstance(materialization, (str, Path)):
        work_path = Path(materialization).expanduser().resolve()
        data = _read_json(work_path, "M3 materialization")
        destination = work_path.parent if output_root is None else Path(output_root).expanduser()
    else:
        data = dict(_mapping(materialization, "M3 materialization"))
        destination = Path(output_root or data.get("output_root", ".")).expanduser()
    if data.get("schema_version") != RESILIENCE_MATERIALIZATION_SCHEMA_VERSION:
        raise ResilienceExecutionError("M3 materialization has an unsupported schema")
    materialization_digest = data.get("materialization_sha256")
    materialization_core = dict(data)
    materialization_core.pop("materialization_sha256", None)
    if materialization_digest != sha256_json(materialization_core):
        raise ResilienceExecutionError("M3 materialization digest does not match its content")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ResilienceExecutionError("M3 materialization has no work items")
    destination = destination.resolve()
    identity = _classifier_identity(classifier)
    classifier_digest = sha256_json(identity)
    outcomes_root = destination / "outcomes"
    outcomes_root.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    pending_classifier_requests = 0
    for item in items:
        item_data = _mapping(item, "M3 materialization item")
        crop_path = destination / str(item_data["crop_path"])
        outcome_path = outcomes_root / f"{item_data['work_id']}.json"
        if outcome_path.is_file():
            try:
                cached = _read_json(outcome_path, "classifier outcome receipt")
            except ResilienceExecutionError:
                cached = {}
            if (
                cached.get("request_digest") == item_data["request_digest"]
                and cached.get("classifier_digest") == classifier_digest
                and cached.get("crop_sha256") == item_data["crop_sha256"]
            ):
                existing[str(item_data["work_id"])] = cached
                continue
        if item_data["crop_status"] == "usable":
            try:
                if _sha256_bytes(crop_path.read_bytes()) != item_data["crop_sha256"]:
                    raise ResilienceExecutionError(
                        f"crop digest differs for {item_data['work_id']}; rematerialize the work"
                    )
            except OSError as error:
                raise ResilienceExecutionError(
                    f"retained crop is missing for {item_data['work_id']}"
                ) from error
            pending_classifier_requests += 1
    if pending_classifier_requests > len(items):
        raise ResilienceExecutionError("M3 classifier request count is invalid")
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    executed = 0
    reused = len(existing)
    for raw_item in items:
        item = _mapping(raw_item, "M3 materialization item")
        work_id = str(item["work_id"])
        cached = existing.get(work_id)
        if cached is not None:
            outcome = dict(cached["outcome"])
            classifier_cache_hit = bool(cached.get("classifier_cache_hit", False))
        elif item["crop_status"] == "usable":
            crop_path = destination / str(item["crop_path"])
            crop_bytes = crop_path.read_bytes()
            try:
                result = classifier.classify_ppm(crop_bytes)
                outcome = _classifier_outcome(result)
                classifier_cache_hit = bool(getattr(result, "cache_hit", False))
            except Exception as error:  # provider adapters must not abort retained denominators
                outcome = _failure_outcome("failed", f"classifier failure: {error}")
                classifier_cache_hit = False
            executed += 1
            receipt = {
                "schema_version": RESILIENCE_RECEIPT_SCHEMA_VERSION,
                "work_id": work_id,
                "request_digest": item["request_digest"],
                "classifier_digest": classifier_digest,
                "crop_sha256": item["crop_sha256"],
                "classifier_cache_hit": classifier_cache_hit,
                "outcome": outcome,
            }
            _write_json_atomic(outcomes_root / f"{work_id}.json", receipt)
        else:
            outcome = _failure_outcome(
                "unusable" if item["crop_status"] == "unusable" else "failed",
                str(item.get("crop_error") or item.get("preflight_error") or "crop unavailable"),
            )
            classifier_cache_hit = False
        rows.append(
            {
                "schema_version": RESILIENCE_COMPARISON_ROW_SCHEMA_VERSION,
                "sample_id": item["matrix_entry"]["sample_id"],
                "partition": item["partition"],
                "source_lineage_group": item["source_lineage_group"],
                "condition_id": item["matrix_entry"]["condition_id"],
                "input_family": item["input_family"],
                "deployable": item["deployable"],
                "corruption": item["corruption"],
                "reviewed_target_identity": item["reviewed_target_identity"],
                "outcome": outcome,
                "lineage": {
                    "frame_identity_sha256": item["frame_identity_sha256"],
                    "reviewed_geometry_sha256": item["reviewed_geometry_sha256"],
                    "crop_sha256": item["crop_sha256"],
                    "crop_path": item["crop_path"],
                },
                "dimensions": item["dimensions"],
                "diagnostics": {
                    **dict(item.get("diagnostics", {})),
                    "classifier": identity,
                    "classifier_cache_hit": classifier_cache_hit,
                    "materialization_status": item["crop_status"],
                    "work_id": work_id,
                },
            }
        )
    elapsed = time.monotonic() - started
    comparison_manifest = {
        "validation_classification_allowed": True,
        "measurement_contract": data["measurement_contract"],
        "measurement_contract_sha256": data["measurement_contract_sha256"],
        "partitions": data["partitions"],
    }
    comparison_directory = destination / "comparison"
    comparison_path = comparison_directory / "comparison.json"
    calculated_comparison = run_resilience_comparison(
        comparison_manifest,
        rows,
        elapsed_wall_clock_seconds=elapsed,
    )
    if comparison_path.is_file():
        comparison = _read_json(comparison_path, "retained M3 comparison")
        if comparison.get("rows") != calculated_comparison["rows"]:
            raise ResilienceExecutionError(
                "comparison output already contains a different execution; choose a new output"
            )
    else:
        comparison = calculated_comparison
        comparison_path = write_resilience_comparison(comparison_directory, comparison)
    execution = {
        "schema_version": RESILIENCE_EXECUTION_SCHEMA_VERSION,
        "execution_state": "complete",
        "m0_manifest_sha256": data["m0_manifest_sha256"],
        "measurement_contract_sha256": data["measurement_contract_sha256"],
        "materialization_sha256": data["materialization_sha256"],
        "classifier": identity,
        "classifier_digest": classifier_digest,
        "summary": {
            "retained_row_count": len(rows),
            "classifier_request_count": executed,
            "classifier_cache_reused_count": reused,
            "elapsed_wall_clock_seconds": elapsed,
            "estimated_cost_usd": sum(row["outcome"]["estimated_cost_usd"] for row in rows),
        },
        "comparison_path": str(comparison_path),
        "comparison_sha256": comparison["comparison_sha256"],
        "rows": rows,
    }
    _write_json_atomic(destination / "execution.json", execution)
    return execution


__all__ = [
    "RESILIENCE_EXECUTION_SCHEMA_VERSION",
    "RESILIENCE_MATERIALIZATION_SCHEMA_VERSION",
    "RESILIENCE_RECEIPT_SCHEMA_VERSION",
    "RESILIENCE_WORK_PLAN_SCHEMA_VERSION",
    "ResilienceExecutionError",
    "build_resilience_work_plan",
    "execute_resilience_work",
    "materialize_resilience_work",
]
