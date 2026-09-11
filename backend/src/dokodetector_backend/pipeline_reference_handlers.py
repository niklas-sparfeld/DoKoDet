"""Content-specific edit and coverage rules for maintained references."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from doko_operations.pipeline_data import (
    EventData,
    RecordingVideoSource,
    canonical_event_data_bytes,
)
from doko_operations.pipeline_reference import (
    PIPELINE_REFERENCE_COVERAGE_SCHEMA_VERSION,
    PIPELINE_REFERENCE_IMPACT_SCHEMA_VERSION,
    PipelineReferenceContractError,
    PipelineReferenceOperation,
    ReferenceDraftItem,
)
from table_evidence_analyzer.pipeline_data import (
    PipelineDataError,
    VisibleCardData,
    VisualIdentityData,
    canonical_visible_card_data_bytes,
    canonical_visual_identity_data_bytes,
)

from dokodetector_backend.pipeline_reference_errors import (
    PipelineReferenceCoverageError,
    PipelineReferenceError,
    PipelineReferenceInputError,
    identifier,
)
from dokodetector_backend.pipeline_store import StoredPipelineRevision

_ITEM_FIELDS = {
    "events": "event_id",
    "visible_cards": "event_id",
    "visual_identities": "card_id",
}


class ReferenceContentHandler:
    """Own common item mechanics and extension points for one content type."""

    content_type: str
    content_key: str
    content_schema: str

    def __init__(
        self,
        *,
        source_for: Callable[[str, str | None], RecordingVideoSource],
        selected_revision: Callable[[str, str], StoredPipelineRevision | None],
    ) -> None:
        self._source_for = source_for
        self._selected_revision = selected_revision

    def item_id(self, item: Mapping[str, Any]) -> str:
        field = _ITEM_FIELDS[self.content_type]
        return identifier(item.get(field), f"item.{field}")

    def content_items(self, revision: StoredPipelineRevision) -> tuple[dict[str, Any], ...]:
        content = revision.content.to_mapping()
        return tuple(dict(item) for item in content[self.content_key])

    def validate_draft_items(
        self,
        recording_id: str,
        source_revision_id: str | None,
        items: list[ReferenceDraftItem],
    ) -> None:
        if len({item.item_id for item in items}) != len(items):
            raise PipelineReferenceInputError("reference item IDs must be unique")
        for item in items:
            if item.item_id != self.item_id(item.item):
                raise PipelineReferenceInputError(
                    f"reference item ID does not match its {self.content_type} content"
                )
            self.validate_item(item.item, source_revision_id, recording_id)

    def validate_item(
        self,
        item: Mapping[str, Any],
        source_revision_id: str | None,
        recording_id: str | None = None,
    ) -> None:
        try:
            source = self._source_for(recording_id, source_revision_id) if recording_id else None
            self._parse_item(item, source)
            if source is not None:
                self._validate_source_lineage(item, source)
        except (PipelineDataError, PipelineReferenceError, TypeError, ValueError) as error:
            if isinstance(error, PipelineReferenceInputError):
                raise
            raise PipelineReferenceInputError("reference item failed content validation") from error

    def apply_operation(
        self,
        items: list[ReferenceDraftItem],
        operation: PipelineReferenceOperation,
        source_revision_id: str | None,
    ) -> list[ReferenceDraftItem]:
        special = self._apply_special_operation(items, operation, source_revision_id)
        if special is not None:
            return special
        if operation.operation in {"accept", "reject", "decide"}:
            assert operation.item_id is not None
            index = self.find_item(items, operation.item_id)
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
                + [self._replace(items[index], review_state=state)]
                + items[index + 1 :]
            )

        assert operation.item is not None
        item_id = self.item_id(operation.item)
        self.validate_item(operation.item, source_revision_id)
        if operation.operation == "add":
            if self.find_item(items, item_id) is not None:
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
        index = self.find_item(items, operation.item_id)
        if index is None:
            raise PipelineReferenceInputError(f"item was not found: {operation.item_id}")
        if item_id != operation.item_id and self.find_item(items, item_id) is not None:
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

    def rebase_items(
        self,
        recording_id: str,
        current: Any,
        source_revision_id: str,
        require_source_revision: Callable[[str, str, str], StoredPipelineRevision],
    ) -> list[ReferenceDraftItem]:
        source_revision = require_source_revision(
            recording_id, self.content_type, source_revision_id
        )
        new_items = self.content_items(source_revision)
        previous_items = list(current.draft.items)
        rebased: list[ReferenceDraftItem] = []
        for raw_item in new_items:
            previous = next(
                (item for item in previous_items if self.rebase_match(item.item, raw_item, item)),
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
                    item_id=self.item_id(raw_item),
                    base_item_id=base_item_id,
                    review_state=state,
                    item=dict(raw_item),
                )
            )
        return rebased

    def rebase_match(
        self,
        previous: Mapping[str, Any],
        current: Mapping[str, Any],
        previous_draft: ReferenceDraftItem,
    ) -> bool:
        del previous_draft
        return self.item_id(previous) == self.item_id(current)

    def human_content(self, items: list[ReferenceDraftItem]) -> dict[str, Any]:
        return {
            "schema_version": self.content_schema,
            self.content_key: [self.human_item(item.item) for item in items],
        }

    def human_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        value = json.loads(json.dumps(item))
        return value

    def canonical_content_bytes(self, content: Mapping[str, Any]) -> bytes:
        try:
            return self._canonical_content_bytes(content)
        except (PipelineDataError, PipelineReferenceContractError, TypeError, ValueError) as error:
            raise PipelineReferenceInputError(
                "the completed reference content is invalid"
            ) from error

    def correction_impact(
        self,
        recording_id: str,
        previous: ReferenceDraftItem,
        corrected: ReferenceDraftItem,
    ) -> tuple[dict[str, Any], ...]:
        del recording_id, previous, corrected
        return ()

    def validate_coverage(
        self,
        raw_coverage: Mapping[str, Any],
        items: tuple[ReferenceDraftItem, ...],
        source: RecordingVideoSource,
        recording_id: str,
    ) -> dict[str, Any]:
        del raw_coverage, items, source, recording_id
        raise NotImplementedError

    @staticmethod
    def find_item(items: list[ReferenceDraftItem], item_id: str) -> int | None:
        return next((index for index, item in enumerate(items) if item.item_id == item_id), None)

    @staticmethod
    def _replace(draft_item: ReferenceDraftItem, **changes: Any) -> ReferenceDraftItem:
        from dataclasses import replace

        return replace(draft_item, **changes)

    def _apply_special_operation(
        self,
        items: list[ReferenceDraftItem],
        operation: PipelineReferenceOperation,
        source_revision_id: str | None,
    ) -> list[ReferenceDraftItem] | None:
        del items, operation, source_revision_id
        return None

    def _parse_item(self, item: Mapping[str, Any], source: RecordingVideoSource | None) -> object:
        del source
        raise NotImplementedError

    def _validate_source_lineage(
        self, item: Mapping[str, Any], source: RecordingVideoSource
    ) -> None:
        frame = item.get("frame_identity")
        if (
            not isinstance(frame, Mapping)
            or frame.get("source_video_sha256") != source.video_sha256
        ):
            raise PipelineReferenceInputError(
                "reference item does not belong to the recording video"
            )

    def _canonical_content_bytes(self, content: Mapping[str, Any]) -> bytes:
        raise NotImplementedError

    def _impact_entry(
        self,
        source_item_id: str,
        downstream_content_type: str,
        affected_item_ids: list[str],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_REFERENCE_IMPACT_SCHEMA_VERSION,
            "source_content_type": self.content_type,
            "source_item_id": source_item_id,
            "downstream_content_type": downstream_content_type,
            "affected_item_ids": sorted(set(affected_item_ids)),
            "reason": reason,
            "re_review_required": True,
        }

    @staticmethod
    def _same_json(left: Any, right: Any) -> bool:
        return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
            right, sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _coverage_time(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PipelineReferenceInputError(f"{field} must be a non-negative integer")
        return value

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
            if status == "face_down":
                return "face-down card needs an explicit face_down decision"
            if status == "unusable":
                return "unusable card needs an explicit unusable or identity_unusable decision"
            if status == "failed":
                return "failed card needs an explicit source_problem decision"
            return "card needs an accepted identity or a correct decision"
        return "event needs an explicit review decision"


class EventReferenceHandler(ReferenceContentHandler):
    content_type = "events"
    content_key = "events"
    content_schema = "event-data/v1"

    def rebase_match(
        self,
        previous: Mapping[str, Any],
        current: Mapping[str, Any],
        previous_draft: ReferenceDraftItem,
    ) -> bool:
        lineage = {previous_draft.item_id, previous_draft.base_item_id}
        return (
            current.get("event_id") in lineage
            and previous.get("event_type") == current.get("event_type")
            and previous.get("start_us") == current.get("start_us")
            and previous.get("end_us") == current.get("end_us")
        )

    def _parse_item(self, item: Mapping[str, Any], source: RecordingVideoSource | None) -> object:
        return EventData.from_mapping(
            {"schema_version": "event-data/v1", "events": [item]},
            duration_us=source.duration_us if source else 2**63 - 1,
        )

    def _validate_source_lineage(
        self, item: Mapping[str, Any], source: RecordingVideoSource
    ) -> None:
        del item, source

    def human_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        value = super().human_item(item)
        value.pop("model_scores", None)
        return value

    def _canonical_content_bytes(self, content: Mapping[str, Any]) -> bytes:
        return canonical_event_data_bytes(EventData.from_mapping(content))

    def validate_coverage(
        self,
        raw_coverage: Any,
        items: tuple[ReferenceDraftItem, ...],
        source: RecordingVideoSource,
        recording_id: str,
    ) -> dict[str, Any]:
        del recording_id
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
            if not isinstance(raw_interval, Mapping) or set(raw_interval) != {"start_us", "end_us"}:
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

    def correction_impact(
        self,
        recording_id: str,
        previous: ReferenceDraftItem,
        corrected: ReferenceDraftItem,
    ) -> tuple[dict[str, Any], ...]:
        event_ids = {previous.item_id, corrected.item_id}
        visible = self._selected_revision(recording_id, "visible_cards")
        if visible is None:
            return ()
        visible_items = self._content_items_for("visible_cards", visible)
        impact: list[dict[str, Any]] = []
        affected_visible = [
            item["event_id"] for item in visible_items if item.get("event_id") in event_ids
        ]
        if affected_visible:
            impact.append(
                self._impact_entry(
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
                for item in self._content_items_for("visual_identities", identities)
                if item.get("card_id") in card_ids
            ]
            if affected_identity:
                impact.append(
                    self._impact_entry(
                        previous.item_id,
                        "visual_identities",
                        affected_identity,
                        "event evidence changed; review its downstream identity crop again",
                    )
                )
        return tuple(impact)

    def _content_items_for(
        self, content_type: str, revision: StoredPipelineRevision
    ) -> tuple[dict[str, Any], ...]:
        key = "events" if content_type == "events" else "outcomes"
        return tuple(dict(item) for item in revision.content.to_mapping()[key])


class VisibleCardReferenceHandler(ReferenceContentHandler):
    content_type = "visible_cards"
    content_key = "outcomes"
    content_schema = "visible-card-data/v1"

    def _parse_item(self, item: Mapping[str, Any], source: RecordingVideoSource | None) -> object:
        del source
        return VisibleCardData.from_mapping(
            {"schema_version": "visible-card-data/v1", "outcomes": [item]}
        )

    def human_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        value = super().human_item(item)
        for candidate in value.get("candidates", []):
            candidate.pop("model_scores", None)
        return value

    def _canonical_content_bytes(self, content: Mapping[str, Any]) -> bytes:
        return canonical_visible_card_data_bytes(VisibleCardData.from_mapping(content))

    def _apply_special_operation(
        self,
        items: list[ReferenceDraftItem],
        operation: PipelineReferenceOperation,
        source_revision_id: str | None,
    ) -> list[ReferenceDraftItem] | None:
        if operation.operation not in {
            "set_frame_review",
            "accept_frame_suggestions",
            "set_frame_unreviewed",
            "restore_frame_suggestions",
            "set_frame_empty",
            "set_frame_unusable",
        }:
            return None
        assert operation.item_id is not None
        index = self.find_item(items, operation.item_id)
        if index is None:
            raise PipelineReferenceInputError(f"item was not found: {operation.item_id}")
        existing = items[index]
        if operation.operation == "restore_frame_suggestions":
            assert operation.item is not None
            self.validate_item(operation.item, source_revision_id)
            if operation.item.get("frame_identity") != existing.item.get("frame_identity"):
                raise PipelineReferenceInputError(
                    "restore_frame_suggestions cannot change the resolved frame identity"
                )
            if self.item_id(operation.item) != existing.item_id:
                raise PipelineReferenceInputError(
                    "restore_frame_suggestions cannot change the source item"
                )
            return (
                items[:index]
                + [
                    self._replace(
                        existing,
                        base_item_id=None,
                        review_state="pending",
                        item=dict(operation.item),
                    )
                ]
                + items[index + 1 :]
            )
        if operation.operation == "set_frame_review":
            assert operation.item is not None
            self.validate_item(operation.item, source_revision_id)
            if operation.item.get("frame_identity") != existing.item.get("frame_identity"):
                raise PipelineReferenceInputError(
                    "set_frame_review cannot change the resolved frame identity"
                )
            updated = ReferenceDraftItem(
                item_id=self.item_id(operation.item),
                base_item_id=existing.item_id,
                review_state="corrected",
                item=dict(operation.item),
            )
            if updated.item_id != existing.item_id:
                raise PipelineReferenceInputError("set_frame_review cannot change the source item")
            return items[:index] + [updated] + items[index + 1 :]
        if operation.operation == "accept_frame_suggestions":
            if existing.item.get("status") == "empty":
                state = "empty"
            elif existing.item.get("status") == "failed":
                state = "unusable"
            else:
                state = "accepted"
            return (
                items[:index] + [self._replace(existing, review_state=state)] + items[index + 1 :]
            )
        if operation.operation == "set_frame_unreviewed":
            if existing.item.get("status") != "detected":
                raise PipelineReferenceInputError("set_frame_unreviewed requires a detected frame")
            return (
                items[:index]
                + [self._replace(existing, base_item_id=None, review_state="pending")]
                + items[index + 1 :]
            )
        replacement = dict(existing.item)
        replacement["candidates"] = []
        if operation.operation == "set_frame_empty":
            replacement.update(status="empty", error=None)
            state = "empty"
        else:
            replacement.update(status="failed", error="Reviewed unusable frame.")
            state = "unusable"
        self.validate_item(replacement, source_revision_id)
        return (
            items[:index]
            + [self._replace(existing, review_state=state, item=replacement)]
            + items[index + 1 :]
        )

    def validate_coverage(
        self,
        raw_coverage: Mapping[str, Any],
        items: tuple[ReferenceDraftItem, ...],
        source: RecordingVideoSource,
        recording_id: str,
    ) -> dict[str, Any]:
        del source, recording_id
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
            entry = by_key.get(self._item_frame_key(item))
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

    def correction_impact(
        self,
        recording_id: str,
        previous: ReferenceDraftItem,
        corrected: ReferenceDraftItem,
    ) -> tuple[dict[str, Any], ...]:
        card_ids = {
            candidate.get("card_id")
            for item in (previous.item, corrected.item)
            for candidate in item.get("candidates", [])
            if isinstance(candidate, Mapping) and isinstance(candidate.get("card_id"), str)
        }
        identities = self._selected_revision(recording_id, "visual_identities")
        if identities is None or not card_ids:
            return ()
        affected_identity = [
            item["card_id"]
            for item in identities.content.to_mapping()["outcomes"]
            if item.get("card_id") in card_ids
        ]
        if not affected_identity:
            return ()
        return (
            self._impact_entry(
                previous.item_id,
                "visual_identities",
                affected_identity,
                "visible-card evidence changed; review its downstream identity again",
            ),
        )

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
                entry["item_id"] = identifier(
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
            return state == "accepted"
        if status == "empty":
            return state == "empty"
        if status == "failed":
            return state in {"unusable", "source_problem"}
        return False


class VisualIdentityReferenceHandler(ReferenceContentHandler):
    content_type = "visual_identities"
    content_key = "outcomes"
    content_schema = "visual-identity-data/v1"

    def _parse_item(self, item: Mapping[str, Any], source: RecordingVideoSource | None) -> object:
        del source
        return VisualIdentityData.from_mapping(
            {"schema_version": "visual-identity-data/v1", "outcomes": [item]}
        )

    def human_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        value = super().human_item(item)
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

    def _canonical_content_bytes(self, content: Mapping[str, Any]) -> bytes:
        return canonical_visual_identity_data_bytes(VisualIdentityData.from_mapping(content))

    def _apply_special_operation(
        self,
        items: list[ReferenceDraftItem],
        operation: PipelineReferenceOperation,
        source_revision_id: str | None,
    ) -> list[ReferenceDraftItem] | None:
        if operation.operation not in {
            "accept_identity_suggestion",
            "set_identity_unreviewed",
            "set_identity_face_down",
            "select_identity",
            "set_identity_unusable",
            "report_identity_source_problem",
        }:
            return None
        assert operation.item_id is not None
        index = self.find_item(items, operation.item_id)
        if index is None:
            raise PipelineReferenceInputError(f"item was not found: {operation.item_id}")
        existing = items[index]
        existing_item = dict(existing.item)
        if operation.operation == "accept_identity_suggestion":
            candidates = existing_item.get("candidates")
            if (
                existing_item.get("status") != "classified"
                or not isinstance(candidates, list)
                or not candidates
            ):
                raise PipelineReferenceInputError(
                    "the identity suggestion is unavailable for this card"
                )
            return (
                items[:index]
                + [self._replace(existing, review_state=self._accepted_identity_state(existing))]
                + items[index + 1 :]
            )
        if operation.operation == "set_identity_unreviewed":
            if existing_item.get("status") not in {
                "classified",
                "face_down",
                "unusable",
                "failed",
            }:
                raise PipelineReferenceInputError(
                    "set_identity_unreviewed requires a classified, face-down, unusable, "
                    "or failed identity"
                )
            return (
                items[:index]
                + [self._replace(existing, base_item_id=None, review_state="pending")]
                + items[index + 1 :]
            )
        if operation.operation == "set_identity_face_down":
            replacement = dict(existing_item)
            replacement.update(
                status="face_down",
                candidates=[],
                unusable_reason=None,
                error=None,
            )
            self.validate_item(replacement, source_revision_id)
            return (
                items[:index]
                + [self._replace(existing, review_state="face_down", item=replacement)]
                + items[index + 1 :]
            )
        if operation.operation == "select_identity":
            assert operation.identity is not None
            replacement = dict(existing_item)
            replacement.update(
                status="classified",
                candidates=[
                    {
                        "identity": operation.identity,
                        "score": None,
                        "score_meaning": None,
                        "producer_id": "human-reference.v1",
                    }
                ],
                unusable_reason=None,
                error=None,
            )
            self.validate_item(replacement, source_revision_id)
            return (
                items[:index]
                + [
                    self._replace(
                        existing,
                        review_state=self._accepted_identity_state(existing),
                        item=replacement,
                    )
                ]
                + items[index + 1 :]
            )
        replacement = dict(existing_item)
        replacement["candidates"] = []
        if operation.operation == "set_identity_unusable":
            replacement.update(
                status="unusable", unusable_reason="Reviewed identity unusable.", error=None
            )
            state = "identity_unusable"
        else:
            replacement.update(
                status="failed", unusable_reason=None, error="Reviewed source problem."
            )
            state = "source_problem"
        self.validate_item(replacement, source_revision_id)
        return (
            items[:index]
            + [self._replace(existing, review_state=state, item=replacement)]
            + items[index + 1 :]
        )

    def validate_coverage(
        self,
        raw_coverage: Mapping[str, Any],
        items: tuple[ReferenceDraftItem, ...],
        source: RecordingVideoSource,
        recording_id: str,
    ) -> dict[str, Any]:
        del source
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
            card_id = identifier(raw_card["card_id"], f"coverage.cards[{index}].card_id")
            decision = raw_card["decision"]
            if decision not in {"identity", "face_down", "unusable", "source_problem"}:
                raise PipelineReferenceInputError(
                    f"coverage.cards[{index}].decision must be identity, face_down, "
                    "unusable, or source_problem"
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
            expected_decision = {
                "classified": "identity",
                "face_down": "face_down",
                "unusable": "unusable",
                "failed": "source_problem",
            }.get(item.item.get("status"))
            if expected_decision != entry["decision"] or not self._identity_coverage_state(
                item.item, item.review_state
            ):
                details.append(
                    {
                        "field": f"items.{item.item_id}",
                        "message": self._coverage_missing_message("visual_identities", item),
                    }
                )
        for card_id in sorted(expected_ids - {item.item_id for item in items}):
            if by_id[card_id]["decision"] not in {"unusable", "source_problem"}:
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
            for item in visible.content.to_mapping()["outcomes"]
            if item.get("status") == "detected"
            for candidate in item.get("candidates", [])
            if isinstance(candidate, Mapping) and isinstance(candidate.get("card_id"), str)
        }
        return {str(card_id) for card_id in card_ids} | {item.item_id for item in items}

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
        if status == "face_down":
            return state in {"face_down", "accepted", "added", "corrected"}
        if status == "unusable":
            return state in {"unusable", "identity_unusable"}
        if status == "failed":
            return state == "source_problem"
        return False

    @staticmethod
    def _accepted_identity_state(item: ReferenceDraftItem) -> str:
        if item.base_item_id is not None:
            return "corrected"
        if item.review_state == "added":
            return "added"
        return "accepted"


def build_reference_handlers(
    *,
    source_for: Callable[[str, str | None], RecordingVideoSource],
    selected_revision: Callable[[str, str], StoredPipelineRevision | None],
) -> dict[str, ReferenceContentHandler]:
    dependencies = {"source_for": source_for, "selected_revision": selected_revision}
    return {
        "events": EventReferenceHandler(**dependencies),
        "visible_cards": VisibleCardReferenceHandler(**dependencies),
        "visual_identities": VisualIdentityReferenceHandler(**dependencies),
    }


__all__ = [
    "ReferenceContentHandler",
    "build_reference_handlers",
]
