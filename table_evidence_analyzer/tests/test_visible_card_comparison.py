from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_visible_card_review_freeze import _partitions, _pilot, _queue

from table_evidence_analyzer.visible_card_comparison import (
    VISIBLE_CARD_COMPARISON_CANDIDATE_SCHEMA,
    VISIBLE_CARD_COMPARISON_POLICIES,
    VISIBLE_CARD_CROP_EVALUATION_SCHEMA,
    VisibleCardComparisonConfig,
    VisibleCardComparisonError,
    compare_visible_card_detectors,
)
from table_evidence_analyzer.visible_card_review import ReviewedVisibleCard
from table_evidence_analyzer.visible_card_review_freeze import (
    freeze_visible_card_review_data,
    load_frozen_visible_card_review_data,
)
from table_evidence_analyzer.visible_card_training import VISIBLE_CARD_TRAINING_RUN_SCHEMA
from table_evidence_analyzer.visible_cards import (
    NormalizedBox,
    NormalizedPoint,
    ProviderResult,
    VisibleCardProposal,
    VisibleCardRequest,
    write_run_artifact,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _freeze(tmp_path: Path) -> dict:
    output = tmp_path / "freeze"
    freeze_visible_card_review_data(
        _queue(tmp_path),
        _pilot(tmp_path),
        _partitions(tmp_path),
        output,
    )
    return load_frozen_visible_card_review_data(output)


def _recipe() -> dict:
    value = {
        "model_variant": "RFDETRLarge",
        "package": {"name": "rfdetr", "version": "1.9.4"},
        "class_map": {"1": "visible_card"},
        "input_size": [704, 704],
        "preprocessing": "rfdetr_standard_704_v1",
        "device": "cuda:0",
        "seed": 37,
        "epochs": 20,
        "confidence_threshold": 0.5,
        "non_maximum_suppression": False,
        "augmentation": "rfdetr_default_v1",
        "final_checkpoint": "checkpoint_best_total.pth",
    }
    return {**value, "recipe_digest": _digest(value)}


def _run_record(tmp_path: Path, freeze: dict, name: str) -> Path:
    source_frame_digests = [
        {"frame_id": frame["frame_id"], "sha256": frame["source"]["frame_sha256"]}
        for frame in freeze["teacher_manifest"]["frames"]
    ]
    record = {
        "schema_version": VISIBLE_CARD_TRAINING_RUN_SCHEMA,
        "run_id": f"run-{name}",
        "status": "completed",
        "dataset": {
            "dataset_digest": _digest({"candidate": name}),
            "split_digest": ("a" * 64),
            "source_frame_digests": source_frame_digests,
        },
        "recipe": _recipe(),
        "bundle": {
            "bundle_digest": _digest({"bundle": name}),
            "checkpoint_sha256": _digest({"checkpoint": name}),
        },
    }
    path = tmp_path / f"{name}-run.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _proposal(card: dict, *, shifted: bool) -> VisibleCardProposal:
    reviewed = ReviewedVisibleCard.from_mapping(card["card"])
    box = reviewed.derived_box.box_2d
    offset = 100 if shifted else 0
    x_min = min(1000 - 1, box.x_min + offset)
    x_max = min(1000, box.x_max + offset)
    if x_max <= x_min:
        x_min, x_max = box.x_min, box.x_max
    normalized = NormalizedBox(
        y_min=box.y_min,
        x_min=x_min,
        y_max=box.y_max,
        x_max=x_max,
    )
    return VisibleCardProposal(
        box_2d=normalized,
        polygon=(
            NormalizedPoint(x=normalized.x_min, y=normalized.y_min),
            NormalizedPoint(x=normalized.x_max, y=normalized.y_min),
            NormalizedPoint(x=normalized.x_max, y=normalized.y_max),
            NormalizedPoint(x=normalized.x_min, y=normalized.y_max),
        ),
        side="unknown",
        label="visible_card",
    )


def _candidate(
    tmp_path: Path,
    freeze: dict,
    candidate_id: str,
    run_path: Path,
    *,
    shifted: bool,
) -> Path:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    result_paths: dict[str, list[str]] = {"validation": [], "challenge": []}
    for partition in result_paths:
        frames = [frame for frame in freeze["partition_manifests"][partition]["frames"]]
        for frame in frames:
            source = frame["source"]
            image_path = Path(source["image"])
            request = VisibleCardRequest(
                package_id=source["package_id"],
                frame_part_name=source["frame_part_name"],
                target_offset_ms=source["target_offset_ms"],
                image_bytes=image_path.read_bytes(),
                width=source["width"],
                height=source["height"],
                provider="local",
                model="local-rfdetr",
            )
            proposals = tuple(_proposal(label, shifted=shifted) for label in frame["labels"])
            result_path = (
                tmp_path / f"{candidate_id}-{partition}-{frame['frame_id'].replace(':', '-')}.json"
            )
            write_run_artifact(
                request,
                ProviderResult(
                    status="ok",
                    proposals=proposals,
                    raw_response={
                        "provider": "local",
                        "detector_scores": [0.9 for _ in proposals],
                        "load_latency_ms": 12.0,
                        "bundle_identity": {
                            "schema_version": "visible-card-detector-bundle/v1",
                            "bundle_digest": run["bundle"]["bundle_digest"],
                            "checkpoint_sha256": run["bundle"]["checkpoint_sha256"],
                            "run_id": run["run_id"],
                        },
                    },
                    latency_ms=25.0,
                ),
                result_path,
            )
            result_paths[partition].append(str(result_path))
    value = {
        "schema_version": VISIBLE_CARD_COMPARISON_CANDIDATE_SCHEMA,
        "candidate_id": candidate_id,
        "label_source": (
            "gemini_pseudo_label"
            if candidate_id == "gemini-pseudo-label"
            else "reviewed_visible_region"
        ),
        "freeze_id": freeze["freeze_id"],
        "freeze_digest": freeze["freeze_digest"],
        "run": {"path": str(run_path), "sha256": _digest_file(run_path)},
        "results": result_paths,
    }
    path = tmp_path / f"{candidate_id}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _crop_evaluation(tmp_path: Path, freeze: dict) -> Path:
    partition_candidates = {}
    for partition in ("validation", "challenge"):
        frames = freeze["partition_manifests"][partition]["frames"]
        candidates = {}
        for candidate_id in ("gemini-pseudo-label", "reviewed-box"):
            policies = {}
            for policy in VISIBLE_CARD_COMPARISON_POLICIES:
                rows = []
                for frame in frames:
                    for label in frame["labels"]:
                        card = ReviewedVisibleCard.from_mapping(label["card"])
                        target = f"identity-{card.card_id}"
                        correct = policy != "raw_rectangular"
                        rows.append(
                            {
                                "frame_id": frame["frame_id"],
                                "card_id": card.card_id,
                                "crop_accepted": True,
                                "detected": True,
                                "identity_prediction": target if correct else "wrong",
                                "identity_target": target,
                                "identity_correct": correct,
                            }
                        )
                policies[policy] = {"rows": rows}
            candidates[candidate_id] = {"policies": policies}
        partition_candidates[partition] = {"candidates": candidates}
    value = {
        "schema_version": VISIBLE_CARD_CROP_EVALUATION_SCHEMA,
        "freeze_id": freeze["freeze_id"],
        "freeze_digest": freeze["freeze_digest"],
        "partitions": partition_candidates,
        "classifier_bundle_sha256": "b" * 64,
    }
    path = tmp_path / "crop-evaluation.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _comparison_inputs(tmp_path: Path) -> tuple[VisibleCardComparisonConfig, dict]:
    freeze = _freeze(tmp_path)
    gemini_run = _run_record(tmp_path, freeze, "gemini")
    reviewed_run = _run_record(tmp_path, freeze, "reviewed")
    gemini = _candidate(
        tmp_path,
        freeze,
        "gemini-pseudo-label",
        gemini_run,
        shifted=True,
    )
    reviewed = _candidate(
        tmp_path,
        freeze,
        "reviewed-box",
        reviewed_run,
        shifted=False,
    )
    config = VisibleCardComparisonConfig(
        freeze=tmp_path / "freeze",
        gemini_candidate=gemini,
        reviewed_candidate=reviewed,
        crop_evaluation=_crop_evaluation(tmp_path, freeze),
        output=tmp_path / "comparison.json",
    )
    return config, freeze


def test_comparison_reports_paired_metrics_and_crop_effects(tmp_path: Path) -> None:
    config, _freeze_value = _comparison_inputs(tmp_path)

    report = compare_visible_card_detectors(config)

    assert report["schema_version"] == "visible-card-comparison/v1"
    assert report["candidates"]["reviewed-box"]["metrics"]["validation"]["box_ap_iou_0_50"] == 1.0
    assert report["conclusion"]["localization"]["direction"] == "improves"
    assert (
        report["conclusion"]["crop_policy_end_to_end_identity"]["validation"]["raw_rectangular"]
        == "does_not_clearly_change"
    )
    assert (
        report["conclusion"]["crop_policy_effect"]["gemini-pseudo-label"]["validation"][
            "oracle_visible_region"
        ]
        == "improves"
    )
    assert len(report["paired_predictions"]) == 4
    assert report["selection_note"].startswith("This is a paired")
    assert config.output.is_file()


def test_comparison_rejects_recipe_or_training_membership_drift(tmp_path: Path) -> None:
    config, _freeze_value = _comparison_inputs(tmp_path)
    reviewed = json.loads(config.reviewed_candidate.read_text(encoding="utf-8"))
    run_path = Path(reviewed["run"]["path"])
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["recipe"]["seed"] = 99
    run["recipe"]["recipe_digest"] = _digest(
        {key: item for key, item in run["recipe"].items() if key != "recipe_digest"}
    )
    run_path.write_text(json.dumps(run), encoding="utf-8")
    reviewed["run"]["sha256"] = _digest_file(run_path)
    config.reviewed_candidate.write_text(json.dumps(reviewed), encoding="utf-8")

    with pytest.raises(VisibleCardComparisonError, match="same frozen recipe"):
        compare_visible_card_detectors(config)


def test_comparison_rejects_stale_crop_classifier_or_incomplete_rows(tmp_path: Path) -> None:
    config, _freeze_value = _comparison_inputs(tmp_path)
    crop = json.loads(config.crop_evaluation.read_text(encoding="utf-8"))
    crop["classifier_bundle_sha256"] = "not-a-digest"
    config.crop_evaluation.write_text(json.dumps(crop), encoding="utf-8")

    with pytest.raises(VisibleCardComparisonError, match="classifier_bundle_sha256"):
        compare_visible_card_detectors(config)
