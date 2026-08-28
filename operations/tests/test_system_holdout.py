from __future__ import annotations

import json
from pathlib import Path

import pytest

from doko_operations.cli import main
from doko_operations.holdout import seal_system_holdout_group
from doko_operations.model_improvement import sha256_mapping
from doko_operations.system_holdout import (
    SystemHoldoutEvaluationError,
    SystemHoldoutFixtureRunner,
    evaluate_system_holdout,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
SCENARIO = REPOSITORY_ROOT / "fixtures" / "game-engine" / "v1" / "rounds" / "unambiguous.json"
CONFIG = (
    REPOSITORY_ROOT / "fixtures" / "model-improvement" / "v1" / "system-reconstruction-config.json"
)
TIMESTAMP = "2026-08-29T10:00:00.000Z"


def _data(prefix: str) -> dict[str, object]:
    split_prefix = chr(ord(prefix) + 1)
    return {
        "dataset": {"id": f"dataset-{prefix}", "digest": f"{prefix}" * 64},
        "split": {"id": f"split-{prefix}", "digest": split_prefix * 64},
        "source_annotation": {"id": f"annotation-{prefix}", "digest": "c" * 64},
        "review": {"id": f"review-{prefix}", "digest": "d" * 64},
    }


def _evaluation(
    *,
    role: str,
    evaluation_id: str,
    bundle_id: str,
    bundle_digest: str,
    data: dict[str, object],
    candidate_id: str | None = None,
) -> dict[str, object]:
    return {
        "evaluation_id": evaluation_id,
        "role": role,
        "candidate_id": candidate_id,
        "run_id": f"run-{evaluation_id}",
        "bundle": {"id": bundle_id, "digest": bundle_digest},
        "state": "success",
        "data": data,
        "metrics": {},
        "gates": [],
        "failure_reason": None,
    }


def _write_locked_campaign(
    campaigns: Path,
    *,
    campaign_id: str,
    component: str,
    capability: str,
    task: str,
    data: dict[str, object],
    baseline_digest: str,
    candidate_digest: str,
) -> None:
    campaign_dir = campaigns / campaign_id
    campaign_dir.mkdir(parents=True)
    recipe_digest = "e" * 64
    candidate_id = "candidate-1"
    candidate_evaluation_id = f"evaluation-{campaign_id}-candidate"
    comparison_id = f"comparison-{campaign_id}"
    lock_id = f"lock-{campaign_id}"
    champion = _evaluation(
        role="champion",
        evaluation_id=f"evaluation-{campaign_id}-champion",
        bundle_id=f"{component}-champion",
        bundle_digest=baseline_digest,
        data=data,
    )
    candidate = _evaluation(
        role="candidate",
        evaluation_id=candidate_evaluation_id,
        bundle_id=f"{component}-candidate",
        bundle_digest=candidate_digest,
        data=data,
        candidate_id=candidate_id,
    )
    comparison = {
        "schema_version": "model-comparison/v1",
        "comparison_id": comparison_id,
        "campaign_id": campaign_id,
        "component": component,
        "capability": capability,
        "task": task,
        "recipe_digest": recipe_digest,
        "gate_profile_id": f"{component}-fixture",
        "data": data,
        "champion": champion,
        "candidates": [candidate],
        "recommendation": "promote_candidate",
        "recommended_candidate_id": candidate_id,
        "selection_order": [candidate_id],
        "generated_at_utc": TIMESTAMP,
    }
    run_id = candidate["run_id"]
    run = {
        "candidate_id": candidate_id,
        "run_id": run_id,
        "state": "success",
        "run_digest": "f" * 64,
        "checkpoint_id": f"checkpoint-{campaign_id}",
        "result_digest": "1" * 64,
        "failure_reason": None,
    }
    campaign = {
        "schema_version": "model-campaign/v1",
        "campaign_id": campaign_id,
        "component": component,
        "capability": capability,
        "task": task,
        "recipe_id": f"recipe-{campaign_id}",
        "recipe_digest": recipe_digest,
        "baseline_bundle": champion["bundle"],
        "data": data,
        "state": "candidate_locked",
        "created_at_utc": TIMESTAMP,
        "updated_at_utc": TIMESTAMP,
        "candidate_runs": [run],
        "comparison_id": comparison_id,
        "lock_id": lock_id,
        "test_evaluation_id": None,
        "promotion_receipt_id": None,
        "recommendation": "promote_candidate",
        "failure_reason": None,
    }
    lock = {
        "schema_version": "model-candidate-lock/v1",
        "lock_id": lock_id,
        "campaign_id": campaign_id,
        "component": component,
        "capability": capability,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "checkpoint_id": run["checkpoint_id"],
        "recipe_digest": recipe_digest,
        "data": data,
        "validation_evaluation_id": candidate_evaluation_id,
        "threshold_settings": {},
        "decoder_settings": {},
        "code_revision": "fixture",
        "code_dirty": False,
        "locked_at_utc": TIMESTAMP,
    }
    for name, payload in (
        ("campaign.json", campaign),
        ("comparison.json", comparison),
        ("lock.json", lock),
    ):
        (campaign_dir / name).write_text(json.dumps(payload, indent=2) + "\n")


def _manifest_pair(root: Path, prefix: str, data: dict[str, object]) -> tuple[Path, Path]:
    dataset_path = root / f"{prefix}-dataset.json"
    split_path = root / f"{prefix}-split.json"
    dataset = {
        "dataset_version_id": data["dataset"]["id"],
        "dataset_version_digest": data["dataset"]["digest"],
        "entries": [
            {
                "dataset_item_id": f"{prefix}-train",
                "group_keys": [["source_lineage", f"{prefix}-training"]],
            },
            {
                "dataset_item_id": f"{prefix}-holdout",
                "group_keys": [["session_id", "synthetic-session-0006"]],
            },
        ],
    }
    split_core = {
        "dataset_version_id": data["dataset"]["id"],
        "dataset_version_digest": data["dataset"]["digest"],
        "train": [f"{prefix}-train"],
        "validation": [],
        "test": [f"{prefix}-holdout"],
        "unassigned": [],
    }
    split = {
        "split_version_id": data["split"]["id"],
        **split_core,
        "split_version_digest": sha256_mapping(split_core),
    }
    data["split"]["digest"] = split["split_version_digest"]
    dataset_path.write_text(json.dumps(dataset, indent=2) + "\n")
    split_path.write_text(json.dumps(split, indent=2) + "\n")
    return dataset_path, split_path


def _setup(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "repository"
    campaigns = root / "campaigns"
    campaigns.mkdir(parents=True)
    card_data = _data("a")
    table_data = _data("b")
    card_dataset, card_split = _manifest_pair(root, "card", card_data)
    table_dataset, table_split = _manifest_pair(root, "table", table_data)
    _write_locked_campaign(
        campaigns,
        campaign_id="card-campaign",
        component="card-event-net",
        capability="event-detection",
        task="cardevent_event_detection",
        data=card_data,
        baseline_digest="1" * 64,
        candidate_digest="2" * 64,
    )
    _write_locked_campaign(
        campaigns,
        campaign_id="table-campaign",
        component="table-evidence-analyzer",
        capability="visual-card-identity",
        task="table_evidence_analysis",
        data=table_data,
        baseline_digest="3" * 64,
        candidate_digest="4" * 64,
    )
    holdout = root / "system-holdout-registry.json"
    seal_system_holdout_group(
        holdout,
        group_name="session_id",
        group_value="synthetic-session-0006",
        reviewer="fixture-reviewer",
        review_id="fixture-review-1",
        reason="M5 local system fixture",
    )
    registry = root / "model-registry.json"
    registry.write_bytes(
        (
            REPOSITORY_ROOT / "fixtures" / "model-improvement" / "v1" / "valid" / "registry.json"
        ).read_bytes()
    )
    return {
        "root": root,
        "campaigns": campaigns,
        "card_dataset": card_dataset,
        "card_split": card_split,
        "table_dataset": table_dataset,
        "table_split": table_split,
        "holdout": holdout,
        "registry": registry,
    }


def _evaluate(paths: dict[str, Path], *, runner: SystemHoldoutFixtureRunner | None = None):
    return evaluate_system_holdout(
        "card-campaign",
        "table-campaign",
        repository_root=paths["root"],
        cardevent_dataset_path=paths["card_dataset"],
        cardevent_split_path=paths["card_split"],
        table_dataset_path=paths["table_dataset"],
        table_split_path=paths["table_split"],
        reconstruction_config_path=CONFIG,
        holdout_registry_path=paths["holdout"],
        model_registry_path=paths["registry"],
        campaign_root=paths["campaigns"],
        fixture_path=SCENARIO,
        evaluation_root=paths["root"] / "evaluations",
        runner=runner,
        now_utc=TIMESTAMP,
    )


def test_system_holdout_runs_locked_fixture_and_is_idempotent(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    before_campaign = (paths["campaigns"] / "card-campaign" / "campaign.json").read_bytes()
    before_registry = paths["registry"].read_bytes()
    runner = SystemHoldoutFixtureRunner()

    report = _evaluate(paths, runner=runner)

    assert report.status == "passed"
    assert report.recommendation == "system_holdout_passed"
    assert report.fixture["covered_holdout_groups"] == [["session_id", "synthetic-session-0006"]]
    assert all(
        item["isolation"]["unseen_by_training_or_selection"] for item in report.components.values()
    )
    assert all(item["status"] == "passed" for item in report.failure_attribution.values())
    assert runner.calls == 1
    assert (paths["campaigns"] / "card-campaign" / "campaign.json").read_bytes() == before_campaign
    assert paths["registry"].read_bytes() == before_registry

    repeated = _evaluate(paths, runner=runner)
    assert repeated.to_mapping() == report.to_mapping()
    assert runner.calls == 1


def test_system_holdout_rejects_component_training_leakage(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    payload = json.loads(paths["card_dataset"].read_text())
    payload["entries"][0]["group_keys"] = [["session_id", "synthetic-session-0006"]]
    paths["card_dataset"].write_text(json.dumps(payload))

    with pytest.raises(SystemHoldoutEvaluationError, match="system holdout leakage"):
        _evaluate(paths)


@pytest.mark.parametrize("boundary", ("event", "observation", "reconstruction"))
def test_system_holdout_attributes_failures_to_pipeline_boundaries(
    tmp_path: Path, boundary: str
) -> None:
    paths = _setup(tmp_path)
    report = _evaluate(paths, runner=SystemHoldoutFixtureRunner(fail_boundary=boundary))

    assert report.status == "failed"
    assert report.recommendation == "human_review_required"
    assert report.failure_attribution[boundary]["status"] == "failed"
    assert report.failure_attribution[boundary]["failures"]
    assert set(report.failure_attribution) == {"event", "observation", "reconstruction"}


def test_system_holdout_requires_a_locked_component_campaign(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    campaign_path = paths["campaigns"] / "table-campaign" / "campaign.json"
    payload = json.loads(campaign_path.read_text())
    payload["state"] = "compared"
    payload["lock_id"] = None
    campaign_path.write_text(json.dumps(payload))

    with pytest.raises(SystemHoldoutEvaluationError, match="is not locked"):
        _evaluate(paths)


def test_system_holdout_cli_writes_json_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _setup(tmp_path)

    assert (
        main(
            [
                "model",
                "evaluate-system",
                "card-campaign",
                "table-campaign",
                "--repository-root",
                str(paths["root"]),
                "--campaign-root",
                str(paths["campaigns"]),
                "--holdout-registry",
                str(paths["holdout"]),
                "--model-registry",
                str(paths["registry"]),
                "--cardevent-dataset",
                str(paths["card_dataset"]),
                "--cardevent-split",
                str(paths["card_split"]),
                "--table-dataset",
                str(paths["table_dataset"]),
                "--table-split",
                str(paths["table_split"]),
                "--reconstruction-config",
                str(CONFIG),
                "--fixture",
                str(SCENARIO),
                "--evaluation-root",
                str(paths["root"] / "evaluations"),
                "--runner",
                "fixture",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["report"]["status"] == "passed"
