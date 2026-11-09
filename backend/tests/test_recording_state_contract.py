from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from dokodetector_backend.recording_state_contract import (
    CompactAnalysisMetadata,
    CompactJobMetadata,
    CompactPackageMetadata,
    ExactResourceRef,
    IndependentReviewRef,
    RecordingHead,
    RecordingHeadUpdate,
    RecordingHistoryPage,
    RecordingStateError,
    RecordingStateSnapshot,
    SlotSelection,
    SnapshotFrozenProcessorInputs,
    StageSelection,
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
        items=[_ref()],
        next_cursor="opaque-cursor",
        has_more=True,
    )
    assert page.next_cursor == "opaque-cursor"
    with pytest.raises(ValidationError, match="has_more must match"):
        RecordingHistoryPage(
            recording_id="recording-1", collection="snapshots", items=[], has_more=True
        )
    with pytest.raises(ValidationError):
        RecordingHistoryPage(
            recording_id="recording-1",
            collection="snapshots",
            items=[_ref() for _ in range(101)],
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
