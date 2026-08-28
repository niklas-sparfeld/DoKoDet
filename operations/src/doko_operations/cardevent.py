"""Repository-backed CardEventNet review adapter.

This adapter keeps the source video at its canonical repository-intake path.  It writes only
review, annotation, cache-refresh, dataset, split, validation, and receipt metadata to the task
staging directory.  The full component UI can replace the decision provider without changing the
shared review-run contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evidence_package import discover_evidence_package_paths, load_evidence_package
from .holdout import (
    SystemHoldoutError,
    empty_system_holdout_registry,
    validate_split_against_system_holdout,
    validate_system_holdout_registry,
)
from .review import ReviewInput, ReviewItem, ReviewRunError, TaskArtifacts

CARD_EVENT_TASK = "cardevent_event_detection"
_ACCEPTED_OUTCOMES = frozenset(
    {"accepted", "confirmed", "confirmed_positive", "include", "reviewed", "complete"}
)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewRunError(f"Could not read CardEventNet input {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ReviewRunError(f"CardEventNet input must contain an object: {path}")
    return value


def _bundle_inputs(item: ReviewInput) -> tuple[Path, Mapping[str, Any], list[Mapping[str, Any]]]:
    bundle = Path(item.bundle_path).resolve()
    manifest = _read_json(bundle / "manifest.json")
    source = _read_json(bundle / "source-record.json")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise ReviewRunError(f"CardEventNet bundle has no files object: {bundle}")
    video_descriptor = files.get("video")
    if not isinstance(video_descriptor, Mapping) or not isinstance(
        video_descriptor.get("relative_path"), str
    ):
        raise ReviewRunError(f"CardEventNet bundle has no video descriptor: {bundle}")
    video = (bundle / video_descriptor["relative_path"]).resolve()
    if not video.is_file():
        raise ReviewRunError(f"CardEventNet source video is missing: {video}")
    runs = files.get("proposal_generator_runs", [])
    if not isinstance(runs, list):
        raise ReviewRunError(f"CardEventNet proposal descriptors are invalid: {bundle}")
    proposals: list[Mapping[str, Any]] = []
    for descriptor in runs:
        if not isinstance(descriptor, Mapping) or not isinstance(
            descriptor.get("relative_path"), str
        ):
            raise ReviewRunError(f"CardEventNet proposal descriptor is invalid: {bundle}")
        proposals.append(_read_json((bundle / descriptor["relative_path"]).resolve()))
    if source.get("source_asset_id") != item.source_asset_id:
        raise ReviewRunError(f"CardEventNet source identity differs for {item.source_asset_id}")
    if source.get("sha256") != item.source_sha256:
        raise ReviewRunError(f"CardEventNet source digest differs for {item.source_asset_id}")
    return video, source, proposals


def _proposal_items(
    item: ReviewInput,
    evidence_roots: Sequence[str | Path] = (),
) -> tuple[list[ReviewItem], dict[str, dict[str, Any]]]:
    video, source, proposals = _bundle_inputs(item)
    del video
    result: list[ReviewItem] = []
    metadata: dict[str, dict[str, Any]] = {}
    wide_id = (
        "cardevent-wide-"
        + _digest({"source_asset_id": item.source_asset_id, "source_sha256": item.source_sha256})[
            :20
        ]
    )
    wide = ReviewItem(
        wide_id,
        item.source_asset_id,
        "video_wide_pass",
        f"Review the complete recording at {item.source_asset_id}, including missed events.",
    )
    result.append(wide)
    metadata[wide_id] = {"kind": wide.kind}
    for proposal in proposals:
        run_id = proposal.get("proposal_generator_run_id")
        events = proposal.get("event_proposals", [])
        if not isinstance(run_id, str) or not isinstance(events, list):
            raise ReviewRunError(
                f"CardEventNet proposal run is incomplete for {item.source_asset_id}"
            )
        for index, event in enumerate(events):
            if not isinstance(event, Mapping) or not isinstance(event.get("time_s"), (int, float)):
                raise ReviewRunError(
                    f"CardEventNet event proposal is invalid for {item.source_asset_id}"
                )
            time_s = float(event["time_s"])
            probability = event.get("probability")
            item_id = (
                "cardevent-proposal-"
                + _digest(
                    {
                        "source_asset_id": item.source_asset_id,
                        "run_id": run_id,
                        "index": index,
                        "time_s": time_s,
                    }
                )[:20]
            )
            candidate = ReviewItem(
                item_id,
                item.source_asset_id,
                "proposal_candidate",
                f"Review CardEventNet proposal at {time_s:.3f}s from {run_id}.",
            )
            result.append(candidate)
            metadata[item_id] = {
                "kind": candidate.kind,
                "time_s": time_s,
                "probability": probability,
                "proposal_generator_run_id": run_id,
            }
    for proposal in proposals:
        probabilities = proposal.get("probabilities", [])
        decoder = proposal.get("decoder", {})
        threshold = decoder.get("threshold") if isinstance(decoder, Mapping) else None
        if not isinstance(probabilities, list) or not isinstance(threshold, (int, float)):
            continue
        low = next(
            (
                sample
                for sample in probabilities
                if isinstance(sample, Mapping)
                and isinstance(sample.get("time_s"), (int, float))
                and isinstance(sample.get("probability"), (int, float))
                and float(sample["probability"]) < float(threshold)
            ),
            None,
        )
        if low is None:
            continue
        time_s = float(low["time_s"])
        item_id = (
            "cardevent-negative-"
            + _digest(
                {"source_asset_id": item.source_asset_id, "time_s": time_s, "threshold": threshold}
            )[:20]
        )
        negative = ReviewItem(
            item_id,
            item.source_asset_id,
            "hard_negative",
            f"Review the hard-negative interval at {time_s:.3f}s.",
        )
        result.append(negative)
        metadata[item_id] = {
            "kind": negative.kind,
            "time_s": time_s,
            "probability": low["probability"],
        }
        break
    for package in _selected_evidence_packages(item, evidence_roots):
        package_item_id = (
            "cardevent-package-"
            + _digest(
                {"source_asset_id": item.source_asset_id, "package_id": package.bundle.package_id}
            )[:20]
        )
        package_item = ReviewItem(
            package_item_id,
            item.source_asset_id,
            "evidence_package",
            (
                f"Review accepted evidence package {package.bundle.package_id} "
                f"for {item.source_asset_id}."
            ),
        )
        result.append(package_item)
        metadata[package_item_id] = {
            "kind": package_item.kind,
            "package_id": package.bundle.package_id,
            "package_path": str(package.path),
        }
    result.sort(key=lambda value: (value.source_asset_id, value.kind, value.item_id))
    return result, metadata


def _selected_evidence_packages(
    item: ReviewInput, evidence_roots: Sequence[str | Path]
) -> list[Any]:
    roots = [Path(root).expanduser().resolve() for root in evidence_roots]
    bundle_path = Path(item.bundle_path).resolve()
    for ancestor in (bundle_path, *bundle_path.parents):
        roots.append(ancestor / "data" / "intake" / "evidence-packages")
    result: list[Any] = []
    seen: set[Path] = set()
    source_record = _read_json(bundle_path / "source-record.json")
    source_session_id = source_record.get("session_id")
    for root in roots:
        for package_path in discover_evidence_package_paths(root):
            if package_path in seen:
                continue
            seen.add(package_path)
            try:
                package = load_evidence_package(package_path)
            except (OSError, ValueError):
                continue
            if CARD_EVENT_TASK not in package.selected_tasks:
                continue
            lineage = package.lineage
            if (
                lineage.parent_source_asset_id != item.source_asset_id
                and lineage.parent_recording_id != item.recording_id
                and lineage.session_id != source_session_id
            ):
                continue
            result.append(package)
    return sorted(result, key=lambda value: value.bundle.package_id)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class CardEventNetReviewAdapter:
    """Use repository proposals to seed a complete video-wide CardEventNet review."""

    def __init__(self, *, evidence_roots: Sequence[str | Path] = ()) -> None:
        self.evidence_roots = tuple(Path(root).expanduser().resolve() for root in evidence_roots)
        self._system_holdout_registry = empty_system_holdout_registry()

    def set_system_holdout_registry(self, registry: Mapping[str, Any]) -> None:
        validate_system_holdout_registry(registry)
        self._system_holdout_registry = dict(registry)

    def discover(self, task: str, inputs: Sequence[ReviewInput]) -> Sequence[ReviewItem]:
        if task != CARD_EVENT_TASK:
            raise ReviewRunError(f"CardEventNet adapter cannot process {task}")
        result: list[ReviewItem] = []
        for item in sorted(inputs, key=lambda value: value.source_asset_id):
            source_items, _ = _proposal_items(item, self.evidence_roots)
            result.extend(source_items)
        return result

    def apply_decision(
        self,
        task: str,
        item: ReviewItem,
        decision: Mapping[str, Any],
        staging_dir: Path,
    ) -> None:
        if task != CARD_EVENT_TASK:
            raise ReviewRunError(f"CardEventNet adapter cannot process {task}")
        if not isinstance(decision.get("outcome"), str) or not decision["outcome"].strip():
            raise ReviewRunError(f"Decision for {item.item_id} needs an outcome.")
        log_path = staging_dir / "decision-log.json"
        current: dict[str, Any] = {}
        if log_path.is_file():
            loaded = _read_json(log_path)
            current = dict(loaded)
        current[item.item_id] = dict(decision)
        _write_json(log_path, current)

    def finalize(
        self,
        task: str,
        inputs: Sequence[ReviewInput],
        items: Sequence[Mapping[str, Any]],
        staging_dir: Path,
    ) -> TaskArtifacts:
        if task != CARD_EVENT_TASK:
            raise ReviewRunError(f"CardEventNet adapter cannot process {task}")
        metadata_by_item: dict[str, dict[str, Any]] = {}
        source_details: dict[str, tuple[Path, Mapping[str, Any], list[Mapping[str, Any]]]] = {}
        for input_item in inputs:
            video, source, proposals = _bundle_inputs(input_item)
            source_details[input_item.source_asset_id] = (video, source, proposals)
            _, item_metadata = _proposal_items(input_item, self.evidence_roots)
            metadata_by_item.update(item_metadata)
        wide_items = [
            item
            for item in items
            if item.get("kind") == "video_wide_pass" and item.get("state") == "complete"
        ]
        expected_wide = {source_id for source_id in source_details}
        reviewed_wide = {item.get("source_asset_id") for item in wide_items}
        if reviewed_wide != expected_wide:
            raise ReviewRunError(
                "A complete video-wide pass is required for every selected source asset; "
                "candidate decisions alone are not sufficient."
            )
        output_root = staging_dir / "cardevent"
        annotation_paths: list[Path] = []
        proposal_runs: dict[str, list[str]] = {}
        for source_id in sorted(source_details):
            video, source, proposals = source_details[source_id]
            events: list[dict[str, Any]] = []
            seen_times: set[float] = set()
            for item in items:
                if item.get("source_asset_id") != source_id or item.get("state") != "complete":
                    continue
                metadata = metadata_by_item.get(item.get("item_id"), {})
                if metadata.get("kind") != "proposal_candidate":
                    continue
                decision = item.get("decision")
                if (
                    not isinstance(decision, Mapping)
                    or decision.get("outcome") not in _ACCEPTED_OUTCOMES
                ):
                    continue
                time_s = float(metadata["time_s"])
                if any(abs(time_s - previous) <= 0.01 for previous in seen_times):
                    continue
                seen_times.add(time_s)
                events.append(
                    {
                        "time_s": time_s,
                        "type": "card_played",
                        "confidence": "confirmed",
                    }
                )
                run_id = metadata.get("proposal_generator_run_id")
                if isinstance(run_id, str):
                    proposal_runs.setdefault(source_id, []).append(run_id)
            events.sort(key=lambda value: value["time_s"])
            annotation_path = output_root / "annotations" / f"{source_id}.json"
            _write_json(
                annotation_path,
                {
                    "schema_version": "cardevent-annotation/v2",
                    "video": video.name,
                    "events": events,
                },
            )
            annotation_paths.append(annotation_path)
            proposal_runs.setdefault(source_id, [])
            proposal_runs[source_id] = sorted(set(proposal_runs[source_id]))
            del proposals
        entries = [
            {
                "dataset_item_id": item.source_asset_id,
                "source_asset_id": item.source_asset_id,
                "source_sha256": item.source_sha256,
                "annotation": f"annotations/{item.source_asset_id}.json",
                "review_state": "reviewed",
                "group_keys": _group_keys(source_details[item.source_asset_id][1]),
            }
            for item in inputs
        ]
        entries.sort(key=lambda value: value["dataset_item_id"])
        group_key_names = sorted({key for entry in entries for key, _ in entry["group_keys"]})
        dataset_core = {
            "schema_version": "cardevent-dataset-version/v1",
            "task": CARD_EVENT_TASK,
            "source_assets": [
                {"source_asset_id": item.source_asset_id, "source_sha256": item.source_sha256}
                for item in inputs
            ],
            "annotations": [str(path.relative_to(output_root)) for path in annotation_paths],
            "entries": entries,
            "group_key_names": group_key_names,
            "review_complete": True,
            "dirty_state": True,
        }
        dataset_path = output_root / "dataset" / "cardevent-dataset-version.json"
        _write_json(
            dataset_path,
            {
                **dataset_core,
                "dataset_version_id": "cardevent-" + _digest(dataset_core)[:20],
                "dataset_version_digest": _digest(dataset_core),
            },
        )
        split_path = output_root / "split-proposal" / "cardevent-split-proposal.json"
        split_core = {
            "schema_version": "cardevent-split-proposal/v1",
            "task": CARD_EVENT_TASK,
            "dataset_version_id": "cardevent-" + _digest(dataset_core)[:20],
            "dataset_version_digest": _digest(dataset_core),
            "group_key_names": group_key_names,
            "seed": 42,
            "train": [],
            "validation": [],
            "test": [],
            "unassigned": [entry["dataset_item_id"] for entry in entries],
        }
        _write_json(
            split_path,
            {
                **split_core,
                "split_version_id": "cardevent-split-" + _digest(split_core)[:20],
                "split_version_digest": _digest(split_core),
            },
        )
        validation_path = output_root / "validation" / "cardevent-validation.json"
        _write_json(
            validation_path,
            {
                "schema_version": "cardevent-validation/v1",
                "task": CARD_EVENT_TASK,
                "valid": True,
                "video_wide_pass": True,
                "source_assets": [item.source_asset_id for item in inputs],
            },
        )
        cache_path = output_root / "cache" / "cardevent-cache-refresh.json"
        _write_json(
            cache_path,
            {
                "schema_version": "cardevent-cache-refresh/v1",
                "task": CARD_EVENT_TASK,
                "action": "refresh_affected_entries",
                "source_assets": [
                    {"source_asset_id": item.source_asset_id, "source_sha256": item.source_sha256}
                    for item in inputs
                ],
            },
        )
        review_manifest_path = output_root / "cardevent-review-manifest.json"
        _write_json(
            review_manifest_path,
            {
                "schema_version": "cardevent-review-manifest/v1",
                "task": CARD_EVENT_TASK,
                "source_assets": [
                    {
                        "source_asset_id": item.source_asset_id,
                        "source_sha256": item.source_sha256,
                        "canonical_video_path": str(source_details[item.source_asset_id][0]),
                        "proposal_generator_run_ids": proposal_runs[item.source_asset_id],
                    }
                    for item in inputs
                ],
                "video_wide_review_complete": True,
            },
        )
        receipt_path = output_root / "lifecycle-receipt.json"
        receipt_payload = {
            "schema_version": "lifecycle-receipt/v1",
            "receipt_id": "receipt-cardevent-"
            + _digest([item.source_sha256 for item in inputs])[:20],
            "receipt_type": "annotation_application",
            "operator": "review-run",
            "occurred_at": _now(),
            "inputs": [
                {"kind": "source_asset", "id": item.source_asset_id, "digest": item.source_sha256}
                for item in inputs
            ],
            "outputs": [
                {"kind": "derived_artifact", "id": "cardevent-dataset-version"},
                {"kind": "derived_artifact", "id": "cardevent-split-proposal"},
            ],
            "dependencies": [
                {"kind": "source_asset", "id": item.source_asset_id, "digest": item.source_sha256}
                for item in inputs
            ],
            "metadata": {
                "task": CARD_EVENT_TASK,
                "video_wide_review_complete": True,
            },
        }
        receipt_payload["receipt_digest"] = _digest(
            {key: value for key, value in receipt_payload.items() if key != "receipt_digest"}
        )
        _write_json(receipt_path, receipt_payload)
        files = tuple(sorted(path for path in staging_dir.rglob("*") if path.is_file()))
        return TaskArtifacts(files, split_approval_required=True)

    def validate(self, task: str, staging_dir: Path) -> Sequence[str]:
        if task != CARD_EVENT_TASK:
            return (f"CardEventNet adapter cannot process {task}",)
        required = (
            staging_dir / "cardevent" / "dataset" / "cardevent-dataset-version.json",
            staging_dir / "cardevent" / "split-proposal" / "cardevent-split-proposal.json",
            staging_dir / "cardevent" / "validation" / "cardevent-validation.json",
            staging_dir / "cardevent" / "cache" / "cardevent-cache-refresh.json",
            staging_dir / "cardevent" / "cardevent-review-manifest.json",
            staging_dir / "cardevent" / "lifecycle-receipt.json",
        )
        errors = list(
            f"missing staged CardEventNet output: {path}" for path in required if not path.is_file()
        )
        if errors:
            return tuple(errors)
        try:
            dataset = _read_json(required[0])
            split = _read_json(required[1])
            validate_split_against_system_holdout(
                dataset, split, self._system_holdout_registry, CARD_EVENT_TASK
            )
        except (OSError, SystemHoldoutError, ReviewRunError) as exc:
            errors.append(f"CardEventNet split validation failed: {exc}")
        return tuple(errors)


def _group_keys(source: Mapping[str, Any]) -> list[list[str]]:
    values = [("source_lineage", str(source["source_asset_id"]))]
    for field in ("session_id", "game_id", "table_setup"):
        value = source.get(field)
        if isinstance(value, str) and value:
            values.append((field, value))
    return [list(value) for value in sorted(values)]


__all__ = ["CARD_EVENT_TASK", "CardEventNetReviewAdapter"]
