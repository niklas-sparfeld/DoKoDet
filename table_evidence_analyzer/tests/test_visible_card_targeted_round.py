from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from table_evidence_analyzer.visible_card_comparison import (
    VisibleCardComparisonConfig,
    compare_visible_card_detectors,
)
from table_evidence_analyzer.visible_card_review_freeze import (
    freeze_visible_card_review_data,
    load_frozen_visible_card_review_data,
)
from table_evidence_analyzer.visible_card_targeted_round import (
    VISIBLE_CARD_TARGETED_BATCH_SCHEMA,
    VISIBLE_CARD_TARGETED_CANDIDATE_SCHEMA,
    VisibleCardTargetedRoundConfig,
    VisibleCardTargetedRoundError,
    evaluate_visible_card_targeted_round,
)
from table_evidence_analyzer.visible_cards import (
    ProviderResult,
    VisibleCardRequest,
    write_run_artifact,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _m3_inputs(tmp_path: Path) -> tuple[dict, Path]:
    from test_visible_card_comparison import (
        _candidate,
        _crop_evaluation,
        _partitions,
        _pilot,
        _run_record,
    )
    from test_visible_card_review_freeze import _queue

    queue_path = _queue(tmp_path)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    validation_item = next(
        item for item in queue["items"] if item["item_id"] == "package-002:frame_00"
    )
    validation_item["review"]["failure_tags"] = ["small_card"]
    for action in validation_item["review"]["actions"]:
        if action["reviewed_card"] is not None:
            action["reviewed_card"]["failure_tags"] = ["small_card"]
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    freeze_path = tmp_path / "freeze"
    freeze_visible_card_review_data(
        queue_path,
        _pilot(tmp_path),
        _partitions(tmp_path),
        freeze_path,
    )
    freeze = load_frozen_visible_card_review_data(freeze_path)
    gemini_run = _run_record(tmp_path, freeze, "gemini")
    reviewed_run = _run_record(tmp_path, freeze, "reviewed")
    gemini = _candidate(tmp_path, freeze, "gemini-pseudo-label", gemini_run, shifted=True)
    reviewed = _candidate(tmp_path, freeze, "reviewed-box", reviewed_run, shifted=False)
    config = VisibleCardComparisonConfig(
        freeze=freeze_path,
        gemini_candidate=gemini,
        reviewed_candidate=reviewed,
        crop_evaluation=_crop_evaluation(tmp_path, freeze),
        output=tmp_path / "comparison.json",
    )
    compare_visible_card_detectors(config)
    return freeze, config.output


def _targeted_queue(tmp_path: Path, freeze: dict, m3_path: Path) -> Path:
    source_queue = tmp_path / "queue.json"
    item = copy.deepcopy(json.loads(source_queue.read_text(encoding="utf-8"))["items"][0])
    source = item["source"]
    old_package = source["package_id"]
    package_id = "targeted-001"
    source.update(
        {
            "package_id": package_id,
            "source_asset_id": "targeted-asset-001",
            "source_lineage_group": "targeted-group-001",
        }
    )
    item["item_id"] = f"{package_id}:{source['frame_part_name']}"

    old_request = item["teacher"]["request"]
    request = VisibleCardRequest(
        package_id=package_id,
        frame_part_name=old_request["frame_part_name"],
        target_offset_ms=old_request["target_offset_ms"],
        image_bytes=Path(source["image"]).read_bytes(),
        width=old_request["width"],
        height=old_request["height"],
        model=old_request["model"],
        prompt=old_request["prompt"],
        response_schema=old_request["response_schema"],
        image_mime_type=old_request["image_mime_type"],
        provider=old_request["provider"],
        api_version=old_request["api_version"],
        thinking_level=old_request["thinking_level"],
        request_version=old_request["schema_version"],
    )
    teacher_result = ProviderResult.from_mapping(item["teacher"]["result"])
    teacher_result_path = tmp_path / "targeted-teacher.json"
    write_run_artifact(
        request,
        teacher_result,
        teacher_result_path,
        image=source["image"],
    )
    item["teacher"].update(
        {
            "result_path": str(teacher_result_path),
            "result_digest": _file_digest(teacher_result_path),
            "request_digest": request.request_key,
            "request": request.to_mapping(),
            "result": teacher_result.to_mapping(),
        }
    )
    item["review"]["failure_tags"] = ["small_card"]
    for action in item["review"]["actions"]:
        reviewed_card = action.get("reviewed_card")
        if reviewed_card is not None:
            reviewed_card["failure_tags"] = ["small_card"]

    queue_value = {
        "schema_version": json.loads(source_queue.read_text(encoding="utf-8"))["schema_version"],
        "run_id": "targeted-review-run",
        "created_at_utc": json.loads(source_queue.read_text(encoding="utf-8"))["created_at_utc"],
        "revision": json.loads(source_queue.read_text(encoding="utf-8"))["revision"],
        "items": [item],
    }
    queue_path = tmp_path / "targeted-queue.json"
    queue_path.write_text(json.dumps(queue_value), encoding="utf-8")
    assert old_package not in item["item_id"]
    assert freeze["freeze_id"]
    assert m3_path.is_file()
    return queue_path


def _batch(tmp_path: Path, freeze: dict, m3_path: Path, queue_path: Path) -> Path:
    value = {
        "schema_version": VISIBLE_CARD_TARGETED_BATCH_SCHEMA,
        "batch_id": "targeted-batch-001",
        "freeze_id": freeze["freeze_id"],
        "freeze_digest": freeze["freeze_digest"],
        "selection": {
            "failure_category": "small_card",
            "item_budget": 2,
            "reason": "M3 measured a small-card recall failure on the review candidate.",
            "m3_report_path": str(m3_path.resolve()),
            "m3_report_sha256": _file_digest(m3_path),
        },
        "review_queue": {
            "path": str(queue_path.resolve()),
            "sha256": _file_digest(queue_path),
        },
        "item_ids": ["targeted-001:frame_00"],
        "system_holdout_groups": [],
    }
    path = tmp_path / "targeted-batch.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _targeted_candidate(
    tmp_path: Path,
    freeze: dict,
    m3_path: Path,
    batch_path: Path,
) -> Path:
    m3 = json.loads(m3_path.read_text(encoding="utf-8"))
    reviewed_descriptor = m3["candidates"]["reviewed-box"]
    reviewed_candidate_path = Path(reviewed_descriptor["candidate_path"])
    reviewed_candidate = json.loads(reviewed_candidate_path.read_text(encoding="utf-8"))
    reviewed_run_path = Path(reviewed_candidate["run"]["path"])
    run = json.loads(reviewed_run_path.read_text(encoding="utf-8"))
    batch_queue = json.loads((tmp_path / "targeted-queue.json").read_text(encoding="utf-8"))
    batch_item = batch_queue["items"][0]
    run["run_id"] = "run-targeted"
    run["dataset"]["dataset_digest"] = _digest({"targeted": True})
    run["dataset"]["source_frame_digests"].append(
        {
            "frame_id": batch_item["item_id"],
            "sha256": batch_item["source"]["frame_sha256"],
        }
    )
    run["bundle"]["bundle_digest"] = _digest({"targeted-bundle": True})
    run["bundle"]["checkpoint_sha256"] = _digest({"targeted-checkpoint": True})
    run_path = tmp_path / "targeted-run.json"
    run_path.write_text(json.dumps(run), encoding="utf-8")

    result_paths: dict[str, list[str]] = {"validation": [], "challenge": []}
    for partition in result_paths:
        paths = reviewed_candidate["results"][partition]
        for index, raw_path in enumerate(paths):
            result = json.loads(Path(raw_path).read_text(encoding="utf-8"))
            result["raw_response"]["bundle_identity"].update(
                {
                    "bundle_digest": run["bundle"]["bundle_digest"],
                    "checkpoint_sha256": run["bundle"]["checkpoint_sha256"],
                    "run_id": run["run_id"],
                }
            )
            result_path = tmp_path / f"targeted-{partition}-{index}.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            result_paths[partition].append(str(result_path))
    value = {
        "schema_version": VISIBLE_CARD_TARGETED_CANDIDATE_SCHEMA,
        "round_id": "targeted-round-001",
        "batch_id": "targeted-batch-001",
        "freeze_id": freeze["freeze_id"],
        "freeze_digest": freeze["freeze_digest"],
        "run": {"path": str(run_path), "sha256": _file_digest(run_path)},
        "results": result_paths,
    }
    path = tmp_path / "targeted-candidate.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _round_inputs(tmp_path: Path) -> VisibleCardTargetedRoundConfig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    freeze, m3_path = _m3_inputs(tmp_path)
    queue_path = _targeted_queue(tmp_path, freeze, m3_path)
    batch_path = _batch(tmp_path, freeze, m3_path, queue_path)
    candidate_path = _targeted_candidate(tmp_path, freeze, m3_path, batch_path)
    return VisibleCardTargetedRoundConfig(
        freeze=tmp_path / "freeze",
        m3_report=m3_path,
        batch=batch_path,
        targeted_candidate=candidate_path,
        output=tmp_path / "targeted-round.json",
    )


def test_targeted_round_reports_bounded_selection_and_unchanged_eval(tmp_path: Path) -> None:
    config = _round_inputs(tmp_path)

    report = evaluate_visible_card_targeted_round(config)

    assert report["schema_version"] == "visible-card-targeted-round/v1"
    assert report["batch"]["selection"]["failure_category"] == "small_card"
    assert report["batch"]["selection"]["item_budget"] == 2
    assert report["evaluation"]["unchanged_freeze"] is True
    assert (
        report["metrics"]["delta_targeted_minus_baseline"]["validation"]["box_ap_iou_0_50"]["delta"]
        == 0.0
    )
    assert report["conclusion"]["localization"]["validation_direction"] == (
        "does_not_clearly_change"
    )
    assert len(report["paired_predictions"]) == 4
    assert config.output.is_file()


def test_targeted_round_rejects_unmeasured_failure_and_split_drift(tmp_path: Path) -> None:
    config = _round_inputs(tmp_path)
    batch = json.loads(config.batch.read_text(encoding="utf-8"))
    batch["selection"]["failure_category"] = "glare"
    config.batch.write_text(json.dumps(batch), encoding="utf-8")
    with pytest.raises(VisibleCardTargetedRoundError, match="did not measure"):
        evaluate_visible_card_targeted_round(config)

    config = _round_inputs(tmp_path / "second")
    candidate = json.loads(config.targeted_candidate.read_text(encoding="utf-8"))
    run_path = Path(candidate["run"]["path"])
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["dataset"]["split_digest"] = _digest({"changed": True})
    run_path.write_text(json.dumps(run), encoding="utf-8")
    candidate["run"]["sha256"] = _file_digest(run_path)
    config.targeted_candidate.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(VisibleCardTargetedRoundError, match="evaluation split"):
        evaluate_visible_card_targeted_round(config)
