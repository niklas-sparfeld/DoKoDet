from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from doko_operations.cli import main
from doko_operations.intake import discover_bundle_paths, inspect_repository
from doko_operations.review import (
    REVIEW_RUN_SCHEMA_VERSION,
    GenericReviewAdapter,
    ReviewInput,
    ReviewItem,
    ReviewRunError,
    TaskArtifacts,
    load_review_report,
    load_review_run,
    render_review_json,
    run_review,
    validate_review_report,
    validate_review_run,
)
from doko_operations.status import render_json
from doko_operations.table_evidence import (
    TABLE_EVIDENCE_TASK,
    TableEvidenceReviewAdapter,
    TableObservationReviewAdapter,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "repository-bundle" / "v1"


def _table_review_input(bundle: Path) -> ReviewInput:
    source = json.loads((bundle / "source-record.json").read_text())
    enrollment = json.loads((bundle / "initial-task-enrollment.json").read_text())
    table = next(item for item in enrollment["enrollments"] if item["task"] == TABLE_EVIDENCE_TASK)
    return ReviewInput(
        task=TABLE_EVIDENCE_TASK,
        source_asset_id=source["source_asset_id"],
        recording_id=source["recording_id"],
        source_sha256=source["sha256"],
        bundle_path=str(bundle),
        task_enrollment_id=table["task_enrollment_id"],
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


def test_review_run_creates_strict_state_and_reports_next_action(tmp_path: Path) -> None:
    result = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="fixture-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
    )

    assert result.state == "in_progress"
    assert result.next_action is not None
    assert result.commit_ready_files == ()
    state = load_review_run(result.run_path)
    report = load_review_report(result.run_path.parent / "report.json")
    assert state["schema_version"] == REVIEW_RUN_SCHEMA_VERSION
    assert report["state"] == "in_progress"
    rendered = json.loads(render_review_json(result, repository_root=REPOSITORY_ROOT))
    validate_review_report(rendered)
    assert not (tmp_path / "artifacts" / "published").exists()
    status = inspect_repository(
        REPOSITORY_ROOT,
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
    )
    assert status.pending_review[0].resumable
    assert status.pending_review[0].run_path is not None


def test_review_run_interrupts_after_saved_decision_and_resumes(tmp_path: Path) -> None:
    calls = 0

    def interrupting_provider(item: ReviewItem) -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return {"outcome": "accepted"}

    first = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="resume-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=interrupting_provider,
        adapters={"cardevent_event_detection": GenericReviewAdapter()},
    )
    assert first.state == "interrupted"
    interrupted = load_review_run(first.run_path)
    items = interrupted["tasks"][0]["items"]
    assert sum(item["state"] == "complete" for item in items) == 1
    assert sum(item["state"] == "pending" for item in items) == len(items) - 1

    resumed = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="resume-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: {"outcome": "accepted"},
        adapters={"cardevent_event_detection": GenericReviewAdapter()},
    )
    assert resumed.state == "complete"
    assert resumed.next_action is None
    assert resumed.commit_ready_files
    assert (tmp_path / "artifacts" / "published" / "cardevent_event_detection").is_dir()


def test_completed_rerun_is_idempotent_and_does_not_call_provider(tmp_path: Path) -> None:
    first = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="idempotent-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: {"outcome": "accepted"},
        adapters={"cardevent_event_detection": GenericReviewAdapter()},
    )
    files = {
        path: path.read_bytes() for path in (first.run_path, first.report_path) if path.is_file()
    }
    published = tmp_path / "artifacts" / "published" / "cardevent_event_detection"
    published_files = {path: path.read_bytes() for path in published.rglob("*") if path.is_file()}

    def unexpected_provider(item: ReviewItem) -> dict[str, str]:
        raise AssertionError(f"completed run asked for {item.item_id}")

    second = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="idempotent-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=unexpected_provider,
        adapters={"cardevent_event_detection": GenericReviewAdapter()},
    )
    assert second.state == "complete"
    assert {path: path.read_bytes() for path in published_files} == published_files
    assert {path: path.read_bytes() for path in files} == files


class FailingValidationAdapter:
    def discover(self, task: str, inputs) -> list[ReviewItem]:
        return [ReviewItem("item-failing", inputs[0].source_asset_id, "test", "Accept fixture")]

    def apply_decision(self, task, item, decision, staging_dir: Path) -> None:
        staging_dir.mkdir(parents=True, exist_ok=True)
        (staging_dir / "partial-dataset.json").write_text("partial", encoding="utf-8")

    def finalize(self, task, inputs, items, staging_dir: Path) -> TaskArtifacts:
        return TaskArtifacts((staging_dir / "partial-dataset.json",))

    def validate(self, task, staging_dir: Path) -> tuple[str, ...]:
        return ("dataset validation failed",)


def test_failed_validation_never_publishes_partial_task_outputs(tmp_path: Path) -> None:
    result = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="failure-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: {"outcome": "accepted"},
        adapters={"cardevent_event_detection": FailingValidationAdapter()},
    )

    assert result.state == "failed"
    state = load_review_run(result.run_path)
    assert state["tasks"][0]["state"] == "failed"
    assert not (tmp_path / "artifacts" / "published").exists()
    assert (tmp_path / "artifacts" / "review-runs" / result.run_id / "staging").is_dir()


def test_all_tasks_keep_completed_and_failed_state_separate(tmp_path: Path) -> None:
    result = run_review(
        REPOSITORY_ROOT,
        task="all",
        reviewer="all-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: {"outcome": "accepted"},
        adapters={
            "cardevent_event_detection": GenericReviewAdapter(),
            "table_evidence_analysis": FailingValidationAdapter(),
        },
    )

    assert result.state == "failed"
    state = load_review_run(result.run_path)
    task_states = {item["task"]: item["state"] for item in state["tasks"]}
    assert task_states == {
        "cardevent_event_detection": "complete",
        "table_evidence_analysis": "failed",
    }
    assert (tmp_path / "artifacts" / "published" / "cardevent_event_detection").is_dir()
    assert not (tmp_path / "artifacts" / "published" / "table_evidence_analysis").exists()


def test_cardevent_adapter_stages_wide_review_and_direct_source_outputs(tmp_path: Path) -> None:
    result = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="cardevent-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: {"outcome": "accepted"},
    )

    assert result.state == "in_progress"
    state = load_review_run(result.run_path)
    task_state = state["tasks"][0]
    assert {item["kind"] for item in task_state["items"]} == {
        "video_wide_pass",
        "proposal_candidate",
        "hard_negative",
    }
    assert task_state["split_approval_required"]
    assert task_state["staged_outputs"]
    assert not (tmp_path / "artifacts" / "published").exists()
    review_manifest = next(
        Path(path)
        for path in task_state["staged_outputs"]
        if Path(path).name == "cardevent-review-manifest.json"
    )
    manifest = json.loads(review_manifest.read_text(encoding="utf-8"))
    assert all(
        item["canonical_video_path"].endswith(
            "/videos/" + item["source_asset_id"].replace("source-", "video-") + ".mov"
        )
        for item in manifest["source_assets"]
    )
    annotation = next(
        Path(path) for path in task_state["staged_outputs"] if Path(path).name == "source-both.json"
    )
    assert set(json.loads(annotation.read_text(encoding="utf-8"))) == {
        "schema_version",
        "video",
        "events",
    }

    completed = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="cardevent-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: (_ for _ in ()).throw(
            AssertionError(f"unexpected repeated decision {item.item_id}")
        ),
        split_approval_provider=lambda task, state: True,
    )
    assert completed.state == "complete"
    published = tmp_path / "artifacts" / "published" / "cardevent_event_detection"
    assert published.is_dir()
    assert not any(path.suffix == ".mov" for path in published.rglob("*"))


def test_cardevent_candidate_decisions_do_not_replace_video_wide_review(tmp_path: Path) -> None:
    def candidate_only(item: ReviewItem) -> dict[str, str] | None:
        if item.kind == "video_wide_pass":
            return None
        return {"outcome": "accepted"}

    result = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="wide-pass-reviewer",
        bundle_root=FIXTURE_ROOT,
        artifacts_root=tmp_path / "artifacts",
        decision_provider=candidate_only,
    )

    state = load_review_run(result.run_path)
    assert result.state == "in_progress"
    assert state["tasks"][0]["items"][-1]["kind"] == "video_wide_pass"
    assert state["tasks"][0]["items"][-1]["state"] == "pending"
    assert not (tmp_path / "artifacts" / "published").exists()


def test_deferred_cardevent_enrollment_creates_no_review_work(tmp_path: Path) -> None:
    result = run_review(
        REPOSITORY_ROOT,
        task="cardevent_event_detection",
        reviewer="deferred-reviewer",
        bundle_root=FIXTURE_ROOT / "table-evidence-only",
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: (_ for _ in ()).throw(
            AssertionError(f"deferred source created {item.item_id}")
        ),
    )

    assert result.state == "complete"
    state = load_review_run(result.run_path)
    assert state["tasks"][0]["inputs"] == []
    assert state["tasks"][0]["items"] == []
    assert not (tmp_path / "artifacts" / "published").exists()


def test_table_evidence_selection_has_proposal_independent_coverage() -> None:
    item = _table_review_input(FIXTURE_ROOT / "both")
    selected = TableEvidenceReviewAdapter(coverage_interval_s=10).discover(
        TABLE_EVIDENCE_TASK, [item]
    )

    assert {candidate.kind for candidate in selected} == {
        "mac_event_proposal",
        "negative_sample",
        "coverage_sample",
    }
    coverage = next(candidate for candidate in selected if candidate.kind == "coverage_sample")
    assert "coverage_sample" in coverage.prompt
    assert "1.000s" not in coverage.prompt


def test_table_evidence_selection_classifies_device_proposals_and_operator_events(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(FIXTURE_ROOT / "table-evidence-only", bundle)
    proposal_path = next((bundle / "predictions").glob("*.json"))
    proposal = json.loads(proposal_path.read_text())
    proposal["execution_environment"]["platform"] = "ios"
    proposal_path.write_text(json.dumps(proposal))
    reviewed_path = tmp_path / "reviewed-events.json"
    reviewed_path.write_text(
        json.dumps(
            {
                "source_asset_id": "source-table-evidence-only",
                "review_state": "reviewed",
                "events": [{"time_s": 3.5, "type": "card_played"}],
            }
        )
    )
    adapter = TableEvidenceReviewAdapter(
        reviewed_event_roots=[reviewed_path],
        operator_intervals={
            "source-table-evidence-only": [
                {"start_s": 5.0, "end_s": 7.0, "label": "difficult transition"}
            ]
        },
    )

    selected = adapter.discover(TABLE_EVIDENCE_TASK, [_table_review_input(bundle)])

    assert "device_event_proposal" in {candidate.kind for candidate in selected}
    assert "reviewed_event" in {candidate.kind for candidate in selected}
    assert "operator_selected" in {candidate.kind for candidate in selected}
    assert all("selected by " in candidate.prompt for candidate in selected)


def test_table_evidence_materializes_frames_and_allows_missing_optional_snippet(
    tmp_path: Path,
) -> None:
    package = tmp_path / "frame-only-package"
    shutil.copytree(REPOSITORY_ROOT / "fixtures" / "evidence" / "v2" / "example-complete", package)
    (package / "snippet.mp4").unlink()
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["video_snippet"] = None
    manifest_path.write_text(json.dumps(manifest))
    adapter = TableEvidenceReviewAdapter(evidence_roots=[package])

    selected = adapter.discover(
        TABLE_EVIDENCE_TASK, [_table_review_input(FIXTURE_ROOT / "table-evidence-only")]
    )
    package_id = manifest["package_id"]
    assert selected

    result = run_review(
        REPOSITORY_ROOT,
        task=TABLE_EVIDENCE_TASK,
        reviewer="table-evidence-fixture",
        bundle_root=FIXTURE_ROOT / "table-evidence-only",
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: {"outcome": "reviewed"},
        adapters={TABLE_EVIDENCE_TASK: adapter},
    )

    assert result.state == "complete"
    output = (
        tmp_path
        / "artifacts"
        / "published"
        / TABLE_EVIDENCE_TASK
        / "table-evidence"
        / "candidate-selection.json"
    )
    payload = json.loads(output.read_text())
    selected_package = next(
        item for item in payload["selections"] if item["evidence_package_id"] == package_id
    )
    assert len(selected_package["evidence"]["frame_references"]) == 6
    assert selected_package["evidence"]["video_snippet"] is None
    assert (
        payload["proposal_generator_runs"][0]["proposal_generator_run_id"]
        == "proposal-table-evidence-only"
    )
    coverage = json.loads(
        (
            tmp_path
            / "artifacts"
            / "published"
            / TABLE_EVIDENCE_TASK
            / "table-evidence"
            / "selection-coverage.json"
        ).read_text()
    )
    assert {item["selection_source"] for item in coverage["selection_sources"]} >= {
        "mac_event_proposal",
        "coverage_sample",
        "negative_sample",
    }


def test_table_evidence_selection_digest_and_order_are_repeatable(tmp_path: Path) -> None:
    adapter = TableEvidenceReviewAdapter(
        operator_intervals={"source-table-evidence-only": [{"start_s": 5.0, "end_s": 7.0}]}
    )
    common = {
        "repository_root": REPOSITORY_ROOT,
        "task": TABLE_EVIDENCE_TASK,
        "reviewer": "repeatable-selection",
        "bundle_root": FIXTURE_ROOT / "table-evidence-only",
        "decision_provider": lambda item: {"outcome": "reviewed"},
        "adapters": {TABLE_EVIDENCE_TASK: adapter},
    }
    first = run_review(artifacts_root=tmp_path / "first", **common)
    second = run_review(artifacts_root=tmp_path / "second", **common)
    first_path = (
        tmp_path
        / "first"
        / "published"
        / TABLE_EVIDENCE_TASK
        / "table-evidence"
        / "candidate-selection.json"
    )
    second_path = (
        tmp_path
        / "second"
        / "published"
        / TABLE_EVIDENCE_TASK
        / "table-evidence"
        / "candidate-selection.json"
    )
    first_payload = json.loads(first_path.read_text())
    second_payload = json.loads(second_path.read_text())

    assert first.state == second.state == "complete"
    assert first_payload["selection_digest"] == second_payload["selection_digest"]
    assert [item["selection_id"] for item in first_payload["selections"]] == [
        item["selection_id"] for item in second_payload["selections"]
    ]


def test_table_observation_review_stages_immutable_outputs_and_keeps_false_proposal_cards(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(REPOSITORY_ROOT / "fixtures" / "evidence" / "v2" / "example-complete", evidence)
    manifest_path = evidence / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["event"]["event_time_ms"] = 1000
    manifest_path.write_text(json.dumps(manifest))
    source_before = (FIXTURE_ROOT / "table-evidence-only" / "source-record.json").read_bytes()
    adapter = TableObservationReviewAdapter(evidence_roots=[evidence])

    def decide(item: ReviewItem) -> dict[str, object]:
        if item.kind == "mac_event_proposal":
            return {
                "event_decision": "reject_event",
                "observed_cards": [
                    {
                        "visual_card_identity": "HEARTS_QUEEN",
                        "bbox": [10, 20, 110, 140],
                        "became_newly_visible": True,
                        "active_area_class": "inside",
                        "tags": ["glare"],
                    }
                ],
            }
        return {"event_decision": "reject_event"}

    result = run_review(
        REPOSITORY_ROOT,
        task=TABLE_EVIDENCE_TASK,
        reviewer="table-observation-reviewer",
        bundle_root=FIXTURE_ROOT / "table-evidence-only",
        artifacts_root=tmp_path / "artifacts",
        decision_provider=decide,
        adapters={TABLE_EVIDENCE_TASK: adapter},
    )

    assert result.state == "in_progress"
    assert (
        result.next_action
        == "Approve the proposed split for table_evidence_analysis before publication."
    )
    staging = result.run_path.parent / "staging" / TABLE_EVIDENCE_TASK / "table-evidence"
    assert (staging / "review-report.json").is_file()
    assert not (tmp_path / "artifacts" / "published").exists()

    published_result = run_review(
        REPOSITORY_ROOT,
        task=TABLE_EVIDENCE_TASK,
        reviewer="table-observation-reviewer",
        bundle_root=FIXTURE_ROOT / "table-evidence-only",
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: (_ for _ in ()).throw(
            AssertionError(f"resumed review requested {item.item_id}")
        ),
        split_approval_provider=lambda task, state: (
            task == TABLE_EVIDENCE_TASK and not state["split_approved"]
        ),
        adapters={TABLE_EVIDENCE_TASK: adapter},
    )

    assert published_result.state == "complete"
    published = tmp_path / "artifacts" / "published" / TABLE_EVIDENCE_TASK / "table-evidence"
    report = json.loads((published / "review-report.json").read_text())
    proposal = next(
        item
        for item in report["annotation_sets"]
        if item["selection_source"] == "mac_event_proposal"
    )
    annotation = json.loads(
        (published / "annotations" / f"{proposal['annotation_set_id']}.json").read_text()
    )
    assert annotation["review_state"] == "reviewed"
    assert annotation["event_review"] == "false_event_proposal"
    assert annotation["observed_cards"][0]["visual_card_identity"] == "HEARTS_QUEEN"
    assert len(annotation["observed_cards"][0]["frame_observations"]) == 6
    assert report["lifecycle_state"] == "eligible"

    dataset = json.loads(
        (published / "dataset" / "table-evidence-dataset-version.json").read_text()
    )
    assert dataset["schema_version"] == "dataset-version/v1"
    assert len(dataset["entries"]) == 6
    assert json.loads((published / "validation" / "table-evidence-validation.json").read_text())[
        "valid"
    ]
    split = json.loads(
        (published / "split-proposal" / "table-evidence-split-proposal.json").read_text()
    )
    assert split["unassigned"] == [entry["dataset_item_id"] for entry in dataset["entries"]]
    receipt = json.loads((published / "lifecycle-receipt.json").read_text())
    assert receipt["metadata"]["lifecycle_state"] == "eligible"
    assert (
        FIXTURE_ROOT / "table-evidence-only" / "source-record.json"
    ).read_bytes() == source_before
    assert not any(path.name == "cardevent-review-manifest.json" for path in published.rglob("*"))


def test_incomplete_table_observation_review_does_not_publish_reviewed_or_eligible_state(
    tmp_path: Path,
) -> None:
    adapter = TableObservationReviewAdapter(
        evidence_roots=[REPOSITORY_ROOT / "fixtures" / "evidence" / "v2" / "example-complete"]
    )
    result = run_review(
        REPOSITORY_ROOT,
        task=TABLE_EVIDENCE_TASK,
        reviewer="incomplete-table-reviewer",
        bundle_root=FIXTURE_ROOT / "table-evidence-only",
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: None,
        adapters={TABLE_EVIDENCE_TASK: adapter},
    )

    assert result.state == "in_progress"
    assert not (tmp_path / "artifacts" / "published").exists()
    assert not list((result.run_path.parent / "staging").rglob("annotations"))
    state = load_review_run(result.run_path)
    assert all(item["state"] == "pending" for item in state["tasks"][0]["items"])


def test_deferred_table_evidence_enrollment_creates_no_review_work(tmp_path: Path) -> None:
    result = run_review(
        REPOSITORY_ROOT,
        task=TABLE_EVIDENCE_TASK,
        reviewer="deferred-table-reviewer",
        bundle_root=FIXTURE_ROOT / "cardevent-only",
        artifacts_root=tmp_path / "artifacts",
        decision_provider=lambda item: (_ for _ in ()).throw(
            AssertionError(f"deferred source created {item.item_id}")
        ),
    )

    assert result.state == "complete"
    state = load_review_run(result.run_path)
    assert state["tasks"][0]["inputs"] == []
    assert state["tasks"][0]["items"] == []
    assert not (tmp_path / "artifacts" / "published").exists()


def test_review_contract_rejects_unknown_state_fields() -> None:
    with pytest.raises(ReviewRunError, match="unknown fields"):
        validate_review_run({"schema_version": REVIEW_RUN_SCHEMA_VERSION, "unexpected": True})
    with pytest.raises(ReviewRunError, match="unknown fields"):
        validate_review_report({"schema_version": "doko-review-report/v1", "unexpected": True})
