from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cardevent.data_contract import (
    ContractError,
    DatasetVersion,
    Eligibility,
    EntityRef,
    LineageEdge,
    LineageGraph,
    SourceRecord,
    adapt_cardevent_manifest,
    sha256_file,
)
from cardevent.manifest import load_dataset_manifest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "data_contract"


def _load_fixture() -> dict:
    return json.loads((FIXTURE_DIR / "contract.json").read_text(encoding="utf-8"))


def test_fixture_traces_crop_to_immutable_source_bytes() -> None:
    fixture = _load_fixture()
    source = SourceRecord.from_mapping(fixture["source"])
    source_path = FIXTURE_DIR / "source-video.bin"
    graph = LineageGraph.from_mapping(fixture["lineage"])
    dataset = DatasetVersion.from_mapping(fixture["dataset_version"])

    assert source.byte_length == source_path.stat().st_size
    assert source.sha256 == sha256_file(str(source_path))
    source.verify_bytes(source_path.read_bytes())
    assert graph.single_source_asset_for(EntityRef("crop", "crop-fixture-001")) == EntityRef(
        "source_asset", source.source_asset_id
    )
    assert dataset.entries[0].source_sha256 == source.sha256
    assert dataset.entries[0].eligibility.source_permission == source.source_permission
    assert dataset.entries[0].eligibility.review_state == "reviewed"


def test_contract_export_preserves_permission_review_and_digest() -> None:
    fixture = _load_fixture()
    dataset = DatasetVersion.from_mapping(fixture["dataset_version"])
    exported = dataset.to_mapping()
    restored = DatasetVersion.from_mapping(exported)

    assert restored == dataset
    assert exported["entries"][0]["eligibility"]["source_permission"] == (
        "training_and_evaluation"
    )
    assert exported["entries"][0]["eligibility"]["review_state"] == "reviewed"


def test_dataset_digest_is_stable_for_equivalent_input_order() -> None:
    fixture = _load_fixture()
    dataset = DatasetVersion.from_mapping(fixture["dataset_version"])
    equivalent = replace(
        dataset,
        entries=tuple(reversed(dataset.entries)),
        allowed_use_filter=tuple(reversed(dataset.allowed_use_filter)),
        group_key_names=tuple(reversed(dataset.group_key_names)),
        created_at="2026-08-28T00:00:00Z",
    )

    assert equivalent.digest == dataset.digest


def test_cardevent_v1_manifest_adapter_preserves_source_facts() -> None:
    manifest_path = Path(__file__).parents[1] / "data" / "dataset-manifest.example.yaml"
    record = load_dataset_manifest(manifest_path)[0]
    digest = "a" * 64
    source = SourceRecord.from_cardevent_record(
        record,
        source_asset_id="source-cardevent-example-001",
        sha256=digest,
        byte_length=123,
        allowed_uses=("train", "validation"),
        recording_id="recording-cardevent-example-001",
    )
    adapted = adapt_cardevent_manifest(
        [record],
        {
            record.video_id: {
                "source_asset_id": source.source_asset_id,
                "sha256": digest,
                "byte_length": 123,
                "allowed_uses": ["train", "validation"],
                "recording_id": "recording-cardevent-example-001",
            }
        },
    )

    assert adapted == (source,)
    assert source.video_id == record.video_id
    assert source.session_id == record.session_id
    assert source.source_permission == record.source_permission


def test_eligible_data_requires_review() -> None:
    fixture = _load_fixture()
    eligibility = dict(fixture["eligibility"])
    eligibility["review_state"] = "draft"

    with pytest.raises(ContractError, match="review_state reviewed"):
        Eligibility.from_mapping(eligibility)


def test_crop_lineage_requires_source_frame_and_transform() -> None:
    with pytest.raises(ContractError, match="source frame and transform"):
        LineageEdge(
            parent=EntityRef("frame", "frame-001"),
            child=EntityRef("crop", "crop-001"),
            relation="crop_from_frame",
        )
