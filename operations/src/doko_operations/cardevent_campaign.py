"""Resumable CardEventNet campaign execution for model-improvement operations."""

from __future__ import annotations

import hashlib
import json
import math
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .model_improvement import (
    ArtifactReference,
    CandidateLock,
    CandidateRunReference,
    DataContext,
    ModelCampaign,
    ModelComparison,
    ModelEvaluation,
    ModelImprovementError,
    ModelRecipe,
    compare_evaluations,
    default_gate_profile,
    load_campaign,
    load_model_recipe,
    load_model_registry,
    render_comparison_report,
    sha256_mapping,
    validate_campaign_against_registry,
)


class CardEventCampaignError(ModelImprovementError):
    """Raised when a CardEventNet campaign cannot be completed."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The small result surface needed by the campaign runner."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Run one existing CardEventNet command."""

    def run(
        self, command: Sequence[str], *, cwd: Path, log_path: Path
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    """Execute CardEventNet commands and retain their complete output."""

    def run(
        self, command: Sequence[str], *, cwd: Path, log_path: Path
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                list(command),
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            _write_text(
                log_path,
                f"command: {shlex.join(command)}\nreturncode: 127\nerror: {error}\n",
            )
            return CommandResult(127, "", str(error))
        _write_text(
            log_path,
            "\n".join(
                (
                    f"command: {shlex.join(command)}",
                    f"returncode: {completed.returncode}",
                    "--- stdout ---",
                    completed.stdout,
                    "--- stderr ---",
                    completed.stderr,
                    "",
                )
            ),
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class FixtureCommandRunner:
    """Create tiny deterministic CardEventNet artifacts for local clean-room tests."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self, command: Sequence[str], *, cwd: Path, log_path: Path
    ) -> CommandResult:
        del cwd
        command = tuple(str(item) for item in command)
        self.commands.append(command)
        _write_text(log_path, f"command: {shlex.join(command)}\nreturncode: 0\n")
        if "train" in command:
            output_dir = Path(_option(command, "--output-dir"))
            run_name = _option(command, "--run-name")
            run_dir = output_dir / run_name
            _write_text(run_dir / "best.pt", f"fixture-checkpoint:{run_name}\n")
            _write_json(run_dir / "summary.json", {"run_dir": str(run_dir), "state": "success"})
        elif "evaluate" in command:
            output_path = Path(_option(command, "--out"))
            checkpoint = Path(_option(command, "--checkpoint"))
            is_candidate = checkpoint.parent.name.startswith("candidate-")
            quality = 0.93 if is_candidate else 0.90
            _write_json(output_path, _fixture_evaluation(quality=quality))
        elif "diagnose" in command:
            _write_json(Path(_option(command, "--out")), {"method": "fixture-diagnostics-v1"})
        elif "export-coreml" in command:
            _write_text(Path(_option(command, "--out")), "fixture-coreml-bundle\n")
        elif "mine-hard-negatives" in command:
            _write_json(
                Path(_option(command, "--out")),
                {"format": "cardevent-hard-negatives-v1", "hard_negative_count": 0},
            )
        return CommandResult(0)


def _fixture_evaluation(*, quality: float) -> dict[str, object]:
    return {
        "method": "cardeventnet-fixture",
        "partition": "val",
        "threshold": 0.5,
        "overall": {
            "event_recall": quality,
            "event_precision": quality,
            "event_f1": quality,
            "false_events_per_hour": 0.4 if quality > 0.90 else 0.5,
            "timestamp_error_median_s": 0.2,
            "emission_latency_median_s": 0.4,
        },
        "videos": [{"video": "fixture-video", "event_f1": quality}],
        "model_metrics": {
            "worst_video_f1": quality,
            "worst_video_support": 1,
            "important_scenario_group_f1": quality,
            "important_scenario_group_support": 1,
            "reviewed_hard_negative_false_positive_rate": 0.0,
            "reviewed_hard_negative_support": 1,
            "inference_latency_ms": 40,
            "coreml_export": True,
            "device_parity": 0.98,
            "regression_fixtures": True,
            "decoder_compatible": True,
        },
    }


def _option(command: Sequence[str], name: str) -> str:
    try:
        return str(command[command.index(name) + 1])
    except (ValueError, IndexError) as error:
        raise CardEventCampaignError(f"fixture command is missing {name}") from error


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, UnicodeError) as error:
        raise CardEventCampaignError(f"Could not hash artifact {path}: {error}") from error


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _resolve(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _read_json(path: Path, context: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventCampaignError(f"Could not read {context} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise CardEventCampaignError(f"{context} {path} must contain a JSON object.")
    return payload


def _write_campaign(path: Path, campaign: ModelCampaign) -> None:
    _write_json(path, campaign.to_mapping())


def _campaign_id(recipe: ModelRecipe, requested: str | None) -> str:
    return requested or f"{recipe.recipe_id}-{recipe.digest[:12]}"


def _command_prefix(project_root: Path) -> tuple[str, ...]:
    return ("mise", "exec", "--", "uv", "run", "--project", str(project_root), "cardevent")


def _path_from_configuration(
    configuration: Mapping[str, object], key: str, default: Path, root: Path
) -> Path:
    value = configuration.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise CardEventCampaignError(f"candidate configuration {key} must be a path string")
    return _resolve(root, value)


def _int_from_configuration(
    configuration: Mapping[str, object], key: str, default: int | None
) -> int | None:
    value = configuration.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CardEventCampaignError(f"candidate configuration {key} must be a positive integer")
    return value


def _seed_from_configuration(configuration: Mapping[str, object], default: int) -> int:
    value = configuration.get("seed", default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CardEventCampaignError("candidate configuration seed must be a non-negative integer")
    return value


def _threshold_from_configuration(
    configuration: Mapping[str, object], key: str = "threshold"
) -> float | None:
    value = configuration.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CardEventCampaignError(f"candidate configuration {key} must be finite")
    if not 0.0 <= value <= 1.0:
        raise CardEventCampaignError(f"candidate configuration {key} must be between 0 and 1")
    return float(value)


def _string_from_configuration(
    configuration: Mapping[str, object], key: str, default: str | None
) -> str | None:
    value = configuration.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CardEventCampaignError(f"candidate configuration {key} must be a non-empty string")
    return value


def _bool_from_configuration(configuration: Mapping[str, object], key: str) -> bool:
    value = configuration.get(key, False)
    if not isinstance(value, bool):
        raise CardEventCampaignError(f"candidate configuration {key} must be a boolean")
    return value


def _candidate_command_options(
    configuration: Mapping[str, object],
    *,
    root: Path,
    project_root: Path,
    default_config: Path,
    default_split: Path,
    default_cache: Path,
    default_annotations: Path,
    output_dir: Path,
    run_name: str,
    hard_negative_manifest: Path | None = None,
    max_samples: int | None = None,
    device: str | None = None,
    precision: str | None = None,
    seed: int = 0,
) -> tuple[str, ...]:
    config_path = _path_from_configuration(
        configuration,
        "config_path",
        _path_from_configuration(configuration, "config", default_config, root),
        root,
    )
    split_path = _path_from_configuration(configuration, "split_path", default_split, root)
    cache_dir = _path_from_configuration(configuration, "cache_dir", default_cache, root)
    annotations_dir = _path_from_configuration(
        configuration, "annotations_dir", default_annotations, root
    )
    selected_samples = _int_from_configuration(configuration, "max_samples", max_samples)
    selected_device = _string_from_configuration(configuration, "device", device)
    selected_precision = _string_from_configuration(configuration, "precision", precision)
    command: list[str] = [
        *_command_prefix(project_root),
        "train",
        "--config",
        str(config_path),
        "--split",
        str(split_path),
        "--output-dir",
        str(output_dir),
        "--run-name",
        run_name,
        "--seed",
        str(seed),
        "--cache-dir",
        str(cache_dir),
        "--annotations-dir",
        str(annotations_dir),
    ]
    if selected_samples is not None:
        command.extend(("--max-samples", str(selected_samples)))
    if selected_device is not None:
        command.extend(("--device", selected_device))
    if selected_precision is not None:
        command.extend(("--precision", selected_precision))
    if hard_negative_manifest is not None:
        command.extend(("--hard-negative-manifest", str(hard_negative_manifest)))
    return tuple(command)


def _evaluation_command(
    checkpoint: Path,
    *,
    project_root: Path,
    split: Path,
    cache_dir: Path,
    annotations_dir: Path,
    output_path: Path,
    device: str | None,
    threshold: float | None = None,
) -> tuple[str, ...]:
    command: list[str] = [
        *_command_prefix(project_root),
        "evaluate",
        "--checkpoint",
        str(checkpoint),
        "--split",
        str(split),
        "--partition",
        "val",
        "--cache-dir",
        str(cache_dir),
        "--annotations-dir",
        str(annotations_dir),
        "--out",
        str(output_path),
    ]
    if device is not None:
        command.extend(("--device", device))
    if threshold is not None:
        command.extend(("--threshold", str(threshold)))
    return tuple(command)


def _diagnose_command(
    checkpoint: Path,
    *,
    split: Path,
    cache_dir: Path,
    annotations_dir: Path,
    output_path: Path,
    device: str | None,
    project_root: Path,
) -> tuple[str, ...]:
    command: list[str] = [
        *_command_prefix(project_root),
        "diagnose",
        "--checkpoint",
        str(checkpoint),
        "--split",
        str(split),
        "--cache-dir",
        str(cache_dir),
        "--annotations-dir",
        str(annotations_dir),
        "--out",
        str(output_path),
    ]
    if device is not None:
        command.extend(("--device", device))
    return tuple(command)


def _metrics_from_evaluation(
    payload: Mapping[str, object], checkpoint: Path
) -> dict[str, object]:
    overall = payload.get("overall", {})
    if not isinstance(overall, Mapping):
        raise CardEventCampaignError("CardEventNet evaluation has no overall metrics object")
    metrics = (
        dict(payload.get("model_metrics", {}))
        if isinstance(payload.get("model_metrics"), Mapping)
        else {}
    )
    aliases = {
        "event_recall": "event_recall",
        "event_precision": "event_precision",
        "event_f1": "event_f1",
        "false_events_per_hour": "false_events_per_hour",
    }
    for destination, source in aliases.items():
        if destination not in metrics and source in overall:
            metrics[destination] = overall[source]
    videos = payload.get("videos", [])
    video_f1 = [
        float(item["event_f1"])
        for item in videos
        if isinstance(item, Mapping) and isinstance(item.get("event_f1"), (int, float))
    ] if isinstance(videos, list) else []
    metrics.setdefault("worst_video_f1", min(video_f1, default=0.0))
    metrics.setdefault("worst_video_support", len(video_f1))
    metrics.setdefault("important_scenario_group_f1", 0.0)
    metrics.setdefault("important_scenario_group_support", 0)
    metrics.setdefault("reviewed_hard_negative_false_positive_rate", 0.0)
    metrics.setdefault("reviewed_hard_negative_support", 0)
    checkpoint_size = checkpoint.stat().st_size / (1024 * 1024) if checkpoint.is_file() else 0.0
    metrics.setdefault("model_size_mb", checkpoint_size)
    if "timestamp_confirmation_delay_ms" not in metrics:
        metrics["timestamp_confirmation_delay_ms"] = float(
            overall.get("timestamp_error_median_s", overall.get("latency_median_s", 0.0))
        ) * 1000.0
    if "causal_confirmation_delay_ms" not in metrics:
        metrics["causal_confirmation_delay_ms"] = float(
            overall.get("emission_latency_median_s", 0.0)
        ) * 1000.0
    metrics.setdefault("decoder_compatible", True)
    return metrics


def _evaluation(
    *,
    evaluation_id: str,
    role: str,
    candidate_id: str | None,
    run_id: str,
    bundle: ArtifactReference,
    state: str,
    data: DataContext,
    metrics: Mapping[str, object],
    failure_reason: str | None = None,
) -> ModelEvaluation:
    return ModelEvaluation.from_mapping(
        {
            "evaluation_id": evaluation_id,
            "role": role,
            "candidate_id": candidate_id,
            "run_id": run_id,
            "bundle": bundle.to_mapping(),
            "state": state,
            "data": data.to_mapping(),
            "metrics": dict(metrics),
            "gates": [],
            "failure_reason": failure_reason,
        }
    )


def _failure_evaluation(
    *, campaign_id: str, candidate_id: str, data: DataContext, state: str, reason: str
) -> ModelEvaluation:
    bundle = ArtifactReference(
        f"bundle-{campaign_id}-{candidate_id}",
        sha256_mapping(
            {"campaign_id": campaign_id, "candidate_id": candidate_id, "reason": reason}
        ),
    )
    return _evaluation(
        evaluation_id=f"evaluation-{campaign_id}-{candidate_id}",
        role="candidate",
        candidate_id=candidate_id,
        run_id=f"run-{campaign_id}-{candidate_id}",
        bundle=bundle,
        state=state,
        data=data,
        metrics={},
        failure_reason=reason,
    )


def _git_metadata(root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "working-tree", False
    return revision or "working-tree", dirty


def _create_campaign(recipe: ModelRecipe, campaign_id: str, timestamp: str) -> ModelCampaign:
    return ModelCampaign.from_mapping(
        {
            "schema_version": "model-campaign/v1",
            "campaign_id": campaign_id,
            "component": recipe.component,
            "capability": recipe.capability,
            "task": recipe.task,
            "recipe_id": recipe.recipe_id,
            "recipe_digest": recipe.digest,
            "baseline_bundle": recipe.baseline_bundle.to_mapping(),
            "data": recipe.data.to_mapping(),
            "state": "created",
            "created_at_utc": timestamp,
            "updated_at_utc": timestamp,
            "candidate_runs": [],
            "comparison_id": None,
            "lock_id": None,
            "test_evaluation_id": None,
            "promotion_receipt_id": None,
            "recommendation": None,
            "failure_reason": None,
        }
    )


def _update(
    campaign: ModelCampaign, *, state: str, timestamp: str, **changes: object
) -> ModelCampaign:
    return replace(campaign, state=state, updated_at_utc=timestamp, **changes)


def _run_checked(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    root: Path,
    log_path: Path,
    manifest_path: Path | None = None,
) -> None:
    record: dict[str, object] = {
        "command": list(command),
        "log_path": str(log_path),
        "returncode": None,
    }
    records: list[dict[str, object]] = []
    if manifest_path is not None and manifest_path.exists():
        existing = _read_json(manifest_path, "command manifest")
        if existing.get("schema_version") != "model-campaign-commands/v1":
            raise CardEventCampaignError("command manifest has an unsupported schema_version")
        value = existing.get("commands")
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise CardEventCampaignError("command manifest commands must be objects")
        records = list(value)
    records.append(record)
    if manifest_path is not None:
        _write_json(
            manifest_path,
            {"schema_version": "model-campaign-commands/v1", "commands": records},
        )
    result = runner.run(command, cwd=root, log_path=log_path)
    record["returncode"] = result.returncode
    if manifest_path is not None:
        _write_json(
            manifest_path,
            {"schema_version": "model-campaign-commands/v1", "commands": records},
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise CardEventCampaignError(f"CardEventNet command failed: {detail}")


def _load_profile(recipe: ModelRecipe):
    profile = default_gate_profile(recipe.component)
    if profile.gate_profile_id != recipe.gate_profile_id:
        raise CardEventCampaignError(
            f"recipe gate profile {recipe.gate_profile_id} does not match checked-in profile "
            f"{profile.gate_profile_id}"
        )
    return profile


def _candidate_configuration(candidate: object) -> Mapping[str, object]:
    configuration = getattr(candidate, "configuration", None)
    if not isinstance(configuration, Mapping):
        raise CardEventCampaignError("candidate configuration must be an object")
    return configuration


def _candidate_run_digest(recipe: ModelRecipe, candidate: object) -> str:
    return sha256_mapping(
        {
            "recipe_digest": recipe.digest,
            "candidate": candidate.to_mapping(),
            "data": recipe.data.to_mapping(),
            "seed": recipe.seeds[0],
        }
    )


def _candidate_lock(
    campaign: ModelCampaign,
    recipe: ModelRecipe,
    candidate: object,
    evaluation: ModelEvaluation,
    evaluation_payload: Mapping[str, object],
    checkpoint_id: str,
    root: Path,
    timestamp: str,
) -> CandidateLock:
    configuration = _candidate_configuration(candidate)
    threshold = evaluation_payload.get("threshold")
    threshold_settings: dict[str, object] = {"source": "validation"}
    if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
        threshold_settings["threshold"] = threshold
    decoder_settings = configuration.get("decoder_settings", {})
    if not isinstance(decoder_settings, Mapping):
        raise CardEventCampaignError("candidate decoder_settings must be an object")
    code_revision, code_dirty = _git_metadata(root)
    identity = {
        "campaign_id": campaign.campaign_id,
        "candidate_id": candidate.candidate_id,
        "evaluation_id": evaluation.evaluation_id,
    }
    return CandidateLock.from_mapping(
        {
            "schema_version": "model-candidate-lock/v1",
            "lock_id": f"lock-{sha256_mapping(identity)[:20]}",
            "campaign_id": campaign.campaign_id,
            "component": recipe.component,
            "capability": recipe.capability,
            "candidate_id": candidate.candidate_id,
            "run_id": evaluation.run_id,
            "checkpoint_id": checkpoint_id,
            "recipe_digest": recipe.digest,
            "data": recipe.data.to_mapping(),
            "validation_evaluation_id": evaluation.evaluation_id,
            "threshold_settings": threshold_settings,
            "decoder_settings": dict(decoder_settings),
            "code_revision": code_revision,
            "code_dirty": code_dirty,
            "locked_at_utc": timestamp,
        }
    )


def render_card_event_campaign_report(
    campaign: ModelCampaign, comparison: ModelComparison, *, recipe: ModelRecipe
) -> str:
    """Render the M1 report from the resolved recipe and comparison artifacts."""
    lines = [
        "# CardEventNet campaign report",
        "",
        f"- Campaign: `{campaign.campaign_id}`",
        f"- Recipe: `{recipe.recipe_id}` (`{recipe.digest}`)",
        f"- Dataset: `{recipe.data.dataset.id}` (`{recipe.data.dataset.digest}`)",
        f"- Validation split: `{recipe.data.split.id}` (`{recipe.data.split.digest}`)",
        f"- Recommendation: `{comparison.recommendation}`",
        "",
        "## Commands",
        "",
        "The campaign evaluates the champion and every candidate on the same validation split. "
        "No test command is part of M1.",
        "",
        "The exact commands and exit codes are recorded in `logs/commands.json`; complete output "
        "is kept beside each command log.",
        "",
        "## Candidate runs",
        "",
        "| Candidate | State | Checkpoint | Result |",
        "| --- | --- | --- | --- |",
    ]
    for run in campaign.candidate_runs:
        lines.append(
            f"| `{run.candidate_id}` | `{run.state}` | "
            f"`{run.checkpoint_id or 'none'}` | `{run.result_digest or 'none'}` |"
        )
    lines.extend(["", "## Validation comparison", "", render_comparison_report(comparison), ""])
    return "\n".join(lines)


def run_card_event_campaign(
    recipe_path: str | Path,
    *,
    repository_root: str | Path,
    registry_path: str | Path | None = None,
    campaign_root: str | Path | None = None,
    campaign_id: str | None = None,
    project_root: str | Path | None = None,
    config_path: str | Path | None = None,
    split_path: str | Path | None = None,
    cache_dir: str | Path | None = None,
    annotations_dir: str | Path | None = None,
    max_samples: int | None = None,
    device: str | None = None,
    precision: str | None = None,
    runner: CommandRunner | None = None,
    now_utc: str | None = None,
) -> ModelCampaign:
    """Run or resume one bounded CardEventNet validation campaign."""
    root = Path(repository_root).resolve()
    recipe_file = _resolve(root, recipe_path)
    recipe = load_model_recipe(recipe_file)
    if recipe.component != "card-event-net":
        raise CardEventCampaignError("CardEventNet campaign recipes must use card-event-net")
    profile = _load_profile(recipe)
    registry_file = _resolve(
        root, registry_path or root / "data" / "model-registry.json"
    )
    registry = load_model_registry(registry_file)
    champion = registry.champion_for(recipe.component, recipe.capability)
    if champion is None:
        raise CardEventCampaignError(
            f"model registry has no {recipe.component}/{recipe.capability} champion"
        )
    if champion.champion_bundle != recipe.baseline_bundle:
        raise CardEventCampaignError("recipe baseline bundle differs from the registry champion")
    campaigns = _resolve(root, campaign_root or root / "data" / "model-campaigns")
    selected_id = _campaign_id(recipe, campaign_id)
    campaign_dir = campaigns / selected_id
    campaign_file = campaign_dir / "campaign.json"
    resolved_recipe = campaign_dir / "resolved-recipe.yaml"
    command_runner = runner or SubprocessCommandRunner()
    timestamp = now_utc or _now()

    if campaign_file.exists():
        campaign = load_campaign(campaigns, selected_id)
        if campaign.recipe_digest != recipe.digest:
            raise CardEventCampaignError("existing campaign uses a different recipe digest")
        if campaign.state in {
            "candidate_locked",
            "tested",
            "promotion_recommended",
            "keep_champion_recommended",
            "human_review_required",
            "promoted",
        }:
            return campaign
    else:
        campaign = _create_campaign(recipe, selected_id, timestamp)
        _write_text(resolved_recipe, recipe_file.read_text(encoding="utf-8"))
        _write_campaign(campaign_file, campaign)

    campaign = _update(campaign, state="validated", timestamp=timestamp)
    _write_campaign(campaign_file, campaign)
    campaign = _update(campaign, state="running", timestamp=timestamp)
    _write_campaign(campaign_file, campaign)
    campaign_dir.joinpath("logs").mkdir(parents=True, exist_ok=True)
    campaign_dir.joinpath("candidates").mkdir(parents=True, exist_ok=True)
    command_manifest = campaign_dir / "logs" / "commands.json"

    project = _resolve(root, project_root or root / "card_event_net")
    default_config = _resolve(root, config_path or project / "configs" / "base.yaml")
    default_split = _resolve(root, split_path or project / "data" / "splits" / "default.yaml")
    default_cache = _resolve(root, cache_dir or project / "data" / "cache")
    default_annotations = _resolve(root, annotations_dir or project / "data" / "annotations")
    champion_evaluation_file = campaign_dir / "champion-evaluation.json"
    champion_evaluation: ModelEvaluation
    champion_payload: dict[str, object]
    champion_checkpoint = _resolve(root, champion.bundle_path)
    if champion_evaluation_file.exists():
        champion_payload = _read_json(champion_evaluation_file, "champion evaluation")
        champion_evaluation = ModelEvaluation.from_mapping(champion_payload)
    else:
        champion_evaluation_output = campaign_dir / "champion-cardevent-evaluation.json"
        champion_command = _evaluation_command(
            champion_checkpoint,
            project_root=project,
            split=default_split,
            cache_dir=default_cache,
            annotations_dir=default_annotations,
            output_path=champion_evaluation_output,
            device=device,
        )
        try:
            _run_checked(
                command_runner,
                champion_command,
                root=root,
                log_path=campaign_dir / "logs" / "champion-evaluate.log",
                manifest_path=command_manifest,
            )
            raw = _read_json(champion_evaluation_output, "CardEventNet champion evaluation")
            champion_payload = {
                "evaluation_id": f"evaluation-{selected_id}-champion",
                "role": "champion",
                "candidate_id": None,
                "run_id": f"run-{selected_id}-champion",
                "bundle": champion.champion_bundle.to_mapping(),
                "state": "success",
                "data": recipe.data.to_mapping(),
                "metrics": _metrics_from_evaluation(raw, champion_checkpoint),
                "gates": [],
                "failure_reason": None,
            }
            champion_evaluation = ModelEvaluation.from_mapping(champion_payload)
            _write_json(champion_evaluation_file, champion_payload)
            _write_json(
                campaign_dir / "champion-run.json",
                {
                    "run_id": f"run-{selected_id}-champion",
                    "recipe_digest": recipe.digest,
                    "data": recipe.data.to_mapping(),
                    "validation_partition": "val",
                },
            )
        except (CardEventCampaignError, OSError, ModelImprovementError) as error:
            campaign = _update(
                campaign,
                state="failed",
                timestamp=timestamp,
                failure_reason=f"champion evaluation failed: {error}",
            )
            _write_campaign(campaign_file, campaign)
            raise

    evaluations: dict[str, ModelEvaluation] = {}
    evaluation_payloads: dict[str, Mapping[str, object]] = {}
    existing_runs = {item.candidate_id: item for item in campaign.candidate_runs}
    failure_count = sum(item.state == "failed" for item in campaign.candidate_runs)
    started = time.monotonic()
    remaining_candidates = sorted(recipe.candidates, key=lambda item: item.candidate_id)
    for candidate in remaining_candidates:
        previous_run = existing_runs.get(candidate.candidate_id)
        candidate_dir = campaign_dir / "candidates" / candidate.candidate_id
        evaluation_file = candidate_dir / "evaluation.json"
        if (
            previous_run is not None
            and previous_run.state == "success"
            and evaluation_file.exists()
        ):
            evaluations[candidate.candidate_id] = ModelEvaluation.from_mapping(
                _read_json(evaluation_file, "candidate evaluation")
            )
            evaluation_payloads[candidate.candidate_id] = _read_json(
                candidate_dir / "cardevent-evaluation.json", "CardEventNet candidate evaluation"
            )
            continue
        if previous_run is not None and previous_run.state in {"failed", "skipped"}:
            evaluations[candidate.candidate_id] = ModelEvaluation.from_mapping(
                _read_json(evaluation_file, "candidate evaluation")
            )
            continue
        if (
            failure_count > 0 and failure_count >= recipe.budget.max_failures
            or time.monotonic() - started >= recipe.budget.max_compute_minutes * 60
        ):
            reason = (
                "failure budget exhausted"
                if failure_count > 0 and failure_count >= recipe.budget.max_failures
                else "compute budget exhausted"
            )
            evaluation = _failure_evaluation(
                campaign_id=selected_id,
                candidate_id=candidate.candidate_id,
                data=recipe.data,
                state="skipped",
                reason=reason,
            )
            run = CandidateRunReference.from_mapping(
                {
                    "candidate_id": candidate.candidate_id,
                    "run_id": evaluation.run_id,
                    "state": "skipped",
                    "run_digest": _candidate_run_digest(recipe, candidate),
                    "checkpoint_id": None,
                    "result_digest": None,
                    "failure_reason": reason,
                }
            )
            _write_json(evaluation_file, evaluation.to_mapping())
            evaluations[candidate.candidate_id] = evaluation
            campaign = _update(
                campaign,
                state="running",
                timestamp=timestamp,
                candidate_runs=tuple((*campaign.candidate_runs, run)),
            )
            _write_campaign(campaign_file, campaign)
            continue
        configuration = _candidate_configuration(candidate)
        run_dir = campaign_dir / "runs" / candidate.candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        hard_negative_manifest: Path | None = None
        try:
            _write_json(
                run_dir / "model-improvement.json",
                {
                    "campaign_id": selected_id,
                    "candidate_id": candidate.candidate_id,
                    "experiment_family": candidate.experiment_family,
                    "recipe_digest": recipe.digest,
                    "data": recipe.data.to_mapping(),
                    "seed": _seed_from_configuration(configuration, recipe.seeds[0]),
                },
            )
            for shared_key, shared_path in (
                ("split_path", default_split),
                ("cache_dir", default_cache),
                ("annotations_dir", default_annotations),
            ):
                if shared_key in configuration:
                    configured_path = _path_from_configuration(
                        configuration, shared_key, shared_path, root
                    )
                    if configured_path != shared_path:
                        raise CardEventCampaignError(
                            f"candidate {candidate.candidate_id} cannot change shared {shared_key}"
                        )
            if _bool_from_configuration(configuration, "mine_hard_negatives"):
                hard_negative_manifest = candidate_dir / "hard-negatives.json"
                mine_command = (
                    *_command_prefix(project),
                    "mine-hard-negatives",
                    "--checkpoint",
                    str(champion_checkpoint),
                    "--split",
                    str(_path_from_configuration(configuration, "split_path", default_split, root)),
                    "--out",
                    str(hard_negative_manifest),
                    "--cache-dir",
                    str(_path_from_configuration(configuration, "cache_dir", default_cache, root)),
                    "--annotations-dir",
                    str(
                        _path_from_configuration(
                            configuration, "annotations_dir", default_annotations, root
                        )
                    ),
                )
                _run_checked(
                    command_runner,
                    mine_command,
                    root=root,
                    log_path=candidate_dir / "hard-negative.log",
                    manifest_path=command_manifest,
                )
            elif "hard_negative_manifest" in configuration:
                hard_negative_manifest = _path_from_configuration(
                    configuration,
                    "hard_negative_manifest",
                    candidate_dir / "hard-negatives.json",
                    root,
                )
            train_command = _candidate_command_options(
                configuration,
                root=root,
                project_root=project,
                default_config=default_config,
                default_split=default_split,
                default_cache=default_cache,
                default_annotations=default_annotations,
                output_dir=run_dir.parent,
                run_name=run_dir.name,
                hard_negative_manifest=hard_negative_manifest,
                max_samples=max_samples,
                device=device,
                precision=precision,
                seed=_seed_from_configuration(configuration, recipe.seeds[0]),
            )
            _run_checked(
                command_runner,
                train_command,
                root=root,
                log_path=candidate_dir / "train.log",
                manifest_path=command_manifest,
            )
            checkpoint = run_dir / "best.pt"
            if not checkpoint.is_file():
                raise CardEventCampaignError(f"training did not write checkpoint {checkpoint}")
            selected_split = _path_from_configuration(
                configuration, "split_path", default_split, root
            )
            selected_cache = _path_from_configuration(
                configuration, "cache_dir", default_cache, root
            )
            selected_annotations = _path_from_configuration(
                configuration, "annotations_dir", default_annotations, root
            )
            selected_device = _string_from_configuration(configuration, "device", device)
            raw_evaluation_path = candidate_dir / "cardevent-evaluation.json"
            _run_checked(
                command_runner,
                _evaluation_command(
                    checkpoint,
                    project_root=project,
                    split=selected_split,
                    cache_dir=selected_cache,
                    annotations_dir=selected_annotations,
                    output_path=raw_evaluation_path,
                    device=selected_device,
                    threshold=_threshold_from_configuration(configuration),
                ),
                    root=root,
                    log_path=candidate_dir / "evaluate.log",
                    manifest_path=command_manifest,
                )
            raw = _read_json(raw_evaluation_path, "CardEventNet candidate evaluation")
            _run_checked(
                command_runner,
                _diagnose_command(
                    checkpoint,
                    split=selected_split,
                    cache_dir=selected_cache,
                    annotations_dir=selected_annotations,
                    output_path=candidate_dir / "diagnostics.json",
                    device=selected_device,
                    project_root=project,
                ),
                    root=root,
                    log_path=candidate_dir / "diagnose.log",
                manifest_path=command_manifest,
            )
            if _bool_from_configuration(configuration, "export_coreml"):
                export_path = candidate_dir / "CardEventNet.mlpackage"
                _run_checked(
                    command_runner,
                    (
                        *_command_prefix(project),
                        "export-coreml",
                        "--checkpoint",
                        str(checkpoint),
                        "--out",
                        str(export_path),
                    ),
                    root=root,
                    log_path=candidate_dir / "export-coreml.log",
                    manifest_path=command_manifest,
                )
                model_metrics = raw.get("model_metrics", {})
                normalized_metrics = (
                    dict(model_metrics) if isinstance(model_metrics, Mapping) else {}
                )
                normalized_metrics["coreml_export"] = True
                raw["model_metrics"] = normalized_metrics
                _write_json(raw_evaluation_path, raw)
            bundle = ArtifactReference(
                f"bundle-{selected_id}-{candidate.candidate_id}", _file_digest(checkpoint)
            )
            evaluation = _evaluation(
                evaluation_id=f"evaluation-{selected_id}-{candidate.candidate_id}",
                role="candidate",
                candidate_id=candidate.candidate_id,
                run_id=f"run-{selected_id}-{candidate.candidate_id}",
                bundle=bundle,
                state="success",
                data=recipe.data,
                metrics=_metrics_from_evaluation(raw, checkpoint),
            )
            run = CandidateRunReference.from_mapping(
                {
                    "candidate_id": candidate.candidate_id,
                    "run_id": evaluation.run_id,
                    "state": "success",
                    "run_digest": _candidate_run_digest(recipe, candidate),
                    "checkpoint_id": f"checkpoint-{selected_id}-{candidate.candidate_id}",
                    "result_digest": sha256_mapping(evaluation.to_mapping()),
                    "failure_reason": None,
                }
            )
            _write_json(evaluation_file, evaluation.to_mapping())
            evaluations[candidate.candidate_id] = evaluation
            evaluation_payloads[candidate.candidate_id] = raw
        except (CardEventCampaignError, OSError, ModelImprovementError) as error:
            failure_count += 1
            reason = str(error)
            evaluation = _failure_evaluation(
                campaign_id=selected_id,
                candidate_id=candidate.candidate_id,
                data=recipe.data,
                state="failed",
                reason=reason,
            )
            run = CandidateRunReference.from_mapping(
                {
                    "candidate_id": candidate.candidate_id,
                    "run_id": evaluation.run_id,
                    "state": "failed",
                    "run_digest": _candidate_run_digest(recipe, candidate),
                    "checkpoint_id": None,
                    "result_digest": None,
                    "failure_reason": reason,
                }
            )
            _write_json(evaluation_file, evaluation.to_mapping())
            evaluations[candidate.candidate_id] = evaluation
        campaign = _update(
            campaign,
            state="running",
            timestamp=timestamp,
            candidate_runs=tuple(
                (
                    *[
                        item
                        for item in campaign.candidate_runs
                        if item.candidate_id != candidate.candidate_id
                    ],
                    run,
                )
            ),
        )
        _write_campaign(campaign_file, campaign)

    candidates = [evaluations[item.candidate_id] for item in remaining_candidates]
    comparison = compare_evaluations(
        campaign_id=selected_id,
        component=recipe.component,
        capability=recipe.capability,
        task=recipe.task,
        recipe_digest=recipe.digest,
        data=recipe.data,
        champion=champion_evaluation,
        candidates=candidates,
        profile=profile,
        generated_at_utc=timestamp,
    )
    comparison_file = campaign_dir / "comparison.json"
    _write_json(comparison_file, comparison.to_mapping())
    recommendation_state = {
        "promote_candidate": "candidate_locked",
        "keep_champion": "keep_champion_recommended",
        "human_review_required": "human_review_required",
        "no_valid_candidate": "compared",
    }[comparison.recommendation]
    lock_id = None
    if comparison.recommendation == "promote_candidate":
        candidate = next(
            item
            for item in recipe.candidates
            if item.candidate_id == comparison.recommended_candidate_id
        )
        run = next(
            item
            for item in campaign.candidate_runs
            if item.candidate_id == candidate.candidate_id
        )
        evaluation = evaluations[candidate.candidate_id]
        lock = _candidate_lock(
            campaign,
            recipe,
            candidate,
            evaluation,
            evaluation_payloads[candidate.candidate_id],
            run.checkpoint_id or "",
            root,
            timestamp,
        )
        lock_id = lock.lock_id
        _write_json(campaign_dir / "lock.json", lock.to_mapping())
    campaign = _update(
        campaign,
        state=recommendation_state,
        timestamp=timestamp,
        comparison_id=comparison.comparison_id,
        lock_id=lock_id,
        recommendation=comparison.recommendation,
    )
    _write_campaign(campaign_file, campaign)
    _write_text(
        campaign_dir / "report.md",
        render_card_event_campaign_report(campaign, comparison, recipe=recipe),
    )
    validate_campaign_against_registry(campaign, registry)
    return campaign


__all__ = [
    "CardEventCampaignError",
    "CommandResult",
    "CommandRunner",
    "FixtureCommandRunner",
    "SubprocessCommandRunner",
    "render_card_event_campaign_report",
    "run_card_event_campaign",
]
