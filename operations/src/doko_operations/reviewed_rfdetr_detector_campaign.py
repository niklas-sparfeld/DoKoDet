"""Freeze the epic 0068 reviewed RF-DETR detector campaign input.

M0 is a read-only audit. It discovers the current completed corrected visible-card
references, joins them to accepted recording bundles, validates source-group lineage,
and writes one deterministic manifest for the later materialization and training steps.
It never changes source data and it never starts a model run.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .rfdetr_segmentation_campaign import (
    RfdetrSegmentationCampaignError,
    _bundle_audit,
    _holdout_groups,
    _read_json,
    _reference_audit,
    _relative,
    _resolve,
    canonical_json_bytes,
    default_rfdetr_segmentation_recipe,
    probe_rfdetr_segmentation_api,
    sha256_json,
)

RFDETR_DETECTOR_MANIFEST_SCHEMA_VERSION = "rfdetr-visible-card-detector-manifest/v1"
RFDETR_DETECTOR_CAMPAIGN_ID = "0068-m0-reviewed-rfdetr-local-visible-card-detector"
RFDETR_PACKAGE_VERSION = "1.9.4"
RFDETR_MODEL_CLASS = "RFDETRSegMedium"
RFDETR_RESOLUTION = [432, 432]

REVIEWED_RECORDING_IDS = (
    "cardeventnet-IMG_0090",
    "cardeventnet-IMG_0091",
    "cardeventnet-IMG_0092",
    "cardeventnet-IMG_0095",
    "cardeventnet-IMG_0096",
    "cardeventnet-IMG_0097",
    "cardeventnet-IMG_0635",
    "cardeventnet-IMG_0636",
    "cardeventnet-IMG_0637",
    "cardeventnet-IMG_0638",
    "cardeventnet-IMG_0639",
    "cardeventnet-IMG_0640",
    "cardeventnet-IMG_0641",
    "cardeventnet-IMG_0642",
    "cardeventnet-IMG_0643",
    "cardeventnet-IMG_0644",
    "cardeventnet-IMG_0645",
    "cardeventnet-IMG_0646",
    "cardeventnet-IMG_0648",
    "cardeventnet-IMG_0649",
    "cardeventnet-IMG_0655",
    "cardeventnet-IMG_0661",
    "cardeventnet-IMG_0669",
    "cardeventnet-IMG_0674",
)

# These assignments are explicit because source-group selection must not depend on identifier
# ordering. The three recordings used as 0067 validation remain development evidence here.
DEFAULT_PARTITION_RECORDING_IDS: dict[str, tuple[str, ...]] = {
    "train": (
        "cardeventnet-IMG_0092",
        "cardeventnet-IMG_0095",
        "cardeventnet-IMG_0096",
        "cardeventnet-IMG_0097",
        "cardeventnet-IMG_0635",
        "cardeventnet-IMG_0636",
        "cardeventnet-IMG_0637",
        "cardeventnet-IMG_0638",
        "cardeventnet-IMG_0639",
        "cardeventnet-IMG_0640",
        "cardeventnet-IMG_0641",
        "cardeventnet-IMG_0643",
        "cardeventnet-IMG_0655",
        "cardeventnet-IMG_0669",
        "cardeventnet-IMG_0674",
    ),
    "validation": (
        "cardeventnet-IMG_0090",
        "cardeventnet-IMG_0091",
        "cardeventnet-IMG_0642",
        "cardeventnet-IMG_0644",
        "cardeventnet-IMG_0645",
        "cardeventnet-IMG_0661",
    ),
    "sealed_test": (
        "cardeventnet-IMG_0646",
        "cardeventnet-IMG_0648",
        "cardeventnet-IMG_0649",
    ),
}

EXPECTED_INVENTORY = {
    "reviewed_frames": 1180,
    "retained_frames": 784,
    "excluded_frames": 259,
    "ineligible_outcomes": 137,
    "ignored_regions": 389,
    "targets": 2203,
}
EXPECTED_SIDE_COUNTS = {"face_up": 1620, "unknown": 560, "face_down": 23}
REQUIRED_SEALED_TEST_GROUPS = 3
CARD_SIDES = frozenset({"face_up", "face_down", "unknown"})


class ReviewedRfdetrDetectorCampaignError(ValueError):
    """Raised when the epic 0068 M0 audit or manifest is invalid."""


def default_reviewed_rfdetr_detector_recipe(
    *,
    repository_root: str | Path | None = None,
    pretrained_checkpoint: str | Path | None = None,
    device: str = "mps",
) -> dict[str, Any]:
    """Return the fixed recipe, matching rules, resource budget, and held-out gate."""

    recipe = default_rfdetr_segmentation_recipe(
        repository_root=repository_root,
        pretrained_checkpoint=pretrained_checkpoint,
        device=device,
    )
    recipe["training"]["output_dir_name"] = "rfdetr-segmentation-0068"
    recipe["data_contract"] = {
        **recipe["data_contract"],
        "test_partition": "sealed_test",
        "partition_policy": "source_group_disjoint/v1",
    }
    recipe["validation"] = {
        **recipe["validation"],
        "group_by": ["recording_id", "card_side", "visible_card_count_bucket"],
        "checkpoint_selection": "highest_validation_mask_ap_50_95_then_recall",
        "matching": {
            "primary_geometry": "mask",
            "supporting_geometry": "box",
            "iou_thresholds": [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95],
            "assignment": "one_to_one_greedy_by_prediction_score",
        },
        "minimum_gate": {
            "mask_ap_50_95": 0.0,
            "recall": 0.0,
            "beats_pretrained_mask_ap_50_95": True,
            "beats_pretrained_recall": True,
            "nonzero_recall_per_sealed_test_recording": True,
        },
    }
    return recipe


def _partition_recording_ids(
    available: Sequence[str],
    requested: Mapping[str, Sequence[str]] | None,
) -> tuple[dict[str, list[str]], list[str]]:
    """Resolve the explicit train, validation, and sealed-test recording split."""

    source = DEFAULT_PARTITION_RECORDING_IDS if requested is None else requested
    if set(source) != {"train", "validation", "sealed_test"}:
        raise ReviewedRfdetrDetectorCampaignError(
            "partition_recording_ids must contain train, validation, and sealed_test only"
        )
    available_set = set(available)
    result: dict[str, list[str]] = {}
    gaps: list[str] = []
    seen: dict[str, str] = {}
    for partition in ("train", "validation", "sealed_test"):
        values = source[partition]
        if isinstance(values, (str, bytes)):
            raise ReviewedRfdetrDetectorCampaignError(
                f"partition_recording_ids.{partition} must be a list"
            )
        result[partition] = []
        for recording_id in values:
            if not isinstance(recording_id, str) or not recording_id:
                raise ReviewedRfdetrDetectorCampaignError(
                    f"partition_recording_ids.{partition} contains an invalid recording ID"
                )
            previous = seen.get(recording_id)
            if previous is not None:
                gaps.append(
                    f"recording {recording_id} is assigned to both {previous} and {partition}"
                )
                continue
            seen[recording_id] = partition
            result[partition].append(recording_id)
            if recording_id not in available_set:
                gaps.append(
                    f"partition recording is not a selected completed corrected reference: "
                    f"{recording_id}"
                )
    missing = sorted(available_set - set(seen))
    if missing:
        gaps.append(
            "selected corrected references have no explicit partition: " + ", ".join(missing)
        )
    for partition in ("train", "validation", "sealed_test"):
        if not result[partition]:
            gaps.append(f"the explicit {partition} partition has no recording")
    if len(result["sealed_test"]) < REQUIRED_SEALED_TEST_GROUPS:
        gaps.append(
            f"sealed_test needs at least {REQUIRED_SEALED_TEST_GROUPS} source groups; "
            f"found {len(result['sealed_test'])} recording assignments"
        )
    return result, gaps


def _discover_selected_corrected_references(
    operations_root: Path, repository_root: Path
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """Discover selected completed corrected visible-card references without changing them."""

    root = operations_root / "pipeline-references"
    discovered: list[str] = []
    unavailable: list[dict[str, Any]] = []
    gaps: list[str] = []
    if not root.is_dir():
        return (
            [],
            unavailable,
            [f"maintained reference root is missing: {_relative(root, repository_root)}"],
        )
    for reference_root in sorted(root.glob("*/visible_cards")):
        recording_id = reference_root.parent.name
        state_path = reference_root / "state.json"
        if not state_path.is_file():
            continue
        try:
            state = _read_json(state_path, f"visible_cards state for {recording_id}")
        except RfdetrSegmentationCampaignError as error:
            gaps.append(str(error))
            continue
        if state.get("draft_state") != "completed":
            continue
        revision_id = state.get("selected_completed_revision_id")
        if not isinstance(revision_id, str) or not revision_id:
            continue
        revision_manifest_path = (
            operations_root / "pipeline" / "revisions" / revision_id / "manifest.json"
        )
        if not revision_manifest_path.is_file():
            unavailable.append(
                {
                    "recording_id": recording_id,
                    "reason": "selected completed revision manifest is missing",
                    "reference_path": _relative(reference_root, repository_root),
                }
            )
            continue
        try:
            revision = _read_json(
                revision_manifest_path, f"visible_cards revision manifest for {recording_id}"
            )
        except RfdetrSegmentationCampaignError as error:
            gaps.append(str(error))
            continue
        if revision.get("origin") != "corrected":
            continue
        discovered.append(recording_id)
    return sorted(set(discovered)), unavailable, gaps


def _selected_reference_ids(
    discovered: Sequence[str],
    partitions: Mapping[str, Sequence[str]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Add expected split IDs to the audit so missing references become item-level gaps."""

    expected = sorted({recording_id for values in partitions.values() for recording_id in values})
    discovered_set = set(discovered)
    unavailable = [
        {
            "recording_id": recording_id,
            "expected_split": partition,
            "reason": "selected completed corrected reference was not discovered",
        }
        for partition, values in partitions.items()
        for recording_id in values
        if recording_id not in discovered_set
    ]
    return sorted(set(discovered).union(expected)), unavailable


def _group_mapping(recording: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete source group used for partition isolation checks."""

    return {
        "recording_id": recording.get("recording_id"),
        "session_id": recording.get("session_id"),
        "source_asset_id": recording.get("source_asset_id"),
        "video_id": recording.get("video_id"),
        "source_sha256": recording.get("source_sha256"),
        "table_setup": recording.get("table_setup"),
    }


def _partition_group_gaps(
    recordings: Sequence[Mapping[str, Any]], partitions: Mapping[str, Sequence[str]]
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id = {str(recording.get("recording_id")): recording for recording in recordings}
    partition_for = {
        recording_id: partition
        for partition, values in partitions.items()
        for recording_id in values
    }
    groups = [
        {
            **_group_mapping(by_id[recording_id]),
            "partition": partition_for[recording_id],
            "group_key": sha256_json(_group_mapping(by_id[recording_id])),
        }
        for recording_id in sorted(by_id)
        if recording_id in partition_for
    ]
    gaps: list[str] = []
    fields = (
        "recording_id",
        "session_id",
        "source_asset_id",
        "video_id",
        "source_sha256",
        "table_setup",
    )
    for field in fields:
        by_value: dict[Any, set[str]] = {}
        for group in groups:
            by_value.setdefault(group[field], set()).add(group["partition"])
        for value, split_names in sorted(by_value.items(), key=lambda item: str(item[0])):
            if len(split_names) > 1:
                gaps.append(
                    f"source group field {field} crosses partitions for {value}: "
                    + ", ".join(sorted(split_names))
                )
    return groups, gaps


def _add_side_counts(report: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(report)
    counts = {side: 0 for side in sorted(CARD_SIDES)}
    for sample in report.get("samples", []):
        for target in sample.get("targets", []):
            side = target.get("side", "unknown")
            if side not in CARD_SIDES:
                raise ReviewedRfdetrDetectorCampaignError(
                    f"{sample.get('event_id')}: card side is not one of {sorted(CARD_SIDES)}"
                )
            counts[side] += 1
    result["side_counts"] = counts
    return result


def _split_summary(
    reports: Sequence[Mapping[str, Any]], partitions: Mapping[str, Sequence[str]]
) -> dict[str, Any]:
    by_recording = {str(report["recording_id"]): report for report in reports}
    result: dict[str, Any] = {}
    for partition in ("train", "validation", "sealed_test"):
        selected = [
            by_recording[recording_id]
            for recording_id in partitions[partition]
            if recording_id in by_recording
        ]
        side_counts = {side: 0 for side in sorted(CARD_SIDES)}
        for report in selected:
            for side, count in report.get("side_counts", {}).items():
                side_counts[side] += count
        result[partition] = {
            "recording_ids": list(partitions[partition]),
            "source_group_count": len(selected),
            "reviewed_frames": sum(report["reviewed_frame_count"] for report in selected),
            "retained_frames": sum(report["retained_frame_count"] for report in selected),
            "excluded_frames": sum(report["excluded_frame_count"] for report in selected),
            "ignored_regions": sum(report["ignored_region_count"] for report in selected),
            "ineligible_outcomes": sum(len(report["ineligible_outcomes"]) for report in selected),
            "targets": sum(report["target_count"] for report in selected),
            "side_counts": side_counts,
        }
    return result


def build_reviewed_rfdetr_detector_manifest(
    repository_root: str | Path,
    *,
    intake_root: str | Path | None = None,
    operations_root: str | Path | None = None,
    holdout_registry_path: str | Path | None = None,
    pretrained_checkpoint: str | Path | None = None,
    device: str = "mps",
    verify_source_bytes: bool = False,
    api_probe: Mapping[str, Any] | None = None,
    partition_recording_ids: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Build the deterministic, read-only epic 0068 M0 manifest."""

    repository = Path(repository_root).expanduser().resolve()
    intake = _resolve(repository, intake_root, repository / "data" / "intake" / "recordings")
    operations = _resolve(repository, operations_root, repository / "data" / "operations")
    recipe = default_reviewed_rfdetr_detector_recipe(
        repository_root=repository,
        pretrained_checkpoint=pretrained_checkpoint,
        device=device,
    )
    probe = dict(api_probe) if api_probe is not None else probe_rfdetr_segmentation_api()
    requested_partitions = (
        DEFAULT_PARTITION_RECORDING_IDS
        if partition_recording_ids is None
        else partition_recording_ids
    )
    discovered, discovery_unavailable, discovery_gaps = _discover_selected_corrected_references(
        operations, repository
    )
    partitions, partition_gaps = _partition_recording_ids(discovered, requested_partitions)
    selected_ids, missing_references = _selected_reference_ids(discovered, partitions)
    gaps = [*discovery_gaps, *partition_gaps]
    recordings: list[dict[str, Any]] = []
    reference_reports: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    excluded_frames: list[dict[str, Any]] = []
    ineligible_outcomes: list[dict[str, Any]] = []
    by_partition = {
        recording_id: partition
        for partition, values in partitions.items()
        for recording_id in values
    }
    holdout, held_out, holdout_gaps = _holdout_groups(repository, operations, holdout_registry_path)
    gaps.extend(holdout_gaps)

    for recording_id in selected_ids:
        split = by_partition.get(recording_id)
        if split is None:
            gaps.append(f"selected reference has no partition: {recording_id}")
            continue
        recording, recording_gaps = _bundle_audit(
            recording_id,
            split,
            intake_root=intake,
            repository_root=repository,
            verify_source_bytes=verify_source_bytes,
        )
        if recording is None:
            gaps.extend(recording_gaps)
            continue
        recording["split"] = split
        recording["source_group"] = _group_mapping(recording)
        protected_groups = {
            ("session_id", recording.get("session_id")),
            ("table_setup", recording.get("table_setup")),
            ("source_lineage", recording.get("source_asset_id")),
        }
        sealed_groups = sorted(protected_groups & held_out)
        if sealed_groups:
            groups = ", ".join(f"{name}:{value}" for name, value in sealed_groups)
            recording_gaps.append(
                f"{recording_id}: recording is in the sealed system holdout ({groups})"
            )
        gaps.extend(recording_gaps)
        reference_manifest_path = operations / "pipeline" / "revisions"
        state_path = (
            operations / "pipeline-references" / recording_id / "visible_cards" / "state.json"
        )
        revision_id = None
        if state_path.is_file():
            with contextlib.suppress(RfdetrSegmentationCampaignError):
                revision_id = _read_json(state_path, f"visible_cards state for {recording_id}").get(
                    "selected_completed_revision_id"
                )
        if isinstance(revision_id, str):
            selected_revision = reference_manifest_path / revision_id / "manifest.json"
            if selected_revision.is_file():
                try:
                    revision = _read_json(
                        selected_revision, f"selected revision for {recording_id}"
                    )
                    if revision.get("origin") != "corrected":
                        recording_gaps.append(
                            f"{recording_id}: selected revision origin is not corrected"
                        )
                except RfdetrSegmentationCampaignError as error:
                    gaps.append(str(error))
        if recording_gaps:
            continue
        report, reference_gaps = _reference_audit(
            recording, operations_root=operations, repository_root=repository
        )
        report = _add_side_counts(report)
        report["origin"] = "corrected"
        gaps.extend(reference_gaps)
        recordings.append(recording)
        reference_reports.append(report)
        group = recording["source_group"]
        samples.extend(
            {
                **sample,
                "source_group": group,
                "source_group_key": sha256_json(group),
            }
            for sample in report["samples"]
        )
        excluded_frames.extend(
            {
                **frame,
                "recording_id": recording_id,
                "session_id": recording["session_id"],
                "source_asset_id": recording["source_asset_id"],
                "source_sha256": recording["source_sha256"],
                "reference_revision_id": report["reference_revision_id"],
                "split": split,
            }
            for frame in report["excluded_frames"]
        )
        ineligible_outcomes.extend(
            {
                **outcome,
                "recording_id": recording_id,
                "session_id": recording["session_id"],
                "source_asset_id": recording["source_asset_id"],
                "source_sha256": recording["source_sha256"],
                "reference_revision_id": report["reference_revision_id"],
                "split": split,
            }
            for outcome in report["ineligible_outcomes"]
        )

    source_groups, source_group_gaps = _partition_group_gaps(recordings, partitions)
    gaps.extend(source_group_gaps)
    selected_recording_set = {recording["recording_id"] for recording in recordings}
    if selected_recording_set != set(selected_ids):
        gaps.append(
            "selected recording set is incomplete: "
            + ", ".join(sorted(set(selected_ids) - selected_recording_set))
        )
    all_reference_gaps = [*missing_references, *discovery_unavailable]
    gaps.extend(
        f"{item.get('recording_id')}: {item.get('reason', 'reference unavailable')}"
        for item in all_reference_gaps
    )
    split = _split_summary(reference_reports, partitions)
    side_counts = {side: 0 for side in sorted(CARD_SIDES)}
    for report in reference_reports:
        for side, count in report["side_counts"].items():
            side_counts[side] += count
    inventory = {
        "selected_recording_count": len(selected_ids),
        "recording_count": len(recordings),
        "completed_corrected_reference_count": len(discovered),
        "reviewed_frame_count": sum(report["reviewed_frame_count"] for report in reference_reports),
        "retained_frame_count": sum(report["retained_frame_count"] for report in reference_reports),
        "excluded_frame_count": len(excluded_frames),
        "ineligible_outcome_count": len(ineligible_outcomes),
        "ignored_region_count": sum(report["ignored_region_count"] for report in reference_reports),
        "target_count": len([target for sample in samples for target in sample["targets"]]),
        "side_counts": side_counts,
    }
    expected = {
        "reviewed_frames": inventory["reviewed_frame_count"],
        "retained_frames": inventory["retained_frame_count"],
        "excluded_frames": inventory["excluded_frame_count"],
        "ineligible_outcomes": inventory["ineligible_outcome_count"],
        "ignored_regions": inventory["ignored_region_count"],
        "targets": inventory["target_count"],
    }
    for field, expected_value in EXPECTED_INVENTORY.items():
        if expected[field] != expected_value:
            gaps.append(f"corpus {field} drift: expected {expected_value}, found {expected[field]}")
    if side_counts != EXPECTED_SIDE_COUNTS:
        gaps.append(
            f"corpus side counts drift: expected {EXPECTED_SIDE_COUNTS}, found {side_counts}"
        )
    if recipe["pretrained_checkpoint"]["sha256"] is None:
        gaps.append("pretrained RF-DETR segmentation checkpoint is missing or unreadable")
    gaps.extend(str(gap) for gap in probe.get("gaps", []) if isinstance(gap, str))
    if not isinstance(probe.get("gaps"), list):
        gaps.append("RF-DETR API probe gaps must be a list")
    freeze_state = "frozen" if not gaps else "blocked"
    core = {
        "schema_version": RFDETR_DETECTOR_MANIFEST_SCHEMA_VERSION,
        "campaign_id": RFDETR_DETECTOR_CAMPAIGN_ID,
        "milestone": "M0",
        "read_only": True,
        "freeze_state": freeze_state,
        "selection": {
            "strategy": "selected_completed_corrected_visible_card_references/v1",
            "selected_recording_ids": list(selected_ids),
            "unavailable_references": all_reference_gaps,
        },
        "split": split,
        "recipe": recipe,
        "recipe_sha256": sha256_json(recipe),
        "api_probe": probe,
        "source_groups": source_groups,
        "recordings": recordings,
        "references": reference_reports,
        "samples": samples,
        "excluded_frames": excluded_frames,
        "ineligible_outcomes": ineligible_outcomes,
        "inventory": inventory,
        "holdout_registry": holdout,
        "coverage_gaps": sorted(set(gaps)),
    }
    return json.loads(
        canonical_json_bytes({**core, "manifest_digest": sha256_json(core)}).decode("utf-8")
    )


def validate_reviewed_rfdetr_detector_manifest(raw: Mapping[str, Any]) -> None:
    """Validate the strict immutable epic 0068 M0 manifest contract."""

    if not isinstance(raw, Mapping):
        raise ReviewedRfdetrDetectorCampaignError("RF-DETR detector manifest must be an object")
    expected_fields = {
        "schema_version",
        "campaign_id",
        "milestone",
        "read_only",
        "freeze_state",
        "selection",
        "split",
        "recipe",
        "recipe_sha256",
        "api_probe",
        "source_groups",
        "recordings",
        "references",
        "samples",
        "excluded_frames",
        "ineligible_outcomes",
        "inventory",
        "holdout_registry",
        "coverage_gaps",
        "manifest_digest",
    }
    if set(raw) != expected_fields:
        raise ReviewedRfdetrDetectorCampaignError("RF-DETR detector manifest has invalid fields")
    if raw["schema_version"] != RFDETR_DETECTOR_MANIFEST_SCHEMA_VERSION:
        raise ReviewedRfdetrDetectorCampaignError("RF-DETR detector manifest schema is unsupported")
    if raw["campaign_id"] != RFDETR_DETECTOR_CAMPAIGN_ID or raw["milestone"] != "M0":
        raise ReviewedRfdetrDetectorCampaignError("RF-DETR detector manifest identity is invalid")
    if raw["read_only"] is not True or raw["freeze_state"] not in {"frozen", "blocked"}:
        raise ReviewedRfdetrDetectorCampaignError("RF-DETR detector manifest state is invalid")
    recipe = raw["recipe"]
    if not isinstance(recipe, Mapping) or raw["recipe_sha256"] != sha256_json(recipe):
        raise ReviewedRfdetrDetectorCampaignError("recipe_sha256 does not match recipe")
    if recipe.get("package") != {"name": "rfdetr", "version": RFDETR_PACKAGE_VERSION}:
        raise ReviewedRfdetrDetectorCampaignError("RF-DETR package pin changed")
    if (
        recipe.get("model", {}).get("class") != RFDETR_MODEL_CLASS
        or recipe.get("model", {}).get("resolution") != RFDETR_RESOLUTION
    ):
        raise ReviewedRfdetrDetectorCampaignError("RF-DETR model or resolution pin changed")
    if recipe.get("data_contract", {}).get("test_partition") != "sealed_test":
        raise ReviewedRfdetrDetectorCampaignError("M0 must define the sealed_test partition")
    if raw["freeze_state"] == "frozen":
        checkpoint = recipe.get("pretrained_checkpoint")
        if not isinstance(checkpoint, Mapping) or not isinstance(checkpoint.get("sha256"), str):
            raise ReviewedRfdetrDetectorCampaignError(
                "frozen M0 manifest must pin a checkpoint digest"
            )
        probe = raw["api_probe"]
        if (
            not isinstance(probe, Mapping)
            or probe.get("status") != "available"
            or probe.get("gaps")
        ):
            raise ReviewedRfdetrDetectorCampaignError(
                "frozen M0 manifest must pass the RF-DETR API probe"
            )
    for field in (
        "source_groups",
        "recordings",
        "references",
        "samples",
        "excluded_frames",
        "ineligible_outcomes",
        "coverage_gaps",
    ):
        if not isinstance(raw[field], list):
            raise ReviewedRfdetrDetectorCampaignError(f"{field} must be a list")
    selection = raw["selection"]
    if not isinstance(selection, Mapping) or set(selection) != {
        "strategy",
        "selected_recording_ids",
        "unavailable_references",
    }:
        raise ReviewedRfdetrDetectorCampaignError("selection has invalid fields")
    if selection.get("strategy") != "selected_completed_corrected_visible_card_references/v1":
        raise ReviewedRfdetrDetectorCampaignError("selection strategy is not frozen")
    if not isinstance(selection.get("selected_recording_ids"), list) or not isinstance(
        selection.get("unavailable_references"), list
    ):
        raise ReviewedRfdetrDetectorCampaignError("selection lists are invalid")
    split = raw["split"]
    if not isinstance(split, Mapping) or set(split) != {"train", "validation", "sealed_test"}:
        raise ReviewedRfdetrDetectorCampaignError(
            "split must contain train, validation, sealed_test"
        )
    assigned: set[str] = set()
    for partition in ("train", "validation", "sealed_test"):
        item = split[partition]
        if (
            not isinstance(item, Mapping)
            or "recording_ids" not in item
            or not isinstance(item["recording_ids"], list)
        ):
            raise ReviewedRfdetrDetectorCampaignError(f"split.{partition} is invalid")
        ids = set(item["recording_ids"])
        if assigned.intersection(ids):
            raise ReviewedRfdetrDetectorCampaignError("split recording IDs overlap")
        assigned.update(ids)
    if len(split["sealed_test"]["recording_ids"]) < REQUIRED_SEALED_TEST_GROUPS:
        raise ReviewedRfdetrDetectorCampaignError("sealed_test has fewer than three recordings")
    inventory = raw["inventory"]
    if not isinstance(inventory, Mapping):
        raise ReviewedRfdetrDetectorCampaignError("inventory must be an object")
    selected_ids = selection["selected_recording_ids"]
    split_ids = [
        recording_id
        for partition in ("train", "validation", "sealed_test")
        for recording_id in split[partition]["recording_ids"]
    ]
    if selected_ids != sorted(split_ids):
        raise ReviewedRfdetrDetectorCampaignError(
            "selection.selected_recording_ids does not match the frozen split"
        )
    if raw["freeze_state"] == "frozen" and raw["coverage_gaps"]:
        raise ReviewedRfdetrDetectorCampaignError("frozen M0 manifest cannot contain coverage gaps")
    groups = raw["source_groups"]
    group_by_recording: dict[str, Mapping[str, Any]] = {}
    for index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            raise ReviewedRfdetrDetectorCampaignError(f"source_groups[{index}] must be an object")
        required_group_fields = {
            "recording_id",
            "session_id",
            "source_asset_id",
            "video_id",
            "source_sha256",
            "table_setup",
            "partition",
            "group_key",
        }
        if set(group) != required_group_fields:
            raise ReviewedRfdetrDetectorCampaignError(f"source_groups[{index}] has invalid fields")
        recording_id = group["recording_id"]
        if not isinstance(recording_id, str) or recording_id in group_by_recording:
            raise ReviewedRfdetrDetectorCampaignError("source group recording IDs are not unique")
        if group["partition"] not in {"train", "validation", "sealed_test"}:
            raise ReviewedRfdetrDetectorCampaignError("source group partition is invalid")
        group_core = {
            field: group[field]
            for field in (
                "recording_id",
                "session_id",
                "source_asset_id",
                "video_id",
                "source_sha256",
                "table_setup",
            )
        }
        if group["group_key"] != sha256_json(group_core):
            raise ReviewedRfdetrDetectorCampaignError("source group key does not match its fields")
        group_by_recording[recording_id] = group
    for field in (
        "recording_id",
        "session_id",
        "source_asset_id",
        "video_id",
        "source_sha256",
        "table_setup",
    ):
        values_by_partition: dict[Any, set[str]] = {}
        for group in groups:
            values_by_partition.setdefault(group[field], set()).add(group["partition"])
        if any(len(partitions) > 1 for partitions in values_by_partition.values()):
            raise ReviewedRfdetrDetectorCampaignError(
                f"source group field {field} crosses partitions"
            )
    for sample in raw["samples"]:
        if not isinstance(sample, Mapping) or sample.get("split") not in {
            "train",
            "validation",
            "sealed_test",
        }:
            raise ReviewedRfdetrDetectorCampaignError("sample has no valid frozen partition")
    if raw["inventory"].get("retained_frame_count") != len(raw["samples"]):
        raise ReviewedRfdetrDetectorCampaignError("inventory retained frame count is stale")
    if raw["inventory"].get("excluded_frame_count") != len(raw["excluded_frames"]):
        raise ReviewedRfdetrDetectorCampaignError("inventory excluded frame count is stale")
    if raw["inventory"].get("ineligible_outcome_count") != len(raw["ineligible_outcomes"]):
        raise ReviewedRfdetrDetectorCampaignError("inventory ineligible outcome count is stale")
    actual_side_counts = {side: 0 for side in sorted(CARD_SIDES)}
    for sample in raw["samples"]:
        targets = sample.get("targets")
        if not isinstance(targets, list):
            raise ReviewedRfdetrDetectorCampaignError("sample targets must be a list")
        for target in targets:
            if not isinstance(target, Mapping) or target.get("side", "unknown") not in CARD_SIDES:
                raise ReviewedRfdetrDetectorCampaignError("sample target has an invalid card side")
            actual_side_counts[target.get("side", "unknown")] += 1
    if dict(inventory["side_counts"]) != actual_side_counts:
        raise ReviewedRfdetrDetectorCampaignError("inventory side counts are stale")
    for field, value in inventory.items():
        if field == "side_counts":
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ReviewedRfdetrDetectorCampaignError(f"inventory.{field} is invalid")
        if value < 0:
            raise ReviewedRfdetrDetectorCampaignError(f"inventory.{field} must not be negative")
    if not isinstance(inventory.get("side_counts"), Mapping):
        raise ReviewedRfdetrDetectorCampaignError("inventory.side_counts is invalid")
    if set(inventory["side_counts"]) != set(CARD_SIDES) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in inventory["side_counts"].values()
    ):
        raise ReviewedRfdetrDetectorCampaignError("inventory.side_counts values are invalid")
    for reference in raw["references"]:
        if not isinstance(reference, Mapping) or reference.get("origin") != "corrected":
            raise ReviewedRfdetrDetectorCampaignError(
                "references must contain only corrected selections"
            )
    core = {key: raw[key] for key in expected_fields if key != "manifest_digest"}
    if raw["manifest_digest"] != sha256_json(core):
        raise ReviewedRfdetrDetectorCampaignError(
            "manifest_digest does not match manifest contents"
        )


def write_reviewed_rfdetr_detector_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    """Write one manifest and refuse to replace an existing different manifest."""

    validate_reviewed_rfdetr_detector_manifest(manifest)
    destination = Path(path).expanduser().resolve()
    payload = canonical_json_bytes(manifest) + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != payload:
        raise ReviewedRfdetrDetectorCampaignError(
            f"immutable RF-DETR detector M0 manifest already exists and differs: {destination}"
        )
    if not destination.exists():
        destination.write_bytes(payload)
    return destination


def render_reviewed_rfdetr_detector_human(manifest: Mapping[str, Any]) -> str:
    """Render a concise operator report for the M0 audit."""

    inventory = manifest["inventory"]
    split = manifest["split"]
    lines = [
        "Reviewed RF-DETR local visible-card detector M0",
        f"status: {manifest['freeze_state']}",
        f"recordings: {inventory['recording_count']}/{inventory['selected_recording_count']}",
        f"reviewed frames: {inventory['reviewed_frame_count']}",
        f"retained frames: {inventory['retained_frame_count']}",
        f"targets: {inventory['target_count']}",
        f"excluded frames: {inventory['excluded_frame_count']}",
        f"ineligible outcomes: {inventory['ineligible_outcome_count']}",
        "partitions: "
        + ", ".join(
            f"{name}={len(split[name]['recording_ids'])} groups"
            for name in ("train", "validation", "sealed_test")
        ),
        f"manifest digest: {manifest['manifest_digest']}",
    ]
    if manifest["coverage_gaps"]:
        lines.append("coverage gaps:")
        lines.extend(f"- {gap}" for gap in manifest["coverage_gaps"])
    return "\n".join(lines) + "\n"


__all__ = [
    "DEFAULT_PARTITION_RECORDING_IDS",
    "EXPECTED_INVENTORY",
    "EXPECTED_SIDE_COUNTS",
    "REVIEWED_RECORDING_IDS",
    "RFDETR_DETECTOR_CAMPAIGN_ID",
    "RFDETR_DETECTOR_MANIFEST_SCHEMA_VERSION",
    "ReviewedRfdetrDetectorCampaignError",
    "build_reviewed_rfdetr_detector_manifest",
    "default_reviewed_rfdetr_detector_recipe",
    "render_reviewed_rfdetr_detector_human",
    "validate_reviewed_rfdetr_detector_manifest",
    "write_reviewed_rfdetr_detector_manifest",
]
