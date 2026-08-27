from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cardevent.cli import main
from cardevent.data_contract import DatasetEntry, DatasetVersion, Eligibility, SourceRecord
from cardevent.lifecycle import (
    LifecycleReceipt,
    LifecycleReceiptError,
    build_dataset_creation_receipt,
    build_training_run_receipt,
    find_source_impact,
    load_lifecycle_receipt,
    retire_source_records,
    save_lifecycle_receipt,
    save_source_records,
)
from cardevent.table_dataset import make_dataset_split


def _source(source_asset_id: str = "source-001") -> SourceRecord:
    return SourceRecord(
        source_asset_id=source_asset_id,
        sha256="a" * 64,
        byte_length=10,
        media_type="video/quicktime",
        original_filename="source.mov",
        acquisition_method="test",
        source_permission="training_and_evaluation",
        allowed_uses=("train", "validation", "test"),
        session_id="session-001",
        recording_id="recording-001",
        video_id="video-001",
        table_setup="setup-001",
        content_type="staged_scenario",
    )


def _dataset(source: SourceRecord | None = None) -> DatasetVersion:
    source = source or _source()
    eligibility = Eligibility(
        source_asset_id=source.source_asset_id,
        state="eligible",
        source_permission=source.source_permission,
        allowed_uses=source.allowed_uses,
        review_state="reviewed",
        annotation_set_id="annotation-001",
        review_id="review-001",
        intended_use="train",
    )
    return DatasetVersion(
        dataset_version_id="dataset-001",
        task="table_evidence_analyzer_identity_crop",
        target_schema="table-observation-annotation/v1",
        entries=(
            DatasetEntry(
                dataset_item_id="item-001",
                source_asset_id=source.source_asset_id,
                source_sha256=source.sha256,
                annotation_set_id="annotation-001",
                review_id="review-001",
                eligibility=eligibility,
                target_schema="table-observation-annotation/v1",
                group_keys=(
                    ("session_id", "session-001"),
                    ("source_lineage", source.source_asset_id),
                ),
                inclusion_reason="reviewed identity crop",
                transform_version="identity-crop-v1",
                source_frame_id="frame-001",
                observed_card_id="card-001",
                bbox=(1, 2, 11, 12),
                visual_card_identity="HEARTS_QUEEN",
            ),
        ),
        allowed_use_filter=("train", "validation", "test"),
        group_key_names=("session_id", "source_lineage"),
        derived_artifact_transform_version="identity-crop-v1",
        creation_code_revision="test",
        dirty_state=False,
    )


def test_lifecycle_receipt_round_trip_has_stable_digest(tmp_path: Path) -> None:
    receipt = LifecycleReceipt(
        receipt_id="receipt-001",
        receipt_type="dataset_creation",
        operator="tester",
        occurred_at="2026-08-27T12:00:00Z",
        inputs=({"kind": "source_asset", "id": "source-001", "digest": "a" * 64},),
        outputs=({"kind": "dataset_version", "id": "dataset-001", "digest": "b" * 64},),
        metadata={"entry_count": 1},
    )
    path = save_lifecycle_receipt(receipt, tmp_path / "receipt.json")

    restored = load_lifecycle_receipt(path)

    assert restored == receipt
    assert restored.to_mapping()["receipt_digest"] == receipt.digest


def test_lifecycle_receipt_rejects_changed_digest() -> None:
    receipt = LifecycleReceipt(
        receipt_id="receipt-001",
        receipt_type="dataset_creation",
        operator="tester",
        occurred_at="2026-08-27T12:00:00Z",
        outputs=({"kind": "dataset_version", "id": "dataset-001"},),
    )
    payload = receipt.to_mapping()
    payload["metadata"] = {"changed": True}

    with pytest.raises(LifecycleReceiptError, match="receipt_digest"):
        LifecycleReceipt.from_mapping(payload)


def test_training_receipt_names_every_source_and_review_version() -> None:
    dataset = _dataset()
    split = make_dataset_split(
        dataset,
        split_version_id="split-001",
        assignments={"item-001": "train"},
    )

    receipt = build_training_run_receipt(
        dataset,
        split,
        training_run_id="run-001",
        operator="tester",
        model_bundle_id="model-001",
    )
    references = {(item["kind"], item["id"]) for item in receipt.to_mapping()["dependencies"]}

    assert ("source_asset", "source-001") in references
    assert ("annotation_set", "annotation-001") in references
    assert ("review", "review-001") in references
    assert ("dataset_version", "dataset-001") in references
    assert ("split_version", "split-001") in references
    assert ("model_bundle", "model-001") in {
        (item["kind"], item["id"]) for item in receipt.to_mapping()["outputs"]
    }


def test_retirement_writes_new_catalog_and_reports_affected_runs(tmp_path: Path) -> None:
    source = _source()
    dataset = _dataset(source)
    split = make_dataset_split(
        dataset,
        split_version_id="split-001",
        assignments={"item-001": "train"},
    )
    dataset_receipt = build_dataset_creation_receipt(
        dataset,
        sources=[source],
        operator="tester",
        receipt_id="dataset-receipt-001",
        occurred_at="2026-08-27T12:00:00Z",
    )
    run_receipt = build_training_run_receipt(
        dataset,
        split,
        training_run_id="run-001",
        operator="tester",
        receipt_id="run-receipt-001",
        occurred_at="2026-08-27T12:01:00Z",
        derived_artifact_ids=("crop-001",),
    )
    receipts_dir = tmp_path / "receipts"
    save_lifecycle_receipt(dataset_receipt, receipts_dir / "dataset.json")
    save_lifecycle_receipt(run_receipt, receipts_dir / "run.json")

    result = retire_source_records(
        [source],
        source_asset_ids=[source.source_asset_id],
        receipts=receipts_dir,
        operator="tester",
        reason="permission withdrawn",
        retention_state="deletion_requested",
        receipt_id="retire-001",
        occurred_at="2026-08-27T12:02:00Z",
    )
    catalog_path = save_source_records(result.source_records, tmp_path / "sources-retired.json")
    save_lifecycle_receipt(result.receipt, tmp_path / "retirement-receipt.json")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["sources"][0]["retention_state"] == "deletion_requested"
    assert result.impact["affected_derived_artifacts"] == ["crop-001"]
    assert result.impact["affected_training_runs"] == ["run-001"]
    assert result.receipt.metadata["reason"] == "permission withdrawn"


def test_source_impact_follows_dataset_receipt_to_derived_artifacts() -> None:
    source = _source()
    dataset = _dataset(source)
    split = make_dataset_split(
        dataset,
        split_version_id="split-001",
        assignments={"item-001": "train"},
    )
    receipt = build_training_run_receipt(
        dataset,
        split,
        training_run_id="run-001",
        operator="tester",
        derived_artifact_ids=("crop-001",),
    )

    impact = find_source_impact([source.source_asset_id], [receipt])

    assert impact["affected_dataset_versions"] == ["dataset-001"]
    assert impact["affected_split_versions"] == ["split-001"]


def test_retirement_does_not_change_the_input_source_record() -> None:
    source = _source()

    result = retire_source_records(
        [source],
        source_asset_ids=[source.source_asset_id],
        operator="tester",
        reason="retire test asset",
        retention_state="retired",
    )

    assert source.retention_state == "active"
    assert result.source_records[0] == replace(source, retention_state="retired")


def test_retire_source_cli_writes_new_catalog_and_receipt(tmp_path: Path) -> None:
    source = _source()
    source_path = save_source_records([source], tmp_path / "sources.json")
    output_path = tmp_path / "retired-sources.json"
    receipt_path = tmp_path / "retirement.json"

    assert (
        main(
            [
                "retire-source",
                "--sources",
                str(source_path),
                "--source-asset-id",
                source.source_asset_id,
                "--reason",
                "permission withdrawn",
                "--retention-state",
                "deletion_requested",
                "--out",
                str(output_path),
                "--receipt",
                str(receipt_path),
            ]
        )
        == 0
    )

    assert load_lifecycle_receipt(receipt_path).receipt_type == "retirement"
    assert (
        json.loads(output_path.read_text(encoding="utf-8"))["sources"][0]["retention_state"]
        == "deletion_requested"
    )
