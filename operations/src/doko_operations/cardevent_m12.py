"""Prepare the CardEventNet M12 interval-aware timing-response handoff."""

from __future__ import annotations

import copy
import hashlib
import json
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .model_improvement import sha256_mapping

M12_SCHEMA_VERSION = "cardeventnet-m12-timing-response/v1"
M12_CAMPAIGN_ID = "cardeventnet-0063-m12-timing-response"
M12_RESPONSE_ID = "interval_endpoint_focus_v1"
M12_ENDPOINT_WINDOW_S = 0.125
M12_TIME_BUDGET_HOURS = 12
M12_GATES = {
    "stable_end_matches": {
        "minimum": 60,
        "meaning": "strict stable-end matches on the six-recording successor validation set",
    },
    "confirmed_no_event_triggers": {
        "maximum": 20,
        "meaning": "confirmed no-event triggers after the M11 reference decisions",
    },
    "duplicate_detections_per_reviewed_change": {
        "maximum": 32,
        "meaning": "duplicate detections attributed to one reviewed change",
    },
    "causal_emission_delay_p95_s": {
        "maximum": 0.75,
        "meaning": "causal emission delay from the stable-end anchor",
    },
    "event_presence_recall": {
        "minimum": 0.98,
        "meaning": "event-presence recall, reported separately from stable-end timing",
    },
}


class CardEventM12Error(ValueError):
    """Raised when M11 cannot support the M12 timing-response handoff."""


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM12Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM12Error(f"{context} {path} must contain an object")
    return dict(value)


def _read_yaml(path: Path, context: str) -> dict[str, Any]:
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError) as error:
        raise CardEventM12Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM12Error(f"{context} {path} must contain an object")
    return dict(value)


def _sha256_file(path: Path, context: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise CardEventM12Error(f"Could not hash {context} {path}: {error}") from error
    return digest.hexdigest()


def _required(path: Path, context: str) -> Path:
    if not path.is_file():
        raise CardEventM12Error(f"{context} is missing: {path}")
    return path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise CardEventM12Error(f"path must stay inside the repository: {path}") from error


def _write_immutable(path: Path, payload: bytes, context: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise CardEventM12Error(f"immutable M12 artifact differs: {path}")
    if not path.exists():
        path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any], context: str) -> str:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return _write_immutable(path, payload, context)


def _yaml_bytes(value: Mapping[str, Any]) -> bytes:
    import yaml

    return yaml.safe_dump(dict(value), sort_keys=False).encode("utf-8")


def _verify_m11(root: Path, source_campaign_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    result_path = _required(source_campaign_dir / "m11-result.json", "M11 result")
    result = _read_json(result_path, "M11 result")
    result_digest = result.get("result_digest")
    result_core = {key: value for key, value in result.items() if key != "result_digest"}
    if result_digest != sha256_mapping(result_core):
        raise CardEventM12Error("M11 result digest does not match its contents")
    if result.get("schema_version") != "cardeventnet-m11-timing-reconciliation/v1":
        raise CardEventM12Error("M11 result has an unsupported schema")
    if result.get("sealed_test_read") or result.get("system_holdout_read"):
        raise CardEventM12Error("M12 cannot start after M11 read sealed or system-holdout output")
    if (
        result.get("training_started")
        or result.get("export_started")
        or result.get("promotion_started")
    ):
        raise CardEventM12Error("M11 contains an operation that M12 must not inherit")

    grid_path = _required(
        root / str(result.get("decoder_grid_path")), "M11 decoder grid"
    )
    if _sha256_file(grid_path, "M11 decoder grid") != result.get("decoder_grid_sha256"):
        raise CardEventM12Error("M11 decoder grid digest differs from the M11 result")
    grid = _read_json(grid_path, "M11 decoder grid")
    selection = grid.get("selection")
    if not isinstance(selection, Mapping):
        raise CardEventM12Error("M11 decoder grid has no selection record")
    if selection.get("selected_decoder") is not None:
        raise CardEventM12Error("M12 interval response is only valid when M11 selected no decoder")
    if grid.get("sealed_test_read") or grid.get("system_holdout_read"):
        raise CardEventM12Error("M11 decoder grid read sealed or system-holdout output")

    successor = result.get("successor_dataset")
    if not isinstance(successor, Mapping):
        raise CardEventM12Error("M11 result has no successor dataset")
    dataset_path = _required(
        root / str(successor.get("path")) / "dataset.json", "M11 successor dataset"
    )
    dataset = _read_json(dataset_path, "M11 successor dataset")
    if dataset.get("dataset_version_id") != successor.get("dataset_version_id"):
        raise CardEventM12Error("M11 successor dataset ID differs from the result")
    if dataset.get("dataset_version_digest") != successor.get("dataset_version_digest"):
        raise CardEventM12Error("M11 successor dataset digest differs from the result")
    split_path = dataset_path.with_name("split.json")
    split = _read_json(_required(split_path, "M11 successor split"), "M11 successor split")
    if split.get("split_version_id") != successor.get("split_version_id"):
        raise CardEventM12Error("M11 successor split ID differs from the result")
    if split.get("split_version_digest") != successor.get("split_version_digest"):
        raise CardEventM12Error("M11 successor split digest differs from the result")
    if successor.get("test_sealed") is not True:
        raise CardEventM12Error("M11 successor dataset is not sealed")
    return result, dict(successor)


def _verify_m9_inputs(
    root: Path, source_campaign_dir: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    handoff_path = _required(source_campaign_dir / "handoff.json", "M9 ablation handoff")
    handoff = _read_json(handoff_path, "M9 ablation handoff")
    digest = handoff.get("handoff_sha256")
    core = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    legacy_digest = hashlib.sha256(json.dumps(core, sort_keys=True).encode("utf-8")).hexdigest()
    if digest not in {sha256_mapping(core), legacy_digest}:
        raise CardEventM12Error("M9 ablation handoff digest does not match its contents")
    if handoff.get("status") != "ready":
        raise CardEventM12Error("M9 ablation handoff is not ready")
    fixed_inputs = handoff.get("fixed_inputs")
    if not isinstance(fixed_inputs, Mapping):
        raise CardEventM12Error("M9 ablation handoff has no fixed inputs")
    for key, expected in (("seed", 42), ("device", "mps"), ("precision", "fp32")):
        if fixed_inputs.get(key) != expected:
            raise CardEventM12Error(f"M9 {key} is not fixed to {expected!r}")
    config_path = _required(root / str(fixed_inputs.get("config")), "M9 training config")
    config = _read_yaml(config_path, "M9 training config")
    manifest = handoff.get("manifest")
    if not isinstance(manifest, Mapping):
        raise CardEventM12Error("M9 ablation handoff has no hard-negative manifest")
    manifest_path = _required(root / str(manifest.get("path")), "M9 hard-negative manifest")
    if _sha256_file(manifest_path, "M9 hard-negative manifest") != manifest.get("sha256"):
        raise CardEventM12Error("M9 hard-negative manifest digest differs from the handoff")
    timing_packet = _read_json(
        _required(source_campaign_dir / "m10-timing-review.json", "M10 timing packet"),
        "M10 timing packet",
    )
    selection = timing_packet.get("selection")
    if not isinstance(selection, Mapping):
        raise CardEventM12Error("M10 timing packet has no selected checkpoint")
    checkpoint_ref = selection.get("checkpoint")
    if not isinstance(checkpoint_ref, Mapping):
        raise CardEventM12Error("M10 timing packet has no checkpoint lineage")
    checkpoint_path = root / str(checkpoint_ref.get("path"))
    checkpoint_sha256 = checkpoint_ref.get("sha256")
    if (
        checkpoint_path.is_file()
        and _sha256_file(checkpoint_path, "M9 checkpoint") != checkpoint_sha256
    ):
        raise CardEventM12Error("M9 checkpoint digest differs from the M10 timing packet")
    checkpoint = {
        "path": checkpoint_ref.get("path"),
        "sha256": checkpoint_ref.get("sha256"),
    }
    return handoff, config, {"manifest": dict(manifest), "checkpoint": checkpoint}


def _endpoint_config(baseline: Mapping[str, Any]) -> dict[str, Any]:
    response = copy.deepcopy(dict(baseline))
    labels = response.get("labels")
    if not isinstance(labels, Mapping):
        raise CardEventM12Error("M9 config has no labels section")
    labels = dict(labels)
    previous_window = labels.get("positive_window_s")
    if previous_window != 0.25:
        raise CardEventM12Error(
            "M12 expects the M9 stable-end positive window to remain 0.25 seconds"
        )
    labels["positive_window_s"] = M12_ENDPOINT_WINDOW_S
    if float(labels.get("negative_past_exclusion_s", 0.0)) < M12_ENDPOINT_WINDOW_S:
        raise CardEventM12Error("M12 endpoint window exceeds the post-event exclusion buffer")
    response["labels"] = labels
    for section, baseline_value in baseline.items():
        if section == "labels":
            section_value = dict(response[section])
            section_baseline = dict(baseline_value)
            section_value.pop("positive_window_s", None)
            section_baseline.pop("positive_window_s", None)
            if section_value != section_baseline:
                raise CardEventM12Error(
                    "M12 response changes more than labels.positive_window_s"
                )
        elif response.get(section) != baseline_value:
            raise CardEventM12Error(f"M12 response changes the {section} configuration")
    return response


def _commands(
    root: Path,
    campaign_dir: Path,
    successor: Mapping[str, Any],
    config_path: Path,
    manifest_path: Path,
) -> dict[str, str]:
    view = Path(".runtime") / "cardevent" / "datasets" / str(successor["dataset_version_id"])
    dataset = Path(str(successor["path"])) / "dataset.json"
    run = (
        Path("data")
        / "model-campaigns"
        / M12_CAMPAIGN_ID
        / "runs"
        / "candidate-interval-endpoint-focus-v1"
    )
    output_dir = run.parent
    config = Path(_relative(root, config_path))
    manifest = Path(_relative(root, manifest_path))
    materialize = shlex.join(
        [
            "mise",
            "exec",
            "--",
            "uv",
            "run",
            "--project",
            "operations",
            "doko",
            "data",
            "cardevent",
            "materialize",
            "--repository-root",
            ".",
            "--dataset",
            dataset.as_posix(),
            "--output",
            view.as_posix(),
        ]
    )
    prepare = shlex.join(
        [
            "mise",
            "exec",
            "--",
            "uv",
            "run",
            "--project",
            "card_event_net",
            "cardevent",
            "prepare",
            "--dataset-view",
            view.as_posix(),
            "--partition",
            "train",
            "val",
        ]
    )
    common = [
        "mise",
        "exec",
        "--",
        "uv",
        "run",
        "--project",
        "card_event_net",
        "cardevent",
    ]
    train = [
        *common,
        "train",
        "--config",
        config.as_posix(),
        "--output-dir",
        output_dir.as_posix(),
        "--run-name",
        run.name,
        "--seed",
        "42",
        "--dataset-view",
        view.as_posix(),
        "--device",
        "mps",
        "--precision",
        "fp32",
        "--hard-negative-manifest",
        manifest.as_posix(),
    ]
    resume = [
        *common,
        "train",
        "--config",
        config.as_posix(),
        "--seed",
        "42",
        "--dataset-view",
        view.as_posix(),
        "--device",
        "mps",
        "--precision",
        "fp32",
        "--hard-negative-manifest",
        manifest.as_posix(),
        "--resume",
        (run / "last.pt").as_posix(),
    ]
    checkpoint = (run / "best.pt").as_posix()
    evaluate = [
        *common,
        "evaluate",
        "--checkpoint",
        checkpoint,
        "--dataset-view",
        view.as_posix(),
        "--partition",
        "val",
        "--out",
        (
            Path("data") / "model-campaigns" / M12_CAMPAIGN_ID / "validation-evaluation.json"
        ).as_posix(),
        "--device",
        "mps",
    ]
    diagnose = [
        *common,
        "diagnose",
        "--checkpoint",
        checkpoint,
        "--dataset-view",
        view.as_posix(),
        "--out",
        (Path("data") / "model-campaigns" / M12_CAMPAIGN_ID / "diagnostics.json").as_posix(),
    ]
    return {
        "materialize_dataset": materialize,
        "prepare_train_and_validation_cache": prepare,
        "train": shlex.join(train),
        "resume": shlex.join(resume),
        "evaluate_validation": shlex.join(evaluate),
        "diagnose_validation": shlex.join(diagnose),
    }


def _render_report(result: Mapping[str, Any]) -> str:
    response = result["response"]
    commands = result["commands"]
    lines = [
        "# CardEventNet M12 timing-response handoff",
        "",
        f"- Campaign: `{result['campaign_id']}`",
        f"- Source M11 campaign: `{result['source_campaign_id']}`",
        f"- Selected response: `{response['response_id']}`",
        "- M11 selected no decoder, so this is the single interval-aware fallback response.",
        "- Sealed test read: `false`",
        "- System holdout read: `false`",
        "- Training started: `false`",
        "",
        "## Response contract",
        "",
        "The response keeps the M9 checkpoint architecture, causal eight-frame clip, full-clip "
        "temporal head, decoder, threshold-selection procedure, seed, device, precision, "
        "hard-negative manifest, and source partition policy. It changes only the stable-end "
        "positive timing window:",
        "",
        "| Setting | M9 baseline | M12 response |",
        "| --- | ---: | ---: |",
        f"| `labels.positive_window_s` | 0.250 s | {response['endpoint_window_s']:.3f} s |",
        "| `labels.negative_past_exclusion_s` | 0.350 s | 0.350 s |",
        "| interval interior | ignored | ignored |",
        "| decoder | current causal peak | current causal peak |",
        "",
        "The interval interior is never relabeled as an ordinary or hard negative. Point events, "
        "close valid events, stable-end anchors, and causal emission remain separate validation "
        "checks in M13.",
        "",
        "## Declared M13 validation gates",
        "",
        "| Metric | Gate |",
        "| --- | --- |",
    ]
    for metric, gate in result["gates"].items():
        operator = "≥" if "minimum" in gate else "≤"
        value = gate.get("minimum", gate.get("maximum"))
        lines.append(f"| `{metric}` | {operator} {value} |")
    lines.extend(
        [
            "",
            "## Operator commands",
            "",
            "M12 prepares these commands and stops. The operator starts the bounded command, "
            f"with a fixed wall-clock budget of "
            f"{result['execution_contract']['time_budget_hours']} hours, "
            "and resumes it only with the command below when required.",
            "",
            "Materialize the successor view and prepare only train and validation caches:",
            "",
            "```bash",
            commands["materialize_dataset"],
            commands["prepare_train_and_validation_cache"],
            "```",
            "",
            "Start training once:",
            "",
            "```bash",
            commands["train"],
            "```",
            "",
            "Resume from the last checkpoint if the bounded run stops:",
            "",
            "```bash",
            commands["resume"],
            "```",
            "",
            "After training completes, evaluate validation and write diagnostics:",
            "",
            "```bash",
            commands["evaluate_validation"],
            commands["diagnose_validation"],
            "```",
            "",
            "Do not read the sealed test partition, system holdout, or export in M12. M13 must "
            "validate output completeness and lineage before reading the validation metrics.",
            "",
            "## Expected completion artifacts",
            "",
        ]
    )
    for path in result["expected_outputs"]:
        lines.append(f"- `{path}`")
    lines.extend(["", "M12 did not start or monitor the long-running command.", ""])
    return "\n".join(lines)


def prepare_cardeventnet_m12_timing_response(
    source_campaign_id: str,
    *,
    repository_root: str | Path,
    campaign_root: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare one immutable M12 timing-response handoff without running training."""

    root = Path(repository_root).resolve()
    campaigns = Path(campaign_root or root / "data" / "model-campaigns")
    if not campaigns.is_absolute():
        campaigns = root / campaigns
    source_campaign_dir = (campaigns / source_campaign_id).resolve()
    try:
        source_campaign_dir.relative_to(root)
    except ValueError as error:
        raise CardEventM12Error(
            "source campaign directory must stay inside the repository"
        ) from error
    m11_result, successor = _verify_m11(root, source_campaign_dir)
    m9_handoff, baseline_config, m9_inputs = _verify_m9_inputs(root, source_campaign_dir)
    response_config = _endpoint_config(baseline_config)

    campaign_dir = (campaigns / M12_CAMPAIGN_ID).resolve()
    try:
        campaign_dir.relative_to(root)
    except ValueError as error:
        raise CardEventM12Error("M12 campaign directory must stay inside the repository") from error
    config_path = campaign_dir / "interval-endpoint-focus-v1.yaml"
    config_sha256 = _write_immutable(config_path, _yaml_bytes(response_config), "M12 config")
    manifest_path = root / str(m9_inputs["manifest"]["path"])
    commands = _commands(root, campaign_dir, successor, config_path, manifest_path)

    source_result_path = source_campaign_dir / "m11-result.json"
    source_result_ref = {
        "path": _relative(root, source_result_path),
        "sha256": _sha256_file(source_result_path, "M11 result"),
        "result_digest": m11_result["result_digest"],
    }
    dataset_dir = root / str(successor["path"])
    lineage = {
        "successor_dataset": {
            "id": successor["dataset_version_id"],
            "digest": successor["dataset_version_digest"],
            "path": _relative(root, dataset_dir),
            "dataset_sha256": _sha256_file(dataset_dir / "dataset.json", "successor dataset"),
            "split_sha256": _sha256_file(dataset_dir / "split.json", "successor split"),
            "materialized_view": successor["materialized_view"],
            "materialization_manifest_digest": successor["materialization_manifest_digest"],
        },
        "m11_result": source_result_ref,
        "hard_negative_manifest": {
            "path": m9_inputs["manifest"]["path"],
            "sha256": m9_inputs["manifest"]["sha256"],
        },
        "m9_checkpoint": m9_inputs["checkpoint"],
        "m9_handoff": {
            "path": _relative(root, source_campaign_dir / "handoff.json"),
            "sha256": _sha256_file(source_campaign_dir / "handoff.json", "M9 handoff"),
            "handoff_sha256": m9_handoff["handoff_sha256"],
        },
    }
    response = {
        "response_id": M12_RESPONSE_ID,
        "kind": "interval_aware_temporal_model",
        "objective": "stable_end_endpoint",
        "endpoint_window_s": M12_ENDPOINT_WINDOW_S,
        "baseline_positive_window_s": 0.25,
        "interval_interior": "ignore",
        "changed_axis": "stable_end_positive_window",
        "config_path": _relative(root, config_path),
        "config_sha256": config_sha256,
    }
    execution_contract = {
        "operator_only": True,
        "time_budget_hours": M12_TIME_BUDGET_HOURS,
        "seed": 42,
        "device": "mps",
        "precision": "fp32",
        "validation_partition": "val",
        "sealed_test": "not_read",
        "system_holdout": "not_read",
        "resume_from": "last.pt",
    }
    expected_outputs = [
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/runs/candidate-interval-endpoint-focus-v1/config.yaml",
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/runs/candidate-interval-endpoint-focus-v1/environment.json",
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/runs/candidate-interval-endpoint-focus-v1/sampling.json",
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/runs/candidate-interval-endpoint-focus-v1/best.pt",
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/runs/candidate-interval-endpoint-focus-v1/last.pt",
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/runs/candidate-interval-endpoint-focus-v1/summary.json",
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/validation-evaluation.json",
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/validation-evaluation-transition-diagnostics.json",
        f"data/model-campaigns/{M12_CAMPAIGN_ID}/diagnostics.json",
    ]
    result_core = {
        "schema_version": M12_SCHEMA_VERSION,
        "campaign_id": M12_CAMPAIGN_ID,
        "source_campaign_id": source_campaign_id,
        "response_selection": {
            "candidates_considered": [M12_RESPONSE_ID],
            "selected_response": M12_RESPONSE_ID,
            "selection_rule": (
                "M11 selected no decoder; use the single interval-aware endpoint response"
            ),
        },
        "response": response,
        "gates": M12_GATES,
        "lineage": lineage,
        "execution_contract": execution_contract,
        "commands": commands,
        "expected_outputs": expected_outputs,
        "sealed_test_read": False,
        "system_holdout_read": False,
        "training_started": False,
        "export_started": False,
        "promotion_started": False,
    }
    result = {**result_core, "result_digest": sha256_mapping(result_core)}
    result_path = campaign_dir / "m12-result.json"
    result_sha256 = _write_json(result_path, result, "M12 result")
    report_path = campaign_dir / "m12-report.md"
    report = _render_report(result)
    report_sha256 = _write_immutable(report_path, report.encode("utf-8"), "M12 report")
    result["result_path"] = _relative(root, result_path)
    result["result_sha256"] = result_sha256
    result["report_path"] = _relative(root, report_path)
    result["report_sha256"] = report_sha256
    return result


def render_cardeventnet_m12_human(result: Mapping[str, Any]) -> str:
    """Render a concise M12 CLI result."""

    return (
        "CardEventNet M12 timing-response handoff\n"
        f"campaign: {result['campaign_id']}\n"
        f"response: {result['response']['response_id']}\n"
        f"config: {result['response']['config_path']}\n"
        f"report: {result['report_path']}\n"
        "training started: false\n"
        "sealed test read: false\n"
    )


__all__ = [
    "CardEventM12Error",
    "M12_CAMPAIGN_ID",
    "M12_RESPONSE_ID",
    "M12_SCHEMA_VERSION",
    "prepare_cardeventnet_m12_timing_response",
    "render_cardeventnet_m12_human",
]
