"""Evaluate the epic 0071 M5 cluster-crop segmentation bundle.

The report keeps crop-coordinate metrics beside the same predictions mapped through the M4
source transform.  It also records exact crop card counts and separation of overlapping reviewed
targets.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .rfdetr_cluster_crop_training import (
    RFDETR_CLUSTER_CROP_CAMPAIGN_ID,
    RfdetrClusterCropTrainingError,
    load_rfdetr_cluster_crop_view,
)
from .rfdetr_segmentation_evaluation import (
    _box_iou,
    _mask_iou,
    _prediction_rows,
    calculate_metrics,
)
from .rfdetr_segmentation_training import (
    RFDETR_SEGMENTATION_INPUT_SIZE,
    _file_digest,
    load_rfdetr_segmentation_bundle,
)

RFDETR_CLUSTER_CROP_EVALUATION_SCHEMA = "rfdetr-cluster-crop-validation/v1"
_PREDICTION_PROVIDER = Callable[[Path, int, int], list[dict[str, Any]]]


class RfdetrClusterCropEvaluationError(ValueError):
    """The M5 validation report cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class RfdetrClusterCropEvaluationConfig:
    """Inputs for one crop and source-coordinate M5 validation."""

    dataset_dir: Path
    candidate_bundle: Path
    output_dir: Path
    runner: Literal["fixture", "rfdetr"] = "rfdetr"
    device: Literal["cpu", "mps", "cuda"] = "mps"

    def __post_init__(self) -> None:
        if self.runner not in {"fixture", "rfdetr"}:
            raise RfdetrClusterCropEvaluationError("runner must be fixture or rfdetr")
        if self.device not in {"cpu", "mps", "cuda"}:
            raise RfdetrClusterCropEvaluationError("device must be cpu, mps, or cuda")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical(value) + b"\n")
    temporary.replace(path)


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RfdetrClusterCropEvaluationError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise RfdetrClusterCropEvaluationError(f"{context} must be a JSON object")
    return value


def _targets(coco: Mapping[str, Any], image: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for annotation in coco["annotations"]:
        if annotation.get("category_id") != 1:
            raise RfdetrClusterCropEvaluationError("M4 validation annotation has another category")
        segmentation = annotation.get("segmentation")
        if not isinstance(segmentation, list) or not segmentation:
            raise RfdetrClusterCropEvaluationError("M4 validation annotation has no mask polygon")
        polygons = [
            [[float(points[index]), float(points[index + 1])] for index in range(0, len(points), 2)]
            for points in segmentation
        ]
        target = {
            "annotation_id": int(annotation["id"]),
            "card_id": str(annotation["card_id"]),
            "card_side": annotation.get("card_side", "unknown"),
            "polygons": polygons,
            "box_xywh": [float(value) for value in annotation["bbox"]],
            "width": int(image["width"]),
            "height": int(image["height"]),
            "polygon_component_count": len(polygons),
            "crop_id": image["crop_id"],
        }
        result.setdefault(int(annotation["image_id"]), []).append(target)
    return result


def _fixture_prediction_rows(coco: Mapping[str, Any], image_id: int) -> list[dict[str, Any]]:
    return [
        {
            "score": 0.9,
            "polygon_pixels": [
                [float(points[index]), float(points[index + 1])]
                for index in range(0, len(annotation["segmentation"][0]), 2)
            ],
            "box_xywh": [float(value) for value in annotation["bbox"]],
            "mask_component_count": len(annotation["segmentation"]),
        }
        for annotation in coco["annotations"]
        if int(annotation["image_id"]) == image_id
        for points in [annotation["segmentation"][0]]
    ]


def _map_xywh(box: Sequence[float], origin_x: float, origin_y: float) -> list[float]:
    return [float(box[0]) + origin_x, float(box[1]) + origin_y, float(box[2]), float(box[3])]


def _map_polygons(
    polygons: Sequence[Sequence[Sequence[float]]], origin_x: float, origin_y: float
) -> list[list[list[float]]]:
    return [
        [[float(point[0]) + origin_x, float(point[1]) + origin_y] for point in polygon]
        for polygon in polygons
    ]


def _exact_card_count(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exact = sum(len(frame["predictions"]) == len(frame["targets"]) for frame in frames)
    return {
        "frame_count": len(frames),
        "exact_count_frames": exact,
        "exact_count_rate": round(exact / len(frames), 6) if frames else 0.0,
    }


def _overlap_separation(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pairs = 0
    separated = 0
    failures: list[dict[str, Any]] = []
    for frame in frames:
        targets = frame["targets"]
        predictions = frame["predictions"]
        for left_index, left in enumerate(targets):
            for _right_index, right in enumerate(targets[left_index + 1 :], start=left_index + 1):
                if _box_iou(left["box_xywh"], right["box_xywh"]) <= 0:
                    continue
                pairs += 1
                left_matches = [
                    index
                    for index, prediction in enumerate(predictions)
                    if _mask_iou(prediction, left) >= 0.5
                ]
                right_matches = [
                    index
                    for index, prediction in enumerate(predictions)
                    if _mask_iou(prediction, right) >= 0.5
                ]
                is_separated = any(
                    left_prediction != right_prediction
                    for left_prediction in left_matches
                    for right_prediction in right_matches
                )
                separated += int(is_separated)
                if not is_separated:
                    failures.append(
                        {
                            "image_id": frame["image_id"],
                            "crop_id": frame["crop_id"],
                            "card_ids": [left["card_id"], right["card_id"]],
                        }
                    )
    return {
        "overlapping_target_pairs": pairs,
        "separated_overlapping_target_pairs": separated,
        "separation_rate": round(separated / pairs, 6) if pairs else None,
        "failures": failures,
    }


def _source_resolution(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [frame["source_pixels_per_model_pixel"] for frame in frames]
    if not values:
        return {"x": [], "y": [], "mean": None, "maximum": None}
    mean = {
        axis: round(sum(float(value[axis]) for value in values) / len(values), 6)
        for axis in ("x", "y")
    }
    maximum = {axis: round(max(float(value[axis]) for value in values), 6) for axis in ("x", "y")}
    return {
        "x": sorted({round(float(value["x"]), 6) for value in values}),
        "y": sorted({round(float(value["y"]), 6) for value in values}),
        "mean": mean,
        "maximum": maximum,
    }


def calculate_cluster_crop_metrics(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate the locked M5 mask, count, and overlap-separation metrics."""

    if not frames:
        raise RfdetrClusterCropEvaluationError("M5 validation has no crop frames")
    metrics = calculate_metrics(frames)
    metrics["exact_card_count"] = _exact_card_count(frames)
    metrics["overlapping_target_separation"] = _overlap_separation(frames)
    metrics["source_pixels_per_model_input_pixel"] = _source_resolution(frames)
    metrics["target_polygon_component_count"] = sum(
        int(target.get("polygon_component_count", len(target["polygons"])))
        for frame in frames
        for target in frame["targets"]
    )
    return metrics


def _prediction_frames(
    view: Any,
    predictor: _PREDICTION_PROVIDER,
    *,
    coordinate_space: Literal["crop", "source"],
) -> list[dict[str, Any]]:
    coco = view.coco["valid"]
    frames: list[dict[str, Any]] = []
    for image in sorted(coco["images"], key=lambda item: int(item["id"])):
        image_id = int(image["id"])
        image_path = view.root / "valid" / str(image["file_name"])
        prediction_rows = predictor(image_path, int(image["width"]), int(image["height"]))
        targets = _targets(coco, image).get(image_id, [])
        transform = image["transform"]
        origin = transform["crop_origin"]
        origin_x, origin_y = float(origin["x"]), float(origin["y"])
        source_size = transform["source_size"]
        predictions: list[dict[str, Any]] = []
        for prediction in prediction_rows:
            polygons = [prediction["polygon_pixels"]]
            box = prediction["box_xywh"]
            if coordinate_space == "source":
                polygons = _map_polygons(polygons, origin_x, origin_y)
                box = _map_xywh(box, origin_x, origin_y)
            predictions.append(
                {
                    **prediction,
                    "polygons": polygons,
                    "box_xywh": box,
                    "width": (
                        int(source_size["width"])
                        if coordinate_space == "source"
                        else int(image["width"])
                    ),
                    "height": (
                        int(source_size["height"])
                        if coordinate_space == "source"
                        else int(image["height"])
                    ),
                }
            )
        frame_targets: list[dict[str, Any]] = []
        for target in targets:
            target_copy = dict(target)
            if coordinate_space == "source":
                target_copy["polygons"] = _map_polygons(target_copy["polygons"], origin_x, origin_y)
                target_copy["box_xywh"] = _map_xywh(target_copy["box_xywh"], origin_x, origin_y)
                target_copy["width"] = int(source_size["width"])
                target_copy["height"] = int(source_size["height"])
            frame_targets.append(target_copy)
        crop_width = float(transform["crop_size"]["width"])
        crop_height = float(transform["crop_size"]["height"])
        frames.append(
            {
                "image_id": image_id,
                "crop_id": image["crop_id"],
                "recording_id": image["recording_id"],
                "event_id": image["event_id"],
                "image_sha256": image["sha256"],
                "source_frame_sha256": image["source_frame_sha256"],
                "source_transform": transform,
                "target_identities": [
                    {
                        "annotation_id": target["annotation_id"],
                        "card_id": target["card_id"],
                        "polygon_component_count": target["polygon_component_count"],
                    }
                    for target in frame_targets
                ],
                "width": int(source_size["width"])
                if coordinate_space == "source"
                else int(image["width"]),
                "height": int(source_size["height"])
                if coordinate_space == "source"
                else int(image["height"]),
                "targets": frame_targets,
                "predictions": predictions,
                "source_pixels_per_model_pixel": {
                    "x": round(crop_width / RFDETR_SEGMENTATION_INPUT_SIZE, 6),
                    "y": round(crop_height / RFDETR_SEGMENTATION_INPUT_SIZE, 6),
                },
            }
        )
    return frames


def _real_predictor(bundle: Any, device: str) -> _PREDICTION_PROVIDER:
    try:
        from .rfdetr_segmentation_evaluation import _load_model

        model = _load_model(bundle.checkpoint_path, device, pretrained=False)
    except Exception as error:
        raise RfdetrClusterCropEvaluationError(f"could not load M5 model: {error}") from error

    def predict(path: Path, width: int, height: int) -> list[dict[str, Any]]:
        try:
            return _prediction_rows(model, path, width, height)
        except Exception as error:
            raise RfdetrClusterCropEvaluationError(
                f"M5 inference failed for {path.name}: {error}"
            ) from error

    return predict


def _fixture_predictor(view: Any) -> _PREDICTION_PROVIDER:
    def predict(path: Path, _width: int, _height: int) -> list[dict[str, Any]]:
        partition_coco = view.coco["valid"]
        image_name = path.name
        for image in partition_coco["images"]:
            if Path(str(image["file_name"])).name == image_name:
                return _fixture_prediction_rows(partition_coco, int(image["id"]))
        raise RfdetrClusterCropEvaluationError(f"fixture has no COCO image for {path.name}")

    return predict


def run_rfdetr_cluster_crop_validation(
    config: RfdetrClusterCropEvaluationConfig,
) -> dict[str, Any]:
    """Evaluate one M5 bundle in crop and exact source coordinates."""

    output = config.output_dir.expanduser().resolve()
    report_path = output / "report.json"
    expected_config = {
        "dataset_dir": str(config.dataset_dir.expanduser().resolve()),
        "candidate_bundle": str(config.candidate_bundle.expanduser().resolve()),
        "output_dir": str(output),
        "runner": config.runner,
        "device": config.device,
    }
    if report_path.is_file():
        report = _read_json(report_path, "M5 validation report")
        if report.get("config") != expected_config:
            raise RfdetrClusterCropEvaluationError("M5 validation output belongs to another run")
        return report
    if output.exists() and any(output.iterdir()):
        raise RfdetrClusterCropEvaluationError("M5 validation output directory is not empty")
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        view = load_rfdetr_cluster_crop_view(config.dataset_dir)
        bundle = load_rfdetr_segmentation_bundle(config.candidate_bundle)
        if bundle.manifest.get("campaign_id") != RFDETR_CLUSTER_CROP_CAMPAIGN_ID:
            raise RfdetrClusterCropEvaluationError("candidate bundle is not the M5 crop bundle")
        if bundle.manifest.get("materialization_digest") != view.materialization_digest:
            raise RfdetrClusterCropEvaluationError(
                "candidate bundle uses another M4 materialization"
            )
        predictor = (
            _fixture_predictor(view)
            if config.runner == "fixture"
            else _real_predictor(bundle, config.device)
        )
        crop_frames = _prediction_frames(view, predictor, coordinate_space="crop")
        source_frames = _prediction_frames(view, predictor, coordinate_space="source")
        crop_metrics = calculate_cluster_crop_metrics(crop_frames)
        source_metrics = calculate_cluster_crop_metrics(source_frames)
        prediction_artifact = {
            "schema_version": "rfdetr-cluster-crop-validation-predictions/v1",
            "bundle_digest": bundle.manifest["bundle_digest"],
            "partition": "validation",
            "frames": {"crop": crop_frames, "source": source_frames},
        }
        prediction_path = output / "validation-predictions.json"
        _write_json(prediction_path, prediction_artifact)
        report = {
            "schema_version": RFDETR_CLUSTER_CROP_EVALUATION_SCHEMA,
            "status": "completed",
            "config": expected_config,
            "campaign_id": RFDETR_CLUSTER_CROP_CAMPAIGN_ID,
            "materialization_digest": view.materialization_digest,
            "candidate_bundle": {
                "bundle_digest": bundle.manifest["bundle_digest"],
                "checkpoint_sha256": bundle.manifest["checkpoint_sha256"],
                "initializer_bundle": bundle.manifest.get("initializer_bundle"),
            },
            "metrics": {"crop_coordinates": crop_metrics, "source_coordinates": source_metrics},
            "effective_resolution": source_metrics["source_pixels_per_model_input_pixel"],
            "artifacts": {
                "validation_predictions": {
                    "path": prediction_path.name,
                    "sha256": _file_digest(prediction_path),
                }
            },
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        _write_json(report_path, report)
        return report
    except (RfdetrClusterCropTrainingError, RfdetrClusterCropEvaluationError):
        raise
    except Exception as error:
        raise RfdetrClusterCropEvaluationError(f"M5 validation failed: {error}") from error


__all__ = [
    "RFDETR_CLUSTER_CROP_EVALUATION_SCHEMA",
    "RfdetrClusterCropEvaluationConfig",
    "RfdetrClusterCropEvaluationError",
    "calculate_cluster_crop_metrics",
    "run_rfdetr_cluster_crop_validation",
]
