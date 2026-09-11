"""Create, edit, and complete maintained recording-pipeline references."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from doko_operations.pipeline_data import (
    DataRevision,
    HumanProducer,
    RecordingVideoSource,
    sha256_bytes,
)
from doko_operations.pipeline_reference import (
    PIPELINE_REFERENCE_CONTENT_TYPES,
    PipelineReferenceContractError,
    PipelineReferenceDraft,
    PipelineReferenceOperation,
    PipelineReferenceState,
    ReferenceDraftItem,
)
from table_evidence_analyzer.pipeline_data import VisibleCardData

from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceConflict,
    PipelineReferenceCoverageError,
    PipelineReferenceError,
    PipelineReferenceInputError,
    identifier,
)
from dokodetector_backend.pipeline_reference_handlers import (
    ReferenceContentHandler,
    build_reference_handlers,
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

_CONTENT_MUTATING_OPERATIONS = frozenset(
    {
        "add",
        "correct",
        "select_identity",
        "set_frame_review",
        "restore_frame_suggestions",
        "set_frame_empty",
        "set_frame_unusable",
        "set_identity_unusable",
        "report_identity_source_problem",
    }
)


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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
        # Pipeline revisions are immutable. Cache their source metadata because validating a
        # multi-item reference must not reparse the complete source revision for every item.
        self._source_revision_sources: dict[str, RecordingVideoSource] = {}
        self._handlers = build_reference_handlers(
            source_for=lambda recording_id, source_revision_id: self._source_for(
                recording_id, source_revision_id
            ),
            selected_revision=lambda recording_id, content_type: self._selected_revision(
                recording_id, content_type
            ),
        )

    def _handler(self, content_type: str) -> ReferenceContentHandler:
        self._validate_content_type(content_type)
        return self._handlers[content_type]

    def get_reference(self, recording_id: str, content_type: str) -> StoredPipelineReference:
        self._validate_content_type(content_type)
        reference = self.reference_store.get(recording_id, content_type)
        if reference is None:
            raise PipelineReferenceNotFound(
                f"The maintained reference was not found: {recording_id}/{content_type}"
            )
        if content_type == "visual_identities":
            reference = self._repair_face_down_reference(recording_id, reference)
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
        operator_id = identifier(payload.get("operator_id"), "operator_id")
        del operator_id
        existing = self.reference_store.get(recording_id, content_type)
        if existing is not None:
            raise PipelineReferenceConflict("a maintained reference already exists", existing)

        source_revision_id = payload.get("source_revision_id")
        if source_revision_id is not None:
            source_revision_id = identifier(source_revision_id, "source_revision_id")
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
                    item_id=self._handler(content_type).item_id(item),
                    base_item_id=None,
                    review_state="pending",
                    item=dict(item),
                )
                for item in self._handler(content_type).content_items(source_revision)
            )
            self._handler(content_type).validate_draft_items(
                recording_id,
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
        identifier(payload.get("operator_id"), "operator_id")
        command_id = payload.get("command_id")
        if command_id is not None:
            command_id = identifier(command_id, "command_id")
        command_digest = _command_digest(payload) if command_id is not None else None
        operations_value = payload.get("operations")
        requested_source_revision_id = payload.get("source_revision_id")
        if requested_source_revision_id is not None:
            requested_source_revision_id = identifier(
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
            handler = self._handler(content_type)
            current = self.reference_store.read_locked(recording_id, content_type)
            commands: dict[str, str] | None = None
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
            changed_item_ids: set[str] = set()
            requires_full_validation = False
            for operation in operations:
                if operation.operation == "rebase":
                    assert operation.source_revision_id is not None
                    items = handler.rebase_items(
                        recording_id,
                        working_current,
                        operation.source_revision_id,
                        self._require_source_revision,
                    )
                    working_current = replace(
                        working_current,
                        draft=replace(
                            working_current.draft,
                            source_revision_id=operation.source_revision_id,
                        ),
                    )
                    requires_full_validation = True
                    continue
                previous_item = None
                if operation.operation == "correct":
                    assert operation.item_id is not None
                    previous_index = handler.find_item(items, operation.item_id)
                    if previous_index is not None:
                        previous_item = items[previous_index]
                items = handler.apply_operation(
                    items,
                    operation,
                    working_current.draft.source_revision_id,
                )
                if operation.operation == "correct" and previous_item is not None:
                    corrected_item = next(
                        item for item in items if item.base_item_id == previous_item.item_id
                    )
                    impacts.extend(
                        handler.correction_impact(
                            recording_id,
                            previous_item,
                            corrected_item,
                        )
                    )
                if operation.operation in _CONTENT_MUTATING_OPERATIONS:
                    changed_item_id = (
                        handler.item_id(operation.item)
                        if operation.item is not None
                        else operation.item_id
                    )
                    if changed_item_id is not None:
                        changed_item_ids.add(changed_item_id)
            if requires_full_validation:
                handler.validate_draft_items(
                    recording_id,
                    working_current.draft.source_revision_id,
                    items,
                )
            else:
                for item_id in changed_item_ids:
                    index = handler.find_item(items, item_id)
                    if index is None:
                        raise PipelineReferenceInputError(f"item was not found: {item_id}")
                    handler.validate_item(
                        items[index].item,
                        working_current.draft.source_revision_id,
                        recording_id,
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
                assert commands is not None
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
        operator_id = identifier(payload.get("operator_id"), "operator_id")
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
            handler = self._handler(content_type)
            content = handler.human_content(active_items)
            content_bytes = handler.canonical_content_bytes(content)
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
                content_schema=handler.content_schema,
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
                    replace(item, item=handler.human_item(item.item))
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
        handler = self._handler(content_type)
        return handler.validate_coverage(raw_coverage, items, source, source.recording_id)

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

    def _repair_face_down_reference(
        self, recording_id: str, reference: StoredPipelineReference
    ) -> StoredPipelineReference:
        """Publish a current face-down correction without rewriting completed history."""

        if reference.state.draft_state != "completed":
            return reference
        visible = self._selected_revision(recording_id, "visible_cards")
        if visible is None or not isinstance(visible.content, VisibleCardData):
            return reference
        face_down_ids = {
            candidate.card_id
            for outcome in visible.content.outcomes
            if outcome.status == "detected"
            for candidate in outcome.candidates
            if candidate.side == "face_down"
        }
        if not face_down_ids:
            return reference

        replacement_revision_id: str | None = None
        repaired: StoredPipelineReference | None = None
        handler = self._handler("visual_identities")
        with self.reference_store.locked(recording_id, "visual_identities"):
            current = self.reference_store.read_locked(recording_id, "visual_identities")
            if current.state.draft_state != "completed":
                return current
            old_revision_id = current.state.selected_completed_revision_id
            if old_revision_id is None:
                return current
            repaired_items = list(current.draft.items)
            changed = False
            for index, item in enumerate(repaired_items):
                if item.item_id not in face_down_ids or item.item.get("status") != "unusable":
                    continue
                replacement = dict(item.item)
                replacement.update(
                    status="face_down",
                    candidates=[],
                    unusable_reason=None,
                    error=None,
                )
                handler.validate_item(replacement, current.draft.source_revision_id)
                repaired_items[index] = replace(
                    item,
                    review_state="face_down",
                    item=replacement,
                )
                changed = True
            if not changed:
                return current

            active_items = [item for item in repaired_items if item.review_state != "rejected"]
            content = handler.human_content(active_items)
            content_bytes = handler.canonical_content_bytes(content)
            content_sha256 = sha256_bytes(content_bytes)
            replacement_revision_id = self._revision_id(
                recording_id,
                "visual_identities",
                content_sha256,
                old_revision_id,
            )
            old_revision = self.revision_store.require(old_revision_id)
            coverage = dict(current.draft.coverage or {})
            raw_cards = coverage.get("cards")
            if isinstance(raw_cards, list):
                updated_cards: list[dict[str, Any]] = []
                for raw_card in raw_cards:
                    if not isinstance(raw_card, Mapping):
                        continue
                    card = dict(raw_card)
                    if card.get("card_id") in face_down_ids:
                        card["decision"] = "face_down"
                    updated_cards.append(card)
                coverage["cards"] = updated_cards
            coverage = {**coverage, "impact": list(current.draft.impact)}
            manifest = DataRevision(
                revision_id=replacement_revision_id,
                content_type="visual_identities",
                content_schema=handler.content_schema,
                recording_id=recording_id,
                source=old_revision.manifest.source,
                content_sha256=content_sha256,
                input_revision_ids=(old_revision_id,),
                origin="corrected",
                producer=HumanProducer(
                    review_id=f"reference-{recording_id}-visual_identities",
                    operator_id="face-down-migration",
                    base_revision_id=old_revision_id,
                ),
                coverage=coverage,
                created_at=_now(),
            )
            self.revision_store.publish(manifest, content_bytes)
            timestamp = _now()
            repaired = self.reference_store.write_locked(
                StoredPipelineReference(
                    state=replace(
                        current.state,
                        source_revision_id=replacement_revision_id,
                        selected_completed_revision_id=replacement_revision_id,
                        updated_at=timestamp,
                    ),
                    draft=replace(
                        current.draft,
                        source_revision_id=replacement_revision_id,
                        items=tuple(repaired_items),
                        coverage=coverage,
                        updated_at=timestamp,
                    ),
                )
            )

        assert repaired is not None and replacement_revision_id is not None
        for _ in range(5):
            selection = self.selection_store.get(recording_id, "visual_identities")
            if (
                selection is None
                or selection.selected_completed_reference_revision_id != old_revision_id
            ):
                break
            try:
                self.selection_store.update_pointers(
                    recording_id,
                    "visual_identities",
                    expected_revision=selection.revision,
                    selected_generated_revision_id=selection.selected_generated_revision_id,
                    selected_completed_reference_revision_id=replacement_revision_id,
                )
                break
            except PipelineSelectionConflict:
                continue
        return repaired

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
        self._source_revision_sources[revision_id] = manifest.source
        return revision

    def _source_for(
        self, recording_id: str, source_revision_id: str | None
    ) -> RecordingVideoSource:
        if source_revision_id is not None:
            cached_source = self._source_revision_sources.get(source_revision_id)
            if cached_source is not None:
                if cached_source.recording_id != recording_id:
                    raise PipelineReferenceInputError(
                        "source revision does not match this recording"
                    )
                return cached_source
            try:
                revision = self.revision_store.require(source_revision_id)
            except PipelineNotFound as error:
                raise PipelineReferenceInputError("source revision was not found") from error
            if revision.manifest.recording_id != recording_id or not isinstance(
                revision.manifest.source, RecordingVideoSource
            ):
                raise PipelineReferenceInputError("source revision does not match this recording")
            source = revision.manifest.source
            self._source_revision_sources[source_revision_id] = source
            return source
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
    "PipelineReferenceService",
]
