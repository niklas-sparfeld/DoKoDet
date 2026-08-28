from __future__ import annotations

import json
from pathlib import Path

import pytest

from table_evidence_analyzer.data import (
    DataContractError,
    MaterializedCropDataset,
    build_smoke_fixture,
    load_artifact_index,
    load_dataset_manifest,
    load_split_manifest,
    materialize_crops,
    validate_dataset,
)


def test_generated_smoke_fixture_has_three_independent_groups_and_loads(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path)

    dataset = load_dataset_manifest(fixture.dataset_path)
    split = load_split_manifest(fixture.split_path)
    index = load_artifact_index(fixture.artifact_index_path)
    report = validate_dataset(dataset, split=split, artifacts=index)
    assert report.valid
    assert {partition for partition in split.partitions if split.partitions[partition]} == {
        "train",
        "validation",
        "test",
    }
    assert len({entry.group_keys[0][1] for entry in dataset.entries}) == 3

    cache = materialize_crops(dataset, split, index, fixture.crop_dir)
    assert len(cache.crops) == len(dataset.entries)
    assert all(crop.source_frame_sha256 for crop in cache.crops)
    samples = list(MaterializedCropDataset(cache))
    assert len(samples) == 3
    assert all(sample.crop_bytes.startswith(b"P6\n") for sample in samples)
    assert [sample.target for sample in samples] == [
        "CLUBS_NINE",
        "SPADES_JACK",
        "HEARTS_QUEEN",
    ]


def test_resolver_rejects_changed_source_frame_bytes(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path)
    index = load_artifact_index(fixture.artifact_index_path)
    changed = fixture.frame_paths[0]
    changed.write_bytes(changed.read_bytes() + b"changed")

    with pytest.raises(DataContractError, match="does not match its digest"):
        index.resolve(fixture.frame_ids[0])


def test_validation_rejects_stale_crop_and_split_leakage(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path)
    dataset = load_dataset_manifest(fixture.dataset_path)
    split = load_split_manifest(fixture.split_path)
    index = load_artifact_index(fixture.artifact_index_path)
    cache = materialize_crops(dataset, split, index, fixture.crop_dir)

    stale = fixture.crop_dir / "crop-manifest.json"
    payload = json.loads(stale.read_text(encoding="utf-8"))
    payload["crops"][0]["transform_version"] = "different-transform-v1"
    stale.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DataContractError, match="stale crop cache"):
        materialize_crops(dataset, split, index, fixture.crop_dir)

    bad_split = dict(split.to_mapping())
    bad_split["validation"] = [bad_split["train"][0]]
    bad_split["train"] = bad_split["train"][1:]
    bad_split["split_version_digest"] = split.digest
    with pytest.raises(DataContractError, match="split_version_digest"):
        load_split_manifest_from_mapping(bad_split)

    assert cache.crops


def load_split_manifest_from_mapping(data: dict) -> object:
    """Keep the split parser test independent from its file format."""

    from table_evidence_analyzer.data import SplitManifest

    return SplitManifest.from_mapping(data)
