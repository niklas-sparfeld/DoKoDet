from __future__ import annotations

import json
from pathlib import Path

from table_evidence_analyzer.data import build_smoke_fixture

from doko_operations.cli import main
from doko_operations.model_improvement import load_campaign_comparison
from doko_operations.table_evidence_campaign import (
    TableEvidenceFixtureCommandRunner,
    run_table_evidence_campaign,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "model-improvement" / "v1"


def _recipe(tmp_path: Path) -> Path:
    smoke = build_smoke_fixture(tmp_path / "table-data")
    payload = json.loads((FIXTURE_ROOT / "recipe-table-analyzer.json").read_text())
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
