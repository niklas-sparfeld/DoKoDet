"""Deterministic calibration-refinement drafts and recording-wide previews.

This module owns the M5 calculation boundary.  It consumes the frozen 0073 contracts and the
existing card-plane geometry implementation.  A preview is a value only: it never mutates the
active calibration or a maintained reference.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from table_evidence_analyzer.card_scene_contract import (
    MAX_FIT_RESIDUAL_TABLE_UNITS,
    MAX_HELD_OUT_ALIGNMENT_CHANGE_PX,
    MAX_PROPOSED_SOURCE_DISPLACEMENT_PX,
    MAX_REVIEWED_SOURCE_DISPLACEMENT_PX,
    MIN_ELIGIBLE_ANCHORS,
    AnchorCommand,
    AnchorObservation,
    CalibrationDraft,
    CalibrationFailure,
    CalibrationGate,
    CalibrationPreview,
    CalibrationReflowReceipt,
    CardReviewState,
    CardSceneContractError,
    CardSceneDraft,
    FrameReviewCompletion,
    ProposedCardScene,
    ReviewedCardSceneRecord,
    anchor_fit_contributions,
    deduplicate_anchor_observations,
    validate_pinned_anchor_conflicts,
)
from table_evidence_analyzer.pipeline_data import (
    ReviewedIgnoreRegionGeometry,
    ReviewedVisibleRegionGeometry,
)

from .card_plane_calibration import CalibrationRun, calibrate_recording
from .card_plane_geometry import (
    CardPlaneGeometryError,
    CardPose,
    CardStackingOrder,
    ReviewedCardScene,
    TablePlaneCalibration,
    apply_homography,
    card_residual,
    derive_pose_scene_visible_regions,
    fit_table_plane,
    project_fixed_card,
    quadrilateral_orientations,
)
from .pipeline_data import canonical_json_bytes
from .pipeline_reference import ReferenceDraftItem
from .visible_card_ignore import geometry_is_within

CALIBRATION_DRAFT_STORE_DIRECTORY = "table-plane-calibration-drafts"
CALIBRATION_REFLOW_STORE_DIRECTORY = "table-plane-calibration-reflows"
CALIBRATION_REFINEMENT_SCHEMA_VERSION = "table-plane-calibration-refinement/v1"


class CalibrationRefinementError(ValueError):
    """Raised when a calibration draft or preview cannot be calculated."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _copy_json(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CalibrationRefinementError(f"{field} must be an object")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CalibrationRefinementError(f"{field} must be a non-empty string")
    if len(value) > 128 or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-:/_"
        for character in value
    ):
        raise CalibrationRefinementError(f"{field} must be a safe identifier")
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationRefinementError(f"{field} must be a finite number")
    result = float(value)
    if not np.isfinite(result):
        raise CalibrationRefinementError(f"{field} must be a finite number")
    return result


def _calibration(value: TablePlaneCalibration | Mapping[str, Any]) -> TablePlaneCalibration:
    if isinstance(value, TablePlaneCalibration):
        return value
    try:
        return TablePlaneCalibration.from_mapping(_mapping(value, "calibration"))
    except (CardPlaneGeometryError, TypeError, ValueError) as error:
        raise CalibrationRefinementError("calibration is invalid") from error


def _source_quad(anchor: AnchorObservation) -> np.ndarray:
    return np.asarray(anchor.quadrilateral, dtype=np.float64)


def _residual_for_calibration(
    calibration: TablePlaneCalibration, anchor: AnchorObservation
) -> tuple[float, np.ndarray]:
    best_score = float("inf")
    best_table: np.ndarray | None = None
    image_to_table = np.asarray(calibration.image_to_table, dtype=np.float64)
    for orientation in quadrilateral_orientations(_source_quad(anchor)):
        table_quad = apply_homography(image_to_table, orientation)
        angle, aspect, parallel = card_residual(table_quad)
        score = float(angle / 10.0 + aspect + parallel)
        if score < best_score:
            best_score = score
            best_table = table_quad
    if best_table is None:
        raise CalibrationRefinementError(f"anchor has no usable orientation: {anchor.anchor_id}")
    return best_score, best_table


def _weighted_fit(
    base: TablePlaneCalibration,
    anchors: Sequence[AnchorObservation],
) -> tuple[TablePlaneCalibration, tuple[dict[str, Any], ...], tuple[str, ...]]:
    selected, rejected = deduplicate_anchor_observations(anchors)
    if len(selected) < MIN_ELIGIBLE_ANCHORS:
        raise CalibrationRefinementError("insufficient eligible anchors for a calibration preview")
    contributions = anchor_fit_contributions(anchors)
    contribution_by_id = {item.anchor_id: item for item in contributions}
    selected_by_id = {item.anchor_id: item for item in selected}
    fit_anchors: list[AnchorObservation] = []
    fit_weights: list[float] = []
    for anchor_id in sorted(selected_by_id):
        contribution = contribution_by_id.get(anchor_id)
        if contribution is None or contribution.weight <= 0:
            continue
        fit_anchors.append(selected_by_id[anchor_id])
        fit_weights.append(contribution.weight)
    if len(fit_anchors) < MIN_ELIGIBLE_ANCHORS:
        raise CalibrationRefinementError("anchor contribution weights produced an empty fit")
    try:
        fit = fit_table_plane(
            [_source_quad(anchor) for anchor in fit_anchors],
            observation_weights=fit_weights,
        )
        candidate = TablePlaneCalibration.create(
            calibration_revision_id=(
                "calibration-preview-"
                + _digest(
                    {
                        "base": base.calibration_digest,
                        "anchors": [anchor.observation_digest for anchor in selected],
                        "weights": [
                            contribution_by_id[item.anchor_id].weight for item in selected
                        ],
                    }
                )[:24]
            ),
            recording_id=base.recording_id,
            source_revision=base.source_revision,
            frame_width=base.frame_width,
            frame_height=base.frame_height,
            image_to_table=fit["image_to_table"],
            table_to_image=fit["table_to_image"],
            card_short_size=fit["card_short_size"],
            card_long_size=fit["card_long_size"],
            candidate_receipt_digests=[item.observation_digest for item in selected],
            diagnostics={
                "schema_version": CALIBRATION_REFINEMENT_SCHEMA_VERSION,
                "base_calibration_digest": base.calibration_digest,
                "weighted_fit": {
                    "selected_anchor_ids": [item.anchor_id for item in selected],
                    "deduplicated_anchor_ids": list(rejected),
                    "contributions": [item.to_mapping() for item in contributions],
                },
                "fit": {
                    "accepted_card_count": fit["accepted_card_count"],
                    "rejected_card_indices": fit["rejected_card_indices"],
                    "median_angle_error_degrees": fit["median_angle_error_degrees"],
                    "median_aspect_error": fit["median_aspect_error"],
                    "median_parallel_error": fit["median_parallel_error"],
                },
            },
        )
    except (CardPlaneGeometryError, ValueError) as error:
        raise CalibrationRefinementError(str(error)) from error

    contribution_records = tuple(item.to_mapping() for item in contributions)
    return candidate, contribution_records, rejected


def _scene_mapping(raw: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    frame_id = raw.get("frame_id", raw.get("item_id"))
    if not isinstance(frame_id, str) or not frame_id:
        return None
    envelope = raw.get("card_scene")
    if isinstance(envelope, Mapping):
        reviewed = envelope.get("reviewed")
        if isinstance(reviewed, Mapping) and isinstance(reviewed.get("scene"), Mapping):
            return frame_id, _mapping(reviewed["scene"], "reviewed scene")
        proposal = envelope.get("proposal")
        if isinstance(proposal, Mapping) and isinstance(proposal.get("initialized_scene"), Mapping):
            return frame_id, _mapping(proposal["initialized_scene"], "proposal scene")
    scene = raw.get("scene")
    if isinstance(scene, Mapping):
        return frame_id, scene
    return None


def _scene_displacement(
    scene: Mapping[str, Any],
    base: TablePlaneCalibration,
    candidate: TablePlaneCalibration,
) -> tuple[float, tuple[str, ...]]:
    poses = scene.get("poses")
    if not isinstance(poses, list):
        return 0.0, ()
    maximum = 0.0
    card_ids: list[str] = []
    for raw_pose in poses:
        if not isinstance(raw_pose, Mapping):
            continue
        card_id = raw_pose.get("card_id")
        center = raw_pose.get("center")
        if (
            not isinstance(card_id, str)
            or not isinstance(center, (list, tuple))
            or len(center) != 2
        ):
            continue
        pose = CardPose(
            card_id=card_id,
            center=tuple(_finite(value, "scene center") for value in center),
            rotation_degrees=_finite(raw_pose.get("rotation_degrees"), "scene rotation"),
            source_suggestion_id=None,
            fit_diagnostics_digest=None,
        )
        _refit, displacement = _refit_scene_pose(pose, base, candidate)
        if displacement > maximum:
            maximum = displacement
        if displacement > 0.0:
            card_ids.append(pose.card_id)
    return maximum, tuple(sorted(set(card_ids)))


def _projected_anchor_outline(
    calibration: TablePlaneCalibration,
    anchor: AnchorObservation,
) -> np.ndarray:
    """Project one source observation through a calibration using its best orientation."""

    best_score = float("inf")
    best_outline: np.ndarray | None = None
    image_to_table = np.asarray(calibration.image_to_table, dtype=np.float64)
    table_to_image = np.asarray(calibration.table_to_image, dtype=np.float64)
    for orientation in quadrilateral_orientations(_source_quad(anchor)):
        table_quad = apply_homography(image_to_table, orientation)
        angle, aspect, parallel = card_residual(table_quad)
        score = float(angle / 10.0 + aspect + parallel)
        if score >= best_score:
            continue
        center = np.mean(table_quad, axis=0)
        short = (table_quad[1] - table_quad[0]) + (table_quad[2] - table_quad[3])
        angle_degrees = float(np.degrees(np.arctan2(short[1], short[0])))
        best_score = score
        best_outline = project_fixed_card(
            table_to_image,
            center,
            angle_degrees,
            calibration.card_short_size,
            calibration.card_long_size,
        )
    if best_outline is None:
        raise CalibrationRefinementError(f"anchor has no projected outline: {anchor.anchor_id}")
    return best_outline


def _failure(
    code: str,
    message: str,
    action: str,
) -> CalibrationFailure:
    try:
        return CalibrationFailure.create(code=code, message=message, action=action)
    except CardSceneContractError as error:
        raise CalibrationRefinementError(str(error)) from error


def build_calibration_preview(
    draft: CalibrationDraft,
    base_calibration: TablePlaneCalibration | Mapping[str, Any],
    *,
    frame_scenes: Sequence[Mapping[str, Any]] = (),
) -> CalibrationPreview:
    """Calculate one deterministic candidate calibration and its recording-wide impact."""

    if not isinstance(draft, CalibrationDraft):
        raise CalibrationRefinementError("draft must be a CalibrationDraft")
    base = _calibration(base_calibration)
    if draft.base_calibration_digest != base.calibration_digest:
        failure = _failure(
            "stale_calibration_revision",
            "the calibration draft does not use the active calibration revision",
            "reload the active calibration and create a new refinement draft",
        )
        return _blocked_preview(draft, base, failure, 0, 0)
    deduplicated: tuple[str, ...] = ()
    try:
        validate_pinned_anchor_conflicts(draft.anchors)
        candidate, _contributions, deduplicated = _weighted_fit(base, draft.anchors)
    except CardSceneContractError as error:
        failure = _failure(
            "conflicting_pinned_anchors",
            str(error),
            "unpin or correct the conflicting anchors before previewing the calibration",
        )
        return _blocked_preview(draft, base, failure, 0, 0)
    except CalibrationRefinementError as error:
        failure = _failure(
            "insufficient_anchors" if "insufficient" in str(error) else "fit_gate_failed",
            str(error),
            "accept or adjust at least three eligible anchors, then preview again",
        )
        return _blocked_preview(draft, base, failure, 0, len(deduplicated))

    eligible = [
        anchor for anchor in draft.anchors if anchor.eligible and anchor.state != "excluded"
    ]
    fit_residuals = [_residual_for_calibration(candidate, anchor)[0] for anchor in eligible]
    pinned_failures = [
        anchor.anchor_id
        for anchor in draft.anchors
        if anchor.state == "pinned"
        and _residual_for_calibration(candidate, anchor)[0] > MAX_FIT_RESIDUAL_TABLE_UNITS
    ]
    if pinned_failures:
        failure = _failure(
            "conflicting_pinned_anchors",
            "pinned anchors cannot all remain inliers: " + ", ".join(sorted(pinned_failures)),
            "unpin or correct the listed anchors before previewing the calibration",
        )
        return _blocked_preview(draft, base, failure, len(eligible), len(deduplicated))

    fit_residual = float(np.median(fit_residuals)) if fit_residuals else float("inf")
    changed_frames: list[str] = []
    changed_cards: list[str] = []
    affected: list[tuple[float, str]] = []
    for raw_scene in frame_scenes:
        parsed = _scene_mapping(_mapping(raw_scene, "frame scene"))
        if parsed is None:
            continue
        frame_id, scene = parsed
        displacement, card_ids = _scene_displacement(scene, base, candidate)
        if displacement > 0.0:
            changed_frames.append(frame_id)
            changed_cards.extend(card_ids)
            affected.append((displacement, frame_id))
    changed_frames = sorted(set(changed_frames))
    changed_cards = sorted(set(changed_cards))
    affected.sort(key=lambda value: (-value[0], value[1]))
    max_displacement = affected[0][0] if affected else 0.0
    most_affected = tuple(frame_id for _distance, frame_id in affected[:5])
    held_out_change = max(
        (
            float(
                np.max(
                    np.linalg.norm(
                        _projected_anchor_outline(candidate, anchor)
                        - _projected_anchor_outline(base, anchor),
                        axis=1,
                    )
                )
            )
            for anchor in draft.anchors
            if anchor.eligible and anchor.state == "candidate"
        ),
        default=0.0,
    )
    gates = (
        CalibrationGate.create(
            gate_id="minimum_eligible_anchors",
            passed=len(eligible) >= MIN_ELIGIBLE_ANCHORS,
            observed=len(eligible),
            threshold=MIN_ELIGIBLE_ANCHORS,
            message="eligible anchors are available for a recording-wide fit",
        ),
        CalibrationGate.create(
            gate_id="fit_residual",
            passed=fit_residual <= MAX_FIT_RESIDUAL_TABLE_UNITS,
            observed=fit_residual,
            threshold=MAX_FIT_RESIDUAL_TABLE_UNITS,
            message=(
                "weighted table-plane residual is within the limit"
                if fit_residual <= MAX_FIT_RESIDUAL_TABLE_UNITS
                else "weighted table-plane residual exceeds the limit"
            ),
        ),
        CalibrationGate.create(
            gate_id="held_out_alignment_change",
            passed=held_out_change <= MAX_HELD_OUT_ALIGNMENT_CHANGE_PX,
            observed=held_out_change,
            threshold=MAX_HELD_OUT_ALIGNMENT_CHANGE_PX,
            message=(
                "held-out source alignment change is within the limit"
                if held_out_change <= MAX_HELD_OUT_ALIGNMENT_CHANGE_PX
                else "held-out source alignment change exceeds the limit"
            ),
        ),
        CalibrationGate.create(
            gate_id="reviewed_displacement",
            passed=all(
                displacement <= MAX_REVIEWED_SOURCE_DISPLACEMENT_PX
                for displacement, _frame_id in affected
            ),
            observed=max_displacement,
            threshold=MAX_REVIEWED_SOURCE_DISPLACEMENT_PX,
            message="reviewed scene displacement is within the confirmation gate",
        ),
        CalibrationGate.create(
            gate_id="proposed_displacement",
            passed=all(
                displacement <= MAX_PROPOSED_SOURCE_DISPLACEMENT_PX
                for displacement, _frame_id in affected
            ),
            observed=max_displacement,
            threshold=MAX_PROPOSED_SOURCE_DISPLACEMENT_PX,
            message="proposed scene displacement is within the preview gate",
        ),
    )
    failed = next((gate for gate in gates if not gate.passed), None)
    failure = None
    status = "pass"
    if failed is not None:
        status = "blocked"
        failure = _failure(
            "reviewed_displacement_exceeded"
            if failed.gate_id == "reviewed_displacement"
            else "held_out_gate_failed"
            if failed.gate_id == "held_out_alignment_change"
            else "fit_gate_failed",
            failed.message,
            "inspect the most affected frames and correct or exclude the outlying anchors",
        )
    candidate_mapping = candidate.to_mapping()
    return CalibrationPreview.create(
        preview_id="preview-" + _digest(
            {"draft": draft.draft_digest, "candidate": candidate_mapping}
        )[:24],
        draft_id=draft.draft_id,
        base_calibration_revision_id=base.calibration_revision_id,
        base_calibration_digest=base.calibration_digest,
        candidate_calibration=candidate_mapping,
        gates=gates,
        status=status,
        failure=failure,
        fit_residual=fit_residual,
        accepted_anchor_count=sum(
            1 for anchor in draft.anchors if anchor.state in {"accepted", "adjusted", "pinned"}
        ),
        rejected_candidate_count=len(deduplicated)
        + sum(1 for anchor in draft.anchors if anchor.state == "excluded"),
        held_out_alignment_change_px=held_out_change,
        changed_frame_ids=changed_frames,
        changed_card_ids=changed_cards,
        max_source_pixel_displacement=max_displacement,
        most_affected_frame_ids=most_affected,
    )


def _blocked_preview(
    draft: CalibrationDraft,
    base: TablePlaneCalibration,
    failure: CalibrationFailure,
    accepted_count: int,
    rejected_count: int,
) -> CalibrationPreview:
    return CalibrationPreview.create(
        preview_id="preview-" + _digest(
            {
                "draft": draft.draft_digest,
                "base": base.calibration_digest,
                "failure": failure.to_mapping(),
            }
        )[:24],
        draft_id=draft.draft_id,
        base_calibration_revision_id=base.calibration_revision_id,
        base_calibration_digest=base.calibration_digest,
        candidate_calibration=None,
        gates=(),
        status="blocked",
        failure=failure,
        fit_residual=0.0,
        accepted_anchor_count=accepted_count,
        rejected_candidate_count=rejected_count,
        held_out_alignment_change_px=0.0,
        changed_frame_ids=(),
        changed_card_ids=(),
        max_source_pixel_displacement=0.0,
        most_affected_frame_ids=(),
    )


def apply_anchor_command_to_draft(
    draft: CalibrationDraft,
    command: AnchorCommand,
) -> CalibrationDraft:
    """Apply one ordered anchor command without calculating or storing a preview."""

    if any(existing.command_id == command.command_id for existing in draft.commands):
        return draft
    if command.expected_draft_revision != draft.revision:
        raise CalibrationRefinementError(
            f"anchor command expects draft revision {command.expected_draft_revision}, "
            f"but the current revision is {draft.revision}"
        )
    if command.sequence != len(draft.commands) + 1:
        raise CalibrationRefinementError("anchor command sequence is not the next ordered command")
    anchors = list(draft.anchors)
    index = next(
        (index for index, item in enumerate(anchors) if item.anchor_id == command.anchor_id),
        None,
    )
    if index is None:
        raise CalibrationRefinementError(f"anchor was not found: {command.anchor_id}")
    current = anchors[index]
    if command.operation == "set_corners":
        assert command.corners is not None
        anchors[index] = AnchorObservation.create(
            anchor_id=current.anchor_id,
            card_id=current.card_id,
            source_frame_id=current.source_frame_id,
            source_frame_digest=current.source_frame_digest,
            detector_revision_id=current.detector_revision_id,
            quadrilateral=command.corners,
            confidence=current.confidence,
            temporal_bin=current.temporal_bin,
            table_region_bin=current.table_region_bin,
            scale_bin=current.scale_bin,
            orientation_bin=current.orientation_bin,
            eligible=True,
            eligibility_reason=None,
            state="adjusted",
            weight_class="adjusted",
        )
    elif command.operation == "set_state":
        assert command.state is not None
        weight_class = (
            "adjusted"
            if command.state == "adjusted"
            else "accepted"
            if command.state == "accepted"
            else current.weight_class
            if command.state == "pinned"
            else "candidate"
        )
        anchors[index] = AnchorObservation.create(
            anchor_id=current.anchor_id,
            card_id=current.card_id,
            source_frame_id=current.source_frame_id,
            source_frame_digest=current.source_frame_digest,
            detector_revision_id=current.detector_revision_id,
            quadrilateral=current.quadrilateral,
            confidence=current.confidence,
            temporal_bin=current.temporal_bin,
            table_region_bin=current.table_region_bin,
            scale_bin=current.scale_bin,
            orientation_bin=current.orientation_bin,
            eligible=current.eligible,
            eligibility_reason=current.eligibility_reason,
            state=command.state,
            weight_class=weight_class,
        )
    else:
        anchors[index] = AnchorObservation.create(
            anchor_id=current.anchor_id,
            card_id=current.card_id,
            source_frame_id=current.source_frame_id,
            source_frame_digest=current.source_frame_digest,
            detector_revision_id=current.detector_revision_id,
            quadrilateral=current.quadrilateral,
            confidence=current.confidence,
            temporal_bin=current.temporal_bin,
            table_region_bin=current.table_region_bin,
            scale_bin=current.scale_bin,
            orientation_bin=current.orientation_bin,
            eligible=current.eligible,
            eligibility_reason=current.eligibility_reason,
            state="candidate",
            weight_class="candidate",
        )
    return CalibrationDraft.create(
        draft_id=draft.draft_id,
        recording_id=draft.recording_id,
        detector_revision_id=draft.detector_revision_id,
        detector_revision_digest=draft.detector_revision_digest,
        base_calibration_revision_id=draft.base_calibration_revision_id,
        base_calibration_digest=draft.base_calibration_digest,
        source_frame_digests=draft.source_frame_digests,
        anchors=anchors,
        commands=(*draft.commands, command),
        revision=draft.revision + 1,
        state="dirty",
    )


def build_calibration_draft(
    *,
    draft_id: str,
    recording_id: str,
    detector_revision_id: str,
    detector_revision_digest: str,
    base_calibration: TablePlaneCalibration | Mapping[str, Any],
    anchors: Sequence[AnchorObservation],
    source_frame_digests: Mapping[str, str],
) -> CalibrationDraft:
    """Create a clean draft from immutable proposal evidence."""

    calibration = _calibration(base_calibration)
    return CalibrationDraft.create(
        draft_id=_identifier(draft_id, "draft_id"),
        recording_id=_identifier(recording_id, "recording_id"),
        detector_revision_id=_identifier(detector_revision_id, "detector_revision_id"),
        detector_revision_digest=detector_revision_digest,
        base_calibration_revision_id=calibration.calibration_revision_id,
        base_calibration_digest=calibration.calibration_digest,
        source_frame_digests=source_frame_digests,
        anchors=anchors,
        commands=(),
        revision=0,
        state="clean",
    )


def exclude_anchors_in_reviewed_ignore_regions(
    draft: CalibrationDraft,
    frame_items: Sequence[Mapping[str, Any]],
) -> CalibrationDraft:
    """Return a preview draft with anchors covered by reviewed ignore regions excluded.

    Ignore regions are added to the maintained reference after the calibration draft can
    already exist. Keep the draft revision and commands stable, but derive the effective anchor
    state from the current reviewed frame data so a later ignore decision is applied
    retrospectively.
    """

    regions_by_frame: dict[str, list[tuple[ReviewedIgnoreRegionGeometry, int, int]]] = {}
    for item in frame_items:
        if not isinstance(item, Mapping):
            continue
        raw_regions = item.get("ignored_regions")
        if not isinstance(raw_regions, list):
            continue
        frame_identity = item.get("frame_identity")
        width = frame_identity.get("width") if isinstance(frame_identity, Mapping) else None
        height = frame_identity.get("height") if isinstance(frame_identity, Mapping) else None
        frame_ids = {
            value
            for value in (
                item.get("item_id"),
                item.get("event_id"),
                frame_identity.get("frame_id") if isinstance(frame_identity, Mapping) else None,
            )
            if isinstance(value, str) and value
        }
        raw_scene = item.get("card_scene")
        if isinstance(raw_scene, Mapping):
            reviewed = raw_scene.get("reviewed")
            scene = reviewed.get("scene") if isinstance(reviewed, Mapping) else None
            source_frame_id = scene.get("source_frame_id") if isinstance(scene, Mapping) else None
            if isinstance(source_frame_id, str) and source_frame_id:
                frame_ids.add(source_frame_id)
        for raw_region in raw_regions:
            if not isinstance(raw_region, Mapping):
                continue
            raw_geometry = raw_region.get("geometry")
            raw_normalization = raw_region.get("normalization")
            try:
                geometry = ReviewedIgnoreRegionGeometry.from_mapping(raw_geometry)
                if not isinstance(raw_normalization, Mapping):
                    continue
                region_width = int(raw_normalization["width"])
                region_height = int(raw_normalization["height"])
            except (KeyError, TypeError, ValueError):
                continue
            resolved_width = width if isinstance(width, int) and width > 0 else region_width
            resolved_height = height if isinstance(height, int) and height > 0 else region_height
            for frame_id in frame_ids:
                regions_by_frame.setdefault(frame_id, []).append(
                    (geometry, resolved_width, resolved_height)
                )

    if not regions_by_frame:
        return draft

    updated_anchors: list[AnchorObservation] = []
    changed = False
    for anchor in draft.anchors:
        regions = regions_by_frame.get(anchor.source_frame_id, ())
        excluded = False
        for region, width, height in regions:
            candidate = ReviewedVisibleRegionGeometry(
                polygons=(
                    tuple(
                        (
                            max(0, min(1000, int(round(point[0] * 1000 / width)))),
                            max(0, min(1000, int(round(point[1] * 1000 / height)))),
                        )
                        for point in anchor.quadrilateral
                    ),
                )
            )
            if geometry_is_within(region, candidate):
                excluded = True
                break
        if excluded and anchor.state != "excluded":
            updated_anchors.append(
                AnchorObservation.create(
                    anchor_id=anchor.anchor_id,
                    card_id=anchor.card_id,
                    source_frame_id=anchor.source_frame_id,
                    source_frame_digest=anchor.source_frame_digest,
                    detector_revision_id=anchor.detector_revision_id,
                    quadrilateral=anchor.quadrilateral,
                    confidence=anchor.confidence,
                    temporal_bin=anchor.temporal_bin,
                    table_region_bin=anchor.table_region_bin,
                    scale_bin=anchor.scale_bin,
                    orientation_bin=anchor.orientation_bin,
                    eligible=False,
                    eligibility_reason="reviewed ignore region",
                    state="excluded",
                    weight_class=anchor.weight_class,
                )
            )
            changed = True
        else:
            updated_anchors.append(anchor)

    if not changed:
        return draft
    return CalibrationDraft.create(
        draft_id=draft.draft_id,
        recording_id=draft.recording_id,
        detector_revision_id=draft.detector_revision_id,
        detector_revision_digest=draft.detector_revision_digest,
        base_calibration_revision_id=draft.base_calibration_revision_id,
        base_calibration_digest=draft.base_calibration_digest,
        source_frame_digests=draft.source_frame_digests,
        anchors=updated_anchors,
        commands=draft.commands,
        revision=draft.revision,
        state=draft.state,
        invalidation_reason=draft.invalidation_reason,
    )


def build_published_calibration_run(
    calibration: TablePlaneCalibration,
    *,
    diagnostics: Mapping[str, Any],
) -> CalibrationRun:
    """Wrap one refined calibration in the immutable calibration-run store contract."""

    core = {
        "schema_version": "card-plane-calibration-run/v1",
        "recording_id": calibration.recording_id,
        "source_revision": calibration.source_revision,
        "status": "published",
        "candidate_receipts": [],
        "diagnostics": json.loads(canonical_json_bytes(diagnostics).decode("utf-8")),
        "calibration": calibration.to_mapping(),
        "failure": None,
    }
    return CalibrationRun(
        recording_id=calibration.recording_id,
        source_revision=calibration.source_revision,
        status="published",
        candidate_receipts=(),
        diagnostics=core["diagnostics"],
        calibration=calibration,
        failure=None,
        run_digest=_digest(core),
    )


@dataclass(frozen=True, slots=True)
class CardSceneReflowResult:
    """One deterministic maintained-card-scene reflow result."""

    draft: CardSceneDraft
    max_source_pixel_displacement: float
    affected_card_ids: tuple[str, ...]


def _refit_scene_pose(
    pose: CardPose,
    source_calibration: TablePlaneCalibration,
    target_calibration: TablePlaneCalibration,
) -> tuple[CardPose, float]:
    source_quad = project_fixed_card(
        np.asarray(source_calibration.table_to_image, dtype=np.float64),
        pose.center,
        pose.rotation_degrees,
        source_calibration.card_short_size,
        source_calibration.card_long_size,
    )
    target_quad = apply_homography(
        np.asarray(target_calibration.image_to_table, dtype=np.float64), source_quad
    )
    center = np.mean(target_quad, axis=0)
    short_axis = (target_quad[1] - target_quad[0]) + (target_quad[2] - target_quad[3])
    angle = float(np.degrees(np.arctan2(short_axis[1], short_axis[0])))
    refit = CardPose(
        card_id=pose.card_id,
        center=(float(center[0]), float(center[1])),
        rotation_degrees=angle,
        source_suggestion_id=pose.source_suggestion_id,
        fit_diagnostics_digest=pose.fit_diagnostics_digest,
    )
    refit_quad = project_fixed_card(
        np.asarray(target_calibration.table_to_image, dtype=np.float64),
        refit.center,
        refit.rotation_degrees,
        target_calibration.card_short_size,
        target_calibration.card_long_size,
    )
    displacement = float(np.max(np.linalg.norm(refit_quad - source_quad, axis=1)))
    return refit, displacement


def reflow_card_scene_draft(
    current: CardSceneDraft,
    target_proposal: ProposedCardScene,
    target_projection: Mapping[str, Any],
    source_calibration: TablePlaneCalibration | Mapping[str, Any],
    target_calibration: TablePlaneCalibration | Mapping[str, Any],
    *,
    target_proposal_revision_id: str | None = None,
    target_proposal_data_digest: str | None = None,
) -> CardSceneReflowResult:
    """Rebase one mutable card-scene draft under a new immutable calibration."""

    source = _calibration(source_calibration)
    target = _calibration(target_calibration)
    if current.proposal.calibration_digest != source.calibration_digest:
        raise CalibrationRefinementError("card-scene draft uses a stale source calibration")
    if target_proposal.status != "supported" or target_proposal.initialized_scene is None:
        raise CalibrationRefinementError("a supported target proposal is required for scene reflow")

    previous_states = {item.card_id: item for item in current.card_states}
    states: list[CardReviewState] = []
    for card_id in target_proposal.card_ids:
        previous = previous_states.get(card_id)
        states.append(
            CardReviewState.create(
                card_id=card_id,
                source="proposal",
                proposal_id=target_proposal.proposal_id,
                state="pending" if previous is None else previous.state,
            )
        )
    for previous in current.card_states:
        if previous.source == "manual" and previous.card_id not in target_proposal.card_ids:
            states.append(previous)

    resolved_ids = {
        item.card_id for item in states if item.state in {"accepted", "adjusted"}
    }
    maximum = 0.0
    affected: list[str] = []
    reviewed = None
    if current.reviewed is not None:
        previous_scene = ReviewedCardScene.from_mapping(current.reviewed.scene)
        refit_poses: list[CardPose] = []
        for pose in previous_scene.poses:
            refit, displacement = _refit_scene_pose(pose, source, target)
            refit_poses.append(refit)
            maximum = max(maximum, displacement)
            if displacement > MAX_REVIEWED_SOURCE_DISPLACEMENT_PX:
                affected.append(pose.card_id)
        selected_poses = tuple(pose for pose in refit_poses if pose.card_id in resolved_ids)
        if selected_poses:
            selected_ids = {pose.card_id for pose in selected_poses}
            order = CardStackingOrder(
                card_ids=tuple(
                    card_id
                    for card_id in previous_scene.stacking_order.card_ids
                    if card_id in selected_ids
                ),
                uncertain_edges=tuple(
                    edge
                    for edge in previous_scene.stacking_order.uncertain_edges
                    if edge[0] in selected_ids and edge[1] in selected_ids
                ),
                contradictions=previous_scene.stacking_order.contradictions,
            )
            refit_scene = ReviewedCardScene.create(
                source_frame_id=previous_scene.source_frame_id,
                source_frame_width=previous_scene.source_frame_width,
                source_frame_height=previous_scene.source_frame_height,
                calibration_revision_id=target.calibration_revision_id,
                calibration_digest=target.calibration_digest,
                poses=selected_poses,
                stacking_order=order,
            )
            reviewed = ReviewedCardSceneRecord.create(
                proposal_id=target_proposal.proposal_id,
                scene=refit_scene.to_mapping(),
                decision=current.reviewed.decision,
            )

    pending_ids = tuple(item.card_id for item in states if item.state == "pending")
    draft = CardSceneDraft.create(
        proposal=target_proposal,
        reviewed=reviewed,
        card_states=tuple(states),
        completion=FrameReviewCompletion.create(
            state="pending" if pending_ids else "complete",
            unresolved_card_ids=pending_ids,
        ),
        draft_revision=current.draft_revision + 1,
        proposal_revision_id=(
            current.proposal_revision_id
            if target_proposal_revision_id is None
            else target_proposal_revision_id
        ),
        proposal_data_digest=(
            current.proposal_data_digest
            if target_proposal_data_digest is None
            else target_proposal_data_digest
        ),
        projection=target_projection,
    )
    return CardSceneReflowResult(
        draft=draft,
        max_source_pixel_displacement=maximum,
        affected_card_ids=tuple(sorted(set(affected))),
    )


def reflow_reference_items(
    current_items: Sequence[ReferenceDraftItem],
    target_items: Sequence[ReferenceDraftItem],
    source_calibration: TablePlaneCalibration | Mapping[str, Any],
    target_calibration: TablePlaneCalibration | Mapping[str, Any],
    *,
    target_proposal_revision_id: str,
    target_proposal_data_digest: str,
    force_affected_frame_ids: Sequence[str] = (),
) -> tuple[tuple[ReferenceDraftItem, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Reflow visible-card items and return reinitialized, rebased, and affected IDs."""

    current_by_id = {item.item_id: item for item in current_items}
    updated: list[ReferenceDraftItem] = []
    reinitialized: list[str] = []
    rebased: list[str] = []
    affected_frames: list[str] = []
    for target_item in target_items:
        previous = current_by_id.get(target_item.item_id)
        if previous is None:
            updated.append(target_item)
            raw_scene = target_item.item.get("card_scene")
            if isinstance(raw_scene, Mapping):
                target_scene = CardSceneDraft.from_mapping(raw_scene)
                reinitialized.extend(target_scene.proposal.card_ids)
            continue
        previous_scene_raw = previous.item.get("card_scene")
        target_scene_raw = target_item.item.get("card_scene")
        if not isinstance(previous_scene_raw, Mapping) or not isinstance(target_scene_raw, Mapping):
            updated.append(previous)
            continue
        current_scene = CardSceneDraft.from_mapping(previous_scene_raw)
        target_scene = CardSceneDraft.from_mapping(target_scene_raw)
        result = reflow_card_scene_draft(
            current_scene,
            target_scene.proposal,
            target_scene.projection or {},
            source_calibration,
            target_calibration,
            target_proposal_revision_id=target_proposal_revision_id,
            target_proposal_data_digest=target_proposal_data_digest,
        )
        item = dict(target_item.item)
        item["ignored_regions"] = previous.item.get("ignored_regions", [])
        item["candidates"] = []
        if result.draft.reviewed is not None:
            derivation = derive_pose_scene_visible_regions(
                result.draft.reviewed.scene, target_scene.projection or {}
            )
            previous_candidates = {
                candidate.get("card_id"): candidate
                for candidate in previous.item.get("candidates", [])
                if isinstance(candidate, Mapping) and isinstance(candidate.get("card_id"), str)
            }
            item["candidates"] = [
                {
                    "card_id": region["card_id"],
                    "geometry": region["geometry"],
                    "normalization": region["normalization"],
                    "side": previous_candidates.get(region["card_id"], {}).get(
                        "side", "unknown"
                    ),
                    **(
                        {"model_scores": previous_candidates[region["card_id"]]["model_scores"]}
                        if region["card_id"] in previous_candidates
                        and "model_scores" in previous_candidates[region["card_id"]]
                        else {}
                    ),
                }
                for region in derivation.regions
            ]
            result = CardSceneReflowResult(
                draft=CardSceneDraft.create(
                    proposal=result.draft.proposal,
                    reviewed=result.draft.reviewed,
                    card_states=result.draft.card_states,
                    completion=result.draft.completion,
                    draft_revision=result.draft.draft_revision,
                    proposal_revision_id=result.draft.proposal_revision_id,
                    proposal_data_digest=result.draft.proposal_data_digest,
                    projection=result.draft.projection,
                    derived_region_receipt=derivation.receipt.to_mapping(),
                ),
                max_source_pixel_displacement=result.max_source_pixel_displacement,
                affected_card_ids=result.affected_card_ids,
            )
        item["card_scene"] = result.draft.to_mapping()
        state = previous.review_state
        if (
            (result.affected_card_ids or target_item.item_id in force_affected_frame_ids)
            and state in {"accepted", "corrected"}
        ):
            state = "affected"
            affected_frames.append(target_item.item_id)
        if state in {"accepted", "corrected", "affected"}:
            rebased.extend(
                card_state.card_id
                for card_state in result.draft.card_states
                if card_state.state in {"accepted", "adjusted"}
            )
        else:
            reinitialized.extend(
                card_state.card_id
                for card_state in result.draft.card_states
                if card_state.state == "pending"
            )
        updated.append(
            ReferenceDraftItem(
                item_id=previous.item_id,
                base_item_id=previous.base_item_id,
                review_state=state,
                item=item,
            )
        )
    return (
        tuple(updated),
        tuple(sorted(set(reinitialized))),
        tuple(sorted(set(rebased))),
        tuple(sorted(set(affected_frames))),
    )


def anchor_observations_from_local_result(
    local_result: Mapping[str, Any],
    *,
    detector_revision_id: str,
) -> tuple[tuple[AnchorObservation, ...], dict[str, str]]:
    """Turn immutable local detector evidence into explicit candidate and excluded anchors."""

    try:
        run = calibrate_recording(local_result)
    except (TypeError, ValueError) as error:
        raise CalibrationRefinementError(
            "local result cannot provide calibration anchors"
        ) from error
    frames = local_result.get("frames")
    if not isinstance(frames, list):
        raise CalibrationRefinementError("local result.frames must be a list")
    frame_digests = {
        str(frame.get("frame_id")): frame.get("source_frame_digest")
        for frame in frames
        if isinstance(frame, Mapping)
        and isinstance(frame.get("frame_id"), str)
        and isinstance(frame.get("source_frame_digest"), str)
    }
    anchors: list[AnchorObservation] = []
    for receipt in run.candidate_receipts:
        source_digest = frame_digests.get(receipt.source_frame_id)
        if source_digest is None:
            continue
        accepted = receipt.accepted
        anchors.append(
            AnchorObservation.create(
                anchor_id=receipt.candidate_id,
                card_id=receipt.candidate_id,
                source_frame_id=receipt.source_frame_id,
                source_frame_digest=source_digest,
                detector_revision_id=detector_revision_id,
                quadrilateral=receipt.quadrilateral,
                confidence=receipt.confidence,
                temporal_bin=receipt.temporal_bin,
                table_region_bin=receipt.table_position_bin,
                scale_bin=receipt.scale_bin,
                orientation_bin=receipt.orientation_bin,
                eligible=accepted,
                eligibility_reason=(
                    None if accepted else receipt.rejection_reason or "rejected candidate"
                ),
                state="candidate" if accepted else "excluded",
                weight_class="candidate",
            )
        )
    return tuple(anchors), frame_digests


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


class CalibrationDraftStore:
    """Persist one mutable calibration draft and its clean starting value per recording."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()

    def _path(self, recording_id: str, draft_id: str) -> Path:
        return (
            self.workspace_root
            / _identifier(recording_id, "recording_id")
            / CALIBRATION_DRAFT_STORE_DIRECTORY
            / _identifier(draft_id, "draft_id")
            / "draft.json"
        )

    def publish(self, draft: CalibrationDraft) -> Path:
        path = self._path(draft.recording_id, draft.draft_id)
        payload = canonical_json_bytes(draft.to_mapping())
        _write_atomic(path, payload)
        return path

    def publish_initial(self, draft: CalibrationDraft) -> Path:
        path = self._path(draft.recording_id, draft.draft_id).with_name("initial.json")
        payload = canonical_json_bytes(draft.to_mapping())
        if path.exists() and path.read_bytes() != payload:
            raise CalibrationRefinementError("calibration draft initial value is immutable")
        if not path.exists():
            _write_atomic(path, payload)
        return path

    def reset(self, recording_id: str, draft_id: str) -> CalibrationDraft:
        path = self._path(recording_id, draft_id).with_name("initial.json")
        if not path.is_file():
            raise CalibrationRefinementError(
                f"calibration draft initial value is missing: {draft_id}"
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            draft = CalibrationDraft.from_mapping(_mapping(raw, "calibration draft"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, CardSceneContractError) as error:
            raise CalibrationRefinementError(
                "calibration draft initial value is not valid JSON"
            ) from error
        self.publish(draft)
        return draft

    def load(self, recording_id: str, draft_id: str) -> CalibrationDraft:
        path = self._path(recording_id, draft_id)
        if not path.is_file():
            raise CalibrationRefinementError(f"calibration draft is missing: {draft_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return CalibrationDraft.from_mapping(_mapping(raw, "calibration draft"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, CardSceneContractError) as error:
            raise CalibrationRefinementError("calibration draft is not valid JSON") from error

    def list_draft_ids(self, recording_id: str) -> tuple[str, ...]:
        root = (
            self.workspace_root
            / _identifier(recording_id, "recording_id")
            / CALIBRATION_DRAFT_STORE_DIRECTORY
        )
        if not root.is_dir():
            return ()
        return tuple(sorted(path.parent.name for path in root.glob("*/draft.json")))


class CalibrationReflowReceiptStore:
    """Persist immutable calibration reflow receipts for retry and audit."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()

    def _path(self, recording_id: str, receipt_id: str) -> Path:
        return (
            self.workspace_root
            / _identifier(recording_id, "recording_id")
            / CALIBRATION_REFLOW_STORE_DIRECTORY
            / _identifier(receipt_id, "receipt_id")
            / "receipt.json"
        )

    def publish(self, recording_id: str, receipt: CalibrationReflowReceipt) -> Path:
        path = self._path(recording_id, receipt.receipt_id)
        payload = canonical_json_bytes(receipt.to_mapping())
        if path.exists() and path.read_bytes() != payload:
            raise CalibrationRefinementError("calibration reflow receipt is immutable")
        if not path.exists():
            _write_atomic(path, payload)
        return path

    def load(self, recording_id: str, receipt_id: str) -> CalibrationReflowReceipt:
        path = self._path(recording_id, receipt_id)
        if not path.is_file():
            raise CalibrationRefinementError(f"calibration reflow receipt is missing: {receipt_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return CalibrationReflowReceipt.from_mapping(_mapping(raw, "reflow receipt"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, CardSceneContractError) as error:
            raise CalibrationRefinementError(
                "calibration reflow receipt is not valid JSON"
            ) from error


__all__ = [
    "CALIBRATION_DRAFT_STORE_DIRECTORY",
    "CALIBRATION_REFLOW_STORE_DIRECTORY",
    "CALIBRATION_REFINEMENT_SCHEMA_VERSION",
    "CardSceneReflowResult",
    "CalibrationDraftStore",
    "CalibrationReflowReceiptStore",
    "CalibrationRefinementError",
    "apply_anchor_command_to_draft",
    "anchor_observations_from_local_result",
    "build_calibration_draft",
    "build_calibration_preview",
    "build_published_calibration_run",
    "exclude_anchors_in_reviewed_ignore_regions",
    "reflow_card_scene_draft",
    "reflow_reference_items",
]
