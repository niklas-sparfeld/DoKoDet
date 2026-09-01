"""Conflict-safe CardEvent review drafts and immutable reviewed versions.

The web application supplies the immutable source and proposal projection. This module owns the
review state transitions and the files below the configured operations workspace. It deliberately
does not write to a repository-intake bundle.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported local runtime is macOS/Linux.
    fcntl = None  # type: ignore[assignment]

CARD_EVENT_REVIEW_SCHEMA_VERSION = "cardevent-review/v1"
CARD_EVENT_ANNOTATION_SCHEMA_VERSION = "cardevent-annotation/v2"
CARD_EVENT_REVIEWED_VERSION_SCHEMA_VERSION = "cardevent-reviewed-annotation/v1"
CARD_EVENT_REVIEW_RECEIPT_SCHEMA_VERSION = "lifecycle-receipt/v1"
CARD_EVENT_REVIEW_STATES = frozenset({"not_started", "draft", "completed"})
CARD_EVENT_PROPOSAL_DECISIONS = frozenset({"undecided", "accepted", "dismissed"})
CARD_EVENT_TYPES = frozenset(
    {
        "card_played",
        "trick_cleared",
        "card_moved",
        "card_removed",
        "card_returned",
        "multiple_cards_dropped",
        "anomalous_state_change",
    }
)
CARD_EVENT_CONFIDENCES = frozenset({"confirmed", "uncertain", "ignore", "proposed"})
DUPLICATE_EVENT_TOLERANCE_S = 0.01


class CardEventReviewError(ValueError):
    """Base class for invalid CardEvent review state or input."""


class CardEventReviewConflict(CardEventReviewError):
    """A review update was based on a stale draft or source."""


class CardEventReviewNotFound(CardEventReviewError):
    """The requested completed review version does not exist."""


class CardEventReviewWriteError(RuntimeError):
    """The review workspace could not be written."""


@dataclass(frozen=True, slots=True)
class CardEventProposal:
    """One immutable proposal shown beside human annotation events."""

    proposal_id: str
    proposal_generator_run_id: str
    time_s: float
    probability: float
    model_bundle_id: str
    execution_platform: str

    def to_mapping(self, decision: str) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_generator_run_id": self.proposal_generator_run_id,
            "time_s": self.time_s,
            "probability": self.probability,
            "model_bundle_id": self.model_bundle_id,
            "execution_platform": self.execution_platform,
            "decision": decision,
        }


@dataclass(frozen=True, slots=True)
class CardEventReviewSource:
    """The immutable source identity needed to validate one review workspace."""

    recording_id: str
    source_asset_id: str
    source_sha256: str
    video: str
    proposals: tuple[CardEventProposal, ...] = ()
    duration_s: float | None = None


class CardEventReviewStore:
    """Persist one source-linked CardEvent review with optimistic concurrency."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()

    def read(self, source: CardEventReviewSource) -> dict[str, Any]:
        """Read the current draft, or create its in-memory empty initial state."""

        path = self._draft_path(source.recording_id)
        if not path.is_file():
            return _project_state(_initial_state(source), source)
        with _review_lock(self._review_root(source.recording_id), exclusive=False):
            try:
                state = _read_json(path)
            except OSError as error:
                raise CardEventReviewWriteError(
                    "The CardEvent review draft could not be read."
                ) from error
        _validate_state_source(state, source)
        return _project_state(state, source)

    def update_draft(
        self,
        source: CardEventReviewSource,
        *,
        annotation: Mapping[str, Any],
        proposals: Sequence[Mapping[str, Any]],
        expected_revision: int,
        full_video_acknowledged: bool = False,
    ) -> dict[str, Any]:
        """Validate and atomically save a complete next draft."""

        _validate_expected_revision(expected_revision)
        with _review_lock(self._review_root(source.recording_id), exclusive=True):
            current = self._read_locked(source)
            _assert_revision(current, expected_revision)
            if current["review_state"] == "completed":
                raise CardEventReviewConflict(
                    "The review is complete. Start a new revision before editing it."
                )
            decisions = _validate_proposal_decisions(proposals, source.proposals)
            normalized_annotation = _validate_annotation(annotation, source)
            normalized_annotation = _apply_accepted_proposals(
                normalized_annotation, decisions, source.proposals
            )
            updated = _draft_state(
                source,
                annotation=normalized_annotation,
                decisions=decisions,
                draft_revision=current["draft_revision"] + 1,
                full_video_acknowledged=full_video_acknowledged,
                review_state="draft",
                parent_version_id=current.get("parent_version_id"),
                parent_digest=current.get("parent_digest"),
            )
            self._write_draft_locked(source.recording_id, updated)
        return _project_state(updated, source)

    def complete(
        self,
        source: CardEventReviewSource,
        *,
        reviewer: str,
        expected_revision: int,
        full_video_acknowledged: bool,
    ) -> dict[str, Any]:
        """Publish one immutable reviewed version and lifecycle receipt."""

        _validate_expected_revision(expected_revision)
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise CardEventReviewError("reviewer must be a non-empty string.")
        if not full_video_acknowledged:
            raise CardEventReviewError(
                "A full-video acknowledgement is required to complete review."
            )

        with _review_lock(self._review_root(source.recording_id), exclusive=True):
            current = self._read_locked(source)
            _assert_revision(current, expected_revision)
            if current["review_state"] == "completed":
                raise CardEventReviewConflict(
                    "The review is already complete. Start a new revision before completing it "
                    "again."
                )
            decisions = _proposal_decisions_from_state(current)
            if any(value == "undecided" for value in decisions.values()):
                raise CardEventReviewError(
                    "Every CardEvent proposal needs an accepted or dismissed decision."
                )
            annotation = _validate_annotation(current["annotation"], source)
            input_digest = _draft_digest(current)
            annotation_digest = _digest(annotation)
            proposal_decision_digest = _digest(_decision_mapping(decisions))
            completed_at = _now()
            version_core = {
                "schema_version": CARD_EVENT_REVIEWED_VERSION_SCHEMA_VERSION,
                "recording_id": source.recording_id,
                "source_asset_id": source.source_asset_id,
                "source_sha256": source.source_sha256,
                "annotation": annotation,
                "proposal_decisions": _decision_mapping(decisions),
                "input_draft_revision": current["draft_revision"],
                "input_draft_digest": input_digest,
                "source_digest": source.source_sha256,
                "reviewed_annotation_digest": annotation_digest,
                "proposal_decision_digest": proposal_decision_digest,
                "reviewer": reviewer.strip(),
                "completed_at": completed_at,
                "parent_version_id": current.get("parent_version_id"),
                "parent_digest": current.get("parent_digest"),
            }
            version_id = "cardevent-reviewed-" + _digest(version_core)[:20]
            version = {**version_core, "version_id": version_id}
            version_digest = _digest(version)
            version["version_digest"] = version_digest
            receipt = _completion_receipt(
                source,
                version_id=version_id,
                version_digest=version_digest,
                input_draft_digest=input_digest,
                annotation_digest=annotation_digest,
                proposal_decision_digest=proposal_decision_digest,
                reviewer=reviewer.strip(),
                occurred_at=completed_at,
            )
            _write_immutable_json(self._version_path(source.recording_id, version_id), version)
            _write_immutable_json(
                self._receipt_path(source.recording_id, receipt["receipt_id"]), receipt
            )
            completed = _draft_state(
                source,
                annotation=annotation,
                decisions=decisions,
                draft_revision=current["draft_revision"],
                full_video_acknowledged=True,
                review_state="completed",
                reviewer=reviewer.strip(),
                completed_at=completed_at,
                completed_version_id=version_id,
                completed_version_digest=version_digest,
                parent_version_id=current.get("parent_version_id"),
                parent_digest=current.get("parent_digest"),
                reviewed_annotation_digest=annotation_digest,
                proposal_decision_digest=proposal_decision_digest,
                completion_receipt_id=receipt["receipt_id"],
            )
            self._write_draft_locked(source.recording_id, completed)
        return _project_state(completed, source)

    def start_revision(
        self,
        source: CardEventReviewSource,
        *,
        parent_version_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Copy a named immutable reviewed version into the current draft."""

        _validate_expected_revision(expected_revision)
        if not isinstance(parent_version_id, str) or not parent_version_id.strip():
            raise CardEventReviewError("parent_version_id must be a non-empty string.")
        with _review_lock(self._review_root(source.recording_id), exclusive=True):
            current = self._read_locked(source)
            _assert_revision(current, expected_revision)
            version_path = self._version_path(source.recording_id, parent_version_id)
            if not version_path.is_file():
                raise CardEventReviewNotFound(
                    "The completed CardEvent review version was not found."
                )
            try:
                version = _read_json(version_path)
            except OSError as error:
                raise CardEventReviewWriteError(
                    "The completed CardEvent review version could not be read."
                ) from error
            _validate_version(version, source, parent_version_id)
            decisions = _validate_proposal_decisions(
                [
                    {"proposal_id": proposal_id, "decision": decision}
                    for proposal_id, decision in version["proposal_decisions"].items()
                ],
                source.proposals,
            )
            annotation = _validate_annotation(version["annotation"], source)
            revision = _draft_state(
                source,
                annotation=annotation,
                decisions=decisions,
                draft_revision=current["draft_revision"] + 1,
                full_video_acknowledged=False,
                review_state="draft",
                parent_version_id=parent_version_id,
                parent_digest=version["version_digest"],
            )
            self._write_draft_locked(source.recording_id, revision)
        return _project_state(revision, source)

    def _review_root(self, recording_id: str) -> Path:
        return self.workspace_root / "cardevent-reviews" / recording_id

    def _draft_path(self, recording_id: str) -> Path:
        return self._review_root(recording_id) / "draft.json"

    def _version_path(self, recording_id: str, version_id: str) -> Path:
        return self._review_root(recording_id) / "versions" / f"{version_id}.json"

    def _receipt_path(self, recording_id: str, receipt_id: str) -> Path:
        return self._review_root(recording_id) / "receipts" / f"{receipt_id}.json"

    def _read_locked(self, source: CardEventReviewSource) -> dict[str, Any]:
        path = self._draft_path(source.recording_id)
        if not path.is_file():
            return _initial_state(source)
        try:
            state = _read_json(path)
        except OSError as error:
            raise CardEventReviewWriteError(
                "The CardEvent review draft could not be read."
            ) from error
        _validate_state_source(state, source)
        return state

    def _write_draft_locked(self, recording_id: str, state: Mapping[str, Any]) -> None:
        try:
            _atomic_write_json(self._draft_path(recording_id), state)
        except OSError as error:
            raise CardEventReviewWriteError(
                "The CardEvent review draft could not be saved."
            ) from error


def proposal_id(source_asset_id: str, run_id: str, index: int, time_s: float) -> str:
    """Return the stable identifier for one source-linked proposal."""

    return "cardevent-proposal-" + _digest(
        {
            "source_asset_id": source_asset_id,
            "run_id": run_id,
            "index": index,
            "time_s": time_s,
        }
    )[:20]


def _initial_state(source: CardEventReviewSource) -> dict[str, Any]:
    return _draft_state(
        source,
        annotation={
            "schema_version": CARD_EVENT_ANNOTATION_SCHEMA_VERSION,
            "video": Path(source.video).name,
            "events": [],
        },
        decisions={proposal.proposal_id: "undecided" for proposal in source.proposals},
        draft_revision=0,
        full_video_acknowledged=False,
        review_state="not_started",
    )


def _draft_state(
    source: CardEventReviewSource,
    *,
    annotation: Mapping[str, Any],
    decisions: Mapping[str, str],
    draft_revision: int,
    full_video_acknowledged: bool,
    review_state: str,
    reviewer: str | None = None,
    completed_at: str | None = None,
    completed_version_id: str | None = None,
    completed_version_digest: str | None = None,
    parent_version_id: str | None = None,
    parent_digest: str | None = None,
    reviewed_annotation_digest: str | None = None,
    proposal_decision_digest: str | None = None,
    completion_receipt_id: str | None = None,
) -> dict[str, Any]:
    if review_state not in CARD_EVENT_REVIEW_STATES:
        raise CardEventReviewError("Unknown CardEvent review state.")
    state: dict[str, Any] = {
        "schema_version": CARD_EVENT_REVIEW_SCHEMA_VERSION,
        "recording_id": source.recording_id,
        "source_asset_id": source.source_asset_id,
        "source_sha256": source.source_sha256,
        "video": Path(source.video).name,
        "draft_revision": draft_revision,
        "annotation": dict(annotation),
        "proposal_decisions": _decision_mapping(decisions),
        "full_video_acknowledged": full_video_acknowledged,
        "review_state": review_state,
        "reviewer": reviewer,
        "completed_at": completed_at,
        "completed_version_id": completed_version_id,
        "completed_version_digest": completed_version_digest,
        "parent_version_id": parent_version_id,
        "parent_digest": parent_digest,
        "reviewed_annotation_digest": reviewed_annotation_digest,
        "proposal_decision_digest": proposal_decision_digest,
        "completion_receipt_id": completion_receipt_id,
    }
    state["draft_digest"] = _draft_digest(state)
    return state


def _project_state(state: Mapping[str, Any], source: CardEventReviewSource) -> dict[str, Any]:
    decisions = _proposal_decisions_from_state(state)
    proposals = [
        proposal.to_mapping(decisions[proposal.proposal_id]) for proposal in source.proposals
    ]
    return {
        "schema_version": CARD_EVENT_REVIEW_SCHEMA_VERSION,
        "recording_id": source.recording_id,
        "source_asset_id": source.source_asset_id,
        "source_sha256": source.source_sha256,
        "video": Path(source.video).name,
        "annotation": dict(state["annotation"]),
        "draft_revision": state["draft_revision"],
        "draft_digest": state["draft_digest"],
        "review_state": state["review_state"],
        "full_video_acknowledged": state["full_video_acknowledged"],
        "reviewer": state.get("reviewer"),
        "completed_at": state.get("completed_at"),
        "completed_version_id": state.get("completed_version_id"),
        "completed_version_digest": state.get("completed_version_digest"),
        "parent_version_id": state.get("parent_version_id"),
        "parent_digest": state.get("parent_digest"),
        "reviewed_annotation_digest": state.get("reviewed_annotation_digest"),
        "proposal_decision_digest": state.get("proposal_decision_digest"),
        "completion_receipt_id": state.get("completion_receipt_id"),
        "proposals": proposals,
    }


def _validate_state_source(state: Mapping[str, Any], source: CardEventReviewSource) -> None:
    if state.get("schema_version") != CARD_EVENT_REVIEW_SCHEMA_VERSION:
        raise CardEventReviewError("The stored CardEvent review has an unsupported schema.")
    if (
        state.get("recording_id") != source.recording_id
        or state.get("source_asset_id") != source.source_asset_id
        or state.get("source_sha256") != source.source_sha256
        or state.get("video") != Path(source.video).name
    ):
        raise CardEventReviewConflict(
            "The accepted recording source changed. The existing review draft was not modified."
        )
    if not isinstance(state.get("draft_revision"), int) or state["draft_revision"] < 0:
        raise CardEventReviewError("The stored CardEvent review has an invalid draft revision.")
    if _draft_digest(state) != state.get("draft_digest"):
        raise CardEventReviewError("The stored CardEvent review draft digest is invalid.")
    _validate_annotation(state.get("annotation"), source)
    _validate_proposal_decisions(
        [
            {"proposal_id": proposal_id_value, "decision": decision}
            for proposal_id_value, decision in state.get("proposal_decisions", {}).items()
        ],
        source.proposals,
    )


def _validate_annotation(
    annotation: Mapping[str, Any], source: CardEventReviewSource
) -> dict[str, Any]:
    if not isinstance(annotation, Mapping):
        raise CardEventReviewError("annotation must be an object.")
    if set(annotation) != {"schema_version", "video", "events"}:
        raise CardEventReviewError("annotation must use exactly schema_version, video, and events.")
    if annotation.get("schema_version") != CARD_EVENT_ANNOTATION_SCHEMA_VERSION:
        raise CardEventReviewError(
            f"annotation schema_version must be {CARD_EVENT_ANNOTATION_SCHEMA_VERSION}."
        )
    video = annotation.get("video")
    if not isinstance(video, str) or not video or Path(video).name != Path(source.video).name:
        raise CardEventReviewError("annotation.video does not match the accepted source video.")
    events = annotation.get("events")
    if not isinstance(events, list):
        raise CardEventReviewError("annotation.events must be a list.")
    normalized_events: list[dict[str, Any]] = []
    previous_time: float | None = None
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise CardEventReviewError(f"annotation.events[{index}] must be an object.")
        if not set(event) <= {"time_s", "type", "confidence", "notes"}:
            raise CardEventReviewError(f"annotation.events[{index}] has unknown fields.")
        time_s = event.get("time_s")
        if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
            raise CardEventReviewError(f"annotation.events[{index}].time_s must be a number.")
        time_s = float(time_s)
        if not math.isfinite(time_s) or time_s < 0:
            raise CardEventReviewError(
                f"annotation.events[{index}].time_s must be finite and non-negative."
            )
        if source.duration_s is not None and time_s > source.duration_s + 1e-6:
            raise CardEventReviewError("Event time exceeds the accepted source video duration.")
        if previous_time is not None and time_s < previous_time:
            raise CardEventReviewError("annotation.events must be sorted by time before saving.")
        previous_time = time_s
        event_type = event.get("type")
        if not isinstance(event_type, str) or event_type not in CARD_EVENT_TYPES:
            raise CardEventReviewError(f"Unknown CardEvent event type: {event_type}.")
        confidence = event.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, str) or confidence not in CARD_EVENT_CONFIDENCES
        ):
            raise CardEventReviewError(
                "event.confidence must be confirmed, uncertain, ignore, or proposed."
            )
        notes = event.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise CardEventReviewError("event.notes must be a string or null.")
        normalized: dict[str, Any] = {"time_s": time_s, "type": event_type}
        if "confidence" in event:
            normalized["confidence"] = confidence
        if "notes" in event:
            normalized["notes"] = notes
        normalized_events.append(normalized)
    for previous, current in zip(normalized_events, normalized_events[1:], strict=False):
        if current["time_s"] - previous["time_s"] <= DUPLICATE_EVENT_TOLERANCE_S:
            raise CardEventReviewError(
                "CardEvent events must be more than 10 ms apart before saving."
            )
    return {
        "schema_version": CARD_EVENT_ANNOTATION_SCHEMA_VERSION,
        "video": Path(video).name,
        "events": normalized_events,
    }


def _validate_proposal_decisions(
    proposals: Sequence[Mapping[str, Any]],
    source_proposals: Sequence[CardEventProposal],
) -> dict[str, str]:
    expected = {proposal.proposal_id for proposal in source_proposals}
    decisions: dict[str, str] = {}
    for item in proposals:
        if not isinstance(item, Mapping):
            raise CardEventReviewError("Each proposal decision must be an object.")
        if set(item) != {"proposal_id", "decision"}:
            raise CardEventReviewError("Proposal decisions need proposal_id and decision only.")
        proposal_id_value = item.get("proposal_id")
        decision = item.get("decision")
        if proposal_id_value not in expected:
            raise CardEventReviewError("The proposal decision references a foreign proposal ID.")
        if proposal_id_value in decisions:
            raise CardEventReviewError("Proposal decisions must not contain duplicate IDs.")
        if decision not in CARD_EVENT_PROPOSAL_DECISIONS:
            raise CardEventReviewError(
                "Proposal decision must be undecided, accepted, or dismissed."
            )
        decisions[proposal_id_value] = decision
    if set(decisions) != expected:
        raise CardEventReviewError(
            "Proposal decisions must include every current proposal exactly once."
        )
    return {key: decisions[key] for key in sorted(decisions)}


def _apply_accepted_proposals(
    annotation: Mapping[str, Any],
    decisions: Mapping[str, str],
    proposals: Sequence[CardEventProposal],
) -> dict[str, Any]:
    """Create a default human event when a proposal is accepted without one."""

    events = [dict(event) for event in annotation["events"]]
    for proposal in proposals:
        if decisions[proposal.proposal_id] != "accepted":
            continue
        if any(
            abs(float(event["time_s"]) - proposal.time_s) <= DUPLICATE_EVENT_TOLERANCE_S
            for event in events
        ):
            continue
        events.append(
            {
                "time_s": proposal.time_s,
                "type": "card_played",
                "confidence": "confirmed",
            }
        )
    events.sort(key=lambda event: event["time_s"])
    return {
        "schema_version": annotation["schema_version"],
        "video": annotation["video"],
        "events": events,
    }


def _proposal_decisions_from_state(state: Mapping[str, Any]) -> dict[str, str]:
    value = state.get("proposal_decisions")
    if not isinstance(value, Mapping):
        raise CardEventReviewError("The stored CardEvent review has invalid proposal decisions.")
    return {str(key): str(item) for key, item in value.items()}


def _decision_mapping(decisions: Mapping[str, str]) -> dict[str, str]:
    return {key: decisions[key] for key in sorted(decisions)}


def _validate_version(
    version: Mapping[str, Any], source: CardEventReviewSource, version_id: str
) -> None:
    if version.get("schema_version") != CARD_EVENT_REVIEWED_VERSION_SCHEMA_VERSION:
        raise CardEventReviewError("The completed CardEvent review version has an invalid schema.")
    if version.get("version_id") != version_id:
        raise CardEventReviewError("The completed CardEvent review version ID does not match.")
    if (
        version.get("recording_id") != source.recording_id
        or version.get("source_asset_id") != source.source_asset_id
        or version.get("source_sha256") != source.source_sha256
    ):
        raise CardEventReviewConflict("The completed review version belongs to another source.")
    _validate_annotation(version.get("annotation"), source)
    decisions = version.get("proposal_decisions")
    if not isinstance(decisions, Mapping):
        raise CardEventReviewError("The completed CardEvent review version has invalid decisions.")
    _validate_proposal_decisions(
        [{"proposal_id": key, "decision": value} for key, value in decisions.items()],
        source.proposals,
    )
    version_core = {key: value for key, value in version.items() if key != "version_digest"}
    if _digest(version_core) != version.get("version_digest"):
        raise CardEventReviewError("The completed CardEvent review version digest is invalid.")


def _completion_receipt(
    source: CardEventReviewSource,
    *,
    version_id: str,
    version_digest: str,
    input_draft_digest: str,
    annotation_digest: str,
    proposal_decision_digest: str,
    reviewer: str,
    occurred_at: str,
) -> dict[str, Any]:
    core = {
        "schema_version": CARD_EVENT_REVIEW_RECEIPT_SCHEMA_VERSION,
        "receipt_type": "annotation_application",
        "operator": reviewer,
        "occurred_at": occurred_at,
        "inputs": [
            {"kind": "source_asset", "id": source.source_asset_id, "digest": source.source_sha256},
            {"kind": "review", "id": source.recording_id, "digest": input_draft_digest},
        ],
        "outputs": [
            {"kind": "annotation_set", "id": version_id, "digest": annotation_digest},
            {"kind": "review", "id": version_id, "digest": version_digest},
        ],
        "dependencies": [
            {"kind": "source_asset", "id": source.source_asset_id, "digest": source.source_sha256}
        ],
        "metadata": {
            "recording_id": source.recording_id,
            "input_draft_digest": input_draft_digest,
            "source_digest": source.source_sha256,
            "reviewed_annotation_digest": annotation_digest,
            "proposal_decision_digest": proposal_decision_digest,
        },
    }
    receipt_digest_core = {
        key: value for key, value in core.items() if key not in {"occurred_at"}
    }
    receipt_id = "receipt-cardevent-review-" + _digest(receipt_digest_core)[:20]
    return {
        **core,
        "receipt_id": receipt_id,
        "receipt_digest": _digest(receipt_digest_core),
    }


def _assert_revision(state: Mapping[str, Any], expected_revision: int) -> None:
    if state["draft_revision"] != expected_revision:
        raise CardEventReviewConflict(
            "The CardEvent review draft changed. Reload the winning revision before saving."
        )


def _validate_expected_revision(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CardEventReviewError("expected_revision must be a non-negative integer.")


def _draft_digest(state: Mapping[str, Any]) -> str:
    return _digest({key: value for key, value in state.items() if key != "draft_digest"})


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise CardEventReviewError("CardEvent review values must be finite JSON values.") from error


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CardEventReviewError(f"Stored CardEvent review must be an object: {path}")
    return value


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
        _fsync_directory(path.parent)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_immutable_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        try:
            if _read_json(path) == dict(value):
                return
        except (OSError, json.JSONDecodeError, CardEventReviewError):
            pass
        raise CardEventReviewWriteError(f"Refusing to overwrite immutable review artifact: {path}")
    try:
        _atomic_write_json(path, value)
    except OSError as error:
        raise CardEventReviewWriteError(
            "The immutable CardEvent review artifact could not be saved."
        ) from error


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _review_lock(path: Path, *, exclusive: bool) -> Iterator[None]:
    path.mkdir(parents=True, exist_ok=True)
    lock_path = path / ".lock"
    with lock_path.open("a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "CARD_EVENT_ANNOTATION_SCHEMA_VERSION",
    "CARD_EVENT_CONFIDENCES",
    "CARD_EVENT_PROPOSAL_DECISIONS",
    "CARD_EVENT_REVIEW_SCHEMA_VERSION",
    "CARD_EVENT_REVIEW_STATES",
    "CARD_EVENT_REVIEWED_VERSION_SCHEMA_VERSION",
    "CARD_EVENT_TYPES",
    "CardEventProposal",
    "CardEventReviewConflict",
    "CardEventReviewError",
    "CardEventReviewNotFound",
    "CardEventReviewSource",
    "CardEventReviewStore",
    "CardEventReviewWriteError",
    "proposal_id",
]
