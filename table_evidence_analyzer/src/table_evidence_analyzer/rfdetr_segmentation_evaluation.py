"""Locked M3 validation for the epic 0067 RF-DETR segmentation candidate."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageChops, ImageDraw

from .rfdetr_segmentation_training import (
    RFDETR_SEGMENTATION_INPUT_SIZE,
    RFDETR_SEGMENTATION_PACKAGE_VERSION,
    _file_digest,
    _import_segmentation_model,
    _load_materialization_view,
    _verify_campaign_manifest,
    load_rfdetr_segmentation_bundle,
)
from .visible_cards import (
    _detections_field,
    _normalise_detection_rows,
    _normalise_mask_rows,
    _normalised_polygon_from_mask,
    _sequence,
)

RFDETR_SEGMENTATION_VALIDATION_SCHEMA = "rfdetr-segmentation-campaign-validation/v1"
_THRESHOLDS = tuple(round(0.5 + index * 0.05, 2) for index in range(10))
_CARD_SIDES = ("face_down", "face_up", "unknown")
_PARTITIONS = ("valid", "sealed_test")
_PARTITION_LABELS = {"valid": "validation", "sealed_test": "sealed_test"}


class RfdetrSegmentationEvaluationError(ValueError):
    """The locked campaign validation cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class RfdetrSegmentationEvaluationConfig:
    """Immutable inputs for one baseline and one candidate validation."""

    dataset_dir: Path
    campaign_manifest: Path
    pretrained_checkpoint: Path
    candidate_bundle: Path
    output_dir: Path
    device: Literal["cpu", "mps", "cuda"] = "mps"


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RfdetrSegmentationEvaluationError("validation values must be finite JSON") from error


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
        raise RfdetrSegmentationEvaluationError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise RfdetrSegmentationEvaluationError(f"{context} must be a JSON object")
    return value


def _assert_device(device: str) -> None:
    try:
        import torch
    except ImportError as error:  # pragma: no cover - installation failure
        raise RfdetrSegmentationEvaluationError("RF-DETR validation requires PyTorch") from error
    available = {
        "cpu": True,
        "mps": bool(torch.backends.mps.is_available()),
        "cuda": bool(torch.cuda.is_available()),
    }
    if device not in available or not available[device]:
        raise RfdetrSegmentationEvaluationError(
            f"requested validation device is unavailable: {device}"
        )


def _load_model(checkpoint: Path, device: str, *, pretrained: bool = False) -> Any:
    _assert_device(device)
    model_class = _import_segmentation_model()
    try:
        if pretrained:
            return model_class(
                num_classes=1,
                pretrain_weights=str(checkpoint),
                resolution=RFDETR_SEGMENTATION_INPUT_SIZE,
                device=device,
                amp=False,
            )
        return model_class.from_checkpoint(
            str(checkpoint),
            num_classes=1,
            resolution=RFDETR_SEGMENTATION_INPUT_SIZE,
            device=device,
        )
    except Exception as error:
        raise RfdetrSegmentationEvaluationError(
            f"could not load RF-DETR segmentation checkpoint {checkpoint.name}: {error}"
        ) from error


def _polygon_pixels(
    points: Sequence[Mapping[str, int]], width: int, height: int
) -> list[list[float]]:
    return [
        [
            round(float(point["x"]) * width / 1000.0, 6),
            round(float(point["y"]) * height / 1000.0, 6),
        ]
        for point in points
    ]


def _prediction_rows(model: Any, image_path: Path, width: int, height: int) -> list[dict[str, Any]]:
    try:
        with Image.open(image_path) as source:
            image = source.convert("RGB").copy()
        detections = model.predict(
            image,
            threshold=0.5,
            shape=(RFDETR_SEGMENTATION_INPUT_SIZE, RFDETR_SEGMENTATION_INPUT_SIZE),
            include_source_image=False,
        )
        boxes = _normalise_detection_rows(_detections_field(detections, "xyxy"), "xyxy")
        scores = _sequence(_detections_field(detections, "confidence"), "confidence")
        class_ids = _sequence(_detections_field(detections, "class_id"), "class_id")
        raw_masks = _detections_field(detections, "mask")
        if raw_masks is None:
            raw_masks = _detections_field(detections, "masks")
        if raw_masks is None:
            raise RfdetrSegmentationEvaluationError("RF-DETR segmentation output has no masks")
        masks = _normalise_mask_rows(raw_masks)
    except RfdetrSegmentationEvaluationError:
        raise
    except Exception as error:
        raise RfdetrSegmentationEvaluationError(
            f"RF-DETR inference failed for {image_path.name}: {error}"
        ) from error
    if not (len(boxes) == len(scores) == len(class_ids) == len(masks)):
        raise RfdetrSegmentationEvaluationError("RF-DETR detection fields have different lengths")
    result: list[dict[str, Any]] = []
    for index, (score_value, class_id, mask) in enumerate(
        zip(scores, class_ids, masks, strict=True)
    ):
        score = float(score_value)
        if not math.isfinite(score) or not 0.5 < score <= 1.0:
            raise RfdetrSegmentationEvaluationError(
                "RF-DETR score is not in the locked threshold range"
            )
        if int(class_id) not in {0, 1}:
            raise RfdetrSegmentationEvaluationError("RF-DETR returned an unsupported category")
        polygon, diagnostics = _normalised_polygon_from_mask(mask, width=width, height=height)
        if polygon is None:
            continue
        normalized = [point.to_mapping() for point in polygon]
        pixels = _polygon_pixels(normalized, width, height)
        x_values = [point[0] for point in pixels]
        y_values = [point[1] for point in pixels]
        result.append(
            {
                "score": round(score, 8),
                "class_id": int(class_id),
                "polygon_normalized": normalized,
                "polygon_pixels": pixels,
                "box_xywh": [
                    round(min(x_values), 6),
                    round(min(y_values), 6),
                    round(max(x_values) - min(x_values), 6),
                    round(max(y_values) - min(y_values), 6),
                ],
                "detector_box_xyxy": [round(float(value), 6) for value in boxes[index]],
                **diagnostics,
            }
        )
    return sorted(result, key=lambda item: (-float(item["score"]), item["polygon_pixels"]))


def _mask(polygons: Sequence[Sequence[Sequence[float]]], width: int, height: int) -> Image.Image:
    result = Image.new("1", (width, height), 0)
    drawer = ImageDraw.Draw(result)
    for polygon in polygons:
        drawer.polygon([(float(point[0]), float(point[1])) for point in polygon], fill=1)
    return result


def _mask_iou(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    width, height = int(left["width"]), int(left["height"])
    left_mask = _mask(left["polygons"], width, height)
    right_mask = _mask(right["polygons"], width, height)
    intersection = ImageChops.logical_and(left_mask, right_mask).histogram()[-1]
    union = ImageChops.logical_or(left_mask, right_mask).histogram()[-1]
    return 0.0 if union == 0 else intersection / union


def _box_iou(left: Sequence[float], right: Sequence[float]) -> float:
    lx, ly, lw, lh = (float(value) for value in left)
    rx, ry, rw, rh = (float(value) for value in right)
    ix = max(lx, rx)
    iy = max(ly, ry)
    ax = min(lx + lw, rx + rw)
    ay = min(ly + lh, ry + rh)
    intersection = max(0.0, ax - ix) * max(0.0, ay - iy)
    union = lw * lh + rw * rh - intersection
    return 0.0 if union <= 0 else intersection / union


def _match(
    frames: Sequence[Mapping[str, Any]],
    threshold: float,
    geometry: Literal["mask", "box"],
    values: Mapping[tuple[str, int, int, str], float],
) -> tuple[list[tuple[float, bool]], int, int, int]:
    scored: list[tuple[float, str, int, Mapping[str, Any]]] = []
    total_targets = 0
    for frame in frames:
        total_targets += len(frame["targets"])
        for index, prediction in enumerate(frame["predictions"]):
            scored.append((float(prediction["score"]), str(frame["image_id"]), index, prediction))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    matched: dict[str, set[int]] = defaultdict(set)
    rows: list[tuple[float, bool]] = []
    false = duplicates = 0
    by_id = {str(frame["image_id"]): frame for frame in frames}
    for score, image_id, _index, _prediction in scored:
        frame = by_id[image_id]
        candidates: list[tuple[float, int]] = []
        for target_index, _target in enumerate(frame["targets"]):
            candidates.append((values[(image_id, _index, target_index, geometry)], target_index))
        available = [item for item in candidates if item[1] not in matched[image_id]]
        best = max(available, default=(0.0, -1))
        if best[0] >= threshold:
            matched[image_id].add(best[1])
            rows.append((score, True))
        else:
            rows.append((score, False))
            false += 1
            if max((value for value, _ in candidates), default=0.0) >= threshold:
                duplicates += 1
    return rows, total_targets, false, duplicates


def _average_precision(rows: Sequence[tuple[float, bool]], target_count: int) -> float:
    if target_count == 0:
        return 0.0
    true_positive = 0
    precision_recall: list[tuple[float, float]] = []
    for index, (_score, matched) in enumerate(rows, start=1):
        true_positive += int(matched)
        precision_recall.append((true_positive / index, true_positive / target_count))
    samples = []
    for step in range(101):
        recall = step / 100.0
        samples.append(
            max(
                (precision for precision, item_recall in precision_recall if item_recall >= recall),
                default=0.0,
            )
        )
    return sum(samples) / len(samples)


def calculate_metrics(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate the frozen one-class metrics from retained prediction rows."""

    if not frames:
        raise RfdetrSegmentationEvaluationError("validation has no frames")
    values: dict[tuple[str, int, int, str], float] = {}
    for frame in frames:
        image_id = str(frame["image_id"])
        for prediction_index, prediction in enumerate(frame["predictions"]):
            for target_index, target in enumerate(frame["targets"]):
                values[(image_id, prediction_index, target_index, "mask")] = _mask_iou(
                    prediction, target
                )
                values[(image_id, prediction_index, target_index, "box")] = _box_iou(
                    prediction["box_xywh"], target["box_xywh"]
                )
    mask_matches = {
        threshold: _match(frames, threshold, "mask", values) for threshold in _THRESHOLDS
    }
    box_matches = {threshold: _match(frames, threshold, "box", values) for threshold in _THRESHOLDS}
    mask_ap = {
        str(threshold): _average_precision(rows, target_count)
        for threshold, (rows, target_count, _false, _duplicates) in mask_matches.items()
    }
    box_ap = {
        str(threshold): _average_precision(rows, target_count)
        for threshold, (rows, target_count, _false, _duplicates) in box_matches.items()
    }
    _rows, target_count, false_predictions, duplicate_predictions = mask_matches[0.5]
    recall = sum(int(matched) for _score, matched in _rows) / target_count if target_count else 0.0
    empty = sum(not frame["predictions"] for frame in frames)
    return {
        "frame_count": len(frames),
        "target_count": target_count,
        "prediction_count": sum(len(frame["predictions"]) for frame in frames),
        "mask_ap_50_95": round(sum(mask_ap.values()) / len(mask_ap), 6),
        "mask_ap50": round(mask_ap["0.5"], 6),
        "box_ap50_95": round(sum(box_ap.values()) / len(box_ap), 6),
        "recall": round(recall, 6),
        "false_predictions": false_predictions,
        "duplicate_predictions": duplicate_predictions,
        "empty_prediction_rate": round(empty / len(frames), 6),
    }


def _targets(coco: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for annotation in coco["annotations"]:
        if annotation.get("category_id") != 1:
            raise RfdetrSegmentationEvaluationError(
                "validation COCO annotation has another category"
            )
        if annotation.get("card_side") not in _CARD_SIDES:
            raise RfdetrSegmentationEvaluationError(
                "validation COCO annotation has an unsupported card side"
            )
        segmentation = annotation.get("segmentation")
        if not isinstance(segmentation, list) or not segmentation:
            raise RfdetrSegmentationEvaluationError(
                "validation COCO annotation has no mask polygon"
            )
        polygons = [
            [[float(points[index]), float(points[index + 1])] for index in range(0, len(points), 2)]
            for points in segmentation
        ]
        result[int(annotation["image_id"])].append(
            {
                "annotation_id": int(annotation["id"]),
                "card_id": annotation["card_id"],
                "card_side": annotation["card_side"],
                "polygons": polygons,
                "box_xywh": [float(value) for value in annotation["bbox"]],
            }
        )
    return result


def _visible_card_count_bucket(count: int) -> str:
    if count < 1:
        raise RfdetrSegmentationEvaluationError("visible-card count must be positive")
    if count <= 2:
        return str(count)
    if count <= 4:
        return "3-4"
    return "5+"


def _filtered_frames(frames: Sequence[Mapping[str, Any]], predicate: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for frame in frames:
        targets = [target for target in frame["targets"] if predicate(frame, target)]
        if targets:
            result.append({**frame, "targets": targets})
    return result


def _slice_metrics(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate the required independent recording, side, and count slices."""

    def by_recording(value: str) -> list[dict[str, Any]]:
        return _filtered_frames(frames, lambda frame, _target: frame["recording_id"] == value)

    def by_side(value: str) -> list[dict[str, Any]]:
        return _filtered_frames(frames, lambda _frame, target: target["card_side"] == value)

    def by_bucket(value: str) -> list[dict[str, Any]]:
        return _filtered_frames(
            frames,
            lambda frame, _target: frame["visible_card_count_bucket"] == value,
        )

    recording_ids = sorted({str(frame["recording_id"]) for frame in frames})
    sides = sorted(
        {
            str(target["card_side"])
            for frame in frames
            for target in frame["targets"]
            if target["card_side"] in _CARD_SIDES
        }
    )
    buckets = sorted({str(frame["visible_card_count_bucket"]) for frame in frames})
    by_group: dict[str, dict[str, Any]] = {}
    for recording_id in recording_ids:
        for side in sides:
            for bucket in buckets:
                selected = _filtered_frames(
                    frames,
                    lambda frame, target, recording_id=recording_id, side=side, bucket=bucket: (
                        frame["recording_id"] == recording_id
                        and frame["visible_card_count_bucket"] == bucket
                        and target["card_side"] == side
                    ),
                )
                if selected:
                    by_group[f"{recording_id}|{side}|{bucket}"] = calculate_metrics(selected)
    return {
        "by_recording": {
            recording_id: calculate_metrics(by_recording(recording_id))
            for recording_id in recording_ids
        },
        "by_side": {side: calculate_metrics(by_side(side)) for side in sides},
        "by_visible_card_count_bucket": {
            bucket: calculate_metrics(by_bucket(bucket)) for bucket in buckets
        },
        "by_recording_side_bucket": by_group,
    }


def _prediction_artifact(
    *, model_id: str, model: Any, view: Mapping[str, Any], partition: str = "valid"
) -> dict[str, Any]:
    if partition not in _PARTITIONS:
        raise RfdetrSegmentationEvaluationError(f"unsupported evaluation partition: {partition}")
    root = Path(view["root"])
    partition_label = _PARTITION_LABELS[partition]
    coco = _read_json(root / partition / "_annotations.coco.json", f"{partition_label} COCO data")
    targets = _targets(coco)
    frames: list[dict[str, Any]] = []
    for image in sorted(coco["images"], key=lambda item: int(item["id"])):
        image_id = int(image["id"])
        image_path = root / partition / str(image["file_name"])
        prediction_rows = _prediction_rows(
            model, image_path, int(image["width"]), int(image["height"])
        )
        frames.append(
            {
                "image_id": image_id,
                "recording_id": image["recording_id"],
                "event_id": image["event_id"],
                "image_sha256": image["sha256"],
                "width": int(image["width"]),
                "height": int(image["height"]),
                "targets": [
                    {**target, "width": int(image["width"]), "height": int(image["height"])}
                    for target in targets[image_id]
                ],
                "predictions": [
                    {
                        **prediction,
                        "polygons": [prediction["polygon_pixels"]],
                        "width": int(image["width"]),
                        "height": int(image["height"]),
                    }
                    for prediction in prediction_rows
                ],
            }
        )
        frames[-1]["visible_card_count"] = len(frames[-1]["targets"])
        frames[-1]["visible_card_count_bucket"] = _visible_card_count_bucket(
            frames[-1]["visible_card_count"]
        )
    return {
        "schema_version": "rfdetr-segmentation-validation-predictions/v1",
        "model_id": model_id,
        "partition": partition_label,
        "confidence_threshold": 0.5,
        "frames": frames,
        "metrics": {"overall": calculate_metrics(frames), **_slice_metrics(frames)},
    }


def _exclusion_artifact(view: Mapping[str, Any], partition: str) -> dict[str, Any]:
    if partition not in _PARTITIONS:
        raise RfdetrSegmentationEvaluationError(f"unsupported exclusion partition: {partition}")
    root = Path(view["root"])
    exclusions = _read_json(root / "exclusions.json", "M1 exclusion receipt")
    label = _PARTITION_LABELS[partition]
    excluded_frames = [
        row for row in exclusions.get("excluded_frames", []) if row.get("split") == label
    ]
    ineligible_outcomes = [
        row for row in exclusions.get("ineligible_outcomes", []) if row.get("split") == label
    ]
    return {
        "excluded_frames": excluded_frames,
        "ineligible_outcomes": ineligible_outcomes,
        "excluded_frame_count": len(excluded_frames),
        "ineligible_outcome_count": len(ineligible_outcomes),
    }


def _clear_device_cache(device: str) -> None:
    try:
        import torch
    except ImportError:
        return
    if device == "mps" and hasattr(torch, "mps"):
        torch.mps.empty_cache()
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _artifact_path(output: Path, key: str) -> Path:
    return output / f"{key.replace('_', '-')}-predictions.json"


def _evaluate_model(
    checkpoint: Path,
    view: Mapping[str, Any],
    device: str,
    *,
    model_id: str,
    pretrained: bool,
    partition: str,
) -> dict[str, Any]:
    model = _load_model(checkpoint, device, pretrained=pretrained)
    try:
        return _prediction_artifact(
            model_id=model_id,
            model=model,
            view=view,
            partition=partition,
        )
    finally:
        del model
        _clear_device_cache(device)


def run_rfdetr_segmentation_campaign_validation(
    config: RfdetrSegmentationEvaluationConfig,
) -> dict[str, Any]:
    """Run the locked validation and, when allowed, one sealed-test evaluation."""

    output = config.output_dir.expanduser().resolve()
    report_path = output / "report.json"
    expected_config = {
        "dataset_dir": str(config.dataset_dir.expanduser().resolve()),
        "campaign_manifest": str(config.campaign_manifest.expanduser().resolve()),
        "pretrained_checkpoint": str(config.pretrained_checkpoint.expanduser().resolve()),
        "candidate_bundle": str(config.candidate_bundle.expanduser().resolve()),
        "output_dir": str(output),
        "device": config.device,
    }
    if report_path.is_file():
        report = _read_json(report_path, "locked validation report")
        if (
            report.get("schema_version") == RFDETR_SEGMENTATION_VALIDATION_SCHEMA
            and report.get("config") == expected_config
        ):
            artifacts = report.get("artifacts")
            if not isinstance(artifacts, Mapping):
                raise RfdetrSegmentationEvaluationError("validation artifacts are missing")
            for artifact in artifacts.values():
                if not isinstance(artifact, Mapping) or not isinstance(artifact.get("path"), str):
                    raise RfdetrSegmentationEvaluationError(
                        "validation artifact metadata is invalid"
                    )
                path = output / artifact["path"]
                if not path.is_file() or artifact.get("sha256") != _file_digest(path):
                    raise RfdetrSegmentationEvaluationError(
                        "completed validation artifact has drifted"
                    )
            return report
        raise RfdetrSegmentationEvaluationError("validation output already belongs to another run")
    if output.exists() and any(output.iterdir()):
        raise RfdetrSegmentationEvaluationError("validation output directory is not empty")
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        view = _load_materialization_view(config.dataset_dir)
        pretrained = config.pretrained_checkpoint.expanduser().resolve()
        if not pretrained.is_file():
            raise RfdetrSegmentationEvaluationError("pretrained checkpoint does not exist")
        pretrained_sha256 = _file_digest(pretrained)
        manifest_receipt = _verify_campaign_manifest(
            view, config.campaign_manifest, pretrained_sha256
        )
        candidate = load_rfdetr_segmentation_bundle(config.candidate_bundle)
        if (
            candidate.manifest["materialization_digest"]
            != view["manifest"]["materialization_digest"]
        ):
            raise RfdetrSegmentationEvaluationError(
                "candidate bundle uses another M1 materialization"
            )
        if (
            manifest_receipt.get("campaign_id")
            == "0068-m0-reviewed-rfdetr-local-visible-card-detector"
            and candidate.manifest.get("campaign_manifest", {}).get("manifest_digest")
            != manifest_receipt["manifest_digest"]
        ):
            raise RfdetrSegmentationEvaluationError(
                "candidate bundle does not contain the frozen 0068 manifest receipt"
            )
        baseline = _evaluate_model(
            pretrained,
            view,
            config.device,
            model_id="pretrained-baseline",
            pretrained=True,
            partition="valid",
        )
        candidate_predictions = _evaluate_model(
            candidate.checkpoint_path,
            view,
            config.device,
            model_id="candidate",
            pretrained=False,
            partition="valid",
        )
        validation_metrics = {
            "baseline": baseline["metrics"],
            "candidate": candidate_predictions["metrics"],
        }
        candidate_overall = candidate_predictions["metrics"]["overall"]
        baseline_overall = baseline["metrics"]["overall"]
        validation_gate = {
            "candidate_reloads": True,
            "metrics_reproducible": True,
            "mask_ap_better_than_baseline": candidate_overall["mask_ap_50_95"]
            > baseline_overall["mask_ap_50_95"],
            "recall_better_than_baseline": candidate_overall["recall"] > baseline_overall["recall"],
        }
        validation_passes = all(validation_gate.values())
        prediction_artifacts: dict[str, dict[str, Any]] = {
            "validation_baseline": baseline,
            "validation_candidate": candidate_predictions,
        }
        sealed_metrics: dict[str, Any] | None = None
        sealed_gate: dict[str, Any] = {
            "evaluated": False,
            "reason": "validation_gate_failed",
            "passes": False,
        }
        if validation_passes:
            sealed_baseline = _evaluate_model(
                pretrained,
                view,
                config.device,
                model_id="pretrained-baseline",
                pretrained=True,
                partition="sealed_test",
            )
            sealed_candidate = _evaluate_model(
                candidate.checkpoint_path,
                view,
                config.device,
                model_id="candidate",
                pretrained=False,
                partition="sealed_test",
            )
            prediction_artifacts.update(
                {
                    "sealed_test_baseline": sealed_baseline,
                    "sealed_test_candidate": sealed_candidate,
                }
            )
            sealed_metrics = {
                "baseline": sealed_baseline["metrics"],
                "candidate": sealed_candidate["metrics"],
            }
            sealed_gate = {
                "evaluated": True,
                "every_recording_has_target_recall": all(
                    metrics["recall"] > 0
                    for metrics in sealed_candidate["metrics"]["by_recording"].values()
                ),
            }
            sealed_gate["passes"] = all(
                value for key, value in sealed_gate.items() if key != "evaluated"
            )
        gate = {
            "validation": {**validation_gate, "passes": validation_passes},
            "sealed_test": sealed_gate,
            "passes": validation_passes and bool(sealed_gate["passes"]),
        }
        for key, artifact in prediction_artifacts.items():
            path = _artifact_path(output, key)
            _write_json(path, artifact)
        exclusions = {
            _PARTITION_LABELS[partition]: _exclusion_artifact(view, partition)
            for partition in _PARTITIONS
        }
        partition_reports = {
            label: {
                "prediction_frame_count": artifact["metrics"]["overall"]["frame_count"],
                "target_count": artifact["metrics"]["overall"]["target_count"],
                "excluded_frame_count": exclusions[label]["excluded_frame_count"],
                "ineligible_outcome_count": exclusions[label]["ineligible_outcome_count"],
            }
            for label, artifact in (
                ("validation", candidate_predictions),
                *(
                    [("sealed_test", prediction_artifacts["sealed_test_candidate"])]
                    if sealed_metrics is not None
                    else []
                ),
            )
        }
        report = {
            "schema_version": RFDETR_SEGMENTATION_VALIDATION_SCHEMA,
            "status": "completed",
            "config": expected_config,
            "duration_seconds": round(time.monotonic() - started, 3),
            "environment": {
                "platform": platform.platform(),
                "rfdetr": RFDETR_SEGMENTATION_PACKAGE_VERSION,
            },
            "campaign_manifest": manifest_receipt,
            "materialization_digest": view["manifest"]["materialization_digest"],
            "pretrained_checkpoint": {"sha256": pretrained_sha256, "path": str(pretrained)},
            "candidate_bundle": {
                "bundle_digest": candidate.manifest["bundle_digest"],
                "checkpoint_sha256": candidate.manifest["checkpoint_sha256"],
            },
            "partitions": partition_reports,
            "metrics": {
                "validation": validation_metrics,
                "sealed_test": sealed_metrics,
            },
            "gate": gate,
            "exclusions": exclusions,
            "limitations": {
                "background_only_frames_available": False,
                "note": (
                    "The corpus has no reviewed empty-background frames. Excluded frames remain "
                    "outside the score."
                ),
            },
            "artifacts": {
                key: {
                    "path": path.name,
                    "sha256": _file_digest(path),
                }
                for key, path in (
                    (key, _artifact_path(output, key)) for key in prediction_artifacts
                )
            },
        }
        _write_json(report_path, report)
        return report
    except Exception:
        # Keep a small failure record without mistaking a partial result for a completed validation.
        _write_json(
            output / "run.json",
            {
                "schema_version": RFDETR_SEGMENTATION_VALIDATION_SCHEMA,
                "status": "failed",
                "config": expected_config,
            },
        )
        raise


__all__ = [
    "RFDETR_SEGMENTATION_VALIDATION_SCHEMA",
    "RfdetrSegmentationEvaluationConfig",
    "RfdetrSegmentationEvaluationError",
    "calculate_metrics",
    "run_rfdetr_segmentation_campaign_validation",
]
