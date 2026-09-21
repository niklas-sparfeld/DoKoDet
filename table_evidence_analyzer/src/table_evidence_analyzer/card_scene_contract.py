"""Versioned contracts for proposed card scenes and calibration refinement.

The contracts in this module are pipeline-data contracts.  They deliberately do not import the
pose editor or the geometry implementation.  A proposed scene can carry the fixed-size geometry
payload produced by that implementation, but the outer proposal value remains processor output.
Only a :class:`ReviewedCardSceneRecord` can provide reviewed geometry to a
:class:`CardSceneDraft`.

All digests use the same canonical JSON rules as the other table-evidence contracts.  Numeric
policy values and state transitions are explicit here so later processor and UI milestones do not
silently invent a second contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PROPOSED_CARD_SCENE_SCHEMA_VERSION = "proposed-card-scene/v1"
REVIEWED_CARD_SCENE_RECORD_SCHEMA_VERSION = "reviewed-card-scene-record/v1"
CARD_SCENE_DRAFT_SCHEMA_VERSION = "card-scene-draft/v1"
CALIBRATION_DRAFT_SCHEMA_VERSION = "table-plane-calibration-draft/v1"
ANCHOR_OBSERVATION_SCHEMA_VERSION = "calibration-anchor-observation/v1"
ANCHOR_COMMAND_SCHEMA_VERSION = "calibration-anchor-command/v1"
CALIBRATION_PREVIEW_SCHEMA_VERSION = "table-plane-calibration-preview/v1"
CALIBRATION_REFLOW_RECEIPT_SCHEMA_VERSION = "calibration-reflow-receipt/v1"
CALIBRATION_FAILURE_SCHEMA_VERSION = "calibration-failure/v1"

CARD_REVIEW_STATES = ("pending", "accepted", "adjusted", "rejected")
ANCHOR_STATES = ("candidate", "accepted", "adjusted", "pinned", "excluded")
ANCHOR_WEIGHT_CLASSES = ("candidate", "accepted", "adjusted")
FRAME_REVIEW_STATES = ("pending", "complete", "unusable")
CALIBRATION_DRAFT_STATES = ("clean", "dirty", "blocked")
HANDLE_CONSTRAINTS = ("diagonal", "card_x", "card_y")
CALIBRATION_PREVIEW_STATES = ("pass", "blocked")
CALIBRATION_FAILURE_CODES = (
    "stale_detector_revision",
    "stale_calibration_revision",
    "stale_source_frame",
    "conflicting_pinned_anchors",
    "insufficient_anchors",
    "fit_gate_failed",
    "held_out_gate_failed",
    "reviewed_displacement_exceeded",
    "source_lineage_invalid",
)

# These values are part of the M0 contract.  A later milestone may use them, but may not replace
# them with UI-local values.
ANCHOR_BASE_WEIGHTS = {"candidate": 1.0, "accepted": 4.0, "adjusted": 12.0}
ANCHOR_FRAME_WEIGHT_CAP = 24.0
ANCHOR_TABLE_REGION_WEIGHT_CAP = 24.0
ANCHOR_PIN_CONFLICT_TOLERANCE_PX = 2.0
ANCHOR_MIN_SIDE_LENGTH_TABLE_UNITS = 0.25
ANCHOR_SNAP_TOLERANCE_TABLE_UNITS = 0.05
TEMPORAL_DEDUPLICATION_BIN_US = 1_000_000
TABLE_REGION_DEDUPLICATION_BIN_UNITS = 2.0
MIN_ELIGIBLE_ANCHORS = 3
MAX_FIT_RESIDUAL_TABLE_UNITS = 0.08
MAX_HELD_OUT_ALIGNMENT_CHANGE_PX = 8.0
MAX_REVIEWED_SOURCE_DISPLACEMENT_PX = 12.0
MAX_PROPOSED_SOURCE_DISPLACEMENT_PX = 24.0
CARD_ASPECT_RATIO = 1.5
CORNER_ORDER_VERSION = "cyclic-short-edge-first/v1"
HANDLE_MODIFIER_POLICY = {
    "none": "diagonal",
    "shift": "card_x",
    "alt": "card_y",
}
HANDLE_KEYBOARD_POLICY = {
    "d": "diagonal",
    "x": "card_x",
    "y": "card_y",
    "escape": "cancel",
}
REVISION_INVALIDATION_RULES = {
    "detector_revision": "block_proposal_and_apply",
    "calibration_revision": "mark_draft_affected",
    "source_frame_digest": "block_proposal_and_apply",
    "proposal_revision": "reinitialize_pending_rebase_reviewed_and_mark_affected",
    "completed_reference": "immutable",
}

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class CardSceneContractError(ValueError):
    """Raised when a proposed-scene or calibration-refinement contract is invalid."""


class StaleCalibrationEvidenceError(CardSceneContractError):
    """Raised when a proposal or apply operation uses stale immutable lineage."""

    def __init__(self, code: str, message: str, action: str) -> None:
        self.code = code
        self.message = message
        self.action = action
        super().__init__(f"{code}: {message} Action: {action}")

    def to_mapping(self) -> dict[str, str]:
        return {
            "schema_version": CALIBRATION_FAILURE_SCHEMA_VERSION,
            "code": self.code,
            "message": self.message,
            "action": self.action,
        }


def canonical_card_scene_bytes(value: Mapping[str, Any]) -> bytes:
    """Return canonical bytes for one JSON contract value."""

    return _canonical_json_bytes(value)


def _canonical_json_bytes(value: Any) -> bytes:
    _validate_json(value, "value")
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CardSceneContractError(f"{field} must be an object")
    return value


def _strict(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    fields = set(value)
    missing = expected - fields
    unknown = fields - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise CardSceneContractError(f"{field} has invalid fields ({'; '.join(details)})")


def _validate_json(value: Any, field: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CardSceneContractError(f"{field} must contain finite JSON values")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CardSceneContractError(f"{field} object keys must be strings")
            _validate_json(child, f"{field}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json(child, f"{field}[{index}]")
        return
    raise CardSceneContractError(f"{field} must contain JSON-compatible values")


def _json_object(value: Any, field: str) -> dict[str, Any]:
    data = _mapping(value, field)
    _validate_json(data, field)
    return json.loads(_canonical_json_bytes(data).decode("utf-8"))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CardSceneContractError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) > 128 or _IDENTIFIER.fullmatch(result) is None:
        raise CardSceneContractError(f"{field} must be a safe identifier")
    return result


def _digest_value(value: Any, field: str) -> str:
    result = _text(value, field)
    if _DIGEST.fullmatch(result) is None:
        raise CardSceneContractError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardSceneContractError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CardSceneContractError(f"{field} must be a finite number")
    return result


def _non_negative(value: Any, field: str) -> float:
    result = _finite(value, field)
    if result < 0:
        raise CardSceneContractError(f"{field} must be non-negative")
    return result


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CardSceneContractError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: Any, field: str) -> int:
    result = _non_negative_int(value, field)
    if result == 0:
        raise CardSceneContractError(f"{field} must be a positive integer")
    return result


def _point(value: Any, field: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CardSceneContractError(f"{field} must contain two coordinates")
    return (_finite(value[0], f"{field}[0]"), _finite(value[1], f"{field}[1]"))


def _signed_area(points: Sequence[tuple[float, float]]) -> float:
    return 0.5 * sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def _quad(value: Any, field: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise CardSceneContractError(f"{field} must contain four corners")
    points = tuple(_point(point, f"{field}[{index}]") for index, point in enumerate(value))
    if abs(_signed_area(points)) <= 1e-9:
        raise CardSceneContractError(f"{field} must have positive area")
    signs: list[float] = []
    for index in range(4):
        first = points[index]
        second = points[(index + 1) % 4]
        third = points[(index + 2) % 4]
        signs.append(
            (second[0] - first[0]) * (third[1] - second[1])
            - (second[1] - first[1]) * (third[0] - second[0])
        )
    if any(sign == 0 or (sign > 0) != (signs[0] > 0) for sign in signs):
        raise CardSceneContractError(f"{field} must be a convex quadrilateral")
    return points


def _round(value: float) -> float:
    return round(float(value), 6)


def _rounded_quad(value: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[_round(point[0]), _round(point[1])] for point in value]


def _identifier_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CardSceneContractError(f"{field} must be a list")
    result = tuple(_identifier(item, f"{field}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise CardSceneContractError(f"{field} must contain unique identifiers")
    return result


def _scene_card_ids(scene: Mapping[str, Any], field: str) -> tuple[str, ...]:
    if scene.get("schema_version") != "reviewed-card-scene/v1":
        raise CardSceneContractError(f"{field}.schema_version must be reviewed-card-scene/v1")
    raw_poses = scene.get("poses")
    if not isinstance(raw_poses, list) or not raw_poses:
        raise CardSceneContractError(f"{field}.poses must be a non-empty list")
    ids: list[str] = []
    for index, raw_pose in enumerate(raw_poses):
        pose = _mapping(raw_pose, f"{field}.poses[{index}]")
        ids.append(_identifier(pose.get("card_id"), f"{field}.poses[{index}].card_id"))
    if len(ids) != len(set(ids)):
        raise CardSceneContractError(f"{field}.poses must contain unique card IDs")
    return tuple(ids)


def _optional_digest(value: Any, field: str) -> str | None:
    return None if value is None else _digest_value(value, field)


@dataclass(frozen=True, slots=True)
class ProposedCardScene:
    """One processor proposal.  It is never reviewed geometry by itself."""

    proposal_id: str
    source_frame_id: str
    source_frame_digest: str
    detector_revision_id: str
    detector_revision_digest: str
    calibration_revision_id: str
    calibration_digest: str
    initializer_recipe_version: str
    status: str
    initialized_scene: dict[str, Any] | None
    fit_diagnostics: dict[str, Any]
    unsupported_reason: str | None
    proposal_digest: str

    @classmethod
    def create(
        cls,
        *,
        proposal_id: str,
        source_frame_id: str,
        source_frame_digest: str,
        detector_revision_id: str,
        detector_revision_digest: str,
        calibration_revision_id: str,
        calibration_digest: str,
        initializer_recipe_version: str,
        status: str,
        initialized_scene: Mapping[str, Any] | None,
        fit_diagnostics: Mapping[str, Any],
        unsupported_reason: str | None = None,
    ) -> "ProposedCardScene":
        if status not in {"supported", "unsupported"}:
            raise CardSceneContractError("proposal.status must be supported or unsupported")
        if status == "supported" and initialized_scene is None:
            raise CardSceneContractError("supported proposal needs initialized_scene")
        if status == "unsupported" and initialized_scene is not None:
            raise CardSceneContractError("unsupported proposal cannot contain initialized_scene")
        if status == "unsupported" and unsupported_reason is None:
            raise CardSceneContractError("unsupported proposal needs unsupported_reason")
        if status == "supported" and unsupported_reason is not None:
            raise CardSceneContractError("supported proposal cannot contain unsupported_reason")
        scene = (
            None
            if initialized_scene is None
            else _json_object(initialized_scene, "initialized_scene")
        )
        if scene is not None:
            _scene_card_ids(scene, "initialized_scene")
        diagnostics = _json_object(fit_diagnostics, "fit_diagnostics")
        core = {
            "schema_version": PROPOSED_CARD_SCENE_SCHEMA_VERSION,
            "proposal_id": _identifier(proposal_id, "proposal_id"),
            "source_frame_id": _identifier(source_frame_id, "source_frame_id"),
            "source_frame_digest": _digest_value(source_frame_digest, "source_frame_digest"),
            "detector_revision_id": _identifier(detector_revision_id, "detector_revision_id"),
            "detector_revision_digest": _digest_value(
                detector_revision_digest, "detector_revision_digest"
            ),
            "calibration_revision_id": _identifier(
                calibration_revision_id, "calibration_revision_id"
            ),
            "calibration_digest": _digest_value(calibration_digest, "calibration_digest"),
            "initializer_recipe_version": _identifier(
                initializer_recipe_version, "initializer_recipe_version"
            ),
            "status": status,
            "initialized_scene": scene,
            "fit_diagnostics": diagnostics,
            "unsupported_reason": (
                None
                if unsupported_reason is None
                else _text(unsupported_reason, "unsupported_reason")
            ),
        }
        return cls(
            proposal_id=core["proposal_id"],
            source_frame_id=core["source_frame_id"],
            source_frame_digest=core["source_frame_digest"],
            detector_revision_id=core["detector_revision_id"],
            detector_revision_digest=core["detector_revision_digest"],
            calibration_revision_id=core["calibration_revision_id"],
            calibration_digest=core["calibration_digest"],
            initializer_recipe_version=core["initializer_recipe_version"],
            status=core["status"],
            initialized_scene=scene,
            fit_diagnostics=diagnostics,
            unsupported_reason=core["unsupported_reason"],
            proposal_digest=_digest(core),
        )

    @property
    def card_ids(self) -> tuple[str, ...]:
        return (
            ()
            if self.initialized_scene is None
            else _scene_card_ids(self.initialized_scene, "initialized_scene")
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": PROPOSED_CARD_SCENE_SCHEMA_VERSION,
            "proposal_id": self.proposal_id,
            "source_frame_id": self.source_frame_id,
            "source_frame_digest": self.source_frame_digest,
            "detector_revision_id": self.detector_revision_id,
            "detector_revision_digest": self.detector_revision_digest,
            "calibration_revision_id": self.calibration_revision_id,
            "calibration_digest": self.calibration_digest,
            "initializer_recipe_version": self.initializer_recipe_version,
            "status": self.status,
            "initialized_scene": self.initialized_scene,
            "fit_diagnostics": self.fit_diagnostics,
            "unsupported_reason": self.unsupported_reason,
        }
        return {**core, "proposal_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "proposal") -> "ProposedCardScene":
        data = _mapping(raw, context)
        expected = {
            "schema_version",
            "proposal_id",
            "source_frame_id",
            "source_frame_digest",
            "detector_revision_id",
            "detector_revision_digest",
            "calibration_revision_id",
            "calibration_digest",
            "initializer_recipe_version",
            "status",
            "initialized_scene",
            "fit_diagnostics",
            "unsupported_reason",
            "proposal_digest",
        }
        _strict(data, expected, context)
        if data["schema_version"] != PROPOSED_CARD_SCENE_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        proposal = cls.create(
            proposal_id=data["proposal_id"],
            source_frame_id=data["source_frame_id"],
            source_frame_digest=data["source_frame_digest"],
            detector_revision_id=data["detector_revision_id"],
            detector_revision_digest=data["detector_revision_digest"],
            calibration_revision_id=data["calibration_revision_id"],
            calibration_digest=data["calibration_digest"],
            initializer_recipe_version=data["initializer_recipe_version"],
            status=data["status"],
            initialized_scene=data["initialized_scene"],
            fit_diagnostics=data["fit_diagnostics"],
            unsupported_reason=data["unsupported_reason"],
        )
        if data["proposal_digest"] != proposal.proposal_digest:
            raise CardSceneContractError(f"{context}.proposal_digest does not match its contents")
        return proposal


@dataclass(frozen=True, slots=True)
class ReviewedCardSceneRecord:
    """Reviewed geometry plus the proposal lineage that it resolves."""

    proposal_id: str
    scene: dict[str, Any]
    decision: str
    reviewed_scene_digest: str

    @classmethod
    def create(
        cls,
        *,
        proposal_id: str,
        scene: Mapping[str, Any],
        decision: str,
    ) -> "ReviewedCardSceneRecord":
        if decision not in {"accepted", "adjusted", "manual"}:
            raise CardSceneContractError("reviewed scene decision is unsupported")
        selected_scene = _json_object(scene, "reviewed_scene.scene")
        _scene_card_ids(selected_scene, "reviewed_scene.scene")
        core = {
            "schema_version": REVIEWED_CARD_SCENE_RECORD_SCHEMA_VERSION,
            "proposal_id": _identifier(proposal_id, "reviewed_scene.proposal_id"),
            "scene": selected_scene,
            "decision": decision,
        }
        return cls(
            proposal_id=core["proposal_id"],
            scene=selected_scene,
            decision=decision,
            reviewed_scene_digest=_digest(core),
        )

    @property
    def card_ids(self) -> tuple[str, ...]:
        return _scene_card_ids(self.scene, "reviewed_scene.scene")

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": REVIEWED_CARD_SCENE_RECORD_SCHEMA_VERSION,
            "proposal_id": self.proposal_id,
            "scene": self.scene,
            "decision": self.decision,
        }
        return {**core, "reviewed_scene_digest": _digest(core)}

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "reviewed_scene"
    ) -> "ReviewedCardSceneRecord":
        data = _mapping(raw, context)
        expected = {"schema_version", "proposal_id", "scene", "decision", "reviewed_scene_digest"}
        _strict(data, expected, context)
        if data["schema_version"] != REVIEWED_CARD_SCENE_RECORD_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        record = cls.create(
            proposal_id=data["proposal_id"], scene=data["scene"], decision=data["decision"]
        )
        if data["reviewed_scene_digest"] != record.reviewed_scene_digest:
            raise CardSceneContractError(f"{context}.reviewed_scene_digest is stale")
        return record


@dataclass(frozen=True, slots=True)
class CardReviewState:
    """One card decision.  It contains no geometry authority."""

    card_id: str
    source: str
    proposal_id: str | None
    state: str

    @classmethod
    def create(
        cls, *, card_id: str, source: str, proposal_id: str | None, state: str
    ) -> "CardReviewState":
        if source not in {"proposal", "manual"}:
            raise CardSceneContractError("card review source is unsupported")
        if state not in CARD_REVIEW_STATES:
            raise CardSceneContractError("card review state is unsupported")
        if source == "proposal" and proposal_id is None:
            raise CardSceneContractError("proposal card review needs proposal_id")
        if source == "manual" and proposal_id is not None:
            raise CardSceneContractError("manual card review cannot have proposal_id")
        return cls(
            card_id=_identifier(card_id, "card_review.card_id"),
            source=source,
            proposal_id=None if proposal_id is None else _identifier(proposal_id, "proposal_id"),
            state=state,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "source": self.source,
            "proposal_id": self.proposal_id,
            "state": self.state,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> "CardReviewState":
        data = _mapping(raw, context)
        _strict(data, {"card_id", "source", "proposal_id", "state"}, context)
        return cls.create(
            card_id=data["card_id"],
            source=data["source"],
            proposal_id=data["proposal_id"],
            state=data["state"],
        )


@dataclass(frozen=True, slots=True)
class FrameReviewCompletion:
    """The explicit completion decision for one source frame."""

    state: str
    unresolved_card_ids: tuple[str, ...]
    reason: str | None

    @classmethod
    def create(
        cls, *, state: str, unresolved_card_ids: Sequence[str], reason: str | None = None
    ) -> "FrameReviewCompletion":
        if state not in FRAME_REVIEW_STATES:
            raise CardSceneContractError("frame completion state is unsupported")
        unresolved = tuple(
            _identifier(card_id, "completion.unresolved_card_ids")
            for card_id in unresolved_card_ids
        )
        if len(unresolved) != len(set(unresolved)):
            raise CardSceneContractError("completion.unresolved_card_ids must be unique")
        if state == "pending" and not unresolved:
            raise CardSceneContractError("pending frame completion needs unresolved cards")
        if state == "complete" and unresolved:
            raise CardSceneContractError("complete frame completion cannot have unresolved cards")
        if state == "unusable" and reason is None:
            raise CardSceneContractError("unusable frame completion needs a reason")
        if state != "unusable" and reason is not None:
            raise CardSceneContractError("only unusable frame completion can have a reason")
        return cls(
            state=state,
            unresolved_card_ids=unresolved,
            reason=None if reason is None else _text(reason, "completion.reason"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "unresolved_card_ids": list(self.unresolved_card_ids),
            "reason": self.reason,
        }

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "completion"
    ) -> "FrameReviewCompletion":
        data = _mapping(raw, context)
        _strict(data, {"state", "unresolved_card_ids", "reason"}, context)
        return cls.create(
            state=data["state"],
            unresolved_card_ids=data["unresolved_card_ids"],
            reason=data["reason"],
        )


@dataclass(frozen=True, slots=True)
class CardSceneDraft:
    """Mutable-review value that keeps proposal and reviewed authority separate."""

    proposal: ProposedCardScene
    reviewed: ReviewedCardSceneRecord | None
    card_states: tuple[CardReviewState, ...]
    completion: FrameReviewCompletion
    draft_revision: int
    draft_digest: str

    @classmethod
    def create(
        cls,
        *,
        proposal: ProposedCardScene,
        reviewed: ReviewedCardSceneRecord | None,
        card_states: Sequence[CardReviewState],
        completion: FrameReviewCompletion,
        draft_revision: int = 0,
    ) -> "CardSceneDraft":
        if draft_revision < 0:
            raise CardSceneContractError("draft_revision must be non-negative")
        states = tuple(card_states)
        state_ids = tuple(item.card_id for item in states)
        if len(state_ids) != len(set(state_ids)):
            raise CardSceneContractError("card_states must contain unique card IDs")
        proposal_ids = set(proposal.card_ids)
        state_proposal_ids = {item.card_id for item in states if item.source == "proposal"}
        if state_proposal_ids != proposal_ids:
            missing = sorted(proposal_ids - state_proposal_ids)
            extra = sorted(state_proposal_ids - proposal_ids)
            raise CardSceneContractError(
                f"card_states do not match proposal cards (missing={missing}, extra={extra})"
            )
        if any(
            item.proposal_id != proposal.proposal_id for item in states if item.source == "proposal"
        ):
            raise CardSceneContractError("proposal card states must reference the current proposal")
        pending_ids = tuple(sorted(item.card_id for item in states if item.state == "pending"))
        if set(pending_ids) != set(completion.unresolved_card_ids):
            raise CardSceneContractError(
                "completion unresolved cards must equal pending card states"
            )
        if proposal.status == "unsupported":
            if states or completion.state != "unusable":
                raise CardSceneContractError(
                    "unsupported proposals can only have unusable completion"
                )
            reviewed = None
        resolved_ids = {item.card_id for item in states if item.state in {"accepted", "adjusted"}}
        if reviewed is None and resolved_ids:
            raise CardSceneContractError("resolved card states need a reviewed scene value")
        if reviewed is not None:
            if reviewed.proposal_id != proposal.proposal_id:
                raise CardSceneContractError("reviewed scene must reference the current proposal")
            if set(reviewed.card_ids) != resolved_ids:
                raise CardSceneContractError(
                    "reviewed scene must contain accepted or adjusted cards only"
                )
        if completion.state == "complete" and (reviewed is None or not resolved_ids):
            raise CardSceneContractError("complete frame needs a non-empty reviewed scene")
        core = {
            "schema_version": CARD_SCENE_DRAFT_SCHEMA_VERSION,
            "proposal": proposal.to_mapping(),
            "reviewed": None if reviewed is None else reviewed.to_mapping(),
            "card_states": [item.to_mapping() for item in states],
            "completion": completion.to_mapping(),
            "draft_revision": draft_revision,
        }
        return cls(
            proposal=proposal,
            reviewed=reviewed,
            card_states=states,
            completion=completion,
            draft_revision=draft_revision,
            draft_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": CARD_SCENE_DRAFT_SCHEMA_VERSION,
            "proposal": self.proposal.to_mapping(),
            "reviewed": None if self.reviewed is None else self.reviewed.to_mapping(),
            "card_states": [item.to_mapping() for item in self.card_states],
            "completion": self.completion.to_mapping(),
            "draft_revision": self.draft_revision,
        }
        return {**core, "draft_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "card_scene") -> "CardSceneDraft":
        data = _mapping(raw, context)
        expected = {
            "schema_version",
            "proposal",
            "reviewed",
            "card_states",
            "completion",
            "draft_revision",
            "draft_digest",
        }
        _strict(data, expected, context)
        if data["schema_version"] != CARD_SCENE_DRAFT_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        raw_states = data["card_states"]
        if not isinstance(raw_states, list):
            raise CardSceneContractError(f"{context}.card_states must be a list")
        draft = cls.create(
            proposal=ProposedCardScene.from_mapping(
                _mapping(data["proposal"], f"{context}.proposal"), f"{context}.proposal"
            ),
            reviewed=(
                None
                if data["reviewed"] is None
                else ReviewedCardSceneRecord.from_mapping(
                    _mapping(data["reviewed"], f"{context}.reviewed"), f"{context}.reviewed"
                )
            ),
            card_states=tuple(
                CardReviewState.from_mapping(item, f"{context}.card_states[{index}]")
                for index, item in enumerate(raw_states)
            ),
            completion=FrameReviewCompletion.from_mapping(
                _mapping(data["completion"], f"{context}.completion"), f"{context}.completion"
            ),
            draft_revision=data["draft_revision"],
        )
        if data["draft_digest"] != draft.draft_digest:
            raise CardSceneContractError(f"{context}.draft_digest does not match its contents")
        return draft


@dataclass(frozen=True, slots=True)
class AnchorObservation:
    """One complete-card calibration observation and its operator state."""

    anchor_id: str
    card_id: str
    source_frame_id: str
    source_frame_digest: str
    detector_revision_id: str
    quadrilateral: tuple[tuple[float, float], ...]
    confidence: float
    temporal_bin: str
    table_region_bin: str
    scale_bin: str
    orientation_bin: str
    eligible: bool
    eligibility_reason: str | None
    state: str
    weight_class: str
    observation_digest: str

    @classmethod
    def create(
        cls,
        *,
        anchor_id: str,
        card_id: str,
        source_frame_id: str,
        source_frame_digest: str,
        detector_revision_id: str,
        quadrilateral: Sequence[Sequence[float]],
        confidence: float,
        temporal_bin: str,
        table_region_bin: str,
        scale_bin: str,
        orientation_bin: str,
        eligible: bool,
        eligibility_reason: str | None,
        state: str = "candidate",
        weight_class: str = "candidate",
    ) -> "AnchorObservation":
        if state not in ANCHOR_STATES:
            raise CardSceneContractError("anchor state is unsupported")
        if weight_class not in ANCHOR_WEIGHT_CLASSES:
            raise CardSceneContractError("anchor weight_class is unsupported")
        if not isinstance(eligible, bool):
            raise CardSceneContractError("anchor eligible must be a boolean")
        if eligible and eligibility_reason is not None:
            raise CardSceneContractError("eligible anchor cannot have eligibility_reason")
        if not eligible and eligibility_reason is None:
            raise CardSceneContractError("ineligible anchor needs eligibility_reason")
        if state in {"accepted", "adjusted", "pinned"} and not eligible:
            raise CardSceneContractError(
                "ineligible anchor cannot be accepted, adjusted, or pinned"
            )
        core = {
            "schema_version": ANCHOR_OBSERVATION_SCHEMA_VERSION,
            "anchor_id": _identifier(anchor_id, "anchor_id"),
            "card_id": _identifier(card_id, "card_id"),
            "source_frame_id": _identifier(source_frame_id, "source_frame_id"),
            "source_frame_digest": _digest_value(source_frame_digest, "source_frame_digest"),
            "detector_revision_id": _identifier(detector_revision_id, "detector_revision_id"),
            "quadrilateral": _rounded_quad(_quad(quadrilateral, "quadrilateral")),
            "confidence": _round(_finite(confidence, "confidence")),
            "temporal_bin": _identifier(temporal_bin, "temporal_bin"),
            "table_region_bin": _identifier(table_region_bin, "table_region_bin"),
            "scale_bin": _identifier(scale_bin, "scale_bin"),
            "orientation_bin": _identifier(orientation_bin, "orientation_bin"),
            "eligible": eligible,
            "eligibility_reason": (
                None
                if eligibility_reason is None
                else _text(eligibility_reason, "eligibility_reason")
            ),
            "state": state,
            "weight_class": weight_class,
        }
        if core["confidence"] < 0.0:
            raise CardSceneContractError("confidence must be non-negative")
        return cls(
            anchor_id=core["anchor_id"],
            card_id=core["card_id"],
            source_frame_id=core["source_frame_id"],
            source_frame_digest=core["source_frame_digest"],
            detector_revision_id=core["detector_revision_id"],
            quadrilateral=tuple(tuple(point) for point in core["quadrilateral"]),
            confidence=core["confidence"],
            temporal_bin=core["temporal_bin"],
            table_region_bin=core["table_region_bin"],
            scale_bin=core["scale_bin"],
            orientation_bin=core["orientation_bin"],
            eligible=core["eligible"],
            eligibility_reason=core["eligibility_reason"],
            state=core["state"],
            weight_class=core["weight_class"],
            observation_digest=_digest(core),
        )

    @property
    def deduplication_key(self) -> tuple[str, str, str, str]:
        return (self.temporal_bin, self.table_region_bin, self.scale_bin, self.orientation_bin)

    @property
    def base_weight(self) -> float:
        return ANCHOR_BASE_WEIGHTS[self.weight_class]

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": ANCHOR_OBSERVATION_SCHEMA_VERSION,
            "anchor_id": self.anchor_id,
            "card_id": self.card_id,
            "source_frame_id": self.source_frame_id,
            "source_frame_digest": self.source_frame_digest,
            "detector_revision_id": self.detector_revision_id,
            "quadrilateral": _rounded_quad(self.quadrilateral),
            "confidence": _round(self.confidence),
            "temporal_bin": self.temporal_bin,
            "table_region_bin": self.table_region_bin,
            "scale_bin": self.scale_bin,
            "orientation_bin": self.orientation_bin,
            "eligible": self.eligible,
            "eligibility_reason": self.eligibility_reason,
            "state": self.state,
            "weight_class": self.weight_class,
        }
        return {**core, "observation_digest": _digest(core)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "anchor") -> "AnchorObservation":
        data = _mapping(raw, context)
        expected = {
            "schema_version",
            "anchor_id",
            "card_id",
            "source_frame_id",
            "source_frame_digest",
            "detector_revision_id",
            "quadrilateral",
            "confidence",
            "temporal_bin",
            "table_region_bin",
            "scale_bin",
            "orientation_bin",
            "eligible",
            "eligibility_reason",
            "state",
            "weight_class",
            "observation_digest",
        }
        _strict(data, expected, context)
        if data["schema_version"] != ANCHOR_OBSERVATION_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        anchor = cls.create(
            anchor_id=data["anchor_id"],
            card_id=data["card_id"],
            source_frame_id=data["source_frame_id"],
            source_frame_digest=data["source_frame_digest"],
            detector_revision_id=data["detector_revision_id"],
            quadrilateral=data["quadrilateral"],
            confidence=data["confidence"],
            temporal_bin=data["temporal_bin"],
            table_region_bin=data["table_region_bin"],
            scale_bin=data["scale_bin"],
            orientation_bin=data["orientation_bin"],
            eligible=data["eligible"],
            eligibility_reason=data["eligibility_reason"],
            state=data["state"],
            weight_class=data["weight_class"],
        )
        if data["observation_digest"] != anchor.observation_digest:
            raise CardSceneContractError(f"{context}.observation_digest is stale")
        return anchor


def _quad_distance(left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]) -> float:
    return max(
        math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))
        for a, b in zip(left, right, strict=True)
    )


def validate_pinned_anchor_conflicts(anchors: Sequence[AnchorObservation]) -> None:
    """Reject pins that disagree inside one temporal/spatial evidence bucket."""

    grouped: dict[tuple[str, str, str, str], list[AnchorObservation]] = defaultdict(list)
    for anchor in anchors:
        if anchor.state == "pinned":
            grouped[anchor.deduplication_key].append(anchor)
    for key, values in grouped.items():
        for index, left in enumerate(values):
            for right in values[index + 1 :]:
                if (
                    _quad_distance(left.quadrilateral, right.quadrilateral)
                    > ANCHOR_PIN_CONFLICT_TOLERANCE_PX
                ):
                    ids = ", ".join(sorted((left.anchor_id, right.anchor_id)))
                    raise CardSceneContractError(
                        "conflicting pinned anchors "
                        f"({ids}) in bucket {'/'.join(key)}; unpin or correct one anchor"
                    )


@dataclass(frozen=True, slots=True)
class AnchorContribution:
    anchor_id: str
    deduplication_key: tuple[str, str, str, str]
    base_weight: float
    weight: float
    capped: bool

    def to_mapping(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "deduplication_key": list(self.deduplication_key),
            "base_weight": _round(self.base_weight),
            "weight": _round(self.weight),
            "capped": self.capped,
        }


def deduplicate_anchor_observations(
    anchors: Sequence[AnchorObservation],
) -> tuple[tuple[AnchorObservation, ...], tuple[str, ...]]:
    """Keep one deterministic eligible observation per temporal/spatial evidence bucket."""

    validate_pinned_anchor_conflicts(anchors)
    rank = {"candidate": 0, "accepted": 1, "adjusted": 2, "pinned": 3, "excluded": -1}
    buckets: dict[tuple[str, str, str, str], list[AnchorObservation]] = defaultdict(list)
    for anchor in anchors:
        if anchor.eligible and anchor.state != "excluded":
            buckets[anchor.deduplication_key].append(anchor)
    selected: list[AnchorObservation] = []
    rejected: list[str] = []
    for key in sorted(buckets):
        values = sorted(
            buckets[key],
            key=lambda item: (
                -rank[item.state],
                -item.base_weight,
                -item.confidence,
                item.anchor_id,
            ),
        )
        selected.append(values[0])
        rejected.extend(item.anchor_id for item in values[1:])
    return tuple(selected), tuple(sorted(rejected))


def anchor_fit_contributions(
    anchors: Sequence[AnchorObservation],
) -> tuple[AnchorContribution, ...]:
    """Return relative weights after deterministic de-duplication and contribution caps."""

    selected, _rejected = deduplicate_anchor_observations(anchors)
    frame_totals: dict[str, float] = defaultdict(float)
    region_totals: dict[str, float] = defaultdict(float)
    for anchor in selected:
        frame_totals[anchor.source_frame_id] += anchor.base_weight
        region_totals[anchor.table_region_bin] += anchor.base_weight
    contributions: list[AnchorContribution] = []
    for anchor in selected:
        frame_scale = min(1.0, ANCHOR_FRAME_WEIGHT_CAP / frame_totals[anchor.source_frame_id])
        region_scale = min(
            1.0, ANCHOR_TABLE_REGION_WEIGHT_CAP / region_totals[anchor.table_region_bin]
        )
        scale = min(frame_scale, region_scale)
        weight = anchor.base_weight * scale
        contributions.append(
            AnchorContribution(
                anchor_id=anchor.anchor_id,
                deduplication_key=anchor.deduplication_key,
                base_weight=anchor.base_weight,
                weight=weight,
                capped=scale < 1.0,
            )
        )
    return tuple(sorted(contributions, key=lambda item: item.anchor_id))


def constrain_anchor_quad(
    corners: Sequence[Sequence[float]],
    *,
    moved_corner: int,
    pointer: Sequence[float],
    constraint: str,
) -> tuple[tuple[float, float], ...]:
    """Apply the frozen M0 corner-handle mathematics in table coordinates.

    The diagonally opposite corner is fixed.  ``diagonal`` scales both local axes, ``card_x``
    scales the local long axis only, and ``card_y`` scales the local short axis only.  The other
    three corners move as a coupled rectangle.  The input corner order is the frozen cyclic order
    with the short edge first.
    """

    original = _quad(corners, "corners")
    if isinstance(moved_corner, bool) or moved_corner not in range(4):
        raise CardSceneContractError("moved_corner must be from 0 through 3")
    if constraint not in HANDLE_CONSTRAINTS:
        raise CardSceneContractError("anchor constraint is unsupported")
    target = _point(pointer, "pointer")
    opposite = (moved_corner + 2) % 4
    fixed = original[opposite]
    anchor = original[moved_corner]
    long_vector = (
        original[(moved_corner - 1) % 4][0] - anchor[0],
        original[(moved_corner - 1) % 4][1] - anchor[1],
    )
    short_vector = (
        original[(moved_corner + 1) % 4][0] - anchor[0],
        original[(moved_corner + 1) % 4][1] - anchor[1],
    )
    long_length = math.hypot(*long_vector)
    short_length = math.hypot(*short_vector)
    if (
        long_length < ANCHOR_MIN_SIDE_LENGTH_TABLE_UNITS
        or short_length < ANCHOR_MIN_SIDE_LENGTH_TABLE_UNITS
    ):
        raise CardSceneContractError("anchor side is below the minimum handle size")
    long_axis = (long_vector[0] / long_length, long_vector[1] / long_length)
    short_axis = (short_vector[0] / short_length, short_vector[1] / short_length)
    delta = (target[0] - fixed[0], target[1] - fixed[1])
    current_diagonal = (anchor[0] - fixed[0], anchor[1] - fixed[1])
    diagonal_length = math.hypot(*current_diagonal)
    if diagonal_length < 1e-9:
        raise CardSceneContractError("anchor diagonal is zero")
    if constraint == "diagonal":
        scale = (delta[0] * current_diagonal[0] + delta[1] * current_diagonal[1]) / (
            diagonal_length**2
        )
        scale = max(scale, ANCHOR_MIN_SIDE_LENGTH_TABLE_UNITS / max(short_length, 1e-9))
        factors = (scale, scale)
    elif constraint == "card_x":
        long_scale = (delta[0] * long_axis[0] + delta[1] * long_axis[1]) / long_length
        long_scale = max(long_scale, ANCHOR_MIN_SIDE_LENGTH_TABLE_UNITS)
        factors = (long_scale / long_length, 1.0)
    else:
        short_scale = (delta[0] * short_axis[0] + delta[1] * short_axis[1]) / short_length
        short_scale = max(short_scale, ANCHOR_MIN_SIDE_LENGTH_TABLE_UNITS)
        factors = (1.0, short_scale / short_length)
    result: list[tuple[float, float]] = []
    for point in original:
        relative = (point[0] - fixed[0], point[1] - fixed[1])
        long_component = relative[0] * long_axis[0] + relative[1] * long_axis[1]
        short_component = relative[0] * short_axis[0] + relative[1] * short_axis[1]
        transformed = (
            fixed[0]
            + long_axis[0] * long_component * factors[0]
            + short_axis[0] * short_component * factors[1],
            fixed[1]
            + long_axis[1] * long_component * factors[0]
            + short_axis[1] * short_component * factors[1],
        )
        result.append((_round(transformed[0]), _round(transformed[1])))
    result[opposite] = fixed
    return tuple(result)


@dataclass(frozen=True, slots=True)
class AnchorCommand:
    """One ordered operator command produced by a completed anchor gesture."""

    command_id: str
    sequence: int
    expected_draft_revision: int
    anchor_id: str
    operation: str
    state: str | None
    moved_corner: int | None
    constraint: str | None
    corners: tuple[tuple[float, float], ...] | None
    operator_id: str
    command_digest: str

    @classmethod
    def create(
        cls,
        *,
        command_id: str,
        sequence: int,
        expected_draft_revision: int,
        anchor_id: str,
        operation: str,
        state: str | None = None,
        moved_corner: int | None = None,
        constraint: str | None = None,
        corners: Sequence[Sequence[float]] | None = None,
        operator_id: str,
    ) -> "AnchorCommand":
        if operation not in {"set_state", "set_corners", "restore"}:
            raise CardSceneContractError("anchor command operation is unsupported")
        if operation == "set_state":
            if state not in ANCHOR_STATES:
                raise CardSceneContractError("set_state command needs an anchor state")
            if any(value is not None for value in (moved_corner, constraint, corners)):
                raise CardSceneContractError("set_state command cannot contain geometry")
        elif operation == "set_corners":
            if (
                state != "adjusted"
                or moved_corner not in range(4)
                or constraint not in HANDLE_CONSTRAINTS
            ):
                raise CardSceneContractError(
                    "set_corners needs adjusted state, corner, and constraint"
                )
            if corners is None:
                raise CardSceneContractError("set_corners command needs corners")
        else:
            if any(value is not None for value in (state, moved_corner, constraint, corners)):
                raise CardSceneContractError("restore command cannot contain state or geometry")
        normalized_corners = None if corners is None else _quad(corners, "command.corners")
        core = {
            "schema_version": ANCHOR_COMMAND_SCHEMA_VERSION,
            "command_id": _identifier(command_id, "command_id"),
            "sequence": _positive_int(sequence, "sequence"),
            "expected_draft_revision": _non_negative_int(
                expected_draft_revision, "expected_draft_revision"
            ),
            "anchor_id": _identifier(anchor_id, "anchor_id"),
            "operation": operation,
            "state": state,
            "moved_corner": moved_corner,
            "constraint": constraint,
            "corners": None if normalized_corners is None else _rounded_quad(normalized_corners),
            "operator_id": _identifier(operator_id, "operator_id"),
        }
        return cls(
            command_id=core["command_id"],
            sequence=core["sequence"],
            expected_draft_revision=core["expected_draft_revision"],
            anchor_id=core["anchor_id"],
            operation=core["operation"],
            state=core["state"],
            moved_corner=core["moved_corner"],
            constraint=core["constraint"],
            corners=(
                None
                if normalized_corners is None
                else tuple(tuple(point) for point in core["corners"])
            ),
            operator_id=core["operator_id"],
            command_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": ANCHOR_COMMAND_SCHEMA_VERSION,
            "command_id": self.command_id,
            "sequence": self.sequence,
            "expected_draft_revision": self.expected_draft_revision,
            "anchor_id": self.anchor_id,
            "operation": self.operation,
            "state": self.state,
            "moved_corner": self.moved_corner,
            "constraint": self.constraint,
            "corners": None if self.corners is None else _rounded_quad(self.corners),
            "operator_id": self.operator_id,
        }
        return {**core, "command_digest": _digest(core)}

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "anchor_command"
    ) -> "AnchorCommand":
        data = _mapping(raw, context)
        expected = {
            "schema_version",
            "command_id",
            "sequence",
            "expected_draft_revision",
            "anchor_id",
            "operation",
            "state",
            "moved_corner",
            "constraint",
            "corners",
            "operator_id",
            "command_digest",
        }
        _strict(data, expected, context)
        if data["schema_version"] != ANCHOR_COMMAND_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        command = cls.create(
            command_id=data["command_id"],
            sequence=data["sequence"],
            expected_draft_revision=data["expected_draft_revision"],
            anchor_id=data["anchor_id"],
            operation=data["operation"],
            state=data["state"],
            moved_corner=data["moved_corner"],
            constraint=data["constraint"],
            corners=data["corners"],
            operator_id=data["operator_id"],
        )
        if data["command_digest"] != command.command_digest:
            raise CardSceneContractError(f"{context}.command_digest is stale")
        return command


@dataclass(frozen=True, slots=True)
class CalibrationDraft:
    """Mutable calibration refinement state tied to immutable source revisions."""

    draft_id: str
    recording_id: str
    detector_revision_id: str
    detector_revision_digest: str
    base_calibration_revision_id: str
    base_calibration_digest: str
    source_frame_digests: tuple[tuple[str, str], ...]
    anchors: tuple[AnchorObservation, ...]
    commands: tuple[AnchorCommand, ...]
    revision: int
    state: str
    invalidation_reason: str | None
    draft_digest: str

    @classmethod
    def create(
        cls,
        *,
        draft_id: str,
        recording_id: str,
        detector_revision_id: str,
        detector_revision_digest: str,
        base_calibration_revision_id: str,
        base_calibration_digest: str,
        source_frame_digests: Mapping[str, str] | Sequence[tuple[str, str]],
        anchors: Sequence[AnchorObservation],
        commands: Sequence[AnchorCommand],
        revision: int = 0,
        state: str = "clean",
        invalidation_reason: str | None = None,
    ) -> "CalibrationDraft":
        if state not in CALIBRATION_DRAFT_STATES:
            raise CardSceneContractError("calibration draft state is unsupported")
        if revision < 0:
            raise CardSceneContractError("calibration draft revision must be non-negative")
        if state == "blocked" and invalidation_reason is None:
            raise CardSceneContractError("blocked calibration draft needs invalidation_reason")
        if state != "blocked" and invalidation_reason is not None:
            raise CardSceneContractError(
                "only blocked calibration drafts can have invalidation_reason"
            )
        if isinstance(source_frame_digests, Mapping):
            frame_pairs = tuple(sorted(source_frame_digests.items()))
        else:
            frame_pairs = tuple(source_frame_digests)
        normalized_frames = tuple(
            (
                _identifier(frame_id, "source_frame_digests.frame_id"),
                _digest_value(digest, "source_frame_digest"),
            )
            for frame_id, digest in frame_pairs
        )
        if len({item[0] for item in normalized_frames}) != len(normalized_frames):
            raise CardSceneContractError("source_frame_digests must contain unique frame IDs")
        normalized_anchors = tuple(anchors)
        if len({item.anchor_id for item in normalized_anchors}) != len(normalized_anchors):
            raise CardSceneContractError("calibration anchors must have unique IDs")
        normalized_commands = tuple(commands)
        if len({item.command_id for item in normalized_commands}) != len(normalized_commands):
            raise CardSceneContractError("anchor commands must have unique IDs")
        sequences = tuple(item.sequence for item in normalized_commands)
        if sequences != tuple(sorted(sequences)) or len(sequences) != len(set(sequences)):
            raise CardSceneContractError("anchor commands must be in strict sequence order")
        anchor_ids = {item.anchor_id for item in normalized_anchors}
        if any(item.anchor_id not in anchor_ids for item in normalized_commands):
            raise CardSceneContractError("anchor command references an unknown anchor")
        core = {
            "schema_version": CALIBRATION_DRAFT_SCHEMA_VERSION,
            "draft_id": _identifier(draft_id, "draft_id"),
            "recording_id": _identifier(recording_id, "recording_id"),
            "detector_revision_id": _identifier(detector_revision_id, "detector_revision_id"),
            "detector_revision_digest": _digest_value(
                detector_revision_digest, "detector_revision_digest"
            ),
            "base_calibration_revision_id": _identifier(
                base_calibration_revision_id, "base_calibration_revision_id"
            ),
            "base_calibration_digest": _digest_value(
                base_calibration_digest, "base_calibration_digest"
            ),
            "source_frame_digests": [
                {"frame_id": frame_id, "frame_digest": digest}
                for frame_id, digest in normalized_frames
            ],
            "anchors": [item.to_mapping() for item in normalized_anchors],
            "commands": [item.to_mapping() for item in normalized_commands],
            "revision": revision,
            "state": state,
            "invalidation_reason": invalidation_reason,
        }
        return cls(
            draft_id=core["draft_id"],
            recording_id=core["recording_id"],
            detector_revision_id=core["detector_revision_id"],
            detector_revision_digest=core["detector_revision_digest"],
            base_calibration_revision_id=core["base_calibration_revision_id"],
            base_calibration_digest=core["base_calibration_digest"],
            source_frame_digests=normalized_frames,
            anchors=normalized_anchors,
            commands=normalized_commands,
            revision=revision,
            state=state,
            invalidation_reason=invalidation_reason,
            draft_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": CALIBRATION_DRAFT_SCHEMA_VERSION,
            "draft_id": self.draft_id,
            "recording_id": self.recording_id,
            "detector_revision_id": self.detector_revision_id,
            "detector_revision_digest": self.detector_revision_digest,
            "base_calibration_revision_id": self.base_calibration_revision_id,
            "base_calibration_digest": self.base_calibration_digest,
            "source_frame_digests": [
                {"frame_id": frame_id, "frame_digest": digest}
                for frame_id, digest in self.source_frame_digests
            ],
            "anchors": [item.to_mapping() for item in self.anchors],
            "commands": [item.to_mapping() for item in self.commands],
            "revision": self.revision,
            "state": self.state,
            "invalidation_reason": self.invalidation_reason,
        }
        return {**core, "draft_digest": _digest(core)}

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "calibration_draft"
    ) -> "CalibrationDraft":
        data = _mapping(raw, context)
        expected = {
            "schema_version",
            "draft_id",
            "recording_id",
            "detector_revision_id",
            "detector_revision_digest",
            "base_calibration_revision_id",
            "base_calibration_digest",
            "source_frame_digests",
            "anchors",
            "commands",
            "revision",
            "state",
            "invalidation_reason",
            "draft_digest",
        }
        _strict(data, expected, context)
        if data["schema_version"] != CALIBRATION_DRAFT_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        frames = data["source_frame_digests"]
        if not isinstance(frames, list):
            raise CardSceneContractError(f"{context}.source_frame_digests must be a list")
        frame_pairs = []
        for index, raw_frame in enumerate(frames):
            frame = _mapping(raw_frame, f"{context}.source_frame_digests[{index}]")
            _strict(frame, {"frame_id", "frame_digest"}, f"{context}.source_frame_digests[{index}]")
            frame_pairs.append((frame["frame_id"], frame["frame_digest"]))
        anchors = data["anchors"]
        commands = data["commands"]
        if not isinstance(anchors, list) or not isinstance(commands, list):
            raise CardSceneContractError(f"{context}.anchors and commands must be lists")
        draft = cls.create(
            draft_id=data["draft_id"],
            recording_id=data["recording_id"],
            detector_revision_id=data["detector_revision_id"],
            detector_revision_digest=data["detector_revision_digest"],
            base_calibration_revision_id=data["base_calibration_revision_id"],
            base_calibration_digest=data["base_calibration_digest"],
            source_frame_digests=frame_pairs,
            anchors=tuple(
                AnchorObservation.from_mapping(item, f"{context}.anchors[{index}]")
                for index, item in enumerate(anchors)
            ),
            commands=tuple(
                AnchorCommand.from_mapping(item, f"{context}.commands[{index}]")
                for index, item in enumerate(commands)
            ),
            revision=data["revision"],
            state=data["state"],
            invalidation_reason=data["invalidation_reason"],
        )
        if data["draft_digest"] != draft.draft_digest:
            raise CardSceneContractError(f"{context}.draft_digest is stale")
        return draft


def validate_calibration_draft_lineage(
    draft: CalibrationDraft,
    *,
    detector_revision_id: str,
    detector_revision_digest: str,
    calibration_revision_id: str,
    calibration_digest: str,
    source_frame_digests: Mapping[str, str],
) -> None:
    """Check all immutable inputs before proposal creation or calibration apply."""

    if (
        draft.detector_revision_id != detector_revision_id
        or draft.detector_revision_digest != detector_revision_digest
    ):
        raise StaleCalibrationEvidenceError(
            "stale_detector_revision",
            "the selected detector revision changed while the calibration draft was open",
            "reload the selected detector result and create a new proposal draft",
        )
    if (
        draft.base_calibration_revision_id != calibration_revision_id
        or draft.base_calibration_digest != calibration_digest
    ):
        raise StaleCalibrationEvidenceError(
            "stale_calibration_revision",
            "the active calibration revision changed while the calibration draft was open",
            "reload the recording calibration before applying anchor commands",
        )
    expected_frames = dict(draft.source_frame_digests)
    for frame_id, expected_digest in expected_frames.items():
        if source_frame_digests.get(frame_id) != expected_digest:
            raise StaleCalibrationEvidenceError(
                "stale_source_frame",
                f"source frame digest changed for {frame_id}",
                "reload the exact source frame and create a new proposal draft",
            )


@dataclass(frozen=True, slots=True)
class CalibrationFailure:
    code: str
    message: str
    action: str

    @classmethod
    def create(cls, *, code: str, message: str, action: str) -> "CalibrationFailure":
        if code not in CALIBRATION_FAILURE_CODES:
            raise CardSceneContractError("calibration failure code is unsupported")
        return cls(
            code=code,
            message=_text(message, "failure.message"),
            action=_text(action, "failure.action"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "schema_version": CALIBRATION_FAILURE_SCHEMA_VERSION,
            "code": self.code,
            "message": self.message,
            "action": self.action,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str = "failure") -> "CalibrationFailure":
        data = _mapping(raw, context)
        _strict(data, {"schema_version", "code", "message", "action"}, context)
        if data["schema_version"] != CALIBRATION_FAILURE_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        return cls.create(code=data["code"], message=data["message"], action=data["action"])


@dataclass(frozen=True, slots=True)
class CalibrationGate:
    gate_id: str
    passed: bool
    observed: int | float
    threshold: int | float
    message: str

    @classmethod
    def create(
        cls,
        *,
        gate_id: str,
        passed: bool,
        observed: int | float,
        threshold: int | float,
        message: str,
    ) -> "CalibrationGate":
        if not isinstance(passed, bool):
            raise CardSceneContractError("calibration gate passed must be a boolean")
        return cls(
            gate_id=_identifier(gate_id, "gate_id"),
            passed=passed,
            observed=_finite(observed, "gate.observed"),
            threshold=_finite(threshold, "gate.threshold"),
            message=_text(message, "gate.message"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "observed": self.observed,
            "threshold": self.threshold,
            "message": self.message,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], context: str) -> "CalibrationGate":
        data = _mapping(raw, context)
        _strict(data, {"gate_id", "passed", "observed", "threshold", "message"}, context)
        return cls.create(
            gate_id=data["gate_id"],
            passed=data["passed"],
            observed=data["observed"],
            threshold=data["threshold"],
            message=data["message"],
        )


@dataclass(frozen=True, slots=True)
class CalibrationPreview:
    preview_id: str
    draft_id: str
    base_calibration_revision_id: str
    base_calibration_digest: str
    candidate_calibration: dict[str, Any] | None
    candidate_calibration_digest: str | None
    gates: tuple[CalibrationGate, ...]
    status: str
    failure: CalibrationFailure | None
    fit_residual: float
    accepted_anchor_count: int
    rejected_candidate_count: int
    held_out_alignment_change_px: float
    changed_frame_ids: tuple[str, ...]
    changed_card_ids: tuple[str, ...]
    max_source_pixel_displacement: float
    most_affected_frame_ids: tuple[str, ...]
    preview_digest: str

    @classmethod
    def create(
        cls,
        *,
        preview_id: str,
        draft_id: str,
        base_calibration_revision_id: str,
        base_calibration_digest: str,
        candidate_calibration: Mapping[str, Any] | None,
        gates: Sequence[CalibrationGate],
        status: str,
        failure: CalibrationFailure | None,
        fit_residual: float,
        accepted_anchor_count: int,
        rejected_candidate_count: int,
        held_out_alignment_change_px: float,
        changed_frame_ids: Sequence[str],
        changed_card_ids: Sequence[str],
        max_source_pixel_displacement: float,
        most_affected_frame_ids: Sequence[str],
    ) -> "CalibrationPreview":
        if status not in CALIBRATION_PREVIEW_STATES:
            raise CardSceneContractError("calibration preview status is unsupported")
        normalized_gates = tuple(gates)
        if len({gate.gate_id for gate in normalized_gates}) != len(normalized_gates):
            raise CardSceneContractError("calibration gates must have unique IDs")
        if status == "pass" and (
            candidate_calibration is None
            or failure is not None
            or not all(gate.passed for gate in normalized_gates)
        ):
            raise CardSceneContractError("passing preview needs a candidate and passing gates")
        if status == "blocked" and failure is None:
            raise CardSceneContractError("blocked preview needs a failure")
        candidate = (
            None
            if candidate_calibration is None
            else _json_object(candidate_calibration, "candidate_calibration")
        )
        changed_frames = tuple(_identifier(item, "changed_frame_ids") for item in changed_frame_ids)
        changed_cards = tuple(_identifier(item, "changed_card_ids") for item in changed_card_ids)
        most_affected = tuple(
            _identifier(item, "most_affected_frame_ids") for item in most_affected_frame_ids
        )
        if len(set(changed_frames)) != len(changed_frames) or len(set(changed_cards)) != len(
            changed_cards
        ):
            raise CardSceneContractError("preview changed IDs must be unique")
        if any(item not in changed_frames for item in most_affected):
            raise CardSceneContractError("most affected frames must be changed frames")
        core = {
            "schema_version": CALIBRATION_PREVIEW_SCHEMA_VERSION,
            "preview_id": _identifier(preview_id, "preview_id"),
            "draft_id": _identifier(draft_id, "draft_id"),
            "base_calibration_revision_id": _identifier(
                base_calibration_revision_id, "base_calibration_revision_id"
            ),
            "base_calibration_digest": _digest_value(
                base_calibration_digest, "base_calibration_digest"
            ),
            "candidate_calibration": candidate,
            "candidate_calibration_digest": None if candidate is None else _digest(candidate),
            "gates": [gate.to_mapping() for gate in normalized_gates],
            "status": status,
            "failure": None if failure is None else failure.to_mapping(),
            "fit_residual": _non_negative(fit_residual, "fit_residual"),
            "accepted_anchor_count": _non_negative_int(
                accepted_anchor_count, "accepted_anchor_count"
            ),
            "rejected_candidate_count": _non_negative_int(
                rejected_candidate_count, "rejected_candidate_count"
            ),
            "held_out_alignment_change_px": _finite(
                held_out_alignment_change_px, "held_out_alignment_change_px"
            ),
            "changed_frame_ids": list(changed_frames),
            "changed_card_ids": list(changed_cards),
            "max_source_pixel_displacement": _non_negative(
                max_source_pixel_displacement, "max_source_pixel_displacement"
            ),
            "most_affected_frame_ids": list(most_affected),
        }
        return cls(
            preview_id=core["preview_id"],
            draft_id=core["draft_id"],
            base_calibration_revision_id=core["base_calibration_revision_id"],
            base_calibration_digest=core["base_calibration_digest"],
            candidate_calibration=candidate,
            candidate_calibration_digest=core["candidate_calibration_digest"],
            gates=normalized_gates,
            status=status,
            failure=failure,
            fit_residual=core["fit_residual"],
            accepted_anchor_count=core["accepted_anchor_count"],
            rejected_candidate_count=core["rejected_candidate_count"],
            held_out_alignment_change_px=core["held_out_alignment_change_px"],
            changed_frame_ids=changed_frames,
            changed_card_ids=changed_cards,
            max_source_pixel_displacement=core["max_source_pixel_displacement"],
            most_affected_frame_ids=most_affected,
            preview_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": CALIBRATION_PREVIEW_SCHEMA_VERSION,
            "preview_id": self.preview_id,
            "draft_id": self.draft_id,
            "base_calibration_revision_id": self.base_calibration_revision_id,
            "base_calibration_digest": self.base_calibration_digest,
            "candidate_calibration": self.candidate_calibration,
            "candidate_calibration_digest": self.candidate_calibration_digest,
            "gates": [gate.to_mapping() for gate in self.gates],
            "status": self.status,
            "failure": None if self.failure is None else self.failure.to_mapping(),
            "fit_residual": _round(self.fit_residual),
            "accepted_anchor_count": self.accepted_anchor_count,
            "rejected_candidate_count": self.rejected_candidate_count,
            "held_out_alignment_change_px": _round(self.held_out_alignment_change_px),
            "changed_frame_ids": list(self.changed_frame_ids),
            "changed_card_ids": list(self.changed_card_ids),
            "max_source_pixel_displacement": _round(self.max_source_pixel_displacement),
            "most_affected_frame_ids": list(self.most_affected_frame_ids),
        }
        return {**core, "preview_digest": _digest(core)}

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "calibration_preview"
    ) -> "CalibrationPreview":
        data = _mapping(raw, context)
        expected = {
            "schema_version",
            "preview_id",
            "draft_id",
            "base_calibration_revision_id",
            "base_calibration_digest",
            "candidate_calibration",
            "candidate_calibration_digest",
            "gates",
            "status",
            "failure",
            "fit_residual",
            "accepted_anchor_count",
            "rejected_candidate_count",
            "held_out_alignment_change_px",
            "changed_frame_ids",
            "changed_card_ids",
            "max_source_pixel_displacement",
            "most_affected_frame_ids",
            "preview_digest",
        }
        _strict(data, expected, context)
        if data["schema_version"] != CALIBRATION_PREVIEW_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        raw_gates = data["gates"]
        if not isinstance(raw_gates, list):
            raise CardSceneContractError(f"{context}.gates must be a list")
        preview = cls.create(
            preview_id=data["preview_id"],
            draft_id=data["draft_id"],
            base_calibration_revision_id=data["base_calibration_revision_id"],
            base_calibration_digest=data["base_calibration_digest"],
            candidate_calibration=data["candidate_calibration"],
            gates=tuple(
                CalibrationGate.from_mapping(item, f"{context}.gates[{index}]")
                for index, item in enumerate(raw_gates)
            ),
            status=data["status"],
            failure=(
                None
                if data["failure"] is None
                else CalibrationFailure.from_mapping(
                    _mapping(data["failure"], f"{context}.failure"), f"{context}.failure"
                )
            ),
            fit_residual=data["fit_residual"],
            accepted_anchor_count=data["accepted_anchor_count"],
            rejected_candidate_count=data["rejected_candidate_count"],
            held_out_alignment_change_px=data["held_out_alignment_change_px"],
            changed_frame_ids=data["changed_frame_ids"],
            changed_card_ids=data["changed_card_ids"],
            max_source_pixel_displacement=data["max_source_pixel_displacement"],
            most_affected_frame_ids=data["most_affected_frame_ids"],
        )
        if data["candidate_calibration_digest"] != preview.candidate_calibration_digest:
            raise CardSceneContractError(f"{context}.candidate_calibration_digest is stale")
        if data["preview_digest"] != preview.preview_digest:
            raise CardSceneContractError(f"{context}.preview_digest is stale")
        return preview


@dataclass(frozen=True, slots=True)
class CalibrationReflowReceipt:
    """Atomic apply receipt describing every draft item affected by a new calibration."""

    receipt_id: str
    draft_id: str
    preview_digest: str
    source_calibration_revision_id: str
    source_calibration_digest: str
    target_calibration_revision_id: str
    target_calibration_digest: str
    proposal_revision_id: str
    anchor_command_digests: tuple[str, ...]
    reinitialized_card_ids: tuple[str, ...]
    rebased_card_ids: tuple[str, ...]
    affected_frame_ids: tuple[str, ...]
    affected_card_ids: tuple[str, ...]
    preserved_anchor_ids: tuple[str, ...]
    receipt_digest: str

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        draft_id: str,
        preview_digest: str,
        source_calibration_revision_id: str,
        source_calibration_digest: str,
        target_calibration_revision_id: str,
        target_calibration_digest: str,
        proposal_revision_id: str,
        anchor_command_digests: Sequence[str],
        reinitialized_card_ids: Sequence[str],
        rebased_card_ids: Sequence[str],
        affected_frame_ids: Sequence[str],
        affected_card_ids: Sequence[str],
        preserved_anchor_ids: Sequence[str],
    ) -> "CalibrationReflowReceipt":
        reinitialized = tuple(
            _identifier(item, "reinitialized_card_ids") for item in reinitialized_card_ids
        )
        rebased = tuple(_identifier(item, "rebased_card_ids") for item in rebased_card_ids)
        affected_frames = tuple(
            _identifier(item, "affected_frame_ids") for item in affected_frame_ids
        )
        affected_cards = tuple(_identifier(item, "affected_card_ids") for item in affected_card_ids)
        preserved = tuple(
            _identifier(item, "preserved_anchor_ids") for item in preserved_anchor_ids
        )
        if set(reinitialized) & set(rebased):
            raise CardSceneContractError("reinitialized and rebased cards must be disjoint")
        if len(set(affected_frames)) != len(affected_frames) or len(set(affected_cards)) != len(
            affected_cards
        ):
            raise CardSceneContractError("reflow affected IDs must be unique")
        commands = tuple(
            _digest_value(item, "anchor_command_digest") for item in anchor_command_digests
        )
        core = {
            "schema_version": CALIBRATION_REFLOW_RECEIPT_SCHEMA_VERSION,
            "receipt_id": _identifier(receipt_id, "receipt_id"),
            "draft_id": _identifier(draft_id, "draft_id"),
            "preview_digest": _digest_value(preview_digest, "preview_digest"),
            "source_calibration_revision_id": _identifier(
                source_calibration_revision_id, "source_calibration_revision_id"
            ),
            "source_calibration_digest": _digest_value(
                source_calibration_digest, "source_calibration_digest"
            ),
            "target_calibration_revision_id": _identifier(
                target_calibration_revision_id, "target_calibration_revision_id"
            ),
            "target_calibration_digest": _digest_value(
                target_calibration_digest, "target_calibration_digest"
            ),
            "proposal_revision_id": _identifier(proposal_revision_id, "proposal_revision_id"),
            "anchor_command_digests": list(commands),
            "reinitialized_card_ids": list(reinitialized),
            "rebased_card_ids": list(rebased),
            "affected_frame_ids": list(affected_frames),
            "affected_card_ids": list(affected_cards),
            "preserved_anchor_ids": list(preserved),
        }
        return cls(
            receipt_id=core["receipt_id"],
            draft_id=core["draft_id"],
            preview_digest=core["preview_digest"],
            source_calibration_revision_id=core["source_calibration_revision_id"],
            source_calibration_digest=core["source_calibration_digest"],
            target_calibration_revision_id=core["target_calibration_revision_id"],
            target_calibration_digest=core["target_calibration_digest"],
            proposal_revision_id=core["proposal_revision_id"],
            anchor_command_digests=commands,
            reinitialized_card_ids=reinitialized,
            rebased_card_ids=rebased,
            affected_frame_ids=affected_frames,
            affected_card_ids=affected_cards,
            preserved_anchor_ids=preserved,
            receipt_digest=_digest(core),
        )

    def to_mapping(self) -> dict[str, Any]:
        core = {
            "schema_version": CALIBRATION_REFLOW_RECEIPT_SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "draft_id": self.draft_id,
            "preview_digest": self.preview_digest,
            "source_calibration_revision_id": self.source_calibration_revision_id,
            "source_calibration_digest": self.source_calibration_digest,
            "target_calibration_revision_id": self.target_calibration_revision_id,
            "target_calibration_digest": self.target_calibration_digest,
            "proposal_revision_id": self.proposal_revision_id,
            "anchor_command_digests": list(self.anchor_command_digests),
            "reinitialized_card_ids": list(self.reinitialized_card_ids),
            "rebased_card_ids": list(self.rebased_card_ids),
            "affected_frame_ids": list(self.affected_frame_ids),
            "affected_card_ids": list(self.affected_card_ids),
            "preserved_anchor_ids": list(self.preserved_anchor_ids),
        }
        return {**core, "receipt_digest": _digest(core)}

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], context: str = "reflow_receipt"
    ) -> "CalibrationReflowReceipt":
        data = _mapping(raw, context)
        expected = {
            "schema_version",
            "receipt_id",
            "draft_id",
            "preview_digest",
            "source_calibration_revision_id",
            "source_calibration_digest",
            "target_calibration_revision_id",
            "target_calibration_digest",
            "proposal_revision_id",
            "anchor_command_digests",
            "reinitialized_card_ids",
            "rebased_card_ids",
            "affected_frame_ids",
            "affected_card_ids",
            "preserved_anchor_ids",
            "receipt_digest",
        }
        _strict(data, expected, context)
        if data["schema_version"] != CALIBRATION_REFLOW_RECEIPT_SCHEMA_VERSION:
            raise CardSceneContractError(f"{context}.schema_version is unsupported")
        receipt = cls.create(
            receipt_id=data["receipt_id"],
            draft_id=data["draft_id"],
            preview_digest=data["preview_digest"],
            source_calibration_revision_id=data["source_calibration_revision_id"],
            source_calibration_digest=data["source_calibration_digest"],
            target_calibration_revision_id=data["target_calibration_revision_id"],
            target_calibration_digest=data["target_calibration_digest"],
            proposal_revision_id=data["proposal_revision_id"],
            anchor_command_digests=data["anchor_command_digests"],
            reinitialized_card_ids=data["reinitialized_card_ids"],
            rebased_card_ids=data["rebased_card_ids"],
            affected_frame_ids=data["affected_frame_ids"],
            affected_card_ids=data["affected_card_ids"],
            preserved_anchor_ids=data["preserved_anchor_ids"],
        )
        if data["receipt_digest"] != receipt.receipt_digest:
            raise CardSceneContractError(f"{context}.receipt_digest is stale")
        return receipt


def calibration_refinement_contract_manifest() -> dict[str, Any]:
    """Return the complete frozen M0 policy and schema boundary."""

    return {
        "schema_versions": {
            "proposal": PROPOSED_CARD_SCENE_SCHEMA_VERSION,
            "reviewed_scene_record": REVIEWED_CARD_SCENE_RECORD_SCHEMA_VERSION,
            "card_scene_draft": CARD_SCENE_DRAFT_SCHEMA_VERSION,
            "calibration_draft": CALIBRATION_DRAFT_SCHEMA_VERSION,
            "anchor_observation": ANCHOR_OBSERVATION_SCHEMA_VERSION,
            "anchor_command": ANCHOR_COMMAND_SCHEMA_VERSION,
            "calibration_preview": CALIBRATION_PREVIEW_SCHEMA_VERSION,
            "reflow_receipt": CALIBRATION_REFLOW_RECEIPT_SCHEMA_VERSION,
        },
        "card_review_states": list(CARD_REVIEW_STATES),
        "anchor_states": list(ANCHOR_STATES),
        "anchor_base_weights": dict(ANCHOR_BASE_WEIGHTS),
        "anchor_frame_weight_cap": ANCHOR_FRAME_WEIGHT_CAP,
        "anchor_table_region_weight_cap": ANCHOR_TABLE_REGION_WEIGHT_CAP,
        "anchor_pin_conflict_tolerance_px": ANCHOR_PIN_CONFLICT_TOLERANCE_PX,
        "anchor_min_side_length_table_units": ANCHOR_MIN_SIDE_LENGTH_TABLE_UNITS,
        "anchor_snap_tolerance_table_units": ANCHOR_SNAP_TOLERANCE_TABLE_UNITS,
        "temporal_deduplication_bin_us": TEMPORAL_DEDUPLICATION_BIN_US,
        "table_region_deduplication_bin_units": TABLE_REGION_DEDUPLICATION_BIN_UNITS,
        "minimum_eligible_anchors": MIN_ELIGIBLE_ANCHORS,
        "max_fit_residual_table_units": MAX_FIT_RESIDUAL_TABLE_UNITS,
        "max_held_out_alignment_change_px": MAX_HELD_OUT_ALIGNMENT_CHANGE_PX,
        "max_reviewed_source_displacement_px": MAX_REVIEWED_SOURCE_DISPLACEMENT_PX,
        "max_proposed_source_displacement_px": MAX_PROPOSED_SOURCE_DISPLACEMENT_PX,
        "card_aspect_ratio": CARD_ASPECT_RATIO,
        "corner_order": CORNER_ORDER_VERSION,
        "handle_modifier_policy": dict(HANDLE_MODIFIER_POLICY),
        "handle_keyboard_policy": dict(HANDLE_KEYBOARD_POLICY),
        "revision_invalidation_rules": dict(REVISION_INVALIDATION_RULES),
    }


__all__ = [
    "ANCHOR_BASE_WEIGHTS",
    "ANCHOR_COMMAND_SCHEMA_VERSION",
    "ANCHOR_FRAME_WEIGHT_CAP",
    "ANCHOR_MIN_SIDE_LENGTH_TABLE_UNITS",
    "ANCHOR_OBSERVATION_SCHEMA_VERSION",
    "ANCHOR_PIN_CONFLICT_TOLERANCE_PX",
    "ANCHOR_SNAP_TOLERANCE_TABLE_UNITS",
    "ANCHOR_STATES",
    "ANCHOR_TABLE_REGION_WEIGHT_CAP",
    "ANCHOR_WEIGHT_CLASSES",
    "CARD_ASPECT_RATIO",
    "CARD_REVIEW_STATES",
    "CALIBRATION_DRAFT_SCHEMA_VERSION",
    "CALIBRATION_DRAFT_STATES",
    "CALIBRATION_FAILURE_CODES",
    "CALIBRATION_FAILURE_SCHEMA_VERSION",
    "CALIBRATION_PREVIEW_SCHEMA_VERSION",
    "CALIBRATION_PREVIEW_STATES",
    "CALIBRATION_REFLOW_RECEIPT_SCHEMA_VERSION",
    "CARD_SCENE_DRAFT_SCHEMA_VERSION",
    "CORNER_ORDER_VERSION",
    "CardReviewState",
    "CardSceneContractError",
    "CardSceneDraft",
    "CalibrationDraft",
    "CalibrationFailure",
    "CalibrationGate",
    "CalibrationPreview",
    "CalibrationReflowReceipt",
    "FrameReviewCompletion",
    "HANDLE_CONSTRAINTS",
    "HANDLE_KEYBOARD_POLICY",
    "HANDLE_MODIFIER_POLICY",
    "MIN_ELIGIBLE_ANCHORS",
    "MAX_FIT_RESIDUAL_TABLE_UNITS",
    "MAX_HELD_OUT_ALIGNMENT_CHANGE_PX",
    "MAX_PROPOSED_SOURCE_DISPLACEMENT_PX",
    "MAX_REVIEWED_SOURCE_DISPLACEMENT_PX",
    "ProposedCardScene",
    "REVISION_INVALIDATION_RULES",
    "ReviewedCardSceneRecord",
    "StaleCalibrationEvidenceError",
    "AnchorCommand",
    "AnchorContribution",
    "AnchorObservation",
    "anchor_fit_contributions",
    "calibration_refinement_contract_manifest",
    "canonical_card_scene_bytes",
    "constrain_anchor_quad",
    "deduplicate_anchor_observations",
    "validate_calibration_draft_lineage",
    "validate_pinned_anchor_conflicts",
]
