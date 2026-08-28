"""Resumable TableEvidenceAnalyzer validation campaigns."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from table_evidence_analyzer.data import (
    DatasetEntry,
    DatasetManifest,
    MaterializedCropDataset,
    SplitManifest,
    assert_valid_dataset,
    load_artifact_index,
    load_dataset_manifest,
    load_split_manifest,
    materialize_crops,
)
from table_evidence_analyzer.export import BUNDLE_SCHEMA, load_bundle
from table_evidence_analyzer.table_observation import (
    ANALYZER_CAPABILITIES,
    OBSERVATION_SCHEMA_VERSION,
    TableObservation,
)

from .cardevent_campaign import (
    _campaign_id,
    _candidate_configuration,
    _candidate_lock,
    _candidate_run_digest,
    _create_campaign,
    _failure_evaluation,
    _seed_from_configuration,
    _string_from_configuration,
    _update,
)
from .model_improvement import (
    ArtifactReference,
    CandidateRunReference,
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


class TableEvidenceCampaignError(ModelImprovementError):
    """Raised when a TableEvidenceAnalyzer campaign cannot be completed."""


@dataclass(frozen=True, slots=True)
class TableEvidenceCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class TableEvidenceCommandRunner(Protocol):
    """Run one existing TableEvidenceAnalyzer command."""

    def run(
        self, command: Sequence[str], *, cwd: Path, log_path: Path
    ) -> TableEvidenceCommandResult: ...


class TableEvidenceSubprocessCommandRunner:
    """Execute analyzer commands and retain their complete output."""

    def run(
        self, command: Sequence[str], *, cwd: Path, log_path: Path
    ) -> TableEvidenceCommandResult:
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
            return TableEvidenceCommandResult(127, "", str(error))
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
        return TableEvidenceCommandResult(completed.returncode, completed.stdout, completed.stderr)


class TableEvidenceFixtureCommandRunner:
    """Create deterministic analyzer artifacts for local clean-room tests."""

    def __init__(
        self,
        *,
        champion_quality: float = 0.90,
        candidate_quality: float = 0.96,
        fail_commands: Sequence[str] = (),
    ) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.champion_quality = champion_quality
        self.candidate_quality = candidate_quality
        self.fail_commands = frozenset(fail_commands)

    def run(
        self, command: Sequence[str], *, cwd: Path, log_path: Path
    ) -> TableEvidenceCommandResult:
        del cwd
        command = tuple(str(item) for item in command)
        self.commands.append(command)
        command_name = next(
            (item for item in command if item in {"train", "evaluate", "export"}), None
        )
        if command_name in self.fail_commands:
            _write_text(log_path, f"command: {shlex.join(command)}\nreturncode: 1\n")
            return TableEvidenceCommandResult(1, "", f"fixture {command_name} failed")
        _write_text(log_path, f"command: {shlex.join(command)}\nreturncode: 0\n")
        if command_name == "train":
            config = _read_json(Path(_option(command, "--config")), "fixture training config")
            output = Path(str(config["output"]))
            output.mkdir(parents=True, exist_ok=True)
            run_name = output.name
            dataset = load_dataset_manifest(Path(str(config["dataset"])))
            split = load_split_manifest(Path(str(config["split"])))
            checkpoint = {
                "schema_version": "table-analyzer-checkpoint/v1",
                "candidate_id": run_name,
                "dataset_version_digest": dataset.digest,
                "split_version_digest": split.digest,
                "seed": config.get("seed", 17),
            }
            _write_json(output / "checkpoint-best.json", checkpoint)
            _write_json(output / "checkpoint-last.json", checkpoint)
            _write_json(
                output / "run.json",
                {
                    "schema_version": "table-analyzer-run/v1",
                    "run_id": f"run-{run_name}",
                    "status": "completed",
                    "config": config,
                    "dataset_version_digest": dataset.digest,
                    "split_version_digest": split.digest,
                    "model": {"adapter": "fixture", "classes": []},
                },
            )
        elif command_name == "evaluate":
            split_name = _option(command, "--split")
            if split_name != "validation":
                _write_text(
                    log_path,
                    f"command: {shlex.join(command)}\nreturncode: 2\n"
                    "fixture only permits validation evaluation\n",
                )
                return TableEvidenceCommandResult(
                    2, "", "fixture only permits validation evaluation"
                )
            run_dir = Path(_option(command, "--run"))
            run = _read_json(run_dir / "run.json", "fixture run")
            config = run.get("config")
            if not isinstance(config, Mapping):
                raise TableEvidenceCampaignError("fixture run has no configuration")
            dataset = load_dataset_manifest(Path(str(config["dataset"])))
            split = load_split_manifest(Path(str(config["split"])))
            is_champion = run_dir.name == "champion"
            quality = self.champion_quality if is_champion else self.candidate_quality
            predictions = _fixture_predictions(dataset, split, quality=quality)
            _write_json(
                run_dir / "evaluation-validation.json",
                {
                    "schema_version": "table-analyzer-evaluation/v1",
                    "run_id": run["run_id"],
                    "split": "validation",
                    "dataset_version_digest": dataset.digest,
                    "split_version_digest": split.digest,
                    "sample_count": len(predictions),
                    "top_1_accuracy": quality,
                    "predictions": predictions,
                    "metrics": {
                        "high_confidence_error_rate": 0.0,
                        "high_confidence_error_support": max(1, len(predictions)),
                        "unusable_sample_rate": 0.0,
                        "inference_latency_ms": 2.0,
                    },
                },
            )
        elif command_name == "export":
            run_dir = Path(_option(command, "--run"))
            output = Path(_option(command, "--output"))
            run = _read_json(run_dir / "run.json", "fixture run")
            model_path = output / "model.json"
            output.mkdir(parents=True, exist_ok=True)
            _write_json(
                model_path,
                {
                    "schema_version": "rgb-nearest-centroid-v1",
                    "centroids": {
                        "CLUBS_NINE": [30.0, 80.0, 120.0],
                        "HEARTS_QUEEN": [140.0, 60.0, 30.0],
                        "SPADES_JACK": [90.0, 40.0, 150.0],
                    },
                },
            )
            _write_json(
                output / "manifest.json",
                {
                    "schema_version": BUNDLE_SCHEMA,
                    "capabilities": ["identity_candidates"],
                    "calibration": "uncalibrated",
                    "card_set_version": "doko-german-suited-v1",
                    "run_id": run["run_id"],
                    "dataset_version_digest": run["dataset_version_digest"],
                    "split_version_digest": run["split_version_digest"],
                    "model_file": "model.json",
                    "model_sha256": _file_digest(model_path),
                },
            )
        return TableEvidenceCommandResult(0)


def _option(command: Sequence[str], name: str) -> str:
    try:
        return str(command[command.index(name) + 1])
    except (ValueError, IndexError) as error:
        raise TableEvidenceCampaignError(f"fixture command is missing {name}") from error


def _read_json(path: Path, context: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TableEvidenceCampaignError(f"Could not read {context} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise TableEvidenceCampaignError(f"{context} {path} must contain a JSON object.")
    return payload


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise TableEvidenceCampaignError(f"Could not hash artifact {path}: {error}") from error


def _path_digest(path: Path) -> str:
    if path.is_file():
        return _file_digest(path)
    if not path.is_dir():
        raise TableEvidenceCampaignError(f"Could not hash missing artifact {path}")
    files: list[dict[str, str]] = []
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        files.append(
            {
                "path": child.relative_to(path).as_posix(),
                "digest": _file_digest(child),
            }
        )
    return sha256_mapping({"files": files})


def _resolve(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _command_prefix(project_root: Path) -> tuple[str, ...]:
    return (
        "mise",
        "exec",
        "--",
        "uv",
        "run",
        "--project",
        str(project_root),
        "table-analyzer",
    )


def _run_checked(
    runner: TableEvidenceCommandRunner,
    command: Sequence[str],
    *,
    root: Path,
    log_path: Path,
    manifest_path: Path,
) -> TableEvidenceCommandResult:
    records: list[dict[str, object]] = []
    if manifest_path.exists():
        existing = _read_json(manifest_path, "command manifest")
        if existing.get("schema_version") != "model-campaign-commands/v1":
            raise TableEvidenceCampaignError("command manifest has an unsupported schema_version")
        value = existing.get("commands")
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise TableEvidenceCampaignError("command manifest commands must be objects")
        records = list(value)
    record: dict[str, object] = {
        "command": list(command),
        "log_path": str(log_path),
        "returncode": None,
    }
    records.append(record)
    _write_json(
        manifest_path,
        {"schema_version": "model-campaign-commands/v1", "commands": records},
    )
    result = runner.run(command, cwd=root, log_path=log_path)
    record["returncode"] = result.returncode
    _write_json(
        manifest_path,
        {"schema_version": "model-campaign-commands/v1", "commands": records},
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise TableEvidenceCampaignError(f"TableEvidenceAnalyzer command failed: {detail}")
    return result


def _configured_path(
    configuration: Mapping[str, object],
    key: str,
    override: str | Path | None,
    *,
    root: Path,
) -> Path:
    value: object = override if override is not None else configuration.get(key)
    if value is None:
        raise TableEvidenceCampaignError(
            f"table campaign requires an explicit {key}; directory scans are not supported"
        )
    if not isinstance(value, (str, Path)) or not str(value):
        raise TableEvidenceCampaignError(f"table campaign {key} must be a path")
    return _resolve(root, value)


def _validate_data_contract(
    recipe: ModelRecipe,
    configuration: Mapping[str, object],
    *,
    root: Path,
    dataset_path: str | Path | None,
    split_path: str | Path | None,
    artifacts_path: str | Path | None,
) -> tuple[DatasetManifest, SplitManifest, Path, Path, Path]:
    selected_dataset = _configured_path(configuration, "dataset_path", dataset_path, root=root)
    selected_split = _configured_path(configuration, "split_path", split_path, root=root)
    selected_artifacts = _configured_path(
        configuration, "artifacts_path", artifacts_path, root=root
    )
    try:
        dataset = load_dataset_manifest(selected_dataset)
        split = load_split_manifest(selected_split)
        artifacts = load_artifact_index(selected_artifacts)
        assert_valid_dataset(dataset, split=split, artifacts=artifacts)
    except (OSError, ValueError) as error:
        raise TableEvidenceCampaignError(f"invalid plan 0020 data artifacts: {error}") from error
    if dataset.task != "table_evidence_analyzer_identity_crop":
        raise TableEvidenceCampaignError("table campaign requires the plan 0020 identity-crop task")
    if (
        recipe.data.dataset.id != dataset.dataset_version_id
        or recipe.data.dataset.digest != dataset.digest
    ):
        raise TableEvidenceCampaignError(
            "recipe dataset version does not match the supplied manifest"
        )
    if recipe.data.split.id != split.split_version_id or recipe.data.split.digest != split.digest:
        raise TableEvidenceCampaignError(
            "recipe split version does not match the supplied manifest"
        )
    return dataset, split, selected_dataset, selected_split, selected_artifacts


def _group_value(entry: DatasetEntry, dataset: DatasetManifest, dimension: str) -> str | None:
    if dimension == "deck_design":
        return dataset.deck_design_version
    aliases = {
        "device": {"device", "device_class", "camera_device", "camera_device_class"},
        "table_setup": {"table_setup"},
        "visibility": {"visibility"},
        "glare": {"glare"},
        "blur": {"blur"},
        "perspective": {"perspective"},
        "occlusion": {"occlusion"},
    }
    names = aliases.get(dimension, {dimension})
    for name, value in entry.group_keys:
        if name in names:
            return value
    for tag in entry.quality_tags:
        for separator in (":", "="):
            prefix, separator_value, value = tag.partition(separator)
            if separator_value and prefix in names and value:
                return value
        if tag in names:
            return "present"
    return None


def _group_metrics(
    dataset: DatasetManifest,
    split: SplitManifest,
    predictions: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    dimensions = (
        "deck_design",
        "device",
        "table_setup",
        "visibility",
        "glare",
        "blur",
        "perspective",
        "occlusion",
    )
    entries = {
        entry.dataset_item_id: entry
        for entry in dataset.entries
        if entry.dataset_item_id in set(split.validation)
    }
    result: dict[str, object] = {}
    for dimension in dimensions:
        by_group: dict[str, list[bool]] = {}
        for item_id, entry in entries.items():
            prediction = predictions.get(item_id)
            value = _group_value(entry, dataset, dimension)
            if prediction is None or value is None:
                continue
            target = prediction.get("target")
            predicted = prediction.get("prediction")
            if isinstance(target, str) and isinstance(predicted, str):
                by_group.setdefault(value, []).append(target == predicted)
        groups = {
            value: {
                "support": len(values),
                "accuracy": sum(values) / len(values),
            }
            for value, values in sorted(by_group.items())
        }
        if groups:
            worst = min(groups.values(), key=lambda item: float(item["accuracy"]))
            result[dimension] = {
                "status": "supported",
                "support": min(int(item["support"]) for item in groups.values()),
                "groups": groups,
                "worst_accuracy": worst["accuracy"],
            }
        else:
            result[dimension] = {
                "status": "not_available",
                "support": 0,
                "groups": {},
                "reason": "no validation samples declare this group dimension",
            }
    return result


def _observation_fixture(
    bundle_path: Path,
    *,
    dataset: DatasetManifest,
    split: SplitManifest,
    artifacts_path: Path,
    cache_path: Path,
) -> tuple[bool, float]:
    started = time.perf_counter()
    bundle = load_bundle(bundle_path)
    artifacts = load_artifact_index(artifacts_path)
    cache = materialize_crops(dataset, split, artifacts, cache_path)
    samples = list(MaterializedCropDataset(cache, partition="validation"))
    cards: list[dict[str, object]] = []
    if samples:
        crop = next(
            item for item in cache.crops if item.dataset_item_id == samples[0].dataset_item_id
        )
        candidates = bundle.classify(cache.root / crop.relative_path)
        cards.append(
            {
                "observed_card_id": "fixture-observed-card",
                "identity_candidates": [
                    candidate.model_dump(mode="json") for candidate in candidates
                ],
            }
        )
    try:
        TableObservation.model_validate(
            {
                "schema_version": OBSERVATION_SCHEMA_VERSION,
                "observation_id": "fixture-observation",
                "source": {"package_id": "fixture-package"},
                "session": {"session_id": "fixture-session", "event_sequence": 1},
                "observed_at_ms": 0,
                "status": "observed" if cards else "insufficient_evidence",
                "capabilities": ["identity_candidates"],
                "cards": cards,
                "calibration": bundle.manifest["calibration"],
                "analyzer": {"name": "table-evidence-analyzer", "version": "bundle-v1"},
                "diagnostics": {},
            }
        )
    except (KeyError, TypeError, ValueError):
        return False, (time.perf_counter() - started) * 1000.0
    return True, (time.perf_counter() - started) * 1000.0


def _validate_bundle(
    bundle_path: Path,
    *,
    component: str,
    capability: str,
    runtime_contract_version: str,
    input_contract_version: str,
    dataset: DatasetManifest,
    split: SplitManifest,
) -> dict[str, object]:
    try:
        bundle = load_bundle(bundle_path)
    except (OSError, TypeError, ValueError) as error:
        raise TableEvidenceCampaignError(f"invalid analyzer capability bundle: {error}") from error
    manifest = bundle.manifest
    if manifest.get("dataset_version_digest") != dataset.digest:
        raise TableEvidenceCampaignError("capability bundle uses a different dataset digest")
    if manifest.get("split_version_digest") != split.digest:
        raise TableEvidenceCampaignError("capability bundle uses a different split digest")
    if manifest.get("capabilities") != ["identity_candidates"]:
        raise TableEvidenceCampaignError(
            "analyzer bundle must declare only the identity_candidates capability"
        )
    contract = {
        "schema_version": "table-analyzer-capability-contract/v1",
        "component": component,
        "capability": capability,
        "bundle_schema": BUNDLE_SCHEMA,
        "output_schema": OBSERVATION_SCHEMA_VERSION,
        "declared_capabilities": ["identity_candidates"],
        "not_provided_capabilities": [
            item for item in ANALYZER_CAPABILITIES if item != "identity_candidates"
        ],
        "scope": "oracle_crop_identity_only",
        "complete_table_analysis": False,
        "runtime_contract_version": runtime_contract_version,
        "input_contract_version": input_contract_version,
    }
    return {"bundle": bundle, "contract": contract}


def _evaluation_metrics(
    payload: Mapping[str, object],
    *,
    dataset: DatasetManifest,
    split: SplitManifest,
    artifact_path: Path,
    checkpoint_path: Path,
    capability: Mapping[str, object],
    observation_fixture_compatible: bool,
    inference_latency_ms: float,
) -> dict[str, object]:
    raw_predictions = payload.get("predictions", [])
    predictions = (
        {
            str(item["sample_id"]): item
            for item in raw_predictions
            if isinstance(item, Mapping) and isinstance(item.get("sample_id"), str)
        }
        if isinstance(raw_predictions, list)
        else {}
    )
    validation_entries = [
        entry for entry in dataset.entries if entry.dataset_item_id in set(split.validation)
    ]
    top1 = payload.get("top_1_accuracy")
    if not isinstance(top1, (int, float)) or isinstance(top1, bool):
        matches = [
            item.get("target") == item.get("prediction")
            for item in predictions.values()
            if isinstance(item.get("target"), str) and isinstance(item.get("prediction"), str)
        ]
        top1 = sum(matches) / len(matches) if matches else 0.0
    topk_matches = [
        item.get("target") in item.get("top_k", [])
        for item in predictions.values()
        if isinstance(item.get("target"), str) and isinstance(item.get("top_k"), list)
    ]
    topk = sum(topk_matches) / len(topk_matches) if topk_matches else float(top1)
    by_identity: dict[str, list[bool]] = {}
    for item in predictions.values():
        target = item.get("target")
        predicted = item.get("prediction")
        if isinstance(target, str) and isinstance(predicted, str):
            by_identity.setdefault(target, []).append(target == predicted)
    identity_metrics = {
        identity: {
            "support": len(values),
            "accuracy": sum(values) / len(values),
        }
        for identity, values in sorted(by_identity.items())
    }
    metrics: dict[str, object] = {
        "top1_accuracy": float(top1),
        "topk_accuracy": float(topk),
        "sample_count": len(validation_entries),
        "prediction_count": len(predictions),
        "per_identity": identity_metrics,
        "per_identity_support": min(
            (int(item["support"]) for item in identity_metrics.values()), default=0
        ),
        "per_identity_min_accuracy": min(
            (float(item["accuracy"]) for item in identity_metrics.values()), default=0.0
        ),
        "group_metrics": _group_metrics(dataset, split, predictions),
        "bundle_integrity": True,
        "runtime_loads": True,
        "observation_fixture_compatible": observation_fixture_compatible,
        "inference_latency_ms": inference_latency_ms,
        "capability_contract": dict(capability),
    }
    groups = metrics["group_metrics"]
    assert isinstance(groups, Mapping)
    gate_names = {
        "deck_design": "worst_deck_design",
        "device": "worst_device",
        "table_setup": "worst_table_setup",
        "visibility": "worst_visibility",
        "glare": "worst_glare",
        "blur": "worst_blur",
        "perspective": "worst_perspective",
        "occlusion": "worst_occlusion",
    }
    for dimension, prefix in gate_names.items():
        group = groups[dimension]
        assert isinstance(group, Mapping)
        metrics[f"{prefix}_support"] = int(group.get("support", 0))
        if group.get("status") == "supported":
            metrics[f"{prefix}_accuracy"] = float(group["worst_accuracy"])
    raw_metrics = payload.get("metrics")
    if isinstance(raw_metrics, Mapping):
        metrics.update(raw_metrics)
    model_size = (
        checkpoint_path.stat().st_size / (1024 * 1024) if checkpoint_path.is_file() else 0.0
    )
    metrics.setdefault("model_size_mb", model_size)
    metrics.setdefault("unusable_sample_rate", 0.0)
    metrics["bundle_artifact"] = {
        "path": str(artifact_path),
        "digest": _path_digest(artifact_path),
    }
    return metrics


def _fixture_predictions(
    dataset: DatasetManifest, split: SplitManifest, *, quality: float
) -> list[dict[str, object]]:
    identities = ["CLUBS_NINE", "HEARTS_QUEEN", "SPADES_JACK"]
    result: list[dict[str, object]] = []
    for index, item_id in enumerate(split.validation):
        entry = next(item for item in dataset.entries if item.dataset_item_id == item_id)
        correct = quality >= 0.95 or index > 0
        prediction = entry.visual_card_identity if correct else identities[0]
        top_k = [prediction, *[item for item in identities if item != prediction]]
        result.append(
            {
                "sample_id": item_id,
                "target": entry.visual_card_identity,
                "prediction": prediction,
                "top_k": top_k,
            }
        )
    return result


def _write_capability_contract(path: Path, contract: Mapping[str, object]) -> None:
    _write_json(path, contract)


def render_table_evidence_campaign_report(
    campaign: ModelCampaign,
    comparison: ModelComparison,
    *,
    recipe: ModelRecipe,
) -> str:
    lines = [
        "# TableEvidenceAnalyzer campaign report",
        "",
        f"- Campaign: `{campaign.campaign_id}`",
        f"- Recipe: `{recipe.recipe_id}` (`{recipe.digest}`)",
        f"- Dataset: `{recipe.data.dataset.id}` (`{recipe.data.dataset.digest}`)",
        f"- Validation split: `{recipe.data.split.id}` (`{recipe.data.split.digest}`)",
        f"- Analyzer capability: `{recipe.capability}`",
        "- Runtime scope: `oracle_crop_identity_only`",
        "- Complete table analysis: `false`",
        f"- Recommendation: `{comparison.recommendation}`",
        "",
        "## Data and commands",
        "",
        "The adapter uses the explicit plan 0020 dataset, split, and sample-artifact paths in the "
        "resolved recipe or command arguments. It does not scan source directories.",
        "",
        "Validation commands and exit codes are recorded in `logs/commands.json`. No test "
        "partition command is part of M3.",
        "",
        "## Group support",
        "",
        "Group dimensions without declared validation support are reported as `not_available`; "
        "they are not converted into passing metrics.",
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


def _champion_evaluation_from_bundle(
    bundle_path: Path,
    *,
    dataset: DatasetManifest,
    split: SplitManifest,
    artifacts_path: Path,
    cache_path: Path,
) -> tuple[dict[str, object], dict[str, object], float]:
    validated = _validate_bundle(
        bundle_path,
        component="table-evidence-analyzer",
        capability="visual-card-identity",
        runtime_contract_version="runtime/v1",
        input_contract_version="input/v1",
        dataset=dataset,
        split=split,
    )
    contract = validated["contract"]
    assert isinstance(contract, Mapping)
    compatible, latency = _observation_fixture(
        bundle_path,
        dataset=dataset,
        split=split,
        artifacts_path=artifacts_path,
        cache_path=cache_path,
    )
    artifacts = load_artifact_index(artifacts_path)
    cache = materialize_crops(dataset, split, artifacts, cache_path)
    predictions: list[dict[str, object]] = []
    bundle = validated["bundle"]
    for sample in MaterializedCropDataset(cache, partition="validation"):
        crop = next(item for item in cache.crops if item.dataset_item_id == sample.dataset_item_id)
        candidates = bundle.classify(cache.root / crop.relative_path)
        ranked = [candidate.card for candidate in candidates]
        predictions.append(
            {
                "sample_id": sample.dataset_item_id,
                "target": sample.target,
                "prediction": ranked[0],
                "top_k": ranked,
            }
        )
    raw = {
        "top_1_accuracy": sum(item["target"] == item["prediction"] for item in predictions)
        / len(predictions)
        if predictions
        else 0.0,
        "predictions": predictions,
        "metrics": {"unusable_sample_rate": 0.0},
    }
    metrics = _evaluation_metrics(
        raw,
        dataset=dataset,
        split=split,
        artifact_path=bundle_path,
        checkpoint_path=bundle_path,
        capability=contract,
        observation_fixture_compatible=compatible,
        inference_latency_ms=latency,
    )
    return raw, metrics, latency


def run_table_evidence_campaign(
    recipe_path: str | Path,
    *,
    repository_root: str | Path,
    registry_path: str | Path | None = None,
    campaign_root: str | Path | None = None,
    campaign_id: str | None = None,
    project_root: str | Path | None = None,
    dataset_path: str | Path | None = None,
    split_path: str | Path | None = None,
    artifacts_path: str | Path | None = None,
    champion_run_path: str | Path | None = None,
    device: str | None = None,
    precision: str | None = None,
    runner: TableEvidenceCommandRunner | None = None,
    now_utc: str | None = None,
) -> ModelCampaign:
    """Run or resume one bounded TableEvidenceAnalyzer validation campaign."""
    root = Path(repository_root).resolve()
    recipe = load_model_recipe(_resolve(root, recipe_path))
    if recipe.component != "table-evidence-analyzer":
        raise TableEvidenceCampaignError(
            "TableEvidenceAnalyzer campaign recipes must use table-evidence-analyzer"
        )
    profile = default_gate_profile(recipe.component)
    if profile.gate_profile_id != recipe.gate_profile_id:
        raise TableEvidenceCampaignError(
            "recipe gate profile does not match the checked-in profile"
        )
    registry_file = _resolve(root, registry_path or root / "data" / "model-registry.json")
    registry = load_model_registry(registry_file)
    champion = registry.champion_for(recipe.component, recipe.capability)
    if champion is None:
        raise TableEvidenceCampaignError(
            f"model registry has no {recipe.component}/{recipe.capability} champion"
        )
    if champion.champion_bundle != recipe.baseline_bundle:
        raise TableEvidenceCampaignError(
            "recipe baseline bundle differs from the registry champion"
        )
    campaigns = _resolve(root, campaign_root or root / "data" / "model-campaigns")
    selected_id = _campaign_id(recipe, campaign_id)
    campaign_dir = campaigns / selected_id
    campaign_file = campaign_dir / "campaign.json"
    command_runner = runner or TableEvidenceSubprocessCommandRunner()
    timestamp = now_utc or _now()

    if campaign_file.exists():
        campaign = load_campaign(campaigns, selected_id)
        if campaign.recipe_digest != recipe.digest:
            raise TableEvidenceCampaignError("existing campaign uses a different recipe digest")
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
        _write_text(campaign_dir / "resolved-recipe.yaml", _recipe_text(recipe_path))
        _write_json(campaign_file, campaign.to_mapping())

    configuration = _candidate_configuration(recipe.candidates[0])
    dataset, split, selected_dataset, selected_split, selected_artifacts = _validate_data_contract(
        recipe,
        configuration,
        root=root,
        dataset_path=dataset_path,
        split_path=split_path,
        artifacts_path=artifacts_path,
    )
    for candidate in recipe.candidates:
        candidate_config = _candidate_configuration(candidate)
        for key, expected in (
            ("dataset_path", selected_dataset),
            ("split_path", selected_split),
            ("artifacts_path", selected_artifacts),
        ):
            if (
                key in candidate_config
                and _configured_path(candidate_config, key, None, root=root) != expected
            ):
                raise TableEvidenceCampaignError(
                    f"candidate {candidate.candidate_id} cannot change shared {key}"
                )
    if device == "auto" or precision == "auto":
        raise TableEvidenceCampaignError(
            "analyzer execution requires an explicit device and precision"
        )
    selected_device = device or recipe.execution.device
    if selected_device not in {"cpu", "mps", "cuda"}:
        raise TableEvidenceCampaignError(f"unsupported analyzer device: {selected_device}")
    selected_precision = precision or recipe.execution.precision
    project = _resolve(root, project_root or root / "table_evidence_analyzer")
    command_manifest = campaign_dir / "logs" / "commands.json"
    campaign_dir.joinpath("logs").mkdir(parents=True, exist_ok=True)
    campaign_dir.joinpath("candidates").mkdir(parents=True, exist_ok=True)
    capability_contract = {
        "schema_version": "table-analyzer-capability-contract/v1",
        "component": recipe.component,
        "capability": recipe.capability,
        "bundle_schema": BUNDLE_SCHEMA,
        "output_schema": OBSERVATION_SCHEMA_VERSION,
        "declared_capabilities": ["identity_candidates"],
        "not_provided_capabilities": [
            item for item in ANALYZER_CAPABILITIES if item != "identity_candidates"
        ],
        "scope": "oracle_crop_identity_only",
        "complete_table_analysis": False,
        "runtime_contract_version": recipe.export_compatibility,
        "input_contract_version": "input/v1",
    }
    _write_capability_contract(campaign_dir / "capability-contract.json", capability_contract)

    champion_evaluation_file = campaign_dir / "champion-evaluation.json"
    champion_payload: dict[str, object]
    champion_evaluation: ModelEvaluation
    if champion_evaluation_file.exists():
        champion_evaluation = ModelEvaluation.from_mapping(
            _read_json(champion_evaluation_file, "champion evaluation")
        )
        champion_payload = _read_json(
            campaign_dir / "champion-evaluation-raw.json", "champion raw evaluation"
        )
    else:
        try:
            configured_champion = champion_run_path or configuration.get("champion_run_path")
            champion_source = (
                _configured_path(configuration, "champion_run_path", configured_champion, root=root)
                if configured_champion is not None
                else _resolve(root, champion.bundle_path)
            )
            if champion_source.is_dir() and (champion_source / "manifest.json").is_file():
                raw, metrics, _latency = _champion_evaluation_from_bundle(
                    champion_source,
                    dataset=dataset,
                    split=split,
                    artifacts_path=selected_artifacts,
                    cache_path=campaign_dir / "champion-cache",
                )
            else:
                if not champion_source.exists() and isinstance(
                    command_runner, TableEvidenceFixtureCommandRunner
                ):
                    champion_source = campaign_dir / "runs" / "champion"
                    _write_json(
                        champion_source / "run.json",
                        {
                            "run_id": f"run-{selected_id}-champion",
                            "config": {
                                "dataset": str(selected_dataset),
                                "split": str(selected_split),
                            },
                        },
                    )
                command = (
                    *_command_prefix(project),
                    "evaluate",
                    "--run",
                    str(champion_source),
                    "--split",
                    "validation",
                )
                _run_checked(
                    command_runner,
                    command,
                    root=root,
                    log_path=campaign_dir / "logs" / "champion-evaluate.log",
                    manifest_path=command_manifest,
                )
                raw = _read_json(
                    champion_source / "evaluation-validation.json",
                    "TableEvidenceAnalyzer champion evaluation",
                )
                metrics = _evaluation_metrics(
                    raw,
                    dataset=dataset,
                    split=split,
                    artifact_path=champion_source,
                    checkpoint_path=champion_source,
                    capability=capability_contract,
                    observation_fixture_compatible=True,
                    inference_latency_ms=float(
                        raw.get("metrics", {}).get("inference_latency_ms", 0.0)
                    )
                    if isinstance(raw.get("metrics"), Mapping)
                    else 0.0,
                )
            champion_payload = raw
            champion_evaluation = ModelEvaluation.from_mapping(
                {
                    "evaluation_id": f"evaluation-{selected_id}-champion",
                    "role": "champion",
                    "candidate_id": None,
                    "run_id": f"run-{selected_id}-champion",
                    "bundle": champion.champion_bundle.to_mapping(),
                    "state": "success",
                    "data": recipe.data.to_mapping(),
                    "metrics": metrics,
                    "gates": [],
                    "failure_reason": None,
                }
            )
            _write_json(champion_evaluation_file, champion_evaluation.to_mapping())
            _write_json(campaign_dir / "champion-evaluation-raw.json", champion_payload)
        except (OSError, ValueError, ModelImprovementError, TableEvidenceCampaignError) as error:
            campaign = _update(
                campaign,
                state="failed",
                timestamp=timestamp,
                failure_reason=f"champion evaluation failed: {error}",
            )
            _write_json(campaign_file, campaign.to_mapping())
            raise

    evaluations: dict[str, ModelEvaluation] = {}
    raw_evaluations: dict[str, Mapping[str, object]] = {}
    existing_runs = {item.candidate_id: item for item in campaign.candidate_runs}
    failure_count = sum(item.state == "failed" for item in campaign.candidate_runs)
    started = time.monotonic()
    for candidate in sorted(recipe.candidates, key=lambda item: item.candidate_id):
        previous = existing_runs.get(candidate.candidate_id)
        candidate_dir = campaign_dir / "candidates" / candidate.candidate_id
        run_dir = campaign_dir / "runs" / candidate.candidate_id
        evaluation_file = candidate_dir / "evaluation.json"
        raw_file = run_dir / "evaluation-validation.json"
        bundle_path = candidate_dir / "capability-bundle"
        if previous is not None and previous.state == "success" and evaluation_file.exists():
            evaluations[candidate.candidate_id] = ModelEvaluation.from_mapping(
                _read_json(evaluation_file, "candidate evaluation")
            )
            if raw_file.exists():
                raw_evaluations[candidate.candidate_id] = _read_json(
                    raw_file, "candidate evaluation"
                )
            continue
        if previous is not None and previous.state in {"failed", "skipped"}:
            evaluations[candidate.candidate_id] = ModelEvaluation.from_mapping(
                _read_json(evaluation_file, "candidate evaluation")
            )
            continue
        if (
            failure_count >= recipe.budget.max_failures and failure_count > 0
        ) or time.monotonic() - started >= recipe.budget.max_compute_minutes * 60:
            reason = (
                "failure budget exhausted"
                if failure_count >= recipe.budget.max_failures and failure_count > 0
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
            _write_json(campaign_file, campaign.to_mapping())
            continue
        configuration = _candidate_configuration(candidate)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        run: CandidateRunReference
        try:
            seed = _seed_from_configuration(configuration, recipe.seeds[0])
            train_config = {
                "dataset": str(selected_dataset),
                "split": str(selected_split),
                "artifacts": str(selected_artifacts),
                "output": str(run_dir),
                "seed": seed,
                "device": _string_from_configuration(configuration, "device", selected_device),
                "precision": _string_from_configuration(
                    configuration, "precision", selected_precision
                ),
            }
            _write_json(candidate_dir / "train-config.json", train_config)
            _write_json(
                run_dir / "model-improvement.json",
                {
                    "campaign_id": selected_id,
                    "candidate_id": candidate.candidate_id,
                    "experiment_family": candidate.experiment_family,
                    "recipe_digest": recipe.digest,
                    "data": recipe.data.to_mapping(),
                    "seed": seed,
                    "analyzer_capability": recipe.capability,
                    "runtime_contract_version": recipe.export_compatibility,
                    "input_contract_version": "input/v1",
                    "scope": "oracle_crop_identity_only",
                },
            )
            _run_checked(
                command_runner,
                (
                    *_command_prefix(project),
                    "train",
                    "--config",
                    str(candidate_dir / "train-config.json"),
                ),
                root=root,
                log_path=candidate_dir / "train.log",
                manifest_path=command_manifest,
            )
            checkpoint = run_dir / "checkpoint-best.json"
            if not checkpoint.is_file():
                raise TableEvidenceCampaignError(f"training did not write checkpoint {checkpoint}")
            _run_checked(
                command_runner,
                (
                    *_command_prefix(project),
                    "evaluate",
                    "--run",
                    str(run_dir),
                    "--split",
                    "validation",
                ),
                root=root,
                log_path=candidate_dir / "evaluate.log",
                manifest_path=command_manifest,
            )
            raw = _read_json(raw_file, "TableEvidenceAnalyzer candidate evaluation")
            _run_checked(
                command_runner,
                (
                    *_command_prefix(project),
                    "export",
                    "--run",
                    str(run_dir),
                    "--output",
                    str(bundle_path),
                ),
                root=root,
                log_path=candidate_dir / "export.log",
                manifest_path=command_manifest,
            )
            validated_bundle = _validate_bundle(
                bundle_path,
                component=recipe.component,
                capability=recipe.capability,
                runtime_contract_version=recipe.export_compatibility,
                input_contract_version="input/v1",
                dataset=dataset,
                split=split,
            )
            contract = validated_bundle["contract"]
            assert isinstance(contract, Mapping)
            compatible, latency = _observation_fixture(
                bundle_path,
                dataset=dataset,
                split=split,
                artifacts_path=selected_artifacts,
                cache_path=candidate_dir / "crop-cache",
            )
            _write_capability_contract(candidate_dir / "capability-contract.json", contract)
            metrics = _evaluation_metrics(
                raw,
                dataset=dataset,
                split=split,
                artifact_path=bundle_path,
                checkpoint_path=checkpoint,
                capability=contract,
                observation_fixture_compatible=compatible,
                inference_latency_ms=latency,
            )
            bundle_ref = ArtifactReference(
                f"bundle-{selected_id}-{candidate.candidate_id}", _path_digest(bundle_path)
            )
            evaluation = ModelEvaluation.from_mapping(
                {
                    "evaluation_id": f"evaluation-{selected_id}-{candidate.candidate_id}",
                    "role": "candidate",
                    "candidate_id": candidate.candidate_id,
                    "run_id": f"run-{selected_id}-{candidate.candidate_id}",
                    "bundle": bundle_ref.to_mapping(),
                    "state": "success",
                    "data": recipe.data.to_mapping(),
                    "metrics": metrics,
                    "gates": [],
                    "failure_reason": None,
                }
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
            _write_json(
                candidate_dir / "run-reference.json",
                {
                    "candidate_id": candidate.candidate_id,
                    "run_id": evaluation.run_id,
                    "checkpoint_id": run.checkpoint_id,
                    "checkpoint_path": str(checkpoint),
                    "bundle_path": str(bundle_path),
                    "validation_evaluation_id": evaluation.evaluation_id,
                    "recipe_digest": recipe.digest,
                    "data": recipe.data.to_mapping(),
                },
            )
            evaluations[candidate.candidate_id] = evaluation
            raw_evaluations[candidate.candidate_id] = raw
        except (OSError, ValueError, ModelImprovementError, TableEvidenceCampaignError) as error:
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
        _write_json(campaign_file, campaign.to_mapping())

    comparison = compare_evaluations(
        campaign_id=selected_id,
        component=recipe.component,
        capability=recipe.capability,
        task=recipe.task,
        recipe_digest=recipe.digest,
        data=recipe.data,
        champion=champion_evaluation,
        candidates=[
            evaluations[item.candidate_id]
            for item in sorted(recipe.candidates, key=lambda item: item.candidate_id)
        ],
        profile=profile,
        generated_at_utc=timestamp,
    )
    _write_json(campaign_dir / "comparison.json", comparison.to_mapping())
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
            item for item in campaign.candidate_runs if item.candidate_id == candidate.candidate_id
        )
        lock = _candidate_lock(
            campaign,
            recipe,
            candidate,
            evaluations[candidate.candidate_id],
            raw_evaluations[candidate.candidate_id],
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
    _write_json(campaign_file, campaign.to_mapping())
    _write_text(
        campaign_dir / "report.md",
        render_table_evidence_campaign_report(campaign, comparison, recipe=recipe),
    )
    validate_campaign_against_registry(campaign, registry)
    return campaign


def _recipe_text(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise TableEvidenceCampaignError(f"could not snapshot model recipe: {error}") from error


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "TableEvidenceCampaignError",
    "TableEvidenceCommandResult",
    "TableEvidenceCommandRunner",
    "TableEvidenceFixtureCommandRunner",
    "TableEvidenceSubprocessCommandRunner",
    "render_table_evidence_campaign_report",
    "run_table_evidence_campaign",
]
