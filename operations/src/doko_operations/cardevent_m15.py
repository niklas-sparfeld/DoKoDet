"""Validate the CardEventNet M14 integration handoffs and close epic 0063."""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .model_improvement import sha256_mapping

M15_SCHEMA_VERSION = "cardeventnet-m15-integration-closeout/v1"
M15_CONTRACT_SCHEMA_VERSION = "cardeventnet-m15-integration-contract/v1"
M15_RUNTIME_SCHEMA_VERSION = "cardeventnet-m15-runtime-checks/v1"
M15_CAMPAIGN_ID = "cardeventnet-0063-m14-development-integration"
M15_SOURCE_CAMPAIGN_ID = "cardeventnet-0063-m9-hard-negative-ablation"
M15_DECODER = {
    "algorithm": "causal_peak",
    "peak_confirmation_s": 0.125,
    "min_event_gap_s": 0.625,
    "event_match_tolerance_s": 0.75,
}
M15_THRESHOLD = 0.4271905720233917
M15_INPUT_SHAPE = [1, 8, 3, 224, 224]
M15_RUNTIME_ATOL = 0.001


class CardEventM15Error(ValueError):
    """Raised when the M14 operator outputs cannot close the campaign."""


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM15Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM15Error(f"{context} {path} must contain an object")
    return dict(value)


def _required(path: Path, context: str) -> Path:
    if not path.is_file():
        raise CardEventM15Error(f"{context} is missing: {path}")
    return path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise CardEventM15Error(f"path must stay inside the repository: {path}") from error


def _sha256_file(path: Path, context: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise CardEventM15Error(f"Could not hash {context} {path}: {error}") from error
    return digest.hexdigest()


def _write_immutable(path: Path, payload: bytes, context: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise CardEventM15Error(f"immutable M15 artifact differs: {path}")
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


def _verify_digest(payload: Mapping[str, Any], key: str, context: str) -> str:
    digest = payload.get(key)
    core = {name: value for name, value in payload.items() if name != key}
    if digest != sha256_mapping(core):
        raise CardEventM15Error(f"{context} digest does not match its contents")
    return str(digest)


def _verify_ref(root: Path, reference: Mapping[str, Any], context: str) -> Path:
    path = _required(root / str(reference.get("path")), context)
    actual = _sha256_file(path, context)
    if actual != reference.get("sha256"):
        raise CardEventM15Error(f"{context} digest differs: {path}")
    return path


def _load_m14(root: Path, campaign_dir: Path) -> dict[str, Any]:
    lock_path = _required(campaign_dir / "integration-lock.json", "M14 integration lock")
    lock = _read_json(lock_path, "M14 integration lock")
    _verify_digest(lock, "lock_digest", "M14 integration lock")
    if lock.get("schema_version") != "cardeventnet-m14-integration-lock/v1":
        raise CardEventM15Error("M14 integration lock has an unsupported schema")
    if lock.get("campaign_id") != M15_CAMPAIGN_ID:
        raise CardEventM15Error("M14 integration lock has the wrong campaign")
    if lock.get("source_campaign_id") != M15_SOURCE_CAMPAIGN_ID:
        raise CardEventM15Error("M14 integration lock has the wrong source campaign")
    if lock.get("threshold", {}).get("value") != M15_THRESHOLD:
        raise CardEventM15Error("M14 threshold is not the accepted locked value")
    if dict(lock.get("decoder", {})) != M15_DECODER:
        raise CardEventM15Error("M14 decoder differs from the accepted locked decoder")
    if lock.get("production_promotion_eligible") is not False:
        raise CardEventM15Error("M14 baseline must remain ineligible for production promotion")
    if lock.get("sealed_test_read") or lock.get("system_holdout_read"):
        raise CardEventM15Error("M14 lock claims a sealed-test or system-holdout read")

    sealed_path = _required(campaign_dir / "sealed-test-handoff.json", "M14 sealed-test handoff")
    sealed = _read_json(sealed_path, "M14 sealed-test handoff")
    _verify_digest(sealed, "handoff_digest", "M14 sealed-test handoff")
    if sealed.get("status") != "pending_operator":
        raise CardEventM15Error("M14 sealed-test handoff was changed after it was locked")
    if sealed.get("one_time_policy") != {
        "configuration_changes_allowed": False,
        "evaluation_count_before_operator": 0,
        "maximum_evaluations": 1,
        "rerun_after_success_allowed": False,
        "threshold_source": "integration_lock",
        "tuning_allowed": False,
    }:
        raise CardEventM15Error("M14 sealed-test handoff no longer has its one-time policy")
    if sealed.get("integration_lock", {}).get("digest") != lock["lock_digest"]:
        raise CardEventM15Error("M14 sealed-test handoff is not bound to the lock")

    export_path = _required(campaign_dir / "export-parity-handoff.json", "M14 export handoff")
    export = _read_json(export_path, "M14 export handoff")
    _verify_digest(export, "handoff_digest", "M14 export handoff")
    if export.get("status") != "pending_operator":
        raise CardEventM15Error("M14 export handoff was changed after it was locked")
    if export.get("artifact_role") != "development_integration_model":
        raise CardEventM15Error("M14 export does not identify an integration model")
    if export.get("production_promotion_eligible") is not False:
        raise CardEventM15Error("M14 export is unexpectedly promotion-eligible")
    if export.get("parity", {}).get("skip_parity_allowed") is not False:
        raise CardEventM15Error("M14 export allows parity to be skipped")
    if export.get("integration_lock", {}).get("digest") != lock["lock_digest"]:
        raise CardEventM15Error("M14 export handoff is not bound to the lock")

    result_path = _required(campaign_dir / "m14-result.json", "M14 result")
    result = _read_json(result_path, "M14 result")
    _verify_digest(result, "result_digest", "M14 result")
    if result.get("state") != "ready_for_operator":
        raise CardEventM15Error("M14 result is not ready for operator completion")
    if result.get("sealed_test_read") or result.get("system_holdout_read"):
        raise CardEventM15Error("M14 result claims a forbidden read")
    if result.get("current_champion_changed") or result.get("promotion_receipt_written"):
        raise CardEventM15Error("M14 changed the production champion or wrote a promotion receipt")

    return {
        "lock": lock,
        "lock_ref": _file_ref(root, lock_path, "M14 integration lock"),
        "sealed": sealed,
        "sealed_ref": _file_ref(root, sealed_path, "M14 sealed-test handoff"),
        "export": export,
        "export_ref": _file_ref(root, export_path, "M14 export handoff"),
        "result": result,
        "result_ref": _file_ref(root, result_path, "M14 result"),
    }


def _verify_sealed_test(root: Path, campaign_dir: Path, m14: Mapping[str, Any]) -> dict[str, Any]:
    sealed_dir = campaign_dir / "sealed-test"
    evaluation_path = _required(sealed_dir / "evaluation.json", "sealed-test evaluation")
    evaluation = _read_json(evaluation_path, "sealed-test evaluation")
    lock = m14["lock"]
    successor = lock["successor_validation_lineage"]["dataset"]
    if evaluation.get("partition") != "test":
        raise CardEventM15Error("sealed-test evaluation does not use the test partition")
    if evaluation.get("threshold") != M15_THRESHOLD:
        raise CardEventM15Error("sealed-test evaluation threshold differs from the lock")
    checkpoint = lock["checkpoint"]
    if evaluation.get("checkpoint") != checkpoint["path"]:
        raise CardEventM15Error("sealed-test evaluation checkpoint differs from the lock")
    if evaluation.get("threshold_source") != "validation":
        raise CardEventM15Error(
            "sealed-test evaluation does not identify validation threshold lineage"
        )

    identity = evaluation.get("data_identity")
    if not isinstance(identity, Mapping):
        raise CardEventM15Error("sealed-test evaluation has no data identity")
    if identity.get("dataset") != {"id": successor["id"], "digest": successor["digest"]}:
        raise CardEventM15Error("sealed-test evaluation dataset differs from the lock")
    if identity.get("split") != {"id": successor["split_id"], "digest": successor["split_digest"]}:
        raise CardEventM15Error("sealed-test evaluation split differs from the lock")
    if identity.get("materializer", {}).get("manifest_digest") != successor[
        "materialization_manifest_digest"
    ]:
        raise CardEventM15Error("sealed-test evaluation materialization differs from the lock")
    if identity.get("preprocessing") != "full_frame_letterbox_v1":
        raise CardEventM15Error("sealed-test evaluation preprocessing differs from the contract")
    if identity.get("event_references") != lock["successor_validation_lineage"][
        "reference_revisions"
    ]:
        raise CardEventM15Error("sealed-test evaluation references differ from the lock")

    split_path = _required(root / successor["path"] / "split.json", "successor split")
    split = _read_json(split_path, "successor split")
    if split.get("test_sealed") is not True:
        raise CardEventM15Error("sealed-test partition is not sealed")
    expected_videos = list(split.get("test", []))
    videos = evaluation.get("videos")
    if not isinstance(videos, list) or [item.get("video") for item in videos] != expected_videos:
        raise CardEventM15Error("sealed-test evaluation videos differ from the sealed split")

    overall = evaluation.get("overall")
    if not isinstance(overall, Mapping) or int(overall.get("videos", -1)) != len(expected_videos):
        raise CardEventM15Error("sealed-test evaluation has incomplete aggregate metrics")

    expected_outputs = m14["sealed"]["expected_outputs"]
    output_refs: list[dict[str, str]] = []
    for output in expected_outputs:
        path = root / str(output)
        if path.is_dir():
            files = sorted(item for item in path.rglob("*") if item.is_file())
            if not files:
                raise CardEventM15Error(f"sealed-test output directory is empty: {path}")
            output_refs.extend(_file_ref(root, item, "sealed-test output") for item in files)
        else:
            output_refs.append(_file_ref(root, path, "sealed-test output"))

    validation_stream_path = _required(
        sealed_dir / "validation-streams" / "evaluation.json.gz", "validation stream"
    )
    try:
        with gzip.open(validation_stream_path, "rt", encoding="utf-8") as stream:
            validation_stream = json.load(stream)
    except (OSError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError) as error:
        raise CardEventM15Error(
            f"Could not read validation stream {validation_stream_path}: {error}"
        ) from error
    if validation_stream.get("format") != "cardevent-validation-stream-v1":
        raise CardEventM15Error("validation stream has an unsupported format")
    validation_names = [item.get("video") for item in validation_stream.get("videos", [])]
    if validation_names != list(split.get("validation", [])):
        raise CardEventM15Error("validation stream does not match the successor validation split")

    return {
        "evaluation": evaluation,
        "evaluation_ref": _file_ref(root, evaluation_path, "sealed-test evaluation"),
        "outputs": output_refs,
        "validation_stream_ref": _file_ref(root, validation_stream_path, "validation stream"),
        "validation_stream_partition": "val",
        "sealed_test_partition": "test",
        "sealed_test_recordings": expected_videos,
    }


def _bundle_files(root: Path, bundle: Path) -> tuple[list[dict[str, str]], str]:
    if not bundle.is_dir():
        raise CardEventM15Error(f"Core ML integration bundle is missing: {bundle}")
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    if not files:
        raise CardEventM15Error("Core ML integration bundle is empty")
    refs = [_file_ref(root, path, "Core ML bundle file") for path in files]
    return refs, sha256_mapping({"files": refs})


def _run_runtime_parity(root: Path, checkpoint: Path, bundle: Path) -> dict[str, Any]:
    """Load the exported package and compare it with the locked checkpoint."""
    script = r'''
import json
import sys
from pathlib import Path

import coremltools as ct
import torch

from cardevent.export_coreml import deterministic_sample, verify_coreml_parity
from cardevent.infer import load_checkpoint

checkpoint = Path(sys.argv[1])
bundle = Path(sys.argv[2])
loaded = load_checkpoint(checkpoint, device_override="cpu")
sample = deterministic_sample(seed=42)
with torch.inference_mode():
    expected = loaded.model(sample).detach().cpu().reshape(-1)
model = ct.models.MLModel(str(bundle))
spec = model.get_spec()
input_description = spec.description.input[0]
output_description = spec.description.output[0]
max_abs_error = verify_coreml_parity(model, sample, expected, atol=0.001, rtol=0.001)
print(json.dumps({
    "schema_version": "cardeventnet-m15-runtime-checks/v1",
    "status": "passed",
    "method": "coremltools.MLModel_and_deterministic_sample",
    "input_name": input_description.name,
    "input_shape": [int(value) for value in input_description.type.multiArrayType.shape],
    "output_name": output_description.name,
    "expected_logit": float(expected[0]),
    "max_abs_error": float(max_abs_error),
    "atol": 0.001,
    "rtol": 0.001,
    "preprocessing": model.user_defined_metadata.get("com.doko-detector.cardevent.preprocessing"),
}, sort_keys=True))
'''
    command = [
        "mise",
        "exec",
        "--",
        "uv",
        "run",
        "--project",
        str(root / "card_event_net"),
        "python",
        "-c",
        script,
        str(checkpoint),
        str(bundle),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise CardEventM15Error(f"Could not start the Core ML runtime check: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CardEventM15Error(f"Core ML runtime or parity check failed: {detail}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise CardEventM15Error("Core ML runtime check produced no result")
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise CardEventM15Error("Core ML runtime check produced invalid JSON") from error
    if not isinstance(result, Mapping):
        raise CardEventM15Error("Core ML runtime check result is not an object")
    return dict(result)


def _verify_fixture(root: Path) -> dict[str, str]:
    fixture_path = _required(
        root / "ios" / "CardEventProbeTests" / "Fixtures" / "full_frame_letterbox_v1.json",
        "preprocessing fixture",
    )
    fixture = _read_json(fixture_path, "preprocessing fixture")
    expected = {
        "name": "full_frame_letterbox_v1",
        "pixel_format": "BGRA",
        "orientation": "up",
        "target_size": 224,
    }
    if any(fixture.get(key) != value for key, value in expected.items()):
        raise CardEventM15Error("preprocessing fixture does not match the runtime contract")
    reference = fixture.get("python_reference")
    if not isinstance(reference, Mapping) or reference.get("tensor_layout") != str(M15_INPUT_SHAPE):
        raise CardEventM15Error(
            "preprocessing fixture tensor layout differs from the model contract"
        )
    return _file_ref(root, fixture_path, "preprocessing fixture")


def _verify_champion(root: Path, lock: Mapping[str, Any], campaign_dir: Path) -> dict[str, Any]:
    current = lock["current_champion"]
    registry_ref = current["registry"]
    registry_path = _verify_ref(root, registry_ref, "current model registry")
    registry = _read_json(registry_path, "current model registry")
    champion = current["champion"]
    matches = [
        item
        for item in registry.get("champions", [])
        if isinstance(item, Mapping)
        and item.get("component") == champion.get("component")
        and item.get("capability") == champion.get("capability")
    ]
    if matches != [champion]:
        raise CardEventM15Error("current CardEventNet champion differs from the M14 lock")
    manifest_path = _verify_ref(root, current["bundle"], "current champion manifest")
    snapshot_core = {
        "schema_version": "cardeventnet-m15-current-champion/v1",
        "registry": registry_ref,
        "champion": champion,
        "bundle_manifest": current["bundle"],
    }
    snapshot = {**snapshot_core, "snapshot_digest": sha256_mapping(snapshot_core)}
    snapshot_path = campaign_dir / "current-champion.json"
    snapshot_sha256 = _write_json(snapshot_path, snapshot, "current champion snapshot")
    return {
        "snapshot": snapshot,
        "snapshot_ref": {"path": _relative(root, snapshot_path), "sha256": snapshot_sha256},
        "registry": registry_ref,
        "manifest": {**current["bundle"], "path": _relative(root, manifest_path)},
    }


def _render_report(result: Mapping[str, Any]) -> str:
    metrics = result["sealed_test"]["metrics"]
    runtime = result["runtime_checks"]["result"]
    lines = [
        "# CardEventNet M15 integration closeout",
        "",
        f"- Campaign: {result['campaign_id']}",
        f"- Outcome: {result['outcome']}",
        f"- Integration model: {result['integration_contract']['model_bundle']['path']}",
        f"- Checkpoint: {result['checkpoint']['path']}",
        f"- Production promotion eligible: {result['production_promotion_eligible']}",
        "",
        "The M9 hard-negative checkpoint remains the development baseline. The sealed test is an",
        "informational integration measurement, not a tuning or promotion decision.",
        "",
        "## Sealed-test result",
        "",
        f"- Recordings: {int(metrics['videos'])}",
        f"- Real events: {int(metrics['real_events'])}",
        f"- Detected true events: {int(metrics['detected_true_events'])}",
        f"- Missed events: {int(metrics['missed_events'])}",
        f"- False events: {int(metrics['false_events'])}",
        f"- Recall: {metrics['event_recall']:.2%}",
        f"- Precision: {metrics['event_precision']:.2%}",
        f"- F1: {metrics['event_f1']:.2%}",
        f"- False events per hour: {metrics['false_events_per_hour']:.2f}",
        "",
        "The existing production gates remain recorded in the M14 lock for information only.",
        "The sealed-test result does not alter the locked threshold, decoder, candidate, or "
        "registry.",
        "",
        "## Runtime contract",
        "",
        f"- Runtime load: {runtime['status']}",
        f"- Input: {runtime['input_name']} {runtime['input_shape']}",
        f"- Output: {runtime['output_name']}",
        f"- Preprocessing: {runtime['preprocessing']}",
        f"- Parity maximum absolute error: {runtime['max_abs_error']:.6g}",
        "",
        "## Downstream measurement questions",
        "",
        "- Does an event produce a correct stable table observation?",
        "- Can a later proposal recover an early proposal?",
        "- Does a miss cause a persistent reconstruction error?",
        "- Do duplicate or false proposals corrupt state, or only add computation?",
        "",
        "The five old-phone recordings remain a separate legacy_device_diagnostic population.",
        "No diagnostic command was run or merged into this campaign.",
        "",
        "Epic 0063 is closed. Defer more CardEventNet training until downstream evidence "
        "identifies",
        "a concrete, non-recoverable failure class.",
        "",
    ]
    return "\n".join(lines)


def validate_cardeventnet_m15_integration(
    campaign_id: str,
    *,
    repository_root: str | Path,
    campaign_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate completed M14 outputs and write the immutable M15 closeout."""
    root = Path(repository_root).resolve()
    campaigns = Path(campaign_root or root / "data" / "model-campaigns")
    if not campaigns.is_absolute():
        campaigns = root / campaigns
    if campaign_id != M15_CAMPAIGN_ID:
        raise CardEventM15Error(f"M15 expects campaign {M15_CAMPAIGN_ID}")
    campaign_dir = (campaigns / campaign_id).resolve()
    source_dir = (campaigns / M15_SOURCE_CAMPAIGN_ID).resolve()
    try:
        campaign_dir.relative_to(root)
        source_dir.relative_to(root)
    except ValueError as error:
        raise CardEventM15Error("M15 campaign paths must stay inside the repository") from error

    m14 = _load_m14(root, campaign_dir)
    sealed = _verify_sealed_test(root, campaign_dir, m14)
    export = m14["export"]
    bundle_path = root / str(export["expected_outputs"][0])
    bundle_files, bundle_digest = _bundle_files(root, bundle_path)
    checkpoint_path = _verify_ref(root, m14["lock"]["checkpoint"], "locked checkpoint")
    fixture_ref = _verify_fixture(root)
    runtime = _run_runtime_parity(root, checkpoint_path, bundle_path)
    if runtime.get("schema_version") != M15_RUNTIME_SCHEMA_VERSION:
        raise CardEventM15Error("runtime check has an unsupported schema")
    if runtime.get("status") != "passed":
        raise CardEventM15Error("Core ML runtime check did not pass")
    if runtime.get("input_name") != "clips" or runtime.get("input_shape") != M15_INPUT_SHAPE:
        raise CardEventM15Error("Core ML input does not match runtime/v1")
    if runtime.get("output_name") != "logit":
        raise CardEventM15Error("Core ML output does not match runtime/v1")
    if runtime.get("preprocessing") != "full_frame_letterbox_v1":
        raise CardEventM15Error("Core ML preprocessing metadata does not match the fixture")
    if float(runtime.get("max_abs_error", float("inf"))) > M15_RUNTIME_ATOL:
        raise CardEventM15Error("Core ML parity exceeds the runtime contract tolerance")

    runtime_path = campaign_dir / "runtime-checks.json"
    runtime_sha256 = _write_json(runtime_path, runtime, "M15 runtime checks")
    champion = _verify_champion(root, m14["lock"], campaign_dir)

    evaluation = sealed["evaluation"]
    metrics = dict(evaluation["overall"])
    contract_core = {
        "schema_version": M15_CONTRACT_SCHEMA_VERSION,
        "campaign_id": M15_CAMPAIGN_ID,
        "role": "development_integration_model",
        "production_promotion_eligible": False,
        "checkpoint": {
            **m14["lock"]["checkpoint"],
            "source_campaign_id": M15_SOURCE_CAMPAIGN_ID,
            "retention": (
                "retained by the locked source campaign and this immutable closeout reference"
            ),
        },
        "threshold": M15_THRESHOLD,
        "decoder": M15_DECODER,
        "model_bundle": {
            "path": _relative(root, bundle_path),
            "bundle_digest": bundle_digest,
            "files": bundle_files,
            "runtime_contract_version": "runtime/v1",
        },
        "preprocessing_fixture": fixture_ref,
        "input": {
            "name": "clips",
            "shape": M15_INPUT_SHAPE,
            "element_type": "float32",
            "layout": "batch,time,rgb,height,width",
            "frame_offsets_s": [-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0],
            "inference_stride_s": 0.125,
        },
        "output": {
            "name": "logit",
            "element_type": "float32",
            "probability": "sigmoid(logit)",
        },
        "current_champion": champion["snapshot_ref"],
        "source_and_annotation_lineage": {
            "dataset": m14["lock"]["successor_validation_lineage"]["dataset"],
            "reference_revisions": m14["lock"]["successor_validation_lineage"][
                "reference_revisions"
            ],
            "sealed_test_evaluation": sealed["evaluation_ref"],
        },
        "downstream_usage": {
            "table_observation": "Use the bundle as a development integration model only.",
            "game_reconstruction": "Treat emitted events as proposals and retain source lineage.",
            "promotion": "Never resolve this path through the production champion registry.",
        },
    }
    contract = {**contract_core, "contract_digest": sha256_mapping(contract_core)}
    contract_path = campaign_dir / "integration-contract.json"
    contract_sha256 = _write_json(contract_path, contract, "M15 integration contract")

    result_core = {
        "schema_version": M15_SCHEMA_VERSION,
        "campaign_id": M15_CAMPAIGN_ID,
        "source_campaign_id": M15_SOURCE_CAMPAIGN_ID,
        "state": "closed",
        "outcome": "m9_retained_as_development_integration_baseline",
        "production_promotion_eligible": False,
        "sealed_test": {
            "status": "validated_once",
            "partition": sealed["sealed_test_partition"],
            "recordings": sealed["sealed_test_recordings"],
            "evaluation": sealed["evaluation_ref"],
            "metrics": metrics,
            "outputs": sealed["outputs"],
            "validation_stream": sealed["validation_stream_ref"],
        },
        "production_gates": {
            "source": "M14 lock decision and M12 gate profile",
            "application": "informational_only",
            "gates": m14["lock"]["decision"]["failed_gates"],
        },
        "runtime_checks": {
            "path": _relative(root, runtime_path),
            "sha256": runtime_sha256,
            "result": runtime,
        },
        "integration_contract": {
            "path": _relative(root, contract_path),
            "sha256": contract_sha256,
            "digest": contract["contract_digest"],
            "model_bundle": contract["model_bundle"],
        },
        "checkpoint": m14["lock"]["checkpoint"],
        "decoder": M15_DECODER,
        "current_champion": champion["snapshot_ref"],
        "current_champion_changed": False,
        "promotion_receipt_written": False,
        "system_holdout_read": False,
        "legacy_device_diagnostic": {
            "status": "not_run",
            "gating": False,
            "recordings": [
                "cardeventnet-IMG_2777",
                "cardeventnet-IMG_2778",
                "cardeventnet-IMG_2779",
                "cardeventnet-IMG_2780",
                "cardeventnet-IMG_2781",
            ],
        },
    }
    result = {**result_core, "result_digest": sha256_mapping(result_core)}
    result_path = campaign_dir / "m15-result.json"
    result_sha256 = _write_json(result_path, result, "M15 result")
    report_path = campaign_dir / "m15-report.md"
    report_sha256 = _write_immutable(
        report_path,
        _render_report(result).encode("utf-8"),
        "M15 report",
    )
    result["result_path"] = _relative(root, result_path)
    result["result_sha256"] = result_sha256
    result["report_path"] = _relative(root, report_path)
    result["report_sha256"] = report_sha256
    return result


def render_cardeventnet_m15_human(result: Mapping[str, Any]) -> str:
    """Render a concise M15 CLI result."""
    metrics = result["sealed_test"]["metrics"]
    return (
        "CardEventNet M15 integration closeout\n"
        f"campaign: {result['campaign_id']}\n"
        f"state: {result['state']}\n"
        f"sealed-test recall: {metrics['event_recall']:.2%}\n"
        f"sealed-test precision: {metrics['event_precision']:.2%}\n"
        f"integration model: {result['integration_contract']['model_bundle']['path']}\n"
        f"report: {result['report_path']}\n"
        "production promotion eligible: false\n"
        "current champion changed: false\n"
    )


__all__ = [
    "CardEventM15Error",
    "M15_CAMPAIGN_ID",
    "M15_SCHEMA_VERSION",
    "validate_cardeventnet_m15_integration",
    "render_cardeventnet_m15_human",
]
