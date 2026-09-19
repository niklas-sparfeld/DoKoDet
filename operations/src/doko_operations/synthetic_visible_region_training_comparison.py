"""Run the bounded epic 0070 M4 RF-DETR comparison.

M4 keeps the existing RF-DETR runner and evaluator as the execution boundary.  This module
only prepares the digest-checked real-plus-synthetic view and records the paired comparison.
The real validation and sealed-test partitions always come from the unchanged 0068 view.
"""

from __future__ import annotations

import json
import platform
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from .reviewed_rfdetr_detector_campaign import canonical_json_bytes
from .synthetic_visible_region_training_view import (
    M3_MANIFEST_DEFAULT,
    SyntheticVisibleRegionTrainingViewError,
    validate_synthetic_visible_region_training_view,
)
from .synthetic_visible_region_training_view import (
    OUTPUT_DIRECTORY_DEFAULT as M3_OUTPUT_DIRECTORY_DEFAULT,
)

M4_SCHEMA_VERSION = "synthetic-visible-region-training-comparison/v1"
M4_CAMPAIGN_ID = "0070-m4-synthetic-visible-region-training-comparison"
M4_OUTPUT_DIRECTORY_DEFAULT = ".runtime/synthetic-visible-region-0070-m4"
M4_REPORT_DEFAULT = "data/operations/synthetic-visible-region-0070-m4-training-comparison.json"
M4_SYNTHETIC_VIEW_DIRECTORY = "synthetic-candidate-view"
M0_MANIFEST_DEFAULT = "data/operations/synthetic-visible-region-0070-m0-manifest.json"
REAL_MANIFEST_DEFAULT = "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"
REAL_MATERIALIZATION_DEFAULT = ".runtime/rfdetr-segmentation-0068"
PRETRAINED_CHECKPOINT_DEFAULT = ".runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt"
_SHA256_LENGTH = 64


class SyntheticVisibleRegionTrainingComparisonError(ValueError):
    """The frozen M4 comparison cannot proceed safely."""


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Any) -> str:
    import hashlib

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyntheticVisibleRegionTrainingComparisonError(
            f"could not read {field}: {path}"
        ) from error
    if not isinstance(value, Mapping):
        raise SyntheticVisibleRegionTrainingComparisonError(f"{field} must be an object")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return _sha256_file(path)


def _resolve(repository: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else repository / path


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise SyntheticVisibleRegionTrainingComparisonError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise SyntheticVisibleRegionTrainingComparisonError(
            f"{field} must be a SHA-256 digest"
        ) from error
    return value


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "byte_length": path.stat().st_size,
            }
        )
    return result


def _verify_inventory(root: Path, expected: Sequence[Mapping[str, Any]], field: str) -> None:
    actual = _file_inventory(root)
    if actual != [dict(item) for item in expected]:
        raise SyntheticVisibleRegionTrainingComparisonError(f"{field} changed")


def _validate_m0_inputs(
    repository: Path,
    m0_path: Path,
    real_manifest_path: Path,
    m3_path: Path,
    real_materialization: Path,
    pretrained: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    m0 = _read_json(m0_path, "0070 M0 manifest")
    try:
        declared_m0_digest = _require_digest(m0.get("manifest_digest"), "M0 manifest_digest")
        m0_core = {key: value for key, value in m0.items() if key != "manifest_digest"}
        if declared_m0_digest != _digest(m0_core):
            raise SyntheticVisibleRegionTrainingComparisonError("0070 M0 manifest digest is stale")
    except TypeError as error:
        raise SyntheticVisibleRegionTrainingComparisonError(
            "0070 M0 manifest is invalid"
        ) from error
    if m0.get("campaign_id") != "0070-m0-synthetic-visible-region-training-data":
        raise SyntheticVisibleRegionTrainingComparisonError(
            "M0 manifest belongs to another campaign"
        )
    trainer = m0.get("recipe", {}).get("trainer", {})
    control = trainer.get("control") if isinstance(trainer, Mapping) else None
    addition = trainer.get("synthetic_addition") if isinstance(trainer, Mapping) else None
    if not isinstance(control, Mapping) or not isinstance(addition, Mapping):
        raise SyntheticVisibleRegionTrainingComparisonError(
            "M0 paired trainer recipe is missing"
        )
    if (
        control.get("budget", {}).get("candidate_count") != 2
        or control.get("budget", {}).get("sweep")
    ):
        raise SyntheticVisibleRegionTrainingComparisonError(
            "M0 does not freeze the paired two-run budget"
        )
    if (
        addition.get("same_as_control") is not True
        or addition.get("real_sample_order_unchanged") is not True
    ):
        raise SyntheticVisibleRegionTrainingComparisonError("M0 synthetic addition is not paired")
    if control.get("training", {}).get("seed") != 7001:
        raise SyntheticVisibleRegionTrainingComparisonError("M4 requires the frozen 0070 seed 7001")

    real_manifest = _read_json(real_manifest_path, "0068 M0 manifest")
    real_manifest_digest = _require_digest(
        real_manifest.get("manifest_digest"), "0068 manifest_digest"
    )
    if real_manifest_digest != _digest(
        {key: value for key, value in real_manifest.items() if key != "manifest_digest"}
    ):
        raise SyntheticVisibleRegionTrainingComparisonError("0068 M0 manifest digest is stale")
    if real_manifest.get("freeze_state") != "frozen":
        raise SyntheticVisibleRegionTrainingComparisonError("0068 M0 manifest is not frozen")

    m3 = _read_json(m3_path, "M3 training-view manifest")
    try:
        validate_synthetic_visible_region_training_view(m3)
    except (SyntheticVisibleRegionTrainingViewError, TypeError) as error:
        raise SyntheticVisibleRegionTrainingComparisonError(str(error)) from error
    if m3["operator_approval"]["status"] != "approved":
        raise SyntheticVisibleRegionTrainingComparisonError("M3 training view is not approved")
    if m3["inputs"]["m0"]["manifest_digest"] != declared_m0_digest:
        raise SyntheticVisibleRegionTrainingComparisonError("M3 points to another 0070 M0 manifest")
    if m3["inputs"]["real_materialization"]["materialization_digest"] != _read_json(
        real_materialization / "materialization.json", "0068 materialization"
    ).get("materialization_digest"):
        raise SyntheticVisibleRegionTrainingComparisonError(
            "M3 points to another 0068 materialization"
        )

    if not pretrained.is_file():
        raise SyntheticVisibleRegionTrainingComparisonError(
            f"pretrained checkpoint is missing: {pretrained}"
        )
    checkpoint_digest = _sha256_file(pretrained)
    for recipe, label in (
        (control, "0070 control"),
        (real_manifest["recipe"], "0068 recipe"),
    ):
        declared = recipe.get("pretrained_checkpoint", {}).get("sha256")
        if declared != checkpoint_digest:
            raise SyntheticVisibleRegionTrainingComparisonError(
                f"{label} checkpoint digest does not match the mounted checkpoint"
            )
    return m0, real_manifest, m3, {
        "m0_digest": declared_m0_digest,
        "real_manifest_digest": real_manifest_digest,
        "checkpoint_sha256": checkpoint_digest,
        "seed": int(control["training"]["seed"]),
        "recipe": dict(control),
    }


def _symlink_directory(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SyntheticVisibleRegionTrainingComparisonError(f"missing dataset partition: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source.resolve(), target_is_directory=True)


def build_synthetic_visible_region_m4_view(
    repository_root: str | Path,
    *,
    m3_manifest_path: str | Path = M3_MANIFEST_DEFAULT,
    m3_output_directory: str | Path = M3_OUTPUT_DIRECTORY_DEFAULT,
    real_materialization: str | Path = REAL_MATERIALIZATION_DEFAULT,
    real_manifest_path: str | Path = REAL_MANIFEST_DEFAULT,
    m0_manifest_path: str | Path = M0_MANIFEST_DEFAULT,
    pretrained_checkpoint: str | Path = PRETRAINED_CHECKPOINT_DEFAULT,
    output_directory: str | Path = M4_OUTPUT_DIRECTORY_DEFAULT,
) -> dict[str, Any]:
    """Create the candidate view with M3 train data and unchanged held-out files."""

    repository = Path(repository_root).expanduser().resolve()
    m3_root = _resolve(repository, m3_output_directory)
    real_root = _resolve(repository, real_materialization)
    m3_path = _resolve(repository, m3_manifest_path)
    real_manifest = _resolve(repository, real_manifest_path)
    m0_path = _resolve(repository, m0_manifest_path)
    pretrained = _resolve(repository, pretrained_checkpoint)
    output = _resolve(repository, output_directory)
    m0, frozen_real, m3, facts = _validate_m0_inputs(
        repository, m0_path, real_manifest, m3_path, real_root, pretrained
    )
    for partition in ("train", "valid", "sealed_test"):
        if not (m3_root / partition).is_dir():
            raise SyntheticVisibleRegionTrainingComparisonError(
                f"M3 training view is missing {partition}: {m3_root / partition}"
            )
    merged_train = _resolve(repository, m3["dataset"]["merged_train"]["path"])
    if _sha256_file(merged_train) != m3["dataset"]["merged_train"]["sha256"]:
        raise SyntheticVisibleRegionTrainingComparisonError("M3 merged train COCO digest is stale")
    m3_heldout = {
        partition: m3["dataset"][partition]["unchanged_file_inventory"]
        for partition in ("validation", "sealed_test")
    }
    _verify_inventory(m3_root / "valid", m3_heldout["validation"], "M3 validation partition")
    _verify_inventory(
        m3_root / "sealed_test", m3_heldout["sealed_test"], "M3 sealed-test partition"
    )

    if output.exists() and any(output.iterdir()):
        materialization = output / "materialization.json"
        if materialization.is_file():
            return {
                "root": output,
                "materialization": _read_json(materialization, "M4 candidate materialization"),
                "reused": True,
                "facts": facts,
            }
        raise SyntheticVisibleRegionTrainingComparisonError(f"M4 view is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    for partition in ("train", "valid", "sealed_test"):
        _symlink_directory(m3_root / partition, output / partition)
    for filename in ("split.json", "exclusions.json"):
        source = real_root / filename
        if not source.is_file():
            raise SyntheticVisibleRegionTrainingComparisonError(
                f"0068 receipt is missing: {source}"
            )
        (output / filename).symlink_to(source.resolve())

    base_materialization = _read_json(real_root / "materialization.json", "0068 materialization")
    base_core = {
        key: value
        for key, value in base_materialization.items()
        if key not in {"materialization_digest", "generated_files"}
    }
    counts = dict(base_core.get("counts", {}))
    synthetic_coco = _read_json(merged_train, "M3 merged train COCO")
    real_coco = _read_json(real_root / "train" / "_annotations.coco.json", "0068 train COCO")
    synthetic_image_count = len(synthetic_coco["images"]) - len(real_coco["images"])
    synthetic_annotation_count = len(synthetic_coco["annotations"]) - len(real_coco["annotations"])
    counts.update(
        {
            "train_images": len(synthetic_coco["images"]),
            "train_annotations": len(synthetic_coco["annotations"]),
            "images": int(base_core["counts"]["images"]) + synthetic_image_count,
            "annotations": int(base_core["counts"]["annotations"]) + synthetic_annotation_count,
        }
    )
    base_core["counts"] = counts
    base_core["materializer_version"] = "synthetic-visible-region-m4-materializer/v1"
    base_core["synthetic_training_view"] = {
        "manifest_digest": m3["manifest_digest"],
        "file_sha256": _sha256_file(m3_path),
        "path": _relative(m3_path, repository),
        "real_train_coco_sha256": _sha256_file(real_root / "train" / "_annotations.coco.json"),
        "merged_train_coco_sha256": _sha256_file(merged_train),
    }
    generated_files: list[dict[str, Any]] = []
    for relative in ("split.json", "exclusions.json"):
        target = output / relative
        generated_files.append({"path": relative, "sha256": _sha256_file(target)})
    for partition in ("train", "valid", "sealed_test"):
        for item in sorted(path for path in (output / partition).rglob("*") if path.is_file()):
            relative = item.relative_to(output).as_posix()
            generated_files.append({"path": relative, "sha256": _sha256_file(item)})
    base_core["generated_files"] = generated_files
    base_core["synthetic_training_view"]["generated_file_count"] = len(generated_files)
    materialization = {
        **base_core,
        "materialization_digest": _digest(base_core),
    }
    _write_json(output / "materialization.json", materialization)
    return {"root": output, "materialization": materialization, "reused": False, "facts": facts}


def _assert_prediction_reproducible(artifact: Mapping[str, Any]) -> None:
    from table_evidence_analyzer.rfdetr_segmentation_evaluation import calculate_metrics

    frames = artifact.get("frames")
    metrics = artifact.get("metrics", {}).get("overall")
    if not isinstance(frames, list) or not isinstance(metrics, Mapping):
        raise SyntheticVisibleRegionTrainingComparisonError("prediction artifact is incomplete")
    if dict(calculate_metrics(frames)) != dict(metrics):
        raise SyntheticVisibleRegionTrainingComparisonError(
            f"metrics do not reproduce from retained {artifact.get('model_id')} predictions"
        )


def _peak_mps_bytes(run: Mapping[str, Any]) -> int | None:
    bundle_path = run.get("bundle", {}).get("path")
    if not isinstance(bundle_path, str):
        return None
    telemetry = Path(bundle_path).parent / "rfdetr" / "mps-memory.jsonl"
    if not telemetry.is_file():
        return None
    values: list[int] = []
    for line in telemetry.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("active_bytes", "driver_bytes"):
            if isinstance(row.get(key), int):
                values.append(int(row[key]))
    return max(values, default=None)


def _run_record_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "duration_seconds": run.get("duration_seconds"),
        "budget_seconds": run.get("budget_seconds"),
        "resource_facts": run.get("resource_facts"),
        "peak_telemetry_bytes": _peak_mps_bytes(run),
        "training_arguments": run.get("training_arguments"),
        "dataset": run.get("dataset"),
        "bundle": run.get("bundle"),
        "checkpoint": run.get("checkpoint"),
    }


def _quality_outcome(control: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    metrics = ("mask_ap_50_95", "recall", "false_predictions", "duplicate_predictions")
    control_overall = control["metrics"]["overall"]
    candidate_overall = candidate["metrics"]["overall"]
    deltas = {
        metric: round(float(candidate_overall[metric]) - float(control_overall[metric]), 6)
        for metric in metrics
    }
    primary_positive = deltas["mask_ap_50_95"] > 0 or deltas["recall"] > 0
    primary_negative = deltas["mask_ap_50_95"] < 0 and deltas["recall"] < 0
    outcome = "improved" if primary_positive and not primary_negative else (
        "harmed" if primary_negative else "no_clear_change"
    )
    return {"outcome": outcome, "deltas_vs_control": deltas}


def run_synthetic_visible_region_m4_comparison(
    repository_root: str | Path,
    *,
    m0_manifest_path: str | Path = M0_MANIFEST_DEFAULT,
    real_manifest_path: str | Path = REAL_MANIFEST_DEFAULT,
    m3_manifest_path: str | Path = M3_MANIFEST_DEFAULT,
    real_materialization: str | Path = REAL_MATERIALIZATION_DEFAULT,
    m3_output_directory: str | Path = M3_OUTPUT_DIRECTORY_DEFAULT,
    pretrained_checkpoint: str | Path = PRETRAINED_CHECKPOINT_DEFAULT,
    output_directory: str | Path = M4_OUTPUT_DIRECTORY_DEFAULT,
    report_path: str | Path = M4_REPORT_DEFAULT,
    runner: Literal["fixture", "rfdetr"] = "rfdetr",
    device: Literal["cpu", "mps", "cuda"] = "mps",
) -> dict[str, Any]:
    """Train the two frozen candidates and compare them on the real validation partition."""

    repository = Path(repository_root).expanduser().resolve()
    output = _resolve(repository, output_directory)
    destination_report = _resolve(repository, report_path)
    if destination_report.is_file():
        report = _read_json(destination_report, "M4 comparison report")
        if report.get("schema_version") != M4_SCHEMA_VERSION:
            raise SyntheticVisibleRegionTrainingComparisonError(
                "existing M4 report has another schema"
            )
        return report
    m0, real_manifest, m3, facts = _validate_m0_inputs(
        repository,
        _resolve(repository, m0_manifest_path),
        _resolve(repository, real_manifest_path),
        _resolve(repository, m3_manifest_path),
        _resolve(repository, real_materialization),
        _resolve(repository, pretrained_checkpoint),
    )
    view = build_synthetic_visible_region_m4_view(
        repository,
        m0_manifest_path=m0_manifest_path,
        real_manifest_path=real_manifest_path,
        m3_manifest_path=m3_manifest_path,
        real_materialization=real_materialization,
        m3_output_directory=m3_output_directory,
        pretrained_checkpoint=pretrained_checkpoint,
        output_directory=output / M4_SYNTHETIC_VIEW_DIRECTORY,
    )
    from table_evidence_analyzer.rfdetr_segmentation_training import (
        RfdetrSegmentationCampaignTrainingConfig,
        run_rfdetr_segmentation_campaign_training,
    )

    started = time.monotonic()
    control_output = output / "control"
    candidate_output = output / "synthetic-addition"
    real_root = _resolve(repository, real_materialization)
    frozen_real_manifest = _resolve(repository, real_manifest_path)
    control_run = run_rfdetr_segmentation_campaign_training(
        RfdetrSegmentationCampaignTrainingConfig(
            dataset_dir=real_root,
            campaign_manifest=frozen_real_manifest,
            pretrained_checkpoint=_resolve(repository, pretrained_checkpoint),
            output_dir=control_output,
            runner=runner,
            device=device,
            seed=facts["seed"],
        )
    )
    candidate_run = run_rfdetr_segmentation_campaign_training(
        RfdetrSegmentationCampaignTrainingConfig(
            dataset_dir=view["root"],
            campaign_manifest=frozen_real_manifest,
            pretrained_checkpoint=_resolve(repository, pretrained_checkpoint),
            output_dir=candidate_output,
            runner=runner,
            device=device,
            seed=facts["seed"],
        )
    )
    if runner == "fixture":
        raise SyntheticVisibleRegionTrainingComparisonError(
            "fixture training is contract-only; M4 evaluation requires the rfdetr runner"
        )

    from table_evidence_analyzer.rfdetr_segmentation_evaluation import (
        _evaluate_model,
        _load_materialization_view,
    )
    from table_evidence_analyzer.rfdetr_segmentation_training import load_rfdetr_segmentation_bundle

    evaluation_dir = output / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    real_view = _load_materialization_view(real_root)
    pretrained_path = _resolve(repository, pretrained_checkpoint)
    control_bundle = load_rfdetr_segmentation_bundle(control_run["bundle"]["path"])
    candidate_bundle = load_rfdetr_segmentation_bundle(candidate_run["bundle"]["path"])
    artifacts: dict[str, dict[str, Any]] = {}
    for key, checkpoint, pretrained_flag in (
        ("pretrained_validation", pretrained_path, True),
        ("control_validation", control_bundle.checkpoint_path, False),
        ("synthetic_validation", candidate_bundle.checkpoint_path, False),
    ):
        artifact = _evaluate_model(
            checkpoint,
            real_view,
            device,
            model_id=key,
            pretrained=pretrained_flag,
            partition="valid",
        )
        _assert_prediction_reproducible(artifact)
        path = evaluation_dir / f"{key}-predictions.json"
        _write_json(path, artifact)
        artifacts[key] = {
            "path": _relative(path, repository),
            "sha256": _sha256_file(path),
            "metrics": artifact["metrics"],
        }
    baseline_metrics = artifacts["pretrained_validation"]["metrics"]["overall"]
    synthetic_metrics = artifacts["synthetic_validation"]["metrics"]["overall"]
    validation_gate = {
        "beats_pretrained_mask_ap_50_95": synthetic_metrics["mask_ap_50_95"]
        > baseline_metrics["mask_ap_50_95"],
        "beats_pretrained_recall": synthetic_metrics["recall"] > baseline_metrics["recall"],
    }
    sealed: dict[str, Any] | None = None
    if all(validation_gate.values()):
        artifact = _evaluate_model(
            candidate_bundle.checkpoint_path,
            real_view,
            device,
            model_id="synthetic_sealed_test",
            pretrained=False,
            partition="sealed_test",
        )
        _assert_prediction_reproducible(artifact)
        path = evaluation_dir / "synthetic-sealed-test-predictions.json"
        _write_json(path, artifact)
        artifact_meta = {
            "path": _relative(path, repository),
            "sha256": _sha256_file(path),
            "metrics": artifact["metrics"],
        }
        sealed = {
            "evaluated": True,
            "artifact": artifact_meta,
            "nonzero_recall_per_recording": all(
                metrics["recall"] > 0
                for metrics in artifact["metrics"]["by_recording"].values()
            ),
        }
        sealed["passes"] = bool(sealed["nonzero_recall_per_recording"])
    else:
        sealed = {
            "evaluated": False,
            "passes": False,
            "reason": "synthetic_candidate_did_not_pass_validation_gate",
        }
    comparison = _quality_outcome(
        artifacts["control_validation"], artifacts["synthetic_validation"]
    )
    report_core = {
        "schema_version": M4_SCHEMA_VERSION,
        "campaign_id": M4_CAMPAIGN_ID,
        "milestone": "M4",
        "status": "completed",
        "freeze_state": "complete_with_declared_m0_gap",
        "inputs": {
            "m0": {
                "path": _relative(_resolve(repository, m0_manifest_path), repository),
                "manifest_digest": facts["m0_digest"],
                "file_sha256": _sha256_file(_resolve(repository, m0_manifest_path)),
            },
            "0068_manifest": {
                "path": _relative(frozen_real_manifest, repository),
                "manifest_digest": facts["real_manifest_digest"],
                "file_sha256": _sha256_file(frozen_real_manifest),
            },
            "m3": {
                "path": _relative(_resolve(repository, m3_manifest_path), repository),
                "manifest_digest": m3["manifest_digest"],
                "file_sha256": _sha256_file(_resolve(repository, m3_manifest_path)),
                "merged_train_sha256": m3["dataset"]["merged_train"]["sha256"],
            },
            "pretrained_checkpoint": {
                "path": _relative(pretrained_path, repository),
                "sha256": facts["checkpoint_sha256"],
            },
        },
        "recipe": {
            "seed": facts["seed"],
            "control": facts["recipe"],
            "synthetic_addition": m0["recipe"]["trainer"]["synthetic_addition"],
            "same_model_and_optimizer_recipe": True,
            "real_sample_order_unchanged": True,
        },
        "views": {
            "control": {
                "root": _relative(real_root, repository),
                "materialization_digest": _read_json(
                    real_root / "materialization.json", "0068 materialization"
                )["materialization_digest"],
            },
            "synthetic_addition": {
                "root": _relative(view["root"], repository),
                "materialization_digest": view["materialization"]["materialization_digest"],
                "synthetic_image_count": m3["dataset"]["synthetic"]["images"],
                "synthetic_annotation_count": m3["dataset"]["synthetic"]["annotations"],
            },
        },
        "runs": {
            "control": _run_record_summary(control_run),
            "synthetic_addition": _run_record_summary(candidate_run),
        },
        "evaluation": {
            "real_validation_partition": True,
            "validation_gate": {**validation_gate, "passes": all(validation_gate.values())},
            "artifacts": artifacts,
            "sealed_test": sealed,
            "comparison": comparison,
        },
        "compute": {
            "added_train_images": m3["dataset"]["synthetic"]["images"],
            "added_train_annotations": m3["dataset"]["synthetic"]["annotations"],
            "added_optimizer_steps_estimate": m3["dataset"]["synthetic"]["images"]
            * int(facts["recipe"]["training"]["epochs"])
            // int(facts["recipe"]["training"]["grad_accum_steps"]),
            "control_duration_seconds": control_run.get("duration_seconds"),
            "synthetic_duration_seconds": candidate_run.get("duration_seconds"),
            "total_wall_clock_seconds": round(time.monotonic() - started, 3),
            "platform": platform.platform(),
        },
        "coverage_gaps": list(m3["coverage_gaps"]),
    }
    report = {**report_core, "manifest_digest": _digest(report_core)}
    _write_json(destination_report, report)
    return report


def render_synthetic_visible_region_m4_human(report: Mapping[str, Any]) -> str:
    evaluation = report["evaluation"]
    comparison = evaluation["comparison"]
    return "\n".join(
        (
            "Synthetic visible-region training data M4",
            f"status: {report['status']}",
            f"validation gate: {evaluation['validation_gate']['passes']}",
            f"sealed test evaluated: {evaluation['sealed_test']['evaluated']}",
            f"outcome: {comparison['outcome']}",
            f"control duration seconds: {report['compute']['control_duration_seconds']}",
            f"synthetic duration seconds: {report['compute']['synthetic_duration_seconds']}",
            f"manifest digest: {report['manifest_digest']}",
        )
    ) + "\n"


__all__ = [
    "M0_MANIFEST_DEFAULT",
    "M4_CAMPAIGN_ID",
    "M4_OUTPUT_DIRECTORY_DEFAULT",
    "M4_REPORT_DEFAULT",
    "M4_SCHEMA_VERSION",
    "M4_SYNTHETIC_VIEW_DIRECTORY",
    "REAL_MANIFEST_DEFAULT",
    "REAL_MATERIALIZATION_DEFAULT",
    "PRETRAINED_CHECKPOINT_DEFAULT",
    "SyntheticVisibleRegionTrainingComparisonError",
    "build_synthetic_visible_region_m4_view",
    "render_synthetic_visible_region_m4_human",
    "run_synthetic_visible_region_m4_comparison",
]
