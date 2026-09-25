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
FINE_FRAME_PROVIDER_VERSION = "local-rfdetr-fine-frame-v6"
FINE_FRAME_SCHEMA = "local-rfdetr-fine-frame/v6"
FINE_FRAME_THRESHOLD = 0.5
CROP_DUPLICATE_IOU_THRESHOLD = DUPLICATE_IOU_THRESHOLD
SMALL_CARD_CLUSTER_MAX_SIZE_FRACTION = 1 / 8
FAR_CLUSTER_MIN_CROP_SCALE_GAIN = 1.5
REFINEMENT_MIN_BOX_IOU = 0.5
REFINEMENT_MIN_MASK_IOU = 0.5
REFINEMENT_MATCH_AMBIGUITY_MARGIN = 0.1
REFINEMENT_MIN_SCORE_GAIN = 0.05
CROP_ADDITION_MIN_SCORE = 0.7
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
    "result_policy": "full_frame_main_with_far_cluster_refinement",
    "far_cluster_routing": {
        "card_size_metric": "longer_visible_box_side",
        "max_card_size_fraction_of_model_input": SMALL_CARD_CLUSTER_MAX_SIZE_FRACTION,
        "max_card_size_model_input_px": 432 * SMALL_CARD_CLUSTER_MAX_SIZE_FRACTION,
        "min_crop_scale_gain": FAR_CLUSTER_MIN_CROP_SCALE_GAIN,
    },
    "refinement_match": {
        "minimum_box_iou": REFINEMENT_MIN_BOX_IOU,
        "minimum_visible_mask_iou": REFINEMENT_MIN_MASK_IOU,
        "ambiguity_margin": REFINEMENT_MATCH_AMBIGUITY_MARGIN,
        "minimum_score_gain": REFINEMENT_MIN_SCORE_GAIN,
    },
    "new_crop_candidate_minimum_score": CROP_ADDITION_MIN_SCORE,
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


def _far_cluster_metrics(
    cluster: Any,
    predictions_by_id: dict[str, MappedPrediction],
    *,
    frame_width: int,
    frame_height: int,
    model_input_size: int,
) -> dict[str, Any]:
    frame_long_edge = max(frame_width, frame_height)
    model_scale = model_input_size / frame_long_edge
    member_sizes = [
        {
            "prediction_id": prediction_id,
            "visible_card_size_model_px": max(
                predictions_by_id[prediction_id].box.width,
                predictions_by_id[prediction_id].box.height,
            )
            * model_scale,
        }
        for prediction_id in cluster.proposal_ids
        if prediction_id in predictions_by_id
    ]
    minimum_card_size = min(
        (item["visible_card_size_model_px"] for item in member_sizes),
        default=0.0,
    )
    maximum_card_size = model_input_size * SMALL_CARD_CLUSTER_MAX_SIZE_FRACTION
    crop_scale_gain = frame_long_edge / cluster.crop_width
    far = (
        bool(member_sizes)
        and minimum_card_size <= maximum_card_size
        and crop_scale_gain >= FAR_CLUSTER_MIN_CROP_SCALE_GAIN
    )
    return {
        "card_size_metric": "longer_visible_box_side",
        "member_card_sizes_model_px": member_sizes,
        "minimum_card_size_model_px": minimum_card_size,
        "maximum_card_size_model_px": maximum_card_size,
        "maximum_card_size_fraction_of_model_input": SMALL_CARD_CLUSTER_MAX_SIZE_FRACTION,
        "crop_scale_gain": crop_scale_gain,
        "route": far,
        "reason": (
            "small_predicted_card_with_useful_crop_upscale"
            if far
            else "no_small_card_or_insufficient_crop_upscale"
        ),
    }


class LocalVisibleCardFineFrameProvider:
    """Use full-frame results as the base and refine far clusters with the same model."""

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
            "far_cluster_routing": FINE_FRAME_PROVIDER_MANIFEST["far_cluster_routing"],
            "refinement_match": FINE_FRAME_PROVIDER_MANIFEST["refinement_match"],
            "new_crop_candidate_minimum_score": CROP_ADDITION_MIN_SCORE,
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
        full_frame_by_id = {item.prediction_id: item for item in full_frame_predictions}
        cluster_routing = {
            cluster.cluster_id: _far_cluster_metrics(
                cluster,
                full_frame_by_id,
                frame_width=request.width,
                frame_height=request.height,
                model_input_size=self.input_size,
            )
            for cluster in layout.clusters
        }
        routed_clusters = tuple(
            cluster for cluster in layout.clusters if cluster_routing[cluster.cluster_id]["route"]
        )
        raw["clusters"] = {
            "status": "ok" if layout.clusters else "empty",
            "layout": layout.to_mapping(),
            "layout_latency_ms": layout_latency_ms,
            "routing": [
                {"cluster_id": cluster_id, **metrics}
                for cluster_id, metrics in cluster_routing.items()
            ],
            "routed_cluster_ids": [cluster.cluster_id for cluster in routed_clusters],
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
        routed_cluster_ids = {cluster.cluster_id for cluster in routed_clusters}
        for cluster in layout.clusters:
            if cluster.cluster_id not in routed_cluster_ids:
                refinement_records.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "status": "skipped",
                        "reason": cluster_routing[cluster.cluster_id]["reason"],
                        "routing": cluster_routing[cluster.cluster_id],
                        "crop": cluster.to_mapping(),
                        "latency_ms": 0.0,
                    }
                )
                continue
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
                    "not_run"
                    if not routed_clusters
                    else (
                        "partial"
                        if any(item["status"] == "unavailable" for item in refinement_records)
                        else "ok"
                    )
                )
            ),
            "latency_ms": _elapsed_ms(crop_started) if routed_clusters else 0.0,
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
        candidate_matches: list[dict[str, Any]] = []
        match_diagnostics: list[dict[str, Any]] = []
        for crop_prediction in crop_reconciliation.retained:
            cluster = next(
                (item for item in routed_clusters if item.cluster_id == crop_prediction.cluster_id),
                None,
            )
            if cluster is None:
                continue
            for prediction_id in cluster.proposal_ids:
                full_prediction = full_frame_by_id[prediction_id]
                box_iou, mask_iou = _prediction_pair_iou(
                    full_prediction,
                    crop_prediction,
                    width=request.width,
                    height=request.height,
                )
                if box_iou >= REFINEMENT_MIN_BOX_IOU and mask_iou >= REFINEMENT_MIN_MASK_IOU:
                    candidate_matches.append(
                        {
                            "full_frame": full_prediction,
                            "crop": crop_prediction,
                            "cluster_id": cluster.cluster_id,
                            "box_iou": box_iou,
                            "mask_iou": mask_iou,
                            "similarity": min(box_iou, mask_iou),
                        }
                    )

        def unique_best(options: list[dict[str, Any]], other_key: str) -> dict[str, Any] | None:
            ordered = sorted(
                options,
                key=lambda item: (
                    -item["similarity"],
                    item[other_key].proposal_order,
                    item[other_key].prediction_id,
                ),
            )
            if len(ordered) > 1 and (
                ordered[0]["similarity"] - ordered[1]["similarity"]
                < REFINEMENT_MATCH_AMBIGUITY_MARGIN
            ):
                return None
            return ordered[0] if ordered else None

        best_for_full = {
            prediction.prediction_id: unique_best(
                [
                    pair
                    for pair in candidate_matches
                    if pair["full_frame"].prediction_id == prediction.prediction_id
                ],
                "crop",
            )
            for prediction in full_frame_predictions
        }
        best_for_crop = {
            prediction.prediction_id: unique_best(
                [
                    pair
                    for pair in candidate_matches
                    if pair["crop"].prediction_id == prediction.prediction_id
                ],
                "full_frame",
            )
            for prediction in crop_reconciliation.retained
        }
        matched_full: dict[str, tuple[MappedPrediction, float, float]] = {}
        matched_crop_ids: set[str] = set()
        for pair in candidate_matches:
            full_prediction = pair["full_frame"]
            crop_prediction = pair["crop"]
            if (
                best_for_full[full_prediction.prediction_id] is not pair
                or best_for_crop[crop_prediction.prediction_id] is not pair
            ):
                continue
            matched_full[full_prediction.prediction_id] = (
                crop_prediction,
                pair["box_iou"],
                pair["mask_iou"],
            )
            matched_crop_ids.add(crop_prediction.prediction_id)

        rejected_match_candidates = [
            {
                "full_frame_prediction_id": pair["full_frame"].prediction_id,
                "crop_prediction_id": pair["crop"].prediction_id,
                "cluster_id": pair["cluster_id"],
                "box_iou": pair["box_iou"],
                "visible_mask_iou": pair["mask_iou"],
                "decision": "ambiguous_or_not_mutual_best",
            }
            for pair in candidate_matches
            if pair["crop"].prediction_id not in matched_crop_ids
            or pair["full_frame"].prediction_id not in matched_full
        ]

        refined_by_id: dict[str, MappedPrediction] = {}
        final_provenance: dict[str, dict[str, Any]] = {}
        for full_prediction in full_frame_predictions:
            final_provenance[full_prediction.prediction_id] = {
                "prediction_id": full_prediction.prediction_id,
                "source": "full_frame",
                "cluster_id": full_prediction.cluster_id,
                "source_transform": {
                    "kind": "source_frame",
                    "width": request.width,
                    "height": request.height,
                },
            }
            match = matched_full.get(full_prediction.prediction_id)
            if match is None:
                continue
            crop_prediction, box_iou, mask_iou = match
            score_gain = crop_prediction.score - full_prediction.score
            refined = score_gain >= REFINEMENT_MIN_SCORE_GAIN
            match_diagnostics.append(
                {
                    "full_frame_prediction_id": full_prediction.prediction_id,
                    "crop_prediction_id": crop_prediction.prediction_id,
                    "cluster_id": crop_prediction.cluster_id,
                    "box_iou": box_iou,
                    "visible_mask_iou": mask_iou,
                    "full_frame_score": full_prediction.score,
                    "crop_score": crop_prediction.score,
                    "score_gain": score_gain,
                    "decision": "refine_geometry" if refined else "keep_full_frame_geometry",
                }
            )
            if refined:
                refined_by_id[full_prediction.prediction_id] = MappedPrediction(
                    prediction_id=full_prediction.prediction_id,
                    cluster_id=full_prediction.cluster_id,
                    proposal_order=full_prediction.proposal_order,
                    score=crop_prediction.score,
                    box=crop_prediction.box,
                    polygons=crop_prediction.polygons,
                )
                final_provenance[full_prediction.prediction_id] = {
                    "prediction_id": full_prediction.prediction_id,
                    "source": "crop_refinement",
                    "cluster_id": crop_prediction.cluster_id,
                    "refined_by_prediction_id": crop_prediction.prediction_id,
                    "source_transform": next(
                        item.transform.to_mapping()
                        for item in routed_clusters
                        if item.cluster_id == crop_prediction.cluster_id
                    ),
                }

        accepted_crops: list[MappedPrediction] = []
        exact_duplicate_decisions: list[dict[str, Any]] = []
        for crop_prediction in crop_reconciliation.retained:
            if crop_prediction.prediction_id in matched_crop_ids:
                continue
            duplicate_of = None
            current_main = [
                refined_by_id.get(item.prediction_id, item) for item in full_frame_predictions
            ] + accepted_crops
            for main_prediction in current_main:
                box_iou, mask_iou = _prediction_pair_iou(
                    main_prediction,
                    crop_prediction,
                    width=request.width,
                    height=request.height,
                )
                duplicate = (
                    box_iou >= CROP_DUPLICATE_IOU_THRESHOLD
                    and mask_iou >= CROP_DUPLICATE_IOU_THRESHOLD
                )
                exact_duplicate_decisions.append(
                    {
                        "main_prediction_id": main_prediction.prediction_id,
                        "crop_prediction_id": crop_prediction.prediction_id,
                        "box_iou": box_iou,
                        "visible_mask_iou": mask_iou,
                        "duplicate": duplicate,
                    }
                )
                if duplicate:
                    duplicate_of = main_prediction.prediction_id
                    break
            if duplicate_of is not None:
                discarded.append(
                    {
                        "prediction": crop_prediction.to_mapping(),
                        "reason": "duplicate_of_main_result",
                        "duplicate_of": duplicate_of,
                    }
                )
                continue
            if crop_prediction.score < CROP_ADDITION_MIN_SCORE:
                discarded.append(
                    {
                        "prediction": crop_prediction.to_mapping(),
                        "reason": "below_crop_addition_threshold",
                        "minimum_score": CROP_ADDITION_MIN_SCORE,
                    }
                )
                continue
            accepted_crops.append(crop_prediction)
            final_provenance[crop_prediction.prediction_id] = {
                "prediction_id": crop_prediction.prediction_id,
                "source": "cluster_crop_addition",
                "cluster_id": crop_prediction.cluster_id,
                "source_transform": next(
                    item.transform.to_mapping()
                    for item in routed_clusters
                    if item.cluster_id == crop_prediction.cluster_id
                ),
            }

        predictions = tuple(
            refined_by_id.get(item.prediction_id, item) for item in full_frame_predictions
        ) + tuple(accepted_crops)
        raw["arbitration"] = {
            "policy": "full_frame_main_with_far_cluster_refinement",
            "full_frame_predictions_retained": len(full_frame_predictions),
            "crop_predictions_before_reconciliation": len(crop_predictions),
            "crop_predictions_added": len(accepted_crops),
            "full_frame_candidates_removed": 0,
            "full_frame_geometries_refined": len(refined_by_id),
            "routed_cluster_count": len(routed_clusters),
            "matched_pairs": match_diagnostics,
            "rejected_match_candidates": rejected_match_candidates,
            "exact_duplicate_decisions": exact_duplicate_decisions,
        }
        raw["mapping"] = {"predictions": [item.to_mapping() for item in predictions]}
        raw["reconciliation"] = {
            "schema_version": crop_reconciliation.to_mapping()["schema_version"],
            "status": "applied" if routed_clusters else "not_needed",
            "policy": "strict_iou_only; full_frame_candidates_are_preserved",
            "duplicate_iou_threshold": CROP_DUPLICATE_IOU_THRESHOLD,
            "retained_prediction_ids": [item.prediction_id for item in predictions],
            "discarded_prediction_ids": [item["prediction"]["prediction_id"] for item in discarded],
            "decisions": [
                *[decision.to_mapping() for decision in crop_reconciliation.decisions],
                *match_diagnostics,
                *exact_duplicate_decisions,
            ],
            "retained": [item.to_mapping() for item in predictions],
            "discarded": discarded,
        }
        return self._result(
            request,
            started,
            raw,
            predictions,
            final_provenance,
        )

    def _result(
        self,
        request: VisibleCardRequest,
        started: float,
        raw: dict[str, Any],
        predictions: tuple[MappedPrediction, ...],
        final_provenance: dict[str, dict[str, Any]],
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
        raw["final_provenance"] = [final_provenance[p.prediction_id] for p in predictions]
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
