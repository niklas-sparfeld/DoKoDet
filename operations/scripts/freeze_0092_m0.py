from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from doko_operations.cardevent_migration import _allowed_uses
from doko_operations.reviewed_visible_card_handoff import (
    validate_reviewed_visible_card_handoff,
)
from doko_operations.rfdetr_segmentation_campaign import (
    default_rfdetr_segmentation_recipe,
    sha256_json,
)

ELIGIBLE_MINIMUM = 18
SPLIT_IDS = {
    "train": [
        "cardeventnet-IMG_0095",
        "cardeventnet-IMG_0097",
        "cardeventnet-IMG_0636",
        "cardeventnet-IMG_0637",
        "cardeventnet-IMG_0638",
        "cardeventnet-IMG_0639",
        "cardeventnet-IMG_0640",
        "cardeventnet-IMG_0641",
        "cardeventnet-IMG_0643",
        "cardeventnet-IMG_0650",
        "cardeventnet-IMG_0653",
        "cardeventnet-IMG_0654",
        "cardeventnet-IMG_0655",
        "cardeventnet-IMG_0657",
        "cardeventnet-IMG_0659",
        "cardeventnet-IMG_0662",
    ],
    "validation": ["cardeventnet-IMG_0651", "cardeventnet-IMG_0658"],
    "sealed_test": ["cardeventnet-IMG_0656", "cardeventnet-IMG_0660"],
}
MINIMUM_SUPPORT = {
    "train": {"retained_frames": 30, "visible_card_targets": 100, "pile_targets": 30},
    "validation": {"retained_frames": 30, "visible_card_targets": 100, "pile_targets": 30},
    "sealed_test": {"retained_frames": 30, "visible_card_targets": 100, "pile_targets": 30},
}
BASELINE_BUNDLE_DIGEST = "018715420524a62335abd30c628382a1caba344f3bb98e1cbab884dfb4590fd9"
BASELINE_CHECKPOINT_DIGEST = "d89c5502b3ff01ed673c2ba04e0a8169c9d1efe3d99c064dcafefdc314aea3fa"
BASELINE_DECISION_DIGEST = "b386f8f403a8da30874c0cdd6a9812ba4357b7ac8e5457e2a9f613abb4379e9d"
PRETRAINED_CHECKPOINT_DIGEST = "3ad325094735f431aee9962a8d204d68eb5bfc393d53e7e836e70998fef5ea58"
TRAINING_BUDGET_SECONDS = 144_000
REFIT_BUDGET_SECONDS = 180_000
BASELINE_TRAINING_SECONDS = 6503.74
BASELINE_TRAINING_FRAMES = 42


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_bundle(bundle: Path, decision_path: Path) -> dict[str, Any]:
    manifest_path = bundle / "manifest.json"
    manifest = _read_json(manifest_path)
    decision = _read_json(decision_path)
    if manifest.get("bundle_digest") != BASELINE_BUNDLE_DIGEST:
        raise ValueError("0087 bundle digest differs from the selected candidate")
    if manifest.get("checkpoint_sha256") != BASELINE_CHECKPOINT_DIGEST:
        raise ValueError("0087 candidate checkpoint digest differs from the selected candidate")
    if decision.get("candidate_bundle_digest") != BASELINE_BUNDLE_DIGEST:
        raise ValueError("0087 decision does not select the pinned candidate bundle")
    if decision.get("decision_sha256") != BASELINE_DECISION_DIGEST:
        raise ValueError("0087 pretest decision digest differs from the published decision")
    if _file_sha256(manifest_path) != decision.get("input_sha256", {}).get("bundle_manifest"):
        raise ValueError("0087 bundle manifest differs from the locked pretest decision")
    checkpoint_name = manifest.get("checkpoint_file")
    if not isinstance(checkpoint_name, str):
        raise ValueError("0087 bundle has no checkpoint file")
    checkpoint = bundle / checkpoint_name
    if _file_sha256(checkpoint) != BASELINE_CHECKPOINT_DIGEST:
        raise ValueError("0087 candidate checkpoint bytes do not match the selected bundle")
    return {
        "path": ".runtime/rfdetr-segmentation-0087-m3-training/bundle",
        "manifest_path": "manifest.json",
        "bundle_digest": BASELINE_BUNDLE_DIGEST,
        "manifest_sha256": _file_sha256(manifest_path),
        "checkpoint_sha256": BASELINE_CHECKPOINT_DIGEST,
        "decision_path": "docs/reports/0087-M5_Pretest_Decision.json",
        "decision_sha256": BASELINE_DECISION_DIGEST,
    }


def _partition_lineage(recordings: list[dict[str, Any]]) -> None:
    fields = (
        "source_group_id",
        "session_id",
        "table_setup",
        "source_asset_id",
        "source_video_sha256",
    )
    for field in fields:
        owners: dict[str, str] = {}
        for split, recording_ids in SPLIT_IDS.items():
            for recording_id in recording_ids:
                item = next(
                    record for record in recordings if record["recording_id"] == recording_id
                )
                value = item["source_group"][field]
                previous = owners.setdefault(value, split)
                if previous != split:
                    raise ValueError(
                        f"{field} lineage overlaps between {previous} and {split}: {value}"
                    )


def _recipe(repository: Path, checkpoint: Path) -> dict[str, Any]:
    recipe = copy.deepcopy(
        default_rfdetr_segmentation_recipe(
            repository_root=repository,
            pretrained_checkpoint=checkpoint,
            device="mps",
        )
    )
    recipe["pretrained_checkpoint"]["path"] = ".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt"
    recipe["pretrained_checkpoint"]["sha256"] = PRETRAINED_CHECKPOINT_DIGEST
    recipe["model"]["class_names"] = ["visible_card", "card_pile"]
    recipe["model"]["num_classes"] = 2
    recipe["training"]["output_dir_name"] = "rfdetr-segmentation-0092"
    recipe["training"]["seed"] = 6701
    recipe["budget"] = {
        "wall_clock_seconds": TRAINING_BUDGET_SECONDS,
        "candidate_count": 1,
        "sweep": False,
    }
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
    recipe["validation"]["group_by"] = [
        "recording_id",
        "card_side",
        "visible_card_count_bucket",
    ]
    recipe["validation"]["minimum_gate"] = {
        "visible_card_mask_ap_50_95": "strictly_greater_than_0087_candidate_validation",
        "visible_card_recall": "strictly_greater_than_0087_candidate_validation",
        "card_pile_mask_ap_50_95": "strictly_greater_than_0087_candidate_validation",
        "card_pile_recall": "strictly_greater_than_0087_candidate_validation",
        "false_detections": "no_worse_than_0087_candidate_validation",
        "duplicate_detections": "no_worse_than_0087_candidate_validation",
        "empty_prediction_rate": "no_worse_than_0087_candidate_validation",
        "nonzero_visible_card_recall_per_sealed_test_recording": True,
        "sealed_test_pile_metrics": "report; no claim if target support is absent",
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
    return recipe


def build_manifest(
    repository: Path,
    handoff_path: Path,
    checkpoint: Path,
    baseline_bundle: Path,
) -> dict[str, Any]:
    handoff = _read_json(handoff_path)
    validate_reviewed_visible_card_handoff(handoff)
    if handoff.get("status") != "ready":
        raise ValueError("0086 M4 detection handoff is not ready")
    if handoff["summary"]["eligible_recording_count"] < ELIGIBLE_MINIMUM:
        raise ValueError("fewer than 18 eligible reviewed recordings are available")
    if handoff["summary"]["eligible_recording_count"] != sum(
        len(recording_ids) for recording_ids in SPLIT_IDS.values()
    ):
        raise ValueError("eligible recording count changed; review the frozen 0092 split")

    inventory_path = repository / "docs/reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json"
    inventory = _read_json(inventory_path)
    expected_candidates = set(inventory["scope"]["candidate_recordings"])
    handoff_candidates = set(handoff["source_inventory"]["candidate_recordings"])
    if expected_candidates != handoff_candidates:
        raise ValueError("0086 M0 inventory candidates differ from the current detection handoff")
    by_id = {item["recording_id"]: item for item in handoff["eligible_recordings"]}
    split_ids = {rid for ids in SPLIT_IDS.values() for rid in ids}
    if set(by_id) != split_ids:
        raise ValueError("eligible recording set changed; review the frozen 0092 split")
    source_group_ids = {item["source_group"]["source_group_id"] for item in by_id.values()}
    if len(source_group_ids) < ELIGIBLE_MINIMUM:
        raise ValueError("fewer than 18 distinct source groups are eligible")
    _partition_lineage(handoff["eligible_recordings"])

    prior_evaluation = handoff["policy"]["prior_evaluation_uses"]
    evaluated_ids = {
        recording_id for campaign in prior_evaluation for recording_id in campaign["recording_ids"]
    }
    if evaluated_ids.intersection(SPLIT_IDS["validation"] + SPLIT_IDS["sealed_test"]):
        raise ValueError(
            "0092 validation and sealed-test recordings must have no prior evaluation use"
        )
    if evaluated_ids.intersection(SPLIT_IDS["sealed_test"]):
        raise ValueError("0092 sealed-test recordings are not fresh")

    partitions: dict[str, Any] = {}
    for split, recording_ids in SPLIT_IDS.items():
        totals = {
            "reviewed_frames": 0,
            "retained_frames": 0,
            "visible_card_targets": 0,
            "pile_targets": 0,
            "pile_reviewed_frames": 0,
        }
        selected = []
        required_use = {"train": "train", "validation": "validation", "sealed_test": "test"}[split]
        for recording_id in recording_ids:
            item = by_id[recording_id]
            metadata_path = (
                repository / "data/operations/cardeventnet-imports" / recording_id / "metadata.json"
            )
            metadata = _read_json(metadata_path)
            permission = metadata.get("source_permission")
            if permission != item["source_permission"]:
                raise ValueError(f"{recording_id} permission differs from original metadata")
            permission_uses = _allowed_uses(permission)
            if required_use not in permission_uses:
                raise ValueError(f"{recording_id} permission does not allow {split}")
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
            selected.append(
                {
                    "recording_id": recording_id,
                    "source_group": item["source_group"],
                    "source_permission": permission,
                    "permission_allowed_uses": permission_uses,
                    "permission_metadata_path": metadata_path.relative_to(repository).as_posix(),
                    "permission_metadata_sha256": _file_sha256(metadata_path),
                    "recorded_allowed_uses": item["allowed_uses"],
                    "prior_partitions": item["prior_partitions"],
                    "event_revision_id": item["event_reference"]["revision_id"],
                    "event_content_sha256": item["event_reference"]["content_sha256"],
                    "reference_revision_id": reference["revision_id"],
                    "reference_manifest_sha256": reference["manifest_sha256"],
                    "reference_content_sha256": reference["content_sha256"],
                    "counts": counts,
                }
            )
        for metric, minimum in MINIMUM_SUPPORT[split].items():
            if totals[metric] < minimum:
                raise ValueError(f"{split} {metric} support is below {minimum}")
        partitions[split] = {"recordings": selected, "counts": totals}

    if not checkpoint.is_file() or _file_sha256(checkpoint) != PRETRAINED_CHECKPOINT_DIGEST:
        raise ValueError("pinned RF-DETR pretrained checkpoint is missing or has changed")
    baseline_decision = repository / "docs/reports/0087-M5_Pretest_Decision.json"
    pinned_baseline = _verify_bundle(baseline_bundle, baseline_decision)
    prior_manifest = _read_json(
        repository / "docs/reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json"
    )
    prior_training_ids = [
        item["recording_id"] for item in prior_manifest["partitions"]["train"]["recordings"]
    ]
    recipe = _recipe(repository, checkpoint)
    excluded = {item["recording_id"]: item for item in handoff["excluded_recordings"]}
    dispositions = handoff.get("recording_dispositions", {}).get("recordings", {})
    candidate_decisions = []
    for recording_id in sorted(expected_candidates):
        if recording_id in by_id:
            split = next(name for name, ids in SPLIT_IDS.items() if recording_id in ids)
            candidate_decisions.append(
                {"recording_id": recording_id, "disposition": "included", "split": split}
            )
        else:
            record = excluded.get(recording_id, {})
            candidate_decisions.append(
                {
                    "recording_id": recording_id,
                    "disposition": record.get(
                        "disposition",
                        dispositions.get(recording_id, {}).get("disposition", "excluded"),
                    ),
                    "reasons": record.get("reasons", []),
                }
            )

    core = {
        "schema_version": "rfdetr-reviewed-campaign-manifest/v1",
        "campaign_id": "0092-m0-expanded-reviewed-rfdetr-campaign",
        "milestone": "M0",
        "freeze_state": "frozen",
        "training_readiness": "ready",
        "training_readiness_gaps": [],
        "source_handoff": {
            "path": ".runtime/0086-m4/detection-handoff.json",
            "handoff_sha256": handoff["handoff_sha256"],
            "file_sha256": _file_sha256(handoff_path),
            "content_schema": "visible-card-data/v2",
            "eligible_recording_count": len(by_id),
            "distinct_source_group_count": len(source_group_ids),
            "candidate_count": handoff["summary"]["candidate_recording_count"],
        },
        "inventory": {
            "path": "docs/reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json",
            "manifest_sha256": inventory["manifest_sha256"],
        },
        "candidate_dispositions": candidate_decisions,
        "prior_evaluation_use": prior_evaluation,
        "prior_candidate_training": {
            "0087": {
                "manifest_sha256": prior_manifest["manifest_sha256"],
                "recording_ids": prior_training_ids,
            }
        },
        "prior_evaluated_groups_assigned_to_training": sorted(
            evaluated_ids.intersection(SPLIT_IDS["train"])
        ),
        "split_policy": (
            "source_group_disjoint/v1; validation and sealed test have no prior evaluation use; "
            "previously evaluated groups may enter training only"
        ),
        "split_rationale": {
            "validation": (
                "Two fresh groups with reviewed pile targets; neither was used "
                "by a prior evaluation."
            ),
            "sealed_test": (
                "Two fresh groups with reviewed pile targets; neither was opened by 0087 "
                "or another campaign."
            ),
            "prior_evaluation_groups": "IMG_0097 and IMG_0654 are assigned to training only.",
        },
        "partitions": partitions,
        "minimum_support": MINIMUM_SUPPORT,
        "comparison_design": {
            "candidate_count": 1,
            "candidate": "expanded_real_only",
            "baseline": pinned_baseline,
            "pretrained_baseline": {
                "path": ".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt",
                "sha256": PRETRAINED_CHECKPOINT_DIGEST,
                "package": "rfdetr==1.9.4",
            },
            "synthetic_data": "excluded",
            "runtime_default": "gemini",
        },
        "recipe": recipe,
        "recipe_sha256": sha256_json(recipe),
        "checkpoint": {
            "path": ".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt",
            "sha256": PRETRAINED_CHECKPOINT_DIGEST,
            "package": "rfdetr==1.9.4",
            "class": "RFDETRSegMedium",
            "resolution": [432, 432],
        },
        "resource_budget": {
            "candidate_count": 1,
            "candidate_wall_clock_seconds": TRAINING_BUDGET_SECONDS,
            "final_refit_wall_clock_seconds": REFIT_BUDGET_SECONDS,
            "estimate_basis": (
                "0087 used 6503.74 seconds for 42 retained training frames. "
                "Scale by 0092 partition frame counts, then add about 35 percent."
            ),
            "candidate_linear_estimate_seconds": round(
                BASELINE_TRAINING_SECONDS
                * partitions["train"]["counts"]["retained_frames"]
                / BASELINE_TRAINING_FRAMES,
                2,
            ),
            "refit_linear_estimate_seconds": round(
                BASELINE_TRAINING_SECONDS
                * handoff["summary"]["retained_frame_count"]
                / BASELINE_TRAINING_FRAMES,
                2,
            ),
            "sweeps": False,
        },
        "quality_gates": recipe["validation"]["minimum_gate"],
        "sealed_test_policy": (
            "Lock the decision after validation; evaluate baseline and candidate once. "
            "Do not revise gates or recipes from sealed-test results."
        ),
        "identity_review_required": False,
        "source_bytes_verified": False,
    }
    return {**core, "manifest_sha256": sha256_json(core)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the expanded reviewed RF-DETR 0092 M0 campaign."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--handoff", type=Path, default=Path(".runtime/0086-m4/detection-handoff.json")
    )
    parser.add_argument(
        "--checkpoint", type=Path, default=Path(".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt")
    )
    parser.add_argument(
        "--baseline-bundle",
        type=Path,
        default=Path(".runtime/rfdetr-segmentation-0087-m3-training/bundle"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/reports/0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Manifest.json"),
    )
    args = parser.parse_args()
    repository = args.repository_root.expanduser().resolve()

    def resolved(path: Path) -> Path:
        return path.expanduser() if path.is_absolute() else repository / path

    manifest = build_manifest(
        repository,
        resolved(args.handoff),
        resolved(args.checkpoint),
        resolved(args.baseline_bundle),
    )
    output = resolved(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{manifest['training_readiness']}: "
        f"{manifest['source_handoff']['eligible_recording_count']} eligible recordings; "
        f"manifest {manifest['manifest_sha256']} written to {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
