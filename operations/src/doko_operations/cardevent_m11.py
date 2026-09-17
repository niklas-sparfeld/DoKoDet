"""Reconcile the CardEventNet M10 review and replay decoder timing offline."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean, median
from typing import Any

from .cardevent_dataset import _coverage, _digest, _validate_dataset
from .cardevent_m10 import M10_RECORDINGS
from .cardevent_materialization import materialize_cardeventnet_dataset
from .model_improvement import sha256_mapping

M11_SCHEMA_VERSION = "cardeventnet-m11-timing-reconciliation/v1"
M11_DECISIONS_SCHEMA_VERSION = "cardeventnet-m11-reference-decisions/v1"
M11_GRID_SCHEMA_VERSION = "cardeventnet-m11-decoder-grid/v1"
M11_TOLERANCE_S = 0.75
M11_GRID = (
    {
        "decoder_id": "current_causal",
        "algorithm": "causal_peak",
        "peak_confirmation_s": 0.125,
        "min_event_gap_s": 0.625,
    },
    {
        "decoder_id": "longer_peak_confirmation",
        "algorithm": "causal_peak",
        "peak_confirmation_s": 0.375,
        "min_event_gap_s": 0.625,
    },
    {
        "decoder_id": "bounded_quiet_window",
        "algorithm": "bounded_quiet_window",
        "peak_confirmation_s": 0.125,
        "min_event_gap_s": 0.625,
        "quiet_window_s": 0.375,
    },
)


class CardEventM11Error(ValueError):
    """Raised when M10 review inputs are incomplete or inconsistent."""


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM11Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM11Error(f"{context} {path} must contain an object")
    return dict(value)


def _read_gzip_json(path: Path, context: str) -> dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventM11Error(f"Could not read {context} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventM11Error(f"{context} {path} must contain an object")
    return dict(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise CardEventM11Error(f"Could not hash {path}: {error}") from error
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise CardEventM11Error(f"path must stay inside the repository: {path}") from None


def _required(path: Path, context: str) -> Path:
    if not path.is_file():
        raise CardEventM11Error(f"{context} is missing: {path}")
    return path


def _write_immutable_json(path: Path, value: Mapping[str, Any]) -> str:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise CardEventM11Error(f"immutable M11 artifact differs: {path}")
    else:
        path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardEventM11Error(f"{context} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise CardEventM11Error(f"{context} must be finite")
    return result


def _verify_packet(packet: Mapping[str, Any], operator_review: Mapping[str, Any]) -> None:
    digest = packet.get("packet_digest")
    core = {
        key: value
        for key, value in packet.items()
        if key not in {"packet_digest", "packet_path", "report_path"}
    }
    if digest != sha256_mapping(core):
        raise CardEventM11Error("M10 timing-review packet digest does not match its contents")
    packet_ref = operator_review.get("packet")
    if not isinstance(packet_ref, Mapping):
        raise CardEventM11Error("M10 operator review has no packet binding")
    if packet_ref.get("path") != packet.get("packet_path") or packet_ref.get("sha256") != digest:
        raise CardEventM11Error("M10 operator review is bound to a different timing packet")
    if operator_review.get("schema_version") != "cardeventnet-m10-operator-review/v1":
        raise CardEventM11Error("M10 operator review has an unsupported schema")


def _normalise_recording_decision(value: Any, recording_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CardEventM11Error(f"{recording_id} has no operator decision")
    normalised = " ".join(value.lower().split())
    if normalised in {"adjusted", "corrected", "reference_corrected"}:
        return "reference_corrected"
    if normalised in {
        "unchanged",
        "confirmed",
        "reference_confirmed",
        "prediction is okay",
        "prediction okay",
    }:
        return "reference_confirmed"
    raise CardEventM11Error(
        f"{recording_id} has an unsupported prose decision: {value!r}"
    )


def _operator_recordings(operator_review: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = operator_review.get("recordings")
    if not isinstance(raw, list):
        raise CardEventM11Error("M10 operator review recordings are invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("recording_id"), str):
            raise CardEventM11Error("M10 operator review has an invalid recording entry")
        recording_id = str(item["recording_id"])
        if recording_id in result:
            raise CardEventM11Error(f"M10 operator review repeats {recording_id}")
        notes = item.get("notes")
        if not isinstance(notes, str) or not notes.strip():
            raise CardEventM11Error(f"{recording_id} has no operator notes")
        result[recording_id] = {
            "recording_id": recording_id,
            "raw_decision": item.get("decision"),
            "decision": _normalise_recording_decision(item.get("decision"), recording_id),
            "notes": notes.strip(),
            "route": item.get("route"),
        }
    if set(result) != set(M10_RECORDINGS):
        raise CardEventM11Error("M10 operator review must contain exactly the six M10 recordings")
    return result


def _operator_regions(operator_review: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = operator_review.get("regions")
    if not isinstance(raw, list):
        raise CardEventM11Error("M10 operator review regions are invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("region_id"), str):
            raise CardEventM11Error("M10 operator review has an invalid region entry")
        region_id = str(item["region_id"])
        if region_id in result:
            raise CardEventM11Error(f"M10 operator review repeats {region_id}")
        decision = item.get("decision")
        if decision is not None and decision not in {
            "reference_corrected",
            "reference_confirmed",
            "no_event_confirmed",
        }:
            raise CardEventM11Error(f"{region_id} has an unsupported canonical decision")
        result[region_id] = dict(item)
    return result


def _load_revision(root: Path, revision_id: str, recording_id: str) -> dict[str, Any]:
    revision_dir = root / "data" / "operations" / "pipeline" / "revisions" / revision_id
    manifest_path = _required(revision_dir / "manifest.json", f"{recording_id} revision manifest")
    content_path = _required(revision_dir / "content.json", f"{recording_id} revision content")
    manifest = _read_json(manifest_path, f"{recording_id} revision manifest")
    content = _read_json(content_path, f"{recording_id} revision content")
    if manifest.get("revision_id") != revision_id or manifest.get("content_type") != "events":
        raise CardEventM11Error(
            f"{recording_id} selected revision is not a completed event revision"
        )
    events = content.get("events")
    if not isinstance(events, list):
        raise CardEventM11Error(f"{recording_id} event revision has no events")
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise CardEventM11Error(f"{recording_id} event revision has no source lineage")
    duration_us = source.get("duration_us")
    if not isinstance(duration_us, int) or isinstance(duration_us, bool) or duration_us <= 0:
        raise CardEventM11Error(f"{recording_id} event revision has no valid duration")
    coverage = manifest.get("coverage")
    if not isinstance(coverage, Mapping) or not isinstance(coverage.get("intervals"), list):
        raise CardEventM11Error(f"{recording_id} event revision has no review coverage")
    intervals: list[dict[str, int]] = []
    cursor = 0
    for item in coverage["intervals"]:
        if not isinstance(item, Mapping):
            raise CardEventM11Error(f"{recording_id} event coverage is invalid")
        start_us, end_us = item.get("start_us"), item.get("end_us")
        if (
            isinstance(start_us, bool)
            or isinstance(end_us, bool)
            or not isinstance(start_us, int)
            or not isinstance(end_us, int)
            or start_us != cursor
            or end_us <= start_us
            or end_us > duration_us
        ):
            raise CardEventM11Error(f"{recording_id} event coverage has a gap")
        intervals.append({"start_us": start_us, "end_us": end_us})
        cursor = end_us
    if not intervals or cursor != duration_us:
        raise CardEventM11Error(f"{recording_id} event coverage is not complete")
    parsed_events: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or event.get("event_type") != "card_state_changed":
            raise CardEventM11Error(f"{recording_id} event {index} is invalid")
        start_us, end_us = event.get("start_us"), event.get("end_us")
        if (
            isinstance(start_us, bool)
            or isinstance(end_us, bool)
            or not isinstance(start_us, int)
            or not isinstance(end_us, int)
            or start_us < 0
            or end_us < start_us
        ):
            raise CardEventM11Error(f"{recording_id} event {index} has an invalid interval")
        parsed_events.append(dict(event))
    return {
        "revision_id": revision_id,
        "manifest": manifest,
        "content": content,
        "events": parsed_events,
        "manifest_path": _relative(root, manifest_path),
        "content_path": _relative(root, content_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "content_sha256": _sha256_file(content_path),
        "duration_us": duration_us,
        "source_video_sha256": source.get("video_sha256"),
        "coverage": {
            "coverage_complete": True,
            "coverage_intervals": intervals,
            "coverage_percent": 100,
            "item_count": len(parsed_events),
            "reviewed_item_count": len(parsed_events),
            "annotation_event_count": len(parsed_events),
            "unresolved_uncertain_events": 0,
        },
    }


def _current_revisions(
    root: Path, packet: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    old: dict[str, dict[str, Any]] = {}
    for item in packet.get("items", []):
        if not isinstance(item, Mapping):
            raise CardEventM11Error("M10 packet contains an invalid item")
        recording_id = item.get("recording_id")
        reference = item.get("reference_revision")
        if not isinstance(recording_id, str) or not isinstance(reference, Mapping):
            raise CardEventM11Error("M10 item has incomplete reference lineage")
        event_revision_id = reference.get("event_revision_id")
        if not isinstance(event_revision_id, str):
            raise CardEventM11Error(f"{recording_id} M10 item has no event revision ID")
        if recording_id not in old:
            old[recording_id] = _load_revision(root, event_revision_id, recording_id)
        elif old[recording_id]["revision_id"] != event_revision_id:
            raise CardEventM11Error(f"M10 items disagree on the old revision for {recording_id}")
    current: dict[str, dict[str, Any]] = {}
    for recording_id in M10_RECORDINGS:
        selection_path = (
            root
            / "data"
            / "operations"
            / "pipeline"
            / "selections"
            / recording_id
            / "events.json"
        )
        selection = _read_json(selection_path, f"{recording_id} reference selection")
        revision_id = selection.get("selected_completed_reference_revision_id")
        if not isinstance(revision_id, str) or not revision_id:
            raise CardEventM11Error(f"{recording_id} has no selected completed reference")
        current[recording_id] = _load_revision(root, revision_id, recording_id)
        if current[recording_id]["source_video_sha256"] != old[recording_id]["source_video_sha256"]:
            raise CardEventM11Error(f"{recording_id} reference source lineage changed")
    if set(old) != set(M10_RECORDINGS):
        raise CardEventM11Error("M10 packet does not contain exactly the six review recordings")
    return old, current


def _event_intervals(revision: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [
        (float(event["start_us"]) / 1_000_000, float(event["end_us"]) / 1_000_000)
        for event in revision["events"]
    ]


def _has_current_event(revision: Mapping[str, Any], time_s: float) -> bool:
    for start_s, end_s in _event_intervals(revision):
        if abs(end_s - time_s) <= M11_TOLERANCE_S or start_s <= time_s < end_s:
            return True
    return False


def _item_decision(
    item: Mapping[str, Any],
    *,
    operator: Mapping[str, Any],
    region: Mapping[str, Any] | None,
    current_revision: Mapping[str, Any],
) -> tuple[str, str]:
    region_decision = region.get("decision") if isinstance(region, Mapping) else None
    if isinstance(region_decision, str):
        return region_decision, "explicit canonical region decision"
    kind = item.get("kind")
    time_s = _number(item.get("time_s"), "M10 item time")
    if kind == "confirmed_false_trigger":
        if _has_current_event(current_revision, time_s):
            return (
                "reference_corrected",
                "the current completed revision now places a reviewed event at the prediction",
            )
        return "no_event_confirmed", "the prose notes review this prediction as a no-event trigger"
    if operator["decision"] == "reference_corrected":
        return "reference_corrected", "the recording notes say that reviewed anchors were adjusted"
    return "reference_confirmed", "the recording notes say that the maintained annotation is fine"


def _build_decision_report(
    root: Path,
    campaign_dir: Path,
    packet: Mapping[str, Any],
    operator_review: Mapping[str, Any],
    operator_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    operators = _operator_recordings(operator_review)
    regions_by_id = _operator_regions(operator_review)
    old, current = _current_revisions(root, packet)
    packet_regions = {
        item["region_id"]: item
        for item in packet.get("regions", [])
        if isinstance(item, Mapping) and isinstance(item.get("region_id"), str)
    }
    item_by_id = {
        item["item_id"]: item
        for item in packet.get("items", [])
        if isinstance(item, Mapping) and isinstance(item.get("item_id"), str)
    }
    if set(packet_regions) != set(regions_by_id):
        raise CardEventM11Error("M10 operator regions do not match the timing packet")
    item_decisions: list[dict[str, Any]] = []
    for item_id in sorted(item_by_id):
        item = item_by_id[item_id]
        recording_id = str(item["recording_id"])
        region_id = next(
            region["region_id"]
            for region in packet["regions"]
            if item_id in region.get("item_ids", [])
        )
        decision, basis = _item_decision(
            item,
            operator=operators[recording_id],
            region=regions_by_id[region_id],
            current_revision=current[recording_id],
        )
        old_revision = old[recording_id]
        new_revision = current[recording_id]
        item_decisions.append(
            {
                "item_id": item_id,
                "region_id": region_id,
                "recording_id": recording_id,
                "kind": item.get("kind"),
                "time_s": item.get("time_s"),
                "decision": decision,
                "decision_basis": basis,
                "operator_notes": operators[recording_id]["notes"],
                "reference_before": {
                    "revision_id": old_revision["revision_id"],
                    "manifest_path": old_revision["manifest_path"],
                    "manifest_sha256": old_revision["manifest_sha256"],
                    "content_path": old_revision["content_path"],
                    "content_sha256": old_revision["content_sha256"],
                },
                "reference_after": {
                    "revision_id": new_revision["revision_id"],
                    "manifest_path": new_revision["manifest_path"],
                    "manifest_sha256": new_revision["manifest_sha256"],
                    "content_path": new_revision["content_path"],
                    "content_sha256": new_revision["content_sha256"],
                    "source_video_sha256": new_revision["source_video_sha256"],
                },
            }
        )
    region_decisions = []
    for region_id in sorted(packet_regions):
        items = [item for item in item_decisions if item["region_id"] == region_id]
        decisions = sorted({item["decision"] for item in items})
        region_decisions.append(
            {
                "region_id": region_id,
                "recording_id": packet_regions[region_id]["recording_id"],
                "item_ids": list(packet_regions[region_id]["item_ids"]),
                "decisions": decisions,
                "decision": decisions[0] if len(decisions) == 1 else "mixed",
                "notes": operators[packet_regions[region_id]["recording_id"]]["notes"],
                "operator_region_input": regions_by_id[region_id].get("decision"),
            }
        )
    reference_summary = []
    for recording_id in M10_RECORDINGS:
        before, after = old[recording_id], current[recording_id]
        reference_summary.append(
            {
                "recording_id": recording_id,
                "operator_decision": operators[recording_id]["raw_decision"],
                "normalised_operator_decision": operators[recording_id]["decision"],
                "notes": operators[recording_id]["notes"],
                "before_revision_id": before["revision_id"],
                "after_revision_id": after["revision_id"],
                "revision_changed": before["revision_id"] != after["revision_id"],
                "content_byte_identical": before["content_sha256"] == after["content_sha256"],
                "manifest_byte_identical": before["manifest_sha256"] == after["manifest_sha256"],
                "after_lineage": {
                    "manifest_path": after["manifest_path"],
                    "manifest_sha256": after["manifest_sha256"],
                    "content_path": after["content_path"],
                    "content_sha256": after["content_sha256"],
                    "origin": after["manifest"].get("origin"),
                    "input_revision_ids": after["manifest"].get("input_revision_ids"),
                    "source": after["manifest"].get("source"),
                },
            }
        )
    core: dict[str, Any] = {
        "schema_version": M11_DECISIONS_SCHEMA_VERSION,
        "campaign_id": packet["campaign_id"],
        "source_packet": {
            "path": packet["packet_path"],
            "sha256": packet["packet_digest"],
        },
        "operator_review": {
            "path": _relative(root, operator_path),
            "sha256": _sha256_file(operator_path),
            "status": operator_review.get("status"),
            "completion_evidence": "all six recording decisions and prose notes are present",
        },
        "recordings": reference_summary,
        "regions": region_decisions,
        "items": item_decisions,
        "counts": {
            "recordings": len(reference_summary),
            "regions": len(region_decisions),
            "items": len(item_decisions),
            "reference_corrected": sum(
                item["decision"] == "reference_corrected" for item in item_decisions
            ),
            "reference_confirmed": sum(
                item["decision"] == "reference_confirmed" for item in item_decisions
            ),
            "no_event_confirmed": sum(
                item["decision"] == "no_event_confirmed" for item in item_decisions
            ),
        },
        "sealed_test_read": False,
        "system_holdout_read": False,
    }
    return {**core, "decision_digest": sha256_mapping(core)}, old, current


def _successor_entry(
    root: Path,
    base_entry: Mapping[str, Any],
    revision: Mapping[str, Any],
) -> dict[str, Any]:
    updated = dict(base_entry)
    updated.update(
        {
            "event_revision_id": revision["revision_id"],
            "event_revision_manifest_path": revision["manifest_path"],
            "event_revision_manifest_sha256": revision["manifest_sha256"],
            "event_revision_content_path": revision["content_path"],
            "event_revision_content_sha256": revision["content_sha256"],
            "event_count": len(revision["events"]),
            "duration_us": revision["duration_us"],
            "review_coverage": revision["coverage"],
        }
    )
    del root
    return updated


def _freeze_successor_dataset(
    root: Path,
    baseline_path: Path,
    decision_report: Mapping[str, Any],
    current: Mapping[str, Mapping[str, Any]],
    *,
    campaign_dir: Path,
) -> dict[str, Any]:
    baseline_dir = baseline_path.parent
    baseline = _read_json(baseline_dir / "dataset.json", "M7 dataset")
    baseline_split = _read_json(baseline_dir / "split.json", "M7 split")
    baseline_coverage = _read_json(baseline_dir / "coverage.json", "M7 coverage")
    baseline_receipt = _read_json(baseline_dir / "receipt.json", "M7 receipt")
    entries = []
    for base_entry in baseline["entries"]:
        recording_id = str(base_entry["recording_id"])
        if recording_id in current:
            entries.append(_successor_entry(root, base_entry, current[recording_id]))
        else:
            entries.append(dict(base_entry))
    lineage = dict(baseline.get("lineage", {}))
    lineage["successor_of"] = {
        "dataset_version_id": baseline["dataset_version_id"],
        "dataset_version_digest": baseline["dataset_version_digest"],
        "path": _relative(root, baseline_dir),
    }
    lineage["m11_reference_decisions"] = {
        "path": _relative(root, campaign_dir / "m11-reference-decisions.json"),
        "decision_digest": decision_report["decision_digest"],
    }
    dataset_core: dict[str, Any] = {
        "schema_version": baseline["schema_version"],
        "task": baseline["task"],
        "readiness_digest": baseline["readiness_digest"],
        "split_version_id": baseline["split_version_id"],
        "split_version_digest": baseline["split_version_digest"],
        "test_sealed": True,
        "interval_aware": True,
        "target_policy": dict(baseline["target_policy"]),
        "diagnostic_exclusion_receipt_sha256": baseline[
            "diagnostic_exclusion_receipt_sha256"
        ],
        "lineage": lineage,
        "entries": entries,
    }
    dataset_digest = _digest(dataset_core)
    dataset_id = f"cardeventnet-interval-dataset-{dataset_digest[:20]}"
    dataset = {
        **dataset_core,
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
    }
    split_core = {
        "schema_version": baseline_split["schema_version"],
        "task": baseline_split["task"],
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "group_key_names": list(baseline_split["group_key_names"]),
        "train": list(baseline_split["train"]),
        "validation": list(baseline_split["validation"]),
        "test": list(baseline_split["test"]),
        "unassigned": list(baseline_split["unassigned"]),
        "test_sealed": True,
    }
    split_digest = _digest(split_core)
    split = {
        **split_core,
        "split_version_id": f"cardeventnet-interval-split-{split_digest[:20]}",
        "split_version_digest": split_digest,
    }
    coverage_core = {
        "schema_version": baseline_coverage["schema_version"],
        "task": baseline_coverage["task"],
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "partitions": _coverage(entries),
    }
    coverage = {**coverage_core, "coverage_digest": _digest(coverage_core)}
    receipt_core = {
        "schema_version": baseline_receipt["schema_version"],
        "receipt_type": "cardeventnet_interval_dataset_successor",
        "operator": "cardeventnet-m11",
        "inputs": [
            {
                "kind": "source_dataset",
                "id": baseline["dataset_version_id"],
                "digest": baseline["dataset_version_digest"],
            },
            {
                "kind": "m11_reference_decisions",
                "digest": decision_report["decision_digest"],
            },
        ],
        "outputs": [],
    }
    receipt_digest = _digest(receipt_core)
    receipt = {
        **receipt_core,
        "outputs": [
            {"kind": "dataset", "id": dataset_id, "digest": dataset_digest},
            {"kind": "split", "id": split["split_version_id"], "digest": split_digest},
            {"kind": "coverage", "digest": coverage["coverage_digest"]},
        ],
    }
    receipt_digest = _digest(receipt)
    receipt = {
        **receipt,
        "receipt_id": f"receipt-cardeventnet-m11-successor-{receipt_digest[:20]}",
        "receipt_digest": receipt_digest,
    }
    try:
        _validate_dataset(dataset, split, coverage, receipt, root)
    except (ValueError, KeyError) as error:
        raise CardEventM11Error(f"successor dataset validation failed: {error}") from error
    destination = root / "data" / "operations" / "cardevent-datasets" / dataset_id
    for name, payload in (
        ("dataset.json", dataset),
        ("split.json", split),
        ("coverage.json", coverage),
        ("receipt.json", receipt),
    ):
        _write_immutable_json(destination / name, payload)
    return {
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "split_version_id": split["split_version_id"],
        "split_version_digest": split_digest,
        "coverage_digest": coverage["coverage_digest"],
        "receipt_id": receipt["receipt_id"],
        "receipt_digest": receipt_digest,
        "path": _relative(root, destination),
        "test_sealed": True,
        "preserved_partitions": {
            partition: list(split[partition]) for partition in ("train", "validation", "test")
        },
        "reviewed_recordings": sorted(current),
        "revision_changed_recordings": sorted(
            item["recording_id"]
            for item in decision_report["recordings"]
            if item["revision_changed"]
        ),
    }


def _load_cardevent_types(root: Path) -> tuple[Any, ...]:
    source_root = str(root / "card_event_net" / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    try:
        from cardevent.evaluation import ScoredVideo  # type: ignore[import-not-found]
        from cardevent.events import (  # type: ignore[import-not-found]
            DetectedEvent,
            ProbabilitySample,
            candidate_peaks,
            classify_prediction_outcomes,
        )
    except ImportError as error:
        raise CardEventM11Error("CardEventNet decoder sources are unavailable") from error
    return (
        DetectedEvent,
        ProbabilitySample,
        candidate_peaks,
        classify_prediction_outcomes,
        ScoredVideo,
    )


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.95
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _quiet_window_events(
    samples: Sequence[Any],
    *,
    threshold: float,
    peak_confirmation_s: float,
    min_event_gap_s: float,
    quiet_window_s: float,
    detected_event_type: Any,
    candidate_peak_type: Any,
) -> list[Any]:
    peaks = candidate_peak_type(samples, min_event_gap_s=min_event_gap_s)
    events: list[Any] = []
    last_event_s: float | None = None
    for peak in peaks:
        if peak.probability < threshold:
            continue
        if last_event_s is not None:
            if peak.time_s - last_event_s <= min_event_gap_s:
                continue
            previous_high = max(
                (
                    sample.time_s
                    for sample in samples
                    if last_event_s <= sample.time_s < peak.time_s
                    and sample.probability >= threshold
                ),
                default=last_event_s,
            )
            if peak.time_s - previous_high < quiet_window_s:
                continue
        emitted_at_s = next(
            (
                sample.time_s
                for sample in samples
                if sample.time_s >= peak.time_s + peak_confirmation_s
            ),
            samples[-1].time_s,
        )
        events.append(
            detected_event_type(
                time_s=peak.time_s,
                probability=peak.probability,
                emitted_at_s=emitted_at_s,
            )
        )
        last_event_s = peak.time_s
    return events


def _replay_metrics(
    root: Path,
    campaign_dir: Path,
    successor: Mapping[str, Any],
    current: Mapping[str, Mapping[str, Any]],
    decision_report: Mapping[str, Any],
) -> dict[str, Any]:
    (
        DetectedEvent,
        ProbabilitySample,
        candidate_peaks,
        classify_prediction_outcomes,
        ScoredVideo,
    ) = _load_cardevent_types(root)
    stream_path = campaign_dir / "validation-streams" / "evaluation.json.gz"
    stream = _read_gzip_json(stream_path, "M9 validation stream")
    if stream.get("format") != "cardevent-validation-stream-v1":
        raise CardEventM11Error("M9 validation stream has an unsupported format")
    by_name = {
        video.get("video"): video
        for video in stream.get("videos", [])
        if isinstance(video, Mapping) and isinstance(video.get("video"), str)
    }
    if set(by_name) != set(M10_RECORDINGS):
        raise CardEventM11Error("M9 validation stream does not contain the six M10 recordings")
    diagnostics = _read_json(
        campaign_dir / "validation-evaluation.json", "M9 validation evaluation"
    )
    threshold = _number(diagnostics.get("threshold"), "M9 validation threshold")
    videos = []
    for recording_id in M10_RECORDINGS:
        raw = by_name[recording_id]
        times = raw.get("decision_timestamps_s")
        probabilities = raw.get("probabilities")
        if (
            not isinstance(times, list)
            or not isinstance(probabilities, list)
            or len(times) != len(probabilities)
        ):
            raise CardEventM11Error(f"{recording_id} saved probability stream is invalid")
        samples = tuple(
            ProbabilitySample(
                _number(time, f"{recording_id} score time"),
                _number(probability, f"{recording_id} probability"),
            )
            for time, probability in zip(times, probabilities, strict=True)
        )
        intervals = tuple(_event_intervals(current[recording_id]))
        videos.append(
            ScoredVideo(
                name=recording_id,
                duration_s=current[recording_id]["duration_us"] / 1_000_000,
                ground_truth_times_s=tuple(end for _, end in intervals),
                probabilities=samples,
                ground_truth_intervals_s=intervals,
            )
        )

    def decode(video: Any, configuration: Mapping[str, Any]) -> list[Any]:
        if configuration["algorithm"] == "bounded_quiet_window":
            return _quiet_window_events(
                video.probabilities,
                threshold=threshold,
                peak_confirmation_s=float(configuration["peak_confirmation_s"]),
                min_event_gap_s=float(configuration["min_event_gap_s"]),
                quiet_window_s=float(configuration["quiet_window_s"]),
                detected_event_type=DetectedEvent,
                candidate_peak_type=candidate_peaks,
            )
        from cardevent.events import probabilities_to_events  # type: ignore[import-not-found]

        return probabilities_to_events(
            video.probabilities,
            threshold=threshold,
            peak_confirmation_s=float(configuration["peak_confirmation_s"]),
            min_event_gap_s=float(configuration["min_event_gap_s"]),
        )

    candidates: list[dict[str, Any]] = []
    for configuration in M11_GRID:
        per_recording = []
        signed_errors: list[float] = []
        emission_delays: list[float] = []
        totals = {
            "point_matches": 0,
            "stable_end_matches": 0,
            "detections_inside_intervals": 0,
            "duplicate_detections_per_reviewed_change": 0,
            "confirmed_no_event_triggers": 0,
        }
        for video in videos:
            events = decode(video, configuration)
            outcomes = classify_prediction_outcomes(
                events,
                video.ground_truth_intervals_s,
                tolerance_s=M11_TOLERANCE_S,
            )
            counts = {
                "point_matches": sum(item.outcome == "point_match" for item in outcomes),
                "stable_end_matches": sum(item.outcome == "stable_end_match" for item in outcomes),
                "detections_inside_intervals": sum(
                    item.outcome == "in_progress_detection" for item in outcomes
                ),
                "confirmed_no_event_triggers": sum(
                    item.outcome == "confirmed_false_trigger" for item in outcomes
                ),
            }
            duplicates = 0
            for start_s, end_s in video.ground_truth_intervals_s:
                matching = [
                    event
                    for event in events
                    if abs(event.time_s - end_s) <= M11_TOLERANCE_S
                    or start_s <= event.time_s < end_s
                ]
                duplicates += max(0, len(matching) - 1)
            counts["duplicate_detections_per_reviewed_change"] = duplicates
            totals = {key: totals[key] + counts[key] for key in totals}
            video_errors = []
            video_emissions = []
            for item in outcomes:
                if item.outcome in {"point_match", "stable_end_match"}:
                    error = item.prediction.time_s - float(item.anchor_time_s)
                    signed_errors.append(error)
                    video_errors.append(error)
                    if item.prediction.emitted_at_s is not None:
                        delay = item.prediction.emitted_at_s - float(item.anchor_time_s)
                        emission_delays.append(delay)
                        video_emissions.append(delay)
            per_recording.append(
                {
                    "recording_id": video.name,
                    **counts,
                    "reviewed_changes": len(video.ground_truth_intervals_s),
                    "predicted_events": [event.to_mapping() for event in events],
                    "signed_timestamp_error_s": {
                        "count": len(video_errors),
                        "median": median(video_errors) if video_errors else 0.0,
                        "p95_abs": _p95([abs(value) for value in video_errors]),
                    },
                    "causal_emission_delay_s": {
                        "count": len(video_emissions),
                        "median": median(video_emissions) if video_emissions else 0.0,
                        "p95": _p95(video_emissions),
                    },
                }
            )
        real_events = sum(len(video.ground_truth_intervals_s) for video in videos)
        matches = totals["point_matches"] + totals["stable_end_matches"]
        core = {
            **configuration,
            "threshold": threshold,
            "event_presence": {
                "reviewed_changes": real_events,
                "matched_changes": matches,
                "recall": matches / real_events if real_events else 0.0,
            },
            **totals,
            "signed_timestamp_error_s": {
                "count": len(signed_errors),
                "median": median(signed_errors) if signed_errors else 0.0,
                "mean": mean(signed_errors) if signed_errors else 0.0,
                "p95_abs": _p95([abs(value) for value in signed_errors]),
            },
            "causal_emission_delay_s": {
                "count": len(emission_delays),
                "median": median(emission_delays) if emission_delays else 0.0,
                "p95": _p95(emission_delays),
            },
            "recordings": per_recording,
        }
        candidates.append(core)
    operator_no_event = decision_report["counts"]["no_event_confirmed"]
    grid_core = {
        "schema_version": M11_GRID_SCHEMA_VERSION,
        "campaign_id": decision_report["campaign_id"],
        "checkpoint": diagnostics.get("checkpoint"),
        "threshold": threshold,
        "event_match_tolerance_s": M11_TOLERANCE_S,
        "reference_decision_no_event_count": operator_no_event,
        "candidates": candidates,
        "selection": {
            "selected_decoder": None,
            "reason": "M11 does not select a decoder from validation or sealed-test output",
            "sealed_test_read": False,
        },
        "sealed_test_read": False,
        "system_holdout_read": False,
    }
    return {**grid_core, "grid_digest": sha256_mapping(grid_core)}


def _render_report(result: Mapping[str, Any]) -> str:
    decisions = result["decision_report"]
    successor = result["successor_dataset"]
    grid = result["decoder_grid"]
    lines = [
        "# CardEventNet M11 reference reconciliation and decoder replay",
        "",
        f"- Campaign: `{result['campaign_id']}`",
        f"- M10 packet: `{decisions['source_packet']['path']}`",
        f"- Operator artifact: `{decisions['operator_review']['path']}`",
        "- Sealed test read: `false`",
        "- System holdout read: `false`",
        "",
        "## Operator decision reconciliation",
        "",
        "The M10 artifact keeps region fields blank, so M11 uses the six recording decisions and "
        "their prose notes as the completion evidence. The mapping is deterministic: adjusted "
        "recordings map missed or in-progress items to `reference_corrected`; unchanged or "
        "prediction-okay recordings map them to `reference_confirmed`; confirmed false triggers "
        "map to `no_event_confirmed` unless the current reference now contains an event at that "
        "time. Any explicit canonical region decision takes precedence.",
        "",
        "| Decision | Items |",
        "| --- | ---: |",
    ]
    for key in ("reference_corrected", "reference_confirmed", "no_event_confirmed"):
        lines.append(f"| `{key}` | {decisions['counts'][key]} |")
    lines.extend(
        [
            "",
            "## Successor development dataset",
            "",
            f"- Dataset: `{successor['dataset_version_id']}`",
            f"- Dataset path: `{successor['path']}`",
            f"- Dataset digest: `{successor['dataset_version_digest']}`",
            f"- Split: `{successor['split_version_id']}`",
            f"- Reviewed recordings: `{', '.join(successor['reviewed_recordings'])}`",
            "- Revision-changed recordings: `"
            f"{', '.join(successor['revision_changed_recordings'])}`",
            "- Source groups and sealed-test membership are preserved from M7.",
            "- The saved checkpoint is evaluated against the successor validation references; "
            "no training is run.",
            "",
            "## Decoder replay",
            "",
            f"- Grid artifact: `{result['decoder_grid_path']}`",
            f"- Grid digest: `{grid['grid_digest']}`",
            "- Threshold is fixed from M9. The decoder grid is validation-only.",
            "- No decoder is selected in M11. Sealed-test output is not read.",
            "",
            "| Decoder | Point | Stable-end | Inside interval | Duplicate detections | "
            "No-event triggers | Signed error median (s) | Emission delay median (s) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for candidate in grid["candidates"]:
        lines.append(
            f"| `{candidate['decoder_id']}` | {candidate['point_matches']} | "
            f"{candidate['stable_end_matches']} | {candidate['detections_inside_intervals']} | "
            f"{candidate['duplicate_detections_per_reviewed_change']} | "
            f"{candidate['confirmed_no_event_triggers']} | "
            f"{candidate['signed_timestamp_error_s']['median']:.6f} | "
            f"{candidate['causal_emission_delay_s']['median']:.6f} |"
        )
    lines.extend(
        [
            "",
            "M11 stops after deterministic reference validation and offline decoder replay. It "
            "does not train, export, promote, read sealed test, or read the system holdout.",
            "",
        ]
    )
    return "\n".join(lines)


def publish_cardeventnet_m11_timing_review(
    campaign_id: str,
    *,
    repository_root: str | Path,
    campaign_root: str | Path | None = None,
) -> dict[str, Any]:
    """Publish M11 decisions, a successor dataset, and a validation-only decoder replay."""

    root = Path(repository_root).resolve()
    campaigns = Path(campaign_root or root / "data" / "model-campaigns")
    if not campaigns.is_absolute():
        campaigns = root / campaigns
    campaign_dir = (campaigns / campaign_id).resolve()
    try:
        campaign_dir.relative_to(root)
    except ValueError as error:
        raise CardEventM11Error("campaign directory must stay inside the repository") from error
    packet_path = _required(campaign_dir / "m10-timing-review.json", "M10 timing packet")
    operator_path = _required(campaign_dir / "m10-operator-review.json", "M10 operator review")
    packet = _read_json(packet_path, "M10 timing packet")
    operator_review = _read_json(operator_path, "M10 operator review")
    _verify_packet(packet, operator_review)
    decision_report, _old, current = _build_decision_report(
        root, campaign_dir, packet, operator_review, operator_path
    )
    decision_path = campaign_dir / "m11-reference-decisions.json"
    decision_file_sha256 = _write_immutable_json(decision_path, decision_report)
    baseline_id = decision_report["source_packet"].get("dataset_id")
    if not isinstance(baseline_id, str):
        baseline_id = packet["lineage"]["dataset"]["id"]
    baseline_path = (
        root / "data" / "operations" / "cardevent-datasets" / baseline_id / "dataset.json"
    )
    _required(baseline_path, "M7 dataset")
    successor = _freeze_successor_dataset(
        root,
        baseline_path,
        decision_report,
        current,
        campaign_dir=campaign_dir,
    )
    materialization = materialize_cardeventnet_dataset(
        root / successor["path"],
        repository_root=root,
        cache_source_root=packet["lineage"]["materialized_view"],
    )
    successor["materialized_view"] = _relative(root, materialization.view_root)
    successor["materialization_manifest_digest"] = materialization.manifest_digest
    decoder_grid = _replay_metrics(root, campaign_dir, successor, current, decision_report)
    grid_path = campaign_dir / "m11-decoder-grid.json"
    grid_file_sha256 = _write_immutable_json(grid_path, decoder_grid)
    result_core = {
        "schema_version": M11_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "decision_report_path": _relative(root, decision_path),
        "decision_report_digest": decision_report["decision_digest"],
        "decision_report_sha256": decision_file_sha256,
        "successor_dataset": successor,
        "decoder_grid_path": _relative(root, grid_path),
        "decoder_grid_digest": decoder_grid["grid_digest"],
        "decoder_grid_sha256": grid_file_sha256,
        "sealed_test_read": False,
        "system_holdout_read": False,
        "training_started": False,
        "export_started": False,
        "promotion_started": False,
        "decision_report": decision_report,
        "decoder_grid": decoder_grid,
    }
    result = {**result_core, "result_digest": sha256_mapping(result_core)}
    report_path = campaign_dir / "m11-report.md"
    _write_immutable_json(campaign_dir / "m11-result.json", result)
    report = _render_report(result)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_bytes = report.encode("utf-8")
    if report_path.exists() and report_path.read_bytes() != report_bytes:
        raise CardEventM11Error(f"immutable M11 artifact differs: {report_path}")
    if not report_path.exists():
        report_path.write_bytes(report_bytes)
    result["report_path"] = _relative(root, report_path)
    return result


def render_cardeventnet_m11_human(result: Mapping[str, Any]) -> str:
    """Render a concise M11 CLI result."""

    return (
        "CardEventNet M11 reference reconciliation\n"
        f"campaign: {result['campaign_id']}\n"
        f"decision report: {result['decision_report_path']}\n"
        f"successor dataset: {result['successor_dataset']['dataset_version_id']}\n"
        f"decoder grid: {result['decoder_grid_path']}\n"
        "selected decoder: none\n"
        "sealed test read: false\n"
    )


__all__ = [
    "CardEventM11Error",
    "M11_DECISIONS_SCHEMA_VERSION",
    "M11_GRID_SCHEMA_VERSION",
    "M11_SCHEMA_VERSION",
    "publish_cardeventnet_m11_timing_review",
    "render_cardeventnet_m11_human",
]
