from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from doko_operations.reviewed_visible_card_handoff import validate_reviewed_visible_card_handoff
from doko_operations.rfdetr_segmentation_campaign import (
    default_rfdetr_segmentation_recipe,
    sha256_json,
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(repository: Path, checkpoint: Path) -> dict[str, Any]:
    handoff_path = repository / "docs/reports/0086-M2_Detection_Only_Handoff.json"
    handoff = _read_json(handoff_path)
    validate_reviewed_visible_card_handoff(handoff)
    if handoff["status"] != "ready":
        raise ValueError("0086 detection-only handoff is not ready")

    by_id = {item["recording_id"]: item for item in handoff["eligible_recordings"]}
    split_ids = {
        "train": ["cardeventnet-IMG_0095", "cardeventnet-IMG_0097"],
        "validation": ["cardeventnet-IMG_0654"],
        "sealed_test": [],
    }
    if set(by_id) != {recording_id for ids in split_ids.values() for recording_id in ids}:
        raise ValueError("eligible handoff recordings changed; review the 0087 split before freeze")

    prior_evaluation = handoff["policy"]["prior_evaluation_uses"]
    previously_evaluated = {
        recording_id for campaign in prior_evaluation for recording_id in campaign["recording_ids"]
    }
    if previously_evaluated.intersection(split_ids["validation"] + split_ids["sealed_test"]):
        raise ValueError("validation or sealed-test group has prior evaluation use")

    partitions: dict[str, Any] = {}
    selected_groups: set[str] = set()
    selected_lineage: dict[str, set[str]] = {
        field: set()
        for field in ("session_id", "table_setup", "source_asset_id", "source_video_sha256")
    }
    for split, recording_ids in split_ids.items():
        recordings = []
        totals = {
            "reviewed_frames": 0,
            "retained_frames": 0,
            "visible_card_targets": 0,
            "pile_targets": 0,
            "pile_reviewed_frames": 0,
        }
        for recording_id in recording_ids:
            item = by_id[recording_id]
            required_use = {"train": "train", "validation": "validation", "sealed_test": "test"}[
                split
            ]
            if required_use not in item["allowed_uses"]:
                raise ValueError(f"{recording_id} source permission does not allow {split}")
            group = item["source_group"]["source_group_id"]
            if group in selected_groups:
                raise ValueError("source group appears in more than one 0087 partition")
            selected_groups.add(group)
            for field in selected_lineage:
                value = item["source_group"][field]
                if value in selected_lineage[field]:
                    raise ValueError(f"source group lineage overlaps for {field}")
                selected_lineage[field].add(value)
            reference = item["reference"]
            counts = {
                "reviewed_frames": reference["reviewed_frame_count"],
                "retained_frames": reference["retained_frame_count"],
                "visible_card_targets": reference["visible_card_target_count"],
                "pile_targets": reference["pile_target_count"],
                "pile_reviewed_frames": reference["pile_reviewed_frame_count"],
            }
            for key, value in counts.items():
                totals[key] += value
            recordings.append(
                {
                    "recording_id": recording_id,
                    "source_group": item["source_group"],
                    "source_permission": item["source_permission"],
                    "allowed_uses": item["allowed_uses"],
                    "prior_partitions": item["prior_partitions"],
                    "reference_revision_id": reference["revision_id"],
                    "reference_manifest_sha256": reference["manifest_sha256"],
                    "reference_content_sha256": reference["content_sha256"],
                    "event_revision_id": item["event_reference"]["revision_id"],
                    "event_content_sha256": item["event_reference"]["content_sha256"],
                    "counts": counts,
                }
            )
        partitions[split] = {"recordings": recordings, "counts": totals}

    checkpoint_digest = _file_sha256(checkpoint)
    recipe = default_rfdetr_segmentation_recipe(
        repository_root=repository,
        pretrained_checkpoint=checkpoint,
        device="mps",
    )
    recipe["pretrained_checkpoint"]["path"] = ".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt"
    recipe["pretrained_checkpoint"]["sha256"] = checkpoint_digest
    recipe["model"]["class_names"] = ["visible_card", "card_pile"]
    recipe["model"]["num_classes"] = 2
    recipe["training"]["output_dir_name"] = "rfdetr-segmentation-0087"
    recipe["budget"] = {"wall_clock_seconds": 7200, "candidate_count": 1, "sweep": False}
    recipe["data_contract"] = {
        **recipe["data_contract"],
        "categories": [
            {"id": 1, "name": "visible_card", "supercategory": "card"},
            {"id": 2, "name": "card_pile", "supercategory": "card"},
        ],
        "pile_mask_source": "reviewed_coarse_pile_region",
        "pixel_ownership": "reviewed-card-pixels-priority-v1",
        "pile_mask_encoding": "coco-uncompressed-rle-column-major-v1",
        "partition_policy": "source_group_disjoint/v1",
        "test_partition": "sealed_test",
    }
    recipe["validation"]["metrics"] = [
        "per_class_mask_ap_50_95",
        "per_class_mask_ap50",
        "per_class_box_ap_50_95",
        "per_class_recall",
        "class_confusion",
        "pile_contained_card_predictions",
        "card_recall_near_piles",
        "false_detections",
        "duplicate_detections",
        "empty_prediction_rate",
        "per_recording_coverage",
    ]
    recipe["validation"]["group_by"] = ["recording_id", "card_side", "visible_card_count_bucket"]
    recipe["validation"]["minimum_gate"] = {
        "visible_card_mask_ap_50_95": "strictly_greater_than_pretrained_validation",
        "visible_card_recall": "strictly_greater_than_pretrained_validation",
        "card_pile_mask_ap_50_95": "report_when_supported; no sealed-test pile claim",
        "card_pile_recall": "nonzero_on_validation_if_supported",
        "nonzero_visible_card_recall_per_sealed_test_recording": True,
        "false_detections": "no_worse_than_pretrained_validation",
        "duplicate_detections": "no_worse_than_pretrained_validation",
        "empty_prediction_rate": "no_worse_than_pretrained_validation",
    }
    recipe["validation"]["slices"] = [
        "ordinary_overlapping_tricks_confusion",
        "card_pile_localization_and_classification",
        "fragments_inside_piles",
        "individual_card_recall_near_piles",
        "small_cards_when_supported",
        "frame_edges_when_supported",
        "human_hand_pixels_when_supported",
    ]

    readiness_gaps = []
    minimum_support = {
        "train": {"retained_frames": 30, "visible_card_targets": 100, "pile_targets": 30},
        "validation": {"retained_frames": 30, "visible_card_targets": 100, "pile_targets": 30},
    }
    for split, minimums in minimum_support.items():
        for metric, minimum in minimums.items():
            if partitions[split]["counts"][metric] < minimum:
                readiness_gaps.append(f"{split} {metric} support is below frozen minimum {minimum}")
    if not checkpoint.is_file():
        readiness_gaps.append("pinned pretrained checkpoint is missing")

    core = {
        "schema_version": "rfdetr-reviewed-campaign-manifest/v1",
        "campaign_id": "0087-m0-reviewed-rfdetr-campaign",
        "milestone": "M0",
        "freeze_state": "frozen",
        "training_readiness": "blocked" if readiness_gaps else "ready",
        "training_readiness_gaps": readiness_gaps,
        "source_handoff": {
            "path": "docs/reports/0086-M2_Detection_Only_Handoff.json",
            "sha256": handoff["handoff_sha256"],
            "content_schema": "visible-card-data/v2",
            "eligible_recording_count": len(by_id),
        },
        "protected_exclusions": handoff["protected_exclusions"],
        "prior_evaluation_use": prior_evaluation,
        "prior_candidate_training": {
            "cardeventnet-IMG_0095": {"campaign": "0068", "partition": "train"},
            "cardeventnet-IMG_0097": {"campaign": "0068", "partition": "train"},
            "cardeventnet-IMG_0654": {"campaign": "0068", "partition": "not-in-frozen-campaign"},
        },
        "split_policy": "source_group_disjoint/v1; no protected group enters training",
        "partitions": partitions,
        "comparison_design": {
            "m3_candidate_count": 1,
            "candidate": "corrected_real_only",
            "control": "pinned_pretrained_checkpoint",
            "paired_retraining_control": False,
            "paired_control_reason": (
                "No unchanged common validation partition and compatible source-group "
                "assignments exist."
            ),
            "m4_candidate_count": 1,
            "m4_candidate": "fixed_real_plus_synthetic_mixture",
            "real_sample_exposure": "equal_to_m3_corrected_real_only",
        },
        "minimum_support": minimum_support,
        "recipe": recipe,
        "recipe_sha256": sha256_json(recipe),
        "checkpoint": {
            "path": ".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt",
            "sha256": checkpoint_digest,
            "package": "rfdetr==1.9.4",
            "class": "RFDETRSegMedium",
            "resolution": [432, 432],
        },
        "resource_budget": {"m3_wall_clock_seconds": 7200, "m4_wall_clock_seconds": 7200},
        "test_policy": (
            "No sealed test is available. Record candidate test results as unavailable; do not "
            "relabel train-only groups as test data."
        ),
        "sealed_test_unavailable_reason": (
            "IMG_0095 and IMG_0097 allow train use only. IMG_0654 is the only eligible "
            "independent group that allows validation or test use, so it is reserved "
            "for validation."
        ),
        "identity_review_required": False,
    }
    return {**core, "manifest_sha256": sha256_json(core)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze the reviewed RF-DETR 0087 M0 campaign.")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path(".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json"),
    )
    args = parser.parse_args()
    repository = args.repository_root.expanduser().resolve()
    checkpoint = args.checkpoint.expanduser()
    if not checkpoint.is_absolute():
        checkpoint = repository / checkpoint
    manifest = build_manifest(repository, checkpoint.resolve())
    output = args.output if args.output.is_absolute() else repository / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    retained_frames = sum(
        partition["counts"]["retained_frames"] for partition in manifest["partitions"].values()
    )
    print(
        f"{manifest['freeze_state']}: {retained_frames} retained frames; "
        f"manifest {manifest['manifest_sha256']} written to {output}"
    )
    return 0 if manifest["freeze_state"] == "frozen" else 1


if __name__ == "__main__":
    raise SystemExit(main())
