"""Assemble selected recording-pipeline results into table observations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from .pipeline_data import TableObservationData, VisibleCardData, VisualIdentityData
from .table_observation import (
    OBSERVATION_SCHEMA_VERSION,
    AnalyzerMetadata,
    IdentityCandidate,
    ObservationSession,
    ObservationSource,
    ObservedCard,
    TableObservation,
)

ASSEMBLY_IMPLEMENTATION_NAME = "observation-assembler"
ASSEMBLY_IMPLEMENTATION_VERSION = "v1"


class ObservationAssemblyError(ValueError):
    """Selected pipeline results cannot be assembled into observations."""


def assemble_table_observations(
    events: Any,
    visible_cards: VisibleCardData,
    visual_identities: VisualIdentityData,
    *,
    recording_id: str,
    video_sha256: str,
    assembly_run_id: str,
    input_revision_ids: Sequence[str] | None = None,
    event_revision_id: str | None = None,
    visible_card_revision_id: str | None = None,
    visual_identity_revision_id: str | None = None,
    session_id: str | None = None,
    calibration: Literal["fixture", "uncalibrated", "calibrated"] = "uncalibrated",
    analyzer_name: str = ASSEMBLY_IMPLEMENTATION_NAME,
    analyzer_version: str = ASSEMBLY_IMPLEMENTATION_VERSION,
) -> TableObservationData:
    """Join exact compatible event, visible-card, and identity results.

    The function only joins evidence.  It does not assign players, tricks, or any other gameplay
    state.  A missing or unusable identity keeps the observation's evidence state explicit.
    """

    revision_ids = _input_revision_ids(
        input_revision_ids,
        event_revision_id,
        visible_card_revision_id,
        visual_identity_revision_id,
    )
    if not recording_id or not video_sha256 or not assembly_run_id:
        raise ObservationAssemblyError("recording, video, and assembly identities are required")
    source = ObservationSource(
        recording_id=recording_id,
        video_sha256=video_sha256,
        assembly_run_id=assembly_run_id,
        input_revision_ids=list(revision_ids),
    )
    event_ids = {event.event_id for event in events.events}
    visible_by_event = {outcome.event_id: outcome for outcome in visible_cards.outcomes}
    for outcome in visible_cards.outcomes:
        if outcome.event_id not in event_ids:
            raise ObservationAssemblyError(
                f"visible-card outcome references unknown event: {outcome.event_id}"
            )
        if (
            outcome.frame_identity is not None
            and outcome.frame_identity.source_video_sha256 != video_sha256
        ):
            raise ObservationAssemblyError(
                f"visible-card frame uses a different video source: {outcome.event_id}"
            )

    visible_cards_by_id = {
        candidate.card_id: (outcome, candidate)
        for outcome in visible_cards.outcomes
        for candidate in outcome.candidates
    }
    for identity in visual_identities.outcomes:
        visible = visible_cards_by_id.get(identity.card_id)
        if visible is None:
            raise ObservationAssemblyError(
                f"identity outcome references unknown visible card: {identity.card_id}"
            )
        visible_outcome, visible_candidate = visible
        if visible_outcome.frame_identity is None:
            raise ObservationAssemblyError(
                f"identity outcome references a visible card without a frame: {identity.card_id}"
            )
        if identity.frame_identity.to_mapping() != visible_outcome.frame_identity.to_mapping():
            raise ObservationAssemblyError(
                f"identity frame does not match visible-card frame: {identity.card_id}"
            )
        if identity.geometry.to_mapping() != visible_candidate.geometry.to_mapping():
            raise ObservationAssemblyError(
                f"identity geometry does not match visible-card geometry: {identity.card_id}"
            )

    observations: list[TableObservation] = []
    for event_index, event in enumerate(events.events, start=1):
        visible_outcome = visible_by_event.get(event.event_id)
        if visible_outcome is None:
            raise ObservationAssemblyError(f"event has no visible-card outcome: {event.event_id}")
        cards: list[ObservedCard] = []
        identity_statuses: dict[str, str] = {}
        identity_details: dict[str, dict[str, str]] = {}
        for candidate in visible_outcome.candidates:
            identity = next(
                (item for item in visual_identities.outcomes if item.card_id == candidate.card_id),
                None,
            )
            if identity is None:
                identity_status = "unusable" if candidate.side == "face_down" else "failed"
                identity_statuses[candidate.card_id] = identity_status
                identity_details[candidate.card_id] = {
                    "side": candidate.side,
                    "status": identity_status,
                    "reason": (
                        "face-down card has no identity outcome"
                        if candidate.side == "face_down"
                        else "missing visual identity outcome"
                    ),
                }
                cards.append(
                    ObservedCard(
                        observed_card_id=candidate.card_id,
                        side=candidate.side,
                        identity_status=identity_status,
                        identity_candidates=[],
                    )
                )
                continue
            converted = _identity_candidates(identity.candidates)
            identity_status = "unusable" if candidate.side == "face_down" else identity.status
            if identity_status == "classified" and not converted:
                identity_status = "unusable"
            identity_statuses[candidate.card_id] = identity_status
            detail = {"side": candidate.side, "status": identity_status}
            if identity.unusable_reason is not None:
                detail["unusable_reason"] = identity.unusable_reason
            elif candidate.side == "face_down":
                detail["unusable_reason"] = "face_down"
            if identity.error is not None:
                detail["error"] = identity.error
            identity_details[candidate.card_id] = detail
            cards.append(
                ObservedCard(
                    observed_card_id=candidate.card_id,
                    side=candidate.side,
                    identity_status=identity_status,
                    identity_candidates=converted if identity_status == "classified" else [],
                )
            )

        if visible_outcome.status == "failed":
            status = "insufficient_evidence"
            cards = []
        elif visible_outcome.status == "empty":
            status = "observed"
            cards = []
        elif visible_outcome.status == "detected":
            status = "observed"
        else:
            status = "insufficient_evidence"

        diagnostics: dict[str, object] = {
            "assembly": {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "visible_card_status": visible_outcome.status,
                "identity_statuses": identity_statuses,
                "identity_details": identity_details,
                "retained_card_count": len(cards),
                "usable_identity_count": sum(
                    card.identity_status == "classified" for card in cards
                ),
            }
        }
        observations.append(
            TableObservation(
                schema_version=OBSERVATION_SCHEMA_VERSION,
                observation_id=f"{assembly_run_id}-observation-{event_index:04d}",
                source=source,
                session=ObservationSession(
                    session_id=session_id or recording_id,
                    event_sequence=event_index,
                ),
                observed_at_ms=event.start_us // 1000,
                status=status,
                capabilities=["identity_candidates"],
                cards=cards,
                calibration=calibration,
                analyzer=AnalyzerMetadata(name=analyzer_name, version=analyzer_version),
                diagnostics=diagnostics,
            )
        )
    return TableObservationData(observations=tuple(observations))


def _input_revision_ids(
    input_revision_ids: Sequence[str] | None,
    event_revision_id: str | None,
    visible_card_revision_id: str | None,
    visual_identity_revision_id: str | None,
) -> tuple[str, str, str]:
    explicit = (event_revision_id, visible_card_revision_id, visual_identity_revision_id)
    if input_revision_ids is not None and any(value is not None for value in explicit):
        raise ObservationAssemblyError("use input_revision_ids or named revision IDs, not both")
    values = tuple(input_revision_ids) if input_revision_ids is not None else explicit
    if len(values) != 3 or any(not isinstance(value, str) or not value for value in values):
        raise ObservationAssemblyError(
            "assembly needs ordered event, visible-card, and identity revision IDs"
        )
    if len(set(values)) != 3:
        raise ObservationAssemblyError("assembly input revision IDs must be unique")
    return values  # type: ignore[return-value]


def _identity_candidates(candidates: Sequence[Any]) -> list[IdentityCandidate]:
    if not candidates:
        return []
    if any(
        candidate.score is None or candidate.score_meaning != "probability"
        for candidate in candidates
    ):
        return []
    try:
        return [
            IdentityCandidate(card=candidate.identity, probability=float(candidate.score))
            for candidate in candidates
        ]
    except (TypeError, ValueError):
        return []


__all__ = [
    "ASSEMBLY_IMPLEMENTATION_NAME",
    "ASSEMBLY_IMPLEMENTATION_VERSION",
    "ObservationAssemblyError",
    "assemble_table_observations",
]
