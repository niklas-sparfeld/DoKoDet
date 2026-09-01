"""Freeze reviewed visible-card data, partitions, and crop-policy contracts.

This module does not select labels from model metrics. It consumes a completed v2 review queue
and an explicit source-lineage partition manifest. The output is immutable and contains the
teacher proposals, reviewed labels, challenge frames, coverage report, and the three crop
conditions required by plan 0038.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, UnidentifiedImageError

from .visible_card_review import (
    VISIBLE_CARD_FAILURE_TAGS,
    VISIBLE_CARD_REVIEW_SCHEMA,
    ReviewedVisibleCard,
    VisibleCardReviewContractError,
)
from .visible_card_review_workflow import (
    VisibleCardReviewItem,
    VisibleCardReviewWorkflowError,
    VisibleCardSourceLineage,
    VisibleCardTeacherLineage,
    load_visible_card_review_queue,
    validate_completed_visible_card_review_queue,
)

VISIBLE_CARD_REVIEW_WORDING_SCHEMA = "visible-card-review-wording/v1"
VISIBLE_CARD_REVIEW_WORDING_VERSION = "visible-card-review-wording/v1"
VISIBLE_CARD_REVIEWED_MANIFEST_SCHEMA = "visible-card-reviewed-manifest/v1"
VISIBLE_CARD_TEACHER_SET_SCHEMA = "visible-card-teacher-set/v1"
VISIBLE_CARD_COVERAGE_SCHEMA = "visible-card-coverage/v1"
VISIBLE_CARD_PARTITION_SCHEMA = "visible-card-review-partition/v1"
VISIBLE_CARD_CROP_POLICY_SCHEMA = "visible-card-crop-policy/v1"
VISIBLE_CARD_FREEZE_SCHEMA = "visible-card-freeze/v1"
VISIBLE_CARD_CROP_POLICY_VERSION = "visible-card-crop-policy/v1"
VISIBLE_CARD_CROP_POLICIES = (
    "raw_rectangular",
    "oracle_visible_region",
    "conservative_box_only",
)
NEUTRAL_FILL_RGB = (128, 128, 128)
SEED_FRAME_TARGET = 100
MINIMUM_SEED_SOURCE_GROUPS = 5
MAX_SEED_SOURCE_GROUP_SHARE = 0.40

VISIBLE_CARD_REVIEW_WORDING = """Review the exact-event frame at target offset 0 ms.

First decide if the frame is GOOD or BAD for visible-card localization. A BAD frame is not an
empty frame. Mark empty_frame=true only when review confirms that no physical card is visible.

For a GOOD frame, review every separately visible physical card. Trace only the pixels visible in
the source frame. Do not include hidden card pixels, an occluding card, a human hand, or the table.
Use more than one polygon when an occluder splits one card's visible pixels. Do not infer a hidden
part of an occluded card. Set the side to face_up, face_down, or unknown. Mark identity usability
and one reason. A card can be a valid localization label when its identity crop is unusable.

Use accepted only when the teacher geometry is correct. Use reshaped when the visible geometry is
corrected, added when the teacher missed a visible card, and removed when the teacher proposed a
false card. Derive the detector box from the reviewed visible region. Do not maintain a separate
inferred full-card box."""


class VisibleCardReviewFreezeError(VisibleCardReviewWorkflowError, ValueError):
    """Raised when reviewed visible-card data cannot be frozen safely."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise VisibleCardReviewFreezeError(f"could not read artifact: {path}") from error


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisibleCardReviewFreezeError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise VisibleCardReviewFreezeError(f"{context} must be a JSON object: {path}")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisibleCardReviewFreezeError(f"{field} must be a non-empty string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-/"
        for character in result
    ):
        raise VisibleCardReviewFreezeError(f"{field} contains unsupported characters")
    return result


def _digest_value(value: Any, field: str) -> str:
    result = _text(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise VisibleCardReviewFreezeError(f"{field} must be a lower-case SHA-256 digest")
    return result


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise VisibleCardReviewFreezeError(f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise VisibleCardReviewFreezeError(f"{field} must not contain duplicate values")
    return tuple(value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _policy_payload() -> dict[str, Any]:
    return {
        "schema_version": VISIBLE_CARD_CROP_POLICY_SCHEMA,
        "version": VISIBLE_CARD_CROP_POLICY_VERSION,
        "neutral_fill_rgb": list(NEUTRAL_FILL_RGB),
        "policies": [
            {
                "policy_id": "raw_rectangular",
                "geometry": "derived_box",
                "operation": "crop_source_image_to_derived_box",
                "outside_visible_region": "preserve_source_pixels",
                "rejection": None,
            },
            {
                "policy_id": "oracle_visible_region",
                "geometry": "derived_box",
                "operation": "crop_to_derived_box_and_mask_outside_visible_region",
                "outside_visible_region": "replace_with_neutral_fill_rgb",
                "rejection": None,
            },
            {
                "policy_id": "conservative_box_only",
                "geometry": "derived_box",
                "operation": "crop_source_image_to_derived_box",
                "outside_visible_region": "preserve_source_pixels",
                "rejection": {
                    "identity_usable": True,
                    "failure_tags": [],
                },
            },
        ],
    }


def frozen_visible_card_crop_policy() -> dict[str, Any]:
    """Return the exact, metric-independent crop policy that M2 freezes."""

    payload = _policy_payload()
    return {**payload, "policy_digest": _digest(payload)}


def load_frozen_visible_card_crop_policy(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Load and reject any crop policy that differs from the frozen contract."""

    policy = _read_json(Path(value), "crop policy") if isinstance(value, (str, Path)) else value
    if not isinstance(policy, dict):
        raise VisibleCardReviewFreezeError("crop policy must be a JSON object")
    expected = frozen_visible_card_crop_policy()
    if policy != expected:
        raise VisibleCardReviewFreezeError("crop policy is not the frozen M2 policy")
    return policy


def _review_policy(
    pilot: dict[str, Any], *, pilot_digest: str, selected_request_version: str
) -> dict[str, Any]:
    wording = {
        "schema_version": VISIBLE_CARD_REVIEW_WORDING_SCHEMA,
        "version": VISIBLE_CARD_REVIEW_WORDING_VERSION,
        "instructions": VISIBLE_CARD_REVIEW_WORDING,
        "instructions_sha256": hashlib.sha256(VISIBLE_CARD_REVIEW_WORDING.encode()).hexdigest(),
    }
    payload = {
        "schema_version": "visible-card-review-policy/v1",
        "review_wording": wording,
        "selected_teacher_request_version": selected_request_version,
        "pilot": {
            "run_id": _identifier(pilot["run_id"], "pilot.run_id"),
            "frame_count": pilot["frame_count"],
            "report_sha256": pilot_digest,
        },
    }
    return {**payload, "policy_digest": _digest(payload)}


def _load_pilot_report(path: Path) -> tuple[dict[str, Any], str, str]:
    pilot = _read_json(path, "visible-card prompt pilot report")
    if pilot.get("schema_version") != "visible-card-prompt-pilot/v1":
        raise VisibleCardReviewFreezeError("unsupported visible-card prompt pilot schema")
    if pilot.get("frame_count") != 20:
        raise VisibleCardReviewFreezeError("M2 requires a 20-frame prompt pilot")
    selection = pilot.get("selection")
    if not isinstance(selection, dict):
        raise VisibleCardReviewFreezeError("prompt pilot selection is missing")
    selected = selection.get("selected_request_version")
    if selected not in {"visible-card-request/v1", "visible-card-request/v2"}:
        raise VisibleCardReviewFreezeError(
            "M2 requires a selected request version from the development pilot"
        )
    if selection.get("scope") != "development":
        raise VisibleCardReviewFreezeError("prompt pilot selection must use development frames")
    excluded = selection.get("excluded_partitions")
    if not isinstance(excluded, list) or not {
        "validation",
        "challenge",
        "test",
        "system_holdout",
    } <= set(excluded):
        raise VisibleCardReviewFreezeError("prompt pilot does not exclude evaluation partitions")
    frames = pilot.get("frames")
    if not isinstance(frames, list) or len(frames) != 20:
        raise VisibleCardReviewFreezeError("prompt pilot frame records are incomplete")
    if any(
        not isinstance(frame, dict) or frame.get("partition") != "development" for frame in frames
    ):
        raise VisibleCardReviewFreezeError("prompt pilot contains a non-development frame")
    request_versions = pilot.get("request_versions")
    if (
        not isinstance(request_versions, list)
        or not request_versions
        or any(not isinstance(item, dict) for item in request_versions)
    ):
        raise VisibleCardReviewFreezeError("prompt pilot request versions are missing")
    if selected not in {item.get("schema_version") for item in request_versions}:
        raise VisibleCardReviewFreezeError("selected request version is absent from pilot report")
    return pilot, _file_digest(path), selected


def load_visible_card_partition_manifest(path: str | Path) -> dict[str, Any]:
    """Load the explicit group-level partition input for a freeze."""

    value = _read_json(Path(path), "visible-card partition manifest")
    fields = {"schema_version", "partitions", "system_holdout_groups", "reason"}
    if set(value) != fields or value["schema_version"] != VISIBLE_CARD_PARTITION_SCHEMA:
        raise VisibleCardReviewFreezeError("partition manifest has unexpected fields")
    partitions = value["partitions"]
    if not isinstance(partitions, dict) or set(partitions) != {"train", "validation", "challenge"}:
        raise VisibleCardReviewFreezeError("partition manifest needs train, validation, challenge")
    parsed: dict[str, list[str]] = {}
    for name in ("train", "validation", "challenge"):
        values = list(_strings(partitions[name], f"partitions.{name}"))
        if not values:
            raise VisibleCardReviewFreezeError(f"partitions.{name} must not be empty")
        parsed[name] = values
    holdout = list(_strings(value["system_holdout_groups"], "system_holdout_groups"))
    all_items = sum(parsed.values(), [])
    if len(all_items) != len(set(all_items)):
        raise VisibleCardReviewFreezeError("partition item IDs must be unique")
    _text(value["reason"], "partition reason")
    return {
        "schema_version": VISIBLE_CARD_PARTITION_SCHEMA,
        "partitions": parsed,
        "system_holdout_groups": holdout,
        "reason": value["reason"],
    }


def _label_mapping(item: VisibleCardReviewItem, action: Any) -> dict[str, Any] | None:
    if action.reviewed_card is None:
        return None
    card = action.reviewed_card
    return {
        "label_id": f"{item.item_id}:{card.card_id}",
        "card": card.to_mapping(),
        "action": action.action,
        "proposal_index": action.proposal_index,
        "geometry_version": VISIBLE_CARD_REVIEW_SCHEMA,
        "source_frame_sha256": item.source.frame_sha256,
        "source_lineage_group": item.source.source_lineage_group,
        "teacher_request_digest": item.teacher.request_digest,
        "teacher_result_digest": item.teacher.result_digest,
        "review_id": item.review.review_id,
        "reviewer": item.review.reviewer,
        "reviewed_at_utc": item.review.completed_at_utc,
    }


def _frame_mapping(item: VisibleCardReviewItem, partition: str) -> dict[str, Any]:
    review = item.review
    labels = [
        label for action in review.actions if (label := _label_mapping(item, action)) is not None
    ]
    return {
        "frame_id": item.item_id,
        "partition": partition,
        "label_state": "reviewed_visible_region",
        "source": item.source.to_mapping(),
        "review": {
            "schema_version": VISIBLE_CARD_REVIEW_SCHEMA,
            "status": review.status,
            "decision": review.decision,
            "empty_frame": review.empty_frame,
            "failure_tags": list(review.failure_tags),
            "reviewer": review.reviewer,
            "review_id": review.review_id,
            "started_at_utc": review.started_at_utc,
            "updated_at_utc": review.updated_at_utc,
            "completed_at_utc": review.completed_at_utc,
        },
        "teacher": item.teacher.to_mapping(),
        "actions": [action.to_mapping() for action in review.actions],
        "labels": labels,
    }


def _coverage(
    items: tuple[VisibleCardReviewItem, ...], assignments: dict[str, str], holdout: set[str]
) -> dict[str, Any]:
    group_frames: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "frame_count": 0,
            "seed_frame_count": 0,
            "challenge_frame_count": 0,
            "failure_tags": {tag: 0 for tag in sorted(VISIBLE_CARD_FAILURE_TAGS)},
        }
    )
    tag_frames: dict[str, set[str]] = {tag: set() for tag in sorted(VISIBLE_CARD_FAILURE_TAGS)}
    tag_cards: dict[str, int] = {tag: 0 for tag in sorted(VISIBLE_CARD_FAILURE_TAGS)}
    seed_groups: dict[str, int] = defaultdict(int)
    for item in items:
        partition = assignments[item.item_id]
        group = item.source.source_lineage_group
        record = group_frames[group]
        record["frame_count"] += 1
        if partition in {"train", "validation"}:
            record["seed_frame_count"] += 1
            seed_groups[group] += 1
        else:
            record["challenge_frame_count"] += 1
        tags = set(item.review.failure_tags)
        for action in item.review.actions:
            if action.reviewed_card is not None:
                tags.update(action.reviewed_card.failure_tags)
                for tag in action.reviewed_card.failure_tags:
                    tag_cards[tag] += 1
        for tag in tags:
            tag_frames[tag].add(item.item_id)
            record["failure_tags"][tag] += 1
    seed_frame_count = sum(seed_groups.values())
    source_group_count = len(seed_groups)
    max_share = max(seed_groups.values(), default=0) / seed_frame_count if seed_frame_count else 0.0
    gaps: list[str] = []
    if seed_frame_count < SEED_FRAME_TARGET:
        gaps.append(f"usable seed frames: {seed_frame_count}/{SEED_FRAME_TARGET}")
    if source_group_count < MINIMUM_SEED_SOURCE_GROUPS:
        gaps.append(f"seed source groups: {source_group_count}/{MINIMUM_SEED_SOURCE_GROUPS}")
    if max_share > MAX_SEED_SOURCE_GROUP_SHARE:
        gaps.append(
            f"largest seed source group share: {max_share:.3f}>{MAX_SEED_SOURCE_GROUP_SHARE:.2f}"
        )
    return {
        "schema_version": VISIBLE_CARD_COVERAGE_SCHEMA,
        "reviewed_frame_count": len(items),
        "partition_counts": {
            name: sum(assignments[item.item_id] == name for item in items)
            for name in ("train", "validation", "challenge")
        },
        "seed": {
            "usable_frame_count": seed_frame_count,
            "source_group_count": source_group_count,
            "largest_source_group_share": round(max_share, 6),
            "target": {
                "usable_frame_count": SEED_FRAME_TARGET,
                "minimum_source_group_count": MINIMUM_SEED_SOURCE_GROUPS,
                "maximum_source_group_share": MAX_SEED_SOURCE_GROUP_SHARE,
            },
            "target_met": not gaps,
            "coverage_gap": gaps,
        },
        "by_source_lineage_group": {group: group_frames[group] for group in sorted(group_frames)},
        "by_failure_tag": {
            tag: {
                "frame_count": len(tag_frames[tag]),
                "card_count": tag_cards[tag],
            }
            for tag in sorted(VISIBLE_CARD_FAILURE_TAGS)
        },
        "system_holdout": {
            "groups": sorted(holdout),
            "frame_count": 0,
            "absent": True,
        },
    }


def _validate_source_partitions(
    items: tuple[VisibleCardReviewItem, ...],
    partitions: dict[str, list[str]],
    holdout: set[str],
) -> dict[str, str]:
    assignments = {item_id: name for name, item_ids in partitions.items() for item_id in item_ids}
    item_ids = {item.item_id for item in items}
    if set(assignments) != item_ids:
        missing = sorted(item_ids - set(assignments))
        extra = sorted(set(assignments) - item_ids)
        detail = f"missing {missing}" if missing else f"unknown {extra}"
        raise VisibleCardReviewFreezeError(f"partition manifest does not cover queue: {detail}")
    group_partitions: dict[str, str] = {}
    by_id = {item.item_id: item for item in items}
    for item_id, partition in assignments.items():
        item = by_id[item_id]
        group = item.source.source_lineage_group
        if group in holdout:
            raise VisibleCardReviewFreezeError(
                f"system holdout source-lineage group is present: {group}"
            )
        previous = group_partitions.get(group)
        if previous is not None and previous != partition:
            raise VisibleCardReviewFreezeError(
                f"source-lineage group crosses partitions: {group} ({previous}, {partition})"
            )
        group_partitions[group] = partition
        if partition in {"train", "validation"} and item.review.decision != "GOOD":
            raise VisibleCardReviewFreezeError(
                f"{partition} contains a frame that is not a GOOD review: {item_id}"
            )
        if partition in {"train", "validation"} and not item.review.actions:
            raise VisibleCardReviewFreezeError(
                f"{partition} frame has no reviewed labels: {item_id}"
            )
    return assignments


def _manifest(
    freeze_id: str,
    partition: Literal["train", "validation", "challenge"],
    frames: list[dict[str, Any]],
    *,
    queue_digest: str,
    partition_digest: str,
    review_policy: dict[str, Any],
    crop_policy: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema_version": VISIBLE_CARD_REVIEWED_MANIFEST_SCHEMA,
        "freeze_id": freeze_id,
        "partition": partition,
        "label_state": "reviewed_visible_region",
        "review_contract": VISIBLE_CARD_REVIEW_SCHEMA,
        "queue_digest": queue_digest,
        "partition_manifest_digest": partition_digest,
        "review_policy_digest": review_policy["policy_digest"],
        "crop_policy_digest": crop_policy["policy_digest"],
        "frames": sorted(frames, key=lambda frame: frame["frame_id"]),
    }
    return {**payload, "manifest_digest": _digest(payload)}


def _teacher_manifest(
    freeze_id: str,
    frames: list[dict[str, Any]],
    *,
    queue_digest: str,
    partition_digest: str,
    review_policy: dict[str, Any],
    crop_policy: dict[str, Any],
) -> dict[str, Any]:
    request_versions = sorted({frame["teacher"]["request"]["schema_version"] for frame in frames})
    payload = {
        "schema_version": VISIBLE_CARD_TEACHER_SET_SCHEMA,
        "freeze_id": freeze_id,
        "label_state": "immutable_teacher_proposals",
        "queue_digest": queue_digest,
        "partition_manifest_digest": partition_digest,
        "review_policy_digest": review_policy["policy_digest"],
        "crop_policy_digest": crop_policy["policy_digest"],
        "request_versions": request_versions,
        "frames": sorted(frames, key=lambda frame: frame["frame_id"]),
    }
    return {**payload, "manifest_digest": _digest(payload)}


def _validate_label(label: Any, frame: dict[str, Any]) -> None:
    if not isinstance(label, dict):
        raise VisibleCardReviewFreezeError("reviewed label must be an object")
    required = {
        "label_id",
        "card",
        "action",
        "proposal_index",
        "geometry_version",
        "source_frame_sha256",
        "source_lineage_group",
        "teacher_request_digest",
        "teacher_result_digest",
        "review_id",
        "reviewer",
        "reviewed_at_utc",
    }
    if set(label) != required:
        raise VisibleCardReviewFreezeError("reviewed label has incomplete provenance")
    try:
        card = ReviewedVisibleCard.from_mapping(label["card"])
    except (TypeError, ValueError, VisibleCardReviewContractError) as error:
        raise VisibleCardReviewFreezeError("reviewed label geometry is invalid") from error
    if (
        label["geometry_version"] != VISIBLE_CARD_REVIEW_SCHEMA
        or label["source_frame_sha256"] != frame["source"]["frame_sha256"]
        or label["source_lineage_group"] != frame["source"]["source_lineage_group"]
        or label["teacher_request_digest"] != frame["teacher"]["request_digest"]
        or label["teacher_result_digest"] != frame["teacher"]["result_digest"]
        or label["review_id"] != frame["review"]["review_id"]
        or label["reviewer"] != frame["review"]["reviewer"]
        or label["reviewed_at_utc"] != frame["review"]["completed_at_utc"]
        or card.card_id != label["card"]["card_id"]
    ):
        raise VisibleCardReviewFreezeError("reviewed label provenance does not match its frame")


def _validate_manifest(value: dict[str, Any], partition: str) -> dict[str, Any]:
    if value.get("schema_version") != VISIBLE_CARD_REVIEWED_MANIFEST_SCHEMA:
        raise VisibleCardReviewFreezeError("unsupported reviewed manifest schema")
    if value.get("partition") != partition:
        raise VisibleCardReviewFreezeError("reviewed manifest partition is inconsistent")
    if value.get("label_state") != "reviewed_visible_region":
        raise VisibleCardReviewFreezeError("reviewed manifest label state is invalid")
    if value.get("review_contract") != VISIBLE_CARD_REVIEW_SCHEMA:
        raise VisibleCardReviewFreezeError("reviewed manifest review contract is invalid")
    expected = _digest({key: item for key, item in value.items() if key != "manifest_digest"})
    if value.get("manifest_digest") != expected:
        raise VisibleCardReviewFreezeError("reviewed manifest digest is stale")
    frames = value.get("frames")
    if not isinstance(frames, list) or not frames:
        raise VisibleCardReviewFreezeError("reviewed manifest frames must not be empty")
    ids = [frame.get("frame_id") for frame in frames if isinstance(frame, dict)]
    if len(ids) != len(frames) or len(ids) != len(set(ids)):
        raise VisibleCardReviewFreezeError("reviewed manifest frame IDs must be unique")
    for frame in frames:
        if not isinstance(frame, dict) or frame.get("partition") != partition:
            raise VisibleCardReviewFreezeError("reviewed manifest frame partition is invalid")
        try:
            VisibleCardSourceLineage.from_mapping(frame["source"])
            VisibleCardTeacherLineage.from_mapping(frame["teacher"])
        except (KeyError, TypeError, ValueError, VisibleCardReviewWorkflowError) as error:
            raise VisibleCardReviewFreezeError(
                "reviewed manifest frame lineage is invalid"
            ) from error
        if frame.get("review", {}).get("status") != "reviewed":
            raise VisibleCardReviewFreezeError("reviewed manifest contains incomplete review")
        labels = frame.get("labels")
        if not isinstance(labels, list):
            raise VisibleCardReviewFreezeError("reviewed manifest labels must be a list")
        for label in labels:
            _validate_label(label, frame)
    return value


def _validate_teacher_manifest(value: dict[str, Any]) -> None:
    if value.get("schema_version") != VISIBLE_CARD_TEACHER_SET_SCHEMA:
        raise VisibleCardReviewFreezeError("unsupported teacher set schema")
    expected = _digest({key: item for key, item in value.items() if key != "manifest_digest"})
    if value.get("manifest_digest") != expected:
        raise VisibleCardReviewFreezeError("teacher set digest is stale")
    frames = value.get("frames")
    if not isinstance(frames, list) or not frames:
        raise VisibleCardReviewFreezeError("teacher set frames must not be empty")
    if any(not isinstance(frame, dict) for frame in frames):
        raise VisibleCardReviewFreezeError("teacher set frames are invalid")


def _validate_review_policy(value: Any, freeze: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise VisibleCardReviewFreezeError("visible-card review policy is missing")
    expected = _digest({key: item for key, item in value.items() if key != "policy_digest"})
    if value.get("policy_digest") != expected:
        raise VisibleCardReviewFreezeError("visible-card review policy digest is stale")
    if value.get("selected_teacher_request_version") != freeze.get(
        "selected_teacher_request_version"
    ):
        raise VisibleCardReviewFreezeError("review policy request selection differs from freeze")
    wording = value.get("review_wording")
    if not isinstance(wording, dict) or wording.get("instructions") != VISIBLE_CARD_REVIEW_WORDING:
        raise VisibleCardReviewFreezeError("review wording is not frozen")
    if (
        wording.get("instructions_sha256")
        != hashlib.sha256(VISIBLE_CARD_REVIEW_WORDING.encode()).hexdigest()
    ):
        raise VisibleCardReviewFreezeError("review wording digest is stale")


def freeze_visible_card_review_data(
    queue_path: str | Path,
    pilot_report_path: str | Path,
    partition_manifest_path: str | Path,
    output_dir: str | Path,
    *,
    freeze_id: str = "visible-card-review-freeze-v1",
) -> dict[str, Any]:
    """Write immutable reviewed seed, challenge, teacher, coverage, and crop artifacts."""

    freeze_id = _identifier(freeze_id, "freeze_id")
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise VisibleCardReviewFreezeError(f"freeze output already exists: {destination}")
    queue = validate_completed_visible_card_review_queue(load_visible_card_review_queue(queue_path))
    pilot, pilot_digest, selected_request_version = _load_pilot_report(Path(pilot_report_path))
    partition = load_visible_card_partition_manifest(partition_manifest_path)
    holdout = set(partition["system_holdout_groups"])
    assignments = _validate_source_partitions(queue.items, partition["partitions"], holdout)
    queue_digest = _digest(queue.to_mapping())
    partition_digest = _digest(partition)
    crop_policy = frozen_visible_card_crop_policy()
    review_policy = _review_policy(
        pilot,
        pilot_digest=pilot_digest,
        selected_request_version=selected_request_version,
    )
    frames = {item.item_id: _frame_mapping(item, assignments[item.item_id]) for item in queue.items}
    coverage = _coverage(queue.items, assignments, holdout)
    train = _manifest(
        freeze_id,
        "train",
        [frames[item_id] for item_id in partition["partitions"]["train"]],
        queue_digest=queue_digest,
        partition_digest=partition_digest,
        review_policy=review_policy,
        crop_policy=crop_policy,
    )
    validation = _manifest(
        freeze_id,
        "validation",
        [frames[item_id] for item_id in partition["partitions"]["validation"]],
        queue_digest=queue_digest,
        partition_digest=partition_digest,
        review_policy=review_policy,
        crop_policy=crop_policy,
    )
    challenge = _manifest(
        freeze_id,
        "challenge",
        [frames[item_id] for item_id in partition["partitions"]["challenge"]],
        queue_digest=queue_digest,
        partition_digest=partition_digest,
        review_policy=review_policy,
        crop_policy=crop_policy,
    )
    teacher = _teacher_manifest(
        freeze_id,
        [
            frames[item_id]
            for item_id in (
                *partition["partitions"]["train"],
                *partition["partitions"]["validation"],
            )
        ],
        queue_digest=queue_digest,
        partition_digest=partition_digest,
        review_policy=review_policy,
        crop_policy=crop_policy,
    )
    freeze_payload = {
        "schema_version": VISIBLE_CARD_FREEZE_SCHEMA,
        "freeze_id": freeze_id,
        "queue_path": str(Path(queue_path)),
        "queue_digest": queue_digest,
        "partition_manifest": partition,
        "partition_manifest_digest": partition_digest,
        "pilot_report_path": str(Path(pilot_report_path)),
        "pilot_report_sha256": pilot_digest,
        "selected_teacher_request_version": selected_request_version,
        "review_policy": review_policy,
        "crop_policy": crop_policy,
        "coverage": coverage,
        "artifact_digests": {
            "review_policy": _digest(review_policy),
            "crop_policy": _digest(crop_policy),
            "coverage": _digest(coverage),
        },
        "manifests": {
            "teacher": {"path": "teacher-manifest.json", "digest": teacher["manifest_digest"]},
            "train": {"path": "train-manifest.json", "digest": train["manifest_digest"]},
            "validation": {
                "path": "validation-manifest.json",
                "digest": validation["manifest_digest"],
            },
            "challenge": {
                "path": "challenge-manifest.json",
                "digest": challenge["manifest_digest"],
            },
        },
    }
    freeze = {**freeze_payload, "freeze_digest": _digest(freeze_payload)}
    if destination.exists():
        raise VisibleCardReviewFreezeError(f"freeze output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.", dir=destination.parent) as tmp:
        working = Path(tmp)
        _write_json(working / "review-policy.json", review_policy)
        _write_json(working / "crop-policy.json", crop_policy)
        _write_json(working / "coverage-report.json", coverage)
        _write_json(working / "teacher-manifest.json", teacher)
        _write_json(working / "train-manifest.json", train)
        _write_json(working / "validation-manifest.json", validation)
        _write_json(working / "challenge-manifest.json", challenge)
        _write_json(working / "freeze-manifest.json", freeze)
        working.replace(destination)
    return {
        "status": "completed",
        "output_dir": str(destination),
        "freeze_manifest": str(destination / "freeze-manifest.json"),
        "coverage_report": str(destination / "coverage-report.json"),
        "selected_teacher_request_version": selected_request_version,
        "seed_frame_count": coverage["seed"]["usable_frame_count"],
        "challenge_frame_count": coverage["partition_counts"]["challenge"],
        "seed_target_met": coverage["seed"]["target_met"],
        "freeze_digest": freeze["freeze_digest"],
    }


def load_frozen_visible_card_review_data(path: str | Path) -> dict[str, Any]:
    """Load and validate one immutable M2 freeze directory."""

    freeze_path = Path(path)
    if freeze_path.is_dir():
        freeze_path = freeze_path / "freeze-manifest.json"
    freeze = _read_json(freeze_path, "visible-card freeze manifest")
    if freeze.get("schema_version") != VISIBLE_CARD_FREEZE_SCHEMA:
        raise VisibleCardReviewFreezeError("unsupported visible-card freeze schema")
    expected = _digest({key: item for key, item in freeze.items() if key != "freeze_digest"})
    if freeze.get("freeze_digest") != expected:
        raise VisibleCardReviewFreezeError("visible-card freeze digest is stale")
    base = freeze_path.parent
    load_frozen_visible_card_crop_policy(freeze.get("crop_policy"))
    review_policy = freeze.get("review_policy")
    _validate_review_policy(review_policy, freeze)
    artifact_digests = freeze.get("artifact_digests")
    if not isinstance(artifact_digests, dict) or set(artifact_digests) != {
        "review_policy",
        "crop_policy",
        "coverage",
    }:
        raise VisibleCardReviewFreezeError("visible-card freeze artifact digests are incomplete")
    for name, filename, embedded in (
        ("review_policy", "review-policy.json", review_policy),
        ("crop_policy", "crop-policy.json", freeze["crop_policy"]),
        ("coverage", "coverage-report.json", freeze["coverage"]),
    ):
        artifact = _read_json(base / filename, filename)
        if artifact != embedded or artifact_digests[name] != _digest(artifact):
            raise VisibleCardReviewFreezeError(f"{filename} does not match freeze")
    manifests = freeze.get("manifests")
    if not isinstance(manifests, dict) or set(manifests) != {
        "teacher",
        "train",
        "validation",
        "challenge",
    }:
        raise VisibleCardReviewFreezeError("visible-card freeze manifests are incomplete")
    loaded: dict[str, Any] = {}
    for name in ("train", "validation", "challenge"):
        descriptor = manifests[name]
        if not isinstance(descriptor, dict):
            raise VisibleCardReviewFreezeError("visible-card manifest descriptor is invalid")
        value = _read_json(base / descriptor["path"], f"{name} manifest")
        _validate_manifest(value, name)
        if (
            value.get("freeze_id") != freeze.get("freeze_id")
            or value.get("queue_digest") != freeze.get("queue_digest")
            or value.get("partition_manifest_digest") != freeze.get("partition_manifest_digest")
            or value.get("review_policy_digest") != review_policy.get("policy_digest")
            or value.get("crop_policy_digest") != freeze["crop_policy"].get("policy_digest")
        ):
            raise VisibleCardReviewFreezeError(f"{name} manifest does not match freeze inputs")
        if value["manifest_digest"] != descriptor["digest"]:
            raise VisibleCardReviewFreezeError(f"{name} manifest digest does not match freeze")
        loaded[name] = value
    teacher = _read_json(base / manifests["teacher"]["path"], "teacher manifest")
    _validate_teacher_manifest(teacher)
    if (
        teacher.get("freeze_id") != freeze.get("freeze_id")
        or teacher.get("queue_digest") != freeze.get("queue_digest")
        or teacher.get("partition_manifest_digest") != freeze.get("partition_manifest_digest")
        or teacher.get("review_policy_digest") != review_policy.get("policy_digest")
        or teacher.get("crop_policy_digest") != freeze["crop_policy"].get("policy_digest")
    ):
        raise VisibleCardReviewFreezeError("teacher manifest does not match freeze inputs")
    if teacher["manifest_digest"] != manifests["teacher"]["digest"]:
        raise VisibleCardReviewFreezeError("teacher manifest digest does not match freeze")
    frame_groups: dict[str, str] = {}
    for name in ("train", "validation", "challenge"):
        for frame in loaded[name]["frames"]:
            group = frame["source"]["source_lineage_group"]
            previous = frame_groups.get(group)
            if previous is not None and previous != name:
                raise VisibleCardReviewFreezeError("source-lineage group crosses frozen partitions")
            frame_groups[group] = name
            if group in set(freeze["partition_manifest"]["system_holdout_groups"]):
                raise VisibleCardReviewFreezeError("system holdout is present in frozen data")
    return {**freeze, "teacher_manifest": teacher, "partition_manifests": loaded}


def _pixel_bounds(card: ReviewedVisibleCard, width: int, height: int) -> tuple[int, int, int, int]:
    box = card.derived_box.box_2d
    bounds = (
        max(0, math.floor(box.x_min * width / 1000)),
        max(0, math.floor(box.y_min * height / 1000)),
        min(width, math.ceil(box.x_max * width / 1000)),
        min(height, math.ceil(box.y_max * height / 1000)),
    )
    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise VisibleCardReviewFreezeError("derived box has no positive pixel crop")
    return bounds


def apply_visible_card_crop_policy(
    image_bytes: bytes,
    card: ReviewedVisibleCard,
    policy_id: Literal["raw_rectangular", "oracle_visible_region", "conservative_box_only"],
    *,
    width: int,
    height: int,
) -> bytes | None:
    """Apply one frozen crop transform and return deterministic PPM bytes.

    ``None`` is the frozen conservative-policy rejection for an unusable or failure-tagged card.
    """

    if policy_id not in VISIBLE_CARD_CROP_POLICIES:
        raise VisibleCardReviewFreezeError(f"unknown crop policy: {policy_id}")
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise VisibleCardReviewFreezeError("image_bytes must be non-empty")
    if width <= 0 or height <= 0:
        raise VisibleCardReviewFreezeError("crop dimensions must be positive")
    if policy_id == "conservative_box_only" and (
        not card.identity_usability.usable or card.failure_tags
    ):
        return None
    bounds = _pixel_bounds(card, width, height)
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.size != (width, height):
                raise VisibleCardReviewFreezeError("decoded image dimensions do not match crop")
            crop = image.convert("RGB").crop(bounds)
            if policy_id == "oracle_visible_region":
                mask = Image.new("L", crop.size, 0)
                draw = ImageDraw.Draw(mask)
                for polygon in card.visible_region.polygons:
                    draw.polygon(
                        [
                            (
                                point.x * width / 1000 - bounds[0],
                                point.y * height / 1000 - bounds[1],
                            )
                            for point in polygon
                        ],
                        fill=255,
                    )
                neutral = Image.new("RGB", crop.size, NEUTRAL_FILL_RGB)
                crop = Image.composite(crop, neutral, mask)
            if crop.width < 4 or crop.height < 4:
                raise VisibleCardReviewFreezeError("crop must be at least 4x4 pixels")
            return f"P6\n{crop.width} {crop.height}\n255\n".encode() + crop.tobytes()
    except UnidentifiedImageError as error:
        raise VisibleCardReviewFreezeError("source image cannot be decoded") from error


__all__ = [
    "MAX_SEED_SOURCE_GROUP_SHARE",
    "MINIMUM_SEED_SOURCE_GROUPS",
    "NEUTRAL_FILL_RGB",
    "SEED_FRAME_TARGET",
    "VISIBLE_CARD_CROP_POLICIES",
    "VISIBLE_CARD_CROP_POLICY_SCHEMA",
    "VISIBLE_CARD_CROP_POLICY_VERSION",
    "VISIBLE_CARD_COVERAGE_SCHEMA",
    "VISIBLE_CARD_FREEZE_SCHEMA",
    "VISIBLE_CARD_PARTITION_SCHEMA",
    "VISIBLE_CARD_REVIEWED_MANIFEST_SCHEMA",
    "VISIBLE_CARD_REVIEW_WORDING",
    "VISIBLE_CARD_REVIEW_WORDING_SCHEMA",
    "VISIBLE_CARD_REVIEW_WORDING_VERSION",
    "VISIBLE_CARD_TEACHER_SET_SCHEMA",
    "VisibleCardReviewFreezeError",
    "apply_visible_card_crop_policy",
    "freeze_visible_card_review_data",
    "frozen_visible_card_crop_policy",
    "load_frozen_visible_card_crop_policy",
    "load_frozen_visible_card_review_data",
    "load_visible_card_partition_manifest",
]
