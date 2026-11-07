"""Per-card classification and classifier selection for visual identity jobs."""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from doko_operations.derived_view import (
    DerivedViewError,
    FrameResolver,
    resolve_exact_event,
    resolve_visible_region_crop,
)
from doko_operations.pipeline_data import ProcessorRunRequest
from table_evidence_analyzer.pipeline_data import (
    PipelineGeometry,
    VisualIdentityCandidate,
    VisualIdentityClassifierIdentity,
    VisualIdentityCropIdentity,
    VisualIdentityCropInputProvenance,
    VisualIdentityOutcome,
)
from table_evidence_analyzer.visual_identity import (
    CardIdentityClassifierProvider,
    VisualIdentityClassifierProvider,
    VisualIdentityRequest,
)
from table_evidence_analyzer.visual_identity_crop_input import VisualIdentityCropInputItem

from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_store import PipelineRuntimeStorage, StoredProcessorRun
from dokodetector_backend.visual_identity_crop_resolution import crop_identity_mapping
from dokodetector_backend.visual_identity_pipeline_errors import (
    VisualIdentityPipelineError,
    VisualIdentityPipelineInputError,
)
from dokodetector_backend.visual_identity_request import (
    _crop_policy_for_geometry,
    _default_crop_policy_for_geometry,
    configuration_provider,
)

LOGGER = logging.getLogger(__name__)
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._:-]+")


def _safe(value: str) -> str:
    return _SAFE_COMPONENT.sub("-", value).strip("-") or "unknown"


def _implementation_id(identity: Any) -> str:
    return _safe(identity.name) + "." + _safe(identity.version)


def _model_id(model: Any | None) -> str | None:
    return None if model is None else _safe(model.name) + "." + _safe(model.version)


def _result_latency_ms(result: Any) -> float | None:
    value = getattr(result, "latency_ms", None)
    return float(value) if isinstance(value, (int, float)) else None


class VisualIdentityClassification:
    """Select the requested classifier and classify one exact crop."""

    def __init__(
        self,
        settings: Settings,
        *,
        classifier: Any | None,
        identity_classifiers: Mapping[str, Any] | None,
        storage: PipelineRuntimeStorage,
        frame_resolver: FrameResolver,
        derived_view_lock: RLock,
        video_path_for_recording: Callable[[str], Path],
        cloud_max_concurrent_requests: int,
        local_max_concurrent_requests: int,
    ) -> None:
        self.settings = settings
        self.classifier = self._adapt_classifier(classifier)
        self.identity_classifiers = identity_classifiers
        self.storage = storage
        self.frame_resolver = frame_resolver
        self._derived_view_lock = derived_view_lock
        self.video_path_for_recording = video_path_for_recording
        self.cloud_max_concurrent_requests = cloud_max_concurrent_requests
        self.local_max_concurrent_requests = local_max_concurrent_requests

    def process_card(
        self,
        run: StoredProcessorRun,
        visible_outcome: Any,
        card: Any,
        crop_item: VisualIdentityCropInputItem,
        item_id: str,
        provenance: VisualIdentityCropInputProvenance | None,
        frame_cache: OrderedDict[tuple[int, str], Any],
        *,
        timings: dict[str, float | None] | None = None,
    ) -> VisualIdentityOutcome:
        assert visible_outcome.frame_identity is not None
        frame_identity = visible_outcome.frame_identity
        geometry: PipelineGeometry = card.geometry
        classifier_identity = self.classifier_identity(run.request)
        frame = None
        try:
            started = time.monotonic()
            with self._derived_view_lock:
                key = (frame_identity.requested_time_us, frame_identity.output_encoding)
                frame = frame_cache.get(key)
                if frame is None:
                    frame = resolve_exact_event(
                        self.video_path_for_recording(run.request.source.recording_id),
                        source=run.request.source,
                        requested_time_us=frame_identity.requested_time_us,
                        cache=self.storage.derived_views_root,
                        resolver=self.frame_resolver,
                        output_encoding=frame_identity.output_encoding,
                        validate_source=False,
                    )
                    frame_cache[key] = frame
                    if len(frame_cache) > 4:
                        frame_cache.popitem(last=False)
                else:
                    frame_cache.move_to_end(key)
            if frame.identity_mapping() != frame_identity.to_mapping():
                raise DerivedViewError("the resolved frame identity changed")
        except (DerivedViewError, OSError, RuntimeError):
            return VisualIdentityOutcome(
                card_id=item_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=None,
                classifier=classifier_identity,
                status="failed",
                candidates=(),
                error="The exact visible-card frame is unavailable.",
                crop_input_provenance=provenance,
            )
        finally:
            if timings is not None:
                timings["frame_resolve_ms"] = round(
                    max(0.0, time.monotonic() - started) * 1000.0, 3
                )

        try:
            started = time.monotonic()
            crop_policy = run.request.crop_policy or {}
            crop_policy_id = crop_policy.get("policy_id")
            if crop_policy_id is None:
                crop_policy_id = _default_crop_policy_for_geometry(geometry)["policy_id"]
            crop_policy_id = _crop_policy_for_geometry(str(crop_policy_id), geometry)
            with self._derived_view_lock:
                crop = resolve_visible_region_crop(
                    frame,
                    geometry.to_mapping(),
                    crop_policy=str(crop_policy_id),
                    output_encoding=str(crop_policy.get("output_encoding", "ppm")),
                    cache=self.storage.derived_views_root,
                )
            crop_identity = VisualIdentityCropIdentity.from_mapping(crop_identity_mapping(crop))
        except (DerivedViewError, OSError, RuntimeError, ValueError):
            return VisualIdentityOutcome(
                card_id=item_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=None,
                classifier=classifier_identity,
                status="failed",
                candidates=(),
                error="The visible-card identity crop is unavailable.",
                crop_input_provenance=provenance,
            )
        finally:
            if timings is not None:
                timings["crop_ms"] = round(max(0.0, time.monotonic() - started) * 1000.0, 3)
        if card.side == "face_down":
            return VisualIdentityOutcome(
                card_id=item_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=crop_identity,
                classifier=classifier_identity,
                status="face_down",
                candidates=(),
                crop_input_provenance=provenance,
            )
        if not crop_item.identity_usable:
            return VisualIdentityOutcome(
                card_id=item_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=crop_identity,
                classifier=classifier_identity,
                status="unusable",
                candidates=(),
                unusable_reason=(
                    ", ".join(crop_item.failure_tags)
                    or "The selected crop input marks this identity as unusable."
                ),
                crop_input_provenance=provenance,
            )
        if crop.status == "unusable":
            return VisualIdentityOutcome(
                card_id=item_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=crop_identity,
                classifier=classifier_identity,
                status="unusable",
                candidates=(),
                unusable_reason=crop.unusable_reason,
                crop_input_provenance=provenance,
            )
        classifier_started: float | None = None
        try:
            assert crop.image_bytes is not None
            classifier = self.classifier_for_request(run.request)
            if classifier is None:
                raise VisualIdentityPipelineError("The visual identity classifier is unavailable.")
            request = VisualIdentityRequest(
                card_id=item_id,
                provider=classifier.name,
                model=run.request.model.name if run.request.model is not None else "unknown",
                crop_bytes=crop.image_bytes,
            )
            classifier_started = time.monotonic()
            result = classifier.classify(request)
            if timings is not None:
                timings["classifier_latency_ms"] = _result_latency_ms(result)
            if result.status == "unavailable":
                return VisualIdentityOutcome(
                    card_id=item_id,
                    frame_identity=frame_identity,
                    geometry=geometry,
                    crop_identity=crop_identity,
                    classifier=classifier_identity,
                    status="failed",
                    candidates=(),
                    error=result.error or "The visual identity classifier failed for this card.",
                    crop_input_provenance=provenance,
                )
            if result.classification == "face_down":
                return VisualIdentityOutcome(
                    card_id=item_id,
                    frame_identity=frame_identity,
                    geometry=geometry,
                    crop_identity=crop_identity,
                    classifier=classifier_identity,
                    status="face_down",
                    candidates=(),
                    crop_input_provenance=provenance,
                )
            if result.classification == "unknown" or not result.candidates:
                return VisualIdentityOutcome(
                    card_id=item_id,
                    frame_identity=frame_identity,
                    geometry=geometry,
                    crop_identity=crop_identity,
                    classifier=classifier_identity,
                    status="unusable",
                    candidates=(),
                    unusable_reason="The classifier returned no identity candidates.",
                    crop_input_provenance=provenance,
                )
            if result.classification != "identity":
                raise VisualIdentityPipelineError(
                    "The visual identity classifier returned an unsupported classification."
                )
            candidates = tuple(
                VisualIdentityCandidate(
                    identity=identity.card,
                    score=identity.probability,
                    score_meaning="probability",
                    producer_id=_model_id(run.request.model)
                    or _implementation_id(run.request.implementation),
                )
                for identity in result.candidates
            )
        except Exception:
            return VisualIdentityOutcome(
                card_id=item_id,
                frame_identity=frame_identity,
                geometry=geometry,
                crop_identity=crop_identity,
                classifier=classifier_identity,
                status="failed",
                candidates=(),
                error="The visual identity classifier failed for this card.",
                crop_input_provenance=provenance,
            )
        finally:
            if timings is not None and classifier_started is not None:
                timings["classifier_wall_time_ms"] = round(
                    max(0.0, time.monotonic() - classifier_started) * 1000.0, 3
                )
        return VisualIdentityOutcome(
            card_id=item_id,
            frame_identity=frame_identity,
            geometry=geometry,
            crop_identity=crop_identity,
            classifier=classifier_identity,
            status="classified",
            candidates=candidates,
            crop_input_provenance=provenance,
        )

    def process_card_timed(
        self,
        run: StoredProcessorRun,
        visible_outcome: Any,
        card: Any,
        crop_item: VisualIdentityCropInputItem,
        item_id: str,
        provenance: VisualIdentityCropInputProvenance | None,
        frame_cache: OrderedDict[tuple[int, str], Any],
    ) -> VisualIdentityOutcome:
        started = time.monotonic()
        timings: dict[str, float | None] = {}
        try:
            return self.process_card(
                run,
                visible_outcome,
                card,
                crop_item,
                item_id,
                provenance,
                frame_cache,
                timings=timings,
            )
        finally:
            LOGGER.info(
                "visual_identity_card_timing",
                extra={
                    "event_name": "visual_identity_card_timing",
                    "run_id": run.run_id,
                    "card_id": item_id,
                    "item_wall_time_ms": round(max(0.0, time.monotonic() - started) * 1000.0, 3),
                    **timings,
                    "timing_scope": (
                        "wall-clock item timing with derived-view and classifier stages"
                    ),
                },
            )

    def max_concurrent_requests(self, request: ProcessorRunRequest) -> int:
        classifier = self.classifier_for_request(request)
        if classifier is not None and getattr(classifier, "name", None) == "local-dinov3":
            return self.local_max_concurrent_requests
        return self.cloud_max_concurrent_requests

    def classifier_identity(self, request: ProcessorRunRequest) -> VisualIdentityClassifierIdentity:
        model = request.model
        classifier = self.classifier_for_request(request)
        if model is None or classifier is None:
            raise VisualIdentityPipelineError("The visual identity classifier identity is missing.")
        return VisualIdentityClassifierIdentity(
            provider=classifier.name,
            implementation_name=request.implementation.name,
            implementation_version=request.implementation.version,
            model_name=model.name,
            model_version=model.version,
        )

    def classifier_for_selection(self, requested_provider: str | None) -> Any | None:
        if requested_provider is None:
            if self.classifier is not None:
                return self.classifier
            requested_provider = getattr(self.settings, "visible_card_identity_classifier", None)
            if requested_provider is None:
                return None
        if requested_provider == "cloud":
            candidates = ("gemini", "cloud")
        elif requested_provider == "local":
            candidates = ("local",)
        elif requested_provider.startswith("local-"):
            # Durable requests store the concrete classifier name, while the lazy registry
            # exposes the configured local implementation under its logical provider name.
            candidates = (requested_provider, "local")
        else:
            candidates = (requested_provider,)
        if self.identity_classifiers is not None:
            for candidate in candidates:
                try:
                    classifier = self.identity_classifiers.get(candidate)
                except (KeyError, ValueError, RuntimeError) as error:
                    raise VisualIdentityPipelineInputError(str(error)) from error
                if classifier is not None:
                    return self._adapt_classifier(classifier)
        current = self.classifier
        if current is not None and requested_provider in {
            current.name,
            "cloud" if current.name == "gemini" else None,
            "local" if current.name.startswith("local") else None,
        }:
            return current
        return None

    def classifier_for_request(self, request: ProcessorRunRequest) -> Any | None:
        classifier = self.classifier_for_selection(configuration_provider(request.configuration))
        if classifier is not None:
            underlying = getattr(classifier, "classifier", classifier)
            for field, actual in (
                ("bundle_identity", getattr(underlying, "bundle_identity", None)),
                ("device", getattr(underlying, "device", None)),
            ):
                if field in request.configuration and request.configuration[field] != actual:
                    raise VisualIdentityPipelineError(
                        f"The identity {field} changed since this run was created. Start a new run."
                    )
        return classifier

    @staticmethod
    def _adapt_classifier(classifier: Any | None) -> VisualIdentityClassifierProvider | None:
        if classifier is None:
            return None
        if isinstance(classifier, VisualIdentityClassifierProvider):
            return classifier
        return CardIdentityClassifierProvider(classifier)
