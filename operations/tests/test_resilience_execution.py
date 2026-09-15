from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image
from table_evidence_analyzer.card_classification import CardClassificationResult
from table_evidence_analyzer.table_observation import IdentityCandidate
from table_evidence_analyzer.visible_cards import ProviderUsage

from doko_operations.derived_view import ResolvedFrame
from doko_operations.resilience_baseline import (
    CONDITION_IDS,
    _estimated_cost_usd,
    _work_matrix,
    default_measurement_contract,
    sha256_json,
)
from doko_operations.resilience_execution import (
    build_resilience_work_plan,
    execute_resilience_work,
    materialize_resilience_work,
)


def _geometry(kind: str, x_min: int, y_min: int, x_max: int, y_max: int) -> dict[str, object]:
    return {
        "kind": kind,
        "visible_region": {
            "polygons": [
                [
                    {"x": x_min, "y": y_min},
                    {"x": x_max, "y": y_min},
                    {"x": x_max, "y": y_max},
                    {"x": x_min, "y": y_max},
                ]
            ]
        },
    }


def _frame() -> ResolvedFrame:
    output = BytesIO()
    Image.new("RGB", (100, 100), (220, 180, 120)).save(output, format="JPEG")
    return ResolvedFrame(
        requested_time_us=1_000,
        frame_index=3,
        presentation_timestamp_us=1_100,
        source_video_sha256=hashlib.sha256(b"video").hexdigest(),
        width=100,
        height=100,
        decoder_version="fixture-decoder/v1",
        transform_version="fixture-transform/v1",
        output_encoding="jpeg",
        image_bytes=output.getvalue(),
    )


def _manifest() -> tuple[dict[str, object], ResolvedFrame]:
    frame = _frame()
    reviewed_geometry = _geometry("reviewed-visible-region/v1", 100, 100, 700, 800)
    generated_geometry = _geometry("visible-region/v1", 110, 110, 690, 790)
    reviewed_neighbor = _geometry("reviewed-visible-region/v1", 500, 100, 900, 700)
    generated_neighbor = _geometry("visible-region/v1", 510, 110, 890, 690)
    sample = {
        "sample_id": "sample-fixture",
        "recording_id": "recording-fixture",
        "source_lineage_group": "group-fixture",
        "source_asset_id": "source-fixture",
        "source_video_sha256": frame.source_video_sha256,
        "source_video_path": "source.mov",
        "source_video_byte_length": 6,
        "visible_card_reference_revision_id": "visible-revision",
        "visual_identity_reference_revision_id": "identity-revision",
        "visible_card_item_id": "event-fixture",
        "visual_identity_item_id": "card-fixture",
        "generated_visible_card_revision_id": "generated-revision",
        "generated_visible_card_item_id": "event-fixture",
        "generated_geometry_is_prediction": True,
        "generated_item_present": True,
        "frame_identity": frame.identity_mapping(),
        "frame_identity_digest": sha256_json(frame.identity_mapping()),
        "reviewed_visible_geometry": reviewed_geometry,
        "generated_visible_geometry": generated_geometry,
        "reviewed_visible_geometry_digest": sha256_json(reviewed_geometry),
        "reviewed_identity_geometry_digest": sha256_json(reviewed_geometry),
        "reviewed_neighbor_geometries": [
            {"proposal_id": "reviewed-neighbor", "geometry": reviewed_neighbor}
        ],
        "generated_neighbor_geometries": [
            {"proposal_id": "generated-neighbor", "geometry": generated_neighbor}
        ],
        "reviewed_target_identity": "HEARTS_QUEEN",
        "partition": "development",
    }
    contract = default_measurement_contract()
    matrix = _work_matrix([sample], contract)
    manifest: dict[str, object] = {
        "schema_version": "visible-region-identity-resilience-manifest/v1",
        "baseline_id": "0051-m0-resilience-baseline",
        "classification_state": "not_started",
        "validation_classification_allowed": True,
        "measurement_contract": contract,
        "measurement_contract_sha256": sha256_json(contract),
        "source_groups": [
            {
                "source_lineage_group": "group-fixture",
                "group_key": "session_id",
                "recording_ids": ["recording-fixture"],
                "paired_sample_count": 1,
                "system_holdout": False,
            }
        ],
        "partitions": {
            "recording_ids": {"development": ["recording-fixture"], "validation": []},
            "development_source_lineage_groups": ["group-fixture"],
            "validation_source_lineage_groups": [],
            "system_holdout_excluded_groups": [],
        },
        "inventory": {
            "recording_count": 1,
            "completed_reference_count": 2,
            "pipeline_revision_count": 3,
            "paired_sample_count": 1,
            "validation_sample_count": 0,
        },
        "experiment_plan": {
            "schema_version": "visible-region-identity-resilience-matrix/v1",
            "available_paired_sample_count": 1,
            "selected_paired_sample_count": 1,
            "requests_per_sample": 120,
            "planned_classifier_request_count": len(matrix),
            "estimated_cost_usd": _estimated_cost_usd(len(matrix), contract),
            "estimated_wall_clock_seconds": 3600,
            "matrix_sha256": sha256_json(matrix),
            "matrix": matrix,
        },
        "coverage_report": {
            "available_sample_ids": ["sample-fixture"],
            "selected_sample_ids": ["sample-fixture"],
            "available_by_partition": {"development": 1, "validation": 0},
            "selected_by_partition": {"development": 1, "validation": 0},
            "required_validation_samples": 24,
            "validation_classification_allowed": True,
            "gaps": [],
        },
        "paired_samples": [sample],
        "coverage_gaps": [],
        "required_review_actions": [],
        "holdout_registry": {
            "path": None,
            "registry_version": "fixture",
            "registry_digest": "fixture",
        },
    }
    return manifest, frame


class _FixtureClassifier:
    name = "fixture"
    version = "fixture-classifier/v1"
    calibration = "uncalibrated"
    model = "fixture"

    def __init__(self) -> None:
        self.calls = 0

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        assert crop_bytes.startswith(b"P6\n")
        self.calls += 1
        return CardClassificationResult(
            status="ok",
            classification="identity",
            candidates=(IdentityCandidate(card="HEARTS_QUEEN", probability=0.9),),
            usage=ProviderUsage(total_tokens=7),
        )


def test_m3_plan_is_complete_before_frame_extraction(tmp_path: Path) -> None:
    manifest, _ = _manifest()

    plan = build_resilience_work_plan(manifest, output_root=tmp_path)

    assert plan["planned_classifier_request_count"] == 120
    assert len(plan["items"]) == 120
    assert {item["input_family"] for item in plan["items"]} == {
        "actual_gemini",
        "reviewed_upper_bound",
        "synthetic_corruption",
    }
    assert {item["matrix_entry"]["condition_id"] for item in plan["items"]} == set(CONDITION_IDS)


def test_m3_materialization_and_classifier_receipts_are_resumable(tmp_path: Path) -> None:
    manifest, frame = _manifest()
    source_path = tmp_path / "source.mov"
    source_path.write_bytes(b"video")

    def resolve(_path: Path, _source: object, _identity: object) -> ResolvedFrame:
        return frame

    materialized = materialize_resilience_work(
        manifest,
        repository_root=tmp_path,
        output_root=tmp_path / "m3",
        frame_resolver=resolve,
    )

    assert materialized["counts"]["planned_work_count"] == 120
    assert materialized["counts"]["materialized_crop_count"] > 0
    assert (tmp_path / "m3" / "work.json").is_file()
    second = materialize_resilience_work(
        manifest,
        repository_root=tmp_path,
        output_root=tmp_path / "m3",
        frame_resolver=resolve,
    )
    assert (
        second["counts"]["reused_crop_count"] == materialized["counts"]["materialized_crop_count"]
    )
    assert second["counts"]["materialized_crop_count"] == 0

    classifier = _FixtureClassifier()
    execution = execute_resilience_work(second, classifier=classifier)
    first_call_count = classifier.calls
    assert first_call_count == materialized["counts"]["materialized_crop_count"]
    assert execution["summary"]["retained_row_count"] == 120
    assert Path(execution["comparison_path"]).is_file()

    resumed = execute_resilience_work(second, classifier=classifier)

    assert classifier.calls == first_call_count
    assert resumed["summary"]["classifier_cache_reused_count"] == first_call_count
