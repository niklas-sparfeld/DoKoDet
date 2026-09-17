from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import doko_operations.reviewed_rfdetr_detector_campaign as reviewed_campaign
import doko_operations.rfdetr_segmentation_campaign as campaign
from doko_operations.cli import main
from doko_operations.rfdetr_segmentation_materialization import (
    RfdetrSegmentationMaterializationError,
    load_rfdetr_segmentation_materialization,
    materialize_rfdetr_segmentation_dataset,
)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixture_corpus(
    root: Path,
    *,
    ignored_recording: str | None = None,
    unusable_recording: str | None = None,
) -> Path:
    intake = root / "data" / "intake" / "recordings"
    operations = root / "data" / "operations"
    all_recordings = (*campaign.TRAIN_RECORDING_IDS, *campaign.VALIDATION_RECORDING_IDS)
    for index, recording_id in enumerate(all_recordings):
        split = campaign.RECORDING_SPLITS[recording_id]
        bundle = intake / recording_id
        bundle.mkdir(parents=True)
        video = f"video-{index}".encode()
        video_digest = _digest(video)
        video_path = bundle / "videos" / f"{recording_id}.mov"
        video_path.parent.mkdir()
        video_path.write_bytes(video)
        manifest = {
            "schema_version": "repository-bundle/v1",
            "state": "complete",
            "recording_id": recording_id,
            "session_id": f"session-{index}",
            "source_asset_id": f"source-{index}",
            "video_id": f"video-{index}",
            "source_sha256": video_digest,
            "files": {
                "video": {
                    "byte_length": len(video),
                    "relative_path": f"videos/{recording_id}.mov",
                    "sha256": video_digest,
                    "type": "video/quicktime",
                }
            },
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        source_record = {
            "schema_version": "source-record/v1",
            "recording_id": recording_id,
            "session_id": f"session-{index}",
            "source_asset_id": f"source-{index}",
            "video_id": f"video-{index}",
            "sha256": video_digest,
            "byte_length": len(video),
            "source_permission": "project_use",
            "allowed_uses": [split],
            "table_setup": f"setup-{index}",
            "retention_state": "active",
        }
        (bundle / "source-record.json").write_text(json.dumps(source_record), encoding="utf-8")

        event_id = f"event-{index}"
        frame_bytes = f"frame-{index}".encode()
        frame = {
            "schema_version": "exact-event/v1",
            "content_type": "image/jpeg",
            "frame_index": index,
            "image_sha256": _digest(frame_bytes),
            "source_video_sha256": video_digest,
            "width": 100,
            "height": 100,
        }
        status = "failed" if recording_id == unusable_recording else "detected"
        candidate = {
            "card_id": f"card-{index}",
            "geometry": {
                "kind": "reviewed-visible-region/v1",
                "visible_region": {
                    "polygons": [[{"x": 10, "y": 10}, {"x": 20, "y": 10}, {"x": 20, "y": 20}]]
                },
            },
            "normalization": {
                "width": 100,
                "height": 100,
                "policy_id": "full-frame-0-1000/v1",
            },
            "side": "unknown",
        }
        outcome = {
            "event_id": event_id,
            "frame_identity": frame,
            "status": status,
            "candidates": [] if status == "failed" else [candidate],
            "error": "fixture unusable" if status == "failed" else None,
        }
        coverage_decision = "unusable" if status == "failed" else "cards"
        if recording_id == ignored_recording:
            outcome["ignored_regions"] = [
                {
                    "region_id": f"ignore-{index}",
                    "reason": "untidy_stack",
                    "geometry": {
                        "kind": "reviewed-ignore-region/v1",
                        "polygons": [[{"x": 1, "y": 1}, {"x": 3, "y": 1}, {"x": 3, "y": 3}]],
                    },
                    "normalization": {
                        "width": 100,
                        "height": 100,
                        "policy_id": "full-frame-0-1000/v1",
                    },
                }
            ]
            coverage_decision = "cards_and_ignored"
        revision_id = f"revision-{index}"
        content = {"schema_version": "visible-card-data/v1", "outcomes": [outcome]}
        revision = operations / "pipeline" / "revisions" / revision_id
        revision.mkdir(parents=True)
        revision_manifest = {
            "schema_version": "data-revision/v1",
            "revision_id": revision_id,
            "recording_id": recording_id,
            "content_type": "visible_cards",
            "content_schema": "visible-card-data/v1",
            "content_sha256": campaign.sha256_json(content),
            "origin": "corrected",
            "producer": {"kind": "human", "operator_id": "fixture"},
            "source": {
                "recording_id": recording_id,
                "video_sha256": video_digest,
            },
        }
        (revision / "manifest.json").write_text(json.dumps(revision_manifest), encoding="utf-8")
        (revision / "content.json").write_text(json.dumps(content), encoding="utf-8")
        reference = operations / "pipeline-references" / recording_id / "visible_cards"
        reference.mkdir(parents=True)
        draft_item = {
            "item_id": event_id,
            "base_item_id": None,
            "review_state": "unusable" if status == "failed" else "accepted",
            "item": outcome,
        }
        draft = {
            "schema_version": "pipeline-reference-draft/v1",
            "recording_id": recording_id,
            "content_type": "visible_cards",
            "revision": 1,
            "source_revision_id": revision_id,
            "items": [draft_item],
            "coverage": {
                "schema_version": "pipeline-reference-coverage/v1",
                "kind": "frame-review",
                "frames": [
                    {"item_id": event_id, "frame_identity": frame, "decision": coverage_decision}
                ],
                "impact": [],
            },
            "impact": [],
        }
        state = {
            "schema_version": "pipeline-reference-state/v1",
            "recording_id": recording_id,
            "content_type": "visible_cards",
            "draft_state": "completed",
            "draft_revision": 1,
            "source_revision_id": revision_id,
            "selected_completed_revision_id": revision_id,
        }
        (reference / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (reference / "draft.json").write_text(json.dumps(draft), encoding="utf-8")
    return root


@pytest.fixture
def fixture_expected_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        campaign,
        "EXPECTED_COUNTS",
        {
            "train": {"reviewed_frames": 6, "retained_frames": 6, "targets": 6},
            "validation": {"reviewed_frames": 3, "retained_frames": 3, "targets": 3},
        },
    )
    monkeypatch.setattr(
        campaign,
        "EXPECTED_TOTALS",
        {"reviewed_frames": 9, "retained_frames": 9, "targets": 9},
    )


def _available_api() -> dict[str, object]:
    return {
        "package": "rfdetr",
        "required_version": campaign.RFDETR_PACKAGE_VERSION,
        "installed_version": campaign.RFDETR_PACKAGE_VERSION,
        "model_class": campaign.RFDETR_MODEL_CLASS,
        "constructor_signature": "(pretrain_weights=None, **kwargs)",
        "train_signature": "(resolution, epochs, batch_size, grad_accum_steps, device, output_dir)",
        "status": "available",
        "gaps": [],
    }


def test_recipe_freezes_one_segmentation_candidate_and_no_test_partition() -> None:
    recipe = campaign.default_rfdetr_segmentation_recipe(device="mps")

    assert recipe["package"] == {"name": "rfdetr", "version": "1.9.4"}
    assert recipe["model"]["class"] == "RFDETRSegMedium"
    assert recipe["model"]["resolution"] == [432, 432]
    assert recipe["budget"] == {"wall_clock_seconds": 7200, "candidate_count": 1, "sweep": False}
    assert recipe["data_contract"]["test_partition"] is None


def test_m0_reproduces_counts_and_keeps_ignored_and_unusable_outcomes(
    tmp_path: Path, fixture_expected_counts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        campaign,
        "EXPECTED_COUNTS",
        {
            "train": {"reviewed_frames": 6, "retained_frames": 5, "targets": 5},
            "validation": {"reviewed_frames": 3, "retained_frames": 2, "targets": 2},
        },
    )
    monkeypatch.setattr(
        campaign,
        "EXPECTED_TOTALS",
        {"reviewed_frames": 9, "retained_frames": 7, "targets": 7},
    )
    root = _fixture_corpus(
        tmp_path,
        ignored_recording=campaign.TRAIN_RECORDING_IDS[0],
        unusable_recording=campaign.VALIDATION_RECORDING_IDS[0],
    )
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    manifest = campaign.build_rfdetr_segmentation_manifest(
        root,
        pretrained_checkpoint=checkpoint,
        verify_source_bytes=True,
        api_probe=_available_api(),
    )

    assert manifest["freeze_state"] == "frozen"
    assert manifest["inventory"] == {
        "recording_count": 9,
        "selected_recording_count": 9,
        "reviewed_frame_count": 9,
        "retained_frame_count": 7,
        "excluded_frame_count": 1,
        "ineligible_outcome_count": 1,
        "ignored_region_count": 1,
        "target_count": 7,
    }
    assert len(manifest["samples"]) == 7
    assert len(manifest["excluded_frames"]) == 1
    assert len(manifest["ineligible_outcomes"]) == 1
    assert "reviewed empty" not in " ".join(manifest["coverage_gaps"])
    campaign.validate_rfdetr_segmentation_manifest(manifest)


def test_m0_digest_is_stable_and_writer_is_immutable(
    tmp_path: Path, fixture_expected_counts: None
) -> None:
    root = _fixture_corpus(tmp_path)
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    kwargs = {
        "pretrained_checkpoint": checkpoint,
        "api_probe": _available_api(),
    }
    first = campaign.build_rfdetr_segmentation_manifest(root, **kwargs)
    second = campaign.build_rfdetr_segmentation_manifest(root, **kwargs)
    assert first == second
    assert first["freeze_state"] == "frozen"
    destination = root / "manifest.json"
    campaign.write_rfdetr_segmentation_manifest(destination, first)
    campaign.write_rfdetr_segmentation_manifest(destination, second)

    changed = dict(second)
    changed["coverage_gaps"] = ["drift"]
    changed["freeze_state"] = "blocked"
    changed["manifest_digest"] = campaign.sha256_json(
        {key: value for key, value in changed.items() if key != "manifest_digest"}
    )
    with pytest.raises(campaign.RfdetrSegmentationCampaignError, match="already exists"):
        campaign.write_rfdetr_segmentation_manifest(destination, changed)


def test_m0_reports_item_level_reference_drift(
    tmp_path: Path, fixture_expected_counts: None
) -> None:
    root = _fixture_corpus(tmp_path)
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    draft_path = (
        root
        / "data"
        / "operations"
        / "pipeline-references"
        / campaign.TRAIN_RECORDING_IDS[0]
        / "visible_cards"
        / "draft.json"
    )
    draft = json.loads(draft_path.read_text())
    draft["items"][0]["item"]["frame_identity"]["source_video_sha256"] = "f" * 64
    draft_path.write_text(json.dumps(draft), encoding="utf-8")

    manifest = campaign.build_rfdetr_segmentation_manifest(
        root,
        pretrained_checkpoint=checkpoint,
        api_probe=_available_api(),
    )

    assert manifest["freeze_state"] == "blocked"
    assert any(
        "selected revision differs from maintained draft" in gap
        for gap in manifest["coverage_gaps"]
    )


def test_cli_does_not_write_an_immutable_manifest_when_preflight_is_blocked(
    tmp_path: Path, fixture_expected_counts: None
) -> None:
    root = _fixture_corpus(tmp_path)
    output = root / "data" / "operations" / "campaign.json"

    result = main(
        [
            "data",
            "rfdetr-segmentation",
            "--repository-root",
            str(root),
            "--output",
            str(output),
        ]
    )

    assert result == 1
    assert not output.exists()


def _frozen_m0_manifest(
    root: Path,
    *,
    ignored_recording: str | None = None,
    unusable_recording: str | None = None,
) -> Path:
    corpus = _fixture_corpus(
        root,
        ignored_recording=ignored_recording,
        unusable_recording=unusable_recording,
    )
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    manifest = campaign.build_rfdetr_segmentation_manifest(
        corpus,
        pretrained_checkpoint=checkpoint,
        verify_source_bytes=True,
        api_probe=_available_api(),
    )
    path = root / "data" / "operations" / "rfdetr-segmentation-0067-m0-manifest.json"
    campaign.write_rfdetr_segmentation_manifest(path, manifest)
    return path


def _fixture_frame_extractor(_video_path: Path, frame: dict[str, object]) -> bytes:
    return f"frame-{frame['frame_index']}".encode()


def _view_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_m1_materialization_is_reproducible_and_preserves_lineage_and_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        campaign,
        "EXPECTED_COUNTS",
        {
            "train": {"reviewed_frames": 6, "retained_frames": 5, "targets": 5},
            "validation": {"reviewed_frames": 3, "retained_frames": 2, "targets": 2},
        },
    )
    monkeypatch.setattr(
        campaign,
        "EXPECTED_TOTALS",
        {"reviewed_frames": 9, "retained_frames": 7, "targets": 7},
    )
    manifest_path = _frozen_m0_manifest(
        tmp_path,
        ignored_recording=campaign.TRAIN_RECORDING_IDS[0],
        unusable_recording=campaign.VALIDATION_RECORDING_IDS[0],
    )
    output = tmp_path / "view"
    first = materialize_rfdetr_segmentation_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=output,
        frame_extractor=_fixture_frame_extractor,
    )
    first_files = _view_files(output)
    second = materialize_rfdetr_segmentation_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=output,
        frame_extractor=_fixture_frame_extractor,
    )

    assert first.to_mapping() == second.to_mapping()
    assert first_files == _view_files(output)
    assert first.image_count == 7
    assert first.annotation_count == 7
    assert first.excluded_frame_count == 1
    assert first.ineligible_outcome_count == 1
    loaded = load_rfdetr_segmentation_materialization(output)
    assert loaded["campaign_manifest"]["manifest_digest"] == first.campaign_manifest_digest

    train = json.loads((output / "train" / "_annotations.coco.json").read_text())
    valid = json.loads((output / "valid" / "_annotations.coco.json").read_text())
    assert len(train["images"]) == 5
    assert len(valid["images"]) == 2
    assert train["categories"] == [{"id": 1, "name": "visible_card", "supercategory": "card"}]
    assert train["annotations"][0]["bbox"] == [1, 1, 1, 1]
    assert train["annotations"][0]["recording_id"] in campaign.TRAIN_RECORDING_IDS
    assert train["annotations"][0]["reference_revision_id"]
    exclusions = json.loads((output / "exclusions.json").read_text())
    assert len(exclusions["excluded_frames"]) == 1
    assert len(exclusions["ineligible_outcomes"]) == 1
    assert exclusions["ineligible_outcomes"][0]["status"] == "failed"


def test_m1_rejects_a_changed_extracted_frame_digest(
    tmp_path: Path, fixture_expected_counts: None
) -> None:
    manifest_path = _frozen_m0_manifest(tmp_path)

    def changed_frame(_video_path: Path, _frame: dict[str, object]) -> bytes:
        return b"not-the-recorded-frame"

    with pytest.raises(RfdetrSegmentationMaterializationError, match="frame digest differs"):
        materialize_rfdetr_segmentation_dataset(
            manifest_path,
            repository_root=tmp_path,
            output_root=tmp_path / "view",
            frame_extractor=changed_frame,
        )
    assert not (tmp_path / "view").exists()


def test_m1_rejects_malformed_polygon_after_m0_digest_is_recomputed(
    tmp_path: Path, fixture_expected_counts: None
) -> None:
    manifest_path = _frozen_m0_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["samples"][0]["targets"][0]["geometry"]["visible_region"]["polygons"] = [
        [{"x": 10, "y": 10}, {"x": 20, "y": 10}]
    ]
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = campaign.sha256_json(core)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RfdetrSegmentationMaterializationError, match="too few points"):
        materialize_rfdetr_segmentation_dataset(
            manifest_path,
            repository_root=tmp_path,
            output_root=tmp_path / "view",
            frame_extractor=_fixture_frame_extractor,
        )


def test_m1_cli_materializes_a_frozen_manifest(
    tmp_path: Path, fixture_expected_counts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _frozen_m0_manifest(tmp_path)
    output = tmp_path / "cli-view"
    monkeypatch.setattr(
        "doko_operations.rfdetr_segmentation_materialization._default_frame_extractor",
        lambda: _fixture_frame_extractor,
    )

    result = main(
        [
            "data",
            "rfdetr-segmentation-materialize",
            "--repository-root",
            str(tmp_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output),
            "--json",
        ]
    )

    assert result == 0
    assert load_rfdetr_segmentation_materialization(output)["counts"]["images"] == 9


def _configure_reviewed_campaign_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    recording_ids = (*campaign.TRAIN_RECORDING_IDS, *campaign.VALIDATION_RECORDING_IDS)
    monkeypatch.setattr(
        reviewed_campaign,
        "DEFAULT_PARTITION_RECORDING_IDS",
        {
            "train": recording_ids[:3],
            "validation": recording_ids[3:6],
            "sealed_test": recording_ids[6:],
        },
    )
    monkeypatch.setattr(
        reviewed_campaign,
        "EXPECTED_INVENTORY",
        {
            "reviewed_frames": 9,
            "retained_frames": 9,
            "excluded_frames": 0,
            "ineligible_outcomes": 0,
            "ignored_regions": 0,
            "targets": 9,
        },
    )
    monkeypatch.setattr(
        reviewed_campaign,
        "EXPECTED_SIDE_COUNTS",
        {"face_up": 0, "unknown": 9, "face_down": 0},
    )


def _authorize_reviewed_campaign_fixture(root: Path) -> None:
    recording_ids = (*campaign.TRAIN_RECORDING_IDS, *campaign.VALIDATION_RECORDING_IDS)
    for recording_id in recording_ids:
        source_record_path = (
            root / "data" / "intake" / "recordings" / recording_id / "source-record.json"
        )
        source_record = json.loads(source_record_path.read_text())
        source_record["allowed_uses"] = ["train", "validation", "evaluation"]
        source_record_path.write_text(json.dumps(source_record), encoding="utf-8")


def _frozen_reviewed_m0_manifest(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ignored_recording: str | None = None,
    unusable_recording: str | None = None,
) -> Path:
    _configure_reviewed_campaign_fixture(monkeypatch)
    if ignored_recording is not None or unusable_recording is not None:
        monkeypatch.setattr(
            reviewed_campaign,
            "EXPECTED_INVENTORY",
            {
                "reviewed_frames": 9,
                "retained_frames": 7,
                "excluded_frames": 1,
                "ineligible_outcomes": 1,
                "ignored_regions": 1,
                "targets": 7,
            },
        )
        monkeypatch.setattr(
            reviewed_campaign,
            "EXPECTED_SIDE_COUNTS",
            {"face_up": 0, "unknown": 7, "face_down": 0},
        )
    corpus = _fixture_corpus(
        root,
        ignored_recording=ignored_recording,
        unusable_recording=unusable_recording,
    )
    _authorize_reviewed_campaign_fixture(corpus)
    checkpoint = corpus / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    manifest = reviewed_campaign.build_reviewed_rfdetr_detector_manifest(
        corpus,
        pretrained_checkpoint=checkpoint,
        verify_source_bytes=True,
        api_probe=_available_api(),
    )
    assert manifest["freeze_state"] == "frozen"
    path = corpus / "data" / "operations" / "rfdetr-visible-card-detector-0068-m0.json"
    reviewed_campaign.write_reviewed_rfdetr_detector_manifest(path, manifest)
    return path


def test_0068_recipe_pins_the_sealed_test_gate_and_supporting_slices() -> None:
    recipe = reviewed_campaign.default_reviewed_rfdetr_detector_recipe(device="mps")

    assert reviewed_campaign.DEFAULT_PARTITION_RECORDING_IDS["sealed_test"] == (
        "cardeventnet-IMG_0646",
        "cardeventnet-IMG_0648",
        "cardeventnet-IMG_0649",
    )
    assert reviewed_campaign.DEFAULT_PARTITION_RECORDING_IDS["train"][:2] == (
        "cardeventnet-IMG_0092",
        "cardeventnet-IMG_0095",
    )
    assert reviewed_campaign.DEFAULT_PARTITION_RECORDING_IDS["train"][-1] == (
        "cardeventnet-IMG_0674"
    )
    assert reviewed_campaign.EXPECTED_INVENTORY["ignored_regions"] == 389
    assert recipe["data_contract"]["test_partition"] == "sealed_test"
    assert recipe["data_contract"]["partition_policy"] == "source_group_disjoint/v1"
    assert recipe["validation"]["group_by"] == [
        "recording_id",
        "card_side",
        "visible_card_count_bucket",
    ]
    assert recipe["validation"]["minimum_gate"] == {
        "mask_ap_50_95": 0.0,
        "recall": 0.0,
        "beats_pretrained_mask_ap_50_95": True,
        "beats_pretrained_recall": True,
        "nonzero_recall_per_sealed_test_recording": True,
    }


def test_0068_m0_discovers_corrected_references_and_freezes_three_partitions(
    tmp_path: Path, fixture_expected_counts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_reviewed_campaign_fixture(monkeypatch)
    root = _fixture_corpus(tmp_path)
    _authorize_reviewed_campaign_fixture(root)
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")

    manifest = reviewed_campaign.build_reviewed_rfdetr_detector_manifest(
        root,
        pretrained_checkpoint=checkpoint,
        verify_source_bytes=True,
        api_probe=_available_api(),
    )

    assert manifest["freeze_state"] == "frozen"
    assert manifest["selection"]["selected_recording_ids"] == sorted(
        (*campaign.TRAIN_RECORDING_IDS, *campaign.VALIDATION_RECORDING_IDS)
    )
    assert manifest["inventory"]["target_count"] == 9
    assert manifest["inventory"]["side_counts"] == {"face_up": 0, "unknown": 9, "face_down": 0}
    assert len(manifest["split"]["sealed_test"]["recording_ids"]) == 3
    assert not set(manifest["split"]["train"]["recording_ids"]).intersection(
        manifest["split"]["sealed_test"]["recording_ids"]
    )
    assert all(
        sample["split"] in {"train", "validation", "sealed_test"} for sample in manifest["samples"]
    )
    reviewed_campaign.validate_reviewed_rfdetr_detector_manifest(manifest)


def test_0068_m0_is_reproducible_and_manifest_writer_is_immutable(
    tmp_path: Path, fixture_expected_counts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_reviewed_campaign_fixture(monkeypatch)
    root = _fixture_corpus(tmp_path)
    _authorize_reviewed_campaign_fixture(root)
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    kwargs = {"pretrained_checkpoint": checkpoint, "api_probe": _available_api()}

    first = reviewed_campaign.build_reviewed_rfdetr_detector_manifest(root, **kwargs)
    second = reviewed_campaign.build_reviewed_rfdetr_detector_manifest(root, **kwargs)
    assert first == second
    destination = root / "data" / "operations" / "reviewed-rfdetr-m0.json"
    reviewed_campaign.write_reviewed_rfdetr_detector_manifest(destination, first)
    reviewed_campaign.write_reviewed_rfdetr_detector_manifest(destination, second)

    changed = dict(second)
    changed["coverage_gaps"] = ["drift"]
    changed["freeze_state"] = "blocked"
    changed["manifest_digest"] = reviewed_campaign.sha256_json(
        {key: value for key, value in changed.items() if key != "manifest_digest"}
    )
    with pytest.raises(
        reviewed_campaign.ReviewedRfdetrDetectorCampaignError, match="already exists"
    ):
        reviewed_campaign.write_reviewed_rfdetr_detector_manifest(destination, changed)


def test_0068_m0_retains_only_the_first_reused_source_frame(
    tmp_path: Path, fixture_expected_counts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_reviewed_campaign_fixture(monkeypatch)
    root = _fixture_corpus(tmp_path)
    _authorize_reviewed_campaign_fixture(root)
    recording_id = campaign.TRAIN_RECORDING_IDS[0]
    reference_root = (
        root / "data" / "operations" / "pipeline-references" / recording_id / "visible_cards"
    )
    state = json.loads((reference_root / "state.json").read_text())
    revision_root = (
        root
        / "data"
        / "operations"
        / "pipeline"
        / "revisions"
        / state["selected_completed_revision_id"]
    )
    content_path = revision_root / "content.json"
    content = json.loads(content_path.read_text())
    duplicate = json.loads(json.dumps(content["outcomes"][0]))
    duplicate["event_id"] = "event-duplicate"
    duplicate["candidates"][0]["card_id"] = "card-duplicate"
    content["outcomes"].append(duplicate)
    content_path.write_text(json.dumps(content), encoding="utf-8")
    revision_manifest_path = revision_root / "manifest.json"
    revision_manifest = json.loads(revision_manifest_path.read_text())
    revision_manifest["content_sha256"] = reviewed_campaign.sha256_json(content)
    revision_manifest_path.write_text(json.dumps(revision_manifest), encoding="utf-8")

    draft_path = reference_root / "draft.json"
    draft = json.loads(draft_path.read_text())
    draft["items"].append(
        {
            "item_id": "event-duplicate",
            "base_item_id": None,
            "review_state": "accepted",
            "item": duplicate,
        }
    )
    draft["coverage"]["frames"].append(
        {
            "item_id": "event-duplicate",
            "frame_identity": duplicate["frame_identity"],
            "decision": "cards",
        }
    )
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    monkeypatch.setattr(
        reviewed_campaign,
        "EXPECTED_INVENTORY",
        {
            "reviewed_frames": 10,
            "retained_frames": 9,
            "excluded_frames": 0,
            "ineligible_outcomes": 1,
            "ignored_regions": 0,
            "targets": 9,
        },
    )
    monkeypatch.setattr(
        reviewed_campaign,
        "EXPECTED_SIDE_COUNTS",
        {"face_up": 0, "unknown": 9, "face_down": 0},
    )
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")

    manifest = reviewed_campaign.build_reviewed_rfdetr_detector_manifest(
        root,
        pretrained_checkpoint=checkpoint,
        api_probe=_available_api(),
    )

    assert manifest["freeze_state"] == "frozen"
    assert manifest["inventory"]["retained_frame_count"] == 9
    assert manifest["inventory"]["ineligible_outcome_count"] == 1
    assert len(manifest["samples"]) == 9
    duplicate = next(
        item for item in manifest["ineligible_outcomes"] if item["status"] == "duplicate"
    )
    assert "first reviewed outcome retained" in duplicate["reason"]


def test_0068_m0_blocks_cross_partition_source_group_overlap(
    tmp_path: Path, fixture_expected_counts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_reviewed_campaign_fixture(monkeypatch)
    root = _fixture_corpus(tmp_path)
    _authorize_reviewed_campaign_fixture(root)
    overlapping_id = campaign.VALIDATION_RECORDING_IDS[0]
    bundle = root / "data" / "intake" / "recordings" / overlapping_id
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    source_record_path = bundle / "source-record.json"
    source_record = json.loads(source_record_path.read_text())
    manifest["session_id"] = "session-0"
    source_record["session_id"] = "session-0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    source_record_path.write_text(json.dumps(source_record), encoding="utf-8")
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")

    result = reviewed_campaign.build_reviewed_rfdetr_detector_manifest(
        root, pretrained_checkpoint=checkpoint, api_probe=_available_api()
    )

    assert result["freeze_state"] == "blocked"
    assert any(
        "source group field session_id crosses partitions" in gap for gap in result["coverage_gaps"]
    )


def test_0068_m0_reports_missing_corrected_reference_as_unavailable(
    tmp_path: Path, fixture_expected_counts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_reviewed_campaign_fixture(monkeypatch)
    root = _fixture_corpus(tmp_path)
    _authorize_reviewed_campaign_fixture(root)
    revision_path = (
        root / "data" / "operations" / "pipeline" / "revisions" / "revision-0" / "manifest.json"
    )
    revision = json.loads(revision_path.read_text())
    revision["origin"] = "manual"
    revision_path.write_text(json.dumps(revision), encoding="utf-8")
    checkpoint = root / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")

    result = reviewed_campaign.build_reviewed_rfdetr_detector_manifest(
        root, pretrained_checkpoint=checkpoint, api_probe=_available_api()
    )

    assert result["freeze_state"] == "blocked"
    assert any(
        item["recording_id"] == campaign.TRAIN_RECORDING_IDS[0]
        for item in result["selection"]["unavailable_references"]
    )
    assert any("selected recording set is incomplete" in gap for gap in result["coverage_gaps"])


def test_0068_m1_materializes_train_validation_and_sealed_test_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _frozen_reviewed_m0_manifest(tmp_path, monkeypatch)
    output = tmp_path / "view"
    first = materialize_rfdetr_segmentation_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=output,
        frame_extractor=_fixture_frame_extractor,
    )
    first_files = _view_files(output)
    second = materialize_rfdetr_segmentation_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=output,
        frame_extractor=_fixture_frame_extractor,
    )

    assert first.to_mapping() == second.to_mapping()
    assert first_files == _view_files(output)
    assert first.image_count == 9
    assert first.annotation_count == 9
    assert (output / "train" / "_annotations.coco.json").is_file()
    assert (output / "valid" / "_annotations.coco.json").is_file()
    assert (output / "sealed_test" / "_annotations.coco.json").is_file()
    materialization = load_rfdetr_segmentation_materialization(output)
    assert materialization["campaign_id"] == reviewed_campaign.RFDETR_DETECTOR_CAMPAIGN_ID
    assert materialization["counts"] == {
        "images": 9,
        "annotations": 9,
        "train_images": 3,
        "validation_images": 3,
        "sealed_test_images": 3,
        "train_annotations": 3,
        "validation_annotations": 3,
        "sealed_test_annotations": 3,
    }
    split = json.loads((output / "split.json").read_text())
    assert split["sealed_test"] == [
        "cardeventnet-IMG_0090",
        "cardeventnet-IMG_0091",
        "cardeventnet-IMG_0661",
    ]
    sealed = json.loads((output / "sealed_test" / "_annotations.coco.json").read_text())
    assert sealed["info"]["trainer_partition"] == "sealed_test"
    assert sealed["images"][0]["source_group_key"]
    assert sealed["annotations"][0]["card_side"] == "unknown"
    assert sealed["annotations"][0]["source_group_key"] == sealed["images"][0]["source_group_key"]


def test_0068_m1_preserves_ignore_and_unusable_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _frozen_reviewed_m0_manifest(
        tmp_path,
        monkeypatch,
        ignored_recording=campaign.TRAIN_RECORDING_IDS[0],
        unusable_recording=campaign.VALIDATION_RECORDING_IDS[0],
    )
    result = materialize_rfdetr_segmentation_dataset(
        manifest_path,
        repository_root=tmp_path,
        output_root=tmp_path / "view",
        frame_extractor=_fixture_frame_extractor,
    )

    assert result.image_count == 7
    assert result.annotation_count == 7
    assert result.excluded_frame_count == 1
    assert result.ineligible_outcome_count == 1
    exclusions = json.loads((tmp_path / "view" / "exclusions.json").read_text())
    assert len(exclusions["excluded_frames"]) == 1
    assert len(exclusions["ineligible_outcomes"]) == 1
    assert exclusions["ineligible_outcomes"][0]["status"] == "failed"


def test_0068_m1_rejects_stale_reference_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _frozen_reviewed_m0_manifest(tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_text())
    manifest["samples"][0]["reference_revision_id"] = "stale-revision"
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = reviewed_campaign.sha256_json(core)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RfdetrSegmentationMaterializationError, match="stale reference lineage"):
        materialize_rfdetr_segmentation_dataset(
            manifest_path,
            repository_root=tmp_path,
            output_root=tmp_path / "view",
            frame_extractor=_fixture_frame_extractor,
        )


def test_0068_m1_rejects_a_stale_source_group_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _frozen_reviewed_m0_manifest(tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_text())
    manifest["samples"][0]["source_group"]["session_id"] = "stale-session"
    core = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = reviewed_campaign.sha256_json(core)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RfdetrSegmentationMaterializationError, match="source group differs"):
        materialize_rfdetr_segmentation_dataset(
            manifest_path,
            repository_root=tmp_path,
            output_root=tmp_path / "view",
            frame_extractor=_fixture_frame_extractor,
        )


def test_0068_m1_cli_materializes_the_sealed_test_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _frozen_reviewed_m0_manifest(tmp_path, monkeypatch)
    output = tmp_path / "cli-view"
    monkeypatch.setattr(
        "doko_operations.rfdetr_segmentation_materialization._default_frame_extractor",
        lambda: _fixture_frame_extractor,
    )

    result = main(
        [
            "data",
            "rfdetr-visible-card-detector-materialize",
            "--repository-root",
            str(tmp_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output),
            "--json",
        ]
    )

    assert result == 0
    assert load_rfdetr_segmentation_materialization(output)["counts"]["sealed_test_images"] == 3
