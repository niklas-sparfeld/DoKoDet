from __future__ import annotations

import json
from pathlib import Path

import pytest

from table_evidence_analyzer.visible_card_evaluation import (
    ReferenceCard,
    VisibleCardEvaluationConfig,
    VisibleCardEvaluationError,
    VisibleCardReference,
    VisibleCardReferenceSet,
    evaluate_visible_card_runs,
    load_visible_card_references,
    polygon_iou,
)
from table_evidence_analyzer.visible_cards import (
    NormalizedBox,
    NormalizedPoint,
    ProviderResult,
    VisibleCardProposal,
    VisibleCardRequest,
    write_run_artifact,
)


def _polygon(x_min: int, y_min: int, x_max: int, y_max: int) -> tuple[NormalizedPoint, ...]:
    return (
        NormalizedPoint(x_min, y_min),
        NormalizedPoint(x_max, y_min),
        NormalizedPoint(x_max, y_max),
        NormalizedPoint(x_min, y_max),
    )


def _proposal(
    x_min: int, y_min: int, x_max: int, y_max: int, *, side: str = "face_up"
) -> VisibleCardProposal:
    return VisibleCardProposal(
        box_2d=NormalizedBox(y_min, x_min, y_max, x_max),
        polygon=_polygon(x_min, y_min, x_max, y_max),
        side=side,
        label="card",
    )


def _request(package_id: str) -> VisibleCardRequest:
    return VisibleCardRequest(
        package_id=package_id,
        frame_part_name="frame_00",
        target_offset_ms=0,
        image_bytes=f"image-{package_id}".encode(),
        width=1000,
        height=1000,
        provider="fake",
    )


def test_polygon_iou_is_exact_for_identical_normalized_squares() -> None:
    square = _polygon(100, 100, 300, 300)

    assert polygon_iou(square, square) == 1.0


def test_visible_card_evaluation_reports_matches_duplicates_false_proposals_and_sides(
    tmp_path: Path,
) -> None:
    request = _request("package-001")
    result_path = tmp_path / "result.json"
    result = ProviderResult(
        status="ok",
        proposals=(
            _proposal(100, 100, 300, 300),
            _proposal(120, 120, 280, 280),
            _proposal(600, 600, 800, 800, side="face_down"),
        ),
        raw_response={"provider": "fake"},
    )
    write_run_artifact(request, result, result_path)
    reference_path = tmp_path / "references.json"
    reference_path.write_text(
        json.dumps(
            VisibleCardReferenceSet(
                (
                    VisibleCardReference(
                        package_id=request.package_id,
                        frame_part_name=request.frame_part_name,
                        target_offset_ms=request.target_offset_ms,
                        image_sha256=request.image_sha256,
                        cards=(
                            ReferenceCard(
                                card_id="card-001",
                                polygon=_polygon(100, 100, 300, 300),
                                side="face_up",
                                usable_for_crop=True,
                            ),
                        ),
                    ),
                )
            ).to_mapping()
        ),
        encoding="utf-8",
    )

    report = evaluate_visible_card_runs(
        VisibleCardEvaluationConfig(
            results=(result_path,),
            references=reference_path,
            output=tmp_path / "evaluation.json",
        )
    )

    metrics = report["metrics"]
    assert metrics["instance_recall"] == 1.0
    assert metrics["false_proposal_count"] == 1
    assert metrics["duplicate_proposal_count"] == 1
    assert metrics["median_boundary_iou"] == 1.0
    assert metrics["usable_crop_recall"] == 1.0
    assert metrics["instance_recall_by_side"]["face_up"]["matched_count"] == 1
    assert report["side_confusion"]["face_up"] == {"face_up": 1}
    assert report["results"][0]["path"] == str(result_path)
    assert len(report["results"][0]["sha256"]) == 64


def test_visible_card_evaluation_counts_unavailable_results(tmp_path: Path) -> None:
    request = _request("package-002")
    result_path = tmp_path / "unavailable.json"
    write_run_artifact(
        request,
        ProviderResult(status="unavailable", error="timeout"),
        result_path,
    )
    reference_path = tmp_path / "references.json"
    reference_path.write_text(
        json.dumps(
            VisibleCardReferenceSet(
                (
                    VisibleCardReference(
                        package_id=request.package_id,
                        frame_part_name=request.frame_part_name,
                        target_offset_ms=request.target_offset_ms,
                        image_sha256=request.image_sha256,
                        cards=(),
                    ),
                )
            ).to_mapping()
        ),
        encoding="utf-8",
    )

    report = evaluate_visible_card_runs(
        VisibleCardEvaluationConfig(
            results=(result_path,),
            references=reference_path,
            output=tmp_path / "evaluation.json",
        )
    )

    assert report["metrics"]["unavailable_count"] == 1
    assert report["metrics"]["unavailable_rate"] == 1.0


def test_reference_loader_rejects_missing_reference_cards_and_unknown_run(tmp_path: Path) -> None:
    request = _request("package-003")
    reference_path = tmp_path / "references.json"
    reference_path.write_text(
        json.dumps(
            {
                "schema_version": "visible-card-reference/v1",
                "references": [
                    {
                        "package_id": request.package_id,
                        "frame_part_name": request.frame_part_name,
                        "target_offset_ms": request.target_offset_ms,
                        "image_sha256": request.image_sha256,
                        "cards": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_visible_card_references(reference_path).references[0].cards == ()

    with pytest.raises(VisibleCardEvaluationError, match="no reviewed reference"):
        result_path = tmp_path / "result.json"
        write_run_artifact(
            _request("different-package"),
            ProviderResult(status="ok", proposals=(), raw_response={"provider": "fake"}),
            result_path,
        )
        evaluate_visible_card_runs(
            VisibleCardEvaluationConfig(
                results=(result_path,),
                references=reference_path,
                output=tmp_path / "evaluation.json",
            )
        )
