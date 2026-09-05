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


class PipelineReferenceError(RuntimeError):
    """The maintained-reference service could not complete an operation."""


class PipelineReferenceInputError(PipelineReferenceError, ValueError):
    """A maintained-reference request is invalid."""


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
                raise PipelineReferenceConflict(
                    "a maintained reference already exists", current
                )
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
            "operations",
            "operation",
            "item_id",
            "item",
        }
        if unknown:
            raise PipelineReferenceInputError(
                f"the reference edit request has unknown fields: {', '.join(sorted(unknown))}"
            )
        expected = _expected_revision(payload.get("expected_revision"))
        _identifier(payload.get("operator_id"), "operator_id")
        operations_value = payload.get("operations")
        if operations_value is None and "operation" in payload:
            operations_value = [
                {
                    key: value
                    for key, value in payload.items()
                    if key in {"operation", "item_id", "item"}
                }
            ]
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
            if current.state.draft_revision != expected:
                raise PipelineReferenceConflict(
                    "the maintained reference draft changed; reload the current revision",
                    current,
                )
            items = list(current.draft.items)
            for operation in operations:
                items = self._apply_operation(content_type, items, operation, current)
            self._validate_draft_items(
                recording_id,
                content_type,
                current.draft.source_revision_id,
                items,
            )
            timestamp = _now()
            draft = replace(
                current.draft,
                revision=current.draft.revision + 1,
                items=tuple(items),
                updated_at=timestamp,
            )
            state = replace(
                current.state,
                draft_revision=draft.revision,
                draft_state="draft",
                updated_at=timestamp,
            )
            return self.reference_store.write_locked(
                StoredPipelineReference(state=state, draft=draft)
            )

    def complete_reference(
        self,
        recording_id: str,
        content_type: str,
        payload: Mapping[str, Any],
    ) -> StoredPipelineReference:
        self._validate_content_type(content_type)
        if not isinstance(payload, Mapping):
            raise PipelineReferenceInputError("the reference completion request must be an object")
        unknown = set(payload) - {"expected_revision", "operator_id"}
        if unknown:
            raise PipelineReferenceInputError(
                "the reference completion request has unknown fields: "
                + ", ".join(sorted(unknown))
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
            if any(item.review_state == "pending" for item in current.draft.items):
                raise PipelineReferenceInputError(
                    "every suggested item needs an accept, reject, add, or correct decision"
                )
            source_revision = (
                None
                if current.draft.source_revision_id is None
                else self._require_source_revision(
                    recording_id, content_type, current.draft.source_revision_id
                )
            )
            source = self._source_for(recording_id, current.draft.source_revision_id)
            active_items = [
                item for item in current.draft.items if item.review_state != "rejected"
            ]
            content = self._human_content(content_type, active_items)
            content_bytes = self._canonical_content_bytes(content_type, content)
            content_sha256 = sha256_bytes(content_bytes)
            origin = "manual" if source_revision is None else "corrected"
            input_revision_ids = (
                ()
                if source_revision is None
                else (source_revision.manifest.revision_id,)
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
                coverage={
                    "kind": "maintained-reference",
                    "reviewed_item_ids": [item.item_id for item in current.draft.items],
                    "rejected_item_ids": [
                        item.item_id
                        for item in current.draft.items
                        if item.review_state == "rejected"
                    ],
                },
                created_at=_now(),
            )
            self.revision_store.publish(manifest, content_bytes)
            selected = self._select_completed(
                recording_id, content_type, revision_id
            )
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
        if operation.operation in {"accept", "reject"}:
            assert operation.item_id is not None
            index = self._find_item(items, operation.item_id)
            if index is None:
                raise PipelineReferenceInputError(f"item was not found: {operation.item_id}")
            return items[:index] + [
                replace(
                    items[index],
                    review_state=(
                        "accepted" if operation.operation == "accept" else "rejected"
                    ),
                )
            ] + items[index + 1 :]

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
        return items[:index] + [
            ReferenceDraftItem(
                item_id=item_id,
                base_item_id=operation.item_id,
                review_state="corrected",
                item=operation.item,
            )
        ] + items[index + 1 :]

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

    def _human_content(
        self, content_type: str, items: list[ReferenceDraftItem]
    ) -> dict[str, Any]:
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
            if (
                revision.manifest.recording_id != recording_id
                or not isinstance(revision.manifest.source, RecordingVideoSource)
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
    "PipelineReferenceError",
    "PipelineReferenceInputError",
    "PipelineReferenceService",
]
