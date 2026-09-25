"""Single-pass full-frame visible-card segmentation with RF-DETR SegMedium."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError

from . import visible_cards
from .visible_card_cluster_geometry import (
    MappedPrediction,
    PixelBox,
    PixelPoint,
)
from .visible_cards import (
    ProviderResult,
    VisibleCardError,
    VisibleCardProposal,
    VisibleCardRequest,
    _elapsed_ms,
)

FINE_FRAME_PROVIDER_NAME = "local-rfdetr-fine-frame"
FINE_FRAME_PROVIDER_VERSION = "local-rfdetr-fine-frame-v1"
FINE_FRAME_SCHEMA = "local-rfdetr-fine-frame/v1"
FINE_FRAME_THRESHOLD = 0.5
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


class LocalVisibleCardFineFrameProvider:
    """Run one SegMedium model on the complete source frame."""

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
        predictions: list[dict[str, Any]], *, origin: str
    ) -> tuple[MappedPrediction, ...]:
        mapped: list[MappedPrediction] = []
        cluster_id = "full_frame"
        for record in predictions:
            polygons = record["polygons"]
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
            "load_latency_ms": self.load_latency_ms,
        }

        def unavailable(message: str) -> ProviderResult:
            raw["timing"] = {
                "load_latency_ms": self.load_latency_ms,
                "total_latency_ms": _elapsed_ms(started),
            }
            raw.setdefault("full_frame", {"status": "not_run"})
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
            predictions = self._map_predictions(records, origin="full_frame")
        except Exception as error:
            raw["full_frame"] = {
                "status": "unavailable",
                "error": str(error),
                "latency_ms": _elapsed_ms(inference_started),
            }
            return unavailable(f"fine full-frame inference failed: {error}")

        raw["full_frame"] = {
            "status": "ok",
            "latency_ms": _elapsed_ms(inference_started),
            "threshold": self.confidence_threshold,
            "detections": diagnostics,
            "predictions": [item.to_mapping() for item in predictions],
        }
        raw["mapping"] = {"predictions": [item.to_mapping() for item in predictions]}
        return self._result(request, started, raw, predictions)

    def _result(
        self,
        request: VisibleCardRequest,
        started: float,
        raw: dict[str, Any],
        predictions: tuple[MappedPrediction, ...],
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
        raw["reconciliation"] = {
            "status": "not_applied",
            "reason": "preserve distinct full-frame predictions",
            "retained": [prediction.to_mapping() for prediction in predictions],
            "discarded": [],
        }
        raw["final_provenance"] = [
            {
                "prediction_id": p.prediction_id,
                "source": "full_frame",
                "cluster_id": p.cluster_id,
                "source_transform": {
                    "kind": "source_frame",
                    "width": request.width,
                    "height": request.height,
                },
            }
            for p in predictions
        ]
        raw["timing"] = {
            "load_latency_ms": self.load_latency_ms,
            "inference_latency_ms": raw["full_frame"].get("latency_ms", 0.0),
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
