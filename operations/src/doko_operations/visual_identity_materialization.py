"""Materialize reviewed visual-identity crops from exact maintained references."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from table_evidence_analyzer.cards import CARD_IDENTITIES
from table_evidence_analyzer.local_identity import FACE_DOWN_TARGET

from .derived_view import (
    ResolvedFrame,
    ReviewedVisibleRegionGeometry,
    _geometry_mask,
    parse_geometry,
    resolve_visible_region_crop,
)
from .pipeline_data import VISIBLE_CARD_DATA_SCHEMA_VERSION, VISUAL_IDENTITY_DATA_SCHEMA_VERSION

SCHEMA = "reviewed-visual-identity-materialization/v1"
TARGETS = frozenset((*CARD_IDENTITIES, FACE_DOWN_TARGET))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject(reason: str) -> dict[str, Any]:
    return {"reason": reason}


def materialize_reviewed_visual_identity_crops(
    recordings: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    frame_resolver: Callable[[Mapping[str, Any]], ResolvedFrame],
) -> dict[str, Any]:
    """Write exact native crops, visible-support masks, targets, and a deterministic report.

    Each recording binds one completed visible-card and one completed visual-identity revision.
    The resolver receives the exact frame identity recorded by those references.
    """

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    crops_dir = root / "crops"
    masks_dir = root / "masks"
    crops_dir.mkdir(exist_ok=True)
    masks_dir.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen_samples: set[tuple[str, str]] = set()
    frame_cache: dict[bytes, ResolvedFrame] = {}

    for recording in sorted(recordings, key=lambda item: str(item.get("recording_id", ""))):
        recording_id = recording.get("recording_id")
        group = recording.get("source_lineage_group")
        visible_revision = recording.get("visible_card_revision")
        identity_revision = recording.get("visual_identity_revision")
        if not isinstance(recording_id, str) or not recording_id:
            exclusions.append({"recording_id": recording_id, **_reject("invalid_recording_id")})
            continue
        if not isinstance(group, Mapping) or not group:
            exclusions.append({"recording_id": recording_id, **_reject("missing_source_group")})
            continue
        if not isinstance(visible_revision, Mapping) or not isinstance(identity_revision, Mapping):
            exclusions.append({"recording_id": recording_id, **_reject("missing_reference")})
            continue
        visible_id, identity_id = (
            visible_revision.get("revision_id"),
            identity_revision.get("revision_id"),
        )
        visible_digest, identity_digest = (
            visible_revision.get("content_digest"),
            identity_revision.get("content_digest"),
        )
        visible_content, identity_content = (
            visible_revision.get("content"),
            identity_revision.get("content"),
        )
        if not all(isinstance(value, str) and value for value in (visible_id, identity_id)):
            exclusions.append({"recording_id": recording_id, **_reject("invalid_revision_id")})
            continue
        if not isinstance(visible_content, Mapping) or not isinstance(identity_content, Mapping):
            exclusions.append(
                {"recording_id": recording_id, **_reject("invalid_reference_content")}
            )
            continue
        if visible_content.get("schema_version") != VISIBLE_CARD_DATA_SCHEMA_VERSION:
            exclusions.append(
                {"recording_id": recording_id, **_reject("unsupported_visible_card_schema")}
            )
            continue
        if identity_content.get("schema_version") != VISUAL_IDENTITY_DATA_SCHEMA_VERSION:
            exclusions.append(
                {
                    "recording_id": recording_id,
                    **_reject("unsupported_visual_identity_schema"),
                }
            )
            continue
        if visible_digest != _sha256(_canonical(visible_content)) or identity_digest != _sha256(
            _canonical(identity_content)
        ):
            exclusions.append({"recording_id": recording_id, **_reject("revision_digest_mismatch")})
            continue
        visible_outcomes = visible_content.get("outcomes")
        identity_outcomes = identity_content.get("outcomes")
        if not isinstance(visible_outcomes, list) or not isinstance(identity_outcomes, list):
            exclusions.append(
                {"recording_id": recording_id, **_reject("invalid_reference_content")}
            )
            continue
        visible_cards: dict[str, dict[str, Any]] = {}
        pile_members: set[str] = set()
        for outcome in visible_outcomes:
            if not isinstance(outcome, Mapping) or outcome.get("status") != "detected":
                continue
            for pile in outcome.get("pile_regions", []):
                if not isinstance(pile, Mapping):
                    continue
                for member in pile.get("grouped_candidates", []):
                    if isinstance(member, Mapping) and isinstance(member.get("card_id"), str):
                        pile_members.add(member["card_id"])
                for member in pile.get("grouped_card_states", []):
                    if isinstance(member, Mapping) and isinstance(member.get("card_id"), str):
                        pile_members.add(member["card_id"])
            for candidate in outcome.get("candidates", []):
                if isinstance(candidate, Mapping) and isinstance(candidate.get("card_id"), str):
                    visible_cards[candidate["card_id"]] = {
                        "frame_identity": outcome.get("frame_identity"),
                        "geometry": candidate.get("geometry"),
                        "side": candidate.get("side", "unknown"),
                    }
        identity_by_card = {
            item.get("card_id"): item
            for item in identity_outcomes
            if isinstance(item, Mapping) and isinstance(item.get("card_id"), str)
        }
        for card_id, visible in sorted(visible_cards.items()):
            identity = identity_by_card.get(card_id)
            reason: str | None = None
            if card_id in pile_members:
                reason = "pile_member"
            elif identity is None:
                reason = "missing_identity_outcome"
            elif identity.get("frame_identity") != visible["frame_identity"]:
                reason = "wrong_frame"
            elif identity.get("geometry") != visible["geometry"]:
                reason = "stale_geometry"
            elif identity.get("status") in {"unusable", "failed"}:
                reason = "unreadable_evidence"
            elif identity.get("status") not in {"classified", "face_down"}:
                reason = "not_a_positive_review"
            elif identity.get("status") == "face_down" and visible.get("side") != "face_down":
                reason = "side_not_reviewed_back"
            elif identity.get("status") == "classified" and visible.get("side") != "face_up":
                reason = "side_not_reviewed_face"
            provenance = (
                identity.get("annotation_provenance") if isinstance(identity, Mapping) else None
            )
            if reason is None and (
                not isinstance(provenance, Mapping) or identity.get("classifier") is not None
            ):
                reason = "not_human_reviewed"
            if reason is None and (
                provenance.get("visible_card_revision_id") != visible_id
                or provenance.get("visible_card_revision_digest") != visible_digest
                or provenance.get("visual_identity_revision_id", identity_id) != identity_id
                or provenance.get("card_id") != card_id
                or provenance.get("frame_identity") != visible["frame_identity"]
                or provenance.get("geometry_digest") != _sha256(_canonical(visible["geometry"]))
            ):
                reason = "annotation_lineage_mismatch"
            crop_identity = identity.get("crop_identity") if isinstance(identity, Mapping) else None
            if reason is None and (
                not isinstance(crop_identity, Mapping)
                or crop_identity.get("status") != "usable"
                or crop_identity.get("crop_policy") != "oracle_visible_region"
                or crop_identity.get("frame_identity") != visible["frame_identity"]
                or crop_identity.get("geometry") != visible["geometry"]
            ):
                reason = "unavailable_or_invalid_crop"
            if reason is not None:
                exclusions.append(
                    {"recording_id": recording_id, "card_id": card_id, "reason": reason}
                )
                continue
            status = identity["status"]
            candidates = identity.get("candidates", [])
            target = (
                FACE_DOWN_TARGET
                if status == "face_down"
                else (
                    candidates[0].get("identity")
                    if isinstance(candidates, list)
                    and candidates
                    and isinstance(candidates[0], Mapping)
                    else None
                )
            )
            if target not in TARGETS:
                exclusions.append(
                    {"recording_id": recording_id, "card_id": card_id, "reason": "invalid_target"}
                )
                continue
            sample = (recording_id, card_id)
            if sample in seen_samples:
                exclusions.append(
                    {"recording_id": recording_id, "card_id": card_id, "reason": "duplicate_card"}
                )
                continue
            seen_samples.add(sample)
            frame_identity = visible["frame_identity"]
            cache_key = _canonical(frame_identity)
            try:
                frame = frame_cache.get(cache_key)
                if frame is None:
                    frame = frame_resolver(frame_identity)
                    if frame.identity_mapping() != frame_identity:
                        raise ValueError("resolved frame identity does not match reference")
                    frame_cache[cache_key] = frame
                geometry = parse_geometry(visible["geometry"])
                if not isinstance(geometry, ReviewedVisibleRegionGeometry):
                    raise ValueError("positive annotation needs reviewed visible-region geometry")
                crop = resolve_visible_region_crop(
                    frame,
                    geometry,
                    crop_policy="oracle_visible_region",
                    output_encoding="ppm",
                )
                if crop.status != "usable" or crop.image_bytes is None or crop.pixel_bounds is None:
                    raise ValueError("reviewed crop is unusable")
                if crop_identity.get("image_sha256") != _sha256(crop.image_bytes):
                    raise ValueError("crop bytes do not match the reviewed crop receipt")
                mask = _geometry_mask(
                    geometry,
                    width=frame.width,
                    height=frame.height,
                    bounds=crop.pixel_bounds,
                )
                key = _sha256(_canonical([recording_id, card_id]))
                crop_name, mask_name = f"{key}.ppm", f"{key}.pgm"
                (crops_dir / crop_name).write_bytes(crop.image_bytes)
                mask.save(masks_dir / mask_name, format="PPM")
                mask_bytes = (masks_dir / mask_name).read_bytes()
            except (OSError, ValueError, TypeError) as error:
                exclusions.append(
                    {
                        "recording_id": recording_id,
                        "card_id": card_id,
                        "reason": "crop_materialization_failed",
                        "detail": str(error),
                    }
                )
                continue
            rows.append(
                {
                    "sample_id": f"{recording_id}:{card_id}",
                    "recording_id": recording_id,
                    "source_lineage_group": dict(sorted(group.items())),
                    "visible_card_revision_id": visible_id,
                    "visible_card_revision_digest": visible_digest,
                    "visual_identity_revision_id": identity_id,
                    "visual_identity_revision_digest": identity_digest,
                    "frame_identity": dict(frame_identity),
                    "card_id": card_id,
                    "target": target,
                    "back_design_id": visible.get("back_design_id")
                    if target == FACE_DOWN_TARGET
                    else None,
                    "crop_path": f"crops/{crop_name}",
                    "crop_sha256": _sha256(crop.image_bytes),
                    "mask_path": f"masks/{mask_name}",
                    "mask_sha256": _sha256(mask_bytes),
                    "crop_policy": "oracle_visible_region",
                }
            )
        for card_id in sorted(set(identity_by_card) - set(visible_cards)):
            reason = "pile_member" if card_id in pile_members else "no_matching_visible_card"
            exclusions.append(
                {
                    "recording_id": recording_id,
                    "card_id": card_id,
                    "reason": reason,
                }
            )

    rows.sort(key=lambda item: item["sample_id"])
    exclusions.sort(
        key=lambda item: (str(item.get("recording_id")), str(item.get("card_id")), item["reason"])
    )
    class_counts = Counter(row["target"] for row in rows)
    class_recordings: dict[str, set[str]] = defaultdict(set)
    back_designs: dict[str, set[str]] = defaultdict(set)
    unknown_back_design_recordings: set[str] = set()
    digest_samples: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        class_recordings[row["target"]].add(row["recording_id"])
        if row["target"] == FACE_DOWN_TARGET:
            design_id = row.get("back_design_id")
            if isinstance(design_id, str) and design_id:
                back_designs[design_id].add(row["recording_id"])
            else:
                unknown_back_design_recordings.add(row["recording_id"])
        digest_samples[row["crop_sha256"]].append(row["sample_id"])
    report = {
        "schema_version": SCHEMA,
        "state": "completed",
        "target_classes": sorted(TARGETS),
        "sample_count": len(rows),
        "class_support": {
            target: {
                "sample_count": class_counts[target],
                "recording_count": len(class_recordings[target]),
                "recording_ids": sorted(class_recordings[target]),
            }
            for target in sorted(TARGETS)
        },
        "back_design_support": {
            design: {"recording_count": len(ids), "recording_ids": sorted(ids)}
            for design, ids in sorted(back_designs.items())
        },
        "back_design_unspecified_recordings": sorted(unknown_back_design_recordings),
        "back_design_metadata_status": "not_provided",
        "duplicate_crop_groups": [
            sorted(samples) for samples in digest_samples.values() if len(samples) > 1
        ],
        "exclusion_counts": dict(sorted(Counter(item["reason"] for item in exclusions).items())),
        "exclusions": exclusions,
        "samples": rows,
    }
    report["manifest_digest"] = _sha256(_canonical(report))
    (root / "manifest.json").write_bytes(_canonical(report) + b"\n")
    return report


__all__ = ["SCHEMA", "TARGETS", "materialize_reviewed_visual_identity_crops"]
