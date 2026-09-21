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
    CardSceneContractError,
    anchor_fit_contributions,
    deduplicate_anchor_observations,
    validate_pinned_anchor_conflicts,
)

from .card_plane_calibration import calibrate_recording
from .card_plane_geometry import (
    CardPlaneGeometryError,
    TablePlaneCalibration,
    apply_homography,
    card_residual,
    fit_table_plane,
    project_fixed_card,
    quadrilateral_orientations,
)
from .pipeline_data import canonical_json_bytes

CALIBRATION_DRAFT_STORE_DIRECTORY = "table-plane-calibration-drafts"
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
    weighted_quads: list[np.ndarray] = []
    for anchor_id in sorted(selected_by_id):
        contribution = contribution_by_id.get(anchor_id)
        if contribution is None or contribution.weight <= 0:
            continue
        # Repeating a quad is the deterministic integer approximation of its bounded weight.  A
        # fixed multiplier keeps candidate (1), accepted (4), and adjusted (12) distinct while
        # preserving the exact per-frame and per-region caps from the shared contract.
        repetitions = max(1, int(round(contribution.weight * 4.0)))
        weighted_quads.extend([_source_quad(selected_by_id[anchor_id])] * repetitions)
    if len(weighted_quads) < MIN_ELIGIBLE_ANCHORS:
        raise CalibrationRefinementError("anchor contribution weights produced an empty fit")
    try:
        fit = fit_table_plane(weighted_quads)
        candidate = TablePlaneCalibration.create(
            calibration_revision_id="calibration-preview-" + _digest(
                {
                    "base": base.calibration_digest,
                    "anchors": [anchor.observation_digest for anchor in selected],
                    "weights": [
                        contribution_by_id[item.anchor_id].weight for item in selected
                    ],
                }
            )[:24],
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
        pose = _mapping(raw_pose, "scene pose")
        card_id = pose.get("card_id")
        center = pose.get("center")
        rotation = pose.get("rotation_degrees")
        if not isinstance(card_id, str) or not isinstance(center, (list, tuple)):
            continue
        base_quad = project_fixed_card(
            np.asarray(base.table_to_image, dtype=np.float64),
            center,
            _finite(rotation, "scene rotation"),
            base.card_short_size,
            base.card_long_size,
        )
        candidate_quad = project_fixed_card(
            np.asarray(candidate.table_to_image, dtype=np.float64),
            center,
            _finite(rotation, "scene rotation"),
            candidate.card_short_size,
            candidate.card_long_size,
        )
        displacement = float(np.max(np.linalg.norm(candidate_quad - base_quad, axis=1)))
        if displacement > maximum:
            maximum = displacement
        if displacement > 0.0:
            card_ids.append(card_id)
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
            message="weighted table-plane residual is within the frozen gate",
        ),
        CalibrationGate.create(
            gate_id="held_out_alignment_change",
            passed=held_out_change <= MAX_HELD_OUT_ALIGNMENT_CHANGE_PX,
            observed=held_out_change,
            threshold=MAX_HELD_OUT_ALIGNMENT_CHANGE_PX,
            message="held-out source alignment change is within the frozen gate",
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
            eligible=current.eligible,
            eligibility_reason=current.eligibility_reason,
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


__all__ = [
    "CALIBRATION_DRAFT_STORE_DIRECTORY",
    "CALIBRATION_REFINEMENT_SCHEMA_VERSION",
    "CalibrationDraftStore",
    "CalibrationRefinementError",
    "apply_anchor_command_to_draft",
    "anchor_observations_from_local_result",
    "build_calibration_draft",
    "build_calibration_preview",
]
