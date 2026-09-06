"""Create, edit, and complete maintained recording-pipeline references."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from doko_operations.pipeline_data import (
    DataRevision,
    HumanProducer,
    RecordingVideoSource,
    canonical_event_data_bytes,
    sha256_bytes,
)
from doko_operations.pipeline_reference import (
    PIPELINE_REFERENCE_CONTENT_TYPES,
    PIPELINE_REFERENCE_COVERAGE_SCHEMA_VERSION,
    PIPELINE_REFERENCE_IMPACT_SCHEMA_VERSION,
    PipelineReferenceContractError,
    PipelineReferenceDraft,
    PipelineReferenceOperation,
    PipelineReferenceState,
    ReferenceDraftItem,
)
from table_evidence_analyzer.pipeline_data import (
    PipelineDataError,
    VisibleCardData,
    VisualIdentityData,
    canonical_visible_card_data_bytes,
    canonical_visual_identity_data_bytes,
)

from dokodetector_backend.pipeline_reference_store import (
    PipelineReferenceNotFound,
    PipelineReferenceStore,
    PipelineReferenceStoreError,
    StoredPipelineReference,
)
from dokodetector_backend.pipeline_store import (
    PipelineNotFound,
    PipelineRevisionStore,
    PipelineSelectionConflict,
    PipelineSelectionStore,
    StoredPipelineRevision,
)
from dokodetector_backend.recording_bundle_store import RecordingBundleStore
from dokodetector_backend.repository_bundle_storage import RepositoryBundleStorage
from dokodetector_backend.video_probe import VideoProbeError, probe_video_path_metadata

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_ITEM_FIELDS = {
    "events": "event_id",
    "visible_cards": "event_id",
    "visual_identities": "card_id",
}


def _command_digest(payload: Mapping[str, Any]) -> str:
    """Hash command bytes without the retry-specific expected revision."""

    command = {
        key: value
        for key, value in payload.items()
        if key not in {"expected_revision", "command_id"}
    }
    return sha256_bytes(
        json.dumps(
            command, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


class PipelineReferenceError(RuntimeError):
    """The maintained-reference service could not complete an operation."""


class PipelineReferenceInputError(PipelineReferenceError, ValueError):
    """A maintained-reference request is invalid."""


class PipelineReferenceCoverageError(PipelineReferenceInputError):
    """A maintained-reference draft does not cover its declared scope."""

    def __init__(self, message: str, details: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.details = details


class PipelineReferenceConflict(PipelineReferenceError):
    """A maintained-reference request used an old draft revision."""

    def __init__(self, message: str, current: StoredPipelineReference) -> None:
        super().__init__(message)
        self.current = current


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or _SAFE_ID.fullmatch(value) is None
    ):
        raise PipelineReferenceInputError(f"{field} must be a safe identifier")
    return value


def _expected_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PipelineReferenceInputError("expected_revision must be a non-negative integer")
    return value


class PipelineReferenceService:
    """Own one mutable draft and publish immutable human reference revisions."""

    def __init__(
        self,
        settings: Any,
        recording_store: RecordingBundleStore,
        repository_storage: RepositoryBundleStorage,
        *,
        reference_store: PipelineReferenceStore,
        revision_store: PipelineRevisionStore,
        selection_store: PipelineSelectionStore,
    ) -> None:
        self.settings = settings
        self.recording_store = recording_store
        self.repository_storage = repository_storage
        self.reference_store = reference_store
        self.revision_store = revision_store
        self.selection_store = selection_store

    def get_reference(self, recording_id: str, content_type: str) -> StoredPipelineReference:
        self._validate_content_type(content_type)
        reference = self.reference_store.get(recording_id, content_type)
        if reference is None:
            raise PipelineReferenceNotFound(
                f"The maintained reference was not found: {recording_id}/{content_type}"
            )
        self._validate_reference_revision(reference)
        return reference

    def create_reference(
        self,
        recording_id: str,
        content_type: str,
        payload: Mapping[str, Any],
    ) -> StoredPipelineReference:
        self._validate_content_type(content_type)
        if not isinstance(payload, Mapping):
            raise PipelineReferenceInputError("the reference request must be an object")
        unknown = set(payload) - {"operator_id", "seed", "source_revision_id"}
        if unknown:
            raise PipelineReferenceInputError(
                f"the reference request has unknown fields: {', '.join(sorted(unknown))}"
            )
        operator_id = _identifier(payload.get("operator_id"), "operator_id")
        del operator_id
        existing = self.reference_store.get(recording_id, content_type)
        if existing is not None:
            raise PipelineReferenceConflict("a maintained reference already exists", existing)

        source_revision_id = payload.get("source_revision_id")
        if source_revision_id is not None:
            source_revision_id = _identifier(source_revision_id, "source_revision_id")
        else:
            seed = payload.get("seed", "selected_generated")
            if seed not in {"selected_generated", "selected_completed", "empty"}:
                raise PipelineReferenceInputError(
                    "seed must be selected_generated, selected_completed, or empty"
                )
            if seed != "empty":
                selection = self.selection_store.get(recording_id, content_type)
                if selection is not None:
                    source_revision_id = (
                        selection.selected_generated_revision_id
                        if seed == "selected_generated"
                        else selection.selected_completed_reference_revision_id
                    )
                if source_revision_id is None and seed == "selected_generated":
                    source_revision_id = (
                        None
                        if selection is None
                        else selection.selected_completed_reference_revision_id
                    )
                if source_revision_id is None:
                    raise PipelineReferenceInputError(
                        f"no {seed.replace('_', ' ')} exists for this recording"
                    )

        source_revision = None
        items: tuple[ReferenceDraftItem, ...] = ()
        if source_revision_id is not None:
            source_revision = self._require_source_revision(
                recording_id, content_type, source_revision_id
            )
            items = tuple(
                ReferenceDraftItem(
                    item_id=self._item_id(content_type, item),
                    base_item_id=None,
                    review_state="pending",
                    item=dict(item),
                )
                for item in self._content_items(content_type, source_revision)
            )
            self._validate_draft_items(
                recording_id,
                content_type,
                source_revision_id,
                list(items),
            )
        del source_revision
        timestamp = _now()
        draft = PipelineReferenceDraft(
            recording_id=recording_id,
            content_type=content_type,
            revision=0,
            source_revision_id=source_revision_id,
            items=items,
            coverage=None,
            impact=(),
            updated_at=timestamp,
        )
        state = PipelineReferenceState(
            recording_id=recording_id,
            content_type=content_type,
            draft_revision=0,
            draft_state="draft",
            source_revision_id=source_revision_id,
            selected_completed_revision_id=None,
            updated_at=timestamp,
        )
        created = StoredPipelineReference(state=state, draft=draft)
        with self.reference_store.locked(recording_id, content_type):
            try:
                current = self.reference_store.read_locked(recording_id, content_type)
            except PipelineReferenceNotFound:
                current = None
            if current is not None:
                raise PipelineReferenceConflict("a maintained reference already exists", current)
            return self.reference_store.write_locked(created)

    def update_draft(
        self,
        recording_id: str,
        content_type: str,
        payload: Mapping[str, Any],
    ) -> StoredPipelineReference:
        self._validate_content_type(content_type)
        if not isinstance(payload, Mapping):
            raise PipelineReferenceInputError("the reference edit request must be an object")
        unknown = set(payload) - {
            "expected_revision",
            "operator_id",
            "command_id",
            "operations",
            "operation",
            "item_id",
            "item",
            "source_revision_id",
        }
        if unknown:
            raise PipelineReferenceInputError(
                f"the reference edit request has unknown fields: {', '.join(sorted(unknown))}"
            )
        expected = _expected_revision(payload.get("expected_revision"))
        _identifier(payload.get("operator_id"), "operator_id")
        command_id = payload.get("command_id")
        if command_id is not None:
            command_id = _identifier(command_id, "command_id")
        command_digest = _command_digest(payload) if command_id is not None else None
        operations_value = payload.get("operations")
        requested_source_revision_id = payload.get("source_revision_id")
        if requested_source_revision_id is not None:
            requested_source_revision_id = _identifier(
                requested_source_revision_id, "source_revision_id"
            )
        if operations_value is None and "operation" in payload:
            operations_value = [
                {
                    key: value
                    for key, value in payload.items()
                    if key in {"operation", "item_id", "item", "decision", "source_revision_id"}
                }
            ]
        if requested_source_revision_id is not None:
            rebase_operation = {
                "operation": "rebase",
                "source_revision_id": requested_source_revision_id,
            }
            has_rebase = isinstance(operations_value, list) and any(
                isinstance(operation, Mapping) and operation.get("operation") == "rebase"
                for operation in operations_value
            )
            if not has_rebase:
                operations_value = [rebase_operation, *(operations_value or [])]
        if not isinstance(operations_value, list) or not operations_value:
            raise PipelineReferenceInputError("operations must be a non-empty list")
        try:
            operations = tuple(
                PipelineReferenceOperation.from_mapping(item, f"operations[{index}]")
                for index, item in enumerate(operations_value)
            )
        except PipelineReferenceContractError as error:
            raise PipelineReferenceInputError(str(error)) from error

        with self.reference_store.locked(recording_id, content_type):
            current = self.reference_store.read_locked(recording_id, content_type)
            if command_id is not None and command_digest is not None:
                commands = self.reference_store.read_commands_locked(recording_id, content_type)
                previous_digest = commands.get(command_id)
                if previous_digest is not None:
                    if previous_digest != command_digest:
                        raise PipelineReferenceInputError(
                            "command_id was already used with different operation bytes"
                        )
                    return current
            if current.state.draft_revision != expected:
                raise PipelineReferenceConflict(
                    "the maintained reference draft changed; reload the current revision",
                    current,
                )
            items = list(current.draft.items)
            impacts = list(current.draft.impact)
            working_current = current
            for operation in operations:
                if operation.operation == "rebase":
                    assert operation.source_revision_id is not None
                    items = self._rebase_items(
                        recording_id,
                        content_type,
                        working_current,
                        operation.source_revision_id,
                    )
                    working_current = replace(
                        working_current,
                        draft=replace(
                            working_current.draft,
                            source_revision_id=operation.source_revision_id,
                        ),
                    )
                    continue
                previous_item = None
                if operation.operation == "correct":
                    assert operation.item_id is not None
                    previous_index = self._find_item(items, operation.item_id)
                    if previous_index is not None:
                        previous_item = items[previous_index]
                items = self._apply_operation(content_type, items, operation, working_current)
                if operation.operation == "correct" and previous_item is not None:
                    corrected_item = next(
                        item for item in items if item.base_item_id == previous_item.item_id
                    )
                    impacts.extend(
                        self._correction_impact(
                            recording_id,
                            content_type,
                            previous_item,
                            corrected_item,
                        )
                    )
            self._validate_draft_items(
                recording_id,
                content_type,
                working_current.draft.source_revision_id,
                items,
            )
            timestamp = _now()
            draft = replace(
                current.draft,
                revision=current.draft.revision + 1,
                source_revision_id=working_current.draft.source_revision_id,
                items=tuple(items),
                coverage=None,
                impact=tuple(impacts),
                updated_at=timestamp,
            )
            state = replace(
                current.state,
                draft_revision=draft.revision,
                draft_state="draft",
                source_revision_id=draft.source_revision_id,
                updated_at=timestamp,
            )
            saved = self.reference_store.write_locked(
                StoredPipelineReference(state=state, draft=draft)
            )
            if command_id is not None and command_digest is not None:
                commands = self.reference_store.read_commands_locked(recording_id, content_type)
                commands[command_id] = command_digest
                self.reference_store.write_commands_locked(recording_id, content_type, commands)
            return saved

    def complete_reference(
        self,
        recording_id: str,
        content_type: str,
        payload: Mapping[str, Any],
    ) -> StoredPipelineReference:
        self._validate_content_type(content_type)
        if not isinstance(payload, Mapping):
            raise PipelineReferenceInputError("the reference completion request must be an object")
        unknown = set(payload) - {"expected_revision", "operator_id", "coverage"}
        if unknown:
            raise PipelineReferenceInputError(
                "the reference completion request has unknown fields: " + ", ".join(sorted(unknown))
            )
        expected = _expected_revision(payload.get("expected_revision"))
        operator_id = _identifier(payload.get("operator_id"), "operator_id")
        with self.reference_store.locked(recording_id, content_type):
            current = self.reference_store.read_locked(recording_id, content_type)
            if current.state.draft_revision != expected:
                raise PipelineReferenceConflict(
                    "the maintained reference draft changed; reload the current revision",
                    current,
                )
            if current.state.draft_state == "completed":
                raise PipelineReferenceConflict(
                    "the maintained reference is already complete; edit it before completing again",
                    current,
                )
            source_revision = (
                None
                if current.draft.source_revision_id is None
                else self._require_source_revision(
                    recording_id, content_type, current.draft.source_revision_id
                )
            )
            source = self._source_for(recording_id, current.draft.source_revision_id)
            coverage = self._validate_coverage(
                content_type,
                payload.get("coverage"),
                current.draft.items,
                source,
            )
            active_items = [item for item in current.draft.items if item.review_state != "rejected"]
            content = self._human_content(content_type, active_items)
            content_bytes = self._canonical_content_bytes(content_type, content)
            content_sha256 = sha256_bytes(content_bytes)
            origin = "manual" if source_revision is None else "corrected"
            input_revision_ids = (
                () if source_revision is None else (source_revision.manifest.revision_id,)
            )
            base_revision_id = (
                None if source_revision is None else source_revision.manifest.revision_id
            )
            revision_id = self._revision_id(
                recording_id,
                content_type,
                content_sha256,
                base_revision_id,
            )
            manifest = DataRevision(
                revision_id=revision_id,
                content_type=content_type,
                content_schema=self._content_schema(content_type),
                recording_id=recording_id,
                source=source,
                content_sha256=content_sha256,
                input_revision_ids=input_revision_ids,
                origin=origin,
                producer=HumanProducer(
                    review_id=f"reference-{recording_id}-{content_type}",
                    operator_id=operator_id,
                    base_revision_id=base_revision_id,
                ),
                coverage={**coverage, "impact": list(current.draft.impact)},
                created_at=_now(),
            )
            self.revision_store.publish(manifest, content_bytes)
            selected = self._select_completed(recording_id, content_type, revision_id)
            del selected
            timestamp = _now()
            completed_draft = replace(
                current.draft,
                source_revision_id=revision_id,
                items=tuple(
                    replace(item, item=self._human_item(content_type, item.item))
                    if item.review_state != "rejected"
                    else item
                    for item in current.draft.items
                ),
                coverage={**coverage, "impact": list(current.draft.impact)},
                updated_at=timestamp,
            )
            completed_state = replace(
                current.state,
                draft_state="completed",
                source_revision_id=revision_id,
                selected_completed_revision_id=revision_id,
                updated_at=timestamp,
            )
            return self.reference_store.write_locked(
                StoredPipelineReference(state=completed_state, draft=completed_draft)
            )

    def _apply_operation(
        self,
        content_type: str,
        items: list[ReferenceDraftItem],
        operation: PipelineReferenceOperation,
        current: StoredPipelineReference,
    ) -> list[ReferenceDraftItem]:
        if operation.operation in {"accept", "reject", "decide"}:
            assert operation.item_id is not None
            index = self._find_item(items, operation.item_id)
            if index is None:
                raise PipelineReferenceInputError(f"item was not found: {operation.item_id}")
            if operation.operation == "decide":
                assert operation.decision is not None
                decision = operation.decision
                if decision == "accepted":
                    state = (
                        "corrected"
                        if items[index].base_item_id is not None
                        else "added"
                        if items[index].review_state == "added"
                        else "accepted"
                    )
                elif decision == "rejected":
                    state = "rejected"
                else:
                    state = decision
            else:
                state = "accepted" if operation.operation == "accept" else "rejected"
                if operation.operation == "accept" and items[index].base_item_id is not None:
                    state = "corrected"
            return (
                items[:index]
                + [
                    replace(
                        items[index],
                        review_state=state,
                    )
                ]
                + items[index + 1 :]
            )

        assert operation.item is not None
        item_id = self._item_id(content_type, operation.item)
        self._validate_item(content_type, operation.item, current.draft.source_revision_id)
        if operation.operation == "add":
            if self._find_item(items, item_id) is not None:
                raise PipelineReferenceInputError(f"item already exists: {item_id}")
            return [
                *items,
                ReferenceDraftItem(
                    item_id=item_id,
                    base_item_id=None,
                    review_state="added",
                    item=operation.item,
                ),
            ]

        assert operation.item_id is not None
        index = self._find_item(items, operation.item_id)
        if index is None:
            raise PipelineReferenceInputError(f"item was not found: {operation.item_id}")
        if item_id != operation.item_id and self._find_item(items, item_id) is not None:
            raise PipelineReferenceInputError(f"item already exists: {item_id}")
        return (
            items[:index]
            + [
                ReferenceDraftItem(
                    item_id=item_id,
                    base_item_id=operation.item_id,
                    review_state="corrected",
                    item=operation.item,
                )
            ]
            + items[index + 1 :]
        )

    def _rebase_items(
        self,
        recording_id: str,
        content_type: str,
        current: StoredPipelineReference,
        source_revision_id: str,
    ) -> list[ReferenceDraftItem]:
        source_revision = self._require_source_revision(
            recording_id, content_type, source_revision_id
        )
        new_items = self._content_items(content_type, source_revision)
        previous_items = list(current.draft.items)
        rebased: list[ReferenceDraftItem] = []
        for raw_item in new_items:
            previous = next(
                (
                    item
                    for item in previous_items
                    if self._rebase_match(content_type, item.item, raw_item, item)
                ),
                None,
            )
            if previous is None:
                state = "affected" if previous_items else "pending"
                base_item_id = None
            else:
                state = previous.review_state
                base_item_id = previous.base_item_id
            rebased.append(
                ReferenceDraftItem(
                    item_id=self._item_id(content_type, raw_item),
                    base_item_id=base_item_id,
                    review_state=state,
                    item=dict(raw_item),
                )
            )
        return rebased

    @staticmethod
    def _rebase_match(
        content_type: str,
        previous: Mapping[str, Any],
        current: Mapping[str, Any],
        previous_draft: ReferenceDraftItem,
    ) -> bool:
        if content_type == "events":
            lineage = {previous_draft.item_id, previous_draft.base_item_id}
            return (
                current.get("event_id") in lineage
                and previous.get("event_type") == current.get("event_type")
                and previous.get("start_us") == current.get("start_us")
                and previous.get("end_us") == current.get("end_us")
            )
        if content_type == "visible_cards":
            return previous.get("event_id") == current.get(
                "event_id"
            ) and PipelineReferenceService._same_json(
                previous.get("frame_identity"), current.get("frame_identity")
            )
        previous_crop = previous.get("crop_identity")
        current_crop = current.get("crop_identity")
        return (
            previous.get("card_id") == current.get("card_id")
            and PipelineReferenceService._same_json(
                previous.get("frame_identity"), current.get("frame_identity")
            )
            and PipelineReferenceService._same_json(
                previous.get("geometry"), current.get("geometry")
            )
            and isinstance(previous_crop, Mapping)
            and isinstance(current_crop, Mapping)
            and previous_crop.get("crop_policy") == current_crop.get("crop_policy")
            and previous_crop.get("image_sha256") == current_crop.get("image_sha256")
        )

    @staticmethod
    def _same_json(left: Any, right: Any) -> bool:
        return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
            right, sort_keys=True, separators=(",", ":")
        )

    def _validate_coverage(
        self,
        content_type: str,
        raw_coverage: Any,
        items: tuple[ReferenceDraftItem, ...],
        source: RecordingVideoSource,
    ) -> dict[str, Any]:
        if not isinstance(raw_coverage, Mapping):
            raise PipelineReferenceCoverageError(
                "reference completion needs an explicit coverage object",
                [{"field": "coverage", "message": "declare the reviewed scope before completion"}],
            )
        unknown = set(raw_coverage) - {"kind", "item_ids", "intervals", "frames", "cards"}
        if unknown:
            raise PipelineReferenceInputError(
                "reference coverage has unknown fields: " + ", ".join(sorted(unknown))
            )
        kind = raw_coverage.get("kind")
        if not isinstance(kind, str):
            raise PipelineReferenceInputError("coverage.kind must be a non-empty string")
        kind_aliases = {
            "events": {"full_recording", "full-recording", "event_intervals", "intervals"},
            "visible_cards": {"visible_frames", "visible-card-frames", "frames"},
            "visual_identities": {
                "visual_identities",
                "visual-card-identities",
                "visible_cards",
            },
        }
        if kind not in kind_aliases[content_type]:
            raise PipelineReferenceCoverageError(
                f"coverage.kind does not describe {content_type} coverage",
                [
                    {
                        "field": "coverage.kind",
                        "message": f"use one of: {', '.join(sorted(kind_aliases[content_type]))}",
                    }
                ],
            )
        if content_type == "events":
            return self._event_coverage(raw_coverage, items, source)
        if content_type == "visible_cards":
            return self._visible_card_coverage(raw_coverage, items)
        return self._identity_coverage(raw_coverage, items, source.recording_id)

    def _event_coverage(
        self,
        raw_coverage: Mapping[str, Any],
        items: tuple[ReferenceDraftItem, ...],
        source: RecordingVideoSource,
    ) -> dict[str, Any]:
        raw_intervals = raw_coverage.get("intervals")
        if raw_intervals is None:
            if raw_coverage["kind"] in {"full_recording", "full-recording"}:
                raw_intervals = [{"start_us": 0, "end_us": source.duration_us}]
            else:
                raise PipelineReferenceCoverageError(
                    "event coverage needs reviewed video intervals",
                    [{"field": "coverage.intervals", "message": "declare one or more intervals"}],
                )
        if not isinstance(raw_intervals, list):
            raise PipelineReferenceInputError("coverage.intervals must be a list")
        intervals: list[dict[str, int]] = []
        for index, raw_interval in enumerate(raw_intervals):
            if not isinstance(raw_interval, Mapping) or set(raw_interval) != {
                "start_us",
                "end_us",
            }:
                raise PipelineReferenceInputError(
                    f"coverage.intervals[{index}] must contain start_us and end_us"
                )
            start_us = self._coverage_time(
                raw_interval["start_us"], f"coverage.intervals[{index}].start_us"
            )
            end_us = self._coverage_time(
                raw_interval["end_us"], f"coverage.intervals[{index}].end_us"
            )
            if start_us >= end_us or end_us > source.duration_us:
                raise PipelineReferenceInputError(
                    f"coverage.intervals[{index}] must be inside the recording video"
                )
            intervals.append({"start_us": start_us, "end_us": end_us})
        intervals.sort(key=lambda interval: (interval["start_us"], interval["end_us"]))
        merged: list[dict[str, int]] = []
        for interval in intervals:
            if merged and interval["start_us"] <= merged[-1]["end_us"]:
                merged[-1]["end_us"] = max(merged[-1]["end_us"], interval["end_us"])
            else:
                merged.append(dict(interval))
        details = [
            {
                "field": f"items.{item.item_id}",
                "message": self._coverage_missing_message("events", item),
            }
            for item in items
            if item.review_state not in {"accepted", "rejected", "added", "corrected"}
        ]
        cursor = 0
        for interval in merged:
            if interval["start_us"] > cursor:
                details.append(
                    {
                        "field": "coverage.intervals",
                        "message": f"missing coverage interval: [{cursor}, {interval['start_us']}]",
                    }
                )
            cursor = max(cursor, interval["end_us"])
        if cursor < source.duration_us:
            details.append(
                {
                    "field": "coverage.intervals",
                    "message": f"missing coverage interval: [{cursor}, {source.duration_us}]",
                }
            )
        if details:
            raise PipelineReferenceCoverageError("event reference coverage is incomplete", details)
        return {
            "schema_version": PIPELINE_REFERENCE_COVERAGE_SCHEMA_VERSION,
            "kind": "event_intervals",
            "intervals": merged,
            "reviewed_item_ids": [item.item_id for item in items],
            "source_duration_us": source.duration_us,
        }

    @staticmethod
    def _coverage_time(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PipelineReferenceInputError(f"{field} must be a non-negative integer")
        return value

    def _visible_card_coverage(
        self,
        raw_coverage: Mapping[str, Any],
        items: tuple[ReferenceDraftItem, ...],
    ) -> dict[str, Any]:
        raw_frames = raw_coverage.get("frames")
        if not isinstance(raw_frames, list) or not raw_frames:
            raise PipelineReferenceCoverageError(
                "visible-card coverage needs reviewed resolved frames",
                [
                    {
                        "field": "coverage.frames",
                        "message": "declare cards, empty, or unusable for every resolved frame",
                    }
                ],
            )
        normalized_frames = self._frame_coverage_entries(raw_frames)
        by_key = {self._frame_coverage_key(entry): entry for entry in normalized_frames}
        details: list[dict[str, str]] = []
        for item in items:
            frame_key = self._item_frame_key(item)
            entry = by_key.get(frame_key)
            if entry is None:
                details.append(
                    {
                        "field": "coverage.frames",
                        "message": f"missing scope: frame for {item.item_id}",
                    }
                )
                continue
            expected_decision = {
                "detected": "cards",
                "empty": "empty",
                "failed": "unusable",
            }.get(item.item.get("status"))
            if expected_decision != entry["decision"] or not self._visible_coverage_state(
                item.item, item.review_state
            ):
                details.append(
                    {
                        "field": f"items.{item.item_id}",
                        "message": self._coverage_missing_message("visible_cards", item),
                    }
                )
        if details:
            raise PipelineReferenceCoverageError(
                "visible-card reference coverage is incomplete", details
            )
        return {
            "schema_version": PIPELINE_REFERENCE_COVERAGE_SCHEMA_VERSION,
            "kind": "visible_frames",
            "frames": normalized_frames,
        }

    def _identity_coverage(
        self,
        raw_coverage: Mapping[str, Any],
        items: tuple[ReferenceDraftItem, ...],
        recording_id: str,
    ) -> dict[str, Any]:
        raw_cards = raw_coverage.get("cards")
        if not isinstance(raw_cards, list) or not raw_cards:
            raise PipelineReferenceCoverageError(
                "identity coverage needs a decision for every upstream visible card",
                [
                    {
                        "field": "coverage.cards",
                        "message": "declare identity or unusable for every card",
                    }
                ],
            )
        cards: list[dict[str, str]] = []
        for index, raw_card in enumerate(raw_cards):
            if not isinstance(raw_card, Mapping) or set(raw_card) != {"card_id", "decision"}:
                raise PipelineReferenceInputError(
                    f"coverage.cards[{index}] must contain card_id and decision"
                )
            card_id = _identifier(raw_card["card_id"], f"coverage.cards[{index}].card_id")
            decision = raw_card["decision"]
            if decision not in {"identity", "unusable"}:
                raise PipelineReferenceInputError(
                    f"coverage.cards[{index}].decision must be identity or unusable"
                )
            cards.append({"card_id": card_id, "decision": decision})
        if len({card["card_id"] for card in cards}) != len(cards):
            raise PipelineReferenceInputError("coverage.cards must contain unique card IDs")
        expected_ids = self._identity_scope_ids(recording_id, items)
        declared_ids = {card["card_id"] for card in cards}
        details = [
            {"field": "coverage.cards", "message": f"missing scope: {card_id}"}
            for card_id in sorted(expected_ids - declared_ids)
        ]
        details.extend(
            {"field": "coverage.cards", "message": f"unknown scope: {card_id}"}
            for card_id in sorted(declared_ids - expected_ids)
        )
        by_id = {card["card_id"]: card for card in cards}
        for item in items:
            entry = by_id.get(item.item_id)
            if entry is None:
                continue
            expected_decision = (
                "identity" if item.item.get("status") == "classified" else "unusable"
            )
            if expected_decision != entry["decision"] or not self._identity_coverage_state(
                item.item, item.review_state
            ):
                details.append(
                    {
                        "field": f"items.{item.item_id}",
                        "message": self._coverage_missing_message("visual_identities", item),
                    }
                )
        for card_id in sorted(expected_ids - set(item.item_id for item in items)):
            if by_id[card_id]["decision"] != "unusable":
                details.append(
                    {
                        "field": f"coverage.cards.{card_id}",
                        "message": "upstream card has no identity result; mark it unusable",
                    }
                )
        if details:
            raise PipelineReferenceCoverageError(
                "visual identity reference coverage is incomplete", details
            )
        return {
            "schema_version": PIPELINE_REFERENCE_COVERAGE_SCHEMA_VERSION,
            "kind": "visual_identities",
            "cards": cards,
            "recording_id": recording_id,
        }

    def _identity_scope_ids(
        self, recording_id: str, items: tuple[ReferenceDraftItem, ...]
    ) -> set[str]:
        visible = self._selected_revision(recording_id, "visible_cards")
        if visible is None:
            return {item.item_id for item in items}
        card_ids = {
            candidate.get("card_id")
            for item in self._content_items("visible_cards", visible)
            if item.get("status") == "detected"
            for candidate in item.get("candidates", [])
            if isinstance(candidate, Mapping) and isinstance(candidate.get("card_id"), str)
        }
        return {str(card_id) for card_id in card_ids} | {item.item_id for item in items}

    @staticmethod
    def _frame_coverage_entries(raw_frames: list[Any]) -> list[dict[str, Any]]:
        from table_evidence_analyzer.pipeline_data import VisibleCardFrameIdentity

        normalized: list[dict[str, Any]] = []
        for index, raw_frame in enumerate(raw_frames):
            if not isinstance(raw_frame, Mapping):
                raise PipelineReferenceInputError(f"coverage.frames[{index}] must be an object")
            if set(raw_frame) not in (
                {"frame_identity", "decision"},
                {"item_id", "frame_identity", "decision"},
            ):
                raise PipelineReferenceInputError(
                    f"coverage.frames[{index}] must contain frame_identity and decision"
                )
            frame_identity = raw_frame["frame_identity"]
            if frame_identity is None:
                if "item_id" not in raw_frame:
                    raise PipelineReferenceInputError(
                        f"coverage.frames[{index}] needs item_id when frame_identity is absent"
                    )
                normalized_frame = None
            else:
                try:
                    normalized_frame = VisibleCardFrameIdentity.from_mapping(
                        frame_identity
                    ).to_mapping()
                except (PipelineDataError, TypeError, ValueError) as error:
                    raise PipelineReferenceInputError(
                        f"coverage.frames[{index}].frame_identity is invalid"
                    ) from error
            decision = raw_frame["decision"]
            if decision not in {"cards", "empty", "unusable"}:
                raise PipelineReferenceInputError(
                    f"coverage.frames[{index}].decision must be cards, empty, or unusable"
                )
            entry = {"frame_identity": normalized_frame, "decision": decision}
            if "item_id" in raw_frame:
                entry["item_id"] = _identifier(
                    raw_frame["item_id"], f"coverage.frames[{index}].item_id"
                )
            normalized.append(entry)
        if len({json.dumps(entry, sort_keys=True) for entry in normalized}) != len(normalized):
            raise PipelineReferenceInputError("coverage.frames must contain unique frames")
        return normalized

    @staticmethod
    def _frame_coverage_key(entry: Mapping[str, Any]) -> str:
        if entry.get("frame_identity") is None:
            return f"item:{entry.get('item_id')}"
        return json.dumps(entry["frame_identity"], sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _item_frame_key(item: ReferenceDraftItem) -> str:
        frame = item.item.get("frame_identity")
        if frame is None:
            return f"item:{item.item_id}"
        return json.dumps(frame, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _visible_coverage_state(item: Mapping[str, Any], state: str) -> bool:
        status = item.get("status")
        if status == "detected":
            return state in {"accepted", "added", "corrected"}
        if status == "empty":
            return state == "empty"
        if status == "failed":
            return state in {"unusable", "source_problem"}
        return False

    @staticmethod
    def _identity_coverage_state(item: Mapping[str, Any], state: str) -> bool:
        status = item.get("status")
        if status == "classified":
            candidates = item.get("candidates")
            return (
                state in {"accepted", "added", "corrected"}
                and isinstance(candidates, list)
                and bool(candidates)
            )
        if status == "unusable":
            return state in {"unusable", "identity_unusable"}
        if status == "failed":
            return state == "source_problem"
        return False

    @staticmethod
    def _coverage_missing_message(content_type: str, item: ReferenceDraftItem) -> str:
        if item.review_state == "affected":
            return "evidence changed; review this item again before completion"
        if item.review_state == "pending":
            return "missing explicit review decision"
        if content_type == "visible_cards":
            status = item.item.get("status")
            if status == "empty":
                return "empty frame needs an explicit empty decision"
            if status == "failed":
                return "failed frame needs an explicit unusable or source_problem decision"
            return "positive frame needs an accept, add, or correct decision"
        if content_type == "visual_identities":
            status = item.item.get("status")
            if status == "unusable":
                return "unusable card needs an explicit unusable or identity_unusable decision"
            if status == "failed":
                return "failed card needs an explicit source_problem decision"
            return "card needs an accepted identity or a correct decision"
        return "event needs an explicit review decision"

    def _correction_impact(
        self,
        recording_id: str,
        content_type: str,
        previous: ReferenceDraftItem,
        corrected: ReferenceDraftItem,
    ) -> tuple[dict[str, Any], ...]:
        impact: list[dict[str, Any]] = []
        if content_type == "events":
            event_ids = {previous.item_id, corrected.item_id}
            visible = self._selected_revision(recording_id, "visible_cards")
            if visible is not None:
                visible_items = self._content_items("visible_cards", visible)
                affected_visible = [
                    item["event_id"] for item in visible_items if item.get("event_id") in event_ids
                ]
                if affected_visible:
                    impact.append(
                        self._impact_entry(
                            content_type,
                            previous.item_id,
                            "visible_cards",
                            affected_visible,
                            "event evidence changed; review its visible-card frame again",
                        )
                    )
                card_ids = {
                    candidate.get("card_id")
                    for item in visible_items
                    if item.get("event_id") in event_ids
                    for candidate in item.get("candidates", [])
                    if isinstance(candidate, Mapping) and isinstance(candidate.get("card_id"), str)
                }
                identities = self._selected_revision(recording_id, "visual_identities")
                if identities is not None and card_ids:
                    affected_identity = [
                        item["card_id"]
                        for item in self._content_items("visual_identities", identities)
                        if item.get("card_id") in card_ids
                    ]
                    if affected_identity:
                        impact.append(
                            self._impact_entry(
                                content_type,
                                previous.item_id,
                                "visual_identities",
                                affected_identity,
                                "event evidence changed; review its downstream identity crop again",
                            )
                        )
        elif content_type == "visible_cards":
            card_ids = {
                candidate.get("card_id")
                for item in (previous.item, corrected.item)
                for candidate in item.get("candidates", [])
                if isinstance(candidate, Mapping) and isinstance(candidate.get("card_id"), str)
            }
            identities = self._selected_revision(recording_id, "visual_identities")
            if identities is not None and card_ids:
                affected_identity = [
                    item["card_id"]
                    for item in self._content_items("visual_identities", identities)
                    if item.get("card_id") in card_ids
                ]
                if affected_identity:
                    impact.append(
                        self._impact_entry(
                            content_type,
                            previous.item_id,
                            "visual_identities",
                            affected_identity,
                            "visible-card evidence changed; review its downstream identity again",
                        )
                    )
        return tuple(impact)

    def _selected_revision(
        self, recording_id: str, content_type: str
    ) -> StoredPipelineRevision | None:
        selection = self.selection_store.get(recording_id, content_type)
        if selection is None:
            return None
        revision_id = (
            selection.selected_completed_reference_revision_id
            or selection.selected_generated_revision_id
        )
        return None if revision_id is None else self.revision_store.get(revision_id)

    @staticmethod
    def _impact_entry(
        source_content_type: str,
        source_item_id: str,
        downstream_content_type: str,
        affected_item_ids: list[str],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_REFERENCE_IMPACT_SCHEMA_VERSION,
            "source_content_type": source_content_type,
            "source_item_id": source_item_id,
            "downstream_content_type": downstream_content_type,
            "affected_item_ids": sorted(set(affected_item_ids)),
            "reason": reason,
            "re_review_required": True,
        }

    @staticmethod
    def _find_item(items: list[ReferenceDraftItem], item_id: str) -> int | None:
        return next((index for index, item in enumerate(items) if item.item_id == item_id), None)

    def _validate_draft_items(
        self,
        recording_id: str,
        content_type: str,
        source_revision_id: str | None,
        items: list[ReferenceDraftItem],
    ) -> None:
        if len({item.item_id for item in items}) != len(items):
            raise PipelineReferenceInputError("reference item IDs must be unique")
        for item in items:
            if item.item_id != self._item_id(content_type, item.item):
                raise PipelineReferenceInputError(
                    f"reference item ID does not match its {content_type} content"
                )
            self._validate_item(content_type, item.item, source_revision_id, recording_id)

    def _validate_item(
        self,
        content_type: str,
        item: Mapping[str, Any],
        source_revision_id: str | None,
        recording_id: str | None = None,
    ) -> None:
        try:
            source = self._source_for(recording_id, source_revision_id) if recording_id else None
            self._parse_item(content_type, item, source)
            if source is not None:
                self._validate_source_lineage(content_type, item, source)
        except (PipelineDataError, PipelineReferenceError, TypeError, ValueError) as error:
            if isinstance(error, PipelineReferenceInputError):
                raise
            raise PipelineReferenceInputError("reference item failed content validation") from error

    @staticmethod
    def _validate_source_lineage(
        content_type: str,
        item: Mapping[str, Any],
        source: RecordingVideoSource,
    ) -> None:
        if content_type == "events":
            return
        frame = item.get("frame_identity")
        if (
            not isinstance(frame, Mapping)
            or frame.get("source_video_sha256") != source.video_sha256
        ):
            raise PipelineReferenceInputError(
                "reference item does not belong to the recording video"
            )

    def _content_items(
        self, content_type: str, revision: StoredPipelineRevision
    ) -> tuple[dict[str, Any], ...]:
        content = revision.content.to_mapping()
        key = {
            "events": "events",
            "visible_cards": "outcomes",
            "visual_identities": "outcomes",
        }[content_type]
        return tuple(dict(item) for item in content[key])

    def _human_content(self, content_type: str, items: list[ReferenceDraftItem]) -> dict[str, Any]:
        key = {
            "events": "events",
            "visible_cards": "outcomes",
            "visual_identities": "outcomes",
        }[content_type]
        return {
            "schema_version": self._content_schema(content_type),
            key: [self._human_item(content_type, item.item) for item in items],
        }

    @staticmethod
    def _human_item(content_type: str, item: Mapping[str, Any]) -> dict[str, Any]:
        value = json.loads(json.dumps(item))
        if content_type == "events":
            value.pop("model_scores", None)
        elif content_type == "visible_cards":
            for candidate in value.get("candidates", []):
                candidate.pop("model_scores", None)
        else:
            classifier = value.get("classifier")
            if isinstance(classifier, Mapping):
                value["classifier"] = {
                    "provider": "human-reference",
                    "implementation": {"name": "maintained-reference", "version": "v1"},
                    "model": {"name": "human-decision", "version": "v1"},
                }
            candidates = value.get("candidates", [])
            if candidates:
                selected = dict(candidates[0])
                selected["score"] = None
                selected["score_meaning"] = None
                selected["producer_id"] = "human-reference.v1"
                value["candidates"] = [selected]
        return value

    def _parse_item(
        self,
        content_type: str,
        item: Mapping[str, Any],
        source: RecordingVideoSource | None,
    ) -> object:
        if content_type == "events":
            from doko_operations.pipeline_data import EventData

            return EventData.from_mapping(
                {"schema_version": "event-data/v1", "events": [item]},
                duration_us=source.duration_us if source else 2**63 - 1,
            )
        if content_type == "visible_cards":
            return VisibleCardData.from_mapping(
                {"schema_version": "visible-card-data/v1", "outcomes": [item]}
            )
        return VisualIdentityData.from_mapping(
            {"schema_version": "visual-identity-data/v1", "outcomes": [item]}
        )

    def _require_source_revision(
        self, recording_id: str, content_type: str, revision_id: str
    ) -> StoredPipelineRevision:
        try:
            revision = self.revision_store.require(revision_id)
        except PipelineNotFound as error:
            raise PipelineReferenceInputError("source revision was not found") from error
        manifest = revision.manifest
        if (
            manifest.recording_id != recording_id
            or manifest.content_type != content_type
            or not isinstance(manifest.source, RecordingVideoSource)
        ):
            raise PipelineReferenceInputError("source revision does not match this reference")
        return revision

    def _source_for(
        self, recording_id: str, source_revision_id: str | None
    ) -> RecordingVideoSource:
        if source_revision_id is not None:
            try:
                revision = self.revision_store.require(source_revision_id)
            except PipelineNotFound as error:
                raise PipelineReferenceInputError("source revision was not found") from error
            if revision.manifest.recording_id != recording_id or not isinstance(
                revision.manifest.source, RecordingVideoSource
            ):
                raise PipelineReferenceInputError("source revision does not match this recording")
            return revision.manifest.source
        bundle = self.recording_store.get(recording_id)
        if bundle is None:
            raise PipelineNotFound(f"The recording was not found: {recording_id}")
        bundle_path = self.repository_storage.bundle_path(recording_id)
        try:
            manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
            relative_video = str(manifest["files"]["video"]["relative_path"])
            video_path = bundle_path / relative_video
            if not video_path.is_file():
                raise OSError("video is unavailable")
            digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
            probe = probe_video_path_metadata(video_path)
            relative_path = (
                video_path.resolve().relative_to(self.settings.repository_root).as_posix()
            )
        except (KeyError, OSError, TypeError, ValueError, VideoProbeError) as error:
            raise PipelineReferenceInputError(
                "the accepted recording video is unavailable"
            ) from error
        if digest != bundle.source_sha256:
            raise PipelineReferenceInputError(
                "the accepted recording video does not match its manifest"
            )
        return RecordingVideoSource(
            recording_id=recording_id,
            relative_path=relative_path,
            video_sha256=digest,
            byte_length=video_path.stat().st_size,
            duration_us=probe.duration_ms * 1000,
        )

    def _select_completed(self, recording_id: str, content_type: str, revision_id: str) -> object:
        for _ in range(5):
            current = self.selection_store.get(recording_id, content_type)
            try:
                return self.selection_store.update_pointers(
                    recording_id,
                    content_type,
                    expected_revision=0 if current is None else current.revision,
                    selected_generated_revision_id=(
                        None if current is None else current.selected_generated_revision_id
                    ),
                    selected_completed_reference_revision_id=revision_id,
                )
            except PipelineSelectionConflict:
                continue
        raise PipelineReferenceError("the completed reference could not update its selection")

    @staticmethod
    def _validate_content_type(content_type: str) -> None:
        if content_type not in PIPELINE_REFERENCE_CONTENT_TYPES:
            raise PipelineReferenceInputError("content_type is not referenceable")

    @staticmethod
    def _item_id(content_type: str, item: Mapping[str, Any]) -> str:
        field = _ITEM_FIELDS[content_type]
        value = item.get(field)
        return _identifier(value, f"item.{field}")

    @staticmethod
    def _content_schema(content_type: str) -> str:
        return {
            "events": "event-data/v1",
            "visible_cards": "visible-card-data/v1",
            "visual_identities": "visual-identity-data/v1",
        }[content_type]

    @staticmethod
    def _canonical_content_bytes(content_type: str, content: Mapping[str, Any]) -> bytes:
        try:
            if content_type == "events":
                from doko_operations.pipeline_data import EventData

                return canonical_event_data_bytes(EventData.from_mapping(content))
            if content_type == "visible_cards":
                return canonical_visible_card_data_bytes(VisibleCardData.from_mapping(content))
            return canonical_visual_identity_data_bytes(VisualIdentityData.from_mapping(content))
        except (PipelineDataError, PipelineReferenceContractError, TypeError, ValueError) as error:
            raise PipelineReferenceInputError(
                "the completed reference content is invalid"
            ) from error

    @staticmethod
    def _revision_id(
        recording_id: str,
        content_type: str,
        content_sha256: str,
        base_revision_id: str | None,
    ) -> str:
        seed = f"{recording_id}:{content_type}:{content_sha256}:{base_revision_id or 'empty'}"
        suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
        return f"reference-{content_type}-{suffix}"

    def _validate_reference_revision(self, reference: StoredPipelineReference) -> None:
        if reference.state.selected_completed_revision_id is None:
            return
        try:
            revision = self.revision_store.require(reference.state.selected_completed_revision_id)
        except PipelineNotFound as error:
            raise PipelineReferenceStoreError(
                "the selected reference revision is unavailable"
            ) from error
        if (
            revision.manifest.recording_id != reference.state.recording_id
            or revision.manifest.content_type != reference.state.content_type
        ):
            raise PipelineReferenceStoreError(
                "the selected reference revision does not match the resource"
            )


__all__ = [
    "PipelineReferenceConflict",
    "PipelineReferenceCoverageError",
    "PipelineReferenceError",
    "PipelineReferenceInputError",
    "PipelineReferenceService",
]
