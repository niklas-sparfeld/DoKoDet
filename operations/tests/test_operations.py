from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from doko_operations.cli import build_parser, main
from doko_operations.evidence_package import load_evidence_package
from doko_operations.holdout import (
    SystemHoldoutError,
    load_system_holdout_registry,
    seal_system_holdout_group,
    validate_split_against_system_holdout,
    validate_system_holdout_registry,
)
from doko_operations.impact import (
    analyze_source_impact,
    load_current_source_state,
    retire_source,
    validate_stale_artifact_receipt,
)
from doko_operations.intake import discover_bundle_paths, inspect_repository
from doko_operations.status import render_json

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "repository-bundle" / "v1"
PENDING_FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "repository-intake" / "v1" / "pending-video"
EVIDENCE_PACKAGE_FIXTURE_ROOT = (
    REPOSITORY_ROOT / "fixtures" / "repository-intake" / "v1" / "evidence-package-complete"
)


def test_fixture_discovery_is_deterministic_and_includes_all_three_cases() -> None:
    paths = discover_bundle_paths(FIXTURE_ROOT)

    assert [path.name for path in paths] == ["both", "cardevent-only", "table-evidence-only"]


def test_status_reports_independent_task_enrollment_and_pending_work() -> None:
    result = inspect_repository(REPOSITORY_ROOT, bundle_root=FIXTURE_ROOT)

    assert result.valid
    assert [item.state for item in result.bundles] == ["complete", "complete", "complete"]
    selected = {
        (task.source_asset_id, task.task)
        for bundle in result.bundles
        for task in bundle.tasks
        if task.disposition == "selected"
    }
    assert selected == {
        ("source-both", "cardevent_event_detection"),
        ("source-both", "table_evidence_analysis"),
        ("source-cardevent-only", "cardevent_event_detection"),
        ("source-table-evidence-only", "table_evidence_analysis"),
    }
    assert {(item.source_asset_id, item.task) for item in result.pending_review} == selected


def test_status_reports_canonical_evidence_package() -> None:
    result = inspect_repository(
        REPOSITORY_ROOT,
        bundle_root=FIXTURE_ROOT,
        evidence_package_root=EVIDENCE_PACKAGE_FIXTURE_ROOT,
    )

    assert result.valid
    assert len(result.evidence_packages) == 1
    assert result.evidence_packages[0].state == "complete"
    assert result.evidence_packages[0].selected_tasks == (
        "cardevent_event_detection",
        "table_evidence_analysis",
    )


def test_obsolete_data_review_command_is_not_registered() -> None:
    parser = build_parser()
    command_parsers = next(
        action for action in parser._subparsers._group_actions if action.dest == "command"
    )
    data_parser = command_parsers.choices["data"]
    data_command_parsers = next(
        action for action in data_parser._subparsers._group_actions if action.dest == "data_command"
    )

    assert "review" not in data_command_parsers.choices


def test_status_reports_ready_and_invalid_pending_videos(tmp_path: Path) -> None:
    pending_root = tmp_path / "incoming" / "videos"
    shutil.copytree(PENDING_FIXTURE_ROOT, pending_root / "upload-pending-001")
    shutil.copytree(PENDING_FIXTURE_ROOT, pending_root / "upload-pending-002")
    (pending_root / "upload-pending-002" / "manifest.json").write_text(
        (pending_root / "upload-pending-002" / "manifest.json")
        .read_text()
        .replace("upload-pending-001", "upload-pending-002")
    )
    (pending_root / "upload-pending-002" / "video-pending.mov").write_bytes(b"changed")

    result = inspect_repository(
        REPOSITORY_ROOT,
        bundle_root=FIXTURE_ROOT,
        pending_video_root=pending_root,
    )

    assert {item.state for item in result.pending_videos} == {"invalid", "ready_to_complete"}
    assert not result.valid
    assert any("digest differs" in failure.message for failure in result.failures)


def test_complete_video_command_publishes_a_recording_bundle(tmp_path: Path, capsys) -> None:
    from test_pending_video import _metadata, _write_pending

    _write_pending(tmp_path / "data" / "incoming" / "videos")
    metadata = tmp_path / "completion.json"
    metadata.write_text(json.dumps(_metadata()))

    assert (
        main(
            [
                "data",
                "complete-video",
                "--repository-root",
                str(tmp_path),
                "--upload-id",
                "upload-001",
                "--metadata",
                str(metadata),
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["recording_id"] == "recording-upload-001"
    assert (tmp_path / "data" / "intake" / "recordings" / "recording-upload-001").is_dir()


def test_adopt_evidence_command_publishes_canonical_bundle_without_deleting_runtime(
    tmp_path: Path, capsys
) -> None:
    package_id = "550e8400-e29b-41d4-a716-446655440000"
    legacy = tmp_path / "runtime" / "evidence" / package_id
    shutil.copytree(EVIDENCE_PACKAGE_FIXTURE_ROOT / "frames", legacy / "frames")
    shutil.copytree(EVIDENCE_PACKAGE_FIXTURE_ROOT / "video", legacy / "video")
    shutil.copy(EVIDENCE_PACKAGE_FIXTURE_ROOT / "evidence-manifest.json", legacy / "manifest.json")
    destination = tmp_path / "data" / "intake" / "evidence-packages"

    assert (
        main(
            [
                "data",
                "adopt-evidence",
                "--repository-root",
                str(tmp_path),
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--package-id",
                package_id,
                "--metadata",
                str(EVIDENCE_PACKAGE_FIXTURE_ROOT),
                "--evidence-package-root",
                str(destination),
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "adopted"
    assert load_evidence_package(destination / package_id).bundle.package_id == package_id
    assert legacy.is_dir()

    assert (
        main(
            [
                "data",
                "adopt-evidence-package",
                "--repository-root",
                str(tmp_path),
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--package-id",
                package_id,
                "--metadata",
                str(EVIDENCE_PACKAGE_FIXTURE_ROOT),
                "--evidence-package-root",
                str(destination),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["state"] == "already_adopted"


def test_incomplete_bundle_is_reported_without_writing_the_bundle(tmp_path: Path) -> None:
    root = tmp_path / "intake"
    shutil.copytree(FIXTURE_ROOT / "both", root / "both")
    proposal = root / "both" / "predictions" / "proposal-both.json"
    before = (root / "both" / "manifest.json").read_bytes()
    proposal.unlink()

    result = inspect_repository(tmp_path, bundle_root=root)

    assert result.bundles[0].state == "incomplete"
    assert any("member file is missing" in error for error in result.bundles[0].errors)
    assert (root / "both" / "manifest.json").read_bytes() == before
    assert not (root / "both" / "sqlite.db").exists()


def test_invalid_bundle_and_validation_exit_are_reported(tmp_path: Path, capsys) -> None:
    root = tmp_path / "intake"
    shutil.copytree(FIXTURE_ROOT / "both", root / "invalid")
    manifest_path = root / "invalid" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["unexpected"] = True
    manifest_path.write_text(json.dumps(manifest))

    assert (
        main(
            [
                "data",
                "validate",
                "--repository-root",
                str(tmp_path),
                "--intake-root",
                str(root),
                "--format",
                "json",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert '"valid": false' in output
    assert '"state": "invalid"' in output


def test_json_output_is_stable_and_reports_run_split_and_stale_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "intake"
    shutil.copytree(FIXTURE_ROOT / "cardevent-only", root / "cardevent-only")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "review-runs").mkdir()
    (artifacts / "review-runs" / "run.json").write_text(
        json.dumps(
            {
                "task": "cardevent_event_detection",
                "source_asset_id": "source-cardevent-only",
                "state": "interrupted",
            }
        )
    )
    (artifacts / "split.json").write_text(
        json.dumps({"task": "cardevent_event_detection", "unassigned": ["session-new"]})
    )
    (artifacts / "stale.json").write_text(json.dumps({"stale": True}))
    result = inspect_repository(
        tmp_path,
        bundle_root=root,
        artifacts_root=artifacts,
    )

    assert result.pending_review[0].resumable
    assert result.pending_review[0].run_path == "artifacts/review-runs/run.json"
    assert result.unassigned_eligible_groups == ("cardevent_event_detection:session-new",)
    assert result.stale_derived_artifacts == ("artifacts/stale.json",)
    first = render_json(result, repository_root=tmp_path, bundle_root=root)
    second = render_json(result, repository_root=tmp_path, bundle_root=root)
    assert first == second


def test_deferred_enrollment_does_not_create_review_work() -> None:
    result = inspect_repository(REPOSITORY_ROOT, bundle_root=FIXTURE_ROOT / "cardevent-only")

    bundle = result.bundles[0]
    table_task = next(task for task in bundle.tasks if task.task == "table_evidence_analysis")
    assert table_task.disposition == "deferred"
    assert all(item.task != "table_evidence_analysis" for item in result.pending_review)


def test_system_holdout_seal_is_explicit_reviewed_and_versioned(tmp_path: Path) -> None:
    registry_path = tmp_path / "system-holdout-registry.json"

    assert not registry_path.exists()
    sealed = seal_system_holdout_group(
        registry_path,
        group_name="session_id",
        group_value="session-held-out",
        reviewer="holdout-reviewer",
        review_id="review-holdout-1",
        reason="Reserve one complete session for end-to-end evaluation.",
    )

    validate_system_holdout_registry(sealed)
    loaded = load_system_holdout_registry(registry_path)
    assert loaded == sealed
    assert loaded["registry_version"] == 1
    assert loaded["seals"][0]["review_state"] == "reviewed"
    assert loaded["seals"][0]["review_id"] == "review-holdout-1"
    with pytest.raises(SystemHoldoutError, match="already sealed"):
        seal_system_holdout_group(
            registry_path,
            group_name="session_id",
            group_value="session-held-out",
            reviewer="holdout-reviewer",
            reason="Duplicate seal must be rejected.",
        )


def test_system_holdout_validation_rejects_training_and_group_leakage(tmp_path: Path) -> None:
    registry_path = tmp_path / "system-holdout-registry.json"
    registry = seal_system_holdout_group(
        registry_path,
        group_name="session_id",
        group_value="session-held-out",
        reviewer="holdout-reviewer",
        reason="Reserve the session for system evaluation.",
    )
    dataset = {
        "entries": [
            {
                "dataset_item_id": "item-held-out",
                "group_keys": [["session_id", "session-held-out"]],
            },
            {
                "dataset_item_id": "item-other",
                "group_keys": [["session_id", "session-other"]],
            },
        ]
    }
    with pytest.raises(SystemHoldoutError, match="system holdout group"):
        validate_split_against_system_holdout(
            dataset,
            {
                "train": ["item-held-out"],
                "validation": [],
                "test": [],
                "unassigned": ["item-other"],
            },
            registry,
            "cardevent_event_detection",
        )
    leakage_dataset = {
        "entries": [
            {"dataset_item_id": "item-one", "group_keys": [["session_id", "session-shared"]]},
            {"dataset_item_id": "item-two", "group_keys": [["session_id", "session-shared"]]},
        ]
    }
    with pytest.raises(SystemHoldoutError, match="crosses group"):
        validate_split_against_system_holdout(
            leakage_dataset,
            {
                "train": ["item-one"],
                "validation": ["item-two"],
                "test": [],
                "unassigned": [],
            },
            registry,
            "cardevent_event_detection",
        )


def test_source_retirement_reports_cross_task_artifacts_and_writes_only_new_receipts(
    tmp_path: Path,
) -> None:
    intake = tmp_path / "intake"
    shutil.copytree(FIXTURE_ROOT, intake)
    artifacts = tmp_path / "artifacts"
    source_id = "source-both"
    source_digest = "7184fd89dd78b265e8f617989e8a9659897e060bde2d4f8d47dc05708771f8a8"

    def write(relative: str, payload: dict[str, object]) -> None:
        path = artifacts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    write(
        "published/cardevent_event_detection/cardevent/annotations/annotation-both.json",
        {
            "schema_version": "cardevent-annotation/v2",
            "source_asset_id": source_id,
            "source_sha256": source_digest,
        },
    )
    write(
        "published/cardevent_event_detection/cardevent/dataset/cardevent-dataset.json",
        {
            "schema_version": "cardevent-dataset-version/v1",
            "task": "cardevent_event_detection",
            "dataset_version_id": "dataset-cardevent-both",
            "source_assets": [{"source_asset_id": source_id, "source_sha256": source_digest}],
        },
    )
    write(
        "published/cardevent_event_detection/cardevent/split/cardevent-split.json",
        {
            "schema_version": "cardevent-split-proposal/v1",
            "task": "cardevent_event_detection",
            "dataset_version_id": "dataset-cardevent-both",
        },
    )
    write(
        "published/cardevent_event_detection/cardevent/cache/cache.json",
        {
            "schema_version": "cardevent-cache-refresh/v1",
            "task": "cardevent_event_detection",
            "source_assets": [{"source_asset_id": source_id, "source_sha256": source_digest}],
        },
    )
    write(
        "published/table_evidence_analysis/table-evidence/annotations/annotation-both.json",
        {
            "schema_version": "table-observation-annotation/v1",
            "source_asset_id": source_id,
            "source_sha256": source_digest,
        },
    )
    write(
        "published/table_evidence_analysis/table-evidence/dataset/table-dataset.json",
        {
            "schema_version": "dataset-version/v1",
            "task": "table_evidence_analysis",
            "dataset_version_id": "dataset-table-both",
            "source_assets": [{"source_asset_id": source_id, "source_sha256": source_digest}],
        },
    )
    write(
        "published/table_evidence_analysis/table-evidence/split/table-split.json",
        {
            "schema_version": "table-dataset-split/v1",
            "task": "table_evidence_analysis",
            "dataset_version_id": "dataset-table-both",
        },
    )
    write(
        "runs/table-run.json",
        {
            "schema_version": "training-run/v1",
            "run_id": "table-run-both",
            "task": "table_evidence_analysis",
            "dataset_version_id": "dataset-table-both",
        },
    )
    write(
        "models/table-model.json",
        {
            "schema_version": "model-bundle/v1",
            "model_bundle_id": "table-model-both",
            "task": "table_evidence_analysis",
            "training_run_id": "table-run-both",
        },
    )
    write("published/unrelated.json", {"schema_version": "unrelated/v1", "valid": True})

    source_before = (intake / "both" / "source-record.json").read_bytes()
    enrollment_before = (intake / "both" / "initial-task-enrollment.json").read_bytes()
    video_before = (intake / "both" / "videos" / "video-both.mov").read_bytes()

    preview = analyze_source_impact(
        tmp_path,
        source_id,
        bundle_root=intake,
        artifacts_root=artifacts,
        requested_retention_state="retired",
    )
    assert {task["task"] for task in preview["task_impacts"]} == {
        "cardevent_event_detection",
        "table_evidence_analysis",
    }
    assert preview["artifact_counts"] == {
        "annotations": 2,
        "caches": 1,
        "datasets": 2,
        "model_bundles": 1,
        "runs": 1,
        "splits": 2,
    }
    assert "published/unrelated.json" not in {
        item["path"] for item in preview["affected_artifacts"]
    }

    result = retire_source(
        tmp_path,
        source_id,
        bundle_root=intake,
        artifacts_root=artifacts,
        retention_state="retired",
        operator="m10-reviewer",
        reason="Permission withdrawn by source owner.",
    )
    assert result["source_state"]["retention_state"] == "retired"
    validate_stale_artifact_receipt(result["stale_receipt"])
    assert load_current_source_state(artifacts, source_id)["retention_state"] == "retired"
    assert (intake / "both" / "source-record.json").read_bytes() == source_before
    assert (intake / "both" / "initial-task-enrollment.json").read_bytes() == enrollment_before
    assert (intake / "both" / "videos" / "video-both.mov").read_bytes() == video_before

    status = inspect_repository(tmp_path, bundle_root=intake, artifacts_root=artifacts)
    assert not status.valid
    assert len(status.source_impacts) == 3
    assert {item["source_asset_id"] for item in status.source_impacts} == {
        "source-both",
        "source-cardevent-only",
        "source-table-evidence-only",
    }
    stale = set(status.stale_derived_artifacts)
    assert (
        "artifacts/published/cardevent_event_detection/cardevent/dataset/cardevent-dataset.json"
        in stale
    )
    assert (
        "artifacts/published/table_evidence_analysis/table-evidence/dataset/table-dataset.json"
        in stale
    )
    assert sum(failure.kind == "cross_task_impact" for failure in status.failures) >= 2
    assert all(item.source_asset_id != source_id for item in status.pending_review)

    repeated = analyze_source_impact(
        tmp_path,
        source_id,
        bundle_root=intake,
        artifacts_root=artifacts,
    )
    assert repeated == analyze_source_impact(
        tmp_path,
        source_id,
        bundle_root=intake,
        artifacts_root=artifacts,
    )


def test_source_retirement_is_idempotent_and_cli_reports_impact(tmp_path: Path, capsys) -> None:
    intake = tmp_path / "intake"
    shutil.copytree(FIXTURE_ROOT, intake)
    artifacts = tmp_path / "artifacts"
    first = retire_source(
        tmp_path,
        "source-cardevent-only",
        bundle_root=intake,
        artifacts_root=artifacts,
        retention_state="deletion_requested",
        operator="m10-reviewer",
        reason="Permission withdrawn.",
    )
    second = retire_source(
        tmp_path,
        "source-cardevent-only",
        bundle_root=intake,
        artifacts_root=artifacts,
        retention_state="deletion_requested",
        operator="m10-reviewer",
        reason="Permission withdrawn.",
    )
    assert second == first
    assert len(list((artifacts / "stale-artifact-receipts").glob("*.json"))) == 1

    assert (
        main(
            [
                "data",
                "impact",
                "--repository-root",
                str(tmp_path),
                "--intake-root",
                str(intake),
                "--artifacts-root",
                str(artifacts),
                "--source-asset-id",
                "source-cardevent-only",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["source_asset_id"] == "source-cardevent-only"
    assert output["retention_state"] == "deletion_requested"
