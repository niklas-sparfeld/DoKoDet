"""Development two-pass provider for the epic 0071 visible-card cascade.

M1 uses the reviewed 0068 segmentation bundle for both passes.  The full-frame pass uses only
detector boxes for clustering.  The same loaded detector then runs on every padded cluster crop;
its mask polygons are mapped back to the source frame and reconciled with the M0 contract.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError

from . import visible_cards
from .rfdetr_cascade import (
    RFDETR_CASCADE_BUNDLE_SCHEMA,
    RfdetrCascadeBundle,
    load_rfdetr_cascade_bundle,
)
from .rfdetr_import import block_pyav_import
from .visible_card_cascade import (
    CASCADE_COARSE_INPUT_SIZE,
    CASCADE_FINE_INPUT_SIZE,
    CASCADE_FINE_MODEL_CLASS,
    CASCADE_FINE_MODEL_VARIANT,
    CoarseProposal,
    MappedPrediction,
    PixelBox,
    PixelPoint,
    build_cascade_layout,
    frozen_cascade_recipe,
    reconcile_predictions,
)
from .visible_cards import (
    NormalizedPoint,
    ProviderResult,
    VisibleCardError,
    VisibleCardProposal,
    VisibleCardRequest,
    _elapsed_ms,
)

CASCADE_PROVIDER_NAME = "local-rfdetr-cascade"
CASCADE_PROVIDER_VERSION = "local-rfdetr-cascade-v2"


def _fine_inference_device(device: str) -> str:
    """Keep fine inference on the configured accelerator after runtime optimization."""

    return device


def _load_local_rfdetr_small(bundle: Any, device: str) -> Any:
    """Load the native M3 RF-DETR Small checkpoint on the requested device."""

    try:
        with block_pyav_import():
            from rfdetr import RFDETRSmall
    except ImportError as error:
        raise VisibleCardError(
            "local cascade inference requires rfdetr 1.9.4; install the inference dependency"
        ) from error
    try:
        version = importlib.metadata.version("rfdetr")
    except importlib.metadata.PackageNotFoundError as error:
        raise VisibleCardError("RF-DETR package metadata is not installed") from error
    if version != "1.9.4":
        raise VisibleCardError(f"installed rfdetr version {version} does not match 1.9.4")
    try:
        model = RFDETRSmall.from_checkpoint(
            str(bundle.checkpoint_path),
            num_classes=1,
            resolution=CASCADE_COARSE_INPUT_SIZE,
            device=device,
        )
    except Exception as error:
        raise VisibleCardError(f"could not load the local RF-DETR Small bundle: {error}") from error
    model_context = getattr(model, "model", None)
    actual_device = getattr(model_context, "device", None)
    if actual_device is not None and str(actual_device).split(":", 1)[0] != device:
        raise VisibleCardError(
            f"RF-DETR Small loaded on {actual_device!s}, but the requested device is {device}"
        )
    return visible_cards._optimize_local_rfdetr_for_inference(model, device=device)


def _finite_pixel_point(value: Any, field: str) -> PixelPoint:
    coordinates = visible_cards._sequence(value, field)
    if len(coordinates) != 2:
        raise VisibleCardError(f"{field} must contain x and y")
    try:
        x, y = (float(coordinate) for coordinate in coordinates)
    except (TypeError, ValueError) as error:
        raise VisibleCardError(f"{field} must contain numeric coordinates") from error
    if not all(math.isfinite(coordinate) for coordinate in (x, y)):
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
    raw_polygons = visible_cards._sequence(visible_cards._mask_to_polygons(mask), "mask polygons")
    polygons: list[tuple[PixelPoint, ...]] = []
    for polygon_index, raw_polygon in enumerate(raw_polygons):
        points = tuple(
            _finite_pixel_point(point, f"mask polygon {polygon_index} point")
            for point in visible_cards._sequence(raw_polygon, "mask polygon")
        )
        if len(points) < 3 or _polygon_area(points) <= 0:
            continue
        if any(not (0 <= point.x <= width and 0 <= point.y <= height) for point in points):
            raise VisibleCardError("detector output mask polygon points must fit the crop")
        polygons.append(points)
    if not polygons:
        return ()
    return tuple(polygons)


def _box_from_polygons(polygons: tuple[tuple[PixelPoint, ...], ...]) -> PixelBox:
    points = tuple(point for polygon in polygons for point in polygon)
    return PixelBox(
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def _normalized_point(point: PixelPoint, *, width: int, height: int) -> dict[str, int]:
    return {
        "x": max(0, min(1000, round(point.x * 1000 / width))),
        "y": max(0, min(1000, round(point.y * 1000 / height))),
    }


def _normalized_polygon(
    polygon: tuple[PixelPoint, ...], *, width: int, height: int
) -> tuple[visible_cards.NormalizedPoint, ...]:
    return tuple(
        visible_cards.NormalizedPoint(**_normalized_point(point, width=width, height=height))
        for point in polygon
    )


def _normalized_polygon_area(polygon: tuple[NormalizedPoint, ...]) -> int:
    return abs(
        sum(
            left.x * right.y - right.x * left.y
            for left, right in zip(polygon, polygon[1:] + polygon[:1], strict=True)
        )
    )


def crop_source_image(source: Image.Image, crop: Any) -> Image.Image:
    """Materialize the exact neutral-padded source crop used by the cascade runtime."""

    canvas = Image.new("RGB", (crop.crop_width, crop.crop_height), crop.padding_color)
    source_box = crop.padded_square_box.intersection(
        PixelBox(0, 0, crop.source_width, crop.source_height)
    )
    if source_box is None:
        return canvas
    source_rectangle = (
        math.floor(source_box.x_min),
        math.floor(source_box.y_min),
        math.ceil(source_box.x_max),
        math.ceil(source_box.y_max),
    )
    source_piece = source.crop(source_rectangle)
    destination = (
        math.floor(source_box.x_min - crop.padded_square_box.x_min),
        math.floor(source_box.y_min - crop.padded_square_box.y_min),
    )
    canvas.paste(source_piece, destination)
    return canvas


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


class LocalVisibleCardCascadeProvider:
    """Run the M1 development or M6 production cascade selected by the bundle path."""

    name = CASCADE_PROVIDER_NAME
    version = CASCADE_PROVIDER_VERSION
    # The shared MPS models are protected by _inference_lock. Keep the event
    # executor single-flight so frames do not queue behind native inference
    # while competing for the same device context.
    event_concurrency_limit = 1

    def __init__(
        self,
        bundle: str | Path,
        *,
        device: Literal["cpu", "mps", "cuda"] = "mps",
        provider_name: str = CASCADE_PROVIDER_NAME,
        detector: Any | None = None,
        model_loader: Callable[[Any, str], Any] | None = None,
        coarse_detector: Any | None = None,
        fine_detector: Any | None = None,
        coarse_model_loader: Callable[[Any, str], Any] | None = None,
        fine_model_loader: Callable[[Any, str], Any] | None = None,
        torch_module: Any | None = None,
    ) -> None:
        if not provider_name.startswith("local-rfdetr-cascade"):
            raise VisibleCardError(f"invalid local cascade provider name: {provider_name}")
        self.name = provider_name
        self.version = f"{provider_name}-v1"
        manifest_path = Path(bundle).expanduser().resolve() / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VisibleCardError(f"could not read cascade provider bundle: {error}") from error
        self._cascade_bundle: RfdetrCascadeBundle | None = None
        self._segmentation_provider: Any | None = None
        self._coarse_detector: Any
        self._fine_detector: Any
        # RF-DETR's MPS inference path is not safe to invoke concurrently on the
        # shared model instances. The pipeline also honors event_concurrency_limit
        # so the native lock does not become an unbounded queue.
        self._inference_lock = Lock()
        started = time.monotonic()
        if (
            isinstance(manifest, dict)
            and manifest.get("schema_version") == RFDETR_CASCADE_BUNDLE_SCHEMA
        ):
            try:
                cascade_bundle = load_rfdetr_cascade_bundle(bundle)
            except Exception as error:
                raise VisibleCardError(
                    f"could not validate the local cascade bundle: {error}"
                ) from error
            if device not in {"cpu", "mps", "cuda"}:
                raise VisibleCardError("local cascade device must be cpu, mps, or cuda")
            if torch_module is None and device != "cpu":
                torch_module = visible_cards._import_torch()
            if torch_module is not None:
                if device == "mps":
                    available = visible_cards._local_device_available(device, torch_module)
                elif device == "cuda":
                    cuda = getattr(torch_module, "cuda", None)
                    available_fn = getattr(cuda, "is_available", None)
                    available = bool(callable(available_fn) and available_fn())
                else:
                    available = True
                if not available:
                    raise VisibleCardError(
                        f"requested local cascade device is unavailable: {device}"
                    )
            self._cascade_bundle = cascade_bundle
            self._coarse_bundle = cascade_bundle.coarse_bundle
            self._fine_bundle = cascade_bundle.fine_bundle
            if detector is not None:
                coarse_detector = detector
                fine_detector = detector
            self._coarse_detector = coarse_detector or (
                coarse_model_loader or _load_local_rfdetr_small
            )(self._coarse_bundle, device)
            fine_device = _fine_inference_device(device)
            self._fine_detector = fine_detector or (
                fine_model_loader or visible_cards._load_local_rfdetr_segmentation
            )(self._fine_bundle, fine_device)
            self._fine_device = fine_device
            self.bundle = cascade_bundle
            self._coarse_input_size = CASCADE_COARSE_INPUT_SIZE
            self._coarse_confidence_threshold = float(
                cascade_bundle.manifest["thresholds"]["coarse"]
            )
            self._coarse_accepted_class_ids = frozenset({0, 1})
        else:
            self._segmentation_provider = visible_cards.LocalVisibleCardSegmentationProvider(
                bundle,
                device=device,
                detector=detector,
                model_loader=model_loader,
                torch_module=torch_module,
            )
            self.bundle = self._segmentation_provider.bundle
            self._coarse_detector = self._segmentation_provider._detector
            self._fine_detector = self._segmentation_provider._detector
            self._fine_device = device
            self._coarse_input_size = CASCADE_FINE_INPUT_SIZE
            self._coarse_confidence_threshold = self._segmentation_provider.confidence_threshold
            self._coarse_accepted_class_ids = self._segmentation_provider.accepted_class_ids
        self.device = device
        self.input_size = CASCADE_FINE_INPUT_SIZE
        self.confidence_threshold = (
            float(self._cascade_bundle.manifest["thresholds"]["fine"])
            if self._cascade_bundle is not None
            else self._segmentation_provider.confidence_threshold
        )
        self.load_latency_ms = (
            _elapsed_ms(started)
            if self._cascade_bundle is not None
            else self._segmentation_provider.load_latency_ms
        )

    @property
    def bundle_identity(self) -> dict[str, Any]:
        if self._cascade_bundle is not None:
            manifest = self._cascade_bundle.manifest
            return {
                "schema_version": manifest["schema_version"],
                "bundle_digest": manifest["bundle_digest"],
                "recipe_digest": manifest["recipe"]["recipe_digest"],
                "coarse": manifest["children"]["coarse"],
                "fine": manifest["children"]["fine"],
            }
        assert self._segmentation_provider is not None
        identity = self._segmentation_provider.bundle_identity
        return {
            "coarse": {
                "role": "development_coarse",
                "model_class": CASCADE_FINE_MODEL_CLASS,
                "model_variant": CASCADE_FINE_MODEL_VARIANT,
                "input_size": self.input_size,
                "bundle": identity,
            },
            "fine": {
                "role": "fine",
                "model_class": CASCADE_FINE_MODEL_CLASS,
                "model_variant": CASCADE_FINE_MODEL_VARIANT,
                "input_size": self.input_size,
                "bundle": identity,
            },
        }

    def _base_raw_response(self, request: VisibleCardRequest) -> dict[str, Any]:
        response = {
            "provider": self.name,
            "version": self.version,
            "device": self.device,
            "fine_device": self._fine_device,
            "source_frame": _source_frame_mapping(request),
            "bundle_identity": self.bundle_identity,
            "cascade_recipe": frozen_cascade_recipe(),
            "load_latency_ms": self.load_latency_ms,
        }
        if self._cascade_bundle is not None:
            response["cascade_bundle"] = {
                "schema_version": RFDETR_CASCADE_BUNDLE_SCHEMA,
                "bundle_digest": self._cascade_bundle.manifest["bundle_digest"],
                "children_loaded_once": True,
            }
        else:
            response["development_coarse_model"] = {
                "model_class": CASCADE_FINE_MODEL_CLASS,
                "model_variant": CASCADE_FINE_MODEL_VARIANT,
                "input_size": self.input_size,
                "replacement_milestone": "M3",
            }
        return response

    def _unavailable(
        self,
        request: VisibleCardRequest,
        started: float,
        error: str,
        raw: dict[str, Any],
    ) -> ProviderResult:
        raw = {**self._base_raw_response(request), **raw}
        raw["timing"] = {
            "load_latency_ms": self.load_latency_ms,
            "total_latency_ms": _elapsed_ms(started),
        }
        return ProviderResult(
            status="unavailable",
            raw_response=raw,
            latency_ms=_elapsed_ms(started),
            error=error,
        )

    def _predict(
        self, image: Image.Image, *, use_masks: bool
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        detector = self._fine_detector if use_masks else self._coarse_detector
        input_size = self.input_size if use_masks else self._coarse_input_size
        threshold = self.confidence_threshold if use_masks else self._coarse_confidence_threshold
        accepted_class_ids = (
            self._segmentation_provider.accepted_class_ids
            if self._segmentation_provider is not None and use_masks
            else (frozenset({0, 1}) if use_masks else self._coarse_accepted_class_ids)
        )
        with self._inference_lock:
            detections = detector.predict(
                image,
                threshold=threshold,
                shape=(input_size, input_size),
                include_source_image=False,
            )
        boxes = visible_cards._normalise_detection_rows(
            visible_cards._detections_field(detections, "xyxy"), "xyxy"
        )
        confidence = visible_cards._sequence(
            visible_cards._detections_field(detections, "confidence"), "confidence"
        )
        class_ids = visible_cards._sequence(
            visible_cards._detections_field(detections, "class_id"), "class_id"
        )
        raw_masks = visible_cards._detections_field(detections, "mask") if use_masks else None
        if use_masks and raw_masks is None:
            raw_masks = visible_cards._detections_field(detections, "masks")
        mask_rows = (
            visible_cards._normalise_mask_rows(raw_masks)
            if use_masks and raw_masks is not None
            else None
        )
        if not (len(boxes) == len(confidence) == len(class_ids)):
            raise VisibleCardError("detector output fields have different lengths")
        if mask_rows is not None and len(mask_rows) != len(boxes):
            raise VisibleCardError("detector output mask field has a different length")

        coarse: list[dict[str, Any]] = []
        fine: list[dict[str, Any]] = []
        width, height = image.size
        for index, (coordinates, raw_score, raw_class_id) in enumerate(
            zip(boxes, confidence, class_ids, strict=True)
        ):
            score = float(raw_score)
            class_id = int(raw_class_id)
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise VisibleCardError("detector output confidence must be finite in [0, 1]")
            if class_id not in accepted_class_ids:
                raise VisibleCardError(f"detector returned unsupported class id: {class_id}")
            if score <= threshold:
                continue
            _normalized_box, pixel_box = visible_cards._normalised_box_from_pixels(
                coordinates, width=width, height=height
            )
            detector_record: dict[str, Any] = {
                "detection_index": index,
                "class_id": class_id,
                "score": score,
                "box_xyxy": pixel_box,
                "mask_available": mask_rows is not None,
            }
            coarse.append(detector_record)
            if mask_rows is None:
                polygons = (
                    (
                        PixelPoint(pixel_box[0], pixel_box[1]),
                        PixelPoint(pixel_box[2], pixel_box[1]),
                        PixelPoint(pixel_box[2], pixel_box[3]),
                        PixelPoint(pixel_box[0], pixel_box[3]),
                    ),
                )
                geometry_source = "detector_box"
            else:
                polygons = _mask_polygons(mask_rows[index], width=width, height=height)
                geometry_source = "segmentation_mask"
                if not polygons:
                    detector_record["mask_empty"] = True
                    continue
            detector_record["geometry_source"] = geometry_source
            fine.append(
                {
                    "detection_index": index,
                    "score": score,
                    "box": _box_from_polygons(polygons),
                    "polygons": polygons,
                    "geometry_source": geometry_source,
                }
            )
        return coarse, fine

    def _mapped_predictions(
        self, cluster: Any, fine_records: list[dict[str, Any]]
    ) -> tuple[MappedPrediction, ...]:
        mapped: list[MappedPrediction] = []
        for order, record in enumerate(fine_records):
            source_polygons = tuple(
                tuple(cluster.transform.crop_to_source(point) for point in polygon)
                for polygon in record["polygons"]
            )
            source_box = _box_from_polygons(source_polygons)
            mapped.append(
                MappedPrediction(
                    prediction_id=f"{cluster.cluster_id}-prediction-{order:04d}",
                    cluster_id=cluster.cluster_id,
                    proposal_order=order,
                    score=record["score"],
                    box=source_box,
                    polygons=source_polygons,
                )
            )
        return tuple(mapped)

    def propose(self, request: VisibleCardRequest) -> ProviderResult:
        if request.provider != self.name:
            raise VisibleCardError(
                f"request provider {request.provider!r} does not match {self.name!r}."
            )
        started = time.monotonic()
        try:
            with Image.open(BytesIO(request.image_bytes)) as source:
                if source.size != (request.width, request.height):
                    raise VisibleCardError(
                        "decoded source image dimensions do not match the request dimensions"
                    )
                source_image = source.convert("RGB").copy()
        except (UnidentifiedImageError, OSError, ValueError) as error:
            return self._unavailable(
                request, started, f"local cascade input could not be decoded: {error}", {}
            )

        raw = self._base_raw_response(request)
        coarse_started = time.monotonic()
        try:
            coarse_records, _ = self._predict(source_image, use_masks=False)
            coarse_proposals = tuple(
                CoarseProposal(
                    proposal_id=f"coarse-{record['detection_index']:04d}",
                    box=PixelBox(*record["box_xyxy"]),
                    score=record["score"],
                )
                for record in coarse_records
            )
            layout = build_cascade_layout(
                coarse_proposals,
                frame_width=request.width,
                frame_height=request.height,
                coarse_threshold=self.confidence_threshold,
                model_input_size=self.input_size,
            )
        except Exception as error:
            raw["coarse"] = {
                "status": "unavailable",
                "error": str(error),
                "latency_ms": _elapsed_ms(coarse_started),
            }
            return self._unavailable(request, started, f"cascade coarse stage failed: {error}", raw)

        raw["coarse"] = {
            "status": "ok",
            "latency_ms": _elapsed_ms(coarse_started),
            "threshold": self._coarse_confidence_threshold,
            "detections": [
                {
                    **record,
                    "mask_ignored_for_clustering": True,
                }
                for record in coarse_records
            ],
            "layout": layout.to_mapping(),
        }
        if not layout.clusters:
            raw["fine"] = {"status": "not_run", "clusters": []}
            raw["reconciliation"] = reconcile_predictions(
                (), frame_width=request.width, frame_height=request.height
            ).to_mapping()
            raw["timing"] = {
                "load_latency_ms": self.load_latency_ms,
                "coarse_latency_ms": raw["coarse"]["latency_ms"],
                "fine_latency_ms": 0.0,
                "total_latency_ms": _elapsed_ms(started),
            }
            return ProviderResult(status="ok", raw_response=raw, latency_ms=_elapsed_ms(started))

        fine_started = time.monotonic()
        all_mapped: list[MappedPrediction] = []
        fine_records: list[dict[str, Any]] = []
        try:
            for cluster in layout.clusters:
                crop_image = crop_source_image(source_image, cluster)
                crop_bytes = _png_bytes(crop_image)
                try:
                    _coarse_crop_records, crop_fine_records = self._predict(
                        crop_image, use_masks=True
                    )
                except Exception as error:
                    fine_records.append(
                        {
                            "cluster_id": cluster.cluster_id,
                            "status": "unavailable",
                            "crop": cluster.to_mapping(),
                            "crop_image_sha256": hashlib.sha256(crop_bytes).hexdigest(),
                            "error": str(error),
                        }
                    )
                    raise
                mapped = self._mapped_predictions(
                    cluster,
                    crop_fine_records,
                )
                all_mapped.extend(mapped)
                fine_records.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "status": "ok",
                        "crop": cluster.to_mapping(),
                        "crop_image_sha256": hashlib.sha256(crop_bytes).hexdigest(),
                        "detector_count": len(crop_fine_records),
                        "predictions": [prediction.to_mapping() for prediction in mapped],
                    }
                )
        except Exception as error:
            raw["fine"] = {
                "status": "unavailable",
                "latency_ms": _elapsed_ms(fine_started),
                "clusters": fine_records,
                "error": str(error),
            }
            return self._unavailable(request, started, f"cascade fine stage failed: {error}", raw)

        reconciliation = reconcile_predictions(
            all_mapped,
            frame_width=request.width,
            frame_height=request.height,
        )
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
        raw["fine"] = {
            "status": "ok",
            "latency_ms": _elapsed_ms(fine_started),
            "clusters": fine_records,
        }
        raw["mapping"] = {
            "prediction_count": len(all_mapped),
            "predictions": [prediction.to_mapping() for prediction in all_mapped],
        }
        cluster_by_id = {cluster.cluster_id: cluster for cluster in layout.clusters}
        retained_ids = {prediction.prediction_id for prediction in reconciliation.retained}
        raw["candidate_mapping"] = [
            {
                "prediction_id": prediction.prediction_id,
                "retained_fine_result_id": prediction.prediction_id,
                "retained": prediction.prediction_id in retained_ids,
                "cluster_id": prediction.cluster_id,
                "source_transform": cluster_by_id[prediction.cluster_id].transform.to_mapping(),
            }
            for prediction in reconciliation.retained
        ]
        raw["reconciliation"] = {
            **reconciliation.to_mapping(),
            "retained": [prediction.to_mapping() for prediction in reconciliation.retained],
            "discarded": [prediction.to_mapping() for prediction in reconciliation.discarded],
        }
        raw["timing"] = {
            "load_latency_ms": self.load_latency_ms,
            "coarse_latency_ms": raw["coarse"]["latency_ms"],
            "fine_latency_ms": raw["fine"]["latency_ms"],
            "total_latency_ms": _elapsed_ms(started),
        }
        return ProviderResult(
            status="ok",
            proposals=tuple(proposals),
            raw_response=raw,
            latency_ms=_elapsed_ms(started),
        )


__all__ = [
    "CASCADE_PROVIDER_NAME",
    "CASCADE_PROVIDER_VERSION",
    "LocalVisibleCardCascadeProvider",
    "crop_source_image",
]
