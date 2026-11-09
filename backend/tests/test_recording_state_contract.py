from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from dokodetector_backend.recording_state_contract import (
    CatalogMetadataPage,
    CompactAnalysisMetadata,
    CompactJobMetadata,
    CompactPackageMetadata,
    ExactResourceRef,
    HistoryPageCursor,
    IndependentReviewRef,
    JobProjectionAuthority,
    LineageEdgeHistoryItem,
    LineageEndpoint,
    RecordingHead,
    RecordingHeadUpdate,
    RecordingHistoryPage,
    RecordingJobProjection,
    RecordingStateError,
    RecordingStateSnapshot,
    RecordingStateSummary,
    ResourceHistoryItem,
    SlotSelection,
    SnapshotFrozenProcessorInputs,
    SnapshotHistoryItem,
    StageSelection,
    StageSummarySelection,
)

DIGEST = "a" * 64


def _empty() -> SlotSelection:
    return SlotSelection(state="empty")


def _ref(kind="pipeline-node-revision", resource_id="rev-1", **kwargs):
    values = {
        "kind": kind,
        "resource_id": resource_id,
        "schema_version": "pipeline-node-revision/v1",
        "sha256": DIGEST,
    }
    if kind == "pipeline-node-revision":
        values.update(node_id="node-1", revision_id=resource_id)
    values.update(kwargs)
    return ExactResourceRef(**values)


def _slots():
    return {
        key: StageSelection(generated=_empty(), completed_reference=_empty())
        for key in (
            "events",
            "visible_cards",
            "table_plane_calibration",
            "virtual_scenes",
            "visual_identities",
            "table_observations",
            "reconstruction_results",
        )
    }


def _snapshot(**overrides):
    payload = {
        "schema_version": "recording-state-snapshot/v1",
        "recording_id": "recording-1",
        "predecessor_snapshot_id": None,
        "slots": _slots(),
        "independent_reviews": [],
        **overrides,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda value: value.model_dump(mode="json"),
    )
    payload["snapshot_id"] = "rs_" + hashlib.sha256(canonical.encode()).hexdigest()
    return RecordingStateSnapshot(**payload)


def test_snapshot_contract_has_explicit_empty_slots_and_separate_reviews():
    review = IndependentReviewRef(
        review_kind="visible-card-review",
        review_id="review-1",
        resource=_ref(),
        state="in_review",
    )
    slots = _slots()
    slots["visible_cards"] = StageSelection(
        generated=SlotSelection(state="selected", resource=_ref()),
        completed_reference=_empty(),
    )
    snapshot = _snapshot(slots=slots, independent_reviews=[review])
    assert snapshot.slots["events"].generated.state == "empty"
    assert snapshot.slots["visible_cards"].completed_reference.state == "empty"
    assert snapshot.independent_reviews[0].review_id == "review-1"
    assert snapshot.independent_reviews[0].resource.revision_id == "rev-1"


def test_snapshot_identity_rejects_a_digest_that_does_not_match_content():
    slots = _slots()
    with pytest.raises(ValidationError, match="canonical snapshot digest"):
        RecordingStateSnapshot(
            recording_id="recording-1",
            snapshot_id="rs_" + "b" * 64,
            slots=slots,
        )


def test_empty_and_stale_slot_rules_are_explicit():
    with pytest.raises(ValidationError, match="empty selection"):
        SlotSelection(state="empty", resource=_ref())
    with pytest.raises(ValidationError, match="stale selection requires"):
        SlotSelection(state="stale", resource=_ref())
    stale = SlotSelection(
        state="stale",
        resource=_ref(),
        stale_reason="dependency_changed",
    )
    assert stale.resource is not None


def test_resource_kind_matches_calibration_and_reconstruction_slots():
    slots = _slots()
    slots["table_plane_calibration"] = StageSelection(
        generated=SlotSelection(state="selected", resource=_ref()),
        completed_reference=_empty(),
    )
    with pytest.raises(ValidationError, match="calibration slot"):
        _snapshot(recording_id="r1", slots=slots)


def test_exact_node_revision_requires_consistent_ids():
    with pytest.raises(ValidationError, match="resource_id must equal revision_id"):
        _ref(resource_id="other", revision_id="rev-1")


def test_missing_and_corrupt_references_have_typed_failures():
    missing = RecordingStateError(
        code="recording_resource_missing", message="The exact resource is not available."
    )
    corrupt = RecordingStateError(
        code="recording_resource_corrupt", message="The exact resource failed validation."
    )
    assert missing.code != corrupt.code


def test_summary_keeps_generated_and_reference_states_separate():
    slots = {
        key: StageSummarySelection(generated="empty", completed_reference="empty")
        for key in (
            "events",
            "visible_cards",
            "table_plane_calibration",
            "virtual_scenes",
            "visual_identities",
            "table_observations",
            "reconstruction_results",
        )
    }
    slots["events"] = StageSummarySelection(generated="stale", completed_reference="selected")
    summary = RecordingStateSummary(
        recording_id="recording-1",
        head_version=3,
        snapshot_id=_snapshot().snapshot_id,
        snapshot_sha256=DIGEST,
        slots=slots,
    )
    assert summary.slots["events"].generated == "stale"
    assert summary.slots["events"].completed_reference == "selected"


def test_history_pages_accept_snapshot_resources_and_lineage_edges():
    snapshot_page = RecordingHistoryPage(
        recording_id="recording-1",
        collection="snapshots",
        items=[
            SnapshotHistoryItem(
                item_key="rs_entry-1",
                snapshot_id=_snapshot().snapshot_id,
                sha256=DIGEST,
                publication_sequence=10,
            )
        ],
        upper_bound_sequence=10,
        has_more=False,
    )
    revision_page = RecordingHistoryPage(
        recording_id="recording-1",
        collection="revisions",
        items=[ResourceHistoryItem(item_key="rev-1", resource=_ref(), publication_sequence=10)],
        upper_bound_sequence=10,
        has_more=False,
    )
    edge_page = RecordingHistoryPage(
        recording_id="recording-1",
        collection="lineage_edges",
        items=[
            LineageEdgeHistoryItem(
                item_key="edge-1",
                edge_kind="used",
                source=LineageEndpoint(kind="revision", node_id="node-1", revision_id="rev-1"),
                target=LineageEndpoint(kind="run", run_id="run-1"),
                publication_sequence=10,
                role="input",
            )
        ],
        upper_bound_sequence=10,
        has_more=False,
    )
    assert snapshot_page.items[0].item_kind == "snapshot"
    assert revision_page.items[0].item_kind == "resource"
    assert edge_page.items[0].item_kind == "lineage_edge"
    with pytest.raises(ValidationError, match="items must match collection"):
        RecordingHistoryPage(
            recording_id="recording-1",
            collection="snapshots",
            upper_bound_sequence=10,
            items=[ResourceHistoryItem(item_key="rev-1", resource=_ref(), publication_sequence=10)],
            has_more=False,
        )


@pytest.mark.parametrize(
    "artifact_id",
    ["recording-video/recording-1", "evidence-package/package-1"],
)
def test_lineage_artifact_endpoint_accepts_namespaced_ids(artifact_id: str):
    endpoint = LineageEndpoint(kind="artifact", artifact_id=artifact_id, sha256=DIGEST)
    assert endpoint.artifact_id == artifact_id


def test_snapshot_history_cursor_excludes_later_hashes_below_sort_order():
    cursor = HistoryPageCursor(
        recording_id="recording-1",
        collection="snapshots",
        filter_sha256=DIGEST,
        upper_bound_sequence=10,
        page_size=100,
    )
    inserted_later = SnapshotHistoryItem(
        item_key="rs_" + "0" * 64,
        snapshot_id="rs_" + "0" * 64,
        sha256=DIGEST,
        publication_sequence=11,
    )
    assert inserted_later.item_key < "rs_" + "f" * 64
    with pytest.raises(ValidationError, match="exceeds the frozen insertion boundary"):
        RecordingHistoryPage(
            recording_id="recording-1",
            collection="snapshots",
            upper_bound_sequence=cursor.upper_bound_sequence,
            items=[inserted_later],
            has_more=False,
        )


def test_catalog_metadata_pages_are_bounded_and_collection_typed():
    page = CatalogMetadataPage(
        recording_id="recording-1",
        collection="jobs",
        items=[
            CompactJobMetadata(
                job_id="job-1",
                schema_version="backend-job/v1",
                status="running",
                updated_at="2026-11-09T12:00:00Z",
            )
        ],
        has_more=False,
    )
    assert page.items[0].item_kind == "job"
    with pytest.raises(ValidationError, match="items must match collection"):
        CatalogMetadataPage(
            recording_id="recording-1",
            collection="jobs",
            items=[
                CompactPackageMetadata(
                    package_id="package-1",
                    schema_version="evidence-package/v1",
                    status="available",
                )
            ],
            has_more=False,
        )
    with pytest.raises(ValidationError):
        CatalogMetadataPage(
            recording_id="recording-1",
            collection="jobs",
            items=[
                CompactJobMetadata(
                    job_id=f"job-{index}",
                    schema_version="backend-job/v1",
                    status="running",
                    updated_at="2026-11-09T12:00:00Z",
                )
                for index in range(101)
            ],
            has_more=False,
        )


def test_job_projection_uses_manager_authority_and_bounded_preview():
    job = CompactJobMetadata(
        job_id="job-1",
        schema_version="backend-job/v1",
        status="running",
        updated_at="2026-11-09T12:00:00Z",
    )
    authority = JobProjectionAuthority(manager_id="job-manager", epoch="epoch-1", sequence=12)
    projection = RecordingJobProjection(
        recording_id="recording-1",
        authority_epoch="epoch-1",
        authority_sequence=12,
        active_job_count=1,
        jobs=[job],
        has_more=False,
    )
    projection.validate_authority(authority)
    restarted_authority = JobProjectionAuthority(
        manager_id="job-manager", epoch="epoch-1", sequence=12
    )
    projection.validate_authority(restarted_authority)
    HistoryPageCursor(
        recording_id="recording-1",
        collection="jobs",
        filter_sha256=DIGEST,
        upper_bound_sequence=12,
        page_size=20,
        authority_epoch=authority.epoch,
        authority_sequence=authority.sequence,
    )
    with pytest.raises(ValueError, match="job projection is stale"):
        projection.validate_authority(
            JobProjectionAuthority(manager_id="job-manager", epoch="epoch-1", sequence=13)
        )
    with pytest.raises(ValidationError, match="must pin Job Manager authority"):
        HistoryPageCursor(
            recording_id="recording-1",
            collection="jobs",
            filter_sha256=DIGEST,
            upper_bound_sequence=12,
            page_size=20,
        )
    with pytest.raises(ValidationError, match="continuation must match active_job_count"):
        RecordingJobProjection(
            recording_id="recording-1",
            authority_epoch="epoch-1",
            authority_sequence=12,
            active_job_count=1,
            jobs=[],
            has_more=False,
        )


def test_head_update_requires_explicit_cas_and_restore_action():
    update = RecordingHeadUpdate(
        recording_id="recording-1",
        expected_head_version=4,
        snapshot_id=_snapshot().snapshot_id,
        action="restore_snapshot",
    )
    assert update.expected_head_version == 4
    head = RecordingHead(recording_id="recording-1", version=5, snapshot_id=_snapshot().snapshot_id)
    assert head.version == 5


def test_history_page_is_bounded_and_cursor_presence_matches_has_more():
    page = RecordingHistoryPage(
        recording_id="recording-1",
        collection="revisions",
        upper_bound_sequence=1,
        items=[ResourceHistoryItem(item_key="rev-1", resource=_ref(), publication_sequence=1)],
        next_cursor="opaque-cursor",
        has_more=True,
    )
    assert page.next_cursor == "opaque-cursor"
    with pytest.raises(ValidationError, match="has_more must match"):
        RecordingHistoryPage(
            recording_id="recording-1",
            collection="snapshots",
            upper_bound_sequence=1,
            items=[],
            has_more=True,
        )
    with pytest.raises(ValidationError):
        RecordingHistoryPage(
            recording_id="recording-1",
            collection="snapshots",
            upper_bound_sequence=1,
            items=[
                ResourceHistoryItem(
                    item_key=f"rev-{index}", resource=_ref(), publication_sequence=1
                )
                for index in range(101)
            ],
            has_more=False,
        )


def test_frozen_processor_inputs_require_expected_head_for_select_on_completion():
    request = SnapshotFrozenProcessorInputs(
        recording_id="recording-1",
        snapshot_id=_snapshot().snapshot_id,
        head_version=5,
        inputs={"events": [_ref()]},
    )
    assert request.inputs["events"][0].revision_id == "rev-1"
    with pytest.raises(ValidationError, match="expected_head_version"):
        SnapshotFrozenProcessorInputs(
            recording_id="recording-1",
            snapshot_id=_snapshot().snapshot_id,
            head_version=5,
            inputs={},
            select_output_on_completion=True,
        )


def test_compact_metadata_contracts_do_not_embed_history_or_payloads():
    analysis = CompactAnalysisMetadata(
        analysis_id="analysis-1",
        schema_version="round-analysis/v1",
        status="complete",
        created_at="2026-11-09T12:00:00Z",
        updated_at="2026-11-09T12:01:00Z",
        result_sha256=DIGEST,
    )
    package = CompactPackageMetadata(
        package_id="package-1",
        schema_version="evidence-package/v1",
        status="available",
        manifest_sha256=DIGEST,
    )
    job = CompactJobMetadata(
        job_id="job-1",
        schema_version="backend-job/v1",
        status="running",
        updated_at="2026-11-09T12:01:00Z",
    )
    assert analysis.result_sha256 == package.manifest_sha256 == DIGEST
    assert job.status == "running"
