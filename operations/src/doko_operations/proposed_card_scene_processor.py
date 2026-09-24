"""Create immutable proposed card scenes from one generated visible-card result.

This processor is deliberately separate from maintained-reference review.  It reuses the 0072
recording calibration and pose initializer, then wraps each result in the 0073 proposal contract.
The detector revision is read-only input and the returned proposals are never reviewed authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from table_evidence_analyzer.card_scene_contract import ProposedCardScene
from table_evidence_analyzer.pipeline_data import (
    PredictedVisibleRegionGeometry,
    ProposedCardSceneData,
    ProposedCardSceneFrame,
    VisibleCardData,
)

from .card_plane_calibration import (
    CalibrationRecipe,
    CalibrationRevisionStore,
    CalibrationRun,
    calibrate_recording,
)
from .card_plane_initialization import (
    INITIALIZATION_PROCESSOR_SCHEMA_VERSION,
    PoseFitRecipe,
    initialize_card_scene,
)
from .pipeline_data import canonical_json_bytes

PROPOSED_CARD_SCENE_PROCESSOR_SCHEMA_VERSION = "proposed-card-scene-processor/v1"
PROPOSED_CARD_SCENE_PROCESSOR_TYPE = "visible-card-scene-proposal"


class ProposedCardSceneProcessorError(ValueError):
    """Raised when a generated visible-card result cannot be used for proposals."""


ProgressCallback = Callable[[str, int, int, str, int, int], None]


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProposedCardSceneProcessorError(f"{field} must be an object")
    return value


def _source_frame_digest(frame: Mapping[str, Any]) -> str | None:
    value = frame.get("source_frame_digest")
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise ProposedCardSceneProcessorError("source_frame_digest must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise ProposedCardSceneProcessorError(
            "source_frame_digest must be a SHA-256 digest"
        ) from error
    return value


def visible_card_data_to_local_result(
    data: VisibleCardData,
    *,
    recording_id: str,
    source_revision: str,
) -> dict[str, Any]:
    """Convert typed detector outcomes to the 0072 processor input shape."""

    if not isinstance(data, VisibleCardData):
        raise ProposedCardSceneProcessorError("visible-card input must be VisibleCardData")
    frames: list[dict[str, Any]] = []
    unresolvable_frames: list[dict[str, str]] = []
    for outcome in data.outcomes:
        identity = outcome.frame_identity
        if identity is None:
            unresolvable_frames.append(
                {"frame_id": outcome.event_id, "reason": "source_frame_unavailable"}
            )
            continue
        predictions: list[dict[str, Any]] = []
        for candidate in outcome.candidates:
            if not isinstance(candidate.geometry, PredictedVisibleRegionGeometry):
                continue
            polygons = candidate.geometry.polygons
            source_polygons = [
                [
                    [float(x) / 1000.0 * identity.width, float(y) / 1000.0 * identity.height]
                    for x, y in polygon
                ]
                for polygon in polygons
            ]
            scores = candidate.model_scores or ()
            confidence = max((float(score.score) for score in scores), default=1.0)
            prediction: dict[str, Any] = {
                "candidate_id": candidate.card_id,
                "confidence": confidence,
                "polygons": source_polygons,
            }
            if scores:
                prediction["provider"] = scores[0].producer_id
            predictions.append(prediction)
        frames.append(
            {
                "frame_id": outcome.event_id,
                "source_frame_digest": identity.image_sha256,
                "frame_index": identity.frame_index,
                "timestamp_us": identity.requested_time_us,
                "width": identity.width,
                "height": identity.height,
                "source_transform": identity.transform_version,
                "predictions": predictions,
                "outcome_status": outcome.status,
            }
        )
    if not frames and not unresolvable_frames:
        raise ProposedCardSceneProcessorError(
            "the selected detector revision has no resolvable source-frame identities"
        )
    return {
        "recording_id": recording_id,
        "source_revision": source_revision,
        "frames": frames,
        "unresolvable_frames": unresolvable_frames,
    }


@dataclass(frozen=True, slots=True)
class ProposedCardSceneProcessorResult:
    """The deterministic processor result and its calibration diagnostics."""

    status: str
    data: ProposedCardSceneData | None
    calibration_run: CalibrationRun
    failure: Mapping[str, str] | None
    result_digest: str

    def to_mapping(self) -> dict[str, Any]:
        value = {
            "schema_version": PROPOSED_CARD_SCENE_PROCESSOR_SCHEMA_VERSION,
            "status": self.status,
            "data": None if self.data is None else self.data.to_mapping(),
            "calibration_run": self.calibration_run.to_mapping(),
            "failure": None if self.failure is None else dict(self.failure),
        }
        return {**value, "result_digest": _digest(value)}


def build_proposed_card_scenes(
    local_result: Mapping[str, Any],
    *,
    detector_revision_id: str,
    detector_revision_digest: str,
    calibration_store: CalibrationRevisionStore | None = None,
    calibration_recipe: CalibrationRecipe | None = None,
    calibration_size_reference: Mapping[str, Any] | None = None,
    calibration_size_reference_revision: str | None = None,
    pose_recipe: PoseFitRecipe | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ProposedCardSceneProcessorResult:
    """Calibrate one generated result and initialize a proposal for every resolvable frame."""

    selected = _mapping(local_result, "local result")
    if selected.get("source_revision") != detector_revision_id:
        raise ProposedCardSceneProcessorError(
            "local result source revision does not match the selected detector revision"
        )
    if progress_callback is not None:
        progress_callback(
            "calibration",
            0,
            3,
            "Calibrating virtual cards",
            1,
            3,
        )
    run = calibrate_recording(
        selected,
        recipe=calibration_recipe,
        size_reference=calibration_size_reference,
        size_reference_revision=calibration_size_reference_revision,
    )
    if run.status != "published" or run.calibration is None:
        if progress_callback is not None:
            progress_callback(
                "calibration",
                1,
                3,
                "Calibration failed",
                1,
                3,
            )
        failure = None if run.failure is None else run.failure.to_mapping()
        value = {
            "schema_version": PROPOSED_CARD_SCENE_PROCESSOR_SCHEMA_VERSION,
            "status": "failed",
            "data": None,
            "calibration_run": run.to_mapping(),
            "failure": failure,
        }
        return ProposedCardSceneProcessorResult(
            status="failed",
            data=None,
            calibration_run=run,
            failure=failure,
            result_digest=_digest(value),
        )

    if calibration_store is not None:
        calibration_store.publish(run)
    calibration = run.calibration
    assert calibration is not None
    if progress_callback is not None:
        raw_frames = selected.get("frames", [])
        unresolved = selected.get("unresolvable_frames", [])
        total_frames = (
            len(raw_frames) if isinstance(raw_frames, list) else 0
        ) + (len(unresolved) if isinstance(unresolved, list) else 0)
        progress_callback(
            "initialization",
            0,
            total_frames,
            "Initializing virtual cards",
            2,
            3,
        )
    data = build_proposed_card_scene_data(
        selected,
        detector_revision_id=detector_revision_id,
        detector_revision_digest=detector_revision_digest,
        calibration=calibration,
        calibration_diagnostics=run.diagnostics,
        pose_recipe=pose_recipe,
        progress_callback=progress_callback,
    )
    if progress_callback is not None:
        progress_callback(
            "publishing",
            2,
            3,
            "Publishing proposed card scenes",
            3,
            3,
        )
    status = "complete" if all(item.status == "supported" for item in data.frames) else "partial"
    value = {
        "schema_version": PROPOSED_CARD_SCENE_PROCESSOR_SCHEMA_VERSION,
        "status": status,
        "data": data.to_mapping(),
        "calibration_run": run.to_mapping(),
        "failure": None,
    }
    return ProposedCardSceneProcessorResult(
        status=status,
        data=data,
        calibration_run=run,
        failure=None,
        result_digest=_digest(value),
    )


def build_proposed_card_scene_data(
    local_result: Mapping[str, Any],
    *,
    detector_revision_id: str,
    detector_revision_digest: str,
    calibration: Any,
    calibration_diagnostics: Mapping[str, Any],
    pose_recipe: PoseFitRecipe | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ProposedCardSceneData:
    """Initialize proposal scenes from a supplied immutable calibration."""

    selected = _mapping(local_result, "local result")
    raw_frames = selected.get("frames")
    if not isinstance(raw_frames, list):
        raise ProposedCardSceneProcessorError("local result.frames must be a list")
    frames: list[ProposedCardSceneFrame] = []
    seen_frame_ids: set[str] = set()
    raw_unresolvable_frames = selected.get("unresolvable_frames", [])
    total_frames = len(raw_frames) + (
        len(raw_unresolvable_frames) if isinstance(raw_unresolvable_frames, list) else 0
    )
    completed_frames = 0
    for raw_frame in raw_frames:
        frame = _mapping(raw_frame, "local result frame")
        frame_id = frame.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id:
            raise ProposedCardSceneProcessorError("local result frame_id must be a string")
        seen_frame_ids.add(frame_id)
        source_digest = _source_frame_digest(frame)
        if source_digest is None:
            frames.append(
                ProposedCardSceneFrame(
                    frame_id=frame_id,
                    source_frame_digest=None,
                    status="unsupported",
                    proposal=None,
                    unsupported_reason="source_frame_digest_unavailable",
                )
            )
            completed_frames += 1
            if progress_callback is not None:
                progress_callback(
                    "initialization",
                    completed_frames,
                    total_frames,
                    f"Initializing virtual card frame {frame_id}",
                    2,
                    3,
                )
            continue
        initialized = initialize_card_scene(
            {
                "recording_id": selected["recording_id"],
                "source_revision": detector_revision_id,
                "frames": [frame],
            },
            calibration,
            source_frame_id=frame_id,
            recipe=pose_recipe,
        )
        if initialized.scene is None:
            reason = (
                initialized.failure.message
                if initialized.failure is not None
                else "no_initialized_candidates"
            )
            proposal = ProposedCardScene.create(
                proposal_id=f"proposal-{frame_id}",
                source_frame_id=frame_id,
                source_frame_digest=source_digest,
                detector_revision_id=detector_revision_id,
                detector_revision_digest=detector_revision_digest,
                calibration_revision_id=calibration.calibration_revision_id,
                calibration_digest=calibration.calibration_digest,
                initializer_recipe_version=(
                    initialized.diagnostics.get("recipe", {}).get(
                        "recipe_version", "fixed-card-pose-grid-search/v1"
                    )
                ),
                status="unsupported",
                initialized_scene=None,
                fit_diagnostics={
                    "initialization_processor_schema_version": (
                        INITIALIZATION_PROCESSOR_SCHEMA_VERSION
                    ),
                    "run_digest": initialized.run_digest,
                    "diagnostics": initialized.diagnostics,
                    "fit_diagnostics": [item.to_mapping() for item in initialized.fit_diagnostics],
                },
                unsupported_reason=reason,
            )
            frames.append(
                ProposedCardSceneFrame(
                    frame_id=frame_id,
                    source_frame_digest=source_digest,
                    status="unsupported",
                    proposal=proposal,
                    unsupported_reason=reason,
                )
            )
            completed_frames += 1
            if progress_callback is not None:
                progress_callback(
                    "initialization",
                    completed_frames,
                    total_frames,
                    f"Initializing virtual card frame {frame_id}",
                    2,
                    3,
                )
            continue
        proposal = ProposedCardScene.create(
            proposal_id=f"proposal-{frame_id}",
            source_frame_id=frame_id,
            source_frame_digest=source_digest,
            detector_revision_id=detector_revision_id,
            detector_revision_digest=detector_revision_digest,
            calibration_revision_id=calibration.calibration_revision_id,
            calibration_digest=calibration.calibration_digest,
            initializer_recipe_version=(
                initialized.diagnostics.get("recipe", {}).get(
                    "recipe_version", "fixed-card-pose-grid-search/v1"
                )
            ),
            status="supported",
            initialized_scene=initialized.scene.to_mapping(),
            fit_diagnostics={
                "initialization_processor_schema_version": (
                    INITIALIZATION_PROCESSOR_SCHEMA_VERSION
                ),
                "run_digest": initialized.run_digest,
                "diagnostics": initialized.diagnostics,
                "fit_diagnostics": [item.to_mapping() for item in initialized.fit_diagnostics],
                "suggestions": list(initialized.suggestions),
            },
        )
        frames.append(
            ProposedCardSceneFrame(
                frame_id=frame_id,
                source_frame_digest=source_digest,
                status="supported",
                proposal=proposal,
                unsupported_reason=None,
            )
        )
        completed_frames += 1
        if progress_callback is not None:
            progress_callback(
                "initialization",
                completed_frames,
                total_frames,
                f"Initializing virtual card frame {frame_id}",
                2,
                3,
            )

    unresolvable_frames = raw_unresolvable_frames
    if not isinstance(unresolvable_frames, list):
        raise ProposedCardSceneProcessorError("local result.unresolvable_frames must be a list")
    for raw_frame in unresolvable_frames:
        frame = _mapping(raw_frame, "unresolvable frame")
        frame_id = frame.get("frame_id")
        reason = frame.get("reason")
        if (
            not isinstance(frame_id, str)
            or not frame_id
            or frame_id in seen_frame_ids
            or not isinstance(reason, str)
            or not reason
        ):
            raise ProposedCardSceneProcessorError("unresolvable frame has invalid lineage")
        seen_frame_ids.add(frame_id)
        frames.append(
            ProposedCardSceneFrame(
                frame_id=frame_id,
                source_frame_digest=None,
                status="unsupported",
                proposal=None,
                unsupported_reason=reason,
            )
        )
        completed_frames += 1
        if progress_callback is not None:
            progress_callback(
                "initialization",
                completed_frames,
                total_frames,
                f"Initializing virtual card frame {frame_id}",
                2,
                3,
            )

    return ProposedCardSceneData.create(
        detector_revision_id=detector_revision_id,
        detector_revision_digest=detector_revision_digest,
        calibration_revision_id=calibration.calibration_revision_id,
        calibration_digest=calibration.calibration_digest,
        calibration=calibration.to_mapping(),
        calibration_diagnostics=calibration_diagnostics,
        frames=frames,
    )


__all__ = [
    "PROPOSED_CARD_SCENE_PROCESSOR_SCHEMA_VERSION",
    "PROPOSED_CARD_SCENE_PROCESSOR_TYPE",
    "ProposedCardSceneProcessorError",
    "ProposedCardSceneProcessorResult",
    "build_proposed_card_scenes",
    "build_proposed_card_scene_data",
    "visible_card_data_to_local_result",
]
