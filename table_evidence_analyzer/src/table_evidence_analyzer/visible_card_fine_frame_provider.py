"""Full-frame and cluster-crop visible-card segmentation with RF-DETR SegMedium."""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError

from . import visible_cards
from .visible_card_cluster_crops import crop_source_image
from .visible_card_cluster_geometry import (
    DUPLICATE_IOU_THRESHOLD,
    ClusterProposal,
    MappedPrediction,
    PixelBox,
    PixelPoint,
    _box_iou,
    _mask_iou,
    build_cluster_layout,
    reconcile_predictions,
)
from .visible_cards import (
    ProviderResult,
    VisibleCardError,
    VisibleCardProposal,
    VisibleCardRequest,
    _elapsed_ms,
)

FINE_FRAME_PROVIDER_NAME = "local-rfdetr-fine-frame"
FINE_FRAME_PROVIDER_VERSION = "local-rfdetr-fine-frame-v2"
FINE_FRAME_SCHEMA = "local-rfdetr-fine-frame/v2"
FINE_FRAME_THRESHOLD = 0.5
CROP_DUPLICATE_IOU_THRESHOLD = DUPLICATE_IOU_THRESHOLD
FINE_FRAME_PROVIDER_MANIFEST = {
    "schema_version": FINE_FRAME_SCHEMA,
    "provider": FINE_FRAME_PROVIDER_NAME,
    "version": FINE_FRAME_PROVIDER_VERSION,
    "model_bundle_schema": "rfdetr-segmentation-bundle/v1",
    "model_class": "RFDETRSegMedium",
    "model_variant": "rfdetr-seg-medium",
    "input_size": [432, 432],
    "class_name": "visible_card",
    "confidence_threshold": FINE_FRAME_THRESHOLD,
    "crop_routing_threshold": FINE_FRAME_THRESHOLD,
    "result_policy": "retain_full_frame_and_add_cluster_predictions",
    "duplicate_rule": "box_iou_and_visible_mask_iou",
    "duplicate_iou_threshold": CROP_DUPLICATE_IOU_THRESHOLD,
}


def _box_from_polygons(polygons: tuple[tuple[PixelPoint, ...], ...]) -> PixelBox:
    points = tuple(point for polygon in polygons for point in polygon)
    return PixelBox(
        min(p.x for p in points),
        min(p.y for p in points),
        max(p.x for p in points),
        max(p.y for p in points),
    )


def _normalized_polygon(polygon: tuple[PixelPoint, ...], *, width: int, height: int):
    return tuple(
        visible_cards.NormalizedPoint(
            x=max(0, min(1000, round(point.x * 1000 / width))),
            y=max(0, min(1000, round(point.y * 1000 / height))),
        )
        for point in polygon
    )


def _normalized_polygon_area(polygon: tuple[Any, ...]) -> int:
    return abs(
        sum(
            left.x * right.y - right.x * left.y
            for left, right in zip(polygon, polygon[1:] + polygon[:1], strict=True)
        )
    )


def _source_frame_mapping(request: VisibleCardRequest) -> dict[str, Any]:
    return {
        "package_id": request.package_id,
        "frame_part_name": request.frame_part_name,
        "target_offset_ms": request.target_offset_ms,
        "image_sha256": request.image_sha256,
        "width": request.width,
        "height": request.height,
    }


def _png_digest(image: Image.Image) -> str:
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return hashlib.sha256(output.getvalue()).hexdigest()


def _prediction_pair_iou(
    left: MappedPrediction,
    right: MappedPrediction,
    *,
    width: int,
    height: int,
) -> tuple[float, float]:
    return (
        _box_iou(left.box, right.box),
        _mask_iou(left, right, width=width, height=height),
    )


class LocalVisibleCardFineFrameProvider:
    """Run one SegMedium model on the frame and add predictions from cluster crops."""

    name = FINE_FRAME_PROVIDER_NAME
    version = FINE_FRAME_PROVIDER_VERSION
    event_concurrency_limit = 1

    def __init__(
        self,
        bundle: str | Path,
        *,
        device: Literal["cpu", "mps", "cuda"] = "mps",
        detector: Any | None = None,
        model_loader: Callable[[Any, str], Any] | None = None,
        torch_module: Any | None = None,
    ) -> None:
        self._segmentation = visible_cards.LocalVisibleCardSegmentationProvider(
            bundle,
            device=device,
            detector=detector,
            model_loader=model_loader,
            torch_module=torch_module,
        )
        self.bundle = self._segmentation.bundle
        self.device = device
        self.input_size = 432
        self.confidence_threshold = FINE_FRAME_THRESHOLD
        self.load_latency_ms = self._segmentation.load_latency_ms
        self._detector = self._segmentation._detector
        self._inference_lock = Lock()

    @property
    def bundle_identity(self) -> dict[str, Any]:
        identity = self._segmentation.bundle_identity
        return {
            "schema_version": identity["schema_version"],
            "bundle_digest": identity["bundle_digest"],
            "checkpoint_sha256": identity["checkpoint_sha256"],
            "model_class": "RFDETRSegMedium",
            "model_variant": "rfdetr-seg-medium",
            "input_size": [self.input_size, self.input_size],
            "class_name": "visible_card",
        }

    def _predict(self, image: Image.Image) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self._inference_lock:
            output = self._detector.predict(
                image,
                # Apply the frozen >= 0.5 rule below. A runtime threshold of zero keeps
                # detections exactly on the boundary available for deterministic filtering.
                threshold=0.0,
                shape=(self.input_size, self.input_size),
                include_source_image=False,
            )
        boxes = visible_cards._normalise_detection_rows(
            visible_cards._detections_field(output, "xyxy"), "xyxy"
        )
        scores = visible_cards._sequence(
            visible_cards._detections_field(output, "confidence"), "confidence"
        )
        class_ids = visible_cards._sequence(
            visible_cards._detections_field(output, "class_id"), "class_id"
        )
        masks = visible_cards._detections_field(output, "mask")
        if masks is None:
            masks = visible_cards._detections_field(output, "masks")
        mask_rows = visible_cards._normalise_mask_rows(masks) if masks is not None else None
        if not (len(boxes) == len(scores) == len(class_ids)):
            raise VisibleCardError("detector output fields have different lengths")
        if mask_rows is not None and len(mask_rows) != len(boxes):
            raise VisibleCardError("detector output mask field has a different length")

        width, height = image.size
        diagnostics: list[dict[str, Any]] = []
        predictions: list[dict[str, Any]] = []
        for index, (coordinates, raw_score, raw_class_id) in enumerate(
            zip(boxes, scores, class_ids, strict=True)
        ):
            record: dict[str, Any] = {"prediction_order": index}
            try:
                score = float(raw_score)
                class_id = int(raw_class_id)
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("confidence must be finite in [0, 1]")
                if class_id not in self._segmentation.accepted_class_ids:
                    raise ValueError(f"unsupported class id: {class_id}")
                if score < self.confidence_threshold:
                    record.update(
                        status="rejected", reason="below_confidence_threshold", score=score
                    )
                    diagnostics.append(record)
                    continue
                if len(coordinates) != 4:
                    raise ValueError("box must contain four coordinates")
                box_values = tuple(float(value) for value in coordinates)
                if not all(math.isfinite(value) for value in box_values):
                    raise ValueError("box coordinates must be finite")
                x0, y0, x1, y1 = box_values
                if x0 < 0 or y0 < 0 or x1 > width or y1 > height or x0 >= x1 or y0 >= y1:
                    raise ValueError("box must be positive and inside the image")
                mask_diagnostics: dict[str, Any] = {}
                if mask_rows is None:
                    polygons = (
                        (
                            PixelPoint(x0, y0),
                            PixelPoint(x1, y0),
                            PixelPoint(x1, y1),
                            PixelPoint(x0, y1),
                        ),
                    )
                    geometry_source = "detector_box"
                else:
                    normalized_polygon, mask_diagnostics = (
                        visible_cards._normalised_polygon_from_mask(
                            mask_rows[index], width=width, height=height
                        )
                    )
                    if normalized_polygon is None:
                        raise ValueError("visible mask is empty")
                    polygons = (
                        tuple(
                            PixelPoint(point.x * width / 1000, point.y * height / 1000)
                            for point in normalized_polygon
                        ),
                    )
                    geometry_source = "segmentation_mask"
                box = _box_from_polygons(polygons)
                record.update(
                    status="ok",
                    score=score,
                    class_id=class_id,
                    box=box.to_mapping(),
                    geometry_source=geometry_source,
                    **mask_diagnostics,
                )
                diagnostics.append(record)
                predictions.append(
                    {"prediction_order": index, "score": score, "box": box, "polygons": polygons}
                )
            except (TypeError, ValueError, OverflowError, VisibleCardError) as error:
                record.update(status="rejected", reason="invalid_geometry", error=str(error))
                diagnostics.append(record)
        return diagnostics, predictions

    @staticmethod
    def _map_predictions(
        predictions: list[dict[str, Any]], *, origin: str, cluster: Any | None = None
    ) -> tuple[MappedPrediction, ...]:
        mapped: list[MappedPrediction] = []
        cluster_id = cluster.cluster_id if cluster is not None else "full_frame"
        for record in predictions:
            polygons = record["polygons"]
            if cluster is not None:
                polygons = tuple(
                    tuple(cluster.transform.crop_to_source(point) for point in polygon)
                    for polygon in polygons
                )
            box = _box_from_polygons(polygons)
            mapped.append(
                MappedPrediction(
                    prediction_id=f"{origin}-{cluster_id}-prediction-{record['prediction_order']:04d}",
                    cluster_id=cluster_id,
                    proposal_order=record["prediction_order"],
                    score=record["score"],
                    box=box,
                    polygons=polygons,
                )
            )
        return tuple(mapped)

    def propose(self, request: VisibleCardRequest) -> ProviderResult:
        if request.provider != self.name:
            raise VisibleCardError(
                f"request provider {request.provider!r} does not match {self.name!r}."
            )
        started = time.monotonic()
        raw: dict[str, Any] = {
            "schema_version": FINE_FRAME_SCHEMA,
            "provider": self.name,
            "version": self.version,
            "device": self.device,
            "source_frame": _source_frame_mapping(request),
            "bundle_identity": self.bundle_identity,
            "provider_manifest": FINE_FRAME_PROVIDER_MANIFEST,
            "confidence_threshold": self.confidence_threshold,
            "crop_routing_threshold": self.confidence_threshold,
            "crop_duplicate_iou_threshold": CROP_DUPLICATE_IOU_THRESHOLD,
            "load_latency_ms": self.load_latency_ms,
        }

        def unavailable(message: str) -> ProviderResult:
            raw["timing"] = {
                "load_latency_ms": self.load_latency_ms,
                "total_latency_ms": _elapsed_ms(started),
            }
            raw.setdefault("full_frame", {"status": "not_run"})
            raw.setdefault("clusters", {"status": "not_run", "layout": None})
            raw.setdefault("refinement", {"status": "not_run", "clusters": []})
            raw.setdefault("arbitration", {"status": "not_run"})
            raw.setdefault("mapping", {"predictions": []})
            raw.setdefault("reconciliation", {"status": "not_run"})
            return ProviderResult(
                status="unavailable",
                raw_response=raw,
                latency_ms=_elapsed_ms(started),
                error=message,
            )

        try:
            with Image.open(BytesIO(request.image_bytes)) as source:
                if source.size != (request.width, request.height):
                    raise VisibleCardError(
                        "decoded source image dimensions do not match the request dimensions"
                    )
                source_image = source.convert("RGB").copy()
        except (UnidentifiedImageError, OSError, ValueError, VisibleCardError) as error:
            return unavailable(f"fine-frame input could not be decoded: {error}")

        inference_started = time.monotonic()
        try:
            diagnostics, records = self._predict(source_image)
            full_frame_inference_ms = _elapsed_ms(inference_started)
            full_frame_predictions = self._map_predictions(records, origin="full_frame")
            layout_started = time.monotonic()
            layout = build_cluster_layout(
                tuple(
                    ClusterProposal(
                        proposal_id=prediction.prediction_id,
                        box=prediction.box,
                        score=prediction.score,
                    )
                    for prediction in full_frame_predictions
                ),
                frame_width=request.width,
                frame_height=request.height,
                confidence_threshold=self.confidence_threshold,
                model_input_size=self.input_size,
            )
            layout_latency_ms = _elapsed_ms(layout_started)
        except Exception as error:
            raw["full_frame"] = {
                "status": "unavailable",
                "error": str(error),
                "latency_ms": _elapsed_ms(inference_started),
            }
            return unavailable(f"fine full-frame inference failed: {error}")

        raw["full_frame"] = {
            "status": "ok",
            "latency_ms": full_frame_inference_ms,
            "threshold": self.confidence_threshold,
            "detections": diagnostics,
            "predictions": [item.to_mapping() for item in full_frame_predictions],
        }
        raw["clusters"] = {
            "status": "ok" if layout.clusters else "empty",
            "layout": layout.to_mapping(),
            "layout_latency_ms": layout_latency_ms,
            "full_frame_attribution": [
                {
                    "cluster_id": cluster.cluster_id,
                    "full_frame_prediction_ids": list(cluster.proposal_ids),
                }
                for cluster in layout.clusters
            ],
        }

        crop_predictions: list[MappedPrediction] = []
        refinement_records: list[dict[str, Any]] = []
        crop_started = time.monotonic()
        for cluster in layout.clusters:
            started_crop = time.monotonic()
            crop_digest: str | None = None
            try:
                crop_image = crop_source_image(source_image, cluster)
                crop_digest = _png_digest(crop_image)
                crop_diagnostics, crop_records = self._predict(crop_image)
                mapped = self._map_predictions(crop_records, origin="cluster_crop", cluster=cluster)
                in_frame: list[MappedPrediction] = []
                rejected: list[dict[str, Any]] = []
                for prediction in mapped:
                    valid = all(
                        0 <= point.x <= request.width and 0 <= point.y <= request.height
                        for polygon in prediction.polygons
                        for point in polygon
                    )
                    if valid:
                        in_frame.append(prediction)
                    else:
                        rejected.append(
                            {
                                "prediction_id": prediction.prediction_id,
                                "reason": "mapped_geometry_outside_source_frame",
                            }
                        )
                crop_predictions.extend(in_frame)
                refinement_records.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "status": "ok",
                        "crop": cluster.to_mapping(),
                        "crop_image_sha256": crop_digest,
                        "latency_ms": _elapsed_ms(started_crop),
                        "threshold": self.confidence_threshold,
                        "detections": crop_diagnostics,
                        "predictions": [item.to_mapping() for item in in_frame],
                        "rejected_predictions": rejected,
                    }
                )
            except Exception as error:
                refinement_records.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "status": "unavailable",
                        "crop": cluster.to_mapping(),
                        "crop_image_sha256": crop_digest,
                        "latency_ms": _elapsed_ms(started_crop),
                        "error": str(error),
                    }
                )

        raw["refinement"] = {
            "status": (
                "not_run"
                if not layout.clusters
                else (
                    "partial"
                    if any(item["status"] != "ok" for item in refinement_records)
                    else "ok"
                )
            ),
            "latency_ms": _elapsed_ms(crop_started) if layout.clusters else 0.0,
            "clusters": refinement_records,
        }

        crop_reconciliation = reconcile_predictions(
            crop_predictions,
            frame_width=request.width,
            frame_height=request.height,
            iou_threshold=CROP_DUPLICATE_IOU_THRESHOLD,
            allow_containment_duplicates=False,
            preserve_input_order=True,
        )
        accepted_crops: list[MappedPrediction] = []
        discarded: list[dict[str, Any]] = [
            {
                "prediction": item.to_mapping(),
                "reason": "duplicate_cluster_crop_prediction",
                "duplicate_of": next(
                    (
                        decision.kept_prediction_id
                        for decision in crop_reconciliation.decisions
                        if decision.discarded_prediction_id == item.prediction_id
                    ),
                    None,
                ),
            }
            for item in crop_reconciliation.discarded
        ]
        cross_source_decisions: list[dict[str, Any]] = []
        for crop_prediction in crop_reconciliation.retained:
            duplicate_of = None
            for full_prediction in full_frame_predictions:
                box_iou, mask_iou = _prediction_pair_iou(
                    full_prediction,
                    crop_prediction,
                    width=request.width,
                    height=request.height,
                )
                duplicate = (
                    box_iou >= CROP_DUPLICATE_IOU_THRESHOLD
                    and mask_iou >= CROP_DUPLICATE_IOU_THRESHOLD
                )
                cross_source_decisions.append(
                    {
                        "full_frame_prediction_id": full_prediction.prediction_id,
                        "crop_prediction_id": crop_prediction.prediction_id,
                        "box_iou": box_iou,
                        "visible_mask_iou": mask_iou,
                        "duplicate": duplicate,
                    }
                )
                if duplicate:
                    duplicate_of = full_prediction.prediction_id
                    break
            if duplicate_of is None:
                accepted_crops.append(crop_prediction)
            else:
                discarded.append(
                    {
                        "prediction": crop_prediction.to_mapping(),
                        "reason": "duplicate_of_full_frame_prediction",
                        "duplicate_of": duplicate_of,
                    }
                )

        predictions = tuple(full_frame_predictions) + tuple(accepted_crops)
        raw["arbitration"] = {
            "policy": "retain_all_full_frame_predictions_and_add_nonduplicate_crop_predictions",
            "full_frame_predictions_retained": len(full_frame_predictions),
            "crop_predictions_before_reconciliation": len(crop_predictions),
            "crop_predictions_added": len(accepted_crops),
            "full_frame_predictions_removed": 0,
            "crop_duplicate_decisions": cross_source_decisions,
        }
        raw["mapping"] = {"predictions": [item.to_mapping() for item in predictions]}
        raw["reconciliation"] = {
            "schema_version": crop_reconciliation.to_mapping()["schema_version"],
            "status": "applied" if layout.clusters else "not_needed",
            "policy": "strict_iou_only; full_frame_predictions_are_immutable",
            "duplicate_iou_threshold": CROP_DUPLICATE_IOU_THRESHOLD,
            "retained_prediction_ids": [item.prediction_id for item in predictions],
            "discarded_prediction_ids": [item["prediction"]["prediction_id"] for item in discarded],
            "decisions": [
                *[decision.to_mapping() for decision in crop_reconciliation.decisions],
                *cross_source_decisions,
            ],
            "retained": [item.to_mapping() for item in predictions],
            "discarded": discarded,
        }
        return self._result(
            request,
            started,
            raw,
            predictions,
            full_frame_predictions,
            layout.clusters,
        )

    def _result(
        self,
        request: VisibleCardRequest,
        started: float,
        raw: dict[str, Any],
        predictions: tuple[MappedPrediction, ...],
        full_frame_predictions: tuple[MappedPrediction, ...],
        clusters: tuple[Any, ...],
    ) -> ProviderResult:
        proposals: list[VisibleCardProposal] = []
        for prediction in predictions:
            polygons = tuple(
                normalized
                for normalized in (
                    _normalized_polygon(polygon, width=request.width, height=request.height)
                    for polygon in prediction.polygons
                )
                if _normalized_polygon_area(normalized) > 0
            )
            if not polygons:
                continue
            proposals.append(
                VisibleCardProposal(
                    box_2d=visible_cards._tight_box_for_polygon(
                        tuple(point for polygon in polygons for point in polygon)
                    ),
                    polygon=polygons[0],
                    side="unknown",
                    label="visible_card",
                    polygons=polygons,
                )
            )
        raw["final_provenance"] = [
            {
                "prediction_id": p.prediction_id,
                "source": (
                    "full_frame"
                    if p.prediction_id in {item.prediction_id for item in full_frame_predictions}
                    else "cluster_crop"
                ),
                "cluster_id": p.cluster_id,
                "source_transform": {
                    "kind": "source_frame",
                    "width": request.width,
                    "height": request.height,
                }
                if p.cluster_id == "full_frame"
                else next(
                    cluster.transform.to_mapping()
                    for cluster in clusters
                    if cluster.cluster_id == p.cluster_id
                ),
            }
            for p in predictions
        ]
        raw["timing"] = {
            "load_latency_ms": self.load_latency_ms,
            "inference_latency_ms": raw["full_frame"].get("latency_ms", 0.0),
            "cluster_layout_latency_ms": raw["clusters"].get("layout_latency_ms", 0.0),
            "crop_latency_ms": raw["refinement"].get("latency_ms", 0.0),
            "total_latency_ms": _elapsed_ms(started),
        }
        return ProviderResult(
            status="ok",
            proposals=tuple(proposals),
            raw_response=raw,
            latency_ms=_elapsed_ms(started),
        )


__all__ = [
    "FINE_FRAME_PROVIDER_NAME",
    "FINE_FRAME_PROVIDER_VERSION",
    "LocalVisibleCardFineFrameProvider",
]
