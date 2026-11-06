"""Frozen request construction for automated pipeline jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StageDefinition:
    """One stage request and its input revisions in a declared sequence."""

    name: str
    request: Mapping[str, Any]
    input_revision_ids: tuple[str, ...]


class PipelineStageRequestBuilder:
    """Build one child job request from the frozen stage inputs."""

    @staticmethod
    def _request_payload(
        stage: str,
        run_id: str,
        request: Mapping[str, Any],
        input_revision_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        values = dict(request)
        values["run_id"] = run_id
        if stage == "event_proposals":
            values.setdefault("input_revision_ids", [])
            return {"request": values}
        if stage == "visible_card_and_pile_proposals":
            if len(input_revision_ids) != 1:
                raise ValueError("Visible-card detection needs one event revision.")
            values["event_revision_id"] = input_revision_ids[0]
            return {"request": values}
        if stage == "card_scene_and_calibration":
            if len(input_revision_ids) != 1:
                raise ValueError("Card-scene proposals need one visible-card revision.")
            return {
                "run_id": run_id,
                "visible_card_revision_id": input_revision_ids[0],
                "configuration": values.get("configuration", {}),
            }
        if stage == "visual_identity_proposals":
            if len(input_revision_ids) != 1:
                raise ValueError("Identity classification needs one proposed card-scene revision.")
            values["card_scene_proposal_revision_id"] = input_revision_ids[0]
            values["crop_input_kind"] = "proposed_virtual_cards"
            return {"request": values}
        if stage == "table_observations":
            if len(input_revision_ids) != 3:
                raise ValueError(
                    "Observation assembly needs event, visible-card, and identity revisions."
                )
            values["input_revision_ids"] = list(input_revision_ids)
            return {"request": values}
        raise ValueError(f"Unsupported retained pipeline stage: {stage}")


def frozen_pilot_stage_plan(
    requests: Mapping[str, Mapping[str, Any]],
) -> tuple[StageDefinition, ...]:
    """Build the five retained processor stages in the M0 pilot order.

    Request settings come from the frozen pilot contract. Revision inputs use stage
    references so the parent job forwards the actual outputs from this run.
    Reconstruction is explicit. Use a skip object for staged sequences without game
    context; real rounds need their frozen session and round context.
    """

    sequence = (
        ("event_proposals", ()),
        ("visible_card_and_pile_proposals", ("@stage:event_proposals",)),
        ("card_scene_and_calibration", ("@stage:visible_card_and_pile_proposals",)),
        ("visual_identity_proposals", ("@stage:card_scene_and_calibration",)),
        (
            "table_observations",
            (
                "@stage:event_proposals",
                "@stage:visible_card_and_pile_proposals",
                "@stage:visual_identity_proposals",
            ),
        ),
    )
    missing = [name for name, _ in sequence if name not in requests]
    if "reconstruction" not in requests:
        missing.append("reconstruction (explicit context or skip required)")
    if missing:
        raise ValueError("Missing frozen request settings for: " + ", ".join(missing))
    plan = tuple(StageDefinition(name, requests[name], inputs) for name, inputs in sequence)
    plan += (
        StageDefinition(
            "reconstruction",
            requests["reconstruction"],
            ("@stage:table_observations",),
        ),
    )
    return plan


__all__ = [
    "PipelineStageRequestBuilder",
    "StageDefinition",
    "frozen_pilot_stage_plan",
]
