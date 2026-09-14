"""Bounded CardEventNet interval-review pilot artifacts.

The pilot is a derived, disposable view.  It never edits an existing frozen dataset.  A pilot
request names one development recording, the exact reviewed interval events, the source-frame
evidence for each interval, and the full-recording review coverage.  The runner publishes a
corrected event revision below the pilot output root, derives a new frozen-shaped dataset from the
0063 dataset, materializes a trainer view, and writes one digest-backed report.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .cardevent_dataset import (
    CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
    CARD_EVENTNET_DATASET_SCHEMA_VERSION,
    CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION,
    CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
    _coverage,
    _digest,
)
from .cardevent_materialization import (
    CardEventNetMaterializationError,
    materialize_cardeventnet_dataset,
)
from .pipeline_data import (
    DataRevision,
    EventData,
    HumanProducer,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
    parse_event_data_bytes,
)

CARD_EVENTNET_INTERVAL_PILOT_SCHEMA_VERSION = "cardeventnet-interval-pilot/v1"
CARD_EVENTNET_INTERVAL_PILOT_REQUEST_SCHEMA_VERSION = "cardeventnet-interval-pilot-request/v1"
CARD_EVENTNET_INTERVAL_PILOT_DATASET_SCHEMA_VERSION = "cardeventnet-interval-pilot-dataset/v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_DIGEST_LENGTH = 64
_MAX_INTERVALS = 20
_DECISIONS = frozenset({"no_event", "missed_event", "uncertain"})
_CANDIDATE_KINDS = frozenset({"uncertain", "missed_hard_negative"})


class CardEventNetIntervalPilotError(ValueError):
    """The bounded interval-review pilot is invalid or cannot be published."""


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise CardEventNetIntervalPilotError(f"{field} must be a safe identifier")
    return value


def _digest_value(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CardEventNetIntervalPilotError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CardEventNetIntervalPilotError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CardEventNetIntervalPilotError(f"{field} must be a non-negative integer")
    return value


def _relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CardEventNetIntervalPilotError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise CardEventNetIntervalPilotError(f"{field} must be a safe relative path")
    return path.as_posix()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CardEventNetIntervalPilotError(f"could not hash {path}: {error}") from error
    return digest.hexdigest()


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventNetIntervalPilotError(f"could not read {field} {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise CardEventNetIntervalPilotError(f"{field} must be a JSON object: {path}")
    return dict(value)


def _resolve_path(repository: Path, value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    return (repository / candidate if not candidate.is_absolute() else candidate).resolve()


def _repository_relative(repository: Path, path: Path, field: str) -> str:
    try:
        return path.resolve().relative_to(repository).as_posix()
    except ValueError as error:
        raise CardEventNetIntervalPilotError(
            f"{field} must be inside the repository root: {path}"
        ) from error


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise CardEventNetIntervalPilotError(f"immutable artifact differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _normalise_coverage(raw: Any, duration_us: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CardEventNetIntervalPilotError("review.coverage must be an object")
    if raw.get("kind") not in {"full_recording", "full-recording"}:
        raise CardEventNetIntervalPilotError("review.coverage.kind must be full_recording")
    intervals = raw.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        raise CardEventNetIntervalPilotError("review.coverage.intervals must not be empty")
    parsed: list[dict[str, int]] = []
    for index, item in enumerate(intervals):
        if not isinstance(item, Mapping):
            raise CardEventNetIntervalPilotError(f"review.coverage.intervals[{index}] is invalid")
        start_us = _non_negative_int(item.get("start_us"), f"coverage interval {index}.start_us")
        end_us = _positive_int(item.get("end_us"), f"coverage interval {index}.end_us")
        if end_us <= start_us or end_us > duration_us:
            raise CardEventNetIntervalPilotError(
                f"review.coverage.intervals[{index}] is outside the source duration"
            )
        parsed.append({"start_us": start_us, "end_us": end_us})
    if parsed != sorted(parsed, key=lambda item: (item["start_us"], item["end_us"])):
        raise CardEventNetIntervalPilotError("review.coverage.intervals must be ordered")
    if parsed[0]["start_us"] != 0 or parsed[-1]["end_us"] != duration_us:
        raise CardEventNetIntervalPilotError(
            "review.coverage must start at zero and end at duration"
        )
    if any(
        left["end_us"] != right["start_us"]
        for left, right in zip(parsed, parsed[1:], strict=False)
    ):
        raise CardEventNetIntervalPilotError("review.coverage must have no gaps")
    return {
        "kind": "full_recording",
        "duration_us": duration_us,
        "intervals": parsed,
        "coverage_complete": True,
    }


def _source_frame_evidence(
    raw: Any,
    *,
    event_id: str,
    start_us: int,
    end_us: int,
    duration_us: int,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise CardEventNetIntervalPilotError(f"interval {event_id} needs source-frame evidence")
    evidence: list[dict[str, Any]] = []
    roles: set[str] = set()
    frame_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise CardEventNetIntervalPilotError(
                f"interval {event_id} source-frame evidence {index} is invalid"
            )
        frame_id = _identifier(item.get("frame_id"), f"interval {event_id}.frame_id")
        role = item.get("role")
        if role not in {"start", "stable_end", "context"}:
            raise CardEventNetIntervalPilotError(
                f"interval {event_id} source-frame evidence role is invalid"
            )
        time_us = _non_negative_int(item.get("time_us"), f"interval {event_id}.time_us")
        if time_us > duration_us or frame_id in frame_ids or role in roles:
            raise CardEventNetIntervalPilotError(
                f"interval {event_id} source-frame evidence is duplicated or out of range"
            )
        frame_ids.add(frame_id)
        roles.add(role)
        evidence.append({"frame_id": frame_id, "role": role, "time_us": time_us})
    if roles != {"start", "stable_end"} and not {"start", "stable_end"}.issubset(roles):
        raise CardEventNetIntervalPilotError(
            f"interval {event_id} needs start and stable_end source frames"
        )
    by_role = {item["role"]: item["time_us"] for item in evidence}
    if by_role["start"] != start_us or by_role["stable_end"] != end_us:
        raise CardEventNetIntervalPilotError(
            f"interval {event_id} bounds must equal its source-frame evidence"
        )
    return sorted(evidence, key=lambda item: (item["time_us"], item["role"], item["frame_id"]))


def _review_events(
    review: Mapping[str, Any], *, recording_id: str, duration_us: int
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    if review.get("schema_version") != CARD_EVENTNET_INTERVAL_PILOT_REQUEST_SCHEMA_VERSION:
        raise CardEventNetIntervalPilotError("unsupported interval pilot request schema")
    if _identifier(review.get("pilot_id"), "pilot_id") != review["pilot_id"]:
        raise CardEventNetIntervalPilotError("pilot_id is invalid")
    if _identifier(review.get("recording_id"), "review.recording_id") != recording_id:
        raise CardEventNetIntervalPilotError("review.recording_id does not match the dataset")
    coverage = _normalise_coverage(review.get("coverage"), duration_us)
    raw_events = review.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise CardEventNetIntervalPilotError("review.events must not be empty")
    if len(raw_events) > _MAX_INTERVALS:
        raise CardEventNetIntervalPilotError(
            f"pilot is limited to {_MAX_INTERVALS} reviewed events"
        )
    event_payload = {
        "schema_version": "event-data/v1",
        "events": copy.deepcopy(raw_events),
    }
    try:
        events = EventData.from_mapping(event_payload, duration_us=duration_us)
    except ValueError as error:
        raise CardEventNetIntervalPilotError(f"review.events are invalid: {error}") from error
    if not any(event.start_us < event.end_us for event in events.events):
        raise CardEventNetIntervalPilotError("pilot must publish at least one nonzero interval")
    evidence_by_event: dict[str, list[dict[str, Any]]] = {}
    for item in review.get("interval_evidence", []):
        if not isinstance(item, Mapping):
            raise CardEventNetIntervalPilotError("review.interval_evidence is invalid")
        event_id = _identifier(item.get("event_id"), "interval_evidence.event_id")
        if event_id in evidence_by_event:
            raise CardEventNetIntervalPilotError(f"interval evidence repeats {event_id}")
        event = next((event for event in events.events if event.event_id == event_id), None)
        if event is None or event.start_us == event.end_us:
            raise CardEventNetIntervalPilotError(
                f"interval evidence must reference a nonzero event: {event_id}"
            )
        evidence_by_event[event_id] = _source_frame_evidence(
            item.get("source_frames"),
            event_id=event_id,
            start_us=event.start_us,
            end_us=event.end_us,
            duration_us=duration_us,
        )
    interval_ids = {event.event_id for event in events.events if event.start_us < event.end_us}
    if set(evidence_by_event) != interval_ids:
        raise CardEventNetIntervalPilotError(
            "every nonzero reviewed event needs exactly one interval evidence entry"
        )
    raw_candidates = review.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise CardEventNetIntervalPilotError("review.candidates must not be empty")
    candidates: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()
    linked_event_ids: set[str] = set()
    for index, raw_candidate in enumerate(raw_candidates):
        if not isinstance(raw_candidate, Mapping):
            raise CardEventNetIntervalPilotError(f"review.candidates[{index}] is invalid")
        candidate_id = _identifier(raw_candidate.get("candidate_id"), "candidate_id")
        if candidate_id in candidate_ids:
            raise CardEventNetIntervalPilotError(f"review candidate repeats {candidate_id}")
        kind = raw_candidate.get("kind")
        if kind not in _CANDIDATE_KINDS:
            raise CardEventNetIntervalPilotError(
                f"review candidate {candidate_id} must be uncertain or missed_hard_negative"
            )
        decision = raw_candidate.get("decision")
        if decision not in _DECISIONS:
            raise CardEventNetIntervalPilotError(f"review candidate {candidate_id} has no decision")
        source_frames = raw_candidate.get("source_frames")
        if not isinstance(source_frames, list) or not source_frames:
            raise CardEventNetIntervalPilotError(
                f"review candidate {candidate_id} needs source-frame evidence"
            )
        normalised_frames = []
        for frame in source_frames:
            if not isinstance(frame, Mapping):
                raise CardEventNetIntervalPilotError(
                    f"review candidate {candidate_id} has invalid source-frame evidence"
                )
            normalised_frames.append(
                {
                    "frame_id": _identifier(frame.get("frame_id"), "candidate.frame_id"),
                    "time_us": _non_negative_int(frame.get("time_us"), "candidate.time_us"),
                }
            )
            if normalised_frames[-1]["time_us"] > duration_us:
                raise CardEventNetIntervalPilotError(
                    f"review candidate {candidate_id} has out-of-range source-frame evidence"
                )
        candidate = {
            "candidate_id": candidate_id,
            "kind": kind,
            "decision": decision,
            "source_frames": sorted(
                normalised_frames, key=lambda item: (item["time_us"], item["frame_id"])
            ),
        }
        linked_event_id = raw_candidate.get("event_id")
        if decision == "missed_event":
            linked_event_id = _identifier(linked_event_id, f"candidate {candidate_id}.event_id")
            if linked_event_id not in interval_ids:
                raise CardEventNetIntervalPilotError(
                    f"candidate {candidate_id} links to an unknown interval event"
                )
            linked_event_ids.add(linked_event_id)
            candidate["event_id"] = linked_event_id
        elif linked_event_id is not None:
            raise CardEventNetIntervalPilotError(
                f"candidate {candidate_id} must not link an event for decision {decision}"
            )
        candidate_ids.add(candidate_id)
        candidates.append(candidate)
    if linked_event_ids != interval_ids:
        raise CardEventNetIntervalPilotError(
            "each reviewed interval must be linked to a missed-event candidate"
        )
    decisions = {
        decision: sum(item["decision"] == decision for item in candidates)
        for decision in _DECISIONS
    }
    normalized = {
        "schema_version": CARD_EVENTNET_INTERVAL_PILOT_REQUEST_SCHEMA_VERSION,
        "pilot_id": review["pilot_id"],
        "recording_id": recording_id,
        "coverage": coverage,
        "events": event_payload["events"],
        "interval_evidence": [
            {"event_id": event_id, "source_frames": evidence_by_event[event_id]}
            for event_id in sorted(evidence_by_event)
        ],
        "candidates": sorted(candidates, key=lambda item: item["candidate_id"]),
    }
    return normalized, events.to_mapping()["events"], decisions


def _load_sampling_report(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    payload = _read_json(path, f"{label} sampling report")
    selected = payload.get("selected")
    available = payload.get("available")
    if not isinstance(selected, Mapping) or not isinstance(available, Mapping):
        raise CardEventNetIntervalPilotError(
            f"{label} sampling report needs available and selected counts"
        )
    required = {"positive", "ordinary_negative", "ignore", "total"}
    if not required.issubset(selected) or not required.issubset(available):
        raise CardEventNetIntervalPilotError(f"{label} sampling report has incomplete counts")
    return payload, _sha256_file(path)


def _sampling_comparison(
    baseline: Mapping[str, Any],
    pilot: Mapping[str, Any],
    *,
    baseline_digest: str,
    pilot_digest: str,
) -> dict[str, Any]:
    def counts(report: Mapping[str, Any], key: str) -> dict[str, int]:
        value = report[key]
        assert isinstance(value, Mapping)
        return {
            name: int(value[name])
            for name in ("positive", "ordinary_negative", "ignore", "total")
        }

    baseline_selected = counts(baseline, "selected")
    pilot_selected = counts(pilot, "selected")
    baseline_available = counts(baseline, "available")
    pilot_available = counts(pilot, "available")
    return {
        "state": "compared",
        "baseline_0063": {
            "sha256": baseline_digest,
            "available": baseline_available,
            "selected": baseline_selected,
        },
        "pilot": {
            "sha256": pilot_digest,
            "available": pilot_available,
            "selected": pilot_selected,
        },
        "selected_delta": {
            key: pilot_selected[key] - baseline_selected[key] for key in baseline_selected
        },
        "available_delta": {
            key: pilot_available[key] - baseline_available[key] for key in baseline_available
        },
    }


def _diagnostics(review: Mapping[str, Any], *, tolerance_s: float) -> dict[str, Any]:
    if (
        not isinstance(tolerance_s, (int, float))
        or isinstance(tolerance_s, bool)
        or tolerance_s < 0
    ):
        raise CardEventNetIntervalPilotError("diagnostics tolerance_s must be non-negative")
    intervals = []
    for event in review["events"]:
        start_us, end_us = event.get("start_us"), event.get("end_us")
        if isinstance(start_us, int) and isinstance(end_us, int):
            intervals.append((start_us / 1_000_000, end_us / 1_000_000, event["event_id"]))
    predictions = review.get("predictions", [])
    if predictions is None:
        predictions = []
    if not isinstance(predictions, list):
        raise CardEventNetIntervalPilotError("review.predictions must be a list")
    details: list[dict[str, Any]] = []
    counts = {"stable_end_match": 0, "in_progress_trick_clear": 0, "confirmed_no_event_trigger": 0}
    seen: set[str] = set()
    for index, raw in enumerate(predictions):
        if not isinstance(raw, Mapping):
            raise CardEventNetIntervalPilotError(f"review.predictions[{index}] is invalid")
        prediction_id = _identifier(raw.get("prediction_id"), "prediction_id")
        if prediction_id in seen:
            raise CardEventNetIntervalPilotError(f"prediction repeats {prediction_id}")
        time_s = raw.get("time_s")
        if isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or time_s < 0:
            raise CardEventNetIntervalPilotError(f"prediction {prediction_id} has invalid time_s")
        stable = next(
            (item for item in intervals if abs(item[1] - float(time_s)) <= tolerance_s), None
        )
        in_progress = next(
            (item for item in intervals if item[0] <= float(time_s) < item[1]), None
        )
        if stable is not None:
            outcome = "stable_end_match"
            detail = {
                "event_id": stable[2],
                "interval_start_s": stable[0],
                "interval_end_s": stable[1],
            }
        elif in_progress is not None:
            outcome = "in_progress_trick_clear"
            detail = {
                "event_id": in_progress[2],
                "interval_start_s": in_progress[0],
                "interval_end_s": in_progress[1],
            }
        else:
            outcome = "confirmed_no_event_trigger"
            detail = {}
        counts[outcome] += 1
        details.append(
            {
                "prediction_id": prediction_id,
                "time_s": float(time_s),
                "outcome": outcome,
                **detail,
            }
        )
        seen.add(prediction_id)
    return {
        "tolerance_s": float(tolerance_s),
        "counts": counts,
        "details": sorted(details, key=lambda item: item["prediction_id"]),
    }


def _derive_dataset(
    baseline: Mapping[str, Any],
    *,
    recording_id: str,
    revision: Mapping[str, Any],
    review_digest: str,
    repository: Path,
    output_root: Path,
) -> tuple[Path, dict[str, Any]]:
    entries = copy.deepcopy(baseline.get("entries"))
    if not isinstance(entries, list):
        raise CardEventNetIntervalPilotError("0063 dataset entries are invalid")
    selected = next((item for item in entries if item.get("recording_id") == recording_id), None)
    if not isinstance(selected, dict):
        raise CardEventNetIntervalPilotError("review recording is not in the 0063 dataset")
    if selected.get("partition") == "test":
        raise CardEventNetIntervalPilotError(
            "the bounded pilot cannot alter the sealed test partition"
        )
    selected.update(
        {
            "event_revision_id": revision["revision_id"],
            "event_revision_manifest_path": revision["manifest_path"],
            "event_revision_manifest_sha256": revision["manifest_sha256"],
            "event_revision_content_path": revision["content_path"],
            "event_revision_content_sha256": revision["content_sha256"],
            "event_count": revision["event_count"],
            "duration_us": revision["duration_us"],
            "review_coverage": revision["review_coverage"],
        }
    )
    dataset_core = {
        "schema_version": CARD_EVENTNET_DATASET_SCHEMA_VERSION,
        "task": baseline.get("task", "cardevent_event_detection"),
        "readiness_digest": review_digest,
        "split_version_id": baseline.get("split_version_id"),
        "split_version_digest": baseline.get("split_version_digest"),
        "test_sealed": True,
        "entries": entries,
    }
    dataset_digest = _digest(dataset_core)
    dataset_id = f"cardeventnet-interval-pilot-{dataset_digest[:20]}"
    dataset = {
        **dataset_core,
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
    }
    split_core = {
        "schema_version": CARD_EVENTNET_SPLIT_SCHEMA_VERSION,
        "task": dataset_core["task"],
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "group_key_names": baseline.get(
            "group_key_names", ["session_id", "source_lineage", "table_setup"]
        ),
        "train": list(baseline.get("split", {}).get("train", []))
        if isinstance(baseline.get("split"), Mapping)
        else [],
        "validation": list(baseline.get("split", {}).get("validation", []))
        if isinstance(baseline.get("split"), Mapping)
        else [],
        "test": list(baseline.get("split", {}).get("test", []))
        if isinstance(baseline.get("split"), Mapping)
        else [],
        "unassigned": list(baseline.get("split", {}).get("unassigned", []))
        if isinstance(baseline.get("split"), Mapping)
        else [],
        "test_sealed": True,
    }
    # Frozen dataset.json does not contain the split lists.  Use the baseline split artifact stored
    # next to the dataset when this helper is called through run_cardeventnet_interval_pilot.
    if not split_core["train"] and not split_core["validation"] and not split_core["test"]:
        raise CardEventNetIntervalPilotError("0063 split artifact is missing its partition lists")
    split_digest = _digest(split_core)
    split = {
        **split_core,
        "split_version_id": f"cardeventnet-split-{split_digest[:20]}",
        "split_version_digest": split_digest,
    }
    coverage_core = {
        "schema_version": CARD_EVENTNET_COVERAGE_SCHEMA_VERSION,
        "task": dataset_core["task"],
        "dataset_version_id": dataset_id,
        "dataset_version_digest": dataset_digest,
        "partitions": _coverage(entries),
    }
    coverage = {**coverage_core, "coverage_digest": _digest(coverage_core)}
    receipt_core = {
        "schema_version": CARD_EVENTNET_FREEZE_RECEIPT_SCHEMA_VERSION,
        "receipt_type": "cardeventnet_dataset_freeze",
        "operator": "epic-0066-m4-pilot",
        "inputs": [
            {"kind": "baseline_0063_dataset", "digest": baseline["dataset_version_digest"]},
            {"kind": "reviewed_event_revision", "digest": review_digest},
        ],
        "outputs": [
            {"kind": "dataset", "id": dataset_id, "digest": dataset_digest},
            {"kind": "split", "id": split["split_version_id"], "digest": split_digest},
            {"kind": "coverage", "digest": coverage["coverage_digest"]},
        ],
    }
    receipt_digest = _digest(receipt_core)
    receipt = {
        **receipt_core,
        "receipt_id": f"receipt-cardeventnet-interval-pilot-{receipt_digest[:20]}",
        "receipt_digest": receipt_digest,
    }
    dataset_dir = output_root / "dataset"
    for name, payload in (
        ("dataset.json", dataset),
        ("split.json", split),
        ("coverage.json", coverage),
        ("receipt.json", receipt),
    ):
        _write_immutable(dataset_dir / name, _json_bytes(payload))
    return dataset_dir, dataset


def run_cardeventnet_interval_pilot(
    repository_root: str | Path,
    *,
    baseline_dataset_path: str | Path,
    review_path: str | Path,
    output_root: str | Path,
    baseline_sampling_report_path: str | Path,
    pilot_sampling_report_path: str | Path,
    tolerance_s: float = 0.5,
) -> dict[str, Any]:
    """Publish and materialize one bounded interval-review pilot."""

    repository = Path(repository_root).expanduser().resolve()
    baseline_dir = _resolve_path(repository, baseline_dataset_path)
    review_file = _resolve_path(repository, review_path)
    output = _resolve_path(repository, output_root)
    try:
        output.relative_to(repository)
    except ValueError as error:
        raise CardEventNetIntervalPilotError(
            "pilot output must be inside the repository"
        ) from error
    baseline = _read_json(baseline_dir / "dataset.json", "0063 dataset")
    split = _read_json(baseline_dir / "split.json", "0063 split")
    _read_json(baseline_dir / "coverage.json", "0063 coverage")
    _read_json(baseline_dir / "receipt.json", "0063 receipt")
    baseline_artifacts = {
        name: _sha256_file(baseline_dir / name)
        for name in ("dataset.json", "split.json", "coverage.json", "receipt.json")
    }
    review = _read_json(review_file, "interval pilot request")
    review_digest = _sha256_file(review_file)
    entries = baseline.get("entries")
    if not isinstance(entries, list):
        raise CardEventNetIntervalPilotError("0063 dataset entries are invalid")
    recording_id = _identifier(review.get("recording_id"), "review.recording_id")
    entry = next((item for item in entries if item.get("recording_id") == recording_id), None)
    if not isinstance(entry, Mapping):
        raise CardEventNetIntervalPilotError("review recording is not in the 0063 dataset")
    if entry.get("partition") == "test":
        raise CardEventNetIntervalPilotError(
            "the bounded pilot cannot alter the sealed test partition"
        )
    base_manifest_path = _resolve_path(repository, entry.get("event_revision_manifest_path"))
    base_content_path = _resolve_path(repository, entry.get("event_revision_content_path"))
    base_manifest_digest = _digest_value(
        entry.get("event_revision_manifest_sha256"), "base manifest digest"
    )
    base_content_digest = _digest_value(
        entry.get("event_revision_content_sha256"), "base content digest"
    )
    if (
        _sha256_file(base_manifest_path) != base_manifest_digest
        or _sha256_file(base_content_path) != base_content_digest
    ):
        raise CardEventNetIntervalPilotError("0063 event revision bytes differ from the dataset")
    base_manifest_bytes = base_manifest_path.read_bytes()
    base_content_bytes = base_content_path.read_bytes()
    base_manifest = _read_json(base_manifest_path, "base event revision manifest")
    base_revision_id = _identifier(base_manifest.get("revision_id"), "base revision_id")
    requested_base = review.get("base_revision")
    if not isinstance(requested_base, Mapping):
        raise CardEventNetIntervalPilotError("review.base_revision is required")
    if (
        requested_base.get("revision_id") != base_revision_id
        or requested_base.get("manifest_sha256") != base_manifest_digest
        or requested_base.get("content_sha256") != base_content_digest
    ):
        raise CardEventNetIntervalPilotError(
            "review.base_revision does not match the 0063 event revision"
        )
    duration_us = (
        base_manifest.get("source", {}).get("duration_us")
        if isinstance(base_manifest.get("source"), Mapping)
        else None
    )
    duration_us = _positive_int(duration_us, "base revision duration_us")
    normalized_review, event_mappings, decision_counts = _review_events(
        review, recording_id=recording_id, duration_us=duration_us
    )
    created_at = review.get("created_at")
    if not isinstance(created_at, str) or not created_at.endswith("Z"):
        raise CardEventNetIntervalPilotError("review.created_at must be a UTC timestamp")
    operator_id = _identifier(review.get("operator_id"), "operator_id")
    revision_id = _identifier(review.get("reviewed_revision_id"), "reviewed_revision_id")
    content_mapping = {"schema_version": "event-data/v1", "events": event_mappings}
    content = parse_event_data_bytes(
        canonical_event_data_bytes(content_mapping), duration_us=duration_us
    )
    content_bytes = canonical_event_data_bytes(content)
    producer = HumanProducer(
        review_id=_identifier(normalized_review["pilot_id"], "pilot_id"),
        operator_id=operator_id,
        base_revision_id=base_revision_id,
    )
    manifest_mapping = {
        "schema_version": "data-revision/v1",
        "revision_id": revision_id,
        "content_type": "events",
        "content_schema": "event-data/v1",
        "recording_id": recording_id,
        "source": base_manifest.get("source"),
        "content_sha256": _sha256_bytes(content_bytes),
        "input_revision_ids": [base_revision_id],
        "origin": "corrected",
        "producer": producer.to_mapping(),
        "coverage": normalized_review["coverage"],
        "created_at": created_at,
    }
    manifest = DataRevision.from_mapping(manifest_mapping)
    manifest_bytes = canonical_data_revision_bytes(manifest)
    revision_root = output / "revision" / recording_id / revision_id
    manifest_path = revision_root / "manifest.json"
    content_path = revision_root / "content.json"
    _write_immutable(manifest_path, manifest_bytes)
    _write_immutable(content_path, content_bytes)
    revision = {
        "revision_id": revision_id,
        "manifest_path": _repository_relative(repository, manifest_path, "revision manifest"),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "content_path": _repository_relative(repository, content_path, "revision content"),
        "content_sha256": _sha256_bytes(content_bytes),
        "event_count": len(content.events),
        "duration_us": duration_us,
        "review_coverage": normalized_review["coverage"],
        "base_revision_id": base_revision_id,
        "base_manifest_sha256": base_manifest_digest,
        "base_content_sha256": base_content_digest,
    }
    baseline_for_dataset = dict(baseline)
    baseline_for_dataset["split"] = split
    dataset_dir, pilot_dataset = _derive_dataset(
        baseline_for_dataset,
        recording_id=recording_id,
        revision=revision,
        review_digest=review_digest,
        repository=repository,
        output_root=output,
    )
    try:
        materialization = materialize_cardeventnet_dataset(
            dataset_dir,
            repository_root=repository,
            output_root=output / "view",
        )
    except CardEventNetMaterializationError as error:
        raise CardEventNetIntervalPilotError(
            f"pilot trainer view could not be materialized: {error}"
        ) from error
    baseline_sampling, baseline_sampling_digest = _load_sampling_report(
        _resolve_path(repository, baseline_sampling_report_path), label="0063"
    )
    pilot_sampling, pilot_sampling_digest = _load_sampling_report(
        _resolve_path(repository, pilot_sampling_report_path), label="pilot"
    )
    unchanged = {
        name: _sha256_file(baseline_dir / name) == digest
        for name, digest in baseline_artifacts.items()
    }
    diagnostics = _diagnostics(review, tolerance_s=tolerance_s)
    report_core = {
        "schema_version": CARD_EVENTNET_INTERVAL_PILOT_SCHEMA_VERSION,
        "pilot_id": normalized_review["pilot_id"],
        "recording_id": recording_id,
        "base_0063": {
            "dataset_version_id": baseline.get("dataset_version_id"),
            "dataset_version_digest": baseline.get("dataset_version_digest"),
            "event_revision_id": base_revision_id,
            "manifest_sha256": base_manifest_digest,
            "content_sha256": base_content_digest,
        },
        "review": {
            "request_sha256": review_digest,
            "operator_id": operator_id,
            "candidate_count": len(normalized_review["candidates"]),
            "decision_counts": decision_counts,
            "ambiguous_hard_negative_candidates": {
                "input": len(normalized_review["candidates"]),
                "interval_resolved": decision_counts["missed_event"],
                "confirmed_no_event": decision_counts["no_event"],
                "remaining_uncertain": decision_counts["uncertain"],
                "reduced_by": decision_counts["missed_event"],
            },
            "interval_count": len(normalized_review["interval_evidence"]),
            "coverage": normalized_review["coverage"],
            "source_frame_evidence": normalized_review["interval_evidence"],
        },
        "reviewed_revision": revision,
        "pilot_dataset": {
            "dataset_version_id": pilot_dataset["dataset_version_id"],
            "dataset_version_digest": pilot_dataset["dataset_version_digest"],
            "path": _repository_relative(repository, dataset_dir, "pilot dataset"),
        },
        "materialization": materialization.to_mapping(),
        "sampling_comparison": _sampling_comparison(
            baseline_sampling,
            pilot_sampling,
            baseline_digest=baseline_sampling_digest,
            pilot_digest=pilot_sampling_digest,
        ),
        "diagnostics": diagnostics,
        "frozen_0063_artifacts": {
            "before": baseline_artifacts,
            "unchanged": unchanged,
            "all_unchanged": all(unchanged.values()),
        },
    }
    report = {**report_core, "report_digest": _digest(report_core)}
    _write_immutable(output / "report.json", _json_bytes(report))
    _write_immutable(output / "review.json", _json_bytes(normalized_review))
    # Keep the raw base bytes in memory until all identity checks have completed.  This explicit
    # use documents that the pilot never rewrites the source revision in place.
    del base_manifest_bytes, base_content_bytes
    return report


def render_cardeventnet_interval_pilot_human(report: Mapping[str, Any]) -> str:
    """Render the bounded pilot report for an operator."""

    review = report["review"]
    diagnostics = report["diagnostics"]["counts"]
    sampling = report["sampling_comparison"]
    lines = [
        "CardEventNet interval-review pilot",
        f"pilot: {report['pilot_id']}",
        f"recording: {report['recording_id']}",
        f"reviewed intervals: {review['interval_count']}",
        "review coverage: "
        + ("complete" if review["coverage"]["coverage_complete"] else "incomplete"),
        "candidate decisions: "
        + ", ".join(f"{key}={value}" for key, value in sorted(review["decision_counts"].items())),
        "diagnostics: " + ", ".join(f"{key}={value}" for key, value in sorted(diagnostics.items())),
        "sampling: "
        + ", ".join(f"{key}={value}" for key, value in sorted(sampling["selected_delta"].items())),
        f"0063 artifacts unchanged: {report['frozen_0063_artifacts']['all_unchanged']}",
        f"report digest: {report['report_digest']}",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "CARD_EVENTNET_INTERVAL_PILOT_REQUEST_SCHEMA_VERSION",
    "CARD_EVENTNET_INTERVAL_PILOT_SCHEMA_VERSION",
    "CardEventNetIntervalPilotError",
    "render_cardeventnet_interval_pilot_human",
    "run_cardeventnet_interval_pilot",
]
