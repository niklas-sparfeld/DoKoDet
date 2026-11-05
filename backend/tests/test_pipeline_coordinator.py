from pathlib import Path

import pytest

from dokodetector_backend.pipeline_coordinator import (
    PipelineCoordinator,
    PipelineCoordinatorCancelled,
    PipelineCoordinatorError,
    RetainedPipelineStageExecutor,
    StageDefinition,
    StageExecution,
    frozen_pilot_stage_plan,
)


def test_identity_stage_uses_proposed_card_scene_crop_input() -> None:
    payload = RetainedPipelineStageExecutor._request_payload(
        "visual_identity_proposals",
        "identity-run",
        {"configuration": {"provider": "local-dino"}},
        ("scene-proposal-r1",),
    )

    assert payload["request"]["card_scene_proposal_revision_id"] == "scene-proposal-r1"
    assert payload["request"]["crop_input_kind"] == "proposed_virtual_cards"
    assert "visible_card_revision_id" not in payload["request"]


def test_coordinator_persists_exact_lineage_and_reuses_completed_stages(tmp_path: Path) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(**kwargs: object) -> StageExecution:
        stage = str(kwargs["stage"])
        inputs = tuple(kwargs["input_revision_ids"])  # type: ignore[arg-type]
        calls.append((stage, inputs))
        output = f"{stage}-output"
        return StageExecution("complete", inputs, (output,))

    coordinator = PipelineCoordinator(tmp_path, execute)
    stages = [
        StageDefinition("events", {"threshold": 0.4}, ("video-source",)),
        StageDefinition("visible-cards", {"provider": "local-rfdetr"}, ("@stage:events",)),
    ]
    result = coordinator.run("recording-1", stages, coordinator_id="pilot-1")

    assert result["status"] == "complete"
    assert calls == [("events", ("video-source",)), ("visible-cards", ("events-output",))]
    assert result["stages"][1]["input_revision_ids"] == ["events-output"]
    assert result["stages"][0]["output_revision_ids"] == ["events-output"]
    coordinator.run("recording-1", stages, coordinator_id="pilot-1")
    assert len(calls) == 2


def test_coordinator_does_not_treat_accepted_request_as_complete(tmp_path: Path) -> None:
    def execute(**_: object) -> StageExecution:
        return StageExecution("accepted", ("input",))

    coordinator = PipelineCoordinator(tmp_path, execute)
    with pytest.raises(PipelineCoordinatorError, match="non-terminal status"):
        coordinator.run(
            "recording-1",
            [StageDefinition("events", {}, ("input",))],
            coordinator_id="pilot-accepted",
        )
    assert '"status": "failed"' in (tmp_path / "pilot-accepted.json").read_text()


def test_failed_stage_stops_dependent_stages_and_records_terminal_failure(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def execute(**kwargs: object) -> StageExecution:
        stage = str(kwargs["stage"])
        calls.append(stage)
        return StageExecution(
            "failed", tuple(kwargs["input_revision_ids"]), failure={"code": "failed"}
        )  # type: ignore[arg-type]

    result = PipelineCoordinator(tmp_path, execute).run(
        "recording-1",
        [
            StageDefinition("events", {}, ("video",)),
            StageDefinition("visible-cards", {}, ("event-revision",)),
        ],
        coordinator_id="pilot-failure",
    )

    assert result["status"] == "failed"
    assert result["failure"]["stage"] == "events"
    assert calls == ["events"]


def test_frozen_pilot_plan_connects_generated_revisions_to_downstream_stages() -> None:
    requests = {
        name: {"configuration": {"stage": name}}
        for name in (
            "event_proposals",
            "visible_card_and_pile_proposals",
            "card_scene_and_calibration",
            "visual_identity_proposals",
            "table_observations",
        )
    }
    requests["reconstruction"] = {
        "skip": True,
        "skip_reason": "staged sequence has no round setup",
    }

    plan = frozen_pilot_stage_plan(requests)

    assert [stage.name for stage in plan] == [*requests]
    assert plan[-2].input_revision_ids == (
        "@stage:event_proposals",
        "@stage:visible_card_and_pile_proposals",
        "@stage:visual_identity_proposals",
    )
    assert plan[3].input_revision_ids == ("@stage:card_scene_and_calibration",)
    assert plan[-1].input_revision_ids == ("@stage:table_observations",)


def test_coordinator_runs_zero_card_scene_with_exact_inputs_and_reuses_terminal_stages(
    tmp_path: Path,
) -> None:
    requests = {
        name: {"configuration": {"stage": name}}
        for name in (
            "event_proposals",
            "visible_card_and_pile_proposals",
            "card_scene_and_calibration",
            "visual_identity_proposals",
            "table_observations",
        )
    }
    requests["reconstruction"] = {"skip": True, "skip_reason": "no round context"}
    stages = frozen_pilot_stage_plan(requests)
    outputs = {
        "event_proposals": "events-r1",
        "visible_card_and_pile_proposals": "visible-no-cards-r1",
        "card_scene_and_calibration": "scene-no-cards-r1",
        "visual_identity_proposals": "identity-empty-r1",
        "table_observations": "observations-r1",
    }
    calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(**kwargs: object) -> StageExecution:
        stage = str(kwargs["stage"])
        inputs = tuple(kwargs["input_revision_ids"])  # type: ignore[arg-type]
        calls.append((stage, inputs))
        if stage == "reconstruction":
            return StageExecution("skipped", inputs, failure={"reason": "no round context"})
        return StageExecution("complete", inputs, (outputs[stage],))

    coordinator = PipelineCoordinator(tmp_path, execute)
    result = coordinator.run("recording-1", stages, coordinator_id="zero-card-resume")
    assert result["status"] == "complete"
    assert calls == [
        ("event_proposals", ()),
        ("visible_card_and_pile_proposals", ("events-r1",)),
        ("card_scene_and_calibration", ("visible-no-cards-r1",)),
        ("visual_identity_proposals", ("scene-no-cards-r1",)),
        ("table_observations", ("events-r1", "visible-no-cards-r1", "identity-empty-r1")),
        ("reconstruction", ("observations-r1",)),
    ]
    assert result["stages"][2]["output_revision_ids"] == ["scene-no-cards-r1"]
    assert result["stages"][3]["input_revision_ids"] == ["scene-no-cards-r1"]
    assert result["stages"][4]["input_revision_ids"] == [
        "events-r1",
        "visible-no-cards-r1",
        "identity-empty-r1",
    ]

    resumed = coordinator.run("recording-1", stages, coordinator_id="zero-card-resume")
    assert resumed == result
    assert len(calls) == len(stages)


@pytest.mark.parametrize(
    "failed_stage", ["card_scene_and_calibration", "visual_identity_proposals"]
)
def test_coordinator_blocks_dependants_after_scene_or_identity_failure(
    tmp_path: Path, failed_stage: str
) -> None:
    requests = {
        name: {"configuration": {"stage": name}}
        for name in (
            "event_proposals",
            "visible_card_and_pile_proposals",
            "card_scene_and_calibration",
            "visual_identity_proposals",
            "table_observations",
        )
    }
    requests["reconstruction"] = {"skip": True}
    stages = frozen_pilot_stage_plan(requests)
    outputs = {
        "event_proposals": "events-r1",
        "visible_card_and_pile_proposals": "visible-r1",
        "card_scene_and_calibration": "scene-r1",
        "visual_identity_proposals": "identity-r1",
        "table_observations": "observations-r1",
    }
    calls: list[str] = []

    def execute(**kwargs: object) -> StageExecution:
        stage = str(kwargs["stage"])
        inputs = tuple(kwargs["input_revision_ids"])  # type: ignore[arg-type]
        calls.append(stage)
        if stage == failed_stage:
            return StageExecution("failed", inputs, failure={"reason": "fixture failure"})
        if stage == "reconstruction":
            return StageExecution("skipped", inputs, failure={"reason": "no context"})
        return StageExecution("complete", inputs, (outputs[stage],))

    result = PipelineCoordinator(tmp_path, execute).run(
        "recording-1", stages, coordinator_id=f"failure-{failed_stage}"
    )
    assert result["status"] == "failed"
    assert result["failure"]["stage"] == failed_stage
    assert calls == [stage.name for stage in stages[: calls.index(failed_stage) + 1]]
    assert "table_observations" not in calls


def test_explicitly_skipped_reconstruction_is_retained_as_a_terminal_decision(
    tmp_path: Path,
) -> None:
    def execute(**kwargs: object) -> StageExecution:
        inputs = tuple(kwargs["input_revision_ids"])  # type: ignore[arg-type]
        if kwargs["stage"] == "reconstruction":
            return StageExecution("skipped", inputs, failure={"reason": "no round setup"})
        return StageExecution("complete", inputs, ("table-observation-revision",))

    stages = [
        StageDefinition("table_observations", {}, ("event", "visible", "identity")),
        StageDefinition("reconstruction", {"skip": True}, ("@stage:table_observations",)),
    ]
    coordinator = PipelineCoordinator(tmp_path, execute)

    result = coordinator.run("recording-1", stages, coordinator_id="pilot-skip")
    resumed = coordinator.run("recording-1", stages, coordinator_id="pilot-skip")

    assert result["status"] == "complete"
    assert result["stages"][-1]["status"] == "skipped"
    assert resumed["stages"][-1]["status"] == "skipped"


def test_restart_resumes_same_durable_processor_request(tmp_path: Path) -> None:
    stage = StageDefinition("events", {"model": "frozen"}, ("video",))
    first_run_ids: list[str] = []

    def interrupted(**kwargs: object) -> StageExecution:
        first_run_ids.append(str(kwargs["run_id"]))
        raise KeyboardInterrupt

    coordinator = PipelineCoordinator(tmp_path, interrupted)
    with pytest.raises(KeyboardInterrupt):
        coordinator.run("recording-1", [stage], coordinator_id="restart")

    resumed_run_ids: list[str] = []

    def resume(**kwargs: object) -> StageExecution:
        resumed_run_ids.append(str(kwargs["run_id"]))
        inputs = tuple(kwargs["input_revision_ids"])  # type: ignore[arg-type]
        return StageExecution("complete", inputs, ("events-r1",))

    result = PipelineCoordinator(tmp_path, resume).run(
        "recording-1", [stage], coordinator_id="restart"
    )

    assert result["status"] == "complete"
    assert resumed_run_ids == first_run_ids


def test_changed_upstream_request_cannot_reuse_stale_downstream_lineage(
    tmp_path: Path,
) -> None:
    downstream_inputs: list[tuple[str, ...]] = []

    def execute(**kwargs: object) -> StageExecution:
        stage = str(kwargs["stage"])
        inputs = tuple(kwargs["input_revision_ids"])  # type: ignore[arg-type]
        if stage == "downstream":
            downstream_inputs.append(inputs)
        output = (
            "events-v2"
            if stage == "upstream" and kwargs["request"] == {"v": 2}
            else f"{stage}-output"
        )
        return StageExecution("complete", inputs, (output,))

    coordinator = PipelineCoordinator(tmp_path, execute)
    coordinator.run(
        "recording-1",
        [
            StageDefinition("upstream", {"v": 1}, ("video",)),
            StageDefinition("downstream", {}, ("@stage:upstream",)),
        ],
        coordinator_id="stale-input",
    )
    result = coordinator.run(
        "recording-1",
        [
            StageDefinition("upstream", {"v": 2}, ("video",)),
            StageDefinition("downstream", {}, ("@stage:upstream",)),
        ],
        coordinator_id="stale-input",
    )

    assert downstream_inputs == [("upstream-output",), ("events-v2",)]
    assert result["stages"][1]["input_revision_ids"] == ["events-v2"]


def test_cancel_persists_partial_progress_and_can_resume(tmp_path: Path) -> None:
    coordinator = PipelineCoordinator(tmp_path, lambda **_: None)  # type: ignore[arg-type]

    def cancel_during_stage(**kwargs: object) -> StageExecution:
        coordinator.request_cancel("cancel-me")
        raise PipelineCoordinatorCancelled("Cancellation requested.")

    coordinator.executor = cancel_during_stage
    stages = [StageDefinition("events", {}, ("video",))]
    cancelled = coordinator.run("recording-1", stages, coordinator_id="cancel-me")

    assert cancelled["status"] == "cancelled"
    assert cancelled["stages"][0]["status"] == "cancelled"
    assert coordinator.read_status("cancel-me")["status"] == "cancelled"

    def resume(**kwargs: object) -> StageExecution:
        inputs = tuple(kwargs["input_revision_ids"])  # type: ignore[arg-type]
        return StageExecution("complete", inputs, ("events-r1",))

    coordinator.executor = resume
    resumed = coordinator.run("recording-1", stages, coordinator_id="cancel-me")
    assert resumed["status"] == "complete"


def test_new_coordinator_id_is_an_explicit_fresh_rerun(tmp_path: Path) -> None:
    run_ids: list[str] = []

    def execute(**kwargs: object) -> StageExecution:
        run_ids.append(str(kwargs["run_id"]))
        inputs = tuple(kwargs["input_revision_ids"])  # type: ignore[arg-type]
        return StageExecution("complete", inputs, ("events-r1",))

    stage = [StageDefinition("events", {}, ("video",))]
    coordinator = PipelineCoordinator(tmp_path, execute)
    coordinator.run("recording-1", stage, coordinator_id="run-one")
    coordinator.run("recording-1", stage, coordinator_id="run-two")

    assert len(run_ids) == 2
    assert run_ids[0] != run_ids[1]
