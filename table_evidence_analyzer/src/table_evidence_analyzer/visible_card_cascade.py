"""Deterministic contracts for the epic 0071 visible-card cascade.

This module contains only geometry, identity, and reconciliation logic.  It does not import a
model runtime.  A coarse detector can therefore be replaced by the trained RF-DETR Small bundle
without changing crop or source-coordinate semantics.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

CASCADE_SCHEMA_VERSION = "local-rfdetr-cascade/v1"
CLUSTER_SCHEMA_VERSION = "visible-card-cluster/v1"
CROP_SCHEMA_VERSION = "visible-card-cluster-crop/v1"
TRANSFORM_SCHEMA_VERSION = "visible-card-coordinate-transform/v1"
RECONCILIATION_SCHEMA_VERSION = "visible-card-reconciliation/v1"

CASCADE_COARSE_MODEL_CLASS = "RFDETRSmall"
CASCADE_COARSE_MODEL_VARIANT = "rfdetr-small"
CASCADE_COARSE_INPUT_SIZE = 512
CASCADE_COARSE_CLASS_NAME = "card_cluster"
CASCADE_FINE_MODEL_CLASS = "RFDETRSegMedium"
CASCADE_FINE_MODEL_VARIANT = "rfdetr-seg-medium"
CASCADE_FINE_INPUT_SIZE = 432
CASCADE_FINE_CLASS_NAME = "visible_card"
CASCADE_RFDETR_VERSION = "1.9.4"
CASCADE_DEVICE = "mps"
CASCADE_SUPPORTED_DEVICES = frozenset({"cpu", "mps", "cuda"})
CASCADE_COARSE_CONFIDENCE_THRESHOLD = 0.5
DUPLICATE_IOU_THRESHOLD = 0.90
DUPLICATE_MASK_CONTAINMENT_THRESHOLD = 0.80
DUPLICATE_BOX_AREA_RATIO_MAX = 0.95
NEUTRAL_PADDING_RGB = (128, 128, 128)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class CascadeContractError(ValueError):
    """Raised when a cascade contract cannot be trusted."""


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CascadeContractError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise CascadeContractError(f"{field} must be finite")
    return number


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CascadeContractError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CascadeContractError(f"{field} must be a non-negative integer")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise CascadeContractError(f"{field} must be a non-empty identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise CascadeContractError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CascadeContractError("cascade contract values must be finite JSON") from error


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class PixelPoint:
    """One point in a pixel-coordinate space.

    Coordinates use the same continuous edge convention as an image crop: the top-left source
    pixel edge is ``(0, 0)`` and the bottom-right edge is ``(width, height)``.
    """

    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _finite_number(self.x, "point x"))
        object.__setattr__(self, "y", _finite_number(self.y, "point y"))

    def to_mapping(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True, slots=True)
class PixelBox:
    """A positive half-open axis-aligned pixel rectangle."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        values = {
            "box x_min": self.x_min,
            "box y_min": self.y_min,
            "box x_max": self.x_max,
            "box y_max": self.y_max,
        }
        normalized = {field: _finite_number(value, field) for field, value in values.items()}
        for field, value in normalized.items():
            object.__setattr__(
                self,
                field.removeprefix("box ").replace("_", " ").replace(" ", "_"),
                value,
            )
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise CascadeContractError("box must have positive width and height")

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def center(self) -> PixelPoint:
        return PixelPoint((self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2)

    def contains(self, other: PixelBox) -> bool:
        return (
            self.x_min <= other.x_min
            and other.x_max <= self.x_max
            and self.y_min <= other.y_min
            and other.y_max <= self.y_max
        )

    def intersects(self, other: PixelBox) -> bool:
        return (
            self.x_min <= other.x_max
            and other.x_min <= self.x_max
            and self.y_min <= other.y_max
            and other.y_min <= self.y_max
        )

    def intersection(self, other: PixelBox) -> PixelBox | None:
        x_min = max(self.x_min, other.x_min)
        y_min = max(self.y_min, other.y_min)
        x_max = min(self.x_max, other.x_max)
        y_max = min(self.y_max, other.y_max)
        if x_min >= x_max or y_min >= y_max:
            return None
        return PixelBox(x_min, y_min, x_max, y_max)

    def to_mapping(self) -> dict[str, float]:
        return {
            "x_min": self.x_min,
            "y_min": self.y_min,
            "x_max": self.x_max,
            "y_max": self.y_max,
        }


@dataclass(frozen=True, slots=True)
class Padding:
    """Source pixels supplied by neutral padding on each crop edge."""

    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        for field in ("left", "top", "right", "bottom"):
            _non_negative_int(getattr(self, field), f"padding {field}")

    def to_mapping(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
        }


@dataclass(frozen=True, slots=True)
class CoordinateTransform:
    """Reversible source-frame, crop, and model-input coordinate transforms."""

    source_width: int
    source_height: int
    crop_x_min: int
    crop_y_min: int
    crop_width: int
    crop_height: int
    model_width: int
    model_height: int

    def __post_init__(self) -> None:
        _positive_int(self.source_width, "source_width")
        _positive_int(self.source_height, "source_height")
        _positive_int(self.crop_width, "crop_width")
        _positive_int(self.crop_height, "crop_height")
        _positive_int(self.model_width, "model_width")
        _positive_int(self.model_height, "model_height")
        if isinstance(self.crop_x_min, bool) or not isinstance(self.crop_x_min, int):
            raise CascadeContractError("crop_x_min must be an integer")
        if isinstance(self.crop_y_min, bool) or not isinstance(self.crop_y_min, int):
            raise CascadeContractError("crop_y_min must be an integer")

    @property
    def scale_x(self) -> float:
        return self.model_width / self.crop_width

    @property
    def scale_y(self) -> float:
        return self.model_height / self.crop_height

    def source_to_crop(self, point: PixelPoint) -> PixelPoint:
        return PixelPoint(point.x - self.crop_x_min, point.y - self.crop_y_min)

    def crop_to_source(self, point: PixelPoint) -> PixelPoint:
        return PixelPoint(point.x + self.crop_x_min, point.y + self.crop_y_min)

    def crop_to_model(self, point: PixelPoint) -> PixelPoint:
        return PixelPoint(point.x * self.scale_x, point.y * self.scale_y)

    def model_to_crop(self, point: PixelPoint) -> PixelPoint:
        return PixelPoint(point.x / self.scale_x, point.y / self.scale_y)

    def source_to_model(self, point: PixelPoint) -> PixelPoint:
        return self.crop_to_model(self.source_to_crop(point))

    def model_to_source(self, point: PixelPoint) -> PixelPoint:
        return self.crop_to_source(self.model_to_crop(point))

    def _map_box(self, box: PixelBox, mapper: Any) -> PixelBox:
        points = [
            mapper(PixelPoint(box.x_min, box.y_min)),
            mapper(PixelPoint(box.x_max, box.y_min)),
            mapper(PixelPoint(box.x_max, box.y_max)),
            mapper(PixelPoint(box.x_min, box.y_max)),
        ]
        return PixelBox(
            min(point.x for point in points),
            min(point.y for point in points),
            max(point.x for point in points),
            max(point.y for point in points),
        )

    def source_to_model_box(self, box: PixelBox) -> PixelBox:
        return self._map_box(box, self.source_to_model)

    def model_to_source_box(self, box: PixelBox) -> PixelBox:
        return self._map_box(box, self.model_to_source)

    def source_to_model_polygons(
        self, polygons: Sequence[Sequence[PixelPoint]]
    ) -> tuple[tuple[PixelPoint, ...], ...]:
        return tuple(
            tuple(self.source_to_model(point) for point in polygon) for polygon in polygons
        )

    def model_to_source_polygons(
        self, polygons: Sequence[Sequence[PixelPoint]]
    ) -> tuple[tuple[PixelPoint, ...], ...]:
        return tuple(
            tuple(self.model_to_source(point) for point in polygon) for polygon in polygons
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": TRANSFORM_SCHEMA_VERSION,
            "source_size": {"width": self.source_width, "height": self.source_height},
            "crop_origin": {"x": self.crop_x_min, "y": self.crop_y_min},
            "crop_size": {"width": self.crop_width, "height": self.crop_height},
            "model_size": {"width": self.model_width, "height": self.model_height},
            "scale": {"x": self.scale_x, "y": self.scale_y},
        }


@dataclass(frozen=True, slots=True)
class CoarseProposal:
    """One coarse proposal in source-frame pixel coordinates."""

    proposal_id: str
    box: PixelBox
    score: float

    def __post_init__(self) -> None:
        _identifier(self.proposal_id, "proposal_id")
        object.__setattr__(self, "score", _finite_number(self.score, "proposal score"))
        if not 0 <= self.score <= 1:
            raise CascadeContractError("proposal score must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class CardCluster:
    """One connected coarse-proposal component and its source crop geometry."""

    cluster_id: str
    proposal_ids: tuple[str, ...]
    source_box: PixelBox
    padded_square_box: PixelBox
    reference_span: float

    def __post_init__(self) -> None:
        _identifier(self.cluster_id, "cluster_id")
        if not self.proposal_ids:
            raise CascadeContractError("cluster must contain at least one proposal")
        if len(set(self.proposal_ids)) != len(self.proposal_ids):
            raise CascadeContractError("cluster proposal IDs must be unique")
        span = _finite_number(self.reference_span, "reference span")
        if span <= 0:
            raise CascadeContractError("reference span must be positive")
        object.__setattr__(self, "reference_span", span)
        if self.padded_square_box.width != self.padded_square_box.height:
            raise CascadeContractError("cluster crop must be square")
        if not self.padded_square_box.contains(self.source_box):
            raise CascadeContractError("cluster crop must contain its source box")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CLUSTER_SCHEMA_VERSION,
            "cluster_id": self.cluster_id,
            "proposal_ids": list(self.proposal_ids),
            "source_box": self.source_box.to_mapping(),
            "padded_square_box": self.padded_square_box.to_mapping(),
            "reference_span": self.reference_span,
        }


@dataclass(frozen=True, slots=True)
class ClusterCrop:
    """One square crop with all source-coordinate metadata needed by a fine stage."""

    cluster: CardCluster
    source_width: int
    source_height: int
    crop_width: int
    crop_height: int
    scale: float
    padding: Padding
    transform: CoordinateTransform

    def __post_init__(self) -> None:
        _positive_int(self.source_width, "source_width")
        _positive_int(self.source_height, "source_height")
        _positive_int(self.crop_width, "crop_width")
        _positive_int(self.crop_height, "crop_height")
        if self.crop_width != self.crop_height:
            raise CascadeContractError("cluster crop dimensions must be square")
        scale = _finite_number(self.scale, "crop scale")
        if scale <= 0:
            raise CascadeContractError("crop scale must be positive")
        object.__setattr__(self, "scale", scale)
        expected = self.cluster.padded_square_box
        if (expected.width, expected.height) != (self.crop_width, self.crop_height):
            raise CascadeContractError("crop dimensions do not match the padded square box")
        if self.transform.source_width != self.source_width:
            raise CascadeContractError("transform source width does not match crop")
        if self.transform.source_height != self.source_height:
            raise CascadeContractError("transform source height does not match crop")
        if (self.transform.crop_width, self.transform.crop_height) != (
            self.crop_width,
            self.crop_height,
        ):
            raise CascadeContractError("transform crop dimensions do not match crop")
        if not math.isclose(self.scale, self.transform.scale_x) or not math.isclose(
            self.scale, self.transform.scale_y
        ):
            raise CascadeContractError("crop scale does not match its coordinate transform")

    @property
    def cluster_id(self) -> str:
        return self.cluster.cluster_id

    @property
    def proposal_ids(self) -> tuple[str, ...]:
        return self.cluster.proposal_ids

    @property
    def source_box(self) -> PixelBox:
        return self.cluster.source_box

    @property
    def padded_square_box(self) -> PixelBox:
        return self.cluster.padded_square_box

    @property
    def padding_color(self) -> tuple[int, int, int]:
        return NEUTRAL_PADDING_RGB

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CROP_SCHEMA_VERSION,
            "cluster": self.cluster.to_mapping(),
            "cluster_id": self.cluster.cluster_id,
            "proposal_ids": list(self.cluster.proposal_ids),
            "source_size": {"width": self.source_width, "height": self.source_height},
            "source_box": self.cluster.source_box.to_mapping(),
            "padded_square_box": self.cluster.padded_square_box.to_mapping(),
            "crop_dimensions": {"width": self.crop_width, "height": self.crop_height},
            "scale": self.scale,
            "padding": self.padding.to_mapping(),
            "padding_color": list(NEUTRAL_PADDING_RGB),
            "transform": self.transform.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class CascadeLayout:
    """Deterministic layout output for one source frame."""

    source_width: int
    source_height: int
    coarse_threshold: float
    reference_span: float | None
    clusters: tuple[ClusterCrop, ...]

    def __post_init__(self) -> None:
        _positive_int(self.source_width, "source_width")
        _positive_int(self.source_height, "source_height")
        threshold = _finite_number(self.coarse_threshold, "coarse threshold")
        if not 0 <= threshold <= 1:
            raise CascadeContractError("coarse threshold must be in [0, 1]")
        object.__setattr__(self, "coarse_threshold", threshold)
        if self.reference_span is not None:
            span = _finite_number(self.reference_span, "reference span")
            if span <= 0:
                raise CascadeContractError("reference span must be positive")
            object.__setattr__(self, "reference_span", span)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CLUSTER_SCHEMA_VERSION,
            "source_size": {"width": self.source_width, "height": self.source_height},
            "coarse_threshold": self.coarse_threshold,
            "reference_span": self.reference_span,
            "clusters": [cluster.to_mapping() for cluster in self.clusters],
        }


def _validate_source_box(box: PixelBox, *, width: int, height: int) -> None:
    frame = PixelBox(0, 0, width, height)
    if not frame.contains(box):
        raise CascadeContractError("proposal box must be inside the source frame")


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _components(proposals: Sequence[CoarseProposal], reference_span: float) -> list[list[int]]:
    expanded = [
        PixelBox(
            proposal.box.x_min - reference_span / 2,
            proposal.box.y_min - reference_span / 2,
            proposal.box.x_max + reference_span / 2,
            proposal.box.y_max + reference_span / 2,
        )
        for proposal in proposals
    ]
    remaining = set(range(len(proposals)))
    components: list[list[int]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        component = [seed]
        queue = [seed]
        while queue:
            current = queue.pop(0)
            connected = sorted(
                candidate
                for candidate in remaining
                if expanded[current].intersects(expanded[candidate])
            )
            for candidate in connected:
                remaining.remove(candidate)
                queue.append(candidate)
                component.append(candidate)
        components.append(sorted(component))
    return components


def _union(boxes: Iterable[PixelBox]) -> PixelBox:
    values = tuple(boxes)
    if not values:
        raise CascadeContractError("cannot union an empty box collection")
    return PixelBox(
        min(box.x_min for box in values),
        min(box.y_min for box in values),
        max(box.x_max for box in values),
        max(box.y_max for box in values),
    )


def _square_box(source_box: PixelBox, reference_span: float) -> PixelBox:
    side = max(source_box.width + reference_span, source_box.height + reference_span)
    center = source_box.center
    desired_min_x = center.x - side / 2
    desired_min_y = center.y - side / 2
    desired_max_x = center.x + side / 2
    desired_max_y = center.y + side / 2
    x_min = math.floor(desired_min_x)
    y_min = math.floor(desired_min_y)
    x_max = math.ceil(desired_max_x)
    y_max = math.ceil(desired_max_y)
    if x_max <= x_min:
        x_max = x_min + 1
    if y_max <= y_min:
        y_max = y_min + 1
    square_side = max(x_max - x_min, y_max - y_min)
    return PixelBox(x_min, y_min, x_min + square_side, y_min + square_side)


def _padding(square_box: PixelBox, *, width: int, height: int) -> Padding:
    return Padding(
        left=max(0, math.ceil(-square_box.x_min)),
        top=max(0, math.ceil(-square_box.y_min)),
        right=max(0, math.ceil(square_box.x_max - width)),
        bottom=max(0, math.ceil(square_box.y_max - height)),
    )


def build_cascade_layout(
    proposals: Sequence[CoarseProposal],
    *,
    frame_width: int,
    frame_height: int,
    coarse_threshold: float = CASCADE_COARSE_CONFIDENCE_THRESHOLD,
    model_input_size: int = CASCADE_FINE_INPUT_SIZE,
) -> CascadeLayout:
    """Build deterministic connected clusters and reversible square crop transforms."""

    _positive_int(frame_width, "frame_width")
    _positive_int(frame_height, "frame_height")
    _positive_int(model_input_size, "model_input_size")
    threshold = _finite_number(coarse_threshold, "coarse threshold")
    if not 0 <= threshold <= 1:
        raise CascadeContractError("coarse threshold must be in [0, 1]")
    proposal_ids = [proposal.proposal_id for proposal in proposals]
    if len(set(proposal_ids)) != len(proposal_ids):
        raise CascadeContractError("proposal IDs must be unique within one frame")
    for proposal in proposals:
        _validate_source_box(proposal.box, width=frame_width, height=frame_height)
    retained = tuple(proposal for proposal in proposals if proposal.score >= threshold)
    if not retained:
        return CascadeLayout(frame_width, frame_height, threshold, None, ())
    reference_span = _median(tuple(min(item.box.width, item.box.height) for item in retained))
    if reference_span <= 0 or not math.isfinite(reference_span):
        raise CascadeContractError("reference span must be finite and positive")
    components = _components(retained, reference_span)
    crops: list[ClusterCrop] = []
    for cluster_number, member_indices in enumerate(components, start=1):
        members = tuple(retained[index] for index in member_indices)
        source_box = _union(member.box for member in members)
        padded_square_box = _square_box(source_box, reference_span)
        if padded_square_box.width != padded_square_box.height:
            raise CascadeContractError("computed cluster crop is not square")
        crop_width = int(padded_square_box.width)
        crop_height = int(padded_square_box.height)
        transform = CoordinateTransform(
            source_width=frame_width,
            source_height=frame_height,
            crop_x_min=int(padded_square_box.x_min),
            crop_y_min=int(padded_square_box.y_min),
            crop_width=crop_width,
            crop_height=crop_height,
            model_width=model_input_size,
            model_height=model_input_size,
        )
        cluster = CardCluster(
            cluster_id=f"cluster-{cluster_number:04d}",
            proposal_ids=tuple(member.proposal_id for member in members),
            source_box=source_box,
            padded_square_box=padded_square_box,
            reference_span=reference_span,
        )
        crops.append(
            ClusterCrop(
                cluster=cluster,
                source_width=frame_width,
                source_height=frame_height,
                crop_width=crop_width,
                crop_height=crop_height,
                scale=model_input_size / crop_width,
                padding=_padding(padded_square_box, width=frame_width, height=frame_height),
                transform=transform,
            )
        )
    return CascadeLayout(frame_width, frame_height, threshold, reference_span, tuple(crops))


@dataclass(frozen=True, slots=True)
class MappedPrediction:
    """One fine-stage result after mapping from a cluster crop to source coordinates."""

    prediction_id: str
    cluster_id: str
    proposal_order: int
    score: float
    box: PixelBox
    polygons: tuple[tuple[PixelPoint, ...], ...]
    mask: frozenset[tuple[int, int]] | None = None

    def __post_init__(self) -> None:
        _identifier(self.prediction_id, "prediction_id")
        _identifier(self.cluster_id, "cluster_id")
        _non_negative_int(self.proposal_order, "proposal_order")
        score = _finite_number(self.score, "prediction score")
        if not 0 <= score <= 1:
            raise CascadeContractError("prediction score must be in [0, 1]")
        object.__setattr__(self, "score", score)
        if not self.polygons or any(len(polygon) < 3 for polygon in self.polygons):
            raise CascadeContractError("prediction must preserve one or more polygon components")
        if self.mask is not None:
            for point in self.mask:
                if (
                    not isinstance(point, tuple)
                    or len(point) != 2
                    or any(isinstance(value, bool) or not isinstance(value, int) for value in point)
                ):
                    raise CascadeContractError("prediction mask must contain integer points")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "cluster_id": self.cluster_id,
            "proposal_order": self.proposal_order,
            "score": self.score,
            "box": self.box.to_mapping(),
            "polygons": [[point.to_mapping() for point in polygon] for polygon in self.polygons],
            "mask": ([[x, y] for x, y in sorted(self.mask)] if self.mask is not None else None),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    """One pairwise duplicate decision retained for diagnostics."""

    left_prediction_id: str
    right_prediction_id: str
    box_iou: float
    mask_iou: float
    duplicate: bool
    kept_prediction_id: str | None
    discarded_prediction_id: str | None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "left_prediction_id": self.left_prediction_id,
            "right_prediction_id": self.right_prediction_id,
            "box_iou": self.box_iou,
            "mask_iou": self.mask_iou,
            "duplicate": self.duplicate,
            "kept_prediction_id": self.kept_prediction_id,
            "discarded_prediction_id": self.discarded_prediction_id,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Final source-frame predictions and the decisions that produced them."""

    retained: tuple[MappedPrediction, ...]
    discarded: tuple[MappedPrediction, ...]
    decisions: tuple[ReconciliationDecision, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": RECONCILIATION_SCHEMA_VERSION,
            "retained_prediction_ids": [prediction.prediction_id for prediction in self.retained],
            "discarded_prediction_ids": [prediction.prediction_id for prediction in self.discarded],
            "decisions": [decision.to_mapping() for decision in self.decisions],
        }


def _box_iou(left: PixelBox, right: PixelBox) -> float:
    intersection = left.intersection(right)
    if intersection is None:
        return 0.0
    union_area = left.width * left.height + right.width * right.height
    intersection_area = intersection.width * intersection.height
    return intersection_area / (union_area - intersection_area)


def _box_containment(left: PixelBox, right: PixelBox) -> float:
    """Return the intersection as a fraction of the smaller box."""

    intersection = left.intersection(right)
    if intersection is None:
        return 0.0
    smaller_area = min(left.width * left.height, right.width * right.height)
    if smaller_area <= 0:
        return 0.0
    return intersection.width * intersection.height / smaller_area


def _point_in_polygon(point: PixelPoint, polygon: Sequence[PixelPoint]) -> bool:
    inside = False
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        crosses = (current.y > point.y) != (previous.y > point.y)
        if crosses:
            x_at_y = (previous.x - current.x) * (point.y - current.y) / (
                previous.y - current.y
            ) + current.x
            if point.x < x_at_y:
                inside = not inside
    return inside


def _polygon_mask(
    prediction: MappedPrediction, *, width: int, height: int
) -> frozenset[tuple[int, int]]:
    x_min = max(0, math.floor(prediction.box.x_min))
    y_min = max(0, math.floor(prediction.box.y_min))
    x_max = min(width, math.ceil(prediction.box.x_max))
    y_max = min(height, math.ceil(prediction.box.y_max))
    pixels: set[tuple[int, int]] = set()
    for y in range(y_min, y_max):
        center_y = y + 0.5
        for polygon in prediction.polygons:
            intersections: list[float] = []
            for index, current in enumerate(polygon):
                previous = polygon[index - 1]
                if (current.y > center_y) == (previous.y > center_y):
                    continue
                intersections.append(
                    (previous.x - current.x) * (center_y - current.y) / (previous.y - current.y)
                    + current.x
                )
            intersections.sort()
            for left, right in zip(intersections[::2], intersections[1::2], strict=False):
                start = max(x_min, math.ceil(left - 0.5))
                stop = min(x_max, math.ceil(right - 0.5))
                pixels.update((x, y) for x in range(start, stop))
    return frozenset(pixels)


def _mask_iou(
    left: MappedPrediction,
    right: MappedPrediction,
    *,
    width: int,
    height: int,
    mask_cache: dict[int, frozenset[tuple[int, int]]] | None = None,
) -> float:
    left_mask = (
        left.mask
        if left.mask is not None
        else (
            mask_cache[id(left)]
            if mask_cache is not None and id(left) in mask_cache
            else _polygon_mask(left, width=width, height=height)
        )
    )
    right_mask = (
        right.mask
        if right.mask is not None
        else (
            mask_cache[id(right)]
            if mask_cache is not None and id(right) in mask_cache
            else _polygon_mask(right, width=width, height=height)
        )
    )
    union = left_mask | right_mask
    if not union:
        return 0.0
    return len(left_mask & right_mask) / len(union)


def _mask_containment(
    left: MappedPrediction,
    right: MappedPrediction,
    *,
    width: int,
    height: int,
    mask_cache: dict[int, frozenset[tuple[int, int]]] | None = None,
) -> float:
    """Return the overlap as a fraction of the smaller visible mask.

    A second detector result can be a partial mask fragment of the same card.  Its mask IoU with
    the complete result is low even though nearly all of its pixels are explained by that result.
    """

    left_mask = (
        left.mask
        if left.mask is not None
        else (
            mask_cache[id(left)]
            if mask_cache is not None and id(left) in mask_cache
            else _polygon_mask(left, width=width, height=height)
        )
    )
    right_mask = (
        right.mask
        if right.mask is not None
        else (
            mask_cache[id(right)]
            if mask_cache is not None and id(right) in mask_cache
            else _polygon_mask(right, width=width, height=height)
        )
    )
    smaller_area = min(len(left_mask), len(right_mask))
    if smaller_area == 0:
        return 0.0
    return len(left_mask & right_mask) / smaller_area


def _priority(prediction: MappedPrediction) -> tuple[float, str, int, str]:
    return (
        -prediction.score,
        prediction.cluster_id,
        prediction.proposal_order,
        prediction.prediction_id,
    )


def reconcile_predictions(
    predictions: Sequence[MappedPrediction],
    *,
    frame_width: int,
    frame_height: int,
    iou_threshold: float = DUPLICATE_IOU_THRESHOLD,
) -> ReconciliationResult:
    """Suppress only near-identical mapped predictions.

    Both tight-box IoU and visible-mask IoU must meet the threshold.  This intentionally retains
    distinct overlapping cards when their visible masks differ.
    """

    _positive_int(frame_width, "frame_width")
    _positive_int(frame_height, "frame_height")
    threshold = _finite_number(iou_threshold, "duplicate IoU threshold")
    if not 0 <= threshold <= 1:
        raise CascadeContractError("duplicate IoU threshold must be in [0, 1]")
    identifiers = [prediction.prediction_id for prediction in predictions]
    if len(set(identifiers)) != len(identifiers):
        raise CascadeContractError("prediction IDs must be unique")

    comparisons: dict[tuple[str, str], tuple[float, float, bool]] = {}
    decisions: list[ReconciliationDecision] = []
    mask_cache = {
        id(prediction): _polygon_mask(prediction, width=frame_width, height=frame_height)
        for prediction in predictions
        if prediction.mask is None
    }
    for left_index, left in enumerate(predictions):
        for right in predictions[left_index + 1 :]:
            box_iou = _box_iou(left.box, right.box)
            mask_iou = _mask_iou(
                left,
                right,
                width=frame_width,
                height=frame_height,
                mask_cache=mask_cache,
            )
            mask_containment = _mask_containment(
                left,
                right,
                width=frame_width,
                height=frame_height,
                mask_cache=mask_cache,
            )
            box_containment = _box_containment(left.box, right.box)
            smaller_box_area = min(
                left.box.width * left.box.height,
                right.box.width * right.box.height,
            )
            larger_box_area = max(
                left.box.width * left.box.height,
                right.box.width * right.box.height,
            )
            nested_duplicate = (
                mask_containment >= DUPLICATE_MASK_CONTAINMENT_THRESHOLD
                and box_containment >= DUPLICATE_MASK_CONTAINMENT_THRESHOLD
                and smaller_box_area / larger_box_area <= DUPLICATE_BOX_AREA_RATIO_MAX
            )
            duplicate = (box_iou >= threshold and mask_iou >= threshold) or nested_duplicate
            comparisons[(left.prediction_id, right.prediction_id)] = (box_iou, mask_iou, duplicate)
            decisions.append(
                ReconciliationDecision(
                    left_prediction_id=left.prediction_id,
                    right_prediction_id=right.prediction_id,
                    box_iou=box_iou,
                    mask_iou=mask_iou,
                    duplicate=duplicate,
                    kept_prediction_id=None,
                    discarded_prediction_id=None,
                )
            )

    retained: list[MappedPrediction] = []
    discarded: list[MappedPrediction] = []
    for candidate in sorted(predictions, key=_priority):
        duplicate_with = next(
            (
                existing
                for existing in retained
                if comparisons.get(
                    (existing.prediction_id, candidate.prediction_id),
                    comparisons.get(
                        (candidate.prediction_id, existing.prediction_id), (0, 0, False)
                    ),
                )[2]
            ),
            None,
        )
        if duplicate_with is None:
            retained.append(candidate)
            continue
        discarded.append(candidate)
        for index, decision in enumerate(decisions):
            if {decision.left_prediction_id, decision.right_prediction_id} == {
                duplicate_with.prediction_id,
                candidate.prediction_id,
            }:
                decisions[index] = ReconciliationDecision(
                    left_prediction_id=decision.left_prediction_id,
                    right_prediction_id=decision.right_prediction_id,
                    box_iou=decision.box_iou,
                    mask_iou=decision.mask_iou,
                    duplicate=True,
                    kept_prediction_id=duplicate_with.prediction_id,
                    discarded_prediction_id=candidate.prediction_id,
                )
                break
    retained.sort(key=lambda prediction: predictions.index(prediction))
    discarded.sort(key=lambda prediction: predictions.index(prediction))
    return ReconciliationResult(tuple(retained), tuple(discarded), tuple(decisions))


@dataclass(frozen=True, slots=True)
class StageBundleIdentity:
    """Immutable identity for one cascade model stage."""

    stage: Literal["coarse", "fine"]
    model_class: str
    input_size: int
    bundle_digest: str
    checkpoint_sha256: str
    device: str = CASCADE_DEVICE
    package_name: str = "rfdetr"
    package_version: str = CASCADE_RFDETR_VERSION
    class_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.stage not in {"coarse", "fine"}:
            raise CascadeContractError("stage must be coarse or fine")
        expected_class = (
            CASCADE_COARSE_MODEL_CLASS if self.stage == "coarse" else CASCADE_FINE_MODEL_CLASS
        )
        expected_size = (
            CASCADE_COARSE_INPUT_SIZE if self.stage == "coarse" else CASCADE_FINE_INPUT_SIZE
        )
        expected_names = (
            (CASCADE_COARSE_CLASS_NAME,) if self.stage == "coarse" else (CASCADE_FINE_CLASS_NAME,)
        )
        if not self.class_names:
            object.__setattr__(self, "class_names", expected_names)
        if self.model_class != expected_class:
            raise CascadeContractError(f"{self.stage} stage must use {expected_class}")
        if self.input_size != expected_size:
            raise CascadeContractError(
                f"{self.stage} stage input size is frozen at {expected_size}"
            )
        _digest(self.bundle_digest, "bundle_digest")
        _digest(self.checkpoint_sha256, "checkpoint_sha256")
        if self.device not in CASCADE_SUPPORTED_DEVICES:
            raise CascadeContractError("device must be cpu, mps, or cuda")
        if self.package_name != "rfdetr" or self.package_version != CASCADE_RFDETR_VERSION:
            raise CascadeContractError("RF-DETR package identity is not the frozen 1.9.4 contract")
        if self.class_names != expected_names:
            raise CascadeContractError(f"{self.stage} stage class names are frozen")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "model": {"class": self.model_class, "input_size": self.input_size},
            "class_names": list(self.class_names),
            "bundle_digest": self.bundle_digest,
            "checkpoint_sha256": self.checkpoint_sha256,
            "package": {"name": self.package_name, "version": self.package_version},
            "device": self.device,
        }


@dataclass(frozen=True, slots=True)
class CascadeBundleIdentity:
    """Identity and frozen recipes for both cascade stages."""

    coarse: StageBundleIdentity
    fine: StageBundleIdentity
    cluster_recipe_version: str = CLUSTER_SCHEMA_VERSION
    crop_recipe_version: str = CROP_SCHEMA_VERSION
    reconciliation_recipe_version: str = RECONCILIATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.coarse.stage != "coarse" or self.fine.stage != "fine":
            raise CascadeContractError("cascade stages must be coarse then fine")
        if self.cluster_recipe_version != CLUSTER_SCHEMA_VERSION:
            raise CascadeContractError("cluster recipe version is not the frozen M0 contract")
        if self.crop_recipe_version != CROP_SCHEMA_VERSION:
            raise CascadeContractError("crop recipe version is not the frozen M0 contract")
        if self.reconciliation_recipe_version != RECONCILIATION_SCHEMA_VERSION:
            raise CascadeContractError(
                "reconciliation recipe version is not the frozen M0 contract"
            )

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_mapping())

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": CASCADE_SCHEMA_VERSION,
            "coarse": self.coarse.to_mapping(),
            "fine": self.fine.to_mapping(),
            "recipes": {
                "cluster": self.cluster_recipe_version,
                "crop": self.crop_recipe_version,
                "reconciliation": self.reconciliation_recipe_version,
            },
            "neutral_padding_rgb": list(NEUTRAL_PADDING_RGB),
            "duplicate_iou_threshold": DUPLICATE_IOU_THRESHOLD,
        }


def frozen_cascade_recipe() -> dict[str, Any]:
    """Return the M0 recipe that later training and runtime manifests must embed."""

    return {
        "schema_version": CASCADE_SCHEMA_VERSION,
        "coarse": {
            "model_class": CASCADE_COARSE_MODEL_CLASS,
            "model_variant": CASCADE_COARSE_MODEL_VARIANT,
            "class_names": [CASCADE_COARSE_CLASS_NAME],
            "input_size": [CASCADE_COARSE_INPUT_SIZE, CASCADE_COARSE_INPUT_SIZE],
            "confidence_threshold": CASCADE_COARSE_CONFIDENCE_THRESHOLD,
        },
        "fine": {
            "model_class": CASCADE_FINE_MODEL_CLASS,
            "model_variant": CASCADE_FINE_MODEL_VARIANT,
            "class_names": [CASCADE_FINE_CLASS_NAME],
            "input_size": [CASCADE_FINE_INPUT_SIZE, CASCADE_FINE_INPUT_SIZE],
        },
        "package": {"name": "rfdetr", "version": CASCADE_RFDETR_VERSION},
        "devices": {"default": CASCADE_DEVICE, "supported": sorted(CASCADE_SUPPORTED_DEVICES)},
        "cluster_recipe": {
            "schema_version": CLUSTER_SCHEMA_VERSION,
            "reference_span": "median_shorter_side",
            "expansion": "half_reference_span_each_edge",
            "connectivity": "transitive_intersection_of_expanded_boxes",
            "crop": "square_around_union_center_with_out_of_frame_padding",
        },
        "crop_recipe": {
            "schema_version": CROP_SCHEMA_VERSION,
            "padding_rgb": list(NEUTRAL_PADDING_RGB),
            "coordinate_convention": "continuous_pixel_edges",
        },
        "reconciliation_recipe": {
            "schema_version": RECONCILIATION_SCHEMA_VERSION,
            "duplicate_rule": "box_iou_and_visible_mask_iou",
            "threshold": DUPLICATE_IOU_THRESHOLD,
            "tie_break": ["cluster_id", "proposal_order", "prediction_id"],
        },
    }


__all__ = [
    "CASCADE_COARSE_CLASS_NAME",
    "CASCADE_COARSE_CONFIDENCE_THRESHOLD",
    "CASCADE_COARSE_INPUT_SIZE",
    "CASCADE_COARSE_MODEL_CLASS",
    "CASCADE_DEVICE",
    "CASCADE_FINE_CLASS_NAME",
    "CASCADE_FINE_INPUT_SIZE",
    "CASCADE_FINE_MODEL_CLASS",
    "CASCADE_RFDETR_VERSION",
    "CascadeBundleIdentity",
    "CascadeContractError",
    "CascadeLayout",
    "CardCluster",
    "ClusterCrop",
    "CoarseProposal",
    "CoordinateTransform",
    "DUPLICATE_BOX_AREA_RATIO_MAX",
    "DUPLICATE_IOU_THRESHOLD",
    "DUPLICATE_MASK_CONTAINMENT_THRESHOLD",
    "MappedPrediction",
    "NEUTRAL_PADDING_RGB",
    "Padding",
    "PixelBox",
    "PixelPoint",
    "ReconciliationDecision",
    "ReconciliationResult",
    "StageBundleIdentity",
    "build_cascade_layout",
    "frozen_cascade_recipe",
    "reconcile_predictions",
]
