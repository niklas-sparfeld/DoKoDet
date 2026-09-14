from __future__ import annotations

from pathlib import Path

from doko_operations.cardevent_campaign import (
    CommandResult,
    FixtureCommandRunner,
    render_card_event_campaign_report,
    run_card_event_campaign,
)
from doko_operations.model_improvement import load_model_recipe

REPOSITORY_ROOT = Path(__file__).parents[2]
RECIPE_PATH = REPOSITORY_ROOT / "experiments" / "cardevent" / "0063-m5-validation.yaml"


def test_epic_0063_m5_recipe_is_bounded_and_targets_frozen_validation_data() -> None:
    recipe = load_model_recipe(RECIPE_PATH)

    assert recipe.recipe_id == "cardeventnet-0063-m5-validation"
    assert recipe.data.dataset.id == "cardeventnet-dataset-babc3dca31acd0c3631c"
    assert recipe.data.split.id == "cardeventnet-split-b5c0a89b89b515b87fed"
    assert recipe.baseline_bundle.id == "cardeventnet-supplied-champion"
    assert recipe.baseline_bundle.digest == (
        "030465d3d7edd2e8fb0feb4d03253c3242d9968123b8c5d451a275d851a2f2a9"
    )
    assert len(recipe.candidates) == recipe.budget.max_candidates == 1
    assert recipe.seeds == (42,)
    assert recipe.budget.max_compute_minutes == 60
    assert recipe.budget.max_failures == 1
    assert recipe.execution.device == "cpu"
    assert recipe.execution.precision == "fp32"
    assert recipe.export_compatibility == "runtime/v1"
    assert recipe.candidates[0].configuration["decoder_settings"] == {
        "peak_confirmation_s": 0.125,
        "min_event_gap_s": 0.625,
    }
    assert recipe.sealed_test_authorized is True


def test_campaign_report_includes_selection_metrics() -> None:
    recipe = load_model_recipe(RECIPE_PATH)
    fixture = {
        "schema_version": "model-campaign/v1",
        "campaign_id": "campaign-report",
        "component": "card-event-net",
        "capability": "event-detection",
        "task": "cardevent_event_detection",
        "recipe_id": recipe.recipe_id,
        "recipe_digest": recipe.digest,
        "baseline_bundle": recipe.baseline_bundle.to_mapping(),
        "data": recipe.data.to_mapping(),
        "state": "keep_champion_recommended",
        "created_at_utc": "2026-09-13T00:00:00Z",
        "updated_at_utc": "2026-09-13T00:00:00Z",
        "candidate_runs": [],
        "comparison_id": "comparison-report",
        "lock_id": None,
        "test_evaluation_id": None,
        "promotion_receipt_id": None,
        "recommendation": "keep_champion",
        "failure_reason": None,
    }
    comparison = {
        "schema_version": "model-comparison/v1",
        "comparison_id": "comparison-report",
        "campaign_id": "campaign-report",
        "component": "card-event-net",
        "capability": "event-detection",
        "task": "cardevent_event_detection",
        "recipe_digest": recipe.digest,
        "gate_profile_id": "card-event-net-v1",
        "data": recipe.data.to_mapping(),
        "champion": {
            "evaluation_id": "evaluation-champion",
            "role": "champion",
            "candidate_id": None,
            "run_id": "run-champion",
            "bundle": recipe.baseline_bundle.to_mapping(),
            "state": "success",
            "data": recipe.data.to_mapping(),
            "metrics": {
                "event_recall": 0.91,
                "event_precision": 0.86,
                "event_f1": 0.88,
                "worst_video_recall": 0.71,
                "worst_video_precision": 0.72,
                "worst_video_f1": 0.70,
                "false_events_per_hour": 0.8,
                "timestamp_confirmation_delay_ms": 210.0,
                "causal_confirmation_delay_ms": 330.0,
                "reviewed_hard_negative_false_positive_rate": 0.01,
            },
            "gates": [],
            "failure_reason": None,
        },
        "candidates": [],
        "recommendation": "keep_champion",
        "recommended_candidate_id": None,
        "selection_order": [],
        "generated_at_utc": "2026-09-13T00:00:00Z",
    }
    from doko_operations.model_improvement import ModelCampaign, ModelComparison

    report = render_card_event_campaign_report(
        ModelCampaign.from_mapping(fixture),
        ModelComparison.from_mapping(comparison),
        recipe=recipe,
    )

    assert "Worst-recording recall" in report
    assert "False events/hour" in report
    assert "Timing delay (ms)" in report
    assert "Hard-negative FP rate" in report


class ChampionFailureFixtureRunner(FixtureCommandRunner):
    def __init__(self) -> None:
        super().__init__()
        self._evaluation_count = 0

    def run(self, command, *, cwd, log_path):
        if "evaluate" in command:
            self._evaluation_count += 1
            if self._evaluation_count == 1:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(
                    "command: champion\nreturncode: 1\n",
                    encoding="utf-8",
                )
                return CommandResult(1, "", "champion checkpoint is not loadable")
        return super().run(command, cwd=cwd, log_path=log_path)


class CollisionFixtureRunner(FixtureCommandRunner):
    def run(self, command, *, cwd, log_path):
        if "train" in command:
            output_dir = Path(command[command.index("--output-dir") + 1])
            run_name = command[command.index("--run-name") + 1]
            suffixed_dir = output_dir / f"{run_name}-1"
            suffixed_dir.mkdir(parents=True, exist_ok=True)
            (suffixed_dir / "best.pt").write_text("fixture-checkpoint\n", encoding="utf-8")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                f"command: fixture\nreturncode: 0\nBest checkpoint: {suffixed_dir / 'best.pt'}\n",
                encoding="utf-8",
            )
            return CommandResult(0, f"Best checkpoint: {suffixed_dir / 'best.pt'}\n", "")
        return super().run(command, cwd=cwd, log_path=log_path)


def test_campaign_uses_checkpoint_reported_after_run_name_collision(tmp_path: Path) -> None:
    fixture_root = REPOSITORY_ROOT / "fixtures" / "model-improvement" / "v1"
    campaign = run_card_event_campaign(
        fixture_root / "recipe-cardevent.json",
        repository_root=fixture_root / "valid",
        registry_path="registry.json",
        campaign_root=tmp_path / "campaigns",
        project_root=tmp_path / "card_event_net",
        runner=CollisionFixtureRunner(),
        now_utc="2026-09-13T00:00:00Z",
    )

    assert campaign.state == "candidate_locked"
    campaign_dir = tmp_path / "campaigns" / campaign.campaign_id
    assert (campaign_dir / "runs" / "candidate-1-1" / "best.pt").is_file()
    assert (campaign_dir / "runs" / "candidate-1-1" / "model-improvement.json").is_file()


def test_campaign_retains_candidate_when_champion_is_not_loadable(tmp_path: Path) -> None:
    runner = ChampionFailureFixtureRunner()
    fixture_root = REPOSITORY_ROOT / "fixtures" / "model-improvement" / "v1"
    campaign = run_card_event_campaign(
        fixture_root / "recipe-cardevent.json",
        repository_root=fixture_root / "valid",
        registry_path="registry.json",
        campaign_root=tmp_path / "campaigns",
        project_root=tmp_path / "card_event_net",
        runner=runner,
        now_utc="2026-09-13T00:00:00Z",
    )

    assert campaign.state == "human_review_required"
    assert campaign.recommendation == "human_review_required"
    campaign_dir = tmp_path / "campaigns" / campaign.campaign_id
    champion = (campaign_dir / "champion-evaluation.json").read_text(encoding="utf-8")
    assert '"state": "skipped"' in champion
    assert (campaign_dir / "candidates" / "candidate-1" / "run-reference.json").is_file()
    assert "champion checkpoint is not loadable" in (campaign_dir / "report.md").read_text(
        encoding="utf-8"
    )
