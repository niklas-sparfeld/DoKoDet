"""Build the classifier dataset projection for a completed identity review.

The generic table-analyzer dataset contract is intentionally small.  This adapter keeps the
identity-specific source, geometry, crop-policy, proposal, and decision lineage in a sidecar so
the classifier sample can be reproduced without changing the reviewed visual card identity.
"""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from table_evidence_analyzer.cards import CARD_SET_ID
from table_evidence_analyzer.data import (
    ARTIFACT_INDEX_SCHEMA,
    DATASET_VERSION_SCHEMA,
    DEFAULT_TRANSFORM_VERSION,
    TARGET_SCHEMA,
    ArtifactIndex,
    ArtifactRecord,
    DatasetEntry,
    DatasetManifest,
    Eligibility,
    SplitManifest,
    assert_valid_dataset,
)

from .visual_card_identity_review_batch import (
    VisualCardIdentityBatchError,
    _canonical,
    _digest_value,
    _read_source_frame,
)

VISUAL_CARD_IDENTITY_DATASET_SCHEMA_VERSION = "visual-card-identity-dataset/v1"
VISUAL_CARD_IDENTITY_LINEAGE_SCHEMA_VERSION = "visual-card-identity-lineage/v1"
VISUAL_CARD_IDENTITY_DATASET_TASK = "visual_card_identity_classification"
VISUAL_CARD_IDENTITY_DATASET_ADAPTER_VERSION = "visual-card-identity-dataset-adapter-v1"
VISUAL_CARD_IDENTITY_DATASET_STATUS_READY = "eligible"
VISUAL_CARD_IDENTITY_DATASET_STATUS_BLOCKED = "blocked"
_PARTITIONS = frozenset({"train", "validation", "test", "unassigned"})
_ALLOWED_USES = frozenset({"train", "validation", "test", "evaluation"})


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisualCardIdentityBatchError(f"{field} must be a non-empty string")
    return value


def _write_immutable(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_bytes() == value:
                return
        except OSError as error:
            raise VisualCardIdentityBatchError(
                f"could not read dataset artifact: {path}"
            ) from error
        raise VisualCardIdentityBatchError(f"refusing to overwrite dataset artifact: {path}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise VisualCardIdentityBatchError(f"could not write dataset artifact: {path}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return _canonical(value) + b"\n"


def _dataset_mapping(dataset: DatasetManifest) -> dict[str, Any]:
    return {
        "schema_version": DATASET_VERSION_SCHEMA,
        "dataset_version_id": dataset.dataset_version_id,
        "task": dataset.task,
        "target_schema": dataset.target_schema,
        "entries": [entry.to_mapping() for entry in dataset.entries],
        "allowed_use_filter": list(dataset.allowed_use_filter),
        "group_key_names": list(dataset.group_key_names),
        "derived_artifact_transform_version": dataset.derived_artifact_transform_version,
        "creation_code_revision": dataset.creation_code_revision,
        "dirty_state": dataset.dirty_state,
        "deck_design_version": dataset.deck_design_version,
        "card_set_version": dataset.card_set_version,
        "created_at": dataset.created_at,
        "dataset_version_digest": dataset.digest,
    }


def _artifact_mapping(index: ArtifactIndex) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_INDEX_SCHEMA,
        "artifact_index_id": index.artifact_index_id,
        "dataset_version_id": index.dataset_version_id,
        "dataset_version_digest": index.dataset_version_digest,
        "artifacts": [
            {
                "source_asset_id": artifact.source_asset_id,
                "source_frame_id": artifact.source_frame_id,
                "relative_path": artifact.relative_path,
                "media_type": artifact.media_type,
                "byte_length": artifact.byte_length,
                "sha256": artifact.sha256,
            }
            for artifact in index.artifacts
        ],
        "artifact_index_digest": index.digest,
    }


def _ppm(source_bytes: bytes) -> bytes:
    try:
        with Image.open(BytesIO(source_bytes)) as image:
            output = BytesIO()
            image.convert("RGB").save(output, format="PPM")
            return output.getvalue()
    except (UnidentifiedImageError, OSError) as error:
        raise VisualCardIdentityBatchError("source frame is not a readable image") from error


def _pixel_bbox(card: Mapping[str, Any], width: int, height: int) -> list[int]:
    box = card.get("derived_box")
    if not isinstance(box, Mapping):
        raise VisualCardIdentityBatchError("identity lineage is missing the derived box")
    try:
        values = [
            max(0, math.floor(float(box["x_min"]) * width / 1000)),
            max(0, math.floor(float(box["y_min"]) * height / 1000)),
            min(width, math.ceil(float(box["x_max"]) * width / 1000)),
            min(height, math.ceil(float(box["y_max"]) * height / 1000)),
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise VisualCardIdentityBatchError("identity lineage has an invalid derived box") from error
    if values[2] <= values[0] or values[3] <= values[1]:
        raise VisualCardIdentityBatchError("identity lineage has an empty derived box")
    return values


def _group_keys(
    source: Mapping[str, Any], explicit: Sequence[tuple[str, str]]
) -> tuple[tuple[str, str], ...]:
    if explicit:
        return tuple(sorted(set(explicit)))
    return (("source_lineage", _text(source["source_lineage_group"], "source_lineage_group")),)


def build_visual_card_identity_dataset(
    completed_review: Mapping[str, Any],
    output_root: str | Path,
    *,
    development_partition: str = "unassigned",
    source_permission: str = "training_only",
    allowed_uses: Sequence[str] = ("train",),
    group_keys: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Build or re-open the immutable dataset projection for one completed review."""

    if completed_review.get("review_state") != "completed":
        raise VisualCardIdentityBatchError("only a completed identity review can enter a dataset")
    if development_partition not in _PARTITIONS:
        raise VisualCardIdentityBatchError("identity dataset partition is invalid")
    if development_partition == "test":
        return {
            "schema_version": VISUAL_CARD_IDENTITY_DATASET_SCHEMA_VERSION,
            "status": VISUAL_CARD_IDENTITY_DATASET_STATUS_BLOCKED,
            "dataset_version_id": None,
            "dataset_version_digest": None,
            "dataset_path": None,
            "split_version_id": None,
            "split_version_digest": None,
            "split_path": None,
            "artifact_index_id": None,
            "artifact_index_digest": None,
            "artifact_index_path": None,
            "lineage_path": None,
            "lineage_digest": None,
            "development_partition": development_partition,
            "blocker": "Identity review samples cannot enter the system holdout test partition.",
            "sample_count": 0,
            "excluded_count": len(completed_review.get("items", [])),
        }
    normalized_uses = tuple(sorted(set(allowed_uses)))
    if not normalized_uses or any(use not in _ALLOWED_USES for use in normalized_uses):
        raise VisualCardIdentityBatchError("identity dataset allowed uses are invalid")
    _text(source_permission, "source_permission")
    items = completed_review.get("items")
    if not isinstance(items, list):
        raise VisualCardIdentityBatchError("completed identity review items are invalid")
    samples = [
        item
        for item in items
        if isinstance(item, Mapping)
        and item.get("decision", {}).get("status") in {"accepted", "corrected"}
    ]
    excluded = [
        {
            "item_id": item.get("item_id"),
            "decision_status": item.get("decision", {}).get("status"),
            "reason": "Identity-unusable cards are excluded from classifier samples.",
        }
        for item in items
        if item not in samples
    ]
    if not samples:
        return {
            "schema_version": VISUAL_CARD_IDENTITY_DATASET_SCHEMA_VERSION,
            "status": VISUAL_CARD_IDENTITY_DATASET_STATUS_BLOCKED,
            "dataset_version_id": None,
            "dataset_version_digest": None,
            "dataset_path": None,
            "split_version_id": None,
            "split_version_digest": None,
            "split_path": None,
            "artifact_index_id": None,
            "artifact_index_digest": None,
            "artifact_index_path": None,
            "lineage_path": None,
            "lineage_digest": None,
            "development_partition": development_partition,
            "blocker": "No decided identity-usable cards are available for classifier training.",
            "sample_count": 0,
            "excluded_count": len(excluded),
        }

    review_version_id = _text(completed_review["publication"]["version_id"], "version_id")
    review_version_digest = _text(
        completed_review["publication"]["version_digest"], "version_digest"
    )
    source_asset_id = _text(completed_review["frozen_inputs"]["source_asset_id"], "source_asset_id")
    source_sha256 = _text(completed_review["frozen_inputs"]["source_sha256"], "source_sha256")
    partition_key = _digest_value(
        {
            "review_version_id": review_version_id,
            "development_partition": development_partition,
            "source_permission": source_permission,
            "allowed_uses": normalized_uses,
            "group_keys": sorted(group_keys),
        }
    )
    dataset_version_id = f"visual-card-identity-dataset-{partition_key[:24]}"
    output = Path(output_root).expanduser().resolve() / dataset_version_id
    artifact_root = output / "artifacts"
    frame_records: list[ArtifactRecord] = []
    frame_records_by_id: dict[str, ArtifactRecord] = {}
    entries: list[DatasetEntry] = []
    lineage_samples: list[dict[str, Any]] = []
    for item in samples:
        source = item.get("source")
        card = item.get("visible_card")
        decision = item.get("decision")
        crop = item.get("crop")
        proposal = item.get("proposal")
        if (
            not isinstance(source, Mapping)
            or not isinstance(card, Mapping)
            or not isinstance(decision, Mapping)
        ):
            raise VisualCardIdentityBatchError("completed identity review has incomplete lineage")
        if not isinstance(crop, Mapping) or not isinstance(proposal, Mapping):
            raise VisualCardIdentityBatchError(
                "completed identity sample is missing crop or proposal"
            )
        identity = decision.get("identity")
        if not isinstance(identity, str) or not identity:
            raise VisualCardIdentityBatchError(
                f"completed identity sample has no identity: {item.get('item_id')}"
            )
        source_frame_id = f"{source['package_id']}:{source['frame_part_name']}"
        if source_frame_id not in frame_records_by_id:
            frame_bytes = _ppm(_read_source_frame(source))
            relative_frame_path = f"frames/{_digest_value(source_frame_id)[:24]}.ppm"
            frame_path = artifact_root / relative_frame_path
            _write_immutable(frame_path, frame_bytes)
            frame_records_by_id[source_frame_id] = ArtifactRecord(
                source_asset_id=source_asset_id,
                source_frame_id=source_frame_id,
                relative_path=relative_frame_path,
                media_type="image/x-portable-pixmap",
                byte_length=len(frame_bytes),
                sha256=_sha256(frame_bytes),
            )
        bbox = _pixel_bbox(card, int(source["width"]), int(source["height"]))
        groups = _group_keys(source, group_keys)
        eligibility = Eligibility(
            source_asset_id=source_asset_id,
            state="eligible",
            source_permission=source_permission,
            allowed_uses=normalized_uses,
            review_state="reviewed",
            annotation_set_id=review_version_id,
            review_id=review_version_id,
            intended_use="train" if "train" in normalized_uses else normalized_uses[0],
        )
        entry_mapping = {
            "dataset_item_id": item["item_id"],
            "source_asset_id": source_asset_id,
            "source_sha256": source_sha256,
            "annotation_set_id": review_version_id,
            "review_id": review_version_id,
            "eligibility": eligibility.to_mapping(),
            "target_schema": TARGET_SCHEMA,
            "group_keys": [list(pair) for pair in groups],
            "inclusion_reason": "Human-reviewed visual card identity with frozen crop lineage.",
            "transform_version": DEFAULT_TRANSFORM_VERSION,
            "source_frame_id": source_frame_id,
            "observed_card_id": card["card_id"],
            "bbox": bbox,
            "visual_card_identity": identity,
            "quality_tags": sorted(
                set(card.get("failure_tags", [])) | set(decision.get("failure_tags", []))
            ),
        }
        entries.append(DatasetEntry.from_mapping(entry_mapping))
        lineage_samples.append(
            {
                "dataset_item_id": item["item_id"],
                "source_frame_id": source_frame_id,
                "source": dict(source),
                "visible_card_digest": item["visible_card_digest"],
                "visible_card": dict(card),
                "crop": dict(crop),
                "proposal": dict(proposal),
                "decision": dict(decision),
                "partition": development_partition,
            }
        )

    group_key_names = tuple(sorted({name for entry in entries for name, _ in entry.group_keys}))
    frame_records = list(frame_records_by_id.values())
    dataset = DatasetManifest(
        dataset_version_id=dataset_version_id,
        task=VISUAL_CARD_IDENTITY_DATASET_TASK,
        target_schema=TARGET_SCHEMA,
        entries=tuple(entries),
        allowed_use_filter=normalized_uses,
        group_key_names=group_key_names,
        derived_artifact_transform_version=DEFAULT_TRANSFORM_VERSION,
        creation_code_revision=VISUAL_CARD_IDENTITY_DATASET_ADAPTER_VERSION,
        dirty_state=False,
        deck_design_version=None,
        card_set_version=CARD_SET_ID,
        created_at=completed_review["completed_at_utc"],
    )
    split = SplitManifest(
        split_version_id=f"visual-card-identity-split-{dataset.digest[:24]}",
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        group_key_names=dataset.group_key_names,
        seed=0,
        train=tuple(entry.dataset_item_id for entry in entries if development_partition == "train"),
        validation=tuple(
            entry.dataset_item_id for entry in entries if development_partition == "validation"
        ),
        test=(),
        unassigned=tuple(
            entry.dataset_item_id for entry in entries if development_partition == "unassigned"
        ),
    )
    artifact_index = ArtifactIndex(
        artifact_index_id=f"visual-card-identity-artifacts-{dataset.digest[:24]}",
        dataset_version_id=dataset.dataset_version_id,
        dataset_version_digest=dataset.digest,
        artifacts=tuple(frame_records),
        root=artifact_root,
    )
    assert_valid_dataset(dataset, split=split, artifacts=artifact_index)
    lineage = {
        "schema_version": VISUAL_CARD_IDENTITY_LINEAGE_SCHEMA_VERSION,
        "dataset_version_id": dataset.dataset_version_id,
        "dataset_version_digest": dataset.digest,
        "split_version_id": split.split_version_id,
        "split_version_digest": split.digest,
        "artifact_index_id": artifact_index.artifact_index_id,
        "artifact_index_digest": artifact_index.digest,
        "review_version_id": review_version_id,
        "review_version_digest": review_version_digest,
        "source_asset_id": source_asset_id,
        "source_sha256": source_sha256,
        "source_permission": source_permission,
        "allowed_uses": list(normalized_uses),
        "development_partition": development_partition,
        "crop_policy": completed_review["crop_policy"],
        "samples": lineage_samples,
        "excluded": excluded,
    }
    lineage["lineage_digest"] = _digest_value(lineage)
    _write_immutable(output / "dataset.json", _json_bytes(_dataset_mapping(dataset)))
    _write_immutable(output / "split.json", _json_bytes(split.to_mapping()))
    _write_immutable(artifact_root / "index.json", _json_bytes(_artifact_mapping(artifact_index)))
    _write_immutable(output / "identity-lineage.json", _json_bytes(lineage))
    return {
        "schema_version": VISUAL_CARD_IDENTITY_DATASET_SCHEMA_VERSION,
        "status": VISUAL_CARD_IDENTITY_DATASET_STATUS_READY,
        "dataset_version_id": dataset.dataset_version_id,
        "dataset_version_digest": dataset.digest,
        "dataset_path": str((output / "dataset.json").resolve()),
        "split_version_id": split.split_version_id,
        "split_version_digest": split.digest,
        "split_path": str((output / "split.json").resolve()),
        "artifact_index_id": artifact_index.artifact_index_id,
        "artifact_index_digest": artifact_index.digest,
        "artifact_index_path": str((artifact_root / "index.json").resolve()),
        "lineage_path": str((output / "identity-lineage.json").resolve()),
        "lineage_digest": lineage["lineage_digest"],
        "sample_count": len(entries),
        "excluded_count": len(excluded),
        "development_partition": development_partition,
        "blocker": None,
    }


__all__ = [
    "VISUAL_CARD_IDENTITY_DATASET_ADAPTER_VERSION",
    "VISUAL_CARD_IDENTITY_DATASET_SCHEMA_VERSION",
    "VISUAL_CARD_IDENTITY_DATASET_STATUS_BLOCKED",
    "VISUAL_CARD_IDENTITY_DATASET_STATUS_READY",
    "VISUAL_CARD_IDENTITY_DATASET_TASK",
    "VISUAL_CARD_IDENTITY_LINEAGE_SCHEMA_VERSION",
    "build_visual_card_identity_dataset",
]
