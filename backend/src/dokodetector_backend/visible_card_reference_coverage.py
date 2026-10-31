"""Visible-card frame coverage parsing and key construction."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from doko_operations.pipeline_reference import ReferenceDraftItem
from table_evidence_analyzer.pipeline_data import (
    PipelineDataError,
    VisibleCardFrameIdentity,
)

from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceInputError,
    identifier,
)


def frame_coverage_entries(raw_frames: list[Any]) -> list[dict[str, Any]]:
    """Validate and normalize declared visible-card frame coverage."""
    normalized: list[dict[str, Any]] = []
    for index, raw_frame in enumerate(raw_frames):
        if not isinstance(raw_frame, Mapping):
            raise PipelineReferenceInputError(f"coverage.frames[{index}] must be an object")
        if set(raw_frame) not in (
            {"frame_identity", "decision"},
            {"item_id", "frame_identity", "decision"},
        ):
            raise PipelineReferenceInputError(
                f"coverage.frames[{index}] must contain frame_identity and decision"
            )
        frame_identity = raw_frame["frame_identity"]
        if frame_identity is None:
            if "item_id" not in raw_frame:
                raise PipelineReferenceInputError(
                    f"coverage.frames[{index}] needs item_id when frame_identity is absent"
                )
            normalized_frame = None
        else:
            try:
                normalized_frame = VisibleCardFrameIdentity.from_mapping(
                    frame_identity
                ).to_mapping()
            except (PipelineDataError, TypeError, ValueError) as error:
                raise PipelineReferenceInputError(
                    f"coverage.frames[{index}].frame_identity is invalid"
                ) from error
        decision = raw_frame["decision"]
        if decision not in {
            "cards",
            "ignored",
            "cards_and_ignored",
            "piles",
            "cards_and_piles",
            "piles_and_ignored",
            "cards_piles_and_ignored",
            "empty",
            "unusable",
        }:
            raise PipelineReferenceInputError(
                "coverage.frames[{}].decision must declare cards, piles, ignored, or a "
                "supported combination".format(index)
            )
        entry = {"frame_identity": normalized_frame, "decision": decision}
        if "item_id" in raw_frame:
            entry["item_id"] = identifier(raw_frame["item_id"], f"coverage.frames[{index}].item_id")
        normalized.append(entry)
    if len({frame_coverage_key(entry) for entry in normalized}) != len(normalized):
        raise PipelineReferenceInputError("coverage.frames must contain unique frames")
    return normalized


def frame_coverage_key(entry: Mapping[str, Any]) -> str:
    """Return the lookup key for one normalized coverage entry."""
    if entry.get("frame_identity") is None:
        return f"item:{entry.get('item_id')}"
    return json.dumps(entry["frame_identity"], sort_keys=True, separators=(",", ":"))


def item_frame_key(item: ReferenceDraftItem) -> str:
    """Return the coverage lookup key for one reference item."""
    frame = item.item.get("frame_identity")
    if frame is None:
        return f"item:{item.item_id}"
    return json.dumps(frame, sort_keys=True, separators=(",", ":"))
