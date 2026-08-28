from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from doko_operations.cardevent_campaign import FixtureCommandRunner, run_card_event_campaign

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "model-improvement" / "v1"
SKILL_ROOT = Path(__file__).parents[2] / ".codex" / "skills" / "model-improvement"
PROPOSAL_SCRIPT = SKILL_ROOT / "scripts" / "propose_recipe.py"
TIMESTAMP = "2026-08-29T10:00:00.000Z"


def _create_proposed_recipe(tmp_path: Path) -> tuple[Path, bytes]:
    output = tmp_path / "proposal" / "proposed-cardevent.json"
    registry_path = FIXTURE_ROOT / "valid" / "registry.json"
    registry_before = registry_path.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            str(PROPOSAL_SCRIPT),
            "--recipe",
            str(FIXTURE_ROOT / "recipe-cardevent.json"),
            "--output",
            str(output),
            "--reason",
            "Recheck the bounded threshold axis on the fixture contract.",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "proposal:" in result.stdout
    assert "recipe digest:" in result.stdout
    assert output.is_file()
    return output, registry_before


def _run_fixture_campaign(recipe_path: Path, root: Path):
    repository_root = root / "repository"
    repository_root.mkdir(parents=True)
    registry_path = repository_root / "registry.json"
    registry_path.write_bytes((FIXTURE_ROOT / "valid" / "registry.json").read_bytes())
    runner = FixtureCommandRunner()
    campaign = run_card_event_campaign(
        recipe_path,
        repository_root=repository_root,
        registry_path=registry_path,
        campaign_root=root / "campaigns",
        project_root=root / "card_event_net",
        runner=runner,
        now_utc=TIMESTAMP,
    )
    return campaign, runner, root / "campaigns" / campaign.campaign_id


def _command_names(runner: FixtureCommandRunner) -> list[str]:
    command_names = {
        "train",
        "evaluate",
        "diagnose",
        "export-coreml",
        "mine-hard-negatives",
    }
    return [next(item for item in command if item in command_names) for command in runner.commands]


def test_skill_and_python_clean_room_campaigns_match(tmp_path: Path) -> None:
    proposed_recipe, registry_before = _create_proposed_recipe(tmp_path)
    plain_campaign, plain_runner, plain_dir = _run_fixture_campaign(
        FIXTURE_ROOT / "recipe-cardevent.json", tmp_path / "plain"
    )
    skill_campaign, skill_runner, skill_dir = _run_fixture_campaign(
        proposed_recipe, tmp_path / "skill"
    )

    assert proposed_recipe.read_bytes() != (FIXTURE_ROOT / "recipe-cardevent.json").read_bytes()
    assert json.loads(proposed_recipe.read_text()) == json.loads(
        (FIXTURE_ROOT / "recipe-cardevent.json").read_text()
    )
    assert plain_campaign.to_mapping() == skill_campaign.to_mapping()
    assert plain_campaign.recommendation == "promote_candidate"
    assert skill_campaign.recommendation == plain_campaign.recommendation
    assert _command_names(plain_runner) == ["evaluate", "train", "evaluate", "diagnose"]
    assert _command_names(skill_runner) == _command_names(plain_runner)

    for artifact_name in ("campaign.json", "comparison.json", "lock.json"):
        assert json.loads((plain_dir / artifact_name).read_text()) == json.loads(
            (skill_dir / artifact_name).read_text()
        )
    assert registry_before == (FIXTURE_ROOT / "valid" / "registry.json").read_bytes()


def test_proposal_helper_cannot_mutate_campaign_or_registry_destinations(tmp_path: Path) -> None:
    source = FIXTURE_ROOT / "recipe-cardevent.json"
    args = [
        sys.executable,
        str(PROPOSAL_SCRIPT),
        "--recipe",
        str(source),
        "--reason",
        "Keep the fixture axis bounded.",
    ]
    campaign_output = tmp_path / "campaigns" / "proposed-recipe.json"
    blocked_campaign = subprocess.run(
        [*args, "--output", str(campaign_output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked_campaign.returncode == 2
    assert not campaign_output.exists()

    registry_output = tmp_path / "registry.json"
    blocked_registry = subprocess.run(
        [*args, "--output", str(registry_output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked_registry.returncode == 2
    assert not registry_output.exists()


def test_skill_documents_human_confirmation_and_blocked_handoff() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text()

    assert "Before candidate lock, read validation artifacts only." in skill
    assert "must not run, a promotion command" in skill
    assert "follow-up epic" in skill
    assert "doko model compare <campaign-id>" in skill
