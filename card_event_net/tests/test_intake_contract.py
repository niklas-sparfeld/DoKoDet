from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import pytest

from cardevent.intake_contract import (
    DATA_TASKS,
    TASK_CARD_EVENT,
    TASK_TABLE_EVIDENCE,
    IntakeContractError,
    parse_evidence_package_bundle,
    parse_evidence_package_lineage,
    parse_evidence_package_record,
    parse_json_bytes,
    parse_pending_video,
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


def _documents(
    name: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], dict[str, Mapping[str, Any]]]:
    root = FIXTURE_ROOT / name
    manifest = parse_json_bytes((root / "manifest.json").read_bytes(), "manifest")
    source = parse_json_bytes((root / "source-record.json").read_bytes(), "source")
    enrollments = parse_json_bytes(
        (root / "initial-task-enrollment.json").read_bytes(), "enrollments"
    )
    runs = {
        path.stem: parse_json_bytes(path.read_bytes(), "proposal run")
        for path in (root / "predictions").glob("*.json")
    }
    return manifest, source, enrollments, runs


@pytest.mark.parametrize("fixture_name", FIXTURES)
def test_replacement_bundle_fixture_round_trips_and_verifies_bytes(fixture_name: str) -> None:
    manifest, source_bytes, enrollment_bytes, run_bytes = _documents(fixture_name)
    bundle, source, enrollments, runs = validate_repository_bundle(
        manifest, source_bytes, enrollment_bytes, run_bytes
    )

    root = FIXTURE_ROOT / fixture_name
    video = (root / bundle.files.video.relative_path).read_bytes()
    bundle.files.video.verify_bytes(video)
    source.verify_bytes(video)
    bundle.files.source_record.verify_bytes(
        (root / bundle.files.source_record.relative_path).read_bytes()
    )
    bundle.files.task_enrollment.verify_bytes(
        (root / bundle.files.task_enrollment.relative_path).read_bytes()
    )
    for descriptor in bundle.files.proposal_generator_runs:
        descriptor.verify_bytes((root / descriptor.relative_path).read_bytes())
    assert source.sha256 == bundle.source_sha256
    assert enrollments.source_asset_id == source.source_asset_id
    assert {item.task for item in enrollments.enrollments} == DATA_TASKS
    assert all(run.purpose == "proposal_only" for run in runs)
    assert all(run.source_asset_id == source.source_asset_id for run in runs)

    selected = {item.task for item in enrollments.enrollments if item.disposition == "selected"}
    expected = {
        "cardevent-only": {TASK_CARD_EVENT},
        "table-evidence-only": {TASK_TABLE_EVIDENCE},
        "both": DATA_TASKS,
    }
    assert selected == expected[fixture_name]


def test_task_enrollment_is_independent_from_immutable_source_bytes() -> None:
    manifest, source_bytes, enrollment_bytes, run_bytes = _documents("both")
    _, source_before, _, _ = validate_repository_bundle(
        manifest, source_bytes, enrollment_bytes, run_bytes
    )
    changed = copy.deepcopy(enrollment_bytes)
    changed["enrollments"][0]["disposition"] = "deferred"
    changed["enrollments"][0]["lifecycle_state"] = "intake"
    changed_bytes = changed
    _, source_after, enrollments_after, _ = validate_repository_bundle(
        manifest, source_bytes, changed_bytes, run_bytes
    )

    assert source_after == source_before
    assert source_after.sha256 == source_before.sha256
    assert enrollments_after.for_task(TASK_CARD_EVENT).disposition == "deferred"


def test_proposal_run_is_lineage_only_and_has_no_dataset_membership_field() -> None:
    manifest, source_bytes, enrollment_bytes, run_bytes = _documents("table-evidence-only")
    _, _, enrollments, runs = validate_repository_bundle(
        manifest, source_bytes, enrollment_bytes, run_bytes
    )

    assert enrollments.for_task(TASK_TABLE_EVIDENCE).disposition == "selected"
    assert runs[0].purpose == "proposal_only"
    assert "dataset_membership" not in next(iter(run_bytes.values()))


@pytest.mark.parametrize("fixture_name", FIXTURES)
def test_strict_contract_rejects_unknown_or_malformed_fields(fixture_name: str) -> None:
    manifest, source_bytes, enrollment_bytes, run_bytes = _documents(fixture_name)

    malformed_manifest = copy.deepcopy(manifest)
    malformed_manifest["unexpected"] = True
    with pytest.raises(IntakeContractError):
        validate_repository_bundle(malformed_manifest, source_bytes, enrollment_bytes, run_bytes)

    malformed_enrollment = copy.deepcopy(enrollment_bytes)
    malformed_enrollment["enrollments"][0]["task"] = "cardevent"
    with pytest.raises(IntakeContractError):
        validate_repository_bundle(manifest, source_bytes, malformed_enrollment, run_bytes)

    run_object = copy.deepcopy(next(iter(run_bytes.values())))
    run_object["purpose"] = "dataset_membership"
    malformed_runs = {next(iter(run_bytes)): run_object}
    with pytest.raises(IntakeContractError):
        validate_repository_bundle(manifest, source_bytes, enrollment_bytes, malformed_runs)


def test_json_parser_rejects_non_object_and_invalid_utf8() -> None:
    with pytest.raises(IntakeContractError):
        parse_json_bytes(b"[]", "fixture")
    with pytest.raises(IntakeContractError):
        parse_json_bytes(b"\xff", "fixture")


def test_cardevent_decodes_pending_and_evidence_package_contracts() -> None:
    pending = parse_pending_video((PENDING_FIXTURE_ROOT / "manifest.json").read_bytes())
    bundle = parse_evidence_package_bundle((EVIDENCE_FIXTURE_ROOT / "manifest.json").read_bytes())
    record = parse_evidence_package_record(
        (EVIDENCE_FIXTURE_ROOT / "package-record.json").read_bytes()
    )
    lineage = parse_evidence_package_lineage((EVIDENCE_FIXTURE_ROOT / "lineage.json").read_bytes())

    assert pending.media_facts.frame_count == 300
    assert bundle.package_id == record.package_id == lineage.package_id
    assert bundle.source_asset_id == record.source_asset_id
    assert len(bundle.files.frames) == 6
