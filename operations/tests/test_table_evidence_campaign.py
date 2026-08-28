from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from table_evidence_analyzer.data import build_smoke_fixture
from table_evidence_analyzer.export import export_bundle

from doko_operations.cli import main
from doko_operations.model_improvement import load_campaign_comparison, load_model_registry
from doko_operations.table_evidence_campaign import (
    TableEvidenceFixtureCommandRunner,
    TableEvidencePromotionError,
    promote_table_evidence_campaign,
    run_table_evidence_campaign,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "model-improvement" / "v1"


def _recipe(tmp_path: Path) -> Path:
    smoke = build_smoke_fixture(tmp_path / "table-data")
    payload = json.loads((FIXTURE_ROOT / "recipe-table-analyzer.json").read_text())
    payload["sealed_test_authorized"] = True
    payload["data"]["dataset"] = {
        "id": json.loads(smoke.dataset_path.read_text())["dataset_version_id"],
        "digest": json.loads(smoke.dataset_path.read_text())["dataset_version_digest"],
    }
    payload["data"]["split"] = {
        "id": json.loads(smoke.split_path.read_text())["split_version_id"],
        "digest": json.loads(smoke.split_path.read_text())["split_version_digest"],
    }
    payload["candidates"][0]["configuration"].update(
        {
            "dataset_path": str(smoke.dataset_path),
            "split_path": str(smoke.split_path),
            "artifacts_path": str(smoke.artifact_index_path),
        }
    )
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(payload, indent=2) + "\n")
    return recipe_path


def _promotion_setup(tmp_path: Path) -> tuple[Path, Path, Path, Path, object]:
    repository = tmp_path / "repository"
    repository.mkdir()
    registry_path = repository / "registry.json"
    registry_payload = json.loads((FIXTURE_ROOT / "valid" / "registry.json").read_text())
    recipe = _recipe(tmp_path)
    recipe_payload = json.loads(recipe.read_text())
    dataset_digest = recipe_payload["data"]["dataset"]["digest"]
    split_digest = recipe_payload["data"]["split"]["digest"]
    old_run = tmp_path / "old-champion-run"
    old_run.mkdir()
    (old_run / "run.json").write_text(
        json.dumps(
            {
                "run_id": "run-table-champion",
                "dataset_version_digest": dataset_digest,
                "split_version_digest": split_digest,
                "centroids": {
                    "CLUBS_NINE": [0.0, 0.0, 0.0],
                    "HEARTS_QUEEN": [0.0, 0.0, 0.0],
                    "SPADES_JACK": [0.0, 0.0, 0.0],
                },
            },
            indent=2,
        )
        + "\n"
    )
    old_bundle = repository / "models" / "table-champion.bundle"
    export_bundle(old_run, old_bundle)
    table_champion = next(
        item
        for item in registry_payload["champions"]
        if item["component"] == "table-evidence-analyzer"
    )
    table_champion["bundle_path"] = "models/table-champion.bundle"
    table_champion["champion_bundle_digest"] = _bundle_digest(old_bundle)
    recipe_payload["baseline_bundle"]["digest"] = table_champion["champion_bundle_digest"]
    recipe.write_text(json.dumps(recipe_payload, indent=2) + "\n")
    registry_path.write_text(json.dumps(registry_payload, indent=2) + "\n")
    runner = TableEvidenceFixtureCommandRunner(test_quality=0.96)
    campaign = run_table_evidence_campaign(
        recipe,
        repository_root=repository,
        registry_path=registry_path,
        campaign_root=tmp_path / "campaigns",
        project_root=tmp_path / "table_evidence_analyzer",
        runner=runner,
        now_utc="2026-08-28T10:00:00.000Z",
    )
    return repository, tmp_path / "campaigns", registry_path, old_bundle, campaign


def _bundle_digest(path: Path) -> str:
    files = []
    for child in sorted(path.rglob("*")):
        if child.is_file():
            files.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "digest": hashlib.sha256(child.read_bytes()).hexdigest(),
                }
            )
    return hashlib.sha256(
        json.dumps({"files": files}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_table_fixture_campaign_is_bounded_capability_scoped_and_validation_only(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "registry.json").write_bytes(
        (FIXTURE_ROOT / "valid" / "registry.json").read_bytes()
    )
    recipe = _recipe(tmp_path)
    runner = TableEvidenceFixtureCommandRunner()

    campaign = run_table_evidence_campaign(
        recipe,
        repository_root=repository,
        registry_path="registry.json",
        campaign_root=tmp_path / "campaigns",
        project_root=tmp_path / "table_evidence_analyzer",
        runner=runner,
        now_utc="2026-08-28T10:00:00.000Z",
    )

    assert campaign.state == "candidate_locked"
    assert campaign.recommendation == "promote_candidate"
    campaign_dir = tmp_path / "campaigns" / campaign.campaign_id
    assert (campaign_dir / "capability-contract.json").is_file()
    assert (campaign_dir / "candidates" / "candidate-1" / "run-reference.json").is_file()
    assert (campaign_dir / "lock.json").is_file()
    contract = json.loads((campaign_dir / "capability-contract.json").read_text())
    assert contract["declared_capabilities"] == ["identity_candidates"]
    assert contract["complete_table_analysis"] is False
    assert contract["output_schema"] == "table-observation/v1"

    comparison = load_campaign_comparison(tmp_path / "campaigns", campaign)
    candidate = comparison.candidates[0]
    assert candidate.metrics["capability_contract"]["scope"] == "oracle_crop_identity_only"
    assert candidate.metrics["group_metrics"]["device"]["status"] == "not_available"
    device_gate = next(gate for gate in candidate.gates if gate.gate_id == "worst-device")
    assert device_gate.status == "not_applicable"
    assert all("test" not in command for command in runner.commands)
    assert [
        item["returncode"]
        for item in json.loads((campaign_dir / "logs" / "commands.json").read_text())["commands"]
    ] == [0, 0, 0, 0]

    command_count = len(runner.commands)
    resumed = run_table_evidence_campaign(
        recipe,
        repository_root=repository,
        registry_path="registry.json",
        campaign_root=tmp_path / "campaigns",
        project_root=tmp_path / "table_evidence_analyzer",
        runner=runner,
        now_utc="2026-08-28T10:00:00.000Z",
    )
    assert resumed.to_mapping() == campaign.to_mapping()
    assert len(runner.commands) == command_count


def test_table_improve_cli_accepts_explicit_plan_0020_paths(tmp_path: Path, capsys) -> None:
    recipe = _recipe(tmp_path)
    configuration = json.loads(recipe.read_text())["candidates"][0]["configuration"]
    repository = tmp_path / "cli-repository"
    repository.mkdir()
    (repository / "registry.json").write_bytes(
        (FIXTURE_ROOT / "valid" / "registry.json").read_bytes()
    )

    assert (
        main(
            [
                "model",
                "improve",
                "table-evidence-analyzer",
                "--recipe",
                str(recipe),
                "--repository-root",
                str(repository),
                "--model-registry",
                "registry.json",
                "--campaign-root",
                str(tmp_path / "cli-campaigns"),
                "--project-root",
                str(tmp_path / "table_evidence_analyzer"),
                "--runner",
                "fixture",
                "--dataset",
                configuration["dataset_path"],
                "--split",
                configuration["split_path"],
                "--artifacts",
                configuration["artifacts_path"],
                "--format",
                "json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["campaign"]["component"] == "table-evidence-analyzer"
    assert result["campaign"]["state"] == "candidate_locked"


def test_table_promotion_runs_sealed_test_and_updates_only_table_champion(tmp_path: Path) -> None:
    repository, campaign_root, registry_path, old_bundle, campaign = _promotion_setup(tmp_path)
    original_card_event = next(
        item
        for item in load_model_registry(registry_path).champions
        if item.component == "card-event-net"
    ).to_mapping()
    runner = TableEvidenceFixtureCommandRunner(test_quality=0.96)

    promoted = promote_table_evidence_campaign(
        campaign.campaign_id,
        repository_root=repository,
        registry_path=registry_path,
        campaign_root=campaign_root,
        project_root=tmp_path / "table_evidence_analyzer",
        runner=runner,
        confirm=True,
        now_utc="2026-08-28T10:00:00.000Z",
    )

    assert promoted.state == "promoted"
    campaign_dir = campaign_root / campaign.campaign_id
    assert (campaign_dir / "test-evaluation.json").is_file()
    assert (campaign_dir / "promotion-bundle").is_dir()
    assert (campaign_dir / "previous-champion-bundle").is_dir()
    assert (campaign_dir / "previous-champion.json").is_file()
    assert old_bundle.is_dir()
    checks = json.loads((campaign_dir / "promotion-checks.json").read_text())
    assert checks["runtime_only_load"]["training_data"] is False
    assert checks["plan0006_observation_fixture"]["schema"] == "table-observation/v1"
    registry = load_model_registry(registry_path)
    table_champion = registry.champion_for("table-evidence-analyzer", "visual-card-identity")
    assert table_champion is not None
    assert table_champion.bundle_path.startswith("models/table-evidence-analyzer-")
    assert table_champion.champion_bundle.digest == checks["bundle_validation"]["digest"]
    card_event = registry.champion_for("card-event-net", "event-detection")
    assert card_event is not None
    assert card_event.to_mapping() == original_card_event
    assert [command[command.index("table-analyzer") + 1] for command in runner.commands] == [
        "evaluate",
        "export",
    ]

    command_count = len(runner.commands)
    repeated = promote_table_evidence_campaign(
        campaign.campaign_id,
        repository_root=repository,
        registry_path=registry_path,
        campaign_root=campaign_root,
        runner=runner,
        confirm=True,
    )
    assert repeated.to_mapping() == promoted.to_mapping()
    assert len(runner.commands) == command_count


def test_table_promotion_requires_confirmation_without_mutation(tmp_path: Path) -> None:
    repository, campaign_root, registry_path, _old_bundle, campaign = _promotion_setup(tmp_path)
    original_registry = registry_path.read_bytes()

    with pytest.raises(TableEvidencePromotionError, match="explicit confirmation"):
        promote_table_evidence_campaign(
            campaign.campaign_id,
            repository_root=repository,
            registry_path=registry_path,
            campaign_root=campaign_root,
            confirm=False,
        )
    assert registry_path.read_bytes() == original_registry


def test_table_promotion_stops_on_poor_sealed_test(tmp_path: Path) -> None:
    repository, campaign_root, registry_path, _old_bundle, campaign = _promotion_setup(tmp_path)
    original_registry = registry_path.read_bytes()
    runner = TableEvidenceFixtureCommandRunner(test_quality=0.5)

    result = promote_table_evidence_campaign(
        campaign.campaign_id,
        repository_root=repository,
        registry_path=registry_path,
        campaign_root=campaign_root,
        project_root=tmp_path / "table_evidence_analyzer",
        runner=runner,
        confirm=True,
        now_utc="2026-08-28T10:00:00.000Z",
    )

    assert result.state == "human_review_required"
    assert registry_path.read_bytes() == original_registry
    assert len(runner.commands) == 1
    assert not (campaign_root / campaign.campaign_id / "promotion-receipt.json").exists()


def test_table_promotion_compensates_after_export_failure(tmp_path: Path) -> None:
    repository, campaign_root, registry_path, _old_bundle, campaign = _promotion_setup(tmp_path)
    original_registry = registry_path.read_bytes()
    runner = TableEvidenceFixtureCommandRunner(test_quality=0.96, fail_commands=("export",))

    with pytest.raises(TableEvidencePromotionError, match="fixture export failed"):
        promote_table_evidence_campaign(
            campaign.campaign_id,
            repository_root=repository,
            registry_path=registry_path,
            campaign_root=campaign_root,
            project_root=tmp_path / "table_evidence_analyzer",
            runner=runner,
            confirm=True,
            now_utc="2026-08-28T10:00:00.000Z",
        )

    failed = json.loads((campaign_root / campaign.campaign_id / "campaign.json").read_text())
    assert failed["state"] == "failed"
    assert registry_path.read_bytes() == original_registry
    target = (
        repository / "models" / f"table-evidence-analyzer-{campaign.campaign_id}-candidate-1.bundle"
    )
    assert not target.exists()


def test_table_promotion_cli_uses_table_promotion_path(tmp_path: Path, capsys) -> None:
    repository, campaign_root, registry_path, _old_bundle, campaign = _promotion_setup(tmp_path)

    assert (
        main(
            [
                "model",
                "promote",
                campaign.campaign_id,
                "--repository-root",
                str(repository),
                "--model-registry",
                str(registry_path),
                "--campaign-root",
                str(campaign_root),
                "--project-root",
                str(tmp_path / "table_evidence_analyzer"),
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
    assert result["campaign"]["component"] == "table-evidence-analyzer"
    assert result["campaign"]["state"] == "promoted"
