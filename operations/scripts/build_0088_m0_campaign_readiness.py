#!/usr/bin/env python3
"""Build the deterministic, read-only 0088 M0 readiness manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DEFAULT = Path("docs/reports/0088-M0_Campaign_Readiness.json")
HANDOFF = Path("docs/reports/0086-M5_DINO_Campaign_Handoff.json")

PARTITIONS = {
    "training": [
        "cardeventnet-IMG_0097",
        "cardeventnet-IMG_0636",
        "cardeventnet-IMG_0637",
        "cardeventnet-IMG_0638",
        "cardeventnet-IMG_0639",
        "cardeventnet-IMG_0640",
        "cardeventnet-IMG_0641",
        "cardeventnet-IMG_0643",
        "cardeventnet-IMG_0650",
        "cardeventnet-IMG_0651",
        "cardeventnet-IMG_0653",
        "cardeventnet-IMG_0655",
        "cardeventnet-IMG_0658",
    ],
    "model_selection": ["cardeventnet-IMG_0657", "cardeventnet-IMG_0662"],
    "confidence_calibration": ["cardeventnet-IMG_0095"],
    "final_test": ["cardeventnet-IMG_0659"],
    "excluded": [
        "cardeventnet-IMG_0654",
        "cardeventnet-IMG_0656",
        "cardeventnet-IMG_0660",
    ],
}

INPUT_PATHS = {
    "0086_m0_partition_inventory": Path(
        "docs/reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json"
    ),
    "0086_m5_campaign_handoff": HANDOFF,
    "0093_m5_input_handoff": Path("docs/reports/0093-M5_Visual_Identity_Input_Handoff.md"),
    "0094_m9_recipe_handoff": Path("docs/reports/0094-M9_Local_Recipe_Handoff.md"),
    "identity_classifier_implementation": Path(
        "table_evidence_analyzer/src/table_evidence_analyzer/card_classification.py"
    ),
    "gemini_model_configuration": Path("backend/src/dokodetector_backend/config.py"),
    "0043_poc_evaluation": Path(
        "data/operations/dinov3-identity-bundles/0043-m1-dinov3-identity-"
        "75000a5eec53a52f088f9e6e/evaluation.json"
    ),
    "0087_sealed_test_lock": Path("docs/reports/0087-M5_Pretest_Decision.json"),
    "0092_sealed_test_lock": Path("docs/reports/0092-M3_Pretest_Decision.json"),
    "pretrained_weights": Path(
        "data/operations/dinov3-identity-bundles/0043-m1-dinov3-identity-"
        "75000a5eec53a52f088f9e6e/model.safetensors"
    ),
    "pretrained_bundle_manifest": Path(
        "data/operations/dinov3-identity-bundles/0043-m1-dinov3-identity-"
        "75000a5eec53a52f088f9e6e/manifest.json"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()

    handoff = read_json(ROOT / HANDOFF)
    inventory = read_json(ROOT / INPUT_PATHS["0086_m0_partition_inventory"])
    recordings = {item["recording_id"]: item for item in handoff["recordings"]}
    inventory_recordings = {item["recording_id"]: item for item in inventory["recordings"]}
    all_recordings = set(recordings)
    partition_ids = [recording_id for values in PARTITIONS.values() for recording_id in values]
    if len(partition_ids) != len(set(partition_ids)):
        raise SystemExit("A recording appears in more than one frozen partition")
    if set(partition_ids) != all_recordings:
        raise SystemExit("Frozen partitions do not cover the exact 0086 M5 recording set")
    training_ids = set(PARTITIONS["training"])
    for recording_id in all_recordings:
        prior_dino_partition = inventory_recordings[recording_id].get("dino_partition")
        if prior_dino_partition == "train" and recording_id not in training_ids:
            raise SystemExit(f"Frozen DINO split moves prior training source {recording_id}")
        if prior_dino_partition == "validation":
            raise SystemExit(f"Frozen DINO split includes prior validation source {recording_id}")

    partition_support: dict[str, dict[str, dict[str, int]]] = {}
    for partition, recording_ids in PARTITIONS.items():
        class_counts = {target: 0 for target in handoff["target"]["classes"]}
        class_groups = {target: set() for target in handoff["target"]["classes"]}
        for recording_id in recording_ids:
            recording = recordings[recording_id]
            source_group = recording["source_group"]["source_group_id"]
            for target, count in recording["class_support"].items():
                if count:
                    class_counts[target] += count
                    class_groups[target].add(source_group)
        partition_support[partition] = {
            target: {"samples": count, "source_groups": len(class_groups[target])}
            for target, count in class_counts.items()
        }

    groups = {
        partition: [
            {
                "recording_id": recording_id,
                "source_group_id": recordings[recording_id]["source_group"]["source_group_id"],
                "positive_crop_count": recordings[recording_id]["positive_crop_count"],
                "prior_assignments": {
                    key: inventory_recordings[recording_id].get(key)
                    for key in ("cardeventnet_partition", "dino_partition", "rfdetr_partition")
                },
            }
            for recording_id in recording_ids
        ]
        for partition, recording_ids in PARTITIONS.items()
    }

    system_holdout_ids = sorted(
        recording_id
        for recording_id, recording in inventory_recordings.items()
        if recording.get("disposition") == "excluded-system-holdout"
    )
    system_holdout_groups = sorted(
        {
            inventory_recordings[recording_id]["source_group_id"]
            for recording_id in system_holdout_ids
        }
    )
    candidate_group_ids = {
        recording["source_group"]["source_group_id"] for recording in recordings.values()
    }
    if len(candidate_group_ids) != handoff["summary"]["source_group_count"]:
        raise SystemExit("The 0086 M5 source-group count is not unique")
    if candidate_group_ids & set(system_holdout_groups):
        raise SystemExit("An 0086 M5 group crosses a protected system holdout boundary")
    rfdetr_sealed_ids = inventory["rfdetr_source"]["partition_recordings"]["sealed_test"]
    rfdetr_sealed_groups = sorted(
        {
            inventory_recordings[recording_id]["source_group_id"]
            for recording_id in rfdetr_sealed_ids
        }
    )
    if candidate_group_ids & set(rfdetr_sealed_groups):
        raise SystemExit("An 0086 M5 group crosses the 0068 RF-DETR sealed-test boundary")
    if set(PARTITIONS["excluded"]) != {
        "cardeventnet-IMG_0654",
        "cardeventnet-IMG_0656",
        "cardeventnet-IMG_0660",
    }:
        raise SystemExit("The 0087/0092 sealed-test exclusions changed")
    if set(PARTITIONS["excluded"]) & (
        set(PARTITIONS["training"])
        | set(PARTITIONS["model_selection"])
        | set(PARTITIONS["confidence_calibration"])
        | set(PARTITIONS["final_test"])
    ):
        raise SystemExit("A sealed-test recording entered an evaluation partition")

    data = {
        "schema_version": "0088-m0-campaign-readiness/v1",
        "frozen_at": "2026-10-16",
        "status": "blocked",
        "campaign_input_revision": "566919e76",
        "inputs": {
            name: {"path": path.as_posix(), "sha256": sha256(ROOT / path)}
            for name, path in INPUT_PATHS.items()
        },
        "source_pool": {
            "handoff_status": handoff["handoff_status"],
            "recording_count": len(recordings),
            "source_group_count": handoff["summary"]["source_group_count"],
            "positive_crop_count": handoff["summary"]["positive_crop_count"],
            "recordings_with_positive_crops": handoff["summary"]["recordings_with_positive_crops"],
            "supported_class_count": handoff["summary"]["supported_class_count"],
            "target_classes": handoff["target"]["classes"],
            "face_down": handoff["campaign_specific_gaps"]["face_down_support"],
            "back_design_unspecified_recordings": handoff["campaign_specific_gaps"][
                "back_design_unspecified_recordings"
            ],
            "recordings_without_positive_crops": handoff["campaign_specific_gaps"][
                "recordings_without_positive_crops"
            ],
            "m4_source_bytes_verified": handoff["campaign_specific_gaps"][
                "m4_source_bytes_were_verified"
            ],
            "per_class_support": handoff["class_support"],
        },
        "protected_source_groups": {
            "0087_sealed_test_recordings": ["cardeventnet-IMG_0654"],
            "0092_sealed_test_recordings": ["cardeventnet-IMG_0656", "cardeventnet-IMG_0660"],
            "0087_sealed_test_source_group_ids": [
                recordings["cardeventnet-IMG_0654"]["source_group"]["source_group_id"]
            ],
            "0092_sealed_test_source_group_ids": [
                recordings[recording_id]["source_group"]["source_group_id"]
                for recording_id in ("cardeventnet-IMG_0656", "cardeventnet-IMG_0660")
            ],
            "0068_sealed_test_recordings": rfdetr_sealed_ids,
            "0068_sealed_test_source_group_ids": rfdetr_sealed_groups,
            "system_holdout_recordings": system_holdout_ids,
            "system_holdout_source_group_ids": system_holdout_groups,
            "system_and_0068_protected_group_overlap_with_0086_m5_candidates": [],
            "permanent_0086_exclusion": ["cardeventnet-IMG_0092"],
            "deferred_0086_recording": ["cardeventnet-IMG_0096"],
        },
        "frozen_partitions": groups,
        "partition_support": partition_support,
        "support_floors": {
            "training": {"samples_per_class": 20, "source_groups_per_class": 5},
            "model_selection": {"samples_per_class": 10, "source_groups_per_class": 3},
            "confidence_calibration": {"samples_per_class": 10, "source_groups_per_class": 3},
            "final_test": {"samples_per_class": 10, "source_groups_per_class": 3},
        },
        "quality_gates": {
            "face_up_top_1_minimum": 0.98,
            "gemini_maximum_deficit": 0.01,
            "face_down_precision_minimum": 0.95,
            "face_down_recall_minimum": 0.95,
            "false_face_down_rate_on_face_up_maximum": 0.01,
            "calibrated_top_1_probability_threshold": 0.9,
            "high_confidence_error_maximum": 0.01,
            "high_confidence_coverage_minimum": 0.9,
            "usable_prediction_coverage_minimum": 0.9,
            "latency_p95_ms_maximum": 100,
            "model_load_seconds_maximum": 10,
            "peak_memory_fraction_of_physical_ram_maximum": 0.75,
            "face_down_pixel_prediction_required": True,
            "report": [
                "top_3",
                "macro_f1",
                "per_class_confusion",
                "per_recording_and_source_group_results",
                "confident_errors",
                "usable_prediction_coverage",
                "all_supported_cards_correct_per_frame",
                "grouped_uncertainty",
                "local_latency_and_peak_memory",
            ],
            "calibration_changes_raw_top_1": False,
            "uncertainty": {
                "per_class_interval": "Wilson 95 percent interval",
                "group_variation": "source-group bootstrap 95 percent interval",
                "bootstrap_replicates": 10000,
                "bootstrap_seed": 17088,
                "report_as_insufficient": "fewer than 3 independent groups",
            },
            "selection_rule": (
                "prefer a challenger only when top-1 improves by at least 1 percentage point, "
                "the paired source-group bootstrap interval excludes zero, and no class falls "
                "by more than 2 percentage points; otherwise keep the qualifying control or "
                "report inconclusive"
            ),
        },
        "candidate_ladder": [
            {"name": "224-cls-frozen-real", "required": True},
            {"name": "384-cls-frozen-real", "required": True, "matched_to": "224-cls-frozen-real"},
            {
                "name": "448-cls-frozen-real",
                "required": False,
                "gate": (
                    "at least 80 percent of eligible training crops have native long sides >= "
                    "448 px and MPS batch-1 preflight uses <= 75 percent of physical memory"
                ),
            },
            {"name": "selected-size-cls-mean-patch-frozen-real", "required": True},
            {
                "name": "selected-size-last-two-blocks-real",
                "required": False,
                "gate": "best frozen candidate misses the main target and all support floors pass",
                "encoder_learning_rate_ratio": 0.1,
            },
        ],
        "fit_budget": {
            "primary_fit_limit": 6,
            "stability_fit_limit": 4,
            "epochs": 8,
            "seeds": {"primary": 17, "additional": [101, 202]},
            "batch_size": 1,
            "precision": "fp32",
            "device": "mps",
            "optimizer": {"name": "AdamW", "learning_rate": 0.001, "weight_decay": 0.0},
            "scheduler": "CosineAnnealingLR",
            "sampling": "class_source_weighted_with_replacement",
            "augmentation": "source_safe_v2",
            "wall_time_limit_hours_per_fit": 2,
            "oom_or_timeout": "skip_candidate_without_changing_recipe",
            "checkpoint": "retain_resumable_checkpoint",
        },
        "gemini_reference": {
            "model": "gemini-3.8-flash",
            "api_version": "v1beta",
            "thinking_level": "low",
            "timeout_seconds": 120,
            "source": "model and classifier implementation pinned by campaign_input_revision",
            "input": (
                "same reviewed native PPM crop; classifier converts it to PNG; DINO uses its "
                "frozen resize and letterbox transform"
            ),
            "prompt": (
                "This image is a transformed crop of one visible Doppelkopf playing card.\n\n"
                "Identify its visible suit and rank using the canonical card label in the response "
                "schema. Return FACE_DOWN when the visible card back is positively recognizable. "
                "Return UNKNOWN when the crop is too occluded, too blurred, or otherwise cannot "
                "support a reliable visual classification. Do not guess. This is visual evidence "
                "only; do not infer a physical card, a card play, a trick, or game state.\n"
            ),
            "response_schema": {
                "required": ["card"],
                "allowed_values": [*handoff["target"]["classes"], "UNKNOWN"],
                "additional_properties": False,
            },
            "max_requests": 250,
            "requests_per_crop": 1,
            "automatic_retries": 0,
            "spend_cap_usd": 10,
            "failures_count_in_coverage": True,
            "final_test_before_m13": "prohibited",
        },
        "command_templates": {
            "root_variables": {
                "RUN": ".runtime/dinov3-identity-0088",
                "WEIGHTS": (
                    "data/operations/dinov3-identity-bundles/0043-m1-dinov3-identity-"
                    "75000a5eec53a52f088f9e6e"
                ),
            },
            "primary_fit": [
                "mise exec -- uv run --project table_evidence_analyzer \\",
                "  --group training table-analyzer train-dinov3-identity \\",
                '  --dataset "$RUN/data/dataset.json" --split "$RUN/data/split.json" \\',
                '  --artifacts "$RUN/data/artifact-index.json" \\',
                '  --identity-config "$RUN/recipes/224-cls.json" \\',
                '  --weights-root "$WEIGHTS" --campaign-manifest "$RUN/manifest.json" \\',
                '  --output "$RUN/results/224-cls" --seed 17 --epochs 8 --batch-size 1 \\',
                "  --learning-rate 0.001 --weight-decay 0 --encoder-training frozen \\",
                "  --device mps --precision fp32",
            ],
            "resume": (
                'Repeat primary_fit with --resume "$RUN/results/224-cls/checkpoint-last.pt".'
            ),
            "matched_candidate_changes": {
                "384": (
                    "Use recipes/384-cls.json and results/384-cls; keep every other argument fixed."
                ),
                "448": (
                    "Use recipes/448-cls.json and results/448-cls only when its frozen gate passes."
                ),
                "pooled_features": (
                    "Use recipes/<selected-size>-cls-mean-patch.json and a matching results path."
                ),
                "adapted_encoder": (
                    "Use recipes/<selected-size>-cls-adapted.json, --encoder-training "
                    "last_two_blocks, and the frozen 0.0001 learning rate."
                ),
            },
        },
        "branch_decisions": {
            "rectification": "not required; no new runtime rectified policy",
            "synthetic": (
                "skip unless a measured training-only robustness gap and eligible training-only "
                "contributors are declared before M8"
            ),
            "final_test": (
                "membership frozen; no crop rendering, scoring, or model prediction before M13"
            ),
        },
        "readiness_gaps": [
            "three FACE_DOWN crops in three source groups do not meet the per-view support floors",
            "FACE_DOWN has zero confidence-calibration examples under the frozen split",
            "the final test has only one positive-crop source group",
            "back design is unspecified for every FACE_DOWN contributor",
            "0086 M5 reports that M4 source bytes were not verified",
            "eight eligible recordings currently have no positive crops",
        ],
        "authorized_work": {
            "crop_materialization": False,
            "gemini_requests": False,
            "model_fitting": False,
            "final_test_predictions": False,
        },
    }

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
