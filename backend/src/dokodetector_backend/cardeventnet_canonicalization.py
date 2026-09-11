"""Canonicalize active CardEventNet event data for epic 0062 M0.

The migration changes only event-type values in the active annotation corpus, active review
fixtures, and revisions reachable from current event references or selections.  Immutable
historical revisions and frozen datasets are never rewritten.  A deterministic receipt makes a
completed migration auditable and turns a repeated invocation into a validation-only no-op.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from doko_operations.pipeline_data import (
    CARD_STATE_CHANGED_EVENT_TYPE,
    EventData,
    EventDataRevision,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
    canonical_json_bytes,
    sha256_bytes,
)
from doko_operations.pipeline_reference import ReferenceDraftItem

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.pipeline_reference_store import (
    PipelineReferenceStore,
    StoredPipelineReference,
)
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    PipelineRuntimeStorage,
    PipelineSelectionStore,
    StoredPipelineRevision,
)

CANONICALIZATION_SCHEMA_VERSION = "cardeventnet-canonicalization/v1"
CANONICALIZATION_ID = "cardeventnet-card-state-m0"
CANONICALIZATION_TIMESTAMP = "2026-09-11T00:00:00.000Z"
DEFAULT_RECEIPT_RELATIVE_PATH = Path("data/operations/cardeventnet-canonicalization-m0.json")
LEGACY_EVENT_TYPES = frozenset(
    {
        "card_played",
        "trick_cleared",
        "card_moved",
        "card_removed",
        "card_returned",
        "multiple_cards_dropped",
        "anomalous_state_change",
    }
)
_EVENT_FIELD_PATTERN = re.compile(r'(?P<field>"(?:type|event_type)"\s*:\s*)"(?P<value>[^"\\]*)"')
_MASKED_EVENT_TYPE = "__event_type__"


class CardEventNetCanonicalizationError(RuntimeError):
    """The active CardEventNet data cannot be canonicalized safely."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardEventNetCanonicalizationError(f"Could not read JSON: {path}") from error
    if not isinstance(value, Mapping):
        raise CardEventNetCanonicalizationError(f"JSON document is not an object: {path}")
    return raw, value


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise CardEventNetCanonicalizationError(
            f"path is outside its configured root: {path}"
        ) from error


def _legacy_event_counts(value: Any) -> Counter[str]:
    counts: Counter[str] = Counter()

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if key in {"type", "event_type"} and child in LEGACY_EVENT_TYPES:
                    counts[str(child)] += 1
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return counts


def _masked_event_evidence(value: Any) -> Any:
    """Return JSON with event-type values masked for before/after comparisons."""

    if isinstance(value, Mapping):
        return {
            key: (
                _MASKED_EVENT_TYPE
                if key in {"type", "event_type"}
                and (child in LEGACY_EVENT_TYPES or child == CARD_STATE_CHANGED_EVENT_TYPE)
                else _masked_event_evidence(child)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_masked_event_evidence(child) for child in value]
    return value


def _event_evidence_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(_masked_event_evidence(value)))


def _replace_event_types_in_bytes(raw: bytes) -> tuple[bytes, Counter[str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CardEventNetCanonicalizationError("JSON document is not UTF-8") from error
    changed: Counter[str] = Counter()

    def replace_match(match: re.Match[str]) -> str:
        value = match.group("value")
        if value not in LEGACY_EVENT_TYPES:
            return match.group(0)
        changed[value] += 1
        return f"{match.group('field')}{json.dumps(CARD_STATE_CHANGED_EVENT_TYPE)}"

    return _EVENT_FIELD_PATTERN.sub(replace_match, text).encode("utf-8"), changed


def _source_inventory_entry(path: Path, root: Path, *, role: str) -> dict[str, Any]:
    raw, value = _read_json(path)
    counts = _legacy_event_counts(value)
    event_count = None
    if role == "annotation":
        events = value.get("events")
        if not isinstance(events, list):
            raise CardEventNetCanonicalizationError(
                f"CardEventNet annotation events are not a list: {path}"
            )
        event_count = len(events)
    return {
        "path": _relative_path(path, root),
        "role": role,
        "byte_length": len(raw),
        "sha256": _sha256_bytes(raw),
        "event_count": event_count,
        "legacy_event_counts": dict(sorted(counts.items())),
        "event_evidence_sha256": _event_evidence_sha256(value),
    }


def _source_paths(source_root: Path) -> tuple[tuple[Path, str], ...]:
    annotations_root = source_root / "annotations"
    review_root = source_root / "reviews"
    paths: list[tuple[Path, str]] = [
        (path, "annotation")
        for path in sorted(annotations_root.glob("*.json"), key=lambda item: item.as_posix())
    ]
    if review_root.is_dir():
        paths.extend(
            (path, "active_fixture")
            for path in sorted(review_root.rglob("*.json"), key=lambda item: item.as_posix())
        )
    return tuple(paths)


def _canonicalize_source_files(
    source_root: Path,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], int]:
    before_annotations: list[dict[str, Any]] = []
    before_fixtures: list[dict[str, Any]] = []
    changed_count = 0
    for path, role in _source_paths(source_root):
        before = _source_inventory_entry(path, source_root, role=role)
        if role == "annotation":
            before_annotations.append(before)
        elif before["legacy_event_counts"]:
            before_fixtures.append(before)

        raw = path.read_bytes()
        replacement, changed = _replace_event_types_in_bytes(raw)
        if changed:
            atomic_replace_json(path, replacement)
            changed_count += sum(changed.values())

    after_annotations: list[dict[str, Any]] = []
    after_fixtures: list[dict[str, Any]] = []
    for path, role in _source_paths(source_root):
        after = _source_inventory_entry(path, source_root, role=role)
        if role == "annotation":
            after_annotations.append(after)
        elif any(item["path"] == after["path"] for item in before_fixtures):
            after_fixtures.append(after)

    if len(before_annotations) != len(after_annotations):
        raise CardEventNetCanonicalizationError("annotation inventory changed during migration")
    before_by_path = {item["path"]: item for item in before_annotations}
    after_by_path = {item["path"]: item for item in after_annotations}
    for path, before in before_by_path.items():
        after = after_by_path[path]
        if before["event_count"] != after["event_count"]:
            raise CardEventNetCanonicalizationError(f"annotation event count changed: {path}")
        if before["event_evidence_sha256"] != after["event_evidence_sha256"]:
            raise CardEventNetCanonicalizationError(f"annotation evidence changed: {path}")
        after["before_sha256"] = before["sha256"]
        after["before_byte_length"] = before["byte_length"]
        after["before_legacy_event_counts"] = before["legacy_event_counts"]

    fixture_by_path = {item["path"]: item for item in before_fixtures}
    for after in after_fixtures:
        before = fixture_by_path[after["path"]]
        if before["event_evidence_sha256"] != after["event_evidence_sha256"]:
            raise CardEventNetCanonicalizationError(f"fixture evidence changed: {after['path']}")
        after["before_sha256"] = before["sha256"]
        after["before_byte_length"] = before["byte_length"]
        after["before_legacy_event_counts"] = before["legacy_event_counts"]

    return (
        tuple(sorted(after_annotations, key=lambda item: item["path"])),
        tuple(sorted(after_fixtures, key=lambda item: item["path"])),
        changed_count,
    )


def _revision_event_counts(revision: StoredPipelineRevision) -> Counter[str]:
    if not isinstance(revision.content, EventData):
        raise CardEventNetCanonicalizationError(
            f"event revision content is not event data: {revision.manifest.revision_id}"
        )
    return Counter(event.event_type for event in revision.content.events)


def _revision_evidence_sha256(revision: StoredPipelineRevision) -> str:
    if not isinstance(revision.content, EventData):
        raise CardEventNetCanonicalizationError(
            f"event revision content is not event data: {revision.manifest.revision_id}"
        )
    return _event_evidence_sha256(revision.content.to_mapping())


def _revision_inventory_entry(revision: StoredPipelineRevision) -> dict[str, Any]:
    manifest = revision.manifest
    if not isinstance(revision.content, EventData):
        raise CardEventNetCanonicalizationError(
            f"event revision content is not event data: {manifest.revision_id}"
        )
    counts = _revision_event_counts(revision)
    return {
        "revision_id": manifest.revision_id,
        "recording_id": manifest.recording_id,
        "content_sha256": manifest.content_sha256,
        "manifest_sha256": sha256_bytes(canonical_data_revision_bytes(manifest)),
        "event_count": len(revision.content.events),
        "legacy_event_counts": dict(
            sorted((key, value) for key, value in counts.items() if key in LEGACY_EVENT_TYPES)
        ),
        "event_evidence_sha256": _revision_evidence_sha256(revision),
        "source": manifest.source.to_mapping(),
        "input_revision_ids": list(manifest.input_revision_ids),
        "coverage": manifest.coverage,
    }


def _replacement_revision_id(revision_id: str) -> str:
    return f"canonical-card-state-{revision_id}"


def _canonical_event_revision(
    revision: StoredPipelineRevision,
) -> tuple[EventDataRevision | None, dict[str, Any] | None]:
    if not isinstance(revision.content, EventData):
        raise CardEventNetCanonicalizationError(
            f"event revision content is not event data: {revision.manifest.revision_id}"
        )
    if not any(event.event_type in LEGACY_EVENT_TYPES for event in revision.content.events):
        return None, None
    content = EventData(
        events=tuple(
            replace(event, event_type=CARD_STATE_CHANGED_EVENT_TYPE)
            if event.event_type in LEGACY_EVENT_TYPES
            else event
            for event in revision.content.events
        )
    )
    content_sha256 = sha256_bytes(canonical_event_data_bytes(content))
    manifest = replace(
        revision.manifest,
        revision_id=_replacement_revision_id(revision.manifest.revision_id),
        content_sha256=content_sha256,
    )
    replacement = EventDataRevision(manifest=manifest, content=content)
    return replacement, {
        "old_revision_id": revision.manifest.revision_id,
        "replacement_revision_id": manifest.revision_id,
        "old_content_sha256": revision.manifest.content_sha256,
        "replacement_content_sha256": manifest.content_sha256,
        "old_manifest_sha256": sha256_bytes(canonical_data_revision_bytes(revision.manifest)),
        "replacement_manifest_sha256": sha256_bytes(canonical_data_revision_bytes(manifest)),
        "event_count": len(content.events),
        "event_evidence_sha256": _revision_evidence_sha256(revision),
        "source": manifest.source.to_mapping(),
        "coverage": manifest.coverage,
        "input_revision_ids": list(manifest.input_revision_ids),
    }


def _reference_paths(store: PipelineReferenceStore) -> tuple[str, ...]:
    root = store.root
    if not root.is_dir() or root.is_symlink():
        return ()
    result: list[str] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".") or path.is_symlink() or not path.is_dir():
            continue
        event_root = path / "events"
        if not event_root.exists():
            continue
        if not (event_root / "state.json").is_file() or not (event_root / "draft.json").is_file():
            raise CardEventNetCanonicalizationError(f"event reference is incomplete: {event_root}")
        result.append(path.name)
    return tuple(result)


def _active_references(store: PipelineReferenceStore) -> tuple[StoredPipelineReference, ...]:
    references: list[StoredPipelineReference] = []
    for recording_id in _reference_paths(store):
        reference = store.get(recording_id, "events")
        if reference is None:
            raise CardEventNetCanonicalizationError(
                f"event reference could not be validated: {recording_id}"
            )
        references.append(reference)
    return tuple(references)


def _active_selections(store: PipelineSelectionStore) -> tuple[Any, ...]:
    root = store.root
    expected_paths: set[tuple[str, str]] = set()
    if root.is_dir() and not root.is_symlink():
        for recording_root in root.iterdir():
            if recording_root.name.startswith(".") or not recording_root.is_dir():
                continue
            for path in recording_root.glob("events.json"):
                expected_paths.add((recording_root.name, path.stem))
    selections: list[Any] = []
    for recording_id, content_type in sorted(expected_paths):
        selection = store.get(recording_id, content_type)
        if selection is None:
            raise CardEventNetCanonicalizationError(
                f"event selection could not be validated: {recording_id}/{content_type}"
            )
        selections.append(selection)
    return tuple(selections)


def _active_revision_ids(
    references: Iterable[StoredPipelineReference], selections: Iterable[Any]
) -> tuple[str, ...]:
    revision_ids: set[str] = set()
    for reference in references:
        for revision_id in (
            reference.state.source_revision_id,
            reference.state.selected_completed_revision_id,
            reference.draft.source_revision_id,
        ):
            if revision_id is not None:
                revision_ids.add(revision_id)
    for selection in selections:
        for revision_id in (
            selection.selected_generated_revision_id,
            selection.selected_completed_reference_revision_id,
        ):
            if revision_id is not None:
                revision_ids.add(revision_id)
    return tuple(sorted(revision_ids))


def _canonicalize_reference_item(item: ReferenceDraftItem) -> ReferenceDraftItem:
    if item.item.get("event_type") not in LEGACY_EVENT_TYPES:
        return item
    updated = dict(item.item)
    updated["event_type"] = CARD_STATE_CHANGED_EVENT_TYPE
    return replace(item, item=updated)


def _reference_change(
    before: StoredPipelineReference,
    after: StoredPipelineReference,
) -> dict[str, Any]:
    return {
        "recording_id": before.state.recording_id,
        "content_type": before.state.content_type,
        "draft_revision": before.state.draft_revision,
        "source_revision_before": before.state.source_revision_id,
        "source_revision_after": after.state.source_revision_id,
        "selected_completed_revision_before": before.state.selected_completed_revision_id,
        "selected_completed_revision_after": after.state.selected_completed_revision_id,
        "coverage_sha256": sha256_bytes(canonical_json_bytes(before.draft.coverage)),
        "lineage_before": before.draft.source_revision_id,
        "lineage_after": after.draft.source_revision_id,
        "items_event_evidence_sha256_before": _event_evidence_sha256(
            [item.item for item in before.draft.items]
        ),
        "items_event_evidence_sha256_after": _event_evidence_sha256(
            [item.item for item in after.draft.items]
        ),
    }


def _update_reference(
    store: PipelineReferenceStore,
    before: StoredPipelineReference,
    replacements: Mapping[str, str],
) -> StoredPipelineReference:
    state = replace(
        before.state,
        source_revision_id=(
            None
            if before.state.source_revision_id is None
            else replacements.get(before.state.source_revision_id, before.state.source_revision_id)
        ),
        selected_completed_revision_id=(
            None
            if before.state.selected_completed_revision_id is None
            else replacements.get(
                before.state.selected_completed_revision_id,
                before.state.selected_completed_revision_id,
            )
        ),
    )
    draft = replace(
        before.draft,
        source_revision_id=(
            None
            if before.draft.source_revision_id is None
            else replacements.get(before.draft.source_revision_id, before.draft.source_revision_id)
        ),
        items=tuple(_canonicalize_reference_item(item) for item in before.draft.items),
    )
    after = StoredPipelineReference(state=state, draft=draft)
    if after == before:
        return before
    with store.locked(before.state.recording_id, before.state.content_type):
        current = store.read_locked(before.state.recording_id, before.state.content_type)
        if current != before:
            raise CardEventNetCanonicalizationError(
                f"event reference changed during migration: {before.state.recording_id}"
            )
        return store.write_locked(after)


def _selection_change(before: Any, after: Any) -> dict[str, Any]:
    return {
        "recording_id": before.recording_id,
        "content_type": before.content_type,
        "selection_revision_before": before.revision,
        "selection_revision_after": after.revision,
        "selected_generated_revision_before": before.selected_generated_revision_id,
        "selected_generated_revision_after": after.selected_generated_revision_id,
        "selected_completed_revision_before": before.selected_completed_reference_revision_id,
        "selected_completed_revision_after": after.selected_completed_reference_revision_id,
    }


def _frozen_dataset_inventory(operations_root: Path) -> tuple[dict[str, Any], ...]:
    if not operations_root.is_dir():
        return ()
    entries: list[dict[str, Any]] = []
    for path in sorted(operations_root.rglob("*.json"), key=lambda item: item.as_posix()):
        relative = path.relative_to(operations_root)
        if any(
            part in {"pipeline-references", "pipeline", "cardeventnet-imports"}
            for part in relative.parts
        ):
            continue
        if not any("dataset" in part.lower() for part in relative.parts):
            continue
        raw, value = _read_json(path)
        counts = _legacy_event_counts(value)
        if not counts:
            continue
        entries.append(
            {
                "path": relative.as_posix(),
                "sha256": _sha256_bytes(raw),
                "byte_length": len(raw),
                "legacy_event_counts": dict(sorted(counts.items())),
                "event_evidence_sha256": _event_evidence_sha256(value),
            }
        )
    return tuple(entries)


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {key: value for key, value in receipt.items() if key != "receipt_digest"}
        )
    )


def _validate_receipt(receipt: Mapping[str, Any]) -> None:
    expected_fields = {
        "schema_version",
        "migration_id",
        "canonical_event_type",
        "occurred_at",
        "tracked_annotations",
        "active_fixtures",
        "event_revisions",
        "revision_replacements",
        "reference_changes",
        "selection_changes",
        "frozen_datasets",
        "totals",
        "receipt_digest",
    }
    if set(receipt) != expected_fields:
        raise CardEventNetCanonicalizationError("canonicalization receipt has invalid fields")
    if receipt["schema_version"] != CANONICALIZATION_SCHEMA_VERSION:
        raise CardEventNetCanonicalizationError(
            "canonicalization receipt has an unsupported schema"
        )
    if receipt["migration_id"] != CANONICALIZATION_ID:
        raise CardEventNetCanonicalizationError("canonicalization receipt has an invalid ID")
    if receipt["canonical_event_type"] != CARD_STATE_CHANGED_EVENT_TYPE:
        raise CardEventNetCanonicalizationError(
            "canonicalization receipt has an invalid event type"
        )
    if receipt["receipt_digest"] != _receipt_digest(receipt):
        raise CardEventNetCanonicalizationError("canonicalization receipt digest does not match")


def _load_receipt(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw, value = _read_json(path)
    del raw
    receipt = dict(value)
    _validate_receipt(receipt)
    return receipt


def _validate_active_state(
    revision_store: PipelineRevisionStore,
    references: Iterable[StoredPipelineReference],
    selections: Iterable[Any],
) -> None:
    for reference in references:
        for revision_id in (
            reference.state.source_revision_id,
            reference.state.selected_completed_revision_id,
            reference.draft.source_revision_id,
        ):
            if revision_id is None:
                continue
            revision = revision_store.require(revision_id)
            if not isinstance(revision.content, EventData):
                raise CardEventNetCanonicalizationError(
                    f"active event pointer has non-event content: {revision_id}"
                )
            if any(event.event_type in LEGACY_EVENT_TYPES for event in revision.content.events):
                raise CardEventNetCanonicalizationError(
                    f"active event revision remains legacy: {revision_id}"
                )
        if any(item.item.get("event_type") in LEGACY_EVENT_TYPES for item in reference.draft.items):
            raise CardEventNetCanonicalizationError(
                f"active event reference items remain legacy: {reference.state.recording_id}"
            )
    for selection in selections:
        for revision_id in (
            selection.selected_generated_revision_id,
            selection.selected_completed_reference_revision_id,
        ):
            if revision_id is None:
                continue
            revision = revision_store.require(revision_id)
            if not isinstance(revision.content, EventData):
                raise CardEventNetCanonicalizationError(
                    f"active event selection has non-event content: {revision_id}"
                )
            if any(event.event_type in LEGACY_EVENT_TYPES for event in revision.content.events):
                raise CardEventNetCanonicalizationError(
                    f"selected event revision remains legacy: {revision_id}"
                )


def canonicalize(
    *,
    source_root: Path,
    backend_root: Path,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Canonicalize active annotations and current event pipeline pointers."""

    source_root = source_root.expanduser().resolve()
    backend_root = backend_root.expanduser().resolve()
    if not source_root.is_dir():
        raise CardEventNetCanonicalizationError(f"source root is not a directory: {source_root}")
    if not backend_root.is_dir():
        raise CardEventNetCanonicalizationError(f"backend root is not a directory: {backend_root}")
    receipt_path = (
        (receipt_path or backend_root / DEFAULT_RECEIPT_RELATIVE_PATH).expanduser().resolve()
    )

    runtime_storage = PipelineRuntimeStorage(
        backend_root / ".runtime",
        backend_root / "data" / "operations",
    )
    revision_store = PipelineRevisionStore(runtime_storage)
    reference_store = PipelineReferenceStore(
        backend_root / "data" / "operations" / "pipeline-references"
    )
    selection_store = PipelineSelectionStore(runtime_storage, revision_store=revision_store)

    existing_receipt = _load_receipt(receipt_path)
    references = _active_references(reference_store)
    selections = _active_selections(selection_store)
    if existing_receipt is not None:
        _validate_active_state(revision_store, references, selections)
        for path, role in _source_paths(source_root):
            _raw, value = _read_json(path)
            del _raw, role
            if _legacy_event_counts(value):
                raise CardEventNetCanonicalizationError(
                    f"active source file remains legacy after migration: {path}"
                )
        return existing_receipt

    all_revisions = tuple(
        revision for revision in revision_store.list() if revision.manifest.content_type == "events"
    )
    revision_by_id = {revision.manifest.revision_id: revision for revision in all_revisions}
    if len(revision_by_id) != len(all_revisions):
        raise CardEventNetCanonicalizationError("event revision IDs are not unique")
    active_revision_ids = _active_revision_ids(references, selections)
    for revision_id in active_revision_ids:
        if revision_id not in revision_by_id:
            raise CardEventNetCanonicalizationError(
                f"active event pointer references an unavailable revision: {revision_id}"
            )

    source_before = tuple(
        _source_inventory_entry(path, source_root, role=role)
        for path, role in _source_paths(source_root)
    )
    frozen_datasets = _frozen_dataset_inventory(runtime_storage.operations_root)
    revision_inventory = tuple(
        sorted(
            (_revision_inventory_entry(revision) for revision in all_revisions),
            key=lambda item: item["revision_id"],
        )
    )

    tracked_annotations, active_fixtures, source_changed_count = _canonicalize_source_files(
        source_root
    )

    replacements: dict[str, str] = {}
    replacement_entries: list[dict[str, Any]] = []
    for revision_id in active_revision_ids:
        replacement, entry = _canonical_event_revision(revision_by_id[revision_id])
        if replacement is None or entry is None:
            replacements[revision_id] = revision_id
            continue
        revision_store.publish(replacement)
        replacements[revision_id] = replacement.manifest.revision_id
        replacement_entries.append(entry)

    reference_changes: list[dict[str, Any]] = []
    updated_references: list[StoredPipelineReference] = []
    for reference in references:
        updated = _update_reference(reference_store, reference, replacements)
        updated_references.append(updated)
        if updated != reference:
            reference_changes.append(_reference_change(reference, updated))

    selection_changes: list[dict[str, Any]] = []
    updated_selections: list[Any] = []
    for selection in selections:
        generated = (
            None
            if selection.selected_generated_revision_id is None
            else replacements.get(
                selection.selected_generated_revision_id,
                selection.selected_generated_revision_id,
            )
        )
        completed = (
            None
            if selection.selected_completed_reference_revision_id is None
            else replacements.get(
                selection.selected_completed_reference_revision_id,
                selection.selected_completed_reference_revision_id,
            )
        )
        if generated != selection.selected_generated_revision_id:
            raise CardEventNetCanonicalizationError(
                "selected generated event revisions require a processor-run output migration"
            )
        if completed == selection.selected_completed_reference_revision_id:
            updated_selections.append(selection)
            continue
        updated = selection_store.update_pointers(
            selection.recording_id,
            selection.content_type,
            expected_revision=selection.revision,
            selected_generated_revision_id=generated,
            selected_completed_reference_revision_id=completed,
            updated_at=selection.updated_at,
        )
        updated_selections.append(updated)
        selection_changes.append(_selection_change(selection, updated))

    updated_source_files = tuple(
        _source_inventory_entry(path, source_root, role=role)
        for path, role in _source_paths(source_root)
    )
    updated_frozen_datasets = _frozen_dataset_inventory(runtime_storage.operations_root)
    if frozen_datasets != updated_frozen_datasets:
        raise CardEventNetCanonicalizationError("frozen dataset inventory changed during migration")
    _validate_active_state(revision_store, updated_references, updated_selections)

    tracked_annotation_entries = tuple(
        entry for entry in updated_source_files if entry["role"] == "annotation"
    )
    fixture_entries = tuple(
        entry
        for entry in updated_source_files
        if entry["role"] == "active_fixture"
        and any(
            source_entry["path"] == entry["path"]
            for source_entry in source_before
            if source_entry["role"] == "active_fixture" and source_entry["legacy_event_counts"]
        )
    )
    durable_legacy_count = sum(
        sum(item["legacy_event_counts"].values()) for item in revision_inventory
    )
    tracked_legacy_count = sum(
        sum(item["legacy_event_counts"].values())
        for item in source_before
        if item["role"] == "annotation"
    )
    fixture_legacy_count = sum(
        sum(item["legacy_event_counts"].values())
        for item in source_before
        if item["role"] == "active_fixture"
    )
    historical_revision_ids = tuple(item["revision_id"] for item in revision_inventory)
    # Every old revision remains readable.  Keep this explicit in the receipt, including the
    # revisions that were current before the migration and are now historical.
    receipt: dict[str, Any] = {
        "schema_version": CANONICALIZATION_SCHEMA_VERSION,
        "migration_id": CANONICALIZATION_ID,
        "canonical_event_type": CARD_STATE_CHANGED_EVENT_TYPE,
        "occurred_at": CANONICALIZATION_TIMESTAMP,
        "tracked_annotations": list(tracked_annotation_entries),
        "active_fixtures": list(fixture_entries),
        "event_revisions": {
            "inventory_before": list(revision_inventory),
            "active_revision_ids_before": list(active_revision_ids),
            "historical_revision_ids": list(historical_revision_ids),
            "frozen_datasets_unchanged": list(frozen_datasets),
        },
        "revision_replacements": sorted(
            replacement_entries, key=lambda item: item["old_revision_id"]
        ),
        "reference_changes": sorted(reference_changes, key=lambda item: item["recording_id"]),
        "selection_changes": sorted(
            selection_changes,
            key=lambda item: (item["recording_id"], item["content_type"]),
        ),
        "frozen_datasets": list(frozen_datasets),
        "totals": {
            "tracked_annotation_files": sum(
                1 for item in source_before if item["role"] == "annotation"
            ),
            "tracked_annotation_events": sum(
                item["event_count"] or 0 for item in source_before if item["role"] == "annotation"
            ),
            "tracked_legacy_events": tracked_legacy_count,
            "active_fixture_files": len(fixture_entries),
            "active_fixture_legacy_events": fixture_legacy_count,
            "durable_event_revisions": len(revision_inventory),
            "durable_legacy_events": durable_legacy_count,
            "source_values_changed": source_changed_count,
            "replacement_revisions": len(replacement_entries),
            "changed_references": len(reference_changes),
            "changed_selections": len(selection_changes),
        },
    }
    receipt["receipt_digest"] = _receipt_digest(receipt)
    _validate_receipt(receipt)
    atomic_replace_json(receipt_path, canonical_json_bytes(receipt))
    return receipt


def _default_repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repository_root = _default_repository_root()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=repository_root / "card_event_net" / "data",
    )
    parser.add_argument("--backend-root", type=Path, default=repository_root)
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args(argv)
    receipt = canonicalize(
        source_root=args.source_root,
        backend_root=args.backend_root,
        receipt_path=args.receipt,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANONICALIZATION_ID",
    "CANONICALIZATION_SCHEMA_VERSION",
    "CARD_STATE_CHANGED_EVENT_TYPE",
    "CardEventNetCanonicalizationError",
    "LEGACY_EVENT_TYPES",
    "canonicalize",
]
