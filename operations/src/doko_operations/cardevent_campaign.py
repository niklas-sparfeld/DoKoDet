"""Resumable CardEventNet campaign execution for model-improvement operations."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import shutil
import subprocess
import tempfile
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
    ChampionModel,
    DataContext,
    ExportContract,
    ModelCampaign,
    ModelComparison,
    ModelEvaluation,
    ModelImprovementError,
    ModelRecipe,
    ModelRegistry,
    PromotionReceipt,
    compare_evaluations,
    default_gate_profile,
    evaluate_gates,
    load_campaign,
    load_campaign_comparison,
    load_candidate_lock,
    load_model_recipe,
    load_model_registry,
    load_promotion_receipt,
    render_comparison_report,
    sha256_mapping,
    validate_campaign_against_registry,
)


class CardEventCampaignError(ModelImprovementError):
    """Raised when a CardEventNet campaign cannot be completed."""


class CardEventPromotionError(CardEventCampaignError):
    """Raised when a locked CardEventNet candidate cannot be promoted."""


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

    def __init__(
        self,
        *,
        test_quality: float | None = None,
        fail_commands: Sequence[str] = (),
    ) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.test_quality = test_quality
        self.fail_commands = frozenset(fail_commands)

    def run(
        self, command: Sequence[str], *, cwd: Path, log_path: Path
    ) -> CommandResult:
        del cwd
        command = tuple(str(item) for item in command)
        self.commands.append(command)
        command_name = next((item for item in command if item in {
            "train",
            "evaluate",
            "diagnose",
            "export-coreml",
            "mine-hard-negatives",
        }), None)
        if command_name in self.fail_commands:
            _write_text(log_path, f"command: {shlex.join(command)}\nreturncode: 1\n")
            return CommandResult(1, "", f"fixture {command_name} failed")
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
            partition = _option(command, "--partition")
            quality = (
                self.test_quality
                if partition == "test" and self.test_quality is not None
                else 0.93 if is_candidate else 0.90
            )
            _write_json(output_path, _fixture_evaluation(quality=quality, partition=partition))
        elif "diagnose" in command:
            _write_json(Path(_option(command, "--out")), {"method": "fixture-diagnostics-v1"})
        elif "export-coreml" in command:
            _write_text(Path(_option(command, "--out")), "fixture-coreml-bundle\n")
            return CommandResult(0, "Parity check passed (max absolute error: 0)\n", "")
        elif "mine-hard-negatives" in command:
            _write_json(
                Path(_option(command, "--out")),
                {"format": "cardevent-hard-negatives-v1", "hard_negative_count": 0},
            )
        return CommandResult(0)


def _fixture_evaluation(*, quality: float, partition: str = "val") -> dict[str, object]:
    return {
        "method": "cardeventnet-fixture",
        "partition": partition,
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


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Replace one file after the complete new contents are durable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    else:
        raise CardEventPromotionError(f"Cannot copy missing app bundle {source}")


@dataclass(slots=True)
class _AppBundleSwap:
    target: Path
    staging_parent: Path
    backup: Path | None
    active: bool = True

    def rollback(self) -> None:
        if not self.active:
            return
        try:
            if self.target.exists() or self.target.is_symlink():
                _remove_path(self.target)
            if self.backup is not None and self.backup.exists():
                os.replace(self.backup, self.target)
        finally:
            shutil.rmtree(self.staging_parent, ignore_errors=True)
            self.active = False

    def finalize(self) -> None:
        if not self.active:
            return
        shutil.rmtree(self.staging_parent, ignore_errors=True)
        self.active = False


def _replace_app_bundle(source: Path, target: Path) -> _AppBundleSwap:
    """Stage a bundle beside its destination and publish it with a rollback handle."""
    if not source.exists():
        raise CardEventPromotionError(f"Core ML export did not write {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_dir() != source.is_dir():
        raise CardEventPromotionError(
            f"app bundle kind differs between export {source} and destination {target}"
        )
    staging_parent = Path(
        tempfile.mkdtemp(prefix=f".doko-promotion-{target.name}-", dir=target.parent)
    )
    staged = staging_parent / target.name
    backup: Path | None = None
    try:
        _copy_path(source, staged)
        if target.exists() or target.is_symlink():
            backup = staging_parent / "previous"
            os.replace(target, backup)
        os.replace(staged, target)
    except (OSError, shutil.Error) as error:
        if backup is not None and backup.exists() and not target.exists():
            os.replace(backup, target)
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise CardEventPromotionError(f"Could not update app bundle {target}: {error}") from error
    return _AppBundleSwap(target, staging_parent, backup)


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, UnicodeError) as error:
        raise CardEventCampaignError(f"Could not hash artifact {path}: {error}") from error


def _path_digest(path: Path) -> str:
    """Hash one file or a directory bundle by path and file content."""
    if path.is_file():
        return _file_digest(path)
    if not path.is_dir():
        raise CardEventPromotionError(f"Could not hash missing artifact {path}")
    files: list[dict[str, str]] = []
    try:
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            files.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "digest": _file_digest(child),
                }
            )
    except OSError as error:
        raise CardEventPromotionError(f"Could not hash artifact {path}: {error}") from error
    return sha256_mapping({"files": files})


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
    partition: str,
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
        partition,
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
) -> CommandResult:
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
    return result


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
            partition="val",
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
                    partition="val",
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


def _root_relative_path(root: Path, path: Path, field: str) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise CardEventPromotionError(f"{field} must be inside the repository root") from error


def _runtime_load_check(bundle: Path) -> dict[str, object]:
    if bundle.is_file():
        if not bundle.read_bytes():
            raise CardEventPromotionError("Core ML export is empty")
        return {"status": "passed", "method": "fixture-file-load"}
    manifest = bundle / "Manifest.json"
    model = bundle / "Data" / "com.apple.CoreML" / "model.mlmodel"
    if not manifest.is_file() or not model.is_file():
        raise CardEventPromotionError(
            "Core ML package is missing its manifest or model specification"
        )
    try:
        import coremltools as ct

        ct.models.MLModel(str(bundle))
    except ImportError as error:
        raise CardEventPromotionError(
            "Core ML runtime load requires coremltools on the promotion host"
        ) from error
    except Exception as error:
        raise CardEventPromotionError(f"Core ML runtime load failed: {error}") from error
    return {"status": "passed", "method": "coremltools.MLModel"}


def _ios_fixture_check(root: Path, *, fixture_backend: bool) -> dict[str, object]:
    fixture = root / "ios" / "CardEventProbeTests" / "Fixtures" / "full_frame_letterbox_v1.json"
    if not fixture.exists():
        if fixture_backend:
            return {"status": "passed", "method": "fixture-backend-contract"}
        raise CardEventPromotionError(f"iOS preprocessing fixture is missing: {fixture}")
    payload = _read_json(fixture, "iOS preprocessing fixture")
    expected = {
        "name": "full_frame_letterbox_v1",
        "pixel_format": "BGRA",
        "orientation": "up",
        "target_size": 224,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise CardEventPromotionError(
            "iOS preprocessing fixture does not match the model input contract"
        )
    python_reference = payload.get("python_reference")
    if not isinstance(python_reference, Mapping) or python_reference.get("tensor_layout") != (
        "[1, 8, 3, 224, 224]"
    ):
        raise CardEventPromotionError("iOS preprocessing fixture has an incompatible tensor layout")
    return {"status": "passed", "method": "ios-full-frame-fixture", "fixture": str(fixture)}


def _write_promotion_report(
    campaign_dir: Path,
    campaign: ModelCampaign,
    *,
    test_evaluation: ModelEvaluation | None,
    checks: Mapping[str, object] | None,
    failure_reason: str | None = None,
) -> None:
    lines = [
        "# CardEventNet promotion report",
        "",
        f"- Campaign: `{campaign.campaign_id}`",
        f"- State: `{campaign.state}`",
        f"- Candidate: `{test_evaluation.candidate_id if test_evaluation else 'none'}`",
        f"- Test evaluation: `{test_evaluation.evaluation_id if test_evaluation else 'none'}`",
        "",
    ]
    if failure_reason is not None:
        lines.extend([f"- Failure: `{failure_reason}`", ""])
    if test_evaluation is not None:
        lines.extend(["## Sealed test gates", ""])
        for gate in test_evaluation.gates:
            lines.append(f"- `{gate.gate_id}`: `{gate.status}` — {gate.reason}")
        lines.append("")
    if checks:
        lines.extend(["## Export and runtime checks", ""])
        for name, result in checks.items():
            status = result.get("status", "unknown") if isinstance(result, Mapping) else "unknown"
            lines.append(f"- `{name}`: `{status}`")
        lines.append("")
    _write_text(campaign_dir / "promotion-report.md", "\n".join(lines))


def _promotion_receipt(
    *,
    campaign: ModelCampaign,
    recipe: ModelRecipe,
    candidate_id: str,
    previous_champion: ArtifactReference,
    promoted_bundle: ArtifactReference,
    export_artifact: ArtifactReference,
    test_evaluation_id: str,
    runtime_contract_version: str,
    input_contract_version: str,
    receipt_id: str,
    registry_before_digest: str,
    registry_after_digest: str | None,
    promotion_state: str,
    registry_update: str,
    occurred_at_utc: str,
    failure_reason: str | None,
) -> PromotionReceipt:
    return PromotionReceipt.from_mapping(
        {
            "schema_version": "model-promotion-receipt/v1",
            "receipt_id": receipt_id,
            "campaign_id": campaign.campaign_id,
            "component": campaign.component,
            "capability": campaign.capability,
            "candidate_id": candidate_id,
            "promoted_bundle": promoted_bundle.to_mapping(),
            "previous_champion": previous_champion.to_mapping(),
            "recipe_digest": recipe.digest,
            "data": recipe.data.to_mapping(),
            "sealed_test_evaluation_id": test_evaluation_id,
            "export_artifact": export_artifact.to_mapping(),
            "runtime_contract_version": runtime_contract_version,
            "input_contract_version": input_contract_version,
            "promotion_state": promotion_state,
            "registry_update": registry_update,
            "registry_before_digest": registry_before_digest,
            "registry_after_digest": registry_after_digest,
            "occurred_at_utc": occurred_at_utc,
            "failure_reason": failure_reason,
        }
    )


def promote_card_event_campaign(
    campaign_id: str,
    *,
    repository_root: str | Path,
    registry_path: str | Path | None = None,
    campaign_root: str | Path | None = None,
    candidate_id: str | None = None,
    project_root: str | Path | None = None,
    split_path: str | Path | None = None,
    cache_dir: str | Path | None = None,
    annotations_dir: str | Path | None = None,
    device: str | None = None,
    app_bundle_path: str | Path | None = None,
    runner: CommandRunner | None = None,
    confirm: bool = False,
    now_utc: str | None = None,
) -> ModelCampaign:
    """Test, validate, and promote one locked CardEventNet candidate."""
    if not confirm:
        raise CardEventPromotionError("promotion requires explicit confirmation")
    root = Path(repository_root).resolve()
    campaigns = _resolve(root, campaign_root or root / "data" / "model-campaigns")
    campaign = load_campaign(campaigns, campaign_id)
    campaign_dir = campaigns / campaign.campaign_id
    receipt_path = campaign_dir / "promotion-receipt.json"
    if receipt_path.exists():
        receipt = load_promotion_receipt(receipt_path)
        if receipt.campaign_id != campaign.campaign_id:
            raise CardEventPromotionError("promotion receipt belongs to a different campaign")
        return campaign
    if campaign.state in {"promoted", "failed", "human_review_required"}:
        return campaign
    if campaign.state not in {"candidate_locked", "tested", "promotion_recommended"}:
        raise CardEventPromotionError(
            f"campaign {campaign.campaign_id} is not ready for promotion: {campaign.state}"
        )

    recipe = load_model_recipe(campaign_dir / "resolved-recipe.yaml")
    if not recipe.sealed_test_authorized:
        raise CardEventPromotionError("recipe does not authorize a sealed test evaluation")
    if recipe.component != "card-event-net":
        raise CardEventPromotionError("only CardEventNet campaigns have an M2 promotion path")
    if recipe.digest != campaign.recipe_digest:
        raise CardEventPromotionError("resolved recipe digest differs from the campaign")
    profile = _load_profile(recipe)
    registry_file = _resolve(root, registry_path or root / "data" / "model-registry.json")
    registry = load_model_registry(registry_file)
    validate_campaign_against_registry(campaign, registry)
    champion = registry.champion_for(campaign.component, campaign.capability)
    if champion is None:
        raise CardEventPromotionError("model registry has no current CardEventNet champion")
    if campaign.baseline_bundle != champion.champion_bundle:
        raise CardEventPromotionError("campaign baseline is no longer the current champion")
    comparison = load_campaign_comparison(campaigns, campaign)
    if comparison.recommendation != "promote_candidate":
        raise CardEventPromotionError(
            f"campaign recommendation is {comparison.recommendation}, not promote_candidate"
        )
    selected_candidate = candidate_id or comparison.recommended_candidate_id
    if selected_candidate != comparison.recommended_candidate_id:
        raise CardEventPromotionError("selected candidate differs from the locked recommendation")
    if selected_candidate is None:
        raise CardEventPromotionError("campaign has no recommended candidate")
    candidate = next(
        (item for item in recipe.candidates if item.candidate_id == selected_candidate), None
    )
    if candidate is None:
        raise CardEventPromotionError(f"candidate {selected_candidate} is not in the recipe")
    lock = load_candidate_lock(campaign_dir / "lock.json")
    if (
        lock.campaign_id != campaign.campaign_id
        or lock.candidate_id != selected_candidate
        or lock.recipe_digest != recipe.digest
        or lock.data != recipe.data
    ):
        raise CardEventPromotionError("candidate lock is stale or incompatible with the campaign")
    run = next(
        (item for item in campaign.candidate_runs if item.candidate_id == selected_candidate), None
    )
    if run is None or run.state != "success" or run.checkpoint_id != lock.checkpoint_id:
        raise CardEventPromotionError("candidate lock does not identify a completed checkpoint")
    candidate_evaluation = next(
        (item for item in comparison.candidates if item.candidate_id == selected_candidate), None
    )
    if candidate_evaluation is None or candidate_evaluation.state != "success":
        raise CardEventPromotionError("locked candidate has no successful validation evaluation")
    checkpoint = campaign_dir / "runs" / selected_candidate / "best.pt"
    if not checkpoint.is_file():
        raise CardEventPromotionError(f"locked checkpoint is missing: {checkpoint}")
    checkpoint_digest = _file_digest(checkpoint)
    if checkpoint_digest != candidate_evaluation.bundle.digest:
        raise CardEventPromotionError("locked checkpoint digest differs from validation evaluation")

    project = _resolve(root, project_root or root / "card_event_net")
    default_split = _resolve(root, split_path or project / "data" / "splits" / "default.yaml")
    default_cache = _resolve(root, cache_dir or project / "data" / "cache")
    default_annotations = _resolve(root, annotations_dir or project / "data" / "annotations")
    configuration = _candidate_configuration(candidate)
    selected_split = _path_from_configuration(configuration, "split_path", default_split, root)
    selected_cache = _path_from_configuration(configuration, "cache_dir", default_cache, root)
    selected_annotations = _path_from_configuration(
        configuration, "annotations_dir", default_annotations, root
    )
    selected_device = _string_from_configuration(configuration, "device", device)
    locked_threshold = lock.threshold_settings.get("threshold")
    if locked_threshold is not None and (
        isinstance(locked_threshold, bool)
        or not isinstance(locked_threshold, (int, float))
        or not math.isfinite(locked_threshold)
    ):
        raise CardEventPromotionError("candidate lock has an invalid threshold")

    command_runner = runner or SubprocessCommandRunner()
    command_manifest = campaign_dir / "logs" / "commands.json"
    timestamp = now_utc or _now()
    test_evaluation_file = campaign_dir / "test-evaluation.json"
    test_evaluation: ModelEvaluation | None = None
    checks: dict[str, object] = {}
    app_swap: _AppBundleSwap | None = None
    registry_before_bytes = registry_file.read_bytes()
    registry_before_digest = sha256_mapping(registry.to_mapping())
    registry_changed = False
    placeholder_export_digest = sha256_mapping(
        {
            "campaign_id": campaign.campaign_id,
            "candidate_id": selected_candidate,
            "artifact": "export",
        }
    )
    export_reference = ArtifactReference(
        f"export-{campaign.campaign_id}-{selected_candidate}", placeholder_export_digest
    )
    promoted_reference = ArtifactReference(
        f"bundle-{campaign.campaign_id}-{selected_candidate}-promoted", placeholder_export_digest
    )
    receipt_identity = {
        "campaign_id": campaign.campaign_id,
        "candidate_id": selected_candidate,
        "lock_id": lock.lock_id,
    }
    receipt_id = f"receipt-{sha256_mapping(receipt_identity)[:20]}"

    try:
        if test_evaluation_file.exists():
            test_evaluation = ModelEvaluation.from_mapping(
                _read_json(test_evaluation_file, "sealed test evaluation")
            )
        else:
            test_raw_output = campaign_dir / "test-cardevent-evaluation.json"
            test_command = _evaluation_command(
                checkpoint,
                project_root=project,
                split=selected_split,
                partition="test",
                cache_dir=selected_cache,
                annotations_dir=selected_annotations,
                output_path=test_raw_output,
                device=selected_device,
                threshold=float(locked_threshold) if locked_threshold is not None else None,
            )
            _run_checked(
                command_runner,
                test_command,
                root=root,
                log_path=campaign_dir / "logs" / "test-evaluate.log",
                manifest_path=command_manifest,
            )
            raw_test = _read_json(test_raw_output, "CardEventNet sealed test evaluation")
            test_evaluation = _evaluation(
                evaluation_id=f"evaluation-{campaign.campaign_id}-{selected_candidate}-test",
                role="candidate",
                candidate_id=selected_candidate,
                run_id=f"run-{campaign.campaign_id}-{selected_candidate}-test",
                bundle=candidate_evaluation.bundle,
                state="success",
                data=recipe.data,
                metrics={
                    **_metrics_from_evaluation(raw_test, checkpoint),
                    "evaluation_partition": "test",
                },
            )
            test_evaluation = replace(
                test_evaluation,
                gates=evaluate_gates(profile, test_evaluation.metrics),
            )
            _write_json(test_evaluation_file, test_evaluation.to_mapping())
        if (
            test_evaluation.role != "candidate"
            or test_evaluation.candidate_id != selected_candidate
        ):
            raise CardEventPromotionError(
                "sealed test evaluation identifies the wrong candidate"
            )
        if test_evaluation.data != recipe.data:
            raise CardEventPromotionError("sealed test evaluation uses the wrong data context")
        if test_evaluation.state != "success":
            raise CardEventPromotionError(
                test_evaluation.failure_reason or "sealed test evaluation failed"
            )
        if not test_evaluation.gates:
            test_evaluation = replace(
                test_evaluation, gates=evaluate_gates(profile, test_evaluation.metrics)
            )
            _write_json(test_evaluation_file, test_evaluation.to_mapping())
        campaign = _update(
            campaign,
            state="tested",
            timestamp=timestamp,
            test_evaluation_id=test_evaluation.evaluation_id,
        )
        _write_campaign(campaign_dir / "campaign.json", campaign)
        failed_gates = [
            gate.gate_id for gate in test_evaluation.gates if gate.hard and gate.status == "failed"
        ]
        if failed_gates:
            reason = f"sealed test hard gates failed: {', '.join(failed_gates)}"
            campaign = _update(
                campaign,
                state="human_review_required",
                timestamp=timestamp,
                failure_reason=reason,
            )
            _write_campaign(campaign_dir / "campaign.json", campaign)
            _write_promotion_report(
                campaign_dir,
                campaign,
                test_evaluation=test_evaluation,
                checks=None,
                failure_reason=reason,
            )
            return campaign

        export_path = campaign_dir / "candidates" / selected_candidate / "CardEventNet.mlpackage"
        export_result = _run_checked(
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
            log_path=campaign_dir / "logs" / "promotion-export-coreml.log",
            manifest_path=command_manifest,
        )
        if (
            not isinstance(command_runner, FixtureCommandRunner)
            and "Parity check passed" not in export_result.stdout
        ):
            raise CardEventPromotionError("Core ML export did not report a successful parity check")
        export_digest = _path_digest(export_path)
        export_reference = ArtifactReference(export_reference.id, export_digest)
        promoted_reference = ArtifactReference(promoted_reference.id, export_digest)
        checks["coreml_export_and_parity"] = {
            "status": "passed",
            "artifact": export_reference.to_mapping(),
            "parity": "passed",
        }
        _write_json(campaign_dir / "promotion-checks.json", checks)
        checks["runtime_load"] = _runtime_load_check(export_path)
        _write_json(campaign_dir / "promotion-checks.json", checks)
        checks["ios_fixture"] = _ios_fixture_check(
            root, fixture_backend=isinstance(command_runner, FixtureCommandRunner)
        )
        _write_json(campaign_dir / "promotion-checks.json", checks)

        target = _resolve(
            root,
            app_bundle_path
            or root / "ios" / "CardEventProbe" / "CardEventNetTransitionV2.mlpackage",
        )
        target_relative = _root_relative_path(root, target, "app bundle path")
        previous_copy = campaign_dir / "previous-champion-app-bundle"
        if target.exists() and not previous_copy.exists():
            _copy_path(target, previous_copy)
        _write_json(
            campaign_dir / "previous-champion.json",
            {
                "champion": champion.to_mapping(),
                "app_bundle_path": target_relative,
            },
        )
        app_swap = _replace_app_bundle(export_path, target)
        if _path_digest(target) != export_digest:
            raise CardEventPromotionError(
                "checked-in app bundle digest differs from Core ML export"
            )
        checks["app_bundle_update"] = {"status": "staged", "path": target_relative}
        _write_json(campaign_dir / "promotion-checks.json", checks)

        new_champion = ChampionModel(
            component=champion.component,
            capability=champion.capability,
            champion_bundle=promoted_reference,
            bundle_path=target_relative,
            runtime_contract_version=champion.runtime_contract_version,
            input_contract_version=champion.input_contract_version,
            data=recipe.data,
            validation_report_id=comparison.comparison_id,
            sealed_test_report_id=test_evaluation.evaluation_id,
            export=ExportContract(
                environment={
                    "tool": "cardevent",
                    "campaign_id": campaign.campaign_id,
                    "candidate_id": selected_candidate,
                },
                compatibility=recipe.export_compatibility,
            ),
            promotion_receipt_id=receipt_id,
            decision_note=(
                f"Promoted {selected_candidate} after explicit confirmation and sealed test "
                f"evaluation {test_evaluation.evaluation_id}."
            ),
        )
        new_registry = ModelRegistry(
            registry_version=registry.registry_version + 1,
            champions=tuple(
                new_champion
                if item.component == champion.component and item.capability == champion.capability
                else item
                for item in registry.champions
            ),
        )
        new_registry = ModelRegistry.from_mapping(new_registry.to_mapping())
        registry_after_digest = sha256_mapping(new_registry.to_mapping())
        _atomic_write_bytes(
            registry_file,
            json.dumps(
                new_registry.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
            + b"\n",
        )
        registry_changed = True
        if sha256_mapping(load_model_registry(registry_file).to_mapping()) != registry_after_digest:
            raise CardEventPromotionError("atomic registry update failed its digest check")
        checks["registry_update"] = {
            "status": "updated",
            "before_digest": registry_before_digest,
            "after_digest": registry_after_digest,
        }
        _write_json(campaign_dir / "promotion-checks.json", checks)
        receipt = _promotion_receipt(
            campaign=campaign,
            recipe=recipe,
            candidate_id=selected_candidate,
            previous_champion=champion.champion_bundle,
            promoted_bundle=promoted_reference,
            export_artifact=export_reference,
            test_evaluation_id=test_evaluation.evaluation_id,
            runtime_contract_version=champion.runtime_contract_version,
            input_contract_version=champion.input_contract_version,
            receipt_id=receipt_id,
            registry_before_digest=registry_before_digest,
            registry_after_digest=registry_after_digest,
            promotion_state="promoted",
            registry_update="updated",
            occurred_at_utc=timestamp,
            failure_reason=None,
        )
        _atomic_write_bytes(
            receipt_path,
            json.dumps(receipt.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n",
        )
        campaign = _update(
            campaign,
            state="promoted",
            timestamp=timestamp,
            test_evaluation_id=test_evaluation.evaluation_id,
            promotion_receipt_id=receipt.receipt_id,
            failure_reason=None,
        )
        _write_campaign(campaign_dir / "campaign.json", campaign)
        _write_promotion_report(
            campaign_dir, campaign, test_evaluation=test_evaluation, checks=checks
        )
        app_swap.finalize()
        return campaign
    except (
        CardEventCampaignError,
        ModelImprovementError,
        OSError,
        ValueError,
        shutil.Error,
    ) as error:
        compensation_errors: list[str] = []
        if registry_changed:
            try:
                _atomic_write_bytes(registry_file, registry_before_bytes)
            except (OSError, ValueError) as compensation_error:
                compensation_errors.append(f"registry restore failed: {compensation_error}")
        if app_swap is not None:
            try:
                app_swap.rollback()
            except (OSError, ValueError) as compensation_error:
                compensation_errors.append(f"app bundle restore failed: {compensation_error}")
        reason = str(error)
        if compensation_errors:
            reason = f"{reason}; {'; '.join(compensation_errors)}"
        if test_evaluation is None:
            test_evaluation = _evaluation(
                evaluation_id=f"evaluation-{campaign.campaign_id}-{selected_candidate}-test",
                role="candidate",
                candidate_id=selected_candidate,
                run_id=f"run-{campaign.campaign_id}-{selected_candidate}-test",
                bundle=candidate_evaluation.bundle,
                state="failed",
                data=recipe.data,
                metrics={},
                failure_reason=reason,
            )
        _write_json(test_evaluation_file, test_evaluation.to_mapping())
        failed_receipt = _promotion_receipt(
            campaign=campaign,
            recipe=recipe,
            candidate_id=selected_candidate,
            previous_champion=champion.champion_bundle,
            promoted_bundle=promoted_reference,
            export_artifact=export_reference,
            test_evaluation_id=test_evaluation.evaluation_id,
            runtime_contract_version=champion.runtime_contract_version,
            input_contract_version=champion.input_contract_version,
            receipt_id=receipt_id,
            registry_before_digest=registry_before_digest,
            registry_after_digest=None,
            promotion_state="failed",
            registry_update="unchanged",
            occurred_at_utc=timestamp,
            failure_reason=reason,
        )
        _atomic_write_bytes(
            receipt_path,
            json.dumps(
                failed_receipt.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
            + b"\n",
        )
        campaign = _update(
            campaign,
            state="failed",
            timestamp=timestamp,
            test_evaluation_id=test_evaluation.evaluation_id,
            promotion_receipt_id=failed_receipt.receipt_id,
            failure_reason=reason,
        )
        _write_campaign(campaign_dir / "campaign.json", campaign)
        _write_promotion_report(
            campaign_dir,
            campaign,
            test_evaluation=test_evaluation,
            checks=checks or None,
            failure_reason=reason,
        )
        raise CardEventPromotionError(reason) from error


__all__ = [
    "CardEventCampaignError",
    "CardEventPromotionError",
    "CommandResult",
    "CommandRunner",
    "FixtureCommandRunner",
    "SubprocessCommandRunner",
    "render_card_event_campaign_report",
    "promote_card_event_campaign",
    "run_card_event_campaign",
]
