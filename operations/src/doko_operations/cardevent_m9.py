"""Review completed CardEventNet M8 artifacts and harvest training candidates."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cardevent_campaign import _file_digest
from .model_improvement import (
    ModelCampaign,
    ModelComparison,
    ModelImprovementError,
    ModelRecipe,
    load_campaign,
    load_campaign_comparison,
    load_model_recipe,
    sha256_mapping,
)
from .source_exclusion import LEGACY_DEVICE_RECORDING_ID_SET

M9_REVIEW_SCHEMA_VERSION = "cardeventnet-m9-review/v1"
M9_CANDIDATE_SCHEMA_VERSION = "cardevent-hard-negative-candidates/v1"
_SAMPLING_POLICY = {
    "version": "stable-end-anchor-v1",
    "positive_window_s": 0.25,
    "negative_past_exclusion_s": 0.35,
    "negative_future_exclusion_s": 0.10,
    "interval_interior": "exclude_from_negative_evidence",
}


class CardEventM9Error(ModelImprovementError):
    """Raised when completed M8 artifacts are incomplete or inconsistent."""


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM9Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, dict):
        raise CardEventM9Error(f"{context} {path} must contain an object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _required_file(path: Path, context: str) -> Path:
    if not path.is_file():
        raise CardEventM9Error(f"{context} is missing: {path}")
    return path


def _relative(root: Path, value: object, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CardEventM9Error(f"{context} must be a repository-relative path")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise CardEventM9Error(f"{context} must stay inside the repository") from error
    return path


def _same_mapping(left: object, right: object, context: str) -> None:
    if left != right:
        raise CardEventM9Error(f"M9 lineage mismatch: {context}")


def _number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardEventM9Error(f"{context} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise CardEventM9Error(f"{context} must be finite")
    return result


def _load_yaml(path: Path, context: str) -> dict[str, Any]:
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError) as error:
        raise CardEventM9Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM9Error(f"{context} {path} must contain an object")
    return dict(value)


def _validate_handoff(root: Path, campaign_id: str, campaign_dir: Path) -> dict[str, Any]:
    handoff = _read_json(campaign_dir / "handoff.json", "M8 handoff")
    digest = handoff.get("handoff_digest")
    core = {key: value for key, value in handoff.items() if key != "handoff_digest"}
    if digest != sha256_mapping(core):
        raise CardEventM9Error("M8 handoff digest does not match its contents")
    if handoff.get("campaign_id") != campaign_id or handoff.get("status") != "ready":
        raise CardEventM9Error("M8 handoff does not identify this ready campaign")
    expected_directory = handoff.get("expected_campaign_directory")
    if expected_directory != campaign_dir.relative_to(root).as_posix():
        raise CardEventM9Error("M8 handoff expected campaign directory differs")
    return handoff


def _validate_recipe_and_data(
    root: Path,
    campaign: ModelCampaign,
    handoff: Mapping[str, Any],
    campaign_dir: Path,
) -> tuple[ModelRecipe, Path, dict[str, Any], dict[str, Any]]:
    recipe_path = campaign_dir / "resolved-recipe.yaml"
    recipe = load_model_recipe(recipe_path)
    if recipe.digest != campaign.recipe_digest:
        raise CardEventM9Error("resolved recipe digest differs from campaign")
    handoff_recipe = handoff.get("recipe")
    if not isinstance(handoff_recipe, Mapping):
        raise CardEventM9Error("M8 handoff has no recipe lineage")
    if handoff_recipe.get("digest") != recipe.digest:
        raise CardEventM9Error("M8 handoff recipe digest differs from resolved recipe")
    _same_mapping(recipe.data.to_mapping(), campaign.data.to_mapping(), "campaign data context")

    data_mapping = handoff.get("data")
    if not isinstance(data_mapping, Mapping):
        raise CardEventM9Error("M8 handoff has no data lineage")
    _same_mapping(data_mapping.get("dataset"), recipe.data.dataset.to_mapping(), "dataset")
    _same_mapping(data_mapping.get("split"), recipe.data.split.to_mapping(), "split")
    view = _relative(root, data_mapping.get("materialized_view"), "materialized view")
    materialization = _read_json(view / "materialization.json", "M7 materialization")
    _same_mapping(
        materialization.get("dataset"), recipe.data.dataset.to_mapping(), "materialized dataset"
    )
    _same_mapping(
        materialization.get("split"), recipe.data.split.to_mapping(), "materialized split"
    )
    dataset_path = _relative(root, data_mapping.get("dataset_path"), "frozen dataset")
    dataset = _read_json(dataset_path / "dataset.json", "frozen dataset")
    _same_mapping(
        {
            "id": dataset.get("dataset_version_id"),
            "digest": dataset.get("dataset_version_digest"),
        },
        recipe.data.dataset.to_mapping(),
        "frozen dataset digest",
    )
    split = _read_json(dataset_path / "split.json", "frozen split")
    _same_mapping(
        {
            "id": split.get("split_version_id"),
            "digest": split.get("split_version_digest"),
        },
        recipe.data.split.to_mapping(),
        "frozen split digest",
    )
    return recipe, view, dataset, split


def _validate_checkpoint_lineage(
    root: Path,
    recipe: ModelRecipe,
    handoff: Mapping[str, Any],
    campaign_dir: Path,
    candidate_id: str,
    candidate_evaluation: Mapping[str, Any],
) -> tuple[Path, Path]:
    if recipe.baseline_checkpoint is None:
        raise CardEventM9Error("M9 requires the loadable M5 checkpoint baseline")
    baseline = _relative(root, recipe.baseline_checkpoint.path, "baseline checkpoint")
    _required_file(baseline, "M5 baseline checkpoint")
    if _file_digest(baseline) != recipe.baseline_checkpoint.digest:
        raise CardEventM9Error("M5 baseline checkpoint digest differs from the recipe")
    handoff_baseline = handoff.get("baseline")
    if (
        not isinstance(handoff_baseline, Mapping)
        or handoff_baseline.get("checkpoint") != recipe.baseline_checkpoint.to_mapping()
    ):
        raise CardEventM9Error("M8 handoff baseline checkpoint differs from the recipe")

    checkpoint = _required_file(
        campaign_dir / "runs" / candidate_id / "best.pt", "candidate checkpoint"
    )
    candidate_bundle = candidate_evaluation.get("bundle")
    if not isinstance(candidate_bundle, Mapping):
        raise CardEventM9Error("candidate evaluation has no checkpoint bundle")
    if candidate_bundle.get("digest") != _file_digest(checkpoint):
        raise CardEventM9Error("candidate checkpoint digest differs from evaluation")
    return baseline, checkpoint


def _read_event_intervals(path: Path, context: str) -> tuple[tuple[float, float], ...]:
    payload = _read_json(path, context)
    events = payload.get("events")
    if not isinstance(events, list):
        raise CardEventM9Error(f"{context} has no events")
    intervals: list[tuple[float, float]] = []
    for event in events:
        if not isinstance(event, Mapping):
            raise CardEventM9Error(f"{context} contains an invalid event")
        if "start_us" in event or "end_us" in event:
            start = _number(event.get("start_us"), f"{context} start") / 1_000_000
            end = _number(event.get("end_us"), f"{context} end") / 1_000_000
        else:
            start = _number(event.get("start_s", event.get("time_s")), f"{context} start")
            end = _number(event.get("end_s", event.get("time_s")), f"{context} end")
        if start < 0.0 or end < start:
            raise CardEventM9Error(f"{context} contains an unordered interval")
        intervals.append((start, end))
    return tuple(intervals)


def _clean_negative_reason(
    time_s: float,
    intervals: Sequence[tuple[float, float]],
) -> str | None:
    if any(start <= time_s < end for start, end in intervals if start < end):
        return "interval_interior"
    event_times = tuple(end for _, end in intervals)
    if any(
        event_time - _SAMPLING_POLICY["positive_window_s"] <= time_s <= event_time
        for event_time in event_times
    ):
        return "positive_window"
    if any(
        time_s - _SAMPLING_POLICY["negative_past_exclusion_s"]
        <= event_time
        <= time_s + _SAMPLING_POLICY["negative_future_exclusion_s"]
        for event_time in event_times
    ):
        return "point_event_exclusion_buffer"
    return None


def _candidate_id(video: str, time_s: float) -> str:
    return f"hard-negative-{sha256_mapping({'video': video, 'time_s': round(time_s, 6)})[:20]}"


def _build_candidate_manifest(
    root: Path,
    campaign: ModelCampaign,
    recipe: ModelRecipe,
    dataset: Mapping[str, Any],
    view: Path,
    checkpoint: Path,
    candidate_id: str,
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    split = _load_yaml(view / "split.yaml", "materialized split")
    train_names = split.get("train")
    if not isinstance(train_names, list) or any(not isinstance(item, str) for item in train_names):
        raise CardEventM9Error("materialized split has no valid train partition")
    train_set = set(train_names)
    if train_set & LEGACY_DEVICE_RECORDING_ID_SET:
        raise CardEventM9Error("legacy-device diagnostics entered the training partition")

    entries = {
        item.get("recording_id"): item
        for item in dataset.get("entries", [])
        if isinstance(item, Mapping) and isinstance(item.get("recording_id"), str)
    }
    train_entries: dict[str, Mapping[str, Any]] = {}
    for name in sorted(train_set):
        entry = entries.get(name)
        if entry is None or entry.get("partition") != "train":
            raise CardEventM9Error(
                f"training candidate {name} is not in the frozen train partition"
            )
        coverage = entry.get("review_coverage")
        if not isinstance(coverage, Mapping) or coverage.get("coverage_complete") is not True:
            raise CardEventM9Error(f"training candidate {name} lacks full review coverage")
        train_entries[name] = entry

    video_diagnostics = diagnostics.get("videos")
    if not isinstance(video_diagnostics, Mapping):
        raise CardEventM9Error("candidate diagnostics has no per-video diagnostics")
    train_diagnostics = video_diagnostics.get("train")
    if not isinstance(train_diagnostics, list):
        raise CardEventM9Error("candidate diagnostics has no train per-video diagnostics")
    diagnostics_by_video = {
        item.get("video"): item
        for item in train_diagnostics
        if isinstance(item, Mapping) and isinstance(item.get("video"), str)
    }
    candidates: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for video in sorted(train_set):
        entry = train_entries[video]
        video_payload = diagnostics_by_video.get(video)
        if not isinstance(video_payload, Mapping):
            raise CardEventM9Error(f"candidate diagnostics has no train result for {video}")
        false_events = video_payload.get("false_event_details")
        if not isinstance(false_events, list):
            raise CardEventM9Error(f"candidate diagnostics has no false-event details for {video}")
        event_path = _relative(root, entry.get("event_revision_content_path"), f"{video} events")
        intervals = _read_event_intervals(event_path, f"{video} event references")
        cache = view / "cache" / video / "metadata.json"
        cache_payload = _read_json(cache, f"{video} cache metadata")
        frame_times = cache_payload.get("frame_timestamps_s")
        if not isinstance(frame_times, list) or not frame_times:
            raise CardEventM9Error(f"{video} cache has no frame timestamps")
        parsed_frame_times = tuple(
            _number(value, f"{video} frame timestamp") for value in frame_times
        )
        local_seen: set[float] = set()
        for false_event in false_events:
            if not isinstance(false_event, Mapping):
                raise CardEventM9Error(f"{video} has an invalid false-event detail")
            source_time = _number(false_event.get("predicted_time_s"), f"{video} prediction time")
            probability = _number(false_event.get("probability"), f"{video} prediction score")
            nearest = min(parsed_frame_times, key=lambda item: (abs(item - source_time), item))
            for checked_time, _label in ((source_time, "prediction"), (nearest, "sample")):
                reason = _clean_negative_reason(checked_time, intervals)
                if reason is not None:
                    rejected[reason] = rejected.get(reason, 0) + 1
                    break
            else:
                if nearest in local_seen:
                    rejected["duplicate_sample"] = rejected.get("duplicate_sample", 0) + 1
                    continue
                local_seen.add(nearest)
                candidates.append(
                    {
                        "id": _candidate_id(video, nearest),
                        "video": video,
                        "time_s": nearest,
                        "source_prediction_time_s": source_time,
                        "probability": probability,
                        "reason": "unmatched_high_score_prediction",
                        "review_state": "pending",
                    }
                )
    candidates.sort(
        key=lambda item: (-float(item["probability"]), str(item["video"]), item["time_s"])
    )
    for rank, item in enumerate(candidates, start=1):
        item["rank"] = rank
    by_video: dict[str, list[dict[str, Any]]] = {name: [] for name in sorted(train_set)}
    for item in candidates:
        by_video[str(item["video"])].append(item)
    videos = [
        {
            "video": name,
            "duration_s": _number(
                next(
                    (
                        value.get("duration_us", 0) / 1_000_000
                        for value in (train_entries[name],)
                        if isinstance(value.get("duration_us"), int)
                    ),
                    0.0,
                ),
                f"{name} duration",
            ),
            "candidates": by_video[name],
        }
        for name in sorted(train_set)
    ]
    core: dict[str, Any] = {
        "schema_version": M9_CANDIDATE_SCHEMA_VERSION,
        "format": "cardevent-hard-negative-candidates-v1",
        "training_input": False,
        "status": "pending_human_review",
        "partition": "train",
        "campaign_id": campaign.campaign_id,
        "candidate_id": candidate_id,
        "recipe": {"id": recipe.recipe_id, "digest": recipe.digest},
        "checkpoint": {
            "path": checkpoint.relative_to(root).as_posix(),
            "sha256": _file_digest(checkpoint),
        },
        "data": recipe.data.to_mapping(),
        "sampling_policy": dict(_SAMPLING_POLICY),
        "exclusions": {
            "interval_interiors": True,
            "positive_windows": True,
            "point_event_exclusion_buffers": True,
            "validation": True,
            "test": True,
            "system_holdout": True,
            "legacy_device_diagnostics": True,
        },
        "candidate_count": len(candidates),
        "rejected_counts": rejected,
        "videos": videos,
    }
    return {**core, "manifest_digest": sha256_mapping(core)}


def _metrics_delta(champion: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, float]:
    keys = (
        "event_recall",
        "event_precision",
        "event_f1",
        "false_events_per_hour",
        "worst_video_f1",
        "timestamp_confirmation_delay_ms",
        "causal_confirmation_delay_ms",
    )
    result: dict[str, float] = {}
    for key in keys:
        left, right = champion.get(key), candidate.get(key)
        if (
            isinstance(left, (int, float))
            and not isinstance(left, bool)
            and isinstance(right, (int, float))
            and not isinstance(right, bool)
        ):
            result[key] = float(right) - float(left)
    return result


def _render_report(review: Mapping[str, Any]) -> str:
    comparison = review["comparison"]
    candidate = comparison["candidate_metrics"]
    champion = comparison["champion_metrics"]
    delta = comparison["metric_delta_candidate_minus_champion"]
    outcomes = comparison["outcomes"]
    lines = [
        "# CardEventNet M9 review",
        "",
        f"- Campaign: `{review['campaign_id']}`",
        f"- Dataset: `{review['lineage']['dataset']['id']}` "
        f"(`{review['lineage']['dataset']['digest']}`)",
        f"- Split: `{review['lineage']['split']['id']}` "
        f"(`{review['lineage']['split']['digest']}`)",
        f"- Decision: `{review['decision']['recommendation']}`",
        "",
        "## Validation comparison",
        "",
        "| Metric | M5 checkpoint | M8 candidate | Candidate minus M5 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in sorted(set(champion) | set(candidate)):
        lines.append(
            f"| `{key}` | {champion.get(key, '—')} | {candidate.get(key, '—')} | "
            f"{delta.get(key, '—')} |"
        )
    lines.extend(
        [
            "",
            "## Interval-aware outcomes",
            "",
            "| Run | Stable-end matches | Point matches | In-progress detections | "
            "Misses | Confirmed false triggers |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for label in ("champion", "candidate"):
        item = outcomes[label]
        lines.append(
            f"| `{label}` | {item['stable_end_matches']} | {item['point_matches']} | "
            f"{item['in_progress_detections']} | {item['misses']} | "
            f"{item['confirmed_false_triggers']} |"
        )
    lines.extend(
        [
            "",
            "## Gate decision",
            "",
            f"The candidate decision is `{review['decision']['recommendation']}`. "
            "No threshold, decoder, or recipe value was changed.",
            "",
            f"Hard-gate failures: `{', '.join(review['decision']['failed_gates']) or 'none'}`.",
            "",
            "## Hard-negative candidates",
            "",
            f"Manifest: `{review['hard_negative_manifest']['path']}`",
            f"Candidate count: `{review['hard_negative_manifest']['candidate_count']}`",
            "",
            "The manifest is training-only in scope but remains `training_input: false` "
            "until human review.",
            "It excludes interval interiors, positive windows, exclusion buffers, validation, "
            "test, "
            "system-holdout, and legacy-device diagnostics.",
            "",
        ]
    )
    return "\n".join(lines)


def review_cardeventnet_m9(
    campaign_id: str,
    *,
    repository_root: str | Path,
    campaign_root: str | Path | None = None,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Validate one completed M8 campaign and publish the M9 review artifacts."""
    root = Path(repository_root).resolve()
    campaigns = Path(campaign_root or root / "data" / "model-campaigns")
    if not campaigns.is_absolute():
        campaigns = root / campaigns
    campaign_dir = campaigns / campaign_id
    campaign = load_campaign(campaigns, campaign_id)
    comparison = load_campaign_comparison(campaigns, campaign)
    handoff = _validate_handoff(root, campaign_id, campaign_dir)
    recipe, view, dataset, _split = _validate_recipe_and_data(root, campaign, handoff, campaign_dir)
    if len(comparison.candidates) != 1:
        raise CardEventM9Error("M9 requires exactly one completed candidate")
    candidate_evaluation = comparison.candidates[0]
    if candidate_evaluation.candidate_id is None or candidate_evaluation.state != "success":
        raise CardEventM9Error("M9 requires a successful candidate evaluation")
    candidate_id = candidate_evaluation.candidate_id
    baseline, checkpoint = _validate_checkpoint_lineage(
        root,
        recipe,
        handoff,
        campaign_dir,
        candidate_id,
        candidate_evaluation.to_mapping(),
    )

    candidate_dir = campaign_dir / "candidates" / candidate_id
    candidate_raw = _read_json(candidate_dir / "cardevent-evaluation.json", "candidate evaluation")
    champion_raw = _read_json(campaign_dir / "champion-cardevent-evaluation.json", "M5 evaluation")
    candidate_transition = _read_json(
        candidate_dir / "cardevent-evaluation-transition-diagnostics.json",
        "candidate transition diagnostics",
    )
    champion_transition = _read_json(
        campaign_dir / "champion-cardevent-evaluation-transition-diagnostics.json",
        "M5 transition diagnostics",
    )
    diagnostics = _read_json(candidate_dir / "diagnostics.json", "candidate diagnostics")
    if candidate_raw.get("partition") != "val" or champion_raw.get("partition") != "val":
        raise CardEventM9Error("M9 comparison must use the validation partition")
    if candidate_transition.get("method") != "cardevent-transition-diagnostics-v1":
        raise CardEventM9Error("candidate transition diagnostics have an unsupported format")
    if champion_transition.get("method") != "cardevent-transition-diagnostics-v1":
        raise CardEventM9Error("M5 transition diagnostics have an unsupported format")
    if diagnostics.get("method") != "cardeventnet_train_validation_diagnostics":
        raise CardEventM9Error("candidate diagnostics have an unsupported format")
    if diagnostics.get("partition") != {"train": "train", "validation": "val"}:
        raise CardEventM9Error("candidate diagnostics do not identify train and validation")
    _same_mapping(
        candidate_raw.get("data_identity", {}).get("dataset"),
        recipe.data.dataset.to_mapping(),
        "candidate dataset identity",
    )
    _same_mapping(
        candidate_raw.get("data_identity", {}).get("split"),
        recipe.data.split.to_mapping(),
        "candidate split identity",
    )
    _same_mapping(
        champion_raw.get("data_identity", {}).get("dataset"),
        recipe.data.dataset.to_mapping(),
        "M5 dataset identity",
    )
    _same_mapping(
        champion_raw.get("data_identity", {}).get("split"),
        recipe.data.split.to_mapping(),
        "M5 split identity",
    )
    candidate_overall = candidate_raw.get("overall")
    champion_overall = champion_raw.get("overall")
    if not isinstance(candidate_overall, Mapping) or not isinstance(champion_overall, Mapping):
        raise CardEventM9Error("validation evaluations have no overall metrics")

    candidate_manifest = _build_candidate_manifest(
        root,
        campaign,
        recipe,
        dataset,
        view,
        checkpoint,
        candidate_id,
        diagnostics,
    )
    candidate_manifest_path = campaign_dir / "m9-hard-negative-candidates.json"
    _write_json(candidate_manifest_path, candidate_manifest)

    candidate_gates = [
        gate for gate in candidate_evaluation.gates if gate.hard and gate.status == "failed"
    ]
    decision = {
        "recommendation": "human_review_required",
        "locked_candidate_id": None,
        "failed_gates": [gate.gate_id for gate in candidate_gates],
        "source_recommendation": comparison.recommendation,
        "reason": (
            "candidate does not satisfy the declared hard gates; "
            "no candidate lock was created"
        ),
        "sealed_test_read": False,
        "threshold_tuned": False,
        "recipe_tuned": False,
    }
    lineage = {
        "recipe": {"id": recipe.recipe_id, "digest": recipe.digest},
        "dataset": recipe.data.dataset.to_mapping(),
        "split": recipe.data.split.to_mapping(),
        "baseline_checkpoint": {
            "path": baseline.relative_to(root).as_posix(),
            "sha256": _file_digest(baseline),
        },
        "candidate_checkpoint": {
            "path": checkpoint.relative_to(root).as_posix(),
            "sha256": _file_digest(checkpoint),
        },
        "decoder": recipe.candidates[0].configuration.get("decoder_settings"),
        "validation_partition": "val",
    }
    outcomes = {
        label: dict(_read_nested_diagnostics(payload, label))
        for label, payload in (
            ("champion", champion_transition),
            ("candidate", candidate_transition),
        )
    }
    champion_metrics = {**dict(champion_overall), **dict(comparison.champion.metrics)}
    candidate_metrics = {**dict(candidate_overall), **dict(candidate_evaluation.metrics)}
    review_core: dict[str, Any] = {
        "schema_version": M9_REVIEW_SCHEMA_VERSION,
        "campaign_id": campaign.campaign_id,
        "generated_at_utc": now_utc or campaign.updated_at_utc,
        "lineage": lineage,
        "decision": decision,
        "comparison": {
            "champion_metrics": champion_metrics,
            "candidate_metrics": candidate_metrics,
            "metric_delta_candidate_minus_champion": _metrics_delta(
                champion_metrics, candidate_metrics
            ),
            "outcomes": outcomes,
        },
        "hard_negative_manifest": {
            "path": candidate_manifest_path.relative_to(root).as_posix(),
            "digest": candidate_manifest["manifest_digest"],
            "candidate_count": candidate_manifest["candidate_count"],
            "training_input": False,
        },
    }
    review = {**review_core, "review_digest": sha256_mapping(review_core)}
    _write_json(campaign_dir / "m9-review.json", review)

    # M8 used no_valid_candidate for the mechanical comparison. M9 records the final
    # human-review state while keeping the comparison ID and all gate observations stable.
    review_comparison = ModelComparison.from_mapping(
        {
            **comparison.to_mapping(),
            "recommendation": "human_review_required",
            "recommended_candidate_id": None,
        }
    )
    updated_campaign = ModelCampaign.from_mapping(
        {
            **campaign.to_mapping(),
            "state": "human_review_required",
            "recommendation": "human_review_required",
            "lock_id": None,
            "updated_at_utc": now_utc or campaign.updated_at_utc,
        }
    )
    _write_json(campaign_dir / "comparison.json", review_comparison.to_mapping())
    _write_json(campaign_dir / "campaign.json", updated_campaign.to_mapping())
    report = _render_report(review)
    (campaign_dir / "m9-report.md").write_text(report, encoding="utf-8")
    review["report_path"] = (campaign_dir / "m9-report.md").relative_to(root).as_posix()
    return review


def _read_nested_diagnostics(payload: Mapping[str, Any], label: str) -> Mapping[str, int]:
    aggregate = payload.get("aggregate")
    if not isinstance(aggregate, Mapping):
        raise CardEventM9Error(f"{label} transition diagnostics have no aggregate")
    event_diagnostics = aggregate.get("event_diagnostics")
    if not isinstance(event_diagnostics, Mapping):
        raise CardEventM9Error(f"{label} transition diagnostics have no event outcomes")
    required = (
        "stable_end_matches",
        "point_matches",
        "in_progress_detections",
        "confirmed_false_triggers",
        "misses",
    )
    result: dict[str, int] = {}
    for key in required:
        value = event_diagnostics.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise CardEventM9Error(f"{label} transition diagnostics has invalid {key}")
        result[key] = value
    return result


__all__ = ["CardEventM9Error", "review_cardeventnet_m9"]
