from __future__ import annotations

import json
from pathlib import Path

import pytest

from dokodetector_backend.intake_contract import (
    TASK_CARD_EVENT,
    TASK_TABLE_EVIDENCE,
    IntakeContractError,
    parse_evidence_package_bundle,
    parse_evidence_package_lineage,
    parse_evidence_package_record,
    parse_pending_video,
    parse_repository_bundle,
    validate_evidence_package_bundle,
    validate_repository_bundle,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository-bundle" / "v1"
FIXTURES = ("cardevent-only", "table-evidence-only", "both")
EVIDENCE_FIXTURE_ROOT = (
    Path(__file__).parents[2]
    / "fixtures"
    / "repository-intake"
    / "v1"
    / "evidence-package-complete"
)
PENDING_FIXTURE_ROOT = (
    Path(__file__).parents[2] / "fixtures" / "repository-intake" / "v1" / "pending-video"
)


def _documents(name: str) -> tuple[bytes, bytes, bytes, dict[str, bytes]]:
    root = FIXTURE_ROOT / name
    return (
        (root / "manifest.json").read_bytes(),
        (root / "source-record.json").read_bytes(),
        (root / "initial-task-enrollment.json").read_bytes(),
        {path.stem: path.read_bytes() for path in (root / "predictions").glob("*.json")},
    )


@pytest.mark.parametrize("fixture_name", FIXTURES)
def test_backend_accepts_each_independent_task_enrollment_fixture(fixture_name: str) -> None:
    manifest, source, enrollment, runs = _documents(fixture_name)
    bundle, source_record, task_enrollment, proposal_runs = validate_repository_bundle(
        manifest, source, enrollment, runs
    )
    video = (FIXTURE_ROOT / fixture_name / bundle.files.video.relative_path).read_bytes()

    assert len(video) == bundle.files.video.byte_length
    assert len(source) == bundle.files.source_record.byte_length
    assert len(enrollment) == bundle.files.task_enrollment.byte_length
    assert all(
        len(runs[descriptor.proposal_generator_run_id]) == descriptor.byte_length
        for descriptor in bundle.files.proposal_generator_runs
    )
    assert source_record.sha256 == bundle.source_sha256
    assert task_enrollment.source_asset_id == bundle.source_asset_id
    assert len(proposal_runs) == len(bundle.files.proposal_generator_runs)
    assert all(run.purpose == "proposal_only" for run in proposal_runs)

    selected = {item.task for item in task_enrollment.enrollments if item.disposition == "selected"}
    expected = {
        "cardevent-only": {TASK_CARD_EVENT},
        "table-evidence-only": {TASK_TABLE_EVIDENCE},
        "both": {TASK_CARD_EVENT, TASK_TABLE_EVIDENCE},
    }
    assert selected == expected[fixture_name]


def test_backend_rejects_legacy_alias_and_unknown_fields() -> None:
    manifest, source, enrollment, runs = _documents("both")
    document = json.loads(manifest)
    document["recording"] = document.pop("recording_id")
    with pytest.raises(IntakeContractError):
        parse_repository_bundle(json.dumps(document).encode())

    enrollment_document = json.loads(enrollment)
    enrollment_document["enrollments"][0]["legacy_disposition"] = "selected"
    with pytest.raises(IntakeContractError):
        validate_repository_bundle(manifest, source, json.dumps(enrollment_document).encode(), runs)


def test_backend_keeps_proposal_lineage_separate_from_enrollment() -> None:
    manifest, source, enrollment, runs = _documents("table-evidence-only")
    _, _, task_enrollment, proposal_runs = validate_repository_bundle(
        manifest, source, enrollment, runs
    )
    assert task_enrollment.enrollments[0].disposition == "deferred"
    assert task_enrollment.enrollments[1].disposition == "selected"
    assert proposal_runs[0].source_asset_id == task_enrollment.source_asset_id
    assert proposal_runs[0].purpose == "proposal_only"


def test_backend_accepts_pending_video_receipt_and_rejects_unknown_fields() -> None:
    receipt = parse_pending_video((PENDING_FIXTURE_ROOT / "manifest.json").read_bytes())
    assert receipt.upload_id == "upload-pending-001"
    assert receipt.media_facts.frame_count == 300

    malformed = json.loads((PENDING_FIXTURE_ROOT / "manifest.json").read_bytes())
    malformed["session_id"] = "must-not-be-invented"
    with pytest.raises(IntakeContractError):
        parse_pending_video(json.dumps(malformed).encode())


def test_backend_accepts_evidence_package_bundle_and_verifies_all_members() -> None:
    root = EVIDENCE_FIXTURE_ROOT
    manifest = (root / "manifest.json").read_bytes()
    evidence_manifest = (root / "evidence-manifest.json").read_bytes()
    package_record = (root / "package-record.json").read_bytes()
    task_enrollment = (root / "initial-task-enrollment.json").read_bytes()
    lineage = (root / "lineage.json").read_bytes()
    bundle = parse_evidence_package_bundle(manifest)
    members = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }

    validated, record, enrollment, package_lineage = validate_evidence_package_bundle(
        manifest, evidence_manifest, package_record, task_enrollment, lineage, members
    )

    assert validated == bundle
    assert record.source_permission == "training_and_evaluation"
    assert {item.task for item in enrollment.enrollments} == {
        "cardevent_event_detection",
        "table_evidence_analysis",
    }
    assert package_lineage.parent_recording_id == "recording-both"
    assert parse_evidence_package_record(package_record) == record
    assert parse_evidence_package_lineage(lineage) == package_lineage
