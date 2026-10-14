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
_CARD_CATEGORY_ID = 1
_PILE_CATEGORY_ID = 2
_MODEL_INDEX_TO_CATEGORY_ID = {0: _CARD_CATEGORY_ID, 1: _PILE_CATEGORY_ID}


def _prediction_category_id(prediction: Mapping[str, Any]) -> int:
    if "category_id" in prediction:
        return int(prediction["category_id"])
    model_index = int(prediction.get("class_id", 0))
    if model_index not in _MODEL_INDEX_TO_CATEGORY_ID:
        raise RfdetrSegmentationEvaluationError("prediction uses an unsupported model class index")
    return _MODEL_INDEX_TO_CATEGORY_ID[model_index]


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
    comparison_bundle: Path | None = None
    device: Literal["cpu", "mps", "cuda"] = "mps"


@dataclass(frozen=True, slots=True)
class RfdetrSegmentationSealedTestConfig:
    """Inputs for the one sealed-test pass authorized by a frozen M5 decision."""

    dataset_dir: Path
    campaign_manifest: Path
    pretrained_checkpoint: Path
    training_run: Path
    validation_report: Path
    candidate_bundle: Path
    pretest_decision: Path
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


def _load_model(
    checkpoint: Path, device: str, *, pretrained: bool = False, num_classes: int = 1
) -> Any:
    _assert_device(device)
    model_class = _import_segmentation_model()
    try:
        if pretrained:
            return model_class(
                num_classes=num_classes,
                pretrain_weights=str(checkpoint),
                resolution=RFDETR_SEGMENTATION_INPUT_SIZE,
                device=device,
                amp=False,
            )
        return model_class.from_checkpoint(
            str(checkpoint),
            num_classes=num_classes,
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
                "category_id": _MODEL_INDEX_TO_CATEGORY_ID[int(class_id)],
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


def _rle_mask(rle: Mapping[str, Any], width: int, height: int) -> Image.Image:
    if rle.get("size") != [height, width] or not isinstance(rle.get("counts"), list):
        raise RfdetrSegmentationEvaluationError("target RLE dimensions or counts are invalid")
    pixels = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(pixels)
    cursor = 0
    value = 0
    for raw_count in rle["counts"]:
        if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
            raise RfdetrSegmentationEvaluationError("target RLE contains an invalid run")
        end = cursor + raw_count
        if end > width * height:
            raise RfdetrSegmentationEvaluationError("target RLE exceeds its declared dimensions")
        if value:
            for index in range(cursor, end):
                draw.point((index // height, index % height), fill=1)
        cursor = end
        value = 1 - value
    if cursor != width * height:
        raise RfdetrSegmentationEvaluationError("target RLE does not cover its declared dimensions")
    return pixels


def _mask(
    polygons: Sequence[Sequence[Sequence[float]]] | None,
    width: int,
    height: int,
    rle: Mapping[str, Any] | None = None,
) -> Image.Image:
    if rle is not None:
        return _rle_mask(rle, width, height)
    result = Image.new("1", (width, height), 0)
    drawer = ImageDraw.Draw(result)
    for polygon in polygons or ():
        drawer.polygon([(float(point[0]), float(point[1])) for point in polygon], fill=1)
    return result


def _mask_iou(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    width, height = int(left["width"]), int(left["height"])
    left_mask = _mask(left.get("polygons"), width, height, left.get("rle"))
    right_mask = _mask(right.get("polygons"), width, height, right.get("rle"))
    intersection = ImageChops.logical_and(left_mask, right_mask).histogram()[-1]
    union = ImageChops.logical_or(left_mask, right_mask).histogram()[-1]
    return 0.0 if union == 0 else intersection / union


def _prediction_area_fraction_inside(
    prediction: Mapping[str, Any], target: Mapping[str, Any]
) -> float:
    width, height = int(prediction["width"]), int(prediction["height"])
    prediction_mask = _mask(prediction.get("polygons"), width, height, prediction.get("rle"))
    target_mask = _mask(target.get("polygons"), width, height, target.get("rle"))
    prediction_area = prediction_mask.histogram()[1]
    intersection = ImageChops.logical_and(prediction_mask, target_mask).histogram()[-1]
    return 0.0 if prediction_area == 0 else intersection / prediction_area


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
            if _prediction_category_id(_prediction) != int(
                _target.get("category_id", _CARD_CATEGORY_ID)
            ):
                continue
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


def calculate_metrics(
    frames: Sequence[Mapping[str, Any]], *, include_class_reports: bool = True
) -> dict[str, Any]:
    """Calculate class-aware mask and box metrics from retained prediction rows."""

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
    result: dict[str, Any] = {
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
    if include_class_reports:
        class_reports: dict[str, Any] = {}
        for category_id, name in (
            (_CARD_CATEGORY_ID, "visible_card"),
            (_PILE_CATEGORY_ID, "card_pile"),
        ):
            class_frames = [
                {
                    **frame,
                    "targets": [
                        target
                        for target in frame["targets"]
                        if int(target.get("category_id", _CARD_CATEGORY_ID)) == category_id
                    ],
                    "predictions": [
                        prediction
                        for prediction in frame["predictions"]
                        if _prediction_category_id(prediction) == category_id
                    ],
                }
                for frame in frames
            ]
            class_reports[name] = calculate_metrics(class_frames, include_class_reports=False)
        confusion = {"visible_card_to_card_pile": 0, "card_pile_to_visible_card": 0}
        fragments_inside_piles = 0
        for frame in frames:
            pile_targets = [
                target
                for target in frame["targets"]
                if int(target.get("category_id", _CARD_CATEGORY_ID)) == _PILE_CATEGORY_ID
            ]
            for prediction in frame["predictions"]:
                category_id = _prediction_category_id(prediction)
                candidates = [
                    (_mask_iou(prediction, target), int(target.get("category_id", 1)))
                    for target in frame["targets"]
                ]
                best_iou, best_category = max(candidates, default=(0.0, category_id))
                if best_iou >= 0.5 and best_category != category_id:
                    key = (
                        "visible_card_to_card_pile"
                        if category_id == _CARD_CATEGORY_ID
                        else "card_pile_to_visible_card"
                    )
                    confusion[key] += 1
                if (
                    category_id == _CARD_CATEGORY_ID
                    and pile_targets
                    and any(
                        _prediction_area_fraction_inside(prediction, pile) > 0.5
                        for pile in pile_targets
                    )
                ):
                    fragments_inside_piles += 1
        near_pile_frames: list[dict[str, Any]] = []
        face_down_frames: list[dict[str, Any]] = []
        for frame in frames:
            piles = [
                target
                for target in frame["targets"]
                if int(target.get("category_id", _CARD_CATEGORY_ID)) == _PILE_CATEGORY_ID
            ]
            cards_near: list[Mapping[str, Any]] = []
            face_down_cards = [
                target
                for target in frame["targets"]
                if int(target.get("category_id", _CARD_CATEGORY_ID)) == _CARD_CATEGORY_ID
                and target.get("card_side") == "face_down"
            ]
            if face_down_cards:
                face_down_frames.append(
                    {
                        **frame,
                        "targets": face_down_cards,
                        "predictions": [
                            prediction
                            for prediction in frame["predictions"]
                            if _prediction_category_id(prediction) == _CARD_CATEGORY_ID
                        ],
                    }
                )
            width, height = int(frame.get("width", 0)), int(frame.get("height", 0))
            gap_limit = max(4.0, min(width, height) * 0.05) if width and height else 4.0
            for card in frame["targets"]:
                if int(card.get("category_id", _CARD_CATEGORY_ID)) != _CARD_CATEGORY_ID:
                    continue
                x, y, w, h = card["box_xywh"]
                for pile in piles:
                    px, py, pw, ph = pile["box_xywh"]
                    dx = max(px - (x + w), x - (px + pw), 0.0)
                    dy = max(py - (y + h), y - (py + ph), 0.0)
                    if math.hypot(dx, dy) <= gap_limit:
                        cards_near.append(card)
                        break
            if cards_near:
                near_pile_frames.append(
                    {
                        **frame,
                        "targets": cards_near,
                        "predictions": [
                            prediction
                            for prediction in frame["predictions"]
                            if _prediction_category_id(prediction) == _CARD_CATEGORY_ID
                        ],
                    }
                )
        result.update(
            {
                "by_class": class_reports,
                "class_confusion_at_mask_iou_50": confusion,
                "visible_card_fragments_inside_piles": fragments_inside_piles,
                "visible_card_near_pile": (
                    {
                        "gap_limit_policy": "5_percent_of_shorter_image_dimension_min_4px",
                        **calculate_metrics(near_pile_frames, include_class_reports=False),
                    }
                    if near_pile_frames
                    else {
                        "status": "no_near_pile_card_targets",
                        "target_count": 0,
                        "gap_limit_policy": "5_percent_of_shorter_image_dimension_min_4px",
                    }
                ),
                "named_slices": {
                    "face_down_cards": (
                        calculate_metrics(face_down_frames, include_class_reports=False)
                        if face_down_frames
                        else {"status": "no_face_down_targets", "target_count": 0}
                    ),
                    "pile_edges": {
                        "status": "not_separately_tagged_in_m2_view",
                        "metrics": class_reports["card_pile"],
                    },
                    "ordinary_trick_overlap": {"status": "not_tagged_in_m2_view"},
                    "human_hands": {"status": "not_tagged_in_m2_view"},
                },
                "slice_availability": {
                    "ordinary_trick_overlap": "not_tagged_in_m2_view",
                    "pile_edges": "pile_targets_reported_as_card_pile_class",
                    "face_down_cards": "available_from_card_side",
                    "human_hands": "not_tagged_in_m2_view",
                },
            }
        )
    return result


def _targets(coco: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    categories = coco.get("categories")
    if categories == [{"id": 1, "name": "visible_card", "supercategory": "card"}]:
        supported_categories = {1: "visible_card"}
    elif categories == [
        {"id": 1, "name": "visible_card", "supercategory": "card"},
        {"id": 2, "name": "card_pile", "supercategory": "card"},
    ]:
        supported_categories = {1: "visible_card", 2: "card_pile"}
    else:
        raise RfdetrSegmentationEvaluationError("validation COCO class map is unsupported")
    for annotation in coco["annotations"]:
        category_id = annotation.get("category_id")
        if category_id not in supported_categories:
            raise RfdetrSegmentationEvaluationError(
                "validation COCO annotation has an unknown category"
            )
        segmentation = annotation.get("segmentation")
        target: dict[str, Any] = {
            "annotation_id": int(annotation["id"]),
            "category_id": int(category_id),
            "category": supported_categories[int(category_id)],
            "box_xywh": [float(value) for value in annotation["bbox"]],
        }
        if category_id == _CARD_CATEGORY_ID:
            if annotation.get("card_side") not in _CARD_SIDES:
                raise RfdetrSegmentationEvaluationError(
                    "validation COCO annotation has an unsupported card side"
                )
            if not isinstance(segmentation, list) or not segmentation:
                raise RfdetrSegmentationEvaluationError("visible card target has no mask polygon")
            target.update(
                {
                    "card_id": annotation.get("card_id"),
                    "card_side": annotation["card_side"],
                    "polygons": [
                        [
                            [float(points[index]), float(points[index + 1])]
                            for index in range(0, len(points), 2)
                        ]
                        for points in segmentation
                    ],
                }
            )
        else:
            if not isinstance(segmentation, Mapping):
                raise RfdetrSegmentationEvaluationError("pile target has no COCO RLE mask")
            target["rle"] = dict(segmentation)
            target["grouped_candidate_ids"] = annotation.get("grouped_candidate_ids", [])
        result[int(annotation["image_id"])].append(target)
    return result


def _visible_card_count_bucket(count: int) -> str:
    if count < 0:
        raise RfdetrSegmentationEvaluationError("visible-card count cannot be negative")
    if count == 0:
        return "0"
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
        return _filtered_frames(frames, lambda _frame, target: target.get("card_side") == value)

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
            if target.get("card_side") in _CARD_SIDES
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
                        and target.get("card_side") == side
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
        frames[-1]["visible_card_count"] = sum(
            int(target.get("category_id", _CARD_CATEGORY_ID)) == _CARD_CATEGORY_ID
            for target in frames[-1]["targets"]
        )
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


def _expanded_validation_gates(
    candidate: Mapping[str, Any], baseline: Mapping[str, Any]
) -> dict[str, bool]:
    candidate_classes = candidate.get("by_class", {})
    baseline_classes = baseline.get("by_class", {})
    candidate_card = candidate_classes.get("visible_card", {})
    baseline_card = baseline_classes.get("visible_card", {})
    candidate_pile = candidate_classes.get("card_pile", {})
    baseline_pile = baseline_classes.get("card_pile", {})
    return {
        "visible_card_mask_ap_50_95_strictly_greater": candidate_card.get(
            "mask_ap_50_95", 0
        )
        > baseline_card.get("mask_ap_50_95", 0),
        "visible_card_recall_strictly_greater": candidate_card.get("recall", 0)
        > baseline_card.get("recall", 0),
        "card_pile_mask_ap_50_95_strictly_greater": candidate_pile.get("mask_ap_50_95", 0)
        > baseline_pile.get("mask_ap_50_95", 0),
        "card_pile_recall_strictly_greater": candidate_pile.get("recall", 0)
        > baseline_pile.get("recall", 0),
        "false_detections_no_worse": candidate.get("false_predictions", 0)
        <= baseline.get("false_predictions", 0),
        "duplicate_detections_no_worse": candidate.get("duplicate_predictions", 0)
        <= baseline.get("duplicate_predictions", 0),
        "empty_prediction_rate_no_worse": candidate.get("empty_prediction_rate", 0)
        <= baseline.get("empty_prediction_rate", 0),
    }


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
    num_classes = len(view.get("class_map", {"1": "visible_card"}))
    model = _load_model(checkpoint, device, pretrained=pretrained, num_classes=num_classes)
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


def _timed_evaluate_model(
    checkpoint: Path,
    view: Mapping[str, Any],
    device: str,
    *,
    model_id: str,
    pretrained: bool,
) -> tuple[dict[str, Any], dict[str, float]]:
    load_started = time.monotonic()
    model = _load_model(
        checkpoint,
        device,
        pretrained=pretrained,
        num_classes=len(view.get("class_map", {})),
    )
    load_ms = (time.monotonic() - load_started) * 1000
    inference_started = time.monotonic()
    try:
        artifact = _prediction_artifact(
            model=model,
            view=view,
            model_id=model_id,
            partition="sealed_test",
        )
        inference_ms = (time.monotonic() - inference_started) * 1000
        frame_count = len(artifact["frames"])
        return artifact, {
            "load_ms": round(load_ms, 3),
            "inference_total_ms": round(inference_ms, 3),
            "inference_mean_ms_per_frame": round(inference_ms / max(frame_count, 1), 3),
            "frame_count": frame_count,
        }
    finally:
        del model
        _clear_device_cache(device)


def run_rfdetr_segmentation_sealed_test(
    config: RfdetrSegmentationSealedTestConfig,
) -> dict[str, Any]:
    """Evaluate the frozen candidate and baseline once after verifying the M5 lock."""

    output = config.output_dir.expanduser().resolve()
    report_path = output / "report.json"
    expected_config = {
        "dataset_dir": str(config.dataset_dir.expanduser().resolve()),
        "campaign_manifest": str(config.campaign_manifest.expanduser().resolve()),
        "pretrained_checkpoint": str(config.pretrained_checkpoint.expanduser().resolve()),
        "training_run": str(config.training_run.expanduser().resolve()),
        "validation_report": str(config.validation_report.expanduser().resolve()),
        "candidate_bundle": str(config.candidate_bundle.expanduser().resolve()),
        "pretest_decision": str(config.pretest_decision.expanduser().resolve()),
        "output_dir": str(output),
        "device": config.device,
    }
    if report_path.is_file():
        report = _read_json(report_path, "M5 sealed-test report")
        if report.get("config") != expected_config:
            raise RfdetrSegmentationEvaluationError("M5 output belongs to another evaluation")
        for key, metadata in report.get("artifacts", {}).items():
            artifact_path = output / metadata["path"]
            if not artifact_path.is_file() or _file_digest(artifact_path) != metadata.get("sha256"):
                raise RfdetrSegmentationEvaluationError(f"M5 artifact drifted: {key}")
        registry_metadata = report.get("provider_registry")
        if isinstance(registry_metadata, Mapping):
            registry_path = output / str(registry_metadata.get("path"))
            if not registry_path.is_file() or _file_digest(registry_path) != registry_metadata.get(
                "sha256"
            ):
                raise RfdetrSegmentationEvaluationError("M5 provider registry has drifted")
        return report
    if output.exists() and any(output.iterdir()):
        raise RfdetrSegmentationEvaluationError("M5 output directory is not empty")

    decision_path = config.pretest_decision.expanduser().resolve()
    decision = _read_json(decision_path, "frozen M5 pretest decision")
    decision_digest = decision.get("decision_sha256")
    unsigned_decision = {key: value for key, value in decision.items() if key != "decision_sha256"}
    if (
        decision.get("schema_version") != "0087-m5-pretest-decision/v1"
        or decision.get("state") != "locked_before_sealed_test"
        or decision_digest != _digest(unsigned_decision)
        or decision.get("action") != "evaluate_candidate_and_baseline_once"
    ):
        raise RfdetrSegmentationEvaluationError("M5 pretest decision is not a valid frozen lock")

    manifest_path = config.campaign_manifest.expanduser().resolve()
    validation_path = config.validation_report.expanduser().resolve()
    training_path = config.training_run.expanduser().resolve()
    bundle_path = config.candidate_bundle.expanduser().resolve()
    manifest = _read_json(manifest_path, "M0 campaign manifest")
    validation = _read_json(validation_path, "M3 validation report")
    training = _read_json(training_path, "M3 training run")
    bundle = load_rfdetr_segmentation_bundle(bundle_path)
    if training.get("status") != "completed":
        raise RfdetrSegmentationEvaluationError("M3 training run is not completed")
    expected_receipts = decision.get("input_sha256", {})
    actual_receipts = {
        "campaign_manifest": _file_digest(manifest_path),
        "validation_report": _file_digest(validation_path),
        "training_run": _file_digest(training_path),
        "bundle_manifest": _file_digest(bundle_path / "manifest.json"),
    }
    if expected_receipts != actual_receipts:
        raise RfdetrSegmentationEvaluationError("M5 frozen input digests do not match")
    if bundle.manifest.get("bundle_digest") != decision.get("candidate_bundle_digest"):
        raise RfdetrSegmentationEvaluationError("M5 candidate bundle differs from the frozen lock")
    if validation.get("gate", {}).get("validation", {}).get("passes") is not True:
        raise RfdetrSegmentationEvaluationError("M3 validation gate did not pass")
    m0_digest = manifest.get("manifest_sha256")
    view = _load_materialization_view(config.dataset_dir)
    _verify_campaign_manifest(
        view,
        manifest_path,
        _file_digest(config.pretrained_checkpoint.expanduser().resolve()),
    )
    if view["manifest"].get("materialization_digest") != decision.get("materialization_digest"):
        raise RfdetrSegmentationEvaluationError("M1 materialization differs from the frozen lock")
    if bundle.manifest.get("materialization_digest") != decision.get("materialization_digest"):
        raise RfdetrSegmentationEvaluationError("candidate bundle lineage differs from M1")

    validation_metrics = validation.get("metrics", {}).get("validation", {})
    baseline = validation_metrics.get("baseline", {}).get("overall", {})
    candidate = validation_metrics.get("candidate", {}).get("overall", {})
    baseline_recordings = validation_metrics.get("baseline", {}).get("by_recording", {})
    candidate_recordings = validation_metrics.get("candidate", {}).get("by_recording", {})
    if not baseline_recordings or baseline_recordings.keys() != candidate_recordings.keys():
        raise RfdetrSegmentationEvaluationError("M3 visible-card recording metrics are incomplete")
    baseline_duplicates = baseline.get("duplicate_predictions")
    candidate_duplicates = candidate.get("duplicate_predictions")
    baseline_empty = baseline.get("empty_prediction_rate")
    candidate_empty = candidate.get("empty_prediction_rate")
    baseline_false = baseline.get("false_predictions")
    candidate_false = candidate.get("false_predictions")
    pile_recordings = [
        recording_id
        for recording_id, metrics in candidate_recordings.items()
        if metrics.get("by_class", {}).get("card_pile", {}).get("target_count", 0) > 0
    ]
    validation_gates = {
        "visible_card_mask_ap_improved": all(
            candidate_recordings[recording_id]["by_class"]["visible_card"].get("mask_ap_50_95", 0)
            > baseline_recordings[recording_id]["by_class"]["visible_card"].get("mask_ap_50_95", 0)
            for recording_id in baseline_recordings
        ),
        "visible_card_recall_improved": all(
            candidate_recordings[recording_id]["by_class"]["visible_card"].get("recall", 0)
            > baseline_recordings[recording_id]["by_class"]["visible_card"].get("recall", 0)
            for recording_id in baseline_recordings
        ),
        "card_pile_recall_nonzero_when_supported": bool(pile_recordings)
        and all(
            candidate_recordings[recording_id]["by_class"]["card_pile"].get("recall", 0) > 0
            for recording_id in pile_recordings
        ),
        "false_predictions_no_worse": candidate_false <= baseline_false,
        "duplicate_predictions_no_worse": candidate_duplicates <= baseline_duplicates,
        "empty_prediction_rate_no_worse": candidate_empty <= baseline_empty,
    }
    if not all(validation_gates.values()):
        raise RfdetrSegmentationEvaluationError("M0 validation gates do not permit sealed-test use")

    minimum = manifest.get("minimum_support", {}).get("sealed_test", {})
    partition = manifest.get("partitions", {}).get("sealed_test", {}).get("counts", {})
    if partition.get("retained_frames", 0) < minimum.get("retained_frames", 0) or partition.get(
        "visible_card_targets", 0
    ) < minimum.get("visible_card_targets", 0):
        raise RfdetrSegmentationEvaluationError("sealed-test support is below the frozen minimum")

    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    checkpoint = config.pretrained_checkpoint.expanduser().resolve()
    baseline_predictions, baseline_timing = _timed_evaluate_model(
        checkpoint, view, config.device, model_id="pretrained-baseline", pretrained=True
    )
    candidate_predictions, candidate_timing = _timed_evaluate_model(
        bundle.checkpoint_path, view, config.device, model_id="candidate", pretrained=False
    )
    candidate_by_recording = candidate_predictions["metrics"]["by_recording"]
    candidate_card_by_recording = {
        recording_id: metrics.get("by_class", {}).get("visible_card", {})
        for recording_id, metrics in candidate_by_recording.items()
    }
    sealed_gate = {
        "every_recording_has_nonzero_visible_card_recall": bool(candidate_card_by_recording)
        and all(metrics.get("recall", 0) > 0 for metrics in candidate_card_by_recording.values()),
        "no_pile_quality_claim": partition.get("pile_targets", 0) == 0,
    }
    gate_passes = (
        all(validation_gates.values())
        and sealed_gate["every_recording_has_nonzero_visible_card_recall"]
    )
    decision_result = (
        "selected_selectable_candidate" if gate_passes else "retained_experiment_baseline_selected"
    )
    prediction_artifacts = {
        "sealed_test_baseline": baseline_predictions,
        "sealed_test_candidate": candidate_predictions,
    }
    artifact_metadata: dict[str, dict[str, str]] = {}
    for key, artifact in prediction_artifacts.items():
        path = _artifact_path(output, key)
        _write_json(path, artifact)
        artifact_metadata[key] = {
            "path": path.name,
            "sha256": _file_digest(path),
        }
    report: dict[str, Any] = {
        "schema_version": "0087-m5-sealed-test-report/v1",
        "status": "completed",
        "decision": decision_result,
        "config": expected_config,
        "pretest_decision_sha256": decision_digest,
        "campaign_manifest_sha256": m0_digest,
        "materialization_digest": decision.get("materialization_digest"),
        "candidate_bundle_digest": bundle.manifest.get("bundle_digest"),
        "candidate_checkpoint_sha256": bundle.manifest.get("checkpoint_sha256"),
        "validation_gates": validation_gates,
        "sealed_test_gate": sealed_gate,
        "metrics": {
            "baseline": baseline_predictions["metrics"],
            "candidate": candidate_predictions["metrics"],
        },
        "latency": {"baseline": baseline_timing, "candidate": candidate_timing},
        "duration_seconds": round(time.monotonic() - started, 3),
        "lineage": {
            **actual_receipts,
            "candidate_materialization_digest": bundle.manifest.get("materialization_digest"),
            "pretrained_checkpoint_sha256": _file_digest(checkpoint),
        },
        "limitations": {
            "sealed_test_pile_targets": partition.get("pile_targets", 0),
            "pile_quality_claim": False,
            "one_training_recording": True,
            "no_empty_background_validation": True,
            "unavailable_slices": ["ordinary_trick_overlap", "human_hand_pixels", "pile_edges"],
        },
        "artifacts": artifact_metadata,
        "provider_registry": None,
    }
    if gate_passes:
        from .rfdetr_segmentation_decision import _provider_registry

        registry_path = output / "provider-registry.json"
        registry = _provider_registry(
            bundle_path=bundle_path,
            manifest=bundle.manifest,
            decision_report=str(report_path),
        )
        _write_json(registry_path, registry)
        report["provider_registry"] = {
            "path": registry_path.name,
            "sha256": _file_digest(registry_path),
            "default_provider": "gemini",
            "selectable": True,
        }
    _write_json(report_path, report)
    return report


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
        "comparison_bundle": (
            str(config.comparison_bundle.expanduser().resolve())
            if config.comparison_bundle is not None
            else None
        ),
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
        if candidate.manifest.get("class_map", {"1": "visible_card"}) != view.get(
            "class_map", {"1": "visible_card"}
        ):
            raise RfdetrSegmentationEvaluationError(
                "candidate bundle class map differs from the frozen COCO view"
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
        comparison_bundle = (
            load_rfdetr_segmentation_bundle(config.comparison_bundle)
            if config.comparison_bundle is not None
            else None
        )
        if manifest_receipt.get("campaign_id") == "0092-m0-expanded-reviewed-rfdetr-campaign":
            if comparison_bundle is None:
                raise RfdetrSegmentationEvaluationError(
                    "0092 validation requires the frozen 0087 comparison bundle"
                )
            manifest = _read_json(config.campaign_manifest, "M0 campaign manifest")
            expected_baseline = manifest.get("comparison_design", {}).get("baseline", {})
            if comparison_bundle.manifest.get("bundle_digest") != expected_baseline.get(
                "bundle_digest"
            ):
                raise RfdetrSegmentationEvaluationError(
                    "comparison bundle differs from the frozen 0087 baseline"
                )
            if comparison_bundle.manifest.get("checkpoint_sha256") != expected_baseline.get(
                "checkpoint_sha256"
            ):
                raise RfdetrSegmentationEvaluationError(
                    "comparison checkpoint differs from the frozen 0087 baseline"
                )
        if comparison_bundle is not None:
            comparison_class_count = len(comparison_bundle.manifest.get("class_map", {}))
            comparison_model = _load_model(
                comparison_bundle.checkpoint_path,
                config.device,
                num_classes=comparison_class_count,
            )
            try:
                baseline = _prediction_artifact(
                    model_id="0087-candidate-baseline",
                    model=comparison_model,
                    view=view,
                    partition="valid",
                )
            finally:
                del comparison_model
                _clear_device_cache(config.device)
        else:
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
        pile_mode = len(view.get("class_map", {})) == 2
        candidate_overall = candidate_predictions["metrics"]["overall"]
        baseline_overall = baseline["metrics"]["overall"]
        validation_gate = {"candidate_reloads": True, "metrics_reproducible": True}
        if manifest_receipt.get("campaign_id") == "0092-m0-expanded-reviewed-rfdetr-campaign":
            validation_gate.update(
                _expanded_validation_gates(candidate_overall, baseline_overall)
            )
        elif pile_mode:
            validation_gate["quality_assessment"] = (
                "awaiting_0087_m5_decision"
                if manifest_receipt.get("campaign_id") == "0087-m0-reviewed-rfdetr-campaign"
                else "deferred_to_0087"
            )
        else:
            validation_gate.update(
                {
                    "mask_ap_better_than_baseline": candidate_overall["mask_ap_50_95"]
                    > baseline_overall["mask_ap_50_95"],
                    "recall_better_than_baseline": candidate_overall["recall"]
                    > baseline_overall["recall"],
                }
            )
        validation_passes = all(
            value is True for key, value in validation_gate.items() if key != "quality_assessment"
        )
        prediction_artifacts: dict[str, dict[str, Any]] = {
            "validation_baseline": baseline,
            "validation_candidate": candidate_predictions,
        }
        sealed_metrics: dict[str, Any] | None = None
        sealed_gate: dict[str, Any] = {
            "evaluated": False,
            "reason": (
                "0087 M5 decides whether to open the sealed test"
                if manifest_receipt.get("campaign_id") == "0087-m0-reviewed-rfdetr-campaign"
                else "0092 M3 requires a locked pretest decision before the sealed test"
                if manifest_receipt.get("campaign_id")
                == "0092-m0-expanded-reviewed-rfdetr-campaign"
                else "0091 M2 view has no sealed_test partition"
                if pile_mode
                else "validation_gate_failed"
            ),
            "passes": False,
        }
        has_sealed_test = "partitions" not in view or "sealed_test" in view["partitions"]
        if validation_passes and not pile_mode and has_sealed_test:
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
            "passes": validation_passes and (pile_mode or bool(sealed_gate["passes"])),
        }
        for key, artifact in prediction_artifacts.items():
            path = _artifact_path(output, key)
            _write_json(path, artifact)
        exclusions = {
            _PARTITION_LABELS[partition]: _exclusion_artifact(view, partition)
            for partition in _PARTITIONS
            if "partitions" not in view or partition in view["partitions"]
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
            "quality_state": (
                "awaiting_0087_m5_decision"
                if manifest_receipt.get("campaign_id") == "0087-m0-reviewed-rfdetr-campaign"
                else "not_assessed_by_0091_m3"
                if pile_mode
                else "evaluated"
            ),
            "evaluation_policy": {
                "grouped_member_candidates_are_individual_ground_truth": False,
                "class_map": view.get("class_map", {"1": "visible_card"}),
                "numerical_quality_gates": "owned_by_0087" if pile_mode else "0068_campaign",
            },
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
