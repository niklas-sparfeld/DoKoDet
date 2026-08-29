"""Adapt visible-card proposals and crop identities into table observations.

The adapter keeps localization and identity provenance separate.  The provider owns the polygon;
the exported identity bundle owns the ranked card candidates; this module only joins both outputs
inside the canonical ``table-observation/v1`` contract.
"""

from __future__ import annotations

import hashlib
import math
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .analyzer import AnalyzerEvidence, AnalyzerFrame
from .export import CapabilityBundle
from .table_observation import (
    OBSERVATION_SCHEMA_VERSION,
    AnalyzerMetadata,
    ObservationSession,
    ObservationSource,
    ObservedCard,
    TableObservation,
    canonical_json_bytes,
)
from .visible_cards import (
    DEFAULT_MODEL,
    PREDICTION_SCHEMA_VERSION,
    ProviderResult,
    VisibleCardProposal,
    VisibleCardProvider,
    VisibleCardRequest,
)

OBSERVATION_ADAPTER_SCHEMA = "visible-card-observation-adapter/v1"
POLYGON_CROP_SCHEMA = "visible-card-polygon-crop/v1"
DEFAULT_ANALYZER_NAME = "visible-card-table-analyzer"
DEFAULT_ANALYZER_VERSION = OBSERVATION_ADAPTER_SCHEMA


class ObservationAdapterError(ValueError):
    """Raised when a visible-card result cannot be adapted to a table observation."""


@dataclass(frozen=True, slots=True)
class PixelBounds:
    """An exclusive pixel rectangle derived from a normalized proposal polygon."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    @property
    def height(self) -> int:
        return self.y_max - self.y_min

    def to_mapping(self) -> dict[str, int]:
        return {
            "x_min": self.x_min,
            "y_min": self.y_min,
            "x_max": self.x_max,
            "y_max": self.y_max,
        }


def polygon_pixel_bounds(proposal: VisibleCardProposal, *, width: int, height: int) -> PixelBounds:
    """Convert a normalized polygon's visible extent into an exclusive pixel rectangle."""

    if width <= 0 or height <= 0:
        raise ObservationAdapterError("source image dimensions must be positive")
    x_values = [point.x for point in proposal.polygon]
    y_values = [point.y for point in proposal.polygon]
    bounds = PixelBounds(
        x_min=max(0, math.floor(min(x_values) * width / 1000)),
        y_min=max(0, math.floor(min(y_values) * height / 1000)),
        x_max=min(width, math.ceil(max(x_values) * width / 1000)),
        y_max=min(height, math.ceil(max(y_values) * height / 1000)),
    )
    if bounds.width <= 0 or bounds.height <= 0:
        raise ObservationAdapterError("proposal polygon has no positive pixel crop")
    return bounds


def polygon_to_ppm(
    image_bytes: bytes,
    proposal: VisibleCardProposal,
    *,
    width: int,
    height: int,
) -> tuple[bytes, PixelBounds]:
    """Decode a source image and return the polygon bounding crop as binary PPM bytes."""

    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ObservationAdapterError("source image bytes must be non-empty")
    bounds = polygon_pixel_bounds(proposal, width=width, height=height)
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.size != (width, height):
                raise ObservationAdapterError(
                    "decoded source image dimensions do not match the request dimensions"
                )
            crop = image.convert("RGB").crop(
                (bounds.x_min, bounds.y_min, bounds.x_max, bounds.y_max)
            )
            if crop.width < 4 or crop.height < 4:
                raise ObservationAdapterError("proposal crop must be at least 4x4 pixels")
            pixels = crop.tobytes()
    except UnidentifiedImageError as error:
        raise ObservationAdapterError("source image cannot be decoded") from error
    except OSError as error:
        raise ObservationAdapterError(f"source image cannot be decoded: {error}") from error
    return f"P6\n{bounds.width} {bounds.height}\n255\n".encode() + pixels, bounds


def _read_frame(frame: AnalyzerFrame) -> bytes:
    if frame.jpeg_bytes is not None:
        return frame.jpeg_bytes
    assert frame.local_reference is not None
    try:
        return Path(frame.local_reference).read_bytes()
    except OSError as error:
        raise ObservationAdapterError("an analyzer frame could not be read") from error


def _select_frame(evidence: AnalyzerEvidence) -> AnalyzerFrame:
    if not evidence.frames:
        raise ObservationAdapterError("analyzer evidence contains no frames")
    return min(
        evidence.frames,
        key=lambda frame: (abs(frame.actual_offset_ms), frame.actual_offset_ms, frame.part_name),
    )


def _provider_name(provider: VisibleCardProvider) -> str:
    current: Any = provider
    while getattr(current, "name", None) == "cached" and hasattr(current, "provider"):
        current = current.provider
    name = getattr(current, "name", None)
    if not isinstance(name, str) or not name:
        raise ObservationAdapterError("visible-card provider must expose a non-empty name")
    return name


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _observation_id(request: VisibleCardRequest) -> str:
    return f"observation-{request.package_id}-{request.frame_part_name}"


def _bundle_calibration(bundle: CapabilityBundle) -> str:
    calibration = bundle.manifest.get("calibration")
    if calibration not in {"fixture", "uncalibrated", "calibrated"}:
        raise ObservationAdapterError("identity bundle has an unsupported calibration state")
    return calibration


def _diagnostics(
    request: VisibleCardRequest,
    result: ProviderResult,
    bundle: CapabilityBundle,
    *,
    actual_offset_ms: int,
    classified: list[dict[str, Any]],
    dropped: list[dict[str, Any]],
    reason: str | None = None,
) -> dict[str, Any]:
    provider: dict[str, Any] = {
        "name": request.provider,
        "model": request.model,
        "status": result.status,
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "total_tokens": result.usage.total_tokens,
        "latency_ms": result.latency_ms,
        "retry_count": result.retry_count,
        "estimated_cost_usd": result.estimated_cost_usd,
    }
    if result.error is not None:
        provider["error"] = result.error
    diagnostics: dict[str, Any] = {
        "adapter_schema_version": OBSERVATION_ADAPTER_SCHEMA,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "crop_schema_version": POLYGON_CROP_SCHEMA,
        "provider": provider,
        "identity_bundle": {
            "schema_version": bundle.manifest.get("schema_version"),
            "run_id": bundle.manifest.get("run_id"),
            "calibration": bundle.manifest.get("calibration"),
        },
        "frame_part_name": request.frame_part_name,
        "target_offset_ms": request.target_offset_ms,
        "actual_offset_ms": actual_offset_ms,
        "source_image_sha256": request.image_sha256,
        "proposal_count": len(result.proposals),
        "classified_proposal_count": len(classified),
        "dropped_proposal_count": len(dropped),
        "classified_proposals": classified,
        "dropped_proposals": dropped,
    }
    if reason is not None:
        diagnostics["reason"] = reason
    return diagnostics


def adapt_visible_card_result(
    request: VisibleCardRequest,
    result: ProviderResult,
    bundle: CapabilityBundle,
    *,
    observed_at_ms: int,
    session_id: str,
    event_sequence: int,
    actual_offset_ms: int = 0,
    observation_id: str | None = None,
    analyzer_name: str = DEFAULT_ANALYZER_NAME,
    analyzer_version: str = DEFAULT_ANALYZER_VERSION,
) -> TableObservation:
    """Convert one visible-card provider result into a validated table observation."""

    if observed_at_ms < 0 or event_sequence < 1:
        raise ObservationAdapterError("observation time and event sequence must be positive")
    if not session_id or not analyzer_name or not analyzer_version:
        raise ObservationAdapterError("session and analyzer identifiers must be non-empty")
    calibration = _bundle_calibration(bundle)
    observation_id = observation_id or _observation_id(request)
    cards: list[ObservedCard] = []
    classified: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    if result.status == "ok":
        for proposal_index, proposal in enumerate(result.proposals):
            try:
                crop_bytes, bounds = polygon_to_ppm(
                    request.image_bytes,
                    proposal,
                    width=request.width,
                    height=request.height,
                )
                candidates = bundle.classify_bytes(crop_bytes)
                if not candidates:
                    raise ObservationAdapterError("identity bundle returned no candidates")
            except (ObservationAdapterError, ValueError) as error:
                dropped.append({"proposal_index": proposal_index, "reason": str(error)})
                continue
            card_id = f"{observation_id}-card-{proposal_index + 1:02d}"
            cards.append(
                ObservedCard(
                    observed_card_id=card_id,
                    identity_candidates=candidates,
                )
            )
            classified.append(
                {
                    "proposal_index": proposal_index,
                    "observed_card_id": card_id,
                    "side": proposal.side,
                    "crop_bounds": bounds.to_mapping(),
                    "crop_sha256": _sha256(crop_bytes),
                }
            )

    if result.status == "unavailable":
        status = "insufficient_evidence"
        reason = "visible-card provider unavailable"
    elif result.proposals and not cards:
        status = "insufficient_evidence"
        reason = "no detected proposal produced a usable identity crop"
    else:
        status = "observed"
        reason = None

    observation = TableObservation(
        schema_version=OBSERVATION_SCHEMA_VERSION,
        observation_id=observation_id,
        source=ObservationSource(package_id=request.package_id),
        session=ObservationSession(session_id=session_id, event_sequence=event_sequence),
        observed_at_ms=observed_at_ms,
        status=status,
        capabilities=["identity_candidates"],
        cards=cards,
        calibration=calibration,
        analyzer=AnalyzerMetadata(name=analyzer_name, version=analyzer_version),
        diagnostics=_diagnostics(
            request,
            result,
            bundle,
            actual_offset_ms=actual_offset_ms,
            classified=classified,
            dropped=dropped,
            reason=reason,
        ),
    )
    return observation


class VisibleCardTableAnalyzer:
    """Run visible-card detection and exported identity classification as one analyzer."""

    name = DEFAULT_ANALYZER_NAME
    version = DEFAULT_ANALYZER_VERSION

    def __init__(
        self,
        provider: VisibleCardProvider,
        bundle: CapabilityBundle,
        *,
        model: str = DEFAULT_MODEL,
        session_id: str | None = None,
        event_sequence: int = 1,
    ) -> None:
        if not model:
            raise ObservationAdapterError("model must be non-empty")
        if event_sequence < 1:
            raise ObservationAdapterError("event_sequence must be positive")
        self.provider = provider
        self.bundle = bundle
        self.model = model
        self.session_id = session_id
        self.event_sequence = event_sequence

    def analyze(self, evidence: AnalyzerEvidence) -> TableObservation:
        """Analyze the frame nearest the event and return one validated observation."""

        try:
            frame = _select_frame(evidence)
            image_bytes = _read_frame(frame)
        except ObservationAdapterError as error:
            return self._insufficient_without_provider(evidence, str(error))

        request = VisibleCardRequest(
            package_id=str(evidence.package_id),
            frame_part_name=frame.part_name,
            target_offset_ms=0,
            image_bytes=image_bytes,
            width=frame.width,
            height=frame.height,
            model=self.model,
            provider=_provider_name(self.provider),
        )
        result = self.provider.propose(request)
        return adapt_visible_card_result(
            request,
            result,
            self.bundle,
            observed_at_ms=evidence.event_time_ms,
            session_id=self.session_id or str(evidence.package_id),
            event_sequence=self.event_sequence,
            actual_offset_ms=frame.actual_offset_ms,
            analyzer_name=self.name,
            analyzer_version=self.version,
        )

    def _insufficient_without_provider(
        self, evidence: AnalyzerEvidence, reason: str
    ) -> TableObservation:
        return TableObservation(
            schema_version=OBSERVATION_SCHEMA_VERSION,
            observation_id=f"observation-{evidence.package_id}",
            source=ObservationSource(package_id=str(evidence.package_id)),
            session=ObservationSession(
                session_id=self.session_id or str(evidence.package_id),
                event_sequence=self.event_sequence,
            ),
            observed_at_ms=evidence.event_time_ms,
            status="insufficient_evidence",
            capabilities=["identity_candidates"],
            cards=[],
            calibration=_bundle_calibration(self.bundle),
            analyzer=AnalyzerMetadata(name=self.name, version=self.version),
            diagnostics={
                "adapter_schema_version": OBSERVATION_ADAPTER_SCHEMA,
                "reason": reason,
            },
        )


def write_observation(observation: TableObservation, path: str | Path) -> Path:
    """Write one canonical observation atomically."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        fd, temporary_path = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        with open(fd, "wb", closefd=True) as temporary:
            temporary.write(canonical_json_bytes(observation) + b"\n")
            temporary.flush()
        Path(temporary_path).replace(destination)
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)
    return destination


__all__ = [
    "DEFAULT_ANALYZER_NAME",
    "DEFAULT_ANALYZER_VERSION",
    "OBSERVATION_ADAPTER_SCHEMA",
    "POLYGON_CROP_SCHEMA",
    "ObservationAdapterError",
    "PixelBounds",
    "VisibleCardTableAnalyzer",
    "adapt_visible_card_result",
    "polygon_pixel_bounds",
    "polygon_to_ppm",
    "write_observation",
]
