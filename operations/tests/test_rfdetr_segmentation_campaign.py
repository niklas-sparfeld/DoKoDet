from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import doko_operations.rfdetr_segmentation_campaign as campaign
from doko_operations.cli import main


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
