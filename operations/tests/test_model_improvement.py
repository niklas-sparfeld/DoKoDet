from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

import doko_operations.cardevent_campaign as campaign_module
from doko_operations.cardevent_campaign import (
    CardEventPromotionError,
    FixtureCommandRunner,
    promote_card_event_campaign,
    run_card_event_campaign,
)
from doko_operations.cli import main
from doko_operations.model_improvement import (
    CandidateRunReference,
    DataContext,
    ModelCampaign,
    ModelEvaluation,
    ModelImprovementError,
    ModelRecipe,
    ModelRegistry,
    PromotionReceipt,
    compare_evaluations,
    default_gate_profile,
    load_campaign,
    load_model_recipe,
    load_model_registry,
    load_promotion_receipt,
    model_status,
    render_comparison_human,
    render_comparison_json,
    render_comparison_report,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
TIMESTAMP = "2026-08-28T10:00:00.000Z"
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "model-improvement" / "v1"


def _data(*, split_digest: str = DIGEST_B) -> dict[str, object]:
    return {
        "dataset": {"id": "dataset-cardevent-fixture", "digest": DIGEST_A},
        "split": {"id": "split-cardevent-fixture", "digest": split_digest},
        "source_annotation": {"id": "annotation-cardevent-fixture", "digest": DIGEST_C},
        "review": {"id": "review-cardevent-fixture", "digest": DIGEST_D},
    }


def _metrics(*, f1: float = 0.91, coreml: bool = True) -> dict[str, object]:
    return {
        "event_recall": 0.93,
        "event_precision": 0.9,
        "event_f1": f1,
        "false_events_per_hour": 0.4,
        "worst_video_f1": 0.8,
        "worst_video_support": 3,
        "important_scenario_group_f1": 0.8,
        "important_scenario_group_support": 3,
        "timestamp_confirmation_delay_ms": 200,
        "causal_confirmation_delay_ms": 400,
        "reviewed_hard_negative_false_positive_rate": 0.01,
        "reviewed_hard_negative_support": 5,
        "model_size_mb": 20,
        "inference_latency_ms": 40,
        "coreml_export": coreml,
        "device_parity": 0.98,
        "regression_fixtures": True,
        "decoder_compatible": True,
    }


def _evaluation(
    *,
    role: str,
    evaluation_id: str,
    bundle_id: str,
    candidate_id: str | None = None,
    f1: float = 0.91,
    coreml: bool = True,
    data: dict[str, object] | None = None,
) -> ModelEvaluation:
    payload = {
        "evaluation_id": evaluation_id,
        "role": role,
        "candidate_id": candidate_id,
        "run_id": f"run-{evaluation_id}",
        "bundle": {"id": bundle_id, "digest": DIGEST_A},
        "state": "success",
        "data": data or _data(),
        "metrics": _metrics(f1=f1, coreml=coreml),
        "gates": [],
        "failure_reason": None,
    }
    return ModelEvaluation.from_mapping(payload)


def _champion_mapping(component: str, capability: str, bundle_id: str) -> dict[str, object]:
    return {
        "component": component,
        "capability": capability,
        "champion_bundle_id": bundle_id,
        "champion_bundle_digest": DIGEST_A,
        "bundle_path": f"models/{bundle_id}.json",
        "runtime_contract_version": "runtime/v1",
        "input_contract_version": "input/v1",
        "dataset_version_id": "dataset-cardevent-fixture",
        "dataset_version_digest": DIGEST_A,
        "split_version_id": "split-cardevent-fixture",
        "split_version_digest": DIGEST_B,
        "annotation_version_id": "annotation-cardevent-fixture",
        "annotation_version_digest": DIGEST_C,
        "review_version_id": "review-cardevent-fixture",
        "review_version_digest": DIGEST_D,
        "validation_report_id": "validation-champion",
        "sealed_test_report_id": "test-champion",
        "export": {
            "environment": {"tool": "fixture", "version": "1"},
            "compatibility": "runtime/v1",
        },
        "promotion_receipt_id": "receipt-champion",
        "decision_note": "Fixture champion.",
    }


def _campaign_mapping(
    comparison: dict[str, object], *, state: str = "compared"
) -> dict[str, object]:
    return {
        "schema_version": "model-campaign/v1",
        "campaign_id": "campaign-fixture",
        "component": "card-event-net",
        "capability": "event-detection",
        "task": "cardevent_event_detection",
        "recipe_id": "recipe-fixture",
        "recipe_digest": DIGEST_C,
        "baseline_bundle": {"id": "cardevent-champion", "digest": DIGEST_A},
        "data": _data(),
        "state": state,
        "created_at_utc": TIMESTAMP,
        "updated_at_utc": TIMESTAMP,
        "candidate_runs": [],
        "comparison_id": comparison["comparison_id"] if state == "compared" else None,
        "lock_id": None,
        "test_evaluation_id": None,
        "promotion_receipt_id": None,
        "recommendation": comparison["recommendation"] if state == "compared" else None,
        "failure_reason": None,
    }


def test_registry_keeps_component_champions_independent() -> None:
    payload = {
        "schema_version": "model-registry/v1",
        "registry_version": 2,
        "champions": [
            _champion_mapping("table-evidence-analyzer", "visual-card-identity", "table-champion"),
            _champion_mapping("card-event-net", "event-detection", "cardevent-champion"),
        ],
    }

    registry = ModelRegistry.from_mapping(payload)

    assert (
        registry.champion_for("card-event-net", "event-detection").champion_bundle.id
        == "cardevent-champion"
    )
    assert (
        registry.champion_for("table-evidence-analyzer", "visual-card-identity").champion_bundle.id
        == "table-champion"
    )
    assert registry.to_mapping()["champions"][0]["component"] == "card-event-net"


def test_recipe_declares_axes_and_has_a_stable_digest() -> None:
    payload = {
        "schema_version": "model-improvement-recipe/v1",
        "recipe_id": "recipe-fixture",
        "recipe_version": 1,
        "component": "card-event-net",
        "capability": "event-detection",
        "task": "cardevent_event_detection",
        "baseline_bundle": {"id": "cardevent-champion", "digest": DIGEST_A},
        "data": _data(),
        "experiment_axes": ["threshold"],
        "candidates": [
            {
                "candidate_id": "candidate-1",
                "experiment_family": "threshold",
                "configuration": {"threshold": 0.5},
            }
        ],
        "seeds": [7],
        "repeat_policy": "single",
        "budget": {"max_candidates": 1, "max_compute_minutes": 5, "max_failures": 0},
        "execution": {"device": "cpu", "precision": "float32"},
        "selection_metrics": [{"metric": "event_f1", "direction": "maximize"}],
        "gate_profile_id": "card-event-net-v1",
        "export_compatibility": "runtime/v1",
        "sealed_test_authorized": True,
    }

    recipe = ModelRecipe.from_mapping(payload)

    assert recipe.to_mapping() == payload
    assert recipe.digest == ModelRecipe.from_mapping(payload).digest

    invalid = copy.deepcopy(payload)
    invalid["experiment_axes"] = []
    with pytest.raises(ModelImprovementError, match="experiment axes"):
        ModelRecipe.from_mapping(invalid)


def test_yaml_recipe_is_loaded_for_operator_campaigns(tmp_path: Path) -> None:
    payload = json.loads((FIXTURE_ROOT / "recipe-cardevent.json").read_text())
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(payload, sort_keys=False))

    assert load_model_recipe(recipe_path).recipe_id == "recipe-fixture"


def test_comparison_is_deterministic_and_uses_validation_gates() -> None:
    profile = default_gate_profile("card-event-net")
    champion = _evaluation(
        role="champion", evaluation_id="champion-eval", bundle_id="cardevent-champion", f1=0.9
    )
    candidate = _evaluation(
        role="candidate",
        evaluation_id="candidate-eval",
        bundle_id="candidate-bundle",
        candidate_id="candidate-1",
        f1=0.93,
    )

    first = compare_evaluations(
        campaign_id="campaign-fixture",
        component="card-event-net",
        capability="event-detection",
        task="cardevent_event_detection",
        recipe_digest=DIGEST_C,
        data=DataContext.from_mapping(_data()),
        champion=champion,
        candidates=[candidate],
        profile=profile,
        generated_at_utc=TIMESTAMP,
    )
    second = compare_evaluations(
        campaign_id="campaign-fixture",
        component="card-event-net",
        capability="event-detection",
        task="cardevent_event_detection",
        recipe_digest=DIGEST_C,
        data=DataContext.from_mapping(_data()),
        champion=champion,
        candidates=[candidate],
        profile=profile,
        generated_at_utc=TIMESTAMP,
    )

    assert first.to_mapping() == second.to_mapping()
    assert first.recommendation == "promote_candidate"
    assert first.recommended_candidate_id == "candidate-1"
    assert "recommendation: promote_candidate" in render_comparison_human(first)
    assert "## Gate results" in render_comparison_report(first)
    assert json.loads(render_comparison_json(first))["recommendation"] == "promote_candidate"


def test_hard_gate_failure_cannot_promote_candidate() -> None:
    profile = default_gate_profile("card-event-net")
    comparison = compare_evaluations(
        campaign_id="campaign-fixture",
        component="card-event-net",
        capability="event-detection",
        task="cardevent_event_detection",
        recipe_digest=DIGEST_C,
        data=DataContext.from_mapping(_data()),
        champion=_evaluation(
            role="champion", evaluation_id="champion-eval", bundle_id="cardevent-champion"
        ),
        candidates=[
            _evaluation(
                role="candidate",
                evaluation_id="candidate-eval",
                bundle_id="candidate-bundle",
                candidate_id="candidate-1",
                f1=0.99,
                coreml=False,
            )
        ],
        profile=profile,
        generated_at_utc=TIMESTAMP,
    )

    assert comparison.recommendation == "no_valid_candidate"
    assert comparison.recommended_candidate_id is None
    assert any(
        gate.gate_id == "coreml-export" and gate.status == "failed"
        for gate in comparison.candidates[0].gates
    )


def test_different_split_digests_are_rejected() -> None:
    profile = default_gate_profile("card-event-net")
    incompatible = json.loads((FIXTURE_ROOT / "incompatible-data.json").read_text())
    with pytest.raises(ModelImprovementError, match="incompatible dataset or split digest"):
        compare_evaluations(
            campaign_id="campaign-fixture",
            component="card-event-net",
            capability="event-detection",
            task="cardevent_event_detection",
            recipe_digest=DIGEST_C,
            data=DataContext.from_mapping(_data()),
            champion=_evaluation(
                role="champion", evaluation_id="champion-eval", bundle_id="cardevent-champion"
            ),
            candidates=[
                _evaluation(
                    role="candidate",
                    evaluation_id="candidate-eval",
                    bundle_id="candidate-bundle",
                    candidate_id="candidate-1",
                    data=incompatible["candidate_data"],
                )
            ],
            profile=profile,
            generated_at_utc=TIMESTAMP,
        )


def test_partially_promoted_receipt_is_rejected() -> None:
    payload = {
        "schema_version": "model-promotion-receipt/v1",
        "receipt_id": "receipt-partial",
        "campaign_id": "campaign-fixture",
        "component": "card-event-net",
        "capability": "event-detection",
        "candidate_id": "candidate-1",
        "promoted_bundle": {"id": "candidate-bundle", "digest": DIGEST_A},
        "previous_champion": {"id": "cardevent-champion", "digest": DIGEST_B},
        "recipe_digest": DIGEST_C,
        "data": _data(),
        "sealed_test_evaluation_id": "test-candidate",
        "export_artifact": {"id": "export-candidate", "digest": DIGEST_D},
        "runtime_contract_version": "runtime/v1",
        "input_contract_version": "input/v1",
        "promotion_state": "promoted",
        "registry_update": "unchanged",
        "registry_before_digest": DIGEST_A,
        "registry_after_digest": None,
        "occurred_at_utc": TIMESTAMP,
        "failure_reason": None,
    }

    with pytest.raises(ModelImprovementError, match="updated registry"):
        PromotionReceipt.from_mapping(payload)


def test_checked_in_failure_fixtures_are_strictly_handled() -> None:
    assert load_model_recipe(FIXTURE_ROOT / "recipe-cardevent.json").recipe_id == "recipe-fixture"
    corrupted = json.loads((FIXTURE_ROOT / "corrupted-registry.json").read_text())
    with pytest.raises(ModelImprovementError, match="unknown fields"):
        ModelRegistry.from_mapping(corrupted)

    interrupted = json.loads((FIXTURE_ROOT / "interrupted-candidate-run.json").read_text())
    assert CandidateRunReference.from_mapping(interrupted).state == "interrupted"

    partial = json.loads((FIXTURE_ROOT / "partially-promoted-receipt.json").read_text())
    with pytest.raises(ModelImprovementError, match="updated registry"):
        PromotionReceipt.from_mapping(partial)

    stale = json.loads((FIXTURE_ROOT / "stale-campaign.json").read_text())
    assert ModelCampaign.from_mapping(stale).state == "running"
    incompatible = json.loads((FIXTURE_ROOT / "incompatible-data.json").read_text())
    assert (
        incompatible["data"]["split"]["digest"] != incompatible["candidate_data"]["split"]["digest"]
    )


def test_status_and_compare_commands_are_read_only(tmp_path: Path, capsys) -> None:
    registry_path = tmp_path / "registry.json"
    campaign_root = tmp_path / "campaigns"
    campaign_dir = campaign_root / "campaign-fixture"
    campaign_dir.mkdir(parents=True)

    profile = default_gate_profile("card-event-net")
    comparison = compare_evaluations(
        campaign_id="campaign-fixture",
        component="card-event-net",
        capability="event-detection",
        task="cardevent_event_detection",
        recipe_digest=DIGEST_C,
        data=DataContext.from_mapping(_data()),
        champion=_evaluation(
            role="champion", evaluation_id="champion-eval", bundle_id="cardevent-champion"
        ),
        candidates=[
            _evaluation(
                role="candidate",
                evaluation_id="candidate-eval",
                bundle_id="candidate-bundle",
                candidate_id="candidate-1",
                f1=0.93,
            )
        ],
        profile=profile,
        generated_at_utc=TIMESTAMP,
    )
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "model-registry/v1",
                "registry_version": 1,
                "champions": [
                    _champion_mapping("card-event-net", "event-detection", "cardevent-champion")
                ],
            }
        )
    )
    (campaign_dir / "campaign.json").write_text(
        json.dumps(_campaign_mapping(comparison.to_mapping()))
    )
    (campaign_dir / "comparison.json").write_text(json.dumps(comparison.to_mapping()))
    before = {
        path: path.read_bytes()
        for path in (
            registry_path,
            campaign_dir / "campaign.json",
            campaign_dir / "comparison.json",
        )
    }

    assert (
        main(
            [
                "model",
                "status",
                "--repository-root",
                str(tmp_path),
                "--model-registry",
                str(registry_path),
                "--campaign-root",
                str(campaign_root),
                "--format",
                "json",
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    assert status["valid"] is True
    assert status["campaigns"][0]["state"] == "compared"

    assert (
        main(
            [
                "model",
                "compare",
                "campaign-fixture",
                "--repository-root",
                str(tmp_path),
                "--campaign-root",
                str(campaign_root),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["campaign_id"] == "campaign-fixture"
    assert {path: path.read_bytes() for path in before} == before


def test_checked_in_valid_fixture_commands(capsys) -> None:
    root = FIXTURE_ROOT / "valid"
    assert (
        main(
            [
                "model",
                "status",
                "--repository-root",
                str(root),
                "--model-registry",
                "registry.json",
                "--campaign-root",
                "campaigns",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert (
        main(
            [
                "model",
                "compare",
                "campaign-fixture",
                "--repository-root",
                str(root),
                "--campaign-root",
                "campaigns",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["recommendation"] == "keep_champion"


def test_stale_campaign_is_reported(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    campaign_root = tmp_path / "campaigns"
    campaign_dir = campaign_root / "campaign-stale"
    campaign_dir.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "model-registry/v1",
                "registry_version": 1,
                "champions": [
                    _champion_mapping("card-event-net", "event-detection", "new-champion")
                ],
            }
        )
    )
    campaign = json.loads((FIXTURE_ROOT / "stale-campaign.json").read_text())
    campaign_dir.joinpath("campaign.json").write_text(json.dumps(campaign))

    status = model_status(tmp_path, registry_path=registry_path, campaign_root=campaign_root)

    assert status["valid"] is False
    assert any(issue["kind"] == "stale_campaign" for issue in status["issues"])


def test_cardevent_fixture_campaign_is_bounded_and_resumable(tmp_path: Path) -> None:
    runner = FixtureCommandRunner()
    campaign = run_card_event_campaign(
        FIXTURE_ROOT / "recipe-cardevent.json",
        repository_root=FIXTURE_ROOT / "valid",
        registry_path="registry.json",
        campaign_root=tmp_path / "campaigns",
        project_root=tmp_path / "card_event_net",
        runner=runner,
        now_utc=TIMESTAMP,
    )

    assert campaign.state == "candidate_locked"
    assert campaign.recommendation == "promote_candidate"
    campaign_dir = tmp_path / "campaigns" / campaign.campaign_id
    assert (campaign_dir / "resolved-recipe.yaml").is_file()
    assert (campaign_dir / "champion-evaluation.json").is_file()
    assert (campaign_dir / "comparison.json").is_file()
    assert (campaign_dir / "report.md").is_file()
    assert (campaign_dir / "lock.json").is_file()
    run_metadata = json.loads(
        (campaign_dir / "runs" / "candidate-1" / "model-improvement.json").read_text()
    )
    assert run_metadata["recipe_digest"] == campaign.recipe_digest
    commands = json.loads((campaign_dir / "logs" / "commands.json").read_text())
    assert [item["returncode"] for item in commands["commands"]] == [0, 0, 0, 0]
    assert [command[command.index("cardevent") + 1] for command in runner.commands] == [
        "evaluate",
        "train",
        "evaluate",
        "diagnose",
    ]
    assert all("test" not in command for command in runner.commands)

    first_command_count = len(runner.commands)
    resumed = run_card_event_campaign(
        FIXTURE_ROOT / "recipe-cardevent.json",
        repository_root=FIXTURE_ROOT / "valid",
        registry_path="registry.json",
        campaign_root=tmp_path / "campaigns",
        project_root=tmp_path / "card_event_net",
        runner=runner,
        now_utc=TIMESTAMP,
    )

    assert resumed.to_mapping() == campaign.to_mapping()
    assert len(runner.commands) == first_command_count


def test_cardevent_improve_cli_runs_fixture_campaign(tmp_path: Path, capsys) -> None:
    assert (
        main(
            [
                "model",
                "improve",
                "card-event-net",
                "--recipe",
                str(FIXTURE_ROOT / "recipe-cardevent.json"),
                "--repository-root",
                str(FIXTURE_ROOT / "valid"),
                "--model-registry",
                "registry.json",
                "--campaign-root",
                str(tmp_path / "campaigns"),
                "--project-root",
                str(tmp_path / "card_event_net"),
                "--runner",
                "fixture",
                "--max-samples",
                "2",
                "--format",
                "json",
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    assert result["campaign"]["state"] == "candidate_locked"
    assert Path(result["campaign_path"], "logs", "commands.json").is_file()


def _start_fixture_campaign(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, ModelCampaign]:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    campaign_root = tmp_path / "campaigns"
    registry_path = repository_root / "registry.json"
    registry_path.write_bytes((FIXTURE_ROOT / "valid" / "registry.json").read_bytes())
    campaign = run_card_event_campaign(
        FIXTURE_ROOT / "recipe-cardevent.json",
        repository_root=repository_root,
        registry_path=registry_path,
        campaign_root=campaign_root,
        project_root=tmp_path / "card_event_net",
        runner=FixtureCommandRunner(),
        now_utc=TIMESTAMP,
    )
    return (
        repository_root,
        campaign_root,
        registry_path,
        repository_root / "CardEventNet.mlpackage",
        campaign,
    )


def test_cardevent_promotion_updates_registry_and_is_idempotent(tmp_path: Path) -> None:
    repository_root, campaign_root, registry_path, app_bundle, campaign = _start_fixture_campaign(
        tmp_path
    )
    original_registry = registry_path.read_bytes()
    runner = FixtureCommandRunner()

    promoted = promote_card_event_campaign(
        campaign.campaign_id,
        repository_root=repository_root,
        registry_path=registry_path,
        campaign_root=campaign_root,
        project_root=tmp_path / "card_event_net",
        app_bundle_path=app_bundle,
        runner=runner,
        confirm=True,
        now_utc=TIMESTAMP,
    )

    assert promoted.state == "promoted"
    assert app_bundle.is_file()
    receipt = load_promotion_receipt(
        campaign_root / campaign.campaign_id / "promotion-receipt.json"
    )
    assert receipt.promotion_state == "promoted"
    assert receipt.previous_champion.id == "cardevent-champion"
    registry = load_model_registry(registry_path)
    champion = registry.champion_for("card-event-net", "event-detection")
    assert champion is not None
    assert champion.bundle_path == "CardEventNet.mlpackage"
    assert champion.champion_bundle.digest == receipt.promoted_bundle.digest
    assert [command[command.index("cardevent") + 1] for command in runner.commands] == [
        "evaluate",
        "export-coreml",
    ]

    command_count = len(runner.commands)
    repeated = promote_card_event_campaign(
        campaign.campaign_id,
        repository_root=repository_root,
        registry_path=registry_path,
        campaign_root=campaign_root,
        app_bundle_path=app_bundle,
        runner=runner,
        confirm=True,
        now_utc=TIMESTAMP,
    )
    assert repeated.to_mapping() == promoted.to_mapping()
    assert len(runner.commands) == command_count
    assert registry_path.read_bytes() != original_registry


def test_cardevent_promotion_requires_confirmation_without_mutation(tmp_path: Path) -> None:
    repository_root, campaign_root, registry_path, app_bundle, campaign = _start_fixture_campaign(
        tmp_path
    )
    original_registry = registry_path.read_bytes()

    with pytest.raises(CardEventPromotionError, match="explicit confirmation"):
        promote_card_event_campaign(
            campaign.campaign_id,
            repository_root=repository_root,
            registry_path=registry_path,
            campaign_root=campaign_root,
            app_bundle_path=app_bundle,
            confirm=False,
        )

    assert registry_path.read_bytes() == original_registry
    assert not app_bundle.exists()
    assert not (campaign_root / campaign.campaign_id / "test-evaluation.json").exists()


def test_cardevent_promotion_stops_on_poor_sealed_test(tmp_path: Path) -> None:
    repository_root, campaign_root, registry_path, app_bundle, campaign = _start_fixture_campaign(
        tmp_path
    )
    original_registry = registry_path.read_bytes()
    runner = FixtureCommandRunner(test_quality=0.5)

    result = promote_card_event_campaign(
        campaign.campaign_id,
        repository_root=repository_root,
        registry_path=registry_path,
        campaign_root=campaign_root,
        project_root=tmp_path / "card_event_net",
        app_bundle_path=app_bundle,
        runner=runner,
        confirm=True,
        now_utc=TIMESTAMP,
    )

    assert result.state == "human_review_required"
    assert result.test_evaluation_id is not None
    assert not app_bundle.exists()
    assert registry_path.read_bytes() == original_registry
    assert len(runner.commands) == 1
    assert not (campaign_root / campaign.campaign_id / "promotion-receipt.json").exists()


def test_cardevent_promotion_compensates_after_export_failure(tmp_path: Path) -> None:
    repository_root, campaign_root, registry_path, app_bundle, campaign = _start_fixture_campaign(
        tmp_path
    )
    original_registry = registry_path.read_bytes()
    runner = FixtureCommandRunner(fail_commands=("export-coreml",))

    with pytest.raises(CardEventPromotionError, match="fixture export-coreml failed"):
        promote_card_event_campaign(
            campaign.campaign_id,
            repository_root=repository_root,
            registry_path=registry_path,
            campaign_root=campaign_root,
            project_root=tmp_path / "card_event_net",
            app_bundle_path=app_bundle,
            runner=runner,
            confirm=True,
            now_utc=TIMESTAMP,
        )

    failed = load_campaign(campaign_root, campaign.campaign_id)
    assert failed.state == "failed"
    receipt = load_promotion_receipt(
        campaign_root / campaign.campaign_id / "promotion-receipt.json"
    )
    assert receipt.promotion_state == "failed"
    assert receipt.registry_update == "unchanged"
    assert registry_path.read_bytes() == original_registry
    assert not app_bundle.exists()


def test_cardevent_promotion_restores_existing_app_bundle_on_registry_failure(
    tmp_path: Path, monkeypatch
) -> None:
    repository_root, campaign_root, registry_path, app_bundle, campaign = _start_fixture_campaign(
        tmp_path
    )
    app_bundle.write_text("old-app-bundle\n")
    original_registry = registry_path.read_bytes()
    original_app = app_bundle.read_bytes()
    real_atomic_write = campaign_module._atomic_write_bytes

    def fail_registry_write(path: Path, payload: bytes) -> None:
        if path == registry_path:
            raise OSError("fixture registry is read-only")
        real_atomic_write(path, payload)

    monkeypatch.setattr(campaign_module, "_atomic_write_bytes", fail_registry_write)
    with pytest.raises(CardEventPromotionError, match="read-only"):
        promote_card_event_campaign(
            campaign.campaign_id,
            repository_root=repository_root,
            registry_path=registry_path,
            campaign_root=campaign_root,
            project_root=tmp_path / "card_event_net",
            app_bundle_path=app_bundle,
            runner=FixtureCommandRunner(),
            confirm=True,
            now_utc=TIMESTAMP,
        )

    assert registry_path.read_bytes() == original_registry
    assert app_bundle.read_bytes() == original_app


def test_cardevent_promote_cli_promotes_fixture(tmp_path: Path, capsys) -> None:
    repository_root, campaign_root, registry_path, app_bundle, campaign = _start_fixture_campaign(
        tmp_path
    )

    assert (
        main(
            [
                "model",
                "promote",
                campaign.campaign_id,
                "--candidate",
                "candidate-1",
                "--repository-root",
                str(repository_root),
                "--model-registry",
                str(registry_path),
                "--campaign-root",
                str(campaign_root),
                "--project-root",
                str(tmp_path / "card_event_net"),
                "--app-bundle",
                str(app_bundle),
                "--runner",
                "fixture",
                "--confirm",
                "--format",
                "json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["campaign"]["state"] == "promoted"
