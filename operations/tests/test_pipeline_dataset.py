from __future__ import annotations

import base64
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from table_evidence_analyzer.local_identity import FACE_DOWN_TARGET
from table_evidence_analyzer.pipeline_data import (
    VisibleCardData,
    VisualIdentityData,
    canonical_visible_card_data_bytes,
    canonical_visual_identity_data_bytes,
)

from doko_operations.pipeline_data import (
    CARD_STATE_CHANGED_EVENT_TYPE,
    DataRevision,
    EventData,
    EventRecord,
    HumanProducer,
    ProcessorProducer,
    RecordingVideoSource,
    canonical_event_data_bytes,
    sha256_bytes,
)
from doko_operations.pipeline_dataset import (
    PipelineDatasetError,
    PipelineDatasetRequest,
    PipelineDatasetSourceGroup,
    materialize_pipeline_dataset,
)

DIGEST = "a" * 64
SOURCE = RecordingVideoSource(
    recording_id="recording-01",
    relative_path="recordings/recording-01/video.mov",
    video_sha256=DIGEST,
    byte_length=100,
    duration_us=10,
)


@dataclass(frozen=True)
class StoredRevision:
    manifest: DataRevision
    content: object


class RevisionCatalog:
    def __init__(self, *revisions: StoredRevision) -> None:
        self.revisions = {revision.manifest.revision_id: revision for revision in revisions}

    def require(self, revision_id: str) -> StoredRevision:
        return self.revisions[revision_id]


def _revision(
    revision_id: str,
    *,
    origin: str,
    coverage: dict[str, object],
    content: EventData | None = None,
    source: RecordingVideoSource = SOURCE,
) -> StoredRevision:
    value = content or EventData(
        events=(
            EventRecord(
                event_id="event-01",
                event_type=CARD_STATE_CHANGED_EVENT_TYPE,
                start_us=2,
                end_us=4,
            ),
        )
    )
    producer = (
        HumanProducer(review_id="review-01", operator_id="operator-01")
        if origin == "manual"
        else ProcessorProducer(
            run_id="run-01",
            processor_type="event-detection",
            implementation_id="fixture.v1",
            model_id="fixture-model.v1",
        )
    )
    manifest = DataRevision(
        revision_id=revision_id,
        content_type="events",
        content_schema="event-data/v1",
        recording_id=source.recording_id,
        source=source,
        content_sha256=sha256_bytes(canonical_event_data_bytes(value)),
        input_revision_ids=(),
        origin=origin,
        producer=producer,
        coverage=coverage,
        created_at="2026-09-05T10:00:00Z",
    )
    return StoredRevision(manifest=manifest, content=value)


def _frame() -> dict[str, object]:
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": DIGEST,
        "requested_time_us": 2,
        "frame_index": 0,
        "presentation_timestamp_us": 2,
        "width": 100,
        "height": 100,
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "output_encoding": "png",
        "content_type": "image/png",
        "image_sha256": DIGEST,
        "policy": "exact-event/v1",
    }


def _geometry() -> dict[str, object]:
    return {
        "kind": "detector-box/v1",
        "box_2d": {"x_min": 1, "y_min": 1, "x_max": 50, "y_max": 50},
    }


def _vision_revision(
    revision_id: str,
    content_type: str,
    content: VisibleCardData | VisualIdentityData,
    *,
    coverage: dict[str, object],
    origin: str = "manual",
    source: RecordingVideoSource = SOURCE,
) -> StoredRevision:
    if content_type == "visible_cards":
        content_bytes = canonical_visible_card_data_bytes(content)
        schema = "visible-card-data/v1"
    else:
        content_bytes = canonical_visual_identity_data_bytes(content)
        schema = "visual-identity-data/v1"
    manifest = DataRevision(
        revision_id=revision_id,
        content_type=content_type,
        content_schema=schema,
        recording_id=source.recording_id,
        source=source,
        content_sha256=sha256_bytes(content_bytes),
        input_revision_ids=(),
        origin=origin,
        producer=HumanProducer(review_id="review-01", operator_id="operator-01"),
        coverage=coverage,
        created_at="2026-09-05T10:00:00Z",
    )
    return StoredRevision(manifest=manifest, content=content)


def _event_reference() -> StoredRevision:
    return _revision(
        "event-reference-01",
        origin="manual",
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 10}],
            "source_duration_us": 10,
        },
    )


def _visible_reference() -> StoredRevision:
    outcome = {
        "event_id": "event-01",
        "frame_identity": _frame(),
        "status": "detected",
        "candidates": [
            {
                "card_id": "card-01",
                "geometry": _geometry(),
                "normalization": {"width": 64, "height": 64, "policy_id": "normalize.v1"},
                "side": "unknown",
            }
        ],
        "ignored_regions": [],
        "error": None,
    }
    content = VisibleCardData.from_mapping(
        {"schema_version": "visible-card-data/v1", "outcomes": [outcome]}
    )
    return _vision_revision(
        "visible-reference-01",
        "visible_cards",
        content,
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "visible_frames",
            "frames": [{"frame_identity": _frame(), "decision": "cards"}],
        },
    )


def _identity_reference() -> StoredRevision:
    frame = _frame()
    geometry = _geometry()
    crop = {
        "schema_version": "visible-region-crop/v1",
        "status": "usable",
        "frame_identity": frame,
        "geometry": geometry,
        "pixel_bounds": {"x_min": 1, "y_min": 1, "x_max": 50, "y_max": 50},
        "crop_policy": "crop.v1",
        "output_encoding": "png",
        "content_type": "image/png",
        "decoder_version": "decoder.v1",
        "transform_version": "transform.v1",
        "image_sha256": DIGEST,
        "unusable_reason": None,
    }
    content = VisualIdentityData.from_mapping(
        {
            "schema_version": "visual-identity-data/v1",
            "outcomes": [
                {
                    "card_id": "card-01",
                    "frame_identity": frame,
                    "geometry": geometry,
                    "crop_identity": crop,
                    "classifier": {
                        "provider": "human-reference",
                        "implementation": {"name": "maintained-reference", "version": "v1"},
                        "model": {"name": "human-decision", "version": "v1"},
                    },
                    "status": "classified",
                    "candidates": [
                        {
                            "identity": "CLUBS_NINE",
                            "score": None,
                            "score_meaning": None,
                            "producer_id": "human-reference.v1",
                        }
                    ],
                    "unusable_reason": None,
                    "error": None,
                }
            ],
        }
    )
    return _vision_revision(
        "identity-reference-01",
        "visual_identities",
        content,
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "visual_identities",
            "cards": [{"card_id": "card-01", "decision": "identity"}],
            "recording_id": SOURCE.recording_id,
        },
    )


def _source_group(*, recording_id: str = SOURCE.recording_id) -> PipelineDatasetSourceGroup:
    return PipelineDatasetSourceGroup(
        recording_id=recording_id,
        source_asset_id="source-01",
        source_sha256=DIGEST,
        group_keys=(("source_lineage", "lineage-01"), ("session_id", "session-01")),
        source_permission="training_and_evaluation",
        allowed_uses=("train", "validation"),
    )


def _request(
    reference_revision_id: str = "reference-01",
    *,
    source_groups: tuple[PipelineDatasetSourceGroup, ...] | None = None,
    policies: dict[str, object] | None = None,
    robustness_input_revision_id: str | None = None,
    visible_card_ignore_policy: str | None = None,
) -> PipelineDatasetRequest:
    return PipelineDatasetRequest(
        task="events",
        reference_revision_id=reference_revision_id,
        selected_input_revision_ids=(),
        source_groups=source_groups or (_source_group(),),
        policies=policies or {"event": {"policy_id": "event-target/v1", "boundary": "source"}},
        partition="train",
        robustness_input_revision_id=robustness_input_revision_id,
        visible_card_ignore_policy=visible_card_ignore_policy,
    )


def test_event_dataset_freezes_reference_source_groups_policy_and_lineage(
    tmp_path: Path,
) -> None:
    reference = _revision(
        "reference-01",
        origin="manual",
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 10}],
            "source_duration_us": 10,
        },
    )
    result = materialize_pipeline_dataset(
        RevisionCatalog(reference), _request(), tmp_path / "dataset"
    )

    manifest = result["manifest"]
    assert manifest["selected_reference_revision_id"] == "reference-01"
    assert manifest["selected_input_revision_ids"] == []
    assert manifest["source_groups"][0]["group_keys"] == [
        ["session_id", "session-01"],
        ["source_lineage", "lineage-01"],
    ]
    assert manifest["policies"]["event"]["boundary"] == "source"
    assert manifest["targets"][0]["target_state"] == "reviewed_reference"
    assert manifest["lineage"]["reference"]["revision_id"] == "reference-01"
    assert (tmp_path / "dataset" / "dataset-manifest.json").is_file()


def test_generated_revision_is_allowed_only_as_explicit_robustness_input(
    tmp_path: Path,
) -> None:
    generated = _revision(
        "generated-01",
        origin="processor",
        coverage={"kind": "processed"},
    )
    reference = _revision(
        "reference-01",
        origin="manual",
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 10}],
            "source_duration_us": 10,
        },
    )
    result = materialize_pipeline_dataset(
        RevisionCatalog(reference, generated),
        _request(robustness_input_revision_id="generated-01"),
        tmp_path / "dataset",
    )
    assert result["manifest"]["robustness_inputs"] == [
        {"revision_id": "generated-01", "role": "robustness_comparison"}
    ]
    assert all(
        target["target_state"] == "reviewed_reference" for target in result["manifest"]["targets"]
    )

    with pytest.raises(PipelineDatasetError, match="completed reference"):
        materialize_pipeline_dataset(
            RevisionCatalog(generated), _request("generated-01"), tmp_path / "generated"
        )


def test_legacy_device_source_is_rejected_before_future_dataset_publication(
    tmp_path: Path,
) -> None:
    legacy_source = replace(
        SOURCE,
        recording_id="cardeventnet-IMG_2777",
        video_sha256="c" * 64,
    )
    reference = _revision(
        "legacy-reference-01",
        origin="manual",
        source=legacy_source,
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 10}],
            "source_duration_us": 10,
        },
    )
    source_group = replace(
        _source_group(recording_id=legacy_source.recording_id),
        source_asset_id="source-cardeventnet-IMG_2777",
        source_sha256=legacy_source.video_sha256,
    )

    with pytest.raises(PipelineDatasetError, match="legacy-device diagnostic-only"):
        materialize_pipeline_dataset(
            RevisionCatalog(reference),
            _request("legacy-reference-01", source_groups=(source_group,)),
            tmp_path / "legacy-diagnostic",
        )
    assert not (tmp_path / "legacy-diagnostic" / "dataset-manifest.json").exists()


@pytest.mark.parametrize(
    "dataset_request",
    [
        _request(source_groups=(_source_group(), _source_group(recording_id="recording-02"))),
        _request(
            source_groups=(
                PipelineDatasetSourceGroup(
                    recording_id=SOURCE.recording_id,
                    source_asset_id="source-01",
                    source_sha256="b" * 64,
                    group_keys=(("source_lineage", "lineage-01"),),
                    source_permission="training_and_evaluation",
                    allowed_uses=("train",),
                ),
            )
        ),
    ],
)
def test_dataset_validation_fails_before_publication(
    tmp_path: Path, dataset_request: PipelineDatasetRequest
) -> None:
    reference = _revision(
        "reference-01",
        origin="manual",
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 10}],
            "source_duration_us": 10,
        },
    )
    with pytest.raises(PipelineDatasetError):
        materialize_pipeline_dataset(
            RevisionCatalog(reference), dataset_request, tmp_path / "dataset"
        )
    assert not (tmp_path / "dataset" / "dataset-manifest.json").exists()


@pytest.mark.parametrize(
    "dataset_request",
    [
        replace(
            _request(),
            source_groups=(_source_group(),),
            protected_groups=(("session_id", "session-01"),),
        ),
        replace(
            _request(),
            source_groups=(replace(_source_group(), allowed_uses=("evaluation",)),),
        ),
    ],
)
def test_permission_and_protected_split_fail_before_publication(
    tmp_path: Path, dataset_request: PipelineDatasetRequest
) -> None:
    reference = _revision(
        "reference-01",
        origin="manual",
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 10}],
            "source_duration_us": 10,
        },
    )
    with pytest.raises(PipelineDatasetError):
        materialize_pipeline_dataset(
            RevisionCatalog(reference), dataset_request, tmp_path / "dataset"
        )
    assert not (tmp_path / "dataset" / "dataset-manifest.json").exists()


def test_incomplete_reference_coverage_fails_before_publication(tmp_path: Path) -> None:
    reference = _revision(
        "reference-01",
        origin="manual",
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 8}],
            "source_duration_us": 10,
        },
    )
    with pytest.raises(PipelineDatasetError, match="coverage"):
        materialize_pipeline_dataset(RevisionCatalog(reference), _request(), tmp_path / "dataset")
    assert not (tmp_path / "dataset").exists()


def test_visible_and_identity_consumers_require_exact_reviewed_lineage(tmp_path: Path) -> None:
    event_reference = _event_reference()
    visible_reference = _visible_reference()
    identity_reference = _identity_reference()
    catalog = RevisionCatalog(event_reference, visible_reference, identity_reference)

    visible_request = PipelineDatasetRequest(
        task="visible_cards",
        reference_revision_id="visible-reference-01",
        selected_input_revision_ids=("event-reference-01",),
        source_groups=(_source_group(),),
        policies={"frame": {"policy_id": "exact-event/v1"}},
        partition="train",
        visible_card_ignore_policy="mask_pixels",
    )
    visible = materialize_pipeline_dataset(catalog, visible_request, tmp_path / "visible")
    assert visible["target_count"] == 1
    assert visible["manifest"]["selected_input_revision_ids"] == ["event-reference-01"]

    identity_request = PipelineDatasetRequest(
        task="visual_identities",
        reference_revision_id="identity-reference-01",
        selected_input_revision_ids=("visible-reference-01",),
        source_groups=(_source_group(),),
        policies={
            "frame": {"policy_id": "exact-event/v1"},
            "crop": {"policy_id": "crop.v1"},
        },
        partition="train",
    )
    identity = materialize_pipeline_dataset(catalog, identity_request, tmp_path / "identity")
    assert identity["manifest"]["targets"][0]["identity"] == "CLUBS_NINE"
    assert identity["manifest"]["target_contract"]["class_count"] == 25
    assert identity["manifest"]["target_contract"]["class_map"]["24"] == FACE_DOWN_TARGET

    face_down_mapping = identity_reference.content.to_mapping()
    face_down_mapping["outcomes"][0].update(
        status="face_down",
        candidates=[],
        unusable_reason=None,
        error=None,
    )
    face_down_reference = _vision_revision(
        "identity-reference-face-down",
        "visual_identities",
        VisualIdentityData.from_mapping(face_down_mapping),
        coverage={
            **identity_reference.manifest.coverage,
            "cards": [{"card_id": "card-01", "decision": "face_down"}],
        },
    )
    face_down_request = replace(
        identity_request,
        reference_revision_id="identity-reference-face-down",
    )
    face_down = materialize_pipeline_dataset(
        RevisionCatalog(event_reference, visible_reference, face_down_reference),
        face_down_request,
        tmp_path / "face-down",
    )
    assert face_down["manifest"]["targets"][0]["identity"] == FACE_DOWN_TARGET
    assert face_down["manifest"]["targets"][0]["target_class"] == FACE_DOWN_TARGET

    generated_event = _revision(
        "event-generated", origin="processor", coverage={"kind": "processed"}
    )
    with pytest.raises(PipelineDatasetError, match="completed references"):
        materialize_pipeline_dataset(
            RevisionCatalog(visible_reference, generated_event),
            replace(visible_request, selected_input_revision_ids=("event-generated",)),
            tmp_path / "missing-input",
        )


def test_identity_geometry_and_policy_mismatch_fail_before_publication(tmp_path: Path) -> None:
    event_reference = _event_reference()
    visible_reference = _visible_reference()
    identity = _identity_reference()
    identity_content = identity.content.to_mapping()
    identity_content["outcomes"][0]["geometry"] = {
        "kind": "detector-box/v1",
        "box_2d": {"x_min": 2, "y_min": 2, "x_max": 50, "y_max": 50},
    }
    identity_content["outcomes"][0]["crop_identity"]["geometry"] = identity_content["outcomes"][0][
        "geometry"
    ]
    broken_identity = _vision_revision(
        "identity-reference-broken",
        "visual_identities",
        VisualIdentityData.from_mapping(identity_content),
        coverage=identity.manifest.coverage,
    )
    request = PipelineDatasetRequest(
        task="visual_identities",
        reference_revision_id="identity-reference-broken",
        selected_input_revision_ids=("visible-reference-01",),
        source_groups=(_source_group(),),
        policies={"frame": {"policy_id": "exact-event/v1"}, "crop": {"policy_id": "crop.v1"}},
        partition="train",
    )
    with pytest.raises(PipelineDatasetError, match="geometry"):
        materialize_pipeline_dataset(
            RevisionCatalog(event_reference, visible_reference, broken_identity),
            request,
            tmp_path / "dataset",
        )
    assert not (tmp_path / "dataset").exists()


def _ignore_region() -> dict[str, object]:
    return {
        "region_id": "img0661-stack-01",
        "geometry": {
            "kind": "reviewed-ignore-region/v1",
            "polygons": [
                [
                    {"x": 0, "y": 0},
                    {"x": 250, "y": 0},
                    {"x": 250, "y": 250},
                    {"x": 0, "y": 250},
                ]
            ],
        },
        "normalization": {
            "width": 100,
            "height": 100,
            "policy_id": "full-frame-0-1000/v1",
        },
        "reason": "untidy_stack",
        "source_candidates": [
            {"revision_id": "img0661-gemini-v1", "card_id": "generated-stack-01"}
        ],
    }


def _visible_reference_with_ignore(
    revision_id: str = "visible-reference-ignore-01",
    *,
    source: RecordingVideoSource = SOURCE,
) -> StoredRevision:
    value = _visible_reference().content.to_mapping()
    value["outcomes"][0]["ignored_regions"] = [_ignore_region()]
    return _vision_revision(
        revision_id,
        "visible_cards",
        VisibleCardData.from_mapping(value),
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "visible_frames",
            "frames": [{"frame_identity": _frame(), "decision": "cards_and_ignored"}],
        },
        source=source,
    )


def _visible_request(
    reference_revision_id: str,
    *,
    source: RecordingVideoSource = SOURCE,
    policy: str | None,
) -> PipelineDatasetRequest:
    return PipelineDatasetRequest(
        task="visible_cards",
        reference_revision_id=reference_revision_id,
        selected_input_revision_ids=("event-reference-01",),
        source_groups=(
            replace(
                _source_group(),
                recording_id=source.recording_id,
                source_sha256=source.video_sha256,
            ),
        ),
        policies={"frame": {"policy_id": "exact-event/v1"}},
        partition="train",
        visible_card_ignore_policy=policy,
    )


def test_visible_dataset_materializes_mask_pixels_and_keeps_clear_mixed_card(
    tmp_path: Path,
) -> None:
    reference = _visible_reference_with_ignore()
    event_reference = _event_reference()
    result = materialize_pipeline_dataset(
        RevisionCatalog(reference, event_reference),
        _visible_request(reference.manifest.revision_id, policy="mask_pixels"),
        tmp_path / "dataset",
    )

    manifest = result["manifest"]
    assert len(manifest["targets"]) == 1
    assert manifest["targets"][0]["card_id"] == "card-01"
    assert manifest["visible_card_ignore_policy"] == "mask_pixels"
    assert len(manifest["ignore_regions"]) == 1
    assert manifest["ignore_regions"][0]["source_candidates"] == [
        {"revision_id": "img0661-gemini-v1", "card_id": "generated-stack-01"}
    ]
    assert manifest["ignore_regions"][0]["effective_ignored_pixel_count"] > 0

    sample = manifest["samples"][0]
    loss_mask = sample["loss_mask"]
    assert loss_mask["applies_to"] == ["positive", "background"]
    packed = base64.b64decode(loss_mask["data_base64"])
    assert (
        loss_mask["ignored_pixel_count"]
        == manifest["ignore_regions"][0]["effective_ignored_pixel_count"]
    )
    assert loss_mask["included_pixel_count"] + loss_mask["ignored_pixel_count"] == 10_000
    assert sum(byte.bit_count() for byte in packed) == loss_mask["included_pixel_count"]
    assert sample["targets"][0]["card_id"] == "card-01"


def test_visible_dataset_excludes_frame_with_exact_source_reason(tmp_path: Path) -> None:
    reference = _visible_reference_with_ignore()
    event_reference = _event_reference()
    result = materialize_pipeline_dataset(
        RevisionCatalog(reference, event_reference),
        _visible_request(reference.manifest.revision_id, policy="exclude_frame"),
        tmp_path / "dataset",
    )

    manifest = result["manifest"]
    assert manifest["samples"] == []
    assert manifest["targets"] == []
    assert manifest["exclusions"] == [
        {
            "event_id": "event-01",
            "frame_identity": _frame(),
            "reason": "untidy_stack",
            "region_ids": ["img0661-stack-01"],
        }
    ]


def test_visible_dataset_requires_an_explicit_ignore_policy(tmp_path: Path) -> None:
    reference = _visible_reference_with_ignore()
    event_reference = _event_reference()
    with pytest.raises(PipelineDatasetError, match="ignore policy"):
        materialize_pipeline_dataset(
            RevisionCatalog(reference, event_reference),
            _visible_request(reference.manifest.revision_id, policy=None),
            tmp_path / "dataset",
        )


def test_visible_dataset_rejects_an_empty_effective_ignore_mask(tmp_path: Path) -> None:
    value = _visible_reference().content.to_mapping()
    value["outcomes"][0]["ignored_regions"] = [_ignore_region()]
    value["outcomes"][0]["ignored_regions"][0]["geometry"]["polygons"] = [
        [
            {"x": 0, "y": 0},
            {"x": 1000, "y": 0},
            {"x": 1000, "y": 1000},
            {"x": 0, "y": 1000},
        ]
    ]
    value["outcomes"][0]["candidates"][0]["geometry"] = {
        "kind": "detector-box/v1",
        "box_2d": {"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
    }
    reference = _vision_revision(
        "visible-reference-empty-ignore",
        "visible_cards",
        VisibleCardData.from_mapping(value),
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "visible_frames",
            "frames": [{"frame_identity": _frame(), "decision": "cards_and_ignored"}],
        },
    )
    with pytest.raises(PipelineDatasetError, match="effective mask is empty"):
        materialize_pipeline_dataset(
            RevisionCatalog(reference, _event_reference()),
            _visible_request(reference.manifest.revision_id, policy="mask_pixels"),
            tmp_path / "dataset",
        )


def test_img_0661_reviewed_ignore_region_keeps_generated_lineage_and_materializes(
    tmp_path: Path,
) -> None:
    annotation_path = (
        Path(__file__).parents[2]
        / "data/operations/cardeventnet-imports/cardeventnet-IMG_0661/annotation.json"
    )
    annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    assert annotation["video"] == "IMG_0661.MOV"
    assert annotation["events"]

    img_source = replace(SOURCE, recording_id="IMG_0661", relative_path="IMG_0661.MOV")
    reference = _visible_reference_with_ignore(source=img_source)
    event_reference = _revision(
        "event-reference-01",
        origin="manual",
        coverage={
            "schema_version": "pipeline-reference-coverage/v1",
            "kind": "event_intervals",
            "intervals": [{"start_us": 0, "end_us": 10}],
            "source_duration_us": 10,
        },
        source=img_source,
    )
    result = materialize_pipeline_dataset(
        RevisionCatalog(reference, event_reference),
        _visible_request(reference.manifest.revision_id, source=img_source, policy="mask_pixels"),
        tmp_path / "dataset",
    )

    assert result["manifest"]["recording_id"] == "IMG_0661"
    assert result["manifest"]["ignore_regions"][0]["reason"] == "untidy_stack"
    assert result["manifest"]["ignore_regions"][0]["source_candidates"]
