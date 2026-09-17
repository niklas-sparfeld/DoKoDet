"""Publish the CardEventNet M10 validation timing-review handoff."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .model_improvement import sha256_mapping

M10_SCHEMA_VERSION = "cardeventnet-m10-timing-review/v1"
M10_GROUP_GAP_S = 2.0
M10_RECORDINGS = (
    "cardeventnet-IMG_0090",
    "cardeventnet-IMG_0644",
    "cardeventnet-IMG_0635",
    "cardeventnet-IMG_0652",
    "cardeventnet-IMG_0091",
    "cardeventnet-IMG_0661",
)

_CHECKLIST = {
    "cardeventnet-IMG_0090": {
        "reason": "false triggers, merged or near misses, and repeated decoder triggers",
        "miss_anchors_s": (29.743, 32.103, 50.044, 110.871),
        "prediction_times_s": (36.750, 48.500, 54.625, 61.000, 62.375, 64.125, 64.875, 71.125),
        "reviewed_intervals_s": (),
        "region_notes": ("Treat 61.000–64.875 seconds as one review region.",),
    },
    "cardeventnet-IMG_0644": {
        "reason": "the dominant false-trigger cluster and one missed card-state change",
        "miss_anchors_s": (17.510,),
        "prediction_times_s": (
            19.375,
            20.375,
            21.250,
            54.125,
            68.500,
            77.250,
            88.000,
            90.000,
            97.500,
        ),
        "reviewed_intervals_s": (),
        "region_notes": ("Treat 17.510–21.250 seconds as one review region.",),
    },
    "cardeventnet-IMG_0635": {
        "reason": "possible missing or shifted point events",
        "miss_anchors_s": (46.529, 49.781, 56.286, 58.037, 67.292),
        "prediction_times_s": (65.750, 94.125),
        "reviewed_intervals_s": (),
        "region_notes": ("Compare the 65.750-second prediction with the 67.292-second miss.",),
    },
    "cardeventnet-IMG_0652": {
        "reason": "the only reviewed trick-clear interval without a decoded trigger",
        "miss_anchors_s": (9.509, 12.262, 23.021, 34.283, 69.066, 73.819),
        "prediction_times_s": (),
        "reviewed_intervals_s": ((21.021, 23.021),),
        "region_notes": ("Inspect the reviewed interval from 21.021 to 23.021 seconds.",),
    },
    "cardeventnet-IMG_0091": {
        "reason": "timing-only review; no confirmed false triggers",
        "miss_anchors_s": (9.217, 22.269, 60.139, 90.442, 99.526),
        "prediction_times_s": (),
        "reviewed_intervals_s": (),
        "region_notes": (
            "Re-annotate only when the current interval start or stable end is wrong.",
        ),
    },
    "cardeventnet-IMG_0661": {
        "reason": "merged and timing-sensitive events",
        "miss_anchors_s": (15.013, 25.775, 37.537, 61.308, 66.315, 74.573, 84.833),
        "prediction_times_s": (89.250,),
        "reviewed_intervals_s": (),
        "region_notes": (
            "Keep valid close events instead of moving them to satisfy the decoder gap.",
        ),
    },
}


class CardEventM10Error(ValueError):
    """Raised when the M10 source artifacts are incomplete or inconsistent."""


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM10Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, dict):
        raise CardEventM10Error(f"{context} {path} must contain an object")
    return value


def _read_gzip_json(path: Path, context: str) -> dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM10Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, dict):
        raise CardEventM10Error(f"{context} {path} must contain an object")
    return value


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise CardEventM10Error(f"Could not hash {path}: {error}") from error
    return digest.hexdigest()


def _required_file(path: Path, context: str) -> Path:
    if not path.is_file():
        raise CardEventM10Error(f"{context} is missing: {path}")
    return path


def _relative(root: Path, value: object, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CardEventM10Error(f"{context} must be a repository-relative path")
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise CardEventM10Error(f"{context} must stay inside the repository") from error
    return path


def _number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardEventM10Error(f"{context} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise CardEventM10Error(f"{context} must be finite")
    return result


def _rounded_times(values: Sequence[object], context: str) -> tuple[float, ...]:
    return tuple(round(_number(value, context), 3) for value in values)


def _verify_handoff(root: Path, campaign_dir: Path) -> dict[str, Any]:
    handoff = _read_json(campaign_dir / "handoff.json", "M9 ablation handoff")
    digest = handoff.get("handoff_sha256")
    core = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    legacy_digest = hashlib.sha256(json.dumps(core, sort_keys=True).encode("utf-8")).hexdigest()
    if digest not in {sha256_mapping(core), legacy_digest}:
        raise CardEventM10Error("M9 ablation handoff digest does not match its contents")
    if handoff.get("schema_version") != "cardeventnet-hard-negative-ablation-handoff/v1":
        raise CardEventM10Error("M9 ablation handoff has an unsupported schema")
    if handoff.get("status") != "ready":
        raise CardEventM10Error("M9 ablation handoff is not ready")
    manifest = handoff.get("manifest")
    if not isinstance(manifest, Mapping):
        raise CardEventM10Error("M9 ablation handoff has no manifest lineage")
    manifest_path = _relative(root, manifest.get("path"), "hard-negative manifest")
    _required_file(manifest_path, "hard-negative manifest")
    if _file_digest(manifest_path) != manifest.get("sha256"):
        raise CardEventM10Error("hard-negative manifest digest differs from M9 handoff")
    return handoff


def _load_config(path: Path) -> dict[str, Any]:
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError) as error:
        raise CardEventM10Error(f"Could not read CardEventNet config {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM10Error(f"CardEventNet config {path} must contain an object")
    return dict(value)


def _load_lineage(
    root: Path, handoff: Mapping[str, Any], diagnostics: Mapping[str, Any]
) -> tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any]]:
    data_identity = diagnostics.get("data_identity")
    if not isinstance(data_identity, Mapping):
        raise CardEventM10Error("M9 diagnostics have no data identity")
    dataset_identity = data_identity.get("dataset")
    split_identity = data_identity.get("split")
    if not isinstance(dataset_identity, Mapping) or not isinstance(split_identity, Mapping):
        raise CardEventM10Error("M9 diagnostics have incomplete data identity")
    dataset_id = dataset_identity.get("id")
    dataset_digest = dataset_identity.get("digest")
    split_id = split_identity.get("id")
    split_digest = split_identity.get("digest")
    for value, context in (
        (dataset_id, "dataset ID"),
        (dataset_digest, "dataset digest"),
        (split_id, "split ID"),
        (split_digest, "split digest"),
    ):
        if not isinstance(value, str) or not value:
            raise CardEventM10Error(f"M9 diagnostics has no valid {context}")
    fixed_inputs = handoff.get("fixed_inputs")
    if not isinstance(fixed_inputs, Mapping):
        raise CardEventM10Error("M9 ablation handoff has no fixed inputs")
    view = _relative(root, fixed_inputs.get("dataset_view"), "materialized dataset view")
    materialization = _read_json(view / "materialization.json", "M7 materialization")
    if materialization.get("dataset") != dict(dataset_identity):
        raise CardEventM10Error("M7 materialization dataset differs from M9 diagnostics")
    if materialization.get("split") != dict(split_identity):
        raise CardEventM10Error("M7 materialization split differs from M9 diagnostics")
    dataset_dir = root / "data" / "operations" / "cardevent-datasets" / str(dataset_id)
    dataset = _read_json(dataset_dir / "dataset.json", "M7 dataset")
    split = _read_json(dataset_dir / "split.json", "M7 split")
    if dataset.get("dataset_version_id") != dataset_id:
        raise CardEventM10Error("M7 dataset ID differs from M9 diagnostics")
    if dataset.get("dataset_version_digest") != dataset_digest:
        raise CardEventM10Error("M7 dataset digest differs from M9 diagnostics")
    if split.get("split_version_id") != split_id:
        raise CardEventM10Error("M7 split ID differs from M9 diagnostics")
    if split.get("split_version_digest") != split_digest:
        raise CardEventM10Error("M7 split digest differs from M9 diagnostics")
    if set(split.get("validation", [])) != set(M10_RECORDINGS):
        raise CardEventM10Error("M7 validation split does not match the M10 review set")
    return (
        {
            "dataset": {"id": dataset_id, "digest": dataset_digest},
            "split": {"id": split_id, "digest": split_digest},
            "materialized_view": view.relative_to(root).as_posix(),
            "materialization": {
                "path": (view / "materialization.json").relative_to(root).as_posix(),
                "sha256": _file_digest(view / "materialization.json"),
                "manifest_digest": materialization.get("manifest_digest"),
            },
        },
        view,
        dataset,
        split,
    )


def _frame_reference(
    root: Path,
    *,
    recording_id: str,
    requested_time_s: float,
    role: str,
    cache_metadata_path: Path,
    source_video_path: Path,
    source_sha256: str,
) -> dict[str, Any]:
    metadata = _read_json(cache_metadata_path, f"{recording_id} cache metadata")
    raw_times = metadata.get("frame_timestamps_s")
    if not isinstance(raw_times, list) or not raw_times:
        raise CardEventM10Error(f"{recording_id} cache has no frame timestamps")
    frame_times = tuple(_number(value, f"{recording_id} frame timestamp") for value in raw_times)
    frame_index = min(
        range(len(frame_times)),
        key=lambda index: (abs(frame_times[index] - requested_time_s), index),
    )
    frame_time_s = frame_times[frame_index]
    return {
        "frame_id": f"{recording_id}-frame-{frame_index:06d}",
        "frame_index": frame_index,
        "role": role,
        "requested_time_s": round(requested_time_s, 6),
        "time_s": round(frame_time_s, 6),
        "time_us": int(round(frame_time_s * 1_000_000)),
        "source_video_path": source_video_path.relative_to(root).as_posix(),
        "source_video_sha256": source_sha256,
        "cache_metadata_path": cache_metadata_path.relative_to(root).as_posix(),
    }


def _reference_lineage(
    root: Path, dataset: Mapping[str, Any], recording_id: str
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    entries = dataset.get("entries")
    if not isinstance(entries, list):
        raise CardEventM10Error("M7 dataset has no entries")
    entry = next(
        (
            item
            for item in entries
            if isinstance(item, Mapping) and item.get("recording_id") == recording_id
        ),
        None,
    )
    if not isinstance(entry, Mapping) or entry.get("partition") != "validation":
        raise CardEventM10Error(f"{recording_id} is not a M7 validation entry")
    content_path = _relative(
        root, entry.get("event_revision_content_path"), f"{recording_id} event content"
    )
    manifest_path = _relative(
        root, entry.get("event_revision_manifest_path"), f"{recording_id} event manifest"
    )
    _required_file(content_path, f"{recording_id} event content")
    _required_file(manifest_path, f"{recording_id} event manifest")
    if _file_digest(content_path) != entry.get("event_revision_content_sha256"):
        raise CardEventM10Error(f"{recording_id} event content digest differs from M7")
    if _file_digest(manifest_path) != entry.get("event_revision_manifest_sha256"):
        raise CardEventM10Error(f"{recording_id} event manifest digest differs from M7")
    source_video_path = _relative(root, entry.get("source_path"), f"{recording_id} source video")
    _required_file(source_video_path, f"{recording_id} source video")
    return (
        {
            "recording_id": recording_id,
            "event_revision_id": entry.get("event_revision_id"),
            "event_revision_content_path": content_path.relative_to(root).as_posix(),
            "event_revision_content_sha256": entry.get("event_revision_content_sha256"),
            "event_revision_manifest_path": manifest_path.relative_to(root).as_posix(),
            "event_revision_manifest_sha256": entry.get("event_revision_manifest_sha256"),
            "review_coverage": entry.get("review_coverage"),
            "source_asset_id": entry.get("source_asset_id"),
            "source_video_path": source_video_path.relative_to(root).as_posix(),
            "source_video_sha256": entry.get("source_sha256"),
        },
        entry,
    )


def _validate_stream_reference(
    root: Path,
    *,
    stream: Mapping[str, Any],
    reference: Mapping[str, Any],
    view: Path,
    recording_id: str,
) -> None:
    annotation_path = view / "annotations" / f"{recording_id}.json"
    annotation_digest = _file_digest(_required_file(annotation_path, f"{recording_id} annotation"))
    if stream.get("annotation_version_hash") != annotation_digest:
        raise CardEventM10Error(f"{recording_id} validation stream uses a different annotation")
    generated_files = _read_json(view / "materialization.json", "M7 materialization").get(
        "generated_files"
    )
    matching = next(
        (
            item
            for item in generated_files or []
            if isinstance(item, Mapping) and item.get("path") == f"annotations/{recording_id}.json"
        ),
        None,
    )
    if not isinstance(matching, Mapping) or matching.get("sha256") != annotation_digest:
        raise CardEventM10Error(f"{recording_id} annotation is not bound to M7 materialization")
    if reference.get("review_coverage", {}).get("coverage_complete") is not True:
        raise CardEventM10Error(f"{recording_id} reference coverage is incomplete")


def _item(
    root: Path,
    *,
    recording_id: str,
    kind: str,
    time_s: float,
    focus_range_s: tuple[float, float],
    model_outcome: Mapping[str, Any],
    reference: Mapping[str, Any],
    entry: Mapping[str, Any],
    view: Path,
) -> dict[str, Any]:
    source_video_path = _relative(root, entry.get("source_path"), f"{recording_id} source video")
    cache_path = view / "cache" / recording_id / "metadata.json"
    evidence_times: list[tuple[str, float]] = []
    if kind == "missed_event":
        evidence_times.append(("reference_anchor", time_s))
    elif kind == "confirmed_false_trigger":
        evidence_times.append(("model_prediction", time_s))
    else:
        evidence_times.extend(
            (
                ("model_prediction", time_s),
                ("interval_start", _number(model_outcome["interval_start_s"], "interval start")),
                ("interval_end", _number(model_outcome["interval_end_s"], "interval end")),
            )
        )
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for role, requested_time_s in evidence_times:
        frame = _frame_reference(
            root,
            recording_id=recording_id,
            requested_time_s=requested_time_s,
            role=role,
            cache_metadata_path=cache_path,
            source_video_path=source_video_path,
            source_sha256=str(entry.get("source_sha256")),
        )
        key = (role, frame["frame_index"])
        if key not in seen:
            seen.add(key)
            evidence.append(frame)
    if kind == "missed_event":
        question = "Is a reviewed card-state change absent or timed incorrectly?"
    elif kind == "in_progress_detection":
        question = "Is this prediction inside one continuous reviewed interval?"
    else:
        question = "Is this a real no-event trigger after the reference is confirmed?"
    return {
        "recording_id": recording_id,
        "kind": kind,
        "time_s": round(time_s, 6),
        "focus_range_s": [round(focus_range_s[0], 6), round(focus_range_s[1], 6)],
        "reference_revision": dict(reference),
        "model_outcome": dict(model_outcome),
        "review_question": question,
        "source_frame_evidence": evidence,
    }


def _build_items(
    root: Path,
    *,
    evaluation: Mapping[str, Any],
    streams: Mapping[str, Any],
    dataset: Mapping[str, Any],
    view: Path,
) -> list[dict[str, Any]]:
    raw_videos = evaluation.get("videos")
    stream_videos = streams.get("videos")
    if not isinstance(raw_videos, list) or not isinstance(stream_videos, list):
        raise CardEventM10Error("M9 evaluation or validation streams have no videos")
    by_stream = {
        item.get("video"): item
        for item in stream_videos
        if isinstance(item, Mapping) and isinstance(item.get("video"), str)
    }
    by_evaluation = {
        item.get("video"): item
        for item in raw_videos
        if isinstance(item, Mapping) and isinstance(item.get("video"), str)
    }
    if set(by_evaluation) != set(M10_RECORDINGS) or set(by_stream) != set(M10_RECORDINGS):
        raise CardEventM10Error("M9 validation artifacts do not contain the six M10 recordings")
    items: list[dict[str, Any]] = []
    for recording_id in M10_RECORDINGS:
        evaluation_video = by_evaluation[recording_id]
        stream = by_stream[recording_id]
        reference, entry = _reference_lineage(root, dataset, recording_id)
        _validate_stream_reference(
            root,
            stream=stream,
            reference=reference,
            view=view,
            recording_id=recording_id,
        )
        for missed in evaluation_video.get("missed_event_details", []):
            if not isinstance(missed, Mapping):
                raise CardEventM10Error(f"{recording_id} has an invalid missed-event detail")
            time_s = _number(missed.get("ground_truth_time_s"), f"{recording_id} miss time")
            items.append(
                _item(
                    root,
                    recording_id=recording_id,
                    kind="missed_event",
                    time_s=time_s,
                    focus_range_s=(time_s, time_s),
                    model_outcome={
                        "category": missed.get("category"),
                        "max_probability_near_event": missed.get("max_probability_near_event"),
                    },
                    reference=reference,
                    entry=entry,
                    view=view,
                )
            )
        for false_event in evaluation_video.get("false_event_details", []):
            if not isinstance(false_event, Mapping):
                raise CardEventM10Error(f"{recording_id} has an invalid false-event detail")
            time_s = _number(
                false_event.get("predicted_time_s"), f"{recording_id} false trigger time"
            )
            items.append(
                _item(
                    root,
                    recording_id=recording_id,
                    kind="confirmed_false_trigger",
                    time_s=time_s,
                    focus_range_s=(time_s, time_s),
                    model_outcome={"probability": false_event.get("probability")},
                    reference=reference,
                    entry=entry,
                    view=view,
                )
            )
        for in_progress in evaluation_video.get("in_progress_detection_details", []):
            if not isinstance(in_progress, Mapping):
                raise CardEventM10Error(f"{recording_id} has an invalid in-progress detail")
            time_s = _number(in_progress.get("predicted_time_s"), f"{recording_id} prediction time")
            start_s = _number(in_progress.get("interval_start_s"), f"{recording_id} interval start")
            end_s = _number(in_progress.get("interval_end_s"), f"{recording_id} interval end")
            if end_s < start_s:
                raise CardEventM10Error(f"{recording_id} has an unordered in-progress interval")
            items.append(
                _item(
                    root,
                    recording_id=recording_id,
                    kind="in_progress_detection",
                    time_s=time_s,
                    focus_range_s=(time_s, time_s),
                    model_outcome={
                        "probability": in_progress.get("probability"),
                        "interval_start_s": start_s,
                        "interval_end_s": end_s,
                    },
                    reference=reference,
                    entry=entry,
                    view=view,
                )
            )
    return items


def _group_regions(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for item in sorted(
        items,
        key=lambda value: (
            str(value["recording_id"]),
            float(value["focus_range_s"][0]),
            str(value["kind"]),
            float(value["time_s"]),
        ),
    ):
        recording_id = str(item["recording_id"])
        start_s, end_s = (float(value) for value in item["focus_range_s"])
        current = regions[-1] if regions else None
        if (
            current is None
            or current["recording_id"] != recording_id
            or start_s > float(current["focus_range_s"][1]) + M10_GROUP_GAP_S
        ):
            regions.append(
                {
                    "region_id": f"m10-region-{len(regions) + 1:03d}",
                    "recording_id": recording_id,
                    "focus_range_s": [round(start_s, 6), round(end_s, 6)],
                    "item_ids": [],
                }
            )
            current = regions[-1]
        current["focus_range_s"][1] = round(max(float(current["focus_range_s"][1]), end_s), 6)
        current["item_ids"].append(_item_id(item))
    return regions


def _item_id(item: Mapping[str, Any]) -> str:
    return f"{item['recording_id']}-{item['kind']}-{float(item['time_s']):.6f}"


def _validate_operator_checklist(items: Sequence[Mapping[str, Any]]) -> None:
    by_recording: dict[str, list[Mapping[str, Any]]] = {
        recording: [] for recording in M10_RECORDINGS
    }
    for item in items:
        by_recording[str(item["recording_id"])].append(item)
    for recording_id, checklist in _CHECKLIST.items():
        recording_items = by_recording[recording_id]
        misses = tuple(
            sorted(
                round(float(item["time_s"]), 3)
                for item in recording_items
                if item["kind"] == "missed_event"
            )
        )
        predictions = tuple(
            sorted(
                round(float(item["time_s"]), 3)
                for item in recording_items
                if item["kind"] == "confirmed_false_trigger"
            )
        )
        if misses != tuple(checklist["miss_anchors_s"]):
            raise CardEventM10Error(f"M10 miss checklist does not match {recording_id}")
        if predictions != tuple(checklist["prediction_times_s"]):
            raise CardEventM10Error(f"M10 prediction checklist does not match {recording_id}")


def _operator_checklist(
    root: Path, campaign_dir: Path, items: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_recording: dict[str, list[Mapping[str, Any]]] = {
        recording: [] for recording in M10_RECORDINGS
    }
    for item in items:
        by_recording[str(item["recording_id"])].append(item)
    result = []
    for order, recording_id in enumerate(M10_RECORDINGS, start=1):
        checklist = _CHECKLIST[recording_id]
        route = f"http://127.0.0.1:5173/recordings/{recording_id}/pipeline/events"
        result.append(
            {
                "order": order,
                "recording_id": recording_id,
                "route": route,
                "reason": checklist["reason"],
                "miss_anchors_s": list(checklist["miss_anchors_s"]),
                "prediction_times_s": list(checklist["prediction_times_s"]),
                "in_progress_prediction_times_s": [
                    round(float(item["time_s"]), 3)
                    for item in by_recording[recording_id]
                    if item["kind"] == "in_progress_detection"
                ],
                "reviewed_intervals_s": [
                    list(interval) for interval in checklist["reviewed_intervals_s"]
                ],
                "notes": list(checklist["region_notes"]),
                "review_packet_path": campaign_dir.relative_to(root).as_posix()
                + "/m10-timing-review.json",
            }
        )
    return result


def _render_report(packet: Mapping[str, Any]) -> str:
    lineage = packet["lineage"]
    selection = packet["selection"]
    lines = [
        "# CardEventNet M10 timing-review handoff",
        "",
        f"- Campaign: `{packet['campaign_id']}`",
        f"- Packet: `{packet['packet_path']}`",
        f"- Packet digest: `{packet['packet_digest']}`",
        f"- Selected checkpoint: `{selection['checkpoint']['path']}`",
        f"- Checkpoint SHA-256: `{selection['checkpoint']['sha256']}`",
        f"- Validation threshold: `{selection['threshold']}`",
        f"- Decoder: `{json.dumps(selection['decoder'], sort_keys=True)}`",
        f"- Raw review items: `{packet['counts']['raw_items']}`",
        f"- Grouped review regions: `{packet['counts']['regions']}`",
        "",
        "M10 is a read-only handoff. Do not change a maintained reference from this report. "
        "If the reference is wrong, create and complete a new draft in the recording workspace.",
        "",
        "## M7 and validation lineage",
        "",
        f"- Dataset: `{lineage['dataset']['id']}` (`{lineage['dataset']['digest']}`)",
        f"- Split: `{lineage['split']['id']}` (`{lineage['split']['digest']}`)",
        f"- Materialized view: `{lineage['materialized_view']}`",
        f"- Validation stream: `{lineage['validation_stream']['path']}` "
        f"(`{lineage['validation_stream']['sha256']}`)",
        "",
        "## Ordered operator checklist",
        "",
    ]
    for item in packet["operator_checklist"]:
        lines.append(f"{item['order']}. **Review `{item['recording_id']}`.** {item['reason']}.")
        miss_anchors = ", ".join(f"{value:.3f}" for value in item["miss_anchors_s"])
        lines.append(f"   - Miss anchors: `{miss_anchors}` seconds.")
        if item["prediction_times_s"]:
            lines.append(
                "   - Predictions: `"
                + ", ".join(f"{value:.3f}" for value in item["prediction_times_s"])
                + "` seconds."
            )
        if item["in_progress_prediction_times_s"]:
            lines.append(
                "   - In-progress predictions: `"
                + ", ".join(f"{value:.3f}" for value in item["in_progress_prediction_times_s"])
                + "` seconds."
            )
        for start_s, end_s in item["reviewed_intervals_s"]:
            lines.append(f"   - Reviewed interval: `{start_s:.3f}–{end_s:.3f}` seconds.")
        for note in item["notes"]:
            lines.append(f"   - {note}")
        lines.append(f"   - Workspace: {item['route']}")
    lines.extend(
        [
            "",
            "## Review regions",
            "",
            "The grouping policy joins adjacent focus times within "
            f"`{M10_GROUP_GAP_S:.3f}` seconds. Each raw item remains in the packet.",
            "",
            "| Region | Recording | Focus range (s) | Items |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    item_by_id = {_item_id(item): item for item in packet["items"]}
    for region in packet["regions"]:
        kinds = ", ".join(item_by_id[item_id]["kind"] for item_id in region["item_ids"])
        start_s, end_s = region["focus_range_s"]
        lines.append(
            f"| `{region['region_id']}` | `{region['recording_id']}` | "
            f"`{start_s:.6f}–{end_s:.6f}` | {len(region['item_ids'])} ({kinds}) |"
        )
    lines.extend(
        [
            "",
            "## Local review commands",
            "",
            "From the repository root, start the local backend in one terminal:",
            "",
            "```bash",
            "mise exec -- uv run --project backend dokodetector-backend",
            "```",
            "",
            "Start the web workspace in a second terminal:",
            "",
            "```bash",
            "cd web",
            "mise exec -- npm run dev",
            "```",
            "",
            "Open the workspace routes in the printed checklist order:",
            "",
        ]
    )
    lines.extend(
        f"{index}. {item['route']}"
        for index, item in enumerate(packet["operator_checklist"], start=1)
    )
    lines.extend(
        [
            "",
            "Complete the operator review in the recording workspace. The exact handoff artifact "
            f"to complete is `{packet['operator_completion_artifact']}`. Keep correct point and "
            "interval references unchanged; publish a new completed revision only when the "
            "reference is wrong and full-source coverage is recorded.",
            "",
            "M10 stops here. It does not create a dataset, tune the decoder, start training, read "
            "the sealed test partition, or read the system holdout.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_deterministic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise CardEventM10Error(
                f"Could not read existing M10 artifact {path}: {error}"
            ) from error
        if existing != encoded:
            raise CardEventM10Error(
                f"existing M10 artifact differs from deterministic output: {path}"
            )
        return
    try:
        path.write_bytes(encoded)
    except OSError as error:
        raise CardEventM10Error(f"Could not write M10 artifact {path}: {error}") from error


def _write_or_preserve_operator_completion(
    path: Path, completion: Mapping[str, Any]
) -> None:
    """Write the initial checklist, or preserve a valid operator edit on rerun."""

    if not path.exists():
        _write_deterministic(path, json.dumps(completion, indent=2, sort_keys=True) + "\n")
        return
    existing = _read_json(path, "existing M10 operator completion")
    if existing.get("schema_version") != completion["schema_version"]:
        raise CardEventM10Error("existing M10 operator completion has an unsupported schema")
    if existing.get("packet") != completion["packet"]:
        raise CardEventM10Error("existing M10 operator completion is bound to another packet")
    if existing.get("allowed_decisions") != completion["allowed_decisions"]:
        raise CardEventM10Error("existing M10 operator completion has different allowed decisions")
    expected_recordings = {
        item["recording_id"]: item["route"] for item in completion["recordings"]
    }
    actual_recordings = {
        item.get("recording_id"): item.get("route")
        for item in existing.get("recordings", [])
        if isinstance(item, Mapping)
    }
    if actual_recordings != expected_recordings:
        raise CardEventM10Error("existing M10 operator completion has different recordings")
    expected_regions = {
        item["region_id"]: (item["recording_id"], tuple(item["item_ids"]))
        for item in completion["regions"]
    }
    actual_regions = {
        item.get("region_id"): (
            item.get("recording_id"),
            tuple(item.get("item_ids", [])),
        )
        for item in existing.get("regions", [])
        if isinstance(item, Mapping)
    }
    if actual_regions != expected_regions:
        raise CardEventM10Error("existing M10 operator completion has different regions")


def publish_cardeventnet_m10_timing_review(
    campaign_id: str,
    *,
    repository_root: str | Path,
    campaign_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate M9 artifacts and publish the deterministic M10 review packet."""

    root = Path(repository_root).resolve()
    campaigns = Path(campaign_root or root / "data" / "model-campaigns")
    if not campaigns.is_absolute():
        campaigns = root / campaigns
    campaign_dir = (campaigns / campaign_id).resolve()
    try:
        campaign_dir.relative_to(root)
    except ValueError as error:
        raise CardEventM10Error("campaign directory must stay inside the repository") from error
    handoff = _verify_handoff(root, campaign_dir)
    evaluation = _read_json(campaign_dir / "validation-evaluation.json", "M9 validation evaluation")
    transition = _read_json(
        campaign_dir / "validation-evaluation-transition-diagnostics.json",
        "M9 transition diagnostics",
    )
    diagnostics = _read_json(campaign_dir / "diagnostics.json", "M9 diagnostics")
    streams_path = _required_file(
        campaign_dir / "validation-streams" / "evaluation.json.gz", "M9 validation streams"
    )
    streams = _read_gzip_json(streams_path, "M9 validation streams")
    if evaluation.get("method") != "cardeventnet" or evaluation.get("partition") != "val":
        raise CardEventM10Error("M9 validation evaluation must be a validation result")
    if transition.get("method") != "cardevent-transition-diagnostics-v1":
        raise CardEventM10Error("M9 transition diagnostics have an unsupported format")
    if diagnostics.get("method") != "cardeventnet_train_validation_diagnostics":
        raise CardEventM10Error("M9 diagnostics have an unsupported format")
    if streams.get("format") != "cardevent-validation-stream-v1":
        raise CardEventM10Error("M9 validation streams have an unsupported format")
    threshold = _number(evaluation.get("threshold"), "validation threshold")
    if threshold != _number(transition.get("threshold"), "diagnostic threshold"):
        raise CardEventM10Error("M9 evaluation and transition thresholds differ")
    checkpoint_path = _relative(root, diagnostics.get("checkpoint"), "selected checkpoint")
    _required_file(checkpoint_path, "selected checkpoint")
    checkpoint_sha256 = _file_digest(checkpoint_path)
    threshold_path = checkpoint_path.parent / "threshold.json"
    if threshold_path.is_file():
        threshold_payload = _read_json(threshold_path, "selected threshold")
        if threshold_payload.get("checkpoint") != diagnostics.get("checkpoint"):
            raise CardEventM10Error("selected threshold references a different checkpoint")
        if threshold_payload.get("threshold") != threshold:
            raise CardEventM10Error("selected threshold differs from validation evaluation")
    config = _load_config(checkpoint_path.parent / "config.yaml")
    inference = config.get("inference")
    if not isinstance(inference, Mapping):
        raise CardEventM10Error("selected checkpoint config has no inference settings")
    decoder = {
        "peak_confirmation_s": _number(inference.get("peak_confirmation_s"), "peak confirmation"),
        "min_event_gap_s": _number(inference.get("min_event_gap_s"), "minimum event gap"),
    }
    diagnostic_timing = transition.get("diagnostic_timing")
    if not isinstance(diagnostic_timing, Mapping):
        raise CardEventM10Error("M9 transition diagnostics have no timing policy")
    if decoder["min_event_gap_s"] != _number(
        diagnostic_timing.get("merge_window_s"), "merge window"
    ):
        raise CardEventM10Error("decoder minimum event gap differs from diagnostic merge window")
    lineage, view, dataset, split = _load_lineage(root, handoff, diagnostics)
    del split
    items = _build_items(root, evaluation=evaluation, streams=streams, dataset=dataset, view=view)
    _validate_operator_checklist(items)
    transition_aggregate = transition.get("aggregate")
    transition_events = (
        transition_aggregate.get("event_diagnostics")
        if isinstance(transition_aggregate, Mapping)
        else None
    )
    expected_transition_counts = {
        "misses": sum(item["kind"] == "missed_event" for item in items),
        "confirmed_false_triggers": sum(
            item["kind"] == "confirmed_false_trigger" for item in items
        ),
        "in_progress_detections": sum(item["kind"] == "in_progress_detection" for item in items),
    }
    if not isinstance(transition_events, Mapping) or any(
        transition_events.get(key) != value for key, value in expected_transition_counts.items()
    ):
        raise CardEventM10Error("M9 transition diagnostics counts differ from the evaluation")
    regions = _group_regions(items)
    lineage["validation_stream"] = {
        "path": streams_path.relative_to(root).as_posix(),
        "sha256": _file_digest(streams_path),
    }
    lineage["evaluation"] = {
        "path": (campaign_dir / "validation-evaluation.json").relative_to(root).as_posix(),
        "sha256": _file_digest(campaign_dir / "validation-evaluation.json"),
    }
    lineage["transition_diagnostics"] = {
        "path": (campaign_dir / "validation-evaluation-transition-diagnostics.json")
        .relative_to(root)
        .as_posix(),
        "sha256": _file_digest(campaign_dir / "validation-evaluation-transition-diagnostics.json"),
    }
    core: dict[str, Any] = {
        "schema_version": M10_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "source_campaign": {
            "campaign_id": campaign_id,
            "handoff_path": (campaign_dir / "handoff.json").relative_to(root).as_posix(),
            "handoff_sha256": handoff["handoff_sha256"],
        },
        "lineage": lineage,
        "selection": {
            "checkpoint": {
                "path": checkpoint_path.relative_to(root).as_posix(),
                "sha256": checkpoint_sha256,
            },
            "threshold": threshold,
            "decoder": decoder,
            "partition": "validation",
        },
        "grouping_policy": {
            "version": "m10-adjacent-focus-v1",
            "max_gap_s": M10_GROUP_GAP_S,
            "interval_focus": (
                "in_progress items retain their reference interval separately; "
                "grouping uses prediction time"
            ),
        },
        "counts": {
            "raw_items": len(items),
            "missed_events": sum(item["kind"] == "missed_event" for item in items),
            "confirmed_false_triggers": sum(
                item["kind"] == "confirmed_false_trigger" for item in items
            ),
            "in_progress_detections": sum(
                item["kind"] == "in_progress_detection" for item in items
            ),
            "regions": len(regions),
        },
        "items": [
            {**item, "item_id": _item_id(item)}
            for item in sorted(items, key=lambda item: (_item_id(item),))
        ],
        "regions": regions,
        "operator_checklist": _operator_checklist(root, campaign_dir, items),
        "operator_completion_artifact": (campaign_dir / "m10-operator-review.json")
        .relative_to(root)
        .as_posix(),
        "sealed_test_read": False,
        "system_holdout_read": False,
    }
    packet = {**core, "packet_digest": sha256_mapping(core)}
    packet_path = campaign_dir / "m10-timing-review.json"
    packet["packet_path"] = packet_path.relative_to(root).as_posix()
    packet_json = json.dumps(packet, indent=2, sort_keys=True) + "\n"
    _write_deterministic(packet_path, packet_json)
    completion_path = campaign_dir / "m10-operator-review.json"
    completion = {
        "schema_version": "cardeventnet-m10-operator-review/v1",
        "status": "pending_operator_review",
        "packet": {
            "path": packet["packet_path"],
            "sha256": packet["packet_digest"],
        },
        "allowed_decisions": [
            "reference_corrected",
            "reference_confirmed",
            "no_event_confirmed",
        ],
        "recordings": [
            {
                "recording_id": recording_id,
                "route": checklist["route"],
                "decision": None,
                "notes": None,
            }
            for recording_id, checklist in zip(
                M10_RECORDINGS, packet["operator_checklist"], strict=True
            )
        ],
        "regions": [
            {
                "region_id": region["region_id"],
                "recording_id": region["recording_id"],
                "item_ids": region["item_ids"],
                "decision": None,
                "notes": None,
            }
            for region in regions
        ],
        "completion_rule": (
            "The operator completes every recording and region after inspecting the full action. "
            "A corrected reference must be published as a new completed revision."
        ),
    }
    _write_or_preserve_operator_completion(completion_path, completion)
    report = _render_report(packet)
    report_path = campaign_dir / "m10-report.md"
    _write_deterministic(report_path, report)
    packet["report_path"] = report_path.relative_to(root).as_posix()
    return packet


def render_cardeventnet_m10_human(packet: Mapping[str, Any]) -> str:
    """Render the concise M10 CLI result."""

    return (
        "CardEventNet M10 timing-review handoff\n"
        f"campaign: {packet['campaign_id']}\n"
        f"review items: {packet['counts']['raw_items']}\n"
        f"review regions: {packet['counts']['regions']}\n"
        f"packet: {packet['packet_path']}\n"
        f"report: {packet['report_path']}\n"
        "sealed test read: false\n"
    )


__all__ = [
    "CardEventM10Error",
    "M10_GROUP_GAP_S",
    "M10_RECORDINGS",
    "M10_SCHEMA_VERSION",
    "publish_cardeventnet_m10_timing_review",
    "render_cardeventnet_m10_human",
]
