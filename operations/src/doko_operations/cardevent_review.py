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
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported local runtime is macOS/Linux.
    fcntl = None  # type: ignore[assignment]

CARD_EVENT_REVIEW_SCHEMA_VERSION = "cardevent-review/v1"
CARD_EVENT_REVIEW_RESOURCE_SCHEMA_VERSION = "cardevent-review-resource/v1"
CARD_EVENT_REVIEW_COLLECTION_SCHEMA_VERSION = "cardevent-review-collection/v1"
CARD_EVENT_REVIEW_EVENT_SCHEMA_VERSION = "cardevent-review-event/v1"
CARD_EVENT_ANNOTATION_SCHEMA_VERSION = "cardevent-annotation/v2"
CARD_EVENT_REVIEWED_VERSION_SCHEMA_VERSION = "cardevent-reviewed-annotation/v1"
CARD_EVENT_REVIEW_RECEIPT_SCHEMA_VERSION = "lifecycle-receipt/v1"
CARD_EVENT_REVIEW_STATES = frozenset({"not_started", "draft", "completed"})
CARD_EVENT_PROPOSAL_DECISIONS = frozenset({"undecided", "accepted", "dismissed"})
CARD_EVENT_EVENT_STATES = frozenset({"proposed", "reviewed", "dismissed"})
CARD_EVENT_EVENT_ORIGINS = frozenset({"manual", "model", "device"})
CARD_EVENT_COMMAND_ACTIONS = frozenset({"accept", "dismiss", "undo", "edit", "retime", "remove"})
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
REVIEW_ID_PATTERN = re.compile(r"^cardevent-review-[0-9a-f]{32}$")
EVENT_ID_PATTERN = re.compile(r"^cardevent-event-[0-9a-f]{32}$")
COMMAND_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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

        resource = self._current_resource(source)
        if resource is not None:
            return _project_state(resource, source)

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

    def list_reviews(self, source: CardEventReviewSource) -> tuple[dict[str, Any], ...]:
        """List all recording-owned review resources in display order."""

        with _review_lock(self._resource_root(), exclusive=False):
            states = self._resource_states_locked(source)
        return tuple(_project_resource_summary(state) for state in _sort_resources(states))

    def create_review(
        self,
        source: CardEventReviewSource,
        *,
        operator: str,
        parent_review_id: str | None = None,
    ) -> dict[str, Any]:
        """Create one recording-owned draft review, optionally seeded from a completion."""

        _validate_operator(operator)
        with _review_lock(self._resource_root(), exclusive=True):
            states = self._resource_states_locked(source)
            if (
                any(state["review_state"] == "draft" for state in states)
                or self._draft_path(source.recording_id).is_file()
            ):
                raise CardEventReviewConflict(
                    "A draft CardEvent review already exists for this recording."
                )

            parent = _select_parent_resource(states, parent_review_id)
            parent_version_id: str | None = None
            parent_digest: str | None = None
            if parent is None:
                events = _validate_event_collection(_initial_events(source), source)
            else:
                parent_version_id = parent.get("completed_version_id")
                if not isinstance(parent_version_id, str) or not parent_version_id:
                    raise CardEventReviewError(
                        "The parent review has no completed annotation version."
                    )
                version = self._read_resource_version_locked(parent, parent_version_id)
                _validate_version(version, source, parent_version_id)
                events = _validate_event_collection(version["events"], source)
                parent_digest = version["version_digest"]

            review_id = "cardevent-review-" + uuid4().hex
            now = _now()
            state = _resource_state(
                source,
                review_id=review_id,
                operator=operator.strip(),
                created_at=now,
                updated_at=now,
                events=events,
                parent_review_id=parent["review_id"] if parent is not None else None,
                parent_version_id=parent_version_id,
                parent_digest=parent_digest,
            )
            self._write_resource_locked(state)
        return _project_resource(state, source)

    def read_review_identity(self, review_id: str) -> dict[str, Any]:
        """Read one resource identity before loading its accepted recording source."""

        path = self._resource_path(review_id)
        with _review_lock(self._resource_root(), exclusive=False):
            try:
                return _read_json(path)
            except FileNotFoundError as error:
                raise CardEventReviewNotFound("The CardEvent review was not found.") from error
            except OSError as error:
                raise CardEventReviewWriteError(
                    "The CardEvent review could not be read."
                ) from error

    def completed_version_path(self, recording_id: str, version_id: str) -> Path:
        """Return the immutable completed version path for downstream consumers."""

        with _review_lock(self._resource_root(), exclusive=False):
            root = self._resource_root()
            if root.is_dir():
                for directory in sorted(root.iterdir(), key=lambda item: item.name):
                    path = directory / "review.json"
                    if not path.is_file():
                        continue
                    state = _read_json(path)
                    if (
                        state.get("recording_id") == recording_id
                        and state.get("completed_version_id") == version_id
                    ):
                        return self._resource_version_path(directory.name, version_id)
        return self._version_path(recording_id, version_id)

    def get_review(self, review_id: str, source: CardEventReviewSource) -> dict[str, Any]:
        """Read one recording-owned review and validate its source identity."""

        with _review_lock(self._resource_root(), exclusive=False):
            state = self._read_resource_locked(review_id)
        _validate_resource_state(state, source, review_id)
        return _project_resource(state, source)

    def add_event(
        self,
        review_id: str,
        source: CardEventReviewSource,
        *,
        client_command_id: str,
        expected_revision: int,
        effective_time_s: float,
        event_type: str,
        confidence: str | None = "confirmed",
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Add one reviewed manual event and make replay safe by command ID."""

        command = {
            "operation": "add",
            "client_command_id": client_command_id,
            "expected_revision": expected_revision,
            "effective_time_s": effective_time_s,
            "type": event_type,
            "confidence": confidence,
            "notes": notes,
        }
        _validate_command_id(client_command_id)
        _validate_expected_revision(expected_revision)
        event_fields = _validate_event_fields(
            effective_time_s=effective_time_s,
            event_type=event_type,
            confidence=confidence,
            notes=notes,
        )
        event = {
            "event_id": "cardevent-event-" + uuid4().hex,
            **event_fields,
            "state": "reviewed",
            "origin": "manual",
            "proposal": None,
        }
        return self._run_event_command(
            review_id,
            source,
            client_command_id=client_command_id,
            expected_revision=expected_revision,
            command=command,
            event_id=event["event_id"],
            next_events_builder=lambda current: [*current, event],
        )

    def update_event(
        self,
        review_id: str,
        source: CardEventReviewSource,
        *,
        event_id: str,
        client_command_id: str,
        expected_revision: int,
        action: str,
        effective_time_s: float | None = None,
        event_type: str | None = None,
        confidence: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Apply one event command without losing proposal lineage."""

        _validate_event_id(event_id)
        _validate_command_id(client_command_id)
        _validate_expected_revision(expected_revision)
        if action not in CARD_EVENT_COMMAND_ACTIONS:
            raise CardEventReviewError(f"Unknown CardEvent event action: {action}.")
        if action == "retime":
            if effective_time_s is None:
                raise CardEventReviewError("retime requires effective_time_s.")
            _validate_event_time(effective_time_s)
        if action == "edit":
            if event_type is None and confidence is None and notes is None:
                raise CardEventReviewError("edit requires a field change.")
            if event_type is not None and event_type not in CARD_EVENT_TYPES:
                raise CardEventReviewError(f"Unknown CardEvent event type: {event_type}.")
            if confidence is not None and confidence not in CARD_EVENT_CONFIDENCES:
                raise CardEventReviewError(
                    "event.confidence must be confirmed, uncertain, ignore, or proposed."
                )
        command = {
            "operation": action,
            "client_command_id": client_command_id,
            "expected_revision": expected_revision,
            "event_id": event_id,
            "effective_time_s": effective_time_s,
            "type": event_type,
            "confidence": confidence,
            "notes": notes,
        }

        def next_events_builder(current: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
            events = [dict(item) for item in current]
            index = next(
                (index for index, item in enumerate(events) if item.get("event_id") == event_id),
                None,
            )
            if index is None:
                raise CardEventReviewNotFound("The CardEvent event was not found.")
            event = events[index]
            state = str(event["state"])
            has_proposal = event.get("proposal") is not None
            if action == "accept":
                if not has_proposal or state != "proposed":
                    raise CardEventReviewError("Only a proposed event can be accepted.")
                event["state"] = "reviewed"
                if event.get("confidence") == "proposed":
                    event["confidence"] = "confirmed"
            elif action == "dismiss":
                if not has_proposal or state != "proposed":
                    raise CardEventReviewError("Only a proposed event can be dismissed.")
                event["state"] = "dismissed"
                event["confidence"] = "ignore"
            elif action == "undo":
                if not has_proposal or state not in {"reviewed", "dismissed"}:
                    raise CardEventReviewError(
                        "Only an accepted or dismissed proposal can be undone."
                    )
                event["state"] = "proposed"
                event["confidence"] = "proposed"
            elif action == "edit":
                if state == "dismissed":
                    raise CardEventReviewError("Undo a dismissed proposal before editing it.")
                if event_type is not None:
                    event["type"] = event_type
                if confidence is not None:
                    event["confidence"] = confidence
                if notes is not None:
                    event["notes"] = notes
                if state == "proposed":
                    event["state"] = "reviewed"
                    if event.get("confidence") == "proposed":
                        event["confidence"] = "confirmed"
            elif action == "retime":
                if state == "dismissed":
                    raise CardEventReviewError("Undo a dismissed proposal before retiming it.")
                event["effective_time_s"] = float(effective_time_s)  # type: ignore[arg-type]
                if state == "proposed":
                    event["state"] = "reviewed"
                    if event.get("confidence") == "proposed":
                        event["confidence"] = "confirmed"
            elif action == "remove":
                if has_proposal and state in {"proposed", "dismissed"}:
                    raise CardEventReviewError(
                        "A proposed or dismissed event remains in review history; undo it first."
                    )
                events.pop(index)
            return events

        return self._run_event_command(
            review_id,
            source,
            client_command_id=client_command_id,
            expected_revision=expected_revision,
            command=command,
            event_id=event_id,
            next_events_builder=next_events_builder,
        )

    def _run_event_command(
        self,
        review_id: str,
        source: CardEventReviewSource,
        *,
        client_command_id: str,
        expected_revision: int,
        command: Mapping[str, Any],
        event_id: str,
        next_events_builder: Any,
    ) -> dict[str, Any]:
        command_path = self._resource_command_path(review_id, client_command_id)
        command_digest = _digest(command)
        with _review_lock(self._resource_root(), exclusive=True):
            current = self._read_resource_locked(review_id)
            _validate_resource_state(current, source, review_id)
            existing = _read_existing_or_none(command_path)
            if existing is not None:
                if existing.get("command_digest") != command_digest:
                    raise CardEventReviewConflict(
                        "The client command ID was already used for another event command."
                    )
                response = existing.get("response")
                if not isinstance(response, Mapping):
                    raise CardEventReviewError("The stored CardEvent command receipt is invalid.")
                return dict(response)
            _assert_revision(current, expected_revision)
            if current["review_state"] == "completed":
                raise CardEventReviewConflict(
                    "The review is complete. Create a new revision before editing it."
                )
            next_events = _validate_event_collection(next_events_builder(current["events"]), source)
            changed_event = next(
                (event for event in next_events if event.get("event_id") == event_id),
                None,
            )
            previous_event = next(
                (event for event in current["events"] if event.get("event_id") == event_id),
                None,
            )
            if changed_event is None and previous_event is None:
                raise CardEventReviewNotFound("The CardEvent event was not found.")
            updated = dict(current)
            updated.update(
                {
                    "events": next_events,
                    "draft_revision": current["draft_revision"] + 1,
                    "updated_at": _now(),
                }
            )
            updated["draft_digest"] = _draft_digest(updated)
            self._write_resource_locked(updated)
            response = _event_command_response(updated, source, changed_event)
            _write_immutable_json(
                command_path,
                {
                    "schema_version": CARD_EVENT_REVIEW_EVENT_SCHEMA_VERSION,
                    "review_id": review_id,
                    "client_command_id": client_command_id,
                    "command_digest": command_digest,
                    "response": response,
                },
            )
        return response

    def update_review(
        self,
        review_id: str,
        source: CardEventReviewSource,
        *,
        annotation: Mapping[str, Any],
        proposals: Sequence[Mapping[str, Any]],
        expected_revision: int,
        full_video_acknowledged: bool = False,
    ) -> dict[str, Any]:
        """Save one complete next draft for a recording-owned review."""

        _validate_expected_revision(expected_revision)
        with _review_lock(self._resource_root(), exclusive=True):
            current = self._read_resource_locked(review_id)
            _validate_resource_state(current, source, review_id)
            _assert_revision(current, expected_revision)
            if current["review_state"] == "completed":
                raise CardEventReviewConflict(
                    "The review is complete. Create a new revision before editing it."
                )
            decisions = _validate_proposal_decisions(proposals, source.proposals)
            normalized_annotation = _validate_annotation(annotation, source)
            events = _legacy_events_from_payload(normalized_annotation, decisions, source)
            updated = dict(current)
            updated.update(
                {
                    "events": events,
                    "draft_revision": current["draft_revision"] + 1,
                    "full_video_acknowledged": full_video_acknowledged,
                    "updated_at": _now(),
                }
            )
            updated["draft_digest"] = _draft_digest(updated)
            self._write_resource_locked(updated)
        return _project_resource(updated, source)

    def complete_review(
        self,
        review_id: str,
        source: CardEventReviewSource,
        *,
        reviewer: str,
        expected_revision: int,
        full_video_acknowledged: bool,
    ) -> dict[str, Any]:
        """Complete one resource and publish immutable review artifacts."""

        _validate_expected_revision(expected_revision)
        _validate_operator(reviewer)
        if not full_video_acknowledged:
            raise CardEventReviewError(
                "A full-video acknowledgement is required to complete review."
            )

        with _review_lock(self._resource_root(), exclusive=True):
            current = self._read_resource_locked(review_id)
            _validate_resource_state(current, source, review_id)
            _assert_revision(current, expected_revision)
            if current["review_state"] == "completed":
                if (
                    current.get("reviewer") == reviewer.strip()
                    and current.get("completed_version_id")
                    and current.get("completion_receipt_id")
                ):
                    return _project_resource(current, source)
                raise CardEventReviewConflict(
                    "The review is already complete. Create a new revision before completing it."
                )

            events = _validate_event_collection(current["events"], source)
            if any(event["state"] == "proposed" for event in events):
                raise CardEventReviewError(
                    "Every proposed CardEvent must be accepted, dismissed, or edited "
                    "before completion."
                )
            annotation = _annotation_from_events(events, source)
            decisions = _proposal_decisions_from_events(events)
            input_digest = _draft_digest(current)
            annotation_digest = _digest(annotation)
            proposal_decision_digest = _digest(_decision_mapping(decisions))
            completion_key = _digest(
                {
                    "review_id": review_id,
                    "draft_revision": current["draft_revision"],
                    "input_draft_digest": input_digest,
                    "reviewer": reviewer.strip(),
                }
            )[:20]
            version_id = "cardevent-reviewed-" + completion_key
            version_path = self._resource_version_path(review_id, version_id)
            version = _read_existing_or_none(version_path)
            if version is None:
                completed_at = _now()
                version_core = {
                    "schema_version": CARD_EVENT_REVIEWED_VERSION_SCHEMA_VERSION,
                    "review_id": review_id,
                    "recording_id": source.recording_id,
                    "source_asset_id": source.source_asset_id,
                    "source_sha256": source.source_sha256,
                    "events": events,
                    "annotation": annotation,
                    "proposal_decisions": _decision_mapping(decisions),
                    "input_draft_revision": current["draft_revision"],
                    "input_draft_digest": input_digest,
                    "source_digest": source.source_sha256,
                    "reviewed_annotation_digest": annotation_digest,
                    "proposal_decision_digest": proposal_decision_digest,
                    "reviewer": reviewer.strip(),
                    "completed_at": completed_at,
                    "parent_review_id": current.get("parent_review_id"),
                    "parent_version_id": current.get("parent_version_id"),
                    "parent_digest": current.get("parent_digest"),
                }
                version = {**version_core, "version_id": version_id}
                version["version_digest"] = _digest(version)
                _write_immutable_json(version_path, version)
            _validate_version(version, source, version_id)
            completed_at = str(version["completed_at"])
            receipt = _resource_completion_receipt(
                source,
                review_id=review_id,
                version_id=version_id,
                version_digest=version["version_digest"],
                input_draft_digest=input_digest,
                annotation_digest=annotation_digest,
                proposal_decision_digest=proposal_decision_digest,
                reviewer=reviewer.strip(),
                occurred_at=completed_at,
            )
            _write_immutable_json(
                self._resource_receipt_path(review_id, receipt["receipt_id"]), receipt
            )
            completed = dict(current)
            completed.update(
                {
                    "events": events,
                    "full_video_acknowledged": True,
                    "review_state": "completed",
                    "reviewer": reviewer.strip(),
                    "completed_at": completed_at,
                    "completed_version_id": version_id,
                    "completed_version_digest": version["version_digest"],
                    "reviewed_annotation_digest": annotation_digest,
                    "proposal_decision_digest": proposal_decision_digest,
                    "completion_receipt_id": receipt["receipt_id"],
                    "updated_at": _now(),
                }
            )
            completed["draft_digest"] = _draft_digest(completed)
            self._write_resource_locked(completed)
        return _project_resource(completed, source)

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
                normalized_annotation, decisions, source.proposals, source
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
                if (
                    current.get("reviewer") == reviewer.strip()
                    and current.get("full_video_acknowledged") is True
                    and current.get("completed_version_id")
                    and current.get("completion_receipt_id")
                ):
                    return _project_state(current, source)
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

    def _resource_root(self) -> Path:
        return self.workspace_root / "cardevent-reviews"

    def _resource_path(self, review_id: str) -> Path:
        if REVIEW_ID_PATTERN.fullmatch(review_id) is None:
            raise CardEventReviewNotFound("The CardEvent review was not found.")
        return self._resource_root() / review_id / "review.json"

    def _resource_version_path(self, review_id: str, version_id: str) -> Path:
        return self._resource_path(review_id).parent / "versions" / f"{version_id}.json"

    def _resource_receipt_path(self, review_id: str, receipt_id: str) -> Path:
        return self._resource_path(review_id).parent / "receipts" / f"{receipt_id}.json"

    def _resource_command_path(self, review_id: str, client_command_id: str) -> Path:
        return (
            self._resource_path(review_id).parent
            / "commands"
            / f"{_digest({'client_command_id': client_command_id})}.json"
        )

    def _resource_states_locked(self, source: CardEventReviewSource) -> list[dict[str, Any]]:
        root = self._resource_root()
        if not root.is_dir():
            return []
        states: list[dict[str, Any]] = []
        for directory in sorted(root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            path = directory / "review.json"
            if not path.is_file():
                continue
            state = _read_json(path)
            if state.get("recording_id") != source.recording_id:
                continue
            _validate_resource_state(state, source, directory.name)
            states.append(state)
        return states

    def _current_resource(self, source: CardEventReviewSource) -> dict[str, Any] | None:
        with _review_lock(self._resource_root(), exclusive=False):
            states = self._resource_states_locked(source)
        return _sort_resources(states)[0] if states else None

    def _read_resource_locked(self, review_id: str) -> dict[str, Any]:
        path = self._resource_path(review_id)
        try:
            return _read_json(path)
        except FileNotFoundError as error:
            raise CardEventReviewNotFound("The CardEvent review was not found.") from error
        except OSError as error:
            raise CardEventReviewWriteError("The CardEvent review could not be read.") from error

    def _read_resource_version_locked(
        self, state: Mapping[str, Any], version_id: str
    ) -> dict[str, Any]:
        path = self._resource_version_path(str(state["review_id"]), version_id)
        try:
            return _read_json(path)
        except FileNotFoundError as error:
            raise CardEventReviewNotFound(
                "The completed CardEvent review version was not found."
            ) from error
        except OSError as error:
            raise CardEventReviewWriteError(
                "The completed CardEvent review version could not be read."
            ) from error

    def _write_resource_locked(self, state: Mapping[str, Any]) -> None:
        try:
            _atomic_write_json(self._resource_path(str(state["review_id"])), state)
        except OSError as error:
            raise CardEventReviewWriteError("The CardEvent review could not be saved.") from error

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

    return (
        "cardevent-proposal-"
        + _digest(
            {
                "source_asset_id": source_asset_id,
                "run_id": run_id,
                "index": index,
                "time_s": time_s,
            }
        )[:20]
    )


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


def _initial_events(source: CardEventReviewSource) -> list[dict[str, Any]]:
    return [_proposal_event(proposal) for proposal in source.proposals]


def _proposal_event(proposal: CardEventProposal) -> dict[str, Any]:
    return {
        "event_id": _proposal_event_id(proposal.proposal_id),
        "effective_time_s": float(proposal.time_s),
        "type": "card_played",
        "confidence": "proposed",
        "state": "proposed",
        "origin": "model",
        "proposal": {
            "proposal_id": proposal.proposal_id,
            "proposal_generator_run_id": proposal.proposal_generator_run_id,
            "proposal_time_s": float(proposal.time_s),
            "probability": float(proposal.probability),
            "model_bundle_id": proposal.model_bundle_id,
            "execution_platform": proposal.execution_platform,
        },
    }


def _proposal_event_id(proposal_id_value: str) -> str:
    return "cardevent-event-" + _digest({"proposal_id": proposal_id_value})[:32]


def _resource_state(
    source: CardEventReviewSource,
    *,
    review_id: str,
    operator: str,
    created_at: str,
    updated_at: str,
    events: Sequence[Mapping[str, Any]],
    parent_review_id: str | None = None,
    parent_version_id: str | None = None,
    parent_digest: str | None = None,
) -> dict[str, Any]:
    """Build one recording-owned draft resource."""

    state: dict[str, Any] = {
        "schema_version": CARD_EVENT_REVIEW_RESOURCE_SCHEMA_VERSION,
        "review_id": review_id,
        "recording_id": source.recording_id,
        "source_asset_id": source.source_asset_id,
        "source_sha256": source.source_sha256,
        "video": Path(source.video).name,
        "operator": operator,
        "created_at": created_at,
        "updated_at": updated_at,
        "review_state": "draft",
        "draft_revision": 0,
        "events": _validate_event_collection(list(events), source),
        "full_video_acknowledged": False,
        "reviewer": None,
        "completed_at": None,
        "completed_version_id": None,
        "completed_version_digest": None,
        "parent_review_id": parent_review_id,
        "parent_version_id": parent_version_id,
        "parent_digest": parent_digest,
        "reviewed_annotation_digest": None,
        "proposal_decision_digest": None,
        "completion_receipt_id": None,
    }
    state["draft_digest"] = _draft_digest(state)
    return state


def _project_resource(state: Mapping[str, Any], source: CardEventReviewSource) -> dict[str, Any]:
    """Project one resource without exposing its private proposal mapping."""

    projected = _project_state(state, source)
    events = _validate_event_collection(state["events"], source)
    return {
        **projected,
        "schema_version": CARD_EVENT_REVIEW_RESOURCE_SCHEMA_VERSION,
        "review_id": state["review_id"],
        "operator": state["operator"],
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
        "parent_review_id": state.get("parent_review_id"),
        "review_url": f"/card-event-reviews/{state['review_id']}",
        "events": events,
    }


def _project_resource_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    events = state.get("events", [])
    counts = _event_counts(events if isinstance(events, list) else [])
    return {
        "review_id": state["review_id"],
        "recording_id": state["recording_id"],
        "state": state["review_state"],
        "review_state": state["review_state"],
        "operator": state["operator"],
        "reviewer": state.get("reviewer"),
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
        "completed_at": state.get("completed_at"),
        "completed_version_id": state.get("completed_version_id"),
        "completed_version_digest": state.get("completed_version_digest"),
        "parent_review_id": state.get("parent_review_id"),
        "parent_version_id": state.get("parent_version_id"),
        "event_counts": {
            "reviewed": counts["reviewed"],
            "proposed": counts["proposed"],
            "dismissed": counts["dismissed"],
        },
        "reviewed_event_count": counts["reviewed"],
        "proposed_event_count": counts["proposed"],
        "dismissed_event_count": counts["dismissed"],
        "review_url": f"/card-event-reviews/{state['review_id']}",
    }


def _sort_resources(states: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Sort drafts first and completed reviews newest first."""

    return [
        dict(state)
        for state in sorted(
            states,
            key=lambda state: (
                0 if state.get("review_state") == "draft" else 1,
                -_timestamp_sort_value(
                    state.get("updated_at")
                    if state.get("review_state") == "draft"
                    else state.get("completed_at")
                ),
                str(state.get("review_id", "")),
            ),
        )
    ]


def _timestamp_sort_value(value: object) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _select_parent_resource(
    states: Sequence[Mapping[str, Any]], parent_review_id: str | None
) -> Mapping[str, Any] | None:
    completed = [state for state in states if state.get("review_state") == "completed"]
    if parent_review_id is not None:
        if REVIEW_ID_PATTERN.fullmatch(parent_review_id) is None:
            raise CardEventReviewNotFound("The parent CardEvent review was not found.")
        parent = next(
            (state for state in completed if state.get("review_id") == parent_review_id),
            None,
        )
        if parent is None:
            raise CardEventReviewNotFound("The parent CardEvent review was not found.")
        return parent
    return max(
        completed,
        key=lambda state: _timestamp_sort_value(state.get("completed_at")),
        default=None,
    )


def _validate_operator(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CardEventReviewError("operator must be a non-empty string.")


def _validate_resource_state(
    state: Mapping[str, Any], source: CardEventReviewSource, review_id: str
) -> None:
    if state.get("schema_version") != CARD_EVENT_REVIEW_RESOURCE_SCHEMA_VERSION:
        raise CardEventReviewError("The stored CardEvent review has an unsupported schema.")
    if state.get("review_id") != review_id:
        raise CardEventReviewError("The stored CardEvent review ID does not match its path.")
    if (
        state.get("recording_id") != source.recording_id
        or state.get("source_asset_id") != source.source_asset_id
        or state.get("source_sha256") != source.source_sha256
        or state.get("video") != Path(source.video).name
    ):
        raise CardEventReviewConflict(
            "The accepted recording source changed. The review resource was not modified."
        )
    if state.get("review_state") not in {"draft", "completed"}:
        raise CardEventReviewError("The stored CardEvent review has an invalid state.")
    _validate_operator(state.get("operator"))
    for field in ("created_at", "updated_at"):
        if not isinstance(state.get(field), str) or not state[field]:
            raise CardEventReviewError(f"The stored CardEvent review has an invalid {field}.")
    if not isinstance(state.get("draft_revision"), int) or state["draft_revision"] < 0:
        raise CardEventReviewError("The stored CardEvent review has an invalid draft revision.")
    if _draft_digest(state) != state.get("draft_digest"):
        raise CardEventReviewError("The stored CardEvent review draft digest is invalid.")
    _validate_event_collection(state.get("events"), source)
    if state.get("review_state") == "completed":
        if not state.get("reviewer") or not state.get("completed_version_id"):
            raise CardEventReviewError("The completed CardEvent review is missing completion data.")
        _validate_operator(state["reviewer"])


def _resource_completion_receipt(
    source: CardEventReviewSource,
    *,
    review_id: str,
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
            {"kind": "review", "id": review_id, "digest": input_draft_digest},
        ],
        "outputs": [
            {"kind": "annotation_set", "id": version_id, "digest": annotation_digest},
            {"kind": "review", "id": review_id, "digest": version_digest},
        ],
        "dependencies": [
            {"kind": "source_asset", "id": source.source_asset_id, "digest": source.source_sha256}
        ],
        "metadata": {
            "recording_id": source.recording_id,
            "review_id": review_id,
            "input_draft_digest": input_draft_digest,
            "source_digest": source.source_sha256,
            "reviewed_annotation_digest": annotation_digest,
            "proposal_decision_digest": proposal_decision_digest,
        },
    }
    receipt_digest_core = {key: value for key, value in core.items() if key != "occurred_at"}
    return {
        **core,
        "receipt_id": "receipt-cardevent-review-" + _digest(receipt_digest_core)[:20],
        "receipt_digest": _digest(receipt_digest_core),
    }


def _read_existing_or_none(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return _read_json(path)
    except OSError as error:
        raise CardEventReviewWriteError(
            "The immutable CardEvent review artifact could not be read."
        ) from error


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
    if "events" in state:
        events = _validate_event_collection(state["events"], source)
        annotation = _annotation_from_events(events, source)
        decisions = _proposal_decisions_from_events(events)
    else:
        annotation = _validate_annotation(state.get("annotation"), source)
        decisions = _proposal_decisions_from_state(state)
    proposals = [
        proposal.to_mapping(decisions.get(proposal.proposal_id, "undecided"))
        for proposal in source.proposals
    ]
    return {
        "schema_version": CARD_EVENT_REVIEW_SCHEMA_VERSION,
        "recording_id": source.recording_id,
        "source_asset_id": source.source_asset_id,
        "source_sha256": source.source_sha256,
        "video": Path(source.video).name,
        "annotation": annotation,
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


def _validate_event_collection(
    events: object, source: CardEventReviewSource
) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        raise CardEventReviewError("CardEvent review events must be a list.")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(events):
        if not isinstance(value, Mapping):
            raise CardEventReviewError(f"CardEvent review events[{index}] must be an object.")
        event_id = value.get("event_id")
        _validate_event_id(event_id)
        if event_id in seen_ids:
            raise CardEventReviewError("CardEvent event IDs must be unique.")
        seen_ids.add(event_id)
        effective_time_s = value.get("effective_time_s")
        _validate_event_time(effective_time_s, source)
        event_type = value.get("type")
        if not isinstance(event_type, str) or event_type not in CARD_EVENT_TYPES:
            raise CardEventReviewError(f"Unknown CardEvent event type: {event_type}.")
        state = value.get("state")
        if state not in CARD_EVENT_EVENT_STATES:
            raise CardEventReviewError(f"Unknown CardEvent event state: {state}.")
        origin = value.get("origin")
        if origin not in CARD_EVENT_EVENT_ORIGINS:
            raise CardEventReviewError(f"Unknown CardEvent event origin: {origin}.")
        confidence = value.get("confidence")
        if confidence is not None and confidence not in CARD_EVENT_CONFIDENCES:
            raise CardEventReviewError(
                "event.confidence must be confirmed, uncertain, ignore, or proposed."
            )
        notes = value.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise CardEventReviewError("event.notes must be a string or null.")
        proposal = value.get("proposal")
        normalized_proposal = _validate_event_proposal(proposal, source)
        if origin == "manual" and normalized_proposal is not None:
            raise CardEventReviewError("Manual CardEvents cannot have proposal lineage.")
        if origin != "manual" and normalized_proposal is None:
            raise CardEventReviewError("Model or device CardEvents need proposal lineage.")
        if state == "proposed" and normalized_proposal is None:
            raise CardEventReviewError("Only proposal-backed CardEvents can be proposed.")
        if state == "proposed" and confidence != "proposed":
            raise CardEventReviewError("Proposed CardEvents must use proposed confidence.")
        if state != "proposed" and confidence == "proposed":
            raise CardEventReviewError(
                "Reviewed or dismissed CardEvents cannot use proposed confidence."
            )
        normalized_event: dict[str, Any] = {
            "event_id": event_id,
            "effective_time_s": float(effective_time_s),
            "type": event_type,
            "confidence": confidence,
            "state": state,
            "origin": origin,
            "proposal": normalized_proposal,
        }
        if notes is not None:
            normalized_event["notes"] = notes
        normalized.append(normalized_event)
    normalized.sort(key=lambda event: (event["effective_time_s"], event["event_id"]))
    for previous, current in zip(normalized, normalized[1:], strict=False):
        if (
            current["effective_time_s"] - previous["effective_time_s"]
            <= DUPLICATE_EVENT_TOLERANCE_S
        ):
            raise CardEventReviewError(
                "CardEvent events must be more than 10 ms apart before saving."
            )
    return normalized


def _validate_event_proposal(
    proposal: object, source: CardEventReviewSource
) -> dict[str, Any] | None:
    if proposal is None:
        return None
    if not isinstance(proposal, Mapping):
        raise CardEventReviewError("CardEvent proposal lineage must be an object or null.")
    required = {
        "proposal_id",
        "proposal_generator_run_id",
        "proposal_time_s",
        "probability",
        "model_bundle_id",
        "execution_platform",
    }
    if set(proposal) != required:
        raise CardEventReviewError("CardEvent proposal lineage has unknown or missing fields.")
    proposal_id_value = proposal.get("proposal_id")
    source_proposal = next(
        (item for item in source.proposals if item.proposal_id == proposal_id_value), None
    )
    if source_proposal is None:
        raise CardEventReviewError("The CardEvent event references a foreign proposal ID.")
    expected = {
        "proposal_id": source_proposal.proposal_id,
        "proposal_generator_run_id": source_proposal.proposal_generator_run_id,
        "proposal_time_s": float(source_proposal.time_s),
        "probability": float(source_proposal.probability),
        "model_bundle_id": source_proposal.model_bundle_id,
        "execution_platform": source_proposal.execution_platform,
    }
    if dict(proposal) != expected:
        raise CardEventReviewError("CardEvent proposal lineage is not immutable source data.")
    return expected


def _validate_event_fields(
    *,
    effective_time_s: object,
    event_type: object,
    confidence: object,
    notes: object,
) -> dict[str, Any]:
    _validate_event_time(effective_time_s)
    if not isinstance(event_type, str) or event_type not in CARD_EVENT_TYPES:
        raise CardEventReviewError(f"Unknown CardEvent event type: {event_type}.")
    if confidence is not None and (
        not isinstance(confidence, str) or confidence not in CARD_EVENT_CONFIDENCES - {"proposed"}
    ):
        raise CardEventReviewError(
            "Manual CardEvent confidence must be confirmed, uncertain, or ignore."
        )
    if notes is not None and not isinstance(notes, str):
        raise CardEventReviewError("event.notes must be a string or null.")
    return {
        "effective_time_s": float(effective_time_s),
        "type": event_type,
        "confidence": "confirmed" if confidence is None else confidence,
        **({"notes": notes} if notes is not None else {}),
    }


def _validate_event_time(value: object, source: CardEventReviewSource | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardEventReviewError("effective_time_s must be a number.")
    time_s = float(value)
    if not math.isfinite(time_s) or time_s < 0:
        raise CardEventReviewError("effective_time_s must be finite and non-negative.")
    if source is not None and source.duration_s is not None and time_s > source.duration_s + 1e-6:
        raise CardEventReviewError("Event time exceeds the accepted source video duration.")


def _validate_event_id(value: object) -> None:
    if not isinstance(value, str) or EVENT_ID_PATTERN.fullmatch(value) is None:
        raise CardEventReviewError("event_id must be a stable CardEvent event ID.")


def _validate_command_id(value: object) -> None:
    if not isinstance(value, str) or COMMAND_ID_PATTERN.fullmatch(value) is None:
        raise CardEventReviewError("client_command_id must be a safe non-empty identifier.")


def _annotation_from_events(
    events: Sequence[Mapping[str, Any]], source: CardEventReviewSource
) -> dict[str, Any]:
    reviewed_events = [event for event in events if event.get("state") == "reviewed"]
    annotation = {
        "schema_version": CARD_EVENT_ANNOTATION_SCHEMA_VERSION,
        "video": Path(source.video).name,
        "events": [
            {
                "time_s": float(event["effective_time_s"]),
                "type": event["type"],
                "confidence": event["confidence"],
                **({"notes": event["notes"]} if "notes" in event else {}),
            }
            for event in sorted(
                reviewed_events,
                key=lambda item: (item["effective_time_s"], item["event_id"]),
            )
        ],
    }
    return _validate_annotation(annotation, source)


def _proposal_decisions_from_events(events: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for event in events:
        proposal = event.get("proposal")
        if isinstance(proposal, Mapping):
            state = event.get("state")
            decisions[str(proposal["proposal_id"])] = {
                "proposed": "undecided",
                "reviewed": "accepted",
                "dismissed": "dismissed",
            }[str(state)]
    return {key: decisions[key] for key in sorted(decisions)}


def _event_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "reviewed": sum(event.get("state") == "reviewed" for event in events),
        "proposed": sum(event.get("state") == "proposed" for event in events),
        "dismissed": sum(event.get("state") == "dismissed" for event in events),
    }


def _event_command_response(
    state: Mapping[str, Any],
    source: CardEventReviewSource,
    changed_event: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the small response used by one event command."""

    events = _validate_event_collection(state["events"], source)
    return {
        "schema_version": CARD_EVENT_REVIEW_EVENT_SCHEMA_VERSION,
        "review_id": state["review_id"],
        "draft_revision": state["draft_revision"],
        "changed_event": None if changed_event is None else dict(changed_event),
        "event_counts": _event_counts(events),
        "completion_blockers": (
            ["proposed_events"] if any(event["state"] == "proposed" for event in events) else []
        ),
    }


def _legacy_events_from_payload(
    annotation: Mapping[str, Any],
    decisions: Mapping[str, str],
    source: CardEventReviewSource,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, value in enumerate(annotation["events"]):
        event = dict(value)
        fields = _validate_event_fields(
            effective_time_s=event["time_s"],
            event_type=event["type"],
            confidence=event.get("confidence"),
            notes=event.get("notes"),
        )
        event_id = event.get("event_id")
        if event_id is None:
            event_id = "cardevent-event-" + _digest({"manual": fields, "index": index})[:32]
        events.append(
            {
                "event_id": event_id,
                **fields,
                "state": "reviewed",
                "origin": "manual",
                "proposal": None,
            }
        )
    for proposal in source.proposals:
        decision = decisions[proposal.proposal_id]
        if decision == "undecided":
            events.append(_proposal_event(proposal))
        else:
            event = _proposal_event(proposal)
            event["state"] = "reviewed" if decision == "accepted" else "dismissed"
            event["confidence"] = "confirmed" if decision == "accepted" else None
            events.append(event)
    return _validate_event_collection(events, source)


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
    source: CardEventReviewSource,
) -> dict[str, Any]:
    """Project accepted legacy decisions without inferring timestamp relationships."""

    events = [dict(event) for event in annotation["events"]]
    for proposal in proposals:
        if decisions[proposal.proposal_id] != "accepted":
            continue
        events.append(
            {
                "time_s": proposal.time_s,
                "type": "card_played",
                "confidence": "confirmed",
            }
        )
    events.sort(key=lambda event: event["time_s"])
    return _validate_annotation(
        {
            "schema_version": annotation["schema_version"],
            "video": annotation["video"],
            "events": events,
        },
        source,
    )


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
    if isinstance(version.get("events"), list):
        events = _validate_event_collection(version["events"], source)
        annotation = _annotation_from_events(events, source)
        if version.get("annotation") != annotation:
            raise CardEventReviewError(
                "The completed CardEvent review annotation does not match its event collection."
            )
    else:
        _validate_annotation(version.get("annotation"), source)
        decision_mapping = version.get("proposal_decisions")
        if not isinstance(decision_mapping, Mapping):
            raise CardEventReviewError(
                "The completed CardEvent review version has invalid decisions."
            )
        _validate_proposal_decisions(
            [{"proposal_id": key, "decision": value} for key, value in decision_mapping.items()],
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
    receipt_digest_core = {key: value for key, value in core.items() if key not in {"occurred_at"}}
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
    "CARD_EVENT_REVIEW_COLLECTION_SCHEMA_VERSION",
    "CARD_EVENT_REVIEW_RESOURCE_SCHEMA_VERSION",
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
