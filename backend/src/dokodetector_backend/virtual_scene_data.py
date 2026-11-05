"""Unified virtual scene content and explicit mappings from existing scene records.

The geometry envelope uses the existing card-plane geometry format. Its historical schema name
is not a review decision. Review and origin remain separate from this content.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from doko_operations.card_plane_geometry import ReviewedCardScene
from table_evidence_analyzer.card_scene_contract import CardSceneDraft
from table_evidence_analyzer.pipeline_data import (
    ProposedCardSceneData,
    VisibleCardFrameIdentity,
    VisibleCardIgnoreRegion,
    VisibleCardPileRegion,
)

SCHEMA = "virtual-scene-data/v1"


def _fields(value: Any, names: set[str], context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != names:
        raise ValueError(f"{context} has invalid fields")
    return value


def validate_virtual_scenes(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate content without calculating or storing derived visible regions."""
    data = _fields(value, {"schema_version", "frames"}, "virtual scene data")
    if data["schema_version"] != SCHEMA or not isinstance(data["frames"], list):
        raise ValueError("invalid virtual scene data")
    frames = []
    for raw in data["frames"]:
        frame = _fields(
            raw,
            {
                "frame_id",
                "frame_identity",
                "calibration",
                "scene",
                "pile_regions",
                "ignore_regions",
            },
            "frame",
        )
        frame_id = frame["frame_id"]
        if not isinstance(frame_id, str) or not frame_id.strip():
            raise ValueError("frame ID is required")
        identity = VisibleCardFrameIdentity.from_mapping(frame["frame_identity"])
        calibration = _fields(frame["calibration"], {"revision_id", "digest"}, "calibration")
        cal_id, digest = calibration["revision_id"], calibration["digest"]
        if (
            not isinstance(cal_id, str)
            or not cal_id.strip()
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("calibration needs an exact revision and SHA-256 digest")
        scene = None if frame["scene"] is None else ReviewedCardScene.from_mapping(frame["scene"])
        if scene is not None and (
            scene.source_frame_id != frame_id
            or scene.source_frame_width != identity.width
            or scene.source_frame_height != identity.height
            or scene.calibration_revision_id != cal_id
            or scene.calibration_digest != digest
        ):
            raise ValueError("scene does not match frame or calibration")
        if not isinstance(frame["pile_regions"], list) or not isinstance(
            frame["ignore_regions"], list
        ):
            raise ValueError("regions must be lists")
        piles = [
            VisibleCardPileRegion.from_mapping(item).to_mapping() for item in frame["pile_regions"]
        ]
        ignores = [
            VisibleCardIgnoreRegion.from_mapping(item).to_mapping()
            for item in frame["ignore_regions"]
        ]
        ids = [x["pile_id"] for x in piles] + [x["region_id"] for x in ignores]
        if scene is not None:
            ids.extend(p.card_id for p in scene.poses)
        if len(ids) != len(set(ids)):
            raise ValueError("card and region IDs must be distinct")
        frames.append(
            {
                "frame_id": frame_id,
                "frame_identity": identity.to_mapping(),
                "calibration": dict(calibration),
                "scene": None if scene is None else scene.to_mapping(),
                "pile_regions": piles,
                "ignore_regions": ignores,
            }
        )
    if len({f["frame_id"] for f in frames}) != len(frames):
        raise ValueError("frame IDs must be unique")
    return {"schema_version": SCHEMA, "frames": frames}


def from_proposed(data: ProposedCardSceneData) -> dict[str, Any]:
    """Map supported and explicit empty proposal frames; refuse missing evidence."""
    if data.calibration_revision_id is None or data.calibration_digest is None:
        raise ValueError("proposal has no exact calibration")
    frames = []
    for frame in data.frames:
        if frame.source_identity is None or frame.status == "unsupported":
            raise ValueError("proposal frame lacks exact usable evidence")
        frames.append(
            {
                "frame_id": frame.frame_id,
                "frame_identity": frame.source_identity.to_mapping(),
                "calibration": {
                    "revision_id": data.calibration_revision_id,
                    "digest": data.calibration_digest,
                },
                "scene": None if frame.proposal is None else frame.proposal.initialized_scene,
                "pile_regions": [p.to_mapping() for p in frame.pile_regions],
                "ignore_regions": [],
            }
        )
    return {
        "content": validate_virtual_scenes({"schema_version": SCHEMA, "frames": frames}),
        "source_proposal": data.to_mapping(),
    }


def from_draft(
    draft: CardSceneDraft,
    frame_identity: Mapping[str, Any],
    *,
    scene: Mapping[str, Any] | None = None,
    pile_regions: list[dict[str, Any]] | None = None,
    ignore_regions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map a draft; return old review facts separately without inventing reviewers.

    Mixed pending and resolved cards need an explicitly supplied full scene. Its poses and
    relative orders must agree with each applicable old scene. Rejected cards are excluded.
    """
    proposal = draft.proposal
    if proposal.status != "supported" or proposal.initialized_scene is None:
        raise ValueError("draft has no supported proposal geometry")
    pending = {s.card_id for s in draft.card_states if s.state == "pending"}
    resolved = {s.card_id for s in draft.card_states if s.state in {"accepted", "adjusted"}}
    proposed = ReviewedCardScene.from_mapping(proposal.initialized_scene)
    reviewed = (
        None if draft.reviewed is None else ReviewedCardScene.from_mapping(draft.reviewed.scene)
    )
    identity = VisibleCardFrameIdentity.from_mapping(frame_identity)
    for old in (proposed, reviewed):
        if old is not None and (
            old.source_frame_id != proposal.source_frame_id
            or old.source_frame_width != identity.width
            or old.source_frame_height != identity.height
            or old.calibration_revision_id != proposal.calibration_revision_id
            or old.calibration_digest != proposal.calibration_digest
        ):
            raise ValueError("draft geometry does not match frame or calibration")
    if scene is None:
        if pending and resolved:
            raise ValueError("mixed draft requires an explicit complete scene")
        selected = proposed if pending else reviewed
        if pending and set(proposed.stacking_order.card_ids) != pending:
            raise ValueError("partial proposal requires an explicit complete scene")
    else:
        selected = ReviewedCardScene.from_mapping(scene)
    expected = pending | resolved
    if (selected is None) != (not expected):
        raise ValueError("complete scene does not match retained cards")
    if selected is not None:
        poses = {p.card_id: p.to_mapping() for p in selected.poses}
        if set(poses) != expected:
            raise ValueError("complete scene does not match retained cards")
        for old, ids in ((proposed, pending), (reviewed, resolved)):
            if not ids:
                continue
            if old is None:
                raise ValueError("resolved geometry is missing")
            old_poses = {p.card_id: p.to_mapping() for p in old.poses}
            if any(poses[i] != old_poses.get(i) for i in ids):
                raise ValueError("complete scene changes retained poses")
            if [i for i in selected.stacking_order.card_ids if i in ids] != [
                i for i in old.stacking_order.card_ids if i in ids
            ]:
                raise ValueError("complete scene changes retained stacking order")
    content = validate_virtual_scenes(
        {
            "schema_version": SCHEMA,
            "frames": [
                {
                    "frame_id": proposal.source_frame_id,
                    "frame_identity": dict(frame_identity),
                    "calibration": {
                        "revision_id": proposal.calibration_revision_id,
                        "digest": proposal.calibration_digest,
                    },
                    "scene": None if selected is None else selected.to_mapping(),
                    "pile_regions": pile_regions or [],
                    "ignore_regions": ignore_regions or [],
                }
            ],
        }
    )
    if content["frames"][0]["frame_identity"]["image_sha256"] != proposal.source_frame_digest:
        raise ValueError("draft frame identity does not match proposal")
    return {
        "content": content,
        "source_draft": draft.to_mapping(),
        "legacy_review": {
            "card_states": [s.to_mapping() for s in draft.card_states],
            "completion": draft.completion.to_mapping(),
            "reviewed": None if draft.reviewed is None else draft.reviewed.to_mapping(),
            "reviewer": None,
        },
    }
