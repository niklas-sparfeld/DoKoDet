from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import doko_operations.synthetic_visible_region_campaign as campaign
from doko_operations.cli import main


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(campaign, "validate_reviewed_rfdetr_detector_manifest", lambda value: None)
    source_dir = tmp_path / "data" / "operations"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "source.json"
    frame_digest = "1" * 64
    source_manifest = {
        "campaign_id": campaign.RFDETR_DETECTOR_CAMPAIGN_ID,
        "freeze_state": "frozen",
        "manifest_digest": "2" * 64,
        "recipe_sha256": "3" * 64,
        "recipe": {"training": {"seed": 6701}},
        "recordings": [
            {
                "recording_id": "recording-train",
                "source_permission": "project_use",
            }
        ],
        "source_groups": [
            {"recording_id": "recording-train", "partition": "train"},
        ],
        "samples": [
            {
                "event_id": "event-quad",
                "item_id": "item-quad",
                "recording_id": "recording-train",
                "reference_revision_id": "revision-1",
                "source_group_key": "4" * 64,
                "source_sha256": "5" * 64,
                "split": "train",
                "table_setup": "setup-a",
                "frame_identity": {
                    "image_sha256": frame_digest,
                    "width": 1920,
                    "height": 1080,
                },
                "targets": [
                    {
                        "card_id": "card-1",
                        "side": "face_up",
                        "geometry": {
                            "visible_region": {
                                "polygons": [
                                    [
                                        {"x": 100, "y": 100},
                                        {"x": 300, "y": 100},
                                        {"x": 300, "y": 500},
                                        {"x": 100, "y": 500},
                                    ]
                                ]
                            }
                        },
                    }
                ],
            },
            {
                "event_id": "event-not-cutout",
                "item_id": "item-not-cutout",
                "recording_id": "recording-train",
                "reference_revision_id": "revision-1",
                "source_group_key": "4" * 64,
                "source_sha256": "5" * 64,
                "split": "train",
                "table_setup": "setup-a",
                "frame_identity": {
                    "image_sha256": "6" * 64,
                    "width": 1920,
                    "height": 1080,
                },
                "targets": [
                    {
                        "card_id": "card-2",
                        "side": "unknown",
                        "geometry": {
                            "visible_region": {
                                "polygons": [
                                    [
                                        {"x": 100, "y": 100},
                                        {"x": 300, "y": 100},
                                        {"x": 300, "y": 500},
                                        {"x": 200, "y": 500},
                                        {"x": 100, "y": 500},
                                    ]
                                ]
                            }
                        },
                    }
                ],
            },
        ],
    }
    source_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    materialization_root = tmp_path / ".runtime" / "materialization"
    (materialization_root / "train" / "images").mkdir(parents=True)
    materialization = {
        "schema_version": "rfdetr-segmentation-materialization/v1",
        "campaign_manifest": {
            "manifest_digest": source_manifest["manifest_digest"],
            "file_sha256": _sha256(source_path),
        },
        "materialization_digest": "7" * 64,
        "split": {"digest": "8" * 64},
        "counts": {"train_images": 2, "train_annotations": 2},
        "generated_files": [
            {
                "kind": "extracted_frame",
                "path": "train/images/image-000001.jpg",
                "event_id": "event-quad",
                "sha256": frame_digest,
            },
            {
                "kind": "extracted_frame",
                "path": "train/images/image-000002.jpg",
                "event_id": "event-not-cutout",
                "sha256": "6" * 64,
            },
        ],
    }
    (materialization_root / "materialization.json").write_text(
        json.dumps(materialization), encoding="utf-8"
    )

    bundle_root = tmp_path / ".runtime" / "bundle"
    bundle_root.mkdir(parents=True)
    checkpoint = bundle_root / "checkpoint.pth"
    checkpoint.write_bytes(b"checkpoint")
    bundle = {
        "campaign_manifest": {
            "manifest_digest": source_manifest["manifest_digest"],
            "materialization_digest": materialization["materialization_digest"],
        },
        "bundle_digest": "9" * 64,
        "checkpoint_sha256": _sha256(checkpoint),
        "checkpoint_file": checkpoint.name,
        "files": {checkpoint.name: _sha256(checkpoint)},
    }
    (bundle_root / "manifest.json").write_text(json.dumps(bundle), encoding="utf-8")

    report_path = tmp_path / ".runtime" / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "rfdetr-segmentation-campaign-validation/v1",
                "status": "completed",
                "campaign_manifest": {"manifest_digest": source_manifest["manifest_digest"]},
                "materialization_digest": materialization["materialization_digest"],
                "candidate_bundle": {"bundle_digest": bundle["bundle_digest"]},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _build(root: Path) -> dict[str, object]:
    return campaign.build_synthetic_visible_region_manifest(
        root,
        source_manifest_path="data/operations/source.json",
        materialization_path=".runtime/materialization",
        detector_bundle_path=".runtime/bundle",
        validation_report_path=".runtime/report.json",
    )


def test_m0_is_deterministic_and_blocks_missing_required_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture_root(tmp_path, monkeypatch)

    first = _build(root)
    second = _build(root)

    assert first == second
    assert first["freeze_state"] == "blocked"
    assert first["inventory"]["eligible_card_cutout_count"] == 1
    assert first["inventory"]["eligible_background_count"] == 0
    assert first["inventory"]["eligible_occluder_count"] == 0
    assert first["inventory"]["max_generated_scene_count"] == 4
    assert first["baseline"]["local_rfdetr_0068"]["bundle_digest"] == "9" * 64
    assert any("empty table background" in gap for gap in first["coverage_gaps"])
    assert any("face_down" in gap for gap in first["coverage_gaps"])
    campaign.validate_synthetic_visible_region_manifest(first)


def test_m0_writer_is_immutable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _fixture_root(tmp_path, monkeypatch)
    manifest = _build(root)
    destination = root / "data" / "operations" / "synthetic.json"

    campaign.write_synthetic_visible_region_manifest(destination, manifest)
    campaign.write_synthetic_visible_region_manifest(destination, manifest)

    changed = dict(manifest)
    changed["question"] = "changed"
    changed["manifest_digest"] = campaign.hashlib.sha256(
        campaign.canonical_json_bytes(
            {key: value for key, value in changed.items() if key != "manifest_digest"}
        )
    ).hexdigest()
    with pytest.raises(campaign.SyntheticVisibleRegionCampaignError, match="already exists"):
        campaign.write_synthetic_visible_region_manifest(destination, changed)


def test_m0_can_retain_a_blocked_receipt_when_required_artifacts_are_missing(
    tmp_path: Path,
) -> None:
    manifest = campaign.build_synthetic_visible_region_manifest(tmp_path)

    assert manifest["freeze_state"] == "blocked"
    assert manifest["inventory"]["real_training_frame_count"] == 0
    campaign.validate_synthetic_visible_region_manifest(manifest)
    campaign.write_synthetic_visible_region_manifest(tmp_path / "blocked.json", manifest)


def test_cli_writes_the_blocked_m0_receipt_without_starting_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture_root(tmp_path, monkeypatch)
    output = root / "data" / "operations" / "synthetic.json"

    result = main(
        [
            "data",
            "synthetic-visible-region",
            "--repository-root",
            str(root),
            "--source-manifest",
            "data/operations/source.json",
            "--materialization",
            ".runtime/materialization",
            "--detector-bundle",
            ".runtime/bundle",
            "--validation-report",
            ".runtime/report.json",
            "--output",
            str(output),
            "--json",
        ]
    )

    assert result == 1
    assert json.loads(output.read_text(encoding="utf-8"))["freeze_state"] == "blocked"
