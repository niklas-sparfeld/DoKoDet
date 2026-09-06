from __future__ import annotations

import json
from pathlib import Path

import pytest

from doko_operations.resilience_baseline import (
    CONDITION_IDS,
    MINIMUM_VALIDATION_SAMPLES,
    ResilienceBaselineError,
    build_resilience_baseline_manifest,
    canonical_json_bytes,
    default_measurement_contract,
    render_resilience_baseline_human,
    sha256_json,
    validate_resilience_baseline_manifest,
)


def test_measurement_contract_freezes_all_m0_conditions_and_gates() -> None:
    contract = default_measurement_contract()

    assert [condition["condition_id"] for condition in contract["conditions"]] == list(
        CONDITION_IDS
    )
    assert {item["family"] for item in contract["corruptions"]} == {
        "erosion_missing_boundary_pixels",
        "dilation_into_background_or_neighbor",
        "position_shift",
        "holes_missing_connected_components",
        "false_disconnected_components",
        "pixels_from_another_visible_card",
        "complete_derived_box_fallback",
    }
    assert contract["exclusion"]["recursive_exclusion"] is False
    assert contract["decision_gates"]["minimum_validation_samples"] == MINIMUM_VALIDATION_SAMPLES
    assert contract["classifier"]["score_calibration"] == (
        "uncalibrated_single_candidate_is_not_probability"
    )


def test_m0_reports_missing_paired_references_without_classification(tmp_path: Path) -> None:
    manifest = build_resilience_baseline_manifest(tmp_path)

    assert manifest["classification_state"] == "not_started"
    assert manifest["validation_classification_allowed"] is False
    assert manifest["inventory"] == {
        "recording_count": 0,
        "completed_reference_count": 0,
        "pipeline_revision_count": 0,
        "paired_sample_count": 0,
        "validation_sample_count": 0,
    }
    assert any("recording intake root is missing" in gap for gap in manifest["coverage_gaps"])
    assert any("at least two source-lineage groups" in gap for gap in manifest["coverage_gaps"])
    assert any("validation coverage needs" in gap for gap in manifest["coverage_gaps"])
    assert "validation classification: not allowed" in render_resilience_baseline_human(manifest)


def test_m0_rejects_invalid_classifier_identifier(tmp_path: Path) -> None:
    with pytest.raises(ResilienceBaselineError, match="classifier_provider"):
        build_resilience_baseline_manifest(tmp_path, classifier_provider="bad/provider")


def test_m0_manifest_validator_rejects_contract_mutation(tmp_path: Path) -> None:
    manifest = build_resilience_baseline_manifest(tmp_path)
    validate_resilience_baseline_manifest(manifest)

    manifest["measurement_contract"]["conditions"][0]["deployable"] = False

    with pytest.raises(ResilienceBaselineError, match="measurement_contract_sha256"):
        validate_resilience_baseline_manifest(manifest)


def test_m0_accepts_relative_roots_and_reads_complete_recording_inventory(tmp_path: Path) -> None:
    intake = tmp_path / "fixture-intake" / "recording-01"
    intake.mkdir(parents=True)
    (intake / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "repository-bundle/v1",
                "state": "complete",
                "recording_id": "recording-01",
                "session_id": "session-01",
                "source_asset_id": "source-01",
                "source_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    manifest = build_resilience_baseline_manifest(tmp_path, intake_root="fixture-intake")

    assert manifest["inventory"]["recording_count"] == 1
    assert manifest["source_groups"] == [
        {
            "source_lineage_group": "session-01",
            "group_key": "session_id",
            "recording_ids": ["recording-01"],
            "paired_sample_count": 0,
            "system_holdout": False,
        }
    ]


def test_m0_pairs_corrected_visible_regions_with_identity_targets(tmp_path: Path) -> None:
    frame = {
        "schema_version": "exact-event/v1",
        "source_video_sha256": "a" * 64,
        "requested_time_us": 1_000,
        "frame_index": 3,
        "presentation_timestamp_us": 1_000,
    }
    geometry = {
        "kind": "visible-region/v1",
        "polygons": [[{"x": 1, "y": 1}, {"x": 9, "y": 1}, {"x": 9, "y": 9}]],
    }
    generated_visible = {
        "schema_version": "visible-card-data/v1",
        "outcomes": [
            {
                "event_id": "event-01",
                "frame_identity": frame,
                "status": "detected",
                "candidates": [{"card_id": "card-01", "geometry": geometry}],
            }
        ],
    }
    reviewed_visible = {
        **generated_visible,
        "outcomes": [
            {
                **generated_visible["outcomes"][0],
                "candidates": [{"card_id": "card-01", "geometry": geometry}],
            }
        ],
    }
    reviewed_identity = {
        "schema_version": "visual-identity-data/v1",
        "outcomes": [
            {
                "card_id": "card-01",
                "frame_identity": frame,
                "geometry": geometry,
                "status": "classified",
                "candidates": [{"identity": "HEARTS_QUEEN"}],
            }
        ],
    }

    def publish_revision(
        revision_id: str,
        content_type: str,
        content: dict[str, object],
        *,
        origin: str,
        producer: dict[str, object],
        recording_id: str,
    ) -> None:
        directory = tmp_path / ".runtime" / "pipeline" / "revisions" / revision_id
        directory.mkdir(parents=True)
        (directory / "content.json").write_bytes(canonical_json_bytes(content))
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "revision_id": revision_id,
                    "content_type": content_type,
                    "origin": origin,
                    "recording_id": recording_id,
                    "producer": producer,
                    "content_sha256": sha256_json(content),
                }
            ),
            encoding="utf-8",
        )

    def write_recording(recording_id: str, session_id: str) -> None:
        bundle = tmp_path / "data" / "intake" / "recordings" / recording_id
        bundle.mkdir(parents=True)
        (bundle / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "repository-bundle/v1",
                    "state": "complete",
                    "recording_id": recording_id,
                    "session_id": session_id,
                    "source_asset_id": f"source-{recording_id}",
                    "source_sha256": "a" * 64,
                }
            ),
            encoding="utf-8",
        )

    def write_reference(
        recording_id: str,
        content_type: str,
        revision_id: str,
        item_id: str,
        item: dict[str, object],
        base_item_id: str,
        source_revision_id: str | None = None,
    ) -> None:
        directory = (
            tmp_path / "data" / "operations" / "pipeline-references" / recording_id / content_type
        )
        directory.mkdir(parents=True)
        (directory / "state.json").write_text(
            json.dumps(
                {
                    "recording_id": recording_id,
                    "content_type": content_type,
                    "draft_state": "completed",
                    "selected_completed_revision_id": revision_id,
                }
            ),
            encoding="utf-8",
        )
        (directory / "draft.json").write_text(
            json.dumps(
                {
                    "recording_id": recording_id,
                    "content_type": content_type,
                    "revision": 1,
                    "source_revision_id": source_revision_id,
                    "items": [
                        {
                            "item_id": item_id,
                            "base_item_id": base_item_id,
                            "review_state": "corrected",
                            "item": item,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    for index in (1, 2):
        recording_id = f"recording-0{index}"
        session_id = f"session-0{index}"
        write_recording(recording_id, session_id)
        generated_id = f"generated-visible-{index}"
        publish_revision(
            generated_id,
            "visible_cards",
            generated_visible,
            origin="processor",
            producer={"kind": "processor"},
            recording_id=recording_id,
        )
        visible_id = f"reviewed-visible-{index}"
        publish_revision(
            visible_id,
            "visible_cards",
            reviewed_visible,
            origin="corrected",
            producer={"kind": "human", "base_revision_id": generated_id},
            recording_id=recording_id,
        )
        identity_id = f"reviewed-identity-{index}"
        publish_revision(
            identity_id,
            "visual_identities",
            reviewed_identity,
            origin="corrected",
            producer={"kind": "human", "base_revision_id": f"generated-identity-{index}"},
            recording_id=recording_id,
        )
        write_reference(
            recording_id,
            "visible_cards",
            visible_id,
            "event-01",
            reviewed_visible["outcomes"][0],
            "event-01",
            generated_id,
        )
        write_reference(
            recording_id,
            "visual_identities",
            identity_id,
            "card-01",
            reviewed_identity["outcomes"][0],
            "card-01",
        )

    manifest = build_resilience_baseline_manifest(tmp_path)

    assert manifest["inventory"]["paired_sample_count"] == 2
    assert {
        sample["generated_visible_card_revision_id"] for sample in manifest["paired_samples"]
    } == {"generated-visible-1", "generated-visible-2"}
    assert {sample["source_lineage_group"] for sample in manifest["paired_samples"]} == {
        "session-01",
        "session-02",
    }
    assert "at least two source-lineage groups" not in "\n".join(manifest["coverage_gaps"])
