"""Fine-model full-frame prepass with optional cluster-crop refinement."""

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
    VISIBLE_CARD_MODEL_INPUT_SIZE,
    ClusterProposal,
    MappedPrediction,
    PixelBox,
    PixelPoint,
    _polygon_mask,
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

FINE_PREPASS_PROVIDER_NAME = "local-rfdetr-fine-prepass"
FINE_PREPASS_PROVIDER_VERSION = "local-rfdetr-fine-prepass-v1"
FINE_PREPASS_SCHEMA = "local-rfdetr-fine-prepass/v1"
FINE_PREPASS_THRESHOLD = 0.5
CROP_COVERAGE_THRESHOLD = 0.75
FINE_PREPASS_PROVIDER_MANIFEST = {
    "schema_version": FINE_PREPASS_SCHEMA,
    "provider": FINE_PREPASS_PROVIDER_NAME,
    "version": FINE_PREPASS_PROVIDER_VERSION,
    "model_bundle_schema": "rfdetr-segmentation-bundle/v1",
    "model_class": "RFDETRSegMedium",
    "model_variant": "rfdetr-seg-medium",
    "input_size": [VISIBLE_CARD_MODEL_INPUT_SIZE, VISIBLE_CARD_MODEL_INPUT_SIZE],
    "class_name": "visible_card",
    "prepass_threshold": FINE_PREPASS_THRESHOLD,
    "crop_routing_threshold": FINE_PREPASS_THRESHOLD,
    "crop_coverage_threshold": CROP_COVERAGE_THRESHOLD,
    "duplicate_thresholds": {
        "box_iou": 0.90,
        "mask_iou": 0.90,
        "mask_containment": 0.75,
        "box_containment": 0.75,
        "smaller_to_larger_box_area_max": 0.95,
    },
}


def _finite_point(value: Any, field: str) -> PixelPoint:
    coordinates = visible_cards._sequence(value, field)
    if len(coordinates) != 2:
        raise VisibleCardError(f"{field} must contain x and y")
    try:
        x, y = (float(coordinate) for coordinate in coordinates)
    except (TypeError, ValueError) as error:
        raise VisibleCardError(f"{field} must contain numeric coordinates") from error
    if not math.isfinite(x) or not math.isfinite(y):
        raise VisibleCardError(f"{field} must contain finite coordinates")
    return PixelPoint(x, y)


def _polygon_area(polygon: tuple[PixelPoint, ...]) -> float:
    return abs(
        sum(
            left.x * right.y - right.x * left.y
            for left, right in zip(polygon, polygon[1:] + polygon[:1], strict=True)
        )
        / 2.0
    )


def _mask_polygons(mask: Any, *, width: int, height: int) -> tuple[tuple[PixelPoint, ...], ...]:
    raw = visible_cards._sequence(visible_cards._mask_to_polygons(mask), "mask polygons")
    polygons: list[tuple[PixelPoint, ...]] = []
    for index, raw_polygon in enumerate(raw):
        polygon = tuple(
            _finite_point(point, f"mask polygon {index} point")
            for point in visible_cards._sequence(raw_polygon, "mask polygon")
        )
        if len(polygon) < 3 or _polygon_area(polygon) <= 0:
            continue
        if any(
            point.x < 0 or point.y < 0 or point.x > width or point.y > height for point in polygon
        ):
            raise VisibleCardError("detector output mask polygon points must fit the image")
        polygons.append(polygon)
    return tuple(polygons)


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


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def _source_frame_mapping(request: VisibleCardRequest) -> dict[str, Any]:
    return {
        "package_id": request.package_id,
        "frame_part_name": request.frame_part_name,
        "target_offset_ms": request.target_offset_ms,
        "image_sha256": request.image_sha256,
        "width": request.width,
        "height": request.height,
    }


def _prediction_mask(
    prediction: MappedPrediction, *, width: int, height: int
) -> frozenset[tuple[int, int]]:
    if prediction.mask is not None:
        return prediction.mask
    return _polygon_mask(prediction, width=width, height=height)


class LocalVisibleCardFinePrepassProvider:
    """Run one SegMedium model on the source frame and its derived cluster crops."""

    name = FINE_PREPASS_PROVIDER_NAME
    version = FINE_PREPASS_PROVIDER_VERSION
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
        self.input_size = VISIBLE_CARD_MODEL_INPUT_SIZE
        self.confidence_threshold = FINE_PREPASS_THRESHOLD
        self.crop_routing_threshold = FINE_PREPASS_THRESHOLD
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
                    polygons = _mask_polygons(mask_rows[index], width=width, height=height)
                    if not polygons:
                        raise ValueError("visible mask is empty")
                    geometry_source = "segmentation_mask"
                box = _box_from_polygons(polygons)
                record.update(
                    status="ok",
                    score=score,
                    class_id=class_id,
                    box=box.to_mapping(),
                    geometry_source=geometry_source,
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
        predictions: list[dict[str, Any]], *, cluster: Any | None, origin: str
    ) -> tuple[MappedPrediction, ...]:
        mapped: list[MappedPrediction] = []
        cluster_id = cluster.cluster_id if cluster is not None else "prepass"
        for record in predictions:
            if cluster is None:
                polygons = record["polygons"]
            else:
                polygons = tuple(
                    tuple(cluster.transform.crop_to_source(point) for point in polygon)
                    for polygon in record["polygons"]
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
            "schema_version": FINE_PREPASS_SCHEMA,
            "provider": self.name,
            "version": self.version,
            "device": self.device,
            "source_frame": _source_frame_mapping(request),
            "bundle_identity": self.bundle_identity,
            "provider_manifest": FINE_PREPASS_PROVIDER_MANIFEST,
            "prepass_threshold": self.confidence_threshold,
            "crop_routing_threshold": self.crop_routing_threshold,
            "crop_coverage_threshold": CROP_COVERAGE_THRESHOLD,
            "duplicate_thresholds": {
                "box_iou": 0.90,
                "mask_iou": 0.90,
                "mask_containment": 0.75,
                "box_containment": 0.75,
                "smaller_to_larger_box_area_max": 0.95,
            },
            "load_latency_ms": self.load_latency_ms,
        }

        def unavailable(message: str) -> ProviderResult:
            raw["timing"] = {
                "load_latency_ms": self.load_latency_ms,
                "total_latency_ms": _elapsed_ms(started),
            }
            raw.setdefault("prepass", {"status": "not_run"})
            raw.setdefault("clusters", {"status": "not_run"})
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
            return unavailable(f"fine-prepass input could not be decoded: {error}")

        prepass_started = time.monotonic()
        try:
            prepass_diagnostics, prepass_records = self._predict(source_image)
            prepass_predictions = self._map_predictions(
                prepass_records, cluster=None, origin="prepass"
            )
            layout = build_cluster_layout(
                tuple(
                    # The generic layout contract consumes confidence-qualified boxes.
                    ClusterProposal(
                        proposal_id=prediction.prediction_id,
                        box=prediction.box,
                        score=prediction.score,
                    )
                    for prediction in prepass_predictions
                ),
                frame_width=request.width,
                frame_height=request.height,
                confidence_threshold=self.crop_routing_threshold,
                model_input_size=self.input_size,
            )
        except Exception as error:
            raw["prepass"] = {
                "status": "unavailable",
                "error": str(error),
                "latency_ms": _elapsed_ms(prepass_started),
            }
            return unavailable(f"fine full-frame prepass failed: {error}")

        raw["prepass"] = {
            "status": "ok",
            "latency_ms": _elapsed_ms(prepass_started),
            "threshold": self.confidence_threshold,
            "detections": prepass_diagnostics,
            "predictions": [item.to_mapping() for item in prepass_predictions],
        }
        layout_mapping = layout.to_mapping()
        layout_mapping["routing_threshold"] = layout_mapping.pop("confidence_threshold")
        raw["clusters"] = {
            "status": "ok" if layout.clusters else "empty",
            "layout": layout_mapping,
            "cluster_prepass_attribution": [
                {"cluster_id": crop.cluster_id, "prepass_prediction_ids": list(crop.proposal_ids)}
                for crop in layout.clusters
            ],
        }
        if not layout.clusters:
            raw["refinement"] = {"status": "not_run", "clusters": []}
            raw["arbitration"] = {"status": "not_needed", "prepass_decisions": []}
            reconciliation = reconcile_predictions(
                prepass_predictions, frame_width=request.width, frame_height=request.height
            )
            return self._result(request, started, raw, (), (), reconciliation)

        refinement_started = time.monotonic()
        crop_predictions: list[MappedPrediction] = []
        refinement_records: list[dict[str, Any]] = []
        for cluster in layout.clusters:
            crop_image = crop_source_image(source_image, cluster)
            crop_digest = hashlib.sha256(_png_bytes(crop_image)).hexdigest()
            try:
                diagnostics, records = self._predict(crop_image)
                mapped = self._map_predictions(records, cluster=cluster, origin="crop")
                # Reject crop masks that use padding. Source coordinates are the final contract.
                valid: list[MappedPrediction] = []
                for prediction in mapped:
                    if any(
                        point.x < 0
                        or point.y < 0
                        or point.x > request.width
                        or point.y > request.height
                        for polygon in prediction.polygons
                        for point in polygon
                    ):
                        continue
                    valid.append(prediction)
                crop_predictions.extend(valid)
                refinement_records.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "status": "ok",
                        "crop": cluster.to_mapping(),
                        "crop_image_sha256": crop_digest,
                        "threshold": self.confidence_threshold,
                        "detections": diagnostics,
                        "predictions": [prediction.to_mapping() for prediction in valid],
                    }
                )
            except Exception as error:
                refinement_records.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "status": "unavailable",
                        "crop": cluster.to_mapping(),
                        "crop_image_sha256": crop_digest,
                        "error": str(error),
                    }
                )
        raw["refinement"] = {
            "status": "partial" if any(x["status"] != "ok" for x in refinement_records) else "ok",
            "latency_ms": _elapsed_ms(refinement_started),
            "clusters": refinement_records,
        }

        crop_by_cluster: dict[str, list[MappedPrediction]] = {}
        for item in crop_predictions:
            crop_by_cluster.setdefault(item.cluster_id, []).append(item)
        cluster_for_prediction = {
            prediction_id: crop.cluster_id
            for crop in layout.clusters
            for prediction_id in crop.proposal_ids
        }
        retained_prepass: list[MappedPrediction] = []
        arbitration: list[dict[str, Any]] = []
        for candidate in prepass_predictions:
            cluster_id = cluster_for_prediction[candidate.prediction_id]
            crops = crop_by_cluster.get(cluster_id, [])
            candidate_mask = _prediction_mask(candidate, width=request.width, height=request.height)
            crop_mask: set[tuple[int, int]] = set()
            for crop_prediction in crops:
                crop_mask.update(
                    _prediction_mask(crop_prediction, width=request.width, height=request.height)
                )
            coverage = (
                len(candidate_mask & crop_mask) / len(candidate_mask) if candidate_mask else 0.0
            )
            superseded = bool(crops) and coverage >= CROP_COVERAGE_THRESHOLD
            arbitration.append(
                {
                    "prepass_prediction_id": candidate.prediction_id,
                    "cluster_id": cluster_id,
                    "mapped_crop_prediction_ids": [p.prediction_id for p in crops],
                    "crop_mask_coverage": coverage,
                    "superseded": superseded,
                    "reason": "crop_coverage" if superseded else "retain_prepass",
                }
            )
            if not superseded:
                retained_prepass.append(candidate)

        combined = tuple(crop_predictions + retained_prepass)
        reconciliation = reconcile_predictions(
            combined, frame_width=request.width, frame_height=request.height
        )
        raw["arbitration"] = {
            "prepass_decisions": arbitration,
            "crop_prediction_count": len(crop_predictions),
            "retained_prepass_count": len(retained_prepass),
        }
        raw["mapping"] = {"predictions": [item.to_mapping() for item in combined]}
        return self._result(
            request,
            started,
            raw,
            layout.clusters,
            tuple(crop_predictions),
            reconciliation,
        )

    def _result(
        self,
        request: VisibleCardRequest,
        started: float,
        raw: dict[str, Any],
        clusters: Any,
        crop_predictions: tuple[MappedPrediction, ...],
        reconciliation: Any,
    ) -> ProviderResult:
        proposals: list[VisibleCardProposal] = []
        for prediction in reconciliation.retained:
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
        raw["reconciliation"] = {
            **reconciliation.to_mapping(),
            "retained": [p.to_mapping() for p in reconciliation.retained],
            "discarded": [p.to_mapping() for p in reconciliation.discarded],
        }
        raw.setdefault(
            "mapping",
            {
                "predictions": [
                    prediction.to_mapping()
                    for prediction in reconciliation.retained + reconciliation.discarded
                ]
            },
        )
        crop_ids = {p.prediction_id for p in crop_predictions}
        raw["final_provenance"] = [
            {
                "prediction_id": p.prediction_id,
                "source": "crop" if p.prediction_id in crop_ids else "prepass",
                "cluster_id": p.cluster_id,
                "source_transform": next(
                    (c.transform.to_mapping() for c in clusters if c.cluster_id == p.cluster_id),
                    {"kind": "source_frame", "width": request.width, "height": request.height},
                ),
            }
            for p in reconciliation.retained
        ]
        raw["timing"] = {
            "load_latency_ms": self.load_latency_ms,
            "prepass_latency_ms": raw["prepass"].get("latency_ms", 0.0),
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
    "FINE_PREPASS_PROVIDER_NAME",
    "FINE_PREPASS_PROVIDER_VERSION",
    "LocalVisibleCardFinePrepassProvider",
]
