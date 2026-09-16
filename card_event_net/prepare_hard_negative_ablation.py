#!/usr/bin/env python3
"""Prepare a reviewed hard-negative manifest and an operator-only ablation handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shlex
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import yaml

DECISIONS = ("no_event", "missed_event", "uncertain")
OUTPUT_FORMAT = "cardevent-hard-negatives-v1"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_key(video: str, time_s: float) -> str:
    return f"{video}@{time_s:.6f}"


def _read_mapping(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {label} {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _read_split(path: Path) -> set[str]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not read split {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("split must contain a mapping")
    train = payload.get("train")
    if not isinstance(train, list) or any(not isinstance(name, str) for name in train):
        raise ValueError("split.train must be a list of video names")
    return set(train)


def _candidate_entries(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if payload.get("format") != "cardevent-hard-negative-candidates-v1":
        raise ValueError("candidate manifest has an unsupported format")
    if payload.get("partition") != "train" or payload.get("training_input") is not False:
        raise ValueError("candidate manifest must be a non-training train manifest")
    entries: dict[str, dict[str, Any]] = {}
    videos = payload.get("videos")
    if not isinstance(videos, list):
        raise ValueError("candidate manifest videos must be a list")
    for video_entry in videos:
        if not isinstance(video_entry, Mapping):
            raise ValueError("candidate manifest video entries must be mappings")
        video = video_entry.get("video")
        duration_s = video_entry.get("duration_s")
        if (
            not isinstance(video, str)
            or not video
            or isinstance(duration_s, bool)
            or not isinstance(duration_s, (int, float))
            or not math.isfinite(float(duration_s))
            or float(duration_s) < 0.0
        ):
            raise ValueError("candidate manifest has an invalid video entry")
        candidates = video_entry.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError(f"candidate list for {video} must be a list")
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                raise ValueError(f"candidate entry for {video} must be a mapping")
            time_s = candidate.get("time_s")
            probability = candidate.get("probability")
            if (
                isinstance(time_s, bool)
                or not isinstance(time_s, (int, float))
                or not math.isfinite(float(time_s))
                or float(time_s) < 0.0
                or float(time_s) > float(duration_s) + 1e-6
                or isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not math.isfinite(float(probability))
            ):
                raise ValueError(f"candidate entry for {video} has invalid numeric values")
            key = _candidate_key(video, float(time_s))
            if key in entries:
                raise ValueError(f"candidate manifest repeats {key}")
            entries[key] = {
                "video": video,
                "time_s": float(time_s),
                "probability": float(probability),
                "duration_s": float(duration_s),
                "source_candidate_id": candidate.get("id"),
                "reason": candidate.get("reason"),
            }
    if not entries:
        raise ValueError("candidate manifest has no candidates")
    return entries


def _review_decisions(
    payload: Mapping[str, Any],
    candidate_path: Path,
    candidate_entries: Mapping[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if payload.get("format") != "cardevent-hard-negative-review-v1":
        raise ValueError("review file has an unsupported format")
    if payload.get("source_manifest_sha256") != _sha256_file(candidate_path):
        raise ValueError("review file was created from a different candidate manifest")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("review items must be a list")
    decisions: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("review items must be mappings")
        video = item.get("video")
        time_s = item.get("time_s")
        decision = item.get("decision")
        if (
            not isinstance(video, str)
            or isinstance(time_s, bool)
            or not isinstance(time_s, (int, float))
            or not math.isfinite(float(time_s))
            or decision not in DECISIONS
        ):
            raise ValueError("review contains an invalid decision")
        key = _candidate_key(video, float(time_s))
        if key in decisions:
            raise ValueError(f"review repeats {key}")
        if key not in candidate_entries:
            raise ValueError(f"review contains a candidate not present in the source: {key}")
        decisions[key] = {"decision": decision}
    missing = set(candidate_entries) - set(decisions)
    extra = set(decisions) - set(candidate_entries)
    if missing or extra:
        raise ValueError(
            f"review does not cover the source exactly (missing={len(missing)}, extra={len(extra)})"
        )
    return decisions


def build_reviewed_manifest(
    candidate_path: str | Path,
    review_path: str | Path,
    split_path: str | Path,
    *,
    output_path: str | Path,
    campaign_id: str,
) -> dict[str, Any]:
    """Convert a complete human review into a training-only hard-negative manifest."""
    candidate_file = Path(candidate_path)
    review_file = Path(review_path)
    split_file = Path(split_path)
    candidate_payload = _read_mapping(candidate_file, "candidate manifest")
    review_payload = _read_mapping(review_file, "review")
    entries = _candidate_entries(candidate_payload)
    train_videos = _read_split(split_file)
    if {entry["video"] for entry in entries.values()} - train_videos:
        raise ValueError("candidate manifest contains a video outside split.train")
    decisions = _review_decisions(review_payload, candidate_file, entries)

    selected = [
        {**entries[key], **decisions[key]}
        for key in sorted(entries)
        if decisions[key]["decision"] == "no_event"
    ]
    by_video: dict[str, list[dict[str, Any]]] = defaultdict(list)
    durations: dict[str, float] = {}
    for item in selected:
        video = item["video"]
        durations[video] = item["duration_s"]
        sample = {
            "time_s": item["time_s"],
            "probability": item["probability"],
            "review_decision": item["decision"],
        }
        if isinstance(item["source_candidate_id"], str):
            sample["source_candidate_id"] = item["source_candidate_id"]
        if isinstance(item["reason"], str):
            sample["reason"] = item["reason"]
        by_video[video].append(sample)

    decision_counts = Counter(item["decision"] for item in decisions.values())
    core: dict[str, Any] = {
        "format": OUTPUT_FORMAT,
        "schema_version": "cardeventnet-reviewed-hard-negatives/v1",
        "campaign_id": campaign_id,
        "partition": "train",
        "training_input": True,
        "status": "approved_for_single_axis_ablation",
        "hard_negative_count": len(selected),
        "reviewed_candidate_count": len(entries),
        "review_decision_counts": dict(sorted(decision_counts.items())),
        "source_manifest": str(candidate_file),
        "source_manifest_sha256": _sha256_file(candidate_file),
        "source_review": str(review_file),
        "source_review_sha256": _sha256_file(review_file),
        "approval": {
            "scope": "single_axis_hard_negative_ablation",
            "included_decision": "no_event",
            "excluded_decisions": ["missed_event", "uncertain"],
        },
        "videos": [
            {
                "video": video,
                "duration_s": durations[video],
                "hard_negatives": by_video[video],
            }
            for video in sorted(by_video)
        ],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(core, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return core


def build_ablation_handoff(
    manifest_path: str | Path,
    *,
    handoff_path: str | Path,
    dataset_view: str | Path,
    config_path: str | Path,
    campaign_id: str,
    project_root: str | Path = ".",
) -> dict[str, Any]:
    """Write the exact manual train/evaluate/diagnose commands without running them."""
    manifest = Path(manifest_path)
    handoff = Path(handoff_path)
    dataset = Path(dataset_view)
    config = Path(config_path)
    project = Path(project_root)
    campaign_dir = handoff.parent
    run_dir = campaign_dir / "runs" / "candidate-hard-negative-v1"
    checkpoint = run_dir / "best.pt"
    train_args = [
        "mise",
        "exec",
        "--",
        "uv",
        "run",
        "--project",
        str(project / "card_event_net"),
        "cardevent",
        "train",
        "--config",
        str(config),
        "--output-dir",
        str(run_dir.parent),
        "--run-name",
        run_dir.name,
        "--seed",
        "42",
        "--dataset-view",
        str(dataset),
        "--device",
        "mps",
        "--precision",
        "fp32",
        "--hard-negative-manifest",
        str(manifest),
    ]
    resume_args = [
        *train_args[: train_args.index("--run-name")],
        "--resume",
        str(run_dir),
        *train_args[train_args.index("--seed") :],
    ]
    evaluate_args = [
        "mise",
        "exec",
        "--",
        "uv",
        "run",
        "--project",
        str(project / "card_event_net"),
        "cardevent",
        "evaluate",
        "--checkpoint",
        str(checkpoint),
        "--dataset-view",
        str(dataset),
        "--partition",
        "val",
        "--out",
        str(campaign_dir / "validation-evaluation.json"),
        "--device",
        "mps",
    ]
    diagnose_args = [
        "mise",
        "exec",
        "--",
        "uv",
        "run",
        "--project",
        str(project / "card_event_net"),
        "cardevent",
        "diagnose",
        "--checkpoint",
        str(checkpoint),
        "--dataset-view",
        str(dataset),
        "--out",
        str(campaign_dir / "diagnostics.json"),
        "--device",
        "mps",
    ]
    core: dict[str, Any] = {
        "schema_version": "cardeventnet-hard-negative-ablation-handoff/v1",
        "status": "ready",
        "campaign_id": campaign_id,
        "ablation_axis": "reviewed-hard-negatives-v1",
        "manifest": {
            "path": str(manifest),
            "sha256": _sha256_file(manifest),
        },
        "fixed_inputs": {
            "dataset_view": str(dataset),
            "config": str(config),
            "seed": 42,
            "device": "mps",
            "precision": "fp32",
            "validation_partition": "val",
            "sealed_test": "not_read",
        },
        "commands": {
            "train": shlex.join(train_args),
            "resume": shlex.join(resume_args),
            "evaluate": shlex.join(evaluate_args),
            "diagnose": shlex.join(diagnose_args),
        },
        "expected_outputs": [
            str(run_dir / "best.pt"),
            str(run_dir / "summary.json"),
            str(campaign_dir / "validation-evaluation.json"),
            str(campaign_dir / "diagnostics.json"),
        ],
        "operator_action": (
            "Run train once. After it exits, run evaluate and diagnose. Do not read the sealed "
            "test partition or export this ablation automatically."
        ),
    }
    handoff_digest = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
    payload = {**core, "handoff_sha256": handoff_digest}
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Reviewed training manifest path.")
    parser.add_argument("--handoff", type=Path, required=True, help="Ablation handoff path.")
    parser.add_argument("--dataset-view", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_reviewed_manifest(
        args.candidate_manifest,
        args.review,
        args.split,
        output_path=args.out,
        campaign_id=args.campaign_id,
    )
    build_ablation_handoff(
        args.out,
        handoff_path=args.handoff,
        dataset_view=args.dataset_view,
        config_path=args.config,
        campaign_id=args.campaign_id,
        project_root=args.project_root,
    )
    print(f"Reviewed hard-negative manifest: {args.out}")
    print(f"Ablation handoff: {args.handoff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
