from pathlib import Path

import pytest

from dokodetector_backend.pipeline_coordinator import (
    PipelineCoordinator,
    PipelineCoordinatorError,
    StageDefinition,
    StageExecution,
    frozen_pilot_stage_plan,
)


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
    assert plan[-1].input_revision_ids == ("@stage:table_observations",)


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
