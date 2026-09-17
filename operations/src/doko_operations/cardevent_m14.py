"""Lock the CardEventNet M9 development baseline and prepare M14 handoffs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .cardevent_m12 import M12_GATES
from .cardevent_m13 import evaluate_cardeventnet_m13_gates
from .model_improvement import sha256_mapping

M14_SCHEMA_VERSION = "cardeventnet-m14-development-integration/v1"
M14_LOCK_SCHEMA_VERSION = "cardeventnet-m14-integration-lock/v1"
M14_SEALED_TEST_SCHEMA_VERSION = "cardeventnet-m14-sealed-test-handoff/v1"
M14_EXPORT_SCHEMA_VERSION = "cardeventnet-m14-coreml-export-parity-handoff/v1"
M14_CAMPAIGN_ID = "cardeventnet-0063-m14-development-integration"
M14_SOURCE_CAMPAIGN_ID = "cardeventnet-0063-m9-hard-negative-ablation"
M14_M13_CAMPAIGN_ID = "cardeventnet-0063-m12-timing-response"
M14_CANDIDATE_ID = "m9_hard_negative_v1"
M14_THRESHOLD = 0.4271905720233917
M14_PEAK_CONFIRMATION_S = 0.125
M14_MIN_EVENT_GAP_S = 0.625

M14_DECISION_RATIONALE = (
    "Accept the M9 hard-negative checkpoint as the development baseline so end-to-end "
    "table-observation and game-reconstruction work can measure the cost of its remaining "
    "errors. This is an explicit engineering acceptance of a known validation result, not a "
    "production promotion decision."
)


class CardEventM14Error(ValueError):
    """Raised when the M9 baseline cannot support the M14 integration lock."""


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM14Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM14Error(f"{context} {path} must contain an object")
    return dict(value)


def _read_yaml(path: Path, context: str) -> dict[str, Any]:
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError) as error:
        raise CardEventM14Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM14Error(f"{context} {path} must contain an object")
    return dict(value)


def _sha256_file(path: Path, context: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise CardEventM14Error(f"Could not hash {context} {path}: {error}") from error
    return digest.hexdigest()


def _required(path: Path, context: str) -> Path:
    if not path.is_file():
        raise CardEventM14Error(f"{context} is missing: {path}")
    return path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise CardEventM14Error(f"path must stay inside the repository: {path}") from error


def _write_immutable(path: Path, payload: bytes, context: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise CardEventM14Error(f"immutable M14 artifact differs: {path}")
    if not path.exists():
        path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any], context: str) -> str:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return _write_immutable(path, payload, context)


def _file_ref(root: Path, path: Path, context: str) -> dict[str, str]:
    _required(path, context)
    return {"path": _relative(root, path), "sha256": _sha256_file(path, context)}


def _verify_mapping_digest(
    payload: Mapping[str, Any], digest_key: str, context: str, *, legacy: bool = False
) -> str:
    digest = payload.get(digest_key)
    core = {key: value for key, value in payload.items() if key != digest_key}
    valid = {sha256_mapping(core)}
    if legacy:
        valid.add(hashlib.sha256(json.dumps(core, sort_keys=True).encode("utf-8")).hexdigest())
    if digest not in valid:
        raise CardEventM14Error(f"{context} digest does not match its contents")
    return str(digest)


def _decoder(config: Mapping[str, Any]) -> dict[str, Any]:
    inference = config.get("inference")
    metrics = config.get("metrics")
    if not isinstance(inference, Mapping) or not isinstance(metrics, Mapping):
        raise CardEventM14Error("M9 config has no inference or metrics section")
    decoder = {
        "algorithm": "causal_peak",
        "peak_confirmation_s": inference.get("peak_confirmation_s"),
        "min_event_gap_s": inference.get("min_event_gap_s"),
        "event_match_tolerance_s": metrics.get("event_match_tolerance_s"),
    }
    if decoder != {
        "algorithm": "causal_peak",
        "peak_confirmation_s": M14_PEAK_CONFIRMATION_S,
        "min_event_gap_s": M14_MIN_EVENT_GAP_S,
        "event_match_tolerance_s": 0.75,
    }:
        raise CardEventM14Error("M9 decoder does not match the accepted development contract")
    return decoder


def _verify_reference_revisions(root: Path, references: Any) -> list[dict[str, Any]]:
    if not isinstance(references, list) or not references:
        raise CardEventM14Error("successor validation has no reference revisions")
    normalized: list[dict[str, Any]] = []
    for reference in references:
        if not isinstance(reference, Mapping):
            raise CardEventM14Error("successor validation contains an invalid reference")
        path = _required(root / str(reference.get("path")), "successor reference")
        if _sha256_file(path, "successor reference") != reference.get("sha256"):
            raise CardEventM14Error(f"successor reference digest differs: {path}")
        normalized.append(dict(reference))
    return normalized


def _verify_baseline(root: Path, campaign_dir: Path) -> dict[str, Any]:
    handoff_path = _required(campaign_dir / "handoff.json", "M9 handoff")
    handoff = _read_json(handoff_path, "M9 handoff")
    handoff_digest = _verify_mapping_digest(handoff, "handoff_sha256", "M9 handoff", legacy=True)
    if handoff.get("schema_version") != "cardeventnet-hard-negative-ablation-handoff/v1":
        raise CardEventM14Error("M9 handoff has an unsupported schema")
    if handoff.get("status") != "ready":
        raise CardEventM14Error("M9 handoff is not ready")

    fixed_inputs = handoff.get("fixed_inputs")
    if not isinstance(fixed_inputs, Mapping):
        raise CardEventM14Error("M9 handoff has no fixed inputs")
    expected_inputs = {
        "dataset_view": (
            ".runtime/cardevent/datasets/"
            "cardeventnet-interval-dataset-2e00fe87f08e25c51aa4"
        ),
        "config": "card_event_net/configs/transition-label-v2.yaml",
        "seed": 42,
        "device": "mps",
        "precision": "fp32",
        "validation_partition": "val",
        "sealed_test": "not_read",
    }
    if dict(fixed_inputs) != expected_inputs:
        raise CardEventM14Error("M9 fixed inputs differ from the accepted baseline")

    config_path = _required(root / str(fixed_inputs["config"]), "M9 config")
    config = _read_yaml(config_path, "M9 config")
    config_ref = _file_ref(root, config_path, "M9 config")
    decoder = _decoder(config)
    if config.get("seed") != 42:
        raise CardEventM14Error("M9 config seed is not 42")

    manifest_info = handoff.get("manifest")
    if not isinstance(manifest_info, Mapping):
        raise CardEventM14Error("M9 handoff has no hard-negative manifest")
    manifest_path = _required(root / str(manifest_info.get("path")), "M9 hard-negative manifest")
    manifest_sha256 = _sha256_file(manifest_path, "M9 hard-negative manifest")
    if manifest_sha256 != manifest_info.get("sha256"):
        raise CardEventM14Error("M9 hard-negative manifest digest differs from the handoff")
    manifest = _read_json(manifest_path, "M9 hard-negative manifest")
    if (
        manifest.get("training_input") is not True
        or manifest.get("partition") != "train"
        or manifest.get("status") != "approved_for_single_axis_ablation"
        or manifest.get("hard_negative_count") != 63
    ):
        raise CardEventM14Error("M9 hard-negative manifest is not the approved 63-item input")

    m10_path = _required(campaign_dir / "m10-timing-review.json", "M10 timing review")
    m10 = _read_json(m10_path, "M10 timing review")
    if m10.get("sealed_test_read") or m10.get("system_holdout_read"):
        raise CardEventM14Error("M10 read sealed-test or system-holdout output")
    selection = m10.get("selection")
    if not isinstance(selection, Mapping):
        raise CardEventM14Error("M10 has no selected baseline")
    checkpoint_selection = selection.get("checkpoint")
    if not isinstance(checkpoint_selection, Mapping):
        raise CardEventM14Error("M10 has no selected checkpoint lineage")
    checkpoint_path = root / str(checkpoint_selection.get("path"))
    checkpoint_ref = _file_ref(root, checkpoint_path, "M9 checkpoint")
    if checkpoint_ref["sha256"] != checkpoint_selection.get("sha256"):
        raise CardEventM14Error("M9 checkpoint digest differs from M10")
    if selection.get("threshold") != M14_THRESHOLD:
        raise CardEventM14Error("M9 threshold differs from the accepted development baseline")
    if dict(selection.get("decoder", {})) != {
        "min_event_gap_s": M14_MIN_EVENT_GAP_S,
        "peak_confirmation_s": M14_PEAK_CONFIRMATION_S,
    }:
        raise CardEventM14Error("M10 decoder differs from the accepted development baseline")
    if checkpoint_ref["path"] not in handoff.get("expected_outputs", []):
        raise CardEventM14Error("M9 handoff does not name the selected checkpoint")

    threshold_path = _required(
        checkpoint_path.parent / "threshold.json", "M9 threshold artifact"
    )
    threshold = _read_json(threshold_path, "M9 threshold artifact")
    if threshold.get("threshold") != M14_THRESHOLD:
        raise CardEventM14Error("M9 threshold artifact differs from the selected threshold")
    validation_path = _required(campaign_dir / "validation-evaluation.json", "M9 validation")
    validation = _read_json(validation_path, "M9 validation")
    if (
        validation.get("checkpoint") != checkpoint_ref["path"]
        or validation.get("threshold") != M14_THRESHOLD
        or validation.get("partition") != "val"
    ):
        raise CardEventM14Error("M9 validation is not the selected validation result")
    validation_identity = validation.get("data_identity")
    m10_lineage = m10.get("lineage")
    if not isinstance(validation_identity, Mapping) or not isinstance(m10_lineage, Mapping):
        raise CardEventM14Error("M9 validation has incomplete data lineage")
    for key in ("dataset", "split"):
        if validation_identity.get(key) != m10_lineage.get(key):
            raise CardEventM14Error(f"M9 validation {key} differs from M10 lineage")

    materialization_path = root / str(m10_lineage["materialization"]["path"])
    materialization_ref = _file_ref(root, materialization_path, "M9 materialization")
    if materialization_ref["sha256"] != m10_lineage["materialization"].get("sha256"):
        raise CardEventM14Error("M9 materialization digest differs from M10")
    materialization = _read_json(materialization_path, "M9 materialization")
    if materialization.get("dataset") != m10_lineage["dataset"]:
        raise CardEventM14Error("M9 materialization uses a different dataset")
    if materialization.get("split") != m10_lineage["split"]:
        raise CardEventM14Error("M9 materialization uses a different split")

    summary_path = _required(
        checkpoint_path.parent / "summary.json", "M9 training summary"
    )
    environment_path = _required(
        checkpoint_path.parent / "environment.json", "M9 training environment"
    )
    summary = _read_json(summary_path, "M9 training summary")
    environment = _read_json(environment_path, "M9 training environment")
    if summary.get("seed") != 42 or summary.get("device") != "mps":
        raise CardEventM14Error("M9 training summary does not preserve seed and device")
    if summary.get("runtime", {}).get("precision") != "fp32":
        raise CardEventM14Error("M9 training summary does not preserve FP32 precision")
    if summary.get("environment") != environment:
        raise CardEventM14Error("M9 training summary and environment differ")
    if environment.get("git_commit") in (None, ""):
        raise CardEventM14Error("M9 training environment has no code revision")
    if summary.get("data_identity", {}).get("dataset") != m10_lineage["dataset"]:
        raise CardEventM14Error("M9 training summary uses a different dataset")
    if summary.get("data_identity", {}).get("split") != m10_lineage["split"]:
        raise CardEventM14Error("M9 training summary uses a different split")

    return {
        "handoff": handoff,
        "handoff_ref": _file_ref(root, handoff_path, "M9 handoff"),
        "handoff_digest": handoff_digest,
        "config": config,
        "config_ref": config_ref,
        "decoder": decoder,
        "manifest": manifest,
        "manifest_ref": {**manifest_info},
        "checkpoint": checkpoint_ref,
        "threshold_ref": _file_ref(root, threshold_path, "M9 threshold artifact"),
        "validation_ref": _file_ref(root, validation_path, "M9 validation"),
        "m10_ref": _file_ref(root, m10_path, "M10 timing review"),
        "m10": m10,
        "materialization_ref": materialization_ref,
        "summary_ref": _file_ref(root, summary_path, "M9 training summary"),
        "environment_ref": _file_ref(root, environment_path, "M9 training environment"),
        "environment": environment,
        "dataset_view": str(fixed_inputs["dataset_view"]),
    }


def _verify_successor(root: Path, m9: Mapping[str, Any]) -> dict[str, Any]:
    campaign_dir = root / "data/model-campaigns" / M14_M13_CAMPAIGN_ID
    m13_result_path = _required(campaign_dir / "m13-result.json", "M13 result")
    m13_result = _read_json(m13_result_path, "M13 result")
    _verify_mapping_digest(m13_result, "result_digest", "M13 result")
    if m13_result.get("schema_version") != "cardeventnet-m13-timing-comparison/v1":
        raise CardEventM14Error("M13 result has an unsupported schema")
    if (
        m13_result.get("decision", {}).get("state") != "human_review_required"
        or m13_result.get("decision", {}).get("candidate_locked") is not False
    ):
        raise CardEventM14Error("M13 does not preserve the known non-lockable timing result")
    if m13_result.get("sealed_test_read") or m13_result.get("system_holdout_read"):
        raise CardEventM14Error("M13 read sealed-test or system-holdout output")

    comparison_path = _required(campaign_dir / "m13-comparison.json", "M13 comparison")
    comparison = _read_json(comparison_path, "M13 comparison")
    if _sha256_file(comparison_path, "M13 comparison") != m13_result.get("comparison_sha256"):
        raise CardEventM14Error("M13 comparison digest differs from the result")
    comparison_core = {
        key: value for key, value in comparison.items() if key != "comparison_digest"
    }
    if comparison.get("comparison_digest") != sha256_mapping(comparison_core):
        raise CardEventM14Error("M13 comparison content digest does not match")
    contract = comparison.get("comparison_contract")
    if not isinstance(contract, Mapping) or contract.get("partition") != "val":
        raise CardEventM14Error("M13 comparison is not validation-only")
    if contract.get("sealed_test_read") or contract.get("system_holdout_read"):
        raise CardEventM14Error("M13 comparison read sealed-test or system-holdout output")

    baseline = comparison.get("baseline")
    if not isinstance(baseline, Mapping):
        raise CardEventM14Error("M13 comparison has no M9 baseline")
    if baseline.get("candidate_id") != M14_CANDIDATE_ID:
        raise CardEventM14Error("M13 comparison names a different baseline")
    baseline_checkpoint = baseline.get("checkpoint")
    if not isinstance(baseline_checkpoint, Mapping) or baseline_checkpoint != m9["checkpoint"]:
        raise CardEventM14Error("M13 comparison baseline checkpoint differs from M9")
    if baseline.get("threshold") != M14_THRESHOLD:
        raise CardEventM14Error("M13 comparison baseline threshold differs from M9")

    lineage = comparison.get("lineage")
    if not isinstance(lineage, Mapping):
        raise CardEventM14Error("M13 comparison has no successor lineage")
    successor = lineage.get("successor_dataset")
    if not isinstance(successor, Mapping):
        raise CardEventM14Error("M13 comparison has no successor dataset")
    successor_dataset_path = _required(
        root / str(successor["path"]) / "dataset.json", "successor dataset"
    )
    successor_split_path = _required(
        root / str(successor["path"]) / "split.json", "successor split"
    )
    if _sha256_file(successor_dataset_path, "successor dataset") != successor.get("dataset_sha256"):
        raise CardEventM14Error("successor dataset digest differs from M13")
    if _sha256_file(successor_split_path, "successor split") != successor.get("split_sha256"):
        raise CardEventM14Error("successor split digest differs from M13")
    split = _read_json(successor_split_path, "successor split")
    if split.get("test_sealed") is not True:
        raise CardEventM14Error("successor test partition is not sealed")
    view_path = root / str(successor["materialized_view"])
    materialization_path = _required(
        view_path / "materialization.json", "successor materialization"
    )
    materialization = _read_json(materialization_path, "successor materialization")
    if materialization.get("dataset") != {
        "id": successor["id"],
        "digest": successor["digest"],
    }:
        raise CardEventM14Error("successor materialization uses a different dataset")
    references = _verify_reference_revisions(root, lineage.get("reference_revisions"))
    if lineage.get("hard_negative_manifest") != m9["manifest_ref"]:
        raise CardEventM14Error("M13 successor lineage uses a different hard-negative manifest")

    return {
        "m13_result_ref": _file_ref(root, m13_result_path, "M13 result"),
        "m13_result": m13_result,
        "comparison_ref": _file_ref(root, comparison_path, "M13 comparison"),
        "comparison": comparison,
        "successor": dict(successor),
        "successor_dataset_ref": _file_ref(root, successor_dataset_path, "successor dataset"),
        "successor_split_ref": _file_ref(root, successor_split_path, "successor split"),
        "successor_materialization_ref": _file_ref(
            root, materialization_path, "successor materialization"
        ),
        "reference_revisions": references,
    }


def _verify_champion(root: Path) -> dict[str, Any]:
    registry_path = _required(root / "data/model-registry.json", "model registry")
    registry = _read_json(registry_path, "model registry")
    if registry.get("schema_version") != "model-registry/v1":
        raise CardEventM14Error("model registry has an unsupported schema")
    champions = registry.get("champions")
    if not isinstance(champions, list):
        raise CardEventM14Error("model registry has no champions")
    champion = next(
        (
            item
            for item in champions
            if isinstance(item, Mapping)
            and item.get("component") == "card-event-net"
            and item.get("capability") == "event-detection"
        ),
        None,
    )
    if not isinstance(champion, Mapping):
        raise CardEventM14Error("model registry has no CardEventNet champion")
    bundle_path = root / str(champion.get("bundle_path"))
    if not bundle_path.is_dir():
        raise CardEventM14Error(f"current champion bundle is missing: {bundle_path}")
    manifest_path = _required(
        bundle_path / "Manifest.json", "current champion bundle manifest"
    )
    return {
        "registry": {
            "path": _relative(root, registry_path),
            "sha256": _sha256_file(registry_path, "model registry"),
        },
        "champion": dict(champion),
        "bundle": _file_ref(root, manifest_path, "current champion bundle manifest"),
    }


def _render_report(result: Mapping[str, Any]) -> str:
    lock = result["integration_lock"]
    decision = result["decision"]
    lines = [
        "# CardEventNet M14 development integration lock",
        "",
        f"- Campaign: `{result['campaign_id']}`",
        f"- Source campaign: `{result['source_campaign_id']}`",
        f"- Decision: `{decision['state']}`",
        f"- Production promotion eligible: `{decision['production_promotion_eligible']}`",
        f"- Integration lock: `{lock['path']}`",
        "",
        "The M9 hard-negative checkpoint is accepted as a development baseline for downstream "
        "table-observation and game-reconstruction measurement. It remains separate from the "
        "production champion and is not a promotion decision.",
        "",
        "## Fixed configuration",
        "",
        f"- Checkpoint: `{result['fixed_configuration']['checkpoint']['path']}`",
        f"- Threshold: `{result['fixed_configuration']['threshold']}`",
        f"- Decoder: `{result['fixed_configuration']['decoder']}`",
        f"- Successor validation dataset: `{result['fixed_configuration']['successor_dataset']}`",
        "",
        "## Known failed production gates",
        "",
    ]
    for name in decision["failed_gate_names"]:
        gate = decision["failed_gates"][name]
        operator = ">=" if gate["comparison"] == "minimum" else "<="
        lines.append(
            f"- `{name}`: {gate['value']:.6g} {operator} {gate['limit']:.6g} failed"
        )
    lines.extend(
        [
            "",
            "## Operator order",
            "",
            "1. Run the one-time sealed-test command in `sealed-test-handoff.json` once.",
            "2. After it exits, run the Core ML export command with parity enabled in "
            "`export-parity-handoff.json`.",
            "3. Stop. M15 validates the outputs; no command in M14 promotes the model.",
            "",
            f"Sealed-test handoff: `{result['sealed_test_handoff']['path']}`",
            f"Export/parity handoff: `{result['export_parity_handoff']['path']}`",
            "",
        ]
    )
    return "\n".join(lines)


def prepare_cardeventnet_m14_integration_handoff(
    source_campaign_id: str,
    *,
    repository_root: str | Path,
    campaign_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate M9 and write the immutable M14 integration lock and handoffs."""
    root = Path(repository_root).resolve()
    campaigns = Path(campaign_root or root / "data" / "model-campaigns")
    if not campaigns.is_absolute():
        campaigns = root / campaigns
    if source_campaign_id != M14_SOURCE_CAMPAIGN_ID:
        raise CardEventM14Error(f"M14 expects source campaign {M14_SOURCE_CAMPAIGN_ID}")

    source_dir = (campaigns / source_campaign_id).resolve()
    output_dir = (campaigns / M14_CAMPAIGN_ID).resolve()
    try:
        source_dir.relative_to(root)
        output_dir.relative_to(root)
    except ValueError as error:
        raise CardEventM14Error(
            "M14 campaign directories must stay inside the repository"
        ) from error

    m9 = _verify_baseline(root, source_dir)
    successor = _verify_successor(root, m9)
    champion = _verify_champion(root)
    baseline_metrics = successor["comparison"]["baseline"]["metrics"]
    failed_gates = evaluate_cardeventnet_m13_gates(baseline_metrics, gates=M12_GATES)
    failed_gate_names = [name for name, gate in failed_gates.items() if not gate["passed"]]
    if not failed_gate_names:
        raise CardEventM14Error("M9 unexpectedly passes every production gate")

    lock_core = {
        "schema_version": M14_LOCK_SCHEMA_VERSION,
        "campaign_id": M14_CAMPAIGN_ID,
        "lock_type": "development_integration",
        "source_campaign_id": source_campaign_id,
        "candidate_id": M14_CANDIDATE_ID,
        "checkpoint": m9["checkpoint"],
        "threshold": {
            "value": M14_THRESHOLD,
            "source": "M9 validation threshold, accepted without retuning",
        },
        "decoder": {
            "algorithm": "causal_peak",
            "peak_confirmation_s": M14_PEAK_CONFIRMATION_S,
            "min_event_gap_s": M14_MIN_EVENT_GAP_S,
            "event_match_tolerance_s": 0.75,
        },
        "production_promotion_eligible": False,
        "decision": {
            "state": "accepted_development_baseline",
            "decided_on": "2026-09-17",
            "rationale": M14_DECISION_RATIONALE,
            "failed_gate_names": failed_gate_names,
            "failed_gates": failed_gates,
        },
        "training_lineage": {
            "handoff": m9["handoff_ref"],
            "handoff_digest": m9["handoff_digest"],
            "config": m9["config_ref"],
            "dataset_view": m9["dataset_view"],
            "materialization": m9["materialization_ref"],
            "hard_negative_manifest": m9["manifest_ref"],
            "checkpoint": m9["checkpoint"],
            "threshold": m9["threshold_ref"],
            "summary": m9["summary_ref"],
            "environment": m9["environment_ref"],
            "code_revision": m9["environment"]["git_commit"],
        },
        "successor_validation_lineage": {
            "m13_result": successor["m13_result_ref"],
            "m13_comparison": successor["comparison_ref"],
            "dataset": successor["successor"],
            "dataset_file": successor["successor_dataset_ref"],
            "split_file": successor["successor_split_ref"],
            "materialization": successor["successor_materialization_ref"],
            "reference_revisions": successor["reference_revisions"],
        },
        "current_champion": champion,
        "sealed_test_read": False,
        "system_holdout_read": False,
    }
    lock = {**lock_core, "lock_digest": sha256_mapping(lock_core)}
    lock_path = output_dir / "integration-lock.json"
    lock_sha256 = _write_json(lock_path, lock, "M14 integration lock")

    fixed = {
        "checkpoint": m9["checkpoint"],
        "threshold": M14_THRESHOLD,
        "decoder": lock["decoder"],
        "training_dataset": m9["m10"]["lineage"]["dataset"],
        "successor_dataset": successor["successor"],
        "successor_validation_references": successor["reference_revisions"],
        "device": "mps",
        "precision": "fp32",
    }
    sealed_dir = output_dir / "sealed-test"
    sealed_evaluation = sealed_dir / "evaluation.json"
    sealed_command = (
        "mise exec -- uv run --project card_event_net cardevent evaluate "
        f"--checkpoint {m9['checkpoint']['path']} "
        f"--dataset-view {successor['successor']['materialized_view']} "
        "--partition test "
        f"--threshold {M14_THRESHOLD} "
        f"--out {_relative(root, sealed_evaluation)} --device mps"
    )
    sealed_core = {
        "schema_version": M14_SEALED_TEST_SCHEMA_VERSION,
        "campaign_id": M14_CAMPAIGN_ID,
        "handoff_type": "one_time_sealed_test",
        "status": "pending_operator",
        "integration_lock": {
            "path": _relative(root, lock_path),
            "sha256": lock_sha256,
            "digest": lock["lock_digest"],
        },
        "fixed_inputs": fixed,
        "command": sealed_command,
        "expected_outputs": [
            _relative(root, sealed_evaluation),
            _relative(root, sealed_dir / "evaluation-transition-diagnostics.json"),
            _relative(root, sealed_dir / "validation-streams" / "evaluation.json.gz"),
            _relative(root, sealed_dir / "evaluation-plots"),
        ],
        "one_time_policy": {
            "maximum_evaluations": 1,
            "evaluation_count_before_operator": 0,
            "tuning_allowed": False,
            "threshold_source": "integration_lock",
            "configuration_changes_allowed": False,
            "rerun_after_success_allowed": False,
        },
        "resume_behavior": (
            "Do not resume or rerun this evaluation. Preserve an interrupted or failed run "
            "for M15 review."
        ),
        "sealed_test_read_before_command": False,
        "system_holdout_read": False,
    }
    sealed_handoff = {**sealed_core, "handoff_digest": sha256_mapping(sealed_core)}
    sealed_path = output_dir / "sealed-test-handoff.json"
    sealed_sha256 = _write_json(sealed_path, sealed_handoff, "M14 sealed-test handoff")

    export_dir = output_dir / "integration-model"
    bundle_path = export_dir / "CardEventNet.mlpackage"
    export_core = {
        "schema_version": M14_EXPORT_SCHEMA_VERSION,
        "campaign_id": M14_CAMPAIGN_ID,
        "handoff_type": "integration_model_export_and_parity",
        "status": "pending_operator",
        "integration_lock": {
            "path": _relative(root, lock_path),
            "sha256": lock_sha256,
            "digest": lock["lock_digest"],
        },
        "fixed_inputs": {
            "checkpoint": m9["checkpoint"],
            "preprocessing": "full_frame_letterbox_v1",
            "coreml_input_shape": [1, 8, 3, 224, 224],
            "coreml_input_name": "clips",
            "coreml_output_name": "logit",
        },
        "command": (
            "mise exec -- uv run --project card_event_net cardevent export-coreml "
            f"--checkpoint {m9['checkpoint']['path']} --out {_relative(root, bundle_path)}"
        ),
        "expected_outputs": [_relative(root, bundle_path)],
        "parity": {
            "required": True,
            "skip_parity_allowed": False,
            "tolerance": {"atol": 0.001, "rtol": 0.001},
            "success_output": "Parity check passed",
        },
        "artifact_role": "development_integration_model",
        "production_promotion_eligible": False,
        "resume_behavior": (
            "Export has no resume mode. Preserve the lock and do not change the checkpoint "
            "or export contract on retry."
        ),
        "sealed_test_read": False,
        "system_holdout_read": False,
    }
    export_handoff = {**export_core, "handoff_digest": sha256_mapping(export_core)}
    export_path = output_dir / "export-parity-handoff.json"
    export_sha256 = _write_json(export_path, export_handoff, "M14 export/parity handoff")

    result_core = {
        "schema_version": M14_SCHEMA_VERSION,
        "campaign_id": M14_CAMPAIGN_ID,
        "source_campaign_id": source_campaign_id,
        "state": "ready_for_operator",
        "decision": {
            "state": "accepted_development_baseline",
            "candidate_id": M14_CANDIDATE_ID,
            "rationale": M14_DECISION_RATIONALE,
            "production_promotion_eligible": False,
            "failed_gate_names": failed_gate_names,
            "failed_gates": failed_gates,
        },
        "fixed_configuration": fixed,
        "integration_lock": {
            "path": _relative(root, lock_path),
            "sha256": lock_sha256,
            "digest": lock["lock_digest"],
        },
        "sealed_test_handoff": {
            "path": _relative(root, sealed_path),
            "sha256": sealed_sha256,
            "digest": sealed_handoff["handoff_digest"],
            "maximum_evaluations": 1,
        },
        "export_parity_handoff": {
            "path": _relative(root, export_path),
            "sha256": export_sha256,
            "digest": export_handoff["handoff_digest"],
        },
        "operator_order": ["sealed_test", "export_and_parity"],
        "long_commands_started": False,
        "sealed_test_read": False,
        "system_holdout_read": False,
        "current_champion_changed": False,
        "promotion_receipt_written": False,
    }
    result = {**result_core, "result_digest": sha256_mapping(result_core)}
    result_path = output_dir / "m14-result.json"
    result_sha256 = _write_json(result_path, result, "M14 result")

    report_path = output_dir / "m14-report.md"
    report_sha256 = _write_immutable(
        report_path,
        _render_report(result).encode(),
        "M14 report",
    )
    result["result_path"] = _relative(root, result_path)
    result["result_sha256"] = result_sha256
    result["report_path"] = _relative(root, report_path)
    result["report_sha256"] = report_sha256
    return result


def render_cardeventnet_m14_human(result: Mapping[str, Any]) -> str:
    """Render a concise M14 CLI result."""

    return (
        "CardEventNet M14 development integration\n"
        f"campaign: {result['campaign_id']}\n"
        f"state: {result['state']}\n"
        f"candidate: {result['decision']['candidate_id']}\n"
        f"production promotion eligible: {result['decision']['production_promotion_eligible']}\n"
        f"integration lock: {result['integration_lock']['path']}\n"
        f"sealed-test handoff: {result['sealed_test_handoff']['path']}\n"
        f"export/parity handoff: {result['export_parity_handoff']['path']}\n"
        "long commands started: false\n"
    )


__all__ = [
    "CardEventM14Error",
    "M14_CAMPAIGN_ID",
    "M14_SCHEMA_VERSION",
    "prepare_cardeventnet_m14_integration_handoff",
    "render_cardeventnet_m14_human",
]
