from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cardevent.data_contract import EntityRef, LineageEdge, LineageGraph, SourceRecord
from cardevent.table_dataset import (
    TableDatasetError,
    assemble_table_evidence_dataset,
    build_table_dataset_coverage,
    make_dataset_split,
    validate_dataset_version,
)
from cardevent.vision_annotation import (
    BoundingBox,
    FrameObservation,
    ObservedCard,
    TableObservationAnnotation,
    VisionSource,
)
from cardevent.vision_review import build_table_observation_review

SOURCE_BYTES = b"table-observation-source"
SOURCE_SHA = "e" * 64


def _source(
    *,
    source_asset_id: str = "source-001",
    session_id: str = "session-001",
    sha256: str = SOURCE_SHA,
) -> SourceRecord:
    return SourceRecord(
        source_asset_id=source_asset_id,
        sha256=sha256,
        byte_length=len(SOURCE_BYTES),
        media_type="video/quicktime",
        original_filename=f"{source_asset_id}.mov",
        acquisition_method="test",
        source_permission="training_and_evaluation",
        allowed_uses=("train", "validation", "test"),
        session_id=session_id,
        recording_id=f"recording-{source_asset_id}",
        video_id=f"video-{source_asset_id}",
        table_setup="setup-001",
        content_type="staged_scenario",
    )


def _annotation(
    *,
    annotation_set_id: str = "annotation-001",
    source_package_id: str = "package-001",
    frame_id: str = "frame-001",
    event_review: str = "unreviewed",
    review_state: str = "draft",
) -> TableObservationAnnotation:
    return TableObservationAnnotation(
        annotation_set_id=annotation_set_id,
        source=VisionSource(package_id=source_package_id),
        observed_cards=(
            ObservedCard(
                observed_card_id=f"card-{annotation_set_id}",
                visual_card_identity="HEARTS_QUEEN",
                visibility="identifiable",
                frame_observations=(
                    FrameObservation(
                        frame_id=frame_id,
                        bbox=BoundingBox(10, 20, 110, 140),
                        usable_for_identity=True,
                        tags=("glare",),
                        observation_id=f"observation-{annotation_set_id}",
                    ),
                ),
                became_newly_visible=True,
                active_area_class="inside",
                movement="moving",
                occlusion="short",
            ),
        ),
        event_review=event_review,
        review_state=review_state,
    )


def _lineage(annotation: TableObservationAnnotation, source: SourceRecord) -> LineageGraph:
    package_id = annotation.source.package_id
    assert package_id is not None
    edges = (
        LineageEdge(
            parent=EntityRef("session", source.session_id),
            child=EntityRef("recording", source.recording_id),
            relation="recording_in_session",
        ),
        LineageEdge(
            parent=EntityRef("source_asset", source.source_asset_id),
            child=EntityRef("recording", source.recording_id),
            relation="source_contains_recording",
        ),
        LineageEdge(
            parent=EntityRef("recording", source.recording_id),
            child=EntityRef("evidence_package", package_id),
            relation="evidence_package_from_recording",
        ),
        LineageEdge(
            parent=EntityRef("evidence_package", package_id),
            child=EntityRef(
                "frame",
                annotation.observed_cards[0].frame_observations[0].frame_id,
            ),
            relation="frame_from_evidence_package",
        ),
        LineageEdge(
            parent=EntityRef("evidence_package", package_id),
            child=EntityRef("annotation_set", annotation.annotation_set_id),
            relation="annotation_for_evidence_package",
        ),
    )
    return LineageGraph(edges)


def test_assembly_requires_review_and_preserves_sample_lineage() -> None:
    annotation = _annotation()
    source = _source()
    review = build_table_observation_review(
        annotation,
        reviewer="tester",
        event_decision="reject_event",
        review_id="review-001",
        reviewed_at="2026-08-27T12:00:00Z",
    )

    result = assemble_table_evidence_dataset(
        [annotation],
        [source],
        reviews={annotation.annotation_set_id: review},
        lineage=_lineage(annotation, source),
        dataset_version_id="dataset-001",
        creation_code_revision="test",
        dirty_state=False,
    )

    assert len(result.dataset_version.entries) == 1
    entry = result.dataset_version.entries[0]
    assert entry.visual_card_identity == "HEARTS_QUEEN"
    assert entry.source_frame_id == "frame-001"
    assert entry.review_id == "review-001"
    assert entry.eligibility.review_state == "reviewed"
    assert result.coverage["event_review"] == {"false_event_proposal": 1}


def test_unreviewed_annotation_is_explicitly_unassigned() -> None:
    annotation = _annotation()
    source = _source()
    with pytest.raises(TableDatasetError, match="No eligible identity samples"):
        assemble_table_evidence_dataset(
            [annotation],
            [source],
            lineage=_lineage(annotation, source),
            dataset_version_id="dataset-001",
        )


def test_group_safe_split_keeps_session_together_and_is_deterministic() -> None:
    annotations = []
    sources = []
    reviews = {}
    all_edges = []
    for index in range(4):
        annotation = _annotation(
            annotation_set_id=f"annotation-{index}",
            source_package_id=f"package-{index}",
            frame_id=f"frame-{index}",
        )
        source = _source(
            source_asset_id=f"source-{index}",
            session_id="shared-session",
            sha256=f"{index + 1:064x}",
        )
        review = build_table_observation_review(
            annotation,
            reviewer="tester",
            event_decision="confirm_card_play",
            review_id=f"review-{index}",
            reviewed_at="2026-08-27T12:00:00Z",
        )
        annotations.append(annotation)
        sources.append(source)
        reviews[annotation.annotation_set_id] = review
        all_edges.extend(_lineage(annotation, source).edges)
    # A shared session with source-specific package edges is one connected leakage group.
    lineage = LineageGraph(tuple(all_edges))
    result = assemble_table_evidence_dataset(
        annotations,
        sources,
        reviews=reviews,
        lineage=lineage,
        dataset_version_id="dataset-001",
        creation_code_revision="test",
        dirty_state=False,
    )

    first = make_dataset_split(result.dataset_version, split_version_id="split-001", seed=7)
    second = make_dataset_split(result.dataset_version, split_version_id="split-001", seed=7)
    assert first == second
    assert len(first.train) == 4
    assert not first.validation
    assert not first.test
    first.validate_against(result.dataset_version)


def test_frozen_validation_rejects_changed_source_digest() -> None:
    annotation = _annotation()
    source = _source()
    review = build_table_observation_review(
        annotation,
        reviewer="tester",
        event_decision="confirm_card_play",
        review_id="review-001",
        reviewed_at="2026-08-27T12:00:00Z",
    )
    result = assemble_table_evidence_dataset(
        [annotation],
        [source],
        reviews={annotation.annotation_set_id: review},
        lineage=_lineage(annotation, source),
        dataset_version_id="dataset-001",
        creation_code_revision="test",
        dirty_state=False,
    )
    changed = replace(source, sha256="f" * 64)

    report = validate_dataset_version(
        result.dataset_version,
        sources=[changed],
        annotations=[review.reviewed_annotation],
        reviews={annotation.annotation_set_id: review},
        lineage=_lineage(annotation, source),
    )

    assert not report.valid
    assert any("changed source SHA-256" in error for error in report.errors)


def test_coverage_report_has_human_rendering_and_explicit_sections(tmp_path: Path) -> None:
    annotation = _annotation()
    source = _source()
    review = build_table_observation_review(
        annotation,
        reviewer="tester",
        event_decision="confirm_card_play",
        review_id="review-001",
        reviewed_at="2026-08-27T12:00:00Z",
    )
    result = assemble_table_evidence_dataset(
        [annotation],
        [source],
        reviews={annotation.annotation_set_id: review},
        lineage=_lineage(annotation, source),
        dataset_version_id="dataset-001",
        creation_code_revision="test",
        dirty_state=False,
    )
    report = build_table_dataset_coverage(
        result.dataset_version,
        reviewed_annotations=[review.reviewed_annotation],
        sources=[source],
        unassigned=({"annotation_set_id": "annotation-unassigned", "reason": "draft"},),
    )

    assert report["quality"]["tags"] == {"glare": 1}
    assert report["quality"]["newly_visible"] == {"true": 1}
    assert report["source_coverage"]["session_id"] == {"session-001": 1}
    from cardevent.table_dataset import coverage_report_markdown

    markdown = coverage_report_markdown(report)
    assert "# TableEvidenceAnalyzer dataset coverage" in markdown
    assert "## Unassigned" in markdown
    assert json.loads(json.dumps(report))["counts"]["dataset_entries"] == 1
