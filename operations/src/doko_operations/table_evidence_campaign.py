"""Resumable TableEvidenceAnalyzer validation campaigns."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
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
    _atomic_write_bytes,
    _campaign_id,
    _candidate_configuration,
    _candidate_lock,
    _candidate_run_digest,
    _copy_path,
    _create_campaign,
    _failure_evaluation,
    _promotion_receipt,
    _remove_path,
    _root_relative_path,
    _seed_from_configuration,
    _string_from_configuration,
    _update,
)
from .model_improvement import (
    ArtifactReference,
    CandidateRunReference,
    ChampionModel,
    ExportContract,
    ModelCampaign,
    ModelComparison,
    ModelEvaluation,
    ModelImprovementError,
    ModelRecipe,
    ModelRegistry,
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


class TableEvidenceCampaignError(ModelImprovementError):
    """Raised when a TableEvidenceAnalyzer campaign cannot be completed."""


class TableEvidencePromotionError(TableEvidenceCampaignError):
    """Raised when a locked TableEvidenceAnalyzer candidate cannot be promoted."""


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
        test_quality: float | None = None,
        fail_commands: Sequence[str] = (),
    ) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.champion_quality = champion_quality
        self.candidate_quality = candidate_quality
        self.test_quality = test_quality
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
            if split_name not in {"validation", "test"} or (
                split_name == "test" and self.test_quality is None
            ):
                _write_text(
                    log_path,
                    f"command: {shlex.join(command)}\nreturncode: 2\n"
                    "fixture only permits authorized evaluation partitions\n",
                )
                return TableEvidenceCommandResult(
                    2, "", "fixture only permits authorized evaluation partitions"
                )
            run_dir = Path(_option(command, "--run"))
            run = _read_json(run_dir / "run.json", "fixture run")
            config = run.get("config")
            if not isinstance(config, Mapping):
                raise TableEvidenceCampaignError("fixture run has no configuration")
            dataset = load_dataset_manifest(Path(str(config["dataset"])))
            split = load_split_manifest(Path(str(config["split"])))
            is_champion = run_dir.name == "champion"
            quality = (
                self.test_quality
                if split_name == "test" and self.test_quality is not None
                else self.champion_quality
                if is_champion
                else self.candidate_quality
            )
            predictions = _fixture_predictions(
                dataset, split, quality=quality, partition=split_name
            )
            _write_json(
                run_dir / f"evaluation-{split_name}.json",
                {
                    "schema_version": "table-analyzer-evaluation/v1",
                    "run_id": run["run_id"],
                    "split": split_name,
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
    *,
    partition: str = "validation",
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
        if entry.dataset_item_id in set(split.partitions[partition])
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


def _plan0006_observation_fixture(
    root: Path,
    bundle_path: Path,
    *,
    dataset: DatasetManifest,
    split: SplitManifest,
    artifacts_path: Path,
    cache_path: Path,
) -> tuple[bool, float]:
    """Validate the promoted output against the canonical plan 0006 fixture."""

    started = time.perf_counter()
    fixture = root / "fixtures" / "game-engine" / "v1" / "observations" / "minimal.json"
    if not fixture.is_file():
        fixture = (
            Path(__file__).resolve().parents[3]
            / "fixtures"
            / "game-engine"
            / "v1"
            / "observations"
            / "minimal.json"
        )
    try:
        payload = _read_json(fixture, "plan 0006 observation fixture")
        bundle = load_bundle(bundle_path)
        artifacts = load_artifact_index(artifacts_path)
        cache = materialize_crops(dataset, split, artifacts, cache_path)
        samples = list(MaterializedCropDataset(cache, partition="validation"))
        cards = list(payload.get("cards", []))
        if samples:
            crop = next(
                item for item in cache.crops if item.dataset_item_id == samples[0].dataset_item_id
            )
            candidates = bundle.classify(cache.root / crop.relative_path)
            if not cards or not isinstance(cards[0], Mapping):
                return False, (time.perf_counter() - started) * 1000.0
            card = dict(cards[0])
            card["identity_candidates"] = [
                candidate.model_dump(mode="json") for candidate in candidates
            ]
            cards = [card]
        payload["cards"] = cards
        payload["capabilities"] = ["identity_candidates"]
        TableObservation.model_validate(payload)
    except (KeyError, OSError, TypeError, ValueError):
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


def _runtime_only_bundle_check(bundle_path: Path) -> dict[str, object]:
    """Load only the portable export interface, without training imports or data."""

    try:
        load_bundle(bundle_path)
    except (OSError, TypeError, ValueError) as error:
        raise TableEvidencePromotionError(f"runtime-only bundle load failed: {error}") from error
    return {
        "status": "passed",
        "method": "table_evidence_analyzer.export.load_bundle",
        "training_data": False,
        "training_modules": False,
    }


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
    partition: str = "validation",
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
    evaluation_entries = [
        entry
        for entry in dataset.entries
        if entry.dataset_item_id in set(split.partitions[partition])
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
        "sample_count": len(evaluation_entries),
        "prediction_count": len(predictions),
        "per_identity": identity_metrics,
        "per_identity_support": min(
            (int(item["support"]) for item in identity_metrics.values()), default=0
        ),
        "per_identity_min_accuracy": min(
            (float(item["accuracy"]) for item in identity_metrics.values()), default=0.0
        ),
        "group_metrics": _group_metrics(dataset, split, predictions, partition=partition),
        "evaluation_partition": partition,
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
    dataset: DatasetManifest,
    split: SplitManifest,
    *,
    quality: float,
    partition: str = "validation",
) -> list[dict[str, object]]:
    identities = ["CLUBS_NINE", "HEARTS_QUEEN", "SPADES_JACK"]
    result: list[dict[str, object]] = []
    for index, item_id in enumerate(split.partitions[partition]):
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


def _write_table_promotion_report(
    campaign_dir: Path,
    campaign: ModelCampaign,
    *,
    test_evaluation: ModelEvaluation | None,
    checks: Mapping[str, object] | None,
    failure_reason: str | None = None,
) -> None:
    lines = [
        "# TableEvidenceAnalyzer promotion report",
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


def _stage_bundle(source: Path, target: Path) -> None:
    """Publish a new bundle at a campaign-owned path with an atomic directory rename."""

    if not source.is_dir():
        raise TableEvidencePromotionError(f"exported analyzer bundle is not a directory: {source}")
    if target.exists() or target.is_symlink():
        raise TableEvidencePromotionError(f"promotion bundle target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    staged = staging_parent / target.name
    try:
        _copy_path(source, staged)
        os.replace(staged, target)
    except (OSError, shutil.Error) as error:
        raise TableEvidencePromotionError(f"could not stage analyzer bundle: {error}") from error
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def _retain_previous_table_champion(
    root: Path,
    campaign_dir: Path,
    champion: ChampionModel,
) -> dict[str, object]:
    """Keep the former table champion reference and a copy when its artifact is present."""

    source = _resolve(root, champion.bundle_path)
    retained = campaign_dir / "previous-champion-bundle"
    available = source.exists()
    source_digest: str | None = None
    if available:
        source_digest = _path_digest(source)
        if source_digest != champion.champion_bundle.digest:
            raise TableEvidencePromotionError(
                "current table champion bundle digest differs from the registry"
            )
        if not retained.exists():
            _copy_path(source, retained)
        if _path_digest(retained) != source_digest:
            raise TableEvidencePromotionError(
                "retained table champion copy failed its digest check"
            )
    record = {
        "champion": champion.to_mapping(),
        "bundle_path": _root_relative_path(root, source, "former champion bundle path"),
        "bundle_available": available,
        "bundle_digest": source_digest,
        "retained_copy_path": (str(retained.resolve()) if available else None),
    }
    _write_json(campaign_dir / "previous-champion.json", record)
    return record


def _validate_test_payload(
    payload: Mapping[str, object],
    *,
    dataset: DatasetManifest,
    split: SplitManifest,
) -> None:
    if payload.get("schema_version") != "table-analyzer-evaluation/v1":
        raise TableEvidencePromotionError("sealed test evaluation has an unsupported schema")
    if payload.get("split") != "test":
        raise TableEvidencePromotionError("sealed test evaluation must use the test partition")
    if payload.get("dataset_version_digest") != dataset.digest:
        raise TableEvidencePromotionError("sealed test evaluation uses a different dataset digest")
    if payload.get("split_version_digest") != split.digest:
        raise TableEvidencePromotionError("sealed test evaluation uses a different split digest")


def promote_table_evidence_campaign(
    campaign_id: str,
    *,
    repository_root: str | Path,
    registry_path: str | Path | None = None,
    campaign_root: str | Path | None = None,
    candidate_id: str | None = None,
    project_root: str | Path | None = None,
    dataset_path: str | Path | None = None,
    split_path: str | Path | None = None,
    artifacts_path: str | Path | None = None,
    runner: TableEvidenceCommandRunner | None = None,
    confirm: bool = False,
    now_utc: str | None = None,
) -> ModelCampaign:
    """Test, validate, and promote one locked TableEvidenceAnalyzer candidate."""

    if not confirm:
        raise TableEvidencePromotionError("promotion requires explicit confirmation")
    root = Path(repository_root).resolve()
    campaigns = _resolve(root, campaign_root or root / "data" / "model-campaigns")
    campaign = load_campaign(campaigns, campaign_id)
    campaign_dir = campaigns / campaign.campaign_id
    receipt_path = campaign_dir / "promotion-receipt.json"
    if receipt_path.exists():
        receipt = load_promotion_receipt(receipt_path)
        if receipt.campaign_id != campaign.campaign_id:
            raise TableEvidencePromotionError("promotion receipt belongs to a different campaign")
        return campaign
    if campaign.state in {"promoted", "failed", "human_review_required"}:
        return campaign
    if campaign.state not in {"candidate_locked", "tested", "promotion_recommended"}:
        raise TableEvidencePromotionError(
            f"campaign {campaign.campaign_id} is not ready for promotion: {campaign.state}"
        )

    recipe = load_model_recipe(campaign_dir / "resolved-recipe.yaml")
    if not recipe.sealed_test_authorized:
        raise TableEvidencePromotionError("recipe does not authorize a sealed test evaluation")
    if recipe.component != "table-evidence-analyzer":
        raise TableEvidencePromotionError(
            "only TableEvidenceAnalyzer campaigns have an M4 promotion path"
        )
    if recipe.digest != campaign.recipe_digest:
        raise TableEvidencePromotionError("resolved recipe digest differs from the campaign")
    profile = default_gate_profile(recipe.component)
    if profile.gate_profile_id != recipe.gate_profile_id:
        raise TableEvidencePromotionError(
            "recipe gate profile does not match the checked-in profile"
        )
    registry_file = _resolve(root, registry_path or root / "data" / "model-registry.json")
    registry = load_model_registry(registry_file)
    validate_campaign_against_registry(campaign, registry)
    champion = registry.champion_for(campaign.component, campaign.capability)
    if champion is None:
        raise TableEvidencePromotionError(
            "model registry has no current TableEvidenceAnalyzer champion"
        )
    if campaign.baseline_bundle != champion.champion_bundle:
        raise TableEvidencePromotionError("campaign baseline is no longer the current champion")
    comparison = load_campaign_comparison(campaigns, campaign)
    if comparison.recommendation != "promote_candidate":
        raise TableEvidencePromotionError(
            f"campaign recommendation is {comparison.recommendation}, not promote_candidate"
        )
    selected_candidate = candidate_id or comparison.recommended_candidate_id
    if selected_candidate != comparison.recommended_candidate_id:
        raise TableEvidencePromotionError(
            "selected candidate differs from the locked recommendation"
        )
    if selected_candidate is None:
        raise TableEvidencePromotionError("campaign has no recommended candidate")
    candidate = next(
        (item for item in recipe.candidates if item.candidate_id == selected_candidate), None
    )
    if candidate is None:
        raise TableEvidencePromotionError(f"candidate {selected_candidate} is not in the recipe")
    lock = load_candidate_lock(campaign_dir / "lock.json")
    if (
        lock.campaign_id != campaign.campaign_id
        or lock.candidate_id != selected_candidate
        or lock.recipe_digest != recipe.digest
        or lock.data != recipe.data
    ):
        raise TableEvidencePromotionError(
            "candidate lock is stale or incompatible with the campaign"
        )
    run = next(
        (item for item in campaign.candidate_runs if item.candidate_id == selected_candidate), None
    )
    if run is None or run.state != "success" or run.checkpoint_id != lock.checkpoint_id:
        raise TableEvidencePromotionError("candidate lock does not identify a completed checkpoint")
    candidate_evaluation = next(
        (item for item in comparison.candidates if item.candidate_id == selected_candidate), None
    )
    if candidate_evaluation is None or candidate_evaluation.state != "success":
        raise TableEvidencePromotionError(
            "locked candidate has no successful validation evaluation"
        )

    candidate_dir = campaign_dir / "candidates" / selected_candidate
    run_dir = campaign_dir / "runs" / selected_candidate
    candidate_bundle = candidate_dir / "capability-bundle"
    checkpoint = run_dir / "checkpoint-best.json"
    if not checkpoint.is_file() or not candidate_bundle.is_dir():
        raise TableEvidencePromotionError(
            "locked analyzer checkpoint or capability bundle is missing"
        )
    configuration = _candidate_configuration(candidate)
    dataset, split, selected_dataset, selected_split, selected_artifacts = _validate_data_contract(
        recipe,
        configuration,
        root=root,
        dataset_path=dataset_path,
        split_path=split_path,
        artifacts_path=artifacts_path,
    )
    validated_candidate = _validate_bundle(
        candidate_bundle,
        component=recipe.component,
        capability=recipe.capability,
        runtime_contract_version=recipe.export_compatibility,
        input_contract_version="input/v1",
        dataset=dataset,
        split=split,
    )
    expected_contract = validated_candidate["contract"]
    assert isinstance(expected_contract, Mapping)
    if _path_digest(candidate_bundle) != candidate_evaluation.bundle.digest:
        raise TableEvidencePromotionError(
            "locked candidate bundle digest differs from validation evaluation"
        )
    stored_contract = _read_json(
        candidate_dir / "capability-contract.json", "candidate capability contract"
    )
    if stored_contract != dict(expected_contract):
        raise TableEvidencePromotionError(
            "candidate capability contract differs from the resolved contract"
        )

    command_runner = runner or TableEvidenceSubprocessCommandRunner()
    command_manifest = campaign_dir / "logs" / "commands.json"
    timestamp = now_utc or _now()
    test_evaluation_file = campaign_dir / "test-evaluation.json"
    test_evaluation: ModelEvaluation | None = None
    checks: dict[str, object] = {}
    registry_before_bytes = registry_file.read_bytes()
    registry_before_digest = sha256_mapping(registry.to_mapping())
    placeholder_digest = sha256_mapping(
        {
            "campaign_id": campaign.campaign_id,
            "candidate_id": selected_candidate,
            "artifact": "export",
        }
    )
    export_reference = ArtifactReference(
        f"export-{campaign.campaign_id}-{selected_candidate}", placeholder_digest
    )
    promoted_reference = ArtifactReference(
        f"bundle-{campaign.campaign_id}-{selected_candidate}-promoted", placeholder_digest
    )
    receipt_identity = {
        "campaign_id": campaign.campaign_id,
        "candidate_id": selected_candidate,
        "lock_id": lock.lock_id,
    }
    receipt_id = f"receipt-{sha256_mapping(receipt_identity)[:20]}"
    target = _resolve(
        root,
        f"models/table-evidence-analyzer-{campaign.campaign_id}-{selected_candidate}.bundle",
    )
    target_staged = False
    registry_changed = False

    try:
        raw_test_path = run_dir / "evaluation-test.json"
        if test_evaluation_file.exists():
            test_evaluation = ModelEvaluation.from_mapping(
                _read_json(test_evaluation_file, "sealed test evaluation")
            )
        else:
            if not raw_test_path.exists():
                project = _resolve(root, project_root or root / "table_evidence_analyzer")
                _run_checked(
                    command_runner,
                    (
                        *_command_prefix(project),
                        "evaluate",
                        "--run",
                        str(run_dir),
                        "--split",
                        "test",
                    ),
                    root=root,
                    log_path=campaign_dir / "logs" / "test-evaluate.log",
                    manifest_path=command_manifest,
                )
            raw_test = _read_json(raw_test_path, "TableEvidenceAnalyzer sealed test evaluation")
            _validate_test_payload(raw_test, dataset=dataset, split=split)
            candidate_latency = candidate_evaluation.metrics.get("inference_latency_ms", 0.0)
            test_metrics = _evaluation_metrics(
                raw_test,
                dataset=dataset,
                split=split,
                artifact_path=candidate_bundle,
                checkpoint_path=checkpoint,
                capability=expected_contract,
                observation_fixture_compatible=True,
                inference_latency_ms=float(candidate_latency)
                if isinstance(candidate_latency, (int, float))
                and not isinstance(candidate_latency, bool)
                else 0.0,
                partition="test",
            )
            test_evaluation = ModelEvaluation.from_mapping(
                {
                    "evaluation_id": f"evaluation-{campaign.campaign_id}-{selected_candidate}-test",
                    "role": "candidate",
                    "candidate_id": selected_candidate,
                    "run_id": f"run-{campaign.campaign_id}-{selected_candidate}-test",
                    "bundle": candidate_evaluation.bundle.to_mapping(),
                    "state": "success",
                    "data": recipe.data.to_mapping(),
                    "metrics": test_metrics,
                    "gates": [gate.to_mapping() for gate in evaluate_gates(profile, test_metrics)],
                    "failure_reason": None,
                }
            )
            _write_json(test_evaluation_file, test_evaluation.to_mapping())
        if (
            test_evaluation.role != "candidate"
            or test_evaluation.candidate_id != selected_candidate
            or test_evaluation.data != recipe.data
            or test_evaluation.state != "success"
        ):
            raise TableEvidencePromotionError(
                "sealed test evaluation identifies the wrong candidate or data"
            )
        if not test_evaluation.gates:
            test_evaluation = replace(
                test_evaluation,
                gates=evaluate_gates(profile, test_evaluation.metrics),
            )
            _write_json(test_evaluation_file, test_evaluation.to_mapping())
        campaign = _update(
            campaign,
            state="tested",
            timestamp=timestamp,
            test_evaluation_id=test_evaluation.evaluation_id,
        )
        _write_json(campaign_dir / "campaign.json", campaign.to_mapping())
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
            _write_json(campaign_dir / "campaign.json", campaign.to_mapping())
            _write_table_promotion_report(
                campaign_dir,
                campaign,
                test_evaluation=test_evaluation,
                checks=None,
                failure_reason=reason,
            )
            return campaign

        project = _resolve(root, project_root or root / "table_evidence_analyzer")
        export_path = campaign_dir / "promotion-bundle"
        if not export_path.exists():
            _run_checked(
                command_runner,
                (
                    *_command_prefix(project),
                    "export",
                    "--run",
                    str(run_dir),
                    "--output",
                    str(export_path),
                ),
                root=root,
                log_path=campaign_dir / "logs" / "promotion-export.log",
                manifest_path=command_manifest,
            )
        validated_export = _validate_bundle(
            export_path,
            component=recipe.component,
            capability=recipe.capability,
            runtime_contract_version=recipe.export_compatibility,
            input_contract_version="input/v1",
            dataset=dataset,
            split=split,
        )
        export_contract = validated_export["contract"]
        assert isinstance(export_contract, Mapping)
        if dict(export_contract) != dict(expected_contract):
            raise TableEvidencePromotionError(
                "exported capability contract is incompatible with the locked candidate"
            )
        run_payload = _read_json(run_dir / "run.json", "locked analyzer run")
        if validated_export["bundle"].manifest.get("run_id") != run_payload.get("run_id"):
            raise TableEvidencePromotionError("exported bundle run ID differs from the locked run")
        export_digest = _path_digest(export_path)
        export_reference = ArtifactReference(export_reference.id, export_digest)
        promoted_reference = ArtifactReference(promoted_reference.id, export_digest)
        checks["bundle_validation"] = {
            "status": "passed",
            "schema": BUNDLE_SCHEMA,
            "digest": export_digest,
            "compatibility": recipe.export_compatibility,
        }
        _write_json(campaign_dir / "promotion-checks.json", checks)
        checks["runtime_only_load"] = _runtime_only_bundle_check(export_path)
        _write_json(campaign_dir / "promotion-checks.json", checks)
        observation_compatible, observation_latency = _plan0006_observation_fixture(
            root,
            export_path,
            dataset=dataset,
            split=split,
            artifacts_path=selected_artifacts,
            cache_path=campaign_dir / "promotion-crop-cache",
        )
        if not observation_compatible:
            raise TableEvidencePromotionError("plan 0006 observation fixture is incompatible")
        checks["plan0006_observation_fixture"] = {
            "status": "passed",
            "schema": OBSERVATION_SCHEMA_VERSION,
            "latency_ms": observation_latency,
        }
        _write_json(campaign_dir / "promotion-checks.json", checks)
        test_raw = _read_json(run_dir / "evaluation-test.json", "sealed test evaluation")
        test_metrics = _evaluation_metrics(
            test_raw,
            dataset=dataset,
            split=split,
            artifact_path=export_path,
            checkpoint_path=checkpoint,
            capability=export_contract,
            observation_fixture_compatible=True,
            inference_latency_ms=observation_latency,
            partition="test",
        )
        test_evaluation = replace(
            test_evaluation,
            bundle=promoted_reference,
            metrics=test_metrics,
            gates=evaluate_gates(profile, test_metrics),
        )
        _write_json(test_evaluation_file, test_evaluation.to_mapping())
        failed_gates = [
            gate.gate_id for gate in test_evaluation.gates if gate.hard and gate.status == "failed"
        ]
        if failed_gates:
            reason = (
                f"promotion checks caused sealed test hard gates to fail: {', '.join(failed_gates)}"
            )
            campaign = _update(
                campaign,
                state="human_review_required",
                timestamp=timestamp,
                failure_reason=reason,
            )
            _write_json(campaign_dir / "campaign.json", campaign.to_mapping())
            _write_table_promotion_report(
                campaign_dir,
                campaign,
                test_evaluation=test_evaluation,
                checks=checks,
                failure_reason=reason,
            )
            return campaign

        previous = _retain_previous_table_champion(root, campaign_dir, champion)
        del previous
        _stage_bundle(export_path, target)
        target_staged = True
        if _path_digest(target) != export_digest:
            raise TableEvidencePromotionError(
                "promoted bundle digest differs from the validated export"
            )
        target_relative = _root_relative_path(root, target, "promoted bundle path")
        checks["registry_bundle_stage"] = {"status": "staged", "path": target_relative}
        _write_json(campaign_dir / "promotion-checks.json", checks)
        new_champion = ChampionModel(
            component=champion.component,
            capability=champion.capability,
            champion_bundle=promoted_reference,
            bundle_path=target_relative,
            runtime_contract_version=recipe.export_compatibility,
            input_contract_version="input/v1",
            data=recipe.data,
            validation_report_id=comparison.comparison_id,
            sealed_test_report_id=test_evaluation.evaluation_id,
            export=ExportContract(
                environment={
                    "tool": "table-evidence-analyzer",
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
        if [
            item.to_mapping()
            for item in new_registry.champions
            if item.component == "card-event-net"
        ] != [
            item.to_mapping() for item in registry.champions if item.component == "card-event-net"
        ]:
            raise TableEvidencePromotionError(
                "TableEvidenceAnalyzer promotion changed CardEventNet registry entries"
            )
        registry_after_digest = sha256_mapping(new_registry.to_mapping())
        _atomic_write_bytes(
            registry_file,
            json.dumps(
                new_registry.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True
            ).encode()
            + b"\n",
        )
        registry_changed = True
        if sha256_mapping(load_model_registry(registry_file).to_mapping()) != registry_after_digest:
            raise TableEvidencePromotionError(
                "atomic analyzer registry update failed its digest check"
            )
        checks["registry_update"] = {
            "status": "updated",
            "before_digest": registry_before_digest,
            "after_digest": registry_after_digest,
            "card_event_net_changed": False,
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
            runtime_contract_version=recipe.export_compatibility,
            input_contract_version="input/v1",
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
            json.dumps(receipt.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True).encode()
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
        _write_json(campaign_dir / "campaign.json", campaign.to_mapping())
        _write_table_promotion_report(
            campaign_dir,
            campaign,
            test_evaluation=test_evaluation,
            checks=checks,
        )
        return campaign
    except (
        TableEvidenceCampaignError,
        ModelImprovementError,
        OSError,
        ValueError,
        shutil.Error,
    ) as error:
        if registry_changed:
            with suppress(OSError, ValueError):
                _atomic_write_bytes(registry_file, registry_before_bytes)
        if target_staged:
            _remove_path(target)
        reason = str(error)
        if test_evaluation is None:
            test_evaluation = ModelEvaluation.from_mapping(
                {
                    "evaluation_id": f"evaluation-{campaign.campaign_id}-{selected_candidate}-test",
                    "role": "candidate",
                    "candidate_id": selected_candidate,
                    "run_id": f"run-{campaign.campaign_id}-{selected_candidate}-test",
                    "bundle": candidate_evaluation.bundle.to_mapping(),
                    "state": "failed",
                    "data": recipe.data.to_mapping(),
                    "metrics": {},
                    "gates": [],
                    "failure_reason": reason,
                }
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
            runtime_contract_version=recipe.export_compatibility,
            input_contract_version="input/v1",
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
            ).encode()
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
        _write_json(campaign_dir / "campaign.json", campaign.to_mapping())
        _write_table_promotion_report(
            campaign_dir,
            campaign,
            test_evaluation=test_evaluation,
            checks=checks or None,
            failure_reason=reason,
        )
        raise TableEvidencePromotionError(reason) from error


__all__ = [
    "TableEvidenceCampaignError",
    "TableEvidencePromotionError",
    "TableEvidenceCommandResult",
    "TableEvidenceCommandRunner",
    "TableEvidenceFixtureCommandRunner",
    "TableEvidenceSubprocessCommandRunner",
    "promote_table_evidence_campaign",
    "render_table_evidence_campaign_report",
    "run_table_evidence_campaign",
]
